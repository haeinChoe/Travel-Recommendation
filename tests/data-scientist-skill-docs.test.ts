import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const repositoryRoot = resolve(import.meta.dirname, "..");

const documentPaths = {
  dataScientistSkill: ".agents/skills/travel-data-scientist/SKILL.md",
  domainReview: ".agents/skills/travel-data-scientist/references/domain-review.md",
  profileGuide: "docs/data/data-science-agent.md",
  agentLoopSkill: ".agents/skills/travel-issue-agent-loop/SKILL.md",
  agentLoopReference: ".agents/skills/travel-issue-agent-loop/references/agent-loop.md",
  agentsGuide: "AGENTS.md",
  agentWorkflow: "docs/agent-workflow.md",
} as const;

type DocumentName = keyof typeof documentPaths;

type RepositoryDocuments = Record<DocumentName, string>;

function readRepositoryDocument(name: DocumentName): string {
  return readFileSync(resolve(repositoryRoot, documentPaths[name]), "utf8");
}

const documents: RepositoryDocuments = Object.fromEntries(
  Object.keys(documentPaths).map((name) => [
    name,
    readRepositoryDocument(name as DocumentName),
  ]),
) as RepositoryDocuments;

function assertContainsAll(
  content: string,
  expectedPhrases: readonly string[],
): void {
  for (const phrase of expectedPhrases) {
    assert.ok(
      content.includes(phrase),
      `Expected document to contain: ${phrase}`,
    );
  }
}

test("data-scientist skill keeps the domain-first problem-alignment gate", () => {
  assertContainsAll(documents.dataScientistSkill, [
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
  assertContainsAll(documents.dataScientistSkill, [
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
    documents.domainReview,
    /absence of a visit is not proof of dislike/,
  );
});

test("domain review distinguishes direct, proxy, and mismatched evidence", () => {
  assertContainsAll(documents.domainReview, [
    "**direct**",
    "**proxy**",
    "**mismatch**",
    "Recall@K",
    "NDCG@K",
    "unvisited = dislike",
  ]);
});

test("agent workflow routes data-science work to the dedicated profile", () => {
  const routingDocuments = [
    documents.agentLoopSkill,
    documents.agentLoopReference,
    documents.agentsGuide,
    documents.agentWorkflow,
  ];

  for (const content of routingDocuments) {
    assertContainsAll(content, [
      "herdr-data-science",
      "travel-data-scientist",
    ]);
  }

  assert.match(documents.agentLoopSkill.toLowerCase(), /do not fall back/);
});

test("permission profile keeps the least-privilege filesystem contract", () => {
  assertContainsAll(documents.profileGuide, [
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
  const combined = [
    documents.dataScientistSkill,
    documents.domainReview,
    documents.profileGuide,
  ].join("\n");

  assertContainsAll(combined, [
    "facts",
    "interpretation/inference",
    "unresolved limitations",
    "next decision",
    "Direct / proxy / mismatch",
    "Negative semantics",
  ]);
});

test("tracked data-science documents do not contain machine-specific paths", () => {
  const combined = [
    documents.dataScientistSkill,
    documents.domainReview,
    documents.profileGuide,
  ].join("\n");

  const forbiddenPathPrefixes = ["/home/", "/Users/", "C:\\Users\\"];

  for (const prefix of forbiddenPathPrefixes) {
    assert.ok(
      !combined.includes(prefix),
      `Machine-specific path leaked into tracked docs: ${prefix}`,
    );
  }

  assert.match(combined, /\/replace\/with\/approved\/aihub\/raw-root/);
});

test("markdown code fences stay balanced", () => {
  const markdownDocuments = [
    documents.dataScientistSkill,
    documents.domainReview,
    documents.profileGuide,
    documents.agentLoopSkill,
    documents.agentLoopReference,
  ];

  for (const content of markdownDocuments) {
    const fenceCount = content
      .split("\n")
      .filter((line) => line.startsWith("```")).length;

    assert.equal(
      fenceCount % 2,
      0,
      "Expected balanced Markdown fenced code blocks",
    );
  }
});
