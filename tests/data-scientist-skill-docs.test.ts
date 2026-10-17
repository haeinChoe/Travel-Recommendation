import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

interface RepositoryDocument {
  readonly path: string;
  readonly content: string;
}

const repositoryRoot = resolve(import.meta.dirname, "..");

function loadDocument(path: string): RepositoryDocument {
  return {
    path,
    content: readFileSync(resolve(repositoryRoot, path), "utf8"),
  };
}

const dataScientistSkill = loadDocument(
  ".agents/skills/travel-data-scientist/SKILL.md",
);
const domainReview = loadDocument(
  ".agents/skills/travel-data-scientist/references/domain-review.md",
);
const profileGuide = loadDocument("docs/data/data-science-agent.md");
const agentLoopSkill = loadDocument(
  ".agents/skills/travel-issue-agent-loop/SKILL.md",
);
const agentLoopReference = loadDocument(
  ".agents/skills/travel-issue-agent-loop/references/agent-loop.md",
);
const agentsGuide = loadDocument("AGENTS.md");
const agentWorkflow = loadDocument("docs/agent-workflow.md");

function assertContainsAll(
  document: RepositoryDocument,
  expectedPhrases: readonly string[],
): void {
  for (const phrase of expectedPhrases) {
    assert.ok(
      document.content.includes(phrase),
      `${document.path} should contain: ${phrase}`,
    );
  }
}

test("data-scientist skill keeps the domain-first problem-alignment gate", () => {
  assertContainsAll(dataScientistSkill, [
    "name: travel-data-scientist",
    "Prediction time",
    "Task type",
    "Candidate/exposure assumption",
    "Implicit feedback",
    "unknown, not automatically negative",
    "classification, retrieval, and ranking",
    "Cohort comparability",
  ]);
});

test("travel-log semantics and post-event leakage rules stay explicit", () => {
  assertContainsAll(dataScientistSkill, [
    "TRAVELER_ID",
    "TRAVEL_ID",
    "TN_VISIT_AREA_INFO",
    "TN_POI_MASTER",
    "DGSTFN",
    "REVISIT_INTENTION",
    "RCMDTN_INTENTION",
    "post-visit feedback",
  ]);

  assert.match(
    domainReview.content,
    /absence of a visit is not proof of dislike/,
  );
});

test("domain review distinguishes direct, proxy, and mismatched evidence", () => {
  assertContainsAll(domainReview, [
    "**direct**",
    "**proxy**",
    "**mismatch**",
    "Recall@K",
    "NDCG@K",
    "unvisited = dislike",
  ]);
});

test("agent workflow routes data-science work to the dedicated profile", () => {
  const routingDocuments: readonly RepositoryDocument[] = [
    agentLoopSkill,
    agentLoopReference,
    agentsGuide,
    agentWorkflow,
  ];

  for (const document of routingDocuments) {
    assertContainsAll(document, [
      "herdr-data-science",
      "travel-data-scientist",
    ]);
  }

  assert.match(agentLoopSkill.content.toLowerCase(), /do not fall back/);
});

test("any actual-data read is delegated away from the entry coordinator", () => {
  assertContainsAll(agentLoopSkill, [
    "any task that reads approved raw/actual data",
    "read-only diagnostics",
    "file existence/counts",
    "must be delegated",
    "entry coordinator must not",
  ]);

  assertContainsAll(agentLoopReference, [
    "Any actual-data read must be delegated",
    "read-only diagnostic",
    "no repository file changes",
    "file existence/counts",
    "must not perform those raw-data checks itself",
  ]);

  assertContainsAll(agentsGuide, [
    "코드 수정 여부와 무관",
    "파일 존재 여부·개수",
    "read-only 진단",
    "조정자는 raw root나 TL/VL 입력을 직접 탐색하거나 파일 개수를 세지 않고",
  ]);
});

test("data-science startup uses the guarded MCP path before CLI fallback", () => {
  assertContainsAll(agentLoopSkill, [
    "herdr_data_science_agent_start(workspace_id)",
    "guarded MCP startup tool first",
    "do not bypass",
    "Simple read-only actual-data smoke",
  ]);

  assertContainsAll(agentLoopReference, [
    "herdr_data_science_agent_start(workspace_id)",
    "guarded MCP startup tool",
    "simple read-only smoke",
    "does not require a reviewer by default",
  ]);

  assertContainsAll(agentsGuide, [
    "herdr_data_science_agent_start(workspace_id)",
    "guarded startup",
    "우회 재시도하지 않는다",
  ]);
});

