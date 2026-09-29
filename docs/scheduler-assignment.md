# Task 배정과 실행 지시 생성

scheduler는 중앙 Task를 그대로 정본으로 두고, 그 Task를 누가 어떤 역할·범위로 실행하는지만 **배정(assignment)**으로 저장한다. 배정은 명시 배정이든 계획이 고른 기본 배정이든 같은 경로를 거친다: 검증 → 영속 저장 → 입력 렌더링·보존 → adapter launch → inbox 인수 ACK. 실행·메시지 계약은 [compact scheduler](project-scheduler.md)와 [메시지함](scheduler-messaging.md)을 따른다.

## 배정 계약

| 값 | 의미 |
| --- | --- |
| `id` | 명시 배정은 coordinator가 정한 안정 ID. 같은 ID·같은 내용은 멱등, 다른 내용은 거부 |
| `task`, `task_path`, `project` | 대상 Task key/경로. 다른 프로젝트 Task는 key가 달라 대상이 될 수 없다 |
| `revision` | 저장 당시 Task의 semantic instruction revision. Current Result·Next Action·evidence 편집은 바꾸지 않는다 |
| `role` | `implement`(write scope 필수) 또는 `review`(product write scope 없음, 산출물은 outputs에만) |
| `scope`, `outputs` | repo 기준 상대 경로. `.`은 repo 전체. 절대 경로·`..`는 거부 |
| `executor` | 선택. `claude/codex/qwen/kiro` preset 중 하나. 없으면 공통 설정. 프로젝트에 명시 `command`가 있으면 override 불가 |

Task 본문은 복제하지 않는다. Task frontmatter의 선택 필드 `write_scope`(경로 목록)가 있으면 모든 scope/outputs가 그 안에 있어야 하며 넓히는 배정은 거부한다. `write_scope`는 instruction revision에 포함된다. 없으면 Task의 서술 범위가 권한이며 기본 배정 scope는 `.`이다. 허용 범위는 협업 계약이고 OS 권한 격리가 아니다.

executor/model은 기존 launcher 정책을 그대로 쓴다(Claude bypass, Codex bypass, Qwen yolo, Kiro `claude-opus-5.5` + trusted tools, effort 생략). 공통 `model`은 설정된 executor에만 적용되고 override executor는 도구 기본값을 쓴다. Kiro는 항상 `claude-opus-5.5`로 고정된다.

## 명시 배정과 기본 배정

```sh
CLI="uv run python -m scheduler --config .runtime/scheduler.json --state .runtime/scheduler"
$CLI assign --id review-1 --task PROJECT/TASK_ID --role review --output reports/review.md
$CLI assign --id impl-1 --task PROJECT/TASK_ID --role implement --scope scheduler --scope tests
$CLI tick            # 조건을 만족하면 같은 launch 경로로 실행
$CLI assignments     # stored / delivered / taken_over / completed 확인
```

`assign`은 coordinator 명령이며 worker 환경(`SCHEDULER_ATTEMPT`)에서는 거부한다. tick 파일 lock을 쓰므로 긴 planner 호출 중에는 busy일 수 있다. 저장만 하며 실행은 다음 tick이 한다. 한 Task에는 열린 명시 배정이 하나만 있다.

tick은 먼저 저장 순서대로 명시 배정을 본다. Task가 ready이고 선행 Task가 수용됐으며 이전 attempt가 없거나 retry일 때 launch한다. 저장 후 instruction revision이 바뀌었으면 다시 렌더링하지 않고 `held`로 둔다. held 배정도 Task를 계속 예약하므로 더 넓은 기본 배정으로 대체되지 않는다. coordinator가 현재 Task를 확인해 새 ID로 다시 배정한다. 그 외 Task는 기존 계획 순서로 고르고 기본 배정(`implement`, scope는 Task `write_scope` 또는 `.`)을 결정적 ID `auto:<digest>`로 만든다.

## 결정적 입력과 보존

launch 직전 Task 원문을 다시 읽어 catalog hash와 대조한다. 실행 입력은 다음을 같은 순서로 렌더링한다: Task key/경로, attempt·배정·역할, launch 시점 Task sha256와 instruction revision, scope/outputs/executor 정책, 역할별 지침, 인수 규칙, Task의 Goal·Scope·Acceptance Criteria·Next Action 발췌, 공통 inbox/claim/processed/ack/complete 규약. 같은 입력은 같은 텍스트를 만든다. 발췌는 편집 정본이 아니며 worker는 현재 Task 전문을 읽는다.

