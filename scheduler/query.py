"""Status projection of one ledger. Queries only: no tick, launch, message or Task effect.

The writer `Scheduler` delegates `status` here over its own connection; `watch`
uses `open_readonly`, so both show the same projection without the viewer
initializing, migrating or re-journaling the ledger.
"""
import dataclasses
import json

from .messaging import Mailbox
from .model import Catalog, Invalid
from .store import Store


class Query:
    def __init__(self, store, catalog, mailbox):
        self.store, self.catalog, self.mailbox = store, catalog, mailbox
        self.db = store.db

    def close(self):
        self.store.close()

    def cleanups(self):
        return [dict(r, detail=json.loads(r["detail"])) for r in
                self.db.execute("SELECT * FROM cleanups ORDER BY updated")]

    def assignment_view(self, row):
        """Stored, delivered, taken over and completed are separate facts."""
        view = dict(row)
        view['contract'] = json.loads(view['contract'])
        view['launches'] = []
        for launch in self.db.execute('SELECT * FROM assignment_launches WHERE assignment=?', (row['id'],)):
            attempt = self.db.execute('SELECT state FROM attempts WHERE id=?', (launch['attempt'],)).fetchone()
            message = self.db.execute('SELECT state,deliveries FROM messages WHERE id=?', (launch['message'],)).fetchone()
            result = self.mailbox.messages.result(launch['message'])
            view['launches'].append(dict(launch, attempt_state=attempt['state'],
                                         delivered=bool(message and message['deliveries']),
                                         taken_over=bool(message and message['state'] == 'acked' and result and result['outcome'] == 'applied'),
                                         completed=attempt['state'] == 'accepted'))
        return view

    def assignment(self, ident):
        return self.assignment_view(self.db.execute('SELECT * FROM assignments WHERE id=?', (ident,)).fetchone())

    def assignments(self):
        return [self.assignment_view(r) for r in self.db.execute('SELECT * FROM assignments ORDER BY seq')]

    def acceptance_blocker(self, active):
        if not active or active.state != 'awaiting_acceptance':
            return None
        context = self.db.execute('SELECT task_path FROM worker_context WHERE attempt=?', (active.id,)).fetchone()
        if not context:
            return None
        try:
            task = self.catalog.read(only_path=context['task_path']).get(active.task)
        except FileNotFoundError:
            return 'task_missing'
        except Invalid as exc:
            return 'task_invalid: ' + str(exc)
        if not task:
            return 'task_missing'
        reason = self.mailbox.acceptance_reason(active.id, task.instruction_revision)
        return reason or (None if task.accepted else 'task_not_accepted')

    def status(self):
        return {"acceptance_blocker": self.acceptance_blocker(self.store.active()),
                "attempts": [dataclasses.asdict(a) for a in self.store.attempts()],
                "cleanups": self.cleanups(),
                "assignments": self.assignments(),
                "messages": [dict(r) for r in self.db.execute('SELECT * FROM messages ORDER BY seq')],
                "worker_results": [dict(r) for r in self.db.execute('SELECT * FROM worker_results ORDER BY seq')],
                "plans": [dict(r) for r in self.db.execute("SELECT * FROM plans ORDER BY created")],
                "events": [dict(r) for r in self.db.execute("SELECT * FROM events ORDER BY created")],
                "projects": {p["id"]: self.store.get("project:" + p["id"]) for p in self.catalog.projects}}


def open_readonly(config, state):
    """Query an existing ledger through a SQLite mode=ro connection (see Store(readonly=True))."""
    catalog = Catalog(config)
    store = Store(state, readonly=True)
    try:
        return Query(store, catalog, Mailbox(store, catalog))
    except BaseException:
        store.close()
        raise
