"""Deterministic ticks, durable planner requests and conservative recovery."""
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

from . import adapters, assignment, planner
from .model import Catalog, Invalid, digest, ordered
from .messaging import Mailbox, worker_protocol
from .query import Query
from .store import CLEANUP_DONE, CLEANUP_FINAL, Store
from .validation import cleanup_state, event_state, explicit_state, launchable
from .worker import atomic_json


class Scheduler:
    def __init__(self, config, state):
        self.catalog = Catalog(config)
        self.store = Store(state)
        self.mailbox = Mailbox(self.store, self.catalog)
        self.query = Query(self.store, self.catalog, self.mailbox)
        self.orca = self.catalog.config.get("orca_command", "orca")

    def close(self):
        self.store.close()

    def _event(self, ident, attempt, kind, payload):
        with self.store.transaction():
            state = event_state(self.store.find_event(ident), self.store.active(), attempt, kind, payload)
            fresh = self.store.event(ident, attempt, kind, payload, "applied" if state else "stale")
            if fresh and state:
                self.store.change(attempt, state, json.dumps(payload))

    def event(self, ident, attempt, kind, payload):
        with self.store.lock():
            self._event("external:" + ident, attempt, kind, payload)

    def collect(self, tasks):
        attempt = self.store.active()
        if not attempt:
            return
        folder = self.store.root / "attempts" / attempt.id
        for kind in ("started", "exited"):
            receipt = folder / f"{kind}.json"
            if receipt.exists():
                payload = json.loads(receipt.read_text())
                if payload.get("attempt") != attempt.id:
                    raise Invalid("receipt attempt mismatch")
                self._event(attempt.id + ":" + kind, attempt.id, kind, payload)
        attempt = self.store.active()
        if attempt and attempt.state == "awaiting_acceptance":
            task = tasks.get(attempt.task)
            if task and task.accepted and task.revision != attempt.revision:
                with self.store.transaction():
                    # Serialize with sends/results and re-read the target at acceptance.
                    task = self.catalog.read(only_path=task.path).get(task.key)
                    if not task or not task.accepted or self.mailbox.acceptance_reason(attempt.id, task.instruction_revision) is not None:
                        return
                    self.store.change(attempt.id, "accepted", task.revision)
                    self.store.event(attempt.id + ":accepted", attempt.id, "accepted",
                                     {"task_revision": task.revision, "evidence": task.evidence}, "applied")

    def cleanup(self):
        """Close terminals of accepted attempts, recorded separately from acceptance.

        Runs under the tick lock, outside the acceptance transaction and only for
        attempts that are accepted and have an exit receipt. A durable `closing` intent
        precedes each external call; a restart re-verifies ownership instead of assuming
        either outcome. Final rows are never retried, so restarts and repeated ticks do
        not close twice.
        """
        rows = self.store.cleanups()
        for attempt in self.store.attempts():
            row = rows.get(attempt.id)
            if attempt.state != "accepted" or (row and row["state"] in CLEANUP_FINAL):
                continue
            folder = self.store.root / "attempts" / attempt.id
            if not (folder / "exited.json").exists():
                # No exit proof: the worker may still run, so its terminal stays open.
                continue
            tries = (row["tries"] if row else 0) + 1
            with self.store.transaction():
                self.store.save_cleanup(attempt.id, "closing", tries, {"detail": "verifying ownership before close"})
            result = adapters.close(attempt.adapter, attempt.handle, folder, self.orca)
            state = cleanup_state(result["outcome"], tries)
            with self.store.transaction():
                self.store.save_cleanup(attempt.id, state, tries, result)
                self.store.event(f"{attempt.id}:cleanup:{tries}", attempt.id, "cleanup",
                                 dict(result, state=state, tries=tries, handle=attempt.handle),
                                 "applied" if state in CLEANUP_DONE else state)

    def _projection(self, tasks):
        # Status/evidence/result edits for a normal completion do not ask the planner.
        latest = {a.task: a for a in self.store.attempts()}
        def availability(task):
            # Worker bookkeeping after its launch, including a failed/retry attempt,
            # is not a priority decision. Actual launch eligibility is checked in tick.
            owned = latest.get(task.key)
            return task.status == "ready" or (task.status in ("active", "review") and
                bool(owned and owned.state != "accepted"))
        return {k: dict(t.planning(), runnable=availability(t)) for k, t in tasks.items()
                if not t.accepted and t.status != "cancelled"}

    def plan(self, tasks):
        current = self._projection(tasks)
        previous = self.store.get("catalog")
        trigger = planner.reason(previous, current, tasks)
        old_order = self.store.get("order", [])
        revision = digest(current)
        if trigger:
            request = dict(revision=revision, reason=trigger, tasks=current,
                           projects=[p["id"] for p in self.catalog.projects],
                           previous_order=old_order,
                           instruction="Return JSON {revision, order}; every pending key exactly once; dependencies first. No tools, commands, Task edits or prose.")
            row = self.store.plan(revision)
            if row is None:
                command = self.catalog.config.get("planner_command")
                self.store.add_plan(revision, request, "calling" if command else "needs_planner")
                if not command:
                    return None
                try:
                    response = planner.invoke(command, request, self.catalog.config.get("planner_timeout", 60))
                    order = planner.validate(response, request, tasks)
                    # Scope must still match after a slow LLM call.
                    if self._projection(self.catalog.read()) != current:
                        raise Invalid("catalog changed during planning")
                    self.store.accept_plan(revision, response)
                except Exception as exc:
                    self.store.reject_plan(revision, str(exc))
                    return None
            elif row["state"] == "accepted":
                order = planner.validate(json.loads(row["response"]), request, tasks)
            else:
                # A crash, timeout or invalid response is never an automatic LLM retry.
                return None
        else:
            pending = {k: tasks[k] for k in current}
            # Preserve the approved order through ordinary completions.
            order = [k for k in old_order if k in pending]
            additions = [k for k in ordered(pending) if k not in order]
            if additions:
                order = ordered(pending)
        # One commit: an interruption leaves no partial metadata, so the next tick re-plans
        # and reuses the accepted plan row instead of falling back to priority order.
        with self.store.transaction():
            self.store.set("catalog", current)
            self.store.set("order", order)
            for p in self.catalog.projects:
                self.store.set("project:" + p["id"], {"revision": digest({k: v for k, v in current.items() if v["project"] == p["id"]}),
                                                        "order": [k for k in order if k.startswith(p["id"] + "/")]})
        return order

    def approve_plan(self, response):
        """Accept a manually returned high-level plan, still subject to all checks."""
        with self.store.lock():
            tasks = self.catalog.read()
            revision = digest(self._projection(tasks))
            row = self.store.plan(revision)
            if not row or response.get("revision") != revision:
                raise Invalid("no matching current planning request")
            planner.validate(response, json.loads(row["request"]), tasks)
            self.store.accept_plan(revision, response)

    def resolve(self, attempt_id, outcome, evidence, stopped):
        """Operator attests the old process is stopped before releasing an uncertain slot."""
        if not stopped or not evidence.strip() or outcome not in ("retry", "failed"):
            raise Invalid("resolution requires stopped-process evidence and retry/failed outcome")
        with self.store.lock():
            row = self.store.attempt(attempt_id)
            if not row or row.state in ("accepted", "retry"):
                raise Invalid("attempt cannot be resolved")
            if self.store.latest(row.task).id != attempt_id:
                raise Invalid("stale attempt resolution")
            with self.store.transaction():
                self.store.change(attempt_id, outcome, evidence)
                self.store.event(str(uuid.uuid4()), attempt_id, "operator_resolution",
                                 {"outcome": outcome, "evidence": evidence, "stopped": True}, "applied")

    def tick(self):
        with self.store.lock():
            tasks = self.catalog.read()
            # Pin configuration: existing attempts cannot be moved to another repo/adapter.
            config_revision = digest(self.catalog.config)
            stored = self.store.get("config_revision")
            if stored and stored != config_revision:
                raise Invalid("configuration changed for this ledger; restore its config")
            self.store.set("config_revision", config_revision)
            self.collect(tasks)
            # Cleanup is also retried when the slot is empty or after a restart.
            self.cleanup()
            active = self.store.active()
            if active:
                return {"state": active.state, "attempt": active.id, "task": active.task,
                        "message_blockers": self.mailbox.messages.blockers(active.id),
                        "acceptance_blocker": self.acceptance_blocker(active)}
            explicit = self._explicit(tasks)
            if explicit:
                return explicit
            order = self.plan(tasks)
            if order is None:
                return {"state": "needs_planner", "revision": digest(self._projection(tasks))}
            # Open or held explicit choices reserve their Task; the default never silently widens them.
            reserved = self.store.reserved()
            for key in order:
                task = tasks[key]
                if key in reserved or not launchable(task, self.store.latest(key), tasks):
                    continue
                # A plan-selected Task receives the default assignment through the same path.
                contract = assignment.build(self.catalog, task, 'implement', task.write_scope or ['.'])
                contract = dataclasses.replace(contract, id=assignment.auto_id(contract))
                return self._launch(task, tasks, contract, 'auto')
            return {"state": "idle"}

    def assign(self, ident, key, role, scope, outputs, executor=None):
        """Coordinator stores an explicit assignment. Launch happens on the next tick."""
        if os.environ.get('SCHEDULER_ATTEMPT'):
            raise Invalid('coordinator-only operation; workers may not assign')
        with self.store.lock():
            task = self.catalog.read().get(key)
            if task is None:
                raise Invalid('unknown Task for configured projects: ' + str(key))
            contract = dataclasses.replace(assignment.build(self.catalog, task, role, scope, outputs, executor), id=ident)
            with self.store.transaction():
                old = self.store.assignment(ident)
                if old:
                    if old != contract:
                        raise Invalid('assignment id reused with different content')
                    return {'stored': True, 'duplicate': True, 'assignment': self.query.assignment(ident)}
                busy = self.store.open_assignment(key)
                if busy:
                    raise Invalid('Task already has an open explicit assignment: ' + busy)
                self.store.add_assignment(contract, 'explicit', 'pending')
            return {'stored': True, 'duplicate': False, 'assignment': self.query.assignment(ident)}

    def _explicit(self, tasks):
        for contract in self.store.open_assignments():
            launched = self.store.launched(contract.id)
            if launched:
                latest = self.store.latest(contract.task)
                step = explicit_state(launched, latest)
                if step:
                    self.store.set_assignment(contract.id, *step)
                    continue
                if latest.state != 'retry':
                    continue
            task = tasks.get(contract.task)
            if task is None or task.instruction_revision != contract.revision:
                # A stale contract is never silently re-rendered; the coordinator reassigns.
                self.store.set_assignment(contract.id, 'held', 'Task missing or instruction revision changed before launch')
                continue
            if launchable(task, self.store.latest(task.key), tasks):
                return self._launch(task, tasks, contract, 'explicit')
        return None

    def _launch(self, task, tasks, contract, origin):
        # Re-read all dependencies and target just before reserving the slot.
        fresh = self.catalog.read()
        if {k: t.revision for k, t in fresh.items()} != {k: t.revision for k, t in tasks.items()}:
            return {"state": "catalog_changed"}
        raw = Path(task.path).read_text()
        if hashlib.sha256(raw.encode()).hexdigest() != task.revision:
            return {"state": "catalog_changed"}
        project = self.catalog.project(task.project)
        adapter = adapters.choose(project.get("adapter", self.catalog.config.get("adapter", "local")), self.orca)
        command = self.catalog.command(project, executor=contract.executor)
        ident = str(uuid.uuid4())
        folder = self.store.root / "attempts" / ident
        folder.mkdir(parents=True)
        recipient = 'worker:' + ident
        message = 'assignment:' + ident
        cli = [sys.executable, '-m', 'scheduler', '--config', str(self.catalog.path),
               '--state', str(self.store.root), 'message']
        protocol = worker_protocol(task, ident, recipient, cli, self.store.root)
        prompt, task_sha = assignment.render(contract, ident, raw, protocol, message)
        prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()
        # Exact inputs are preserved so the launch can be reproduced and audited.
        (folder / "task-input.md").write_text(raw)
        # Byte-compatible with earlier attempt folders: an explicit contract was written in its
        # stored (sorted-key) form, an auto contract in build order.
        record = contract.record()
        atomic_json(folder / "assignment.json", record if origin == 'auto' else dict(sorted(record.items())))
        atomic_json(folder / "spec.json", dict(attempt=ident, task=task.key, task_path=task.path,
                                               repo=project["repo"], command=command, prompt=prompt,
                                               recipient=recipient, state=str(self.store.root),
                                               config=str(self.catalog.path), cli=cli, assignment=contract.id,
                                               task_sha256=task_sha, prompt_sha256=prompt_sha))
        payload = {'text': 'Take over this assignment after reading the full current Task.',
                   'ref': str(folder / 'assignment.json'), 'task_sha256': task_sha, 'prompt_sha256': prompt_sha,
                   'expect': assignment.take_over(contract, task.instruction_revision)}
        with self.store.transaction():
            self.store.add_attempt(ident, task.key, task.project, task.revision, adapter)
            self.store.add_context(ident, recipient, task.path)
            if origin == 'auto':
                self.store.add_assignment(contract, 'auto', 'launched', existing_ok=True)
            self.store.set_assignment(contract.id, 'launched', None)
            self.store.add_launch(ident, contract.id, message, task_sha, prompt_sha)
            self.mailbox.insert(message, task.key, task.project, ident, recipient, task.instruction_revision,
                                'instruction', payload, True, actor='scheduler')
            self.store.event(ident + ":intent", ident, "launch_intent", {"adapter": adapter, "assignment": contract.id}, "applied")
        try:
            handle = adapters.launch(adapter, folder / "spec.json", project, self.orca)
            self.store.change(ident, "running", handle=handle)
        except adapters.NotLaunched as exc:
            self.store.change(ident, "failed", str(exc))
        except Exception as exc:
            self.store.change(ident, "unknown", str(exc))
        return {"state": self.store.attempts()[-1].state, "attempt": ident, "task": task.key,
                "adapter": adapter, "assignment": contract.id}

    def notify(self, attempt_id):
        """Deliver an owner-confirmed Task change to the running worker via the same render+mailbox path."""
        # One lock around the whole operation: reads, render, send and supersession (the CLI no longer locks).
        with self.store.lock():
            if os.environ.get('SCHEDULER_ATTEMPT'):
                raise Invalid('coordinator-only operation; workers may not notify')
            launch = self.store.launch(attempt_id)
            if launch is None:
                raise Invalid('attempt has no scheduler assignment')
            contract = self.store.assignment(launch['assignment'])
            context = self.store.context(attempt_id)
            task = self.catalog.read(only_path=context['task_path']).get(contract.task)
            if task is None:
                raise Invalid('Task no longer exists in configured scope')
            revision = task.instruction_revision
            wider = assignment.exceeding(task, contract.scope, contract.outputs)
            if wider:
                # Checked before any render/send: the running contract's scope is never re-certified
                # under a new revision. The coordinator narrows it by an explicit new assignment.
                raise Invalid('scope conflict: running assignment %s exceeds the current Task write_scope [%s]: %s; '
                              'no update was sent; restore the Task scope, or stop/resolve the attempt and reassign within it'
                              % (contract.id, ', '.join(task.write_scope), ', '.join(wider)))
            ident = f"assignment:{attempt_id}:{revision[:16]}"
            if not self.mailbox.messages.find(ident) and self.mailbox.messages.assignment_revision(attempt_id) == revision:
                raise Invalid('Task instruction revision is unchanged; nothing to notify')
            raw = Path(task.path).read_text()
            folder = self.store.root / 'attempts' / attempt_id
            text, task_sha = assignment.render(dataclasses.replace(contract, revision=revision), attempt_id, raw, '', ident)
            update = folder / f'update-{revision[:16]}.md'
            if not update.exists():
                update.write_text(text)
            payload = {'text': 'Owner-confirmed Task change. Read the full current Task and the rendered update; '
                               'apply it within the same assignment scope or record deferred/conflict.',
                       'ref': str(update), 'task_sha256': task_sha,
                       'expect': assignment.take_over(contract, revision)}
            result = self.mailbox.send(ident, contract.task, attempt_id, context['recipient'], revision,
                                       'instruction', payload, True)
            # Older unapplied assignment messages are superseded explicitly, never applied later.
            for old in self.mailbox.messages.unapplied_assignments(attempt_id, ident):
                self.mailbox.dismiss(old, 'superseded by ' + ident)
            return result

    # Read-only projection lives in query.Query; these keep the writer's public API.
    def assignment_view(self, row):
        return self.query.assignment_view(row)

    def assignments(self):
        return self.query.assignments()

    def acceptance_blocker(self, active):
        return self.query.acceptance_blocker(active)

    def status(self):
        return self.query.status()
