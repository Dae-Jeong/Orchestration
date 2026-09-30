"""Read-only terminal view of one scheduler ledger (`watch`).

Each frame reuses the same `query.Query.status()` projection as `status`, plus
the attempt receipts the worker supervisor already writes, over a SQLite
mode=ro connection: no schema creation, migration or journal-mode change. A
missing, foreign or older/incomplete ledger is reported, never created or
upgraded. The viewer never ticks, launches, claims, ACKs, closes terminals or
edits Tasks. Ctrl-C ends only the viewer.

The session overview adds WAITING / PROBLEMS / PROGRESS / SESSIONS from four phase-1
sources: this ledger, its ref_events + wake audit rows, central Task frontmatter in the
configured task dirs, and (only when a vault root is configured) the harness PUBLIC
`work status` JSON. Each source fails on its own and unknown facts are shown as
unavailable/unsupported, never inferred. Phase 2 adds read-only Orca verbs; a session is
linked to an Orca terminal only by recorded evidence (see `orca_section`).
"""
from datetime import datetime
import glob
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

from .launcher import PROFILES
from .model import Catalog, Invalid
from .query import open_readonly
from .refs import items as ref_items, sha as ref_sha
from .store import CLEANUP_DONE, CLEANUP_FINAL, EXECUTING_STATES, LEDGER, SLOT_STATES, Attempt

HARNESS_COMMAND = ("uv", "run", "--quiet", "python", "-m", "harness")  # config `harness_command` overrides
HARNESS_TIMEOUT = 30
REF_SETTLED = ("acked", "dismissed")
WAITING_STATUSES = ("blocked", "review")
MAX_ATTEMPTS = 8
MAX_SESSIONS = 8  # --sessions N|all; --json always keeps the full list
# `work status` selects work_sessions without ORDER BY: observed first-bind (rowid) order, a later bind
# of a new session appended last, a rebind not moved. Undocumented and not a timestamp.
SESSION_ORDER = "newest bind first = reverse harness output order (observed first-bind order; no timestamp)"
MIN_WIDTH = 40
HOME, CLEAR_SCREEN, CLEAR_LINE, CLEAR_BELOW = "\x1b[H", "\x1b[2J", "\x1b[K", "\x1b[J"
OPEN_ASSIGNMENTS = ("pending", "held")


class Missing(RuntimeError):
    """A configured path does not exist; nothing is created on its behalf."""


def _json(path):
    """(value, None) | (None, None) when absent | (None, reason) when unreadable."""
    try:
        return json.loads(Path(path).read_text()), None
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as exc:
        return None, "unreadable %s: %s" % (Path(path).name, exc)


def _task_state(catalog, key, path):
    if not path:
        return "task path unknown for this attempt"
    try:
        task = catalog.read(only_path=path).get(key)
    except FileNotFoundError:
        return "task file missing: " + str(path)
    except Exception as exc:  # malformed frontmatter, invalid fields, unreadable file
        return "task malformed: %s" % exc
    if task is None:
        return "task not found in configured scope: " + str(path)
    return "status=%s%s" % (task.status, " evidence=%d" % len(task.evidence) if task.evidence else "")


def collect(config, state):
    """One read-only observation of the ledger, attempt receipts and referenced Tasks."""
    config, root = Path(config), Path(state)
    if not config.is_file():
        raise Missing("config not found: %s" % config)
    if not (root / LEDGER).is_file():
        raise Missing("state ledger not found: %s (viewer creates nothing; check --state)" % (root / LEDGER))
    query = open_readonly(config, root)
    try:
        status = query.status()
        launches = {}
        for view in status["assignments"]:
            for launch in view["launches"]:
                launches[launch["attempt"]] = (view, launch)
        attempts = []
        for row in status["attempts"]:
            folder = query.store.root / "attempts" / row["id"]
            files = {name: _json(folder / (name + ".json")) for name in ("spec", "started", "exited", "terminal")}
            view, launch = launches.get(row["id"], (None, None))
            spec = files["spec"][0] or {}
            path = spec.get("task_path") or (view or {}).get("contract", {}).get("task_path")
            attempts.append(dict(
                row=row, folder=str(folder), files=files, assignment=view, launch=launch,
                task_state=_task_state(query.catalog, row["task"], path),
                blocker=query.acceptance_blocker(Attempt(**row)) if row["state"] == "awaiting_acceptance" else None,
                outputs={n: _size(folder / n) for n in ("stdout.txt", "stderr.txt")}))
        try:
            refs = ref_rows(query.db)
            refs_error = "none: ledger has no ref_events table" if refs is None else None
        except (sqlite3.Error, ValueError) as exc:
            refs, refs_error = None, "unavailable: %s" % exc
        return dict(state=str(query.store.root), status=status, attempts=attempts, refs=refs, refs_error=refs_error)
    finally:
        query.close()


def _size(path):
    try:
        return Path(path).stat().st_size
    except OSError:
        return None


