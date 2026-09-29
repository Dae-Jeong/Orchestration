# Compact project scheduler

수동으로 시작하는 Python 지속 프로세스가 기존 Markdown Task를 읽고 한 번에 하나씩 실행한다. 메인 LLM은 우선순위 충돌, 연결 작업 유입, 계획을 무효화하는 변경에만 실행 순서를 반환한다. 일상 배정·종료 수집·수용 확인·재시작 복구는 Python과 SQLite가 담당한다.

## 시작

Python 3.11 이상, `uv`, 로컬 POSIX 파일시스템이 필요하다. `uv sync --locked`로 설치한다. 아래 JSON을 Git 밖의 `.runtime/scheduler.json`에 작성하고 실제 프로젝트 경로와 **이미 승인된** worker 명령을 넣는다. `examples/scheduler/config.json`은 경로를 채우는 예시이며 바로 운영할 설정이 아니다.

```json
{
  "adapter": "auto",
  "executor": "codex",
  "planner_command": ["/absolute/orchestration/.venv/bin/python", "-m", "scheduler.claude_planner"],
  "projects": [
    {"id": "project-a", "repo": "/absolute/project-a", "tasks": "/absolute/vault/project-a/tasks"},
    {"id": "project-b", "repo": "/absolute/project-b", "tasks": "/absolute/vault/project-b/tasks"}
  ]
}
```

공통 `executor`는 `claude`, `codex`, `qwen`, `kiro` 중 선택하고 선택적 `model`도 같은 설정 파일 한 곳에 둔다. Task에는 실행자·모델 boilerplate를 추가하지 않는다. 2026-09-29 사용자 지정 정책에 따라 새 worker를 다음 argv로 시작한다. effort 옵션은 전달하지 않아 기존 기본값을 유지한다. 실행 중 세션은 이 정책 변경으로 재시작하지 않는다.

| 실행자 | 새 worker 기본 명령 |
| --- | --- |
| Claude | `claude --print --dangerously-skip-permissions` |
| Codex | `codex exec --dangerously-bypass-approvals-and-sandbox` |
| Qwen | `qwen --yolo` |
| Kiro | `kiro-cli chat --no-interactive --trust-all-tools --model claude-opus-5.5` |

명시적인 공통 `model`은 CLI의 `--model`로 전달한다. Kiro는 사용자 정책에 따라 `claude-opus-5.5`로 고정하며 다른 값을 지정하면 거부한다. 다른 실행자는 모델을 생략하면 도구 기본값을 따른다. prompt는 launcher가 stdin에서 읽어 하나의 argv 인자로 전달하며 shell 해석을 하지 않는다. scheduler가 preset 실행 파일을 자신의 PATH에서 절대 경로로 확인해 spec에 저장하므로 Orca terminal의 다른 PATH가 다른 CLI를 선택하지 않는다. 도구 내부가 호출하는 하위 명령·인증 환경은 해당 runtime에 의존한다. Codex preset은 Git repo를 전제로 하며 `--skip-git-repo-check`를 자동 추가하지 않는다. 설치된 네 CLI의 help에서 위 옵션을 확인했고 fixture 실행 파일로 실제 argv 전달을 검증했다. 네 provider가 실제 제품 Task를 끝까지 수행하는 시험은 아니다.

