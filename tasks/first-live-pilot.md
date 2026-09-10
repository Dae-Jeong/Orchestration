# 첫 실제 오케스트레이션 시범

Status: 실행·검증 완료 · 2026-09-10

## 목표와 승인 범위

사용자 요청: README를 새 전체 업무 흐름에 맞추고 실제로 한 번 실행해 보기.
이번 소재는 이 repo의 README 정합성이다. 제품 개발/디자인/마케팅을 억지로 실행하지 않는다.
현재 세션이 PM·문서 편집을 맡고, 별도 Orca Codex worker가 QA, 후속 worker가 HR 관점으로 리뷰한다.
ChatGPT 로그인 기반 기존 Codex 실행을 사용한다. 별도 유료 API·광고·외부 연락·배포·스케줄은 제외.

## 계약 · ORCH-LIVE-001 / revision 1

- 허용 변경: README, 이 task 및 시범 리뷰 문서. PM은 검증된 수정·commit/push를 소유.
- QA 소유: tasks/first-live-qa.md만 작성. 검토 대상 파일은 변경하지 않는다.
- HR 소유: tasks/first-live-hr.md만 작성. QA 결과 이후 시작하고 개선안·측정 한계를 제시한다.
- 동시 쓰기: 역할별 파일 분리. QA 검토 중 README는 PM도 변경하지 않는다.
- 실행 한도: QA 1회 + HR 1회, 필요한 수정 재검증 최대 1회; 각 worker 10분을 작업 한도로 전달.
  초과/환경 장애는 사실을 보존하고 판단 요청. timeout만으로 중복 실행하거나 종료하지 않는다.
- 모델: 사용자가 설정한 Orca Codex 기본값. 실제 receipt/관찰로 확인되는 값만 기록.
- 비용: 기존 로그인 사용, 정확한 사용 비용은 관측 전 unknown. 무료 실행으로 주장하지 않는다.

| 기준 | 관찰 가능한 완료 조건 | 검증 담당/방법 |
| --- | --- | --- |
| C1 | README에 7개 실행/운영 역할과 PM·도구·QA·HR 흐름이 현재 reference와 일치 | QA 원본 대조 |
| C2 | 이미지·상대 링크가 존재하고 설치/준비 조건·미활성 상태를 과장하지 않음 | QA 링크/이미지·설치 문서 대조 |
| C3 | 기존 v1 계약 5개 검사와 unit tests 통과, fixture 미변경 | QA 실제 실행·diff |
| C4 | Paperclip issue 상태와 Orca 실제 dispatch/settlement·검증 증거 연결 | PM API/receipt 확인 |
| C5 | HR 리뷰가 관찰·원인 가설·개선안·효과 확인법·표본 한계를 제공 | PM 직접 검토 |

계약 hash는 위 C1~C5와 권한·자원·한도를 담은 로컬 계약 JSON을 정렬 직렬화해 계산하고
Paperclip 설명과 실행 spec에 연결한다. v1 샘플 JSON은 이 시범의 실행 허가가 아니다.

## 진행·검증

계약 SHA-256: `b628898a7fb212a33bd806eff31c71a3f254181304192fe4940bf6f22a2c5fa2`.
Paperclip: ORC-7(전체) / ORC-8(QA) / ORC-9(HR, QA를 native blocker로 연결).
보드 담당자는 local-board이며 실제 실행 worker는 Orca에서 연결한다.

첫 worker-start는 Codex 업데이트 안내로 입력 단계에서 실패했다. 작업이 실행되지 않은
receipt를 확인하고 해당 worker를 공식 release로 정리했다. 새 터미널에서 안내의 Skip을
선택하고 tui-idle을 확인한 뒤, 동일 Orca Task에 retry-of로 새 Dispatch를 연결했다.
Codex 0.153.4, ChatGPT 로그인, 실제 worker projection에서 gpt-6-astra 확인.
기존 launcher의 권한 설정은 변경하지 않았으며 추가 sandbox bypass 플래그도 사용하지 않았다.
시작 장애는 역할 수행 실패와 분리한다. native 상태 변경 시 owner 요구를 충족했으며
실행 준비 장애는 comment로 기록했다. HR의 blockedBy 관계를 API에서 확인했다.

