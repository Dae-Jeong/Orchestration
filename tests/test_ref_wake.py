"""Best-effort wake of an idle `orca:<handle>` recipient, against a fake orca executable."""
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import unittest
from contextlib import closing
from unittest.mock import patch

import test_scheduler as fixtures
from scheduler.refs import References

WORKER = ('kiro:term-w1', 'orca-dispatch:ctx-w1')
MAIN = ('orca:term-main', 'orca:term-main')  # wakeable: execution identity is the Orca terminal handle

FAKE = '''#!{python}
import json, sys
args = sys.argv[1:]
with open({log!r}, 'a') as stream:
    stream.write(json.dumps(args) + '\\n')
modes = json.load(open({scenario!r}))
verb, mode = args[1], None
mode = modes.get(verb, 'ok')
def out(body, code=0):
    print(json.dumps(body)); sys.exit(code)
if mode == 'crash':
    sys.exit(7)
handle = args[args.index('--terminal') + 1]
if verb == 'show':
    if mode == 'stale':
        out({{'ok': False, 'error': {{'code': 'terminal_handle_stale'}}}}, 1)
    dead = mode == 'orphaned'
    terminal = {{'handle': handle, 'orphaned': dead, 'connected': not dead, 'writable': not dead}}
    if dead:
        terminal['exitCause'] = {{'kind': 'operator_close'}}
    out({{'ok': True, 'result': {{'terminal': terminal}}}})
if verb == 'wait':
    if mode == 'busy':
        out({{'ok': False, 'error': {{'code': 'timeout', 'message': 'timeout'}}}}, 1)
    out({{'ok': True, 'result': {{'wait': {{'handle': handle, 'condition': 'tui-idle', 'satisfied': True}}}}}})
if verb == 'send':
    if mode == 'rejected':
        out({{'ok': False, 'error': {{'code': 'terminal_not_writable'}}}}, 1)
    prompt = {{'requestId': 'req-1', 'stages': ['input_accepted'], 'provider': 'unsupported',
              'observation': 'unsupported', 'processIncarnation': 'inc-1'}}
    out({{'ok': True, 'result': {{'send': {{'handle': handle, 'accepted': True, 'prompt': prompt}},
          'warnings': ['input was accepted, but this provider cannot report delivery.']}}}})
sys.exit(9)
'''


def block(ident, body):
    return f'<!-- item:{ident} -->\n{body}\n<!-- /item:{ident} -->\n'


def prompt_check(test, text, state=None):
    """One line, a runnable ref wait for the same ledger and recipient, and no Task content."""
    test.assertNotIn('\n', text)
    for body in ('Which token?', 'Result: ok', 'item:q1', 'Exchange'):
        test.assertNotIn(body, text)
    command = shlex.split(text.split('Run: ', 1)[1].split(' ; ', 1)[0])
    test.assertEqual(command, [os.path.abspath(sys.executable), '-m', 'scheduler',
                               '--config', str(test.config.resolve()), '--state', str((state or test.root / 'state').resolve()),
                               'ref', 'wait', '--as', MAIN[0], '--exec', MAIN[1], '--timeout', '60'])
    test.assertTrue(all(os.path.isabs(command[i]) for i in (0, 4, 6)))
    return command


def sent_prompt(log):
    sent = json.loads(log.read_text().splitlines()[-1])
    return sent[sent.index('--text') + 1]


