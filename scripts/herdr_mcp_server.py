#!/usr/bin/env python3
"""A small, read-only MCP stdio bridge for the local Herdr CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any


PROTOCOL_VERSION = "2025-11-25"
SERVER_INFO = {"name": "travel-recommendation-herdr", "version": "1.0.0"}
MAX_REQUEST_BYTES = 1_048_576
HERDR_TIMEOUT_SECONDS = 8

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


def _run_herdr(spec: dict[str, Any]) -> Any:
    environment = os.environ.copy()
    environment["HERDR_ENV"] = "1"
    try:
        completed = subprocess.run(
            ["herdr", *spec["command"]],
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
        return _filter_result(spec, json.loads(completed.stdout))
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("Herdr returned an invalid or unsupported JSON response") from exc


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
                "instructions": "Read-only access to Herdr server status, workspace labels, and agent lifecycle locations.",
            },
        )
    if method == "ping":
        return _json_response(request_id, {})
    if method == "tools/list":
        tools = [
            {
                "name": name,
                "description": spec["description"],
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            }
            for name, spec in TOOLS.items()
        ]
        return _json_response(request_id, {"tools": tools})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or name not in TOOLS:
            return _json_response(request_id, _tool_error("Unknown read-only Herdr tool"))
        if not isinstance(arguments, dict) or arguments:
            return _json_response(request_id, _tool_error("This Herdr tool accepts no arguments"))
        try:
            return _json_response(request_id, _tool_success(_run_herdr(TOOLS[name])))
        except RuntimeError as exc:
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
