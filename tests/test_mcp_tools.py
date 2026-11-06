"""AP2/AP6: the four MCP tools through a real MCP client session (in-process)."""

from __future__ import annotations

import unicodedata

import pytest
from conftest import default_tree
from mcp import Client

from levuvo_nextcloud_mcp import __version__
from levuvo_nextcloud_mcp.server import SERVER_NAME, create_mcp

pytestmark = pytest.mark.asyncio

TOOLS = {"list_files", "get_file_info", "search_files", "read_file"}


@pytest.fixture
def server(make_settings, nextcloud):
    settings = make_settings("dir:05_Projekte", "file:06_Marketing/CI.md", denied=("05_Projekte/Vertraulich",))
    return create_mcp(settings, transport=nextcloud.transport())


def text_of(result) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


async def test_initialize_reports_server_identity(server) -> None:
    async with Client(server) as client:
        info = client.server_info if hasattr(client, "server_info") else None
        tools = await client.list_tools()
    assert {tool.name for tool in tools.tools} == TOOLS
    if info is not None:
        assert info.name == SERVER_NAME and info.version == __version__


async def test_tools_are_annotated_read_only_and_closed_world(server) -> None:
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
    assert len(tools) == 4
    for tool in tools:
        a = tool.annotations
        assert (a.read_only_hint, a.destructive_hint, a.idempotent_hint, a.open_world_hint) == (
            True,
            False,
            True,
            False,
        )
        assert a.title


async def test_schemas_carry_limits(server) -> None:
    async with Client(server) as client:
        schemas = {tool.name: tool.input_schema["properties"] for tool in (await client.list_tools()).tools}
    assert schemas["list_files"]["limit"]["minimum"] == 1 and schemas["list_files"]["limit"]["maximum"] == 250
    assert schemas["read_file"]["max_chars"]["minimum"] == 100 and schemas["read_file"]["max_chars"]["maximum"] == 30000
    assert schemas["read_file"]["path"]["maxLength"] == 1024 and schemas["read_file"]["path"]["minLength"] == 1
    assert schemas["search_files"]["query"]["maxLength"] == 120
    assert schemas["search_files"]["max_depth"]["maximum"] == 6
    assert schemas["search_files"]["max_results"]["maximum"] == 100


async def test_all_four_tools_work(server) -> None:
    async with Client(server) as client:
        listing = await client.call_tool("list_files", {})
        folder = await client.call_tool("list_files", {"path": "05_Projekte"})
        info = await client.call_tool("get_file_info", {"path": "06_Marketing/CI.md"})
        search = await client.call_tool("search_files", {"query": "plan"})
        read = await client.call_tool("read_file", {"path": "05_Projekte/Offen/Plan.md", "max_chars": 200})
    for result in (listing, folder, info, search, read):
        assert not result.is_error, text_of(result)
    assert [i["path"] for i in listing.structured_content["items"]] == ["05_Projekte", "06_Marketing/CI.md"]
    assert [i["name"] for i in folder.structured_content["items"]] == ["Geschäftsführung", "Offen"]
    assert info.structured_content["is_dir"] is False
    assert {r["path"] for r in search.structured_content["results"]} == {
        "05_Projekte/Offen/Plan.md",
        "05_Projekte/Offen/Kunde A/Projektplan.txt",
    }
    assert read.structured_content["text"].startswith("# Freigegeben")


