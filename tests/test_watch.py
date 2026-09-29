"""Read-only `watch` view: synthetic states, failures, width/ANSI and viewer-only Ctrl-C."""
import io
import json
import os
from pathlib import Path
import pty
import select
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import yaml

from scheduler import watch as view
from scheduler.runtime import Scheduler
from scheduler.worker import atomic_json
from test_cleanup import FakeOrca

REPO = Path(__file__).resolve().parents[1]
NOW = 2_000_000_000.0


def clean_env():
    return {k: v for k, v in os.environ.items() if not k.startswith("SCHEDULER_")}


def dump(state):
    db = sqlite3.connect(Path(state) / view.LEDGER)
    try:
        return list(db.iterdump())
    finally:
        db.close()


class Fixture(unittest.TestCase):
    adapter = "orca"

    def setUp(self):
        env = patch.dict(os.environ, clean_env(), clear=True)
        env.start()
        self.addCleanup(env.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "a" / "tasks").mkdir(parents=True)
        self.config = self.root / "config.json"
        self.state = self.root / "state"
        self.config.write_text(json.dumps({"adapter": self.adapter, "command": self.command(),
            "projects": [{"id": "a", "repo": str(self.root / "a"), "tasks": str(self.root / "a" / "tasks")}]}))
        self.task()

    def command(self):
        return [sys.executable, "-c", "pass"]

    def task(self, status="ready", evidence=None):
        meta = dict(type="task", id="one", project_id="a", status=status, evidence=evidence or [])
        self.task_path().write_text("---\n" + yaml.safe_dump(meta) + "---\n\n## Goal\nFixture.\n")

    def task_path(self):
        return self.root / "a" / "tasks" / "one.md"


