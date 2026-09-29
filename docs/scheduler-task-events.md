# Task 항목 참조 이벤트

worker와 메인(coordinator)이 질문·답변·완료·막힘을 **Task의 Markdown 항목 참조**로 주고받는다. 본문의 정본은 Task 파일이고 SQLite에는 참조 envelope와 전달·처리 상태만 둔다. 기존 [scheduler 메시지함](scheduler-messaging.md)은 coordinator→attempt 단방향 지시용으로 그대로 두며, 이 기능은 scheduler attempt가 아닌 일반 TUI Kiro·Orca native dispatch·메인도 쓸 수 있는 별도의 양방향 표면이다. broker·daemon·push는 없다.

## 항목 형식과 hash

```markdown
<!-- item:q-output-token -->
질문 또는 답변 본문
<!-- /item:q-output-token -->
```

- 여는/닫는 marker는 각각 한 줄을 차지한다. ID는 `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`이다.
- **hash = 두 marker 줄 사이 원문의 정확한 UTF-8 byte에 대한 SHA-256**이다. 줄바꿈·공백 정규화는 없고, 여는 marker 줄의 개행 뒤부터 닫는 marker 줄 직전까지다. 항목 밖의 수정은 hash를 바꾸지 않는다.
- 파일 전체에서 중복 ID, 중첩, 닫히지 않은 항목, 짝이 맞지 않는 닫힘, `<!-- item:`처럼 보이지만 형식이 틀린 marker는 모두 거부한다. 빈 본문도 거부한다.
- Task 경로는 설정된 프로젝트 `tasks` 디렉터리의 **직접 자식** `.md`여야 한다. symlink 파일과 resolve 후 밖으로 나가는 경로는 거부한다. frontmatter의 id/project가 `--task PROJECT/ID`와 일치해야 한다.

**작성 전략(동시 편집 방지):** 기본은 **기존 Task를 정본으로** 쓰고 질문마다 별도 Task를 만들지 않는다. 항목은 append 전용이다. 각 참여자는 자기 새 항목만 추가하고 다른 참여자의 항목을 수정하지 않으며, 답변은 질문 항목을 고치지 않고 새 항목으로 추가한다. 쓰기 순서는 명시적 차례로 정한다: 질문을 올린 worker는 `question.opened` 뒤 답을 기다리는 동안 그 Task를 쓰지 않고, 메인은 그 사이에만 snapshot(harness 사용 시)·재읽기 후 답변 항목을 append한 다음 publish한다. 이 차례 넘김이 동시 작성을 막는 장치이며, 별도 교환 Task를 쓰는 것만으로는 다중 작성자를 막지 못한다. scheduler는 Task를 편집하지 않고 파일 lock도 제공하지 않는다. `publish --sha256`은 작성자가 검토한 hash와 현재 파일이 같을 때만 저장하는 CAS다. 질문을 바꿔야 하면 항목을 수정한 뒤 새 event ID로 `question.opened`를 다시 올린다.

해결된 항목을 Log로 옮기는 것은 그 항목을 참조하는 이벤트가 모두 acked/dismissed된 뒤에만 한다. 미처리 이벤트가 있는 동안 항목이 사라지면 해당 이벤트는 `item not found`로 held된다.

## envelope

| 필드 | 의미 |
| --- | --- |
| `id` | 발신자가 정한 안정 event ID. 같은 내용 재발신은 기존 receipt, 다른 내용 재사용은 거부 |
| `kind` | `question.opened`, `question.answered`, `work.completed`, `work.blocked` |
| `task`, `task_path`, `item`, `item_sha256` | 참조 대상. event ID와 item ID/hash는 별개 |
| `sender`/`sender_exec`, `recipient`/`recipient_exec` | 참여자 주소와 실행 식별자. `recipient_exec`가 없으면 그 참여자의 어느 실행이든 수신 |
| `reply_to`, `reply_sha256` | 답변이 가리키는 질문 event와 **답변 시점 질문 항목 hash**(질문 revision) |

본문은 SQLite에 저장하지 않는다. 처리 보고(report)만 저장한다.

**신원:** 참여자·실행 문자열은 같은 호스트·같은 OS 사용자 안의 **자기 선언**이며 인증이 아니다. native dispatch의 권한은 문자열만으로 증명되지 않는다. CLI는 선언된 수신자·실행과 이벤트가 정확히 일치하는지(claim/read/processed/ack), 답변자가 질문의 수신자이고 질문 발신 실행에게 보내는지, 같은 Task인지를 검사한다. 예외적으로 `scheduler:<attempt>` 실행은 원장의 live attempt이고 그 attempt의 Task와 같아야 하며, `SCHEDULER_ATTEMPT` 환경 안에서는 이 형식만 허용한다. 권장 주소: 메인 `orca:<terminal handle>` + `orca-run:<run id>`, worker `kiro:<terminal handle>` + `orca-dispatch:<dispatch id>`. 세션 ID를 지어내지 않는다.

## 명령

