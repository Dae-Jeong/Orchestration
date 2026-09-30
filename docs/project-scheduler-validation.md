# Scheduler validation

Checked: 2026-09-30. This report describes the compact scheduler's acceptance evidence; the central parent/child Tasks own work status. The command and operational contract is [project-scheduler.md](project-scheduler.md).

Raw test output, ledgers, receipts, session/dispatch identifiers and review reports are kept in the operator's local evidence store and Log. They are not part of this repository (see [external environment](external-dependencies.md)). A clone can rerun the deterministic suite below; the live runs cannot be independently reproduced from the clone alone.

## Deterministic and local integration evidence

`uv run python -m unittest discover -s tests -v` passed 38 tests at this first stage: 33 scheduler tests and 5 existing contract tests. Python 3.14.7 on macOS, SQLite on a local filesystem, isolated temporary Task directories and state DBs. This is functional/recovery evidence, not a performance benchmark. The current suite count is in the last section.

| Requirement | Actual observations |
| --- | --- |
| Existing Task/minimal metadata | Defaults, scoped duplicate IDs, YAML scalar delimiter regression, missing dependencies, cycles and invalid priority rejection |
| Two projects / dependency acceptance / one slot | Cross-project dependency waits for `done + evidence`, exit alone holds slot, two real scheduler processes create one attempt, OS lock and DB unique slot both reject concurrent ownership |
| Persistent execution / events | Intent interruption, ambiguous launch and restart never relaunch; file receipts recover; duplicate events apply once; delayed/stale events do not change a newer attempt; conflicting event ID rejected |
| Local and Orca adapters | Real local subprocess output/exit and duplicate-worker guard, CLI persistent loop and SIGTERM/restart; mock Orca command/receipt and auto preflight selection; no fallback after launch uncertainty |
| High-level planner only | Ordinary independent completion has zero planner calls; conflict invokes once; related intake/scope changes replan; result prose does not; invalid revision/scope/order rejected; concurrent Task change rejects a slow response; provider timeout is durable and child process group is stopped |
| Common executor policy | Real launcher subprocesses with fixture executables capture exact Claude/Codex/Qwen/Kiro argv and literal prompt; no effort override; model/executor lives in common config |

The YAML parsing regression was reproduced against the preserved pre-refinement source in an isolated temporary directory. The baseline rejected a valid quoted string containing `---`; the parser now recognizes only full delimiter lines.

## Live connector evidence

These fixtures used no production Tasks or product edits by workers. Fixture Task acceptance was performed by the implementing session after inspecting the actual output and exit receipts.

- **Orca 1.4.215:** public CLI created a new terminal running the scheduler worker in the product checkout. The worker only printed a fixture sentinel. The scheduler collected code 0, held `awaiting_acceptance`, then observed the fixture's acceptance and became idle. One attempt, zero planner calls. The implementing session closed only that newly created terminal after inspecting the exit receipt.
- **Claude planner provider:** the optional bridge called the installed Claude CLI with tools and MCP access disabled. A real structured response passed revision/scope/dependency checks for two fixture projects with equal priority. Two local worker attempts completed; one planner request was stored and accepted, with no second call on ordinary completion. This first provider smoke preceded the user's later permission-flag policy; launcher policy is separately tested above.

The final policy bridge was re-tested with the user-requested Claude permission flag and empty tool/MCP surface: two accepted fixture attempts, one accepted plan and zero completion replans. Installed help confirms all four executor options. Only the Claude planner provider and Orca worker bridge were exercised against live connectors; executable argv fixtures do not establish Codex/Qwen/Kiro provider completion or permission behavior in a real product run.

## Evidence limits

The single slot covers processes sharing one state directory on one POSIX host. It does not lock other schedulers with different state paths, remote hosts, external Task writers or arbitrary user-launched processes. Network filesystems, power loss, long-running unattended operation, force preemption and remote Orca are outside this validation.

`done + evidence` is a central acceptance declaration; the runtime does not prove the content or quality of the evidence. Workers must finish their children before exiting. Operator `--stopped` resolution is an attestation, not automatic process-tree authentication. Launcher support for an executor is separate from central harness session binding: the operator's current local harness binds Codex, Claude and Kiro sessions, Qwen is not supported, and the harness is an external dependency whose installed version must be checked ([details](project-scheduler.md#시작)).

No daemon was installed, no artifact was published, no old supervisor or terminal was reused, and no live session was restarted to adopt the new launcher policy.

## Independent Kiro review and integration

The user assigned Kiro (`claude-opus-5.5`, default effort) read-only QA. Kiro reviewed a fixed source snapshot, passed its 29 scheduler tests on a temporary copy and found no Critical/High issue in duplicate launch/events, ambiguous launch, restart or same-state contention. Kiro did not run live providers or Orca and did not edit product code or central Tasks. Final integration and the post-fix tests below belong to Codex.

