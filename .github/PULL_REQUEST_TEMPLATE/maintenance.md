## 유지보수 신속 경로

중단된 작업: #<issue>
중단된 원래 Issue 브랜치: `agent/<issue>-<slug>`
유지보수 브랜치: `agent/<issue>-maintenance-<slug>`

> 이 템플릿은 `docs/agent-workflow.md`의 유지보수 신속 경로 조건을 모두 만족하는 저위험 blocker에만 사용합니다. 원래 Issue worktree/branch와 유지보수 worktree/branch를 분리합니다.

## 발생한 문제

현재 작업을 막는 운영/지침/에이전트 워크플로 문제를 간단히 설명합니다.

-

## 신속 경로 적용 범위 확인

- [ ] 이미 승인된 Issue 작업 중 발견된 blocker 또는 운영 결함입니다.
- [ ] 제품 요구사항, 데이터 의미, 모델 의미, 평가 의미를 변경하지 않습니다.
- [ ] 변경 파일이 허용된 유지보수 경로에 속합니다.
- [ ] 원래 Issue의 기능 범위를 대신 확장하지 않습니다.
- [ ] 검증 방법이 명확합니다.
- [ ] 원래 Issue worktree/branch는 그대로 보존했고, `dev`에서 별도 maintenance worktree/branch를 만들었습니다.
- [ ] 이 PR에는 원래 Issue branch의 미병합 변경이 포함되지 않습니다.

경로 검사:

```bash
git diff --name-only -z origin/dev...HEAD \
  | xargs -0 node scripts/maintenance/validate-fast-path-scope.ts
```

## 변경 범위

- 실제 수정 대상:
- 수정 이유:

## 변경하지 않는 것

- [ ] 제품 계약
- [ ] 데이터·전처리 의미
- [ ] 추천 문제 정의
- [ ] 평가 프로토콜
- [ ] API/DB schema/서비스 도메인 의미
- [ ] 모델 학습·추론 의미

## 검증

| 명령 또는 확인 | 결과 |
| --- | --- |
| 유지보수 경로 검사 | PASS / FAIL / NOT RUN |
| `origin/dev...HEAD`에 원래 Issue 변경이 섞이지 않았는지 확인 | PASS / FAIL / NOT RUN |
| 관련 계약 검증 테스트 | PASS / FAIL / NOT RUN |
| `npm test` | PASS / FAIL / NOT RUN |
| `git diff --check` | PASS / FAIL / NOT RUN |

미실행 항목과 이유:

-

## 권한 확인

- [ ] 사용자의 `유지보수 게이트로 처리` 지시 또는 현재 Issue가 유지보수 branch push·PR 생성을 허용합니다.
- [ ] 유지보수 변경은 `agent/<issue>-maintenance-<slug>` 별도 branch/worktree에서 수행했습니다.
- [ ] `dev` / `main`에 직접 push하지 않았습니다.
- [ ] force push를 사용하지 않았습니다.
- [ ] 이 PR을 생성하는 권한을 merge 권한으로 해석하지 않았습니다.

## 병합 후 작업 재개

유지보수 PR이 별도 승인으로 병합된 뒤 maintenance worktree에서 원래 Issue 작업을 이어가지 않습니다. 현재 세션에서 허용된 도구와 Git 상태로 원래 Issue branch와 기존 worktree를 다시 확인한 뒤 그 worktree를 재사용합니다. Herdr 관리는 Herdr 관리 세션에서만 사용합니다.

`$BLOCKED_ISSUE_WORKTREE`는 현재 세션에서 허용된 worktree 도구와 Git 매핑으로 확인한 원래 Issue worktree 경로입니다. 경로를 추측하거나 PR에 실제 로컬 경로를 기록하지 않습니다.

```bash
git -C "$BLOCKED_ISSUE_WORKTREE" status
git -C "$BLOCKED_ISSUE_WORKTREE" fetch origin
git -C "$BLOCKED_ISSUE_WORKTREE" merge origin/dev
```

- [ ] 재개 대상이 maintenance worktree가 아니라 원래 중단된 Issue worktree임을 확인했습니다.
- [ ] 이미 push된 원래 Issue branch를 기본적으로 rebase하지 않습니다.
- [ ] force push를 사용하지 않습니다.
- [ ] 충돌 시 유지보수 변경과 기존 Issue 변경의 의미를 모두 보존합니다.
- [ ] 원래 Issue worktree의 로컬 변경을 reset/stash로 임의 은닉하지 않습니다.
- [ ] merge 후 기존 Issue 관련 검증을 다시 실행합니다.

## 작성자 확인

- [ ] 중단된 기존 Issue를 참조했습니다.
- [ ] 원래 Issue branch와 별도 maintenance branch를 모두 기록했습니다.
- [ ] 변경 파일과 전체 diff를 확인했습니다.
- [ ] 유지보수 범위 밖 변경을 포함하지 않았습니다.
- [ ] 비밀정보·실제 데이터 행·원본 경로를 포함하지 않았습니다.
- [ ] 미검증 항목과 한계를 명시했습니다.
