# 개인 오케스트레이션 모델

Status: v1 계약·5개 샘플 유지, 역할/인계 지침 구성 완료. 전용 runtime Pencil 연결 성공, UIBowl 인증 미완료. 제품/LLM 시범 미실행.
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

### 설정 화면 오류 복구

후속 사용자 제보로 실제 화면의 Internal server error를 확인했다. 프로젝트 이름에 의도하지
않은 입력이 섞여 urlKey가 바뀌었고, 기존 이름 URL 조회가 실패했다. 이 버전은 찾지 못한
shortname을 UUID 쿼리에 전달해 HTTP 500을 반환한다. 앞선 UUID API 확인만으로는 이 오류를
발견하지 못했다. 이름을 Personal Orchestration Model로 복원한 뒤 기존 shortname API 200,
Orca 새로고침 후 Configuration/Codebase 렌더링 및 오류 문구 없음까지 확인했다.
설정·workspace·작업은 보존했고 upstream 소스나 DB schema를 수정하지 않았다.

## 역할 지침과 디자인 연결 · 2026-09-10

사용자의 후속 논의를 이 task 범위의 계약으로 반영했다. 기존 global Product Workflow와
product-workflow skill을 읽고 연결하며 공통 정본을 복사하지 않는다.

- [x] PM·기획·디자인·개발·QA 각각 입력/책임/판단 권한/산출물/시작/완료/다음 인계/
  실패 귀환을 references/roles.md에 구성. 직군과 DACI 결정 책임, 독립/자가 검증 구분.
- [x] references/handoff.md에 공통 DoD, 관찰 가능한 task 조건·검증법·증거·reviewer,
  기존 권한 재사용, 기준 변경 영향 검토, 병렬/대기 이유와 한도·중단/재개 기록 구성.
  delivery와 outcome·새 학습 루프를 구분. 자료 없는 항목은 proposed.
- [x] UIBowl → Pencil → FE/QA 인계 확정. 디자인 원본/노드·토큰·상태와 렌더 증거,
  FE의 CSS/컴포넌트 대응·실제 브라우저 검증을 분리. 별도 scheduler는 추가하지 않음.
- [x] v1 JSON과 샘플 5개는 수정하지 않음. enum의 pm-planning/verification에 상세
  관점을 매핑. 계약 검사 5 tests와 skill validator 통과, 참조 문서 읽기 probe 성공.
- [x] 동일 회사 skill ID로 import 갱신. Design Readiness codex_local agent를 만들고
  paused 유지, heartbeat off, sandbox/approval bypass false, 모델 호출/실제 작업 없음.
  디자인 전용 진입 지침과 squad-model desired skill을 연결했다.

### 직접 검증과 인계 근거

Pencil MCP read_skill, execute/schema 문서를 읽고 get_app_state 성공.
명시 원본에서 주요 플로우 노드 yAO0C와 reusable 6개를 read-only로 조회했다.
다른 디자인 원본/active canvas는 편집하지 않았다. 전체 SDS 24개, 화면/상태 수,
스크린샷·잘림 검사는 제작자 보고이며 이 작업에서 전체 재검증한 결과가 아니다.
UIBowl의 실제 사용은 사용자 전달 제작자 답변으로 확정, 현 catalog 노출도 확인했다.
새 레퍼런스 검색 호출이나 결과 적합성 검사는 하지 않았다.
Open Design은 이번 제작 미사용, Figma는 필수 의존성 아님.

설치 버전 코드에서 codex_local sync는 supported:true / mode:ephemeral,
state:configured / targetPath:null이며 다음 run에 실제 mount한다.
새 `scripts/probe-design-readiness.py`를 paused agent 대상으로 실행한 결과:
effective_home_exists=false, per_agent_home_exists=false, skill_entries=[],
connection_verified=false, model_calls=0, mcp_calls=0.
호스트 설정에서는 pencil(stdio), uibowl(http)의 enabled만 확인했고 원문 설정/URL은
출력·복사하지 않았다. 호스트 연결 성공을 managed runtime 성공으로 간주하지 않는다.

### 전용 runtime 구성과 남은 장애

기본 managed Codex home에 두 MCP만 노출하는 연결은 **미검증**이다. 설치 코드의
seedManagedCodexHome는 호스트 config.toml/config.json/instructions.md를 복사하고
auth를 연결한다. 기본 seed를 호출하면 필요한 두 server만 노출한다고 보장할 수 없다.
초기 미존재 probe 후 공식 지원 env.CODEX_HOME override를 선택해
.runtime/design-codex-home을 이 agent에 명시적으로 연결했다. 기본 managed seed를
검증했다고 주장하지 않는다. 원문 설정은 출력하지 않고 호스트의 pencil/uibowl
두 항목만 이 로컬 home의 600 권한 config에 구성했다. home 권한 700,
Codex auth는 복제하지 않았다. squad-model/product-workflow는 원본 skill symlink,
PRODUCT_WORKFLOW_FILE은 운영자 정본을 가리킨다. git에는 경로나 인증 값을 넣지 않는다.

전용 home에서 `codex mcp list --json` 결과를 이름/활성 여부만 추려 두 server enabled
확인. 같은 config로 MCP SDK를 사용해 모델 없는 initialize/tools/list 실행:
첫 Pencil 초기화 실패 후 1회 재확인에서 5 tools와 get_app_state 성공.
UIBowl은 두 번 모두 HTTP 401 Unauthorized. 설정에 별도 bearer env/header가 없어
누락 환경 변수라고 단정할 수 없으며, 현재 대화 connector 노출과 이 연결의 인증은 다르다.
인증 값은 출력/커밋하지 않았다. private 점검 코드는 .artifacts에만 두었다.

후속 read-only readiness probe: explicit_override, effective_home_exists=true,
pencil/uibowl configured+enabled, 두 skill 파일과 정본 읽기 성공. 파일 접근 및 Pencil
protocol 연결 증거이며 Paperclip가 모델을 실행해 skill을 이해했다는 증거가 아니다.
기본 Codex sync의 자동 skill mount도 아직 실행 검증하지 않았다.
Design Readiness는 paused, heartbeat off, bypass false, lastHeartbeatAt=null이다.

남은 구체적 장애는 **전용 runtime UIBowl 인증 401**이다. 운영자 소유 UIBowl 연결을
재인증/갱신한 뒤 비밀을 노출하지 않고 initialize/tools/list를 다시 확인해야 한다.
실제 모델 수행은 소재·수용 조건·reviewer·횟수/시간/비용 한도가 있는 별도 task다.
상시 유료 loop, 자동 디자인→코드 동기화, 배포, 실제 제품 outcome은 승인/검증되지 않았다.
