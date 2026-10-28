# 에이전트 작업 흐름

이 문서는 Issue를 에이전트가 수행할 수 있는 작업으로 구체화하고, 변경과 권한을 검토 가능한 단위로 제한하는 절차를 정의한다.

## 작업 흐름

Issue 작성 및 권한 지정 → 사용자가 작업 Issue 지정 → 관련 문서·데이터·현재 구현 확인 → 범위 내 작업과 검증 → 로컬 변경 및 허용된 커밋 → PR 내용과 재현 정보 검토 → 명시된 권한에 따른 원격 반영

Issue가 존재한다는 사실만으로 작업 실행이나 원격 변경 권한이 생기지는 않는다. 사용자가 수행할 Issue를 지정하고, Issue에 권한이 명시되어야 한다.

## Issue 작성

Task Issue는 데이터 분석, 전처리, 추천 실험, 문서 및 일반 엔지니어링 작업에 사용한다. 작업에는 다음 항목이 있어야 한다.

- 목적 또는 답하려는 질문
- 관련 문서·데이터 출처와 버전, 확인한 이용 조건
- 변경 또는 분석 범위와 Non-Goals
- 검증 가능한 완료 조건
- 실행할 분석·검증 방법
- 미결정 사항 및 선행 작업
- 데이터 접근, 파일 수정, 커밋, 원격 반영 권한

Decision Issue는 아직 결정되지 않은 데이터·모델·아키텍처 선택지를 조사하고 결정하기 위해 사용한다. Decision Issue 자체는 구현 권한을 부여하지 않는다. 결정 후 승인된 결과와 근거를 문서화하고, 구현이 필요하면 별도 Task Issue를 만든다.

## 작업 전 확인과 중단 기준

Herdr 관련 선행 절차와 명령은 현재 세션이 Herdr 관리 환경이거나 사용자가 Herdr 사용을 명시한 경우에만 적용한다. ChatGPT Desktop Work 등 Herdr와 무관한 세션에서는 Herdr를 호출하지 않고, 그 세션에서 허용된 workspace·Git·GitHub·subagent 경로로 같은 branch/worktree 보존 및 권한 원칙을 지킨다. 사용 가능한 승인 경로가 있으면 Herdr 부재만으로 작업을 중단하지 않는다.

### 기술 실패 복구와 진행 확인

기술 실패는 네트워크/서비스 일시 장애, timeout·정체, 호출·컨텍스트 오류, 자격 증명·권한 부족, 데이터 출처 불확실성, 코드 결함으로 나눠 기록한다. 안전한 상태 정보만 확인하고, 멱등 작업만 backoff를 두어 최대 두 번 재시도한다. 같은 branch/worktree에 두 번째 writer를 시작하지 말고 기존 변경을 보존한다. 외부 의존성이 막혀도 독립적인 코드·문서·synthetic 검증은 계속한다.

필요한 credential은 값이 아닌 존재 여부만 확인한다. 네트워크/DNS/TLS와 endpoint 접근·이용 조건을 확인한 뒤, 허용된 경우에만 제한적이고 비용이 발생하지 않는 smoke 요청을 한다. timeout/DNS/TLS, 401/403, 429, 5xx를 구분한다. 키 발급, 이용 조건 동의, 유료 사용은 수행하지 않는다.

환경 변수 전체, shell history, 헤더, credential이 포함된 URL, 원본 행, 정확한 로컬 경로와 식별자를 로그나 PR에 남기지 않는다. 오류 분류/status, 안전한 request ID, 시각, query를 제거한 host/path만 보존한다. 에이전트가 정체되면 상태를 읽기 전용으로 확인하고 한 번만 제한된 연장 또는 checkpoint를 요청한다. 원 writer가 종료됐는지 확인하기 전 대체 writer를 띄우지 않는다.

이미 승인된 범위의 가역적 일상 작업이고 새 제품·데이터·보안·credential·이용 조건·비용 결정이 필요 없는 단순 “계속할까요?”는 조정자가 자동으로 계속한다. 새 결정, 범위 확대, 파괴적 정리 또는 중대한 모호성이 있으면 해당 지점에서만 멈춘다.

파일이나 실제 데이터에 접근하기 전에 다음을 확인한다.

1. 사용자가 지정한 Issue와 권한 선택
2. Issue의 목적, 범위, Non-Goals 및 완료 조건
3. 참조 문서의 상태와 실제 소스·스키마·테스트
4. 기존 작업 트리 변경과 데이터 경로
5. 미결정 사항 및 결과에 미치는 영향

