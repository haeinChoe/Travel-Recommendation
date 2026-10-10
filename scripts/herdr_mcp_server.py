#!/usr/bin/env python3
"""A small, constrained MCP stdio bridge for the local Herdr CLI."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = "2025-11-25"
SERVER_INFO = {"name": "travel-recommendation-herdr", "version": "1.0.0"}
MAX_REQUEST_BYTES = 1_048_576
HERDR_TIMEOUT_SECONDS = 8
GIT_TIMEOUT_SECONDS = 5
WORKSPACE_ID_PATTERN = re.compile(r"^[^\x00-\x20\x7f]{1,256}$")

TOOLS: dict[str, dict[str, Any]] = {
    "herdr_server_status": {
        "description": "Read the local Herdr server status.",
        "command": ("status", "server", "--json"),
        "kind": "object",
        "fields": ("status", "running", "version", "protocol", "compatible"),
    },
    "herdr_workspace_list": {
        "description": "List Herdr workspaces using identifiers and labels only.",
        "command": ("workspace", "list"),
        "kind": "list",
        "collection": "workspaces",
        "fields": ("workspace_id", "label", "focused"),
    },
    "herdr_agent_list": {
        "description": "List Herdr agents and their location and lifecycle status.",
        "command": ("agent", "list"),
        "kind": "list",
        "collection": "agents",
        "fields": ("agent", "name", "agent_status", "pane_id", "workspace_id", "tab_id"),
    },
    "herdr_worktree_remove": {
        "description": "Safely remove the clean linked worktree for one Herdr workspace.",
        "input": "workspace_id",
        "mutation": "worktree_remove",
    },
    "herdr_workspace_close": {
        "description": "Safely close one non-focused plain Herdr workspace after validating primary checkout ownership and linked worktrees.",
        "input": "workspace_id",
        "mutation": "workspace_close",
    },
}


def _json_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_error(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


def _tool_success(value: Any) -> dict[str, Any]:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return {
        "content": [{"type": "text", "text": encoded}],
        "structuredContent": value,
    }


def _unwrap_cli_result(document: Any) -> Any:
    if isinstance(document, dict) and "result" in document:
        return document["result"]
    return document


def _filter_result(spec: dict[str, Any], document: Any) -> Any:
    result = _unwrap_cli_result(document)
    fields = spec["fields"]
    if spec["kind"] == "object":
        if not isinstance(result, dict):
            raise ValueError("Herdr returned an unexpected status response")
        if isinstance(result.get("server"), dict):
            result = result["server"]
        return {key: result[key] for key in fields if key in result}

    if isinstance(result, dict):
        items = result.get(spec["collection"])
    else:
        items = result
    if not isinstance(items, list):
        raise ValueError("Herdr returned an unexpected list response")
    filtered = []
    for item in items:
        if isinstance(item, dict):
            filtered.append({key: item[key] for key in fields if key in item})
    return {"items": filtered}


def _run_herdr_json(command: list[str]) -> Any:
    environment = os.environ.copy()
    environment["HERDR_ENV"] = "1"
    try:
        completed = subprocess.run(
            ["herdr", *command],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=HERDR_TIMEOUT_SECONDS,
            env=environment,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Herdr command timed out after {HERDR_TIMEOUT_SECONDS} seconds") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("Herdr CLI was not found; install Herdr or make `herdr` available on PATH") from exc
    except OSError as exc:
        raise RuntimeError(f"Could not start the Herdr CLI ({exc.__class__.__name__})") from exc

    if completed.returncode != 0:
        stderr = completed.stderr.casefold()
        if "operation not permitted" in stderr or "permissiondenied" in stderr or "eperm" in stderr:
            raise RuntimeError(
                "Herdr socket access denied (EPERM). The current sandbox blocks this connection; "
                "confirm HERDR_ENV=1 and diagnose from the same sandbox context."
            )
        if "permission denied" in stderr or "eacces" in stderr:
            raise RuntimeError(
                "Herdr socket access denied (EACCES). Check socket ownership and sandbox access "
                "from this same context."
            )
        if "connection refused" in stderr or "not connected" in stderr or "server_not_running" in stderr:
            raise RuntimeError("Herdr server is unavailable; start or attach to a Herdr session, then retry")
        raise RuntimeError(f"Herdr CLI failed with exit status {completed.returncode}")

    try:
        return json.loads(completed.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("Herdr returned an invalid or unsupported JSON response") from exc


def _run_herdr(spec: dict[str, Any]) -> Any:
    return _filter_result(spec, _run_herdr_json(list(spec["command"])))


def _collection(command: list[str], key: str) -> list[dict[str, Any]]:
    document = _run_herdr_json(command)
    result = _unwrap_cli_result(document)
    items = result.get(key) if isinstance(result, dict) else result
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise RuntimeError(f"Herdr returned an unexpected {key} response")
    return items


def _validate_workspace_id(value: Any) -> str:
    if not isinstance(value, str) or not WORKSPACE_ID_PATTERN.fullmatch(value):
        raise ValueError("workspace_id must be a non-empty Herdr ID without whitespace or control characters")
    return value


def _workspace_context(workspace_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
    workspaces = _collection(["workspace", "list"], "workspaces")
    matches = [item for item in workspaces if item.get("workspace_id") == workspace_id]
    if len(matches) > 1:
        raise RuntimeError("Herdr returned duplicate workspace IDs")
    agents = _collection(["agent", "list"], "agents")
    return (matches[0] if matches else None, workspaces, agents)


def _assert_not_focused(workspace: dict[str, Any]) -> None:
    if workspace.get("focused") is not False:
        raise RuntimeError("Refusing to close the current or focused workspace")


def _focused_workspace_id(workspaces: list[dict[str, Any]]) -> str | None:
    focused = []
    for workspace in workspaces:
        if not isinstance(workspace.get("focused"), bool):
            raise RuntimeError("Herdr returned invalid focus metadata; refusing teardown")
        if workspace["focused"]:
            workspace_id = workspace.get("workspace_id")
            if not isinstance(workspace_id, str) or not workspace_id:
                raise RuntimeError("Herdr returned invalid focused workspace metadata; refusing teardown")
            focused.append(workspace_id)
    if len(focused) > 1:
        raise RuntimeError("Herdr reported multiple focused workspaces; refusing teardown")
    return focused[0] if focused else None


def _restore_focus(focused_workspace_id: str | None) -> list[dict[str, Any]]:
    workspaces = _collection(["workspace", "list"], "workspaces")
    actual_focus = _focused_workspace_id(workspaces)
    if actual_focus == focused_workspace_id:
        return workspaces
    if focused_workspace_id is None:
        raise RuntimeError("Herdr focus changed from no focused workspace and cannot be restored safely")
    if not any(item.get("workspace_id") == focused_workspace_id for item in workspaces):
        raise RuntimeError("The previously focused workspace is no longer available to restore")
    _run_herdr_json(["workspace", "focus", focused_workspace_id])
    restored = _collection(["workspace", "list"], "workspaces")
    if _focused_workspace_id(restored) != focused_workspace_id:
        raise RuntimeError("Could not restore the previously focused Herdr workspace")
    return restored


def _run_mutation_preserving_focus(
    command: list[str], focused_workspace_id: str | None
) -> list[dict[str, Any]]:
    try:
        _run_herdr_json(command)
    except RuntimeError as mutation_error:
        try:
            _restore_focus(focused_workspace_id)
        except RuntimeError as focus_error:
            raise RuntimeError(f"{mutation_error}; focus restoration failed: {focus_error}") from mutation_error
        raise
    return _restore_focus(focused_workspace_id)


def _assert_agents_settled(agents: list[dict[str, Any]], workspace_id: str) -> None:
    for agent in agents:
        if agent.get("workspace_id") != workspace_id:
            continue
        state = agent.get("agent_status")
        if state not in {"idle", "done"}:
            raise RuntimeError("Refusing to close a workspace with a working, blocked, or unknown agent")


def _worktrees_for(workspace_id: str) -> list[dict[str, Any]]:
    return _collection(["worktree", "list", "--workspace", workspace_id], "worktrees")


def _worktrees_for_checkout(checkout_path: str) -> list[dict[str, Any]]:
    return _collection(["worktree", "list", "--cwd", checkout_path], "worktrees")


def _git(path: str, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", path, *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Could not verify the linked Git worktree") from exc
    if completed.returncode != 0:
        raise RuntimeError("Could not verify the linked Git worktree")
    return completed.stdout.strip()


def _assert_clean_linked_worktree(workspace_id: str, worktree: dict[str, Any]) -> str:
    if worktree.get("is_linked_worktree") is not True or worktree.get("open_workspace_id") != workspace_id:
        raise RuntimeError("Refusing to remove a workspace that is not a linked Herdr worktree")
    path = worktree.get("path")
    branch = worktree.get("branch")
    if not isinstance(path, str) or not path or not isinstance(branch, str) or not branch:
        raise RuntimeError("Herdr worktree metadata is incomplete; refusing removal")
    if branch in {"dev", "main"}:
        raise RuntimeError("Refusing to remove a worktree checked out on dev or main")
    if not Path(path).is_absolute():
        raise RuntimeError("Herdr returned a non-absolute worktree path; refusing removal")

    top_level = _git(path, "rev-parse", "--show-toplevel")
    if Path(top_level).resolve() != Path(path).resolve():
        raise RuntimeError("Herdr worktree path does not match its Git checkout")
    if _git(path, "rev-parse", "--abbrev-ref", "HEAD") != branch:
        raise RuntimeError("Herdr worktree branch does not match Git; refusing removal")
    status = _git(path, "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching")
    if status:
        raise RuntimeError("Refusing to remove a dirty worktree")
    listings = _git(path, "worktree", "list", "--porcelain")
    entries = [entry for entry in listings.split("\n\n") if entry.strip()]
    matching = [entry for entry in entries if any(line == f"worktree {top_level}" for line in entry.splitlines())]
    if len(matching) != 1 or "\nbranch refs/heads/" + branch not in "\n" + matching[0]:
        raise RuntimeError("Git does not confirm this as the expected linked worktree")
    return path


def _git_status_snapshot(paths: list[str]) -> dict[str, str]:
    snapshot = {}
    for path in paths:
        resolved = str(Path(path).resolve())
        snapshot[resolved] = _git(resolved, "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching")
    return snapshot


def _git_worktree_snapshot(paths: list[str]) -> dict[str, str]:
    snapshot = {}
    for path in paths:
        resolved = str(Path(path).resolve())
        snapshot[resolved] = _git(resolved, "worktree", "list", "--porcelain")
    return snapshot


def _assert_plain_workspace_provenance(
    workspace: dict[str, Any],
    workspaces: list[dict[str, Any]],
    worktrees: list[dict[str, Any]],
    workspace_id: str,
) -> tuple[str, str]:
    if "worktree" not in workspace:
        raise RuntimeError("Herdr workspace worktree provenance is missing; refusing close")

    provenance = workspace["worktree"]
    if provenance is None:
        raise RuntimeError("Herdr workspace worktree provenance is missing or null; refusing close")

    required_fields = ("repo_key", "repo_name", "repo_root", "checkout_path", "is_linked_worktree")
    if not isinstance(provenance, dict) or any(field not in provenance for field in required_fields):
        raise RuntimeError("Herdr workspace worktree provenance is invalid; refusing close")
    if any(not isinstance(provenance[field], str) or not provenance[field] for field in required_fields[:-1]):
        raise RuntimeError("Herdr workspace worktree provenance is invalid; refusing close")
    if any(not Path(provenance[field]).is_absolute() for field in ("repo_root", "checkout_path")):
        raise RuntimeError("Herdr workspace worktree provenance is invalid; refusing close")
    if not isinstance(provenance["is_linked_worktree"], bool):
        raise RuntimeError("Herdr workspace worktree provenance is invalid; refusing close")
    if provenance["is_linked_worktree"] is not False:
        raise RuntimeError("Remove the linked worktree before closing its workspace")

    checkout_path = provenance["checkout_path"]
    matching = [item for item in worktrees if item.get("path") == checkout_path]
    if len(matching) != 1 or matching[0].get("is_linked_worktree") is not False:
        raise RuntimeError("Workspace and worktree inventories disagree; refusing close")
    for item in worktrees:
        if item.get("path") == checkout_path:
            continue
        if not isinstance(item.get("is_linked_worktree"), bool):
            raise RuntimeError("Worktree inventory has a missing or invalid linked flag; refusing close")
        if item["is_linked_worktree"] is False:
            continue
        linked_owner_id = item.get("open_workspace_id")
        if not isinstance(linked_owner_id, str) or not WORKSPACE_ID_PATTERN.fullmatch(linked_owner_id):
            raise RuntimeError("Linked worktree owner identity is missing or invalid; refusing close")
        linked_owners = [row for row in workspaces if row.get("workspace_id") == linked_owner_id]
        if len(linked_owners) != 1 or not isinstance(linked_owners[0].get("focused"), bool):
            raise RuntimeError("Linked worktree owner is missing or invalid in the workspace inventory; refusing close")
        if linked_owner_id == workspace_id:
            raise RuntimeError("Workspace and worktree inventories disagree; refusing close")
    open_workspace_id = matching[0].get("open_workspace_id")
    if not isinstance(open_workspace_id, str) or not WORKSPACE_ID_PATTERN.fullmatch(open_workspace_id):
        raise RuntimeError("Primary checkout owner identity is missing or invalid; refusing close")
    owners = [item for item in workspaces if item.get("workspace_id") == open_workspace_id]
    if len(owners) != 1 or not isinstance(owners[0].get("focused"), bool):
        raise RuntimeError("Primary checkout owner is missing or invalid in the workspace inventory; refusing close")
    return open_workspace_id, checkout_path


def _mutate_tool(name: str, workspace_id: str) -> dict[str, Any]:
    workspace, all_workspaces, agents = _workspace_context(workspace_id)
    if workspace is None:
        if name == "herdr_worktree_remove":
            return {"workspace_id": workspace_id, "removed": False, "already_absent": True}
        return {"workspace_id": workspace_id, "closed": False, "already_absent": True}

    focused_workspace_id = _focused_workspace_id(all_workspaces)
    _assert_not_focused(workspace)
    _assert_agents_settled(agents, workspace_id)
    worktrees = _worktrees_for(workspace_id)
    linked = [item for item in worktrees if item.get("open_workspace_id") == workspace_id]

    if name == "herdr_worktree_remove":
        if not linked:
            return {"workspace_id": workspace_id, "removed": False, "already_absent": True}
        if len(linked) != 1:
            raise RuntimeError("Herdr returned ambiguous linked worktree metadata; refusing removal")
        path = _assert_clean_linked_worktree(workspace_id, linked[0])
        listing_before = _git(path, "worktree", "list", "--porcelain")
        entries = [entry for entry in listing_before.split("\n\n") if entry.strip()]
        primary_paths = [
            line.removeprefix("worktree ")
            for entry in entries
            for line in entry.splitlines()
            if line.startswith("worktree ") and Path(line.removeprefix("worktree ")).resolve() != Path(path).resolve()
        ]
        if not primary_paths:
            raise RuntimeError("Git did not report a primary worktree for this linked checkout")
        primary_path = primary_paths[0]
        git_before = _git_status_snapshot([primary_path])
        remaining_workspaces = _run_mutation_preserving_focus(
            ["worktree", "remove", "--workspace", workspace_id], focused_workspace_id
        )
        workspace_remains = any(item.get("workspace_id") == workspace_id for item in remaining_workspaces)
        if workspace_remains:
            remaining = _worktrees_for(workspace_id)
            if any(item.get("is_linked_worktree") is not False for item in remaining):
                raise RuntimeError("Herdr worktree removal did not pass readback verification")
        if Path(path).exists():
            raise RuntimeError("Git worktree path still exists after Herdr reported removal")
        if any(line == f"worktree {Path(path).resolve()}" for line in _git(primary_path, "worktree", "list", "--porcelain").splitlines()):
            raise RuntimeError("Git still lists the linked checkout after Herdr reported removal")
        if _git_status_snapshot([primary_path]) != git_before:
            raise RuntimeError("Git worktree status changed outside the requested checkout")
        return {"workspace_id": workspace_id, "removed": True, "already_absent": False}

    checkout_owner_id, checkout_path = _assert_plain_workspace_provenance(
        workspace, all_workspaces, worktrees, workspace_id
    )
    if checkout_owner_id == workspace_id and any(item.get("is_linked_worktree") is not False for item in worktrees):
        raise RuntimeError("Refusing to close a workspace while a linked worktree remains")
    git_paths = [item["path"] for item in worktrees if isinstance(item.get("path"), str) and item.get("path")]
    git_before = _git_status_snapshot(git_paths)
    git_worktrees_before = _git_worktree_snapshot(git_paths)
    remaining = _run_mutation_preserving_focus(["workspace", "close", workspace_id], focused_workspace_id)
    if any(item.get("workspace_id") == workspace_id for item in remaining):
        raise RuntimeError("Herdr workspace close did not pass readback verification")
    if checkout_owner_id != workspace_id:
        owners_after = [item for item in remaining if item.get("workspace_id") == checkout_owner_id]
        if len(owners_after) != 1:
            raise RuntimeError("Primary checkout owner disappeared while closing the workspace")
        checkout_after = _worktrees_for_checkout(checkout_path)
        primary_after = [item for item in checkout_after if item.get("path") == checkout_path]
        if (
            len(primary_after) != 1
            or primary_after[0].get("is_linked_worktree") is not False
            or primary_after[0].get("open_workspace_id") != checkout_owner_id
        ):
            raise RuntimeError("Primary checkout ownership changed while closing the workspace")
    if _git_worktree_snapshot(git_paths) != git_worktrees_before:
        raise RuntimeError("Git worktree list changed while closing the workspace")
    if _git_status_snapshot(git_paths) != git_before:
        raise RuntimeError("Git worktree status changed while closing the workspace")
    return {"workspace_id": workspace_id, "closed": True, "already_absent": False}


def _input_schema(spec: dict[str, Any]) -> dict[str, Any]:
    if "input" not in spec:
        return {"type": "object", "properties": {}, "additionalProperties": False}
    return {
        "type": "object",
        "properties": {spec["input"]: {"type": "string", "minLength": 1, "maxLength": 256}},
        "required": [spec["input"]],
        "additionalProperties": False,
    }


def _handle(request: Any) -> dict[str, Any] | None:
    if not isinstance(request, dict):
        return _error_response(None, -32600, "Invalid Request")

    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})
    if not isinstance(method, str) or not isinstance(params, dict):
        return _error_response(request_id, -32600, "Invalid Request") if "id" in request else None

    if method.startswith("notifications/"):
        return None
    if "id" not in request:
        return None

    if method == "initialize":
        requested_version = params.get("protocolVersion")
        # This bridge implements one protocol version; offer it when the client
        # requests an unsupported version, as required by MCP initialization.
        negotiated_version = requested_version if requested_version == PROTOCOL_VERSION else PROTOCOL_VERSION
        return _json_response(
            request_id,
            {
                "protocolVersion": negotiated_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": "Read-only Herdr status and inventory plus guarded cleanup of one clean linked worktree or one eligible workspace.",
            },
        )
    if method == "ping":
        return _json_response(request_id, {})
    if method == "tools/list":
        tools = [
            {
                "name": name,
                "description": spec["description"],
                "inputSchema": _input_schema(spec),
            }
            for name, spec in TOOLS.items()
        ]
        return _json_response(request_id, {"tools": tools})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or name not in TOOLS:
            return _json_response(request_id, _tool_error("Unknown Herdr tool"))
        if not isinstance(arguments, dict):
            return _json_response(request_id, _tool_error("Tool arguments must be an object"))
        try:
            spec = TOOLS[name]
            if "input" in spec:
                if set(arguments) != {spec["input"]}:
                    raise ValueError(f"This tool requires exactly one {spec['input']} string")
                value = _validate_workspace_id(arguments[spec["input"]])
                result = _mutate_tool(name, value)
            else:
                if arguments:
                    raise ValueError("This Herdr tool accepts no arguments")
                result = _run_herdr(spec)
            return _json_response(request_id, _tool_success(result))
        except (RuntimeError, ValueError) as exc:
            return _json_response(request_id, _tool_error(str(exc)))

    return _error_response(request_id, -32601, "Method not found")


def main() -> int:
    while True:
        raw_line = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
        if not raw_line:
            break
        if len(raw_line) > MAX_REQUEST_BYTES:
            while raw_line and not raw_line.endswith(b"\n"):
                raw_line = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
            print(json.dumps(_error_response(None, -32700, "Request exceeds the 1 MiB limit")), flush=True)
            continue
        try:
            request = json.loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            print(json.dumps(_error_response(None, -32700, "Parse error")), flush=True)
            continue
        response = _handle(request)
        if response is not None:
            print(json.dumps(response, ensure_ascii=False, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
