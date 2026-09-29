"""Single-host SQLite execution ledger plus OS lock for external-call serialization."""
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
from pathlib import Path
import sqlite3
import time

from .assignment import Assignment


SLOT_STATES = ('launching', 'running', 'unknown', 'awaiting_acceptance')
EXECUTING_STATES = SLOT_STATES[:3]

# Terminal cleanup states. `closing` is a durable intent; `unconfirmed` is retried after
# re-verifying ownership until CLEANUP_TRIES, then `failed`. Withheld/failed need an operator.
CLEANUP_DONE = ("closed", "already_closed", "not_applicable")
CLEANUP_FINAL = CLEANUP_DONE + ("withheld", "failed")
CLEANUP_TRIES = 3


SCHEMA = '''
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts(
  id TEXT PRIMARY KEY, task TEXT NOT NULL, project TEXT NOT NULL,
  revision TEXT NOT NULL, adapter TEXT NOT NULL, state TEXT NOT NULL,
  handle TEXT, created REAL NOT NULL, detail TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_slot ON attempts((1))
  WHERE state IN ('launching','running','unknown','awaiting_acceptance');
CREATE TABLE IF NOT EXISTS events(
  id TEXT PRIMARY KEY, attempt TEXT, kind TEXT NOT NULL, payload TEXT NOT NULL,
  disposition TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS plans(
  revision TEXT PRIMARY KEY, request TEXT NOT NULL, response TEXT,
  state TEXT NOT NULL, detail TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS worker_context(
  attempt TEXT PRIMARY KEY, recipient TEXT NOT NULL, task_path TEXT NOT NULL, protocol INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS messages(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
  task TEXT NOT NULL, project TEXT NOT NULL, attempt TEXT NOT NULL,
  recipient TEXT NOT NULL, revision TEXT NOT NULL, kind TEXT NOT NULL,
  payload TEXT NOT NULL, required INTEGER NOT NULL, envelope TEXT NOT NULL,
  state TEXT NOT NULL, deliveries INTEGER NOT NULL DEFAULT 0,
  token TEXT, expires REAL, reason TEXT, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS inbox_target ON messages(attempt,recipient,seq);
CREATE TABLE IF NOT EXISTS processing_results(
  message TEXT PRIMARY KEY, outcome TEXT NOT NULL, report TEXT NOT NULL,
  reconciliation TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS message_acks(
  message TEXT PRIMARY KEY, token TEXT NOT NULL, outcome TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS worker_results(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
  attempt TEXT NOT NULL, recipient TEXT NOT NULL, task TEXT NOT NULL,
  revision TEXT NOT NULL, inbox_seq INTEGER NOT NULL, report TEXT NOT NULL,
  created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS assignments(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, task TEXT NOT NULL,
  origin TEXT NOT NULL, contract TEXT NOT NULL, state TEXT NOT NULL, reason TEXT,
  created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS assignment_launches(
  attempt TEXT PRIMARY KEY, assignment TEXT NOT NULL, message TEXT NOT NULL,
  task_sha256 TEXT NOT NULL, prompt_sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS message_audit(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT, action TEXT NOT NULL,
  detail TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS cleanups(
  attempt TEXT PRIMARY KEY, state TEXT NOT NULL, tries INTEGER NOT NULL,
  detail TEXT NOT NULL, updated REAL NOT NULL);
'''


@dataclass(frozen=True)
class Attempt:
    """One `attempts` row. Fields follow the column order, so `dataclasses.asdict` is its status JSON form."""
    id: str
    task: str
    project: str
    revision: str
    adapter: str
    state: str
    handle: str | None
    created: float
    detail: str | None


class Busy(RuntimeError):
    pass


class Unsupported(RuntimeError):
    """The state path is not a ledger this reader can project; nothing is created or migrated."""


LEDGER = "ledger.sqlite3"


def schema_columns():
    """{table: columns} defined by SCHEMA, derived from the DDL itself rather than a second list."""
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(SCHEMA)
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t: [c[1] for c in db.execute(f"PRAGMA table_info({t})")] for t in tables}
    finally:
        db.close()