- [x] README와 역할/도구 계약·현재 서버 확인.
- [x] 실제 QA dispatch·settlement·판정 확인.
- [x] QA 후 HR dispatch·settlement·리뷰 검토.
- [x] Paperclip 상태·증거 반영, worker 정리.
- 원격 반영: 이 기록을 포함한 Git commit과 origin/main 이력으로 확인한다.

제품 성과, 전체 7개 역할의 실전 품질, Pencil/UIBowl 실제 디자인 수행, 무인 반복 운영은
이번 문서 시범으로 검증되지 않는다. 상세 실행 ID·handle은 로컬 매핑에 보존한다.

### QA 완료와 수정

별도 QA의 성공 settlement를 coordinator가 수신하고 원본 보고서를 검토했다.
[QA 보고서](first-live-qa.md)의 C1–C3은 pass다. ORC-8을 done으로 반영한 뒤
후속 HR을 실행했다. 기존 QA 증거는 수정 전 기준점으로 보존한다.
비차단 개선 3건(중립적 실행 도구 표기, Paperclip 상시 agent와 Orca 단발 실행 구분,
PNG의 상세 HTML 안내)을 PM이 채택했다. 변경분은 PM 자가 검증이며 독립 재검증은 아니다.
HTML에서 PNG를 재생성하고 직접 시각 확인했다. v1 fixture는 변경하지 않았다.

PM 변경분 확인: README·HTML의 상대 링크 누락 0개, `git diff --check` 통과,
v1 fixture SHA-256은 QA 기준점과 동일하다. 로컬 계약 JSON을 재계산해 위 hash와
일치함을 확인했다. HR이 문서의 QA 완료 체크 지연을 발견해 착수 조건을 질문했고,
PM이 실제 settlement·보고서 판정과 ORC-8 완료를 근거로 답한 뒤 리뷰를 재개했다.
질문/응답도 실제 인계 검증에 포함한다. 자동 기록 동기화가 검증된 것은 아니다.

### HR 검토와 최종 판정

[HR 보고서](first-live-hr.md)를 PM이 직접 검토했다. 관찰과 원인 가설, 담당·검증법이
있는 개선안 2개, 표본·비용·제품 성과의 한계가 있어 **C5 pass**로 판정했다.
두 worker 모두 실제 projection은 gpt-6-astra였으며 별도 모델 override는 하지 않았다.
보고서의 미완료 항목은 작성 당시 상태로 보존하고, 이 절에서 후속 처리를 기록한다.

- 준비 확인: 다음 승인된 단발 실행에서 입력 가능 상태와 시작 receipt를 함께 남기는
  개선 후보로 채택한다. 자동 업데이트나 새 상시 실행 정책은 만들지 않았다.
- 인계 정합성: 이번 QA 완료 체크·Paperclip 상태·후속 착수 확인과 표현 3건 수정을
  반영했다. 다음 실행의 확인 질문·준비 장애 재발을 관찰해야 하며 효과는 아직 unknown이다.

**C1–C3:** 독립 QA pass. 표현 수정과 최종 README 상태 갱신은 PM 자가 검증으로 구분한다.
**C4:** QA·HR 성공 settlement, native 선행 blocker, 질문/회신, 각 issue 상태와
보고서 연결을 PM이 대조했다. 계약 hash는 동일하며 실행 ID 매핑은 로컬에만 보존한다.
QA·HR 터미널은 성공 후 idle을 확인하고 이번 시범에서 만든 정확한 대상만 정리했다.
최종 API 재조회에서 ORC-7·8·9가 모두 done이고 HR의 QA blocker도 done임을 확인했다.
Orca의 reclaimable worker는 0개다. 미리 준비한 두 터미널은 external로 기록되어
worker-release가 retained를 반환했으므로, 정착·idle 확인 후 정확한 handle로 닫았다.
첫 시작 실패 1회는 실제 QA 수행과 구분하며, 별도 수정 재검증 worker는 실행하지 않았다.

문서 납품과 1회 인계 루프는 완료다. 자동 강제·여러 제품 운용·HR 개선 효과·정기 실행은
이 결과의 범위가 아니다. Paperclip 접속/중지 방법은 README와 설치 가이드에 유지한다.
