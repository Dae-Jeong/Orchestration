"""watch: harness-recorded `terminal` links a session to a live Orca terminal only on an exact `orca:<handle>` match."""
import io
import json

from scheduler import watch as view
from test_watch import NOW
import test_watch_phase2 as phase2
from test_watch_phase2 import FREE, LIVE_A, OTHER


def session(ident, terminal=None, source=None, **extra):
    row = {"id": ident, "workspace": "/w/a", "project": "a", "task": None, "calls": [], "issues": []}
    if terminal is not None or source is not None:
        row.update(terminal=terminal, terminal_source=source)
    return row | extra


class TerminalLink(phase2.Phase2):
    """Reuses the phase-2 fixture (fake Orca/harness); its own tests run once, in test_watch_phase2."""
    locals().update({n: None for n in dir(phase2.Phase2) if n.startswith("test_")})

    def sessions(self, *rows):
        self.harness({"sessions": list(rows), "issues": []}, 0)

    def data(self, **kw):
        stream = io.StringIO()
        view.watch(self.config, self.state, once=True, stream=stream, clock=lambda: NOW, as_json=True, **kw)
        return json.loads(stream.getvalue())

    @staticmethod
    def fields(data, key):
        return next(s for s in data["sessions"] if s["key"] == key)["fields"]

    @staticmethod
    def unknown(data):
        return [t["line"].split()[1] for t in data["terminals"] or []]

    def test_exact_match_links_under_session_and_leaves_unknown(self):
        self.sessions(session("kiro:s-t", "orca:" + FREE, "env"), session("codex:s-x", "orca:" + OTHER, "explicit"))
        data = self.data(projects=["a"])
        fields = self.fields(data, "kiro:s-t")
        self.assertIn(["terminal", FREE], fields)
        self.assertIn(["worktree", "%s (terminal list)" % (self.root / "a")], fields)
        self.assertIn(["orca", "agent=unknown connected=True orphaned=False last output %s (terminal list)"
                       % view.when(NOW - 5)], fields)
        self.assertIn(["dispatch", "ctx_1 task task_1 worker=ready outcome=in_progress "
                       "liveness=unverifiable/missing_status (worker-list)"], fields)
        self.assertIn(["link", "harness terminal (env)"], fields)
        self.assertIn(["link", "harness terminal (explicit)"], self.fields(data, "codex:s-x"))
        self.assertIn(["terminal", OTHER], self.fields(data, "codex:s-x"))  # linked even outside project a's worktrees
        self.assertNotIn(FREE, self.unknown(data))
        self.assertNotIn(OTHER, self.unknown(data))
        self.assertIn(LIVE_A, self.unknown(data))  # its ref pairing names kiro:s-a, which is not bound here
        _, text = self.frame(projects=["a"])
        block = text.split("\n- kiro:s-t", 1)[1].split("\n- ", 1)[0]
        self.assertIn("terminal    %s\n" % FREE, block)
        self.assertIn("link        harness terminal (env)", block)
        self.assertNotIn("- %s terminal, session unknown" % FREE, text)

    def test_mismatch_or_absent_stays_unknown(self):
        near = ["orca:" + FREE + "x", FREE, "orca:" + FREE.upper(), "kiro:" + FREE, "orca: " + FREE, "orca:" + FREE[:-1]]
        self.sessions(*[session("kiro:m%d" % i, value, "explicit") for i, value in enumerate(near)],
                      session("kiro:none"), session("kiro:null") | {"terminal": None, "terminal_source": None})
        data = self.data(projects=["a"])
        self.assertIn(FREE, self.unknown(data))
        for i, value in enumerate(near):
            fields = self.fields(data, "kiro:m%d" % i)
            self.assertIn(["terminal", "%s recorded by harness (explicit); not in live orca terminal list" % value], fields)
            self.assertFalse([f for f in fields if f[0] == "link"], value)
        for key in ("kiro:none", "kiro:null"):
            self.assertFalse([f for f in self.fields(data, key) if f[0] in ("terminal", "link")], key)

    def test_orca_unavailable_shows_recorded_terminal_unverified(self):
        self.sessions(session("kiro:s-t", "orca:" + FREE, "env"), session("kiro:plain"))
        self.orca_files(status=json.dumps({"ok": False, "error": {"code": "runtime_unavailable"}}))
        data = self.data()
        self.assertIsNone(data["terminals"])
        self.assertIn(["terminal", "orca:%s recorded by harness (env); not verified live: Orca unavailable" % FREE],
                      self.fields(data, "kiro:s-t"))
        self.assertFalse([f for f in self.fields(data, "kiro:s-t") if f[0] == "link"])
        self.assertFalse([f for f in self.fields(data, "kiro:plain") if f[0] == "terminal"])
        config = json.loads(self.config.read_text())
        self.config.write_text(json.dumps(dict(config, orca_command=str(self.root / "missing"))))
        _, text = self.frame()
        self.assertIn("terminal    orca:%s recorded by harness (env); not verified live: Orca unavailable" % FREE, text)

    def test_harness_link_keeps_ref_pairing_as_secondary_label(self):
        self.sessions(session("kiro:s-a", "orca:" + LIVE_A, "explicit"))
        fields = self.fields(self.data(projects=["a"]), "kiro:s-a")
        self.assertIn(["link", "harness terminal (explicit)"], fields)
        self.assertIn(["ref pairing", "kiro:s-a (ref ev-exec identity)"], fields)
        self.assertNotIn(["terminal", "%s via (ref ev-exec identity)" % LIVE_A], fields)
        self.assertEqual([f for f in fields if f[0] == "terminal"], [["terminal", LIVE_A]])

    def test_older_harness_output_unchanged(self):
        base = [session("kiro:s-a", workspace=str(self.root / "a")), session("codex:s-c", workspace=str(self.root / "a"))]
        self.sessions(*base)
        old = self.data(projects=["a"])
        self.sessions(*[s | {"terminal": None, "terminal_source": None} for s in base])
        nulls = self.data(projects=["a"])
        for data in (old, nulls):
            data["sources"].pop("harness")  # the only difference: sha256 of the harness output
        self.assertEqual(old, nulls)
        self.assertIn(["terminal", "%s via (ref ev-exec identity)" % LIVE_A], self.fields(old, "kiro:s-a"))
        self.assertFalse([f for f in self.fields(old, "kiro:s-a") if f[0] in ("link", "ref pairing")])
        self.assertIn(FREE, self.unknown(old))
        self.assertNotIn(LIVE_A, self.unknown(old))