| Finding | Disposition and evidence |
| --- | --- |
| K1: worker status bookkeeping triggers LLM after failure | Fixed. Projection recognizes owned worker active/review transitions after failed/retry attempts; removed unreachable active exemption. Regression reproduces failure first, then confirms no planner call. |
| K2: initial equal priorities / related chain invoke LLM | Retained as the explicit initial high-level planning policy. Equal priority defaults are a one-time scheduling choice; related batches are in the authorized trigger scope. Normal completion still makes zero additional calls. This is not a claim of the theoretically smallest possible call count. |
| K3: new arrival compared with blocked Task priorities | Fixed. Compare ready Tasks only, matching the initial conflict rule. Isolated regression reproduced the extra call and now launches deterministically. |
| K4/K5: different state directories / killed worker | Documented limits retained. All participants must share state. A killed worker without exit proof holds the slot for inspection and explicit resolution; no PID-based auto-relaunch. |
| K6: Kiro model override | Fixed by rejecting models other than the user-required `claude-opus-5.5`. Regression verifies rejection. |
| K7: Orca PATH may choose another executor | Preset CLI executable is resolved to an absolute path by the scheduler and stored in the worker argv. A real launcher fixture still invokes the chosen executable under an empty replacement PATH. Child tool/auth environment parity remains unverified. |
| K8: Codex non-Git root | Product repo is the supported preset root; no automatic Git-check bypass is added. Live non-Git Codex execution is unverified. |
| K9: manual event poisons file-receipt ID | Fixed with a separate external event namespace. Regression first raised Invalid, then successfully collected the file receipt. |
| K10/K11: declared acceptance / project directory boundary | Accepted existing contracts. Evidence is a declaration, not semantic certification; shared central Task files cannot be enrolled under different project identities. |

The before-fix reproduction had three expected failures and one error. Kiro's original report is preserved unchanged; Codex did not attribute the post-fix review to Kiro.

## Addressed messaging extension

The messaging follow-up passed `uv run python -m unittest discover -s tests -v`: **57 tests** (19 message protocol tests, 33 scheduler tests and 5 existing contract tests). The earlier 38-test baseline remains historical evidence; new attempts additionally require the completion/message gate described in [the messaging contract](scheduler-messaging.md).

The suite covers committed send visibility; same-ID duplicate/collision; processing result before ACK; ACK loss and persistent reuse after restart; result-before-ACK crash and token replacement; reconciliation requirement on uncertain redelivery; two real claimant processes; wrong targets; old attempts; FIFO and explicit stale-revision supersession; exact delivery limit; conflict hold; progress edits versus instruction revision; late required message and owner revision change during completion; inbox sequence fencing; message CLI in a foreign cwd; mailbox operations under tick lock and unrelated-project corruption; legacy attempts and stable insertion order.

**Live Claude CLI application ACK:** a real local worker using Claude `--print --dangerously-skip-permissions` and only Bash/Read/Write tools read a sentinel file without changing product code or the fixture Task. It called the common CLI: claim → persisted applied report containing the exact sentinel text → ACK → completion submission. The message had one delivery. Code 0 alone left the attempt awaiting acceptance; the fixture owner inspected the sentinel report and then accepted the Task. Only then did the attempt become accepted. This verifies explicit agent application reporting and the acceptance separation, not arbitrary external effects or autonomous product work. Codex/Qwen/Kiro live ACK and Kiro first-run consent remain unverified; all four receive the same protocol and retain their existing launcher policy.

**Kiro design review** of the pre-implementation snapshot is not an independent review of the final messaging code. Codex applied and tested its constraints:

- E1: semantic instruction revision excludes worker progress/evidence edits, while full file SHA remains execution evidence.
- E2/E4: messaging uses SQLite transactions without tick flock and reads only the addressed Task.
- E3/E5: explicit required-message/completion gate, absolute common CLI and execution environment.
- E6/E7: new tables and defaults; existing pinned config and running legacy attempts are retained.
- E8/D1–D9: insertion sequence, claim tokens, durable result/ACK receipts, FIFO, bounded redelivery, explicit conflict/dismissal, attempt/revision/inbox fences.
- D10/D11: pull-only agent compliance and initial authentication/consent are explicit limits.

A separately authorized post-implementation Kiro code quality review follows this functional acceptance; the pre-implementation report does not substitute for it.

## 구현 후 코드 품질 리뷰

Kiro는 메시징 완료 후 고정된 22개 파일 manifest를 두 번 확인하고 격리 사본에서 57개 테스트를 실행했다. 초기 보고서의 C1–C3은 종료 후 메시지/완료 흐름과 저장된 결과의 ACK 복구 문제였다. Codex는 재현 시험(25개 중 failure 5, error 2)을 보존하고 수정 후 전체 63개 테스트를 통과했다.

C1–C7 반영: 종료 이후 새 입력 거부, 저장된 결과의 ACK 재claim, 실제 생명주기 순서의 테스트, launch 시점 실행 파일 해석, SQLite JSON 오류, acceptance_blocker, worker의 coordinator 명령 금지 및 역할 감사. C8–C11 반영: Store 트랜잭션 공통화, 슬롯 상태 상수, 공통 프로토콜 함수, inbox 읽기 트랜잭션. C12는 기존 사후 revision 검사/rollback을 유지하며 외부 효과와 DB의 비원자성 및 대조 의무를 문서화했다. 보안 인증·외부 효과 exactly-once·강제 agent poll은 추가하지 않았다.

이번 변경 후 실제 provider를 재실행한 증거는 없으며 기존 Claude 적용 ACK 실험은 변경 전 메시징 버전의 증거다.

