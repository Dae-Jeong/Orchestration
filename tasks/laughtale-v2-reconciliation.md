# Laughtale V2 상태 대조와 후속 작업 구성

Status: 배정·실행·PM 검토 완료 · 2026-09-10

## 목표

사용자의 PM 조율·실행 요청에 따라 Laughtale 기존 세션에 V2 상태 정리와 task 분해를
배정한다. 제품 구현이나 부하 재실행이 아니라 코드·기존 증거의 대조와 작업 계획이 범위다.

## 계약 · LAUGH-V2-RECON-001 / revision 1

- 실행자: 기존 Laughtale Codex 세션. PM은 orchestration 세션에서 배정·검증·보드를 소유한다.
- 허용 쓰기: Laughtale `tasks/linky-chat-internal-dm.md`, `tasks/README.md`만.
- 보존: 과거 실험·실패·승인 이력과 기존 dirty 변경. 제품 코드·DB·배포·부하·디자인 변경 금지.
- 실행 한도: 문서 대조 1회, 15분. 추가 agent·외부 API 실행·commit/push 금지.
- 종료: 근거가 부족한 항목은 unknown으로 남기고 PM에 보고한다. timeout으로 중복 실행하지 않는다.

| 기준 | 예상 결과 | 검증 |
| --- | --- | --- |
| C1 | 예전 V2 미구현 표기와 현재 상태의 범위·시점이 구분됨 | PM diff·원문 대조 |
| C2 | 구현/검증/실패/미검증을 코드·시험·기존 기록 경로로 구분한 표가 있음 | PM 대표 코드·기록 표본 확인 |
| C3 | 최대 6개 후속 task에 stable ID·입출력·수용 조건·검증자·depends_on·공유 자원·권한 상태가 있음 | PM 의존성·범위 검토 |
| C4 | 실제 Orca 성공/실패 receipt와 Paperclip 상태·후속 후보가 연결됨 | PM CLI/API 대조 |

후속 기준·수치가 새로 필요한 것은 proposed로 표시한다. 기존 승인도 범위별 근거를 연결하며,
후속 후보 작성이 자동 실행 허가는 아니다. hash는 이 계약의 revision·기준·권한을 담은
로컬 매핑으로 연결하고 실행 순서와 분리한다.

## 진행

기존 Laughtale 조율 세션이 PM 창구 알림을 확인하고 idle로 돌아온 transcript를 확인했다.
이전 Run의 두 worker는 completed/released다. 이전 Run을 강제 takeover하지 않고
이번 bounded 작업의 새로운 Run/Dispatch로 배정한다. 기존 터미널은 사용자 세션이므로 유지한다.

Paperclip: ORC-10, Laughtale 프로젝트. criteria_hash:
`8c3833d6b86c2c28c6e758bb2124de0a2a4445cc410d2b090a2cd102b26a0e59`.
기존 세션에 current worker-start 입력 수락 receipt를 확인했다. 실제 완료 판정은
worker settlement와 PM 검토 후 기록한다. 실행 매핑은 ignored 로컬 파일에만 보존한다.

실행자가 다른 검토 세션의 쓰기 상태를 질문해 PM이 Orca tui-idle을 확인하고 두 문서의
writer를 지정했다. 이전 coordinator였던 터미널을 worker로 재사용하면 기본 check가
옛 Run을 가리키는 제약이 관찰됐다. 옛 inbox는 추가 소비하지 않고 비소비 조회로 제한했으며,
이번 preamble의 ask/reply는 현재 Run에 도착함을 확인했다. 기존 Run takeover·프로세스 재시작은
하지 않았다. 새 작업에 기존 coordinator를 재사용할 때의 메시지 경로는 자동으로 안전하다고
가정하지 않는다. 다음 작업은 이 제약을 피할 실행 배치를 선택한다.

PM 초안 검토에서 성능·확장 후보 외에 제품 경로/브라우저·세션 폐기 목표가 빠질 수 있음을
발견해 여섯 번째 후보 보완을 실행자에게 요청했다. 제품 문서는 실행자가 수정하고 PM이
검토한다. PM은 MessageOutbox 저장·SharedSessions·Fanout 코드를 표본 확인했으며,
대표 기존 E2E 원장에서 correct=true / pass=false / browser_verified=false와
ACK p99 약0.843초·WS p99 약1.722초를 직접 대조했다. 새 실험은 수행하지 않았다.

## 결과

기존 Laughtale Codex 세션의 성공 worker_done을 수신했고 지정된 두 task 문서의
현재 상태·후속 계약을 PM이 검토했다. C1–C3 pass, ORC-10 완료 및 후속 native blocker
재조회로 C4 pass다. 문서 작성과 PM 검토는 별도 세션이며 전체 제품 QA 재실행은 아니다.
새 상태 절의 상대 링크 누락 0개, 실행자의 diff whitespace 검사 통과를 확인했다.

| 업무판 | stable task | 후속 후보 |
| --- | --- | --- |
| ORC-12 | LAUGH-V2-EVIDENCE-001 | 소스·실험 이미지·원장의 증거 기준선 |
| ORC-13 | LAUGH-V2-PATH-001 | 실행 버전·진입 경로 분리 |
| ORC-14 | LAUGH-V2-LATENCY-001 | 단일 변수 지연 진단 |
| ORC-15 | LAUGH-V2-SCALE-001 | 미완료 증설 검증 재개 |
| ORC-16 | LAUGH-V2-CAPACITY-001 | 대용량 시험 재개 판단 |
| ORC-17 | LAUGH-V2-PRODUCT-001 | 실제 브라우저·세션 폐기 검증 |

모두 backlog/proposed이며 실제 후속 실행은 하지 않았다. 후보별 revision 1과 별도 hash를
부여해 로컬 매핑과 업무판에 연결했고, 번호/hash로 순서를 정하지 않았다.
증거 기준선→경로→지연→증설/대용량의 native blocker를 재조회했다. 제품 후보는 증거 기준선에
의존하며 실제 브라우저 실행 전 PATH의 진입 준비를 PM이 추가 확인한다. 이 조건과 공유 자원
배타 실행은 coordinator 관행이며 자동 resource lock을 구현한 것은 아니다.

첫 권장 작업은 ORC-12다. 파일과 기존 원장만으로 재사용할 증거와 unknown을 한정하고,
이후 필요한 재시험을 정한다. 이미 수행한 대조 전체를 반복하거나 모든 unknown 해소를 요구하지 않는다.
제품 구현·부하·DB·배포를 새로 수행하지 않았고 Laughtale dirty 변경은 commit/push하지 않았다.
기존 사용자 세션은 worker-release가 external_terminal/retained로 확인했으며 그대로 유지했다.
이번 Run의 reclaimable worker는 0개다. 다음 실제 배정에서는 기존 coordinator의 inbox 혼동을
피할 worker 전용 세션 또는 확인된 메시지 경로를 사용한다.
