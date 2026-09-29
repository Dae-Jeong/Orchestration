"""Addressed, leased, at-least-once local delivery; application effects are not replayed."""
import json
import math
import os
import shlex
import time
import uuid

from .model import Invalid, digest
from .protocol_store import MessageStore, packed
from .store import SLOT_STATES


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise Invalid(f'{label} must be nonempty')


class Mailbox:
    def __init__(self, store, catalog, clock=time.time):
        self.store, self.catalog, self.clock = store, catalog, clock
        self.messages = MessageStore(store.db)
        self.max_deliveries = catalog.config.get('message_max_deliveries', 3)
        if type(self.max_deliveries) is not int or self.max_deliveries < 1:
            raise Invalid('message_max_deliveries must be a positive integer')

    def transaction(self, write=True):
        return self.store.transaction(write=write)

    def coordinator_only(self):
        if os.environ.get('SCHEDULER_ATTEMPT'):
            raise Invalid('coordinator-only operation; workers may not send or dismiss')

    def scope(self, task, attempt, recipient, live=True):
        if self.store.get('config_revision') != digest(self.catalog.config):
            raise Invalid('configuration does not match the execution ledger')
        row = self.messages.target(attempt)
        if not row or row['task'] != task or row['recipient'] != recipient:
            raise Invalid('wrong task, execution identity or recipient')
        if live and row['state'] not in SLOT_STATES:
            raise Invalid('stale execution attempt')
        latest = self.messages.latest_attempt(task)
        if live and latest != attempt:
            raise Invalid('stale execution attempt')
        if live and (row['state'] == 'awaiting_acceptance' or
                     (self.store.root / 'attempts' / attempt / 'exited.json').exists()):
            raise Invalid('worker exited; inspect and resolve the stopped attempt explicitly')
        current = self.catalog.read(only_path=row['task_path']).get(task)
        if current is None:
            raise Invalid('Task no longer exists in configured scope')
        return current

    def revision(self, task, attempt, recipient, expected):
        current = self.scope(task, attempt, recipient)
        if current.instruction_revision != expected:
            raise Invalid('stale Task revision; reread the current Task and inbox')
        return current

    def row(self, ident):
        row = self.messages.find(ident)
        if row is None:
            raise Invalid('unknown message id')
        return row

    def view(self, row):
        result = dict(row)
        result['payload'] = json.loads(result['payload'])
        result.pop('envelope', None)
        result['processing_result'] = self.messages.result(result['id'])
        result['needs_reconciliation'] = result['deliveries'] > 1 and result['processing_result'] is None
        return result

    def send(self, ident, task, attempt, recipient, revision, kind, payload, required=True):
        self.coordinator_only()
        nonempty(ident, 'message id')
        if kind not in ('instruction', 'question', 'result') or type(required) is not bool:
            raise Invalid('invalid message kind or required flag')
        if not isinstance(payload, dict) or not payload:
            raise Invalid('payload must be a nonempty JSON object (text and/or reference)')
        envelope = packed(dict(id=ident, task=task, attempt=attempt, recipient=recipient,
                               revision=revision, kind=kind, payload=payload, required=required))
        with self.transaction():
            old = self.messages.find(ident)
            if old:
                if old['envelope'] != envelope:
                    raise Invalid('message id reused with different content')
                self.scope(task, attempt, recipient, live=False)
                result = dict(accepted=True, duplicate=True, message=self.view(old))
            else:
                current = self.revision(task, attempt, recipient, revision)
                self.insert(ident, task, current.project, attempt, recipient, revision, kind, payload, required, envelope)
                self.revision(task, attempt, recipient, revision)
                result = dict(accepted=True, duplicate=False, message=self.view(self.row(ident)))
        return result  # Only after COMMIT. Accepted is not delivery/application/completion.

    def insert(self, ident, task, project, attempt, recipient, revision, kind, payload, required, envelope=None, actor='coordinator'):
        """Caller owns the transaction and has validated the target (send or scheduler launch)."""
        envelope = envelope or packed(dict(id=ident, task=task, attempt=attempt, recipient=recipient,
                                           revision=revision, kind=kind, payload=payload, required=required))
        self.messages.add(ident, task, project, attempt, recipient, revision, kind, payload, required, envelope,
                          self.clock())
        self.messages.audit(ident, 'stored', {'revision': revision, 'actor': actor}, self.clock())

    def inbox(self, task, attempt, recipient):
        with self.transaction(write=False):
            current = self.scope(task, attempt, recipient, live=False)
            rows = self.messages.inbox(attempt, recipient)
            return dict(task=task, attempt=attempt, recipient=recipient, revision=current.instruction_revision,
                        inbox_seq=self.messages.inbox_seq(attempt), messages=[self.view(r) for r in rows])

    def hold(self, row, reason):
        self.messages.settle(row['id'], 'held', reason)
        self.messages.audit(row['id'], 'held', {'reason': reason}, self.clock())

    def claim(self, task, attempt, recipient, revision, lease=60):
        if not isinstance(lease, (float, int)) or isinstance(lease, bool) or not math.isfinite(lease) or lease <= 0:
            raise Invalid('lease must be finite and positive')
        with self.transaction():
            self.revision(task, attempt, recipient, revision)
            row = self.messages.next(attempt, recipient)
            if row is None:
                return {'state': 'empty', 'inbox_seq': self.messages.inbox_seq(attempt), 'revision': revision}
            if row['state'] == 'held':
                return {'state': 'held', 'message': self.view(row)}
            if row['revision'] != revision:
                self.hold(row, 'stale Task revision; coordinator must reconcile or supersede explicitly')
                return {'state': 'held', 'message': self.view(self.row(row['id']))}
            if row['state'] == 'claimed' and row['expires'] > self.clock():
                return {'state': 'busy', 'message_id': row['id']}
            if row['deliveries'] >= self.max_deliveries and self.messages.result(row['id']) is None:
                self.hold(row, 'delivery limit reached; no automatic processing retry')
                return {'state': 'held', 'message': self.view(self.row(row['id']))}
            token = str(uuid.uuid4())
            self.messages.claim(row['id'], token, self.clock() + lease)
            self.messages.audit(row['id'], 'claimed', {'token': token, 'redelivery': row['deliveries'] > 0}, self.clock())
            self.revision(task, attempt, recipient, revision)
            result = {'state': 'claimed', 'message': self.view(self.row(row['id']))}
        return result

    def claimed(self, ident, task, attempt, recipient, revision, token):
        self.revision(task, attempt, recipient, revision)
        row = self.row(ident)
        if (row['task'], row['attempt'], row['recipient'], row['revision']) != (task, attempt, recipient, revision):
            raise Invalid('wrong message target or revision')
        if row['state'] != 'claimed' or row['token'] != token or row['expires'] <= self.clock():
            raise Invalid('expired or superseded claim token')
        return row

    def processed(self, ident, task, attempt, recipient, revision, token, outcome, report, reconciliation=''):
        if outcome not in ('applied', 'deferred', 'conflict') or not isinstance(report, dict) or not report:
            raise Invalid('processing requires applied/deferred/conflict and a nonempty result report')
        with self.transaction():
            row = self.claimed(ident, task, attempt, recipient, revision, token)
            existing = self.messages.result(ident)
            if existing:
                if existing['outcome'] != outcome or existing['report'] != report:
                    raise Invalid('processing result already recorded with different content')
                return existing
            expected = json.loads(row['payload']).get('expect')
            if outcome == 'applied' and isinstance(expected, dict):
                # Take-over evidence: the worker must echo what it actually read, not only accept transport.
                wrong = sorted(k for k, v in expected.items() if report.get(k) != v)
                if wrong:
                    raise Invalid('applied report must echo expected fields: ' + ', '.join(wrong))
            if row['deliveries'] > 1:
                nonempty(reconciliation, 'redelivery reconciliation before reporting external effects')
            self.messages.add_result(ident, outcome, report, reconciliation, self.clock())
            self.messages.audit(ident, 'processing_recorded', {'outcome': outcome, 'token': token}, self.clock())
            self.revision(task, attempt, recipient, revision)
            result = self.messages.result(ident)
        return result

    def ack(self, ident, task, attempt, recipient, revision, token):
        with self.transaction():
            self.scope(task, attempt, recipient, live=False)
            row = self.row(ident)
            if (row['task'], row['attempt'], row['recipient'], row['revision'], row['token']) != (task, attempt, recipient, revision, token):
                raise Invalid('wrong ACK target, revision or claim token')
            result = self.messages.result(ident)
            receipt = self.messages.ack(ident)
            if receipt and receipt['token'] == token:
                return {'acknowledged': True, 'duplicate': True, 'processing_result': result, 'state': row['state']}
            self.claimed(ident, task, attempt, recipient, revision, token)
            if result is None:
                raise Invalid('record processing result before ACK; transport receipt is insufficient')
            state = 'acked' if result['outcome'] == 'applied' else 'held'
            self.messages.settle(ident, state, None if state == 'acked' else result['outcome'])
            self.messages.add_ack(ident, token, result['outcome'], self.clock())
            self.messages.audit(ident, 'acknowledged', {'outcome': result['outcome'], 'token': token}, self.clock())
            self.revision(task, attempt, recipient, revision)
        return {'acknowledged': True, 'duplicate': False, 'processing_result': result, 'state': state}

    def dismiss(self, ident, reason):
        self.coordinator_only()
        nonempty(reason, 'coordinator reconciliation/supersession reason')
        with self.transaction():
            row = self.row(ident)
            self.scope(row['task'], row['attempt'], row['recipient'], live=False)
            if row['state'] == 'acked':
                raise Invalid('cannot dismiss an already applied ACK')
            if row['state'] == 'claimed' and row['expires'] > self.clock():
                raise Invalid('claim still live; coordinate with worker before dismissal')
            self.messages.settle(ident, 'dismissed', reason)
            self.messages.audit(ident, 'coordinator_dismissed', {'reason': reason, 'actor': 'coordinator'}, self.clock())
        return {'state': 'dismissed', 'id': ident, 'reason': reason}

    def complete(self, ident, task, attempt, recipient, revision, inbox_seq, report):
        nonempty(ident, 'completion id')
        if type(inbox_seq) is not int or inbox_seq < 0 or not isinstance(report, dict) or not report:
            raise Invalid('completion requires observed inbox_seq and nonempty report')
        with self.transaction():
            self.scope(task, attempt, recipient, live=False)
            old = self.messages.completion(ident)
            values = (attempt, recipient, task, revision, inbox_seq, packed(report))
            if old:
                if tuple(old[k] for k in ('attempt','recipient','task','revision','inbox_seq','report')) != values:
                    raise Invalid('completion id reused with different content')
                return {'submitted': True, 'duplicate': True, 'id': ident}
            self.revision(task, attempt, recipient, revision)
            if self.messages.inbox_seq(attempt) != inbox_seq:
                raise Invalid('inbox changed; check messages before completion')
            if self.messages.blockers(attempt):
                raise Invalid('unapplied required messages block completion')
            self.messages.add_completion(ident, *values, self.clock())
            self.messages.audit(None, 'completion_submitted', {'id': ident, 'attempt': attempt, 'revision': revision},
                                self.clock())
            self.revision(task, attempt, recipient, revision)
        return {'submitted': True, 'duplicate': False, 'id': ident, 'accepted': False}

    def acceptance_reason(self, attempt, revision):
        """Read within the acceptance transaction; legacy attempts remain compatible."""
        if not self.messages.context(attempt):
            return None
        row = self.messages.latest_completion(attempt)
        if not row:
            return 'no_completion'
        if row['revision'] != revision:
            return 'completion_revision_stale'
        if row['inbox_seq'] != self.messages.inbox_seq(attempt):
            return 'inbox_changed'
        if self.messages.blockers(attempt):
            return 'blocked_messages'
        return None


