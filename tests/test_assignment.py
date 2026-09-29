import dataclasses
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import yaml

import test_scheduler as fixtures
from scheduler import assignment
from scheduler.model import Invalid
from scheduler.runtime import Scheduler
from scheduler.store import Busy, Store

BODY = ("\n## Goal\nRead the sentinel.\n\n## Scope\nOnly docs/ may change.\n\n## Acceptance Criteria\n- AC01: report it.\n"
        "\n## Current Result\nnone\n\n## Next Action\nStart.\n")


class AssignmentTest(unittest.TestCase):
    setUp = fixtures.SchedulerTest.setUp
    tearDown = fixtures.SchedulerTest.tearDown
    fake_launch = fixtures.SchedulerTest.fake_launch
    take_over = fixtures.SchedulerTest.take_over

    def write(self, key='a/one', body=BODY, **meta):
        p, ident = key.split('/')
        values = dict(type='task', id=ident, project_id=p, status='ready', priority=10, depends_on=[], evidence=[])
        values.update(meta)
        path = self.root / p / 'tasks' / (ident + '.md')
        path.write_text('---\n' + yaml.safe_dump(values) + '---\n' + body)
        return path

    def launch(self, **assign):
        self.runner.assign(assign.pop('ident', 'as1'), assign.pop('key', 'a/one'), assign.pop('role', 'implement'),
                           assign.pop('scope', ['docs']), assign.pop('outputs', []), assign.pop('executor', None))
        with self.fake_launch():
            return self.runner.tick()

    def spec(self, attempt):
        return json.loads((self.root / 'state/attempts' / attempt / 'spec.json').read_text())

    def view(self, ident='as1'):
        return next(a for a in self.runner.assignments() if a['id'] == ident)

    def test_explicit_assignment_renders_deterministic_preserved_input(self):
        path = self.write()
        result = self.launch()
        self.assertEqual(result['assignment'], 'as1')
        folder = self.root / 'state/attempts' / result['attempt']
        spec = self.spec(result['attempt'])
        self.assertEqual((folder / 'task-input.md').read_text(), path.read_text())
        self.assertEqual(spec['task_sha256'], self.runner.catalog.read()['a/one'].revision)
        contract = assignment.Assignment.from_record(json.loads((folder / 'assignment.json').read_text()))
        for text in ('Read the sentinel.', 'Only docs/ may change.', 'AC01: report it.', 'Start.', 'role: implement',
                     'Allowed write scope (repo-relative collaboration contract, not OS isolation): docs',
                     'assignment:' + result['attempt'], 'processed --id', 'complete --id'):
            self.assertIn(text, spec['prompt'])
        self.assertNotIn('## Current Result', spec['prompt'])
        protocol = spec['prompt'][spec['prompt'].index('\nExecution identity'):]
        again, sha = assignment.render(contract, result['attempt'], path.read_text(), protocol, 'assignment:' + result['attempt'])
        self.assertEqual(again, spec['prompt'])
        self.assertEqual(spec['prompt_sha256'], __import__('hashlib').sha256(again.encode()).hexdigest())

    def test_contract_record_is_the_stored_form_and_other_shapes_are_rejected(self):
        self.write()
        shown = self.runner.assign('as1', 'a/one', 'implement', ['docs'], ['docs/r.md'], None)['assignment']['contract']
        contract = self.runner.store.assignment('as1')
        self.assertEqual((contract.scope, contract.outputs), (('docs',), ('docs/r.md',)))
        self.assertEqual(contract.record(), shown)
        self.assertEqual(assignment.Assignment.from_record(shown), contract)
        self.assertNotIn('id', dataclasses.replace(contract, id=None).record())  # auto_id digests the id-less form
        for bad in (dict(shown, extra=1), {k: v for k, v in shown.items() if k != 'executor'},
                    dict(shown, scope='docs'), dict(shown, outputs=[1]), dict(shown, id=None), dict(shown, role=None)):
            with self.subTest(bad=bad), self.assertRaisesRegex(Invalid, 'unexpected shape'):
                assignment.Assignment.from_record(bad)

    def test_review_and_implement_roles_and_scope_rules(self):
        self.write(write_scope=['docs', 'tests/test_a.py'])
        with self.assertRaisesRegex(Invalid, 'review assignment has no product write scope'):
            self.runner.assign('r0', 'a/one', 'review', ['docs'], [], None)
        with self.assertRaisesRegex(Invalid, 'requires a write scope'):
            self.runner.assign('i0', 'a/one', 'implement', [], [], None)
        for scope in (['../b/tasks'], ['/etc'], ['src']):
            with self.assertRaises(Invalid):
                self.runner.assign('bad', 'a/one', 'implement', scope, [], None)
        with self.assertRaisesRegex(Invalid, 'exceeds Task-approved'):
            self.runner.assign('bad', 'a/one', 'review', [], ['reports/review.md'], None)
        stored = self.runner.assign('rev', 'a/one', 'review', [], ['docs/review.md'], None)
        self.assertEqual(stored['assignment']['contract']['role'], 'review')
        with self.fake_launch():
            result = self.runner.tick()
        self.assertIn('Review only: do not modify product files', self.spec(result['attempt'])['prompt'])
        self.assertIn('(none: do not modify product files)', self.spec(result['attempt'])['prompt'])

    def test_unknown_or_other_project_task_and_duplicate_ids(self):
        self.write()
        with self.assertRaisesRegex(Invalid, 'unknown Task'):
            self.runner.assign('x', 'b/one', 'implement', ['.'], [], None)
        self.runner.assign('same', 'a/one', 'implement', ['docs'], [], None)
        self.assertTrue(self.runner.assign('same', 'a/one', 'implement', ['docs'], [], None)['duplicate'])
        with self.assertRaisesRegex(Invalid, 'different content'):
            self.runner.assign('same', 'a/one', 'implement', ['docs', 'tests'], [], None)
        with self.assertRaisesRegex(Invalid, 'open explicit assignment'):
            self.runner.assign('other', 'a/one', 'implement', ['docs'], [], None)
        with patch.dict(os.environ, {'SCHEDULER_ATTEMPT': 'worker'}):
            with self.assertRaisesRegex(Invalid, 'coordinator-only'):
                self.runner.assign('w', 'a/one', 'implement', ['docs'], [], None)

    def test_executor_policy_for_all_presets_and_command_conflict(self):
        self.write()
        with self.assertRaisesRegex(Invalid, 'explicit command'):
            self.runner.assign('x', 'a/one', 'implement', ['docs'], [], 'codex')
        with self.assertRaisesRegex(Invalid, 'must be claude'):
            self.runner.assign('x', 'a/one', 'implement', ['docs'], [], 'gpt')
        config = json.loads(self.config.read_text())
        del config['command']
        config.update(executor='codex', model='gpt-fixture')
        self.config.write_text(json.dumps(config))
        self.runner.close()
        self.runner = Scheduler(self.config, self.root / 'state')
        with patch('scheduler.model.shutil.which', side_effect=lambda name: '/fixture/bin/' + name):
            for n, executor in enumerate(('claude', 'codex', 'qwen', 'kiro', None)):
                if n:
                    last = self.runner.store.attempts()[-1].id
                    self.runner.resolve(last, 'retry', 'fixture launch never ran', True)
                    self.runner.store.db.execute("UPDATE assignments SET state='completed' WHERE origin='explicit'")
                result = self.launch(ident='e%d' % n, executor=executor)
                command = self.spec(result['attempt'])['command']
                expected = executor or 'codex'
                self.assertEqual(command[command.index('--executor') + 1], expected)
                self.assertNotIn('--effort', command)
                binary = {'kiro': 'kiro-cli'}.get(expected, expected)
                self.assertEqual(command[command.index('--executable') + 1], '/fixture/bin/' + binary)
                # The common model belongs only to the configured executor; Kiro keeps its pinned default.
                self.assertEqual('--model' in command, expected == 'codex')

    def test_revision_change_before_launch_holds_but_result_edit_does_not(self):
        path = self.write()
        self.runner.assign('as1', 'a/one', 'implement', ['docs'], [], None)
        path.write_text(path.read_text().replace('## Current Result\nnone', '## Current Result\nprogress'))
        with self.fake_launch():
            self.assertEqual(self.runner.tick()['assignment'], 'as1')
        self.runner.resolve(self.runner.store.attempts()[-1].id, 'retry', 'fixture launch never ran', True)
        path.write_text(path.read_text().replace('Only docs/ may change.', 'Only docs/ and tests/ may change.'))
        with self.fake_launch() as launch:
            result = self.runner.tick()
        launch.assert_not_called()
        self.assertEqual(result['state'], 'idle')
        self.assertEqual(self.view()['state'], 'held')
        self.assertIn('instruction revision changed', self.view()['reason'])
        # The held explicit choice still reserves the Task: no silent fallback to a broader default assignment.
        self.assertEqual(len(self.runner.store.attempts()), 1)
        self.runner.assign('as2', 'a/one', 'implement', ['docs'], [], None)
        with self.fake_launch():
            self.assertEqual(self.runner.tick()['assignment'], 'as2')

    def test_take_over_requires_worker_report_not_transport(self):
        self.write()
        result = self.launch()
        target = ('a/one', result['attempt'], 'worker:' + result['attempt'])
        bus = self.runner.mailbox
        rev = bus.inbox(*target)['revision']
        launch = self.view()['launches'][0]
        self.assertEqual((launch['delivered'], launch['taken_over'], launch['completed']), (False, False, False))
        claim = bus.claim(*target, rev)['message']
        self.assertEqual(claim['id'], 'assignment:' + result['attempt'])
        self.assertTrue(self.view()['launches'][0]['delivered'])
        self.assertFalse(self.view()['launches'][0]['taken_over'])
        with self.assertRaisesRegex(Invalid, 'echo expected fields: assignment, role'):
            bus.processed(claim['id'], *target, rev, claim['token'], 'applied', {'task_revision': rev, 'note': 'accepted'})
        with self.assertRaisesRegex(Invalid, 'unapplied required'):
            bus.complete('c', *target, rev, bus.inbox(*target)['inbox_seq'], {'e': 1})
        bus.processed(claim['id'], *target, rev, claim['token'], 'applied', dict(claim['payload']['expect'], read='Task'))
        bus.ack(claim['id'], *target, rev, claim['token'])
        self.assertTrue(self.view()['launches'][0]['taken_over'])
        self.assertFalse(self.view()['launches'][0]['completed'])
        bus.complete('c', *target, rev, bus.inbox(*target)['inbox_seq'], {'e': 1})
        self.runner.event('x', result['attempt'], 'exited', {'code': 0})
        self.write(status='done', evidence=['result.json'])
        self.assertEqual(self.runner.tick()['state'], 'idle')
        self.assertEqual(self.view()['state'], 'completed')
        self.assertTrue(self.view()['launches'][0]['completed'])

    def test_ambiguous_launch_restart_keeps_ids_and_retry_reuses_assignment(self):
        self.write()
        self.runner.assign('as1', 'a/one', 'implement', ['docs'], [], None)
        with patch('scheduler.adapters.launch', side_effect=RuntimeError('response lost')):
            first = self.runner.tick()
        self.assertEqual(first['state'], 'unknown')
        self.runner.close()
        self.runner = Scheduler(self.config, self.root / 'state')
        with self.fake_launch() as launch:
            again = self.runner.tick()
        launch.assert_not_called()
        self.assertEqual((again['state'], again['attempt']), ('unknown', first['attempt']))
        ids = [m['id'] for m in self.runner.status()['messages']]
        self.assertEqual(ids, ['assignment:' + first['attempt']])
        self.runner.resolve(first['attempt'], 'retry', 'operator confirmed no worker ran', True)
        with self.fake_launch():
            second = self.runner.tick()
        self.assertEqual(second['assignment'], 'as1')
        self.assertNotEqual(second['attempt'], first['attempt'])
        self.assertEqual([l['attempt'] for l in self.view()['launches']], [first['attempt'], second['attempt']])
        old = ('a/one', first['attempt'], 'worker:' + first['attempt'])
        with self.assertRaisesRegex(Invalid, 'stale execution'):
            self.runner.mailbox.claim(*old, self.runner.mailbox.inbox(*old)['revision'])

    def test_plan_selected_task_uses_same_path_with_deterministic_default(self):
        self.write(write_scope=['docs'])
        with self.fake_launch():
            first = self.runner.tick()
        auto = first['assignment']
        self.assertTrue(auto.startswith('auto:'))
        self.assertEqual(self.view(auto)['contract']['scope'], ['docs'])
        self.assertIn('assignment:' + first['attempt'], [m['id'] for m in self.runner.status()['messages']])
        self.runner.resolve(first['attempt'], 'retry', 'fixture launch never ran', True)
        with self.fake_launch():
            second = self.runner.tick()
        self.assertEqual(second['assignment'], auto)
        self.assertEqual(len(self.view(auto)['launches']), 2)

    def test_task_change_notification_uses_render_and_mailbox_path(self):
        path = self.write()
        result = self.launch()
        attempt = result['attempt']
        target = ('a/one', attempt, 'worker:' + attempt)
        with self.assertRaisesRegex(Invalid, 'unchanged'):
            self.runner.notify(attempt)
        path.write_text(path.read_text().replace('- AC01: report it.', '- AC01: report it.\n- AC02: also list files.'))
        stored = self.runner.notify(attempt)
        update = stored['message']
        self.assertTrue(update['id'].startswith('assignment:' + attempt + ':'))
        self.assertIn('AC02: also list files.', Path(update['payload']['ref']).read_text())
        states = {m['id']: m['state'] for m in self.runner.status()['messages']}
        self.assertEqual(states['assignment:' + attempt], 'dismissed')
        self.assertTrue(self.runner.notify(attempt)['duplicate'])
        bus = self.runner.mailbox
        rev = bus.inbox(*target)['revision']
        self.assertEqual(rev, update['revision'])
        claim = bus.claim(*target, rev)['message']
        self.assertEqual(claim['id'], update['id'])
        bus.processed(claim['id'], *target, rev, claim['token'], 'applied', dict(claim['payload']['expect']))
        self.assertEqual(bus.ack(claim['id'], *target, rev, claim['token'])['state'], 'acked')

    def narrow(self, path, old, new):
        """Owner edits only the Task write_scope of a running attempt."""
        text = path.read_text()
        path.write_text(text.replace(yaml.safe_dump(dict(write_scope=old)), yaml.safe_dump(dict(write_scope=new)), 1))
        self.assertIn(yaml.safe_dump(dict(write_scope=new)), path.read_text())

    def assert_notify_conflict(self, attempt, *wider):
        folder = self.root / 'state/attempts' / attempt
        before = ([m['id'] for m in self.runner.status()['messages']], sorted(p.name for p in folder.iterdir()),
                  len(self.runner.status()['attempts']))
        with self.assertRaisesRegex(Invalid, 'scope conflict') as caught:
            self.runner.notify(attempt)
        for path in wider:
            self.assertIn(path, str(caught.exception))
        # No stale-scope instruction, rendered update or new worker exists after the diagnostic.
        after = ([m['id'] for m in self.runner.status()['messages']], sorted(p.name for p in folder.iterdir()),
                 len(self.runner.status()['attempts']))
        self.assertEqual(after, before)
        return caught.exception

    def test_notify_rejects_scope_narrowed_below_running_assignment(self):
        path = self.write(write_scope=['.'])
        attempt = self.launch(scope=['.'])['attempt']
        target = ('a/one', attempt, 'worker:' + attempt)
        self.narrow(path, ['.'], ['docs'])
        self.assert_notify_conflict(attempt, '.')
        # The worker cannot obtain an instruction for the new revision that still grants '.'.
        bus = self.runner.mailbox
        rev = bus.inbox(*target)['revision']
        self.assertFalse([m for m in bus.inbox(*target)['messages'] if m['revision'] == rev])
        claim = bus.claim(*target, rev)
        self.assertEqual(claim['state'], 'held')  # only the launch-time instruction, held as stale
        self.assertNotEqual(claim['message']['revision'], rev)
        # Stays a diagnostic on retry; nothing is silently widened or re-rendered.
        self.assert_notify_conflict(attempt, '.')

    def test_notify_rejects_outputs_outside_narrowed_scope(self):
        path = self.write(write_scope=['docs', 'reports'])
        attempt = self.launch(role='review', scope=[], outputs=['reports/review.md'])['attempt']
        self.narrow(path, ['docs', 'reports'], ['docs'])
        error = self.assert_notify_conflict(attempt, 'reports/review.md')
        self.assertIn('reassign', str(error))

    def test_notify_rejects_newly_introduced_narrower_scope(self):
        path = self.write()
        attempt = self.launch(scope=['docs', 'tests'])['attempt']
        text = path.read_text()
        path.write_text(text.replace('evidence: []\n', 'evidence: []\nwrite_scope:\n- docs\n', 1))
        self.assert_notify_conflict(attempt, 'tests')

    def test_notify_compatible_scope_change_keeps_assignment_scope(self):
        path = self.write(write_scope=['docs', 'tests'])
        attempt = self.launch(scope=['docs'], outputs=['docs/report.md'])['attempt']
        target = ('a/one', attempt, 'worker:' + attempt)
        for new in (['docs'], ['docs', 'scheduler']):  # narrowing that still covers it, then widening
            self.narrow(path, ['docs', 'tests'] if new == ['docs'] else ['docs'], new)
            stored = self.runner.notify(attempt)['message']
            rendered = Path(stored['payload']['ref']).read_text()
            self.assertIn('Allowed write scope (repo-relative collaboration contract, not OS isolation): docs.', rendered)
            self.assertIn('Outputs: docs/report.md.', rendered)
        bus = self.runner.mailbox
        rev = bus.inbox(*target)['revision']
        self.assertEqual(rev, stored['revision'])
        claim = bus.claim(*target, rev)['message']
        self.assertEqual(claim['id'], stored['id'])
        bus.processed(claim['id'], *target, rev, claim['token'], 'applied', dict(claim['payload']['expect']))
        self.assertEqual(bus.ack(claim['id'], *target, rev, claim['token'])['state'], 'acked')
        self.assertEqual(len(self.runner.status()['attempts']), 1)

    def test_cli_notify_scope_conflict_is_a_diagnostic_exit(self):
        import subprocess
        path = self.write(write_scope=['.'])
        attempt = self.launch(scope=['.'])['attempt']
        self.narrow(path, ['.'], ['docs'])
        self.runner.close()
        env = {k: v for k, v in os.environ.items() if k != 'SCHEDULER_ATTEMPT'}
        result = subprocess.run([sys.executable, '-m', 'scheduler', '--config', str(self.config), '--state',
                                 str(self.root / 'state'), 'notify', '--attempt', attempt],
                                capture_output=True, text=True, cwd=Path(__file__).parents[1], env=env)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('scope conflict', json.loads(result.stdout)['detail'])
        self.runner = Scheduler(self.config, self.root / 'state')

    def change_goal(self, path):
        path.write_text(path.read_text().replace('- AC01: report it.', '- AC01: report it.\n- AC02: also list files.'))

    def test_direct_notify_holds_the_scheduler_lock_for_the_whole_operation(self):
        path = self.write()
        attempt = self.launch()['attempt']
        self.change_goal(path)
        folder = self.root / 'state/attempts' / attempt
        observed = lambda: ([m['id'] for m in self.runner.status()['messages']], sorted(p.name for p in folder.iterdir()))
        before = observed()
        other = Store(self.root / 'state')
        try:
            with other.lock():  # another tick/assign/notify owner through its own handle
                with self.assertRaises(Busy):
                    self.runner.notify(attempt)
        finally:
            other.close()
        self.assertEqual(observed(), before)  # nothing rendered, sent or dismissed without the lock
        self.assertFalse(self.runner.notify(attempt)['duplicate'])
        with self.assertRaisesRegex(Invalid, 'coordinator-only'), patch.dict(os.environ, {'SCHEDULER_ATTEMPT': attempt}):
            self.runner.notify(attempt)
        with self.runner.store.lock():  # released after success and after a rejected call
            pass

    def test_cli_notify_succeeds_with_a_single_lock(self):
        import subprocess
        path = self.write()
        attempt = self.launch()['attempt']
        self.change_goal(path)
        self.runner.close()
        env = {k: v for k, v in os.environ.items() if k != 'SCHEDULER_ATTEMPT'}
        result = subprocess.run([sys.executable, '-m', 'scheduler', '--config', str(self.config), '--state',
                                 str(self.root / 'state'), 'notify', '--attempt', attempt],
                                capture_output=True, text=True, cwd=Path(__file__).parents[1], env=env)
        self.runner = Scheduler(self.config, self.root / 'state')
        self.assertEqual(result.returncode, 0, result.stdout)
        sent = json.loads(result.stdout)
        self.assertEqual((sent['accepted'], sent['duplicate']), (True, False))
        self.assertIn('AC02: also list files.', Path(sent['message']['payload']['ref']).read_text())

    def test_cli_assign_list_and_worker_guard(self):
        import subprocess
        self.write()
        base = [sys.executable, '-m', 'scheduler', '--config', str(self.config), '--state', str(self.root / 'state')]
        env = {k: v for k, v in os.environ.items() if k != 'SCHEDULER_ATTEMPT'}
        run = lambda args, **extra: subprocess.run(base + args, capture_output=True, text=True,
                                                   cwd=Path(__file__).parents[1], env=dict(env, **extra))
        stored = run(['assign', '--id', 'cli1', '--task', 'a/one', '--role', 'implement', '--scope', 'docs'])
        self.assertEqual(stored.returncode, 0, stored.stdout)
        self.assertEqual(json.loads(stored.stdout)['assignment']['state'], 'pending')
        denied = run(['assign', '--id', 'cli2', '--task', 'a/one', '--role', 'review'], SCHEDULER_ATTEMPT='x')
        self.assertEqual((denied.returncode, 'coordinator-only' in denied.stdout), (2, True))
        listed = json.loads(run(['assignments']).stdout)
        self.assertEqual([a['id'] for a in listed], ['cli1'])


if __name__ == '__main__':
    unittest.main()