class WatchStates(Fixture):
    def setUp(self):
        super().setUp()
        self.orca = FakeOrca()
        run = patch("scheduler.adapters.subprocess.run", side_effect=self.orca.run)
        run.start()
        self.addCleanup(run.stop)
        self.runner = Scheduler(self.config, self.state)
        self.addCleanup(lambda: self.runner.close())

    def frame(self, width=0):
        return view.render(view.collect(self.config, self.state), NOW, width)

    def section(self, text, ident):
        """Lines belonging to one attempt block."""
        block = text.split("- [%s]" % ident[:8], 1)[1]
        return block.split("\n- [", 1)[0]

    def launch(self):
        result = self.runner.assign("dash", "a/one", "implement", ["scheduler"], [".artifacts/x.json"])
        self.assertFalse(result["duplicate"])
        started = self.runner.tick()
        self.assertEqual(started["state"], "running")
        return started["attempt"]

    def take_over(self, ident):
        bus, target = self.runner.mailbox, ("a/one", ident, "worker:" + ident)
        claim = bus.claim(*target, bus.inbox(*target)["revision"])["message"]
        bus.processed(claim["id"], *target, claim["revision"], claim["token"], "applied", dict(claim["payload"]["expect"]))
        bus.ack(claim["id"], *target, claim["revision"], claim["token"])
        return bus, target

    def complete(self, ident):
        bus, target = self.take_over(ident)
        inbox = bus.inbox(*target)
        bus.complete("done-" + ident, *target, inbox["revision"], inbox["inbox_seq"], {"fixture": True})

    def receipt(self, ident, kind, **values):
        atomic_json(self.state / "attempts" / ident / (kind + ".json"), dict(values, attempt=ident))

    def test_pending_assignment_before_launch(self):
        self.task(status="blocked")
        self.runner.assign("later", "a/one", "review", [], ["report.md"])
        text = self.frame()
        self.assertIn("slot        free", text)
        self.assertIn("PENDING ASSIGNMENTS (stored, not launched): 1", text)
        self.assertIn("- later review a/one", text)
        self.assertIn("ATTEMPTS: 0", text)

    def test_running_before_and_after_take_over(self):
        ident = self.launch()
        text = self.frame()
        self.assertIn("slot        running %s a/one" % ident[:8], text)
        block = self.section(text, ident)
        self.assertIn("started     no receipt", block)
        self.assertIn("delivered=no taken_over=no", block)
        self.assertIn("unapplied   assignment:%s(queued)" % ident, block)
        self.assertIn("executor    python -c", block)
        self.assertIn("(configured command)", block)
        self.assertIn("role        implement origin=explicit state=launched", block)
        self.assertIn("report      not submitted", block)
        self.assertIn("cleanup     not eligible", block)
        self.assertIn("orca term_", block)
        self.assertIn("(identity recorded)", block)
        self.assertIn(str(self.state / "attempts" / ident / "stdout.txt") + " (absent)", block)

        self.receipt(ident, "started", pid=1, at=NOW - 125)
        self.take_over(ident)
        block = self.section(self.frame(), ident)
        self.assertIn("delivered=yes taken_over=yes", block)
        self.assertIn("unapplied   none", block)
        self.assertIn("elapsed     2m05s since started receipt", block)
        self.assertIn("exited      no receipt", block)

    def test_report_is_not_acceptance_or_exit(self):
        ident = self.launch()
        self.complete(ident)
        block = self.section(self.frame(), ident)
        self.assertIn("report      submitted", block)
        self.assertIn("worker report, not acceptance", block)
        self.assertIn("acceptance  not accepted; worker has not exited", block)
        self.assertIn("ledger      running", block)

    def test_awaiting_acceptance_blocker_then_accepted_and_cleanup(self):
        ident = self.launch()
        self.receipt(ident, "started", pid=1, at=NOW - 70)
        self.complete(ident)
        self.receipt(ident, "exited", code=0, at=NOW - 10)
        self.assertEqual(self.runner.tick()["state"], "awaiting_acceptance")
        block = self.section(self.frame(), ident)
        self.assertIn("AWAITING_ACCEPTANCE", block)
        self.assertIn("blocker: task_not_accepted", block)
        self.assertIn("exited      code 0 at", block)
        self.assertIn("ran         1m00s (receipts)", block)
        self.assertIn("cleanup     not eligible", block)

        self.task(status="done", evidence=["verified.json"])
        self.runner.tick()
        text = self.frame()
        block = self.section(text, ident)
        self.assertIn("slot        free", text)
        self.assertIn("acceptance  accepted at", block)
        self.assertIn("(ledger event)", block)
        self.assertIn("cleanup     closed [done] tries=1", block)
        self.assertIn("role        implement origin=explicit state=completed", block)

    def test_blocked_required_message_and_withheld_cleanup(self):
        ident = self.launch()
        self.take_over(ident)
        self.runner.mailbox.insert("note-1", "a/one", "a", ident, "worker:" + ident,
                                   self.runner.catalog.read()["a/one"].instruction_revision,
                                   "instruction", {"text": "extra"}, True)
        block = self.section(self.frame(), ident)
        self.assertIn("unapplied   note-1(queued)", block)
        (self.state / "attempts" / ident / "terminal.json").unlink()
        self.complete_after_note(ident)
        self.receipt(ident, "exited", code=0)
        self.task(status="done", evidence=["verified.json"])
        self.runner.tick()
        self.runner.tick()
        block = self.section(self.frame(), ident)
        self.assertIn("exited      code 0 (receipt without time)", block)
        self.assertIn("cleanup     withheld [operator]", block)
        self.assertIn("no identity record", block)

    def complete_after_note(self, ident):
        bus, target = self.runner.mailbox, ("a/one", ident, "worker:" + ident)
        claim = bus.claim(*target, bus.inbox(*target)["revision"])["message"]
        bus.processed(claim["id"], *target, claim["revision"], claim["token"], "applied", {"done": True})
        bus.ack(claim["id"], *target, claim["revision"], claim["token"])
        inbox = bus.inbox(*target)
        bus.complete("done-" + ident, *target, inbox["revision"], inbox["inbox_seq"], {"fixture": True})

    def test_malformed_and_missing_task_are_shown_per_attempt(self):
        ident = self.launch()
        self.task_path().write_text("no frontmatter\n")
        text = self.frame()
        self.assertIn("task        task malformed: missing frontmatter", self.section(text, ident))
        self.task_path().unlink()
        self.assertIn("task        task file missing", self.section(self.frame(), ident))

    def test_unreadable_receipt_is_reported(self):
        ident = self.launch()
        (self.state / "attempts" / ident / "started.json").write_text("{broken")
        self.assertIn("started     unreadable started.json", self.section(self.frame(), ident))

    def test_narrow_width_keeps_identity(self):
        ident = self.launch()
        text = self.frame(width=44)
        for line in text.splitlines():
            self.assertLessEqual(len(line), 44, line)
        self.assertIn("- [%s] RUNNING a/one" % ident[:8], text)
        self.assertIn("~", text)  # long paths are shortened in the middle
        self.assertNotIn("\x1b", text)

    def test_view_is_read_only(self):
        ident = self.launch()
        self.take_over(ident)
        before, task = dump(self.state), self.task_path().read_bytes()
        forbidden = ["scheduler.runtime.Scheduler." + n for n in
                     ("tick", "assign", "notify", "resolve", "event", "cleanup", "collect", "approve_plan")]
        forbidden += ["scheduler.messaging.Mailbox." + n for n in
                      ("send", "claim", "processed", "ack", "complete", "dismiss", "insert")]
        forbidden += ["scheduler.adapters.launch", "scheduler.adapters.close"]
        patches = [patch(name, side_effect=AssertionError("watch called " + name)) for name in forbidden]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        stream = io.StringIO()
        self.assertEqual(view.watch(self.config, self.state, once=True, stream=stream), 0)
        self.assertIn(ident[:8], stream.getvalue())
        self.assertEqual(dump(self.state), before)
        self.assertEqual(self.task_path().read_bytes(), task)


