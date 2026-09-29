import argparse
import json
import os
import signal
import sqlite3
import threading

from .model import Invalid
from .runtime import Scheduler
from .store import Busy


def main():
    parser = argparse.ArgumentParser(description="Single-host compact project scheduler; no service installation")
    parser.add_argument("--config", default=os.environ.get('SCHEDULER_CONFIG'))
    parser.add_argument("--state", default=os.environ.get('SCHEDULER_STATE'), help="one shared local state directory for ALL participating projects")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("tick")
    sub.add_parser("status")
    run = sub.add_parser("run")
    run.add_argument("--interval", type=float, default=2)
    watch = sub.add_parser("watch", help="read-only terminal view of status; Ctrl-C stops only the viewer")
    watch.add_argument("--interval", type=float, default=2, help="seconds between refreshes")
    watch.add_argument("--once", action="store_true", help="print one plain frame and exit (2 on query failure)")
    watch.add_argument("--width", type=int, help="columns for shortening long values; 0 disables (default: terminal width on a TTY, else 0)")
    apply = sub.add_parser("apply-plan")
    apply.add_argument("response", help="JSON file returned by the high-level planner")
    event = sub.add_parser("event")
    event.add_argument("--id", required=True)
    event.add_argument("--attempt", required=True)
    event.add_argument("--kind", choices=["started", "exited"], required=True)
    event.add_argument("--code", type=int)
    resolve = sub.add_parser("resolve")
    resolve.add_argument("--attempt", required=True)
    resolve.add_argument("--outcome", choices=["retry", "failed"], required=True)
    resolve.add_argument("--evidence", required=True)
    resolve.add_argument("--stopped", action="store_true", help="attest that the previous worker AND child have stopped")
    assign = sub.add_parser('assign', help='coordinator: store an explicit Task assignment (launched by tick)')
    assign.add_argument('--id', required=True)
    assign.add_argument('--task', required=True, help='PROJECT/TASK_ID')
    assign.add_argument('--role', choices=['implement', 'review'], required=True)
    assign.add_argument('--scope', action='append', default=[], help='repo-relative allowed write path (repeat)')
    assign.add_argument('--output', action='append', default=[], help='repo-relative output path (repeat)')
    assign.add_argument('--executor', choices=['claude', 'codex', 'qwen', 'kiro'])
    sub.add_parser('assignments', help='stored/launched/delivered/taken-over/completed view')
    notify = sub.add_parser('notify', help='coordinator: deliver an owner-confirmed Task change to a running attempt')
    notify.add_argument('--attempt', required=True)
    message = sub.add_parser('message', help='addressed send/inbox/claim/processing/ACK/completion')
    verbs = message.add_subparsers(dest='verb', required=True)
    for verb in ('send', 'inbox', 'claim', 'processed', 'ack', 'complete', 'dismiss'):
        command = verbs.add_parser(verb)
        if verb == 'dismiss':
            command.add_argument('--id', required=True)
            command.add_argument('--reason', required=True)
            continue
        for target in ('task', 'attempt', 'recipient'):
            command.add_argument('--' + target, default=os.environ.get('SCHEDULER_' + target.upper()))
        if verb not in ('inbox',):
            command.add_argument('--revision', required=True)
        if verb in ('send', 'processed', 'ack', 'complete'):
            command.add_argument('--id', required=True)
        if verb == 'send':
            command.add_argument('--kind', choices=['instruction','question','result'], default='instruction')
            command.add_argument('--payload-file', required=True)
            command.add_argument('--optional', action='store_true')
        if verb == 'claim':
            command.add_argument('--lease', type=float, default=60)
        if verb in ('processed', 'ack'):
            command.add_argument('--token', required=True)
        if verb in ('processed', 'complete'):
            command.add_argument('--report-file', required=True)
        if verb == 'processed':
            command.add_argument('--outcome', choices=['applied','deferred','conflict'], required=True)
            command.add_argument('--reconciliation', default='')
        if verb == 'complete':
            command.add_argument('--inbox-seq', type=int, required=True)
    ref = sub.add_parser('ref', help='Task-item reference events (question/answer/completed/blocked); see docs/scheduler-task-events.md')
    ref_verbs = ref.add_subparsers(dest='verb', required=True)
    for verb in ('item', 'publish', 'inbox', 'claim', 'wait', 'read', 'processed', 'ack', 'dismiss', 'show'):
        command = ref_verbs.add_parser(verb)
        if verb in ('item', 'publish'):
            command.add_argument('--task', required=True, help='PROJECT/TASK_ID')
            command.add_argument('--path', required=True, help='Task file (direct child of the project tasks dir)')
            command.add_argument('--item', required=True)
        if verb in ('publish', 'inbox', 'claim', 'wait', 'read', 'processed', 'ack', 'dismiss'):
            command.add_argument('--as', dest='who', default=os.environ.get('SCHEDULER_REF_AS'), help='participant address')
            command.add_argument('--exec', dest='execution', default=os.environ.get('SCHEDULER_REF_EXEC'), help='execution identity')
        if verb in ('publish', 'read', 'processed', 'ack', 'dismiss', 'show'):
            command.add_argument('--id', required=True)
        if verb == 'publish':
            command.add_argument('--kind', choices=['question.opened', 'question.answered', 'work.completed', 'work.blocked'], required=True)
            command.add_argument('--to', required=True)
            command.add_argument('--to-exec')
            command.add_argument('--reply-to')
            command.add_argument('--sha256', help='expected item hash (CAS against what you reviewed)')
        if verb in ('claim', 'wait'):
            command.add_argument('--lease', type=float, default=60)
        if verb == 'wait':
            command.add_argument('--timeout', type=float, required=True, help='seconds; timeout exits 3 and is not success/failure')
            command.add_argument('--interval', type=float, default=1.0)
        if verb in ('read', 'processed', 'ack'):
            command.add_argument('--token', required=True)
        if verb == 'processed':
            command.add_argument('--outcome', choices=['applied', 'deferred', 'conflict'], required=True)
            command.add_argument('--report-file', required=True)
            command.add_argument('--reconciliation', default='')
        if verb == 'dismiss':
            command.add_argument('--reason', required=True)
    args = parser.parse_args()
    if not args.config or not args.state:
        parser.error('--config and --state (or worker environment) are required')
    if args.action == 'watch':
        # Dispatched before Scheduler(): a missing state path is reported, not created.
        if not args.interval > 0 or (args.width is not None and args.width < 0):
            parser.error('watch --interval must be positive and --width non-negative')
        from .watch import watch as view
        return view(args.config, args.state, args.interval, args.once, args.width)
    scheduler = None
    try:
        scheduler = Scheduler(args.config, args.state)
        if args.action == 'assign':
            result = scheduler.assign(args.id, args.task, args.role, args.scope, args.output, args.executor)
        elif args.action == 'assignments':
            result = scheduler.assignments()
        elif args.action == 'notify':
            result = scheduler.notify(args.attempt)
        elif args.action == 'message':
            result = message_action(scheduler.mailbox, args)
        elif args.action == 'ref':
            result = ref_action(scheduler, args)
            if args.verb == 'wait' and result.get('state') == 'timeout':
                print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
                return 3
        elif args.action == "status":
            result = scheduler.status()
        elif args.action == "tick":
            result = scheduler.tick()
        elif args.action == "apply-plan":
            with open(args.response) as stream:
                scheduler.approve_plan(json.load(stream))
            result = {"state": "plan_accepted"}
        elif args.action == "resolve":
            scheduler.resolve(args.attempt, args.outcome, args.evidence, args.stopped)
            result = {"state": "resolved"}
        elif args.action == "event":
            scheduler.event(args.id, args.attempt, args.kind, {"code": args.code})
            result = {"state": "event_recorded"}
        else:
            if args.interval <= 0:
                raise Invalid("interval must be positive")
            stop = threading.Event()
            signal.signal(signal.SIGTERM, lambda *_: stop.set())
            signal.signal(signal.SIGINT, lambda *_: stop.set())
            while not stop.is_set():
                try:
                    print(json.dumps(scheduler.tick()), flush=True)
                except Busy:
                    print(json.dumps({"state": "busy"}), flush=True)
                except (Invalid, OSError, ValueError, sqlite3.Error) as exc:
                    print(json.dumps({"state": "error", "detail": str(exc)}), flush=True)
                stop.wait(args.interval)
            result = {"state": "stopped", "workers": "continue; restart with the same state directory"}
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0
    except (Invalid, Busy, OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"state": "error", "detail": str(exc)}))
        return 2
    finally:
        if scheduler:
            scheduler.close()