def executor_label(command):
    """(executable name and model, actual path and policy) for a preset launcher or explicit command."""
    if not isinstance(command, list) or not command:
        return "unknown", "no spec.json command"
    def flag(name):
        return command[command.index(name) + 1] if name in command[:-1] else None
    model = flag("--model")
    if any(str(part).endswith("launcher.py") for part in command):
        executor = flag("--executor") or "?"
        path = flag("--executable") or PROFILES.get(executor, ["?"])[0]
        name, policy = Path(path).name, "preset " + executor
    else:
        name, path, policy = Path(command[0]).name, command[0], "configured command"
        if name.startswith("python") and len(command) > 1:
            name += " " + Path(command[1]).name
    return name + (" model=" + model if model else ""), "%s (%s)" % (path, policy)


def when(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return datetime.fromtimestamp(value).strftime("%m-%d %H:%M:%S")


def span(seconds):
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    return ("%dh" % hours if hours else "") + "%dm%02ds" % divmod(rest, 60)


def middle(value, room):
    """Shorten the middle so both the identifying head and the tail stay visible."""
    if room <= 0 or len(value) <= room:
        return value
    if room < 5:
        return value[:room]
    head = (room - 1) // 2
    return value[:head] + "~" + value[len(value) - (room - 1 - head):]


class Frame:
    def __init__(self, width):
        self.width, self.lines = width, []

    def line(self, text=""):
        self.lines.append(middle(text, self.width) if self.width else text)

    def field(self, label, value, indent=4):
        value = str(value)
        prefix = " " * indent + "%-11s " % label
        room = self.width - len(prefix) if self.width else 0
        self.lines.append(prefix + (middle(value, max(room, 8)) if self.width else value))

    def text(self):
        return "\n".join(self.lines) + "\n"


def header(frame, now, state=None):
    stamp = datetime.fromtimestamp(now).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    frame.line("scheduler watch (read-only; Ctrl-C stops the viewer only)")
    frame.field("time", stamp, indent=0)
    if state:
        frame.field("state", state, indent=0)


def _messages(status, attempt):
    rows = [m for m in status["messages"] if m["attempt"] == attempt]
    open_required = [m for m in rows if m["required"] and m["state"] not in ("acked", "dismissed")]
    counts = {}
    for m in rows:
        counts[m["state"]] = counts.get(m["state"], 0) + 1
    summary = " ".join("%s=%d" % kv for kv in sorted(counts.items())) or "none"
    pending = ", ".join("%s(%s%s)" % (m["id"], m["state"], ": " + m["reason"] if m.get("reason") else "")
                        for m in open_required)
    return summary, pending


def _execution(item, now):
    """Separate (label, value) facts; every time names its ledger/receipt source."""
    row, files = item["row"], item["files"]
    started, started_err = files["started"]
    exited, exited_err = files["exited"]
    start_at = started.get("at") if started and when(started.get("at")) else None
    facts = [("ledger", row["state"]), ("launched", "%s (ledger)" % (when(row["created"]) or "?"))]
    if started_err or started:
        facts.append(("started", started_err or ("%s (receipt)" % when(start_at) if start_at else "receipt without time")))
    else:
        facts.append(("started", "no receipt"))
    if exited_err or exited:
        end_at = exited.get("at") if exited and when(exited.get("at")) else None
        facts.append(("exited", exited_err or "code %s %s" % (
            exited.get("code"), "at %s (receipt)" % when(end_at) if end_at else "(receipt without time)")))
        if start_at and end_at:
            facts.append(("ran", span(end_at - start_at) + " (receipts)"))
    else:
        facts.append(("exited", "no receipt"))
        if start_at and row["state"] in EXECUTING_STATES:
            facts.append(("elapsed", span(now - start_at) + " since started receipt"))
    return facts


def _acceptance(item, status):
    row = item["row"]
    if row["state"] == "accepted":
        event = next((e for e in status["events"] if e["attempt"] == row["id"] and e["kind"] == "accepted"), None)
        return "accepted" + (" at %s (ledger event)" % when(event["created"]) if event else "")
    if row["state"] == "awaiting_acceptance":
        return "awaiting Task acceptance; blocker: %s" % (item["blocker"] or "none (next tick may accept)")
    if row["state"] in EXECUTING_STATES:
        return "not accepted; worker has not exited"
    return "not accepted; attempt " + row["state"]


def _cleanup(item, status):
    row = item["row"]
    record = next((c for c in status["cleanups"] if c["attempt"] == row["id"]), None)
    if record:
        detail = record["detail"].get("detail", "") if isinstance(record["detail"], dict) else ""
        final = "done" if record["state"] in CLEANUP_DONE else "operator" if record["state"] in CLEANUP_FINAL else "retrying"
        return "%s [%s] tries=%d at %s%s" % (record["state"], final, record["tries"], when(record["updated"]),
                                              "; " + detail if detail else "")
    if row["state"] != "accepted":
        return "not eligible (attempt not accepted; terminal stays open)"
    if not item["files"]["exited"][0]:
        return "waiting for exit receipt before closing"
    return "pending (next tick closes the owned terminal)"


def _terminal(item):
    row = item["row"]
    if row["adapter"] == "local":
        return "local pid %s" % (row["handle"] or "?")
    record, error = item["files"]["terminal"]
    identity = "identity recorded" if record and record.get("identity") else error or "no identity record"
    return "%s %s (%s)" % (row["adapter"], row["handle"] or "no handle", identity)


def _attempt_fields(item, status, now):
    row, view, launch = item["row"], item["assignment"], item["launch"]
    fields = [("attempt", row["id"]), ("task", item["task_state"])]
    if view:
        fields += [("assignment", view["id"]),
                   ("role", "%s origin=%s state=%s" % (view["contract"].get("role"), view["origin"], view["state"]))]
    else:
        fields.append(("assignment", "none recorded for this attempt"))
    spec, spec_err = item["files"]["spec"]
    name, path = executor_label((spec or {}).get("command"))
    fields += [("executor", spec_err or name), ("exec path", path)] + _execution(item, now)
    if launch:
        fields.append(("take-over", "delivered=%s taken_over=%s" % (
            "yes" if launch["delivered"] else "no", "yes" if launch["taken_over"] else "no")))
    summary, open_required = _messages(status, row["id"])
    reports = [w for w in status["worker_results"] if w["attempt"] == row["id"]]
    fields += [("messages", summary), ("unapplied", open_required or "none"),
               ("report", "submitted %s (ledger) %s; worker report, not acceptance" % (
                   when(reports[-1]["created"]), reports[-1]["id"]) if reports else "not submitted"),
               ("acceptance", _acceptance(item, status)), ("cleanup", _cleanup(item, status)),
               ("terminal", _terminal(item))]
    for name in ("stdout.txt", "stderr.txt"):
        size = item["outputs"][name]
        fields.append((name.split(".")[0], "%s (%s)" % (str(Path(item["folder"]) / name),
                                                        "absent" if size is None else "%d bytes" % size)))
    return fields


def progress(observation, now, projects=()):
    """PROGRESS data (slot, stored assignments, attempts) shared by the text frame and --json."""
    status = observation["status"]
    active = next((a for a in observation["attempts"] if a["row"]["state"] in SLOT_STATES), None)
    slot = "%s %s %s" % (active["row"]["state"], active["row"]["id"][:8], active["row"]["task"]) if active else "free"
    if active and not _keep(projects, active["row"]["project"]):
        slot += " (outside --project; the one slot is shared)"
    pending = [dict(line="  - %s %s %s" % (v["id"], v["contract"].get("role"), v["task"]),
                    fields=[("stored", "%s %s %s" % (v["state"], v["origin"], when(v["created"])))]
                    + ([("reason", v["reason"])] if v.get("reason") else []))
               for v in status["assignments"] if v["state"] in OPEN_ASSIGNMENTS and not v["launches"]
               and _keep(projects, _project_of(v["task"]))]
    items = sorted((a for a in observation["attempts"] if _keep(projects, a["row"]["project"])),
                   key=lambda a: (a is not active, -a["row"]["created"]))
    attempts = [dict(line="- [%s] %s %s" % (i["row"]["id"][:8], i["row"]["state"].upper(), i["row"]["task"]),
                     fields=_attempt_fields(i, status, now)) for i in items[:MAX_ATTEMPTS]]
    return dict(state=observation["state"], slot=slot, pending=pending, attempts=attempts, total=len(items),
                omitted=max(0, len(items) - MAX_ATTEMPTS))


def _progress_lines(frame, data):
    frame.field("slot", data["slot"], indent=0)
    frame.line()
    frame.line("PENDING ASSIGNMENTS (stored, not launched): %d" % len(data["pending"]))
    _items(frame, data["pending"])
    frame.line()
    frame.line("ATTEMPTS: %d (active first, then newest)" % data["total"])
    _items(frame, data["attempts"])
    if data["omitted"]:
        frame.line("... %d older attempts omitted; use `status` for the full ledger" % data["omitted"])


def _items(frame, rows):
    for row in rows:
        frame.line(row["line"])
        for label, value in row["fields"]:
            frame.field(label, value)


def render(observation, now, width=0):
    """The original ledger-only frame (header + PROGRESS)."""
    frame = Frame(max(width, MIN_WIDTH) if width else 0)
    header(frame, now, observation["state"])
    _progress_lines(frame, progress(observation, now))
    return frame.text()


# ---- session overview: WAITING / PROBLEMS / PROGRESS / SESSIONS ------------------------------

def _project_of(task):
    return task.split("/", 1)[0] if isinstance(task, str) and "/" in task else None


def _keep(projects, project):
    return not projects or project in projects


def harness_sessions(root, command=None, run=None):
    """Sessions from the harness PUBLIC CLI (`work status`, run from the vault root).

    Never reads harness storage. Missing root, launch error, timeout, unexpected exit
    or malformed JSON -> unavailable. Exit 1 with valid JSON means sessions have issues.
    """
    if not root:
        return dict(state="unavailable", reason="harness root not configured (--harness-root or config harness_root)")
    if not Path(root).is_dir():
        return dict(state="unavailable", reason="harness root not found: %s" % root)
    argv, run = [str(part) for part in (command or HARNESS_COMMAND)] + ["work", "status"], run or subprocess.run
    try:
        done = run(argv, cwd=str(root), capture_output=True, text=True, timeout=HARNESS_TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        return dict(state="unavailable", reason="harness query failed: %s" % exc)
    try:
        data = json.loads(done.stdout)
        sessions = data["sessions"]
        valid = isinstance(sessions, list) and all(isinstance(s, dict) and ":" in str(s.get("id", "")) for s in sessions)
    except (ValueError, KeyError, TypeError):
        valid = False
    if done.returncode not in (0, 1) or not valid:
        tail = ((done.stderr or "").strip() or ("" if valid else (done.stdout or "").strip()))[-200:]
        return dict(state="unavailable", reason="harness work status exit %s, %s%s" % (
            done.returncode, "valid JSON" if valid else "malformed output", ": " + tail if tail else ""))
    return dict(state="ok", exit=done.returncode, sessions=sessions, issues=data.get("issues", []),
                sha256=hashlib.sha256(done.stdout.encode()).hexdigest())


def central_tasks(catalog):
    """(blocked/review Tasks, per-file read problems) from the configured project task dirs."""
    found, problems = [], []
    for project in catalog.projects:
        for path in sorted(Path(project["tasks"]).glob("*.md")):
            try:
                tasks = catalog.read(only_path=path)
            except Exception as exc:  # malformed frontmatter or fields: shown, never guessed
                problems.append(dict(project=project["id"], path=str(path), reason="task malformed: %s" % exc))
                continue
            found += [dict(project=t.project, task=t.key, status=t.status, title=t.title, path=t.path)
                      for t in tasks.values() if t.status in WAITING_STATUSES]
    return found, problems


def ref_rows(db):
    """ref_events plus their wake audit rows, read over the viewer's mode=ro connection."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ref_events'").fetchone():
        return None  # no `ref` command has used this ledger yet; the viewer does not add the table
    events = [dict(r) for r in db.execute(
        "SELECT id,kind,task,task_path,item,item_sha256,sender,sender_exec,recipient,recipient_exec,"
        "reply_to,state,deliveries,expires,outcome,reason,created FROM ref_events ORDER BY seq")]
    wakes = {}
    for r in db.execute("SELECT message,action,detail,created FROM message_audit "
                        "WHERE action LIKE 'ref.wake_%' ORDER BY seq"):
        detail = json.loads(r["detail"]) if r["detail"] else {}
        wakes.setdefault(r["message"][len("ref:"):], []).append(dict(
            action=r["action"][len("ref."):], reason=detail.get("reason"), sent=detail.get("sent"), at=r["created"]))
    for event in events:
        event["wakes"] = wakes.get(event["id"], [])
    return events


def _stale(event):
    """Same item hash check as `ref claim/read`, recomputed read-only (answer staleness not recomputed)."""
    try:
        body = ref_items(Path(event["task_path"]).read_text()).get(event["item"])
    except (OSError, Invalid) as exc:
        return "stale_reference: %s" % exc
    if body is None:
        return "stale_reference: item not found"
    return None if ref_sha(body) == event["item_sha256"] else "stale_reference: item content changed since publish"


def _row(source, line, *fields):
    return dict(source=source, line=line, fields=[f for f in fields if f])


def _ref_section(events, now, waiting, problems):
    for e in events:
        if e["state"] in REF_SETTLED:
            continue
        where = ("task", "%s item %s" % (e["task"], e["item"]))
        wakes = e["wakes"]
        last = wakes[-1] if wakes else None
        wake = ("last wake", "%s%s at %s (audit)" % (last["action"], " " + last["reason"] if last["reason"] else "",
                                                    when(last["at"]))) if last else ("last wake", "none recorded")
        if e["state"] == "held":
            problems.append(_row("ref", "- [ref] %s %s held" % (e["id"], e["kind"]), ("reason", e["reason"]), where))
            continue
        stale = _stale(e)
        if stale:
            problems.append(_row("ref", "- [ref] %s %s %s but stale" % (e["id"], e["kind"], e["state"]),
                                 ("reason", stale + " (ledger not yet held; next claim/read holds it)"), where))
        busy = sum(1 for w in wakes if w["action"] == "wake_skipped" and w["reason"] == "busy")
        if last and last["action"] == "wake_failed":
            problems.append(_row("wake", "- [wake] %s last wake failed" % e["id"], wake, ("to", e["recipient_exec"])))
        elif busy >= 2:
            problems.append(_row("wake", "- [wake] %s recipient busy %d times" % (e["id"], busy), wake,
                                 ("to", e["recipient_exec"])))
        if stale:
            continue
        state = e["state"] + (" (lease expired)" if e["state"] == "claimed" and (e["expires"] or 0) <= now else "")
        waiting.append(_row("ref", "- [ref] %s %s %s" % (e["id"], e["kind"], state),
                            ("waits on", e["recipient"] + ("" if e["recipient_exec"] == e["recipient"] else
                                                          " (%s)" % (e["recipient_exec"] or "no exec: pull only"))),
                            ("from", e["sender"]), where,
                            ("since", "%s (ledger) deliveries=%d" % (when(e["created"]), e["deliveries"])), wake))


def _session_rows(harness, events, projects):
    if harness["state"] != "ok":
        return [], []
    rows, problems = [], []
    for s in harness["sessions"]:
        if not _keep(projects, s.get("project")):
            continue
        key = s["id"]
        refs = [e["id"] for e in events if key in (e["sender"], e["recipient"])]  # exact key match only
        pending = [c.get("tool") for c in s.get("calls") or [] if c.get("state") == "pending"]
        rows.append(dict(key=key, workspace=s.get("workspace")) | _row("harness", "- %s project=%s task=%s" % (key, s.get("project"), s.get("task") or "none bound"),
                         ("workspace", s.get("workspace")),
                         ("calls", "%d recorded%s" % (len(s["calls"]), ", pending: " + ", ".join(pending)
                                                      if pending else "")) if s.get("calls") else None,
                         ("issues", ", ".join(s["issues"])) if s.get("issues") else None,
                         ("refs", ", ".join(refs)) if refs else None))
        if s.get("issues"):
            problems.append(_row("harness", "- [harness] %s %s" % (key, ", ".join(s["issues"])),
                                 ("task", s.get("task") or "none bound")))
    return rows[::-1], problems  # SESSION_ORDER: reverse of the harness output order


SESSION_FILES = {  # provider -> (env override of its home, default home, glob under the home; {id} = raw session id)
    "kiro": (None, "~/.kiro", "sessions/cli/{id}.jsonl"),
    "codex": ("CODEX_HOME", "~/.codex", "sessions/*/*/*/rollout-*-{id}.jsonl"),
    "claude": ("CLAUDE_CONFIG_DIR", "~/.claude", "projects/*/{id}.jsonl"),
}
ORCA_TIMEOUT = 10


def session_roots(override=None):
    override = override if isinstance(override, dict) else {}
    return {agent: str(Path(override.get(agent) or os.environ.get(env or "", "") or home).expanduser())
            for agent, (env, home, _) in SESSION_FILES.items()}


def last_activity(key, roots):
    """mtime of the provider's own session file for this session id. os.stat only; never opened."""
    agent, ident = key.split(":", 1)
    if agent not in SESSION_FILES or not ident or any(c in ident for c in "/*?[]"):
        return "unavailable (no known session file layout for %s)" % agent
    matches = sorted(glob.glob(str(Path(roots[agent]) / SESSION_FILES[agent][2].format(id=ident))))
    if len(matches) != 1:
        return "unavailable (%s session files for this id)" % ("no" if not matches else len(matches))
    try:
        return "%s (session file mtime: %s)" % (when(os.stat(matches[0]).st_mtime), matches[0])
    except OSError as exc:
        return "unavailable (stat failed: %s)" % exc.strerror


def _orca(orca, args, run):
    try:
        done = run([orca, *args, "--json"], capture_output=True, text=True, timeout=ORCA_TIMEOUT, stdin=subprocess.DEVNULL)
        body = json.loads(done.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return None, "orca %s: %s" % (" ".join(args), exc)
    if not isinstance(body, dict) or not body.get("ok") or not isinstance(body.get("result"), dict):
        code = (body.get("error") or {}).get("code") if isinstance(body, dict) and isinstance(body.get("error"), dict) else None
        return None, "orca %s: %s (exit %s)" % (" ".join(args), code or "unexpected payload", done.returncode)
    return body["result"], None


def _handle(address):
    """Terminal handle from an `orca:<handle>` / `<agent>:<handle>` execution identity, else None."""
    tail = address.split(":", 1)[1] if isinstance(address, str) and ":" in address else ""
    return tail if tail.startswith("term_") else None


def recorded_terminals(harness, sessions):
    """{session key: (terminal, terminal_source)} for shown sessions whose harness `work status` row carries
    a recorded terminal. Older harness output has no such field -> {} (behaviour unchanged)."""
    if harness["state"] != "ok":
        return {}
    shown = {row["key"] for row in sessions}
    return {s["id"]: (s["terminal"], s.get("terminal_source") or "source unknown") for s in harness["sessions"]
            if s["id"] in shown and isinstance(s.get("terminal"), str) and s["terminal"]}


def _unverified(sessions, recorded, reason):
    """Show each recorded terminal as the harness recorded it, explicitly not checked against Orca."""
    for row in sessions:
        if row["key"] in recorded:
            terminal, source = recorded[row["key"]]
            row["fields"].append(("terminal", "%s recorded by harness (%s); not verified live: %s" % (terminal, source, reason)))


def orca_section(raw, projects, observation, events, sessions, problems, sources, run=None, recorded=None):
    """Live Orca terminals and supervised dispatches via read-only verbs only (status, terminal list,
    orchestration worker-list). A terminal joins a session when the session's harness-recorded `terminal`
    equals `orca:<handle>` exactly (primary), or through a ref event pairing that session key with a terminal
    execution identity (secondary label when both exist). Folder or agent name never link. Every other
    terminal is listed as session unknown."""
    run, recorded = run or subprocess.run, recorded or {}
    orca = shutil.which(raw.get("orca_command") or "orca")
    if not orca:
        sources["orca"] = "unavailable: orca not found (config orca_command or PATH)"
        _unverified(sessions, recorded, "Orca unavailable")
        return None
    status, error = _orca(orca, ["status"], run)
    runtime = (status or {}).get("runtime") or {}
    if error or runtime.get("state") != "ready" or not runtime.get("reachable"):
        sources["orca"] = "unavailable: %s" % (error or "runtime not ready (%s)" % runtime.get("state"))
        _unverified(sessions, recorded, "Orca unavailable")
        return None
    listed, error = _orca(orca, ["terminal", "list"], run)
    if error or not isinstance(listed.get("terminals"), list):
        sources["orca"] = "unavailable: %s" % (error or "terminal list without terminals")
        _unverified(sessions, recorded, "Orca unavailable")
        return None
    workers, werror = _orca(orca, ["orchestration", "worker-list"], run)
    dispatches = {}
    for w in (workers or {}).get("workers") or []:
        if isinstance(w, dict) and w.get("agentTerminalHandle"):
            dispatches.setdefault(w["agentTerminalHandle"], w)  # newest first per Orca
    live = {t["handle"]: t for t in listed["terminals"] if isinstance(t, dict) and t.get("handle")}
    sources["orca"] = "ok: %d live terminals%s; dispatches %s" % (len(live), " (truncated)" if listed.get("truncated") else "",
        "unavailable: " + werror if werror else "%d (scope %s)" % (len(dispatches), (workers.get("scope") or {}).get("source")))
    keys = {row["key"]: row for row in sessions}
    evidence = {}  # handle -> [(kind, detail)]
    for e in events:
        for who, exe in ((e["sender"], e["sender_exec"]), (e["recipient"], e["recipient_exec"])):
            for address in dict.fromkeys((who, exe)):  # participant and its execution identity
                handle = _handle(address)
                if handle and who in keys:  # recorded pairing: harness session key <-> terminal identity
                    evidence.setdefault(handle, []).append(("session", "%s (ref %s identity)" % (who, e["id"])))
                elif handle:
                    evidence.setdefault(handle, []).append(("ref", "%s in %s" % (who, e["id"])))
        handle = _handle(e["recipient_exec"])
        if handle and handle not in live and e["state"] not in REF_SETTLED:
            problems.append(_row("orca", "- [orca] %s recipient terminal not live" % e["id"], ("terminal", handle),
                                 ("source", "absent from orca terminal list (stale or closed)")))
    for item in (observation or {}).get("attempts", []):
        row = item["row"]
        if row["adapter"] == "orca" and row["handle"] and _keep(projects, row["project"]):
            evidence.setdefault(row["handle"], []).append(("attempt", "%s %s (terminal.json %s)" % (
                row["id"][:8], row["state"], "identity" if (item["files"]["terminal"][0] or {}).get("identity") else "no identity")))
    roots = [Path(p["repo"]) for p in raw.get("projects", []) if isinstance(p, dict) and p.get("repo")
             and _keep(projects, p.get("id"))] + [Path(r["workspace"]) for r in sessions if r.get("workspace")]
    linked_by_harness = {}  # handle -> [session key] whose recorded terminal == "orca:<handle>" exactly
    for key, (terminal, _) in recorded.items():
        if terminal.startswith("orca:") and terminal[len("orca:"):] in live:
            linked_by_harness.setdefault(terminal[len("orca:"):], []).append(key)
        else:
            keys[key]["fields"].append(("terminal", "%s recorded by harness (%s); not in live orca terminal list%s" % (
                terminal, recorded[key][1], " (list truncated)" if listed.get("truncated") else "")))
    def in_scope(t):
        return not projects or t["handle"] in evidence or t["handle"] in linked_by_harness or any(
            Path(t.get("worktreePath") or "/nonexistent") == root for root in roots)
    unknown = []
    for handle, t in live.items():
        if not in_scope(t):
            continue
        d = dispatches.get(handle)
        projection = (d or {}).get("projection") or {}
        orca_fact = ("orca", "agent=%s connected=%s orphaned=%s last output %s (terminal list)" % (
            t.get("agentIdentity") or "unknown", t.get("connected"), t.get("orphaned"),
            when(t["lastOutputAt"] / 1000) if isinstance(t.get("lastOutputAt"), (int, float)) else "unavailable"))
        facts = [("worktree", t.get("worktreePath")), orca_fact]
        dispatch = None
        if d:
            liveness = projection.get("liveness") or {}
            dispatch = ("dispatch", "%s task %s worker=%s outcome=%s liveness=%s/%s (worker-list)" % (
                d.get("dispatchId"), d.get("taskId"), d.get("workerState"), projection.get("outcome"),
                liveness.get("verdict"), liveness.get("reason")))
            facts.append(dispatch)
        linked = [detail for kind, detail in evidence.get(handle, []) if kind == "session"]
        secondary = [(kind, detail) for kind, detail in dict.fromkeys(evidence.get(handle, [])) if kind != "session"]
        harness_keys = linked_by_harness.get(handle, [])
        for key in harness_keys:
            keys[key]["fields"] += [("terminal", handle), ("worktree", "%s (terminal list)" % t.get("worktreePath")),
                                    orca_fact] + ([dispatch] if dispatch else []) + [
                ("link", "harness terminal (%s)" % recorded[key][1])] + [
                ("ref pairing", detail) for detail in dict.fromkeys(linked)] + secondary
        for detail in dict.fromkeys(linked):
            who = detail.split(" ", 1)[0]
            if who not in harness_keys:  # ref-only pairing: unchanged (harness link already lists it as secondary)
                keys[who]["fields"].append(("terminal", "%s via %s" % (handle, detail.split(" ", 1)[1])))
        if not linked and not harness_keys:
            unknown.append(_row("orca", "- %s terminal, session unknown" % handle, *facts + secondary))
    return unknown


def overview(config, state, projects=(), harness_root=None, now=None, run=None):
    """One read-only observation of every phase-1 source; each source fails independently."""
    now, projects = time.time() if now is None else now, tuple(projects or ())
    raw = _json(config)[0] if Path(config).is_file() else None
    raw = raw if isinstance(raw, dict) else {}
    root = harness_root or raw.get("harness_root")
    if root and not harness_root:
        root = (Path(config).resolve().parent / root).resolve()
    sources, errors, waiting, problems, events, data = {}, [], [], [], [], None
    try:
        observation = collect(config, state)
        data = progress(observation, now, projects)
        events = [e for e in observation.get("refs") or [] if _keep(projects, _project_of(e["task"]))]
        sources["scheduler"] = "ok: " + observation["state"]
        sources["ref events"] = observation.get("refs_error") or "ok: %d in filter" % len(events)
    except Exception as exc:  # the same failures the ledger view already reports
        errors.append("%s: %s" % (type(exc).__name__, exc))
        sources["scheduler"] = sources["ref events"] = "unavailable: " + str(exc)
    _ref_section(events, now, waiting, problems)
    try:
        tasks, bad = central_tasks(Catalog(config))
        sources["tasks"] = "ok"
    except Exception as exc:
        tasks, bad, sources["tasks"] = [], [], "unavailable: %s" % exc
    waiting += [_row("task", "- [task] %s status=%s" % (t["task"], t["status"]), ("title", t["title"]), ("path", t["path"]))
                for t in tasks if _keep(projects, t["project"])]
    problems += [_row("task", "- [task] %s" % b["path"], ("reason", b["reason"])) for b in bad if _keep(projects, b["project"])]
    if data:
        problems += [_row("attempt", "- [attempt] %s %s %s" % (a["row"]["id"][:8], a["row"]["state"], a["row"]["task"]),
                          ("attempt", a["row"]["id"]), ("blocker", a["blocker"]) if a["blocker"] else None)
                     for a in observation["attempts"] if _keep(projects, a["row"]["project"])
                     and (a["row"]["state"] in ("failed", "unknown") or a["blocker"])]
    harness = harness_sessions(root, raw.get("harness_command"), run)
    sources["harness"] = ("ok: exit %d%s, %d sessions, sha256 %s" % (
        harness["exit"], " (sessions with issues)" if harness["exit"] == 1 else "", len(harness["sessions"]),
        harness["sha256"][:12]) if harness["state"] == "ok" else "unavailable: " + harness["reason"])
    sources["approval"] = "unsupported (no CLI approval-wait source yet)"
    sessions, session_problems = _session_rows(harness, events, projects)
    roots = session_roots(raw.get("session_file_roots"))
    sources["session files"] = "stat only (contents never read): " + ", ".join("%s %s" % kv for kv in roots.items())
    for row in sessions:
        row["fields"].append(("last activity", last_activity(row["key"], roots)))
    terminals = orca_section(raw, projects, observation if data else None, events, sessions, problems, sources, run,
                             recorded_terminals(harness, sessions))
    return dict(time=now, state=str(state), filter=list(projects) or "all", errors=errors, sources=sources,
                waiting=waiting, problems=problems + session_problems, progress=data,
                sessions=sessions if harness["state"] == "ok" else None, session_order=SESSION_ORDER,
                terminals=terminals)


def render_overview(data, width=0, interval=None, sessions_cap=MAX_SESSIONS):
    """`sessions_cap` None shows every session; the data (and --json) always keep all of them."""
    frame = Frame(max(width, MIN_WIDTH) if width else 0)
    header(frame, data["time"], data["state"])
    frame.field("projects", "all" if data["filter"] == "all" else ", ".join(data["filter"]), indent=0)
    for error in data["errors"]:
        frame.field("ERROR", error, indent=0)
        if interval:
            frame.field("", "query failed; retrying every %gs (nothing was changed)" % interval, indent=0)
    frame.line("SOURCES")
    for label, value in data["sources"].items():
        frame.field(label, value, indent=2)
    frame.line()
    frame.line("WAITING: %d (CLI approval waits: unsupported)" % len(data["waiting"]))
    _items(frame, data["waiting"])
    frame.line()
    frame.line("PROBLEMS: %d" % len(data["problems"]))
    _items(frame, data["problems"])
    frame.line()
    frame.line("PROGRESS" + ("" if data["progress"] else ": unavailable (see ERROR)"))
    if data["progress"]:
        _progress_lines(frame, data["progress"])
    frame.line()
    sessions = data["sessions"]
    frame.line("SESSIONS: " + ("unavailable (see SOURCES harness)" if sessions is None else
                               "%d bound in harness (unbound sessions are not visible)" % len(sessions)))
    if sessions is not None:
        frame.field("last activity", "session file mtime (activity, not liveness)", indent=2)
        frame.field("terminal", "only through recorded evidence (harness terminal == orca:<handle>, else ref exec identity); Orca fields labelled", indent=2)
        frame.field("order", data["session_order"], indent=2)
    shown = (sessions or []) if sessions_cap is None else (sessions or [])[:sessions_cap]
    _items(frame, shown)
    if sessions and len(sessions) > len(shown):
        frame.line("... %d more not shown (use --sessions all or --json)" % (len(sessions) - len(shown)))
    terminals = data.get("terminals")
    frame.line()
    frame.line("TERMINALS, SESSION UNKNOWN: " + ("unavailable (see SOURCES orca)" if terminals is None else str(len(terminals))))
    _items(frame, terminals or [])
    return frame.text()


def render_error(error, now, width, state, interval=None):
    frame = Frame(max(width, MIN_WIDTH) if width else 0)
    header(frame, now, state)
    frame.field("ERROR", "%s: %s" % (type(error).__name__, error), indent=0)
    if interval:
        frame.field("", "query failed; retrying every %gs (nothing was changed)" % interval, indent=0)
    return frame.text()


def clip(text, rows):
    """Keep an in-place TTY frame within the screen so refresh never scrolls."""
    lines = text.splitlines()
    if rows < 3 or len(lines) < rows:
        return text
    hidden = len(lines) - (rows - 2)
    return "\n".join(lines[:rows - 2] + ["... %d more lines; enlarge the terminal or use --once" % hidden]) + "\n"


def watch(config, state, interval=2.0, once=False, width=None, stream=None, clock=time.time, sleep=time.sleep,
          projects=(), harness_root=None, as_json=False, sessions_cap=MAX_SESSIONS):
    """Print frames until Ctrl-C. Exit 0 on a clean stop, 2 when a `--once` ledger/config query fails.

    `--json` prints the same overview data as one JSON object per refresh (no ANSI)."""
    stream = stream or sys.stdout
    tty = not once and not as_json and stream.isatty()
    try:
        if tty:
            stream.write(CLEAR_SCREEN)
        while True:
            columns = width if width is not None else (shutil.get_terminal_size().columns if stream.isatty() else 0)
            now = clock()
            try:
                data = overview(config, state, projects, harness_root, now)
                ok = not data["errors"]
                text = (json.dumps(data, ensure_ascii=False, default=str) + "\n" if as_json else
                        render_overview(data, columns, None if once else interval, sessions_cap))
            except Exception as exc:  # never fatal to watch
                text, ok = render_error(exc, now, columns, state, None if once else interval), False
            if once:
                stream.write(text)
                stream.flush()
                return 0 if ok else 2
            if tty:
                text = clip(text, shutil.get_terminal_size().lines)
                stream.write(HOME + text.replace("\n", CLEAR_LINE + "\n") + CLEAR_BELOW)
            else:
                stream.write(text if as_json else text + "\n")
            stream.flush()
            sleep(interval)
    except KeyboardInterrupt:
        stream.write("\nviewer stopped; scheduler and workers were not signalled\n")
        stream.flush()
        return 0
