import { execFileSync, type ExecFileSyncOptions } from "node:child_process";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

interface Options {
  readonly apply: boolean;
  readonly localBranches: readonly string[];
}

interface Worktree {
  readonly path: string;
  readonly branch: string | null;
}

const ISSUE_BRANCH = /^agent\/\d+-(?:maintenance-)?[a-z0-9][a-z0-9._-]*$/;
const GIT_OPTIONS: ExecFileSyncOptions = {
  encoding: "utf8",
  stdio: ["ignore", "pipe", "pipe"],
};

function git(cwd: string, args: readonly string[]): string {
  return execFileSync("git", [...args], { ...GIT_OPTIONS, cwd }) as string;
}

function gitStatus(cwd: string, args: readonly string[]): number {
  try {
    git(cwd, args);
    return 0;
  } catch (error) {
    const status = (error as NodeJS.ErrnoException & { status?: number }).status;
    return typeof status === "number" ? status : 1;
  }
}

function parseOptions(argv: readonly string[]): Options {
  let apply = false;
  const localBranches: string[] = [];

  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--apply") {
      if (apply) throw new Error("--apply may be specified only once");
      apply = true;
      continue;
    }

    if (argument === "--local") {
      const branch = argv[index + 1];
      if (!branch || branch.startsWith("--")) {
        throw new Error(`${argument} requires an explicit branch name`);
      }
      index += 1;
      assertIssueBranch(branch);
      if (localBranches.includes(branch)) {
        throw new Error(`duplicate ${argument} branch: ${branch}`);
      }
      localBranches.push(branch);
      continue;
    }

    throw new Error(`unknown argument: ${argument}`);
  }

  return { apply, localBranches };
}

function assertIssueBranch(branch: string): void {
  if (branch === "dev" || branch === "main" || !ISSUE_BRANCH.test(branch)) {
    throw new Error(`refusing non-Issue or protected branch: ${branch}`);
  }
  if (gitStatus(process.cwd(), ["check-ref-format", "--branch", branch]) !== 0) {
    throw new Error(`invalid branch name: ${branch}`);
  }
}

function parseWorktrees(output: string): Worktree[] {
  const records: Worktree[] = [];
  let current: { path?: string; branch: string | null } | null = null;

  const finish = (): void => {
    if (current?.path) records.push({ path: current.path, branch: current.branch });
    current = null;
  };

  for (const line of output.split(/\r?\n/)) {
    if (line.length === 0) {
      finish();
    } else if (line.startsWith("worktree ")) {
      finish();
      current = { path: line.slice("worktree ".length), branch: null };
    } else if (line.startsWith("branch ") && current) {
      current.branch = line.slice("branch ".length);
    }
  }
  finish();
  return records;
}

function locatePrimaryDev(cwd: string): string {
  const currentCommon = git(cwd, ["rev-parse", "--path-format=absolute", "--git-common-dir"]).trim();
  const worktrees = parseWorktrees(git(cwd, ["worktree", "list", "--porcelain"]));
  const devWorktrees = worktrees.filter((worktree) => worktree.branch === "refs/heads/dev");

  if (devWorktrees.length !== 1) {
    throw new Error(`expected exactly one dev worktree in shared Git metadata; found ${devWorktrees.length}`);
  }

  const primary = devWorktrees[0];
  if (!primary) throw new Error("primary dev worktree lookup failed");
  const primaryCommon = git(primary.path, ["rev-parse", "--path-format=absolute", "--git-common-dir"]).trim();
  if (resolve(primaryCommon) !== resolve(currentCommon)) {
    throw new Error("dev worktree does not share Git metadata with the invoking worktree");
  }
  if (git(primary.path, ["branch", "--show-current"]).trim() !== "dev") {
    throw new Error("identified primary worktree is not checked out on dev");
  }
  return primary.path;
}

function isClean(worktree: string): boolean {
  return git(worktree, ["status", "--porcelain=v1", "--untracked-files=all"]).trim().length === 0;
}

function refExists(worktree: string, ref: string): boolean {
  return gitStatus(worktree, ["show-ref", "--verify", "--quiet", ref]) === 0;
}

function isAncestor(worktree: string, ancestor: string, descendant: string): boolean {
  return gitStatus(worktree, ["merge-base", "--is-ancestor", ancestor, descendant]) === 0;
}

function currentOriginDev(worktree: string): string | null {
  if (!refExists(worktree, "refs/remotes/origin/dev")) return null;
  return git(worktree, ["rev-parse", "--verify", "refs/remotes/origin/dev^{commit}"]).trim();
}

