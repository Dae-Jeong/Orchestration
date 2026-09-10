# Paperclip 설치·시범 운영

Status: 설치·UI·전용 DB·종료/재기동·상태 보존 완료. 무료 probe 완료; 실제 LLM 운영 미실행.
Updated: 2026-09-10

## 범위와 결정

기존 공유 5433 인스턴스의 새 전용 DB만 변경한다. 다른 앱/DB/role의 기존 권한·프로세스는
변경하지 않는다. 후속 사용자 지시로 개인 모델 구성·private origin 생성·commit/push가 추가됐다.
[모델 작업](personal-model.md) 참조. 유료 모델·상시 다중 agent·제품 배포·외부 메시지는 제외한다.

## 설치와 환경

| 항목 | 확인 결과 |
| --- | --- |
| 공식 배포 | npm paperclipai@2026.831.1, package-lock.json integrity 고정 |
| 소스 대조 | tag v2026.831.1, commit 65ec059bde30d98c92165b24a30a540800dd1f6f |
| Node 요구/설치 | >=24.11.0 / 프로젝트 fnm Node 24.21.0; 기존 v22.9.0 변경 없음 |
| 시스템 | macOS arm64, Orca 1.4.199 |
| DB | 기존 thready-postgres, PostgreSQL 16.15, 127.0.0.1:5433 |
| 전용 DB/role | orchestration_paperclip / 같은 이름의 LOGIN |
| role 권한 | NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS |
| DB 권한 | 전용 DB owner, 전용 DB PUBLIC 접근/스키마 CREATE 제거; 타 DB/role 변경 없음 |
| 확장 | pg_trgm 1.6, fuzzystrmatch 1.2; 해당 DB에만 설치 |
| 앱 | 127.0.0.1:13100, local_trusted, static UI; 초기 점유 없음 확인 |
| 자동 실행 | heartbeat scheduler disabled, probe agent heartbeat disabled |
| 외부 비용 | 유료 LLM 미설정, model_calls=0, DO_NOT_TRACK=1 |
| 백업 | 자동 DB backup disabled; DB dump 생성하지 않음 |

PostgreSQL 16 호환은 229 migration과 CRUD/재기동으로 확인했다. 모든 기능의 호환성을 보증하지 않는다.
embedded PostgreSQL은 배포 의존성에 포함되지만 인스턴스를 기동하지 않았다.

## 실행·중지·저장

`./scripts/install-paperclip` → 외부 DB 구성 →
`./scripts/paperclip onboard --yes --no-install-service`.
이후 `./scripts/paperclip run --no-repair`. UI <http://127.0.0.1:13100/ORC/issues>.
중지는 서버 Ctrl-C 또는 Orca의 해당 Paperclip terminal close만 사용한다. OS 서비스는 설치하지 않았다.

| 데이터 | 위치 (checkout 상대) |
| --- | --- |
| 런타임 | .runtime/fnm, node_modules |
| 비밀 환경 | .env.paperclip (0600) |
| 앱 설정/키 | .paperclip/instances/default/config.json, secrets/master.key, .env |
| 파일/skill/로그 | .paperclip/instances/default/data, workspaces, logs 등 |
| 주요 영속 상태 | 공유 PostgreSQL의 전용 orchestration_paperclip DB |
| 샘플 ID 매핑 | .paperclip/pilot-map.json |
| 변경 전 로컬 문서 | .artifacts/pre-install (원격 제외) |

설정/키/파일 저장소도 DB와 함께 보존해야 한다. DB만으로 전체 복원된다고 주장하지 않는다.
머신 절대 경로와 runtime handle은 원격 기록에서 제외한다.

## 검증 증거

- [x] 공식 npm/tag 요구 버전 및 lockfile 확인.
- [x] 기존 PostgreSQL 16.15 실접속, 새 role/DB, 229 migration 성공.
- [x] /api/health: status=ok, version=2026.831.1, local_trusted, authReady=true.
- [x] Orca dashboard/tasks 화면 직접 확인. ORC-1~6 표시.
- [x] 첫 서버 02:25:14 UTC → terminal close(ptyKilled=true), 13100 listener 없음 →
  02:27:03 UTC 재시작. ORC-1 UUID 74c502c7-9906-47ae-9e59-69ae4ef173cb,
  backlog, description 동일. DB 컨테이너는 재기동하지 않았다.
- [x] process run f3a412b1-7e0c-48cb-8f08-4621aba7dfc7: succeeded,
  contracts_valid=5, canonical_workflow_read=true, model_calls=0.
- [x] 회사 skill/reference API 읽기 성공; process 자동 skill sync 미지원 확인.
- [x] native blocker 0/1/1/2/1 및 optional approval 저장; 순환 관계 HTTP 422 거부.
- [x] 계약 검사 5 tests, skill 구조 validator 통과.
- [x] 공식 lockfile로 npm ci --ignore-scripts 재설치 완료(9초). 02:36:14 UTC 두 번째
  재기동 후 ORC-2~6 ID/backlog/blocker 수와 probe run succeeded 이력 보존 확인.
- [x] 전용 DB public 테이블 179개, 확장 3개(plpgsql 포함), 전용 role의 관리 권한 모두 false.

## 설치 버전 대조와 한계

실제 API에서 enableIsolatedWorkspaces=false, enableIssuePlanDecompositions=false.
소스 packages/shared/src/feature-catalog.ts에서도 selfHostedDefault=false다.
server/src/services/issue-execution-policy.ts에서 기본 review rounds 3,
responsibleUserId → createdByUserId 순서의 사람 상향, 사람 없는 예외를 확인했다.
기본 issue policy는 null, ORC-6에만 사용자 approval을 명시했다.
실제 agent done interception/수정 반복/사람 상향 전체 동작은 미검증이다.
workspace opt-in이나 sandbox bypass는 하지 않았다.

Doctor는 critical checks 통과, secrets strict mode 기본 false 경고 1개.
npm audit는 undici(Cursor cloud 의존성) 1 high와 연쇄 5 moderate.
이 pilot은 해당 adapter를 사용하지 않으며 외부 노출 전에 재검토한다.
force fix 제안은 구버전으로 변경하므로 실행하지 않았다.

Codex managed home/skill 주입, 역할 품질, resource lock, crash 후 외부 효과 중복 방지,
기준 변경 자동 무효화는 미검증. 다음 실험의 소재·권한·시간/비용은 별도 합의한다.

## 공식 출처 (2026-09-10 확인, 변경 가능)

- [고정 소스](https://github.com/paperclipai/paperclip/tree/v2026.831.1)
- [DB 문서](https://docs.paperclip.ing/reference/deploy/database/)
- [Execution policy](https://docs.paperclip.ing/guides/power/execution-policy/)
- [Workspaces](https://docs.paperclip.ing/guides/projects-workflow/workspaces/)

공식 embedded/파괴적 reset 절차는 이 머신 정책과 맞지 않아 사용하지 않았다.
