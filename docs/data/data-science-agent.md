# 데이터 사이언티스트 에이전트와 Codex 권한 프로필

Issue #51의 데이터 사이언티스트 역할은 **추천시스템·여행데이터·실험설계 판단**과 **승인된 실제 데이터의 반복 분석**을 분리된 Herdr 역할로 제공한다.

## 역할 분리

| 역할 | 기본 프로필 | 책임 |
| --- | --- | --- |
| entry coordinator / reviewer | `entry-readonly` | Issue 범위 확인, 조정, diff/근거 검토. raw data 분석이나 저장소 쓰기를 대신하지 않음 |
| implementation agent | `herdr-implementation` | 제품/실험 코드 구현, 테스트, 리뷰 수정 |
| data-science agent | `herdr-data-science` | 분석 전 도메인 검토, 승인 raw data read-only 분석, privacy-safe 결과, 실험 설계와 해석 |

실제 데이터 작업은 권한만 다른 implementation agent가 아니라 [`travel-data-scientist`](../../.agents/skills/travel-data-scientist/SKILL.md) 역할을 사용한다.

## Permission profile contract

`herdr-data-science`는 사용자 수준 Codex permission profile이다. 저장소에 machine-specific path를 커밋하지 않는다.

필수 경계:

| 대상 | 권한 |
| --- | --- |
| Herdr가 할당한 현재 Issue workspace root | write |
| Issue가 승인한 외부 AI Hub raw root | read |
| workspace 내부의 승인된 Git-ignored result 위치 | write |
| 다른 임의 경로 | 별도 승인 없이는 확장 금지 |
| raw 원본 변경/삭제/이동/rename | 금지 |
| credential/token/cookie/secret | 접근 범위 확장 금지 |

Codex의 현재 named permission profile은 `default_permissions`로 선택하며, 사용자 정의 filesystem policy는 `[permissions.<name>.filesystem]`에 둔다. `:workspace_roots`와 절대 경로/glob에 `read` / `write` / `deny`를 지정할 수 있다. permission profile은 legacy `sandbox_mode` 또는 `sandbox_workspace_write`와 함께 사용하지 않는다.

machine-local 예시:

```toml
# ~/.codex/config.toml
# 실제 raw 경로는 이 사용자 로컬 파일에만 기록하고 저장소에는 커밋하지 않는다.

[permissions.herdr-data-science.filesystem]
":workspace_roots" = "write"
"/replace/with/approved/aihub/raw-root" = "read"
```

여러 승인 raw root가 필요하면 각각 `read` 항목으로 추가한다. 결과가 workspace 밖에 있어야 한다면 Issue가 해당 위치 쓰기를 명시적으로 승인한 경우에만 별도 `write` 경로를 추가한다. command/network policy는 기존 `herdr-implementation`보다 넓히지 않고, 데이터 분석 때문에 새로운 호스트나 unrestricted access를 추가하지 않는다.

선택 예:

```bash
codex --config 'default_permissions="herdr-data-science"'
```

Herdr 시작 예:

```bash
herdr agent start data-scientist --kind codex --pane "$PANE_ID" -- \
  --config 'default_permissions="herdr-data-science"'
```

현재 Codex config reference의 named permission profile 문법을 기준으로 한다. 로컬 Codex 버전이 이 구문을 지원하지 않거나 profile을 선택할 수 없으면 blocker로 보고한다. `herdr-implementation`이나 unrestricted/default profile로 대체하지 않는다.

## 데이터 접근 절차

1. Issue의 데이터 접근 권한과 분석 목적을 확인한다.
2. `AGENTS.md`, `docs/data/aihub-workflow.md`, 관련 데이터 계약과 `travel-data-scientist` skill을 읽는다.
3. 현재 프로세스의 승인된 경로 변수를 우선 사용한다.
4. 변수가 없을 때만 허용된 위치에서 bounded discovery를 수행한다.
5. 실제 row를 열기 전에 provenance, 이용 조건, region, TL/VL/Other 역할을 확인한다.
6. raw root는 read-only로 사용하고 분석 결과는 승인된 ignored 위치에만 쓴다.
7. raw path, identifier, row-level value, coordinate, free text를 공유 출력에 포함하지 않는다.

## 실행 전 도메인 gate

data-science agent는 실제 분석보다 먼저 다음을 확인한다.

- 제품/연구 질문
- prediction time
- user / trip context / POI / interaction / feedback 역할
- label이 질문에 direct / proxy / mismatch 중 무엇인지
- classification / retrieval / ranking 구분
- candidate/exposure 가정
- implicit feedback에서 unobserved의 의미
- leakage와 split/cohort
- baseline과 metric

문제가 발견되면 기존 실험 정의를 무조건 실행하지 않는다. 무엇을 검증할 수 있고 무엇을 검증할 수 없는지 보고하고, 더 직접적인 최소 실험을 제안한다.

## Handoff

모든 actual-data 분석은 다음 정보를 남긴다.

- 분석 목적과 product question
- dataset/region/role, raw path 제외
- code revision
- problem type / prediction time / entity roles
- target과 direct/proxy/mismatch 판정
- candidate/exposure와 negative semantics
- split/cohort/leakage
- baseline/metrics
- 실제 실행한 validation
- privacy-safe result
- facts
- interpretation/inference
- unresolved limitations
- next decision

## 검증

저장소에서 자동 검증 가능한 항목:

```bash
python3 -m unittest tests.test_data_scientist_skill_docs -v
python3 -m unittest tests.test_agent_loop_cleanup_docs -v
git diff --check
```

로컬 Herdr/Codex 환경에서 별도로 확인할 항목:

1. `herdr-data-science` profile이 선택 가능하다.
2. 승인 raw root의 파일을 읽을 수 있다.
3. Issue worktree와 승인된 ignored result 위치에 쓸 수 있다.
4. 실제 raw root를 변경하지 않은 상태에서 분석이 끝난다.
5. 환경변수가 없을 때 bounded discovery가 전체 HOME/drive scan 없이 역할을 복구한다.
6. synthetic domain-review 사례에서 post-event leakage, 자동 negative, ranking/classification mismatch를 식별한다.

**실제 raw root에 write/delete를 시도해 권한을 시험하지 않는다.** destructive probe 없이 boundary를 입증할 방법이 현재 환경에 없다면 해당 항목을 미실행으로 보고하고, 원본 무변경과 profile 설정을 별도 근거로 남긴다.

## 참고

Codex의 named permission profile과 filesystem policy 문법은 OpenAI Codex configuration reference를 기준으로 한다:

- https://developers.openai.com/docs/config-file/config-reference

프로젝트 파일에는 실제 raw path, 사용자 홈 경로, credential 또는 machine-specific profile 값을 기록하지 않는다.
