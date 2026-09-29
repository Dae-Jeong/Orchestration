import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from contextlib import closing
from unittest.mock import patch

import test_scheduler as fixtures
from scheduler.model import Invalid
from scheduler.refs import References, items, sha
from scheduler.runtime import Scheduler

WORKER = ('kiro:term-w1', 'orca-dispatch:ctx-w1')
OTHER = ('kiro:term-w2', 'orca-dispatch:ctx-w2')
MAIN = ('orca:term-main', 'orca-run:run-main')


def block(ident, body):
    return f'<!-- item:{ident} -->\n{body}\n<!-- /item:{ident} -->\n'


class RefsTest(unittest.TestCase):
    tearDown = fixtures.SchedulerTest.tearDown

    def setUp(self):
        fixtures.SchedulerTest.setUp(self)
        self.path = self.write('Fixture.\n', block('q1', 'Which token?') + block('done1', 'Result: ok'))
        self.now = 1000.0
        self.refs = self.make(self.runner)

    def make(self, runner):
        refs = References(runner.store, runner.catalog, runner.mailbox.max_deliveries, clock=lambda: self.now)
        return refs

    def write(self, preface, exchange, name='one', project='a'):
        path = self.root / project / 'tasks' / (name + '.md')
        path.write_text(f'---\ntype: task\nid: {name}\nproject_id: {project}\nstatus: active\n---\n\n'
                        f'## Goal\n{preface}\n## Exchange\n\n{exchange}')
        return path

    def append(self, text):
        with self.path.open('a') as stream:
            stream.write(text)

    def publish(self, ident, kind, item, who=WORKER, to=MAIN[0], **kw):
        return self.refs.publish(ident, kind, 'a/one', str(self.path), item, *who, to, **kw)

    def deliver(self, who=MAIN, report=None):
        claim = self.refs.claim(*who, lease=10)
        self.assertEqual(claim['state'], 'claimed', claim)
        ident, token = claim['event']['id'], claim['token']
        read = self.refs.read(ident, *who, token)
        self.refs.processed(ident, *who, token, 'applied', report or {'applied': read['sha256']})
        return claim, read, self.refs.ack(ident, *who, token)

    # ---- item format and path containment ------------------------------------
    def test_item_boundaries_and_hash_are_deterministic(self):
        found = items('x\n' + block('a', 'one\ntwo') + 'y\n')
        self.assertEqual(found, {'a': 'one\ntwo\n'})
        before = self.refs.item('a/one', str(self.path), 'q1')['sha256']
        self.assertEqual(before, sha('Which token?\n'))
        self.path.write_text(self.path.read_text().replace('Fixture.', 'Unrelated edit.'))
        self.append('\nMore unrelated text.\n' + block('later', 'x'))
        self.assertEqual(self.refs.item('a/one', str(self.path), 'q1')['sha256'], before)

    def test_invalid_item_structure_is_rejected(self):
        cases = {'duplicate item id': block('a', '1') + block('a', '2'),
                 'nested': '<!-- item:a -->\n<!-- item:b -->\nx\n<!-- /item:b -->\n<!-- /item:a -->\n',
                 'unclosed': '<!-- item:a -->\nx\n',
                 'unbalanced': '<!-- item:a -->\nx\n<!-- /item:b -->\n',
                 'malformed': '<!-- item: a -->\nx\n<!-- /item:a -->\n'}
        for reason, text in cases.items():
            with self.subTest(reason), self.assertRaisesRegex(Invalid, reason):
                items(text)
        with self.assertRaisesRegex(Invalid, 'item not found'):
            self.refs.item('a/one', str(self.path), 'missing')
        self.append(block('empty', ' '))
        with self.assertRaisesRegex(Invalid, 'empty'):
            self.refs.item('a/one', str(self.path), 'empty')

    def test_paths_outside_allowed_tasks_and_symlinks_are_rejected(self):
        outside = self.root / 'outside.md'
        outside.write_text(self.path.read_text())
        link = self.root / 'a' / 'tasks' / 'link.md'
        link.symlink_to(outside)
        nested = self.root / 'a' / 'tasks' / 'sub'
        nested.mkdir()
        (nested / 'one.md').write_text(self.path.read_text())
        for path, reason in ((outside, 'outside'), (link, 'symlink'), (nested / 'one.md', 'outside'),
                             (self.root / 'a' / 'tasks' / 'nope.md', 'not found'),
                             (self.root / 'a' / 'tasks' / 'sub' / '..' / '..' / '..' / 'outside.md', 'outside')):
            with self.subTest(str(path)), self.assertRaisesRegex(Invalid, reason):
                self.refs.item('a/one', str(path), 'q1')
        with self.assertRaisesRegex(Invalid, 'does not match'):
            self.refs.item('a/other', str(self.path), 'q1')
        with self.assertRaisesRegex(Invalid, 'not configured'):
            self.refs.item('zzz/one', str(self.path), 'q1')

    # ---- normal exchange -------------------------------------------------------
    def test_question_answer_round_trip_and_ack_is_not_resolution(self):
        stored = self.publish('e-q1', 'question.opened', 'q1')
        self.assertEqual((stored['duplicate'], stored['event']['state']), (False, 'queued'))
        self.assertEqual(self.refs.claim(*WORKER)['state'], 'empty')  # sender does not receive its own event
        claim, read, ack = self.deliver(MAIN)
        self.assertEqual(read['body'], 'Which token?\n')
        self.assertEqual(ack['state'], 'acked')
        self.assertIn('does not resolve', ack['note'])
        self.append(block('a1', 'Answer: TOKEN-42'))
        answer = self.publish('e-a1', 'question.answered', 'a1', who=MAIN, to=WORKER[0], reply_to='e-q1')
        self.assertEqual(answer['event']['recipient_exec'], WORKER[1])
        self.assertEqual(answer['event']['reply_sha256'], stored['event']['item_sha256'])
        _, read, ack = self.deliver(WORKER)
        self.assertEqual((read['body'], read['reply_to']['id']), ('Answer: TOKEN-42\n', 'e-q1'))
        thread = self.refs.show('e-q1')
        self.assertEqual([r['id'] for r in thread['replies']], ['e-a1'])
        with closing(sqlite3.connect(self.root / 'state/ledger.sqlite3')) as db:
            columns = [r[1] for r in db.execute('PRAGMA table_info(ref_events)')]
            self.assertNotIn('body', columns)
            self.assertFalse(db.execute("SELECT count(*) FROM ref_events WHERE envelope LIKE '%TOKEN-42%'").fetchone()[0])
            self.assertEqual(db.execute('SELECT count(*) FROM messages').fetchone()[0], 0)

    def test_completed_and_blocked_share_envelope(self):
        self.append(block('blk1', 'Blocked: need fixture data'))
        self.publish('e-b1', 'work.blocked', 'blk1')
        self.publish('e-d1', 'work.completed', 'done1')
        kinds = [self.deliver(MAIN)[0]['event']['kind'] for _ in range(2)]
        self.assertEqual(kinds, ['work.blocked', 'work.completed'])
        self.assertEqual(self.runner.store.attempts(), [])  # no scheduler attempt is implied

    # ---- idempotence, ACK loss, expiry, restart ----------------------------------
    def test_duplicate_publish_and_id_reuse(self):
        first = self.publish('e-q1', 'question.opened', 'q1')
        again = self.publish('e-q1', 'question.opened', 'q1')
        self.assertTrue(again['duplicate'])
        self.assertEqual(first['event']['seq'], again['event']['seq'])
        with self.assertRaisesRegex(Invalid, 'reused'):
            self.publish('e-q1', 'work.completed', 'q1')
        with self.assertRaisesRegex(Invalid, 'item changed since you read'):
            self.publish('e-x', 'question.opened', 'q1', expected_sha='0' * 64)

    def test_ack_loss_expiry_and_restart_reuse_recorded_result(self):
        self.publish('e-q1', 'question.opened', 'q1')
        claim = self.refs.claim(*MAIN, lease=10)
        ident, token = claim['event']['id'], claim['token']
        with self.assertRaisesRegex(Invalid, 'read the verified item'):
            self.refs.processed(ident, *MAIN, token, 'applied', {'x': 1})
        self.refs.read(ident, *MAIN, token)
        with self.assertRaisesRegex(Invalid, 'record processing'):
            self.refs.ack(ident, *MAIN, token)
        self.refs.processed(ident, *MAIN, token, 'applied', {'x': 1})
        self.assertEqual(self.refs.processed(ident, *MAIN, token, 'applied', {'x': 1})['outcome'], 'applied')
        with self.assertRaisesRegex(Invalid, 'different content'):
            self.refs.processed(ident, *MAIN, token, 'applied', {'x': 2})
        # ACK response lost and the lease expires; content changes; process restarts.
        self.now += 11
        self.path.write_text(self.path.read_text().replace('Which token?', 'Edited later'))
        self.runner.close()
        self.runner = Scheduler(self.config, self.root / 'state')
        self.refs = self.make(self.runner)
        with self.assertRaisesRegex(Invalid, 'expired'):
            self.refs.ack(ident, *MAIN, token)
        again = self.refs.claim(*MAIN, lease=10)
        self.assertEqual(again['event']['processing_result']['report'], {'x': 1})
        historical = self.refs.read(ident, *MAIN, again['token'])
        self.assertEqual(historical['state'], 'historical')
        self.assertNotIn('body', historical)
        ack = self.refs.ack(ident, *MAIN, again['token'])
        self.assertEqual((ack['state'], ack['duplicate']), ('acked', False))
        self.assertTrue(self.refs.ack(ident, *MAIN, again['token'])['duplicate'])
        with self.assertRaisesRegex(Invalid, 'expired or superseded'):
            self.refs.ack(ident, *MAIN, token)

    def test_redelivery_without_result_requires_reconciliation_and_limit_holds(self):
        self.publish('e-q1', 'question.opened', 'q1')
        first = self.refs.claim(*MAIN, lease=10)
        self.now += 11
        second = self.refs.claim(*MAIN, lease=10)
        self.assertTrue(second['event']['needs_reconciliation'])
        self.assertNotEqual(first['token'], second['token'])
        self.refs.read('e-q1', *MAIN, second['token'])
        with self.assertRaisesRegex(Invalid, 'reconciliation'):
            self.refs.processed('e-q1', *MAIN, second['token'], 'applied', {'x': 1})
        self.now += 11
        self.refs.claim(*MAIN, lease=10)
        self.now += 11
        held = self.refs.claim(*MAIN, lease=10)
        self.assertEqual((held['state'], held['held']), ('empty', ['e-q1']))
        self.assertIn('delivery limit', self.refs.show('e-q1')['event']['reason'])

    # ---- stale references and independent streams ------------------------------
    def test_changed_item_is_held_without_blocking_independent_worker(self):
        self.publish('e-q1', 'question.opened', 'q1')
        other = self.write('Other.\n', block('r2', 'Worker two done'), name='two')
        self.refs.publish('e-r2', 'work.completed', 'a/two', str(other), 'r2', *OTHER, MAIN[0])
        self.path.write_text(self.path.read_text().replace('Which token?', 'Changed question'))
        claim, read, _ = self.deliver(MAIN)
        self.assertEqual((claim['event']['id'], read['body']), ('e-r2', 'Worker two done\n'))
        self.assertEqual(claim['held'], ['e-q1'])
        self.assertIn('stale_reference', self.refs.show('e-q1')['event']['reason'])
        self.assertEqual(self.refs.claim(*MAIN)['state'], 'empty')
        dismissed = self.refs.dismiss('e-q1', *WORKER, 'superseded by e-q1b')
        self.assertEqual(dismissed['state'], 'dismissed')
        with self.assertRaisesRegex(Invalid, 'sender or recipient'):
            self.refs.dismiss('e-r2', *WORKER, 'not mine')

    def test_change_between_claim_and_read_holds(self):
        self.publish('e-q1', 'question.opened', 'q1')
        claim = self.refs.claim(*MAIN)
        self.path.write_text(self.path.read_text().replace('Which token?', 'Changed'))
        read = self.refs.read('e-q1', *MAIN, claim['token'])
        self.assertEqual(read['state'], 'held')
        self.assertNotIn('body', read)

    def test_stale_answers_are_rejected_or_held(self):
        self.publish('e-q1', 'question.opened', 'q1')
        self.deliver(MAIN)
        self.append(block('a1', 'Answer one'))
        self.publish('e-a1', 'question.answered', 'a1', who=MAIN, to=WORKER[0], reply_to='e-q1')
        # Question edited after the answer was published: the answer is held, not applied.
        self.path.write_text(self.path.read_text().replace('Which token?', 'Which other token?'))
        held = self.refs.claim(*WORKER)
        self.assertEqual((held['state'], held['held']), ('empty', ['e-a1']))
        self.assertIn('stale_answer', self.refs.show('e-a1')['event']['reason'])
        # Answering the old question event after edit is refused.
        self.append(block('a2', 'Answer two'))
        with self.assertRaisesRegex(Invalid, 'question changed'):
            self.publish('e-a2', 'question.answered', 'a2', who=MAIN, to=WORKER[0], reply_to='e-q1')
        # Reopen with a new event; answers to the superseded event remain stale.
        self.refs.dismiss('e-a1', *WORKER, 'question revised; wait for e-q1b answer')
        self.publish('e-q1b', 'question.opened', 'q1')
        with self.assertRaisesRegex(Invalid, 'reopened'):
            self.publish('e-a3', 'question.answered', 'a2', who=MAIN, to=WORKER[0], reply_to='e-q1')
        self.deliver(MAIN)
        self.publish('e-a4', 'question.answered', 'a2', who=MAIN, to=WORKER[0], reply_to='e-q1b')
        _, read, _ = self.deliver(WORKER)
        self.assertEqual(read['body'], 'Answer two\n')

    # ---- recipient scope ---------------------------------------------------------
    def test_recipient_and_execution_scope(self):
        self.publish('e-q1', 'question.opened', 'q1', to_exec=MAIN[1])
        self.assertEqual(self.refs.claim(*OTHER)['state'], 'empty')
        self.assertEqual(self.refs.claim(MAIN[0], 'orca-run:other')['state'], 'empty')
        claim = self.refs.claim(*MAIN)
        for who in (OTHER, (MAIN[0], 'orca-run:other')):
            with self.subTest(who), self.assertRaisesRegex(Invalid, 'not addressed'):
                self.refs.read('e-q1', *who, claim['token'])
            with self.assertRaisesRegex(Invalid, 'not addressed'):
                self.refs.ack('e-q1', *who, claim['token'])
        self.append(block('a1', 'Answer'))
        with self.assertRaisesRegex(Invalid, 'only the question recipient'):
            self.publish('e-a1', 'question.answered', 'a1', who=OTHER, to=WORKER[0], reply_to='e-q1')
        with self.assertRaisesRegex(Invalid, 'only the question recipient'):
            self.publish('e-a1', 'question.answered', 'a1', who=MAIN, to=OTHER[0], reply_to='e-q1')
        with self.assertRaisesRegex(Invalid, 'asking execution'):
            self.publish('e-a1', 'question.answered', 'a1', who=MAIN, to=WORKER[0], reply_to='e-q1', to_exec='x:y')
        with self.assertRaisesRegex(Invalid, 'new item'):
            self.publish('e-a1', 'question.answered', 'q1', who=MAIN, to=WORKER[0], reply_to='e-q1')
        with self.assertRaisesRegex(Invalid, 'requires --reply-to'):
            self.publish('e-a1', 'question.answered', 'a1', who=MAIN, to=WORKER[0])
        with self.assertRaisesRegex(Invalid, 'participant'):
            self.publish('e-bad', 'question.opened', 'q1', who=('bad id', 'x'))

    def test_scheduler_attempt_identity_is_not_implied(self):
        with patch.dict(os.environ, {'SCHEDULER_ATTEMPT': 'abc'}):
            with self.assertRaisesRegex(Invalid, 'scheduler:<attempt>'):
                self.publish('e-q1', 'question.opened', 'q1')
            with self.assertRaisesRegex(Invalid, 'not a live attempt'):
                self.publish('e-q1', 'question.opened', 'q1', who=(WORKER[0], 'scheduler:abc'))
        self.runner.store.db.execute("INSERT INTO attempts VALUES ('abc','a/two','a','r','local','running',NULL,0,NULL)")
        with patch.dict(os.environ, {'SCHEDULER_ATTEMPT': 'abc'}):
            with self.assertRaisesRegex(Invalid, 'does not own this Task'):
                self.publish('e-q1', 'question.opened', 'q1', who=(WORKER[0], 'scheduler:abc'))
        self.runner.store.db.execute("UPDATE attempts SET task='a/one'")
        with patch.dict(os.environ, {'SCHEDULER_ATTEMPT': 'abc'}):
            self.assertFalse(self.publish('e-q1', 'question.opened', 'q1', who=(WORKER[0], 'scheduler:abc'))['duplicate'])

    def test_change_after_read_is_not_certified_as_applied(self):
        self.publish('e-q1', 'question.opened', 'q1')
        claim = self.refs.claim(*MAIN)
        self.assertEqual(self.refs.read('e-q1', *MAIN, claim['token'])['state'], 'read')
        self.path.write_text(self.path.read_text().replace('Which token?', 'Changed after read'))
        result = self.refs.processed('e-q1', *MAIN, claim['token'], 'applied', {'x': 1})
        self.assertEqual(result['state'], 'held')
        event = self.refs.show('e-q1')['event']
        self.assertEqual((event['state'], event['outcome']), ('held', None))

    def test_question_change_after_answer_read_is_not_certified(self):
        self.publish('e-q1', 'question.opened', 'q1')
        self.deliver(MAIN)
        self.append(block('a1', 'Answer'))
        self.publish('e-a1', 'question.answered', 'a1', who=MAIN, to=WORKER[0], reply_to='e-q1')
        claim = self.refs.claim(*WORKER)
        self.refs.read('e-a1', *WORKER, claim['token'])
        self.path.write_text(self.path.read_text().replace('Which token?', 'Revised question'))
        self.assertIn('stale_answer', self.refs.processed('e-a1', *WORKER, claim['token'], 'applied', {'x': 1})['reason'])

    def test_read_returns_the_same_text_it_verified(self):
        self.publish('e-q1', 'question.opened', 'q1')
        claim = self.refs.claim(*MAIN)
        with patch.object(self.refs, 'item', wraps=self.refs.item) as spy:
            read = self.refs.read('e-q1', *MAIN, claim['token'])
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(sha(read['body']), read['event']['item_sha256'])

    def test_publish_rechecks_reference_before_commit(self):
        with patch.object(self.refs, 'stale', return_value=('stale_reference: fixture race', None)):
            with self.assertRaisesRegex(Invalid, 'changed during publish'):
                self.publish('e-q1', 'question.opened', 'q1')
        with self.assertRaisesRegex(Invalid, 'unknown event'):
            self.refs.show('e-q1')

    def test_wait_is_bounded_and_holds_no_transaction_while_sleeping(self):
        observed = []
        clock = [0.0]

        def sleep(seconds):
            observed.append(self.runner.store.db.in_transaction)
            clock[0] += seconds

        result = self.refs.wait(*MAIN, timeout=3, interval=1, sleep=sleep, now=lambda: clock[0])
        self.assertEqual(result['state'], 'timeout')
        self.assertEqual(observed, [False, False, False])
        self.publish('e-q1', 'question.opened', 'q1')
        self.assertEqual(self.refs.wait(*MAIN, timeout=3, sleep=sleep, now=lambda: clock[0])['state'], 'claimed')


