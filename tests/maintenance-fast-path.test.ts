import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

import {
  isMaintenanceFastPathAllowed,
  validateMaintenanceFastPathScope,
} from "../scripts/maintenance/validate-fast-path-scope.ts";

const repositoryRoot = resolve(import.meta.dirname, "..");

function readRepositoryFile(path: string): string {
  return readFileSync(resolve(repositoryRoot, path), "utf8");
}

test("maintenance fast path accepts only the initial repository allowlist", () => {
  const allowed = [
    "AGENTS.md",
    "docs/agent-workflow.md",
    ".agents/skills/travel-issue-agent-loop/SKILL.md",
    ".agents/skills/travel-issue-agent-loop/references/agent-loop.md",
    ".github/ISSUE_TEMPLATE/task.yml",
    ".github/PULL_REQUEST_TEMPLATE/maintenance.md",
    "scripts/maintenance/sync-finished-branches.ts",
    "scripts/maintenance/validate-fast-path-scope.ts",
    "tests/maintenance-fast-path.test.ts",
    "tests/maintenance-sync-finished-branches.test.ts",
    "tests/test_agent_loop_cleanup_docs.py",
    "package.json",
  ] as const;

  for (const path of allowed) {
    assert.equal(isMaintenanceFastPathAllowed(path), true, path);
  }
});

test("maintenance fast path rejects product, data, recommendation, and unknown paths", () => {
  const denied = [
    "scripts/recommendation/evaluate_popularity.py",
    "docs/recommendation/poi-catalog-candidate-contract.md",
    "data/raw/example.csv",
    "apps/api/src/main.ts",
    "services/recommender/model.py",
    "scripts/maintenance/sync-finished-branches-extra.ts",
    "tests/maintenance-sync-finished-branches.integration.test.ts",
    "tests/test_agent_loop_cleanup_docs_extended.py",
    "../AGENTS.md",
    "/tmp/AGENTS.md",
    "C:\\repo\\AGENTS.md",
  ] as const;

  for (const path of denied) {
    assert.equal(isMaintenanceFastPathAllowed(path), false, path);
  }

  const result = validateMaintenanceFastPathScope([
    "AGENTS.md",
    "scripts/recommendation/evaluate_popularity.py",
  ]);

  assert.deepEqual(result.allowed, ["AGENTS.md"]);
  assert.deepEqual(result.denied, [
    "scripts/recommendation/evaluate_popularity.py",
  ]);
});

test("workflow documents authorization, isolation, and resume semantics", () => {
  const workflow = readRepositoryFile("docs/agent-workflow.md");

  for (const phrase of [
    "유지보수 신속 경로",
    "유지보수 게이트로 처리",
    "agent/<N>-maintenance-<maintenance-slug>",
    "별도 maintenance worktree",
    "중단된 원래 Issue branch/worktree는 유지보수 수정 장소로 재사용하지 않는다",
    "경로가 허용되었다고 의미 변경까지 안전하다는 뜻은 아니다",
    "일반 Issue로 승격",
    'git -C "$BLOCKED_ISSUE_WORKTREE" merge origin/dev',
    "maintenance worktree에서 원래 작업을 계속하지 않는다",
    "git pull --ff-only",
    "force push",
    "scripts/maintenance/sync-finished-branches.ts",
    "--apply",
    "origin/dev",
  ]) {
    assert.ok(workflow.includes(phrase), phrase);
  }
});

test("AGENTS and issue-loop skill preserve the blocked worktree and use a maintenance branch", () => {
  const agents = readRepositoryFile("AGENTS.md");
  const skill = readRepositoryFile(
    ".agents/skills/travel-issue-agent-loop/SKILL.md",
  );

  for (const content of [agents, skill]) {
    assert.ok(content.includes("유지보수 신속 경로"));
    assert.ok(content.includes("유지보수 게이트로 처리"));
    assert.ok(content.includes("agent/<"));
    assert.ok(content.includes("-maintenance-<slug>"));
    assert.ok(content.includes("worktree"));
    assert.ok(content.includes("force push"));
  }
});

test("issue-loop reference defines the maintenance isolation exception", () => {
  const reference = readRepositoryFile(
    ".agents/skills/travel-issue-agent-loop/references/agent-loop.md",
  );

  for (const phrase of [
    "Maintenance fast-path workspace isolation",
    "deliberate isolation exception",
    "agent/<N>-maintenance-<maintenance-slug>",
    'herdr workspace create --cwd "$REPO_ROOT" --label "maintenance-<N>" --no-focus',
    "Resume there, not in the maintenance worktree",
  ]) {
    assert.ok(reference.includes(phrase), phrase);
  }
});

test("maintenance PR template preserves branch/worktree isolation and separate merge authorization", () => {
  const template = readRepositoryFile(
    ".github/PULL_REQUEST_TEMPLATE/maintenance.md",
  );

  for (const phrase of [
    "중단된 작업",
    "중단된 원래 Issue 브랜치",
    "유지보수 브랜치",
    "agent/<issue>-maintenance-<slug>",
    "원래 Issue worktree/branch는 그대로 보존",
    "이 PR에는 원래 Issue branch의 미병합 변경이 포함되지 않습니다",
    "현재 세션에서 허용된 도구와 Git 상태",
    "Herdr 관리는 Herdr 관리 세션에서만 사용합니다",
    "병합 후 작업 재개",
    'git -C "$BLOCKED_ISSUE_WORKTREE" merge origin/dev',
    "maintenance worktree가 아니라 원래 중단된 Issue worktree",
    "merge 권한",
  ]) {
    assert.ok(template.includes(phrase), phrase);
  }
});

test("issue recovery and data-science routing work without Herdr", () => {
  const issueLoop = readRepositoryFile(
    ".agents/skills/travel-issue-agent-loop/SKILL.md",
  );
  const reference = readRepositoryFile(
    ".agents/skills/travel-issue-agent-loop/references/agent-loop.md",
  );
  const dataScientist = readRepositoryFile(
    ".agents/skills/travel-data-scientist/SKILL.md",
  );
  const workflow = readRepositoryFile("docs/agent-workflow.md");

  for (const phrase of [
    "do not block otherwise authorized work",
    "In a non-Herdr session, skip Herdr inspection",
    "In other sessions, establish reuse from the Issue branch",
    "The branch-isolation requirements below apply in every session",
    "In other sessions, use the active session's authorized repository/worktree tool",
  ]) {
    assert.ok(issueLoop.includes(phrase) || reference.includes(phrase), phrase);
  }

  assert.ok(dataScientist.includes("In a non-Herdr session"));
  assert.ok(dataScientist.includes("defer actual-data reads"));
  assert.ok(workflow.includes("다른 세션은 그 세션의 승인된 writer 경로를 사용"));
  assert.ok(workflow.includes("다른 세션에서는 해당 세션에서 승인된 repository/worktree 경로를 사용"));

  for (const phrase of [
    "at most twice",
    "never print its value",
    "DNS/TLS",
    "401/403",
    "Do not launch a replacement writer",
    "Routine continuation prompts",
  ]) {
    assert.ok([issueLoop, reference, dataScientist, workflow].some((text) => text.includes(phrase)), phrase);
  }
});
