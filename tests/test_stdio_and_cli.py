"""stdio compatibility (real subprocess, as Claude Code starts it) and CLI behaviour."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


def child_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "NEXTCLOUD_URL=https://nextcloud.invalid\n"  # .invalid never resolves: no real network access
        "NEXTCLOUD_USERNAME=agent.levuvo\n"
        "NEXTCLOUD_APP_PASSWORD=DUMMY_TEST_SECRET\n"
        "NEXTCLOUD_ALLOWED_PATHS=dir:00_Agent_Test\n"
        "NEXTCLOUD_DENIED_PATHS=dir:00_Agent_Test/Intern\n"
        "NEXTCLOUD_TIMEOUT_SECONDS=2\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("NEXTCLOUD_", "MCP_", "LEVUVO_"))}
    env.update({"LEVUVO_MCP_ENV_FILE": str(env_file), "PYTHONDONTWRITEBYTECODE": "1"})
    env.update(extra)
    return env


def run_cli(tmp_path: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "levuvo_nextcloud_mcp", *args],
        cwd=tmp_path,
        env=child_env(tmp_path, **env),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.asyncio
async def test_stdio_handshake_and_tool_calls(tmp_path: Path) -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "levuvo_nextcloud_mcp"], env=child_env(tmp_path), cwd=str(tmp_path)
    )
    async with Client(params, read_timeout_seconds=30) as client:
        tools = await client.list_tools()
        denied = await client.call_tool("read_file", {"path": "00_Agent_Test/intern/geheim.md"})
        outside = await client.call_tool("list_files", {"path": "01_Unternehmen"})
        offline = await client.call_tool("list_files", {})
    assert {t.name for t in tools.tools} == {"list_files", "get_file_info", "search_files", "read_file"}
    assert denied.is_error and "The path is not released for the MCP agent." in denied.content[0].text
    assert outside.is_error and "The path is not released for the MCP agent." in outside.content[0].text
    assert offline.is_error and "Connection to Nextcloud failed" in offline.content[0].text
    assert "DUMMY_TEST_SECRET" not in offline.content[0].text


def test_check_config_prints_summary_without_secrets(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "--check-config")
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["version"] == "0.5.2"
    assert summary["allowed_paths"] == ["dir:00_Agent_Test"]
    assert summary["denied_paths"] == ["dir:00_Agent_Test/Intern"]
    assert "DUMMY_TEST_SECRET" not in result.stdout + result.stderr


def test_configuration_errors_exit_with_code_2(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "--check-config", NEXTCLOUD_DENIED_PATHS="DIR:00_Agent_Test/Intern")
    assert result.returncode == 2
    assert result.stderr.startswith("Configuration error: ") and "unknown prefix" in result.stderr
    assert "Traceback" not in result.stderr


def test_http_transport_requires_valid_remote_settings(tmp_path: Path) -> None:
    result = run_cli(
        tmp_path, "--transport", "http", "--check-config", MCP_AUTH_MODE="static", MCP_STATIC_TOKEN="short"
    )
    assert result.returncode == 2 and "MCP_STATIC_TOKEN" in result.stderr


def test_check_nextcloud_reports_network_failure(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "--check-nextcloud")
    assert result.returncode == 1 and "Nextcloud check failed for dir:00_Agent_Test: " in result.stderr


def test_version_flag(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "--version")
    assert result.returncode == 0 and result.stdout.strip().endswith("0.5.2")


def test_permissive_env_file_warning_on_stderr(tmp_path: Path) -> None:
    env = child_env(tmp_path)
    Path(env["LEVUVO_MCP_ENV_FILE"]).chmod(0o644)
    result = subprocess.run(
        [sys.executable, "-m", "levuvo_nextcloud_mcp", "--check-config"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0 and "chmod 600" in result.stderr
