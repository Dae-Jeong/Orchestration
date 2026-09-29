import json
import multiprocessing
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from contextlib import closing
from unittest.mock import patch

import test_scheduler as fixtures
from scheduler.model import Invalid
from scheduler.runtime import Scheduler


def competing_claim(config, state, target, revision, queue):
    runner = Scheduler(config, state)
    try:
        queue.put(runner.mailbox.claim(*target, revision))
    except Exception as exc:
        queue.put({'error': str(exc)})
    finally:
        runner.close()


class MessagingTest(unittest.TestCase):
    task = fixtures.SchedulerTest.task
    fake_launch = fixtures.SchedulerTest.fake_launch
    tearDown = fixtures.SchedulerTest.tearDown

    def setUp(self):
        fixtures.SchedulerTest.setUp(self)
        self.path = self.task()
        with self.fake_launch():
            self.launch = self.runner.tick()
        self.target = ('a/one', self.launch['attempt'], 'worker:' + self.launch['attempt'])
        self.bus = self.runner.mailbox
        self.rev = self.bus.inbox(*self.target)['revision']
        fixtures.SchedulerTest.take_over(self, self.target[1], 'a/one')
        self.now = 1000.0
        self.bus.clock = lambda: self.now

    def send(self, ident='m1', **kwargs):
        return self.bus.send(ident, *self.target, kwargs.get('revision', self.rev),
                             'instruction', kwargs.get('payload', {'text': 'Read new instruction'}), kwargs.get('required', True))

    def claim(self, revision=None):
        return self.bus.claim(*self.target, revision or self.rev, lease=10)

    def processed(self, claim, outcome='applied', reconciliation=''):
        m = claim['message']
        return self.bus.processed(m['id'], *self.target, m['revision'], m['token'], outcome,
                                  {'observed': 'fixture applied' if outcome == 'applied' else 'fixture reason'}, reconciliation)

    def ack(self, claim):
        m = claim['message']
        return self.bus.ack(m['id'], *self.target, m['revision'], m['token'])

    def complete(self, ident='finish'):
        inbox = self.bus.inbox(*self.target)
        return self.bus.complete(ident, *self.target, inbox['revision'], inbox['inbox_seq'], {'evidence': 'fixture'})

    def exit_done(self):
        self.runner.event('fixture-exit', self.launch['attempt'], 'exited', {'code': 0})
        self.task(status='done', evidence=['fixture-result'])

    def test_normal_delivery_commit_ack_and_completion_are_distinct(self):
        stored = self.send()
        self.assertTrue(stored['accepted'])
        with closing(sqlite3.connect(self.root / 'state/ledger.sqlite3')) as db:
            self.assertEqual(db.execute("SELECT state FROM messages WHERE id='m1'").fetchone()[0], 'queued')
        claim = self.claim()
        self.assertEqual(claim['state'], 'claimed')
        with self.assertRaisesRegex(Invalid, 'record processing'):
            self.ack(claim)
        self.processed(claim)
        with self.assertRaisesRegex(Invalid, 'unapplied required'):
            self.complete()
        self.ack(claim)
        self.assertFalse(self.complete()['accepted'])
        self.exit_done()
        self.assertEqual(self.runner.tick()['state'], 'idle')
        self.assertEqual(self.runner.store.attempts()[0].state, 'accepted')

    def test_send_idempotency_and_content_collision(self):
        self.send()
        self.assertTrue(self.send()['duplicate'])
        with self.assertRaisesRegex(Invalid, 'different content'):
            self.send(payload={'text': 'different'})
        self.assertEqual(self.runner.store.db.execute("SELECT count(*) FROM messages WHERE id NOT LIKE 'assignment:%'").fetchone()[0], 1)

    def test_ack_loss_reuses_durable_result_after_restart(self):
        self.send()
        claim = self.claim()
        self.processed(claim)
        original = self.ack(claim)
        self.runner.close()
        self.runner = Scheduler(self.config, self.root / 'state')
        self.bus = self.runner.mailbox
        duplicate = self.ack(claim)
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(original['processing_result'], duplicate['processing_result'])
        self.assertEqual(self.runner.store.db.execute("SELECT count(*) FROM processing_results WHERE message NOT LIKE 'assignment:%'").fetchone()[0], 1)

    def test_crash_after_result_before_ack_reclaim_reuses_result(self):
        self.send()
        old = self.claim()
        self.processed(old)
        self.now += 11
        new = self.claim()
        self.assertEqual(new['message']['id'], old['message']['id'])
        self.assertIsNotNone(new['message']['processing_result'])
        self.assertFalse(new['message']['needs_reconciliation'])
        with self.assertRaises(Invalid):
            self.ack(old)
        self.assertTrue(self.ack(new)['acknowledged'])

    def test_redelivery_without_result_requires_reconciliation(self):
        self.send()
        old = self.claim()
        self.now += 11
        new = self.claim()
        self.assertTrue(new['message']['needs_reconciliation'])
        with self.assertRaisesRegex(Invalid, 'reconciliation'):
            self.processed(new)
        with self.assertRaisesRegex(Invalid, 'superseded'):
            self.processed(old)
        self.processed(new, reconciliation='Compared actual output; no previous effect occurred')
        self.ack(new)

    def test_claim_competition_is_atomic_across_processes(self):
        self.send()
        ctx = multiprocessing.get_context('spawn')
        queue = ctx.Queue()
        children = [ctx.Process(target=competing_claim, args=(str(self.config), str(self.root / 'state'), self.target, self.rev, queue)) for _ in range(2)]
        for child in children:
            child.start()
        for child in children:
            child.join(10)
            self.assertEqual(child.exitcode, 0)
        results = [queue.get(timeout=2) for _ in children]
        self.assertEqual(sorted(r['state'] for r in results), ['busy', 'claimed'])
        self.assertEqual(self.bus.row('m1')['deliveries'], 1)

    def test_wrong_task_recipient_attempt_rejected(self):
        self.send()
        for target in [('b/one', *self.target[1:]), (self.target[0], 'wrong', self.target[2]), (*self.target[:2], 'other-worker')]:
            with self.assertRaisesRegex(Invalid, 'identity or recipient'):
                self.bus.claim(*target, self.rev)
        claim = self.claim()
        self.processed(claim)
        with self.assertRaises(Invalid):
            self.bus.ack('m1', *self.target[:2], 'other', self.rev, claim['message']['token'])

    def test_previous_attempt_is_not_delivered_to_replacement(self):
        self.send()
        self.runner.resolve(self.launch['attempt'], 'retry', 'fixture launch never ran', True)
        with self.fake_launch():
            replacement = self.runner.tick()
        with self.assertRaisesRegex(Invalid, 'stale execution'):
            self.claim()
        target = ('a/one', replacement['attempt'], 'worker:' + replacement['attempt'])
        # The replacement receives only its own new assignment, never the old attempt's m1.
        self.assertEqual(self.bus.claim(*target, self.rev)['message']['id'], 'assignment:' + replacement['attempt'])
        self.assertIn('m1', [m['id'] for m in self.bus.inbox(*self.target)['messages']])

    def test_fifo_and_stale_revision_require_explicit_supersession(self):
        self.send()
        self.send('m2')
        first = self.claim()
        self.assertEqual(self.claim()['state'], 'busy')
        self.processed(first)
        self.ack(first)
        self.path.write_text(self.path.read_text() + '\n## Scope\nNew owner requirements.\n')
        current = self.bus.inbox(*self.target)['revision']
        with self.assertRaisesRegex(Invalid, 'stale Task'):
            self.claim()
        self.assertEqual(self.claim(current)['state'], 'held')
        self.send('m3', revision=current)
        self.assertEqual(self.claim(current)['state'], 'held')
        self.bus.dismiss('m2', 'Owner superseded old instruction with m3; compared no effects')
        self.assertEqual(self.claim(current)['message']['id'], 'm3')

    def test_delivery_limit_holds_and_blocks_completion(self):
        self.send()
        for i in range(3):
            claim = self.claim()
            self.assertEqual(claim['message']['deliveries'], i + 1)
            self.now += 11
        held = self.claim()
        self.assertEqual(held['state'], 'held')
        self.assertIn('limit', held['message']['reason'])
        with self.assertRaisesRegex(Invalid, 'unapplied required'):
            self.complete()
        self.assertEqual(len(self.runner.store.attempts()), 1)
        self.assertEqual(self.runner.store.active().state, 'running')

    def test_deferred_and_conflict_are_not_applied(self):
        self.send()
        claim = self.claim()
        self.processed(claim, outcome='conflict')
        self.assertEqual(self.ack(claim)['state'], 'held')
        self.assertTrue(self.ack(claim)['duplicate'])
        with self.assertRaisesRegex(Invalid, 'unapplied'):
            self.complete()
        self.bus.dismiss('m1', 'Owner withdraws conflicting directive after comparison')
        self.assertTrue(self.complete()['submitted'])

    def test_progress_edits_do_not_fence_instruction_revision(self):
        self.send()
        claim = self.claim()
        old_hash = self.runner.catalog.read()['a/one'].revision
        self.path.write_text(self.path.read_text() + '\n## Current Result\nWorker progress evidence.\n')
        self.assertNotEqual(self.runner.catalog.read()['a/one'].revision, old_hash)
        self.assertEqual(self.bus.inbox(*self.target)['revision'], self.rev)
        self.processed(claim)
        self.ack(claim)

    def test_late_required_message_invalidates_completion_submission(self):
        self.complete()
        self.send()
        result = self.runner.tick()
        self.assertEqual(result['state'], 'running')
        self.assertEqual(result['message_blockers'], ['m1'])
        claim = self.claim()
        self.processed(claim)
        self.ack(claim)
        self.assertEqual(self.runner.tick()['state'], 'running')
        self.complete('finish-after-message')
        self.exit_done()
        self.assertEqual(self.runner.tick()['state'], 'idle')

    def test_owner_revision_change_invalidates_completion(self):
        self.complete()
        self.exit_done()
        self.path.write_text(self.path.read_text() + '\n## Scope\nAdditional requirement.\n')
        self.assertEqual(self.runner.tick()['state'], 'awaiting_acceptance')
        self.assertEqual(self.runner.tick()['acceptance_blocker'], 'completion_revision_stale')
        with self.assertRaisesRegex(Invalid, 'worker exited'):
            self.complete('finish-new-revision')
        self.runner.resolve(self.launch['attempt'], 'failed', 'worker exited; owner will assess changed scope', True)
        self.assertIsNone(self.runner.store.active())

    def test_inbox_seq_compare_and_completion_id_collision(self):
        inbox = self.bus.inbox(*self.target)
        self.send(required=False)
        with self.assertRaisesRegex(Invalid, 'inbox changed'):
            self.bus.complete('finish', *self.target, self.rev, inbox['inbox_seq'], {'result': 'done'})
        result = self.complete()
        self.assertTrue(self.complete()['duplicate'])
        with self.assertRaisesRegex(Invalid, 'different content'):
            self.bus.complete('finish', *self.target, self.rev, 1, {'different': 'report'})
        self.assertTrue(result['submitted'])

    def test_mailbox_works_during_tick_lock_and_other_project_parse_error(self):
        (self.root / 'b/tasks/bad.md').write_text('---\ntype: task\nid: bad\nstatus: invalid\n---\n')
        with self.runner.store.lock():
            other = Scheduler(self.config, self.root / 'state')
            try:
                other.mailbox.send('m1', *self.target, self.rev, 'question', {'text': 'read'}, False)
                claim = other.mailbox.claim(*self.target, self.rev)
                other.mailbox.processed('m1', *self.target, self.rev, claim['message']['token'], 'applied', {'answer': 'yes'})
                other.mailbox.ack('m1', *self.target, self.rev, claim['message']['token'])
            finally:
                other.close()
        self.assertEqual(self.bus.row('m1')['state'], 'acked')

    def test_cli_end_to_end_from_foreign_cwd(self):
        base = [sys.executable, '-m', 'scheduler', '--config', str(self.config), '--state', str(self.root / 'state'), 'message']
        target = ['--task', self.target[0], '--attempt', self.target[1], '--recipient', self.target[2]]
        payload = self.root / 'payload.json'
        payload.write_text('{"text":"read-only fixture directive"}')
        def call(args):
            proc = subprocess.run(base + args, cwd='/', capture_output=True, text=True, check=True)
            return json.loads(proc.stdout)
        self.assertTrue(call(['send', *target, '--id', 'cli', '--revision', self.rev, '--payload-file', str(payload)])['accepted'])
        claim = call(['claim', *target, '--revision', self.rev])['message']
        call(['processed', *target, '--id', 'cli', '--revision', self.rev, '--token', claim['token'], '--outcome', 'applied', '--report-file', str(payload)])
        self.assertTrue(call(['ack', *target, '--id', 'cli', '--revision', self.rev, '--token', claim['token']])['acknowledged'])

    def test_new_attempt_environment_and_prompt_contain_common_protocol(self):
        folder = self.root / 'state/attempts' / self.target[1]
        spec = json.loads((folder / 'spec.json').read_text())
        self.assertEqual(spec['state'], str((self.root / 'state').resolve()))
        self.assertEqual(spec['recipient'], self.target[2])
        self.assertEqual(spec['cli'][0], sys.executable)
        self.assertIn('processed --id', spec['prompt'])
        self.assertIn('complete --id', spec['prompt'])

    def test_legacy_attempt_compatibility_and_rowid_order(self):
        self.runner.store.db.execute('DELETE FROM worker_context')
        self.exit_done()
        self.assertEqual(self.runner.tick()['state'], 'idle')
        self.runner.store.db.execute("INSERT INTO attempts VALUES ('new','b/x','b','r','local','failed',NULL,1,NULL)")
        self.assertEqual(self.runner.store.attempts()[-1].id, 'new')

    def test_post_exit_messages_rejected_even_before_receipt_collection(self):
        self.complete()
        folder = self.root / 'state/attempts' / self.target[1]
        (folder / 'exited.json').write_text(json.dumps({'attempt': self.target[1], 'code': 0}))
        for required in (True, False):
            with self.assertRaisesRegex(Invalid, 'worker exited'):
                self.send(required=required)
        self.runner.tick()
        with self.assertRaisesRegex(Invalid, 'worker exited'):
            self.send()
        self.task(status='done', evidence=['fixture'])
        self.assertEqual(self.runner.tick()['state'], 'idle')
        self.assertEqual(self.bus.messages.inbox_seq(self.target[1]), 1)  # only the assignment message

    def test_saved_applied_result_can_be_acked_beyond_delivery_limit(self):
        self.send()
        first = self.claim()
        self.processed(first)
        for _ in range(4):
            self.now += 11
            replay = self.claim()
            self.assertEqual(replay['state'], 'claimed')
            self.assertIsNotNone(replay['message']['processing_result'])
        self.assertTrue(self.ack(replay)['acknowledged'])
        self.assertEqual(self.runner.store.db.execute("SELECT count(*) FROM processing_results WHERE message NOT LIKE 'assignment:%'").fetchone()[0], 1)

    def test_corrupt_database_is_structured_cli_error(self):
        broken = self.root / 'broken'
        broken.mkdir()
        (broken / 'ledger.sqlite3').write_bytes(b'not a sqlite database')
        result = subprocess.run([sys.executable,'-m','scheduler','--config',str(self.config),'--state',str(broken),'status'],capture_output=True,text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['state'], 'error')
        self.assertNotIn('Traceback', result.stderr)

    def test_inbox_does_not_require_executor_on_callers_path(self):
        config = json.loads(self.config.read_text())
        del config['command']
        config['executor'] = 'claude'
        self.config.write_text(json.dumps(config))
        from scheduler.model import digest, Catalog
        with patch('scheduler.model.shutil.which', return_value='/fixture/claude'):
            catalog = Catalog(self.config)
        self.runner.store.set('config_revision', digest(catalog.config))
        import os
        cmd = [sys.executable,'-m','scheduler','--config',str(self.config),'--state',str(self.root/'state'),'message','inbox','--task',self.target[0],'--attempt',self.target[1],'--recipient',self.target[2]]
        result = subprocess.run(cmd,capture_output=True,text=True,env=dict(os.environ,PATH='/no-executables'))
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_worker_environment_cannot_use_coordinator_verbs(self):
        self.send()
        with patch.dict('os.environ', SCHEDULER_ATTEMPT=self.target[1]):
            with self.assertRaisesRegex(Invalid, 'coordinator-only'):
                self.bus.dismiss('m1', 'worker tries to skip requirement')
            with self.assertRaisesRegex(Invalid, 'coordinator-only'):
                self.send('m2')
        self.assertEqual(self.bus.messages.blockers(self.target[1]), ['m1'])

    def test_status_survives_malformed_task(self):
        self.exit_done()
        path = self.runner.catalog.read()[self.target[0]].path
        Path(path).write_text('---\ntype: task\nid: one\nstatus: broken\n---\n')
        result = self.runner.status()
        self.assertTrue(result['acceptance_blocker'].startswith('task_invalid: '))
        self.assertEqual(len(result['attempts']), 1)
        with self.assertRaises(Invalid):
            self.runner.tick()

    def test_missing_completion_reason_is_visible(self):
        self.exit_done()
        self.assertEqual(self.runner.tick()['acceptance_blocker'], 'no_completion')
        self.assertEqual(self.runner.status()['acceptance_blocker'], 'no_completion')


if __name__ == '__main__':
    unittest.main()