```sh
CLI="/absolute/orchestration/.venv/bin/python -m scheduler --config CONFIG --state STATE ref"
ME="--as PARTICIPANT --exec EXECUTION"   # 또는 SCHEDULER_REF_AS / SCHEDULER_REF_EXEC

$CLI item    --task P/ID --path TASK.md --item ITEM                 # 현재 hash와 본문(읽기 전용)
$CLI publish $ME --id EVT --kind question.opened --task P/ID --path TASK.md --item ITEM \
             --to RECIPIENT [--to-exec EXEC] [--sha256 HASH]
$CLI publish $ME --id EVT2 --kind question.answered ... --item ANSWER_ITEM --reply-to EVT --to ASKER
$CLI wait    $ME --timeout 600 [--interval 1] [--lease 60]          # claim 또는 timeout(exit 3)
$CLI read    $ME --id EVT --token TOKEN                             # hash 검증된 본문
$CLI processed $ME --id EVT --token TOKEN --outcome applied|deferred|conflict --report-file R.json [--reconciliation TEXT]
$CLI ack     $ME --id EVT --token TOKEN
$CLI inbox   $ME;  $CLI claim $ME;  $CLI show --id EVT;  $CLI dismiss $ME --id EVT --reason TEXT
```

## 단계와 상태

1. **publish(저장):** 대상 항목을 읽어 hash를 계산하고, 답변이면 질문 항목이 질문 event의 hash 그대로이고 그 항목의 최신 `question.opened`인지 확인한다. commit 직전에 같은 검사를 다시 하며 실패하면 rollback한다. `stored: true`는 저장만 뜻한다.
2. **claim/wait(수신):** 수신자·실행에 온 이벤트를 **발신 실행 stream별 FIFO**로 본다. 각 stream의 선두만 처리하고, held/busy인 stream은 건너뛰어 다른 stream을 준다. 따라서 한 worker의 held 질문이 독립 worker의 결과 수신을 막지 않는다. 처리 결과가 없는 선두는 claim 때 항목·질문 hash를 재검증해 다르면 `held`(stale_reference/stale_answer)로 두고 내용을 전달하지 않는다. `wait`은 claim 한 번마다 짧은 트랜잭션을 쓰고 **트랜잭션 밖에서** sleep한다. timeout은 exit 3, `state: timeout`이며 성공·실패·재실행 사유가 아니다.
3. **read(검증된 읽기):** 파일을 한 번 읽어 hash·질문 revision을 비교하고, 비교한 그 본문만 돌려준다. 다르면 held.
4. **processed:** 수신자가 실제 적용/보류/충돌 결과를 report로 기록한다. `applied`는 같은 claim token으로 read한 뒤에만 가능하며, 기록 직전 참조가 바뀌었으면 held로 두고 기록하지 않는다. 결과 없는 재전달은 `--reconciliation`이 필수이고, 기본 3회(`message_max_deliveries`) 이후 held.
5. **ack:** 유효 token과 저장된 결과가 있어야 한다. applied → `acked`, deferred/conflict → `held`(그 stream은 dismiss 전까지 멈춤). 같은 token 재ACK는 기존 receipt를 돌려준다. lease 만료 후 재claim하면 기존 `processing_result`가 함께 오며, 이때 read는 본문 없이 `historical` receipt만 준다. 내용이 바뀐 뒤에도 오래된 텍스트를 새로 적용하지 않는다.

ACK는 수신자가 처리를 기록했다는 뜻이지 질문 해결·Task done이 아니다. 해결 여부는 질문자가 답변을 적용한 결과로 Task에 기록하고, Task done은 기존대로 owner만 선언한다. `work.completed` ACK는 scheduler attempt의 종료 영수증·완료 제출·acceptance gate를 대신하거나 약화하지 않는다. `dismiss`는 발신 실행 또는 수신자가 사유와 함께 stale/held 이벤트를 치울 때 쓰며 live claim과 applied ACK에는 쓸 수 없다.

## 저장과 한계

SQLite에 `ref_events` 테이블 하나를 추가한다(envelope·상태·token·처리 결과·ACK token을 한 행에). 감사는 기존 `message_audit`에 `ref:<id>` / `ref.<action>`으로 남긴다. 기존 `messages`/`processing_results`는 attempt에 묶인 id 공간과 acceptance gate가 있어 섞지 않았다. 설정 hash pin은 기존 원장 규칙을 따른다.

Markdown 저장과 SQLite commit은 원자적이지 않다. commit 직전 재검사 뒤에도 파일이 바뀔 수 있으며, 그 경우 claim/read/processed의 재검사가 held로 막는다. 파일 저장 후 publish 실패는 같은 ID로 재발신하거나 명시적으로 재조정한다. 참여자 신원은 인증되지 않는다.

**활성 대기 한계:** 전달은 pull이다. 수신자가 활성 세션에서 `wait`/`claim`을 실행하고 있을 때만 사용자 재촉 없이 처리된다. 종료되거나 idle 상태인 세션을 깨우거나 다시 실행하지 않으며, 그 경우 이벤트는 저장된 채 다음 poll까지 남는다. 다른 채널(예: Orca native ask)로 상대의 주의를 끄는 것은 가능하지만 그 채널의 내용은 이 기능의 답·완료 근거가 아니다. Task 항목을 수정하기만 해서는 이벤트가 생기지 않으며 `publish`를 명시적으로 실행해야 한다. 승인 대기나 중단을 자동으로 감지·알리는 hook이 없고, 일반 scheduler attempt TUI와의 통합도 없다. 검증 범위: [검증 보고서](project-scheduler-validation.md#task-item-reference-events).
