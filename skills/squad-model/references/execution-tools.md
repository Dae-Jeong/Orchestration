# 현재 도구 연결: Paperclip + Orca

이 문서는 [PM 업무 계약](pm-flow.md)을 현재 도구에 연결한다. 도구를 교체할 때 바꿀 수
있는 지침이며 범용 adapter API를 구현하지 않는다. Paperclip 버전별 매핑은
[model.md](model.md)의 Paperclip mapping을 따른다.

Orca 실행 전 orca-cli skill로 선택한 바이너리의 `skills get orchestration`을 읽는다.
모델/재사용은 coordinator-loop, 배치는 placement-and-remote, 중단/재개는 recovery
reference를 읽는다. 이 문서의 요약이 live preamble이나 버전별 권한 규약을 대신하지 않는다.

## 실행 연결

사용자 합의: 프레임워크와 기존 권한 안의 역할 배정·착수·검증·수정·후속 진행을 PM에게
위임한다. PM agent가 실제 지시 주체다. 별도 PM 상시 프로세스가 존재한다는 뜻은 아니다.

| 소유자 | 소유하는 판단·상태 |
| --- | --- |
| 사용자 | 제품 방향·원하는 결과·권한 경계, 위임 밖의 결정 |
| PM agent | 프레임워크 적용, 역할 배분, 두 도구 호출, 진행·증거 검토·상향 판단 |
| Paperclip | 프로젝트의 인계/검증 가능한 업무 단위, 담당·기준·우선순위·업무 간 blocker·review·증거 |
| Orca orchestration | 해당 업무의 실행 Task와 권위 있는 Dispatch 시도, worker 배치·질문·결과·실행 생명주기 |
| 직무 worker | 실제 프로젝트 workspace의 상세 실행·산출물·검증 증거 |

1. **요청 수신:** PM이 제품 목표·원문·프로젝트 규칙·현재 작업을 읽는다.
2. **업무 구성:** PM이 기획·QA 관점으로 수용 조건을 구체화하고 Paperclip에 인계 가능한
   단위로 기록한다. 구현 순서·디버깅 단계는 담당자의 프로젝트 task 문서가 관리한다.
3. **배정·준비:** PM이 역할/실행자/도구·한도를 선택하고 선행 검증·공유 자원을 확인한다.
   새 승인 없이 처리 가능한 위임 범위는 바로 진행한다.
4. **실제 지시:** PM이 버전별 Orca orchestration skill을 읽고 정확한 제품 workspace에
   worker를 배치한다. 지시에는 대상·변경·제약·쓰기 소유권·관찰 가능한 완료 조건과
   계약 revision/hash·입력/증거 위치를 전달한다. 다른 repo 작업을 현재 폴더로 옮기지 않는다.
5. **질문·진행:** worker는 Orca의 실행 계약으로 질문/결과를 PM에게 전달한다.
   PM은 범위 내 질문을 해결하고 필요한 상태·막힘을 Paperclip에 반영한다.
6. **검증·수정:** Orca의 성공 보고는 실행 시도의 결과다. QA가 해당 계약 증거를 검증한다.
   PM은 fail이면 담당 역할에 새 수정 시도를 배정하고, unknown이면 확인 작업/대기로 남긴다.
7. **완료·후속:** 필수 기준과 review가 통과하면 PM이 Paperclip 업무를 완료 처리하고
   후속 작업의 의존성·자원 상태를 다시 확인한다. Orca worker의 회수·재사용은 그 skill의
   settlement 규약을 따른다. 제품 성과 관찰은 delivery 완료와 별도로 남긴다.

### 연결 계약과 중복 실행 방지

한 Paperclip issue에 여러 Orca 실행 Task가 연결될 수 있고, 각 Task에는 여러 순차 시도가
있을 수 있다. 로컬 연결 기록은 `project_id`, `issue_id`, `stable_task_id`, `revision`,
`criteria_hash`, `orca_run_id`, `orca_task_id`, `dispatch_id`, `workspace`, `evidence_ref`를
구분한다. 복사한 Dispatch ID로 실행 권한을 재구성하지 않고 실제 live preamble/receipt를 따른다.

Paperclip의 업무 의존성과 Orca의 내부 실행 의존성을 양방향으로 자동 복제하지 않는다.
PM은 준비된 업무의 실행만 Orca에 위임한다. 동일 시도를 Paperclip adapter와 Orca worker로
중복 시작하지 않는다. 이 결합안에서는 직무 실행을 Orca가 소유한다.
모델 선택은 Orca의 현재 launch 규약을 따르며 요청값이 아니라 effective receipt로 확인한다.
아직 후보인 모델 배정표만으로 명시적 launch override를 실행하지 않는다.

### 사람 판단·중단·재개

PM은 합의된 기준이나 제품 방향의 변경, 추가 권한/비용 범위, 한도 소진처럼 위임 범위를
벗어나는 결정을 사용자에게 돌린다. 단순 역할 배정·수정마다 재승인을 요구하지 않는다.
연락 두절/timeout은 완료나 종료가 아니다. 활성 시도가 불명확하면 재시작하지 않고 Orca
증거와 Paperclip 기록·실제 외부 효과를 대조한다. PM 세션 교체 시 이 연결 기록과 미처리
질문·남은 한도를 인계한다. 기존 실행의 권한·인계는 Orca recovery/legacy guide로 확인한다.

이 절은 **합의한 운영 설계**다. 두 제품 간 자동 adapter/동기화, 상시 PM, 실제 통합 시범은
아직 구현·검증하지 않았다. 다음 검증은 한 업무의 배정→결과→검증→상태 반영→재개다.

업무판을 바꿀 때는 현재 계약·결정·의존성·증거를 portable 인계본으로 보존하고 새 업무판이
정본이 되는 시점을 기록한다. 양쪽을 동시에 편집 정본으로 두지 않는다.
다른 실행 수단으로 이전할 때는 기존 실행의 종료 또는 공식 소유권 이전을 확인한다.
portable 문서가 있다고 앱 세션·인증·디자인 파일 형식까지 자동 이식되는 것은 아니다.
