# Personal Orchestration

소재를 PM/기획·디자인·개발의 작업으로 구체화하고, 완료 조건·권한·의존성·검증 증거를
연결하는 개인 운영 모델입니다. Paperclip을 상태와 실행 기반으로 사용하며 별도 scheduler는 없습니다.

## 업무 흐름과 역할

![사용자·PM·기획·디자인·개발·QA와 Paperclip·Orca를 연결한 통합 업무 흐름](docs/images/model-process.png)

[이미지 크게 보기](docs/images/model-process.png) · [원본 흐름도와 역할별 인계 상세](tasks/model-process.html)

모델 배정과 주기 점검 루프는 운영안이며, 상시 실행 중인 agent 구성을 뜻하지 않습니다.

## 현재 결과

2026-09-10: Paperclip 2026.831.1 설치, UI, 전용 DB, 앱 종료/재시작 후 상태 보존 검증 완료.
5개 제안 계약과 회사 skill을 등록하고 무료 process probe를 실행했습니다.
LLM 역할 팀의 실제 제품 수행과 지속 병렬 실행은 아직 검증하지 않았습니다.

- 접속: <http://127.0.0.1:13100/ORC/issues> — Orca 프로젝트 browser에도 열려 있습니다.
- 기동: `./scripts/paperclip run --no-repair`
- 중지: Paperclip 서버 터미널에서 Ctrl-C. Orca CLI에서는 버전 guide를 읽고
  `orca terminal list --worktree active --json`으로 Paperclip local을 찾은 뒤
  `orca terminal close --terminal <handle> --json`. DB 컨테이너는 중지하지 않습니다.
- [설치·환경·증거](tasks/paperclip-pilot.md), [모델 작업](tasks/personal-model.md)
- [재사용 skill](skills/squad-model/SKILL.md), [모델 계약](skills/squad-model/references/model.md),
  [샘플 계약](examples/pilot.json)
- [PM·기획·디자인·개발·QA 역할 계약](skills/squad-model/references/roles.md),
  [완료·인계 양식](skills/squad-model/references/handoff.md),
  [UIBowl → Pencil 도구 계약](skills/squad-model/references/design-tools.md)

역할 지침과 회사 skill 갱신을 완료했습니다. Design Readiness Codex agent는 paused입니다.
명시적 전용 CODEX_HOME에 두 MCP와 필요한 skill을 구성했고 모델 없는 연결 검사에서
Pencil은 성공, UIBowl은 HTTP 401로 인증 미완료입니다. 기본 managed seed 검증과 구분합니다.

## 새 clone에서 설치

필요한 도구: Git, fnm, Python 3, 운영자가 이미 준비한 PostgreSQL.
검증 환경은 macOS arm64, Node 24.21.0, PostgreSQL 16.15입니다. 다른 OS/CPU는 별도 확인이 필요합니다.

```sh
./scripts/install-paperclip
```

프로젝트 .runtime/fnm에 Node를 설치하고 npm ci --ignore-scripts로 lockfile을 설치합니다.
공식 npm 배포를 사용하며 upstream 코드를 커밋하지 않습니다. embedded PostgreSQL 패키지는
배포 의존성으로 존재하지만 인스턴스를 생성/기동하지 않습니다.

DB 설정은 자동 일반화하지 않습니다. 운영자 승인 범위에서만
`python3 scripts/provision-paperclip-db.py`를 사용했습니다. 기존 thready-postgres(5433)의
thready 관리 접속을 전제로 새 orchestration_paperclip DB/role과 해당 DB 확장만 만듭니다.
기존 이름이 있으면 변경 없이 멈춥니다. 다른 머신에서는 관리자가 기존 인스턴스와 최소 권한을
준비해야 합니다. 기존 다른 DB/앱을 업그레이드하지 않습니다.

.env.paperclip(Git 제외)에 외부 DATABASE_URL, PAPERCLIP_HOME, PORT, HOST, SERVE_UI를 설정합니다.
현재 wrapper는 이 전용 DB/5433 목적지만 허용합니다. 자동 일정은 HEARTBEAT_SCHEDULER_ENABLED=false,
telemetry는 DO_NOT_TRACK=1로 끕니다. 비밀은 chmod 600으로 보호하고 출력하지 않습니다.

```sh
./scripts/paperclip onboard --yes --no-install-service
# 새 전용 DB에서만 초기 migration 질문에 y
```

