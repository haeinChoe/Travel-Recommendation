# 에이전트 작업 원칙

이 파일은 모노레포 전체에 적용되는 저장소 작업 원칙을 정의한다. 작업별 요구사항과 권한은 사용자의 지시 및 선택된 Issue에서 확인한다. 현재 프로젝트 단계나 일정에 따라 달라지는 상태를 이 파일에 고정하지 않는다.

## Skill 및 데이터 사전 점검

- 특수 도구나 워크플로를 사용하기 전에 현재 세션의 skill catalog를 확인하고, 적용되는 각 skill의 전체 `SKILL.md`와 참조 자료를 읽는다. Issue/PR 작업에는 저장소 로컬 `.agents/skills/travel-issue-agent-loop/` skill과 현재 세션 catalog에서 찾은 전역 `herdr` skill을 모두 적용한다. 전역 skill의 파일 경로를 저장소 지침에 고정하지 않는다. Herdr 작업 전에 두 skill을 모두 따르고 필요한 Herdr 접근 절차를 확인한다.
- 실제 데이터 분석, 추천 문제 정의 또는 반복 실험이 포함된 Issue에는 저장소 로컬 `.agents/skills/travel-data-scientist/` skill도 함께 적용한다. 이 skill은 단순 실행 절차가 아니라 problem/label/feature/metric 정렬, implicit feedback, leakage, ranking 평가와 여행로그 도메인 의미를 검토하는 전문 역할을 정의한다.
- 실제 데이터를 처리하기 전 선택한 실험·데이터 워크플로의 재현 명령을 읽고 필요한 데이터 입력을 식별한다. 현재 프로세스에서 `RAW_ROOT`, `CAPITAL_TL`, `CAPITAL_VL`, `WEST_TL`, `WEST_VL`, `EAST_TL`, `EAST_VL`, `JEJU_TL`, `JEJU_VL` 등 필요한 변수를 사용할 수 있으면 우선 사용한다. 변수가 보이지 않는다는 이유만으로 데이터가 없다고 판단하지 않는다.
- 필요한 경로를 현재 환경에서 확인할 수 없으면, 선택된 Issue와 `docs/data/aihub-workflow.md`가 허용한 로컬·마운트 위치에서 제한된 깊이와 역할 marker를 사용해 bounded discovery를 수행한다. 환경변수 확인은 경로 해석 수단이지 actual-data 접근의 필수 gate가 아니다. 전체 홈 또는 드라이브를 훑지 않는다. 실제 입력을 열기 전 출처, 이용 조건, 권한, 예상 TL/VL 역할 매핑을 검증하고, 로컬 경로나 변수 값을 프롬프트·로그·Git·PR에 넣지 않는다. 승인된 데이터 위치를 유일하게 식별할 수 없거나 provenance/역할 검증에 실패할 때만 actual-data 작업을 중단한다.

## 지시와 작업 범위

- 현재 사용자의 명시적 지시와 실행 대상으로 지정된 Issue를 확인한다. Issue에 목적, 범위, Non-Goals, 완료 조건 또는 필요한 권한이 없으면 추측하지 말고 확인을 요청한다.
- 더 구체적인 디렉터리 지침은 해당 디렉터리에서 우선 적용한다. 지침끼리 충돌하거나 결과에 영향을 주는 결정이 미정이면 임의로 선택하지 말고 충돌과 선택지를 보고한다.
- 현재 Issue의 목적에 필요한 최소 변경만 수행한다. 발견한 인접 개선사항은 함께 구현하지 말고 별도 제안으로 남긴다.
- 기존 사용자 변경사항과 출처가 불분명한 파일을 보존한다. 지시 없이 삭제·되돌리거나 덮어쓰지 않는다.

## 근거와 판단

