import { execFileSync, type ExecFileSyncOptions } from "node:child_process";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

interface MergedPrHeadTarget {
  readonly branch: string;
  readonly sha: string;
}

interface Options {
  readonly apply: boolean;
  readonly localBranches: readonly string[];
  readonly mergedPrHeadBranches: readonly MergedPrHeadTarget[];
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
  const mergedPrHeadBranches: MergedPrHeadTarget[] = [];

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
      if (localBranches.includes(branch) || mergedPrHeadBranches.some((t) => t.branch === branch)) {
        throw new Error(`duplicate branch in arguments: ${branch}`);
      }
      localBranches.push(branch);
      continue;
    }

    if (argument === "--merged-pr-head") {
      const param = argv[index + 1];
      if (!param || param.startsWith("--")) {
        throw new Error(`${argument} requires <branch>=<40-char-sha>`);
      }
      index += 1;
      const eqIndex = param.indexOf("=");
      if (eqIndex <= 0) {
        throw new Error(`${argument} requires <branch>=<40-char-sha>`);
      }
      const branch = param.slice(0, eqIndex);
      const sha = param.slice(eqIndex + 1);
      assertIssueBranch(branch);
      if (!/^[0-9a-fA-F]{40}$/.test(sha)) {
        throw new Error(`${argument} requires a 40-character hex commit SHA`);
      }
      if (localBranches.includes(branch) || mergedPrHeadBranches.some((t) => t.branch === branch)) {
        throw new Error(`duplicate branch in arguments: ${branch}`);
      }
      mergedPrHeadBranches.push({ branch, sha: sha.toLowerCase() });
      continue;
    }

    throw new Error(`unknown argument: ${argument}`);
  }

  return { apply, localBranches, mergedPrHeadBranches };
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
  console.log(`dev worktree status: ${isClean(primary) ? "clean" : "dirty (apply would hold dev sync if update needed)"}`);
  console.log("Mode: plan only; no changes made.");

  const worktrees = parseWorktrees(git(primary, ["worktree", "list", "--porcelain"]));

  for (const branch of options.localBranches) {
    const tip = localTip(primary, branch);
    if (!tip) {
      console.log(`Local ${branch}: already absent.`);
    } else if (worktrees.some((item) => item.branch === `refs/heads/${branch}`)) {
      console.log(`Local ${branch}: checked out in a worktree; apply would hold.`);
    } else if (originDev && isAncestor(primary, tip, originDev)) {
      console.log(`Local ${branch}: tip is an ancestor of origin/dev; eligible for non-force deletion.`);
    } else {
      console.log(`Local ${branch}: ancestry cannot be confirmed; apply would hold.`);
    }
  }

  for (const target of options.mergedPrHeadBranches) {
    const { branch, sha } = target;
    const tip = localTip(primary, branch);
    if (!tip) {
      console.log(`Legacy squash/rebase ${branch}: already absent.`);
    } else if (worktrees.some((item) => item.branch === `refs/heads/${branch}`)) {
      console.log(`Legacy squash/rebase ${branch}: checked out in a worktree; apply would hold.`);
    } else if (tip.toLowerCase() === sha) {
      console.log(`Legacy squash/rebase ${branch}: local tip matches caller-supplied PR head ${sha} (CLI does not query GitHub; verify MERGED PR headRefOid first); eligible for CAS deletion.`);
    } else {
      console.log(`Legacy squash/rebase ${branch}: local tip (${tip}) does not match caller-supplied PR head ${sha}; apply would hold.`);
    }
  }
}