@pytest.mark.parametrize(
    "tool, args, message",
    [
        ("read_file", {"path": "08_Privat/Tagebuch.txt"}, "The path is not released for the MCP agent."),
        (
            "read_file",
            {"path": "05_Projekte/vertraulich/Kundenvertrag.pdf"},
            "The path is not released for the MCP agent.",
        ),
        ("get_file_info", {"path": "../etc/passwd"}, "'.' and '..'"),
        ("get_file_info", {"path": "/05_Projekte"}, "relative"),
        ("get_file_info", {"path": "05_Projekte%2FVertraulich"}, "URL-encoded"),
        ("read_file", {"path": "05_Projekte/Offen/fehlt.md"}, "File or folder not found."),
        ("read_file", {"path": "05_Projekte/Offen/Kunde A"}, "This is a folder. Use list_files."),
        ("read_file", {"path": "07_Ablage/x", "max_chars": 500}, "The path is not released for the MCP agent."),
        ("list_files", {"path": "06_Marketing/CI.md"}, "This is a file. Use get_file_info or read_file."),
    ],
)
async def test_expected_errors_reach_the_client_with_their_message(server, tool, args, message) -> None:
    async with Client(server) as client:
        result = await client.call_tool(tool, args)
    assert result.is_error
    text = text_of(result)
    assert message in text
    assert "Traceback" not in text and "DUMMY_TEST_SECRET" not in text


@pytest.mark.parametrize(
    "tool, args",
    [
        ("read_file", {"path": "05_Projekte/Offen/Plan.md", "max_chars": 5}),
        ("read_file", {"path": "05_Projekte/Offen/Plan.md", "max_chars": 999999}),
        ("read_file", {"path": ""}),
        ("read_file", {"path": "a" * 1025}),
        ("list_files", {"limit": 0}),
        ("search_files", {"query": ""}),
        ("search_files", {"query": "a", "max_depth": 99}),
        ("read_file", {}),
    ],
)
async def test_schema_validation_rejects_out_of_range_arguments(server, tool, args) -> None:
    async with Client(server) as client:
        result = await client.call_tool(tool, args)
    assert result.is_error
    assert "validation error" in text_of(result)


async def test_unsupported_format_and_limits_are_explained(make_settings) -> None:
    fake = default_tree()
    fake.files["05_Projekte/Offen/bild.png"] = b"\x89PNG"
    fake.files["05_Projekte/Offen/gross.txt"] = b"x" * 5000
    server = create_mcp(make_settings("dir:05_Projekte/Offen", max_file_bytes=1000), transport=fake.transport())
    async with Client(server) as client:
        png = await client.call_tool("read_file", {"path": "05_Projekte/Offen/bild.png"})
        big = await client.call_tool("read_file", {"path": "05_Projekte/Offen/gross.txt"})
    assert png.is_error and "is not supported" in text_of(png)
    assert big.is_error and "download limit" in text_of(big)


async def test_nextcloud_auth_failure_is_reported_without_details(make_settings) -> None:
    fake = default_tree()
    fake.status_override["05_Projekte"] = 401
    server = create_mcp(make_settings("dir:05_Projekte"), transport=fake.transport())
    async with Client(server) as client:
        result = await client.call_tool("list_files", {})
    assert result.is_error and "check the username and app password" in text_of(result)


async def test_unexpected_crash_returns_generic_message(server, monkeypatch) -> None:
    from levuvo_nextcloud_mcp.webdav import NextcloudWebDAV

    async def boom(self, path):
        raise RuntimeError("internal detail /etc/secret DUMMY_TEST_SECRET")

    monkeypatch.setattr(NextcloudWebDAV, "info", boom)
    async with Client(server) as client:
        result = await client.call_tool("get_file_info", {"path": "05_Projekte"})
    assert result.is_error
    assert text_of(result) == "Error executing tool get_file_info"


async def test_nfd_paths_work_through_the_protocol(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "read_file", {"path": unicodedata.normalize("NFD", "05_Projekte/Offen/Ümlaut Übersicht.md")}
        )
    assert not result.is_error and result.structured_content["text"] == "Umlaute äöü"


async def test_one_http_client_per_server(server) -> None:
    async with Client(server) as client:
        await client.call_tool("list_files", {})
        first = server.levuvo_client.get()
        await client.call_tool("get_file_info", {"path": "06_Marketing/CI.md"})
        assert server.levuvo_client.get() is first
    await server.levuvo_client.aclose()
