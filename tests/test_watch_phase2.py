"""watch phase 2: stat-only session-file activity and read-only Orca terminals/dispatches."""
import builtins
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from scheduler import watch as view
from test_watch_overview import NOW, OverviewFixture

# Fake `orca`: answers from <verb>.json next to it (missing file -> non-JSON), logs argv.
FAKE_ORCA = '''import json, pathlib, sys
here = pathlib.Path(__file__).parent
with (here / "orca-args.log").open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
name = "-".join(a for a in sys.argv[1:] if not a.startswith("--")) + ".json"
path = here / name
sys.stdout.write(path.read_text() if path.exists() else "not json")
'''
LIVE_A = "term_live-a"  # linked to kiro:s-a by a ref execution identity
FREE = "term_free"      # in project a's worktree, no session evidence, has a dispatch
OTHER = "term_other"    # another worktree: shown only without --project


def ok(result):
    return json.dumps({"ok": True, "result": result})


class Phase2(OverviewFixture):
    def setUp(self):
        super().setUp()
        self.bin = self.root / "orca-bin"
        self.bin.mkdir()
        orca = self.bin / "orca"
        orca.write_text("#!%s\n%s" % (sys.executable, FAKE_ORCA))
        orca.chmod(0o755)
        self.home = self.root / "home"
        config = json.loads(self.config.read_text())
        config.update(orca_command=str(orca), session_file_roots={a: str(self.home / a) for a in ("kiro", "codex", "claude")})
        self.config.write_text(json.dumps(config))
        self.harness({"sessions": [
            {"id": "kiro:s-a", "workspace": str(self.root / "a"), "project": "a", "task": "one", "calls": [], "issues": []},
            {"id": "codex:s-c", "workspace": str(self.root / "a"), "project": "a", "task": None, "calls": [], "issues": []},
            {"id": "claude:s-d", "workspace": str(self.root / "a"), "project": "a", "task": None, "calls": [], "issues": []},
            {"id": "kiro:s-none", "workspace": str(self.root / "a"), "project": "a", "task": None, "calls": [], "issues": []}],
            "issues": []})
        self.refs.publish("ev-exec", "question.opened", "a/one", str(self.root / "a" / "tasks" / "one.md"), "q1",
                          "kiro:s-a", "orca:" + LIVE_A, "orca:term-main", "orca:term_gone")
        attempt_handle = self.runner.store.attempt(self.attempt).handle
        self.orca_files(status=ok({"runtime": {"state": "ready", "reachable": True}}),
                        terminals=[self.terminal(LIVE_A, self.root / "a", "kiro"), self.terminal(FREE, self.root / "a"),
                                   self.terminal(OTHER, self.root / "elsewhere", "codex"),
                                   self.terminal(attempt_handle, self.root / "elsewhere")])
        self.files = {"kiro": self.home / "kiro/sessions/cli/s-a.jsonl",
                      "codex": self.home / "codex/sessions/2026/09/30/rollout-2026-09-30T01-00-00-s-c.jsonl",
                      "claude": self.home / "claude/projects/-w-a/s-d.jsonl"}
        for i, path in enumerate(self.files.values()):
            path.parent.mkdir(parents=True)
            path.write_text("SECRET transcript\n")
            os.utime(path, (NOW - 100 * (i + 1), NOW - 100 * (i + 1)))
            path.chmod(0)  # unreadable: any content read would fail
            self.addCleanup(path.chmod, 0o600)

    @staticmethod
    def terminal(handle, worktree, agent=None):
        return dict(handle=handle, worktreePath=str(worktree), connected=True, orphaned=False,
                    lastOutputAt=(NOW - 5) * 1000, preview="PRIVATE OUTPUT", **({"agentIdentity": agent} if agent else {}))

    def orca_files(self, status=None, terminals=None, workers=True):
        if status is not None:
            (self.bin / "status.json").write_text(status)
        if terminals is not None:
            (self.bin / "terminal-list.json").write_text(ok({"terminals": terminals, "truncated": False}))
        if workers:
            (self.bin / "orchestration-worker-list.json").write_text(ok({"scope": {"source": "all"}, "workers": [
                {"dispatchId": "ctx_1", "taskId": "task_1", "workerState": "ready", "agentTerminalHandle": FREE,
                 "projection": {"outcome": "in_progress", "liveness": {"verdict": "unverifiable", "reason": "missing_status"}}}]}))
        else:
            (self.bin / "orchestration-worker-list.json").unlink(missing_ok=True)

    def test_sessions_get_file_activity_and_evidenced_terminal(self):
        _, text = self.frame(projects=["a"], sessions_cap=None)
        sessions = text.split("\nSESSIONS", 1)[1].split("\nTERMINALS", 1)[0]
        block = sessions.split("- kiro:s-a", 1)[1].split("\n- ", 1)[0]
        self.assertIn("last activity %s (session file mtime: %s)" % (view.when(NOW - 100), self.files["kiro"]), block)
        self.assertIn("terminal    %s via (ref ev-exec identity)" % LIVE_A, block)
        self.assertIn("last activity %s (session file mtime" % view.when(NOW - 200), sessions.split("- codex:s-c", 1)[1])
        self.assertIn("last activity %s (session file mtime" % view.when(NOW - 300), sessions.split("- claude:s-d", 1)[1])
        self.assertIn("last activity unavailable (no session files for this id)", sessions.split("- kiro:s-none", 1)[1])
        self.assertNotIn("SECRET", text)
        self.assertNotIn("PRIVATE OUTPUT", text)

    def test_unlinked_filtered_and_stale_terminals(self):
        _, text = self.frame(projects=["a"])
        terminals = text.split("\nTERMINALS, SESSION UNKNOWN: ", 1)[1]
        self.assertIn("- %s terminal, session unknown" % FREE, terminals)
        self.assertIn("dispatch    ctx_1 task task_1 worker=ready outcome=in_progress liveness=unverifiable/missing_status (worker-list)",
                      terminals)
        self.assertIn("agent=unknown connected=True orphaned=False last output %s (terminal list)" % view.when(NOW - 5), terminals)
        self.assertNotIn(LIVE_A + " terminal, session unknown", terminals)  # linked, so shown under its session
        self.assertNotIn(OTHER, text)  # outside project a's worktrees and no evidence
        attempt_handle = self.runner.store.attempt(self.attempt).handle
        self.assertIn("- %s terminal, session unknown" % attempt_handle, terminals)  # scheduler terminal.json evidence
        self.assertIn("attempt     %s running (terminal.json identity)" % self.attempt[:8], terminals)
        problems = text.split("\nPROBLEMS", 1)[1].split("\nPROGRESS", 1)[0]
        self.assertIn("- [orca] ev-exec recipient terminal not live", problems)
        self.assertIn("terminal    term_gone", problems)
        self.assertIn("orca        ok: 4 live terminals; dispatches 1 (scope all)", text)
        self.assertIn("- %s terminal, session unknown" % OTHER, self.frame()[1])  # no filter: every live terminal

    def test_orca_absent_malformed_or_not_ready_never_blocks(self):
        cases = [("not json", "orca status"), (ok({"runtime": {"state": "starting", "reachable": False}}), "runtime not ready (starting)"),
                 (json.dumps({"ok": False, "error": {"code": "runtime_unavailable"}}), "runtime_unavailable")]
        for status, reason in cases:
            with self.subTest(reason=reason):
                self.orca_files(status=status)
                code, text = self.frame(projects=["a"])
                self.assertEqual(code, 0)
                self.assertIn("orca        unavailable: ", text)
                self.assertIn(reason, text)
                self.assertIn("TERMINALS, SESSION UNKNOWN: unavailable (see SOURCES orca)", text)
                self.assertIn("- [ref] ev-q", text)
                self.assertIn("last activity %s" % view.when(NOW - 100), text)
        self.orca_files(status=ok({"runtime": {"state": "ready", "reachable": True}}))
        (self.bin / "terminal-list.json").write_text(json.dumps({"ok": False, "error": {"code": "terminal_handle_stale"}}))
        self.assertIn("unavailable: orca terminal list: terminal_handle_stale", self.frame()[1])
        self.orca_files(terminals=[self.terminal(FREE, self.root / "a")], workers=False)
        _, text = self.frame(projects=["a"])
        self.assertIn("orca        ok: 1 live terminals; dispatches unavailable: orca orchestration worker-list", text)
        self.assertIn("- %s terminal, session unknown" % FREE, text)
        config = json.loads(self.config.read_text())
        self.config.write_text(json.dumps(dict(config, orca_command=str(self.root / "missing"))))
        self.assertIn("orca        unavailable: orca not found", self.frame()[1])

    def test_only_read_only_orca_verbs_and_stat_only_session_files(self):
        guarded = {str(p) for p in self.files.values()}
        real_open, real_os_open = builtins.open, os.open

        def no_read(file, *a, **kw):
            if str(file) in guarded:
                raise AssertionError("session file opened: %s" % file)
            return real_open(file, *a, **kw)

        def no_os_open(path, *a, **kw):
            if str(path) in guarded:
                raise AssertionError("session file opened: %s" % path)
            return real_os_open(path, *a, **kw)

        with patch("builtins.open", no_read), patch("io.open", no_read), patch("os.open", no_os_open):
            stream = io.StringIO()
            self.assertEqual(view.watch(self.config, self.state, once=True, stream=stream, clock=lambda: NOW,
                                        projects=["a"], as_json=True), 0)
        data = json.loads(stream.getvalue())
        kiro = next(s for s in data["sessions"] if s["key"] == "kiro:s-a")
        self.assertIn(["last activity", "%s (session file mtime: %s)" % (view.when(NOW - 100), self.files["kiro"])], kiro["fields"])
        self.assertIn(["terminal", "%s via (ref ev-exec identity)" % LIVE_A], kiro["fields"])
        self.assertEqual([t["line"] for t in data["terminals"]][:1], ["- %s terminal, session unknown" % FREE])
        verbs = {tuple(json.loads(line)) for line in (self.bin / "orca-args.log").read_text().splitlines()}
        self.assertEqual(verbs, {("status", "--json"), ("terminal", "list", "--json"),
                                 ("orchestration", "worker-list", "--json")})
        for path in self.files.values():
            self.assertEqual(path.stat().st_mode & 0o777, 0)  # still unreadable, untouched