실제 데이터 권한, 데이터 버전·이용 조건, 컬럼 의미 또는 핵심 전처리 기준이 빠져 있으면 임의로 진행하지 않는다. 확인된 근거와 필요한 결정을 사용자에게 보고한다. 작업 범위 밖의 결함은 현재 작업에 섞지 말고 후속 Issue 후보로 보고한다.

## 권한 단계

Issue 작성자는 저장소 작업 권한과 데이터 접근 권한을 각각 선택한다. 저장소 권한은 가장 높은 허용 단계 하나를 선택하는 방식이며, 해당 단계보다 높은 작업은 허용하지 않는다.

### 저장소 작업 권한

| Issue 선택값 | 허용 범위 |
| --- | --- |
| 조사와 진단만 허용 | 읽기·검색·보고. 파일 변경 금지 |
| 파일 수정과 검증까지 허용 | 파일 수정 및 검증. 커밋 금지 |
| 검증된 로컬 커밋까지 허용 | 파일 수정, 검증, Issue 범위 내 로컬 커밋 |
| 검증된 로컬 커밋 및 push·PR 생성까지 허용 | 위 작업과 기능 브랜치 push 및 PR 생성. push 전 검증 보고 필요. 병합·force push 금지 |

push·PR 권한이 선택된 Issue를 사용자가 작업 대상으로 지정하면, 에이전트는 push 전에 커밋 로그, 파일 통계, 변경 파일과 검증 결과를 보고한 뒤 해당 범위의 기능 브랜치를 push하고 PR을 만든다. 이 사전 보고는 추가 승인 요청이 아니라 권한 범위와 변경 결과를 확인할 수 있게 하는 절차다. dev와 main에 직접 push하지 않는다.

### 데이터 접근 권한

| Issue 선택값 | 허용 범위 |
| --- | --- |
| 데이터 접근 없음 | 데이터 API 사용 없음. 이미 승인된 문서·스키마만 확인 |
| MCP·Shell 메타데이터 조회 | AI Hub MCP 또는 Shell 목록 모드로 후보와 메타데이터 조회. 파일 다운로드 금지 |
| 승인된 AI Hub 데이터 다운로드, 원본 읽기 및 Git 제외 위치에 파생 결과 작성 | 웹사이트 승인이 끝난 지정 데이터셋·파일만 API Shell로 data/raw에 내려받고 읽으며, Issue에 지정된 Git 제외 경로에 파생 결과를 작성 |
| 승인된 로컬 원본 읽기만 | 이미 승인된 지정 원본을 읽고 분석. 파생 파일 작성 금지 |
| 승인된 로컬 원본 읽기 및 Git 제외 위치에 파생 결과 작성 | 지정 원본 읽기와 승인된 data/interim, data/processed 위치에 결과 작성 |

API Key 발급, 이용 조건 동의, 데이터셋 승인 신청·승인 대행, 유료 리소스 사용, 제3자 서비스로 원본 전송, 자격 증명 변경은 이 선택값에 포함되지 않는다. 이 행위는 사용자의 별도 명시적 지시가 필요하다. MCP는 메타데이터 탐색에만 사용하고 파일 다운로드에 사용하지 않는다. 세부 절차는 docs/data/aihub-workflow.md를 따른다.

## 데이터 사이언티스트 에이전트 역할

실제 데이터의 반복 분석이나 추천 실험 설계가 중심인 Issue는 저장소의 `travel-data-scientist` skill을 적용한 전담 데이터 사이언스 에이전트에 맡긴다. Herdr 관리 세션에서는 `herdr-data-science` 프로필을 사용하고, Herdr와 무관한 세션에서는 해당 세션에서 승인된 전담 분석 에이전트 경로를 사용한다. 안전한 전담 경로가 없으면 실제 데이터 읽기만 보류하고 독립적인 synthetic 검증과 문서·코드 작업은 계속한다.