- 저장소의 실제 파일, 데이터 스키마, 실행 결과와 테스트를 확인한 뒤 결정한다.
- 저장소의 운영 지침과 승인된 결정 문서를 Issue 범위에 맞게 적용한다. 확인되지 않은 제안은 확정된 요구사항이나 데이터 의미처럼 사용하지 않는다.
- 확인한 사실과 가정, 미확인 사항을 구분한다. 컬럼 의미, 결측 처리, 매핑 기준, 평가 split을 임의로 정하지 않는다.
- 공개 API, 데이터 계약, 의존성, 서비스 경계 또는 아키텍처에 영향을 주는 변경은 Issue가 명시적으로 포함하지 않는 한 먼저 보고한다.

## 데이터와 비밀정보

- 실제 데이터 접근과 결과 쓰기는 선택된 Issue에 기록된 권한 범위 안에서만 한다. 데이터 접근 권한이 없거나 출처·버전·이용 조건이 불분명하면 실제 데이터 처리를 시작하지 않는다.
- 원본 데이터는 읽기 전용으로 취급한다. 원본·제한 데이터·개인정보·자격 증명을 Git, Issue, PR, 로그, 노트북 출력 또는 외부 서비스에 포함하지 않는다.
- 데이터 처리 위치, 재현성 및 안전한 결과 공유 규칙은 docs/data/aihub-workflow.md를 따른다.

## 검증과 문서화

- 변경에 맞는 검증을 실행하고, 실행한 명령과 결과를 보고한다. 실행하지 않은 검증은 이유와 함께 명시한다.
- 데이터 또는 실험 결과를 보고할 때 재현에 필요한 데이터 식별 정보, 코드 버전, 설정, seed, 평가 조건과 비식별 집계 결과를 기록한다.
- 동작, 데이터 계약, 전처리 기준 또는 실험 프로토콜이 바뀌면 관련 문서를 갱신하거나 문서 변경이 불필요한 이유를 설명한다.
- 미결정 사항은 확정된 것처럼 표현하지 않고, 필요한 근거와 결정을 사용자에게 보고한다.

## Git과 원격 작업 권한

- Issue에 허용된 범위만 수정한다. 커밋은 Issue의 권한 선택이 허용할 때만 로컬에서 수행한다.
- 커밋 전 git status와 staged diff를 확인한다. 원본·파생 데이터, 비밀정보, Issue 범위 밖 파일은 커밋하지 않는다.
- push 및 PR 생성은 Issue 또는 사용자의 명시적 허가가 있을 때만 수행한다. dev와 main에 직접 push하지 않는다.
- 병합은 사용자의 별도 명시 지시가 있을 때만 수행한다.
- 리뷰·조사만 요청받으면 파일 변경이나 Git 작업을 하지 않는다.

## Herdr 작업

