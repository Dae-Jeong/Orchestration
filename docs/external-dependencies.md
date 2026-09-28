# 외부 환경과 로컬 근거

이 저장소는 운영 모델·측정 기준·시각화를 제공한다. 중앙 Obsidian vault와 harness, 개인 작업 기록은 clone에 포함되지 않는다. 아래 경로는 운영자의 vault 기준이며 공개 웹 링크가 아니다. `~`는 운영자의 홈 디렉터리다.

## 사용 전 확인

제품 repo의 `AGENTS.md`, 운영자가 제공한 공통 지침·Task 위치를 확인한다. harness를 사용할 경우 별도 중앙 vault와 CLI 설치가 필요하다. 이 저장소의 `npm install`은 이전 Paperclip 실험 의존성만 설치하며 중앙 harness를 설치하지 않는다.

로컬 연결 정보는 Git에서 제외한 `AGENTS.local.md`에 두고, 제공된 `PRODUCT_WORKFLOW_FILE`이 있으면 원문을 참조한다. 기록을 가져올 수 없는 환경에서는 README의 로컬 검증 주장을 독립 재현했다고 간주하지 않는다.

## 로컬 정본 위치

공개 문서에는 역할과 검증 범위만 설명하며 현재 작업 결과와 실행 이력은 아래 정본에서 관리한다.

<a id="local-1"></a>
### 설정 안내

`docs/harness/document-workflow.md`

<a id="local-2"></a>
### 검증 결과와 한계

`wiki/projects/llm-wiki/tasks/orchestration-patterns.md`

<a id="local-3"></a>
### 기록·복구

`docs/harness/agent-hooks-design.md`

<a id="local-4"></a>
### 공통 작업 규약

`wiki/notes/agents/work-management-policy.md`

<a id="local-5"></a>
### 로컬 QA 근거

`wiki/notes/meta/qa-and-evidence.md`

<a id="local-6"></a>
### 백엔드 신뢰성

`wiki/notes/knowledge/development/backend-reliability.md`

<a id="local-7"></a>
### 컴포넌트 동작 계약

`wiki/notes/knowledge/design/design-systems/component-docs-structure.md`

<a id="local-8"></a>
### Orchestration 스킬 진입점

`~/.agents/skills/orchestration/SKILL.md`

<a id="local-9"></a>
### Orca CLI 스킬 진입점

`~/.agents/skills/orca-cli/SKILL.md`

<a id="local-10"></a>
### 문서 생애주기

`docs/document-lifecycle.md`

<a id="local-11"></a>
### 현재 harness 구현 범위

`wiki/projects/llm-wiki/tasks/shared-task-harness.md`
