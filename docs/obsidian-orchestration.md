# Obsidian + Orchestration

Obsidian의 로컬 LLM Wiki를 공통 입구로 사용하고 이 프로젝트의 실행 모델을 연결한다.
머신별 경로는 Git-ignored `AGENTS.local.md`가 소유한다.

| 구성 | 소유하는 것 |
| --- | --- |
| Obsidian / LLM Wiki | 프로젝트 맥락·출처 지도·검증된 결과의 연결 |
| Orchestration | 작업 범위·역할 배정·검증과 인계 절차 |
| Paperclip | 업무 상태·담당·검증 증거 연결 |
| Orca | 실제 agent 실행과 실행 시도의 상태 |
| 제품 repo | 코드·제품별 결정·상세 검증 근거 |

PM은 위키의 `wiki/index.md`에서 관련 영역을 찾고, 해당 `index.md`를
따라 원문을 읽는다. 탐색 경로가 부족하면 관련 폴더를 파일·본문 검색한다.

관련 원본과 실제 상태를 확인한 뒤 기존
[Squad Model](../skills/squad-model/SKILL.md)로 작업한다. 검증 후 원본 보고서를 보존하고
위키의 `wiki/projects/<product>/reviews/`에 결과·출처·확인 시점·적용 한계·남은 일을 기록하고
해당 제품의 `index.md`에서 연결한다. 기존 작업은 `tasks/`의 같은 문서를 갱신한다.

현재 사실·적용 규칙은 해당 정본에 간결하게 유지하고, 임시 조치·중간 판단·변경 과정은
위키의 `wiki/log/`에 필요한 기록만 남긴다. 과거 기록을 현재 상태로 읽지 않도록 출처와 날짜를 구분한다.

작업 기록과 개인 지식은 로컬에 유지한다. 장기 결정·피드백의 정본은 글로벌 규칙이 정한
owner를 따른다.

agent가 문서를 읽고 실행하며, 담당자가 검증 근거를 확인해 상태와 문서 링크를 갱신한다.
