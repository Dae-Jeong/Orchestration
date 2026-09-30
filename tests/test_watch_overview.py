"""Session overview in `watch`: WAITING/PROBLEMS/PROGRESS/SESSIONS, --project, --json, read-only sources."""
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from scheduler import watch as view
from scheduler.refs import References
from scheduler.runtime import Scheduler
from test_cleanup import FakeOrca
from test_watch import NOW, REPO, Fixture, clean_env, dump

# Stand-in for the harness public CLI: prints out.json, exits with code.txt, logs its argv.
FAKE_HARNESS = '''import json, pathlib, sys
here = pathlib.Path(__file__).parent
with (here / "args.log").open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
sys.stdout.write((here / "out.json").read_text())
sys.exit(int((here / "code.txt").read_text()))
'''
SESSIONS = {"sessions": [
    {"id": "kiro:s-a", "workspace": "/w/a", "project": "a", "task": "one", "calls": [], "issues": []},
    {"id": "codex:s-b", "workspace": "/w/b", "project": "b", "task": None,
     "calls": [{"tool": "t1", "state": "pending", "ambiguous": 1, "reconciliation": None}], "issues": ["work-pending"]}],
    "issues": ["work-pending"]}
MAIN = ("orca:term-main", "orca:term-main")


def block(ident, body):
    return "<!-- item:%s -->\n%s\n<!-- /item:%s -->\n" % (ident, body, ident)


class OverviewFixture(Fixture):
    """Two projects, a running and a failed attempt, ref events and a fake harness (no tests here)."""

    def setUp(self):
        super().setUp()
        (self.root / "b" / "tasks").mkdir(parents=True)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        (self.vault / "fake_harness.py").write_text(FAKE_HARNESS)
        self.harness(SESSIONS, 1)
        self.config.write_text(json.dumps({
            "adapter": "orca", "command": [sys.executable, "-c", "pass"], "harness_root": "vault",
            "orca_command": str(self.root / "no-orca"), "session_file_roots": {a: str(self.root / "no-home") for a in ("kiro", "codex", "claude")},
            "harness_command": [sys.executable, str(self.vault / "fake_harness.py")],
            "projects": [{"id": p, "repo": str(self.root / p), "tasks": str(self.root / p / "tasks")} for p in "ab"]}))
        self.write("a", "one", "ready", block("q1", "Which token?") + block("s1", "Old text"))
        self.write("a", "rev", "review")
        self.write("b", "two", "blocked", block("done1", "Result: ok"))
        orca = FakeOrca()
        run = patch("scheduler.adapters.subprocess.run", side_effect=orca.run)
        run.start()
        self.runner = Scheduler(self.config, self.state)
        self.addCleanup(lambda: self.runner.close())
        self.runner.assign("dash", "a/one", "implement", ["scheduler"], [".artifacts/x.json"])
        self.attempt = self.runner.tick()["attempt"]
        run.stop()  # the fake Orca patches subprocess.run globally; the viewer never calls Orca
        self.runner.store.db.execute(
            "INSERT INTO attempts(id,task,project,revision,adapter,state,handle,created,detail) "
            "VALUES ('f0000000-b','b/two','b','r','orca','failed','h',?, '{}')", (NOW - 60,))
        self.refs = References(self.runner.store, self.runner.catalog, self.runner.mailbox.max_deliveries,
                               clock=lambda: NOW - 30)
        self.publish("ev-q", "question.opened", "a", "one", "q1")
        self.publish("ev-held", "work.blocked", "a", "one", "q1")
        self.publish("ev-stale", "work.completed", "a", "one", "s1")
        self.publish("ev-b", "work.completed", "b", "two", "done1")
        self.refs.hold(self.refs.row("ev-held"), "stale_reference: fixture")
        for _ in range(2):
            self.refs.events.audit("ev-q", "wake_skipped", {"reason": "busy", "sent": "no"}, NOW - 20)
        self.refs.events.audit("ev-b", "wake_failed", {"reason": "terminal_stale", "sent": "no"}, NOW - 10)
        path = self.root / "a" / "tasks" / "one.md"
        path.write_text(path.read_text().replace("Old text", "New text"))  # ev-stale's item changed
        (self.root / "b" / "tasks" / "bad.md").write_text("---\ntype: task\nid: bad\nstatus: nope\n---\n")

    def write(self, project, name, status, exchange=""):
        (self.root / project / "tasks" / (name + ".md")).write_text(
            "---\ntype: task\nid: %s\nproject_id: %s\nstatus: %s\n---\n\n## Goal\nFixture.\n\n%s" % (
                name, project, status, exchange))

    def publish(self, ident, kind, project, task, item):
        path = self.root / project / "tasks" / (task + ".md")
        self.refs.publish(ident, kind, "%s/%s" % (project, task), str(path), item, "kiro:s-a", "kiro:s-a", *MAIN)

    def harness(self, output, code=0):
        (self.vault / "out.json").write_text(output if isinstance(output, str) else json.dumps(output))
        (self.vault / "code.txt").write_text(str(code))

    def frame(self, state=None, **kw):
        stream = io.StringIO()
        code = view.watch(self.config, state or self.state, once=True, stream=stream, clock=lambda: NOW, **kw)
        return code, stream.getvalue()

    @staticmethod
    def section(text, name):
        return text.split("\n" + name, 1)[1].split("\n\n" + {"WAITING": "PROBLEMS", "PROBLEMS": "PROGRESS",
                                                              "PROGRESS": "SESSIONS"}.get(name, "\x00"), 1)[0]