외부 DB 설정 없이 공식 quickstart를 직접 실행하면 embedded DB를 만들 수 있으므로
이 repo의 외부 DB wrapper를 사용합니다.

## 모델 사용과 검증

[PM 업무 계약](skills/squad-model/references/pm-flow.md)은 도구와 분리하고,
[Paperclip·Orca 연결](skills/squad-model/references/execution-tools.md)은 별도 지침으로 둡니다.
[인계 양식](skills/squad-model/references/handoff.md)은 다른 실행 수단에서도 읽을 수 있는
업무·결과·남은 일 snapshot입니다. 자동 이전 기능은 아닙니다.
[주기 점검 루프](skills/squad-model/references/review-loop.md)는 설계 후보이며 아직 활성화하지 않았습니다.

[모델 → 역할 → 업무 인계 시각화](tasks/model-process.html)에서 실제 모델 설정과
역할별 배정안을 구분해 볼 수 있습니다. 상시 팀이나 자동 모델 배정은 아직 미구현입니다.

[여러 프로젝트의 소유 구조·작업 흐름·현황 시각화](tasks/portfolio-overview.html)를
브라우저에서 열 수 있습니다. [조사 근거](tasks/portfolio-overview.md)는 2026-09-10
snapshot이며 실시간 dashboard나 프로젝트 간 자동 실행 구현은 아닙니다.

```sh
python3 scripts/check-contracts.py examples/pilot.json
python3 -m unittest discover -s tests -v
python3 scripts/seed-paperclip-pilot.py --company-id <local-company-uuid>
```

seed는 local pilot API에 미할당 backlog와 구조화된 blocker를 등록합니다. 반복 실행 시
같은 제목을 재사용하며 기존 계약은 업데이트하지 않습니다. 변경 계약은 별도 비교·합의 후
수정해야 합니다. 샘플의 proposed는 사용자 합의를 뜻하지 않습니다.

회사 skill은 checkout을 Paperclip project workspace로 등록한 뒤
`./scripts/paperclip skills import "$PWD/skills/squad-model" --company-id <id> --api-base http://127.0.0.1:13100`
로 가져옵니다. 서버가 다른 머신이면 서버에서 접근 가능한 경로가 필요합니다.
process adapter는 managed skill sync가 미지원이므로 probe는 파일을 명시적으로 읽습니다.
Codex adapter도 sync 응답의 configured는 다음 실행 시 연결 예정이라는 뜻입니다.
무료 구성 확인은 다음과 같이 실행하며 agent/model/MCP를 기동하지 않습니다.

```sh
python3 scripts/probe-design-readiness.py --agent-id <design-agent-uuid> \
  --instance-root .paperclip/instances/default
```

실제 디자인 실행에는 운영자 소유의 Pencil 앱/CLI, 인증된 UIBowl MCP,
product-workflow skill과 정본 연결이 필요합니다. 인증 URL/config는 복제해 배포하지 않습니다.
현재 기본 managed home seed가 호스트 config 전체를 복사하므로 이 agent는 공식 지원
env.CODEX_HOME override로 .runtime/design-codex-home을 사용합니다. 두 MCP 설정만
로컬 권한 600 파일에 구성하고 skill은 원본으로 연결했습니다. Codex 인증은 복제하지
않았으며 유료 실행은 하지 않았습니다. UIBowl 인증과 실행 범위가 준비되기 전 paused를
유지합니다. 자세한 검증 경계는 모델 작업 문서에 있습니다.

## 외부 문서와 로컬 데이터

운영자의 machine-wide AGENTS.md 및 그것이 가리키는 global wiki가 공통 규칙의 정본입니다.
Product Workflow는 운영자가 제공하는 PRODUCT_WORKFLOW_FILE로 연결합니다. 해당 파일은
저장소에 포함하지 않으며 새 clone만으로 접근할 수 없습니다. 없으면 repo의 명시적 계약만
적용하고 정본을 읽었다고 주장하지 않습니다. 실제 역할 수행 전에 연결을 확인합니다.

미확정 .ideas/는 로컬 원장으로 보존합니다. .env*, .paperclip/, .runtime/, node_modules/,
.artifacts/, 조사용 vendor/, 덤프·로그·인증 파일·머신 절대 경로는 원격에 올리지 않습니다.

upstream audit에 1 high / 5 moderate가 남아 있습니다. 미사용 Cursor cloud 의존성의 undici
연쇄이며 외부 공개/agent 확장 전에 재검토합니다. audit fix --force는 적용하지 않았습니다.