function localTip(worktree: string, branch: string): string | null {
  const ref = `refs/heads/${branch}`;
  return refExists(worktree, ref)
    ? git(worktree, ["rev-parse", "--verify", `${ref}^{commit}`]).trim()
    : null;
}

function printPlan(primary: string, options: Options): void {
  const head = git(primary, ["rev-parse", "HEAD"]).trim();
  const originDev = currentOriginDev(primary);
  console.log(`Primary dev HEAD: ${head}`);
  console.log(`Existing refs/remotes/origin/dev snapshot (may be stale): ${originDev ?? "missing; apply would fetch origin dev"}`);
  console.log(`dev worktree status: ${isClean(primary) ? "clean" : "dirty (apply refused)"}`);
  console.log("Mode: plan only; no changes made.");

  for (const branch of options.localBranches) {
    const tip = localTip(primary, branch);
    if (!tip) {
      console.log(`Local ${branch}: already absent.`);
    } else if (parseWorktrees(git(primary, ["worktree", "list", "--porcelain"])).some((item) => item.branch === `refs/heads/${branch}`)) {
      console.log(`Local ${branch}: checked out in a worktree; apply would refuse.`);
    } else if (originDev && isAncestor(primary, tip, originDev)) {
      console.log(`Local ${branch}: tip is an ancestor of origin/dev; eligible for non-force deletion.`);
    } else {
      console.log(`Local ${branch}: ancestry cannot be confirmed; apply would refuse.`);
    }
  }

}

function prepareLocalTargets(
  worktree: string,
  branches: readonly string[],
  originDev: string,
  worktrees: readonly Worktree[],
): Array<{ branch: string; tip: string | null }> {
  return branches.map((branch) => {
    const tip = localTip(worktree, branch);
    if (!tip) return { branch, tip: null };
    if (worktrees.some((item) => item.branch === `refs/heads/${branch}`)) {
      throw new Error(`local branch ${branch} is checked out in a worktree; refusing cleanup`);
    }
    if (!isAncestor(worktree, tip, originDev)) {
      throw new Error(`local branch ${branch} is not merged into origin/dev; refusing cleanup`);
    }
    return { branch, tip };
  });
}

function applyPlan(primary: string, options: Options): void {
  if (!isClean(primary)) {
    throw new Error("primary dev worktree is dirty; refusing apply before fetch or cleanup");
  }

  git(primary, ["fetch", "--no-tags", "--refmap=", "origin", "dev"]);
  const fetchedDev = git(primary, ["rev-parse", "--verify", "FETCH_HEAD^{commit}"]).trim();

  const devHead = git(primary, ["rev-parse", "HEAD"]).trim();
  if (!isAncestor(primary, devHead, fetchedDev)) {
    throw new Error("local dev is not an ancestor of fetched origin dev; refusing non-fast-forward update");
  }

  const worktrees = parseWorktrees(git(primary, ["worktree", "list", "--porcelain"]));
  const localPlans = prepareLocalTargets(primary, options.localBranches, fetchedDev, worktrees);

  if (devHead !== fetchedDev) {
    git(primary, ["merge", "--ff-only", fetchedDev]);
  }
  const updatedHead = git(primary, ["rev-parse", "HEAD"]).trim();
  if (updatedHead !== fetchedDev) throw new Error("dev fast-forward readback did not match fetched origin dev");
  if (!isClean(primary)) throw new Error("primary dev became dirty after fast-forward; refusing branch cleanup");

  for (const plan of localPlans) {
    if (!plan.tip) {
      console.log(`Local branch ${plan.branch} was already absent.`);
      continue;
    }
    git(primary, ["branch", "-d", "--", plan.branch]);
    console.log(`Deleted local branch ${plan.branch} with git branch -d.`);
  }

  console.log(`Primary dev fast-forwarded to ${updatedHead}.`);
}

function main(argv: readonly string[]): number {
  try {
    const options = parseOptions(argv);
    const invokingWorktree = git(process.cwd(), ["rev-parse", "--show-toplevel"]).trim();
    const primary = locatePrimaryDev(invokingWorktree);
    if (options.apply) {
      applyPlan(primary, options);
    } else {
      printPlan(primary, options);
      console.log("Use --apply to fetch origin dev and fast-forward safely; add --local <branch> only for explicitly named local branch cleanup.");
    }
    return 0;
  } catch (error) {
    console.error(`sync-finished-branches: ${(error as Error).message}`);
    return 1;
  }
}

const executedPath = process.argv[1];
if (executedPath && import.meta.url === pathToFileURL(resolve(executedPath)).href) {
  process.exitCode = main(process.argv.slice(2));
}
