# 대상별 메시지와 처리 ACK

기존 SQLite 원장에 실행별 inbox를 추가한다. 발신 저장 확인, claim(전달·처리권), 적용 결과/ACK, worker 완료 제출, Task 수용은 서로 다른 증거다. 외부 broker, 별도 로그 재생, DB 재구성이나 daemon은 포함하지 않는다. 기본 실행·복구 계약은 [compact scheduler](project-scheduler.md)를 따른다.

## 경계와 대상

첫 버전은 같은 호스트·같은 OS 사용자의 신뢰 경계다. `(project/task, attempt UUID, recipient)`가 일치해야 처리할 수 있지만 OS 권한 격리나 원격 인증 기능은 아니다. coordinator는 send/dismiss를, 지정 worker는 inbox/claim/processed/ack/complete를 사용한다. worker 시작 지시가 send/dismiss를 금지하고 SCHEDULER_ATTEMPT가 있는 호출은 거부한다. 감사 기록에 coordinator 역할을 남긴다. 환경을 지울 수 있는 동일 사용자의 인증 장치는 아니다. 같은 OS 사용자가 다른 수신자 문자열을 사칭하는 것을 막는 보안 장치로 해석하지 않는다.

수신자는 새 attempt마다 생성되는 `worker:<attempt UUID>`다. 하나의 attempt에 하나의 논리 worker inbox가 있다. agent의 실제 session ID와 이 실행 ID는 다르며 기존 중앙 work bind에는 실제 session ID를 사용한다. 메시지는 현재 실행에만 발신·claim할 수 있고 이전 attempt의 항목을 새 worker로 옮기지 않는다. 이전 inbox/status는 감사 조회에 남긴다. 새 실행에 필요한 지시는 owner가 현재 revision을 확인해 새로운 메시지 ID로 명시적으로 보낸다.

