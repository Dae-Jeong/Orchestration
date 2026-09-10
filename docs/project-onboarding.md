# 프로젝트 연결과 사용

현재 하나의 Paperclip 회사에 제품별 프로젝트를 나누고, 각 제품의 기존 Orca workspace를
연결한다. 프로젝트를 등록하면 PM이 사용할 목적지가 생기며, agent가 자동으로 기동되지는 않는다.

| 제품 | 프로젝트 진입 문서 | 제품 내 정본 |
| --- | --- | --- |
| Laughtale | `workspace:laughtale/docs/orchestration.md` | README → docs router → 해당 named task·서비스 계약 |
| Dae-Jeong | `workspace:Dae-Jeong/wiki/context/orchestration.md` | context manifest → product hub → profile/evidence·기존 skill |

각 AGENTS가 위 진입 문서로 연결한다. 공통 모델은 이 repo의 `skills/squad-model/SKILL.md`를
고정 버전으로 참조하며 복제하지 않는다. 이 연결은 Codex의 자동 skill 등록과 별개다.
PM은 진입 문서를 통해 명시적으로 읽는다. 새 worker에서도 실제 읽기·도구 준비를 확인한다.

## 사용

해당 프로젝트의 세션에서 다음처럼 소재를 전달한다.

> 이 프로젝트 PM으로 오케스트레이션 진입 문서를 읽고, 이 소재를 기존 작업과 대조해
> 필요한 역할·완료 조건·검증 방법을 정하고 승인 범위 안에서 진행해줘: …

중앙 세션에서도 제품명을 지정해 같은 요청을 할 수 있다. PM은 대상 repo와 활성 담당자를
먼저 확인하고 Paperclip issue에 projectId를 지정한다. 세부 작업은 제품 정본에 남긴다.
한 제품의 기준·예산·DB·디자인 원본을 다른 제품에 자동 상속하지 않는다.
진행 중인 작업을 일괄 복사하거나 다른 PM 세션에 소유권 확인 없이 지시하지 않는다.

## 로컬 연결

각 제품의 ignored `.local/source-roots.yaml`에서 `roots.workspace`와 `roots.wiki`를
설정한다. `workspace:<repo>`는 workspace root 아래 repo, `wiki:<document>`는 wiki root
아래 문서다. `.local/orchestration.json`은 모델 채택 버전과 Paperclip·Orca 식별자만 보관한다.
런타임 식별자는 실행 전 재조회하며 다른 머신에서는 등록 후 새 값을 설정한다.

새 clone은 이 private 모델 repo 접근 권한, 채택 버전 checkout, 운영자 global wiki와
제품별 도구 준비가 필요하다. model checkout이 채택 버전과 다르면 차이를 검토하거나
채택 버전을 따로 준비한다. 모델 본문 변경을 소비 repo에 자동 적용하지 않는다.

현재 두 프로젝트는 `planned`, workspace runtime은 `manual`, Paperclip execution workspace
policy는 비활성으로 등록했다. 실제 실행 조율은 PM이 Orca를 호출한다. 자체 scheduler,
자동 동기화, 상시 역할 agent, 정기 HR 리뷰는 활성화하지 않았다.