class RefsCliTest(unittest.TestCase):
    """Isolated subprocesses: separate processes play worker and main against one state."""
    tearDown = fixtures.SchedulerTest.tearDown

    def setUp(self):
        fixtures.SchedulerTest.setUp(self)
        self.runner.close()
        self.path = RefsTest.write(self, 'Fixture.\n', block('q1', 'Which token?') + block('blk1', 'Blocked: x'))

    def cli(self, *args, who=None, code=0):
        env = dict(os.environ)
        env.pop('SCHEDULER_ATTEMPT', None)
        if who:
            env.update(SCHEDULER_REF_AS=who[0], SCHEDULER_REF_EXEC=who[1])
        proc = subprocess.run([sys.executable, '-m', 'scheduler', '--config', str(self.config),
                               '--state', str(self.root / 'state'), 'ref', *args],
                              capture_output=True, text=True, env=env, cwd=Path(__file__).parents[1])
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def handle(self, who, outcome='applied'):
        claim = self.cli('wait', '--timeout', '5', '--interval', '0.1', who=who)
        ident, token = claim['event']['id'], claim['token']
        read = self.cli('read', '--id', ident, '--token', token, who=who)
        report = self.root / (ident + '.json')
        report.write_text(json.dumps({'read_sha256': read['sha256']}))
        self.cli('processed', '--id', ident, '--token', token, '--outcome', outcome, '--report-file', str(report), who=who)
        return claim, read, self.cli('ack', '--id', ident, '--token', token, who=who)

    def test_cli_round_trip_blocked_completed_and_timeout(self):
        timeout = self.cli('wait', '--timeout', '0.2', '--interval', '0.1', who=MAIN, code=3)
        self.assertEqual(timeout['state'], 'timeout')
        base = ('--task', 'a/one', '--path', str(self.path))
        item = self.cli('item', *base, '--item', 'q1')
        self.cli('publish', '--id', 'e-q1', '--kind', 'question.opened', *base, '--item', 'q1',
                 '--sha256', item['sha256'], '--to', MAIN[0], who=WORKER)
        self.assertEqual(self.handle(MAIN)[1]['body'], 'Which token?\n')
        with self.path.open('a') as stream:
            stream.write(block('a1', 'TOKEN-42') + block('done1', 'Completed'))
        self.cli('publish', '--id', 'e-a1', '--kind', 'question.answered', *base, '--item', 'a1',
                 '--reply-to', 'e-q1', '--to', WORKER[0], who=MAIN)
        self.assertEqual(self.handle(WORKER)[1]['body'], 'TOKEN-42\n')
        self.cli('publish', '--id', 'e-b1', '--kind', 'work.blocked', *base, '--item', 'blk1', '--to', MAIN[0], who=WORKER)
        self.cli('publish', '--id', 'e-d1', '--kind', 'work.completed', *base, '--item', 'done1', '--to', MAIN[0], who=WORKER)
        self.assertEqual(self.handle(MAIN, 'deferred')[2]['state'], 'held')
        error = self.cli('claim', who=MAIN, code=0)
        self.assertEqual((error['state'], error['held']), ('empty', ['e-b1']))  # deferred blocks only its stream
        self.cli('dismiss', '--id', 'e-b1', '--reason', 'reviewed blocker', who=MAIN)
        self.assertEqual(self.handle(MAIN)[0]['event']['kind'], 'work.completed')
        shown = self.cli('show', '--id', 'e-q1')
        self.assertEqual(shown['replies'][0]['state'], 'acked')
        bad = self.cli('read', '--id', 'e-q1', '--token', 'nope', who=OTHER, code=2)
        self.assertEqual(bad['state'], 'error')


if __name__ == '__main__':
    unittest.main()