Kiro 재확인은 22개 파일 해시 일치, 격리 사본 63개 테스트와 V1–V7 fixture로 C1–C11 해결/C12 문서화를 확인했다. 새 Low N1은 malformed Task에서도 status가 원장과 task_invalid 사유를 반환하도록 보완하고 회귀를 추가했다. N2는 deliveries가 ACK 복구 claim도 포함한다는 의미를 문서화했다. 이 추가 변경 후 전체 64개 테스트가 통과했다.

## Task assignment and take-over

A Kiro session implemented the assignment follow-up. `uv run python -m unittest discover -s tests -v` passed **74 tests** (10 assignment tests plus the existing messaging, scheduler and contract suites). Existing messaging tests now take over the initial assignment message in their fixture setup; their assertions otherwise stay the same, except that counts exclude the new message.

Deterministic tests cover: identical re-rendering and preserved Task input/prompt hashes; implement/review role rules; scope escapes and Task `write_scope` narrowing; unknown Task, duplicate IDs and the worker-environment guard; all four executor presets with the common model limited to the configured executor and no effort flag; holding an explicit assignment when the instruction revision changes before launch, while a Current Result edit does not; take-over needing the echoed `expect` fields before completion; ambiguous launch with restart keeping attempt/message IDs, and retry reusing the assignment ID with the old attempt fenced; the plan-selected default using the same path; Task change notification with supersession; and the CLI.

**Live Kiro:** one explicit `review` assignment on an isolated read-only fixture ran through `assign` → `tick` → local adapter → launcher → `kiro-cli chat --no-interactive --trust-all-tools --model claude-opus-5.5` (kiro-cli 2.25.0, no effort). The worker claimed `assignment:<attempt>`, recorded an applied report with the `expect` fields and the exact sentinel text, ACKed, and submitted completion. It modified neither the fixture Task (hash unchanged) nor the repository. After exit the attempt waited with `task_not_accepted`. The fixture owner inspected the report and marked the fixture done, and only then did the attempt become accepted. The Kiro first-run consent did not block this run. Orca, Codex/Claude/Qwen live take-over and product implementation work were not exercised on this revision.

## Accepted terminal cleanup

