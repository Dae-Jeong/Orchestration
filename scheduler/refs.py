"""Task-item reference events: question/answer/completed/blocked exchanged by reference.

The Markdown Task item is the canonical body. SQLite stores only the reference envelope
(ids, Task path, item id, item SHA-256, sender/recipient execution identities, reply link)
and the delivery/processing/ACK state. Nothing here edits Task files.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import uuid

from .messaging import nonempty
from .model import Invalid, digest
from .protocol_store import RefStore, packed
from .store import EXECUTING_STATES

KINDS = ('question.opened', 'question.answered', 'work.completed', 'work.blocked')
ITEM_ID = r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}'
OPEN = re.compile(r'<!-- item:(' + ITEM_ID + r') -->[ \t]*\r?')
CLOSE = re.compile(r'<!-- /item:(' + ITEM_ID + r') -->[ \t]*\r?')
MARKER = re.compile(r'^[ \t]*<!--\s*/?\s*item\s*:', re.I)
PARTICIPANT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,199}')
DONE = ('acked', 'dismissed')


def items(text):
    """Parse uniquely bounded items. Body = exact text between the marker lines."""
    found, current, offset = {}, None, 0
    for line in text.splitlines(keepends=True):
        bare = line.rstrip('\n')
        start, offset = offset, offset + len(line)
        if not MARKER.match(bare):
            continue
        opened, closed = OPEN.fullmatch(bare), CLOSE.fullmatch(bare)
        if opened:
            if current:
                raise Invalid(f'nested item marker inside {current[0]}')
            if opened.group(1) in found:
                raise Invalid(f'duplicate item id: {opened.group(1)}')
            current = (opened.group(1), offset)
        elif closed:
            if not current or closed.group(1) != current[0]:
                raise Invalid(f'unbalanced item close marker: {closed.group(1)}')
            found[current[0]] = text[current[1]:start]
            current = None
        else:
            raise Invalid('malformed item marker: ' + bare.strip()[:80])
    if current:
        raise Invalid(f'unclosed item: {current[0]}')
    return found


def sha(body):
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def participant(value, label):
    if not isinstance(value, str) or not PARTICIPANT.fullmatch(value):
        raise Invalid(f'{label} must match {PARTICIPANT.pattern}')


class References:
    def __init__(self, store, catalog, max_deliveries, clock=time.time):
        self.store, self.catalog, self.clock = store, catalog, clock
        self.max_deliveries = max_deliveries
        self.events = RefStore(store.db)

    # ---- canonical Markdown -------------------------------------------------
    def locate(self, task, path):
        """Resolve a Task path that is a direct, non-symlink child of its project's tasks dir."""
        if not isinstance(task, str) or task.count('/') != 1:
            raise Invalid('task must be PROJECT/TASK_ID')
        project = next((p for p in self.catalog.projects if p['id'] == task.split('/')[0]), None)
        if project is None:
            raise Invalid('project is not configured')
        raw = Path(path)
        if raw.is_symlink():
            raise Invalid('Task path must not be a symlink')
        try:
            resolved = raw.resolve(strict=True)
        except OSError as exc:
            raise Invalid('Task file not found') from exc
        if resolved.parent != Path(project['tasks']) or resolved.suffix != '.md':
            raise Invalid('Task path is outside the configured project task directory')
        if task not in self.catalog.read(only_path=str(resolved)):
            raise Invalid('Task id/project does not match the file')
        return str(resolved)

    def item(self, task, path, item):
        path = self.locate(task, path)
        try:
            text = Path(path).read_bytes().decode('utf-8')
        except UnicodeDecodeError as exc:
            raise Invalid('Task is not valid UTF-8') from exc
        found = items(text)
        if item not in found:
            raise Invalid(f'item not found: {item}')
        body = found[item]
        if not body.strip():
            raise Invalid('item body is empty')
        return dict(task=task, task_path=path, item=item, sha256=sha(body), body=body)

    def stale(self, row):
        """(reason, current item) from ONE read of the file; reason is None when still current.

        The returned body is exactly the text whose hash was compared, so callers never
        hand out a second, unverified read.
        """
        try:
            current = self.item(row['task'], row['task_path'], row['item'])
        except Invalid as exc:
            return 'stale_reference: ' + str(exc), None
        if current['sha256'] != row['item_sha256']:
            return 'stale_reference: item content changed since publish', None
        if row['reply_to']:
            question = self.row(row['reply_to'])
            if question['kind'] == 'question.opened':
                try:
                    asked = self.item(question['task'], question['task_path'], question['item'])
                except Invalid as exc:
                    return 'stale_answer: ' + str(exc), None
                if asked['sha256'] != row['reply_sha256']:
                    return 'stale_answer: question item changed after it was answered', None
                if self.events.latest_question(question['task'], question['item'])['id'] != question['id']:
                    return 'stale_answer: question was reopened by a newer event', None
        return None, current

    # ---- ledger helpers -----------------------------------------------------
    def pin(self):
        revision = digest(self.catalog.config)
        stored = self.store.get('config_revision')
        if stored and stored != revision:
            raise Invalid('configuration does not match the execution ledger')
        if not stored:
            self.store.set('config_revision', revision)

    def identity(self, who, execution, task=None):
        participant(who, 'participant'), participant(execution, 'execution identity')
        attempt = os.environ.get('SCHEDULER_ATTEMPT')
        if attempt and execution != 'scheduler:' + attempt:
            raise Invalid('inside a scheduler attempt the execution identity must be scheduler:<attempt>')
        if execution.startswith('scheduler:'):
            row = self.events.attempt(execution[10:])
            if not row or row['state'] not in EXECUTING_STATES:
                raise Invalid('scheduler execution identity is not a live attempt')
            if task is not None and row['task'] != task:
                raise Invalid('scheduler attempt does not own this Task')

    def row(self, ident):
        row = self.events.find(ident)
        if row is None:
            raise Invalid('unknown event id')
        return row

    def view(self, row):
        keep = ('seq', 'id', 'kind', 'task', 'task_path', 'item', 'item_sha256', 'sender', 'sender_exec',
                'recipient', 'recipient_exec', 'reply_to', 'reply_sha256', 'state', 'deliveries', 'expires', 'outcome', 'reason', 'reconciliation')
        result = {k: row[k] for k in keep}
        result['processing_result'] = None if row['outcome'] is None else dict(
            outcome=row['outcome'], report=json.loads(row['report']))
        result['needs_reconciliation'] = row['deliveries'] > 1 and row['outcome'] is None
        return result

    def mine(self, row, who, execution):
        if row['recipient'] != who or row['recipient_exec'] not in (None, execution):
            raise Invalid('event is not addressed to this participant/execution')

    def claimed(self, ident, who, execution, token):
        row = self.row(ident)
        self.mine(row, who, execution)
        if row['state'] != 'claimed' or row['token'] != token or row['expires'] <= self.clock():
            raise Invalid('expired or superseded claim token')
        return row

    def hold(self, row, reason):
        self.events.settle(row['id'], 'held', reason)
        self.events.audit(row['id'], 'held', {'reason': reason}, self.clock())

    # ---- operations ---------------------------------------------------------
    def publish(self, ident, kind, task, path, item, who, execution, to, to_exec=None,
                reply_to=None, expected_sha=None):
        nonempty(ident, 'event id')
        if kind not in KINDS:
            raise Invalid('kind must be one of ' + ', '.join(KINDS))
        self.identity(who, execution, task)
        participant(to, 'recipient')
        if to_exec is not None:
            participant(to_exec, 'recipient execution identity')
        with self.store.transaction():
            self.pin()
            current = self.item(task, path, item)
            if expected_sha is not None and expected_sha != current['sha256']:
                raise Invalid('item changed since you read it; reread and publish the current hash')
            reply_sha = None
            if kind == 'question.answered' and not reply_to:
                raise Invalid('question.answered requires --reply-to QUESTION_EVENT_ID')
            if kind == 'question.opened' and reply_to:
                raise Invalid('question.opened cannot reply to another event')
            if reply_to:
                parent = self.row(reply_to)
                if parent['task'] != task or parent['task_path'] != current['task_path']:
                    raise Invalid('reply must reference an event on the same Task')
                if kind == 'question.answered':
                    if parent['kind'] != 'question.opened' or item == parent['item']:
                        raise Invalid('answer must be a new item replying to a question.opened event')
                    if (who, to) != (parent['recipient'], parent['sender']) or \
                            parent['recipient_exec'] not in (None, execution):
                        raise Invalid('only the question recipient may answer, and only to its sender')
                    if to_exec not in (None, parent['sender_exec']):
                        raise Invalid('answer must address the asking execution')
                    to_exec = parent['sender_exec']
                    reply_sha = parent['item_sha256']
            envelope = packed(dict(id=ident, kind=kind, task=task, task_path=current['task_path'], item=item,
                                   item_sha256=current['sha256'], sender=who, sender_exec=execution,
                                   recipient=to, recipient_exec=to_exec, reply_to=reply_to, reply_sha256=reply_sha))
            old = self.events.find(ident)
            if old:
                if old['envelope'] != envelope:
                    raise Invalid('event id reused with different content (or the item changed since the first publish)')
                return dict(stored=True, duplicate=True, event=self.view(old))
            if kind == 'question.answered':
                asked = self.item(parent['task'], parent['task_path'], parent['item'])
                if asked['sha256'] != parent['item_sha256'] or \
                        self.events.latest_question(parent['task'], parent['item'])['id'] != parent['id']:
                    raise Invalid('question changed or was reopened; answer the current question event')
            self.events.add(ident, kind, task, current['task_path'], item, current['sha256'], who, execution,
                            to, to_exec, reply_to, reply_sha, envelope, self.clock())
            stored = self.row(ident)
            reason = self.stale(stored)[0]
            if reason:  # re-read just before COMMIT; raising rolls the insert back
                raise Invalid('reference changed during publish: ' + reason)
            self.events.audit(ident, 'stored', {'sender': who, 'sender_exec': execution, 'kind': kind}, self.clock())
            result = dict(stored=True, duplicate=False, event=self.view(stored))
        return result  # durable storage only; not delivery, reading or processing

    def inbox(self, who, execution):
        participant(who, 'participant')
        with self.store.transaction(write=False):
            rows = self.events.inbox(who, execution)
            return dict(participant=who, execution=execution, events=[self.view(r) for r in rows])

    def claim(self, who, execution, lease=60):
        if not isinstance(lease, (float, int)) or isinstance(lease, bool) or not math.isfinite(lease) or lease <= 0:
            raise Invalid('lease must be finite and positive')
        self.identity(who, execution)
        with self.store.transaction():
            self.pin()
            rows = self.events.pending(who, execution)
            heads, held, busy = {}, [], []
            for r in rows:  # FIFO per source execution stream; streams are independent
                heads.setdefault((r['sender'], r['sender_exec']), r)
            for row in sorted(heads.values(), key=lambda r: r['seq']):
                if row['state'] == 'held':
                    held.append(row['id'])
                    continue
                if row['state'] == 'claimed' and row['expires'] > self.clock():
                    busy.append(row['id'])
                    continue
                if row['outcome'] is None:
                    reason = self.stale(row)[0]
                    if reason is None and row['deliveries'] >= self.max_deliveries:
                        reason = 'delivery limit reached; no automatic processing retry'
                    if reason:
                        self.hold(row, reason)
                        held.append(row['id'])
                        continue
                token = str(uuid.uuid4())
                self.events.claim(row['id'], token, self.clock() + lease)
                self.events.audit(row['id'], 'claimed', {'token': token, 'by': who, 'exec': execution}, self.clock())
                return dict(state='claimed', token=token, event=self.view(self.row(row['id'])), held=held, busy=busy)
            return dict(state='empty', held=held, busy=busy)

    def wait(self, who, execution, timeout, lease=60, interval=1.0, sleep=time.sleep, now=time.monotonic):
        """Bounded poll. Each attempt is a short transaction; sleeping holds no DB transaction."""
        if not (isinstance(timeout, (int, float)) and math.isfinite(timeout) and 0 <= timeout <= 86400):
            raise Invalid('timeout must be between 0 and 86400 seconds')
        if not (isinstance(interval, (int, float)) and math.isfinite(interval) and interval > 0):
            raise Invalid('interval must be positive')
        deadline = now() + timeout
        while True:
            result = self.claim(who, execution, lease)
            remaining = deadline - now()
            if result['state'] == 'claimed' or remaining <= 0:
                break
            sleep(min(interval, remaining))
        if result['state'] != 'claimed':
            result = dict(result, state='timeout', timeout=timeout,
                          note='timeout is not success, failure or a reason to re-run')
        return result

    def read(self, ident, who, execution, token):
        with self.store.transaction():
            row = self.claimed(ident, who, execution, token)
            reason, current = self.stale(row)
            if reason and row['outcome'] is not None:
                # Recovery after a recorded result: only the historical receipt, never new text.
                return dict(state='historical', id=ident, reason=reason,
                            processing_result=self.view(row)['processing_result'])
            if reason:
                self.hold(row, reason)
                return dict(state='held', id=ident, reason=reason)
            if row['outcome'] is not None:
                return dict(state='historical', id=ident, reason='processing already recorded',
                            processing_result=self.view(row)['processing_result'])
            self.events.mark_read(ident, token)
            self.events.audit(ident, 'read', {'token': token, 'sha256': current['sha256']}, self.clock())
            result = dict(state='read', event=self.view(self.row(ident)), sha256=current['sha256'], body=current['body'])
            if row['reply_to']:
                parent = self.row(row['reply_to'])
                result['reply_to'] = dict(id=parent['id'], kind=parent['kind'], item=parent['item'],
                                          item_sha256=parent['item_sha256'])
        return result

    def processed(self, ident, who, execution, token, outcome, report, reconciliation=''):
        if outcome not in ('applied', 'deferred', 'conflict') or not isinstance(report, dict) or not report:
            raise Invalid('processing requires applied/deferred/conflict and a nonempty JSON report')
        with self.store.transaction():
            row = self.claimed(ident, who, execution, token)
            if row['outcome'] is not None:
                if row['outcome'] != outcome or json.loads(row['report']) != report:
                    raise Invalid('processing result already recorded with different content')
                return self.view(row)['processing_result']
            if outcome == 'applied' and row['read_token'] != token:
                raise Invalid('read the verified item with this claim before recording applied')
            reason = self.stale(row)[0]
            if reason:  # the text you read is no longer the reference; never certify it
                self.hold(row, reason)
                return dict(state='held', id=ident, reason=reason)
            if row['deliveries'] > 1:
                nonempty(reconciliation, 'redelivery reconciliation')
            self.events.record(ident, outcome, report, reconciliation)
            self.events.audit(ident, 'processing_recorded', {'outcome': outcome, 'token': token}, self.clock())
            return self.view(self.row(ident))['processing_result']

    def ack(self, ident, who, execution, token):
        with self.store.transaction():
            row = self.row(ident)
            self.mine(row, who, execution)
            if row['ack_token'] is not None and row['ack_token'] == token:
                return dict(acknowledged=True, duplicate=True, state=row['state'],
                            processing_result=self.view(row)['processing_result'])
            row = self.claimed(ident, who, execution, token)
            if row['outcome'] is None:
                raise Invalid('record processing result before ACK; receipt is insufficient')
            state = 'acked' if row['outcome'] == 'applied' else 'held'
            self.events.ack(ident, state, token, None if state == 'acked' else row['outcome'])
            self.events.audit(ident, 'acknowledged', {'outcome': row['outcome'], 'token': token}, self.clock())
            return dict(acknowledged=True, duplicate=False, state=state,
                        processing_result=self.view(self.row(ident))['processing_result'],
                        note='ACK records processing; it does not resolve the question or complete the Task')

    def dismiss(self, ident, who, execution, reason):
        nonempty(reason, 'dismissal reason')
        with self.store.transaction():
            row = self.row(ident)
            if (who, execution) != (row['sender'], row['sender_exec']) and not (
                    who == row['recipient'] and row['recipient_exec'] in (None, execution)):
                raise Invalid('only the sender or recipient execution may dismiss an event')
            if row['state'] == 'acked':
                raise Invalid('cannot dismiss an applied ACK')
            if row['state'] == 'claimed' and row['expires'] > self.clock():
                raise Invalid('claim still live; coordinate before dismissal')
            self.events.settle(ident, 'dismissed', reason)
            self.events.audit(ident, 'dismissed', {'by': who, 'exec': execution, 'reason': reason}, self.clock())
        return dict(state='dismissed', id=ident, reason=reason)

    def show(self, ident):
        with self.store.transaction(write=False):
            row = self.row(ident)
            return dict(event=self.view(row), replies=[self.view(r) for r in self.events.replies(ident)])
