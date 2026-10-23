import { pathToFileURL } from "node:url";

const EXACT_ALLOWED_PATHS = new Set([
  "AGENTS.md",
  "docs/agent-workflow.md",
  ".github/PULL_REQUEST_TEMPLATE.md",
  "package.json",
  "scripts/maintenance/sync-finished-branches.ts",
  "scripts/maintenance/validate-fast-path-scope.ts",
  "tests/maintenance-fast-path.test.ts",
  "tests/maintenance-sync-finished-branches.test.ts",
  "tests/test_agent_loop_cleanup_docs.py",
]);

const ALLOWED_PREFIXES = [
  ".agents/skills/",
  ".github/ISSUE_TEMPLATE/",
  ".github/PULL_REQUEST_TEMPLATE/",
] as const;

export interface MaintenanceScopeResult {
  readonly allowed: readonly string[];
  readonly denied: readonly string[];
}

function normalizeRepositoryPath(path: string): string | null {
  const normalized = path.replaceAll("\\", "/").replace(/^\.\//, "");

  if (
    normalized.length === 0 ||
    normalized.startsWith("/") ||
    /^[A-Za-z]:\//.test(normalized) ||
    normalized === ".." ||
    normalized.startsWith("../") ||
    normalized.includes("/../")
  ) {
    return null;
  }

  return normalized;
}

export function isMaintenanceFastPathAllowed(path: string): boolean {
  const normalized = normalizeRepositoryPath(path);
  if (normalized === null) {
    return false;
  }

  if (EXACT_ALLOWED_PATHS.has(normalized)) {
    return true;
  }

  return ALLOWED_PREFIXES.some((prefix) => normalized.startsWith(prefix));
}

export function validateMaintenanceFastPathScope(
  paths: readonly string[],
): MaintenanceScopeResult {
  const allowed: string[] = [];
  const denied: string[] = [];

  for (const path of paths) {
    if (isMaintenanceFastPathAllowed(path)) {
      allowed.push(path);
    } else {
      denied.push(path);
    }
  }

  return { allowed, denied };
}

function runCli(paths: readonly string[]): number {
  if (paths.length === 0) {
    console.error(
      "usage: node scripts/maintenance/validate-fast-path-scope.ts <changed-file>...",
    );
    return 2;
  }

  const result = validateMaintenanceFastPathScope(paths);

  if (result.denied.length > 0) {
    console.error("유지보수 신속 경로 범위 밖 파일:");
    for (const path of result.denied) {
      console.error(`- ${path}`);
    }
    console.error(
      "경로 검사는 의미 안전성을 대신하지 않습니다. 범위 밖 또는 의미 변경은 일반 Issue로 승격하세요.",
    );
    return 1;
  }

  console.log(
    `유지보수 신속 경로 경로 검사 PASS (${result.allowed.length} files)`,
  );
  return 0;
}

const executedPath = process.argv[1];
if (executedPath && import.meta.url === pathToFileURL(executedPath).href) {
  process.exitCode = runCli(process.argv.slice(2));
}
