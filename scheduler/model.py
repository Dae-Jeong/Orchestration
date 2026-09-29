"""Read-only central Task projection. No business status is written to the ledger."""
from collections.abc import Container
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

import yaml

from .launcher import PROFILES


class Invalid(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def argv(value):
    if not isinstance(value, list) or not value or not all(isinstance(x, str) and x for x in value):
        raise Invalid("command must be a nonempty argv array")
    return value


@dataclass(frozen=True)
class Task:
    key: str
    project: str
    path: str
    status: str
    priority: int
    depends_on: tuple[str, ...]
    title: str
    evidence: tuple[str, ...]
    revision: str
    brief: str
    write_scope: tuple[str, ...] | None = None

    @property
    def accepted(self):
        return self.status == "done" and bool(self.evidence)

    def planning(self):
        return dict(key=self.key, project=self.project, priority=self.priority,
                    depends_on=list(self.depends_on), title=self.title, brief=self.brief)

    @property
    def instruction_revision(self):
        # Owner-issued instructions live in Goal/Scope/Acceptance Criteria and
        # scheduling metadata. Routine worker progress must not invalidate a claim.
        value = dict(self.planning(), stop=self.status if self.status in ('blocked', 'cancelled') else None)
        if self.write_scope is not None:
            # Optional owner-approved write boundary is part of the assignment contract.
            value['write_scope'] = list(self.write_scope)
        return digest(value)


class Catalog:
    def __init__(self, config_path):
        self.path = Path(config_path).resolve()
        self.config = json.loads(self.path.read_text())
        self.projects = self.config.get("projects", [])
        seen = set()
        for p in self.projects:
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", p["id"]) or p["id"] in seen:
                raise Invalid("invalid or duplicate project id")
            seen.add(p["id"])
            for field in ("repo", "tasks"):
                p[field] = str((self.path.parent / p[field]).resolve())
                if not Path(p[field]).is_dir():
                    raise Invalid(f"missing {field}: {p[field]}")
            self.command(p, resolve=False)
            if p.get("adapter", self.config.get("adapter", "local")) not in ("local", "orca", "auto"):
                raise Invalid("adapter must be local, orca or auto")
        if not seen:
            raise Invalid("at least one explicitly authorized project is required")
        if "planner_command" in self.config:
            argv(self.config["planner_command"])

    def project(self, key):
        return next(p for p in self.projects if p["id"] == key)

    def command(self, project, resolve=True, executor=None):
        """Worker argv. An assignment may choose another preset executor, never a new command."""
        custom = project.get("command", self.config.get("command"))
        if executor is not None and executor not in PROFILES:
            raise Invalid("assignment executor must be claude, codex, qwen or kiro")
        if custom is not None:
            if executor is not None:
                raise Invalid("project uses an explicit command; assignment executor override is not allowed")
            return argv(custom)
        configured = self.config.get("executor")
        executor = executor or configured
        if not isinstance(executor, str) or executor not in PROFILES:
            raise Invalid("configure a common executor (claude/codex/qwen/kiro) or explicit command")
        result = [sys.executable, str(Path(__file__).with_name("launcher.py")), "--executor", executor]
        if resolve:
            executable = shutil.which(PROFILES[executor][0])
            if not executable:
                raise Invalid(f"executor executable not found: {PROFILES[executor][0]}")
            result += ["--executable", str(Path(executable).absolute())]
        # The common model belongs to the configured executor; overrides use their tool default.
        model = self.config.get("model") if executor == configured else None
        if model is not None:
            if not isinstance(model, str) or not model.strip():
                raise Invalid("model must be a nonempty string")
            if executor == "kiro" and model != "claude-opus-5.5":
                raise Invalid("Kiro model is pinned to claude-opus-5.5 by operator policy")
            result += ["--model", model]
        return result

    def read(self, only_path=None):
        """File IO around `parse`: one project's Task files (or one file), duplicates, then the dependency check."""
        tasks = {}
        paths = set()
        for p in self.projects:
            if only_path is not None:
                target = Path(only_path).resolve()
                candidates = [target] if target.parent == Path(p['tasks']) else []
            else:
                candidates = sorted(Path(p["tasks"]).glob("*.md"))
            for path in candidates:
                task = parse(path.read_text(), p["id"], str(path.resolve()), str(path), taken=tasks)
                if task is None:
                    continue
                if path.resolve() in paths:  # one file seen through two projects sharing a tasks dir
                    raise Invalid(f"duplicate Task: {task.key}")
                paths.add(path.resolve())
                tasks[task.key] = task
        if only_path is None:
            check_dependencies(tasks)
        return tasks


STATUSES = ("ready", "active", "blocked", "review", "done", "cancelled")


def parse(raw: str, project: str, path: str, source: str, taken: Container[str] = ()) -> Task | None:
    """One Task file's text as a Task, or None when it is not a Task. No file or catalog access.

    `path` is the resolved location stored on the Task; `source` is the path named in errors.
    A key in `taken` is a duplicate, reported before the field checks as the catalog always did.
    """
    parts = re.split(r"(?m)^---\s*$", raw, maxsplit=2)
    if not raw.startswith("---\n") or len(parts) != 3:
        raise Invalid(f"missing frontmatter: {source}")
    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise Invalid(f"invalid frontmatter: {source}") from exc
    if not isinstance(meta, dict) or meta.get("type", meta.get("kind")) != "task":
        return None
    ident = meta.get("id")
    if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", ident):
        raise Invalid(f"invalid Task id: {source}")
    if meta.get("project_id", project) != project:
        raise Invalid(f"project mismatch: {source}")
    key = project + "/" + ident
    if key in taken:
        raise Invalid(f"duplicate Task: {key}")
    status = meta.get("status", "ready")
    if status not in STATUSES:
        raise Invalid(f"invalid status: {key}")
    priority = meta.get("priority", 0)
    deps = meta.get("depends_on", [])
    evidence = meta.get("evidence", [])
    if type(priority) is not int or not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
        raise Invalid(f"invalid priority/dependencies: {key}")
    if not isinstance(evidence, list) or not all(isinstance(e, str) and e.strip() for e in evidence):
        raise Invalid(f"invalid evidence: {key}")
    qualified = tuple(d if "/" in d else project + "/" + d for d in deps)
    write_scope = meta.get("write_scope")
    if write_scope is not None and (not isinstance(write_scope, list) or
                                    not all(isinstance(w, str) and w.strip() for w in write_scope)):
        raise Invalid(f"invalid write_scope: {key}")
    sections = re.split(r"(?m)^## ", parts[2])
    brief = "\n".join(s for s in sections[1:] if s.splitlines()[0].strip() in
                      ("Goal", "Scope", "Acceptance Criteria"))
    return Task(key, project, path, status, priority, qualified, str(meta.get("title", ident)), tuple(evidence),
                hashlib.sha256(raw.encode()).hexdigest(), brief, None if write_scope is None else tuple(write_scope))


def check_dependencies(tasks: dict[str, Task]) -> None:
    """Raise on an unknown dependency or a cycle, in the catalog's file order."""
    visiting, visited = set(), set()

    def visit(key):
        if key in visiting:
            raise Invalid(f"dependency cycle: {key}")
        if key in visited:
            return
        visiting.add(key)
        for dep in tasks[key].depends_on:
            if dep not in tasks:
                raise Invalid(f"unknown dependency: {key} -> {dep}")
            visit(dep)
        visiting.remove(key)
        visited.add(key)
    for key in tasks:
        visit(key)


def ordered(tasks):
    """Stable topological order with higher numeric priority first."""
    remaining = dict(tasks)
    result = []
    while remaining:
        ready = [t for t in remaining.values() if not set(t.depends_on) & remaining.keys()]
        if not ready:
            raise Invalid("dependency cycle")
        task = min(ready, key=lambda t: (-t.priority, t.key))
        result.append(task.key)
        del remaining[task.key]
    return result