A Kiro session implemented [accepted terminal cleanup](project-scheduler.md#수용-후-terminal-정리). `uv run python -m unittest discover -s tests -v` with `SCHEDULER_*` worker variables unset passed **83 tests** (9 new cleanup tests plus the previous 74).

`tests/test_cleanup.py` launches through the real Orca adapter against a fake Orca CLI that models runtime-issued handles over PTY incarnations and changes volatile fields on each `show`. It covers: no close while running or awaiting acceptance; exactly one `show`+`close` of the owned handle after acceptance, with an unrelated terminal untouched and no second close on repeated ticks or restart; a crash after close resuming as `already_closed` without a second close; close failure/timeout retried only after a new ownership check, ending `failed` and never success; an outer `ok: true` whose `result.close` has another handle, `ptyKilled: false` or a `ptyStopVerdict` is not success; transient failure then success on the same handle; replaced incarnation/PTY, a different runtime or a stale handle becoming `withheld` with no close; missing, partial-format or corrupt identity records withheld without any Orca call; and a local worker with no signal sent.

An earlier interrupted attempt's uncommitted partial edits were the starting point; they were preserved in the operator's Log, but the untracked pre-edit baseline was not recoverable and those edits were not observed by the harness. Against that partial code the new tests fail: its field blacklist compared the create-time `title` with the live one, so the owned terminal was never closed; one unresolved result blocked every retry; and cleanup did not run when the slot was empty.

Live Orca was read only: `terminal list/show` on the worker's own terminal confirmed the `runtimeId` (`_meta`), `ptyId`, `incarnationId` and `worktreeId` fields, and a stale handle returns `ok: false` with `terminal_handle_stale`. The close result shape `result.close = {handle, tabId, ptyKilled[, ptyStopVerdict]}` was read from the installed Orca app bundle, not from a live close. A closed terminal remained visible to `show` with `exitCause`. No terminal was created or closed by this validation. Whether `terminal create` responses always include `_meta.runtimeId` (otherwise cleanup is withheld) remains unverified.

**Later live run (2026-09-29, same day):** the persistent `scheduler run` launched a review attempt through the Orca adapter. In that attempt the Kiro worker applied and ACKed its assignment, wrote a report, submitted completion and exited with code 0. The coordinator accepted the report. On the next tick the scheduler closed exactly the owned terminal: cleanup `closed` with `tries=1`, `ptyKilled: true`, and the handle absent from the Orca terminal list afterwards. The same loop then started the next Task's attempt automatically. The status snapshot and the run's Log are local evidence. Scope: this run used Kiro's headless scheduler launch, not the normal TUI. A separately bootstrapped implementation terminal was closed manually and does not count as automatic cleanup.

## Terminal watch view

A Kiro session implemented the read-only [`watch` command](project-scheduler.md#터미널-진행-조회-watch). With `SCHEDULER_*` worker variables unset and `-W error::ResourceWarning`, `uv run python -m unittest discover -s tests -v` passed **101 tests** (18 new watch tests plus the previous 83).

**Synthetic (`tests/test_watch.py`, fake Orca, isolated fixtures):** a pending assignment with a free slot; a running attempt before and after take-over (delivered/taken_over, queued required message, elapsed time from the started receipt); a completion report shown as not acceptance while the worker still runs; awaiting acceptance with `task_not_accepted`, then accepted with its ledger event time and a closed cleanup; an unapplied extra required message and a withheld cleanup with a missing identity record; a malformed and a missing Task file; an unreadable receipt; a 44-column frame keeping the short attempt ID, state and Task tail; a missing state path that is not created; a missing config; a transient `database is locked` error followed by a normal frame and Ctrl-C; interval validation; preset and explicit executor labels. A read-only test patches tick/assign/notify/resolve/event/cleanup/collect/plan approval, all mailbox writers and the adapter launch/close to fail, and compares a full SQLite dump and the Task bytes before and after. **Real subprocesses:** a local-adapter `scheduler run` with a detached sleeping worker, the watch CLI on a pipe (at least two refreshes, no ANSI) and in a pseudo-terminal (clear/home escape codes). SIGINT to the viewer exits 0 while `run` and the worker stay alive.

**Live ledger (read only):** a check script ran against a demo ledger while a real `scheduler run` and the Kiro worker were running. `--once` printed 71 plain lines; `--width 48` stayed within 48 columns. A piped watch (5 frames, no ANSI) and a pty watch (1 clear, 5 home refreshes, clipped to 40 rows) each exited 0 on SIGINT with the stop message. All three processes were still alive afterwards and the `status` JSON hash was the same before and after. The live ledger shows one running, one accepted/closed and one accepted/withheld attempt. It has no pending, awaiting-acceptance, malformed-Task or failed-query state; those states were covered only by the synthetic tests. How the live screen renders in Orca's own terminal UI and how a person reads it in practice were not verified.

## Task-item reference events

Contract: [scheduler-task-events.md](scheduler-task-events.md). Checked 2026-09-29 by a Kiro worker dispatched through Orca.

- **Deterministic/isolated:** `tests/test_refs.py` (19 tests) covers item boundaries and exact-byte hash, unrelated-edit hash stability, duplicate/nested/unclosed/malformed markers, missing/empty items, outside-directory, nested, `..` and symlink paths, round trip and blocked/completed, duplicate publish and ID reuse, CAS mismatch, ACK loss + lease expiry + process restart returning only the historical receipt after content changed, redelivery reconciliation and delivery limit, change between claim/read and between read/processed (held, never certified), stale/reopened answers, recipient/execution scope, `scheduler:<attempt>` Task ownership, bounded wait holding no transaction while sleeping, and one subprocess test where separate CLI processes play worker and main (timeout exit 3, deferred stream held without blocking another event). Baseline before the change: 101 tests OK; after: 120 tests OK.
- **Live (real participants, fixture Task):** the Kiro worker published `question.opened` for a dedicated fixture Task; the active Orca main received it with its own `ref wait/read/processed/ack`, appended its answer item and published `question.answered`; the worker's background `ref wait` claimed it, read the hash-verified body, wrote the answer token to a file and recorded applied/ACK; the worker then published `work.completed` to the main, which claimed, read, reviewed and recorded an applied ACK. Ledger audit rows and per-step JSON outputs are kept as local evidence. An Orca native ask/reply was used only as bootstrap attention to tell the main that a question was waiting; the answer applied by the worker came only from the Task item via `ref wait/read`, not from the native reply. The fixture Task is dedicated to this demonstration; the documented default is the existing Task with an explicit writer turn.
- **Provider round trip (2026-09-29, one Orca run):** one Codex main supervised separate native-dispatch workers. Each worker had its own fixture Task, and all of them shared one ledger. Each worker used the existing Task with an explicit writer turn. It appended `q-token` and published `question.opened`, then made no Task writes until main appended an answer item and published `question.answered`. The worker then claimed the answer with `ref wait`, read the hash-verified body, wrote the token into its own proof file and recorded `processed applied` + ACK. Next it appended `blocked` and `q-resume` and published `work.blocked` + `question.opened`. Main answered the second question the same way, the worker applied the second token, and it published `work.completed`. Both test answers came only from `ref`, never from the native ask/reply channel, and no worker answered its own question.
  - **Claude** and **Kiro** (normal TUI, claude-opus-5.5, default effort, trust-all) workers, each in its own Orca dispatch, completed the full sequence. The ledger has 12 events (`q-token`, `a-token`, `blocked`, `q-resume`, `a-resume`, `completed` × 2). All 12 are `acked`/`applied`, their sender/recipient execution pairs match the dispatches, and a later independent `ref item` re-read matched every stored item hash. Each worker's proof file holds both tokens matching main's answer items, and each worker's native `worker_done` came after its completion event was stored (Kiro's from its own send receipt, Claude's from main's run record). The Kiro fixture needed `type: task` in its frontmatter before the catalog would accept it.
  - **Codex as worker: not proven.** The Orca `agent_readiness` check failed three times, and no task prompt was injected. The Codex fixture Task is unchanged, and the ledger holds no Codex events.
- **Limits:** participant/execution strings are same-user declarations, not authentication. Markdown writes and SQLite commits are not atomic. Delivery requires the recipient to be actively polling (`wait`), and a stopped or idle session is not woken or restarted. Editing a Task item does not publish an event; `publish` is always an explicit CLI call. There is no automatic approval hook: a worker waiting for approval, or one that was interrupted, is not detected or reported automatically. Crash and permission-UI states are not detected either. Normal scheduler-attempt TUI integration with `ref` remains separate and was not exercised. The legacy mailbox, completion submission and acceptance gates are unchanged and were not exercised by the live runs.

## Scope revalidation and read-only watch repair

Checked 2026-09-30 by a Kiro worker dispatched through Orca. This repairs two defects reproduced in a code review: notify re-certified a narrowed write scope, and watch initialized the ledger through the writer `Store`.

- **Before the fix:** the 13 new regressions in `tests/test_assignment.py` and `tests/test_watch.py` ran against a copy of the unchanged source (`PYTHONPATH` pinned). 8 failed and 2 errored. The 3 that passed are guards: a compatible change, a missing ledger and a non-SQLite file. Without the guard that rejects building a writer `Scheduler`, watch still accepted a foreign SQLite file and a ledger missing tables (exit 0), and its projection failed on a missing column. Before this change the full suite had 120 passing tests.
- **After the fix:** `uv run python -W error::ResourceWarning -m unittest discover -s tests -v` passed **133 tests**. A rerun of the review fixtures showed notify rejected with `scope conflict` and no update or message, and the foreign file keeping its tables, its `delete` journal mode and its bytes. A read-only state check recorded file sizes and hashes, `sqlite_master` objects and the journal mode before and after `watch --once` for seven cases: a valid closed ledger, a valid ledger with an open writer, a foreign SQLite file, missing tables, missing columns, a non-SQLite file and a missing ledger. In every case the ledger bytes, schema and journal mode are unchanged. The only new paths are the SQLite-managed `-wal` (0 bytes) and `-shm` of a WAL ledger.
- **Covered:** scope and outputs narrowed below a running assignment, and a narrower `write_scope` newly introduced. Messages, attempt files and the attempt count stay unchanged, the launch message is held as stale, and the CLI exits 2. Compatible narrowing and widening still send the original assignment scope, which is claimed, applied and ACKed. watch no longer constructs `Scheduler` and uses an ordinary SQLite `mode=ro` connection. It rejects a foreign SQLite file, a ledger missing tables or columns, and a non-SQLite file, and it creates nothing for a missing ledger. The read-only connection rejects writes, and an open writer's committed but uncheckpointed WAL content is visible. Existing writer initialization (WAL), run/tick and watch frame tests are unchanged and pass.
- **Limits:** write scope is still a collaboration contract, not OS isolation. The conflict is a synchronous diagnostic to the coordinator, not a durable ledger record, and no worker is told automatically. SQLite may leave its empty `-wal` and `-shm` read-lock files beside a WAL ledger that no writer holds open. A live Orca/provider run of these paths was not performed.

## Backend-template storage and validation cleanup

Checked 2026-09-30 by a Kiro worker dispatched through Orca. This implements accepted design slice 1 (F1–F8) of a local structure design review.

- **F1 defect:** `plan()` saved `catalog`, `order` and each `project:*` in separate autocommits. After an interruption between those writes, the next tick skipped the accepted planner order. Those writes are now one transaction. The planner intent, accepted/rejected updates and the external planner call stay where they were. Against the unchanged source, the new regression `test_interrupted_plan_metadata_keeps_accepted_order` fails (partial `catalog` stored). After the fix it passes, and the design reproduction's second tick launches the next Task with one planner call.
- **Structure:** `runtime.py` has no direct SQL. Named `Store` methods, and three message reads (then on `Mailbox`, now in `protocol_store.MessageStore`), run the same SQL and JSON encoding. Transaction, lock and external-call placement is unchanged apart from F1. Event, launch-eligibility, explicit-assignment and cleanup-cap decisions are pure functions in `validation.py`. The cleanup state constants live in `store.py`, so `watch` no longer imports the writer. `notify_change` is now `notify`, and the `acceptance_ready` and `Scheduler.cleanups` wrappers are removed.
- **Checks:** `uv run python -W error::ResourceWarning -m unittest discover -s tests -v` passed **141 tests**: 133 existing, 1 F1 regression and 7 pure-decision tests. Existing tests changed only for the `notify` rename. CLI `--help` for the root, every subcommand and every verb, plus the ledger schema, is byte-identical before and after.
- **Limits:** this slice deferred design items T1, T2, M8, M9 and M10; the next section completes them. The F1 interruption is injected in tests, not provoked by real SQLite contention. A live Orca/provider run was not performed.

## Typed contracts, pure Task parsing and protocol storage

Checked 2026-09-30 by a Kiro worker dispatched through Orca. This completes design items T1, T2, M8, M9 and M10.

- **Structure:**
  - The assignment contract is the frozen `assignment.Assignment`. Its `record()` is the only external form, and `from_record()` validates a stored contract once at the storage boundary.
  - Attempt rows are the frozen `store.Attempt`, and `status` serializes it with `dataclasses.asdict` in column order.
  - `model.parse` and `model.check_dependencies` are pure. `Catalog.read` only reads files and checks duplicate paths.
  - `Scheduler.notify` holds the scheduler lock for the whole operation, and the CLI no longer adds a second lock.
  - The message and reference SQL moved to `protocol_store.MessageStore/RefStore`. Their operational methods never begin, commit or roll back a transaction. `Mailbox` and `References` keep every verb, check, transaction boundary, recheck point and clock reading.
  - The ref DDL moved from `refs.SCHEMA` to `protocol_store.REF_SCHEMA` with byte-identical text. No `refs.SCHEMA` Python symbol is kept; this is an internal API change only. `References()` still initializes the table at construction through `RefStore.__init__`, using the same `executescript`. Because this is SQLite `executescript`, it implicitly commits any transaction that is already open, as it did before. Read-only `Query`/watch never construct `References`.
- **Compatibility:** each check compares against a full-byte copy of the previous source.
  - Golden capture: identical bytes for `assignment.json`, `spec.json`, the rendered update and prompt, the stored contract column, `auto_id`, the assign/notify/tick/status/assignments JSON, and `Catalog.read` results and errors over 33 Task-file cases. One preserved quirk: explicit attempts write `assignment.json` with sorted keys, while auto attempts use build order.
  - Ledger load: identical loads of 9 preserved real ledgers.
  - Protocol trace: identical SQL text and order, `BEGIN`/`COMMIT` boundaries and clock-read positions across 55 message/reference protocol steps, with 11 expected rejections.
  - CLI `--help` and the ledger schema are byte-identical.
- **Tests:** `uv run python -W error::ResourceWarning -m unittest discover -s tests -v` passed **151 tests**: 141 existing plus 10 new (2 for M9, 1 for T1, 1 for T2, 3 for M10 pure parsing and 3 for contention). The coordinator independently reran the suite and the compatibility checks before accepting the change.
  - `tests/test_contention.py` passes on both the previous and the current source. It covers a three-process reference claim with a single owner; superseded message and reference tokens that cannot read, record or ACK; and an audit failure injected with a SQLite TEMP trigger, which rolls back every protocol write. A hidden `COMMIT` injected into a claim makes that test fail.
  - The new direct-notify lock test fails on the previous source.
  - Existing tests changed only for typed attribute access and the storage method location. No assertion was removed or relaxed.
- **Limits:** no live Orca, provider or worker run was performed; contention was exercised only on isolated temporary ledgers. Markdown writes and SQLite commits are still not atomic together. The golden, ledger and trace capture scripts ran against local copies and are not part of this repository.

## Idle Orca recipient wake

Checked 2026-09-30 by a Kiro worker dispatched through Orca. Contract: [scheduler-task-events.md](scheduler-task-events.md#유휴-orca-수신자-wakebest-effort).

- **Change:** `ref publish --wake` (after the commit) and the recovery verb `ref wake --to R --to-exec orca:H [--id EVT]` send one fixed prompt to an idle `orca:<handle>` recipient execution: pending-event and duplicate gate → `orca terminal show` (not stale/orphaned) → `orca terminal wait --for tui-idle` → gate recheck → one `orca terminal send --enter`. Outcomes go to the existing `message_audit` as `ref.wake_requested|wake_skipped|wake_failed` with the Orca receipt fields. No new table, queue or daemon; existing publish/claim/read/processed/ack and messaging/assignment code paths are unchanged. The Orca calls reuse `adapters._orca_json`.
- **Tests:** `tests/test_ref_wake.py` (7 tests) runs a fake `orca` executable given by `--orca`/explicit path or found on `PATH`: idle → exactly one send and `wake_requested` with `stages: [input_accepted]`, `provider: unsupported`; busy (tui-idle timeout) → no send, event queued and claimable; duplicate suppressed until a claim by that execution or the cooldown; missing/non-JSON orca, stale handle, orphaned terminal, failed idle check, rejected and unknown send → `wake_failed`, event still stored and claimable, unknown send never resent; non-Orca recipient → `not_orca`, `supported: false`, no Orca call; CLI `publish --wake` with a missing orca still `stored: true`, exit 0; the sent prompt is one line whose runnable prefix is exactly this venv's Python, `-m scheduler` and the publishing process's absolute `--config`/`--state` plus `ref wait --as TO --exec TO_EXEC --timeout 60`, with no item body (API and CLI paths), and a state path containing a space is shell-quoted. `uv run python -W error::ResourceWarning -m unittest discover -s tests -v` with `SCHEDULER_*` unset: 151 existing + 7 new = **158 tests OK**.
- **Not verified:** a real idle Kiro main resumed by a worker event through this product code (the capability probe only showed Orca input starting a Kiro turn when idle and steering a busy turn). Orca cannot report Kiro turn start; that needs the recipient's later `ref.claimed` or its session transcript. Other providers' tui-idle behavior, and the non-atomic idle-check/send window, are untested.

## Session overview in watch (phase 1)

Checked 2026-09-30 by a Kiro worker dispatched through Orca. Contract: [project-scheduler.md](project-scheduler.md#세션-대기문제진행-조회).

- **Change:** `watch` shows WAITING, PROBLEMS, PROGRESS (the existing attempt view) and SESSIONS, with `--project ID` (repeatable), `--json` and `--harness-root`/config `harness_root`. Sources are the ledger, `ref_events` plus wake rows in `message_audit` (mode=ro connection), Task frontmatter in the configured task dirs, and the harness public `work status` JSON. There is no new table, cache, server or daemon, and Orca is not called. `scheduler/watch.py` +319/−57 lines, `scheduler/cli.py` +4/−1.
- **Harness output check:** `work status` returns `id` (`agent:session`), `workspace`, `project`, `task`, `task_path`, hashes, `calls` and `issues`, with exit 1 when any session has issues. There is no time field, so the last-observed time is shown as unavailable.
- **Tests:** `tests/test_watch_overview.py` adds 7 tests on isolated fixtures with two projects and a fake harness executable:
  - the four sections in order, with queued/held/stale refs, repeated busy and failed wakes, blocked/review/malformed Tasks, failed attempts and harness issues;
  - `--project a` and `--project b` excluding the other project's refs, Tasks, attempts and sessions (the shared slot is labelled);
  - `--json` equal to the overview data the frame renders, including through the CLI;
  - harness not configured, missing root, non-JSON, JSON without sessions, bad session id, exit 3, timeout and launch error, all shown as unavailable while the other sections still render;
  - a missing ledger (exit 2, Task and harness sections still shown, nothing created);
  - a ledger without `ref_events` (reported, dump unchanged);
  - read-only checks: writer, mailbox, `References` and `RefStore.__init__` patched to fail; the ledger dump, all Task bytes and the harness output hash equal before and after; the fake harness was called only with `work status`.
  
  With `SCHEDULER_*` unset, `uv run python -W error::ResourceWarning -m unittest discover -s tests` ran 158 existing + 7 new = **165 tests OK**.
- **Live (read only):** `.artifacts/scheduler/session-overview/live-check.sh` copied the `main-wakeup/live` ledger to a temp dir and ran `watch --once` with the vault harness. With `--project live --project llm-wiki`, queued `ev-live-wake-1` (waiting on `orca:term_072da485-…`, last wake `wake_skipped busy`) is under WAITING, and `kiro:6cd886fe-a25b-4ff0-afcf-093a75fe3b76` (llm-wiki, `llm-wiki-scheduler-main-wakeup`) is under SESSIONS. `ev-live-wake-1` belongs to the demo config's project `live`, so `--project llm-wiki` alone excludes it by design and still shows the session. The `--json`, `--width 60` (no line over 60 columns) and no-harness runs exited 0. The hashes of the source ledger, the copy, the Task file, the config and the `harness work status` stdout were equal before and after. In one earlier unrecorded run the harness stdout hash differed; the follow-up below traced this to a concurrent session.
- **Not verified:** session liveness, idle state and last activity (phase 2, Orca). CLI approval waits have no source (`unsupported`). Answer staleness is shown only after the ledger holds the event. A person reading the TTY screen in Orca was not checked. Harness latency per refresh was not measured.
- **Follow-up (same day): session order and cap.** SESSIONS lists the newest bind first, as the reverse of the harness output order, and shows at most 8 rows by default. `--sessions N` or `--sessions all` changes the cap; the extra rows are reported as `N more not shown`, and `--json` keeps the full list. The order basis is printed on the `order` line and in `session_order`. `work status` runs `SELECT * FROM work_sessions` without `ORDER BY`, so this is first-bind (rowid) order as observed: a newly bound session appeared last, and a rebind keeps its place. It is not a documented guarantee and not a timestamp. One new test covers the cap, `all`, `2`, the full `--json` list and invalid values; the suite ran **166 tests OK**. On the live copy, 8 of 29 llm-wiki sessions were shown with 21 more not shown, today's two Kiro sessions first. The hashes were equal before and after.
- **Harness hash difference explained.** `.artifacts/scheduler/session-overview/hash-repro.sh` made 40 `work status` captures, 10 `watch --once --json` runs and 10 idle gaps over 27 seconds. It used `stat` only on `.local/harness/hook-state.sqlite` and its `-journal`/`-wal`/`-shm`; the database was not opened or copied.
  - The output changed twice: once across a watch run and once across an idle gap with no command. Both changes were a concurrent Codex session (`codex:01a0eb28-…`, vault workspace, hook-observed `exec-*` calls) adding and then clearing a pending call. The database mtime changed around those moments, including during an idle gap, and a rollback `-journal` briefly appeared from that writer.
  - 47 of 50 calls saw no mtime or size change. A write by `status` or `watch` would change the mtime on every call. The hook database uses a rollback journal; there is no `-wal`.
  - In code, `work status` opens an ordinary writable connection and runs `CREATE TABLE IF NOT EXISTS` and `commit()`. This is a no-op when the tables exist, but on a vault with no harness state it would create `.local/harness/hook-state.sqlite`. That case was not exercised.
  - So the earlier difference was another agent's harness activity during the check, not a write by watch. The same `codex:01a0eb28` pending-call flicker appears in the first live frame (15:18).

## Session overview in watch (phase 2)

Checked 2026-09-30 by the same Kiro worker. Contract: [project-scheduler.md](project-scheduler.md#세션-대기문제진행-조회).

- **Change:** two optional sources, each shown as `unavailable` on its own without blocking the frame.
  - Last activity comes from `os.stat` of the CLI's own session file for the session ID. This machine uses `~/.kiro/sessions/cli/<id>.jsonl`, `~/.codex/sessions/*/*/*/rollout-*-<id>.jsonl` and `~/.claude/projects/*/<id>.jsonl`. The harness listed 19 Kiro, 25 Codex and 17 Claude sessions; 17, 22 and 16 of them had exactly one matching file.
  - Orca is read through `status`, `terminal list` and `orchestration worker-list`, checked with `--help` and the bundled `orca-cli`/`orchestration` skills. A terminal joins a harness session only through a ref event that pairs that session key with a terminal execution identity. Other live terminals, filtered to the project repos and session workspaces, are listed under `TERMINALS, SESSION UNKNOWN` with labelled Orca, dispatch, ref and attempt facts.
  - Kiro turn markers (`<pid>-<ms>.json`) were not used, because mapping one to a session requires reading its contents.
  - `scheduler/watch.py` grew by +130 lines in this phase and is 734 lines total (+458/−57 vs HEAD).
- **Tests:** `tests/test_watch_phase2.py` adds 4 tests using a fake `orca` executable and temp session-file homes:
  - Kiro, Codex and Claude mtimes, plus an absent file;
  - a ref-evidenced terminal linked to its session; an unlinked terminal with its dispatch; an attempt terminal carrying `terminal.json` evidence; another worktree excluded by `--project`; a queued ref whose recipient terminal is not live, shown under PROBLEMS;
  - Orca absent, returning non-JSON, not ready, `ok:false`, `terminal list` failing with `terminal_handle_stale`, and `worker-list` missing, all rendered without blocking;
  - stat only: the session files are mode 000 and `open`/`io.open`/`os.open` on them fail the test, yet mtimes still render and no content or preview appears. The fake `orca` saw only the 3 read-only verbs.
  
  Existing watch fixtures now point `orca_command` at a missing path so they stay hermetic. With `SCHEDULER_*` unset, the suite ran **170 tests OK**.
- **Live (read only):** `.artifacts/scheduler/session-overview/phase2-live-check.sh` ran `--once` on a copy of `main-wakeup/live` with the real Orca and vault harness, filtered to `live` and `llm-wiki`.
  - WAITING still has `ev-live-wake-1`.
  - SESSIONS shows mtimes for recent Kiro sessions: `kiro:7369c6af…` at 15:41:40 and `kiro:6cd886fe…` at 14:14:03.
  - `TERMINALS, SESSION UNKNOWN` lists 4 terminals. `term_614fadc5-…` has its dispatch `ctx_4d67e4910ca0`. No record pairs it with `kiro:7369c6af…`, so it stays unlinked. The coordinator `term_072da485-…` and `term_334b0aba-…` appear with their ref evidence.
  - Hashes of the source ledger, the copy, the demo Task, the config, this Task and the `harness work status` stdout were equal before and after. `hook-state.sqlite` mtime and size were also unchanged.
- **Not verified:**
  - that session-file mtime tracks every turn for each provider (a write can lag or batch);
  - Orca `lastOutputAt` is terminal output time, not agent idleness; dispatch liveness was `unverifiable/missing_status` for these external terminals;
  - remote Orca hosts (`--include-remote` not used), and `worker-list` pages beyond the first 100 rows;
  - CLI approval waits (still `unsupported`).

## Harness terminal link in watch

Checked 2026-09-30 by Kiro worker `kiro:0211505e-1840-462d-b221-d5e80250d378` (terminal `term_1cb0ea3c-…`), Task `llm-wiki-session-terminal-link` product step. Contract: [project-scheduler.md](project-scheduler.md#세션-대기문제진행-조회).

- **Change:** `scheduler/watch.py` reads the `terminal`/`terminal_source` fields that the vault harness now puts in `work status` JSON. A session links to a live Orca terminal only when `terminal == "orca:<handle>"` exactly. The session then shows the handle, worktree, Orca fields, dispatch and `link harness terminal (<source>)`, and the terminal leaves `TERMINALS, SESSION UNKNOWN`. A ref pairing for the same terminal stays as a secondary `ref pairing` label. A value that does not match a live handle is shown as recorded, not linked. With Orca unavailable the value is shown as `not verified live: Orca unavailable`. Sessions without the fields keep the previous behaviour, including ref-only linking. No new table, daemon or dependency; still read-only.
- **Tests:** `tests/test_watch_terminal_link.py` adds 5 tests on the phase-2 fixture: exact match links (including a terminal outside the `--project` worktrees); six near-miss values (suffix, missing `orca:`, case, other agent prefix, space, truncated) plus absent/`null` stay unknown; Orca down or missing shows the recorded value unverified; harness link plus ref pairing; old output (no fields) and `null` fields give identical JSON with the ref-only link unchanged. With `SCHEDULER_*` unset and `-W error::ResourceWarning`, the suite ran **175 tests OK** (the previous 170 plus 5).
- **Live (read only):** vault `wiki/log/20260930T-session-terminal-link/product/live-check.sh` ran `watch --once --project llm-wiki --sessions all` on a copy of `main-wakeup/live` with the real Orca (12 live terminals) and vault harness (66 sessions). `kiro:0211505e…` showed `terminal term_1cb0ea3c-1c67-424e-a51b-2fc6070962f6` with its dispatch `ctx_07266429cdba` and `link harness terminal (env)`. `kiro:88782dd6…` showed `term_14f99595-a826-4861-b089-8399a5b4aadf` with `ctx_28c79c64e602`. `kiro:7369c6af…`, bound before the harness change, had no terminal field. Neither linked terminal appeared under `TERMINALS, SESSION UNKNOWN`. Both runs exited 0, and the ledger hashes were unchanged.
- **Not verified:** that the recorded value belongs to the session (it is self-reported at bind), remote Orca hosts, and Codex/Claude hook processes recording the handle.