Kiro preset은 headless(`--no-interactive`) scheduler 실행 경로다. Orca native dispatch로 여는 일반 Kiro TUI 세션(`claude-opus-5.5`, trust-all, 기본 effort)과는 다른 실행 방식이며, [provider 왕복 검증](project-scheduler-validation.md#task-item-reference-events)은 일반 TUI 세션으로 수행했다. scheduler attempt를 일반 TUI로 실행하는 통합은 없다.

**CLI 실행 지원과 중앙 harness 세션 기록 지원은 다르다.** 중앙 harness는 이 clone에 포함되지 않는 [외부 환경](external-dependencies.md)이다. 운영자의 현재 로컬 harness는 `work bind/record --agent codex|claude|kiro`를 받아 실제 Kiro session ID로 제품 쓰기를 Task에 연결할 수 있다. 이 지원은 해당 harness 설치 버전에 의존하므로 사용 전 `harness work bind --help`의 `--agent` 선택지를 확인한다. Qwen bind는 지원하지 않으며, 다른 agent 이름으로 bind하거나 scheduler attempt ID를 session ID로 쓰지 않는다.

비-LLM 프로그램이나 별도 wrapper가 필요하면 `command` argv 배열을 명시한다. 이 명령은 prompt를 stdin으로 받고 preset보다 우선하며 정책 플래그를 임의로 삽입하지 않는다. 프로젝트별 `command`·`adapter`도 지정할 수 있다. `SCHEDULER_ATTEMPT`, `SCHEDULER_TASK`, `SCHEDULER_TASK_PATH`, `SCHEDULER_RESULT_DIR`를 worker 환경에 제공한다.

```sh
uv run python -m scheduler --config .runtime/scheduler.json --state .runtime/scheduler status
uv run python -m scheduler --config .runtime/scheduler.json --state .runtime/scheduler tick
uv run python -m scheduler --config .runtime/scheduler.json --state .runtime/scheduler run --interval 2
```

`tick`은 한 번 처리하며 실제 실행을 시작할 수 있다. `run`은 같은 처리를 반복한다. Ctrl-C/SIGTERM은 scheduler만 멈추며 이미 시작한 worker는 계속 실행한다. 같은 설정과 state 경로로 재시작하면 영수증을 수집한다. 설치형 daemon이나 자동 게시 기능은 없다. 프로세스가 살아 있어야 신규 Task 유입을 탐지한다.

**모든 참여 프로젝트와 scheduler 프로세스는 하나의 state 디렉터리를 공유해야 한다.** 경로별 OS lock과 DB unique index로 이 범위에서 전체 단일 슬롯을 보장한다. 서로 다른 state 디렉터리, 다른 호스트, 사람이 별도로 시작한 실행까지 잠그는 기능은 없다. 실행 중 state를 지우거나 복사해 새 실행기로 사용하지 않는다. 설정 hash는 최초 tick에서 고정된다. ledger를 다른 repo·명령·adapter 설정에 재연결하면 거부한다. Task 추가·수정은 같은 Task 디렉터리에서 반영되며 프로젝트 목록 변경은 현재 실행을 모두 정리한 후 별도 구성을 준비하는 운영 작업이다.

### 터미널 진행 조회 `watch`

```sh
uv run python -m scheduler --config .runtime/scheduler.json --state .runtime/scheduler watch            # 2초마다 갱신
uv run python -m scheduler --config .runtime/scheduler.json --state .runtime/scheduler watch --once     # 한 화면만 출력
uv run python -m scheduler --config .runtime/scheduler.json --state .runtime/scheduler watch --interval 5 --width 80
```

`status`와 attempt 디렉터리의 영수증(`spec`·`started`·`exited`·`terminal.json`)을 매번 다시 읽어 사람이 읽는 화면으로 보여 주는 **조회 전용** 명령이다. tick·launch·claim·ACK·close·Task 수정을 호출하지 않고 하위 프로세스도 만들지 않는다. 표준 라이브러리만 쓴다. 새 정본이나 캐시를 만들지 않으며, 없는 config·state 경로는 오류로 표시할 뿐 생성하지 않는다. 원장은 SQLite `mode=ro` 연결로 열며 스키마 생성·migration·journal mode 변경을 하지 않는다. WAL 원장에서는 SQLite가 읽기 잠금용 `-wal`·`-shm` 파일을 스스로 만들 수 있다. 이때 `-wal`은 비어 있고 원장 파일 byte는 바뀌지 않는다. scheduler 원장이 아닌 SQLite 파일, 테이블·열이 빠진 이전·불완전 원장, SQLite가 아닌 파일은 변경 없이 `ERROR`로 진단한다. 원장 초기화는 writer(`run`·`tick` 등)만 한다.

- 상단: 조회 시각, state 경로, 실행 슬롯(`free` 또는 현재 attempt), launch 전 `pending`·`held` 배정.
- attempt별(실행 중인 것부터, 그다음 최신 순서로 최대 8개): 전체 attempt ID, Task 파일 상태(`status`, 읽기 실패·없는 파일·malformed 표시), assignment·role, 실제 executable(설정 command의 `argv[0]` 또는 preset launcher의 `--executable`)과 model, 원장 상태, 시각, delivered/taken_over, 메시지 상태별 개수와 미처리 required 메시지, worker 완료 보고, 수용 여부와 blocker, cleanup 상태, terminal handle과 identity 기록 여부, stdout/stderr 경로와 크기를 **각각 별도 줄**에 표시한다.
- 시각은 출처를 함께 적는다. `launched`는 원장, `started`·`exited`는 worker 영수증, 수용은 원장 `accepted` 이벤트 시각이다. 경과 시간은 started 영수증 시각이 있을 때만 계산한다. 영수증에 시각이 없으면 `receipt without time`으로 표시한다.
- worker 완료 보고는 `worker report, not acceptance`로 표시하고 수용·terminal 종료와 구분한다. 수용 전 attempt의 cleanup은 `not eligible`, `withheld`·`failed`는 운영자 확인이 필요한 `[operator]`로 표시한다.
- TTY에서는 화면 맨 위로 이동해 같은 화면을 덮어쓰고 터미널 높이에 맞춰 자른다. 파이프·파일 출력과 `--once`에는 ANSI 코드를 쓰지 않는다. `--width`(기본값은 TTY 폭, 비TTY는 0이며 0은 자르지 않음)를 주면 긴 값의 가운데를 `~`로 줄이고 앞의 식별자와 끝의 경로는 남긴다.
- 조회가 실패하면(DB 잠김, config 오류 등) `ERROR` 화면을 보여 주고 다음 간격에 다시 조회한다. `--once`는 이 경우 exit 2로 끝난다. Ctrl-C는 viewer만 끝내고(exit 0) scheduler와 worker에는 signal을 보내지 않는다.

## Task 최소 계약과 소유권

Task 디렉터리 바로 아래 `.md`를 읽는다. `type: task` 또는 `kind: task`와 안정적인 `id`가 필요하다. 기존 `status`, `depends_on`, `evidence`, `project_id`, `title`을 소비하며 새로운 선택 메타는 `priority`뿐이다. 별도 workflow DSL은 없다.

| 필드 | 기본값·의미 |
| --- | --- |
| `status` | 생략 시 `ready`. `ready`만 새 배정 가능. `active`, `review`, `blocked`, `cancelled`, `done`은 배정하지 않음 |
| `priority` | 정수 `0`. 큰 수가 우선, 동일 우선순위의 최초 선택·새 유입 충돌은 고수준 계획 요청 |
| `depends_on` | `[]`. 같은 프로젝트의 Task ID, 또는 명시적인 `project/id`로 프로젝트 간 선행 조건 |
| `evidence` | `[]`. `done`이며 비어 있지 않은 evidence 목록이면 중앙 Task에서 수용됐다는 선언으로 소비 |
| `project_id` | 설정의 프로젝트 ID. 명시한 값이 다르면 거부 |

Task ID는 영문·숫자·`_.-` 조합이다. `(project, id)`로 분리하므로 다른 프로젝트에서 같은 ID를 쓸 수 있다. 모든 선행 Task가 설정된 범위에 존재해야 하며 누락·순환·중복 ID·잘못된 메타는 실행을 멈추고 진단한다. Goal·Scope·Acceptance Criteria는 계획 문맥이고 Current Result·Next Action의 일반 기록 변경은 재계획 이유가 아니다.

중앙 Markdown은 업무 상태의 유일한 정본이다. worker가 전체 Task·AGENTS를 읽고 실제 세션을 bind하며 기존 보존·검증·기록 절차를 수행한다. scheduler는 Task를 수정하거나 테스트 통과를 판단하지 않는다. `done + evidence`는 담당자가 완료 조건을 검증했다는 **선언**이며 evidence 파일 내용·테스트 품질·의미적 수용을 scheduler가 인증하지 않는다. 기존 다른 담당자가 실행 중인 Task는 `ready`로 두지 않는다. Markdown 편집과 DB 선점 사이의 다중 파일 원자성이나 외부 작성자 잠금은 제공하지 않는다.

이미 실행한 Task는 파일이 바뀌어도 자동 재실행하지 않는다. 수용된 Task ID를 새 작업으로 재사용하지 않고 새 목표에는 새 Task를 사용한다. 확정 실패도 반복 실행하지 않으며 명시적인 복구가 필요하다.

## 대상별 지시와 ACK

새 attempt에는 [메시지함·처리 ACK 계약](scheduler-messaging.md)이 적용된다. 공통 CLI로 send/inbox/claim/processed/ack/complete를 사용하며 저장 확인·적용 ACK·완료 제출·Task 수용을 분리한다. 기존에 시작한 attempt는 재시작하지 않고 legacy 방식으로 종료한다.

attempt에 묶이지 않은 양방향 질문·답변·완료·막힘은 [Task 항목 참조 이벤트](scheduler-task-events.md)(`ref` 명령)를 쓴다. 기존 메시지함과 acceptance gate는 바뀌지 않는다.

## 배정과 실행 지시

모든 launch는 [배정 계약](scheduler-assignment.md)을 거친다. `assign`으로 역할·허용 범위·산출물을 명시하거나 계획이 고른 Task에 기본 배정을 만든다. 실행 입력은 Task 발췌·배정·공통 규약으로 결정적으로 렌더링되고 원문·hash와 함께 attempt 폴더에 보존된다. worker는 필수 인수 메시지를 ACK해야 완료를 제출할 수 있다.

## 실행·이벤트·복구 계약

`state/ledger.sqlite3`는 계획 요청/응답, attempt, 이벤트와 프로젝트별 계획 projection을 저장한다. 업무 상태 보드는 아니다. `state/attempts/<UUID>/`는 실행 spec, stdout/stderr, 시작·종료 영수증을 보존한다. 제품 증거는 해당 repo에 남기고 중앙 Task는 그 결과를 연결한다. 실행 로그에는 작업 내용이 들어갈 수 있으므로 state는 개인 로컬 경계에 둔다.

| 실행 상태 | 의미·다음 처리 |
| --- | --- |
| `launching` | 외부 호출 전에 intent를 DB에 확정. 여기서 중단되면 자동 launch 재시도 없음 |
| `running` | launch 응답 또는 시작 영수증 확인. timeout만으로 슬롯을 해제하지 않음 |
| `unknown` | 외부 호출 결과 불명. 기존 영수증/실제 terminal·프로세스를 조사하고 유지 |
| `awaiting_acceptance` | 종료 code 0 수집. Task의 `done + evidence`와 현재 revision/inbox의 완료 제출·필수 메시지 해결까지 슬롯 유지 (legacy는 기존 수용 조건) |
| `accepted` | 실행 종료·중앙 수용 선언·새 protocol의 완료/필수 메시지 gate를 모두 관측. 다음 Task의 선행 조건 검사 |
| `failed` | 종료 실패 또는 로컬 OS의 확정적인 생성 실패. 슬롯 해제, 자동 재시도 없음 |
| `retry` | 운영자가 이전 worker와 child의 정지를 확인하고 새 attempt를 허용 |

외부 실행 전 intent 확정과 unique slot, tick OS lock을 함께 사용한다. scheduler가 launch 전후에 죽으면 기존 attempt를 복구하며 다른 adapter로 fallback하지 않는다. worker의 exclusive lock과 시작 영수증은 같은 spec을 다시 호출해도 명령을 반복 실행하지 않도록 한다. 시작 영수증만 있고 종료 영수증이 없으면 재실행하지 않는다. 성공 exit 후 지연된 started 이벤트, 이전 attempt의 완료 이벤트는 stale로 기록한다. 같은 event ID의 같은 내용은 중복 반영하지 않으며 다른 내용을 재사용하면 거부한다.

worker 명령은 종료할 때 자신의 작업 프로세스를 모두 끝내야 한다. background 자식/원격 작업을 남긴 명령의 종료를 scheduler가 전체 실행 종료로 증명할 수는 없다. OS 강제 종료·전원 장애·원격 Orca·NFS에 대한 보장은 없다. 로컬 scheduler 재시작과 응답 유실은 아래 시험 범위에서 검증했다.

복구 시 `status`, attempt 디렉터리와 해당 terminal/프로세스를 확인한다. PID만으로 재사용된 프로세스를 종료하지 않는다. 실제 worker와 child가 모두 끝났다는 증거를 확보한 뒤 다음 명령을 사용한다.

```sh
uv run python -m scheduler --config .runtime/scheduler.json --state .runtime/scheduler resolve \
  --attempt ATTEMPT_UUID --outcome retry --stopped --evidence '/absolute/result-or-investigation.json'
```

`--stopped`는 운영자의 확인 진술이다. scheduler의 프로세스 종료 인증 기능이 아니다. `--outcome failed`는 재실행을 허용하지 않고 슬롯만 해제한다. 같은 Task의 최신 attempt만 복구할 수 있다. 모호한 launch를 확인 없이 retry하면 중복 외부 효과가 생길 수 있다. 직접 DB 수정이나 state 삭제로 우회하지 않는다.

외부 이벤트 ID는 `external:` namespace로 저장해 파일 영수증 ID와 충돌하지 않는다. `event --id EVENT_ID --attempt ATTEMPT_UUID --kind exited --code 0`은 신뢰된 로컬 통합이 실제 종료를 보고하는 인터페이스다. 원격 인증 endpoint가 아니며 같은 사용자에게 쓰기 권한이 있는 CLI다. 일반 사용에서는 worker 파일 영수증을 자동 수집하므로 수동 이벤트가 필요 없다.

## 고수준 LLM 계획

Python은 선행 조건·상태·단일 슬롯을 매번 확인한다. LLM은 허용된 Task의 순서만 반환한다. Task 생성, 상태 변경, 임의 명령, 의존 관계 수정, 강제 선점은 응답 스키마에 없다.

계획 요청에는 `revision`, `reason`, 프로젝트별로 구분된 Task 목록(우선순위·선행 관계·목표·범위·완료 조건), 이전 순서가 들어간다. 다음 때만 호출한다.

- 최초 또는 새로운 Task 유입에서 동일 우선순위 충돌.
- 서로 연결된 작업의 최초 묶음 또는 기존 계획과 연결된 작업 유입.
- 기존 우선순위·의존 관계·목표·범위·완료 조건·실행 가능 상태 변경, 미수용 Task 제거/취소.

실행 중에는 현재 attempt를 유지하고 계획 변경은 슬롯이 비면 처리한다. 일반 완료로 수용된 Task가 빠질 때는 기존 순서를 유지하고 LLM을 부르지 않는다. 충돌 없는 독립 작업은 우선순위와 안정적인 key 순서로 선택한다. 실패한 Task의 재시도 결정도 자동 LLM 호출로 바꾸지 않는다. 이 scheduler가 실행한 worker의 일반 `ready→active/review` 기록 변경은 실패/복구 이후에도 재계획 이유가 아니다. 실제 배정에는 여전히 `ready`가 필요하다. 신규 유입의 우선순위 비교는 ready Task끼리 수행한다.

`planner_command`는 JSON stdin → JSON stdout인 argv 배열이다. provider가 설치되지 않아도 요청을 영속화하고 `needs_planner`로 대기한다. 응답은 정확히 다음 두 필드다.

```json
{"revision": "REQUEST_REVISION", "order": ["project-a/task-1", "project-b/task-2"]}
```

응답 revision, 전체 범위의 정확한 일치, 중복, 의존 순서와 호출 중 Task 변경을 검사한다. 유효하지 않거나 timeout인 요청, 호출 중 프로세스 중단은 DB에 남으며 같은 revision으로 자동 재호출하지 않는다. `status`의 `plans[].request`로 메인 LLM이 직접 계획을 검토하고 다음 명령으로 반환할 수 있다. 수동 반환도 같은 검사를 거친다.

```sh
uv run python -m scheduler --config .runtime/scheduler.json --state .runtime/scheduler apply-plan /absolute/response.json
```

선택적으로 `scheduler.claude_planner`가 설치된 Claude CLI의 구조화 출력을 변환한다. 빈 도구 목록, 빈 MCP 설정, 별도 임시 cwd와 session 비보존으로 계획만 요청한다. 사용자 정책의 `--dangerously-skip-permissions`를 포함하되 도구 목록은 비워 두며 기존 계정·기본 모델을 사용한다. 호출당 CLI 예산은 $1, 내부 timeout은 50초, scheduler 기본 timeout은 60초다. 다른 provider는 같은 JSON bridge로 바꿀 수 있다. timeout은 프로세스 그룹을 정리하며 계획 호출을 자동 반복하지 않는다.

## Adapter 선택과 지원 경계

- `local`: detached Python worker가 명령을 실행하고 durable receipt로 종료를 보고한다.
- `orca`: 설치된 public CLI의 `terminal create --worktree path:... --command ... --json`으로 같은 worker를 실행한다. 초기 prompt는 명령의 stdin으로 전달하므로 TUI readiness 탐지/terminal send에 의존하지 않는다. repo가 Orca에 연결돼 있고 같은 호스트에서 state와 Python 경로에 접근할 수 있어야 한다.
- `auto`: **attempt 생성 전** Orca status가 reachable인지 확인해 Orca 또는 local을 고른다. 선택값을 attempt에 저장한다. 선택 후 오류는 다른 경로로 재실행하지 않는다. 명시적 `orca`는 접근 불가여도 local로 바꾸지 않는다.

### 수용 후 terminal 정리

수용(`accepted`)과 terminal 정리는 별개 기록이다. `status`의 `cleanups[]`(attempt별 `state`·`tries`·근거)와 `events[]`의 `cleanup` 이벤트로 확인한다. tick은 attempt가 `accepted`이고 종료 영수증 `exited.json`이 있을 때만 정리한다. 실행 중이거나 수용 전인 attempt의 terminal은 닫지 않는다. 슬롯이 비었거나 재시작한 뒤에도 같은 원장의 tick이 이어서 처리한다.

Orca launch는 create 응답의 `_meta.runtimeId`와 `handle`·`ptyId`·`incarnationId`·`worktreeId`를 attempt 폴더 `terminal.json`(version 1)에 저장한다. 정리 직전 `terminal show`로 다섯 값을 다시 읽어 정확히 일치할 때만 그 handle 하나를 `terminal close --terminal`로 닫는다. title·preview·`lastOutputAt`·`connected` 같은 변동 값은 비교하지 않는다. `--all`이나 worktree 단위 close는 쓰지 않는다.

| 상태 | 의미 | 재시도 |
| --- | --- | --- |
| `closing` | 외부 호출 전 확정한 intent. 중단되면 다음 tick이 소유권부터 다시 확인 | 예 |
| `closed` | 소유 확인 후 close 응답 `result.close`의 handle이 같고 `ptyKilled: true`이며 `ptyStopVerdict`가 없음. 바깥 `ok: true`만으로는 성공이 아님 | 없음 |
| `already_closed` | 같은 identity의 terminal에 `exitCause`가 있음. close를 다시 보내지 않음 | 없음 |
| `not_applicable` | local adapter. 영수증이 종료를 증명하며 PID 재사용 위험 때문에 신호를 보내지 않음 | 없음 |
| `unconfirmed` | show/close 무응답·timeout·비JSON·`ok: false`, 또는 PTY 종료 미확인 close. 성공으로 보지 않음 | 다음 tick에 show부터 다시, 최대 3회 |
| `failed` | 3회 모두 확인 실패 | 운영자 확인 |
| `withheld` | identity 기록 없음(이전 attempt)·불완전·손상, handle stale, runtime/PTY/incarnation 불일치. 아무것도 닫지 않음 | 운영자 확인 |

`withheld`·`failed` terminal은 운영자가 `status` 근거와 실제 terminal을 확인한 뒤 해당 handle만 수동으로 닫는다. stale handle은 Orca 재시작 후 재발급됐을 수도 있으므로 종료 증거로 쓰지 않는다. 수용 실패·실패 attempt의 terminal은 자동 정리 대상이 아니다. 이전 supervisor Dispatch나 terminal handle을 재사용하는 기능은 없다.

## 검증

```sh
uv run python -m unittest discover -s tests -v
```

회귀 시험은 실제 로컬 subprocess·CLI 지속 loop·두 scheduler 프로세스 경쟁, mock Orca 응답과 planner 실패/지연을 조합한다. 요구별 범위와 원시 증거 위치는 [검증 기록](project-scheduler-validation.md)을 참조한다. 시험 통과를 장기 무인 운영 안정성이나 실제 제품 작업의 완료율로 확대하지 않는다.
