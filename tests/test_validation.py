"""Pure scheduling decisions: records in, decision out, no ledger."""
import json
import unittest

from scheduler.model import Invalid, Task, check_dependencies, parse
from scheduler.store import Attempt
from scheduler.validation import cleanup_state, event_state, explicit_state, launchable


def task(key, status="ready", deps=(), evidence=()):
    return Task(key, key.split("/")[0], "/fixture/" + key + ".md", status, 0, tuple(deps), key,
                tuple(evidence), "rev", "")


def attempt(ident, state):
    return Attempt(ident, "a/one", "a", "rev", "local", state, None, 0.0, None)


class EventStateTest(unittest.TestCase):
    def test_live_attempt_transitions(self):
        for state in ("launching", "running", "unknown"):
            active = attempt("a1", state)
            self.assertEqual(event_state(None, active, "a1", "started", {}), "running")
            self.assertEqual(event_state(None, active, "a1", "exited", {"code": 0}), "awaiting_acceptance")
            self.assertEqual(event_state(None, active, "a1", "exited", {"code": 3}), "failed")

    def test_other_or_finished_attempt_is_stale(self):
        self.assertIsNone(event_state(None, None, "a1", "started", {}))
        self.assertIsNone(event_state(None, attempt("a2", "running"), "a1", "exited", {"code": 0}))
        self.assertIsNone(event_state(None, attempt("a1", "awaiting_acceptance"), "a1", "exited", {"code": 0}))

    def test_invalid_input_raises_even_when_stale(self):
        with self.assertRaisesRegex(Invalid, "integer code"):
            event_state(None, None, "a1", "exited", {"code": "0"})
        with self.assertRaisesRegex(Invalid, "only started/exited"):
            event_state(None, attempt("a1", "running"), "a1", "cleanup", {})

    def test_reused_id_must_repeat_the_same_event(self):
        stored = {"attempt": "a1", "kind": "exited", "payload": json.dumps({"code": 0})}
        self.assertEqual(event_state(stored, attempt("a1", "running"), "a1", "exited", {"code": 0}),
                         "awaiting_acceptance")
        for other in (("a2", "exited", {"code": 0}), ("a1", "started", {"code": 0}), ("a1", "exited", {"code": 1})):
            with self.subTest(other=other), self.assertRaisesRegex(Invalid, "reused"):
                event_state(stored, attempt("a1", "running"), *other)


class LaunchTest(unittest.TestCase):
    def test_launchable_requires_ready_released_slot_and_accepted_dependencies(self):
        done = task("a/dep", status="done", evidence=["result"])
        unaccepted = task("a/raw", status="done")
        tasks = {t.key: t for t in (done, unaccepted)}
        self.assertTrue(launchable(task("a/one", deps=["a/dep"]), None, tasks))
        self.assertTrue(launchable(task("a/one"), attempt("x", "retry"), tasks))
        self.assertFalse(launchable(task("a/one"), attempt("x", "failed"), tasks))
        self.assertFalse(launchable(task("a/one", status="active"), None, tasks))
        self.assertFalse(launchable(task("a/one", deps=["a/raw"]), None, tasks))

    def test_explicit_state_for_launched_assignment(self):
        self.assertEqual(explicit_state({"x"}, attempt("y", "running")), ("superseded", "another attempt ran this Task"))
        self.assertEqual(explicit_state({"x"}, attempt("x", "accepted")), ("completed", None))
        self.assertEqual(explicit_state({"x"}, attempt("x", "failed")), ("failed", "attempt failed; assign again explicitly"))
        for state in ("running", "awaiting_acceptance", "retry"):
            self.assertIsNone(explicit_state({"x"}, attempt("x", state)))

    def test_cleanup_state_caps_only_unconfirmed(self):
        self.assertEqual(cleanup_state("unconfirmed", 2), "unconfirmed")
        self.assertEqual(cleanup_state("unconfirmed", 3), "failed")
        self.assertEqual(cleanup_state("withheld", 9), "withheld")
        self.assertEqual(cleanup_state("closed", 3), "closed")


class ParseTest(unittest.TestCase):
    """Task text in, Task out: no file exists at the given path."""

    def test_defaults_and_qualified_dependencies_without_files(self):
        raw = "---\ntype: task\nid: t\ndepends_on: [u, b/v]\n---\n## Goal\ng\n## Next Action\nn\n"
        parsed = parse(raw, "a", "/nowhere/t.md", "shown.md")
        self.assertEqual((parsed.key, parsed.status, parsed.priority, parsed.title, parsed.evidence, parsed.write_scope),
                         ("a/t", "ready", 0, "t", (), None))
        self.assertEqual((parsed.path, parsed.depends_on, parsed.brief), ("/nowhere/t.md", ("a/u", "b/v"), "Goal\ng\n"))
        self.assertIsNone(parse("---\ntype: note\n---\n", "a", "/nowhere/n.md", "n.md"))

    def test_errors_name_the_source_or_key_and_duplicates_come_first(self):
        with self.assertRaisesRegex(Invalid, "^missing frontmatter: shown.md$"):
            parse("# none\n", "a", "/nowhere/t.md", "shown.md")
        with self.assertRaisesRegex(Invalid, "^duplicate Task: a/t$"):
            parse("---\ntype: task\nid: t\nstatus: nope\n---\n", "a", "/p", "s", taken={"a/t"})
        with self.assertRaisesRegex(Invalid, "^invalid status: a/t$"):
            parse("---\ntype: task\nid: t\nstatus: nope\n---\n", "a", "/p", "s")

    def test_dependency_check_over_parsed_tasks(self):
        check_dependencies({"a/x": task("a/x", deps=["a/y"]), "a/y": task("a/y")})
        with self.assertRaisesRegex(Invalid, "unknown dependency: a/x -> a/z"):
            check_dependencies({"a/x": task("a/x", deps=["a/z"])})
        with self.assertRaisesRegex(Invalid, "dependency cycle: a/x"):
            check_dependencies({"a/x": task("a/x", deps=["a/y"]), "a/y": task("a/y", deps=["a/x"])})


if __name__ == "__main__":
    unittest.main()
