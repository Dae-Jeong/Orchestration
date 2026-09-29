"""Pure scheduling decisions over records the caller already read. No ledger, file or process access."""
import json

from .model import Invalid, Task
from .store import CLEANUP_TRIES, EXECUTING_STATES, Attempt


def event_state(existing: dict | None, active: Attempt | None, attempt: str, kind: str, payload: dict) -> str | None:
    """New attempt state for a worker event, or None when the event is stale."""
    if existing and (existing["attempt"] != attempt or existing["kind"] != kind or
                     json.loads(existing["payload"]) != payload):
        raise Invalid("event id reused with different content")
    if kind not in ("started", "exited"):
        raise Invalid("only started/exited worker events are supported")
    if kind == "exited" and type(payload.get("code")) is not int:
        raise Invalid("exit event requires integer code")
    if not active or active.id != attempt or active.state not in EXECUTING_STATES:
        return None
    return "running" if kind == "started" else ("awaiting_acceptance" if payload["code"] == 0 else "failed")


def launchable(task: Task, latest: Attempt | None, tasks: dict[str, Task]) -> bool:
    """A ready Task with no attempt, or whose latest attempt was released for retry, and accepted dependencies."""
    return (task.status == "ready" and (latest is None or latest.state == "retry")
            and all(tasks[d].accepted for d in task.depends_on))


def explicit_state(launched: set[str], latest: Attempt) -> tuple[str, str | None] | None:
    """Ledger state for a launched explicit assignment; None while its attempt runs or awaits retry."""
    if latest.id not in launched:
        return "superseded", "another attempt ran this Task"
    if latest.state == "accepted":
        return "completed", None
    if latest.state == "failed":
        return "failed", "attempt failed; assign again explicitly"
    return None


def cleanup_state(outcome: str, tries: int) -> str:
    """An unconfirmed close becomes final `failed` at the retry cap."""
    return "failed" if outcome == "unconfirmed" and tries >= CLEANUP_TRIES else outcome