test("explicit TL/VL bindings are validated instead of re-inferred from path names", () => {
  assertContainsAll(dataScientistSkill, [
    "Source-role binding vs validation",
    "CAPITAL_TL",
    "CAPITAL_VL",
    "approved_capital_filekey_root",
    "Do not reverse this order",
    "A missing `TL_csv` or `VL_csv` token",
    "export marker",
  ]);

  assertContainsAll(domainReview, [
    "Source-role provenance review",
    "Role binding",
    "Role validation",
    "capital:TL=...",
    "CAPITAL_TL",
    "directory names omit `TL_csv` / `VL_csv`",
  ]);

  assertContainsAll(profileGuide, [
    "source-role binding",
    "CAPITAL_TL",
    "region-specific layout",
    "역할을 바꿔 추측하지 말고",
  ]);
});

test("permission profile keeps the least-privilege filesystem contract", () => {
  assertContainsAll(profileGuide, [
    "[permissions.herdr-data-science.filesystem]",
    '":workspace_roots" = "write"',
    '"/replace/with/approved/aihub/raw-root" = "read"',
    'default_permissions="herdr-data-science"',
    "sandbox_mode",
    "sandbox_workspace_write",
    "함께 사용하지 않는다",
    "실제 raw root에 write/delete를 시도해 권한을 시험하지 않는다",
  ]);
});

test("handoff separates facts, interpretation, limitations, and next decision", () => {
  const handoffContract: RepositoryDocument = {
    path: "combined data-science handoff contract",
    content: [
      dataScientistSkill.content,
      domainReview.content,
      profileGuide.content,
    ].join("\n"),
  };

  assertContainsAll(handoffContract, [
    "facts",
    "interpretation/inference",
    "unresolved limitations",
    "next decision",
    "Direct / proxy / mismatch",
    "Negative semantics",
  ]);
});

test("tracked data-science documents do not contain machine-specific paths", () => {
  const trackedDocuments = [
    dataScientistSkill,
    domainReview,
    profileGuide,
  ] as const;

  const forbiddenPathPrefixes = ["/home/", "/Users/", "C:\\Users\\"] as const;

  for (const document of trackedDocuments) {
    for (const prefix of forbiddenPathPrefixes) {
      assert.ok(
        !document.content.includes(prefix),
        `${document.path} leaked a machine-specific path: ${prefix}`,
      );
    }
  }

  assert.match(
    profileGuide.content,
    /\/replace\/with\/approved\/aihub\/raw-root/,
  );
});

test("markdown code fences stay balanced", () => {
  const markdownDocuments = [
    dataScientistSkill,
    domainReview,
    profileGuide,
    agentLoopSkill,
    agentLoopReference,
  ] as const;

  for (const document of markdownDocuments) {
    const fenceCount = document.content
      .split("\n")
      .filter((line) => line.startsWith("```")).length;

    assert.equal(
      fenceCount % 2,
      0,
      `${document.path} should have balanced Markdown fenced code blocks`,
    );
  }
});

test("agent recovery guidance keeps retries bounded and diagnostics secret-safe", () => {
  const recoveryDocuments = [agentLoopSkill, agentLoopReference, dataScientistSkill, agentWorkflow];
  const requiredPhrases = [
    "at most twice",
    "never print its value",
    "DNS/TLS",
    "401/403",
    "Do not launch a replacement writer",
    "Routine continuation prompts",
  ];

  for (const phrase of requiredPhrases) {
    assert.ok(
      recoveryDocuments.some((document) => document.content.includes(phrase)),
      `recovery guidance should include: ${phrase}`,
    );
  }

  assertContainsAll(agentWorkflow, [
    "최대 두 번 재시도",
    "환경 변수 전체",
    "대체 writer를 띄우지 않는다",
    "조정자가 자동으로 계속한다",
  ]);
  assertContainsAll(agentLoopSkill, [
    "do not block otherwise authorized work",
    "This section applies only in a Herdr-managed session",
    "Otherwise, skip Herdr-only inspection and orchestration steps",
  ]);
});
