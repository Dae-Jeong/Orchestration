# 첫 실제 시범 독립 QA

Status: QA 1회 검토 완료 · 2026-09-10 · C1–C3 pass, 비차단 개선 3건

계약: **ORCH-LIVE-001 / revision 1**. 전달받은 `criteria_hash`:
`b628898a7fb212a33bd806eff31c71a3f254181304192fe4940bf6f22a2c5fa2`.
[시범 계약](first-live-pilot.md)의 C1–C3 문구를 원본으로 대조했다. 로컬 계약 JSON의
hash 재계산과 Paperclip 연결 검증은 수행하지 않았으며 C4 담당 PM에게 남긴다.

## 검증자·범위·독립성

검증자: 이번 시범에 별도로 배정된 Codex QA worker. 검토 대상의 작성·수정에
참여하지 않고 원본 문서·실제 명령 결과·PNG를 직접 확인했다. **검토 대상에 대한
self-review가 아니다.** 이 QA 보고서 자체는 작성자가 확인했으며 별도 검증되지 않았다.
동일 모델 여부는 독립성 근거로 삼지 않았고 실제 모델 설정·비용은 측정하지 않았다.

검토 기준점: Git HEAD `e4625bd` 위의 작업 트리. 시작 시 README 수정과
`tasks/first-live-pilot.md` 신규 파일이 이미 있었으며 기존 변경을 보존했다.
이 worker가 작성한 파일은 이 보고서뿐이다. 테스트는 `Darwin arm64`, Python 3.13.2에서
수행했다. 설치 재실행·브라우저 탐색·네트워크 조사·DB/Paperclip 변경은 하지 않았다.

범위: README, 상세 HTML, PNG, 운영/설치/성과 문서, squad-model의 역할·PM·도구·루프·v1 계약,
시범/시각화 기록 대조와 로컬 링크 존재 검사. 외부 Product Workflow 정본은 이 검토에서
읽었다고 주장하지 않으며 전달된 명시적 계약을 적용했다.

## 기준별 판정

| 기준 | 판정 | 기대 / 실제 및 정확한 근거 |
| --- | --- | --- |
| C1 | **pass** | README 19–25행에 PM·기획·디자인·개발·QA·마케팅·HR 7개 역할이 있고 사용자 행은 별도다. 역할·인계·모델 후보는 `docs/operating-model.md`의 역할 표와 `skills/squad-model/references/roles.md` 각 역할 절에 일치한다. README 23·27행은 초기 QA와 self-review 표시, 34행은 선행 검증/자원 충돌 조건, 49–54행은 PM/Paperclip/Orca/repo 책임, 58–64행은 공동 HR 리뷰와 미활성 루프를 명시한다. `pm-flow.md`, `execution-tools.md`, `review-loop.md`, `docs/role-performance.md`와 대조해 현재 책임 계약의 불일치를 발견하지 않았다. |
| C2 | **pass** | README의 상대 링크/이미지 참조 11개 모두 존재한다(중복 참조 포함). 상세 HTML의 로컬 href 6개와 해당 HTML anchor도 모두 존재한다. PNG는 실제 디코딩·시각 확인했으며 3200×2760이다. README 73–78행의 설치 검증/디자인 인증 미완료/제품 수행 미검증/루프 미활성 구분은 `docs/local-setup.md`와 `tasks/paperclip-pilot.md` 기록에 부합한다. 82–93행의 도구·외부 workflow·DB/환경 선행 준비·clone 제한도 설치 가이드와 일치한다. 설치 실동작이나 현재 인증 상태를 새로 검증한 판정은 아니다. 아래 비차단 표현 개선은 남아 있다. |
| C3 | **pass** | 실제 계약 검사 결과 `5 contracts valid; no work dispatched`, unit tests 5개 모두 `ok`, 최종 `OK`. `git diff HEAD -- examples/pilot.json` 출력 없음, 이어 `git diff --exit-code HEAD -- examples/pilot.json`도 차이 없음. fixture는 검토 시 HEAD와 동일하다. |
| C4 | **unknown · 담당 범위 밖** | Paperclip issue 상태와 Orca dispatch/settlement의 전체 증거 연결은 PM 소유다. 이 QA의 성공 보고를 C4 통과로 취급하지 않는다. |
| C5 | **unknown · 후속 범위** | HR 리뷰는 QA 이후 예정되어 있다. 아직 없는 HR 보고서/링크를 결함으로 판정하지 않았으며 HR 리뷰 또는 개선 효과 완료를 주장하지 않는다. |

## 실제 실행·링크·이미지 증거

```text
python3 scripts/check-contracts.py examples/pilot.json
5 contracts valid; no work dispatched

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
test_agreement_requires_receipt ... ok
test_changed_authority_invalidates_hash ... ok
test_cycle_and_missing_dependency_rejected ... ok
test_prior_evidence_invalid_after_revision ... ok
test_valid_fork_and_join ... ok
Ran 5 tests in 0.001s
OK

git diff HEAD -- examples/pilot.json
(출력 없음)
git diff --exit-code HEAD -- examples/pilot.json
(출력 없음)
git diff --check
(출력 없음)
```