- 분석 전에 제품 질문, 예측 시점, user/trip context/item/interaction/feedback 역할, label, feature, split/cohort, baseline, metric이 서로 정렬되는지 확인한다.
- 방문 같은 implicit interaction은 관측 positive가 될 수 있지만 미관측 item을 자동 negative로 해석하지 않는다. negative sampling과 exposure 가정은 실험별로 명시한다.
- classification, retrieval, ranking을 구분하며 추천 ranking 질문을 일반 classification accuracy만으로 결론내리지 않는다.
- 방문 후 feedback과 추천 시점 feature를 구분하고 동일 trip/user/item 및 시간 기준 leakage를 검토한다.
- 기존 Issue나 문서의 실험 정의도 제품 목표와 어긋나면 그대로 실행하지 않고 차이, 영향, 더 직접적인 대안을 먼저 보고한다.
- raw data는 Issue가 승인한 범위에서 read-only로 다루고, raw path·identifier·row·좌표·자유 텍스트를 Git/Issue/PR/log에 남기지 않는다.
- 데이터 분석 범위를 넘어서는 구현 변경은 전담 implementation 에이전트에 handoff한다. Herdr 세션은 `herdr-implementation`을 사용하고, 다른 세션은 그 세션의 승인된 writer 경로를 사용한다. 필요한 권한 경로가 없으면 더 넓은 profile로 대체하지 않는다.

상세 역할, Codex profile 계약, handoff 형식은 [`data/data-science-agent.md`](data/data-science-agent.md)를 따른다.

## 문서 작성과 전달

저장소 문서와 Issue/PR 설명은 실행 주체가 아니라 **사람 독자**를 기준으로 작성한다. 세부 원칙은 [사람 중심 문서 작성 가이드](documentation-style-guide.md)를 따른다.

### 문서 작성 순서

연구·실험·설계 문서는 가능한 경우 다음 내용을 상단에서 먼저 제공한다.

1. 답하려는 질문
2. 현재 상태
3. 한눈에 보는 결론
4. 현재 결정된 것
5. 아직 결정되지 않은 것
6. 다음 행동

재현 명령, 해시, 세부 진단 표는 핵심 결론 뒤에 둔다. 긴 실행 로그를 그대로 붙이지 않는다.

### 용어 사용

- 일반 설명은 한국어를 우선한다.
- 코드/컬럼/API/파일명/공식 알고리즘 이름은 원문을 유지한다.
- 전문 용어와 약어는 첫 등장 시 한국어 설명과 원어를 함께 적는다.
- 추천 시스템 공통 용어는 [추천 시스템 용어 사전](recommendation/glossary.md)의 의미와 일치시킨다.
- 새 내부 용어가 필요하면 정의, 기존 용어와의 차이, 필요한 이유를 함께 기록한다.

### 사실과 판단

분석 결과는 다음을 구분한다.

- **확인된 사실**: 데이터, 코드, 실행 결과, 공식 문서에서 직접 확인한 내용
- **해석**: 사실로부터 도출한 프로젝트의 이해
- **결정**: 실제로 채택한 규칙 또는 방향
- **미결정 / 추가 검증 필요**: 현재 근거만으로 판단할 수 없는 내용

문서 정리 중 기술적 의미나 계약의 모순을 발견해도 현재 Issue가 허용하지 않으면 함께 수정하지 않는다. 후속 Issue 후보로 남긴다.

### Issue와 PR

Issue는 해결 방법을 나열하기 전에 문제와 질문, 완료 조건을 명확히 한다. PR은 파일 목록보다 먼저 **변경 이유, 결과, 의미 변화 여부, 사람이 검토해야 할 판단**을 설명한다.

표를 사용할 때는 표 앞에서 무엇을 판단하려는지 설명한다. 상세 수치가 많으면 핵심 결과와 진단용 세부 결과를 분리한다.

## 브랜치와 작업 트리

- Issue별 전용 작업 브랜치를 사용하고 dev에서 분기한다.
- 권장 이름: agent/<issue번호>-<slug>
- 작업 전에 git status와 현재 브랜치를 확인한다.
- 기존 사용자 변경사항을 작업에 포함하거나 되돌리지 않는다.
- dev와 main에 직접 push하지 않는다. 변경은 해당 브랜치를 대상으로 한 PR로 전달한다.

## 커밋 원칙

커밋 권한이 있을 때만 로컬 커밋한다.

- 하나의 커밋은 하나의 논리적 변경을 담는다.
- 서로 독립적으로 검토 가능한 코드, 전처리, 검증, 문서 변경은 가능한 범위에서 나눈다.
- 커밋 전에 git status, staged 파일 목록, staged diff를 확인한다.
- 데이터 원본, 데이터 행이 포함된 파생 파일, 비밀정보, 캐시, 실행 산출물을 커밋하지 않는다.
- 권장 메시지 형식은 <유형>(<영역>): <변경 요약>이다. 예: data(preprocess): 방문 기록 정규화 추가, test(data): 매핑 검증 사례 추가, docs: 데이터 작업 절차 기록.
- Issue와 무관한 변경이 발견되면 해당 파일을 임의로 정리하지 말고 사용자에게 알린다.