새 attempt의 첫 필수 메시지는 [배정 인수](scheduler-assignment.md#인수-ack와-상태-구분) `assignment:<attempt>`다. payload에 `expect` object가 있으면 applied report가 그 필드를 그대로 포함해야 한다. 새 attempt는 공통 시작 지시와 다음 환경을 받는다. Task마다 설정이나 SQL을 작성하지 않는다.

- `SCHEDULER_TASK`, `SCHEDULER_ATTEMPT`, `SCHEDULER_RECIPIENT`
- `SCHEDULER_TASK_PATH`, `SCHEDULER_STATE`, `SCHEDULER_CONFIG`, `SCHEDULER_RESULT_DIR`
- `SCHEDULER_CLI_JSON`: 설치된 Python의 절대 경로부터 시작하는 CLI argv 배열. 시스템 Python이나 Orca의 PATH에 모듈 설치를 가정하지 않는다.

공통 시작 지시에는 실제 state/config 경로를 포함한 완전한 CLI가 있다. 아래 예시의 `CLI`는 설명용 자리표시자다. 실제로는 시작 지시의 명령을 사용하거나 `SCHEDULER_CLI_JSON`을 JSON으로 해석해 argv로 실행한다. shell eval로 실행하지 않는다.

```text
/absolute/orchestration/.venv/bin/python -m scheduler --config /absolute/config.json --state /absolute/state message
```

worker에서는 task/attempt/recipient가 환경에서 채워진다. coordinator는 send에 `--task PROJECT/ID --attempt UUID --recipient worker:UUID`를 지정한다. Claude/Codex/Qwen/Kiro 모두 같은 지시와 CLI를 받으며 공통 launcher의 permission/model 정책과 effort 기본값을 유지한다.

이는 **pull 방식**이다. worker는 시작, 자연스러운 작업 경계, 완료 제출 직전에 inbox를 확인해야 한다. 실행 중 agent의 주의 전환이나 도구 호출을 강제로 유발하지 않는다. CLI를 호출하지 않는 worker의 즉각 지시 반영은 보장하지 않지만, 필수 메시지가 남으면 scheduler의 최종 수용 gate가 막는다. Kiro 최초 신뢰 동의·로그인과 각 CLI 최초 인증이 headless 실행을 막는지는 별도 환경 문제다. 이를 `--trust-all-tools` 등으로 해결했다고 주장하지 않는다. 중앙 harness의 agent별 bind 지원 범위는 [scheduler 문서](project-scheduler.md#시작)를 따른다(Qwen 미지원, Kiro는 설치된 harness 버전에 의존).

## 최소 메시지 계약과 revision

| 값 | 의미 |
| --- | --- |
| `id` | 발신자가 정한 안정 ID. 재전송·재전달에서 유지하며 다른 내용으로 재사용 불가 |
| `project/task`, `attempt`, `recipient` | 대상 작업과 정확한 실행 identity. project는 task key로부터 결정 |
| `revision` | owner가 확정한 업무 지시의 semantic digest. 아래 필드가 같으면 worker 진행 기록과 무관하게 유지 |
| `kind` | `instruction`, `question`, `result`. 이름만으로 적용 ACK나 작업 완료가 되지 않음 |
| `payload` | 비어 있지 않은 JSON object. `text`와 `ref` 등으로 내용/근거를 전달. 참조를 자동 실행하거나 검증하지 않음 |
| `required` | 기본 true. 필수 적용 지시 여부; `--optional`이면 완료 gate에서 제외 |
| `seq` | DB가 부여하는 단조 증가 전달 순서. wall-clock timestamp를 FIFO 근거로 쓰지 않음 |

`revision`은 Task key/project/title/priority/depends_on, `## Goal`, `## Scope`, `## Acceptance Criteria`와 blocked/cancelled 상태의 digest다. `Current Result`, `Next Action`, evidence, ready/active/review/done 진행 전환은 제외한다. 전체 파일 SHA는 기존 실행 증거로 별도 유지된다. 새 지시의 정본은 지정 Task owner가 이 지시 필드에 기록하거나 같은 base revision의 새 메시지 payload로 보낸다. 다른 임의 제목 아래에 중요한 요구를 숨겨 놓고 revision에 반영됐다고 가정하지 않는다.

send 전 owner는 Task 변경을 확정하고 inbox의 현재 revision을 확인한다. message revision은 Task owner가 확정한 내용을 가리키며 scheduler는 Task를 수정하지 않는다. Task 파일과 SQLite의 쓰기는 원자적이지 않다. CLI는 처리 전후 revision을 검사하고 acceptance 직전에도 재확인하지만 파일시스템 편집과 DB commit을 하나의 트랜잭션으로 만드는 보장은 없다. 공동 작성자는 권한·소유권을 지켜야 하며 충돌 시 실제 Task/산출물과 원장을 대조한다.

## send → claim → processed → ACK

```sh
CLI send --task PROJECT/ID --attempt UUID --recipient worker:UUID \
  --id MESSAGE_ID --revision REV --kind instruction --payload-file /absolute/instruction.json
CLI inbox
CLI claim --revision REV --lease 60
CLI processed --id MESSAGE_ID --revision REV --token CLAIM_TOKEN \
  --outcome applied --report-file /absolute/application-result.json
CLI ack --id MESSAGE_ID --revision REV --token CLAIM_TOKEN
```

1. **send:** envelope를 commit한 뒤에만 `accepted: true`를 반환한다. 같은 ID·같은 내용은 기존 receipt를 반환하고 같은 ID·다른 대상/내용/revision은 거부한다. terminal 입력 accepted와 동일한 이름이어도 여기서는 DB 저장만 증명한다.
2. **inbox/claim:** inbox는 조회다. claim만 SQLite `BEGIN IMMEDIATE` 안에서 처리권을 부여하며 token·만료 시각·deliveries를 반환한다. tick 파일 lock을 사용하지 않아 긴 planner 호출과 충돌하지 않는다. 대상 Task 하나만 읽으므로 다른 프로젝트의 잘못된 Task가 inbox를 막지 않는다.
3. **processed:** worker가 실제 적용·비교를 수행하고 `applied`, `deferred`, `conflict` 중 결과와 비어 있지 않은 JSON report를 저장한다. report에는 무엇을 적용/보류했는지와 실제 증거 또는 참조를 적는다. DB 저장은 외부 효과를 대신 수행하지 않는다.
4. **ack:** 같은 대상/revision의 유효 claim token과 영속 처리 결과가 있어야 ACK를 기록한다. `applied`는 `acked`, 보류/충돌은 사유가 있는 `held`가 된다. 결과 없는 ACK, 만료되거나 교체된 token의 ACK는 거부한다. ACK 응답이 유실되면 같은 token으로 재요청해 저장된 결과를 받는다. 적용 ACK도 작업 전체의 완료는 아니다.

처리 결과가 저장된 후 ACK 전에 중단되면 재claim 응답에 기존 `processing_result`가 포함된다. worker는 효과를 반복하지 않고 이를 재사용해 새 token으로 ACK한다. 이전 token은 새 claim을 덮어쓰지 못한다. 결과 자체도 같은 메시지 ID에서 다른 내용으로 다시 쓸 수 없다.

외부 효과를 만들고 결과를 DB에 기록하기 전에 중단된 경우에는 DB만으로 성공 여부를 알 수 없다. 재전달의 `needs_reconciliation: true`이면 실제 파일·Task·외부 시스템과 대조한 뒤 `processed --reconciliation '비교 결과와 근거'`를 사용한다. 비어 있지 않은 대조 기록은 필수지만 그 내용의 진실을 자동 인증하지 않는다. 임의 외부 효과의 exactly-once를 주장하지 않는다. 효과 발생 후 processed의 사후 revision 검사에서 실패하면 DB 기록은 rollback되어 실제 효과와 다를 수 있으므로 동일한 대조 절차가 필요하다.

## 순서·만료·보류

같은 attempt의 가장 작은 미해결 seq만 claim한다. 선두가 아직 임대 중이면 busy, held이면 held를 반환한다. 따라서 뒤 메시지가 먼저 적용되지 않는다. 오래된 revision은 held로 전환하며 현재 revision 메시지로 자동 변환하거나 다른 attempt로 전달하지 않는다.

lease 만료는 **메시지 처리권만** 다시 부여한다. 같은 메시지 ID와 새 token을 쓰며 worker 프로세스를 만들거나 Task를 재실행하지 않는다. `deliveries`는 효과의 실행 횟수가 아니라 ACK 복구를 포함한 claim 횟수다. 저장된 결과의 ACK 복구 claim 횟수에는 별도 상한이 없다. 처리 결과가 없는 메시지는 기본 최대 전달 횟수 3회 이후 사유와 함께 held다. 이미 영속 처리 결과가 있으면 이 한도를 넘어 새 token을 받아 결과 재적용 없이 ACK를 복구할 수 있다. stale revision과 명시적 held는 여전히 자동 해제하지 않는다. ACK가 없거나 claim이 만료됐다는 이유로 실행 슬롯을 해제하지 않는다. timestamp는 lease 경과 판단에 쓰지만 늦은 ACK 방어는 token 일치도 함께 검사한다. OS clock 변경에 따른 지연 가능성은 남는다.

coordinator가 실제 효과와 새 지시를 대조한 뒤 이전 지시를 철회/대체할 필요가 있으면 다음 명령을 사용한다.

```sh
CLI dismiss --id MESSAGE_ID --reason '실제 효과 확인 결과와 철회/대체 메시지 ID'
```

살아 있는 claim은 먼저 worker와 조율해야 하므로 dismiss를 거부한다. 이미 적용된 ACK도 dismiss하지 않는다. dismissed는 명시적 owner 결정이며 적용 성공으로 표시하지 않는다. 필요하면 현재 revision을 가진 새 ID의 지시를 보낸다. held 항목의 재시도 횟수를 자동 초기화하지 않는다.

## 완료 제출과 최종 수용

worker는 최종 Task 결과를 갱신한 후 inbox를 다시 읽고 최신 revision·inbox_seq로 제출한다.

```sh
CLI complete --id UNIQUE_COMPLETION_ID --revision REV --inbox-seq N \
  --report-file /absolute/completion-result.json
```

complete는 현재 실행과 revision, 조회한 inbox_seq, 미적용 필수 메시지의 부재를 한 DB 트랜잭션에서 확인한다. 같은 ID/내용의 재제출은 멱등적이며 다른 내용은 거부한다. 응답은 `submitted: true`, `accepted: false`다. 그 뒤 새 메시지가 도착하거나 지시 revision이 바뀌면 기존 완료 제출은 수용에 사용할 수 없다. 아직 실행 중인 worker가 새 inbox 처리·비교 후 새 completion ID로 제출해야 한다.

scheduler는 다음 조건을 모두 확인해야 attempt를 accepted로 바꾼다.

- 실제 종료 code 0 영수증.
- 중앙 Task의 done + evidence 선언.
- 현재 지시 revision 및 최신 inbox_seq와 일치하는 worker 완료 제출.
- 모든 필수 메시지가 applied ACK 또는 사유 있는 coordinator dismissal로 해결됨.

종료 영수증이 있거나 awaiting_acceptance 상태면 새 send/claim/processed/complete를 거부한다. 기존 send/ACK/complete의 동일 receipt 재조회는 허용한다. 종료 전에 완료를 제출해야 하며, 종료 뒤 누락된 완료나 변경된 revision을 dead worker 대신 제출하지 않는다. coordinator는 실제 종료·산출물을 확인한 뒤 기존 resolve --stopped --outcome failed/retry와 근거로 명시적으로 복구한다. dismiss만으로 오래된 completion snapshot을 유효하게 만들지 않는다.

tick/status의 acceptance_blocker는 no_completion, completion_revision_stale, inbox_changed, blocked_messages, task_missing, task_invalid, task_not_accepted 등 대기 원인을 표시한다. inbox CLI는 실행 파일 탐색을 요구하지 않으며 실행 파일은 실제 launch 준비 때 해석한다. SQLite 오류도 CLI JSON error와 exit 2로 반환한다.

이 gate와 send는 같은 SQLite 쓰기 트랜잭션 경계를 사용한다. acceptance가 먼저 commit되면 해당 이전 실행으로의 신규 send를 거부한다. send가 먼저 commit되면 완료 snapshot이 오래돼 수용을 막는다. 마지막 poll 이후 실제 종료까지의 좁은 경쟁 구간은 남으며, 이때도 추정 성공 대신 명시적 복구가 필요하다. optional 메시지도 새로운 유입 사실은 inbox_seq를 바꾸므로 완료 전에 다시 조회해야 하지만 적용 ACK 자체는 필수가 아니다.

## 호환성과 검증 한계

새 테이블을 추가하므로 기존 attempts/events 열은 바꾸지 않는다. 메시지 기본값은 새 config 키를 요구하지 않는다. 새 설정에서만 `message_max_deliveries`를 지정할 수 있으며 기존 config hash pinning은 그대로 유지한다. 기존 실행을 재시작하거나 설정을 임의 변경해 protocol을 붙이지 않는다.

업그레이드 전에 이미 시작한 attempt는 worker_context가 없어 기존 수용 방식으로 끝난다. 새 attempt부터 protocol 1과 완료 제출 gate가 적용된다. 기존 attempt는 새 메시지 기능의 수신 대상이 아니며, legacy 완료를 메시지 ACK 검증으로 해석하지 않는다. 비-LLM custom command도 새 attempt에서는 공통 완료 제출을 구현해야 한다.

[검증 보고서](project-scheduler-validation.md)는 fixture·실제 agent CLI ACK·기존 독립 QA의 경계를 구분한다. 저장된 결과는 agent의 명시적 보고와 원장 확인의 증거이지 모든 외부 효과의 자동 인증이 아니다. 별도 로그 재생, SQLite 복구/재구성, 외부 broker와 다중 호스트는 백로그다.