bytecode 파일 생성을 막는 환경 변수만 추가했다. 테스트는 v1 레코드·순환/누락 의존성·권한
변경 hash·기준 변경 후 증거·합의 receipt를 검사한다. 실제 scheduler, worker 판단 품질,
외부 효과, resource lock 또는 신규 7개 역할 runtime을 검사하지 않는다.

읽기 전용 Python 검사로 Markdown inline 상대 링크와 HTML href/src를 추출해 대상 파일 존재를
확인했다. README 11개, operating-model 4개, local-setup 15개, squad-model SKILL 7개,
reference 8개 파일의 합계 15개, 상세 HTML 6개에서 누락 0개였다. role-performance의 상대
링크는 0개다. Markdown anchor 렌더 규칙, 외부 URL 응답, 연결된 모든 문서의 재귀 탐색은
검사 범위가 아니다.

PNG 직접 보기에서 상단 사용자/맥락/도구 → PM → 실행 역할 → QA → HR/제품 성과와
귀환선을 확인했다. 보이는 텍스트·노드의 잘림이나 중첩은 발견하지 않았다. HTML SVG의
역할·라벨·배치와 육안으로 일치한다. 원본 이미지는 확대 링크로 접근할 수 있다.
브라우저 탐색 금지 범위에 따라 현재 README/HTML의 실제 PC·모바일 viewport 렌더,
좁은 README 화면의 작은 글자 가독성, 픽셀 단위 HTML/PNG 동일성은 **미검증**이다.

검토 산출물 SHA-256:

| 파일 | SHA-256 |
| --- | --- |
| `README.md` | `bcd48da0e8a9e11cff6e37bc87d990ecff2ccb8aed893191179f61080f83fe7c` |
| `tasks/model-process.html` | `68ee108d4e8bfd51b90d7b890da944fdcec188a35630c5dae6b765963006a640` |
| `docs/images/model-process.png` | `9d6af9e19557be4d9dae2504842f0dc9f809b6f5c86b6db5746d889820afe94c` |
| `examples/pilot.json` | `46053f14febdd92e1c75d1872228fc2e83ca75fbe8ac27be0830f4bca594eb29` |

## 비차단 개선과 귀환 대상

1. **PM / v1 도식의 실행 도구 표기:** `skills/squad-model/references/model.md` Mermaid의
   `E[Paperclip execution]`은 현재 `execution-tools.md`의 Orca 실행 소유와 다르다.
   v1 설치 pilot 문맥으로 읽을 수 있어 README C1 실패로 처리하지 않았지만, 현재 운영
   설명으로 재사용할 때 오해할 수 있다. 도식을 역사적 Paperclip pilot로 명시하거나
   현재 도구 계약을 참조하는 중립적 실행 라벨로 바꾸고 v1 fixture는 보존할 것을 제안한다.
2. **PM / 상세 HTML의 executor 상태 범위:** `tasks/model-process.html` 129행의
   “별도 PM·개발·QA executor나 자동 역할 배정은 아직 구성하지 않았습니다”는
   Paperclip 설정 문단 안에 있지만, README 68–69행의 별도 Orca QA 시범과 함께 읽으면
   전체 도구에서 executor가 없다는 뜻으로 오해할 수 있다. “Paperclip 상시 역할 agent”와
   “이번 Orca 단발 QA 시범”을 구분하고 시범 계약을 링크할 것을 제안한다. 자동 배정이
   구현됐다는 근거는 없으며 그렇게 수정해서는 안 된다.
3. **PM / PNG의 독립 문맥:** PNG 하단의 “세부 양방향 인계는 아래 표”는 HTML 74행에서
   가져온 표현이다. PNG 자체에는 아래 표가 없고 README 바로 아래 역할 표도 상세
   양방향 인계 표가 아니다. “상세 HTML의 인계 표 참조”로 고치고 이미지를 재생성하면
   확대 이미지에서도 안내가 정확해진다. 현재 상세 HTML 링크는 정상이라 탐색을 막지는 않는다.

## 남은 일

- [x] 독립 원본 대조·C1–C3 판정·테스트·fixture diff·로컬 링크·PNG 확인.
- [x] 대상 문서를 변경하지 않고 이 보고서만 작성.
- [ ] PM이 비차단 개선 채택 여부를 결정하고 변경 시 해당 증거를 재확인.
- [ ] PM의 C4 연결 검증 및 후속 HR의 C5 리뷰.

표본은 문서 작업 1회다. 이번 결과로 전체 역할의 전문 품질, 제품 성과, 무인 반복 운영,
모델 적합성·비용·개선의 인과 효과를 일반화할 수 없다.
