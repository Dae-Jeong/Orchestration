---
name: project-orchestrator
description: Start, resume, or inspect a named project through an Obsidian vault; resolve its repository and central Task, then coordinate execution and evidence. Use for project-level requests from the vault, not ordinary note editing or standalone factual questions.
---

# Project orchestrator

Use the operator's existing project registry and Task owners. This skill is a routing entry, not a scheduler or a second task database.

## Resolve the operating context

Read the workspace AGENTS and its linked shared work policy. Locate the vault from those entry documents or the operator-provided location; do not assume the current directory is the product repository.

Resolve this installed SKILL.md to its real filesystem path before following repository-relative links. It may be installed as a directory symlink. Read [the operating model](../../docs/task-session-model.md) for execution and handoff rules; read [measurement criteria](../../docs/engineering-measurement.md) only when choosing or interpreting measurements. Missing documents require resolving the checkout location, not inventing replacement rules.

## Route the request

1. Match the requested project against the vault's `.local/harness/projects.json` and `wiki/projects/index.md`. Read only the selected project's index and AGENTS. The registry owns repo/document paths; the index owns purpose and knowledge links. Do not copy these into a new profile file.
2. From the vault, run the public `uv run python -m harness context /absolute/product/repo`. Use `--task ID` to retrieve the selected full Task. Check actual repo state, active writers and pending work. If no unique project or Task follows from the request, ask only for the missing choice. Do not enroll an unknown project or select an arbitrary Task.
3. For status-only requests, report the current Task and evidence without claiming ownership or modifying it. For execution, continue the same Task, or create one for a new substantive goal under the shared policy. A simple lookup needs no Task. Do not take over another active writer's work.

## Connect execution to the correct repository

A session's startup workspace and its command working directory are different concepts. The current harness binds a session to one repository and rejects silently switching worktrees. A shell `cd` does not migrate hook ownership.

- In a product-rooted execution session, bind its real agent/session identity to that product's Task according to the shared policy before code changes. Run product commands there and central harness commands from the vault.
- In a vault-rooted session, inspect and coordinate there. When product edits are needed, connect a separate execution session rooted at the target repository. Use the installed Orca orchestration skill for supervised work/result tracking, or orca-cli for a full ownership handoff; follow the user's requested mode. Do not pretend a terminal launch means work succeeded. If execution tools are unavailable, give the exact repo and Task for a product-rooted session.
- Pass the goal, authorized scope, Task path/ID, repository, expected result and evidence location. Require the executor to read the product instructions. Avoid two writers for the same scope and account for shared ports/DBs. Project coordination does not authorize publishing or unrelated work.

## Complete or hand off

Follow the shared work policy for preservation, checks, session binding and evidence recording. Keep status, result and next action in the original Task; code and raw output remain in the product repo, history in Log. The executing session records its own changes; never reconcile or record a live worker's unfinished call on its behalf.

Judge completion against the Task's actual goal and acceptance conditions. Select additional BE/FE measurements only where relevant. Return the project, Task, verified result and remaining work. Skill discovery, terminal launch and document validation are not proof of successful product execution.
