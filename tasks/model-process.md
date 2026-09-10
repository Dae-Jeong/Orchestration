# 모델·역할·업무 프로세스 시각화

Status: 구성·시각 검증 완료 · 2026-09-10

사용자 교정: 프로젝트 현황보다 실제 작업의 모델 목록 → 역할 배정 → 업무 인계 순서를
설명하려던 요청이다. 기존 현황 조사는 보존하고 새 시각화의 중심을 실행 모델로 바꾼다.

확인: 호스트 Codex 기본은 gpt-6-astra / medium. 로컬 model cache에는 astra,
5.6-sol/terra/luna, 5.5, 5.3-codex-spark와 reserve/auto-review 항목이 있다.
목록은 사용 자격/성능·비용 실측이 아니다. reserve/auto-review는 역할 executor로 배정하지 않았다.
Paperclip API에는 process Contract Probe와 paused codex_local Design Readiness만 있다.
둘 다 model/reasoningEffort 미지정, heartbeat off. 실제 역할 팀이 있다고 주장하지 않는다.

배정 제안: 총괄/계약 Astra, 기획/디자인 Astra 또는 Sol, 개발 Terra 또는 Sol,
검증은 별도 세션/검증자. 작은 보조 작업 Luna는 후보. 능력 비교 결과나 사용자 합의로
기록하지 않는다. PM·기획·디자인·개발·QA는 model 이름과 다른 역할 계약이다.

업무: intake → 총괄의 프로젝트/범위 조율 → PM·기획·QA의 기준 설계 →
기존 승인 근거와 완료 조건·권한·한도 확정 → 준비된 디자인/개발 → 검증 → 수정/사람 판단
또는 후속 해제 → 제품 성과·새 학습. 디자인 의존 개발은 원본 인계 검증을 기다린다.

산출: [모델·역할·업무 흐름](model-process.html). 새로운 agent 실행/모델 고정/비용 사용은 없음.

검증: Orca browser에서 실제 렌더·snapshot 확인, 모델표·역할별 산출물·인계 화살표와
현재 설정/제안의 구분을 PC screenshot으로 확인했다. 원본 설정/인증은 산출물에 없음.
