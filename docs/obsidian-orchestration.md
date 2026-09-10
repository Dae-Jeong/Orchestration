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

PM은 위키에서 관련 원본을 찾고 실제 상태를 확인한 뒤 기존
[Squad Model](../skills/squad-model/SKILL.md)로 작업한다. 검증 후 원본 보고서를 보존하고
위키의 Results에 결과·출처·확인 시점·적용 한계·남은 일을 연결한다.

작업 기록과 개인 지식은 로컬에 유지한다. 장기 결정·피드백의 정본은 글로벌 규칙이 정한
기존 owner를 따르며 위키가 별도 복제 정본을 만들지 않는다.

현재 연결은 agent가 읽고 수행하는 작업 절차다. 상시 실행·자동 수집·자동 상태 동기화나
두 저장소의 물리적 합병은 구현하지 않았다.
