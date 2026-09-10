# 모델·역할·업무 프로세스 시각화

Status: 구성·시각 검증 완료 · 2026-09-10

사용자 교정: 프로젝트 현황보다 실제 작업의 모델 목록 → 역할 배정 → 업무 인계 순서를
설명하려던 요청이다. 기존 현황 조사는 보존하고 새 시각화의 중심을 실행 모델로 바꾼다.

확인: 호스트 Codex 기본은 gpt-6-astra / medium. 로컬 model cache에는 astra,
5.6-sol/terra/luna, 5.5, 5.3-codex-spark와 reserve/auto-review 항목이 있다.
목록은 사용 자격/성능·비용 실측이 아니다. reserve/auto-review는 역할 executor로 배정하지 않았다.
Paperclip API에는 process Contract Probe와 paused codex_local Design Readiness만 있다.
둘 다 model/reasoningEffort 미지정, heartbeat off. 실제 역할 팀이 있다고 주장하지 않는다.

배정 제안: 총괄/계약 Astra, 기획/디자인 Astra 또는 Sol, 개발 Terra 또는 Sol,
검증은 별도 세션/검증자. 작은 보조 작업 Luna는 후보. 능력 비교 결과나 사용자 합의로
기록하지 않는다. PM·기획·디자인·개발·QA는 model 이름과 다른 역할 계약이다.

업무: intake → 총괄의 프로젝트/범위 조율 → PM·기획·QA의 기준 설계 →
기존 승인 근거와 완료 조건·권한·한도 확정 → 준비된 디자인/개발 → 검증 → 수정/사람 판단
또는 후속 해제 → 제품 성과·새 학습. 디자인 의존 개발은 원본 인계 검증을 기다린다.

산출: [모델·역할·업무 흐름](model-process.html). 새로운 agent 실행/모델 고정/비용 사용은 없음.

검증: Orca browser에서 실제 렌더·snapshot 확인, 모델표·역할별 산출물·인계 화살표와
현재 설정/제안의 구분을 PC screenshot으로 확인했다. 원본 설정/인증은 산출물에 없음.

## PM 중심 통합 · 2026-09-10

사용자 지시로 PM이 프레임워크를 적용해 역할을 배분하는 책임을 명시했다.
별도 총괄 직군을 추가하지 않고 coordinator를 PM의 조율 책임으로 통합한다.
references/pm-flow.md가 이 모델의 배정·인계 계약을 소유하며 SKILL/roles/handoff에서 연결한다.
PM은 정본·프로젝트 문서·도구 준비 상태·기존 권한을 읽고 역할/실제 executor/model을
작업별로 선택한다. QA는 최초 기준부터 참여, 디자인 의존 개발은 검증된 원본 인계 후 시작.
모델명 배정은 아직 제안이고 자동 scheduler/실제 역할 팀을 생성하지 않았다.
시각화에는 PM 책임, 모델 배정, 단계별 참여자/산출물/시작 조건을 함께 반영했다.

검증: skill validator 통과, v1 샘플 5개 계약 검사 통과. 동일 회사 skill을 갱신했고
Orca 실제 화면에서 PM 배정 구조와 단계별 업무 표의 렌더를 확인했다.

## PM → Paperclip + Orca 실행 흐름 · 2026-09-10

사용자와 합의한 위임: PM agent가 프레임워크 안에서 역할 배정·착수·수정·검증·후속
진행을 직접 조율하고 기존 권한을 반복 승인받지 않는다. 위임 밖의 기준/방향·권한/비용
변경이나 한도 소진은 사용자에게 돌린다. 상시 PM 기동 승인은 아니다.

버전별 Orca orchestration, coordinator-loop, placement-and-remote guide를 근거로
Paperclip=업무 상태, Orca=실행 Task/Dispatch, PM=판단·두 도구 호출로 책임을 나눴다.
pm-flow 참조에 ID 연결, 중복 실행 방지, worker_done과 검증 완료 구분, 중단/재개를 추가했다.
시각화와 업무 표도 동일 흐름으로 갱신했다. 실제 run/worker를 만들거나 자동 동기화를
구현하지 않았다. 다음 통합 시범에서 실제 lifecycle과 기록 반영을 검증해야 한다.

검증: skill validator와 기존 5개 계약 검사 통과, Orca PC 렌더 확인.
Orca 노드의 보조 라벨 여백을 조정했고 기존 제품 작업·runtime 설정은 변경하지 않았다.

## 도구 분리와 주기 점검 후보 · 2026-09-10

사용자가 승인한 도구 분리: PM 업무 계약과 현재 Paperclip/Orca 연결 지침을 분리했다.
pm-flow는 판단·역할·업무 ID·기준을 소유, execution-tools는 앱 ID·실행·회복 규약 연결을
소유한다. handoff에는 입력/권한/기준/현재 결과/남은 일/중단 상태/재개 조건을 담는
portable snapshot 양식을 추가했다. 기존 v1 JSON·샘플은 보존한다.

후속 질문의 주기적 루프는 review-loop에 제안으로 기록했다. 이벤트 반응 + 주기 누락 점검,
no-op, 활성 시도 중복 방지, PM/worker 합산 한도·중단·재개를 포함한다.
대상·주기·운영 시간·한도는 미정이며 schedule·PM/worker 실행을 켜지 않았다.
상시 runtime·범용 adapter·자동 타 도구 복구를 구현한 것으로 기록하지 않는다.

## 역할별 내부 흐름과 전체 인계 · 2026-09-10

사용자 요청으로 PM·기획·디자인·개발·QA를 하나의 실행 팀 경계 안에 배치했다.
각 역할의 모델 후보, 내부 5단계, 입력/산출물, 실패 시 귀환을 roles.md에 근거해 표시한다.
주요 인계는 연결도로, 역할 사이 10개 조합의 양방향 인계/피드백은 표로 표현했다.
사용자⇄PM과 후속·성과 연결까지 포함해 인계 표는 12행이다. 직접 전문 질문과
PM이 조율하는 범위/기준·재배정을 구분한다. 논리적 책임 영역이며 상시 agent 배포도가 아니다.

검증: Orca PC screenshot에서 전체 팀 경계·역할별 흐름·하단 인계 표 렌더 확인.
DOM 확인 결과 역할 5, 내부 단계 25, 인계 12행, 페이지 가로 overflow 없음.
도구 분리 문서 링크·skill validator·기존 계약 5개 검사 통과. v1 fixture 바이트 유지.
주기 점검과 모델 배정은 후보로 보존했고 실제 실행·schedule은 활성화하지 않았다.
