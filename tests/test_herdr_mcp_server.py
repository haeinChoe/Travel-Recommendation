from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

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
    if "socket" in normalized and any(
        marker in normalized for marker in ("operation not permitted", "permission denied", "eperm", "eacces")
    ):
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
        self.assertEqual(_recognized_herdr_unavailability("Herdr socket access denied: EPERM"), "Herdr socket access was denied (EPERM)")
        self.assertIsNone(_recognized_herdr_unavailability("worktree: Operation not permitted"))
        self.assertIsNone(_recognized_herdr_unavailability("checkout: permission denied (EACCES)"))
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


class IsolatedMCPIntegrationTests(unittest.TestCase):
    def test_stdio_bridge_preserves_herdr_primary_group_refusal(self) -> None:
        """Exercise the MCP subprocess boundary with a guarded Herdr group-close refusal."""
        with tempfile.TemporaryDirectory(prefix="herdr-mcp-isolated-") as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            repo.mkdir()
            caller_repo = root / "caller-repo"
            caller_repo.mkdir()
            subprocess.run(["git", "init", "-q", "--initial-branch=main"], cwd=repo, check=True)
            subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            (repo / "tracked.txt").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
            linked_path = root / "linked"
            subprocess.run(["git", "worktree", "add", "-qb", "linked-fixture", str(linked_path)], cwd=repo, check=True)

            provenance = {
                "repo_key": "shared-fixture-repository",
                "repo_name": "repo",
                "repo_root": str(repo),
                "checkout_path": str(repo),
                "is_linked_worktree": False,
            }
            caller_provenance = {
                "repo_key": "caller-fixture-repository",
                "repo_name": "caller-repo",
                "repo_root": str(caller_repo),
                "checkout_path": str(caller_repo),
                "is_linked_worktree": False,
            }
            state_path = root / "herdr-state.json"
            commands_path = root / "herdr-commands.jsonl"
            state_path.write_text(
                json.dumps(
                    {
                        "workspaces": [
                            {
                                "workspace_id": "caller",
                                "focused": True,
                                "worktree": caller_provenance,
                                "_fixture_repo_key": "caller-fixture-repository",
                            },
                            {
                                "workspace_id": "target",
                                "focused": False,
                                "worktree": provenance,
                                "_fixture_repo_key": "shared-fixture-repository",
                            },
                            {"workspace_id": "unknown", "focused": False, "_fixture_repo_key": "shared-fixture-repository"},
                        ],
                        "worktrees": [
                            {
                                "path": str(repo),
                                "is_linked_worktree": False,
                                "open_workspace_id": "target",
                            },
                            {
                                "path": str(linked_path),
                                "is_linked_worktree": True,
                                "open_workspace_id": "unknown",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            worktrees_before = json.loads(state_path.read_text(encoding="utf-8"))["worktrees"]
            git_worktrees_before = subprocess.run(
                ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            git_status_before = bridge._git_status_snapshot([str(repo), str(linked_path)])

            bin_dir = root / "bin"
            bin_dir.mkdir()
            fake_herdr = bin_dir / "herdr"
            fake_herdr.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, pathlib, sys\n"
                "state_path = pathlib.Path(os.environ['HERDR_TEST_STATE'])\n"
                "commands_path = pathlib.Path(os.environ['HERDR_TEST_COMMANDS'])\n"
                "args = sys.argv[1:]\n"
                "with commands_path.open('a', encoding='utf-8') as stream: stream.write(json.dumps(args) + '\\n')\n"
                "state = json.loads(state_path.read_text(encoding='utf-8'))\n"
                "if args == ['pane', 'current', '--current']:\n"
                "    result = {'type': 'pane_info', 'pane': {'pane_id': 'fixture-pane', 'workspace_id': 'caller', 'focused': True}}\n"
                "elif args[:2] == ['status', 'server']:\n"
                "    result = {'status': 'running', 'running': True, 'version': '0.9.3', 'protocol': 22, 'compatible': True}\n"
                "elif args[:2] == ['workspace', 'list']:\n"
                "    result = {'workspaces': state['workspaces']}\n"
                "elif args[:2] == ['agent', 'list']:\n"
                "    result = {'agents': []}\n"
                "elif args[:2] == ['worktree', 'list']:\n"
                "    result = {'worktrees': state['worktrees']}\n"
                "elif args[:2] == ['workspace', 'close']:\n"
                "    print(json.dumps({'error': {'code': 'workspace_group_close_required', 'message': 'close primary and linked workspaces together'}}), file=sys.stderr); sys.exit(1)\n"
                "else:\n"
                "    print('unsupported fixture command: ' + ' '.join(args), file=sys.stderr); sys.exit(2)\n"
                "print(json.dumps({'result': result}))\n",
                encoding="utf-8",
            )
            fake_herdr.chmod(0o755)

            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{bin_dir}{os.pathsep}{environment.get('PATH', '')}",
                    "HERDR_ENV": "1",
                    "HERDR_PANE_ID": "fixture-pane",
                    "HERDR_WORKSPACE_ID": "ignored-stale-workspace",
                    "HERDR_TEST_STATE": str(state_path),
                    "HERDR_TEST_COMMANDS": str(commands_path),
                }
            )
            request = {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "herdr_workspace_close", "arguments": {"workspace_id": "target"}},
            }
            completed = subprocess.run(
                [sys.executable, str(Path(bridge.__file__).resolve())],
                input=json.dumps(request) + "\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
                cwd=root,
                timeout=10,
                check=True,
            )

            response = json.loads(completed.stdout)
            self.assertTrue(response["result"]["isError"])
            self.assertIn("Herdr refused to close a primary workspace", response["result"]["content"][0]["text"])
            after = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [row["workspace_id"] for row in after["workspaces"]],
                ["caller", "target", "unknown"],
                "the invoking, target, and unclassified workspaces must survive the rejected close",
            )
            self.assertEqual(after["worktrees"], worktrees_before)
            commands = [json.loads(line) for line in commands_path.read_text(encoding="utf-8").splitlines()]
            close_commands = [command for command in commands if command[:2] == ["workspace", "close"]]
            self.assertEqual(close_commands, [["workspace", "close", "target"]])
            self.assertEqual((repo / "tracked.txt").read_text(encoding="utf-8"), "fixture\n")
            self.assertEqual(
                subprocess.run(
                    ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout,
                git_worktrees_before,
            )
            self.assertEqual(bridge._git_status_snapshot([str(repo), str(linked_path)]), git_status_before)


class WorkspaceCloseVersionTests(unittest.TestCase):
    def test_guarded_close_version_detection(self) -> None:
        for version, expected in (("0.9.0", True), ("0.9.3", True), ("1.0.0", True), ("0.8.2", False)):
            with self.subTest(version=version), patch.object(
                bridge, "_run_herdr_json", return_value={"result": {"version": version}}
            ) as status:
                self.assertEqual(bridge._supports_guarded_workspace_close(), expected)
                status.assert_called_once_with(["status", "server", "--json"])

        for document in ({"result": {"version": "unknown"}}, {"result": {}}):
            with self.subTest(document=document), patch.object(
                bridge, "_run_herdr_json", return_value=document
            ):
                with self.assertRaisesRegex(RuntimeError, "Cannot verify Herdr 0.9.0 or newer"):
                    bridge._supports_guarded_workspace_close()


class TeardownSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.caller_env = patch.dict(
            os.environ,
            {"HERDR_PANE_ID": "fixture-caller-pane", "HERDR_WORKSPACE_ID": "ignored-stale-workspace"},
        )
        self.caller_env.start()
        self.caller_context = patch.object(bridge, "_caller_workspace_id", return_value="caller")
        self.caller_context.start()
        self.safe_close_support = patch.object(bridge, "_supports_guarded_workspace_close", return_value=True)
        self.safe_close_support.start()
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
        self.safe_close_support.stop()
        self.caller_context.stop()
        self.caller_env.stop()

    def _git_worktree(self, branch: str = "feature", checkout_name: str = "checkout") -> Path:
        path = self.temp_root / checkout_name
        subprocess.run(["git", "worktree", "add", "-qb", branch, str(path)], cwd=self.repo, check=True)
        return path

    def _with_caller(self, workspaces: list[dict[str, object]]) -> list[dict[str, object]]:
        if any(item.get("workspace_id") == "caller" for item in workspaces):
            return workspaces
        return [
            *workspaces,
            {
                "workspace_id": "caller",
                "focused": False,
                "worktree": {"repo_key": "caller-fixture-repository"},
            },
        ]

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
                return self._with_caller([workspace])
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

    def test_rejects_caller_workspace_before_reading_agents_or_mutating(self) -> None:
        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            if command[:2] == ["workspace", "list"]:
                return [{"workspace_id": "target", "focused": False}]
            raise AssertionError(command)

        for name in ("herdr_worktree_remove", "herdr_workspace_close"):
            with self.subTest(name=name), patch.object(
                bridge, "_caller_workspace_id", return_value="target"
            ), patch.object(bridge, "_collection", side_effect=collection) as inventory, patch.object(
                bridge, "_run_herdr_json"
            ) as mutation:
                with self.assertRaisesRegex(RuntimeError, "workspace running this caller"):
                    bridge._mutate_tool(name, "target")
            inventory.assert_called_once_with(["workspace", "list"], "workspaces")
            mutation.assert_not_called()

    @staticmethod
    def _pane_info(workspace_id: str, *, focused: bool = False) -> dict[str, object]:
        return {
            "result": {
                "type": "pane_info",
                "pane": {"pane_id": "current-pane", "workspace_id": workspace_id, "focused": focused},
            }
        }

    def _use_real_caller_context(self) -> None:
        self.caller_context.stop()

    def test_moved_nonfocused_pane_uses_pane_current_not_stale_workspace_env(self) -> None:
        self._use_real_caller_context()
        with patch.dict(
            os.environ,
            {"HERDR_PANE_ID": "launch-pane-alias", "HERDR_WORKSPACE_ID": "stale-launch-workspace"},
        ), patch.object(bridge, "_run_herdr_json", return_value=self._pane_info("moved-workspace")) as pane_call:
            self.assertEqual(bridge._caller_workspace_id(), "moved-workspace")
        pane_call.assert_called_once_with(["pane", "current", "--current"])

    def test_caller_identity_requires_exactly_one_inventory_match_before_agents(self) -> None:
        self._use_real_caller_context()
        workspaces = [
            {"workspace_id": "moved-workspace", "focused": False},
            {"workspace_id": "other-focused-workspace", "focused": True},
        ]

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            if command[:2] == ["workspace", "list"]:
                return workspaces
            raise AssertionError(f"unexpected inventory read: {command}")

        with patch.object(bridge, "_run_herdr_json", return_value=self._pane_info("moved-workspace")) as pane_call, patch.object(
            bridge, "_collection", side_effect=collection
        ) as inventory:
            result = bridge._mutate_tool("herdr_workspace_close", "absent-target")
        self.assertTrue(result["already_absent"])
        pane_call.assert_called_once_with(["pane", "current", "--current"])
        inventory.assert_called_once_with(["workspace", "list"], "workspaces")

    def test_denies_missing_closed_malformed_or_failed_pane_context_before_inventory_or_mutation(self) -> None:
        self._use_real_caller_context()
        cases = (
            ("missing", {}, None, "Caller pane identity is unavailable"),
            ("invalid env", {"HERDR_PANE_ID": "bad pane"}, None, "Caller pane identity is unavailable"),
            ("closed pane", {"HERDR_PANE_ID": "caller-pane"}, RuntimeError("Herdr CLI failed with exit status 1"), "Herdr CLI failed"),
            (
                "no workspace-id fallback",
                {"HERDR_PANE_ID": "caller-pane", "HERDR_WORKSPACE_ID": "target"},
                RuntimeError("Herdr CLI failed with exit status 1"),
                "Herdr CLI failed",
            ),
            ("timeout", {"HERDR_PANE_ID": "caller-pane"}, RuntimeError("Herdr command timed out after 8 seconds"), "timed out"),
            ("wrong result type", {"HERDR_PANE_ID": "caller-pane"}, {"result": {"type": "workspace_info", "pane": {"workspace_id": "caller"}}}, "invalid caller pane context"),
            ("missing CLI result wrapper", {"HERDR_PANE_ID": "caller-pane"}, {"type": "pane_info", "pane": {"workspace_id": "caller"}}, "invalid caller pane context"),
            ("missing pane", {"HERDR_PANE_ID": "caller-pane"}, {"result": {"type": "pane_info"}}, "invalid caller pane context"),
            ("missing workspace", {"HERDR_PANE_ID": "caller-pane"}, {"result": {"type": "pane_info", "pane": {"pane_id": "private-pane"}}}, "invalid caller pane workspace context"),
            ("invalid workspace", {"HERDR_PANE_ID": "caller-pane"}, self._pane_info("bad workspace"), "invalid caller pane workspace context"),
        )
        for label, environment, response, error in cases:
            with self.subTest(label=label), patch.dict(os.environ, environment, clear=True), patch.object(
                bridge, "_run_herdr_json", side_effect=response if isinstance(response, Exception) else None,
                return_value=response if not isinstance(response, Exception) else None,
            ) as pane_call, patch.object(bridge, "_collection") as inventory:
                with self.assertRaisesRegex(RuntimeError, error):
                    bridge._mutate_tool("herdr_workspace_close", "target")
                inventory.assert_not_called()
                if environment.get("HERDR_PANE_ID") == "caller-pane":
                    pane_call.assert_called_once_with(["pane", "current", "--current"])
                else:
                    pane_call.assert_not_called()

        secret_markers = ("private-pane", "/private/workspace", "private-pid")
        with patch.dict(os.environ, {"HERDR_PANE_ID": "caller-pane"}, clear=True), patch.object(
            bridge,
            "_run_herdr_json",
            return_value={
                "result": {
                    "type": "pane_info",
                    "pane": {
                        "pane_id": secret_markers[0],
                        "workspace_id": "bad workspace",
                        "cwd": secret_markers[1],
                        "pid": secret_markers[2],
                    },
                }
            },
        ), patch.object(bridge, "_collection") as inventory:
            with self.assertRaises(RuntimeError) as raised:
                bridge._mutate_tool("herdr_workspace_close", "target")
        inventory.assert_not_called()
        for marker in secret_markers:
            self.assertNotIn(marker, str(raised.exception))

    def test_denies_mismatched_or_duplicate_inventory_without_agent_inspection_or_mutation(self) -> None:
        self._use_real_caller_context()
        cases = (
            ("missing match", [{"workspace_id": "other", "focused": False}], "missing from the Herdr inventory"),
            (
                "duplicate match",
                [
                    {"workspace_id": "caller-current", "focused": False},
                    {"workspace_id": "caller-current", "focused": True},
                    {"workspace_id": "target", "focused": False},
                ],
                "identity is ambiguous",
            ),
        )
        for label, workspaces, error in cases:
            def collection(command: list[str], key: str) -> list[dict[str, object]]:
                if command[:2] == ["workspace", "list"]:
                    return workspaces
                raise AssertionError(f"unexpected inventory read: {command}")

            with self.subTest(label=label), patch.dict(
                os.environ, {"HERDR_PANE_ID": "caller-pane", "HERDR_WORKSPACE_ID": "target"}, clear=True
            ), patch.object(bridge, "_run_herdr_json", return_value=self._pane_info("caller-current")) as pane_call, patch.object(
                bridge, "_collection", side_effect=collection
            ) as inventory:
                with self.assertRaisesRegex(RuntimeError, error):
                    bridge._mutate_tool("herdr_workspace_close", "target")
            pane_call.assert_called_once_with(["pane", "current", "--current"])
            self.assertEqual(inventory.call_args_list, [call(["workspace", "list"], "workspaces")])

    def test_rechecks_pane_context_before_mutation_and_refuses_move_into_target(self) -> None:
        target = {"workspace_id": "target", "focused": False, "worktree": None}
        caller = {"workspace_id": "caller", "focused": False}
        with patch.object(bridge, "_caller_workspace_id", side_effect=["caller", "target"]), patch.object(
            bridge, "_workspace_context", return_value=(target, [caller, target], [])
        ), patch.object(bridge, "_focused_workspace_id", return_value=None), patch.object(
            bridge, "_assert_not_focused"
        ), patch.object(bridge, "_assert_agents_settled"), patch.object(
            bridge, "_supports_guarded_workspace_close", return_value=True
        ), patch.object(bridge, "_worktrees_for", return_value=[]), patch.object(
            bridge, "_assert_plain_workspace_provenance", return_value=("owner", "fixture")
        ), patch.object(bridge, "_git_status_snapshot", return_value=[]), patch.object(
            bridge, "_git_worktree_snapshot", return_value=[]
        ), patch.object(bridge, "_collection") as inventory, patch.object(
            bridge, "_run_mutation_preserving_focus"
        ) as mutation:
            with self.assertRaisesRegex(RuntimeError, "changed during teardown checks"):
                bridge._mutate_tool("herdr_workspace_close", "target")
        inventory.assert_not_called()
        mutation.assert_not_called()

    def test_missing_target_returns_noop_without_reading_agents_or_mutating(self) -> None:
        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            if command[:2] == ["workspace", "list"]:
                return [{"workspace_id": "caller", "focused": True}]
            raise AssertionError(f"unexpected inventory read: {command}")

        expected = {
            "herdr_worktree_remove": {"workspace_id": "missing", "removed": False, "already_absent": True},
            "herdr_workspace_close": {"workspace_id": "missing", "closed": False, "already_absent": True},
        }
        for name, result in expected.items():
            with self.subTest(name=name), patch.dict(os.environ, {"HERDR_WORKSPACE_ID": "caller"}), patch.object(
                bridge, "_collection", side_effect=collection
            ) as inventory, patch.object(bridge, "_run_herdr_json") as mutation:
                self.assertEqual(bridge._mutate_tool(name, "missing"), result)
            inventory.assert_called_once_with(["workspace", "list"], "workspaces")
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

    def test_workspace_close_rejects_linked_worktree_without_exact_mapping(self) -> None:
        provenance = {
            "repo_key": "repo",
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.temp_root / "checkout"),
            "is_linked_worktree": True,
        }
        mocks, *_ = self._setup_api(provenance=provenance)
        with mocks, self.assertRaisesRegex(RuntimeError, "missing or ambiguous"):
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
                return self._with_caller([workspace])
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

    def test_workspace_close_rejects_malformed_target_repository_key(self) -> None:
        for repo_key in (" \t ", "target\nrepository"):
            provenance = {
                "repo_key": repo_key,
                "repo_name": "repo",
                "repo_root": str(self.repo),
                "checkout_path": str(self.repo),
                "is_linked_worktree": False,
            }
            mocks, *_ = self._setup_api(provenance=provenance)
            with self.subTest(repo_key=repr(repo_key)), mocks, patch.object(
                bridge, "_run_herdr_json"
            ) as mutation:
                with self.assertRaisesRegex(RuntimeError, "provenance is invalid"):
                    bridge._mutate_tool("herdr_workspace_close", "target")
                mutation.assert_not_called()

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
        caller = {"workspace_id": "caller", "focused": True, "worktree": {"repo_key": "caller-fixture-repository"}}

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            nonlocal workspace_reads
            if command[:2] == ["workspace", "list"]:
                workspace_reads += 1
                return [{"workspace_id": "target", "focused": False, "worktree": provenance}, caller] if workspace_reads == 1 else [caller]
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

    def test_workspace_close_closes_linked_session_and_preserves_dirty_checkout(self) -> None:
        linked_path = self._git_worktree("linked-session", "linked-session-checkout")
        (linked_path / "tracked.txt").write_text("dirty linked content\n", encoding="utf-8")
        exclude_file = self.repo / ".git" / "info" / "exclude"
        with exclude_file.open("a", encoding="utf-8") as stream:
            stream.write("preserved-ignored.txt\n")
        ignored_file = linked_path / "preserved-ignored.txt"
        ignored_file.write_text("ignored results remain\n", encoding="utf-8")

        provenance = {
            "repo_key": str(self.repo / ".git"),
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(linked_path),
            "is_linked_worktree": True,
        }
        caller = {"workspace_id": "caller", "focused": True, "worktree": {"repo_key": "caller-repo"}}
        target = {"workspace_id": "target", "focused": False, "worktree": provenance}
        peer_provenance = {
            "repo_key": "peer-repository",
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        derived_link = {
            "path": str(self.repo / "peer-linked-checkout"),
            "branch": "agent/29-popularity-baseline",
            "is_linked_worktree": True,
            "open_workspace_id": "target",
        }
        peer = {
            "workspace_id": "peer",
            "focused": False,
            "worktree": peer_provenance,
            "worktrees": [derived_link],
        }
        peer_after_close = {
            **peer,
            "worktrees": [{key: value for key, value in derived_link.items() if key != "open_workspace_id"}],
        }
        linked_row = {
            "path": str(linked_path),
            "branch": "linked-session",
            "is_linked_worktree": True,
            "open_workspace_id": "target",
        }
        initial_workspaces = [caller, target, peer]
        remaining_workspaces = [caller, peer_after_close]
        workspace_reads = 0
        commands: list[list[str]] = []

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            nonlocal workspace_reads
            if command[:2] == ["workspace", "list"]:
                workspace_reads += 1
                return initial_workspaces if workspace_reads == 1 else remaining_workspaces
            if command[:2] == ["agent", "list"]:
                return [{"workspace_id": "target", "agent_status": "done"}]
            if command[:2] == ["worktree", "list"]:
                self.assertEqual(command, ["worktree", "list", "--workspace", "target"])
                return [linked_row]
            raise AssertionError(command)

        def run(command: list[str]) -> dict[str, object]:
            commands.append(command)
            if command == ["workspace", "close", "target"]:
                return {"result": {}}
            raise AssertionError(command)

        git_before = bridge._git_worktree_snapshot([str(linked_path)])
        status_before = bridge._git_status_snapshot([str(linked_path)])
        self.assertIn("M tracked.txt", status_before[str(linked_path.resolve())])
        self.assertIn("!! preserved-ignored.txt", status_before[str(linked_path.resolve())])
        with patch.object(bridge, "_collection", side_effect=collection), patch.object(
            bridge, "_run_herdr_json", side_effect=run
        ):
            result = bridge._mutate_tool("herdr_workspace_close", "target")

        self.assertEqual(result, {"workspace_id": "target", "closed": True, "already_absent": False})
        self.assertEqual(commands, [["workspace", "close", "target"]])
        self.assertEqual(workspace_reads, 3)
        self.assertTrue(linked_path.is_dir())
        self.assertEqual((linked_path / "tracked.txt").read_text(encoding="utf-8"), "dirty linked content\n")
        self.assertEqual(ignored_file.read_text(encoding="utf-8"), "ignored results remain\n")
        self.assertEqual(bridge._git_worktree_snapshot([str(linked_path)]), git_before)
        self.assertEqual(bridge._git_status_snapshot([str(linked_path)]), status_before)

    def test_linked_session_peer_readback_allows_only_one_released_target_owner_link(self) -> None:
        peer_before = {
            "workspace_id": "peer",
            "focused": False,
            "worktree": {"repo_key": "peer-repository", "checkout_path": str(self.repo)},
            "worktrees": [
                {
                    "path": str(self.repo / "peer-linked-checkout"),
                    "branch": "agent/29-popularity-baseline",
                    "is_linked_worktree": True,
                    "open_workspace_id": "target",
                }
            ],
        }
        peer_after = {
            **peer_before,
            "worktrees": [
                {
                    key: value
                    for key, value in peer_before["worktrees"][0].items()
                    if key != "open_workspace_id"
                }
            ],
        }

        self.assertTrue(
            bridge._workspace_peers_preserved(
                [peer_before], [peer_after], "target", allow_linked_session_release=True
            )
        )
        self.assertFalse(
            bridge._workspace_peers_preserved(
                [peer_before], [peer_after], "target", allow_linked_session_release=False
            )
        )

        changed_focus = {**peer_after, "focused": True}
        changed_provenance = {**peer_after, "worktree": {"repo_key": "changed", "checkout_path": str(self.repo)}}
        changed_link = {
            **peer_after,
            "worktrees": [{**peer_after["worktrees"][0], "branch": "different-branch"}],
        }
        changed_path = {
            **peer_after,
            "worktrees": [{**peer_after["worktrees"][0], "path": str(self.repo / "other-checkout")}],
        }
        changed_linked_flag = {
            **peer_after,
            "worktrees": [{**peer_after["worktrees"][0], "is_linked_worktree": False}],
        }
        reassigned_link = {
            **peer_before,
            "worktrees": [{**peer_before["worktrees"][0], "open_workspace_id": "different-target"}],
        }
        second_released_link = {
            **peer_before,
            "worktrees": [
                peer_before["worktrees"][0],
                {**peer_before["worktrees"][0], "path": str(self.repo / "another-checkout")},
            ],
        }
        second_released_after = {
            **second_released_link,
            "worktrees": [
                {key: value for key, value in row.items() if key != "open_workspace_id"}
                for row in second_released_link["worktrees"]
            ],
        }
        missing_peer = {**peer_after, "workspace_id": "other"}
        unrelated_owner_before = {"workspace_id": "peer", "focused": False, "open_workspace_id": "target"}
        unrelated_owner_after = {"workspace_id": "peer", "focused": False}
        self.assertFalse(
            bridge._workspace_peers_preserved(
                [peer_before], [changed_focus], "target", allow_linked_session_release=True
            )
        )
        self.assertFalse(
            bridge._workspace_peers_preserved(
                [peer_before], [changed_provenance], "target", allow_linked_session_release=True
            )
        )
        self.assertFalse(
            bridge._workspace_peers_preserved(
                [peer_before], [changed_link], "target", allow_linked_session_release=True
            )
        )
        self.assertFalse(
            bridge._workspace_peers_preserved(
                [peer_before], [changed_path], "target", allow_linked_session_release=True
            )
        )
        self.assertFalse(
            bridge._workspace_peers_preserved(
                [peer_before], [changed_linked_flag], "target", allow_linked_session_release=True
            )
        )
        self.assertFalse(
            bridge._workspace_peers_preserved(
                [peer_before], [reassigned_link], "target", allow_linked_session_release=True
            )
        )
        self.assertFalse(
            bridge._workspace_peers_preserved(
                [second_released_link], [second_released_after], "target", allow_linked_session_release=True
            )
        )
        self.assertFalse(
            bridge._workspace_peers_preserved(
                [unrelated_owner_before], [unrelated_owner_after], "target", allow_linked_session_release=True
            )
        )
        self.assertFalse(
            bridge._workspace_peers_preserved(
                [peer_before], [missing_peer], "target", allow_linked_session_release=True
            )
        )

    def test_workspace_close_refuses_linked_session_with_ambiguous_mapping(self) -> None:
        linked_path = self._git_worktree("linked-session", "linked-session-checkout")
        provenance = {
            "repo_key": str(self.repo / ".git"),
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(linked_path),
            "is_linked_worktree": True,
        }
        caller = {"workspace_id": "caller", "focused": True}
        target = {"workspace_id": "target", "focused": False, "worktree": provenance}
        linked_row = {
            "path": str(linked_path),
            "branch": "linked-session",
            "is_linked_worktree": True,
            "open_workspace_id": "target",
        }

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            if command[:2] == ["workspace", "list"]:
                return [caller, target]
            if command[:2] == ["agent", "list"]:
                return [{"workspace_id": "target", "agent_status": "done"}]
            if command[:2] == ["worktree", "list"]:
                return [linked_row, dict(linked_row, branch="ambiguous-branch")]
            raise AssertionError(command)

        with patch.object(bridge, "_collection", side_effect=collection), patch.object(
            bridge, "_run_herdr_json"
        ) as mutation:
            with self.assertRaisesRegex(RuntimeError, "missing or ambiguous"):
                bridge._mutate_tool("herdr_workspace_close", "target")
        mutation.assert_not_called()

    def test_workspace_close_refuses_linked_session_with_path_or_branch_mismatch(self) -> None:
        linked_path = self._git_worktree("linked-session", "linked-session-checkout")
        provenance = {
            "repo_key": str(self.repo / ".git"),
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(linked_path),
            "is_linked_worktree": True,
        }
        caller = {"workspace_id": "caller", "focused": True}
        target = {"workspace_id": "target", "focused": False, "worktree": provenance}
        for label, path, branch, message in (
            ("path mismatch", str(self.repo), "linked-session", "path or branch mapping is invalid"),
            ("branch mismatch", str(linked_path), "different-branch", "branch does not match Git"),
        ):
            linked_row = {
                "path": path,
                "branch": branch,
                "is_linked_worktree": True,
                "open_workspace_id": "target",
            }

            def collection(command: list[str], key: str) -> list[dict[str, object]]:
                if command[:2] == ["workspace", "list"]:
                    return [caller, target]
                if command[:2] == ["agent", "list"]:
                    return [{"workspace_id": "target", "agent_status": "done"}]
                if command[:2] == ["worktree", "list"]:
                    return [linked_row]
                raise AssertionError(command)

            with self.subTest(label=label), patch.object(bridge, "_collection", side_effect=collection), patch.object(
                bridge, "_run_herdr_json"
            ) as mutation:
                with self.assertRaisesRegex(RuntimeError, message):
                    bridge._mutate_tool("herdr_workspace_close", "target")
                mutation.assert_not_called()

    def test_workspace_close_refuses_linked_session_with_active_or_unknown_agent(self) -> None:
        linked_path = self._git_worktree("linked-session", "linked-session-checkout")
        provenance = {
            "repo_key": str(self.repo / ".git"),
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(linked_path),
            "is_linked_worktree": True,
        }
        worktree = {
            "path": str(linked_path),
            "branch": "linked-session",
            "is_linked_worktree": True,
            "open_workspace_id": "target",
        }
        for status in ("working", "unknown"):
            def collection(command: list[str], key: str) -> list[dict[str, object]]:
                if command[:2] == ["workspace", "list"]:
                    return self._with_caller([{"workspace_id": "target", "focused": False, "worktree": provenance}])
                if command[:2] == ["agent", "list"]:
                    return [{"workspace_id": "target", "agent_status": status}]
                if command[:2] == ["worktree", "list"]:
                    raise AssertionError("linked worktree inventory must not be read before agent settlement")
                raise AssertionError(command)

            with self.subTest(status=status), patch.object(bridge, "_collection", side_effect=collection), patch.object(
                bridge, "_run_herdr_json"
            ) as mutation:
                with self.assertRaisesRegex(RuntimeError, "working, blocked, or unknown agent"):
                    bridge._mutate_tool("herdr_workspace_close", "target")
                mutation.assert_not_called()

    def test_workspace_close_closes_secondary_plain_workspace_and_preserves_primary_owner(self) -> None:
        provenance = {
            "repo_key": str(self.repo / ".git"),
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        caller = {"workspace_id": "caller", "focused": True, "worktree": provenance}
        target = {"workspace_id": "target", "focused": False, "worktree": provenance}
        peer = {"workspace_id": "peer", "focused": False, "worktree": {"repo_key": "peer-repository"}}
        worktree_info = {
            "path": str(self.repo),
            "branch": "base",
            "is_bare": False,
            "is_detached": False,
            "is_prunable": False,
            "is_linked_worktree": False,
            "label": "repo",
            "open_workspace_id": "caller",
        }
        unrelated_linked_paths = [
            self._git_worktree("linked-agent-17", "checkout-agent-17"),
            self._git_worktree("linked-pilot-entry-read-only", "checkout-pilot-entry-read-only"),
        ]
        unrelated_linked_worktrees = [
            {"path": str(path), "is_linked_worktree": True} for path in unrelated_linked_paths
        ]
        initial_workspaces = [caller, target, peer]
        remaining_workspaces = [caller, peer]
        worktree_commands: list[list[str]] = []
        workspace_reads = 0

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            nonlocal workspace_reads
            if command[:2] == ["workspace", "list"]:
                workspace_reads += 1
                return initial_workspaces if workspace_reads == 1 else remaining_workspaces
            if command[:2] == ["agent", "list"]:
                return [{"workspace_id": "target", "agent_status": "idle"}]
            if command[:2] == ["worktree", "list"]:
                worktree_commands.append(command)
                return [worktree_info, *unrelated_linked_worktrees]
            raise AssertionError(command)

        close_commands: list[list[str]] = []

        def close(command: list[str]) -> dict[str, object]:
            close_commands.append(command)
            if command == ["workspace", "close", "target"]:
                return {"result": {}}
            raise AssertionError(command)

        snapshot_paths = [str(self.repo), *(str(path) for path in unrelated_linked_paths)]
        git_before = bridge._git_worktree_snapshot(snapshot_paths)
        status_before = bridge._git_status_snapshot(snapshot_paths)
        with patch.object(bridge, "_collection", side_effect=collection), patch.object(
            bridge, "_run_herdr_json", side_effect=close
        ):
            result = bridge._mutate_tool("herdr_workspace_close", "target")

        self.assertTrue(result["closed"])
        self.assertEqual(close_commands, [["workspace", "close", "target"]])
        self.assertIn(["worktree", "list", "--workspace", "target"], worktree_commands)
        self.assertIn(["worktree", "list", "--cwd", str(self.repo)], worktree_commands)
        self.assertEqual(workspace_reads, 3)
        self.assertEqual(bridge._git_worktree_snapshot(snapshot_paths), git_before)
        self.assertEqual(bridge._git_status_snapshot(snapshot_paths), status_before)

    def test_workspace_close_allows_shared_repository_and_missing_unrelated_owner(self) -> None:
        linked_path = self._git_worktree("unrelated-linked")
        provenance = {
            "repo_key": "shared-repository",
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        target = {"workspace_id": "target", "focused": False, "worktree": provenance}
        caller = {"workspace_id": "caller", "focused": True, "worktree": provenance}
        peer_with_unknown_repo = {"workspace_id": "peer-with-unknown-repo", "focused": False}
        linked_owner = {
            "workspace_id": "linked-owner",
            "focused": False,
            "worktree": {"checkout_path": str(linked_path)},
        }
        worktree_info = {
            "path": str(self.repo),
            "is_linked_worktree": False,
            "open_workspace_id": "caller",
        }
        unrelated_linked = {"path": str(linked_path), "is_linked_worktree": True}
        workspace_reads = 0

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            nonlocal workspace_reads
            if command[:2] == ["workspace", "list"]:
                workspace_reads += 1
                return [target, caller, peer_with_unknown_repo, linked_owner] if workspace_reads == 1 else [caller, peer_with_unknown_repo, linked_owner]
            if command[:2] == ["agent", "list"]:
                return [{"workspace_id": "target", "agent_status": "done"}]
            if command[:2] == ["worktree", "list"]:
                return [worktree_info, unrelated_linked]
            raise AssertionError(command)

        def run(command: list[str]) -> dict[str, object]:
            if command == ["workspace", "close", "target"]:
                return {"result": {}}
            raise AssertionError(command)

        with patch.object(bridge, "_collection", side_effect=collection), patch.object(
            bridge, "_run_herdr_json", side_effect=run
        ):
            result = bridge._mutate_tool("herdr_workspace_close", "target")
        self.assertTrue(result["closed"])
        self.assertEqual(workspace_reads, 3)

    def test_workspace_close_refuses_old_server_before_worktree_inspection_or_mutation(self) -> None:
        provenance = {
            "repo_key": "shared-repository",
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
                return [{"workspace_id": "target", "agent_status": "done"}]
            if command[:2] == ["worktree", "list"]:
                return [worktree_info]
            raise AssertionError(command)

        self.safe_close_support.stop()
        with patch.object(bridge, "_collection", side_effect=collection), patch.object(
            bridge, "_run_herdr_json", return_value={"result": {"version": "0.8.2"}}
        ) as command:
            with self.assertRaisesRegex(RuntimeError, "0.9.0 or newer workspace-close guard"):
                bridge._mutate_tool("herdr_workspace_close", "target")
        command.assert_called_once_with(["status", "server", "--json"])

    def test_workspace_close_refuses_unknown_server_before_worktree_inspection_or_mutation(self) -> None:
        provenance = {
            "repo_key": "repository",
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            if command[:2] == ["workspace", "list"]:
                return [
                    {"workspace_id": "target", "focused": False, "worktree": provenance},
                    {"workspace_id": "caller", "focused": True},
                ]
            if command[:2] == ["agent", "list"]:
                return []
            raise AssertionError(f"unexpected inventory read: {command}")

        self.safe_close_support.stop()
        with patch.object(bridge, "_collection", side_effect=collection), patch.object(
            bridge, "_run_herdr_json", return_value={"result": {"version": "unknown"}}
        ) as command:
            with self.assertRaisesRegex(RuntimeError, "Cannot verify Herdr 0.9.0 or newer"):
                bridge._mutate_tool("herdr_workspace_close", "target")
        command.assert_called_once_with(["status", "server", "--json"])

    def test_workspace_close_readback_detects_missing_peer_workspace(self) -> None:
        provenance = {
            "repo_key": "repository",
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        target = {"workspace_id": "target", "focused": False, "worktree": provenance}
        caller = {"workspace_id": "caller", "focused": True}
        peer = {"workspace_id": "peer", "focused": False}
        worktree_info = {"path": str(self.repo), "is_linked_worktree": False, "open_workspace_id": "target"}
        workspace_reads = 0

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            nonlocal workspace_reads
            if command[:2] == ["workspace", "list"]:
                workspace_reads += 1
                return [target, caller, peer] if workspace_reads == 1 else [caller]
            if command[:2] == ["agent", "list"]:
                return [{"workspace_id": "target", "agent_status": "done"}]
            if command[:2] == ["worktree", "list"]:
                return [worktree_info]
            raise AssertionError(command)

        with patch.object(bridge, "_collection", side_effect=collection), patch.object(
            bridge, "_run_herdr_json", return_value={"result": {}}
        ) as close:
            with self.assertRaisesRegex(RuntimeError, "changed another workspace"):
                bridge._mutate_tool("herdr_workspace_close", "target")
        close.assert_called_once_with(["workspace", "close", "target"])

    def test_workspace_close_relinquishes_primary_group_refusal_to_herdr(self) -> None:
        provenance = {
            "repo_key": str(self.repo / ".git"),
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        owner = {"workspace_id": "owner", "focused": False, "worktree": provenance}
        peer_workspace = {"workspace_id": "target", "focused": False, "worktree": provenance}
        linked_owner = {"workspace_id": "agent-17", "focused": False}
        worktree_info = {
            "path": str(self.repo),
            "is_linked_worktree": False,
            "open_workspace_id": "owner",
        }
        linked_path = self._git_worktree("linked-agent-17")
        unrelated_linked_worktree = {
            "path": str(linked_path),
            "is_linked_worktree": True,
            "open_workspace_id": "agent-17",
        }

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            if command[:2] == ["workspace", "list"]:
                return self._with_caller([owner, peer_workspace, linked_owner])
            if command[:2] == ["agent", "list"]:
                return []
            if command[:2] == ["worktree", "list"]:
                return [worktree_info, unrelated_linked_worktree]
            raise AssertionError(command)

        def close(command: list[str]) -> dict[str, object]:
            if command == ["workspace", "close", "owner"]:
                raise RuntimeError("workspace_group_close_required")
            raise AssertionError(command)

        with patch.object(bridge, "_collection", side_effect=collection), patch.object(
            bridge, "_run_herdr_json", side_effect=close
        ) as mutation:
            with self.assertRaisesRegex(RuntimeError, "workspace_group_close_required"):
                bridge._mutate_tool("herdr_workspace_close", "owner")
        mutation.assert_called_once_with(["workspace", "close", "owner"])

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
            (
                "invalid owner id",
                {"path": str(self.repo / "linked"), "is_linked_worktree": True, "open_workspace_id": "agent 17"},
                [primary, target],
                "owner identity is invalid",
            ),
            (
                "owner is absent from workspace inventory",
                {"path": str(self.repo / "linked"), "is_linked_worktree": True, "open_workspace_id": "agent-17"},
                [primary, target],
                "owner is missing or invalid in the workspace inventory",
            ),
            (
                "target-owned linked row",
                {"path": str(self.repo / "linked"), "is_linked_worktree": True, "open_workspace_id": "target"},
                [primary, target],
                "owns a linked worktree",
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
                    return self._with_caller(workspaces)
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

    def test_workspace_close_rejects_ambiguous_linked_owner_for_primary_workspace(self) -> None:
        provenance = {
            "repo_key": str(self.repo / ".git"),
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        primary = {"workspace_id": "target", "focused": False, "worktree": provenance}
        primary_worktree = {
            "path": str(self.repo),
            "is_linked_worktree": False,
            "open_workspace_id": "target",
        }
        linked_rows = (
            ({"path": str(self.repo / "unmapped"), "is_linked_worktree": True}, "ownership is ambiguous"),
            (
                {"path": str(self.repo / "target-owned"), "is_linked_worktree": True, "open_workspace_id": "target"},
                "owns a linked worktree",
            ),
        )
        for linked_row, expected_error in linked_rows:
            def collection(command: list[str], key: str) -> list[dict[str, object]]:
                if command[:2] == ["workspace", "list"]:
                    return self._with_caller([primary])
                if command[:2] == ["agent", "list"]:
                    return []
                if command[:2] == ["worktree", "list"]:
                    return [primary_worktree, linked_row]
                raise AssertionError(command)

            with self.subTest(linked_row=linked_row), patch.object(
                bridge, "_collection", side_effect=collection
            ), patch.object(bridge, "_run_herdr_json") as mutation:
                with self.assertRaisesRegex(RuntimeError, expected_error):
                    bridge._mutate_tool("herdr_workspace_close", "target")
                mutation.assert_not_called()

    def test_workspace_close_rejects_ambiguous_ownerless_link_mapping(self) -> None:
        provenance = {
            "repo_key": str(self.repo / ".git"),
            "repo_name": "repo",
            "repo_root": str(self.repo),
            "checkout_path": str(self.repo),
            "is_linked_worktree": False,
        }
        caller = {"workspace_id": "caller", "focused": True, "worktree": provenance}
        target = {"workspace_id": "target", "focused": False, "worktree": provenance}
        linked_path = self._git_worktree("ambiguous-ownerless")
        linked_owner_a = {
            "workspace_id": "linked-owner-a",
            "focused": False,
            "worktree": {"checkout_path": str(linked_path)},
        }
        linked_owner_b = {
            "workspace_id": "linked-owner-b",
            "focused": False,
            "worktree": {"checkout_path": str(linked_path)},
        }
        primary_worktree = {
            "path": str(self.repo),
            "is_linked_worktree": False,
            "open_workspace_id": "caller",
        }
        linked_worktree = {"path": str(linked_path), "is_linked_worktree": True}

        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            if command[:2] == ["workspace", "list"]:
                return [caller, target, linked_owner_a, linked_owner_b]
            if command[:2] == ["agent", "list"]:
                return [{"workspace_id": "target", "agent_status": "idle"}]
            if command[:2] == ["worktree", "list"]:
                return [primary_worktree, linked_worktree]
            raise AssertionError(command)

        with patch.object(bridge, "_collection", side_effect=collection), patch.object(
            bridge, "_run_herdr_json"
        ) as mutation:
            with self.assertRaisesRegex(RuntimeError, "ownership is ambiguous"):
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
                    return self._with_caller(workspaces)
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
                return self._with_caller(workspaces)
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

    def test_nonzero_cli_failure_reports_fixed_step_category_and_exit_status(self) -> None:
        cases = (
            (
                ["workspace", "close", "private-workspace-id"],
                "workspace close",
                "Herdr refused to close a primary workspace (group close refused)",
                "workspace_group_close_required",
                1,
            ),
            (
                ["worktree", "list", "--cwd", "/private/local/checkout"],
                "checkout worktree inventory read",
                "permission denied",
                "Operation not permitted",
                23,
            ),
            (
                ["worktree", "list", "--cwd", "/private/local/checkout"],
                "checkout worktree inventory read",
                "permission denied",
                "permission denied (EACCES)",
                13,
            ),
            (
                ["workspace", "list"],
                "workspace inventory read",
                "socket access denied (EPERM)",
                "Herdr Unix socket access denied: EPERM",
                1,
            ),
            (
                ["workspace", "list"],
                "workspace inventory read",
                "CLI command failed",
                "unclassified failure",
                2,
            ),
        )
        for command, operation, category, stderr, exit_status in cases:
            with self.subTest(operation=operation), patch.object(
                bridge.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    ["herdr"], exit_status, stdout="", stderr=stderr
                ),
            ):
                with self.assertRaises(RuntimeError) as raised:
                    bridge._run_herdr_json(command)
            self.assertEqual(
                str(raised.exception),
                f"Herdr {operation} failed: {category} (exit status {exit_status})",
            )
            self.assertNotIn("private-workspace-id", str(raised.exception))
            self.assertNotIn("/private/local/checkout", str(raised.exception))

    def test_mcp_cli_failure_redacts_output_and_sensitive_identifiers(self) -> None:
        sensitive_values = (
            "/home/private-user/workspaces/secret-checkout",
            "workspace-secret-123",
            "pane-secret-456",
            "credential-secret-token",
            "private travel data",
        )
        raw_output = " ".join(sensitive_values)
        with patch.object(
            bridge.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                ["herdr"], 7, stdout=raw_output, stderr=f"Herdr socket access denied: EPERM {raw_output}"
            ),
        ):
            response = bridge._handle(
                {
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "tools/call",
                    "params": {"name": "herdr_workspace_list", "arguments": {}},
                }
            )

        self.assertTrue(response["result"]["isError"])
        diagnostic = response["result"]["content"][0]["text"]
        self.assertEqual(
            diagnostic,
            "Herdr workspace inventory read failed: socket access denied (EPERM) (exit status 7)",
        )
        for sensitive in sensitive_values:
            self.assertNotIn(sensitive, json.dumps(response))

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
                return self._with_caller([workspace]) if workspace_reads <= 2 else []
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
                return self._with_caller([workspace])
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
        caller = {"workspace_id": "caller", "focused": True, "worktree": {"repo_key": "caller-fixture-repository"}}
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
                return [workspace, caller] if call == 1 else [caller]
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
