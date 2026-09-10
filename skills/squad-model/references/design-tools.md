# 디자인 도구와 개발 인계

[design-entry.md](design-entry.md)는 이 pilot의 일시정지 디자인 executor 진입 지침이다.

확정된 현장 흐름: **UIBowl 레퍼런스 검색 → Pencil 디자인 → FE·QA 인계**.
Laughtale 제작자 인계(2026-09-10)에서 실제 보조 도구는 UIBowl MCP로 확인됐다.
Open Design은 사용하지 않았고 Figma는 초기 호출 제한으로 중단되어 필수 의존성이 아니다.

## 사용 계약

1. UIBowl `search_ui_patterns`로 화면/플로우 레퍼런스를 찾고 출처와 채택·제외 이유를
   기록한다. PC 결과에 AI 채팅이 섞였던 사례처럼 제품 맥락이 다르면 레이아웃 참고로
   범위를 한정한다. UIBowl은 읽기 전용 레퍼런스 DB이며 디자인/코드 생성기가 아니다.
2. Pencil `read_skill()` 후 `execute.md`, `pen-schema.md`와 해당 mobile/web guide를
   읽는다. `.pen`은 암호화되어 파일 Read/rg로 읽지 않는다. 전용 도구의 명시적
   filePath·노드로 대상을 고정하고 다른 작업의 active canvas를 자동 편집하지 않는다.
3. 공유 `.pen` 원본은 writer 충돌 자원이다. 컨셉·피드백·상태·reusable 연결을 만든 뒤
   대상 viewport 렌더와 잘림을 확인한다. 원본 버전/노드/토큰·상태 매핑과 증거를 인계한다.
4. MCP 장애 시 제작자가 검증한 대체 경로는 `@pen.dev/cli` 0.3.7의
   `pen interactive --app desktop --in <명시한 대상.pen>`이다. 설치 버전과 CLI
   read_skill을 다시 확인하고 새 세션을 쓴다. 과거 PTY ID를 재사용하지 않는다.

## 연결 경계

운영자 소유 Codex 설정의 `mcp_servers.uibowl`과 `mcp_servers.pencil`을 참조한다.
URL에 인증값이 포함될 수 있으므로 원문 URL/config를 출력·문서화·커밋하지 않는다.
새 clone에는 실행자가 설치한 Pencil 앱/CLI와 인증된 UIBowl 연결이 별도로 필요하다.
임의 샘플 credential이나 머신 경로를 배포하지 않는다.

현재 대화의 MCP catalog 노출/성공은 Paperclip managed CODEX_HOME 성공과 다르다.
실제 디자인 executor에서 home·필요한 두 server의 노출·skill/reference 접근을 확인하고,
모델 호출 없는 MCP 초기화/tools 목록 및 명시 대상 read-only 호출로 연결을 검증한다.
config 존재만으로 연결 성공을 선언하지 않는다. 필요한 server만 구성하고 인증은
런타임 소유로 유지한다. 실제 모델 실행과 새 비용은 별도 bounded task 범위다.

## 현장 근거의 수준

- 제작자 보고: 모바일/웹 3안, 각 인터랙션 상태 9개, 서비스 흐름 13개, SDS 컴포넌트
  24개/가이드, 주요 ref 연결, TakeScreenshot 및 resolveInstances 잘림 검사 통과.
- 이번 직접 확인: Pencil 연결, 명시 원본의 주요 플로우 노드와 reusable 6개 조회 성공.
  제작자가 보고한 전체 화면·컴포넌트 수나 렌더 검사를 재검증한 것은 아니다.
- UIBowl: 제작자의 실제 검색 사용 확인과 현재 catalog 노출. 이번 작업에서는 새 검색
  결과의 디자인 적합성을 검증하지 않았다.
- 전용 Codex home probe: 필요한 두 server만 configured/enabled. 같은 설정의 MCP
  초기화에서 Pencil 5 tools와 앱 상태 조회 성공, UIBowl HTTP 401 Unauthorized.
  기본 managed seed가 아닌 명시적 CODEX_HOME override이며 모델은 실행하지 않았다.
- 미구현: 클릭 가능한 프로토타입, FE 코드 패키지, 디자인→코드 자동 동기화,
  인증·실시간 기능, 브라우저 E2E/접근성 검증.

디자인의 캔버스 검증과 FE·QA 완료는 [roles.md](roles.md)의 별도 기준으로 판정한다.
