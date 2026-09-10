# 개인 오케스트레이션 모델

Status: v1 지침·계약·Paperclip 샘플 등록 검증 완료. 실제 제품/LLM 시범은 미실행.
Updated: 2026-09-10

## 범위와 결정

사용자가 개인 orchestration 저장소에 자신의 모델을 구성하고 origin에 올리도록 승인했다.
기존 비공개 아이디어와 운영자 소유 Product Workflow에서 이번 범위만 구체화했다.
공통 행동 규칙은 복제하지 않는다. 역할은 관점이며 독립 agent 수를 강제하지 않는다.

구현: intake → 역할 조율 → 작업별 기준/권한 기록 → 안정적인 ID 및 별도 revision/hash →
의존성과 공유 자원 판단 → 실행/검증/수정/사람 판단 → 후속 재개.
Paperclip을 작업 상태·blocker·review/approval 저장소로 사용한다. 자체 scheduler는 없다.
계약 검사기는 정적 오류를 발견할 뿐 실행 권한이나 준비 상태를 강제하지 않는다.

## 결과와 증거

- [x] `skills/squad-model/`: 역할 입력·출력, 계약, 검증과 재개 지침. Skill validator 통과.
- [x] `examples/pilot.json`: 5개 제안 계약. 사용자 합의 사실을 만들어 넣지 않았다.
- [x] 계약 검사 5 tests 통과: 정상 fork/join, 누락/순환 의존성, 권한 변경 hash 불일치,
  revision 변경 후 이전 증거 거부, 합의 근거 없는 agreed 상태 거부.
- [x] Paperclip ORC-2~6 등록. blocker 수 0/1/1/2/1, ORC-6에 명시적 사용자 approval.
- [x] seed 재실행 시 같은 ID 유지. 이 도구는 기존 계약을 덮어쓰거나 실행하지 않는다.
- [x] 실제 순환 blocker PATCH에 HTTP 422 `Blocking relations cannot contain cycles`.
- [x] 회사 skill import와 reference 파일 읽기 API 성공. workspace 등록 전 경계 거부는
  프로젝트의 로컬 workspace 등록으로 해결했고 우회 플래그를 사용하지 않았다.
- [x] 무료 process probe 성공: skill/reference hash 출력, 5 contracts valid,
  canonical_workflow_read=true, model_calls=0. 파일 접근 증거이며 LLM 이해 검증이 아니다.
- [x] 개인 GitHub `KimMarin` 확인, 기존 동명 repo 없음(404).
  private origin `https://github.com/KimMarin/orchestration` 생성·연결 확인.
  최종 Git commit/remote ref가 전송 증거이며 비밀/로컬 원장은 제외한다.

## 남은 경계

process adapter skill sync는 `supported:false`; 파일을 명시적으로 읽는 probe로 검증했다.
실제 Codex adapter의 managed home·skill 주입·유료 실행, 병렬 executor 동작, resource lock,
review 반복 후 사람 상향, crash 후 외부 효과 중복 방지, 변경 기준의 자동 무효화는 미검증이다.
설치 성공과 운영 모델의 제품 적합성 검증을 구분한다.

다음 선택지: (1) 현재 무료 fixture로 native review 전환을 더 검증, (2) 단일 Codex executor에
실제 소재·권한·횟수/시간/비용 한도를 정해 한 번 실행, (3) 그 결과 이후 역할별 분리 판단.
새로운 기본 재시도/예산/검토 정책은 후보이며 이번 문서로 상시 실행을 승인하지 않는다.

## Orca 브라우저 설정 · 2026-09-10

사용자 요청으로 실제 브라우저 UI에서 기존 Personal Orchestration Model 프로젝트를 정리했다.
Configuration → Codebase에서 개인 GitHub 저장소를 연결하고 기존 local-model workspace를
유지했다. 프로젝트 설명과 PRODUCT_WORKFLOW_FILE 환경 변수도 저장했다. 경로 값은 DB에만 둔다.
ORC-2~6을 각각 Properties → Project로 이 프로젝트에 연결했다. 모두 backlog이며 기존
blocker/approval은 유지했다. 새로운 회사나 중복 workspace, 유료 agent는 생성하지 않았다.

검증: UI 저장 후 API 재조회에서 repo URL, workspace 1개, 설명, 환경 변수 키와 프로젝트
소속 이슈 5개 확인. Orca 설정 탭 URL:
http://127.0.0.1:13100/ORC/projects/personal-orchestration-model/configuration
일반 workspace 연결은 Codebase에 표시되며, 실험적 작업별 격리 workspace는 계속 비활성이다.
