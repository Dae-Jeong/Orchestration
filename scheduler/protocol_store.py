"""Storage of the message and reference protocols: named SQL over the shared ledger connection.

Operational methods return materialized rows (dicts), ids or nothing and own JSON encoding of
stored values. None of them begins, commits or rolls back: Mailbox/References own every
transaction, the order of writes within it, the recheck points and each clock reading (passed
in as `at`). The one exception is `RefStore.__init__`, see there.
"""
import json

AUDIT = 'INSERT INTO message_audit(message,action,detail,created) VALUES (?,?,?,?)'

REF_SCHEMA = '''
CREATE TABLE IF NOT EXISTS ref_events(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
  task TEXT NOT NULL, task_path TEXT NOT NULL, item TEXT NOT NULL, item_sha256 TEXT NOT NULL,
  sender TEXT NOT NULL, sender_exec TEXT NOT NULL, recipient TEXT NOT NULL, recipient_exec TEXT,
  reply_to TEXT, reply_sha256 TEXT, envelope TEXT NOT NULL,
  state TEXT NOT NULL, deliveries INTEGER NOT NULL DEFAULT 0, token TEXT, expires REAL,
  read_token TEXT, outcome TEXT, report TEXT, reconciliation TEXT, ack_token TEXT,
  reason TEXT, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ref_inbox ON ref_events(recipient, state, seq);
'''


