# Orchestration

AI 세션으로 제품 작업을 진행하고, 그 맥락을 Obsidian에 모아 이어가는 운영 구조다. **Task 하나 + 담당 세션 하나**를 기본으로, 목표·완료 조건·현재 결과·다음 행동을 같은 Task에 남긴다.

담당 세션이 조율과 실행을 함께 맡는다. 독립적으로 나눌 이득이 있을 때만 추가 세션을 활용하고, 최종 결과는 담당 세션이 확인한다.

## 동작 흐름

[![Task 중심 실행: 인수 → 실행 → 검증 → 기록](docs/images/task-session-flow.png)](docs/images/task-session-flow.png)

[SVG 원본](docs/images/task-session-flow.svg)

1. **인수** — 기존 Task와 실제 파일, 현재 담당을 확인한다. 새 업무라면 요청을 받은 세션이 목표·범위·완료 조건을 작성한다.
2. **실행** — 제품 repo에서 작업한다. 분담이 필요하면 작업 범위와 담당을 정하고 산출물·검증 근거를 돌려받는다.
3. **검증** — 처음 정한 완료 조건으로 결과를 확인한다. 목표나 변경 영향에 맞는 성능 지표도 필요한 경우 함께 측정한다.
4. **기록** — 같은 Task에 현재 결과·증거·다음 행동을 갱신한다. 다음 세션은 이 기록과 실제 파일을 대조해 남은 일을 이어간다.

## 완료 조건과 성능 측정

완료 조건은 **그 Task가 달성하려는 결과**다. BE·FE 지표를 모든 작업의 공통 통과 기준으로 적용하지 않는다.

| 작업 예시 | 완료를 확인할 근거 | 함께 살펴볼 측정 |
| --- | --- | --- |
| DB 쿼리 성능 개선 | 결과·권한 유지, 같은 조건에서 전후 성능 개선 확인 | 쿼리 시간·실행 계획·쿼리 수 |
| 화면 로딩 개선 | 목표 화면의 로딩 개선과 기능 유지 | LCP·요청 수·번들 크기 중 관련 항목 |
| 문구·단순 UI 수정 | 요청한 표현·동작·레이아웃 확인 | 성능 영향이 없으면 생략 |

성능 개선 자체가 목표이면 측정이 목표 달성의 근거가 된다. 그 외 추가 측정은 영향과 후속 개선을 판단하는 자료로 기록한다. [측정 선택·해석 기준](docs/engineering-measurement.md)

## 구성

| 구성 | 역할 |
| --- | --- |
| Obsidian Task | 업무 상태의 정본. 목표·담당·완료 조건·현재 결과·다음 행동 |
| 제품 repo · Agent | 코드·설계·검증 산출물이 있는 실제 작업 공간과 실행자 |
| Harness · Log | 관측된 변경을 세션·Task·증거에 연결하고 변경 이력을 보존 |
| Orca · 선택 | 추가 세션 실행과 결과 전달. 업무 상태는 중앙 Task에 연결 |

현재 상태는 Task, 산출물은 제품 repo, 변경 이력은 Log에 둔다. 별도 보드나 진행 문서에 같은 상태를 중복 관리하지 않는다.

## 시작하기

대상 repo에서 세션을 열고 `AGENTS.md`와 기존 Task·담당을 확인한 뒤 목표를 전달한다.

> 목록 쿼리를 개선해줘. 결과·권한은 유지하고 전후 시간을 비교해줘.

세션을 바꿀 때는 같은 Task를 지정해 이어가도록 요청한다. 새 세션은 이전 작업자의 종료·인수 가능 상태와 남은 변경을 확인한다. Task 갱신만으로 새 세션이 자동 실행되지는 않는다.

중앙 wiki·harness는 외부 환경이다. clone에 포함되지 않으며 [설정 안내 · 로컬 의존성](docs/external-dependencies.md#local-1)를 따른다. 중앙 vault에서 프로젝트를 조회할 수 있다.

```sh
uv run python -m harness context /absolute/product/repo
```

## 검증 범위

별도 세션이 같은 Task를 읽고 작업을 인수해 수정·검증·기록하는 흐름을 실제로 확인했다. 중단·기록 재시도·동시 변경 판정은 격리된 회귀 시험으로 확인했다.

자동 배정·자동 재개와 동시 쓰기 잠금은 제공하지 않는다. 세션 종료나 문서 검사 통과만으로 제품 작업의 완료를 판단하지 않는다. [검증 결과와 한계 · 로컬 의존성](docs/external-dependencies.md#local-2)

## 저장소 구성

- `docs/` — 현재 운영 모델, 측정 기준, 가상 사례와 외부 방식 비교
- `docs/images/task-session-flow.*` — README 구성도와 편집 가능한 SVG 원본
- `skills/squad-model/`, `scripts/`, `examples/`, `tests/` — 이전 역할·계약 중심 실험과 검증 도구

Paperclip 관련 스크립트와 npm 의존성은 이전 실험용으로 보존한다. 현재 Task·세션 모델을 읽고 적용하는 데 Paperclip 설치는 필요하지 않다. 중앙 wiki·harness 연결은 [외부 환경 안내](docs/external-dependencies.md)를 참고한다.

## 상세 문서

[운영 모델](docs/task-session-model.md) · [BE·FE 측정 기준](docs/engineering-measurement.md) · [가상 사례](docs/engineering-measurement-simulation.md) · [기록·복구 · 로컬 의존성](docs/external-dependencies.md#local-3) · [외부 방식 비교](docs/orchestration-patterns.md)