class WakeTest(unittest.TestCase):
    tearDown = fixtures.SchedulerTest.tearDown

    def setUp(self):
        env = patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith('SCHEDULER_')}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        fixtures.SchedulerTest.setUp(self)
        self.path = self.root / 'a' / 'tasks' / 'one.md'
        self.path.write_text('---\ntype: task\nid: one\nproject_id: a\nstatus: active\n---\n\n## Exchange\n\n'
                             + block('q1', 'Which token?') + block('done1', 'Result: ok'))
        self.now = 1000.0
        self.refs = References(self.runner.store, self.runner.catalog, self.runner.mailbox.max_deliveries,
                               clock=lambda: self.now)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log, self.scenario = self.root / 'orca-calls.jsonl', self.root / 'orca-scenario.json'
        self.orca = self.bin / 'orca'
        self.orca.write_text(FAKE.format(python=sys.executable, log=str(self.log), scenario=str(self.scenario)))
        self.orca.chmod(0o755)
        self.modes()

    def modes(self, **modes):
        self.scenario.write_text(json.dumps(modes))

    def calls(self):
        return [json.loads(line)[1] for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def publish(self, ident, item='q1', to_exec=MAIN[1]):
        return self.refs.publish(ident, 'question.opened' if item == 'q1' else 'work.completed', 'a/one',
                                 str(self.path), item, *WORKER, MAIN[0], to_exec)

    def wake(self, ident=None, to_exec=MAIN[1], **kw):
        return self.refs.wake(MAIN[0], to_exec, ident, orca=str(self.orca), **kw)

    def audit(self):
        with closing(sqlite3.connect(self.root / 'state/ledger.sqlite3')) as db:
            return [(m, a, json.loads(d)) for m, a, d in db.execute(
                "SELECT message,action,detail FROM message_audit WHERE action LIKE 'ref.wake%' ORDER BY rowid")]

    def assertClaimable(self, ident):
        self.assertEqual(self.refs.show(ident)['event']['state'], 'queued')
        claim = self.refs.claim(*MAIN, lease=10)
        self.assertEqual((claim['state'], claim['event']['id']), ('claimed', ident))
        return claim

    def test_idle_recipient_gets_one_fixed_prompt_and_only_input_accepted(self):
        self.publish('e1')
        result = self.wake('e1')
        self.assertEqual((result['state'], result['wake'], result['delivery']), ('wake_requested', 'requested', 'input_accepted'))
        self.assertEqual(result['receipt']['stages'], ['input_accepted'])
        self.assertEqual(result['receipt']['provider'], 'unsupported')  # Kiro: Orca cannot report turn start
        self.assertEqual(result['not_proven'], ['turn_started', 'processing_acked', 'task_accepted'])
        self.assertEqual(self.calls(), ['show', 'wait', 'send'])
        sent = json.loads(self.log.read_text().splitlines()[-1])
        self.assertEqual(sent[sent.index('--terminal') + 1], 'term-main')
        self.assertIn('--enter', sent)
        self.assertIn('--as orca:term-main --exec orca:term-main', sent[sent.index('--text') + 1])
        prompt_check(self, sent_prompt(self.log))
        waited = json.loads(self.log.read_text().splitlines()[1])
        self.assertEqual(waited[waited.index('--for') + 1], 'tui-idle')
        self.assertEqual([(m, a, d['sent']) for m, a, d in self.audit()], [('ref:e1', 'ref.wake_requested', 'yes')])
        self.assertClaimable('e1')  # wake changed nothing in the event

    def test_prompt_shell_quotes_a_state_path_with_spaces(self):
        from scheduler.runtime import Scheduler
        spaced = self.root / 'state dir'
        runner = Scheduler(self.config, spaced)
        self.addCleanup(runner.close)
        refs = References(runner.store, runner.catalog, runner.mailbox.max_deliveries, clock=lambda: self.now)
        refs.publish('e1', 'question.opened', 'a/one', str(self.path), 'q1', *WORKER, MAIN[0], MAIN[1])
        self.assertEqual(refs.wake(MAIN[0], MAIN[1], 'e1', orca=str(self.orca))['state'], 'wake_requested')
        prompt = sent_prompt(self.log)
        self.assertIn(shlex.quote(str(spaced.resolve())), prompt)
        prompt_check(self, prompt, spaced)

    def test_busy_recipient_gets_nothing_and_event_is_preserved(self):
        self.publish('e1')
        self.modes(wait='busy')
        result = self.wake('e1')
        self.assertEqual((result['state'], result['reason'], result['delivery']), ('wake_skipped', 'busy', 'pull'))
        self.assertEqual(self.calls(), ['show', 'wait'])  # never send into a running turn (live steering)
        self.assertClaimable('e1')
        self.modes()
        self.assertEqual(self.wake()['reason'], 'no_pending')  # live claim: the recipient is already on it

    def test_duplicate_wake_is_suppressed_until_claim_or_cooldown(self):
        self.publish('e1')
        self.assertEqual(self.wake('e1')['state'], 'wake_requested')
        self.publish('e2', item='done1')
        self.assertEqual((self.wake()['state'], self.wake('e2')['reason']), ('wake_skipped', 'duplicate'))
        self.assertEqual(self.calls().count('send'), 1)
        self.now += 601  # default cooldown elapsed without a claim: one more wake is allowed
        self.assertEqual(self.wake()['state'], 'wake_requested')
        self.assertEqual(self.wake(cooldown=10_000)['reason'], 'duplicate')
        claim = self.refs.claim(*MAIN, lease=10)  # the woken exec pulled: a later event may wake again
        self.now += 11  # lease expired, event e1 is claimable again
        self.assertEqual(claim['state'], 'claimed')
        self.assertEqual(self.wake(cooldown=10_000)['state'], 'wake_requested')
        self.assertEqual(self.calls().count('send'), 3)

    def test_failures_are_recorded_and_the_event_stays_stored_and_claimable(self):
        self.publish('e1')
        cases = [({}, 'missing', 'orca_unavailable', False), ({'show': 'crash'}, None, 'orca_unavailable', False),
                 ({'show': 'stale'}, None, 'terminal_stale', True), ({'show': 'orphaned'}, None, 'terminal_orphaned', True),
                 ({'wait': 'crash'}, None, 'idle_check_failed', True), ({'send': 'rejected'}, None, 'send_rejected', True)]
        for modes, orca, reason, supported in cases:
            with self.subTest(reason=reason, modes=modes):
                self.modes(**modes)
                result = self.refs.wake(MAIN[0], MAIN[1], 'e1', orca=str(self.root / orca) if orca else str(self.orca))
                self.assertEqual((result['state'], result['reason'].split(':')[0], result['supported']),
                                 ('wake_failed', reason, supported))
                self.assertEqual(self.refs.show('e1')['event']['state'], 'queued')
        self.assertEqual(self.calls().count('send'), 1)  # only the rejected case reached send
        self.modes(send='crash')  # transport failure after send started: outcome unknown, never resent
        self.assertEqual((self.wake('e1')['reason'].split(':')[0], self.audit()[-1][2]['sent']), ('send_unknown', 'unknown'))
        self.modes()
        self.assertEqual(self.wake('e1')['reason'], 'duplicate')
        self.assertClaimable('e1')

    def test_non_orca_recipient_and_no_pending_are_skipped_without_orca_calls(self):
        self.publish('e1', to_exec=None)
        self.publish('e2', item='done1', to_exec='orca-run:run-main')
        for to_exec in (None, 'orca-run:run-main', 'orca:'):
            result = self.wake(to_exec=to_exec)
            self.assertEqual((result['state'], result['reason'], result['supported'], result['delivery']),
                             ('wake_skipped', 'not_orca', False, 'pull'))
        self.assertEqual(self.wake('missing')['reason'], 'no_pending')
        self.assertEqual(self.calls(), [])


class WakeCliTest(unittest.TestCase):
    tearDown = fixtures.SchedulerTest.tearDown
    modes, calls = WakeTest.modes, WakeTest.calls

    def cli(self, *args, path=None):
        env = dict(os.environ, SCHEDULER_REF_AS=WORKER[0], SCHEDULER_REF_EXEC=WORKER[1])
        if path:
            env['PATH'] = path
        proc = subprocess.run([sys.executable, '-m', 'scheduler', '--config', str(self.config), '--state',
                               str(self.root / 'state'), 'ref', *args], capture_output=True, text=True, env=env,
                              cwd=Path(__file__).parents[1])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def setUp(self):
        WakeTest.setUp(self)
        self.runner.close()  # separate processes own the ledger from here on
        self.base = ('--task', 'a/one', '--path', str(self.path), '--to', MAIN[0], '--to-exec', MAIN[1])

    def test_publish_wake_failure_keeps_stored_and_recovery_wake_uses_orca_on_path(self):
        result = self.cli('publish', '--id', 'e1', '--kind', 'question.opened', *self.base, '--item', 'q1',
                          '--wake', '--orca', str(self.root / 'no-orca'))
        self.assertEqual((result['stored'], result['wake']['state'], result['wake']['supported']),
                         (True, 'wake_failed', False))
        self.assertEqual(result['event']['state'], 'queued')
        recovered = self.cli('wake', '--to', MAIN[0], '--to-exec', MAIN[1], '--id', 'e1',
                             path=str(self.bin) + os.pathsep + '/usr/bin:/bin')
        self.assertEqual((recovered['state'], recovered['receipt']['stages']), ('wake_requested', ['input_accepted']))
        self.assertEqual(recovered['by'], ' '.join(WORKER))
        prompt_check(self, sent_prompt(self.log))  # the publishing process's own absolute config/state
        again = self.cli('publish', '--id', 'e2', '--kind', 'work.completed', *self.base, '--item', 'done1',
                         '--wake', '--orca', str(self.orca))
        self.assertEqual((again['stored'], again['wake']['reason']), (True, 'duplicate'))
        self.assertEqual(self.calls(), ['show', 'wait', 'send'])


if __name__ == '__main__':
    unittest.main()
