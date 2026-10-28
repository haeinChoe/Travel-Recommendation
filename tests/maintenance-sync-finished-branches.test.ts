import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join, resolve } from "node:path";
import test, { type TestContext } from "node:test";

const repositoryRoot = resolve(import.meta.dirname, "..");
const cliPath = join(repositoryRoot, "scripts/maintenance/sync-finished-branches.ts");
const temporaryRootPrefix = join(repositoryRoot, ".maintenance-sync-test-");

interface Fixture {
  readonly root: string;
  readonly seed: string;
  readonly dev: string;
}

function git(cwd: string, args: readonly string[]): string {
  return execFileSync("git", [...args], {
    cwd,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

function gitIfPresent(cwd: string, args: readonly string[]): string {
  const result = spawnSync("git", [...args], {
    cwd,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  return result.status === 0 ? (result.stdout ?? "").trim() : "";
}

function runCli(
  cwd: string,
  args: readonly string[],
  env?: NodeJS.ProcessEnv
): { status: number | null; output: string } {
  const result = spawnSync(process.execPath, [cliPath, ...args], {
    cwd,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, ...env },
  });
  return {
    status: result.status,
    output: `${result.stdout ?? ""}${result.stderr ?? ""}`,
  };
}

function createFakeGh(root: string, prs: readonly object[]): string {
  const fakeGhPath = join(root, `fake-gh-${Math.random().toString(36).slice(2)}.cjs`);
  const content = `#!/usr/bin/env node
const prs = ${JSON.stringify(prs)};
process.stdout.write(JSON.stringify(prs));
`;
  writeFileSync(fakeGhPath, content, { mode: 0o755 });
  return fakeGhPath;
}

function makeFixture(context: TestContext): Fixture {
  const root = mkdtempSync(temporaryRootPrefix);
  context.after(() => {
    if (existsSync(root)) rmSync(root, { recursive: true });
  });

  const remote = join(root, "origin.git");
  const seed = join(root, "seed");
  const dev = join(root, "dev-checkout");
  mkdirSync(root, { recursive: true });
  git(root, ["init", "--bare", remote]);
  git(root, ["init", seed]);
  git(seed, ["checkout", "-b", "dev"]);
  git(seed, ["config", "user.name", "Maintenance Test"]);
  git(seed, ["config", "user.email", "maintenance-test@example.invalid"]);
  writeFileSync(join(seed, ".gitignore"), "*.local\n", "utf8");
  writeFileSync(join(seed, "README.md"), "fixture base\n", "utf8");
  git(seed, ["add", ".gitignore", "README.md"]);
  git(seed, ["commit", "-m", "fixture base"]);
  git(seed, ["remote", "add", "origin", remote]);
  git(seed, ["push", "-u", "origin", "dev"]);
  git(root, ["clone", "--branch", "dev", remote, dev]);
  git(dev, ["config", "user.name", "Maintenance Test"]);
  git(dev, ["config", "user.email", "maintenance-test@example.invalid"]);
  return { root, seed, dev };
}

function pushIssueBranch(fixture: Fixture, branch: string): string {
  git(fixture.seed, ["checkout", "-b", branch, "dev"]);
  writeFileSync(join(fixture.seed, `${branch.split("/").at(-1)}.txt`), "finished issue change\n", "utf8");
  git(fixture.seed, ["add", "."]);
  git(fixture.seed, ["commit", "-m", `finish ${branch}`]);
  const tip = git(fixture.seed, ["rev-parse", "HEAD"]);
  git(fixture.seed, ["push", "origin", branch]);
  return tip;
}

function mergeBranchIntoRemoteDev(fixture: Fixture, branch: string): string {
  git(fixture.seed, ["checkout", "dev"]);
  git(fixture.seed, ["merge", "--no-ff", branch, "-m", `merge ${branch}`]);
  git(fixture.seed, ["push", "origin", "dev"]);
  return git(fixture.seed, ["rev-parse", "dev"]);
}

function advanceRemoteDev(fixture: Fixture): string {
  git(fixture.seed, ["checkout", "dev"]);
  writeFileSync(join(fixture.seed, "remote-update.txt"), "remote update\n", "utf8");
  git(fixture.seed, ["add", "remote-update.txt"]);
  git(fixture.seed, ["commit", "-m", "advance dev"]);
  git(fixture.seed, ["push", "origin", "dev"]);
  return git(fixture.seed, ["rev-parse", "dev"]);
}

function createLocalBranchAtRemoteTip(fixture: Fixture, branch: string): string {
  git(fixture.dev, ["fetch", "origin", `refs/heads/${branch}`]);
  const tip = git(fixture.dev, ["rev-parse", "FETCH_HEAD"]);
  git(fixture.dev, ["branch", branch, tip]);
  return tip;
}

test("plan mode reports the proposed sync and cleanup without mutating refs or worktree", (context) => {
  const fixture = makeFixture(context);
  const branch = "agent/42-finished-cleanup";
  pushIssueBranch(fixture, branch);
  mergeBranchIntoRemoteDev(fixture, branch);
  createLocalBranchAtRemoteTip(fixture, branch);
  git(fixture.dev, ["fetch", "origin", "dev"]);
  writeFileSync(join(fixture.dev, "keep.local"), "keep me\n", "utf8");

  const beforeHead = git(fixture.dev, ["rev-parse", "HEAD"]);
  const beforeStatus = git(fixture.dev, ["status", "--porcelain=v1", "--untracked-files=all"]);
  const result = runCli(fixture.dev, ["--local", branch]);

  assert.equal(result.status, 0, result.output);
  assert.match(result.output, /plan only; no changes made/i);
  assert.match(result.output, /eligible for non-force deletion/i);
  assert.equal(git(fixture.dev, ["rev-parse", "HEAD"]), beforeHead);
  assert.equal(git(fixture.dev, ["status", "--porcelain=v1", "--untracked-files=all"]), beforeStatus);
  assert.equal(git(fixture.dev, ["show-ref", "--verify", `refs/heads/${branch}`]).trim().length > 0, true);
  assert.equal(readFileSync(join(fixture.dev, "keep.local"), "utf8"), "keep me\n");
});

test("apply fast-forwards dev from FETCH_HEAD without updating origin/dev tracking ref", (context) => {
  const fixture = makeFixture(context);
  const beforeOriginDev = git(fixture.dev, ["rev-parse", "refs/remotes/origin/dev"]);
  const remoteDev = advanceRemoteDev(fixture);
  const result = runCli(fixture.dev, ["--apply"]);

  assert.equal(result.status, 0, result.output);
  assert.equal(git(fixture.dev, ["rev-parse", "HEAD"]), remoteDev);
  assert.equal(git(fixture.dev, ["rev-parse", "FETCH_HEAD"]), remoteDev);
  assert.equal(git(fixture.dev, ["rev-parse", "refs/remotes/origin/dev"]), beforeOriginDev);
  assert.notEqual(beforeOriginDev, remoteDev);
  assert.equal(git(fixture.dev, ["branch", "--show-current"]), "dev");
  assert.match(result.output, /fast-forwarded/i);
});

test("apply from a linked Issue worktree fast-forwards the separate dev worktree and preserves the caller", (context) => {
  const fixture = makeFixture(context);
  const callerBranch = "agent/42-caller-worktree";
  const caller = join(fixture.root, "caller-worktree");
  const callerHead = git(fixture.dev, ["rev-parse", "HEAD"]);
  git(fixture.dev, ["worktree", "add", "-b", callerBranch, caller, "dev"]);
  const callerStatus = git(caller, ["status", "--porcelain=v1", "--untracked-files=all"]);
  const primaryCommon = git(fixture.dev, ["rev-parse", "--path-format=absolute", "--git-common-dir"]);
  const callerCommon = git(caller, ["rev-parse", "--path-format=absolute", "--git-common-dir"]);
  assert.equal(callerCommon, primaryCommon);

  const remoteDev = advanceRemoteDev(fixture);
  const result = runCli(caller, ["--apply"]);

  assert.equal(result.status, 0, result.output);
  assert.equal(git(fixture.dev, ["rev-parse", "HEAD"]), remoteDev);
  assert.equal(git(fixture.dev, ["branch", "--show-current"]), "dev");
  assert.equal(git(caller, ["branch", "--show-current"]), callerBranch);
  assert.equal(git(caller, ["rev-parse", "HEAD"]), callerHead);
  assert.equal(git(fixture.dev, ["rev-parse", `refs/heads/${callerBranch}`]), callerHead);
  assert.equal(git(caller, ["status", "--porcelain=v1", "--untracked-files=all"]), callerStatus);
  assert.equal(existsSync(caller), true);
  const worktrees = git(fixture.dev, ["worktree", "list", "--porcelain"]);
  assert.ok(worktrees.includes(`worktree ${caller}`));
  assert.ok(worktrees.includes(`branch refs/heads/${callerBranch}`));
});

test("apply removes only explicitly named merged local Issue branches and preserves ignored files", (context) => {
  const fixture = makeFixture(context);
  const branch = "agent/42-finished-cleanup";
  pushIssueBranch(fixture, branch);
  const remoteDev = mergeBranchIntoRemoteDev(fixture, branch);
  const branchTip = createLocalBranchAtRemoteTip(fixture, branch);
  writeFileSync(join(fixture.dev, "keep.local"), "preserve ignored content\n", "utf8");

  const unrelated = "agent/43-unrelated";
  git(fixture.dev, ["branch", unrelated, branchTip]);
  const result = runCli(fixture.dev, ["--apply", "--local", branch]);

  assert.equal(result.status, 0, result.output);
  assert.equal(git(fixture.dev, ["rev-parse", "HEAD"]), remoteDev);
  assert.equal(gitIfPresent(fixture.dev, ["show-ref", "--verify", `refs/heads/${branch}`]), "");
  assert.equal(git(fixture.dev, ["show-ref", "--verify", `refs/heads/${unrelated}`]).length > 0, true);
  assert.equal(readFileSync(join(fixture.dev, "keep.local"), "utf8"), "preserve ignored content\n");
  assert.equal(git(fixture.dev, ["status", "--porcelain=v1", "--untracked-files=all"]), "");
});

test("apply holds unmerged local Issue branch while fast-forwarding dev independently", (context) => {
  const fixture = makeFixture(context);
  const branch = "agent/43-open-review";
  const pushedTip = pushIssueBranch(fixture, branch);
  const branchTip = createLocalBranchAtRemoteTip(fixture, branch);
  assert.equal(branchTip, pushedTip);
  const remoteDev = advanceRemoteDev(fixture);
  const result = runCli(fixture.dev, ["--apply", "--local", branch]);

  assert.equal(result.status, 1);
  assert.match(result.output, /not merged into origin\/dev/i);
  assert.equal(git(fixture.dev, ["rev-parse", "HEAD"]), remoteDev);
  assert.notEqual(gitIfPresent(fixture.dev, ["show-ref", "--verify", `refs/heads/${branch}`]), "");
});

test("apply succeeds on clean branch cleanup when dev already matches remote, even if dev has local changes", (context) => {
  const fixture = makeFixture(context);
  const branch = "agent/42-finished-cleanup";
  pushIssueBranch(fixture, branch);
  mergeBranchIntoRemoteDev(fixture, branch);
  createLocalBranchAtRemoteTip(fixture, branch);

  // First sync dev to remote tip so dev matches remoteDev
  const syncResult = runCli(fixture.dev, ["--apply"]);
  assert.equal(syncResult.status, 0);

  // Now introduce dirty tracked change into primary dev
  writeFileSync(join(fixture.dev, "README.md"), "local dirty change\n", "utf8");

  // Since devHead === fetchedDev, dev sync is skipped and branch cleanup succeeds
  const result = runCli(fixture.dev, ["--apply", "--local", branch]);
  assert.equal(result.status, 0, result.output);
  assert.match(result.output, /already matches fetched origin dev/i);
  assert.match(result.output, /deleted local branch agent\/42-finished-cleanup/i);
  assert.equal(gitIfPresent(fixture.dev, ["show-ref", "--verify", `refs/heads/${branch}`]), "");
});

test("apply fast-forwards dev when untracked files do not collide with incoming changes", (context) => {
  const fixture = makeFixture(context);
  writeFileSync(join(fixture.dev, "unrelated-untracked.txt"), "unrelated untracked\n", "utf8");
  const remoteDev = advanceRemoteDev(fixture);

  const result = runCli(fixture.dev, ["--apply"]);
  assert.equal(result.status, 0, result.output);
  assert.equal(git(fixture.dev, ["rev-parse", "HEAD"]), remoteDev);
  assert.equal(readFileSync(join(fixture.dev, "unrelated-untracked.txt"), "utf8"), "unrelated untracked\n");
});

test("apply holds dev sync when untracked file collides with incoming changes, preserving the file", (context) => {
  const fixture = makeFixture(context);
  // Remote creates remote-update.txt
  advanceRemoteDev(fixture);
  // Local primary dev also creates untracked remote-update.txt with different content
  writeFileSync(join(fixture.dev, "remote-update.txt"), "local conflicting content\n", "utf8");
  const beforeHead = git(fixture.dev, ["rev-parse", "HEAD"]);

  const result = runCli(fixture.dev, ["--apply"]);
  assert.equal(result.status, 1, result.output);
  assert.match(result.output, /untracked or ignored file collides with incoming origin\/dev changes/i);
  assert.equal(git(fixture.dev, ["rev-parse", "HEAD"]), beforeHead);
  assert.equal(readFileSync(join(fixture.dev, "remote-update.txt"), "utf8"), "local conflicting content\n");
});

test("apply holds dev sync when ignored file collides with incoming origin/dev changes, preserving file and cleaning eligible branch", (context) => {
  const fixture = makeFixture(context);
  // Set up an eligible branch merged into origin dev
  const eligibleBranch = "agent/60-eligible-cleanup";
  pushIssueBranch(fixture, eligibleBranch);
  mergeBranchIntoRemoteDev(fixture, eligibleBranch);
  createLocalBranchAtRemoteTip(fixture, eligibleBranch);

  // Fast-forward local dev to include eligibleBranch
  git(fixture.dev, ["pull", "--ff-only", "origin", "dev"]);

  // Remote dev advances further by adding ignored-collision.local (which is ignored by .gitignore *.local)
  git(fixture.seed, ["checkout", "dev"]);
  writeFileSync(join(fixture.seed, "ignored-collision.local"), "remote tracked content\n", "utf8");
  git(fixture.seed, ["add", "-f", "ignored-collision.local"]);
  git(fixture.seed, ["commit", "-m", "remote adds tracked ignored-collision.local"]);
  git(fixture.seed, ["push", "origin", "dev"]);

  // Local primary dev already has ignored file ignored-collision.local
  writeFileSync(join(fixture.dev, "ignored-collision.local"), "local preserved content\n", "utf8");
  assert.equal(git(fixture.dev, ["check-ignore", "ignored-collision.local"]), "ignored-collision.local");

  const beforeHead = git(fixture.dev, ["rev-parse", "HEAD"]);
  const result = runCli(fixture.dev, ["--apply", "--local", eligibleBranch]);

  assert.equal(result.status, 1, result.output);
  assert.match(result.output, /untracked or ignored file collides with incoming origin\/dev changes \(ignored-collision\.local\)/i);
  assert.match(result.output, /deleted local branch agent\/60-eligible-cleanup with git branch -d/i);
  assert.equal(git(fixture.dev, ["rev-parse", "HEAD"]), beforeHead);
  assert.equal(readFileSync(join(fixture.dev, "ignored-collision.local"), "utf8"), "local preserved content\n");
  assert.equal(gitIfPresent(fixture.dev, ["show-ref", "--verify", `refs/heads/${eligibleBranch}`]), "");
});

test("apply performs partial cleanup deleting eligible branches while holding ineligible branches", (context) => {
  const fixture = makeFixture(context);
  const eligibleBranch = "agent/42-eligible";
  pushIssueBranch(fixture, eligibleBranch);
  mergeBranchIntoRemoteDev(fixture, eligibleBranch);
  createLocalBranchAtRemoteTip(fixture, eligibleBranch);

  const unmergedBranch = "agent/43-unmerged";
  pushIssueBranch(fixture, unmergedBranch);
  createLocalBranchAtRemoteTip(fixture, unmergedBranch);

  const result = runCli(fixture.dev, [
    "--apply",
    "--local",
    eligibleBranch,
    "--local",
    unmergedBranch,
  ]);

  assert.equal(result.status, 1);
  assert.match(result.output, /deleted local branch agent\/42-eligible/i);
  assert.match(result.output, /held local branch agent\/43-unmerged/i);
  assert.equal(gitIfPresent(fixture.dev, ["show-ref", "--verify", `refs/heads/${eligibleBranch}`]), "");
  assert.notEqual(gitIfPresent(fixture.dev, ["show-ref", "--verify", `refs/heads/${unmergedBranch}`]), "");
});

test("apply supports --merged-pr-head CAS deletion verified by gh pr list and holds on mismatch", (context) => {
  const fixture = makeFixture(context);
  const branch = "agent/50-squashed";
  const tipSha = pushIssueBranch(fixture, branch);
  createLocalBranchAtRemoteTip(fixture, branch);

  // 1. Success case: local tip matches sha AND gh pr list verifies MERGED PR into dev
  const fakeGhSuccess = createFakeGh(fixture.root, [
    {
      number: 50,
      state: "MERGED",
      baseRefName: "dev",
      headRefName: branch,
      headRefOid: tipSha,
      mergedAt: "2026-10-20T10:00:00Z",
    },
  ]);
  const planMatch = runCli(fixture.dev, ["--merged-pr-head", `${branch}=${tipSha}`], { GH_BIN: fakeGhSuccess });
  assert.equal(planMatch.status, 0);
  assert.match(planMatch.output, /local tip and github merged pr #50 into dev match head/i);
  assert.match(planMatch.output, /eligible for cas deletion/i);

  // 2. Unverified case: local tip matches sha, but gh pr list has no matching MERGED PR (or different sha)
  const fakeGhUnverified = createFakeGh(fixture.root, []);
  const planUnverified = runCli(fixture.dev, ["--merged-pr-head", `${branch}=${tipSha}`], { GH_BIN: fakeGhUnverified });
  assert.equal(planUnverified.status, 0);
  assert.match(planUnverified.output, /could not verify a github merged pr into dev matching head/i);
  assert.match(planUnverified.output, /apply would hold/i);

  const applyUnverified = runCli(
    fixture.dev,
    ["--apply", "--merged-pr-head", `${branch}=${tipSha}`],
    { GH_BIN: fakeGhUnverified }
  );
  assert.equal(applyUnverified.status, 1);
  assert.match(applyUnverified.output, /held local branch agent\/50-squashed: could not verify a github merged pr into dev matching head/i);
  assert.notEqual(gitIfPresent(fixture.dev, ["show-ref", "--verify", `refs/heads/${branch}`]), "");

  // 3. Mismatch case: local tip does not match sha
  const wrongSha = "0123456789abcdef0123456789abcdef01234567";
  const planMismatch = runCli(fixture.dev, ["--merged-pr-head", `${branch}=${wrongSha}`], { GH_BIN: fakeGhSuccess });
  assert.equal(planMismatch.status, 0);
  assert.match(planMismatch.output, /local tip .* does not match caller-supplied pr head/i);
  assert.match(planMismatch.output, /apply would hold/i);

  const applyMismatch = runCli(
    fixture.dev,
    ["--apply", "--merged-pr-head", `${branch}=${wrongSha}`],
    { GH_BIN: fakeGhSuccess }
  );
  assert.equal(applyMismatch.status, 1);
  assert.match(applyMismatch.output, /held local branch agent\/50-squashed: local tip .* does not match caller-supplied pr head/i);
  assert.notEqual(gitIfPresent(fixture.dev, ["show-ref", "--verify", `refs/heads/${branch}`]), "");

  // Finally, apply success case: CAS deletion succeeds when verified
  const applySuccess = runCli(
    fixture.dev,
    ["--apply", "--merged-pr-head", `${branch}=${tipSha}`],
    { GH_BIN: fakeGhSuccess }
  );
  assert.equal(applySuccess.status, 0);
  assert.match(applySuccess.output, /deleted legacy squash\/rebase branch agent\/50-squashed via cas at github-verified merged pr #50 head/i);
  assert.equal(gitIfPresent(fixture.dev, ["show-ref", "--verify", `refs/heads/${branch}`]), "");
});

test("apply holds branch checked out in another worktree while fast-forwarding dev", (context) => {
  const fixture = makeFixture(context);
  const branch = "agent/44-other-worktree";
  const pushedTip = pushIssueBranch(fixture, branch);
  const remoteDev = mergeBranchIntoRemoteDev(fixture, branch);
  const linked = join(fixture.root, "other-worktree");
  const tip = createLocalBranchAtRemoteTip(fixture, branch);
  assert.equal(tip, pushedTip);
  git(fixture.dev, ["worktree", "add", linked, branch]);

  const checkedOut = runCli(fixture.dev, ["--apply", "--local", branch]);
  assert.equal(checkedOut.status, 1);
  assert.match(checkedOut.output, /checked out in a worktree/i);
  assert.equal(git(fixture.dev, ["rev-parse", "HEAD"]), remoteDev);
  assert.equal(git(fixture.dev, ["rev-parse", `refs/heads/${branch}`]).length > 0, true);

  const protectedName = runCli(fixture.dev, ["--apply", "--local", "dev"]);
  assert.notEqual(protectedName.status, 0);
  assert.match(protectedName.output, /protected branch/i);
});
