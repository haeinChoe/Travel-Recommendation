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
  readonly remote: string;
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

function runCli(cwd: string, args: readonly string[]): { status: number | null; output: string } {
  const result = spawnSync(process.execPath, [cliPath, ...args], {
    cwd,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  return {
    status: result.status,
    output: `${result.stdout ?? ""}${result.stderr ?? ""}`,
  };
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
  return { root, remote, seed, dev };
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

function remoteBranchExists(fixture: Fixture, branch: string): boolean {
  return git(fixture.dev, ["ls-remote", "--heads", "origin", `refs/heads/${branch}`]).length > 0;
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
  const result = runCli(fixture.dev, ["--local", branch, "--remote", branch]);

  assert.equal(result.status, 0, result.output);
  assert.match(result.output, /plan only; no changes made/i);
  assert.match(result.output, /eligible for non-force deletion/i);
  assert.equal(git(fixture.dev, ["rev-parse", "HEAD"]), beforeHead);
  assert.equal(git(fixture.dev, ["status", "--porcelain=v1", "--untracked-files=all"]), beforeStatus);
  assert.equal(remoteBranchExists(fixture, branch), true);
  assert.equal(git(fixture.dev, ["show-ref", "--verify", `refs/heads/${branch}`]).trim().length > 0, true);
  assert.equal(readFileSync(join(fixture.dev, "keep.local"), "utf8"), "keep me\n");
});

test("apply fast-forwards dev from origin/dev without cleaning unrelated branches", (context) => {
  const fixture = makeFixture(context);
  const remoteDev = advanceRemoteDev(fixture);
  const result = runCli(fixture.dev, ["--apply"]);

  assert.equal(result.status, 0, result.output);
  assert.equal(git(fixture.dev, ["rev-parse", "HEAD"]), remoteDev);
  assert.equal(git(fixture.dev, ["branch", "--show-current"]), "dev");
  assert.match(result.output, /fast-forwarded/i);
});

test("apply removes only explicitly named merged local and remote Issue branches and preserves ignored files", (context) => {
  const fixture = makeFixture(context);
  const branch = "agent/42-finished-cleanup";
  pushIssueBranch(fixture, branch);
  const remoteDev = mergeBranchIntoRemoteDev(fixture, branch);
  const branchTip = createLocalBranchAtRemoteTip(fixture, branch);
  git(fixture.dev, ["update-ref", `refs/remotes/origin/${branch}`, branchTip]);
  git(fixture.dev, ["branch", "--set-upstream-to", `origin/${branch}`, branch]);
  writeFileSync(join(fixture.dev, "keep.local"), "preserve ignored content\n", "utf8");

  const unrelated = "agent/43-unrelated";
  git(fixture.dev, ["branch", unrelated, branchTip]);
  const result = runCli(fixture.dev, ["--apply", "--local", branch, "--remote", branch]);

  assert.equal(result.status, 0, result.output);
  assert.equal(git(fixture.dev, ["rev-parse", "HEAD"]), remoteDev);
  assert.equal(gitIfPresent(fixture.dev, ["show-ref", "--verify", `refs/heads/${branch}`]), "");
  assert.equal(git(fixture.dev, ["show-ref", "--verify", `refs/heads/${unrelated}`]).length > 0, true);
  assert.equal(remoteBranchExists(fixture, branch), false);
  assert.equal(gitIfPresent(fixture.dev, ["show-ref", "--verify", `refs/remotes/origin/${branch}`]), "");
  assert.equal(readFileSync(join(fixture.dev, "keep.local"), "utf8"), "preserve ignored content\n");
  assert.equal(git(fixture.dev, ["status", "--porcelain=v1", "--untracked-files=all"]), "");
});

test("apply refuses an unmerged open Issue branch before moving dev or deleting refs", (context) => {
  const fixture = makeFixture(context);
  const branch = "agent/43-open-review";
  pushIssueBranch(fixture, branch);
  const remoteDev = advanceRemoteDev(fixture);
  const beforeHead = git(fixture.dev, ["rev-parse", "HEAD"]);
  const result = runCli(fixture.dev, ["--apply", "--remote", branch]);

  assert.notEqual(result.status, 0);
  assert.match(result.output, /not merged into origin\/dev/i);
  assert.equal(git(fixture.dev, ["rev-parse", "HEAD"]), beforeHead);
  assert.notEqual(beforeHead, remoteDev);
  assert.equal(remoteBranchExists(fixture, branch), true);
});

test("apply refuses dirty dev before fetching or removing anything", (context) => {
  const fixture = makeFixture(context);
  const branch = "agent/42-finished-cleanup";
  pushIssueBranch(fixture, branch);
  mergeBranchIntoRemoteDev(fixture, branch);
  createLocalBranchAtRemoteTip(fixture, branch);
  writeFileSync(join(fixture.dev, "README.md"), "local dirty change\n", "utf8");
  const beforeHead = git(fixture.dev, ["rev-parse", "HEAD"]);
  const beforeOriginDev = git(fixture.dev, ["rev-parse", "refs/remotes/origin/dev"]);

  const result = runCli(fixture.dev, ["--apply", "--local", branch, "--remote", branch]);

  assert.notEqual(result.status, 0);
  assert.match(result.output, /dirty; refusing apply before fetch/i);
  assert.equal(git(fixture.dev, ["rev-parse", "HEAD"]), beforeHead);
  assert.equal(git(fixture.dev, ["rev-parse", "refs/remotes/origin/dev"]), beforeOriginDev);
  assert.equal(remoteBranchExists(fixture, branch), true);
});

test("apply refuses a branch checked out in another worktree and rejects non-Issue names", (context) => {
  const fixture = makeFixture(context);
  const branch = "agent/44-other-worktree";
  const tip = pushIssueBranch(fixture, branch);
  mergeBranchIntoRemoteDev(fixture, branch);
  const linked = join(fixture.root, "other-worktree");
  git(fixture.dev, ["fetch", "origin", `refs/heads/${branch}`]);
  const fetchedTip = git(fixture.dev, ["rev-parse", "FETCH_HEAD"]);
  assert.equal(fetchedTip, tip);
  git(fixture.dev, ["update-ref", `refs/remotes/origin/${branch}`, fetchedTip]);
  git(fixture.dev, ["worktree", "add", "--track", "-b", branch, linked, `refs/remotes/origin/${branch}`]);

  const beforeHead = git(fixture.dev, ["rev-parse", "HEAD"]);
  const checkedOut = runCli(fixture.dev, ["--apply", "--remote", branch]);
  assert.notEqual(checkedOut.status, 0);
  assert.match(checkedOut.output, /checked out in a worktree/i);
  assert.equal(git(fixture.dev, ["rev-parse", "HEAD"]), beforeHead);
  assert.equal(git(fixture.dev, ["rev-parse", `refs/heads/${branch}`]).length > 0, true);

  const protectedName = runCli(fixture.dev, ["--apply", "--remote", "dev"]);
  assert.notEqual(protectedName.status, 0);
  assert.match(protectedName.output, /protected branch/i);
  assert.equal(git(fixture.dev, ["rev-parse", "HEAD"]), beforeHead);
  assert.ok(tip.length > 0);
});

test("apply removes only a stale origin tracking ref after the remote branch is confirmed absent", (context) => {
  const fixture = makeFixture(context);
  const branch = "agent/46-stale-remote";
  const stale = git(fixture.seed, ["rev-parse", "dev"]);
  git(fixture.dev, ["update-ref", `refs/remotes/origin/${branch}`, stale]);
  git(fixture.dev, ["branch", "agent/47-preserved-local", stale]);

  const result = runCli(fixture.dev, ["--apply", "--remote", branch]);

  assert.equal(result.status, 0, result.output);
  assert.match(result.output, /already absent/i);
  assert.match(result.output, /removed stale tracking ref/i);
  assert.equal(gitIfPresent(fixture.dev, ["show-ref", "--verify", `refs/remotes/origin/${branch}`]), "");
  assert.equal(git(fixture.dev, ["show-ref", "--verify", "refs/heads/agent/47-preserved-local"]).length > 0, true);
});