def packed(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _one(row):
    return dict(row) if row else None


class MessageStore:
    """messages, processing_results, message_acks, worker_results and their message_audit rows."""

    def __init__(self, db):
        self.db = db

    def audit(self, message: str | None, action: str, detail: dict, at: float) -> None:
        self.db.execute(AUDIT, (message, action, packed(detail), at))

    def target(self, attempt: str) -> dict | None:
        """The attempt row joined with its worker recipient and Task path."""
        return _one(self.db.execute('SELECT a.*,c.recipient,c.task_path FROM attempts a JOIN worker_context c '
                                    'ON c.attempt=a.id WHERE a.id=?', (attempt,)).fetchone())

    def latest_attempt(self, task: str) -> str:
        return self.db.execute('SELECT id FROM attempts WHERE task=? ORDER BY rowid DESC LIMIT 1', (task,)).fetchone()['id']

    def context(self, attempt: str) -> dict | None:
        return _one(self.db.execute('SELECT * FROM worker_context WHERE attempt=?', (attempt,)).fetchone())

    def find(self, ident: str) -> dict | None:
        return _one(self.db.execute('SELECT * FROM messages WHERE id=?', (ident,)).fetchone())

    def result(self, ident: str) -> dict | None:
        """Recorded processing result with its report decoded."""
        row = self.db.execute('SELECT * FROM processing_results WHERE message=?', (ident,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result['report'] = json.loads(result['report'])
        return result

    def add(self, ident, task, project, attempt, recipient, revision, kind, payload: dict, required: bool,
            envelope: str, at: float) -> None:
        self.db.execute('''INSERT INTO messages(id,task,project,attempt,recipient,revision,kind,payload,
                           required,envelope,state,created) VALUES (?,?,?,?,?,?,?,?,?,?,'queued',?)''',
                        (ident, task, project, attempt, recipient, revision, kind, packed(payload),
                         int(required), envelope, at))

    def inbox_seq(self, attempt: str) -> int:
        return self.db.execute('SELECT coalesce(max(seq),0) FROM messages WHERE attempt=?', (attempt,)).fetchone()[0]

    def inbox(self, attempt: str, recipient: str) -> list[dict]:
        return [dict(r) for r in self.db.execute('SELECT * FROM messages WHERE attempt=? AND recipient=? ORDER BY seq',
                                                 (attempt, recipient)).fetchall()]

    def next(self, attempt: str, recipient: str) -> dict | None:
        """Oldest message of the recipient that is neither acked nor dismissed."""
        return _one(self.db.execute("SELECT * FROM messages WHERE attempt=? AND recipient=? AND state NOT IN "
                                    "('acked','dismissed') ORDER BY seq LIMIT 1", (attempt, recipient)).fetchone())

    def settle(self, ident: str, state: str, reason: str | None) -> None:
        """Set a final or held state; any lease ends."""
        self.db.execute('UPDATE messages SET state=?,reason=?,expires=NULL WHERE id=?', (state, reason, ident))

    def claim(self, ident: str, token: str, expires: float) -> None:
        self.db.execute("UPDATE messages SET state='claimed',token=?,expires=?,deliveries=deliveries+1 WHERE id=?",
                        (token, expires, ident))

    def add_result(self, ident: str, outcome: str, report: dict, reconciliation: str, at: float) -> None:
        self.db.execute('INSERT INTO processing_results VALUES (?,?,?,?,?)',
                        (ident, outcome, packed(report), reconciliation, at))

    def ack(self, ident: str) -> dict | None:
        return _one(self.db.execute('SELECT * FROM message_acks WHERE message=?', (ident,)).fetchone())

    def add_ack(self, ident: str, token: str, outcome: str, at: float) -> None:
        self.db.execute('INSERT INTO message_acks VALUES (?,?,?,?)', (ident, token, outcome, at))

    def blockers(self, attempt: str) -> list[str]:
        """Required messages of the attempt that are neither acked nor dismissed."""
        return [r[0] for r in self.db.execute("SELECT id FROM messages WHERE attempt=? AND required=1 AND state NOT IN "
                                              "('acked','dismissed') ORDER BY seq", (attempt,))]

    def completion(self, ident: str) -> dict | None:
        return _one(self.db.execute('SELECT * FROM worker_results WHERE id=?', (ident,)).fetchone())

    def latest_completion(self, attempt: str) -> dict | None:
        return _one(self.db.execute('SELECT * FROM worker_results WHERE attempt=? ORDER BY seq DESC LIMIT 1',
                                    (attempt,)).fetchone())

    def add_completion(self, ident, attempt, recipient, task, revision, inbox_seq: int, report: str, at: float) -> None:
        """`report` is the packed report the caller compared against an existing submission."""
        self.db.execute('INSERT INTO worker_results(id,attempt,recipient,task,revision,inbox_seq,report,created) '
                        'VALUES (?,?,?,?,?,?,?,?)', (ident, attempt, recipient, task, revision, inbox_seq, report, at))

    def assignment_revision(self, attempt: str) -> str | None:
        """Instruction revision of the attempt's newest assignment message."""
        row = self.db.execute("SELECT revision FROM messages WHERE attempt=? AND id LIKE 'assignment:%' ORDER BY seq DESC LIMIT 1",
                              (attempt,)).fetchone()
        return row['revision'] if row else None

    def unapplied_assignments(self, attempt: str, keep: str) -> list[str]:
        """Queued or held assignment message ids of the attempt other than `keep`."""
        return [r['id'] for r in self.db.execute(
            "SELECT id FROM messages WHERE attempt=? AND id LIKE 'assignment:%' AND id!=? AND state IN ('queued','held')",
            (attempt, keep)).fetchall()]


class RefStore:
    """ref_events and their `ref:`-addressed message_audit rows."""

    def __init__(self, db):
        """Adds the ref table when absent (additive DDL; legacy tables are untouched), at References()
        construction as before. SQLite `executescript` first commits any open transaction."""
        self.db = db
        db.executescript(REF_SCHEMA)

    def audit(self, ident: str, action: str, detail: dict, at: float) -> None:
        self.db.execute(AUDIT, ('ref:' + ident, 'ref.' + action, packed(detail), at))

    def attempt(self, ident: str) -> dict | None:
        return _one(self.db.execute('SELECT state,task FROM attempts WHERE id=?', (ident,)).fetchone())

    def find(self, ident: str) -> dict | None:
        return _one(self.db.execute('SELECT * FROM ref_events WHERE id=?', (ident,)).fetchone())

    def latest_question(self, task: str, item: str) -> dict:
        return dict(self.db.execute(
            "SELECT * FROM ref_events WHERE kind='question.opened' AND task=? AND item=? ORDER BY seq DESC LIMIT 1",
            (task, item)).fetchone())

    def add(self, ident, kind, task, task_path, item, item_sha256, sender, sender_exec, recipient, recipient_exec,
            reply_to, reply_sha256, envelope: str, at: float) -> None:
        self.db.execute('''INSERT INTO ref_events(id,kind,task,task_path,item,item_sha256,sender,sender_exec,
                           recipient,recipient_exec,reply_to,reply_sha256,envelope,state,created)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'queued',?)''',
                        (ident, kind, task, task_path, item, item_sha256, sender, sender_exec,
                         recipient, recipient_exec, reply_to, reply_sha256, envelope, at))

    def inbox(self, who: str, execution: str) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            'SELECT * FROM ref_events WHERE recipient=? AND (recipient_exec IS NULL OR recipient_exec=?) ORDER BY seq',
            (who, execution)).fetchall()]

    def pending(self, who: str, execution: str) -> list[dict]:
        """Events addressed to the participant/execution that are neither acked nor dismissed, oldest first."""
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM ref_events WHERE recipient=? AND (recipient_exec IS NULL OR recipient_exec=?) "
            "AND state NOT IN ('acked','dismissed') ORDER BY seq", (who, execution))]

    def settle(self, ident: str, state: str, reason: str) -> None:
        """Set held or dismissed; any lease ends."""
        self.db.execute('UPDATE ref_events SET state=?,reason=?,expires=NULL WHERE id=?', (state, reason, ident))

    def claim(self, ident: str, token: str, expires: float) -> None:
        self.db.execute("UPDATE ref_events SET state='claimed',token=?,expires=?,deliveries=deliveries+1 WHERE id=?",
                        (token, expires, ident))

    def mark_read(self, ident: str, token: str) -> None:
        self.db.execute('UPDATE ref_events SET read_token=? WHERE id=?', (token, ident))

    def record(self, ident: str, outcome: str, report: dict, reconciliation: str) -> None:
        self.db.execute('UPDATE ref_events SET outcome=?,report=?,reconciliation=? WHERE id=?',
                        (outcome, packed(report), reconciliation, ident))

    def ack(self, ident: str, state: str, token: str, reason: str | None) -> None:
        self.db.execute('UPDATE ref_events SET state=?,ack_token=?,expires=NULL,reason=? WHERE id=?',
                        (state, token, reason, ident))

    def replies(self, ident: str) -> list[dict]:
        return [dict(r) for r in self.db.execute('SELECT * FROM ref_events WHERE reply_to=? ORDER BY seq',
                                                 (ident,)).fetchall()]