function applyPlan(primary: string, options: Options): number {
  git(primary, ["fetch", "--no-tags", "--refmap=", "origin", "dev"]);
  const fetchedDev = git(primary, ["rev-parse", "--verify", "FETCH_HEAD^{commit}"]).trim();
  const devHead = git(primary, ["rev-parse", "HEAD"]).trim();

  let devSyncHeld = false;
  let branchHeld = false;

  if (devHead === fetchedDev) {
    console.log(`Primary dev already matches fetched origin dev (${fetchedDev}); sync skipped.`);
  } else {
    if (!isAncestor(primary, devHead, fetchedDev)) {
      console.log("Primary dev sync held: local dev is not an ancestor of fetched origin dev.");
      devSyncHeld = true;
    } else if (git(primary, ["status", "--porcelain=v1", "--untracked-files=no"]).trim().length > 0) {
      console.log("Primary dev sync held: tracked files are dirty in primary dev worktree.");
      devSyncHeld = true;
    } else {
      const incomingFiles = git(primary, ["diff", "--name-only", "-z", devHead, fetchedDev])
        .split("\0")
        .filter(Boolean);
      const localOtherFiles = git(primary, ["ls-files", "-z", "--others"])
        .split("\0")
        .filter(Boolean);
      const colliding = incomingFiles.find((incoming) =>
        localOtherFiles.some(
          (local) => incoming === local || incoming.startsWith(local + "/") || local.startsWith(incoming + "/")
        )
      );
      if (colliding) {
        console.log(`Primary dev sync held: untracked or ignored file collides with incoming origin/dev changes (${colliding}).`);
        devSyncHeld = true;
      } else {
        try {
          git(primary, ["merge", "--ff-only", "--no-overwrite-ignore", fetchedDev]);
          const updatedHead = git(primary, ["rev-parse", "HEAD"]).trim();
          if (updatedHead !== fetchedDev) throw new Error("dev fast-forward readback did not match fetched origin dev");
          console.log(`Primary dev fast-forwarded to ${updatedHead}.`);
        } catch {
          console.log("Primary dev sync held: git merge --ff-only --no-overwrite-ignore refused or failed.");
          devSyncHeld = true;
        }
      }
    }
  }

  const worktrees = parseWorktrees(git(primary, ["worktree", "list", "--porcelain"]));

  for (const branch of options.localBranches) {
    const tip = localTip(primary, branch);
    if (!tip) {
      console.log(`Local branch ${branch} was already absent.`);
      continue;
    }
    if (worktrees.some((item) => item.branch === `refs/heads/${branch}`)) {
      console.log(`Held local branch ${branch}: checked out in a worktree.`);
      branchHeld = true;
      continue;
    }
    if (!isAncestor(primary, tip, fetchedDev)) {
      console.log(`Held local branch ${branch}: local branch ${branch} is not merged into origin/dev.`);
      branchHeld = true;
      continue;
    }
    try {
      git(primary, ["branch", "-d", "--", branch]);
      console.log(`Deleted local branch ${branch} with git branch -d.`);
    } catch {
      console.log(`Held local branch ${branch}: git branch -d refused deletion.`);
      branchHeld = true;
    }
  }

  for (const target of options.mergedPrHeadBranches) {
    const { branch, sha } = target;
    const tip = localTip(primary, branch);
    if (!tip) {
      console.log(`Local branch ${branch} was already absent.`);
      continue;
    }
    if (worktrees.some((item) => item.branch === `refs/heads/${branch}`)) {
      console.log(`Held local branch ${branch}: checked out in a worktree.`);
      branchHeld = true;
      continue;
    }
    if (tip.toLowerCase() !== sha) {
      console.log(`Held local branch ${branch}: local tip (${tip}) does not match caller-supplied PR head ${sha}.`);
      branchHeld = true;
      continue;
    }
    git(primary, ["update-ref", "-d", `refs/heads/${branch}`, sha]);
    console.log(`Deleted legacy squash/rebase branch ${branch} via CAS at caller-supplied PR head ${sha} (GitHub MERGED state must be pre-verified by caller).`);
  }

  return devSyncHeld || branchHeld ? 1 : 0;
}

function main(argv: readonly string[]): number {
  try {
    const options = parseOptions(argv);
    const invokingWorktree = git(process.cwd(), ["rev-parse", "--show-toplevel"]).trim();
    const primary = locatePrimaryDev(invokingWorktree);
    if (options.apply) {
      return applyPlan(primary, options);
    } else {
      printPlan(primary, options);
      console.log("Use --apply to fetch origin dev and fast-forward safely; add --local <branch> or --merged-pr-head <branch>=<sha> only for explicitly named branch cleanup.");
      return 0;
    }
  } catch (error) {
    console.error(`sync-finished-branches: ${(error as Error).message}`);
    return 1;
  }
}

const executedPath = process.argv[1];
if (executedPath && import.meta.url === pathToFileURL(resolve(executedPath)).href) {
  process.exitCode = main(process.argv.slice(2));
}
