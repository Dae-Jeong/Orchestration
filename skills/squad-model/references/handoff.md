# 작업 인계 기록 양식

기존 `tasks/<work>.md`에 필요한 항목만 채운다. 새 글로벌 정책/자동 실행 schema가 아니다.
아래 빈칸과 수치 없는 예시는 **proposed**이며 승인 사실이 아니다.
v1 JSON 외의 보충 기록은 task 문서에 두고 해당 contract의 acceptance/verification/
authority/resources/decision에 핵심 조건과 버전이 고정된 근거를 연결한다.
수용 조건·권한을 바꾸는 보충 문서는 contract revision/hash도 갱신한다.

## 계약 조율

- task_id / Paperclip issue 연결 / 역할·실제 담당자:
- PM 배정: executor / model·설정 / 배정 이유 / 필요한 skill·도구의 실제 준비 상태:
- Orca 실행 시: Run / Task / active Dispatch / 정확한 workspace / 실행 소유 도구:
- 원문 근거와 범위 / 관찰 / 해석·대안 / 가설·반증 질문:
- 성공·실패·무효·한계 / 요약 선택 기준:
- 문제·대상 / 성과 질문 / 범위·비범위:
- decision: proposed 또는 기존 합의 근거·결정자. 반복 승인을 요구하지 않는다.
- DACI: 결정 질문 / Driver / Approver / Contributors / Informed / 결정·이유:
- revision / criteria_hash / 이전 revision 영향 범위:
- authority: 허용 효과·환경 / 제외 / 재시도 횟수·시간·비용 한도 / 중단 조건:
- depends_on / 공유 자원 key·read/write / 대기 이유·해제 조건:

| 기준 ID | 관찰 가능한 완료 조건 | 검증법·환경 | 증거 위치/버전 | reviewer |
| --- | --- | --- | --- | --- |
| proposed | 소재에 맞춰 작성 | 재현 가능한 검사 | 실행 전에는 없음 | 실제 담당자 |

## 공통 DoD와 인계

이 모델의 공통 DoD는 합의된 revision/hash의 필수 기준이 증거로 통과하고,
허용 효과 안의 산출물을 다음 담당자가 열고 재현할 수 있으며, 한계와 다음 판단이
기록된 상태다. task-specific 조건과 위 표를 함께 사용한다.

- 입력 기준 revision/hash / 산출물 버전·노드 또는 commit:
- 기준별 pass/fail/unknown / 기대·실제 / 재현·증거 / 검증자 / independent 또는 self-review:
- 알려진 한계·미구현 / 다음 담당자·시작 조건 / 실패 귀환 역할:
- delivery 상태 / outcome 상태(미관찰 가능) / 관찰 지표·기준선·시점·담당자:

## 실행·재개 기록

intake → 역할 조율 → 계약 → Paperclip 큐 → 준비된 작업 실행 → 독립 검증
(자가 검증이면 표시) → 수정 또는 사람 판단 → 다음 작업 해제 → 제품 성과 확인
→ 새 학습/후보를 반복한다. 이 순서는 coordinator 운영 계약이며 자동 scheduler가 아니다.

- 선행 작업의 검증 완료와 자원 비충돌을 확인한 작업만 병렬 가능하다.
  failed/review/unknown은 완료가 아니다. hash는 순서나 priority가 아니다.
- Paperclip blocker/review/ownership을 먼저 사용한다. 공유 파일·DB·디자인 원본의
  writer 충돌은 실제 자원 key로 기록하고 coordinator가 직렬화한다.
- 기준 변경: 영향받는 산출물/후속 작업, 이전 증거의 유효·무효와 이유를 검토한다.
  이전 hash 증거를 새 계약의 pass로 옮기지 않는다. 자동 무효화는 아직 미검증이다.
- 매 시도에는 사용한 한도, 중단/대기 이유, 재개 조건과 담당자를 기록한다.
  재시작 시 외부 효과와 run/issue 상태를 먼저 대조한다. 한도 소진·미설명 반복 실패는
  사람에게 상향하며 무제한 유료 재시도를 만들지 않는다.
- delivery done 후 outcome 관찰이 남으면 실제 예약 여부를 구분하여 다음 트리거를 남긴다.
  성과 확인의 성공/실패/무효/불확실 결과를 새 근거·후보로 연결한다.
