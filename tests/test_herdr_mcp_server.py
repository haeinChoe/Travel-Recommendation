from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from scripts import herdr_mcp_server as bridge


def _worktree(path: str, workspace_id: str = "target", branch: str = "feature") -> dict[str, object]:
    return {
        "path": path,
        "branch": branch,
        "is_linked_worktree": True,
        "open_workspace_id": workspace_id,
    }


def _recognized_herdr_unavailability(stderr: str) -> str | None:
    normalized = stderr.casefold()
    if "operation not permitted" in normalized or "herdr socket access denied" in normalized:
        return "Herdr socket access was denied (EPERM)"
    if any(marker in normalized for marker in ("connection refused", "not connected", "server_not_running", "server is unavailable")):
        return "Herdr server/socket is unavailable"
    return None


def _assert_disposable_source_cleanup_safe(
    source_id: str,
    target_id: str | None,
    target_path: Path,
    workspaces: list[dict[str, object]],
    worktrees: list[dict[str, object]],
    agents: list[dict[str, object]],
    git_worktree_list: str,
) -> None:
    target_path = target_path.resolve()
    if target_path.exists():
        raise AssertionError(f"Fixture target checkout still exists: {target_path}")
    if any(
        isinstance(item.get("path"), str) and Path(item["path"]).resolve() == target_path
        for item in worktrees
    ):
        raise AssertionError(f"Herdr still lists fixture target checkout: {target_path}")
    if any(
        line.startswith("worktree ")
        and Path(line.removeprefix("worktree ")).resolve() == target_path
        for line in git_worktree_list.splitlines()
    ):
        raise AssertionError(f"Git still lists fixture target checkout: {target_path}")
    if target_id is not None:
        if any(item.get("workspace_id") == target_id for item in workspaces):
            raise AssertionError(f"Fixture target workspace still exists: {target_id}")
        if any(
            item.get("is_linked_worktree") is True and item.get("open_workspace_id") == target_id
            for item in worktrees
        ):
            raise AssertionError(f"Herdr still lists linked worktrees owned by fixture target: {target_id}")
    if any(item.get("workspace_id") == source_id for item in agents):
        raise AssertionError(f"Fixture source workspace still has agents: {source_id}")


class MCPProtocolTests(unittest.TestCase):
    def test_real_integration_preflight_only_recognizes_socket_or_server_unavailable_errors(self) -> None:
        self.assertEqual(_recognized_herdr_unavailability('Error: Os { message: "Operation not permitted" }'), "Herdr socket access was denied (EPERM)")
        self.assertEqual(_recognized_herdr_unavailability("server_not_running: connection refused"), "Herdr server/socket is unavailable")
        self.assertIsNone(_recognized_herdr_unavailability("error: unrecognized subcommand 'status'"))
        self.assertIsNone(_recognized_herdr_unavailability("herdr: command not found"))
        self.assertIsNone(_recognized_herdr_unavailability("configuration error: invalid socket path"))

    def test_tools_list_has_two_strict_workspace_id_schemas(self) -> None:
        response = bridge._handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        for name in ("herdr_worktree_remove", "herdr_workspace_close"):
            self.assertEqual(
                tools[name]["inputSchema"],
                {
                    "type": "object",
                    "properties": {"workspace_id": {"type": "string", "minLength": 1, "maxLength": 256}},
                    "required": ["workspace_id"],
                    "additionalProperties": False,
                },
            )

    def test_rejects_wrong_or_extra_tool_arguments(self) -> None:
        for args in ({}, {"workspace_id": "target", "force": True}, {"workspace_id": " target"}, {"workspace_id": 4}):
            response = bridge._handle(
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "herdr_worktree_remove", "arguments": args}}
            )
            self.assertTrue(response["result"]["isError"])

    def test_disposable_source_cleanup_requires_target_gone_and_source_agent_free(self) -> None:
        with tempfile.TemporaryDirectory(prefix="herdr-source-cleanup-") as temp_dir:
            target_path = Path(temp_dir) / "checkout"
            base_worktree = {"path": str(Path(temp_dir) / "repo"), "is_linked_worktree": False}
            valid_workspaces = [{"workspace_id": "source"}]
            clean_git_worktrees = f"worktree {Path(temp_dir) / 'repo'}\n"
            _assert_disposable_source_cleanup_safe(
                "source", "target", target_path, valid_workspaces, [base_worktree], [], clean_git_worktrees
            )

            cases = (
                (
                    "target workspace remains",
                    [{"workspace_id": "source"}, {"workspace_id": "target"}],
                    [base_worktree],
                    [],
                    clean_git_worktrees,
                ),
                (
                    "target checkout remains in Herdr inventory",
                    valid_workspaces,
                    [base_worktree, {"path": str(target_path), "is_linked_worktree": True}],
                    [],
                    clean_git_worktrees,
                ),
                (
                    "target still owns a linked checkout",
                    valid_workspaces,
                    [base_worktree, {"path": str(Path(temp_dir) / "other"), "is_linked_worktree": True, "open_workspace_id": "target"}],
                    [],
                    clean_git_worktrees,
                ),
                (
                    "source still has an agent",
                    valid_workspaces,
                    [base_worktree],
                    [{"workspace_id": "source"}],
                    clean_git_worktrees,
                ),
                (
                    "Git still lists fixture checkout",
                    valid_workspaces,
                    [base_worktree],
                    [],
                    f"{clean_git_worktrees}worktree {target_path}\n",
                ),
            )
            for label, workspaces, worktrees, agents, git_worktree_list in cases:
                with self.subTest(label=label), self.assertRaises(AssertionError):
                    _assert_disposable_source_cleanup_safe(
                        "source", "target", target_path, workspaces, worktrees, agents, git_worktree_list
                    )


class TeardownSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path(tempfile.mkdtemp(prefix="herdr-bridge-unit-"))
        self.repo = self.temp_root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "--initial-branch=base"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True)
        (self.repo / "tracked.txt").write_text("clean\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.repo, check=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root)

    def _git_worktree(self, branch: str = "feature") -> Path:
        path = self.temp_root / "checkout"
        subprocess.run(["git", "worktree", "add", "-qb", branch, str(path)], cwd=self.repo, check=True)
        return path

    def _setup_api(
        self,
        *,
        focused: bool = False,
        status: str = "idle",
        worktree: dict[str, object] | None = None,
        provenance: dict[str, object] | None = None,
    ) -> tuple[object, ...]:
        workspace = {"workspace_id": "target", "focused": focused, "worktree": provenance}
        agents = [{"workspace_id": "target", "agent_status": status}]
        worktrees = [worktree] if worktree is not None else []
        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            if command[:2] == ["workspace", "list"]:
                return [workspace]
            if command[:2] == ["agent", "list"]:
                return agents
            if command[:2] == ["worktree", "list"]:
                return worktrees
            raise AssertionError(command)
        return patch.object(bridge, "_collection", side_effect=collection), workspace, agents, worktrees

    def test_rejects_focused_or_unknown_agent_workspace(self) -> None:
        for focused, status in ((True, "idle"), (False, "working"), (False, "blocked"), (False, "unknown"), (False, None)):
            mocks, *_ = self._setup_api(focused=focused, status=status)
            with mocks, self.assertRaises(RuntimeError):
                bridge._mutate_tool("herdr_workspace_close", "target")

    def test_rejects_unlinked_and_dirty_worktrees(self) -> None:
        path = self._git_worktree()
        mocks, *_ = self._setup_api(worktree={**_worktree(str(path)), "is_linked_worktree": False})
        with mocks, self.assertRaisesRegex(RuntimeError, "not a linked"):
            bridge._mutate_tool("herdr_worktree_remove", "target")
        (path / "untracked.txt").write_text("keep\n", encoding="utf-8")
        mocks, *_ = self._setup_api(worktree=_worktree(str(path)))
        with mocks, self.assertRaisesRegex(RuntimeError, "dirty"):
            bridge._mutate_tool("herdr_worktree_remove", "target")

    def test_rejects_main_and_dev_worktree_branches(self) -> None:
        path = self._git_worktree("main") if subprocess.run(["git", "show-ref", "--verify", "--quiet", "refs/heads/main"], cwd=self.repo).returncode == 0 else None
        if path is None:
            subprocess.run(["git", "branch", "main"], cwd=self.repo, check=True)
            path = self.temp_root / "main-checkout"
            subprocess.run(["git", "worktree", "add", "-q", str(path), "main"], cwd=self.repo, check=True)
        with self.assertRaisesRegex(RuntimeError, "dev or main"):
            bridge._assert_clean_linked_worktree("target", _worktree(str(path), branch="main"))

    def test_workspace_close_rejects_missing_provenance_even_with_linked_worktree(self) -> None:
        path = self._git_worktree()
        mocks, *_ = self._setup_api(worktree=_worktree(str(path)))
        with mocks, self.assertRaisesRegex(RuntimeError, "provenance is missing or null"):
            bridge._mutate_tool("herdr_workspace_close", "target")

    def test_workspace_close_rejects_null_provenance_without_mutating(self) -> None:
        mocks, *_ = self._setup_api(provenance=None)
        with mocks, patch.object(bridge, "_run_herdr_json") as mutation:
            with self.assertRaisesRegex(RuntimeError, "provenance is missing or null"):
                bridge._mutate_tool("herdr_workspace_close", "target")
        mutation.assert_not_called()

    def test_focus_restore_targets_only_the_previously_focused_workspace(self) -> None:
        focus_reads = iter(
            [
                [
                    {"workspace_id": "original", "focused": False},
                    {"workspace_id": "other", "focused": True},
                ],
                [
                    {"workspace_id": "original", "focused": True},
                    {"workspace_id": "other", "focused": False},
                ],
            ]
        )
        with patch.object(bridge, "_collection", side_effect=lambda *_: next(focus_reads)), patch.object(
            bridge, "_run_herdr_json", return_value={"result": {}}
        ) as command:
            workspaces = bridge._run_mutation_preserving_focus(
                ["workspace", "close", "target"], "original"
            )
        self.assertEqual(bridge._focused_workspace_id(workspaces), "original")
        self.assertEqual(
            command.call_args_list,
            [
                unittest.mock.call(["workspace", "close", "target"]),
                unittest.mock.call(["workspace", "focus", "original"]),
            ],
        )

    def test_rejects_ambiguous_initial_focus(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "multiple focused"):
            bridge._focused_workspace_id(
                [
                    {"workspace_id": "one", "focused": True},
                    {"workspace_id": "two", "focused": True},
                ]
            )

    def test_workspace_close_rejects_linked_worktree_provenance(self) -> None:
        provenance = {
            "repo_key": "repo",
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.temp_root / "checkout"),
            "is_linked_worktree": True,
        }
        mocks, *_ = self._setup_api(provenance=provenance)
        with mocks, self.assertRaisesRegex(RuntimeError, "Remove the linked worktree"):
            bridge._mutate_tool("herdr_workspace_close", "target")

    def test_workspace_close_rejects_missing_provenance_flag(self) -> None:
        provenance = {
            "repo_key": "repo",
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
        }
        mocks, *_ = self._setup_api(provenance=provenance)
        with mocks, self.assertRaisesRegex(RuntimeError, "provenance is invalid"):
            bridge._mutate_tool("herdr_workspace_close", "target")

    def test_workspace_close_rejects_omitted_workspace_provenance_without_mutating(self) -> None:
        workspace = {"workspace_id": "target", "focused": False}
        worktree_info = {
            "path": str(self.repo),
            "branch": "base",
            "is_linked_worktree": False,
            "open_workspace_id": "target",
        }

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            if command[:2] == ["workspace", "list"]:
                return [workspace]
            if command[:2] == ["agent", "list"]:
                return [{"workspace_id": "target", "agent_status": "idle"}]
            if command[:2] == ["worktree", "list"]:
                return [worktree_info]
            raise AssertionError(command)

        with patch.object(bridge, "_collection", side_effect=collection), patch.object(
            bridge, "_run_herdr_json"
        ) as mutation:
            with self.assertRaisesRegex(RuntimeError, "provenance is missing"):
                bridge._mutate_tool("herdr_workspace_close", "target")
        mutation.assert_not_called()

    def test_workspace_close_rejects_wrong_provenance_flag_type(self) -> None:
        provenance = {
            "repo_key": "repo",
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": "false",
        }
        mocks, *_ = self._setup_api(provenance=provenance)
        with mocks, self.assertRaisesRegex(RuntimeError, "provenance is invalid"):
            bridge._mutate_tool("herdr_workspace_close", "target")

    def test_workspace_close_accepts_schema_valid_plain_workspace_provenance(self) -> None:
        provenance = {
            "repo_key": "repo",
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        worktree_info = {
            "path": str(self.repo),
            "branch": "base",
            "is_bare": False,
            "is_detached": False,
            "is_prunable": False,
            "is_linked_worktree": False,
            "label": "repo",
            "open_workspace_id": "target",
        }
        workspace_reads = 0

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            nonlocal workspace_reads
            if command[:2] == ["workspace", "list"]:
                workspace_reads += 1
                return [{"workspace_id": "target", "focused": False, "worktree": provenance}] if workspace_reads == 1 else []
            if command[:2] == ["agent", "list"]:
                return [{"workspace_id": "target", "agent_status": "idle"}]
            if command[:2] == ["worktree", "list"]:
                return [worktree_info]
            raise AssertionError(command)

        mocks = patch.object(bridge, "_collection", side_effect=collection)
        with mocks, patch.object(bridge, "_run_herdr_json") as mutation:
            mutation.return_value = {"result": {}}
            result = bridge._mutate_tool("herdr_workspace_close", "target")
        self.assertTrue(result["closed"])
        mutation.assert_called_once_with(["workspace", "close", "target"])

    def test_workspace_close_rejects_conflicting_inventory_provenance(self) -> None:
        provenance = {
            "repo_key": "repo",
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        worktree_info = {
            "path": str(self.repo),
            "is_linked_worktree": True,
            "open_workspace_id": "target",
        }
        mocks, *_ = self._setup_api(provenance=provenance, worktree=worktree_info)
        with mocks, self.assertRaisesRegex(RuntimeError, "inventories disagree"):
            bridge._mutate_tool("herdr_workspace_close", "target")

    def test_workspace_close_allows_plain_target_with_another_primary_checkout_owner(self) -> None:
        provenance = {
            "repo_key": str(self.repo / ".git"),
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        primary = {"workspace_id": "primary", "focused": True, "worktree": provenance}
        target = {"workspace_id": "target", "focused": False, "worktree": provenance}
        linked_owner = {"workspace_id": "agent-17", "focused": False}
        worktree_info = {
            "path": str(self.repo),
            "branch": "base",
            "is_bare": False,
            "is_detached": False,
            "is_prunable": False,
            "is_linked_worktree": False,
            "label": "repo",
            "open_workspace_id": "primary",
        }
        unrelated_linked_path = self._git_worktree("linked-agent-17")
        unrelated_linked_worktree = {
            "path": str(unrelated_linked_path),
            "is_linked_worktree": True,
            "open_workspace_id": "agent-17",
        }
        workspace_reads = 0
        worktree_commands: list[list[str]] = []

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            nonlocal workspace_reads
            if command[:2] == ["workspace", "list"]:
                workspace_reads += 1
                return [primary, target, linked_owner] if workspace_reads == 1 else [primary, linked_owner]
            if command[:2] == ["agent", "list"]:
                return [{"workspace_id": "target", "agent_status": "idle"}]
            if command[:2] == ["worktree", "list"]:
                worktree_commands.append(command)
                return [worktree_info, unrelated_linked_worktree]
            raise AssertionError(command)

        git_before = bridge._git(str(self.repo), "worktree", "list", "--porcelain")
        status_before = bridge._git(str(self.repo), "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching")
        with patch.object(bridge, "_collection", side_effect=collection), patch.object(
            bridge, "_run_herdr_json", return_value={"result": {}}
        ) as mutation:
            result = bridge._mutate_tool("herdr_workspace_close", "target")

        self.assertEqual(result, {"workspace_id": "target", "closed": True, "already_absent": False})
        mutation.assert_called_once_with(["workspace", "close", "target"])
        self.assertIn(["worktree", "list", "--cwd", str(self.repo)], worktree_commands)
        self.assertEqual(bridge._focused_workspace_id([primary]), "primary")
        self.assertEqual(bridge._git(str(self.repo), "worktree", "list", "--porcelain"), git_before)
        self.assertEqual(
            bridge._git(str(self.repo), "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching"),
            status_before,
        )

    def test_workspace_close_owner_refuses_while_other_workspace_linked_worktree_remains(self) -> None:
        provenance = {
            "repo_key": str(self.repo / ".git"),
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        owner = {"workspace_id": "owner", "focused": False, "worktree": provenance}
        target = {"workspace_id": "target", "focused": True, "worktree": provenance}
        linked_owner = {"workspace_id": "agent-17", "focused": False}
        worktree_info = {
            "path": str(self.repo),
            "is_linked_worktree": False,
            "open_workspace_id": "owner",
        }
        unrelated_linked_worktree = {
            "path": str(self.repo / "linked-agent-17"),
            "is_linked_worktree": True,
            "open_workspace_id": "agent-17",
        }

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            if command[:2] == ["workspace", "list"]:
                return [owner, target, linked_owner]
            if command[:2] == ["agent", "list"]:
                return []
            if command[:2] == ["worktree", "list"]:
                return [worktree_info, unrelated_linked_worktree]
            raise AssertionError(command)

        with patch.object(bridge, "_collection", side_effect=collection), patch.object(
            bridge, "_run_herdr_json"
        ) as mutation:
            with self.assertRaisesRegex(RuntimeError, "linked worktree remains"):
                bridge._mutate_tool("herdr_workspace_close", "owner")
        mutation.assert_not_called()

    def test_workspace_close_rejects_linked_rows_with_unknown_owners(self) -> None:
        provenance = {
            "repo_key": str(self.repo / ".git"),
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        primary = {"workspace_id": "primary", "focused": True, "worktree": provenance}
        target = {"workspace_id": "target", "focused": False, "worktree": provenance}
        primary_worktree = {
            "path": str(self.repo),
            "is_linked_worktree": False,
            "open_workspace_id": "primary",
        }
        cases = (
            ("missing owner", {"path": str(self.repo / "linked"), "is_linked_worktree": True}, [primary, target], "Linked worktree owner identity"),
            (
                "invalid owner",
                {"path": str(self.repo / "linked"), "is_linked_worktree": True, "open_workspace_id": "agent 17"},
                [primary, target],
                "Linked worktree owner identity",
            ),
            (
                "missing owner workspace",
                {"path": str(self.repo / "linked"), "is_linked_worktree": True, "open_workspace_id": "agent-17"},
                [primary, target],
                "Linked worktree owner is missing",
            ),
            (
                "target-owned linked row",
                {"path": str(self.repo / "linked"), "is_linked_worktree": True, "open_workspace_id": "target"},
                [primary, target],
                "inventories disagree",
            ),
            (
                "null linked flag on nonprimary target-owned row",
                {"path": str(self.repo / "linked"), "is_linked_worktree": None, "open_workspace_id": "target"},
                [primary, target],
                "missing or invalid linked flag",
            ),
        )
        for label, linked_worktree, workspaces, expected_error in cases:
            def collection(command: list[str], key: str) -> list[dict[str, object]]:
                if command[:2] == ["workspace", "list"]:
                    return workspaces
                if command[:2] == ["agent", "list"]:
                    return [{"workspace_id": "target", "agent_status": "idle"}]
                if command[:2] == ["worktree", "list"]:
                    return [primary_worktree, linked_worktree]
                raise AssertionError(command)

            with self.subTest(label=label), patch.object(bridge, "_collection", side_effect=collection), patch.object(
                bridge, "_run_herdr_json"
            ) as mutation:
                with self.assertRaisesRegex(RuntimeError, expected_error):
                    bridge._mutate_tool("herdr_workspace_close", "target")
                mutation.assert_not_called()

    def test_workspace_close_rejects_primary_checkout_owner_change_on_readback(self) -> None:
        provenance = {
            "repo_key": str(self.repo / ".git"),
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        primary = {"workspace_id": "primary", "focused": True, "worktree": provenance}
        target = {"workspace_id": "target", "focused": False, "worktree": provenance}
        worktree_before = {
            "path": str(self.repo),
            "is_linked_worktree": False,
            "open_workspace_id": "primary",
        }
        worktree_after = {**worktree_before, "open_workspace_id": "other"}
        workspace_reads = 0

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            nonlocal workspace_reads
            if command[:2] == ["workspace", "list"]:
                workspace_reads += 1
                return [primary, target] if workspace_reads == 1 else [primary]
            if command[:2] == ["agent", "list"]:
                return [{"workspace_id": "target", "agent_status": "idle"}]
            if command[:2] == ["worktree", "list"]:
                if "--cwd" in command:
                    return [worktree_after]
                return [worktree_before]
            raise AssertionError(command)

        with patch.object(bridge, "_collection", side_effect=collection), patch.object(
            bridge, "_run_herdr_json", return_value={"result": {}}
        ) as mutation:
            with self.assertRaisesRegex(RuntimeError, "Primary checkout ownership changed"):
                bridge._mutate_tool("herdr_workspace_close", "target")
        mutation.assert_called_once_with(["workspace", "close", "target"])

    def test_workspace_close_rejects_missing_or_unknown_primary_checkout_owner(self) -> None:
        provenance = {
            "repo_key": str(self.repo / ".git"),
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        for worktree_info, workspaces in (
            ({"path": str(self.repo), "is_linked_worktree": False}, [{"workspace_id": "target", "focused": False, "worktree": provenance}]),
            (
                {"path": str(self.repo), "is_linked_worktree": False, "open_workspace_id": "missing-owner"},
                [{"workspace_id": "target", "focused": False, "worktree": provenance}],
            ),
        ):
            def collection(command: list[str], key: str) -> list[dict[str, object]]:
                if command[:2] == ["workspace", "list"]:
                    return workspaces
                if command[:2] == ["agent", "list"]:
                    return [{"workspace_id": "target", "agent_status": "idle"}]
                if command[:2] == ["worktree", "list"]:
                    return [worktree_info]
                raise AssertionError(command)

            with patch.object(bridge, "_collection", side_effect=collection), self.assertRaisesRegex(
                RuntimeError, "owner"
            ):
                bridge._mutate_tool("herdr_workspace_close", "target")

    def test_workspace_close_rejects_invalid_primary_owner_metadata(self) -> None:
        provenance = {
            "repo_key": str(self.repo / ".git"),
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        workspaces = [
            {"workspace_id": "target", "focused": False, "worktree": provenance},
            {"workspace_id": "primary", "focused": "false", "worktree": provenance},
        ]
        worktree_info = {"path": str(self.repo), "is_linked_worktree": False, "open_workspace_id": "primary"}

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            if command[:2] == ["workspace", "list"]:
                return workspaces
            if command[:2] == ["agent", "list"]:
                return [{"workspace_id": "target", "agent_status": "idle"}]
            if command[:2] == ["worktree", "list"]:
                return [worktree_info]
            raise AssertionError(command)

        with patch.object(bridge, "_collection", side_effect=collection), self.assertRaisesRegex(
            RuntimeError, "invalid focus metadata"
        ):
            bridge._mutate_tool("herdr_workspace_close", "target")

    def test_cli_timeout_is_returned_as_a_tool_error(self) -> None:
        with patch.object(bridge.subprocess, "run", side_effect=subprocess.TimeoutExpired(["herdr"], 8)):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                bridge._run_herdr_json(["workspace", "close", "target"])

    def test_mutation_and_failed_readback_are_errors(self) -> None:
        path = self._git_worktree()
        mocks, _, _, worktrees = self._setup_api(worktree=_worktree(str(path)))
        with mocks, patch.object(bridge, "_run_herdr_json") as mutation:
            mutation.return_value = {"result": {}}
            with self.assertRaisesRegex(RuntimeError, "readback verification"):
                bridge._mutate_tool("herdr_worktree_remove", "target")
            mutation.assert_called_once_with(["worktree", "remove", "--workspace", "target"])
        self.assertTrue(path.exists())

    def test_successful_remove_uses_no_force_and_verifies_gone_state(self) -> None:
        path = self._git_worktree()
        workspace = {"workspace_id": "target", "focused": False, "worktree": None}
        workspace_reads = 0
        worktree_reads = 0

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            nonlocal workspace_reads, worktree_reads
            if command[:2] == ["workspace", "list"]:
                workspace_reads += 1
                return [workspace] if workspace_reads == 1 else []
            if command[:2] == ["agent", "list"]:
                return []
            if command[:2] == ["worktree", "list"]:
                worktree_reads += 1
                return [_worktree(str(path))] if worktree_reads == 1 else []
            raise AssertionError(command)

        def remove(command: list[str]) -> dict[str, object]:
            subprocess.run(["git", "-C", str(self.repo), "worktree", "remove", str(path)], check=True)
            return {"result": {}}

        with patch.object(bridge, "_collection", side_effect=collection), patch.object(bridge, "_run_herdr_json", side_effect=remove) as mutation:
            result = bridge._mutate_tool("herdr_worktree_remove", "target")
        self.assertEqual(result, {"workspace_id": "target", "removed": True, "already_absent": False})
        mutation.assert_called_once_with(["worktree", "remove", "--workspace", "target"])
        self.assertFalse(path.exists())
        self.assertEqual(worktree_reads, 1, "closed workspace must not be queried through scoped worktree list")

    def test_remove_queries_remaining_inventory_when_workspace_stays_open(self) -> None:
        path = self._git_worktree()
        workspace = {"workspace_id": "target", "focused": False, "worktree": None}
        worktree_reads = 0

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            nonlocal worktree_reads
            if command[:2] == ["workspace", "list"]:
                return [workspace]
            if command[:2] == ["agent", "list"]:
                return []
            if command[:2] == ["worktree", "list"]:
                worktree_reads += 1
                if worktree_reads == 1:
                    return [_worktree(str(path))]
                return [_worktree(str(self.repo), workspace_id="sibling")]
            raise AssertionError(command)

        def remove(command: list[str]) -> dict[str, object]:
            subprocess.run(["git", "-C", str(self.repo), "worktree", "remove", str(path)], check=True)
            return {"result": {}}

        with patch.object(bridge, "_collection", side_effect=collection), patch.object(
            bridge, "_run_herdr_json", side_effect=remove
        ):
            with self.assertRaisesRegex(RuntimeError, "did not pass readback verification"):
                bridge._mutate_tool("herdr_worktree_remove", "target")
        self.assertFalse(path.exists())
        self.assertEqual(worktree_reads, 2)

    def test_already_absent_target_is_an_explicit_noop(self) -> None:
        with patch.object(bridge, "_workspace_context", return_value=(None, [], [])):
            result = bridge._mutate_tool("herdr_worktree_remove", "missing")
        self.assertEqual(result, {"workspace_id": "missing", "removed": False, "already_absent": True})

    def test_close_verifies_workspace_disappears(self) -> None:
        provenance = {
            "repo_key": str(self.repo / ".git"),
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        workspace = {"workspace_id": "target", "focused": False, "worktree": provenance}
        worktree_info = {
            "path": str(self.repo),
            "branch": "base",
            "is_linked_worktree": False,
            "open_workspace_id": "target",
        }
        call = 0
        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            nonlocal call
            if command[:2] == ["workspace", "list"]:
                call += 1
                return [workspace] if call == 1 else []
            if command[:2] == ["agent", "list"]:
                return []
            if command[:2] == ["worktree", "list"]:
                return [worktree_info]
            raise AssertionError(command)
        with patch.object(bridge, "_collection", side_effect=collection), patch.object(bridge, "_run_herdr_json") as mutation:
            mutation.return_value = {"result": {}}
            result = bridge._mutate_tool("herdr_workspace_close", "target")
        self.assertEqual(result["closed"], True)
        mutation.assert_called_once_with(["workspace", "close", "target"])

    def test_close_mutation_succeeding_but_target_readback_stays_present_is_error(self) -> None:
        provenance = {
            "repo_key": str(self.repo / ".git"),
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        worktree_info = {
            "path": str(self.repo),
            "branch": "base",
            "is_linked_worktree": False,
            "open_workspace_id": "target",
        }
        mocks, *_ = self._setup_api(provenance=provenance, worktree=worktree_info)
        with mocks, patch.object(bridge, "_run_herdr_json", return_value={"result": {}}) as mutation:
            with self.assertRaisesRegex(RuntimeError, "did not pass readback verification"):
                bridge._mutate_tool("herdr_workspace_close", "target")
        mutation.assert_called_once_with(["workspace", "close", "target"])


@unittest.skipUnless(os.environ.get("HERDR_REAL_INTEGRATION") == "1", "set HERDR_REAL_INTEGRATION=1 to use a disposable real Herdr session")
class RealHerdrSubprocessIntegrationTests(unittest.TestCase):
    @staticmethod
    def _real_herdr_env(test: unittest.TestCase) -> dict[str, str]:
        env = os.environ.copy()
        env["HERDR_ENV"] = "1"
        status = subprocess.run(["herdr", "status", "server", "--json"], capture_output=True, text=True, env=env, check=False)
        if status.returncode != 0:
            unavailable = _recognized_herdr_unavailability(status.stderr)
            if unavailable is not None:
                test.skipTest(f"{unavailable} before fixture creation: {status.stderr.strip()}")
            test.fail(
                "Herdr status command failed for an unexpected reason "
                f"(exit {status.returncode}): {status.stderr.strip()}"
            )
        try:
            status_document = json.loads(status.stdout)
        except json.JSONDecodeError as exc:
            test.fail(f"Herdr status command returned invalid JSON: {exc}")
        status_result = status_document.get("result", status_document)
        if not isinstance(status_result, dict):
            test.fail("Herdr status command returned an unsupported response")
        if status_result.get("running") is False:
            test.skipTest("Herdr server is not running before fixture creation")
        if status_result.get("running") is not True:
            test.fail("Herdr status response does not contain a valid running flag")
        if status_result.get("compatible") is False:
            test.fail("Herdr server protocol is incompatible with this bridge")
        return env

    @staticmethod
    def _herdr_json(env: dict[str, str], *args: str) -> dict[str, object]:
        completed = subprocess.run(["herdr", *args], capture_output=True, text=True, env=env, check=False)
        if completed.returncode != 0:
            raise AssertionError(
                f"Herdr command {' '.join(args)!r} failed with exit {completed.returncode}: "
                f"{completed.stderr.strip()}"
            )
        try:
            document = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"Herdr command {' '.join(args)!r} returned invalid JSON: {exc}") from exc
        if not isinstance(document, dict):
            raise AssertionError(f"Herdr command {' '.join(args)!r} returned an unsupported response")
        return document

    @staticmethod
    def _workspace_records(document: dict[str, object]) -> list[dict[str, object]]:
        result = document.get("result", document)
        items = result.get("workspaces") if isinstance(result, dict) else result
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise AssertionError("Herdr returned an unsupported workspace list")
        return items

    @staticmethod
    def _worktree_records(document: dict[str, object]) -> list[dict[str, object]]:
        result = document.get("result", document)
        items = result.get("worktrees") if isinstance(result, dict) else result
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise AssertionError("Herdr returned an unsupported worktree list")
        return items

    @staticmethod
    def _focused_id(records: list[dict[str, object]]) -> str | None:
        focused = [item for item in records if item.get("focused") is True]
        if any(not isinstance(item.get("focused"), bool) for item in records) or len(focused) > 1:
            raise AssertionError("Herdr returned ambiguous focus metadata")
        if not focused:
            return None
        focused_workspace_id = focused[0].get("workspace_id")
        if not isinstance(focused_workspace_id, str) or not focused_workspace_id:
            raise AssertionError("Herdr returned invalid focused workspace metadata")
        return focused_workspace_id

    @staticmethod
    def _bridge_response(env: dict[str, str], name: str, workspace_id: str, cwd: Path) -> dict[str, object]:
        request = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": name, "arguments": {"workspace_id": workspace_id}},
        }
        result = subprocess.run(
            ["python3", str(Path(bridge.__file__).resolve())],
            input=json.dumps(request) + "\n",
            capture_output=True,
            text=True,
            env=env,
            check=True,
            cwd=cwd,
        )
        response = json.loads(result.stdout)
        if response.get("error"):
            raise AssertionError(response["error"])
        return response["result"]

    @classmethod
    def _bridge_call(cls, env: dict[str, str], name: str, workspace_id: str, cwd: Path) -> dict[str, object]:
        tool_result = cls._bridge_response(env, name, workspace_id, cwd)
        if tool_result.get("isError"):
            raise AssertionError(tool_result["content"])
        return tool_result["structuredContent"]

    @classmethod
    def _git_primary_checkout(cls, test: unittest.TestCase, cwd: Path) -> Path:
        listing = subprocess.run(
            ["git", "worktree", "list", "--porcelain"], cwd=cwd, check=True, capture_output=True, text=True
        ).stdout
        candidates: list[Path] = []
        for entry in listing.split("\n\n"):
            path_line = next((line for line in entry.splitlines() if line.startswith("worktree ")), None)
            if path_line is None:
                continue
            checkout = Path(path_line.removeprefix("worktree ")).resolve()
            if not checkout.is_dir():
                continue
            git_dir = subprocess.run(
                ["git", "-C", str(checkout), "rev-parse", "--absolute-git-dir"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            common_dir = subprocess.run(
                ["git", "-C", str(checkout), "rev-parse", "--git-common-dir"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            git_dir_path = Path(git_dir).resolve()
            common_dir_path = Path(common_dir)
            if not common_dir_path.is_absolute():
                common_dir_path = checkout / common_dir_path
            if git_dir_path == common_dir_path.resolve():
                candidates.append(checkout)
        if len(candidates) != 1:
            test.fail(f"Expected exactly one non-linked primary Git checkout, found {len(candidates)}: {candidates}")
        return candidates[0]

    def test_bridge_removes_only_its_disposable_worktree(self) -> None:
        env = self._real_herdr_env(self)
        original_focus = self._focused_id(self._workspace_records(self._herdr_json(env, "workspace", "list")))
        root = Path(tempfile.mkdtemp(prefix="herdr-bridge-integration-"))
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "--initial-branch=main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Herdr bridge test"], cwd=repo, check=True)
        (repo / "fixture.txt").write_text("disposable\n", encoding="utf-8")
        subprocess.run(["git", "add", "fixture.txt"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "disposable fixture"], cwd=repo, check=True)
        label = f"herdr-bridge-test-{uuid.uuid4().hex[:12]}"
        worktree_path = root / "checkout"
        source_id: str | None = None
        target_id: str | None = None

        failure: Exception | None = None
        try:
            created = self._herdr_json(env, "workspace", "create", "--cwd", str(repo), "--label", label, "--no-focus")
            source_id = created["result"]["workspace"]["workspace_id"]
            worktree = self._herdr_json(
                env,
                "worktree", "create", "--workspace", source_id, "--branch", f"test/{label}",
                "--base", "main", "--path", str(worktree_path), "--label", label, "--no-focus",
            )
            target_id = worktree["result"]["workspace"]["workspace_id"]
            self.assertEqual(self._focused_id(self._workspace_records(self._herdr_json(env, "workspace", "list"))), original_focus)
            self.assertEqual(self._bridge_call(env, "herdr_worktree_remove", target_id, repo)["removed"], True)
            self.assertFalse(worktree_path.exists())
            self.assertEqual(self._focused_id(self._workspace_records(self._herdr_json(env, "workspace", "list"))), original_focus)
            git_worktrees = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True).stdout
            self.assertIn(f"worktree {repo}", git_worktrees)
            self.assertNotIn(f"worktree {worktree_path}", git_worktrees)
        except Exception as exc:
            failure = exc
        finally:
            cleanup_errors = []
            # Only the IDs returned by this test's fixture creation are eligible for cleanup.
            if target_id is not None:
                try:
                    self._bridge_call(env, "herdr_worktree_remove", target_id, repo)
                except Exception as exc:
                    cleanup_errors.append(f"target cleanup: {exc}")
            if source_id is not None:
                try:
                    source_inventory = self._workspace_records(self._herdr_json(env, "workspace", "list"))
                    source_records = [item for item in source_inventory if item.get("workspace_id") == source_id]
                    if len(source_records) == 1 and source_records[0].get("worktree") is None:
                        target_worktrees = self._worktree_records(
                            self._herdr_json(env, "worktree", "list", "--cwd", str(repo))
                        )
                        agent_document = self._herdr_json(env, "agent", "list")
                        agent_result = agent_document.get("result", agent_document)
                        source_agents = agent_result.get("agents") if isinstance(agent_result, dict) else agent_result
                        if not isinstance(source_agents, list) or any(
                            not isinstance(agent, dict) for agent in source_agents
                        ):
                            raise AssertionError("Herdr returned an unsupported agent list")
                        git_worktree_list = subprocess.run(
                            ["git", "worktree", "list", "--porcelain"],
                            cwd=repo,
                            check=True,
                            capture_output=True,
                            text=True,
                        ).stdout
                        _assert_disposable_source_cleanup_safe(
                            source_id,
                            target_id,
                            worktree_path,
                            source_inventory,
                            target_worktrees,
                            source_agents,
                            git_worktree_list,
                        )
                        # Disposable-repo workspace creation does not currently expose
                        # workspace provenance, so the bridge correctly refuses this
                        # fixture-only teardown. Close only this exact ID after proving
                        # its linked target and agents are gone.
                        self._herdr_json(env, "workspace", "close", source_id)
                    elif not source_records:
                        pass
                    else:
                        self._bridge_call(env, "herdr_workspace_close", source_id, repo)
                except Exception as exc:
                    cleanup_errors.append(f"source workspace cleanup: {exc}")

            fixture_gone = False
            try:
                listed_workspaces = self._workspace_records(self._herdr_json(env, "workspace", "list"))
                fixture_ids = {value for value in (source_id, target_id) if value is not None}
                fixture_workspaces = [item for item in listed_workspaces if item.get("workspace_id") in fixture_ids]
                fixture_worktrees = self._worktree_records(self._herdr_json(env, "worktree", "list", "--cwd", str(repo)))
                if fixture_workspaces or any(
                    item.get("path") == str(worktree_path) or item.get("open_workspace_id") in fixture_ids
                    for item in fixture_worktrees
                    if isinstance(item, dict)
                ) or worktree_path.exists():
                    cleanup_errors.append("fixture workspace or worktree remains in Herdr/Git readback")
                else:
                    fixture_gone = True
            except Exception as exc:
                cleanup_errors.append(f"fixture readback: {exc}")

            try:
                current_focus = self._focused_id(self._workspace_records(self._herdr_json(env, "workspace", "list")))
                if current_focus != original_focus:
                    raise AssertionError(f"original focus changed from {original_focus!r} to {current_focus!r}")
            except Exception as exc:
                cleanup_errors.append(f"focus restoration: {exc}")

            if fixture_gone:
                shutil.rmtree(root)

        if failure is not None or cleanup_errors:
            self.fail(
                f"real Herdr integration failed ({failure}); cleanup: {cleanup_errors}; "
                f"disposable fixture path: {root if not fixture_gone else 'removed'}"
            )

    def test_bridge_closes_only_an_extra_workspace_sharing_primary_checkout(self) -> None:
        env = self._real_herdr_env(self)
        workspace_before = self._workspace_records(self._herdr_json(env, "workspace", "list"))
        original_focus = self._focused_id(workspace_before)
        primary_path = self._git_primary_checkout(self, Path.cwd())

        try:
            primary_herdr_rows = self._worktree_records(
                self._herdr_json(env, "worktree", "list", "--cwd", str(primary_path))
            )
        except Exception as exc:
            self.fail(f"Could not inspect Herdr worktrees for primary checkout {primary_path}: {exc}")
        primary_rows = [item for item in primary_herdr_rows if item.get("path") == str(primary_path)]
        if len(primary_rows) != 1 or primary_rows[0].get("is_linked_worktree") is not False:
            self.fail(
                "Expected exactly one nonlinked Herdr primary row for "
                f"{primary_path}, found: {primary_rows!r}"
            )
        owner_id = primary_rows[0].get("open_workspace_id")
        if not isinstance(owner_id, str) or not bridge.WORKSPACE_ID_PATTERN.fullmatch(owner_id):
            self.fail(f"Primary checkout {primary_path} has a missing or invalid Herdr owner ID: {owner_id!r}")
        owner_records = [item for item in workspace_before if item.get("workspace_id") == owner_id]
        if len(owner_records) != 1 or not isinstance(owner_records[0].get("focused"), bool):
            self.fail(f"Primary checkout owner {owner_id!r} is absent or invalid in Herdr workspace inventory")

        git_worktrees_before = subprocess.run(
            ["git", "worktree", "list", "--porcelain"], cwd=primary_path, check=True, capture_output=True, text=True
        ).stdout
        git_status_before = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching"],
            cwd=primary_path, check=True, capture_output=True, text=True,
        ).stdout
        label = f"herdr-shared-primary-{uuid.uuid4().hex[:12]}"
        target_id: str | None = None
        missing_provenance = False
        failure: Exception | None = None
        cleanup_errors: list[str] = []
        fixture_gone = False
        try:
            created = self._herdr_json(
                env, "workspace", "create", "--cwd", str(primary_path), "--label", label, "--no-focus"
            )
            target = created.get("result", {}).get("workspace") if isinstance(created.get("result"), dict) else None
            if not isinstance(target, dict) or not isinstance(target.get("workspace_id"), str):
                self.fail(f"Herdr returned no target workspace ID for fixture label {label!r}")
            target_id = target["workspace_id"]

            created_workspaces = self._workspace_records(self._herdr_json(env, "workspace", "list"))
            target_records = [item for item in created_workspaces if item.get("workspace_id") == target_id]
            self.assertEqual(len(target_records), 1, f"Created workspace {target_id!r} is missing from inventory")
            self.assertIs(target_records[0].get("focused"), False, "Created workspace unexpectedly has focus")
            provenance = target_records[0].get("worktree")
            missing_provenance = provenance is None
            if not missing_provenance:
                self.assertIsInstance(provenance, dict, f"Target workspace {target_id!r} has invalid provenance")
                self.assertIs(provenance.get("is_linked_worktree"), False, "Target is not a nonlinked workspace")
                self.assertEqual(Path(provenance.get("checkout_path", "")).resolve(), primary_path)
                for field in ("repo_key", "repo_name", "repo_root", "checkout_path"):
                    self.assertIsInstance(provenance.get(field), str, f"Target provenance is missing {field}")
                    self.assertTrue(provenance[field], f"Target provenance has empty {field}")
                self.assertTrue(Path(provenance["repo_root"]).is_absolute())
                self.assertTrue(Path(provenance["checkout_path"]).is_absolute())
            self.assertEqual(self._focused_id(created_workspaces), original_focus)

            owner_before_close = self._worktree_records(
                self._herdr_json(env, "worktree", "list", "--cwd", str(primary_path))
            )
            rows_before_close = [item for item in owner_before_close if item.get("path") == str(primary_path)]
            self.assertEqual(len(rows_before_close), 1)
            self.assertIs(rows_before_close[0].get("is_linked_worktree"), False)
            self.assertEqual(rows_before_close[0].get("open_workspace_id"), owner_id)

            if missing_provenance:
                response = self._bridge_response(env, "herdr_workspace_close", target_id, primary_path)
                self.assertIs(response.get("isError"), True, "Bridge accepted a target with missing provenance")
                error_text = " ".join(
                    item.get("text", "") for item in response.get("content", []) if isinstance(item, dict)
                )
                self.assertIn("provenance is missing", error_text.casefold(), error_text)
                workspaces_after_close = self._workspace_records(self._herdr_json(env, "workspace", "list"))
                self.assertIn(target_id, {item.get("workspace_id") for item in workspaces_after_close})
                owner_after_close = [item for item in workspaces_after_close if item.get("workspace_id") == owner_id]
                self.assertEqual(len(owner_after_close), 1)
                self.assertEqual(self._focused_id(workspaces_after_close), original_focus)
            else:
                result = self._bridge_call(env, "herdr_workspace_close", target_id, primary_path)
                self.assertIs(result.get("closed"), True)

                workspaces_after_close = self._workspace_records(self._herdr_json(env, "workspace", "list"))
                self.assertNotIn(target_id, {item.get("workspace_id") for item in workspaces_after_close})
                owner_after_close = [item for item in workspaces_after_close if item.get("workspace_id") == owner_id]
                self.assertEqual(len(owner_after_close), 1)
                self.assertEqual(self._focused_id(workspaces_after_close), original_focus)
            worktrees_after_close = self._worktree_records(
                self._herdr_json(env, "worktree", "list", "--cwd", str(primary_path))
            )
            primary_after_close = [item for item in worktrees_after_close if item.get("path") == str(primary_path)]
            self.assertEqual(len(primary_after_close), 1)
            self.assertIs(primary_after_close[0].get("is_linked_worktree"), False)
            self.assertEqual(primary_after_close[0].get("open_workspace_id"), owner_id)
            self.assertEqual(
                subprocess.run(
                    ["git", "worktree", "list", "--porcelain"], cwd=primary_path, check=True,
                    capture_output=True, text=True,
                ).stdout,
                git_worktrees_before,
            )
            self.assertEqual(
                subprocess.run(
                    ["git", "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching"],
                    cwd=primary_path, check=True, capture_output=True, text=True,
                ).stdout,
                git_status_before,
            )
        except Exception as exc:
            failure = exc
        finally:
            if target_id is not None:
                try:
                    if missing_provenance:
                        remaining_before_cleanup = self._workspace_records(
                            self._herdr_json(env, "workspace", "list")
                        )
                        target_before_cleanup = [
                            item for item in remaining_before_cleanup if item.get("workspace_id") == target_id
                        ]
                        self.assertEqual(len(target_before_cleanup), 1)
                        self.assertIs(target_before_cleanup[0].get("focused"), False)
                        agents = self._herdr_json(env, "agent", "list")
                        agent_result = agents.get("result", agents)
                        agent_records = agent_result.get("agents") if isinstance(agent_result, dict) else agent_result
                        self.assertIsInstance(agent_records, list, "Herdr returned unsupported agent inventory")
                        self.assertFalse(
                            any(isinstance(agent, dict) and agent.get("workspace_id") == target_id for agent in agent_records),
                            f"Test-created target {target_id} unexpectedly has an agent",
                        )
                        target_worktrees = self._worktree_records(
                            self._herdr_json(env, "worktree", "list", "--workspace", target_id)
                        )
                        self.assertFalse(
                            any(
                                item.get("is_linked_worktree") is True
                                and item.get("open_workspace_id") == target_id
                                for item in target_worktrees
                            ),
                            f"Test-created target {target_id} unexpectedly has a linked checkout",
                        )
                        # The bridge correctly refuses missing provenance. This fixture ID
                        # alone is closed through the CLI after verifying its cleanup guards.
                        self._herdr_json(env, "workspace", "close", target_id)
                    else:
                        self._bridge_call(env, "herdr_workspace_close", target_id, primary_path)
                except Exception as exc:
                    cleanup_errors.append(f"target workspace cleanup ({target_id}): {exc}")
            try:
                remaining = self._workspace_records(self._herdr_json(env, "workspace", "list"))
                target_remains = target_id is not None and any(
                    item.get("workspace_id") == target_id for item in remaining
                )
                owner_remains = [item for item in remaining if item.get("workspace_id") == owner_id]
                if target_remains or len(owner_remains) != 1:
                    cleanup_errors.append("target/owner workspace readback did not match fixture postconditions")
                if self._focused_id(remaining) != original_focus:
                    cleanup_errors.append("focus changed during shared-workspace close test")
                final_worktrees = self._worktree_records(
                    self._herdr_json(env, "worktree", "list", "--cwd", str(primary_path))
                )
                final_primary = [item for item in final_worktrees if item.get("path") == str(primary_path)]
                if (
                    len(final_primary) != 1
                    or final_primary[0].get("is_linked_worktree") is not False
                    or final_primary[0].get("open_workspace_id") != owner_id
                ):
                    cleanup_errors.append("primary checkout owner readback changed during cleanup")
                if subprocess.run(
                    ["git", "worktree", "list", "--porcelain"], cwd=primary_path, check=True,
                    capture_output=True, text=True,
                ).stdout != git_worktrees_before:
                    cleanup_errors.append("Git worktree list changed during cleanup")
                if subprocess.run(
                    ["git", "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching"],
                    cwd=primary_path, check=True, capture_output=True, text=True,
                ).stdout != git_status_before:
                    cleanup_errors.append("Git status changed during cleanup")
                fixture_gone = not target_remains and len(owner_remains) == 1
            except Exception as exc:
                cleanup_errors.append(f"shared-workspace fixture readback: {exc}")

        if failure is not None or cleanup_errors:
            self.fail(
                f"real shared-workspace integration failed ({failure}); cleanup: {cleanup_errors}; "
                f"target ID: {target_id}; target absent: {fixture_gone}"
            )


if __name__ == "__main__":
    unittest.main()
