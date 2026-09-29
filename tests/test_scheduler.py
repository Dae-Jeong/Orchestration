import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scheduler import adapters
from scheduler.model import Catalog, Invalid
from scheduler.runtime import Scheduler
from scheduler.store import Busy, Store, schema_columns
from scheduler.worker import atomic_json


def competing_tick(config, state, queue):
    runner = Scheduler(config, state)
    try:
        queue.put(runner.tick())
    except Busy:
        queue.put({"state": "busy"})
    finally:
        runner.close()


class SchedulerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for project in ("a", "b"):
            (self.root / project / "tasks").mkdir(parents=True)
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps({"command": [sys.executable, "-c", "print('executed')"],
            "projects": [{"id": p, "repo": str(self.root / p), "tasks": str(self.root / p / "tasks")}
                         for p in ("a", "b")]}))
        self.runner = Scheduler(self.config, self.root / "state")

    def tearDown(self):
        self.runner.close()
        self.temp.cleanup()

    def task(self, key="a/one", priority=10, deps=None, status="ready", evidence=None, **extra):
        p, ident = key.split("/")
        meta = dict(type="task", id=ident, project_id=p, status=status, priority=priority,
                    depends_on=deps or [], evidence=evidence or [], **extra)
        import yaml
        path = self.root / p / "tasks" / (ident + ".md")
        path.write_text("---\n" + yaml.safe_dump(meta) + "---\n\n# Goal\nFixture.\n")
        return path

    def fake_launch(self):
        return patch("scheduler.adapters.launch", return_value="fixture-handle")

    def finish(self, result, code=0):
        self.runner.event(result["attempt"] + ":exit-fixture", result["attempt"], "exited", {"code": code})

    def take_over(self, attempt, task=None):
        """Fixture worker reads the assignment and records take-over before other messages."""
        bus = self.runner.mailbox
        task = task or self.runner.store.db.execute('SELECT task FROM attempts WHERE id=?', (attempt,)).fetchone()[0]
        target = (task, attempt, 'worker:' + attempt)
        revision = bus.inbox(*target)['revision']
        claim = bus.claim(*target, revision)['message']
        report = dict(claim['payload']['expect'], observed='fixture read Task')
        bus.processed(claim['id'], *target, revision, claim['token'], 'applied', report)
        return bus.ack(claim['id'], *target, revision, claim['token'])

    def submit_worker_result(self, result):
        target = (result['task'], result['attempt'], 'worker:' + result['attempt'])
        if self.runner.mailbox.messages.blockers(result['attempt']):
            self.take_over(result['attempt'], result['task'])
        inbox = self.runner.mailbox.inbox(*target)
        self.runner.mailbox.complete('complete-' + result['attempt'], *target, inbox['revision'], inbox['inbox_seq'], {'fixture': 'verified'})

    def approve(self, order):
        result = self.runner.tick()
        self.assertEqual(result["state"], "needs_planner")
        self.runner.approve_plan({"revision": result["revision"], "order": order})

    def test_two_projects_dependency_requires_acceptance(self):
        self.task("a/one", priority=20)
        self.task("b/two", priority=10, deps=["a/one"])
        self.approve(["a/one", "b/two"])
        with self.fake_launch():
            first = self.runner.tick()
            self.assertEqual(first["task"], "a/one")
            self.submit_worker_result(first)
            self.finish(first)
            self.assertEqual(self.runner.tick()["state"], "awaiting_acceptance")
            self.task("a/one", priority=20, status="done")
            self.assertEqual(self.runner.tick()["state"], "awaiting_acceptance")
            self.task("a/one", priority=20, status="done", evidence=["result.json"])
            second = self.runner.tick()
            self.assertEqual(second["task"], "b/two")
        self.assertEqual(len(self.runner.status()["plans"]), 1)
        self.assertEqual(self.runner.status()["projects"]["b"]["order"], ["b/two"])

    def test_status_serializes_attempt_records_in_ledger_column_order(self):
        self.task("a/one")
        with self.fake_launch():
            result = self.runner.tick()
        row = dict(self.runner.store.db.execute("SELECT * FROM attempts").fetchone())
        (shown,) = self.runner.status()["attempts"]
        self.assertEqual(list(shown), schema_columns()["attempts"])
        self.assertEqual(shown, row)
        self.assertEqual(self.runner.store.attempt(result["attempt"]), self.runner.store.active())

    def test_duplicate_delayed_and_stale_events(self):
        self.task()
        with self.fake_launch():
            first = self.runner.tick()
        self.finish(first)
        self.runner.event("late-start", first["attempt"], "started", {})
        self.finish(first)
        self.assertEqual(self.runner.store.active().state, "awaiting_acceptance")
        self.runner.resolve(first["attempt"], "retry", "fixture child stopped", True)
        with self.fake_launch():
            second = self.runner.tick()
        self.runner.event("stale-exit", first["attempt"], "exited", {"code": 0})
        self.assertEqual(self.runner.store.active().id, second["attempt"])
        dispositions = {e["id"]: e["disposition"] for e in self.runner.status()["events"]}
        self.assertEqual(dispositions["external:late-start"], "stale")
        self.assertEqual(dispositions["external:stale-exit"], "stale")

    def test_unknown_launch_restart_never_falls_back(self):
        self.task()
        with patch("scheduler.adapters.choose", return_value="orca"), patch("scheduler.adapters.launch", side_effect=TimeoutError("response lost")) as launch:
            result = self.runner.tick()
            self.assertEqual(result["state"], "unknown")
            self.runner.close()
            self.runner = Scheduler(self.config, self.root / "state")
            self.assertEqual(self.runner.tick()["state"], "unknown")
            self.assertEqual(launch.call_count, 1)
            self.assertEqual(self.runner.store.active().adapter, "orca")

    def test_crash_after_intent_no_second_launch(self):
        self.task()
        with patch("scheduler.adapters.launch", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.runner.tick()
        with self.fake_launch() as launch:
            self.assertEqual(self.runner.tick()["state"], "launching")
            launch.assert_not_called()

    def test_exit_receipt_recovers_ambiguous_launch(self):
        self.task()
        with patch("scheduler.adapters.launch", side_effect=TimeoutError):
            result = self.runner.tick()
        folder = self.root / "state" / "attempts" / result["attempt"]
        self.submit_worker_result(result)
        atomic_json(folder / "exited.json", {"attempt": result["attempt"], "code": 0})
        self.assertEqual(self.runner.tick()["state"], "awaiting_acceptance")
        self.task(status="done", evidence=["verified-result"])
        self.assertEqual(self.runner.tick()["state"], "idle")
        self.assertEqual(self.runner.store.attempts()[0].state, "accepted")

    def test_nonzero_exit_no_automatic_retry(self):
        self.task()
        with self.fake_launch() as launch:
            result = self.runner.tick()
            self.finish(result, code=1)
            self.assertEqual(self.runner.tick()["state"], "idle")
            self.assertEqual(launch.call_count, 1)
        with self.assertRaises(Invalid):
            self.runner.resolve(result["attempt"], "retry", "", False)

    def test_prelaunch_os_failure_releases_slot(self):
        self.task()
        with patch("scheduler.adapters.launch", side_effect=adapters.NotLaunched("no executable")):
            self.assertEqual(self.runner.tick()["state"], "failed")
        self.assertIsNone(self.runner.store.active())

    def test_default_metadata_and_scoped_duplicate_ids(self):
        self.task("a/same", priority=20)
        self.task("b/same", priority=10)
        self.assertEqual(set(self.runner.catalog.read()), {"a/same", "b/same"})
        path = self.root / "a/tasks/min.md"
        path.write_text("---\ntype: task\nid: min\n---\nMinimal")
        task = self.runner.catalog.read()["a/min"]
        self.assertEqual((task.status, task.priority, task.depends_on), ("ready", 0, ()))

    def test_invalid_dependency_cycle_project_and_priority(self):
        self.task(deps=["missing"])
        with self.assertRaisesRegex(Invalid, "unknown dependency"):
            self.runner.tick()
        self.task(deps=["two"])
        self.task("a/two", deps=["one"])
        with self.assertRaisesRegex(Invalid, "cycle"):
            self.runner.tick()
        self.task(deps=[])
        self.task("a/two", priority=True)
        with self.assertRaisesRegex(Invalid, "priority"):
            self.runner.tick()
        self.assertEqual(self.runner.store.attempts(), [])

    def test_planner_invalid_scope_revision_dependency(self):
        self.task(priority=0)
        self.task("a/two", priority=0, deps=["one"])
        request = self.runner.tick()
        for response in ({"revision": "stale", "order": ["a/one", "a/two"]},
                         {"revision": request["revision"], "order": ["a/one", "other/task"]},
                         {"revision": request["revision"], "order": ["a/two", "a/one"]},
                         {"revision": request["revision"], "order": ["a/one", "a/one"]}):
            with self.assertRaises(Invalid):
                self.runner.approve_plan(response)
        self.assertEqual(self.runner.store.attempts(), [])

    def test_planner_calls_only_on_conflict_and_invalidating_change(self):
        self.task(priority=0)
        self.task("b/two", priority=0)
        self.runner.catalog.config["planner_command"] = ["fake"]
        def answer(command, request, timeout):
            return {"revision": request["revision"], "order": list(request["tasks"])}
        with patch("scheduler.planner.invoke", side_effect=answer) as invoke, self.fake_launch():
            first = self.runner.tick()
            self.runner.tick()
            self.submit_worker_result(first)
            self.finish(first)
            self.task(status="done", priority=0, evidence=["result"])
            second = self.runner.tick()
            self.assertEqual(invoke.call_count, 1)
            self.finish(second, code=1)
            self.task("b/two", priority=2)
            self.runner.tick()
            self.assertEqual(invoke.call_count, 2)

    def test_independent_ordinary_completion_zero_llm_calls(self):
        self.task(priority=20)
        self.task("b/two", priority=10)
        with patch("scheduler.planner.invoke") as invoke, self.fake_launch():
            first = self.runner.tick()
            self.submit_worker_result(first)
            self.finish(first)
            self.task(status="done", priority=20, evidence=["result"])
            self.assertEqual(self.runner.tick()["task"], "b/two")
            invoke.assert_not_called()

    def test_planner_timeout_is_durable_and_not_retried(self):
        self.task(priority=0)
        self.task("b/two", priority=0)
        self.runner.catalog.config["planner_command"] = ["fake"]
        with patch("scheduler.planner.invoke", side_effect=TimeoutError) as invoke:
            self.runner.tick()
            self.runner.tick()
            self.assertEqual(invoke.call_count, 1)
            self.assertEqual(self.runner.status()["plans"][0]["state"], "rejected")

    def test_task_change_during_planner_rejects_response(self):
        self.task(priority=0)
        self.task("b/two", priority=0)
        self.runner.catalog.config["planner_command"] = ["fake"]
        def answer(command, request, timeout):
            self.task("b/two", priority=100)
            return {"revision": request["revision"], "order": list(request["tasks"])}
        with patch("scheduler.planner.invoke", side_effect=answer):
            self.assertEqual(self.runner.tick()["state"], "needs_planner")
            self.assertIn("changed", self.runner.status()["plans"][0]["detail"])

    def test_interrupted_plan_metadata_keeps_accepted_order(self):
        # The planner reverses the default priority-tie order (a/one first).
        self.task(priority=0)
        self.task("b/two", priority=0)
        self.runner.catalog.config["planner_command"] = ["fake"]
        def answer(command, request, timeout):
            return {"revision": request["revision"], "order": ["b/two", "a/one"]}
        original = Store.set
        def interrupted(store, key, value):
            if key == "order":
                raise sqlite3.OperationalError("database is locked")
            return original(store, key, value)
        with patch("scheduler.planner.invoke", side_effect=answer) as invoke, self.fake_launch():
            with patch.object(Store, "set", interrupted), self.assertRaises(sqlite3.OperationalError):
                self.runner.tick()
            # The accepted plan is durable; the partial scheduling metadata is not.
            self.assertEqual([p["state"] for p in self.runner.status()["plans"]], ["accepted"])
            self.assertIsNone(self.runner.store.get("catalog"))
            self.assertEqual(self.runner.store.attempts(), [])
            result = self.runner.tick()
            self.assertEqual(result["task"], "b/two")
            self.assertEqual(invoke.call_count, 1)
            self.assertEqual(self.runner.store.get("order"), ["b/two", "a/one"])

    def test_related_batch_triggers_replanning(self):
        self.task(status="blocked")
        self.assertEqual(self.runner.tick()["state"], "idle")
        self.task("b/two", priority=5, deps=["a/one"])
        result = self.runner.tick()
        self.assertEqual(result["state"], "needs_planner")
        self.assertEqual(json.loads(self.runner.status()["plans"][0]["request"])["reason"], "related_batch")

    def test_auto_adapter_selected_before_intent(self):
        with patch("scheduler.adapters.orca_ready", return_value=False):
            self.assertEqual(adapters.choose("auto", "orca"), "local")
            self.assertEqual(adapters.choose("orca", "orca"), "orca")
        with patch("scheduler.adapters.orca_ready", return_value=True):
            self.assertEqual(adapters.choose("auto", "orca"), "orca")

    def test_orca_argv_and_receipt(self):
        self.task()
        completed = subprocess.CompletedProcess([], 0, json.dumps({"ok": True, "result": {"terminal": {"handle": "term-test"}}}), "")
        with patch("scheduler.adapters.subprocess.run", return_value=completed) as run:
            result = adapters.launch("orca", self.root / "spec.json", {"repo": str(self.root / "a")}, "orca")
        self.assertEqual(result, "term-test")
        self.assertIn("path:" + str(self.root / "a"), run.call_args.args[0])
        self.assertIn("--command", run.call_args.args[0])

    def test_two_processes_reserve_only_one_slot(self):
        self.task()
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        children = [context.Process(target=competing_tick, args=(str(self.config), str(self.root / "state"), queue)) for _ in range(2)]
        for p in children:
            p.start()
        for p in children:
            p.join(10)
            self.assertEqual(p.exitcode, 0)
        results = [queue.get(timeout=2) for _ in children]
        self.assertTrue(any(r["state"] in ("running", "awaiting_acceptance") for r in results))
        self.assertEqual(len(self.runner.store.attempts()), 1)
        self.wait_receipt(self.runner.store.attempts()[0].id)

    def wait_receipt(self, ident):
        path = self.root / "state/attempts" / ident / "exited.json"
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(path.exists())
        return path

    def test_real_local_worker_restart_collect_and_duplicate_guard(self):
        self.task()
        first = self.runner.tick()
        path = self.wait_receipt(first["attempt"])
        self.runner.close()
        self.runner = Scheduler(self.config, self.root / "state")
        self.assertEqual(self.runner.tick()["state"], "awaiting_acceptance")
        output = (path.parent / "stdout.txt").read_text()
        self.assertEqual(output.strip(), "executed")
        before = path.read_bytes()
        subprocess.run([sys.executable, "-m", "scheduler.worker", str(path.parent / "spec.json")], check=True)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual((path.parent / "stdout.txt").read_text(), output)

    def test_cli_persistent_loop_and_graceful_stop(self):
        self.task()
        command = [sys.executable, "-m", "scheduler", "--config", str(self.config), "--state", str(self.root / "state")]
        proc = subprocess.Popen(command + ["run", "--interval", "0.05"], stdout=subprocess.PIPE, text=True)
        try:
            line = json.loads(proc.stdout.readline())
            self.assertEqual(line["state"], "running")
            self.wait_receipt(line["attempt"])
        finally:
            proc.terminate()
            out, _ = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 0)
        self.assertIn('"stopped"', out)
        result = subprocess.run(command + ["tick"], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["state"], "awaiting_acceptance")

    def test_configuration_drift_blocked(self):
        self.task()
        with self.fake_launch():
            self.runner.tick()
        self.runner.catalog.config["command"] = ["other"]
        with self.assertRaisesRegex(Invalid, "configuration changed"):
            self.runner.tick()

    def test_yaml_delimiter_inside_scalar_and_malformed_yaml(self):
        path = self.task(title="before---after")
        self.assertEqual(self.runner.catalog.read()["a/one"].title, "before---after")
        path.write_text("---\ntype: task\nid: [\n---\n")
        with self.assertRaisesRegex(Invalid, "invalid frontmatter"):
            self.runner.tick()

    def test_goal_change_invalidates_plan_but_result_prose_does_not(self):
        path = self.task(status="blocked")
        self.runner.tick()
        path.write_text(path.read_text() + "\n## Current Result\nStill waiting.\n")
        self.assertEqual(self.runner.tick()["state"], "idle")
        path.write_text(path.read_text() + "\n## Scope\nChanged scope.\n")
        self.assertEqual(self.runner.tick()["state"], "needs_planner")

    def test_event_id_collision_is_rejected(self):
        self.task()
        with self.fake_launch():
            result = self.runner.tick()
        self.runner.event("event-1", result["attempt"], "started", {})
        with self.assertRaisesRegex(Invalid, "event id reused"):
            self.runner.event("event-1", result["attempt"], "exited", {"code": 0})
        self.assertEqual(self.runner.store.active().state, "running")

    def test_task_disappears_during_attempt_holds_slot(self):
        path = self.task()
        with self.fake_launch() as launch:
            result = self.runner.tick()
            path.unlink()
            self.finish(result)
            self.assertEqual(self.runner.tick()["state"], "awaiting_acceptance")
            self.assertEqual(launch.call_count, 1)

    def test_planner_timeout_stops_bridge_child(self):
        from scheduler.planner import invoke
        marker = self.root / "unexpected-child"
        script = self.root / "bridge.py"
        child = f"import time; from pathlib import Path; time.sleep(.5); Path({str(marker)!r}).touch()"
        script.write_text(f"import subprocess,sys,time\nsubprocess.Popen([sys.executable, '-c', {child!r}])\ntime.sleep(5)\n")
        with self.assertRaises(subprocess.TimeoutExpired):
            invoke([sys.executable, str(script)], {}, .15)
        time.sleep(.6)
        self.assertFalse(marker.exists())

    def test_concurrent_lock_and_sqlite_slot_constraint(self):
        import sqlite3
        self.task()
        with self.runner.store.lock():
            other = Scheduler(self.config, self.root / "state")
            try:
                with self.assertRaises(Busy):
                    other.tick()
            finally:
                other.close()
        with self.fake_launch():
            self.runner.tick()
        with self.assertRaises(sqlite3.IntegrityError):
            self.runner.store.db.execute("INSERT INTO attempts VALUES ('other','b/x','b','hash','local','launching',NULL,1,NULL)")

    def test_common_executor_policy_and_literal_prompt_delivery(self):
        from scheduler import launcher
        expected = {
            "claude": ["--print", "--dangerously-skip-permissions"],
            "codex": ["exec", "--dangerously-bypass-approvals-and-sandbox"],
            "qwen": ["--yolo"],
            "kiro": ["chat", "--no-interactive", "--trust-all-tools", "--model", "claude-opus-5.5"],
        }
        bindir = self.root / "bin"
        bindir.mkdir()
        prompt = 'Task text with "quotes", newline\n$(touch NOT_A_COMMAND) and `literal`.'
        for executor, flags in expected.items():
            executable = launcher.PROFILES[executor][0]
            script = bindir / executable
            script.write_text(f"#!{sys.executable}\nimport sys,json\nprint(json.dumps(sys.argv[1:]))\n")
            script.chmod(0o700)
            result = subprocess.run([sys.executable, launcher.__file__, "--executor", executor],
                                    input=prompt, capture_output=True, text=True, check=True,
                                    env=dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ["PATH"]))
            self.assertEqual(json.loads(result.stdout), flags + [prompt])
            self.assertFalse(any("effort" in arg for arg in launcher.command(executor)))
        with self.assertRaisesRegex(ValueError, "Kiro model"):
            launcher.command("kiro", "explicit-model")

    def test_executor_selection_is_common_config_only(self):
        config = json.loads(self.config.read_text())
        del config["command"]
        config["executor"] = "codex"
        self.config.write_text(json.dumps(config))
        with patch("scheduler.model.shutil.which", return_value="/fixture/bin/codex"):
            catalog = Catalog(self.config)
            self.assertEqual(catalog.command(catalog.projects[0]), catalog.command(catalog.projects[1]))
            self.assertIn("codex", catalog.command(catalog.projects[0]))
        config["executor"] = "unknown"
        self.config.write_text(json.dumps(config))
        with self.assertRaisesRegex(Invalid, "common executor"):
            Catalog(self.config)

    def test_failed_worker_status_bookkeeping_does_not_replan(self):
        self.task()
        self.runner.catalog.config["planner_command"] = ["fake"]
        with patch("scheduler.planner.invoke") as invoke, self.fake_launch():
            first = self.runner.tick()
            self.task(status="active")
            self.finish(first, 3)
            self.assertEqual(self.runner.tick()["state"], "idle")
            self.runner.resolve(first["attempt"], "retry", "exit 3 collected", True)
            self.assertEqual(self.runner.tick()["state"], "idle")
            invoke.assert_not_called()

    def test_new_arrival_does_not_conflict_with_blocked_priority(self):
        self.task(priority=0, status="blocked")
        self.runner.tick()
        self.task("b/two", priority=0)
        with self.fake_launch():
            self.assertEqual(self.runner.tick()["state"], "running")

    def test_manual_event_id_cannot_poison_automatic_receipt(self):
        self.task()
        with self.fake_launch():
            first = self.runner.tick()
        ident = first["attempt"]
        self.runner.event(ident + ":exited", ident, "exited", {"code": 0})
        folder = self.root / "state/attempts" / ident
        atomic_json(folder / "exited.json", {"attempt": ident, "code": 0, "at": 123})
        self.assertEqual(self.runner.tick()["state"], "awaiting_acceptance")

    def test_resolved_executor_survives_worker_path_change(self):
        bindir = self.root / "bin"
        bindir.mkdir()
        executable = bindir / "codex"
        executable.write_text(f"#!{sys.executable}\nimport sys,json\nprint(json.dumps(sys.argv[1:]))\n")
        executable.chmod(0o700)
        config = json.loads(self.config.read_text())
        del config["command"]
        config["executor"] = "codex"
        self.config.write_text(json.dumps(config))
        with patch.dict(os.environ, PATH=str(bindir)):
            catalog = Catalog(self.config)
            command = catalog.command(catalog.projects[0])
        result = subprocess.run(command, input="fixture prompt", capture_output=True, text=True,
                                env=dict(os.environ, PATH="/no-executables"), check=True)
        self.assertEqual(json.loads(result.stdout), ["exec", "--dangerously-bypass-approvals-and-sandbox", "fixture prompt"])


if __name__ == "__main__":
    unittest.main()
