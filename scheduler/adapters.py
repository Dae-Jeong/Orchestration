"""Both adapters launch the same worker exactly once per persisted intent."""
import json
from pathlib import Path
import shlex
import subprocess
import sys
import threading

from .worker import atomic_json


class NotLaunched(RuntimeError):
    """Local OS rejected process creation before an external launch was possible."""


# Durable Orca identity of one terminal session. runtimeId comes from the response
# `_meta`; the rest from `result.terminal`. Volatile fields (title, preview,
# lastOutputAt, connected, ...) are deliberately excluded: they change with output.
TERMINAL_RECORD = 1
IDENTITY_FIELDS = ("runtimeId", "handle", "ptyId", "incarnationId", "worktreeId")
STALE_HANDLE = "terminal_handle_stale"


def terminal_identity(body):
    """Exact identity from an Orca create/show response, or None when any field is missing."""
    if not isinstance(body, dict):
        return None
    result, meta = body.get("result"), body.get("_meta")
    terminal = result.get("terminal") if isinstance(result, dict) else None
    if not isinstance(terminal, dict) or not isinstance(meta, dict):
        return None
    identity = {k: terminal.get(k) for k in IDENTITY_FIELDS[1:]}
    identity["runtimeId"] = meta.get("runtimeId")
    if not all(isinstance(v, str) and v for v in identity.values()):
        return None
    return identity


def orca_ready(command):
    try:
        result = subprocess.run([command, "status", "--json"], capture_output=True, text=True, timeout=10)
        body = json.loads(result.stdout)
        return result.returncode == 0 and body.get("ok") is True and body["result"]["runtime"]["reachable"] is True
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        return False


def choose(preference, orca):
    if preference == "auto":
        return "orca" if orca_ready(orca) else "local"
    return preference


def launch(adapter, spec_path, project, orca):
    command = [sys.executable, str(Path(__file__).with_name("worker.py")), str(spec_path)]
    if adapter == "local":
        try:
            process = subprocess.Popen(command, cwd=project["repo"], stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       start_new_session=True)
        except OSError as exc:
            raise NotLaunched(str(exc)) from exc
        # Reap while this scheduler lives; the worker remains detached on shutdown.
        threading.Thread(target=process.wait, daemon=True).start()
        return str(process.pid)
    if adapter != "orca":
        raise ValueError("unknown adapter")
    result = subprocess.run([orca, "terminal", "create", "--worktree", "path:" + project["repo"],
                             "--title", "scheduler-" + spec_path.parent.name,
                             "--command", shlex.join(command), "--json"],
                            capture_output=True, text=True, timeout=30)
    body = json.loads(result.stdout)
    if result.returncode or body.get("ok") is not True:
        raise RuntimeError("Orca launch not confirmed; reconcile the persisted attempt")
    terminal = body.get("result", {}).get("terminal", {})
    handle = terminal.get("handle") or body.get("result", {}).get("handle")
    if not handle:
        raise RuntimeError("Orca response lacks a terminal handle; do not relaunch")
    # Persist the created session's exact identity next to the attempt so a later
    # cleanup can prove it closes the same session and not a reused handle. A response
    # without the full identity still launched: cleanup for it is withheld, not guessed.
    atomic_json(spec_path.parent / "terminal.json",
                {"version": TERMINAL_RECORD, "handle": handle, "identity": terminal_identity(body)})
    return handle


def _orca_json(orca, args, timeout):
    """(body, None) for a parsed Orca response, else (None, reason). Never raises for transport."""
    try:
        result = subprocess.run([orca, "terminal", *args, "--json"], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, "orca %s did not answer: %s" % (args[0], exc)
    try:
        body = json.loads(result.stdout)
    except ValueError:
        return None, "orca %s returned non-JSON (exit %s)" % (args[0], result.returncode)
    if not isinstance(body, dict):
        return None, "orca %s returned an unexpected payload" % args[0]
    return body, None


def _error_code(body):
    error = body.get("error")
    return error.get("code") if isinstance(error, dict) else None


def close(adapter, handle, folder, orca):
    """Close exactly the owned worker terminal after re-verifying its identity.

    Returns {"outcome", "detail", ...}. Outcomes:
      closed / already_closed / not_applicable - final, the owned session is proven gone or never existed
      withheld    - final, ownership cannot be proven (missing/legacy identity, stale or reused handle,
                    drift); nothing was closed and an operator must inspect
      unconfirmed - transport failure or an unconfirmed close; retry re-verifies identity first
    Local workers are detached and their exit receipt already proves termination, so this
    never signals a local process (a PID may have been reused).
    """
    if adapter == "local":
        return {"outcome": "not_applicable", "detail": "local worker exited per receipt; no signal sent"}
    if adapter != "orca":
        return {"outcome": "withheld", "detail": "unknown adapter %r" % adapter}
    record = Path(folder) / "terminal.json"
    try:
        stored = json.loads(record.read_text())
    except FileNotFoundError:
        return {"outcome": "withheld", "detail": "no terminal identity recorded for this attempt (launched before identity capture)"}
    except ValueError:
        return {"outcome": "withheld", "detail": "terminal identity record is unreadable"}
    if not isinstance(stored, dict):
        stored = {}
    expected = stored.get("identity")
    if (stored.get("version") != TERMINAL_RECORD or not isinstance(expected, dict)
            or set(expected) != set(IDENTITY_FIELDS) or not handle
            or stored.get("handle") != handle or expected.get("handle") != handle):
        return {"outcome": "withheld", "detail": "stored terminal identity is incomplete or does not match the attempt handle"}
    body, reason = _orca_json(orca, ["show", "--terminal", handle], 15)
    if body is None:
        return {"outcome": "unconfirmed", "detail": "ownership unverified: " + reason}
    if body.get("ok") is not True:
        code = _error_code(body)
        if code == STALE_HANDLE:
            # The runtime no longer knows this handle (closed, or re-issued after a restart).
            # That is not proof the session ended, so nothing is closed or declared closed.
            return {"outcome": "withheld", "detail": "terminal handle is stale; session state cannot be verified", "error": code}
        return {"outcome": "unconfirmed", "detail": "terminal show failed", "error": code}
    live = terminal_identity(body)
    if live != expected:
        drift = sorted(k for k in IDENTITY_FIELDS if (live or {}).get(k) != expected.get(k))
        return {"outcome": "withheld", "detail": "live terminal identity differs; refusing to close another session",
                "mismatch": drift}
    terminal = body["result"]["terminal"]
    if terminal.get("exitCause"):
        # The same session already ended; closing it again is unnecessary.
        return {"outcome": "already_closed", "detail": "owned terminal already exited",
                "exitCause": terminal.get("exitCause"), "identity": live}
    body, reason = _orca_json(orca, ["close", "--terminal", handle], 30)
    if body is None:
        return {"outcome": "unconfirmed", "detail": "close result unknown: " + reason, "identity": live}
    if body.get("ok") is not True:
        return {"outcome": "unconfirmed", "detail": "terminal close reported failure", "error": _error_code(body),
                "identity": live}
    # Orca's outer ok only means the request ran; the PTY stop is reported in result.close.
    closed = body.get("result", {}).get("close") if isinstance(body.get("result"), dict) else None
    if (not isinstance(closed, dict) or closed.get("handle") != handle or closed.get("ptyKilled") is not True
            or "ptyStopVerdict" in closed):  # Orca adds a verdict only when the stop is unverifiable/live
        return {"outcome": "unconfirmed", "detail": "close did not confirm the owned PTY was killed",
                "close": closed, "identity": live}
    return {"outcome": "closed", "detail": "owned terminal closed", "close": closed, "identity": live}
