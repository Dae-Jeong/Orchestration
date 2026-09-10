# 여러 프로젝트 조율 구조와 현황 시각화

Status: 시각화·현황 조사 완료 · 2026-09-10

## 목표와 범위

대표인 사용자 → 공통 조율 → 프로젝트별 역할/작업의 관계와 현재 연결 수준을 구분한다.
Dae-Jeong의 `skills/render-server-architecture/SKILL.md`와 운영자 wiki의
Server Architecture Views 표현 기준을 적용한다. 시간 순서는 별도 흐름으로 표현한다.
다른 repo는 읽기만 하며, 프로젝트 등록·agent dispatch·배포·DB 변경은 이 작업에 포함하지 않는다.

수용 조건: 실제 HTML 구성도, 프로젝트별 현황/출처/미확인 범위, 현재/제안 연결의 구분,
Orca PC 렌더와 주요 탭 조작 검증. 새 scheduler나 실시간 대시보드는 만들지 않는다.

## 조사 범위와 근거

2026-09-10 Orca repo list/worktree ps에 등록된 저장소 8개와 해당 README·현재 상태·최근
task, Git branch/HEAD/dirty 여부를 읽었다. 머신 전체 저장소나 원격 서비스의 전수 조사는 아니다.
Orca 카드 상태는 작업자 기록이며 테스트 통과/제품 완료 증거가 아니다. 다른 프로젝트의
테스트·배포·DB는 재실행하지 않았다. 아래 제품 상태는 문서 근거의 요약이다.

Paperclip API 직접 조회: 회사 1, project 1(Personal Orchestration Model, planned),
연결된 제안 issue 5(backlog), 프로젝트 외 persistence fixture 1. 나머지 7 repo는 이
Paperclip 회사의 project로 등록돼 있지 않다. Orca terminal 존재는 Paperclip 관리 증거가 아니다.

| 저장소 | 목적 / 문서상 현재 범위 | Orca 카드 | 다음 확인 / 한계 | 근거 |
| --- | --- | --- | --- | --- |
| orchestration | 설치·v1 계약·역할 지침, Pencil 연결 | in-progress | UIBowl 인증 401, 제품 실행 미검증 | tasks/personal-model.md + API |
| Dae-Jeong | 경력 근거·이력서·포트폴리오, UI 비교안 검토 | in-review | 양식 선택 대기, 공개 표현 변경과 구분 | README, wiki/context/current-state.md, Orca 카드 |
| laughtale | 채팅 제품·신뢰성 실험, Peer 리팩터링과 디자인 인계 | in-progress | FE 디자인 반영/제품 인증/성능 목표 구분 | README, tasks/linky-chat-internal-dm.md, 사용자 디자인 인계 |
| showmethemoney | 오프라인 Paper Trading·PG Journal·API | in-progress | 실제 시장 연동/실주문 없음 | README, tasks/code-readability.md |
| backend-template | FastAPI/NestJS/Spring Boot 공통 개발 기반 | completed | 카드 완료는 최근 작업 상태, 모든 제품의 완료 아님 | README, Orca 카드 |
| tellingme-server | Spring 서버 통합·PostgreSQL 단일화 | in-review | 원격 CI/AWS 검증은 해당 task에서 미실행 | README, tasks/h2-and-unused-files-review.md |
| thready | 콘텐츠 운영 FE/BE/AI, release 브랜치 작업 | in-progress | current-state 문서 v1.9 후보와 브랜치 v1.10 차이; 실제 배포판 미확인 | AGENTS, wiki/current-state.md, Git |
| MEDISOLVEAI-INFRA | 공통 인프라·모니터링 조율 | in-progress | 문서/카드 기준; 실제 운영 재검증 없음 | README, Orca 카드 |

조회 시 dirty repo 4개(Dae-Jeong, laughtale, showmethemoney, MEDISOLVEAI-INFRA).
다른 작업이 진행 중이므로 현황 조사를 쓰기 소유권으로 해석하지 않는다.
전역 profile에 있는 Centurion/NEXUS/mediness는 이번 Orca 등록 목록에 독립 repo로 없으므로
위 8개와 별도다. 발견 목록과 전체 제품 포트폴리오가 동일하다고 주장하지 않는다.

## 제안 모델

사용자는 대표/제품 판단권자, coordinator는 우선순위·권한·의존성·증거를 연결한다.
제품별 프로젝트가 목표·backlog·환경·근거를 소유하고 PM/기획/디자인/개발/QA 관점은
필요한 작업에 배정한다. 직군마다 상시 agent를 띄우거나 repo마다 고정 팀을 만들지 않는다.
backend-template/인프라/orchestration 같은 공통 기반은 여러 제품을 돕는 별도 프로젝트다.
repo 하나에 여러 제품이 있을 수 있고 한 제품이 여러 repo를 쓸 수 있으므로 1:1을 강제하지 않는다.

제품 간 전환에는 project ID, workspace/branch, 규칙 정본, task 기준 revision/hash,
권한·예산·검증자, 공유 자원 소유권을 다시 선택한다. 이미 합의한 권한은 재사용한다.
자원 비충돌과 선행 검증 완료면 동시 진행, review/fail/기준 변경/충돌이면 해당 작업만 대기한다.
회사/개인/외부 협업 저장소의 자격·배포 권한은 서로 상속하지 않는다.
하나의 화면에서 볼 수 있다는 것과 하나의 보안 경계로 합친다는 것은 다르다.

현재 한 Paperclip company 아래 여러 project로 표현하는 방향은 후보다. 조직/자격 경계가
다르면 별도 company 또는 별도 인스턴스 필요성을 검토한다. 이번에는 어떤 repo도 새로
등록하거나 권한을 넘기지 않았다. 구조도 점선은 제안 연결이며 자동 dispatch 구현이 아니다.

## 산출물과 검증

- [시각화](portfolio-overview.html): 소유 구조 / 작업 흐름 / 프로젝트 현황, 읽기 전용 snapshot.
- [x] Orca PC 2378×1551에서 소유 구조·프로세스·현황 화면 스크린샷 확인.
  실제 도식은 최대 1240px 레이아웃에 배치, 제목·연결·경계/라벨 점검.
- [x] 세 탭 전환, Laughtale 선택 시 상세 변경, 현황 8행 확인, 페이지 가로 overflow 없음.
  프로세스 탭의 hidden SVG marker 참조를 자체 marker로 수정했고 기준 변경 귀환은 계약에 연결.
- [x] 별도 런타임/외부 라이브러리 없는 standalone HTML. 새 DB/agent/프로젝트 등록 없음.
- [x] git diff whitespace·파일 링크 검사. A4/PDF·모바일은 이번 검증 범위 아님.