class Overview(OverviewFixture):
    def test_four_sections_in_priority_order(self):
        code, text = self.frame()
        self.assertEqual(code, 0, text)
        marks = [text.index("\n" + name) for name in ("WAITING", "PROBLEMS", "PROGRESS", "SESSIONS")]
        self.assertEqual(marks, sorted(marks))
        waiting = self.section(text, "WAITING")
        self.assertIn("- [ref] ev-q question.opened queued", waiting)
        self.assertIn("waits on    orca:term-main\n", waiting)
        self.assertIn("- [ref] ev-b work.completed queued", waiting)
        self.assertIn("- [task] a/rev status=review", waiting)
        self.assertIn("- [task] b/two status=blocked", waiting)
        self.assertIn("CLI approval waits: unsupported", text)
        for absent in ("ev-held", "ev-stale"):
            self.assertNotIn(absent, waiting)
        problems = self.section(text, "PROBLEMS")
        self.assertIn("- [ref] ev-held work.blocked held", problems)
        self.assertIn("- [ref] ev-stale work.completed queued but stale", problems)
        self.assertIn("item content changed since publish", problems)
        self.assertIn("- [wake] ev-q recipient busy 2 times", problems)
        self.assertIn("- [wake] ev-b last wake failed", problems)
        self.assertIn("- [attempt] f0000000 failed b/two", problems)
        self.assertIn("task malformed: invalid status", problems)
        self.assertIn("- [harness] codex:s-b work-pending", problems)
        self.assertIn("- [%s] RUNNING a/one" % self.attempt[:8], self.section(text, "PROGRESS"))
        sessions = text.split("\nSESSIONS", 1)[1]
        self.assertIn(": 2 bound in harness", sessions)
        self.assertIn("- kiro:s-a project=a task=one", sessions)
        self.assertIn("refs        ev-q, ev-held, ev-stale, ev-b", sessions)
        self.assertIn("calls       1 recorded, pending: t1", sessions)
        self.assertIn("last activity unavailable (no session files for this id)", sessions)
        self.assertIn("TERMINALS, SESSION UNKNOWN: unavailable (see SOURCES orca)", sessions)
        self.assertIn("harness     ok: exit 1 (sessions with issues), 2 sessions", text)

    def test_project_filter_excludes_other_projects(self):
        _, text = self.frame(projects=["a"])
        self.assertIn("projects    a\n", text)
        for present in ("ev-q", "a/rev", "RUNNING a/one", "kiro:s-a project=a", "ev-held"):
            self.assertIn(present, text)
        for absent in ("ev-b", "b/two", "codex:s-b", "f0000000", "bad.md", "/w/b"):
            self.assertNotIn(absent, text)
        _, only_b = self.frame(projects=["b"])
        self.assertNotIn(self.attempt[:8] + "] RUNNING", only_b)
        self.assertIn("slot        running %s a/one (outside --project; the one slot is shared)" % self.attempt[:8], only_b)
        self.assertIn("ATTEMPTS: 1", only_b)
        self.assertIn("- [ref] ev-b", only_b)

    def test_json_is_the_rendered_data(self):
        stream = io.StringIO()
        self.assertEqual(view.watch(self.config, self.state, once=True, stream=stream, clock=lambda: NOW,
                                    projects=["a"], as_json=True), 0)
        data = json.loads(stream.getvalue())
        expected = json.loads(json.dumps(view.overview(self.config, self.state, ["a"], None, NOW), default=str))
        self.assertEqual(data, expected)
        self.assertEqual(view.render_overview(view.overview(self.config, self.state, ["a"], None, NOW)),
                         self.frame(projects=["a"])[1])
        self.assertEqual([w["line"] for w in data["waiting"]][:1], ["- [ref] ev-q question.opened queued"])
        self.assertEqual(data["filter"], ["a"])
        self.assertEqual(data["sources"]["orca"], "unavailable: orca not found (config orca_command or PATH)")
        result = subprocess.run([sys.executable, "-m", "scheduler", "--config", str(self.config), "--state",
                                 str(self.state), "watch", "--once", "--json", "--project", "b"],
                                cwd=REPO, env=clean_env(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout[:3000])
        cli = json.loads(result.stdout)
        self.assertEqual(cli["filter"], ["b"])
        self.assertEqual([s["line"] for s in cli["sessions"]], ["- codex:s-b project=b task=none bound"])
        self.assertNotIn("\x1b", result.stdout)

    def test_harness_missing_failing_and_malformed_are_unavailable(self):
        cases = [("not JSON", 0, "malformed output"), ({"nope": []}, 0, "malformed output"),
                 ({"sessions": [{"id": "no-colon"}]}, 0, "malformed output"), (SESSIONS, 3, "valid JSON")]
        for output, code, reason in cases:
            with self.subTest(reason=reason, code=code):
                self.harness(output, code)
                rc, text = self.frame()
                self.assertEqual(rc, 0)
                self.assertIn("harness     unavailable: harness work status exit %d, %s" % (code, reason), text)
                self.assertIn("SESSIONS: unavailable (see SOURCES harness)", text)
                self.assertIn("- [ref] ev-q", text)  # other sources still render
                self.assertNotIn("kiro:s-a project", text)
        self.harness(SESSIONS, 0)
        _, text = self.frame(harness_root=str(self.root / "no-vault"))
        self.assertIn("harness root not found", text)
        for error in (subprocess.TimeoutExpired("uv", 30), FileNotFoundError("uv")):
            with self.subTest(error=type(error).__name__), patch("scheduler.watch.subprocess.run", side_effect=error):
                self.assertIn("harness     unavailable: harness query failed", self.frame()[1])
        self.config.write_text(json.dumps({k: v for k, v in json.loads(self.config.read_text()).items()
                                           if not k.startswith("harness")}))
        with patch("scheduler.watch.subprocess.run", side_effect=AssertionError("no harness configured")):
            _, text = self.frame()
        self.assertIn("harness     unavailable: harness root not configured", text)

    def test_missing_ledger_keeps_other_sources_and_creates_nothing(self):
        missing = self.root / "nope"
        code, text = self.frame(state=missing)
        self.assertEqual(code, 2)
        self.assertIn("ERROR       Missing: state ledger not found", text)
        self.assertIn("PROGRESS: unavailable (see ERROR)", text)
        self.assertIn("scheduler   unavailable", text)
        self.assertIn("- [task] b/two status=blocked", text)
        self.assertIn("- kiro:s-a project=a", text)
        self.assertFalse(missing.exists())

    def test_ledger_without_ref_table_is_reported_and_not_upgraded(self):
        state = self.root / "fresh"
        Scheduler(self.config, state).close()
        before = dump(state)
        _, text = self.frame(state=state)
        self.assertIn("ref events  none: ledger has no ref_events table", text)
        self.assertEqual(dump(state), before)

    def test_overview_is_read_only(self):
        files = sorted(self.root.glob("[ab]/tasks/*.md"))
        before = (dump(self.state), [p.read_bytes() for p in files])
        harness_before = view.harness_sessions(self.vault, [sys.executable, str(self.vault / "fake_harness.py")])
        (self.vault / "args.log").unlink()
        forbidden = ["scheduler.runtime.Scheduler." + n for n in
                     ("tick", "assign", "notify", "resolve", "event", "cleanup", "collect", "approve_plan")]
        forbidden += ["scheduler.messaging.Mailbox." + n for n in ("send", "claim", "processed", "ack", "complete", "dismiss")]
        forbidden += ["scheduler.refs.References." + n for n in
                      ("publish", "claim", "read", "processed", "ack", "dismiss", "wake", "hold")]
        forbidden += ["scheduler.protocol_store.RefStore.__init__", "scheduler.adapters.launch", "scheduler.adapters.close"]
        for name in forbidden:
            p = patch(name, side_effect=AssertionError("watch called " + name))
            p.start()
            self.addCleanup(p.stop)
        code, text = self.frame()
        stream = io.StringIO()
        view.watch(self.config, self.state, once=True, stream=stream, clock=lambda: NOW, as_json=True)
        self.assertEqual(code, 0, text)
        self.assertEqual((dump(self.state), [p.read_bytes() for p in files]), before)
        self.assertEqual([json.loads(line) for line in (self.vault / "args.log").read_text().splitlines()],
                         [["work", "status"], ["work", "status"]])  # the only harness verb called
        after = view.harness_sessions(self.vault, [sys.executable, str(self.vault / "fake_harness.py")])
        self.assertEqual(after["sha256"], harness_before["sha256"])
        self.assertIn(harness_before["sha256"][:12], text)
        self.assertEqual(hashlib.sha256((self.vault / "out.json").read_bytes()).hexdigest(), after["sha256"])

    def test_sessions_newest_bind_first_with_cap(self):
        many = {"sessions": [{"id": "kiro:n%02d" % i, "workspace": "/w/a", "project": "a", "task": None,
                              "calls": [], "issues": []} for i in range(11)], "issues": []}
        self.harness(many, 0)
        _, text = self.frame()
        sessions = text.split("\nSESSIONS", 1)[1]
        shown = [line.split()[1] for line in sessions.splitlines() if line.startswith("- kiro:")]
        self.assertEqual(shown, ["kiro:n%02d" % i for i in range(10, 2, -1)])  # reverse output order, 8 rows
        self.assertIn(": 11 bound in harness", sessions)
        self.assertIn("... 3 more not shown (use --sessions all or --json)", sessions)
        self.assertIn("order       newest bind first = reverse harness output order", sessions)
        self.assertNotIn("more not shown", self.frame(sessions_cap=None)[1])
        self.assertEqual(self.frame(sessions_cap=None)[1].count("\n- kiro:n"), 11)
        _, two = self.frame(sessions_cap=2)
        self.assertEqual([l.split()[1] for l in two.splitlines() if l.startswith("- kiro:")], ["kiro:n10", "kiro:n09"])
        self.assertIn("... 9 more not shown", two)
        stream = io.StringIO()
        view.watch(self.config, self.state, once=True, stream=stream, clock=lambda: NOW, as_json=True, sessions_cap=2)
        data = json.loads(stream.getvalue())
        self.assertEqual([s["line"].split()[1] for s in data["sessions"]], ["kiro:n%02d" % i for i in range(10, -1, -1)])
        self.assertTrue(data["session_order"].startswith("newest bind first"))
        for bad in ("0", "-1", "x"):
            result = subprocess.run([sys.executable, "-m", "scheduler", "--config", str(self.config), "--state",
                                     str(self.state), "watch", "--once", "--sessions", bad],
                                    cwd=REPO, env=clean_env(), capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, bad)
            self.assertIn("--sessions must be a positive integer or all", result.stderr)
        result = subprocess.run([sys.executable, "-m", "scheduler", "--config", str(self.config), "--state",
                                 str(self.state), "watch", "--once", "--sessions", "all"],
                                cwd=REPO, env=clean_env(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("\n- kiro:n"), 11)