## PR 작성과 검토

PR은 명시적으로 허가된 경우에만 만든다. dev 대상 PR은 merge commit(`--merge`)으로만 병합하며, 새 SHA를 만들어 조상 판정을 깨뜨리는 squash와 rebase 병합은 비활성화한다. 이를 통해 새 PR의 커밋 이력을 dev에 보존해 조상 검사를 통과시키고 로컬 브랜치를 git branch -d로 안전하게 정리한다. PR에는 다음 내용을 기록한다.

- 연결된 Issue와 해결한 결과
- 변경 범위와 Non-Goals
- 관련 데이터·문서 계약의 영향
- 재현에 필요한 실행 명령과 설정
- 실행한 검증 및 미실행 항목과 이유
- 데이터 작업의 버전·처리 결과 요약·안전한 산출물 위치
- 사람이 검토해야 할 판단과 한계

PR에는 실제 데이터 행, 개인 식별 가능 정보, 토큰·비밀값, 원본 데이터 파일을 넣지 않는다. 상세한 데이터 처리 규칙은 data/aihub-workflow.md를 따른다.


## 유지보수 신속 경로

승인된 Issue 작업 중 발견된 저위험 운영·지침·에이전트 워크플로 blocker는 별도 Issue 생명주기를 처음부터 반복하지 않고 **유지보수 신속 경로**로 처리할 수 있다. 이 경로는 안전 장치를 줄이는 우회 절차가 아니라, 현재 작업과 직접 연결된 작은 유지보수 변경의 승인·검증·PR 절차를 짧게 만드는 경로다.

### 진입 조건

다음 조건을 모두 만족해야 한다.

1. 이미 승인된 Issue 작업 중 발견된 blocker 또는 운영 결함이다.
2. 제품 요구사항, 데이터 의미, 모델 의미, 평가 의미를 변경하지 않는다.
3. 변경 이유와 중단된 작업의 관계를 짧고 명확하게 설명할 수 있다.
4. 변경 파일이 아래 초기 허용 범위에 속한다.
5. 자동 테스트 또는 명확한 수동 검증 방법이 있다.
6. 원래 Issue의 기능 범위를 대신 확장하지 않는다.

사용자가 특정 blocker에 대해 `유지보수 게이트로 처리`라고 명시하면, 그 blocker에 한해 다음 작업을 승인한 것으로 해석한다.

- Herdr 관리 세션에서는 기존 승인 경로를 통한 별도 maintenance workspace/worktree 생성. 다른 세션에서는 해당 세션에서 승인된 repository/worktree 경로를 사용
- `dev`에서 분기한 `agent/<중단된-issue>-maintenance-<slug>` 유지보수 브랜치 생성
- 허용된 유지보수 파일 수정과 검증
- 검증된 유지보수 브랜치 commit/push
- `dev` 대상 유지보수 PR 생성 또는 갱신

이 문구는 `dev`/`main` 직접 push, force push, merge 권한을 부여하지 않는다. 유지보수 신속 경로 자체가 새 제품 결정을 승인하지 않는다. 진입 조건을 만족하지 못하거나 의미 변경 여부가 불분명하면 일반 Issue로 승격한다.

### 작업 격리와 브랜치/worktree

일반 Issue는 기존 규칙대로 Issue별 전용 branch/worktree를 사용한다.

```text
중단된 원래 작업
  branch: agent/<N>-<issue-slug>
  worktree: 해당 Issue에 매핑된 기존 worktree

유지보수 작업
  branch: agent/<N>-maintenance-<maintenance-slug>
  worktree: dev에서 새로 만든 별도 maintenance worktree
```

여기서 `<N>`은 **중단된 기존 Issue 번호**다. 유지보수 신속 경로는 새 Issue를 만들지 않으므로 중단된 Issue가 추적성 기준점으로 남는다.

중단된 원래 Issue branch/worktree는 유지보수 수정 장소로 재사용하지 않는다. 원래 branch에는 아직 PR되지 않은 기능 변경, 데이터 분석 코드 또는 로컬 변경이 존재할 수 있으므로 그 worktree에서 유지보수 파일을 수정하면 유지보수 PR에 원래 Issue diff가 섞일 수 있다. 유지보수 변경은 반드시 `dev`를 base로 한 별도 maintenance branch/worktree에서 수행한다.