def verify_schema(db, path):
    """Raise Unsupported when an existing ledger lacks any table/column the current SCHEMA defines."""
    present = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    expected = schema_columns()
    tables = sorted(t for t in expected if t not in present)
    columns = sorted(f"{t}.{c}" for t, cols in expected.items() if t in present
                     for c in set(cols) - {r[1] for r in db.execute(f"PRAGMA table_info({t})")})
    if not tables and not columns:
        return
    foreign = len(tables) == len(expected)
    kind = "not a scheduler ledger" if foreign else "older or incomplete ledger schema"
    detail = "; ".join(filter(None, ["missing tables: " + ", ".join(tables) if tables else "",
                                     "missing columns: " + ", ".join(columns) if columns else ""]))
    hint = "check --state" if foreign else "check --state; only the scheduler writer (run/tick) initializes a ledger"
    raise Unsupported(f"{kind} at {path} ({detail}); the viewer does not migrate: {hint}")


class Store:
    def __init__(self, directory, readonly=False):
        """Writer by default. `readonly=True` opens an existing ledger with SQLite mode=ro:
        no directory, schema, migration or journal-mode change, and SQLite rejects every write."""
        self.root = Path(directory).resolve()
        if readonly:
            self.db = self._open_readonly(self.root / LEDGER)
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / LEDGER, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript(SCHEMA)
        except BaseException:
            self.db.close()
            raise

    @staticmethod
    def _open_readonly(path):
        if not path.is_file():
            raise Unsupported(f"state ledger not found: {path} (nothing was created)")
        # Ordinary SQLite read-only locking. For a WAL ledger SQLite itself may create its
        # -wal/-shm read-lock files; the database file, schema and journal mode stay unchanged.
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            verify_schema(db, path)
        except BaseException:
            db.close()
            raise
        return db

    @contextmanager
    def transaction(self, write=True):
        self.db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            raise

    @contextmanager
    def lock(self):
        with (self.root / "scheduler.lock").open("a+") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Busy("another scheduler owns the tick") from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.db.execute("INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(value)))

    def attempts(self) -> list[Attempt]:
        return [Attempt(**r) for r in self.db.execute("SELECT * FROM attempts ORDER BY rowid")]

    def active(self) -> Attempt | None:
        return self._attempt("SELECT * FROM attempts WHERE state IN (?,?,?,?)", SLOT_STATES)

    def change(self, attempt, state, detail=None, handle=None):
        self.db.execute("UPDATE attempts SET state=?,detail=?,handle=coalesce(?,handle) WHERE id=?",
                        (state, detail, handle, attempt))

    def event(self, ident, attempt, kind, payload, disposition):
        return self.db.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?)",
                               (ident, attempt, kind, json.dumps(payload), disposition, time.time())).rowcount

    # Named storage facts for the scheduler flow. None of these begins or commits a
    # transaction: the caller owns the transaction and the step order.

    def _one(self, sql: str, params: tuple) -> dict | None:
        row = self.db.execute(sql, params).fetchone()
        return dict(row) if row else None

    def find_event(self, ident: str) -> dict | None:
        return self._one("SELECT * FROM events WHERE id=?", (ident,))

    def _attempt(self, sql: str, params: tuple) -> Attempt | None:
        row = self._one(sql, params)
        return Attempt(**row) if row else None

    def attempt(self, ident: str) -> Attempt | None:
        return self._attempt("SELECT * FROM attempts WHERE id=?", (ident,))

    def latest(self, task: str) -> Attempt | None:
        """Newest attempt of a Task by ledger insertion order."""
        return self._attempt("SELECT * FROM attempts WHERE task=? ORDER BY rowid DESC LIMIT 1", (task,))

    def add_attempt(self, ident: str, task: str, project: str, revision: str, adapter: str) -> None:
        self.db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,'launching',NULL,?,NULL)",
                        (ident, task, project, revision, adapter, time.time()))

    def context(self, attempt: str) -> dict | None:
        return self._one("SELECT * FROM worker_context WHERE attempt=?", (attempt,))

    def add_context(self, attempt: str, recipient: str, task_path: str) -> None:
        self.db.execute("INSERT INTO worker_context VALUES (?,?,?,1)", (attempt, recipient, task_path))

    def cleanups(self) -> dict[str, dict]:
        return {r["attempt"]: dict(r) for r in self.db.execute("SELECT * FROM cleanups")}

    def save_cleanup(self, attempt: str, state: str, tries: int, detail: dict) -> None:
        self.db.execute("INSERT INTO cleanups VALUES (?,?,?,?,?) ON CONFLICT(attempt) DO UPDATE SET "
                        "state=excluded.state,tries=excluded.tries,detail=excluded.detail,updated=excluded.updated",
                        (attempt, state, tries, json.dumps(detail), time.time()))

    def plan(self, revision: str) -> dict | None:
        return self._one("SELECT * FROM plans WHERE revision=?", (revision,))

    def add_plan(self, revision: str, request: dict, state: str) -> None:
        self.db.execute("INSERT INTO plans VALUES (?,?,NULL,?,NULL,?)",
                        (revision, json.dumps(request), state, time.time()))

    def accept_plan(self, revision: str, response: dict) -> None:
        self.db.execute("UPDATE plans SET response=?,state='accepted',detail=NULL WHERE revision=?",
                        (json.dumps(response), revision))

    def reject_plan(self, revision: str, detail: str) -> None:
        self.db.execute("UPDATE plans SET state='rejected',detail=? WHERE revision=?", (detail, revision))

    def assignment(self, ident: str) -> Assignment | None:
        row = self._one("SELECT contract FROM assignments WHERE id=?", (ident,))
        return Assignment.from_record(json.loads(row["contract"])) if row else None

    def open_assignment(self, task: str) -> str | None:
        """Id of the Task's pending or launched explicit assignment."""
        row = self._one("SELECT id FROM assignments WHERE task=? AND origin='explicit' AND state IN ('pending','launched')",
                        (task,))
        return row["id"] if row else None

    def open_assignments(self) -> list[Assignment]:
        return [Assignment.from_record(json.loads(r["contract"])) for r in self.db.execute(
            "SELECT contract FROM assignments WHERE origin='explicit' AND state IN ('pending','launched') ORDER BY seq").fetchall()]

    def reserved(self) -> set[str]:
        """Tasks held back from default selection by an open or held explicit assignment."""
        return {r["task"] for r in self.db.execute(
            "SELECT task FROM assignments WHERE origin='explicit' AND state IN ('pending','launched','held')")}

    def add_assignment(self, contract: Assignment, origin: str, state: str, existing_ok: bool = False) -> None:
        verb = "INSERT OR IGNORE" if existing_ok else "INSERT"
        self.db.execute(f"{verb} INTO assignments(id,task,origin,contract,state,created) VALUES (?,?,?,?,?,?)",
                        (contract.id, contract.task, origin, json.dumps(contract.record(), sort_keys=True), state,
                         time.time()))

    def set_assignment(self, ident: str, state: str, reason: str | None) -> None:
        self.db.execute("UPDATE assignments SET state=?,reason=? WHERE id=?", (state, reason, ident))

    def launch(self, attempt: str) -> dict | None:
        return self._one("SELECT * FROM assignment_launches WHERE attempt=?", (attempt,))

    def launched(self, assignment: str) -> set[str]:
        """Attempt ids launched for an assignment."""
        return {r["attempt"] for r in self.db.execute(
            "SELECT attempt FROM assignment_launches WHERE assignment=?", (assignment,)).fetchall()}

    def add_launch(self, attempt: str, assignment: str, message: str, task_sha: str, prompt_sha: str) -> None:
        self.db.execute("INSERT INTO assignment_launches VALUES (?,?,?,?,?)",
                        (attempt, assignment, message, task_sha, prompt_sha))

    def close(self):
        self.db.close()
