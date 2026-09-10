# Laughtale · Dae-Jeong 연결

Status: 로컬 연결·검증 완료 · 2026-09-10

## 목표

사용자가 지정한 두 repo를 공통 Squad Model과 현재 Paperclip 회사에 연결한다.
제품별 맥락·정본·검증을 유지하며 다음 PM 세션이 올바른 repo에서 업무를 시작하게 한다.

## 예상 결과

- 각 AGENTS에서 프로젝트별 연결 문서와 고정 모델 버전을 찾을 수 있음.
- Paperclip에 구분된 두 프로젝트와 정확한 로컬 workspace가 저장됨.
- 현재 제품 변경·진행 중인 세션을 보존하고 새로운 작업을 중복 실행하지 않음.
- 로컬 경로·runtime ID는 ignored 설정에만 보존, portable 문서는 logical alias 사용.

## 범위와 판단

설정은 문서 라우팅·로컬 소스 매핑·Paperclip 프로젝트 등록이다. 공통 행동 규칙은 global wiki,
Squad 계약은 이 repo, 제품 사실과 검증은 각 제품 repo가 소유한다. 제품별 agent 설치나
기존 작업 일괄 이관·자동 실행·주기 루프를 포함하지 않는다.
Laughtale의 기존 Product Workflow 시범은 요약 적용 기록이며 실행기 설치 증거는 아니다.
Dae-Jeong의 지원 팀 skill·claim 검증 흐름은 새 일반 역할로 대체하지 않는다.
두 repo의 기존 변경이 많으므로 새 연결 파일과 진입점만 편집하며 제품 repo push는 하지 않는다.

## 검증

- [x] 진입 문서·모델 pin·local alias 해석 확인.
- [x] Paperclip 프로젝트·workspace·manual 상태 재조회.
- [x] 두 repo의 연결 문서 검사와 변경 범위 확인.

AGENTS에 연결한 Laughtale `docs/orchestration.md`, Dae-Jeong
`wiki/context/orchestration.md`의 상대 링크와 모델 채택 커밋의 skill 존재를 확인했다.
각 `.local/source-roots.yaml`과 `.local/orchestration.json`은 git check-ignore로 제외를 확인했다.
Paperclip 두 프로젝트의 이름·서로 다른 ID·로컬 cwd·primary workspace를 재조회했고,
runtime desiredState=manual, executionWorkspacePolicy.enabled=false, leadAgentId=null이었다.
Orca repo/worktree 목록에서 각각의 실제 기존 checkout을 대조했다.

Dae-Jeong `make verify-wiki`: workspace validation PASS / verify PASS.
이는 기존 dirty 작업 트리에서 수행한 wiki 검사이며 FE·배포·제품 실행 검증은 아니다.
두 제품의 연결 변경에 diff whitespace 오류가 없었다. 변경은 각 AGENTS, 새 연결 문서,
Laughtale gitignore의 `.local/` 제외와 ignored 로컬 매핑이다. 기존 제품 변경을 보존했다.
제품 repo는 커밋·push하지 않았다. 중앙 repo에는 사용 안내·검증 기록만 반영한다.

설정 완료와 두 제품의 실제 업무 수행 검증은 별개다. 첫 제품 작업의 소재와 완료 조건은
해당 프로젝트 PM이 다음 사용자 요청에서 구체화한다.