def ref_action(scheduler, args):
    from .refs import References
    refs = References(scheduler.store, scheduler.catalog, scheduler.mailbox.max_deliveries)
    if args.verb == 'item':
        return refs.item(args.task, args.path, args.item)
    if args.verb == 'show':
        return refs.show(args.id)
    if not args.who or not args.execution:
        raise Invalid('ref operations require --as and --exec (or SCHEDULER_REF_AS/SCHEDULER_REF_EXEC)')
    me = (args.who, args.execution)
    if args.verb == 'publish':
        return refs.publish(args.id, args.kind, args.task, args.path, args.item, *me, args.to,
                            args.to_exec, args.reply_to, args.sha256)
    if args.verb == 'inbox':
        return refs.inbox(*me)
    if args.verb == 'claim':
        return refs.claim(*me, args.lease)
    if args.verb == 'wait':
        return refs.wait(*me, args.timeout, args.lease, args.interval)
    if args.verb == 'read':
        return refs.read(args.id, *me, args.token)
    if args.verb == 'ack':
        return refs.ack(args.id, *me, args.token)
    if args.verb == 'dismiss':
        return refs.dismiss(args.id, *me, args.reason)
    with open(args.report_file) as stream:
        report = json.load(stream)
    return refs.processed(args.id, *me, args.token, args.outcome, report, args.reconciliation)


def message_action(mailbox, args):
    if args.verb == 'dismiss':
        return mailbox.dismiss(args.id, args.reason)
    if not all((args.task, args.attempt, args.recipient)):
        raise Invalid('message operations require task, attempt and recipient (flags or worker environment)')
    target = (args.task, args.attempt, args.recipient)
    if args.verb == 'inbox':
        return mailbox.inbox(*target)
    if args.verb == 'claim':
        return mailbox.claim(*target, args.revision, args.lease)
    if args.verb == 'ack':
        return mailbox.ack(args.id, *target, args.revision, args.token)
    path = args.payload_file if args.verb == 'send' else args.report_file
    with open(path) as stream:
        payload = json.load(stream)
    if args.verb == 'send':
        return mailbox.send(args.id, *target, args.revision, args.kind, payload, not args.optional)
    if args.verb == 'processed':
        return mailbox.processed(args.id, *target, args.revision, args.token, args.outcome, payload, args.reconciliation)
    return mailbox.complete(args.id, *target, args.revision, args.inbox_seq, payload)
