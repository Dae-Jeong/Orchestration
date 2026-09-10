# Personal Orchestration

여러 제품의 업무를 PM 중심으로 배정하고, 기획·디자인·개발·QA의 인계와 완료 기준을 관리하는 개인 오케스트레이션 모델입니다.

**PM이 조율하고, Paperclip에 업무를 기록하고, Orca에서 실행합니다.** 역할과 작업 계약은 도구와 분리합니다.

![통합 업무 흐름](docs/images/model-process.png)

[이미지 확대](docs/images/model-process.png) · [역할과 업무 프로세스](docs/operating-model.md)

## 현재 상태

- **검증 완료:** Paperclip 로컬 설치·UI·재시작 후 상태 보존, 샘플 계약 5개 검사.
- **구성 완료:** 역할별 지침·완료 기준·인계 계약.
- **미검증:** 실제 제품을 수행하는 다중 agent 팀·자동 역할 배정.
- **미활성:** 주기 실행 루프. 디자인 도구는 Pencil 연결 확인, UIBowl 인증 미완료.

## 시작하기

설정된 로컬 환경에서:

```sh
./scripts/paperclip run --no-repair
```

접속: <http://127.0.0.1:13100/ORC/issues> · 중지: 서버 터미널에서 `Ctrl-C`

처음 설치한다면 [로컬 설치 가이드](docs/local-setup.md)를 따릅니다.
기존 PostgreSQL과 운영자의 공통 workflow 문서가 필요하며, clone만으로 모든 환경이 구성되지는 않습니다.

## 문서

| 문서 | 내용 |
| --- | --- |
| [운영 모델](docs/operating-model.md) | 역할·모델 후보, 업무 순서, 여러 제품과 도구의 책임 |
| [재사용 skill](skills/squad-model/SKILL.md) | 작업 계약·역할 지침·완료 및 인계 기준 |
| [설치·검증](docs/local-setup.md) | 요구 환경, DB 구성, 실행 명령, 도구 연결과 한계 |
| [샘플 계약](examples/pilot.json) | v1 모델의 제안 작업 5개 |
| [작업 기록](tasks/personal-model.md) | 결정과 검증 근거 |
