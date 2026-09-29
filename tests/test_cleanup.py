"""Accepted Orca worker terminals are closed only when the exact owned session is proven."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

import yaml

from scheduler import adapters
from scheduler.runtime import Scheduler
from scheduler.worker import atomic_json


class FakeOrca:
    """Minimal model of the Orca terminal CLI: runtime-issued handles over PTY incarnations."""

    def __init__(self):
        self.runtime = "runtime-1"
        self.terminals = {}
        self.calls = []
        self.close_reply = None  # override: a dict body, or an exception to raise
        self.after_close = None  # hook run after a successful close (e.g. simulate a crash)

    def body(self, terminal):
        return {"ok": True, "result": {"terminal": dict(terminal)}, "_meta": {"runtimeId": self.runtime}}

    def run(self, argv, **kwargs):
        verb = argv[2]
        self.calls.append(verb)
        args = dict(zip(argv[3::2], argv[4::2]))
        if verb == "create":
            handle = "term_" + uuid.uuid4().hex
            self.terminals[handle] = {"handle": handle, "ptyId": "wt@@" + uuid.uuid4().hex[:8],
                                      "incarnationId": str(uuid.uuid4()), "worktreeId": "repo::" + args["--worktree"],
                                      "title": args["--title"], "connected": True, "lastOutputAt": 1}
            return self.reply(self.body(self.terminals[handle]))
        terminal = self.terminals.get(args.get("--terminal"))
        if terminal is None:
            return self.reply({"ok": False, "error": {"code": "terminal_handle_stale"}, "_meta": {"runtimeId": self.runtime}}, 1)
        if verb == "show":
            # Volatile fields change constantly and must not affect ownership.
            terminal["title"] = "/usr/bin/python"
            terminal["lastOutputAt"] += 1
            return self.reply(self.body(terminal))
        if verb == "close":
            if isinstance(self.close_reply, BaseException):
                raise self.close_reply
            if self.close_reply is not None:
                return self.reply(self.close_reply, 0 if self.close_reply.get("ok") else 1)
            terminal.update(connected=False, exitCause={"kind": "operator_close"})
            if self.after_close:
                self.after_close()
            close = {"handle": terminal["handle"], "tabId": "tab", "ptyKilled": True}
            return self.reply({"ok": True, "result": {"close": close}, "_meta": {"runtimeId": self.runtime}})
        raise AssertionError("unexpected orca verb " + verb)

    @staticmethod
    def reply(body, code=0):
        return subprocess.CompletedProcess([], code, json.dumps(body), "")


class CleanupTest(unittest.TestCase):
    def setUp(self):
        # A worker environment must not leak into coordinator fixtures.
        env = patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith("SCHEDULER_")}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "a" / "tasks").mkdir(parents=True)
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps({"adapter": "orca", "command": [sys.executable, "-c", "pass"],
            "projects": [{"id": "a", "repo": str(self.root / "a"), "tasks": str(self.root / "a" / "tasks")}]}))
        self.orca = FakeOrca()
        run = patch("scheduler.adapters.subprocess.run", side_effect=self.orca.run)
        run.start()
        self.addCleanup(run.stop)
        self.runner = Scheduler(self.config, self.root / "state")
        self.addCleanup(lambda: self.runner.close())

    def task(self, status="ready", evidence=None):
        meta = dict(type="task", id="one", project_id="a", status=status, evidence=evidence or [])
        (self.root / "a" / "tasks" / "one.md").write_text("---\n" + yaml.safe_dump(meta) + "---\n\n# Goal\nFixture.\n")

    def restart(self):
        self.runner.close()
        self.runner = Scheduler(self.config, self.root / "state")

    def launch(self):
        """Launch through the real Orca adapter, take over and submit completion, then exit 0."""
        self.task()
        result = self.runner.tick()
        self.assertEqual(result["state"], "running")
        ident = result["attempt"]
        bus = self.runner.mailbox
        target = ("a/one", ident, "worker:" + ident)
        claim = bus.claim(*target, bus.inbox(*target)["revision"])["message"]
        bus.processed(claim["id"], *target, claim["revision"], claim["token"], "applied", dict(claim["payload"]["expect"]))
        bus.ack(claim["id"], *target, claim["revision"], claim["token"])
        inbox = bus.inbox(*target)
        bus.complete("done-" + ident, *target, inbox["revision"], inbox["inbox_seq"], {"fixture": True})
        return ident

    def exit(self, ident, code=0):
        atomic_json(self.folder(ident) / "exited.json", {"attempt": ident, "code": code})

    def folder(self, ident):
        return self.root / "state" / "attempts" / ident

    def accept(self):
        self.task(status="done", evidence=["verified.json"])
        return self.runner.tick()

    def cleanup_row(self, ident):
        rows = [r for r in self.runner.status()["cleanups"] if r["attempt"] == ident]
        return rows[0] if rows else None

    def handle(self, ident):
        return self.runner.store.attempts()[0].handle

    def test_terminal_kept_until_exit_and_acceptance(self):
        ident = self.launch()
        record = json.loads((self.folder(ident) / "terminal.json").read_text())
        self.assertEqual(set(record["identity"]), set(adapters.IDENTITY_FIELDS))
        self.assertEqual(record["identity"]["runtimeId"], "runtime-1")
        # Declared done while the worker still runs: not accepted, terminal untouched.
        self.task(status="done", evidence=["verified.json"])
        self.assertEqual(self.runner.tick()["state"], "running")
        self.task()
        self.exit(ident)
        self.assertEqual(self.runner.tick()["state"], "awaiting_acceptance")
        self.assertEqual(self.runner.tick()["state"], "awaiting_acceptance")
        self.assertEqual(self.orca.calls, ["create"])
        self.assertIsNone(self.cleanup_row(ident))

    def test_exact_terminal_closed_once_after_acceptance(self):
        ident = self.launch()
        other = self.orca.run(["orca", "terminal", "create", "--worktree", "path:x", "--title", "user", "--json"])
        self.exit(ident)
        self.assertEqual(self.accept()["state"], "idle")
        attempt = self.runner.store.attempts()[0]
        self.assertEqual(attempt.state, "accepted")
        self.assertEqual(self.orca.calls, ["create", "create", "show", "close"])
        self.assertIn("exitCause", self.orca.terminals[attempt.handle])
        untouched = json.loads(other.stdout)["result"]["terminal"]["handle"]
        self.assertNotIn("exitCause", self.orca.terminals[untouched])
        row = self.cleanup_row(ident)
        self.assertEqual((row["state"], row["tries"]), ("closed", 1))
        kinds = [(e["kind"], e["disposition"]) for e in self.runner.status()["events"] if e["attempt"] == ident]
        self.assertIn(("accepted", "applied"), kinds)
        self.assertIn(("cleanup", "applied"), kinds)
        # Repeated ticks and a restart on the same ledger never close again.
        self.runner.tick()
        self.restart()
        self.runner.tick()
        self.assertEqual(self.orca.calls.count("close"), 1)

    def test_crash_after_close_reverifies_instead_of_closing_twice(self):
        ident = self.launch()
        self.exit(ident)
        def crash():
            raise KeyboardInterrupt
        self.orca.after_close = crash
        with self.assertRaises(KeyboardInterrupt):
            self.accept()
        self.assertEqual(self.cleanup_row(ident)["state"], "closing")
        self.assertEqual(self.runner.store.attempts()[0].state, "accepted")
        self.orca.after_close = None
        self.restart()
        self.runner.tick()
        row = self.cleanup_row(ident)
        self.assertEqual((row["state"], row["tries"]), ("already_closed", 2))
        self.assertEqual(self.orca.calls.count("close"), 1)

    def test_close_failure_is_retried_after_reverification_then_failed(self):
        ident = self.launch()
        self.exit(ident)
        self.orca.close_reply = {"ok": False, "error": {"code": "internal"}}
        self.accept()
        row = self.cleanup_row(ident)
        self.assertEqual((row["state"], row["detail"]["error"]), ("unconfirmed", "internal"))
        self.orca.close_reply = subprocess.TimeoutExpired("orca", 30)
        self.runner.tick()
        self.assertEqual(self.cleanup_row(ident)["state"], "unconfirmed")
        self.orca.close_reply = {"ok": False}
        self.runner.tick()
        self.assertEqual(self.cleanup_row(ident)["state"], "failed")
        self.runner.tick()
        # Every close was preceded by a fresh ownership check; nothing reported success.
        self.assertEqual(self.orca.calls[1:], ["show", "close"] * 3)
        dispositions = [e["disposition"] for e in self.runner.status()["events"] if e["kind"] == "cleanup"]
        self.assertEqual(dispositions, ["unconfirmed", "unconfirmed", "failed"])
        self.assertNotIn("exitCause", self.orca.terminals[self.handle(ident)])

    def test_outer_ok_without_killed_pty_is_not_success(self):
        replies = [{"handle": None, "ptyKilled": True}, {"ptyKilled": False},
                   {"ptyKilled": True, "ptyStopVerdict": "unverifiable"}]
        ident = self.launch()
        handle = self.handle(ident)
        self.exit(ident)
        for index, close in enumerate(replies):
            close.setdefault("handle", handle)
            self.orca.close_reply = {"ok": True, "result": {"close": close}}
            self.accept() if index == 0 else self.runner.tick()
            self.assertIn(self.cleanup_row(ident)["state"], ("unconfirmed", "failed"))
        self.assertEqual(self.cleanup_row(ident)["state"], "failed")
        states = [json.loads(e["payload"])["state"] for e in self.runner.status()["events"] if e["kind"] == "cleanup"]
        self.assertNotIn("closed", states)

    def test_transient_failure_then_success_targets_the_same_terminal(self):
        ident = self.launch()
        self.exit(ident)
        self.orca.close_reply = subprocess.TimeoutExpired("orca", 30)
        self.accept()
        self.orca.close_reply = None
        self.runner.tick()
        self.assertEqual(self.cleanup_row(ident)["state"], "closed")
        self.assertIn("exitCause", self.orca.terminals[self.handle(ident)])

    def test_replaced_handle_or_runtime_is_never_closed(self):
        for change in ("incarnationId", "ptyId", "runtime", "stale"):
            with self.subTest(change=change):
                self.fresh_ledger()
                ident = self.launch()
                handle = self.handle(ident)
                self.exit(ident)
                if change == "runtime":
                    self.orca.runtime = "runtime-2"
                elif change == "stale":
                    del self.orca.terminals[handle]
                else:
                    self.orca.terminals[handle][change] = "reused-" + change
                self.accept()
                row = self.cleanup_row(ident)
                self.assertEqual(row["state"], "withheld")
                self.assertNotIn("close", self.orca.calls)
                self.runner.tick()
                self.assertEqual(self.orca.calls.count("show"), 1)

    def fresh_ledger(self):
        """Fresh ledger and fake runtime for a subtest."""
        self.runner.close()
        shutil.rmtree(self.root / "state", ignore_errors=True)
        self.orca.terminals.clear()
        self.orca.calls.clear()
        self.orca.runtime = "runtime-1"
        self.runner = Scheduler(self.config, self.root / "state")

    def test_legacy_or_partial_identity_is_withheld_without_orca_calls(self):
        for record in (None, {"handle": "H", "identity": {"handle": "H", "title": "x"}}, "not json"):
            with self.subTest(record=record):
                self.fresh_ledger()
                ident = self.launch()
                path = self.folder(ident) / "terminal.json"
                if record is None:
                    path.unlink()
                elif isinstance(record, str):
                    path.write_text(record)
                else:
                    path.write_text(json.dumps(dict(record, handle=self.handle(ident))))
                self.exit(ident)
                self.accept()
                self.assertEqual(self.cleanup_row(ident)["state"], "withheld")
                self.assertEqual(self.orca.calls, ["create"])

    def test_local_adapter_sends_no_signal(self):
        self.config.write_text(json.dumps(dict(json.loads(self.config.read_text()), adapter="local")))
        self.fresh_ledger()
        with patch("scheduler.adapters.subprocess.Popen") as popen, patch("os.kill") as kill:
            popen.return_value.pid = 424242
            popen.return_value.wait.return_value = 0
            ident = self.launch()
            self.exit(ident)
            self.accept()
        kill.assert_not_called()
        row = self.cleanup_row(ident)
        self.assertEqual(row["state"], "not_applicable")
        self.assertEqual(self.orca.calls, [])


if __name__ == "__main__":
    unittest.main()
