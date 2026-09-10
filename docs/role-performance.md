# 역할 성과와 HR 리뷰

상태: 2026-09-10 운영 설계. 역할 계약과 도식에 반영했으며 실제 측정·자동 리뷰는 미실행.
HR은 AI agent의 역량·온보딩·준비 상태와 리뷰를 관리한다. 사람 채용·인사 평가는 범위 밖이다.

## 책임과 흐름

PM이 제품별 목표·작업을 배정 → 각 역할과 QA가 증거 기록 → HR이 PM·QA·해당 역할과
리뷰 → PM이 개선 작업 배정 → QA가 재검증 → HR이 효과 추적.
HR 자체 개선의 효과는 PM·사용자가 검토한다. HR이 모든 전문 판정을 단독 채점하지 않는다.
제품 공통 맥락: 사용자·문제·현재 기능·근거·이번 목표·repo/원본·권한. PM이 연결하고
역할이 원본을 확인한다. HR은 해당 지침·도구 접근과 준비 여부를 확인한다.

## 지표 후보

| 역할 | 산출물·과정 | 결과·효과 |
| --- | --- | --- |
| PM | 계약 누락으로 생긴 대기·재작업, 근거 있는 우선순위 | 합의한 제품 목표와 후속 학습 |
| 기획 | 규칙·상태·예외 누락, 검증 가능한 수용 조건 | 기획 모호성에 따른 후속 수정 |
| 디자인 | 원본·상태·토큰 인계 완전성, 시각 검증 | 사용자 과업 성공·오류·만족도 |
| 개발 | 기준 충족·재현 가능성·회귀 결함 | 제품별 전달 속도·안정성 |
| QA | 중요 기준의 검증 범위, 판정 재현성 | 관찰 기간 내 누락 결함·잔여 위험 |
| 마케팅 | 고객 근거·가설·측정 품질·비용 | 유효 전환·핵심 행동·실험 학습 |
| HR | 온보딩·도구 준비 실패, 근거 있는 개선안 | 반복 문제 재발·개선 전후 효과 |

목표치와 주기는 미정이다. 산출물 완료와 제품 성과는 별도 판정한다. 서로 다른 제품·난도·
작업 유형을 합쳐 순위를 매기지 않는다. 작업 수·속도·발견 결함 수만으로 평가하지 않는다.
DORA는 배포 관찰이 가능한 제품/서비스 단위에서 사용하며 개별 agent 점수로 대체하지 않는다.

## 최소 측정·리뷰 기록

- 대상: project/task ID, criteria revision/hash, 역할·모델·skill/도구 버전.
- 측정: 지표 정의, 분자/분모(해당 시), 관찰 기간, 표본 수, 기준선·목표 또는 미지값.
- 근거: 산출물·기준별 판정·reviewer, 재작업 이유, 실행/대기 시간·실제 비용(알 때만).
- 해석: 제품/산출물/효율 구분, 성공·실패·무효·unknown, 환경/측정 실패와 수행 실패 구분.
- 개선: 관찰 → 원인 가설 → 담당·변경안 → 전후 비교 기준 → 재검토 조건.

비율은 분모와 표본을 함께 보고하고 기준 변경 전후의 결과를 섞지 않는다. 단순 전후 변화는
개선의 인과 증거로 단정하지 않는다. 반복 평가 과제도 코드 검사·모델 평가·사람 검토를
적절히 조합하고 평가자 자체를 점검한다. 비밀·raw 인증/실행 로그는 공유 기록에 넣지 않는다.
기록은 기존 task/증거를 참조하며 v1 JSON enum·5개 fixture를 확장하지 않는다.

## 정기 리뷰 후보

작업 종료 시 기록, 주간 또는 새 증거가 쌓였을 때 공동 리뷰하는 안이다. 확정된 일정은 없다.
새 증거 없으면 종료, 활성 개선 작업은 중복 배정하지 않음. 자동 실행의 시간·비용·재시도
한도는 별도 설정 필요. 지침 변경은 해당 정본 소유 위치에서 수행하며 공통 규칙을 repo로 복제하지 않는다.

## 조사 근거와 적용 경계

- [GitLab calibration](https://handbook.gitlab.com/handbook/engineering/infrastructure-platforms/processes/calibration/): 관리자들과 People Business Partner가 평가를 조정하는 공개 운영 사례.
- [GitLab PM 역량](https://handbook.gitlab.com/handbook/product/product-management/product-cdf-competencies/): KPI와 역량, 주기 시작 시 성공 기준 합의. 위 agent 지표는 이 사례의 그대로인 복제가 아니다.
- [DORA](https://dora.dev/guides/dora-metrics/), [SPACE](https://www.microsoft.com/en-us/research/publication/the-space-of-developer-productivity-theres-more-to-it-than-you-think/): 제품별 전달 성과와 다차원 생산성. 개인 활동량 평가와 구분.
- [HEART 원저자](https://kerryrodden.com/heart): 사용자 경험 측정. 디자이너 개인 점수와 구분.
- [ISTQB CTFL](https://istqb.org/wp-content/uploads/2024/11/ISTQB_CTFL_Syllabus_v4.0.1.pdf): 위험·커버리지·결함 등 테스트 측정의 참고.
- [GitLab 마케팅](https://handbook.gitlab.com/handbook/enterprise-data/marketing-analytics/dashboards/demand-generation-dashboard/): 접점·유효 리드·영업 기회·파이프라인을 연결하는 B2B 사례. 제품에 맞게 전환 정의 필요.
- [Anthropic agent evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents): 반복 평가와 코드·모델·사람 검토 조합.

외부 사례는 공개 문서에서 확인한 범위이며 우리 agent 팀에서의 효과를 검증한 것은 아니다.
