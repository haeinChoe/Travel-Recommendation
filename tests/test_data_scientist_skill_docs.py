"""Static regression checks for the travel data-scientist skill and role wiring."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DS_SKILL = ROOT / ".agents/skills/travel-data-scientist/SKILL.md"
DS_REFERENCE = ROOT / ".agents/skills/travel-data-scientist/references/domain-review.md"
PROFILE_DOC = ROOT / "docs/data/data-science-agent.md"
LOOP_SKILL = ROOT / ".agents/skills/travel-issue-agent-loop/SKILL.md"
LOOP_REFERENCE = ROOT / ".agents/skills/travel-issue-agent-loop/references/agent-loop.md"
AGENTS = ROOT / "AGENTS.md"
WORKFLOW = ROOT / "docs/agent-workflow.md"


class DataScientistSkillDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = DS_SKILL.read_text(encoding="utf-8")
        cls.reference = DS_REFERENCE.read_text(encoding="utf-8")
        cls.profile = PROFILE_DOC.read_text(encoding="utf-8")
        cls.loop_skill = LOOP_SKILL.read_text(encoding="utf-8")
        cls.loop_reference = LOOP_REFERENCE.read_text(encoding="utf-8")
        cls.agents = AGENTS.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_domain_first_problem_alignment_gate(self) -> None:
        self.assertIn("name: travel-data-scientist", self.skill)
        for phrase in (
            "Prediction time",
            "Task type",
            "Candidate/exposure assumption",
            "Implicit feedback",
            "unknown, not automatically negative",
            "classification, retrieval, and ranking",
            "Cohort comparability",
        ):
            self.assertIn(phrase, self.skill)

    def test_travel_log_semantics_and_leakage_are_explicit(self) -> None:
        for token in (
            "TRAVELER_ID", "TRAVEL_ID", "TN_VISIT_AREA_INFO", "TN_POI_MASTER",
            "DGSTFN", "REVISIT_INTENTION", "RCMDTN_INTENTION", "post-visit feedback",
        ):
            self.assertIn(token, self.skill)
        self.assertIn("absence of a visit is not proof of dislike", self.reference)

    def test_domain_reference_distinguishes_direct_proxy_and_mismatch(self) -> None:
        for phrase in ("**direct**", "**proxy**", "**mismatch**", "Recall@K", "NDCG@K", "unvisited = dislike"):
            self.assertIn(phrase, self.reference)

    def test_issue_loop_routes_to_data_science_profile(self) -> None:
        for text in (self.loop_skill, self.loop_reference, self.agents, self.workflow):
            self.assertIn("herdr-data-science", text)
            self.assertIn("travel-data-scientist", text)
        self.assertIn("do not fall back", self.loop_skill.casefold())

    def test_profile_is_least_privilege_named_permissions(self) -> None:
        self.assertIn("[permissions.herdr-data-science.filesystem]", self.profile)
        self.assertIn('":workspace_roots" = "write"', self.profile)
        self.assertIn('"/replace/with/approved/aihub/raw-root" = "read"', self.profile)
        self.assertIn('default_permissions="herdr-data-science"', self.profile)
        self.assertIn("sandbox_mode", self.profile)
        self.assertIn("sandbox_workspace_write", self.profile)
        self.assertIn("함께 사용하지 않는다", self.profile)
        self.assertIn("실제 raw root에 write/delete를 시도해 권한을 시험하지 않는다", self.profile)

    def test_handoff_separates_evidence_and_uncertainty(self) -> None:
        combined = "\n".join((self.skill, self.reference, self.profile))
        for phrase in (
            "facts", "interpretation/inference", "unresolved limitations", "next decision",
            "Direct / proxy / mismatch", "Negative semantics",
        ):
            self.assertIn(phrase, combined)

    def test_machine_specific_paths_are_not_committed(self) -> None:
        combined = "\n".join((self.skill, self.reference, self.profile))
        self.assertNotIn("/home/", combined)
        self.assertNotIn("/Users/", combined)
        self.assertNotIn("C:" + chr(92) + "Users" + chr(92), combined)
        self.assertIn("/replace/with/approved/aihub/raw-root", self.profile)

    def test_required_local_links_exist(self) -> None:
        for path in (DS_SKILL, DS_REFERENCE, PROFILE_DOC, LOOP_SKILL, LOOP_REFERENCE, AGENTS, WORKFLOW):
            self.assertTrue(path.is_file(), path)

    def test_markdown_fences_are_balanced(self) -> None:
        for source in (DS_SKILL, DS_REFERENCE, PROFILE_DOC, LOOP_SKILL, LOOP_REFERENCE):
            fences = [line for line in source.read_text(encoding="utf-8").splitlines() if line.startswith("```")]
            self.assertEqual(len(fences) % 2, 0, f"Unbalanced fenced code block in {source}")


if __name__ == "__main__":
    unittest.main()