- 승인된 Issue 구현과 열린 PR의 후속 작업은 저장소 로컬 `.agents/skills/travel-issue-agent-loop/` 절차를 따른다.
- 사용자 요청을 받은 Codex 세션은 `entry-readonly` 사용자 권한 프로필을 기본으로 사용하며 저장소 내용에 대해 읽기 전용 조정자다. 범위와 상태를 확인하고 계획을 세우며 반환된 diff와 검증 결과를 읽기 전용으로 확인한다. 명령 네트워크 정책은 선택한 사용자 수준 Codex 권한 프로필과 설정에서 정의하며 호스트 목록을 저장소 지침에 복제하지 않는다. 설정에는 Herdr Unix socket 규칙이 있지만, Herdr CLI와 MCP 접근은 각각 별도로 확인한다. 이 세션은 저장소 파일 편집, 테스트, 리뷰 수정, staging, commit, push 또는 PR 생성을 하지 않는다. 사용자 또는 리뷰어의 수정 요청과 허용된 저장소 변경·전달 작업은 기존 구현 에이전트에 위임한다.
- 전용 구현 에이전트는 할당된 worktree에서 저장소 변경을 담당하며 `herdr-implementation` 사용자 권한 프로필로 시작한다. 명령 네트워크 정책은 선택한 사용자 수준 Codex 권한 프로필과 설정에서 정의한다. 설정에는 Herdr Unix socket 규칙이 있지만, Herdr CLI와 MCP 접근은 각각 별도로 확인한다. 현재 쓰기 가능 root는 `~/.herdr/worktrees` 전체이므로 이 설정은 worktree별 파일 쓰기를 강제하지 않는다. 편집, 테스트 및 리뷰 수정에 더해 Issue 또는 사용자가 허용한 경우에만 staging·commit하고, push 및 PR 생성·갱신은 명시적으로 허용된 경우에만 수행한다. 별도 허가 없이는 merge하지 않는다. 리뷰 에이전트는 `entry-readonly` 프로필로 시작하며 읽기 전용이다. Codex permission profile은 legacy `sandbox_mode` 또는 `sandbox_workspace_write`와 함께 설정하지 않는다.
- 실제 데이터 분석 전담 에이전트는 `herdr-data-science` 사용자 권한 프로필로 시작한다. 승인된 raw data root는 read-only, Herdr가 할당한 Issue worktree와 승인된 Git-ignored 결과 위치만 writable이어야 한다. 데이터 사이언티스트는 실행 전에 추천 문제와 label/feature/metric의 정렬을 검토하고, 문제 정의가 어긋나면 실행보다 먼저 근거와 대안을 보고한다. 제품 코드 변경이 주업무가 되면 `herdr-implementation` 에이전트로 handoff한다.
- 필요한 사용자 권한 프로필이 없거나 선택할 수 없으면 정확한 blocker를 보고하고 중단한다. 제한 없는 기본 쓰기 설정으로 조용히 대체하거나 조정자가 구현을 대신하지 않는다.
- Herdr가 필수 구현 에이전트를 생성하거나 시작할 수 없으면 정확한 blocker를 보고하고, 조정자가 구현을 대신하지 않는다.
- Herdr 서버·workspace·agent 상태를 확인할 때 현재 세션에 등록된 Herdr MCP bridge의 읽기 전용 도구를 우선 사용한다. MCP 상태 확인이 성공하면 Herdr CLI를 같은 상태 확인 목적으로 다시 실행할 필요는 없다. worktree·branch·PR 상태는 Git과 GitHub에서 독립적으로 확인한다.
- MCP bridge는 읽기 전용 상태 확인과 명시적으로 승인된 좁은 범위의 workspace/worktree teardown 도구를 제공한다. workspace/worktree 생성, agent 시작·prompt, pane 제어처럼 MCP mutation 대안이 없는 승인된 상태 변경 작업은 저장소 skill과 전역 Herdr skill이 정의한 approval-reviewed 실행 경로를 첫 시도부터 사용한다. MCP 상태 도구를 사용할 수 없거나 호출에 실패하면 skill에서 승인한 읽기 전용 Herdr CLI fallback을 사용한다. 상태 변경 명령을 ordinary sandbox에서 잘못 시도해 `EPERM` 또는 `Operation not permitted`가 발생한 경우 그 실패 자체를 Issue blocker로 보지 말고, 아직 시도하지 않은 이미 정의된 승인 경로로만 진행한다. 그 승인 경로가 거부되거나 동일 오류로 실패하면 blocker를 보고하고 중단한다. 새롭거나 더 넓은 escalation, sandbox bypass, force/unrestricted profile로 복구하지 않는다. CLI 실패만으로 MCP 실패를 추정하지 않는다.
- `herdr_worktree_remove`와 `herdr_workspace_close`는 사용자 또는 Issue가 cleanup을 명시적으로 승인한 경우에만 사용할 수 있으며, 사전 조건과 사후 확인은 `.agents/skills/travel-issue-agent-loop/references/agent-loop.md`의 cleanup 절차를 따른다.

## 상세 지침

- 작업 요청, 권한 단계, 브랜치·커밋·PR 절차는 docs/agent-workflow.md를 따른다.
- AI Hub 원본 및 파생 데이터 처리 절차는 docs/data/aihub-workflow.md를 따른다.
- 문서 목록과 역할은 docs/README.md에서 확인한다.
- 2023 국내 여행로그 네 권역 설명서의 Markdown 변환본과 원문·권역별 차이는 docs/data/travel-log-2023/README.md에서 확인한다.
- 수도권 스키마와 EDA 관련 컬럼 요약은 docs/data/aihub-71776-capital-schema.md를 참고한다.
