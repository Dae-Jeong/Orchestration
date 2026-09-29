"""Minimal assignment contract and deterministic worker input.

The central Task stays canonical for purpose and approval. An assignment only
references it (key/path/semantic revision) and adds role, allowed write scope,
outputs and executor choice. Write scope is a collaboration contract, not OS
isolation.
"""
import dataclasses
from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath
import re

from .model import Invalid, digest

ROLES = ('implement', 'review')
EXCERPT = ('Goal', 'Scope', 'Acceptance Criteria', 'Next Action')


@dataclass(frozen=True)
class Assignment:
    """Fixed assignment contract. `record()` is its only external form (ledger column, assignment.json, auto_id)."""
    task: str
    task_path: str
    project: str
    revision: str
    role: str
    scope: tuple[str, ...]
    outputs: tuple[str, ...]
    executor: str | None
    command_policy: str
    id: str | None = None

    def record(self) -> dict:
        """The exact stored dict: field order, list values, and no `id` key before an id is assigned."""
        value = dict(dataclasses.asdict(self), scope=list(self.scope), outputs=list(self.outputs))
        if self.id is None:
            del value['id']
        return value

    @classmethod
    def from_record(cls, value: dict) -> 'Assignment':
        """Validate a stored contract once at the storage boundary; any other shape is rejected."""
        names = {f.name for f in dataclasses.fields(cls)}
        if not isinstance(value, dict) or set(value) != names or not all(
                isinstance(v, list) and all(isinstance(p, str) for p in v) if k in ('scope', 'outputs')
                else isinstance(v, str) or (k == 'executor' and v is None) for k, v in value.items()):
            raise Invalid('stored assignment contract has an unexpected shape')
        return cls(**dict(value, scope=tuple(value['scope']), outputs=tuple(value['outputs'])))


def paths(values, label):
    """Repo-relative POSIX paths; '.' is the whole repository. No absolute or parent escapes."""
    if not isinstance(values, (list, tuple)) or not all(isinstance(v, str) and v.strip() for v in values):
        raise Invalid(f'{label} must be a list of repository-relative paths')
    result = set()
    for value in values:
        path = PurePosixPath(value.strip())
        if path.is_absolute() or '..' in path.parts or '\\' in value:
            raise Invalid(f'{label} path escapes the project repository: {value}')
        result.add(str(path))
    return sorted(result)


def within(path, parent):
    return parent == '.' or path == parent or path.startswith(parent.rstrip('/') + '/')


def exceeding(task, scope, outputs):
    """Paths of a contract that the Task's current write_scope does not cover ([] when none is declared)."""
    if task.write_scope is None:
        return []
    approved = paths(list(task.write_scope), 'Task write_scope')
    return [p for p in list(scope) + list(outputs) if not any(within(p, a) for a in approved)]


def build(catalog, task, role, scope=(), outputs=(), executor=None) -> Assignment:
    """Validate and return a contract without an id. Never widens Task-approved scope."""
    if role not in ROLES:
        raise Invalid('assignment role must be implement or review')
    scope, outputs = paths(list(scope), 'write scope'), paths(list(outputs), 'outputs')
    if role == 'implement' and not scope:
        raise Invalid('implement assignment requires a write scope')
    if role == 'review' and scope:
        raise Invalid('review assignment has no product write scope; declare its report under outputs')
    wider = exceeding(task, scope, outputs)
    if wider:
        raise Invalid('assignment exceeds Task-approved write_scope: ' + ', '.join(wider))
    project = catalog.project(task.project)
    catalog.command(project, resolve=False, executor=executor)  # rejects invalid executor/command mixes
    custom = project.get('command', catalog.config.get('command'))
    policy = 'configured command' if custom is not None else 'preset ' + (executor or catalog.config['executor'])
    return Assignment(task.key, task.path, task.project, task.instruction_revision, role, tuple(scope),
                      tuple(outputs), executor, policy)


def excerpt(raw):
    body = raw.split('\n---', 1)[1] if raw.startswith('---\n') and '\n---' in raw else raw
    found = {}
    for part in re.split(r'(?m)^## ', body)[1:]:
        heading, _, text = part.partition('\n')
        if heading.strip() in EXCERPT and heading.strip() not in found:
            found[heading.strip()] = text.strip()
    return found


def render(contract: Assignment, ident, raw, protocol, message):
    """Same inputs always yield the same text. Content is passed as data via stdin/argv, never a shell."""
    task_sha = hashlib.sha256(raw.encode()).hexdigest()
    parts = excerpt(raw)
    scope = ', '.join(contract.scope) or '(none: do not modify product files)'
    outputs = ', '.join(contract.outputs) or '(none)'
    guidance = ('Implement only within the allowed write scope. Bind your real session to the Task before changes '
                'and follow preservation/check/evidence rules.' if contract.role == 'implement' else
                'Review only: do not modify product files or the Task; write findings only to the declared outputs.')
    lines = [
        f"Execute central Task {contract.task} at {contract.task_path}.",
        f"Scheduler attempt: {ident}; assignment: {contract.id}; role: {contract.role}.",
        f"Task file sha256 at launch: {task_sha}; instruction revision: {contract.revision}.",
        f"Allowed write scope (repo-relative collaboration contract, not OS isolation): {scope}.",
        f"Outputs: {outputs}. Executor policy: {contract.command_policy}.",
        guidance,
        "Read global/product AGENTS and the full current Task; the Task is canonical and this excerpt is not an editable copy. "
        "Update its result, evidence and status when accepted; process exit alone is not acceptance. "
        "Do not publish or install daemons.",
        f"Take-over: first claim inbox message {message}. After reading the full Task, record `processed --outcome applied` "
        "with a JSON report containing the message payload's `expect` fields exactly, then ACK. "
        "Transport or terminal acceptance is not take-over. Later Task changes arrive as new assignment messages.",
        "",
        "Task excerpt at launch:",
    ]
    for name in EXCERPT:
        lines += [f"## {name}", parts.get(name, '(not present)'), ""]
    return '\n'.join(lines) + protocol, task_sha


def take_over(contract: Assignment, revision: str) -> dict:
    return {'assignment': contract.id, 'role': contract.role, 'task_revision': revision}


def auto_id(contract: Assignment) -> str:
    return 'auto:' + digest(contract.record())[:24]
