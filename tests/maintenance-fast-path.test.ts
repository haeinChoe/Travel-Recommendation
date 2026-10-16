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
    ".github/ISSUE_TEMPLATE/task.yml",
    ".github/PULL_REQUEST_TEMPLATE/maintenance.md",
    "scripts/maintenance/validate-fast-path-scope.ts",
    "tests/maintenance-fast-path.test.ts",
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

test("workflow documents the authorization and semantic boundary", () => {
  const workflow = readRepositoryFile("docs/agent-workflow.md");

  for (const phrase of [
    "유지보수 신속 경로",
    "유지보수 게이트로 처리",
    "경로가 허용되었다고 의미 변경까지 안전하다는 뜻은 아니다",
    "일반 Issue로 승격",
    "git merge origin/dev",
    "git pull --ff-only",
    "force push",
  ]) {
    assert.ok(workflow.includes(phrase), phrase);
  }
});

test("AGENTS and issue-loop skill route eligible blockers through the same gate", () => {
  const agents = readRepositoryFile("AGENTS.md");
  const skill = readRepositoryFile(
    ".agents/skills/travel-issue-agent-loop/SKILL.md",
  );

  for (const content of [agents, skill]) {
    assert.ok(content.includes("유지보수 신속 경로"));
    assert.ok(content.includes("유지보수 게이트로 처리"));
    assert.ok(content.includes("force push"));
  }
});

test("maintenance PR template preserves traceability and separate merge authorization", () => {
  const template = readRepositoryFile(
    ".github/PULL_REQUEST_TEMPLATE/maintenance.md",
  );

  for (const phrase of [
    "중단된 작업",
    "발생한 문제",
    "신속 경로 적용 범위 확인",
    "변경하지 않는 것",
    "검증",
    "병합 후 작업 재개",
    "git merge origin/dev",
    "merge 권한",
  ]) {
    assert.ok(template.includes(phrase), phrase);
  }
});