class WatchFailures(Fixture):
    def test_missing_state_is_reported_and_not_created(self):
        missing = self.root / "nope"
        stream = io.StringIO()
        self.assertEqual(view.watch(self.config, missing, once=True, stream=stream), 2)
        self.assertIn("ERROR", stream.getvalue())
        self.assertIn("state ledger not found", stream.getvalue())
        self.assertFalse(missing.exists())

    def test_missing_config(self):
        stream = io.StringIO()
        self.assertEqual(view.watch(self.root / "none.json", self.state, once=True, stream=stream), 2)
        self.assertIn("config not found", stream.getvalue())

    def test_transient_failure_keeps_watching_and_ctrl_c_stops_viewer(self):
        Scheduler(self.config, self.state).close()  # empty ledger
        calls, sleeps = [], []
        real = view.collect

        def flaky(config, state):
            calls.append(1)
            if len(calls) == 1:
                raise sqlite3.OperationalError("database is locked")
            return real(config, state)

        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 2:
                raise KeyboardInterrupt

        stream = io.StringIO()
        with patch("scheduler.watch.collect", side_effect=flaky):
            code = view.watch(self.config, self.state, interval=0.5, stream=stream, sleep=sleep)
        out = stream.getvalue()
        self.assertEqual(code, 0)
        self.assertEqual(sleeps, [0.5, 0.5])
        self.assertIn("ERROR       OperationalError: database is locked", out)
        self.assertIn("retrying every 0.5s", out)
        self.assertIn("slot        free", out.split("database is locked", 1)[1])
        self.assertIn("viewer stopped; scheduler and workers were not signalled", out)
        self.assertNotIn("\x1b", out)

    def test_cli_rejects_bad_interval(self):
        result = subprocess.run([sys.executable, "-m", "scheduler", "--config", str(self.config), "--state",
                                 str(self.state), "watch", "--interval", "0"], cwd=REPO, env=clean_env(),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--interval must be positive", result.stderr)
        self.assertFalse(self.state.exists())


SIDECARS = {view.LEDGER + "-wal", view.LEDGER + "-shm"}


class WatchLedgerReadOnly(Fixture):
    """watch opens an ordinary SQLite mode=ro connection: no schema, migration, journal-mode or
    application file writes. For a WAL ledger SQLite itself may add its -wal/-shm read-lock
    files; they stay bounded (no WAL frames) and the database file bytes stay identical."""

    def files(self):
        return {str(p.relative_to(self.state)): p.read_bytes() for p in sorted(self.state.rglob("*")) if p.is_file()}

    def schema(self):
        path = self.state / view.LEDGER
        if not path.is_file():
            return None
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            return (sorted(tuple(r) for r in db.execute("SELECT type, name, sql FROM sqlite_master")),
                    db.execute("PRAGMA journal_mode").fetchone()[0])
        except sqlite3.DatabaseError as exc:
            return ("unreadable", str(exc))
        finally:
            db.close()

    def observe(self):
        files = self.files()  # file bytes first, before inspecting the schema
        return dict(files=files, schema=self.schema())

    def assert_unmodified(self, before, after):
        self.assertEqual(after["schema"], before["schema"])  # tables, indexes, DDL and journal mode
        app = lambda files: {k: v for k, v in files.items() if k not in SIDECARS}
        self.assertEqual(app(after["files"]), app(before["files"]))  # ledger bytes and every other path
        self.assertLessEqual(set(after["files"]) - set(before["files"]), SIDECARS)
        wal = view.LEDGER + "-wal"
        self.assertEqual(after["files"].get(wal, b""), before["files"].get(wal, b""))  # no WAL frames written

    def once(self):
        stream = io.StringIO()
        with patch("scheduler.runtime.Scheduler.__init__", side_effect=AssertionError("watch built a writer Scheduler")):
            code = view.watch(self.config, self.state, once=True, stream=stream)
        return code, stream.getvalue()

    def writer_ledger(self):
        Scheduler(self.config, self.state).close()

    def assert_rejected(self, *diagnostic):
        before = self.observe()
        code, out = self.once()
        self.assertEqual(code, 2, out)
        for text in diagnostic:
            self.assertIn(text, out)
        after = self.observe()
        self.assert_unmodified(before, after)
        return out, before, after

    def test_unrelated_sqlite_file_is_rejected_unchanged(self):
        self.state.mkdir()
        with sqlite3.connect(self.state / view.LEDGER) as db:
            db.execute("CREATE TABLE operator_marker(value TEXT)")
        db.close()
        _, before, after = self.assert_rejected("not a scheduler ledger", "missing tables")
        self.assertEqual([r[1] for r in after["schema"][0]], ["operator_marker"])
        self.assertEqual(after["schema"][1], "delete")
        self.assertEqual(set(after["files"]), set(before["files"]))  # rollback journal: no sidecar at all

    def test_older_ledger_missing_tables_is_not_migrated(self):
        self.writer_ledger()
        with sqlite3.connect(self.state / view.LEDGER) as db:
            for table in ("cleanups", "assignment_launches", "assignments"):
                db.execute("DROP TABLE " + table)
        db.close()
        out, _, after = self.assert_rejected("missing tables", "assignment_launches, assignments, cleanups")
        self.assertIn("viewer does not migrate", out)
        self.assertNotIn("cleanups", [r[1] for r in after["schema"][0]])
        self.assertEqual(after["schema"][1], "wal")

    def test_incomplete_table_columns_are_reported(self):
        self.writer_ledger()
        with sqlite3.connect(self.state / view.LEDGER) as db:
            db.execute("DROP TABLE cleanups")
            db.execute("CREATE TABLE cleanups(attempt TEXT PRIMARY KEY, state TEXT NOT NULL)")
        db.close()
        self.assert_rejected("missing columns", "cleanups.detail")

    def test_non_database_file_is_rejected_unchanged(self):
        self.state.mkdir()
        (self.state / view.LEDGER).write_bytes(b"operator notes, not sqlite\n" * 40)
        _, before, after = self.assert_rejected("ERROR")
        self.assertEqual(after["files"], before["files"])

    def test_existing_state_without_ledger_creates_nothing(self):
        self.state.mkdir()
        self.assert_rejected("state ledger not found")
        self.assertEqual(list(self.state.iterdir()), [])

    def test_valid_closed_ledger_is_viewed_without_mutation(self):
        self.writer_ledger()
        before = self.observe()
        self.assertEqual(before["schema"][1], "wal")  # normal writer initialization is unchanged
        code, out = self.once()
        self.assertEqual(code, 0, out)
        self.assertIn("slot        free", out)
        self.assert_unmodified(before, self.observe())

    def test_query_connection_rejects_writes(self):
        from scheduler.store import Store
        self.writer_ledger()
        before = self.observe()
        store = Store(self.state, readonly=True)
        try:
            with self.assertRaisesRegex(sqlite3.OperationalError, "readonly"):
                store.db.execute("CREATE TABLE intruder(x)")
            with self.assertRaisesRegex(sqlite3.OperationalError, "readonly"):
                store.set("intruder", 1)
        finally:
            store.close()
        self.assert_unmodified(before, self.observe())

    def test_active_writer_wal_content_is_visible(self):
        from scheduler.store import Store
        self.writer_ledger()
        writer = Scheduler(self.config, self.state)  # an open writer, as during `run`
        try:
            writer.store.set("marker", 2)  # committed to the WAL, not yet checkpointed
            self.assertTrue(len((self.state / (view.LEDGER + "-wal")).read_bytes()) > 0)
            store = Store(self.state, readonly=True)
            try:
                self.assertEqual(store.get("marker"), 2)
            finally:
                store.close()
            writer.store.set("marker", 3)
            code, out = self.once()
            self.assertEqual(code, 0, out)
            store = Store(self.state, readonly=True)
            try:
                self.assertEqual(store.get("marker"), 3)
            finally:
                store.close()
        finally:
            writer.close()


class ExecutorLabels(unittest.TestCase):
    def test_preset_shows_actual_executable(self):
        name, path = view.executor_label([sys.executable, "/x/scheduler/launcher.py", "--executor", "kiro",
                                          "--executable", "/opt/bin/kiro-cli", "--model", "claude-opus-5.5"])
        self.assertEqual(name, "kiro-cli model=claude-opus-5.5")
        self.assertEqual(path, "/opt/bin/kiro-cli (preset kiro)")

    def test_explicit_command_shows_executable(self):
        name, path = view.executor_label(["/Users/u/.local/bin/kiro-cli", "chat", "--model", "claude-opus-5.5"])
        self.assertEqual(name, "kiro-cli model=claude-opus-5.5")
        self.assertEqual(path, "/Users/u/.local/bin/kiro-cli (configured command)")

    def test_middle_keeps_head_and_tail(self):
        self.assertEqual(view.middle("abcdefghij", 7), "abc~hij")
        self.assertEqual(view.middle("short", 10), "short")


class LiveViewer(Fixture):
    """Real processes: local-adapter scheduler `run`, a detached worker and the watch CLI."""
    adapter = "local"

    def command(self):
        return [sys.executable, "-c", "import time; time.sleep(60)"]

    def cli(self, *args):
        return [sys.executable, "-m", "scheduler", "--config", str(self.config), "--state", str(self.state), *args]

    def start_scheduler(self):
        runner = subprocess.Popen(self.cli("run", "--interval", "0.2"), cwd=REPO, env=clean_env(),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop, runner)
        deadline = time.time() + 20
        started = None
        while time.time() < deadline:
            found = list(self.state.glob("attempts/*/started.json"))
            if found:
                started = json.loads(found[0].read_text())
                break
            time.sleep(0.1)
        self.assertIsNotNone(started, "worker did not start")
        self.addCleanup(self.kill_group, started["pid"])
        return runner, started["pid"]

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    @staticmethod
    def kill_group(pid):
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass

    @staticmethod
    def alive(pid):
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def wait_for(self, process, needle, stream_read, timeout=15):
        data, deadline = b"", time.time() + timeout
        while needle not in data and time.time() < deadline and process.poll() is None:
            data += stream_read()
        return data

    def test_ctrl_c_stops_viewer_only(self):
        runner, worker = self.start_scheduler()
        viewer = subprocess.Popen(self.cli("watch", "--interval", "0.2"), cwd=REPO, env=clean_env(),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.stop, viewer)
        fd = viewer.stdout.fileno()
        read = lambda: os.read(fd, 65536) if select.select([fd], [], [], 0.2)[0] else b""
        data = self.wait_for(viewer, b"ATTEMPTS: 1", read)
        data += self.wait_for(viewer, b"ATTEMPTS: 1", read)  # at least two refreshes
        self.assertGreaterEqual(data.count(b"scheduler watch"), 2, data[-500:])
        self.assertIn(b"RUNNING a/one", data)
        viewer.send_signal(signal.SIGINT)
        out, err = viewer.communicate(timeout=10)
        self.assertEqual(viewer.returncode, 0, err)
        self.assertIn(b"viewer stopped", out)
        self.assertNotIn(b"\x1b", data + out)
        time.sleep(0.5)
        self.assertIsNone(runner.poll(), "scheduler run must keep running")
        self.assertTrue(self.alive(worker), "worker must keep running")

    def test_tty_refreshes_in_place(self):
        runner, worker = self.start_scheduler()
        master, slave = pty.openpty()
        viewer = subprocess.Popen(self.cli("watch", "--interval", "0.2"), cwd=REPO, env=clean_env(),
                                  stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        self.addCleanup(os.close, master)
        self.addCleanup(self.stop, viewer)
        def read():
            try:
                return os.read(master, 65536) if select.select([master], [], [], 0.2)[0] else b""
            except OSError:
                return b""
        data = self.wait_for(viewer, b"RUNNING a/one", read)
        data += self.wait_for(viewer, b"\x1b[H", read)
        self.assertIn(view.CLEAR_SCREEN.encode(), data)
        self.assertGreaterEqual(data.count(view.HOME.encode()), 1)
        os.kill(viewer.pid, signal.SIGINT)
        viewer.wait(10)
        self.assertEqual(viewer.returncode, 0)
        self.assertIsNone(runner.poll())
        self.assertTrue(self.alive(worker))


if __name__ == "__main__":
    unittest.main()
