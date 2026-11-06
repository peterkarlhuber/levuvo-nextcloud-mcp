"""0.5.1 regression: search_files must find explicitly released root entries themselves.

Live finding of 2026-11-06 (user-reported): ``search_files("Agent")`` and ``search_files("Agent Test")``
did not return the released folder ``00_Agent Test``, while ``search_files("test.txt")`` worked.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeNextcloud
from mcp import Client

from levuvo_nextcloud_mcp.server import create_mcp
from levuvo_nextcloud_mcp.settings import ENV_FILE_VARIABLE, Settings, load_env_file
from levuvo_nextcloud_mcp.webdav import NextcloudWebDAV

pytestmark = pytest.mark.asyncio

ROOT = "00_Agent Test"


def agent_tree() -> FakeNextcloud:
    fake = FakeNextcloud(
        files={
            f"{ROOT}/test.txt": b"Hallo",
            f"{ROOT}/Unterordner/notiz.md": b"Notiz",
            f"{ROOT}/Agent Geheim/geheim.md": b"SECRET",
            "01_Agent Archiv/alt.md": b"Alt",
            "02_Finanzen/Agent Bilanz.xlsx": b"FINANZEN",
            "02_Finanzen/Agent Test Kopie.txt": b"FINANZEN",
            "03_Agent Datei.txt": b"Datei",
        }
    )
    fake.folders.add("04_Leer")
    return fake


def client(settings: Settings, fake: FakeNextcloud) -> NextcloudWebDAV:
    return NextcloudWebDAV(settings, transport=fake.transport())


def paths(result: dict) -> list[str]:
    return [r["path"] for r in result["results"]]


async def test_root_folder_with_space_is_found(make_settings) -> None:
    fake = agent_tree()
    async with client(make_settings(f"dir:{ROOT}"), fake) as dav:
        short = await dav.search_files("Agent")
        full = await dav.search_files("Agent Test")
    assert paths(short) == [ROOT, f"{ROOT}/Agent Geheim"]
    assert paths(full) == [ROOT]
    assert short["results"][0]["is_dir"] is True
    assert short["complete"] is True and full["complete"] is True


@pytest.mark.parametrize("query", ["agent test", "AGENT TEST", "aGeNt tEsT", "00_agent"])
async def test_root_match_is_case_insensitive(make_settings, query: str) -> None:
    async with client(make_settings(f"dir:{ROOT}"), agent_tree()) as dav:
        result = await dav.search_files(query)
    assert paths(result) == [ROOT]


async def test_file_search_behaves_as_before(make_settings) -> None:
    async with client(make_settings(f"dir:{ROOT}"), agent_tree()) as dav:
        result = await dav.search_files("test.txt")
    assert paths(result) == [f"{ROOT}/test.txt"]


async def test_multiple_roots_and_direct_file_share(make_settings) -> None:
    settings = make_settings(f"dir:{ROOT}", "dir:01_Agent Archiv", "file:03_Agent Datei.txt", "dir:04_Leer")
    async with client(settings, agent_tree()) as dav:
        agent = await dav.search_files("Agent")
        datei = await dav.search_files("datei")
        leer = await dav.search_files("Leer")
    assert sorted(paths(agent)) == sorted([ROOT, "01_Agent Archiv", "03_Agent Datei.txt", f"{ROOT}/Agent Geheim"])
    assert paths(datei) == ["03_Agent Datei.txt"]
    assert datei["results"][0]["is_dir"] is False
    assert paths(leer) == ["04_Leer"]


async def test_subfolders_are_found(make_settings) -> None:
    async with client(make_settings(f"dir:{ROOT}"), agent_tree()) as dav:
        result = await dav.search_files("unterordner")
    assert paths(result) == [f"{ROOT}/Unterordner"]


async def test_empty_result(make_settings) -> None:
    async with client(make_settings(f"dir:{ROOT}"), agent_tree()) as dav:
        result = await dav.search_files("gibt es nicht")
    assert result["results"] == [] and result["complete"] is True


async def test_max_results_counts_root_hits(make_settings) -> None:
    settings = make_settings(f"dir:{ROOT}", "dir:01_Agent Archiv", "file:03_Agent Datei.txt")
    async with client(settings, agent_tree()) as dav:
        result = await dav.search_files("Agent", max_results=2)
    assert len(result["results"]) == 2 and result["complete"] is False


async def test_depth_zero_finds_root_and_direct_children_only(make_settings) -> None:
    async with client(make_settings(f"dir:{ROOT}"), agent_tree()) as dav:
        root = await dav.search_files("Agent Test", max_depth=0)
        child = await dav.search_files("test.txt", max_depth=0)
        deep0 = await dav.search_files("notiz", max_depth=0)
        deep1 = await dav.search_files("notiz", max_depth=1)
    assert paths(root) == [ROOT]
    assert paths(child) == [f"{ROOT}/test.txt"]
    assert paths(deep0) == []
    assert paths(deep1) == [f"{ROOT}/Unterordner/notiz.md"]


async def test_denylist_still_applies(make_settings) -> None:
    fake = agent_tree()
    settings = make_settings(f"dir:{ROOT}", denied=(f"dir:{ROOT}/Agent Geheim",))
    async with client(settings, fake) as dav:
        agent = await dav.search_files("Agent")
        geheim = await dav.search_files("geheim")
    assert paths(agent) == [ROOT]
    assert paths(geheim) == []
    assert f"{ROOT}/Agent Geheim" not in fake.paths_requested()


async def test_no_hits_outside_policy(make_settings) -> None:
    fake = agent_tree()
    async with client(make_settings(f"dir:{ROOT}"), fake) as dav:
        results = [await dav.search_files(q) for q in ("Agent", "Agent Test", "Finanzen", "Bilanz", "Kopie")]
    found = [p for r in results for p in paths(r)]
    assert not any(p.startswith("02_Finanzen") for p in found)
    assert not any(p.startswith("02_Finanzen") for p in fake.paths_requested())
    assert "" not in fake.paths_requested()  # never lists the account root


async def test_overlapping_roots_produce_no_duplicates(make_settings) -> None:
    settings = make_settings(f"dir:{ROOT}", f"dir:{ROOT}/Unterordner", f"file:{ROOT}/test.txt")
    async with client(settings, agent_tree()) as dav:
        sub = await dav.search_files("Unterordner")
        note = await dav.search_files("notiz")
        test = await dav.search_files("test")
    assert paths(sub) == [f"{ROOT}/Unterordner"]
    assert paths(note) == [f"{ROOT}/Unterordner/notiz.md"]
    assert sorted(paths(test)) == sorted([ROOT, f"{ROOT}/test.txt"])
    assert sub["directories_scanned"] == 3  # root, Unterordner, Agent Geheim - each once


async def test_root_hit_needs_no_additional_requests(make_settings) -> None:
    fake = agent_tree()
    async with client(make_settings(f"dir:{ROOT}"), fake) as dav:
        result = await dav.search_files("Agent")
    # One depth-0 PROPFIND for the root (already done in 0.5.0) plus one depth-1 PROPFIND per scanned folder.
    assert len(fake.requests) == 1 + result["directories_scanned"]
    assert all(method == "PROPFIND" for method, _ in fake.requests)


# --------------------------------------------------------------------------- MCP tool-call level
async def test_search_tool_finds_root_via_mcp(make_settings) -> None:
    fake = agent_tree()
    server = create_mcp(make_settings(f"dir:{ROOT}", "file:03_Agent Datei.txt"), transport=fake.transport())
    async with Client(server) as mcp_client:
        agent = await mcp_client.call_tool("search_files", {"query": "Agent"})
        agent_test = await mcp_client.call_tool("search_files", {"query": "Agent Test"})
        test_txt = await mcp_client.call_tool("search_files", {"query": "test.txt"})
        finanzen = await mcp_client.call_tool("list_files", {"path": "02_Finanzen"})
    for result in (agent, agent_test, test_txt):
        assert not result.is_error
    assert sorted(paths(agent.structured_content)) == sorted([ROOT, "03_Agent Datei.txt", f"{ROOT}/Agent Geheim"])
    assert paths(agent_test.structured_content) == [ROOT]
    assert paths(test_txt.structured_content) == [f"{ROOT}/test.txt"]
    assert finanzen.is_error and "nicht für den MCP-Agenten freigegeben" in finanzen.content[0].text
    assert not any(p.startswith("02_Finanzen") for p in fake.paths_requested())


# --------------------------------------------------------------------------- .env with a space in the path
async def test_env_file_with_unquoted_space_in_allowed_path(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "NEXTCLOUD_URL=https://storage.levuvo.com\nNEXTCLOUD_USERNAME=agent.levuvo\n"
        "NEXTCLOUD_APP_PASSWORD=DUMMY_TEST_SECRET\nNEXTCLOUD_ALLOWED_PATHS=dir:00_Agent Test\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    clean_env.setenv(ENV_FILE_VARIABLE, str(env_file))
    load_env_file()
    settings = Settings.from_env()
    assert [(r.path, r.kind) for r in settings.policy.allowed] == [(ROOT, "dir")]