이 별도 maintenance worktree 생성은 동일 Issue 작업을 중복 구현하는 것이 아니라 **PR 격리를 위한 명시적 예외**다. `.agents/skills/travel-issue-agent-loop/references/agent-loop.md`의 유지보수 격리 절차를 따른다. Herdr 세션은 기존 승인된 Herdr 경로를 사용하고, 다른 세션은 그 세션의 승인된 repository/worktree 도구를 사용한다. 실제 worktree 경로는 해당 도구와 Git 상태에서 확인하고 임의로 추측하거나 합성하지 않는다.

### 초기 허용 범위

자동 적용 범위는 보수적인 allowlist로 시작한다.

- `AGENTS.md`
- `docs/agent-workflow.md`
- `.agents/skills/**`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/PULL_REQUEST_TEMPLATE/**`
- `.github/ISSUE_TEMPLATE/**`
- 유지보수 신속 경로 자체의 계약 검증 파일
  - `scripts/maintenance/sync-finished-branches.ts`
  - `scripts/maintenance/validate-fast-path-scope.ts`
  - `tests/maintenance-fast-path.test.ts`
  - `tests/maintenance-sync-finished-branches.test.ts`
  - `tests/test_agent_loop_cleanup_docs.py`
  - `package.json`의 관련 테스트 스크립트

현재 Issue를 직접 막는 좁은 CI/개발 도구 설정이 필요하더라도 위 allowlist 밖이면 자동으로 통과시키지 않는다. 해당 정확한 경로와 비의미 변경임을 먼저 검토하고, 필요하면 일반 Issue 또는 별도 승인으로 범위를 확장한다.

### 금지 범위

다음 의미를 바꾸는 변경은 파일 위치와 관계없이 유지보수 신속 경로를 사용할 수 없다.

- 추천 알고리즘 또는 모델 학습·추론
- 제품 요구사항 또는 서비스 도메인 규칙
- 데이터 계약, 데이터 의미 또는 전처리 의미
- 평가 프로토콜, label/feature/split/metric 의미
- API 계약
- DB schema
- 실제 데이터 처리 결과를 바꾸는 로직

경계가 애매하면 신속 경로가 아니라 일반 Issue로 처리한다. 단순 diff 크기만으로 안전 여부를 판단하지 않는다.

### 신속 경로 적용 범위 확인

변경 파일은 다음 도구로 1차 확인한다.

```bash
node scripts/maintenance/validate-fast-path-scope.ts <changed-file>...
```

maintenance branch 전체 변경 파일을 확인하는 예:

```bash
git diff --name-only -z origin/dev...HEAD \
  | xargs -0 node scripts/maintenance/validate-fast-path-scope.ts
```

이 검사는 경로 allowlist만 확인한다. **경로가 허용되었다고 의미 변경까지 안전하다는 뜻은 아니다.** PR 작성자와 검토자는 금지 의미 변경이 없는지 별도로 확인하고 관련 계약 검증 테스트를 실행한다.

### 유지보수 PR

유지보수 PR은 `.github/PULL_REQUEST_TEMPLATE/maintenance.md`를 사용하고 반드시 다음을 기록한다.

- 중단된 기존 Issue
- 중단된 원래 Issue branch
- 별도 maintenance branch
- 발생한 blocker
- 실제 변경 범위
- 제품·데이터·모델·평가 의미에서 변경하지 않는 것
- 실행한 검증과 미실행 검증의 이유
- 병합 후 기존 작업 재개 절차

유지보수 PR은 **별도 maintenance branch에서 `dev`를 대상으로** 만든다. 중단된 원래 Issue branch를 유지보수 PR의 head로 사용하지 않는다. PR diff에 원래 Issue의 미병합 변경이 섞이지 않았는지 `origin/dev...HEAD` 기준으로 확인한다. 유지보수 PR 생성 권한은 merge 권한을 포함하지 않는다.

### 병합 후 작업 재개

유지보수 PR이 별도 승인으로 `dev`에 병합된 뒤에는 maintenance worktree에서 원래 작업을 계속하지 않는다. 담당 agent가 현재 세션에서 허용된 Herdr 또는 repository 도구와 Git 상태를 사용해 중단된 Issue 번호, `agent/<N>-<issue-slug>` branch, 기존 worktree를 정확히 식별하고 **그 원래 Issue worktree**를 대상으로 작업을 재개한다. 사용자에게 branch나 worktree를 직접 checkout하라고 요청하지 않는다.

아래 `$BLOCKED_ISSUE_WORKTREE`는 추측한 경로가 아니라 현재 세션의 허용된 worktree 도구와 Git 매핑에서 확인한 기존 Issue worktree의 절대 경로를 의미한다.

```bash
git -C "$BLOCKED_ISSUE_WORKTREE" status
git -C "$BLOCKED_ISSUE_WORKTREE" fetch origin
git -C "$BLOCKED_ISSUE_WORKTREE" merge origin/dev
```

기본 동기화 방식은 원래 Issue branch에 `origin/dev`를 merge하는 것이다. 이미 원격에 push된 Issue branch의 SHA를 다시 쓰는 rebase나 force push를 기본 절차로 사용하지 않는다. merge 전에 현재 변경사항과 충돌 가능성을 확인하고, 충돌 시 유지보수 변경과 원래 Issue 변경의 의미를 모두 보존한다.

원래 Issue worktree의 미커밋 변경 때문에 merge가 안전하게 진행되지 않으면 이를 숨기기 위해 임의로 reset, stash, 강제 commit하지 않는다. 기존 Issue 권한과 현재 작업 상태에 맞는 안전한 방법을 선택하고, 자동으로 해결할 수 없으면 정확한 blocker를 보고한다. merge 후 원래 Issue 관련 검증을 다시 실행한 뒤 작업을 재개한다.

로컬 `dev` 자체를 갱신해야 할 때는 예상치 못한 merge commit 생성을 피하기 위해 `git pull --ff-only`를 권장한다.

완료된 Issue branch 정리와 primary `dev` 동기화에는 repository-local `scripts/maintenance/sync-finished-branches.ts`를 사용한다. 기본 실행은 **plan-only**이며 실제 primary `dev` worktree를 현재 worktree와 shared Git metadata에서 찾는다. branch 정리 없이 `dev` 동기화만 적용하려면 branch 인자 없이 `--apply`를 사용한다. 병합된 local Issue branch 정리를 요청할 때만 각 branch 이름을 `--local agent/<N>-<slug>`로 명시하고, 과거 squash/rebase 브랜치는 `--merged-pr-head agent/<N>-<slug>=<sha>`로 명시하며, 계획을 검토한 뒤 `--apply`를 추가한다. 과거 squash/rebase 브랜치는 GitHub의 병합된 PR(`MERGED`)과 정확한 병합 당시 `headRefOid`를 근거로 정리 후보에 올릴 수 있으며, `--merged-pr-head <branch>=<sha>`는 GitHub을 직접 조회하지 않고 호출자가 GitHub에서 사전 확인한 `MERGED` PR의 `headRefOid`와 로컬 tip의 일치 여부만 검사해 CAS 원자적 명령(`git update-ref -d refs/heads/<branch> <sha>`)으로 삭제한다. 단, 로컬 커밋이 병합 head에 포함됐다는 근거가 없거나 후속 PR과의 관계가 불확실하면 보존한다(`git cherry`나 후속 PR 병합 사실만으로 원본 브랜치를 자동 삭제하지 않음). `git branch -D`와 원격 브랜치 자동 삭제는 계속 금지한다. Apply는 `git fetch --no-tags --refmap= origin dev`로 remote tip을 `FETCH_HEAD`에만 기록한다. `FETCH_HEAD`에서 읽은 commit SHA로 ancestry를 검사하고 dev가 이미 최신이면 동기화를 건너뛰고 독립적인 브랜치 정리를 진행한다. `sync-finished-branches.ts`는 `dev` fast-forward 전에 추적 파일 변경을 확인하고, 미추적 파일뿐 아니라 ignored 파일까지 반입 경로 충돌 검사에 포함하며 `git merge --ff-only --no-overwrite-ignore`를 사용한다. 충돌하는 미추적 파일이나 ignored 파일, 또는 추적 변경이 있으면 보존한 채 동기화만 보류한다. 그 SHA를 `git merge --ff-only --no-overwrite-ignore`에 전달하며, Apply 중에는 `refs/remotes/origin/dev`를 읽거나 갱신하지 않는다. Plan은 현재 `refs/remotes/origin/dev` 값을 잠재적으로 오래된 snapshot으로 표시할 수 있다. 보호 branch/non-Issue branch, 다른 worktree에서 checkout된 branch, fetch한 dev commit에 포함되지 않은 local branch는 보류한다. 여러 대상 중 일부가 보류되더라도 나머지 적격 대상은 독립적으로 처리한다. Local ref는 non-force `git branch -d`만 사용한다. Remote branch deletion is outside this tool's scope. CLI는 remote branch refs와 local remote-tracking refs를 변경하지 않는다. 무관한 branch/worktree와 ignored 파일은 보존한다. reset, stash, rebase, force, 전체 prune 또는 shell 문자열 실행은 사용하지 않는다. 테스트는 저장소 안의 임시 bare remote와 폐기 가능한 worktree만 사용하며 실제 primary checkout을 변경하지 않는다.

### Issue 작업 공간 정리와 산출물 보존

workspace, worktree, local branch 또는 연결된 파일을 정리할 때도 담당 agent가 허용된 도구와 Git 상태로 대상을 식별하고 직접 해당 worktree를 선택해 절차를 수행한다. 사용자가 직접 branch/worktree를 checkout하거나 파일을 옮기도록 요청하지 않는다. 정리는 사용자 또는 Issue의 명시적 권한이 있을 때만 시작하며, 병합되지 않은 PR이 열려 있다는 이유만으로 작업을 폐기하지 않는다.

정리 전에 tracked, untracked, ignored 항목을 읽기 전용으로 목록화하고 각 항목의 소유자, Issue와의 관계, 민감도, 재생성 가능성을 확인한다. 정리 인벤토리에는 항목이 하나도 생략되지 않은 machine-readable 상태 출력(`git status --porcelain=v1 -z --untracked-files=all --ignored=matching` 등)을 요구하며 축약 요약본이 전체 목록을 보장하지 못하면 다시 수집한다. 목록만으로 확인할 수 없는 출처·권한·민감도는 추측하지 않는다. 원본·제한 데이터, 비밀정보, 개인정보, 출처나 이용 권한이 확인되지 않은 항목은 열거나 복사하지 말고 정리를 멈춘다. 사용자 소유이거나 소유자가 불명확한 항목도 보존하고 결정을 요청한다. 재생성 가능한 cache와 environment는 가치 있는 산출물과 구분하며, `.venv`, `node_modules`, `__pycache__`, `.pytest_cache`, `.ruff_cache`처럼 재생성 가능한 항목은 사용자가 워크트리 정리를 요청했고 역할이 확인된 경우 기본 캐시 allowlist로 정리할 수 있다. `dist/`, `build/`는 중요한 산출물일 수 있어 기본 allowlist에 넣지 않는다. 캐시 정리 후에는 최종 상태 검사(`git status --porcelain=v1 --untracked-files=all --ignored=matching`)를 유지하고, 미분류 파일이나 사용자 파일이 남으면 그 워크트리만 보류한다.

확인된 비민감 Issue 산출물의 명시적 cleanup 승인은 primary `dev` checkout으로의 로컬 복사를 포함할 수 있다. 실제 데이터 파생 파일은 `docs/data/aihub-workflow.md`와 Issue에 기록된 권한을 충족해야 하며, dataset Parquet 등 파생 데이터는 Git에 추가하지 않는다. 출처, 이용 조건, 민감도 또는 로컬 이동 권한을 확인할 수 없으면 복사하지 말고 정리를 멈춘다.

복사 전에 repository/worktree 상태에서 확인한 primary `dev` checkout의 정확한 destination에 `git check-ignore -q -- <destination>` 또는 지정 도구의 동등 기능을 실행한다. destination이 Git-ignore되지 않으면 어떤 파일도 쓰기 전에 멈춘다. 사전 확인이 통과한 뒤에만 지정 경로로 복사하며, 아래 복사 후 Git-ignore 재확인도 계속 수행한다.

보존 목적지는 임의의 worktree가 아니라 **repository/worktree 상태에서 확인한 실제 로컬 primary `dev` checkout**이다. 담당 산출물 생성 agent는 각 Issue 산출물의 정확한 파일 집합과 Issue 상대 위치를 기록한 manifest를 소유하고, 생성 후 산출물을 다시 열어 schema, row count, key integrity, readability 및 해당 Issue의 semantic acceptance check를 확인한다. 파일명·크기·hash만 검사한 것은 내용 검증이 아니다. 현재 세션에서는 등록된 local-file 작업 경로 `functions.exec` → `tools.exec_command`를 지정 복사 도구로 사용한다. 다른 세션에서는 그 세션에 등록된 지정 static file/workspace 도구를 사용한다. 원본 worktree를 정리하기 전에 확인된 primary `dev` checkout의 `results/issue-<N>/`에만 복사하며 임의로 추측한 목적지에는 쓰지 않는다. 복사 후 manifest와 destination의 정확한 file set을 대조하고, 각 파일의 content equality를 확인하며, 실제 destination의 Git-ignore 상태와 destination artifact를 다시 열어 Issue별 semantic check 및 readability를 확인한다. manifest(또는 정리 기록)에는 `검증됨 → 복사됨 → 복사 후 대조됨 → 원본 처리됨` 상태 전이를 남겨 사전 검증 기록과 실제 복사 완료 증거를 구분한다. source와 destination의 내용·의미가 모두 일치하고 ignore 및 접근 정책이 확인되기 전에는 source copy/cache 삭제나 worktree cleanup을 하지 않는다. Herdr에 연결된 워크트리는 guarded MCP(`herdr_worktree_remove` / `herdr_workspace_close`)로만 제거하고, MCP가 없으면 해당 도구가 있는 세션으로 넘긴다. Herdr와 무관한 일반 Git 워크트리에는 동일한 사전·사후 검사를 거치는 `git worktree remove` 절차를 별도로 허용한다(`--force`, `-D`, 원격 삭제 제외).

현재 세션의 `functions.exec` → `tools.exec_command` 또는 다른 세션의 등록된 지정 도구가 실제 primary `dev` checkout을 식별·작성하지 못하면 정확한 도구/capability blocker를 기록하고 원본 산출물과 source worktree를 보존한 채 멈춘다. 별도 branch archive, 직접 Git write, 또는 사용자에게 checkout/copy를 요청하는 방법으로 대체하지 않는다. 원본·제한 데이터와 identifying value는 열거나 hash·복사·공유하지 않는다. Issue와 데이터 정책이 허용하는 비민감 산출물만 로컬 이동한다. PR과 로그에는 경로, 식별값, raw rows 대신 안전한 aggregate evidence만 기록한다.

확인된 산출물의 원본 복사본은 복사 검증 후에만 명시적으로 승인된 정리의 일부로 제거할 수 있다. 그 외 항목은 대상 상태를 다시 확인한 뒤 guarded worktree removal 조건을 만족하지 않으면 삭제를 시도하지 않는다. Herdr workspace session을 닫는 것은 checkout을 보존하는 별도 작업이며 worktree나 branch 정리 완료로 간주하지 않는다. local branch는 작업 트리가 제거되고 branch가 병합된 경우에만 정책에 따라 non-force 삭제할 수 있다. remote branch 삭제는 별도 명시 승인이 필요하다. 세부 결정 흐름과 guarded Herdr 조건은 [Issue workspace cleanup 절차](../.agents/skills/travel-issue-agent-loop/references/agent-loop.md#authorized-issue-workspace-cleanup)를 따른다.

### dry-run 기준

최소 dry-run 시나리오는 다음과 같다.

1. `agent/<N>-<issue-slug>` 전용 worktree에서 승인된 Issue 작업 중 문서/에이전트 지침 blocker 발견
2. 사용자가 `유지보수 게이트로 처리` 지시
3. 원래 Issue worktree는 그대로 보존
4. `dev`에서 `agent/<N>-maintenance-<slug>` 별도 maintenance worktree/branch 생성
5. 허용 경로만 수정하고 경로 검사와 관련 계약 검증 실행
6. 별도 maintenance branch로 유지보수 PR 생성, 중단된 Issue와 원래 branch 참조
7. 별도 merge 승인 전에는 병합하지 않음
8. 병합 후 maintenance worktree가 아니라 원래 중단된 Issue worktree를 다시 식별
9. 그 원래 Issue branch에 `origin/dev` merge
10. 기존 Issue 검증 재실행 후 작업 재개

긴급 우회 절차, required check 우회, 자동 merge, force push는 이 흐름에 포함하지 않는다.

## 작업 완료 보고

완료 보고에는 변경 파일과 범위, 브랜치·커밋, 실행한 검증 결과, 미실행 항목, 데이터 또는 계약 영향, PR·원격 작업 여부를 포함한다. 실행하지 않은 작업을 완료했다고 표현하지 않는다.
