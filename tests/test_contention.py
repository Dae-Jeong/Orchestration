"""Protocol fences under contention, superseded claims and failed writes, on isolated real SQLite ledgers.

These guard the claim/lease/ACK core independently of where its SQL lives: every check goes
through the public Mailbox/References verbs and inspects the ledger through a second connection.
"""
from contextlib import closing
import multiprocessing
import sqlite3
import unittest

import test_scheduler as fixtures
from scheduler.model import Invalid
from scheduler.refs import References
from scheduler.runtime import Scheduler
from test_refs import MAIN, WORKER, block

PROTOCOL_TABLES = ('messages', 'processing_results', 'message_acks', 'worker_results', 'ref_events', 'message_audit')


def competing_ref_claim(config, state, who, start, queue):
    runner = Scheduler(config, state)
    try:
        refs = References(runner.store, runner.catalog, runner.mailbox.max_deliveries)
        start.wait(10)
        queue.put(refs.claim(*who, lease=30))
    except Exception as exc:
        queue.put({'error': repr(exc)})
    finally:
        runner.close()


class ContentionTest(unittest.TestCase):
    task = fixtures.SchedulerTest.task
    fake_launch = fixtures.SchedulerTest.fake_launch
    tearDown = fixtures.SchedulerTest.tearDown

    def setUp(self):
        fixtures.SchedulerTest.setUp(self)
        self.task()
        with self.fake_launch():
            launch = self.runner.tick()
        self.attempt = launch['attempt']
        self.target = ('a/one', self.attempt, 'worker:' + self.attempt)
        self.bus = self.runner.mailbox
        self.rev = self.bus.inbox(*self.target)['revision']
        fixtures.SchedulerTest.take_over(self, self.attempt, 'a/one')
        self.path = self.root / 'a' / 'tasks' / 'refs.md'
        self.path.write_text('---\ntype: task\nid: refs\nproject_id: a\nstatus: active\n---\n\n## Exchange\n\n'
                             + block('q1', 'Which token?') + block('a1', 'This one.'))
        self.now = 1000.0
        self.bus.clock = lambda: self.now
        self.refs = References(self.runner.store, self.runner.catalog, self.bus.max_deliveries, clock=lambda: self.now)

    def ledger(self):
        """Protocol tables as seen by an independent connection (committed state only)."""
        with closing(sqlite3.connect(self.root / 'state/ledger.sqlite3')) as db:
            return {t: db.execute(f'SELECT * FROM {t} ORDER BY rowid').fetchall() for t in PROTOCOL_TABLES}

    def send(self, ident='m1'):
        return self.bus.send(ident, *self.target, self.rev, 'instruction', {'text': 'fixture'}, True)

    def publish(self, ident='e1', item='q1'):
        return self.refs.publish(ident, 'question.opened', 'a/refs', str(self.path), item, *WORKER, MAIN[0])

    def test_ref_claim_competition_has_one_owner_across_processes(self):
        self.publish()
        ctx = multiprocessing.get_context('spawn')
        queue, start = ctx.Queue(), ctx.Event()
        children = [ctx.Process(target=competing_ref_claim,
                                args=(str(self.config), str(self.root / 'state'), MAIN, start, queue)) for _ in range(3)]
        for child in children:
            child.start()
        start.set()
        results = [queue.get(timeout=20) for _ in children]
        for child in children:
            child.join(10)
            self.assertEqual(child.exitcode, 0)
        self.assertEqual(sorted(r.get('state', r.get('error')) for r in results), ['claimed', 'empty', 'empty'], results)
        owner = next(r for r in results if r['state'] == 'claimed')
        self.assertTrue(all(r['busy'] == ['e1'] for r in results if r['state'] == 'empty'))
        row = self.refs.row('e1')
        self.assertEqual((row['deliveries'], row['token'], row['state']), (1, owner['token'], 'claimed'))

    def test_superseded_claim_token_cannot_read_record_or_ack(self):
        self.send()
        old = self.bus.claim(*self.target, self.rev, lease=10)['message']
        self.now += 11
        new = self.bus.claim(*self.target, self.rev, lease=10)['message']
        self.assertNotEqual(old['token'], new['token'])
        before = self.ledger()
        with self.assertRaisesRegex(Invalid, 'expired or superseded'):
            self.bus.processed('m1', *self.target, self.rev, old['token'], 'applied', {'stale': True})
        with self.assertRaisesRegex(Invalid, 'wrong ACK target'):
            self.bus.ack('m1', *self.target, self.rev, old['token'])
        self.assertEqual(self.ledger(), before)
        self.bus.processed('m1', *self.target, self.rev, new['token'], 'applied', {'fresh': True}, 'redelivered; nothing applied yet')
        self.assertEqual(self.bus.ack('m1', *self.target, self.rev, new['token'])['state'], 'acked')

        self.publish()
        first = self.refs.claim(*MAIN, lease=10)
        self.refs.read('e1', *MAIN, first['token'])
        self.now += 11
        second = self.refs.claim(*MAIN, lease=10)
        before = self.ledger()
        for call in (lambda t: self.refs.read('e1', *MAIN, t),
                     lambda t: self.refs.processed('e1', *MAIN, t, 'applied', {'stale': True}, 'x'),
                     lambda t: self.refs.ack('e1', *MAIN, t)):
            with self.assertRaisesRegex(Invalid, 'expired or superseded'):
                call(first['token'])
        self.assertEqual(self.ledger(), before)
        # The earlier read does not certify the new claim: applied still needs a read with this token.
        with self.assertRaisesRegex(Invalid, 'read the verified item'):
            self.refs.processed('e1', *MAIN, second['token'], 'applied', {'fresh': True}, 'redelivered')
        self.refs.read('e1', *MAIN, second['token'])
        self.refs.processed('e1', *MAIN, second['token'], 'applied', {'fresh': True}, 'redelivered')
        self.assertEqual(self.refs.ack('e1', *MAIN, second['token'])['state'], 'acked')

    def test_failed_protocol_write_rolls_back_the_whole_operation(self):
        """An audit insert that fails after the operation's own writes leaves no committed trace."""
        db = self.runner.store.db

        def rejected(label, call):
            db.execute("CREATE TEMP TRIGGER fail_audit BEFORE INSERT ON message_audit BEGIN "
                       "SELECT RAISE(ABORT, 'injected audit failure'); END")
            try:
                before = self.ledger()
                with self.subTest(label), self.assertRaisesRegex(sqlite3.IntegrityError, 'injected'):
                    call()
                self.assertEqual(self.ledger(), before, label)
                self.assertFalse(db.in_transaction, label)
            finally:
                db.execute('DROP TRIGGER fail_audit')

        rejected('send', self.send)
        self.send()
        rejected('claim', lambda: self.bus.claim(*self.target, self.rev, lease=10))
        claim = self.bus.claim(*self.target, self.rev, lease=10)['message']
        rejected('processed', lambda: self.bus.processed('m1', *self.target, self.rev, claim['token'], 'applied', {'a': 1}))
        self.bus.processed('m1', *self.target, self.rev, claim['token'], 'applied', {'a': 1})
        rejected('ack', lambda: self.bus.ack('m1', *self.target, self.rev, claim['token']))
        self.bus.ack('m1', *self.target, self.rev, claim['token'])
        self.send('m2')
        rejected('dismiss', lambda: self.bus.dismiss('m2', 'fixture supersession'))
        self.bus.dismiss('m2', 'fixture supersession')
        inbox = self.bus.inbox(*self.target)
        rejected('complete', lambda: self.bus.complete('done', *self.target, inbox['revision'], inbox['inbox_seq'], {'e': 1}))

        rejected('publish', self.publish)
        self.publish()
        rejected('ref claim', lambda: self.refs.claim(*MAIN, lease=10))
        token = self.refs.claim(*MAIN, lease=10)['token']
        rejected('ref read', lambda: self.refs.read('e1', *MAIN, token))
        self.refs.read('e1', *MAIN, token)
        rejected('ref processed', lambda: self.refs.processed('e1', *MAIN, token, 'applied', {'a': 1}))
        self.refs.processed('e1', *MAIN, token, 'applied', {'a': 1})
        rejected('ref ack', lambda: self.refs.ack('e1', *MAIN, token))
        self.publish('e2', 'a1')
        rejected('ref dismiss', lambda: self.refs.dismiss('e2', *WORKER, 'fixture'))


if __name__ == '__main__':
    unittest.main()