`state/attempts/<attempt>/`에는 `task-input.md`(launch 시점 Task 원문), `assignment.json`, `spec.json`(prompt·command·`task_sha256`·`prompt_sha256`)이 남는다. prompt는 기존 worker stdin → launcher argv 경로로 전달되며 shell 문자열을 만들지 않는다. Orca adapter도 같은 spec을 실행하므로 terminal에 장문을 입력할 필요가 없다.

## 인수 ACK와 상태 구분

launch 트랜잭션은 attempt·worker context·배정 launch 기록과 함께 필수 메시지 `assignment:<attempt>`를 저장한다. payload의 `expect`는 `{assignment, role, task_revision}`이다. worker는 이 메시지를 claim하고 Task를 읽은 뒤 `expect` 필드를 그대로 포함한 report로 `processed --outcome applied`를 기록하고 ACK한다. 필드가 다르거나 빠지면 applied를 거부한다. 이 필수 메시지가 해결되기 전에는 `complete`와 최종 수용이 막힌다.

| 상태 | 근거 |
| --- | --- |
| stored | `assignments` 행 저장 |
| launched | attempt 행과 launch intent. adapter 응답이 불명이면 `unknown`으로 유지하고 재launch하지 않음 |
| delivered | 인수 메시지 claim(deliveries > 0). 전달은 인수가 아님 |
| taken_over | worker가 `expect`를 담은 applied 결과를 기록하고 ACK |
| completed | 기존 수용 gate(exit 0, Task done+evidence, 완료 제출, 필수 메시지 해결)로 attempt accepted |

terminal 입력 accepted나 exit code는 어느 단계도 만들지 않는다. launch 응답 불명과 재시작에서는 기존 attempt·메시지 ID가 유지된다. `resolve --outcome retry` 후에는 같은 배정 ID로 새 attempt와 새 `assignment:<attempt>` 메시지가 만들어지고 이전 attempt 메시지는 새 worker에 전달되지 않는다. 실패한 명시 배정은 `failed`가 되며 다시 배정해야 한다.

## 실행 중 Task 변경

owner가 Task의 지시 필드를 확정한 뒤 다음을 실행한다.

```sh
$CLI notify --attempt ATTEMPT_UUID
```

같은 렌더링으로 `update-<revision>.md`를 attempt 폴더에 남기고 새 revision의 필수 메시지 `assignment:<attempt>:<revision>`을 같은 메시지함으로 보낸다. revision이 같으면 거부하고, 같은 revision의 재실행은 기존 receipt를 반환한다. 아직 적용되지 않은 이전 배정 메시지는 `superseded by …` 사유로 dismiss되어 나중에 적용되지 않는다. claim 중인 메시지는 dismiss하지 않으므로 worker와 조율한다. worker 종료 후에는 기존 규칙대로 거부되며 resolve로 복구한다.

보내기 전에 실행 중 배정의 write scope와 outputs를 현재 Task `write_scope`로 다시 검사한다. Task 범위가 줄어 기존 배정이 더 넓으면 `scope conflict` 진단(CLI exit 2)으로 거부하고 update 파일·메시지를 만들지 않는다. 이전 범위를 새 revision으로 다시 인증하거나 범위를 자동으로 줄이거나 넓히지 않으며 새 worker도 실행하지 않는다. coordinator가 Task 범위를 되돌리거나, worker를 멈추고 `resolve`한 뒤 현재 범위 안에서 명시적으로 다시 `assign`한다. 기존 배정을 계속 포함하는 변경(범위 확대, 배정 경로를 유지한 축소)은 기존 배정 범위 그대로 전달한다.

## 한계

같은 호스트·같은 OS 사용자의 협업 계약이다. worker가 scope 밖을 쓰는 것을 막는 실행 격리는 없다. 인수 report는 worker의 명시적 보고이지 Task 이해의 자동 증명이 아니다. [검증 범위](project-scheduler-validation.md#task-assignment-and-take-over)는 fixture와 한 번의 실제 Kiro 읽기 전용 실행을 구분한다.
