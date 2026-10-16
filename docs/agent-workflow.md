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

실제 데이터의 반복 분석이나 추천 실험 설계가 중심인 Issue는 저장소의 `travel-data-scientist` skill을 적용하고 `herdr-data-science` 권한 프로필을 사용하는 전담 에이전트에 맡긴다.

- 분석 전에 제품 질문, 예측 시점, user/trip context/item/interaction/feedback 역할, label, feature, split/cohort, baseline, metric이 서로 정렬되는지 확인한다.
- 방문 같은 implicit interaction은 관측 positive가 될 수 있지만 미관측 item을 자동 negative로 해석하지 않는다. negative sampling과 exposure 가정은 실험별로 명시한다.
- classification, retrieval, ranking을 구분하며 추천 ranking 질문을 일반 classification accuracy만으로 결론내리지 않는다.
- 방문 후 feedback과 추천 시점 feature를 구분하고 동일 trip/user/item 및 시간 기준 leakage를 검토한다.
- 기존 Issue나 문서의 실험 정의도 제품 목표와 어긋나면 그대로 실행하지 않고 차이, 영향, 더 직접적인 대안을 먼저 보고한다.
- raw data는 Issue가 승인한 범위에서 read-only로 다루고, raw path·identifier·row·좌표·자유 텍스트를 Git/Issue/PR/log에 남기지 않는다.
- 데이터 분석 범위를 넘어서는 구현 변경은 `herdr-implementation` 에이전트에 handoff한다. 필요한 profile이 없으면 더 넓은 profile로 대체하지 않는다.

상세 역할, Codex profile 계약, handoff 형식은 [`data/data-science-agent.md`](data/data-science-agent.md)를 따른다.

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

PR은 명시적으로 허가된 경우에만 만든다. PR에는 다음 내용을 기록한다.

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

- 기존 Herdr 승인 경로를 통한 별도 maintenance workspace/worktree 생성
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

이 별도 maintenance worktree 생성은 동일 Issue 작업을 중복 구현하는 것이 아니라 **PR 격리를 위한 명시적 예외**다. `.agents/skills/travel-issue-agent-loop/references/agent-loop.md`의 유지보수 격리 절차와 기존 Herdr 승인 경로를 사용한다. 실제 worktree 경로는 Herdr/Git 상태에서 읽고 임의로 추측하거나 합성하지 않는다.

### 초기 허용 범위

자동 적용 범위는 보수적인 allowlist로 시작한다.

- `AGENTS.md`
- `docs/agent-workflow.md`
- `.agents/skills/**`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/PULL_REQUEST_TEMPLATE/**`
- `.github/ISSUE_TEMPLATE/**`
- 유지보수 신속 경로 자체의 계약 검증 파일
  - `scripts/maintenance/validate-fast-path-scope.ts`
  - `tests/maintenance-fast-path.test.ts`
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

유지보수 PR이 별도 승인으로 `dev`에 병합된 뒤에는 maintenance worktree에서 원래 작업을 계속하지 않는다. Herdr/Git 상태로 중단된 Issue 번호, `agent/<N>-<issue-slug>` branch, 기존 worktree가 정확히 매핑되는지 확인한 다음 **그 원래 Issue worktree**로 돌아간다.

아래 `$BLOCKED_ISSUE_WORKTREE`는 추측한 경로가 아니라 Herdr/Git 매핑에서 확인한 기존 Issue worktree의 절대 경로를 의미한다.

```bash
git -C "$BLOCKED_ISSUE_WORKTREE" status
git -C "$BLOCKED_ISSUE_WORKTREE" fetch origin
git -C "$BLOCKED_ISSUE_WORKTREE" merge origin/dev
```

기본 동기화 방식은 원래 Issue branch에 `origin/dev`를 merge하는 것이다. 이미 원격에 push된 Issue branch의 SHA를 다시 쓰는 rebase나 force push를 기본 절차로 사용하지 않는다. merge 전에 현재 변경사항과 충돌 가능성을 확인하고, 충돌 시 유지보수 변경과 원래 Issue 변경의 의미를 모두 보존한다.

원래 Issue worktree의 미커밋 변경 때문에 merge가 안전하게 진행되지 않으면 이를 숨기기 위해 임의로 reset, stash, 강제 commit하지 않는다. 기존 Issue 권한과 현재 작업 상태에 맞는 안전한 방법을 선택하고, 자동으로 해결할 수 없으면 정확한 blocker를 보고한다. merge 후 원래 Issue 관련 검증을 다시 실행한 뒤 작업을 재개한다.

로컬 `dev` 자체를 갱신해야 할 때는 예상치 못한 merge commit 생성을 피하기 위해 `git pull --ff-only`를 권장한다.

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