def worker_protocol(task, ident, recipient, cli, state):
    return (f"\nExecution identity: {ident}; recipient: {recipient}; Task: {task.key}; "
                f"instruction revision: {task.instruction_revision}; state directory: {state}.\n"
                f"Common messaging CLI: {shlex.join(cli)}\n"
                "Your SCHEDULER_TASK/ATTEMPT/RECIPIENT environment supplies target flags. "
                "The first message is your assignment; a message payload `expect` object must be echoed in its applied report. "
                "At startup, natural work boundaries and before completion call `inbox`. "
                "For its current revision call `claim --revision REV`. A claim is delivery, not application. "
                "Read each directive and its current Task; do not apply old attempt/revision instructions. "
                "After applying it, write a nonempty JSON report file and call "
                "`processed --id ID --token TOKEN --revision REV --outcome applied --report-file PATH`, "
                "then `ack --id ID --token TOKEN --revision REV`. Use deferred/conflict with reasons when needed. "
                "If claim includes a processing_result, reuse it and ACK; do not repeat effects. "
                "For redelivery without a result, reconcile actual effects before repeating and pass "
                "`--reconciliation REASON` when recording the result. Never access the DB directly. Never call send or dismiss: those are coordinator-only operations. "
                "Only the designated Task owner changes Goal/Scope/Acceptance Criteria. Routine Current Result edits do not change instruction revision. "
                "After final Task updates, read inbox again and call "
                "`complete --id UNIQUE_RESULT_ID --revision REV --inbox-seq N --report-file PATH`. "
                "A stored message, applied ACK, worker completion submission and Task acceptance are distinct. "
                "Do not claim success with unapplied required messages. There is no push interrupt: you must poll.\n")
