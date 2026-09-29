"""High-level planning only; provider output never contains executable commands."""
import json
import os
import signal
import subprocess

from .model import Invalid


def reason(previous, current, tasks):
    if previous is None:
        ready = [t.priority for t in tasks.values() if t.status == "ready"]
        if len(ready) != len(set(ready)):
            return "priority_conflict"
        if len(current) > 1 and any(t.depends_on for t in tasks.values()):
            return "related_batch"
        return None
    added = current.keys() - previous.keys()
    removed = previous.keys() - current.keys()
    # Completion is deterministic: removed done Tasks alone do not invoke the LLM.
    invalid = [key for key in removed if key not in tasks or not tasks[key].accepted]
    if invalid or any(previous[k] != current[k] for k in previous.keys() & current.keys()):
        return "plan_invalidated"
    if added:
        if any(set(tasks[k].depends_on) & current.keys() for k in added) or any(
                set(t.depends_on) & added for t in tasks.values()):
            return "related_batch"
        priorities = [tasks[key].priority for key in current if tasks[key].status == "ready"]
        if len(priorities) != len(set(priorities)):
            return "priority_conflict"
    return None


def validate(response, request, tasks):
    if not isinstance(response, dict) or set(response) != {"revision", "order"}:
        raise Invalid("planner response requires exactly revision and order")
    order = response["order"]
    if response["revision"] != request["revision"]:
        raise Invalid("stale planner revision")
    if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
        raise Invalid("planner order must be a string array")
    if len(order) != len(set(order)) or set(order) != set(request["tasks"]):
        raise Invalid("planner order must cover exactly the pending scope")
    rank = {key: i for i, key in enumerate(order)}
    for key in order:
        if any(rank[d] > rank[key] for d in tasks[key].depends_on if d in rank):
            raise Invalid("planner reversed a dependency")
    return order


def invoke(command, request, timeout):
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, start_new_session=True) as process:
        try:
            stdout, _ = process.communicate(json.dumps(request), timeout=timeout)
        except subprocess.TimeoutExpired:
            # The bridge can itself spawn a provider CLI. Stop the whole group.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise
        if process.returncode:
            raise Invalid(f"planner command exited {process.returncode}")
        return json.loads(stdout)
