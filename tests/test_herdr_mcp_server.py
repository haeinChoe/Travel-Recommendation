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


class MCPProtocolTests(unittest.TestCase):
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

    def test_workspace_close_rejects_a_linked_worktree(self) -> None:
        path = self._git_worktree()
        mocks, *_ = self._setup_api(worktree=_worktree(str(path)))
        with mocks, self.assertRaisesRegex(RuntimeError, "inventories disagree"):
            bridge._mutate_tool("herdr_workspace_close", "target")

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
        workspace = {"workspace_id": "target", "focused": False, "worktree": None}
        call = 0
        def collection(command: list[str], key: str) -> list[dict[str, object]]:
            nonlocal call
            if command[:2] == ["workspace", "list"]:
                call += 1
                return [workspace] if call == 1 else []
            if command[:2] == ["agent", "list"]:
                return []
            if command[:2] == ["worktree", "list"]:
                return []
            raise AssertionError(command)
        with patch.object(bridge, "_collection", side_effect=collection), patch.object(bridge, "_run_herdr_json") as mutation:
            mutation.return_value = {"result": {}}
            result = bridge._mutate_tool("herdr_workspace_close", "target")
        self.assertEqual(result["closed"], True)
        mutation.assert_called_once_with(["workspace", "close", "target"])


@unittest.skipUnless(os.environ.get("HERDR_REAL_INTEGRATION") == "1", "set HERDR_REAL_INTEGRATION=1 to use a disposable real Herdr session")
class RealHerdrSubprocessIntegrationTests(unittest.TestCase):
    def test_bridge_removes_only_its_disposable_worktree_and_workspace(self) -> None:
        env = os.environ.copy()
        env["HERDR_ENV"] = "1"
        status = subprocess.run(["herdr", "status", "server", "--json"], capture_output=True, text=True, env=env, check=False)
        if status.returncode != 0:
            self.skipTest(f"real Herdr socket unavailable before fixture creation: {status.stderr.strip()}")

        def workspace_records(document: dict[str, object]) -> list[dict[str, object]]:
            result = document.get("result", document)
            items = result.get("workspaces") if isinstance(result, dict) else result
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise AssertionError("Herdr returned an unsupported workspace list")
            return items

        def focused_id(records: list[dict[str, object]]) -> str | None:
            focused = [item for item in records if item.get("focused") is True]
            if any(not isinstance(item.get("focused"), bool) for item in records) or len(focused) > 1:
                raise AssertionError("Herdr returned ambiguous focus metadata")
            if not focused:
                return None
            focused_workspace_id = focused[0].get("workspace_id")
            if not isinstance(focused_workspace_id, str) or not focused_workspace_id:
                raise AssertionError("Herdr returned invalid focused workspace metadata")
            return focused_workspace_id

        original_focus = focused_id(workspace_records(json.loads(subprocess.run(
            ["herdr", "workspace", "list"], capture_output=True, text=True, env=env, check=True
        ).stdout)))

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

        def herdr_json(*args: str) -> dict[str, object]:
            result = subprocess.run(["herdr", *args], capture_output=True, text=True, env=env, check=True)
            return json.loads(result.stdout)

        def bridge_call(name: str, workspace_id: str) -> dict[str, object]:
            request = {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": name, "arguments": {"workspace_id": workspace_id}}}
            result = subprocess.run(
                ["python3", str(Path(bridge.__file__).resolve())],
                input=json.dumps(request) + "\n",
                capture_output=True,
                text=True,
                env=env,
                check=True,
                cwd=repo,
            )
            response = json.loads(result.stdout)
            if response.get("error"):
                raise AssertionError(response["error"])
            tool_result = response["result"]
            if tool_result.get("isError"):
                raise AssertionError(tool_result["content"])
            return tool_result["structuredContent"]

        failure: Exception | None = None
        try:
            created = herdr_json("workspace", "create", "--cwd", str(repo), "--label", label, "--no-focus")
            source_id = created["result"]["workspace"]["workspace_id"]
            worktree = herdr_json(
                "worktree", "create", "--workspace", source_id, "--branch", f"test/{label}",
                "--base", "main", "--path", str(worktree_path), "--label", label, "--no-focus",
            )
            target_id = worktree["result"]["workspace"]["workspace_id"]
            self.assertEqual(focused_id(workspace_records(herdr_json("workspace", "list"))), original_focus)
            self.assertEqual(bridge_call("herdr_worktree_remove", target_id)["removed"], True)
            self.assertFalse(worktree_path.exists())
            self.assertEqual(focused_id(workspace_records(herdr_json("workspace", "list"))), original_focus)
            self.assertEqual(bridge_call("herdr_workspace_close", source_id)["closed"], True)
            self.assertEqual(focused_id(workspace_records(herdr_json("workspace", "list"))), original_focus)
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
                    bridge_call("herdr_worktree_remove", target_id)
                except Exception as exc:
                    cleanup_errors.append(f"target cleanup: {exc}")
            if source_id is not None:
                try:
                    bridge_call("herdr_workspace_close", source_id)
                except Exception as exc:
                    cleanup_errors.append(f"source cleanup: {exc}")

            fixture_gone = False
            try:
                listed_workspaces = workspace_records(herdr_json("workspace", "list"))
                fixture_ids = {value for value in (source_id, target_id) if value is not None}
                fixture_workspaces = [item for item in listed_workspaces if item.get("workspace_id") in fixture_ids]
                worktree_result = herdr_json("worktree", "list", "--cwd", str(repo))
                worktree_document = worktree_result.get("result", worktree_result)
                fixture_worktrees = worktree_document.get("worktrees", []) if isinstance(worktree_document, dict) else worktree_document
                if not isinstance(fixture_worktrees, list):
                    raise AssertionError("Herdr returned an unsupported worktree list")
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
                current_focus = focused_id(workspace_records(herdr_json("workspace", "list")))
                if current_focus != original_focus:
                    if original_focus is None:
                        raise AssertionError("initially unfocused Herdr session cannot be safely refocused")
                    current_workspaces = workspace_records(herdr_json("workspace", "list"))
                    if not any(item.get("workspace_id") == original_focus for item in current_workspaces):
                        raise AssertionError("original focused workspace is no longer available")
                    herdr_json("workspace", "focus", original_focus)
                    if focused_id(workspace_records(herdr_json("workspace", "list"))) != original_focus:
                        raise AssertionError("original focus did not restore")
            except Exception as exc:
                cleanup_errors.append(f"focus restoration: {exc}")

            if fixture_gone:
                shutil.rmtree(root)

        if failure is not None or cleanup_errors:
            self.fail(
                f"real Herdr integration failed ({failure}); cleanup: {cleanup_errors}; "
                f"disposable fixture path: {root if not fixture_gone else 'removed'}"
            )


if __name__ == "__main__":
    unittest.main()
