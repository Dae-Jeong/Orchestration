"""Read-only terminal view of one scheduler ledger (`watch`).

Each frame reuses the same `query.Query.status()` projection as `status`, plus
the attempt receipts the worker supervisor already writes, over a SQLite
mode=ro connection: no schema creation, migration or journal-mode change. A
missing, foreign or older/incomplete ledger is reported, never created or
upgraded. The viewer never ticks, launches, claims, ACKs, closes terminals or
edits Tasks, and it starts no child process: Ctrl-C ends only the viewer.
"""
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
import time

from .launcher import PROFILES
from .query import open_readonly
from .store import CLEANUP_DONE, CLEANUP_FINAL, EXECUTING_STATES, LEDGER, SLOT_STATES, Attempt

MAX_ATTEMPTS = 8
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
        return dict(state=str(query.store.root), status=status, attempts=attempts)
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


def render(observation, now, width=0):
    width = max(width, MIN_WIDTH) if width else 0
    frame = Frame(width)
    status = observation["status"]
    header(frame, now, observation["state"])
    active = next((a for a in observation["attempts"] if a["row"]["state"] in SLOT_STATES), None)
    frame.field("slot", "%s %s %s" % (active["row"]["state"], active["row"]["id"][:8], active["row"]["task"])
                if active else "free", indent=0)
    frame.line()
    pending = [a for a in status["assignments"] if a["state"] in OPEN_ASSIGNMENTS and not a["launches"]]
    frame.line("PENDING ASSIGNMENTS (stored, not launched): %d" % len(pending))
    for view in pending:
        contract = view["contract"]
        frame.line("  - %s %s %s" % (view["id"], contract.get("role"), view["task"]))
        frame.field("stored", "%s %s %s" % (view["state"], view["origin"], when(view["created"])))
        if view.get("reason"):
            frame.field("reason", view["reason"])
    frame.line()
    items = sorted(observation["attempts"], key=lambda a: (a is not active, -a["row"]["created"]))
    frame.line("ATTEMPTS: %d (active first, then newest)" % len(items))
    for item in items[:MAX_ATTEMPTS]:
        row, view, launch = item["row"], item["assignment"], item["launch"]
        frame.line("- [%s] %s %s" % (row["id"][:8], row["state"].upper(), row["task"]))
        frame.field("attempt", row["id"])
        frame.field("task", item["task_state"])
        if view:
            frame.field("assignment", view["id"])
            frame.field("role", "%s origin=%s state=%s" % (view["contract"].get("role"), view["origin"], view["state"]))
        else:
            frame.field("assignment", "none recorded for this attempt")
        spec, spec_err = item["files"]["spec"]
        name, path = executor_label((spec or {}).get("command"))
        frame.field("executor", spec_err or name)
        frame.field("exec path", path)
        for label, value in _execution(item, now):
            frame.field(label, value)
        if launch:
            frame.field("take-over", "delivered=%s taken_over=%s" % (
                "yes" if launch["delivered"] else "no", "yes" if launch["taken_over"] else "no"))
        summary, open_required = _messages(status, row["id"])
        frame.field("messages", summary)
        frame.field("unapplied", open_required or "none")
        reports = [w for w in status["worker_results"] if w["attempt"] == row["id"]]
        frame.field("report", "submitted %s (ledger) %s; worker report, not acceptance" % (
            when(reports[-1]["created"]), reports[-1]["id"]) if reports else "not submitted")
        frame.field("acceptance", _acceptance(item, status))
        frame.field("cleanup", _cleanup(item, status))
        frame.field("terminal", _terminal(item))
        for name in ("stdout.txt", "stderr.txt"):
            size = item["outputs"][name]
            frame.field(name.split(".")[0], "%s (%s)" % (str(Path(item["folder"]) / name),
                                                         "absent" if size is None else "%d bytes" % size))
    if len(items) > MAX_ATTEMPTS:
        frame.line("... %d older attempts omitted; use `status` for the full ledger" % (len(items) - MAX_ATTEMPTS))
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


def watch(config, state, interval=2.0, once=False, width=None, stream=None, clock=time.time, sleep=time.sleep):
    """Print frames until Ctrl-C. Exit 0 on a clean stop, 2 when a `--once` query fails."""
    stream = stream or sys.stdout
    tty = not once and stream.isatty()
    try:
        if tty:
            stream.write(CLEAR_SCREEN)
        while True:
            columns = width if width is not None else (shutil.get_terminal_size().columns if stream.isatty() else 0)
            now = clock()
            try:
                text, ok = render(collect(config, state), now, columns), True
            except Exception as exc:  # transient DB/Task/config problems stay visible, never fatal to watch
                text, ok = render_error(exc, now, columns, state, None if once else interval), False
            if once:
                stream.write(text)
                stream.flush()
                return 0 if ok else 2
            if tty:
                text = clip(text, shutil.get_terminal_size().lines)
                stream.write(HOME + text.replace("\n", CLEAR_LINE + "\n") + CLEAR_BELOW)
            else:
                stream.write(text + "\n")
            stream.flush()
            sleep(interval)
    except KeyboardInterrupt:
        stream.write("\nviewer stopped; scheduler and workers were not signalled\n")
        stream.flush()
        return 0
