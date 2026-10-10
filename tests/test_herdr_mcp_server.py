from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
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
        self.caller_env = patch.dict(os.environ, {"HERDR_WORKSPACE_ID": "caller"})
        self.caller_env.start()
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
        self.caller_env.stop()

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

    def test_rejects_caller_workspace_before_reading_or_mutating(self) -> None:
        with patch.dict(os.environ, {"HERDR_WORKSPACE_ID": "target"}), patch.object(
            bridge, "_workspace_context"
        ) as context, patch.object(bridge, "_run_herdr_json") as mutation:
            with self.assertRaisesRegex(RuntimeError, "workspace running this caller"):
                bridge._mutate_tool("herdr_workspace_close", "target")
        context.assert_not_called()
        mutation.assert_not_called()

    def test_rejects_teardown_without_caller_context(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(
            bridge, "_workspace_context"
        ) as context, patch.object(bridge, "_run_herdr_json") as mutation:
            with self.assertRaisesRegex(RuntimeError, "Caller workspace identity is unavailable"):
                bridge._mutate_tool("herdr_workspace_close", "target")
        context.assert_not_called()
        mutation.assert_not_called()

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

    def test_workspace_close_rejects_shared_primary_checkout_workspace(self) -> None:
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
        worktree_commands: list[list[str]] = []

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            if command[:2] == ["workspace", "list"]:
                return [primary, target, linked_owner]
            if command[:2] == ["agent", "list"]:
                return [{"workspace_id": "target", "agent_status": "idle"}]
            if command[:2] == ["worktree", "list"]:
                worktree_commands.append(command)
                return [worktree_info, unrelated_linked_worktree]
            raise AssertionError(command)

        git_before = bridge._git(str(self.repo), "worktree", "list", "--porcelain")
        status_before = bridge._git(str(self.repo), "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching")
        with patch.object(bridge, "_collection", side_effect=collection), patch.object(
            bridge, "_run_herdr_json"
        ) as mutation:
            with self.assertRaisesRegex(RuntimeError, "shares its primary checkout"):
                bridge._mutate_tool("herdr_workspace_close", "target")

        mutation.assert_not_called()
        self.assertIn(["worktree", "list", "--workspace", "target"], worktree_commands)
        self.assertEqual(bridge._git(str(self.repo), "worktree", "list", "--porcelain"), git_before)
        self.assertEqual(
            bridge._git(str(self.repo), "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching"),
            status_before,
        )

    def test_workspace_close_rejects_repository_shared_with_caller(self) -> None:
        provenance = {
            "repo_key": str(self.repo / ".git"),
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        target = {"workspace_id": "target", "focused": False, "worktree": provenance}
        caller = {"workspace_id": "caller", "focused": True, "worktree": provenance}
        worktree_info = {
            "path": str(self.repo),
            "is_linked_worktree": False,
            "open_workspace_id": "target",
        }

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            if command[:2] == ["workspace", "list"]:
                return [target, caller]
            if command[:2] == ["agent", "list"]:
                return [{"workspace_id": "target", "agent_status": "idle"}]
            if command[:2] == ["worktree", "list"]:
                return [worktree_info]
            raise AssertionError(command)

        with patch.object(bridge, "_collection", side_effect=collection), patch.object(
            bridge, "_run_herdr_json"
        ) as mutation:
            with self.assertRaisesRegex(RuntimeError, "another workspace shares its Git repository"):
                bridge._mutate_tool("herdr_workspace_close", "target")
        mutation.assert_not_called()

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

    def test_workspace_close_rejects_nonowner_before_mutation(self) -> None:
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
            with self.assertRaisesRegex(RuntimeError, "shares its primary checkout"):
                bridge._mutate_tool("herdr_workspace_close", "target")
        mutation.assert_not_called()

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




if __name__ == "__main__":
    unittest.main()
