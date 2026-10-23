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
        linked_session = {
            guard
            for operation, guard in self.matrix
            if operation == "linked workspace-session closure"
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
                "outputs_preserved",
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
            linked_session,
            {"target", "authorization", "workspace", "checkout_preservation", "mutation", "readback"},
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

    def test_plain_workspace_close_has_provenance_owner_and_group_close_guard(self) -> None:
        repository_guard = self.matrix[("plain workspace closure", "repository_guard")].casefold()
        cascade_reason = self.matrix[("plain workspace closure", "cascade_reason")].casefold()
        self.assertIn("valid caller identity", repository_guard)
        self.assertIn("exact primary-checkout ownership", repository_guard)
        self.assertIn("rejects mapped linked child rows owned by the target", repository_guard)
        self.assertIn("other primary-close attempts may be refused", repository_guard)
        self.assertIn("secondary plain workspace may close", repository_guard)
        self.assertIn("never passes group intent", cascade_reason)

    def test_linked_session_close_preserves_checkout_and_uses_guarded_mcp_only(self) -> None:
        preservation = self.matrix[("linked workspace-session closure", "checkout_preservation")].casefold()
        mutation = self.matrix[("linked workspace-session closure", "mutation")].casefold()
        readback = self.matrix[("linked workspace-session closure", "readback")].casefold()
        self.assertIn("at most one derived `open_workspace_id`", preservation)
        self.assertIn("from a linked-worktree row", preservation)
        self.assertIn("path, branch, linked flag", preservation)
        self.assertIn("git worktree list --porcelain", preservation)
        self.assertIn("--untracked-files=all --ignored=matching", preservation)
        self.assertIn("git worktree list --porcelain", readback)
        self.assertIn("--untracked-files=all --ignored=matching", readback)
        self.assertIn("unchanged", readback)
        self.assertIn("guarded mcp", mutation)
        self.assertIn("herdr_workspace_close", mutation)
        self.assertIn("without `--group`", mutation)
        self.assertIn("never use cli", mutation)

    def test_worktree_guard_covers_ignored_files_branch_deletion_and_readback(self) -> None:
        clean = self.matrix[("linked worktree removal", "git_clean")]
        branch = self.matrix[("linked worktree removal", "local_branch")]
        readback = self.matrix[("linked worktree removal", "readback")]
        self.assertIn("--untracked-files=all --ignored=matching", clean)
        self.assertIn("git branch -d", branch)
        self.assertIn("remote branch", branch)
        self.assertIn("`-D`", branch)
        self.assertIn("git worktree list --porcelain", readback)

    def test_issue_outputs_are_semantically_validated_and_preserved_via_designated_tool(self) -> None:
        condition = self.matrix[("linked worktree removal", "outputs_preserved")].casefold()
        for phrase in (
            "output-producing agent's manifest",
            "semantically validated",
            "functions.exec` → `tools.exec_command",
            "repository/worktree state",
            "other sessions use their registered designated static tool",
            "actual primary `dev` checkout",
            "never guess or choose an arbitrary destination",
            "exact file set",
            "content equality",
            "run `git check-ignore -q -- <destination>` or its designated-tool equivalent before writing",
            "stop if not ignored",
            "verify destination git-ignore status again after copy",
            "reopen/read semantic checks",
        ):
            self.assertIn(phrase, condition)
        for text in (self.skill, self.reference):
            folded = text.casefold()
            self.assertIn("branch archive", folded)
            self.assertIn("direct git writes", folded)
            self.assertIn("schema", folded)
            self.assertIn("row counts", folded)
            self.assertIn("key integrity", folded)
        workflow = (ROOT / "docs/agent-workflow.md").read_text(encoding="utf-8").casefold()
        instructions = (ROOT / "AGENTS.md").read_text(encoding="utf-8").casefold()
        self.assertIn("static file/workspace", workflow)
        self.assertIn("functions.exec` → `tools.exec_command", workflow)
        self.assertIn("다른 세션에서는", workflow)
        self.assertIn("`git check-ignore -q -- <destination>`", workflow)
        self.assertIn("git-ignore되지 않으면 어떤 파일도 쓰기 전에 멈춘다", workflow)
        self.assertIn("복사 후 git-ignore 재확인", workflow)
        self.assertNotIn("일반 shell copy", workflow)
        self.assertIn("functions.exec` → `tools.exec_command", instructions)
        self.assertIn("다른 세션에서는", instructions)
        self.assertIn("`git check-ignore -q -- <destination>`", instructions)
        self.assertIn("ignore되지 않으면 쓰기 전에 중단", instructions)
        self.assertIn("identifying value", workflow)
        self.assertIn("aggregate evidence", workflow)
        self.assertIn("안전한 aggregate evidence", workflow)
        self.assertIn("사용자 수동 checkout/copy", instructions)
        self.assertIn("임의로 추측한 목적지", workflow)

    def test_finished_branch_cleanup_uses_the_bounded_local_cli(self) -> None:
        workflow = (ROOT / "docs/agent-workflow.md").read_text(encoding="utf-8")
        reference = self.reference
        cli = (ROOT / "scripts/maintenance/sync-finished-branches.ts").read_text(encoding="utf-8")
        for text in (workflow, reference):
            self.assertIn("scripts/maintenance/sync-finished-branches.ts", text)
            self.assertIn("--apply", text)
            self.assertIn("origin/dev", text)
            self.assertIn("git branch -d", text)
            self.assertIn("git push origin --delete", text)
            self.assertIn("plan-only", text)
            self.assertRegex(text.casefold(), r"only when requesting branch cleanup|정리를 요청할 때만")
        self.assertIn("branch 인자 없이 `--apply`", workflow.casefold())
        self.assertIn("`--apply` alone is supported", reference.casefold())
        self.assertIn('"--ff-only"', cli)
        self.assertIn('"--delete"', cli)
        self.assertIn('"-d"', cli)
        self.assertNotIn('"-D"', cli)

    def test_refusal_procedure_names_the_observed_blocker_and_forbids_bypass(self) -> None:
        self.assertIn("Caller pane identity is unavailable; refusing teardown", self.reference)
        self.assertIn("not a shared-`.git` refusal", self.reference)
        self.assertIn("blind retries", self.reference)
        self.assertIn("raw APIs", self.reference)

    def test_skill_routes_to_the_operation_specific_reference(self) -> None:
        self.assertIn("linked-worktree removal, linked workspace-session closure, and plain-workspace closure", self.skill)
        self.assertIn("Use only the guarded MCP teardown tools", self.skill)
        self.assertIn("never substitute CLI, group-close", self.skill)

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
