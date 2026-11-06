"""Release consistency and static read-only guarantees."""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

from levuvo_nextcloud_mcp import __version__, webdav

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "levuvo_nextcloud_mcp"


def test_single_version_source() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == "0.5.0"
    assert "version" in pyproject["project"]["dynamic"]
    assert pyproject["tool"]["hatch"]["version"]["path"] == "src/levuvo_nextcloud_mcp/__init__.py"
    for source in SRC.glob("*.py"):
        if source.name == "__init__.py":
            continue
        assert not re.search(r"""["']0\.\d+\.\d+["']""", source.read_text(encoding="utf-8")), source


def test_changelog_starts_with_current_version() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## (\d+\.\d+\.\d+)", changelog, re.MULTILINE)
    assert first and first.group(1) == __version__


def test_user_agent_uses_package_version(make_settings) -> None:
    client = webdav.NextcloudWebDAV(make_settings("dir:A"))
    assert client._http.headers["User-Agent"] == f"Levuvo-Nextcloud-MCP/{__version__}"


def test_webdav_client_only_uses_read_methods() -> None:
    """Static check: every HTTP method literal passed to the client is GET or PROPFIND."""
    tree = ast.parse((SRC / "webdav.py").read_text(encoding="utf-8"))
    methods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in {"_request", "stream", "request"}:
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                methods.add(first.value)
    assert methods == {"GET", "PROPFIND"}
    assert webdav.ALLOWED_METHODS == frozenset({"GET", "PROPFIND"})
    for source in SRC.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        for verb in ("PUT", "DELETE", "MKCOL", "MOVE", "COPY", "PROPPATCH", "LOCK"):
            assert f'"{verb}"' not in text and f"'{verb}'" not in text, (source, verb)


def test_no_shell_or_dynamic_code_execution() -> None:
    for source in SRC.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        for needle in ("subprocess", "os.system", "eval(", "exec(", "pickle", "shell=True"):
            assert needle not in text, (source, needle)


def test_lockfiles_present() -> None:
    for name in ("uv.lock", "requirements.lock", "requirements-dev.lock"):
        assert (ROOT / name).is_file(), name
