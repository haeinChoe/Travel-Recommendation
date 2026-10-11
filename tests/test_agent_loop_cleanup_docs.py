"""Synthetic checks for the Issue workspace cleanup policy documentation."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents/skills/travel-issue-agent-loop/SKILL.md"
REFERENCE = ROOT / ".agents/skills/travel-issue-agent-loop/references/agent-loop.md"


def _cleanup_matrix(markdown: str) -> dict[tuple[str, str], str]:
    section = markdown.split("### Cleanup decision matrix\n", maxsplit=1)[1].split("\n### ", maxsplit=1)[0]
    rows = [line for line in section.splitlines() if line.startswith("|")]
    parsed = [[cell.strip() for cell in line.strip("|").split("|")] for line in rows]
    header, body = parsed[0], parsed[2:]
    if header != ["Operation", "Guard", "Required condition"]:
        raise AssertionError(f"Unexpected cleanup matrix columns: {header!r}")
    matrix = {}
    for row in body:
        if len(row) != len(header):
            raise AssertionError(f"Malformed cleanup matrix row: {row!r}")
        key = (row[0], row[1])
        if key in matrix:
            raise AssertionError(f"Duplicate cleanup matrix guard: {key!r}")
        matrix[key] = row[2]
    return matrix


class CleanupDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = SKILL.read_text(encoding="utf-8")
        cls.reference = REFERENCE.read_text(encoding="utf-8")
        cls.matrix = _cleanup_matrix(cls.reference)

    def test_matrix_covers_distinct_operations_and_safety_guards(self) -> None:
        linked = {
            guard
            for operation, guard in self.matrix
            if operation == "linked worktree removal"
        }
        plain = {
            guard
            for operation, guard in self.matrix
            if operation == "plain workspace closure"
        }
        self.assertEqual(
            linked,
            {
                "target",
                "authorization",
                "workspace",
                "git_clean",
                "protected_branch",
                "common_git_dir",
                "mutation",
                "local_branch",
                "readback",
            },
        )
        self.assertEqual(
            plain,
            {
                "target",
                "authorization",
                "workspace",
                "repository_guard",
                "cascade_reason",
                "mutation",
                "readback",
            },
        )

    def test_common_git_dir_is_not_a_linked_removal_veto(self) -> None:
        condition = self.matrix[("linked worktree removal", "common_git_dir")].casefold()
        self.assertIn("share", condition)
        self.assertIn("normal", condition)
        self.assertIn("alone does not block", condition)
        self.assertIn("not a blanket restriction", self.matrix[("plain workspace closure", "cascade_reason")].casefold())

    def test_workspace_close_alone_has_repository_exclusivity_and_cascade_guard(self) -> None:
        repository_guard = self.matrix[("plain workspace closure", "repository_guard")].casefold()
        cascade_reason = self.matrix[("plain workspace closure", "cascade_reason")].casefold()
        self.assertIn("valid caller identity", repository_guard)
        self.assertIn("exclusive repository ownership", repository_guard)
        self.assertIn("another herdr workspace shares", repository_guard)
        self.assertIn("can cascade", cascade_reason)

    def test_worktree_guard_covers_ignored_files_branch_deletion_and_readback(self) -> None:
        clean = self.matrix[("linked worktree removal", "git_clean")]
        branch = self.matrix[("linked worktree removal", "local_branch")]
        readback = self.matrix[("linked worktree removal", "readback")]
        self.assertIn("--untracked-files=all --ignored=matching", clean)
        self.assertIn("git branch -d", branch)
        self.assertIn("remote branch", branch)
        self.assertIn("`-D`", branch)
        self.assertIn("git worktree list --porcelain", readback)

    def test_refusal_procedure_names_the_observed_blocker_and_forbids_bypass(self) -> None:
        self.assertIn("Caller workspace identity is unavailable; refusing teardown", self.reference)
        self.assertIn("not a shared-`.git` refusal", self.reference)
        self.assertIn("blind retries", self.reference)
        self.assertIn("raw APIs", self.reference)

    def test_skill_routes_to_the_operation_specific_reference(self) -> None:
        self.assertIn("linked-worktree removal and plain-workspace closure", self.skill)
        self.assertIn("Do not apply that close-only guard", self.skill)

    def test_local_markdown_links_resolve(self) -> None:
        for source in (SKILL, REFERENCE):
            text = source.read_text(encoding="utf-8")
            for raw_target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
                target = raw_target.split(maxsplit=1)[0].strip("<>")
                if target.startswith(("https://", "http://", "mailto:", "#")):
                    continue
                path_text, separator, fragment = target.partition("#")
                destination = (source.parent / path_text).resolve()
                self.assertTrue(destination.is_file(), f"Broken link in {source}: {target}")
                if separator and fragment:
                    headings = {
                        re.sub(r"[^a-z0-9 -]", "", heading.casefold()).replace(" ", "-")
                        for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", destination.read_text(encoding="utf-8"), re.M)
                    }
                    self.assertIn(fragment.casefold(), headings, f"Broken heading link in {source}: {target}")

    def test_markdown_fenced_code_blocks_are_balanced(self) -> None:
        for source in (SKILL, REFERENCE):
            fence_lines = [
                line
                for line in source.read_text(encoding="utf-8").splitlines()
                if line.startswith("```")
            ]
            self.assertEqual(len(fence_lines) % 2, 0, f"Unbalanced fenced code block in {source}")


if __name__ == "__main__":
    unittest.main()
