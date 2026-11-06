"""0.5.3: configurable search limits, search below a folder, incomplete_reasons, version and active limits."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import SECRET, FakeNextcloud
from mcp import Client
from test_stdio_and_cli import run_cli

from levuvo_nextcloud_mcp import __version__
from levuvo_nextcloud_mcp.errors import AccessDeniedError, ConfigurationError, InvalidArgumentError
from levuvo_nextcloud_mcp.server import INSTRUCTIONS, create_mcp
from levuvo_nextcloud_mcp.settings import Settings
from levuvo_nextcloud_mcp.webdav import SEARCH_CONCURRENCY, NextcloudWebDAV

ACCESS_DENIED = "The path is not released for the MCP agent."
SEARCH_VARS = ("NEXTCLOUD_SEARCH_MAX_DEPTH", "NEXTCLOUD_SEARCH_MAX_DIRECTORIES", "NEXTCLOUD_SEARCH_MAX_RESULTS")


def base_env(monkeypatch: pytest.MonkeyPatch, **extra: str) -> None:
    values = {
        "NEXTCLOUD_URL": "https://storage.levuvo.com",
        "NEXTCLOUD_USERNAME": "agent.levuvo",
        "NEXTCLOUD_APP_PASSWORD": "DUMMY_TEST_SECRET",
        "NEXTCLOUD_ALLOWED_PATHS": "dir:01_Unternehmen",
        **extra,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def deep_tree(levels: int) -> FakeNextcloud:
    """R/L1/L2/.../Ln, each level holding one file 'hit-<n>.md'."""
    files, folder = {}, "R"
    for n in range(1, levels + 1):
        folder = f"{folder}/L{n}"
        files[f"{folder}/hit-{n}.md"] = b"x"
    return FakeNextcloud(files=files)


def wide_tree(count: int, hit_at: int | None = None) -> FakeNextcloud:
    files = {f"R/d{i:04d}/file.md": b"x" for i in range(count)}
    if hit_at is not None:
        files[f"R/d{hit_at:04d}/treffer.md"] = b"x"
    return FakeNextcloud(files=files)


def dav(settings: Settings, fake: FakeNextcloud) -> NextcloudWebDAV:
    return NextcloudWebDAV(settings, transport=fake.transport())


def paths(result: dict) -> list[str]:
    return [entry["path"] for entry in result["results"]]


# --------------------------------------------------------------------------- configuration
def test_defaults_equal_the_fixed_limits_of_0_5_2(clean_env) -> None:
    base_env(clean_env)
    s = Settings.from_env()
    assert (s.search_max_depth, s.search_max_directories, s.search_max_results) == (6, 100, 100)
    assert s.max_file_bytes == 25_000_000


def test_maximum_values_can_be_configured(clean_env) -> None:
    base_env(
        clean_env,
        NEXTCLOUD_SEARCH_MAX_DEPTH="20",
        NEXTCLOUD_SEARCH_MAX_DIRECTORIES="1000",
        NEXTCLOUD_SEARCH_MAX_RESULTS="500",
        NEXTCLOUD_MAX_FILE_BYTES="100000000",
    )
    s = Settings.from_env()
    assert (s.search_max_depth, s.search_max_directories, s.search_max_results, s.max_file_bytes) == (
        20,
        1000,
        500,
        100_000_000,
    )


@pytest.mark.parametrize(
    "name, value, message",
    [
        ("NEXTCLOUD_SEARCH_MAX_DEPTH", "2", "NEXTCLOUD_SEARCH_MAX_DEPTH must be between 3 and 20."),
        ("NEXTCLOUD_SEARCH_MAX_DEPTH", "21", "NEXTCLOUD_SEARCH_MAX_DEPTH must be between 3 and 20."),
        ("NEXTCLOUD_SEARCH_MAX_DEPTH", "-6", "NEXTCLOUD_SEARCH_MAX_DEPTH must be between 3 and 20."),
        ("NEXTCLOUD_SEARCH_MAX_DEPTH", "deep", "NEXTCLOUD_SEARCH_MAX_DEPTH must be a number"),
        ("NEXTCLOUD_SEARCH_MAX_DEPTH", "6.5", "NEXTCLOUD_SEARCH_MAX_DEPTH must be a number"),
        ("NEXTCLOUD_SEARCH_MAX_DIRECTORIES", "0", "NEXTCLOUD_SEARCH_MAX_DIRECTORIES must be between 1 and 1000."),
        ("NEXTCLOUD_SEARCH_MAX_DIRECTORIES", "1001", "NEXTCLOUD_SEARCH_MAX_DIRECTORIES must be between 1 and 1000."),
        ("NEXTCLOUD_SEARCH_MAX_DIRECTORIES", "", "NEXTCLOUD_SEARCH_MAX_DIRECTORIES must be a number"),
        ("NEXTCLOUD_SEARCH_MAX_RESULTS", "24", "NEXTCLOUD_SEARCH_MAX_RESULTS must be between 25 and 500."),
        ("NEXTCLOUD_SEARCH_MAX_RESULTS", "501", "NEXTCLOUD_SEARCH_MAX_RESULTS must be between 25 and 500."),
        ("NEXTCLOUD_SEARCH_MAX_RESULTS", "1e3", "NEXTCLOUD_SEARCH_MAX_RESULTS must be a number"),
    ],
)
def test_invalid_search_limits_are_rejected(clean_env, name: str, value: str, message: str) -> None:
    base_env(clean_env, **{name: value})
    with pytest.raises(ConfigurationError) as excinfo:
        Settings.from_env()
    assert str(excinfo.value).startswith(message)


def test_search_limits_never_change_access(make_settings) -> None:
    small = make_settings("dir:A", denied=("A/B",))
    large = make_settings("dir:A", denied=("A/B",), search_max_depth=20, search_max_directories=1000)
    for path in ("A/x", "A/B/x", "C/x"):
        assert small.policy.matching_allows(path) == large.policy.matching_allows(path)
        assert small.policy.is_denied(path) == large.policy.is_denied(path)


def test_check_config_prints_the_effective_limits(tmp_path: Path) -> None:
    result = run_cli(
        tmp_path,
        "--check-config",
        NEXTCLOUD_SEARCH_MAX_DEPTH="20",
        NEXTCLOUD_SEARCH_MAX_DIRECTORIES="1000",
        NEXTCLOUD_SEARCH_MAX_RESULTS="500",
        NEXTCLOUD_MAX_FILE_BYTES="100000000",
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["version"] == __version__
    assert summary["search"] == {
        "max_depth": 20,
        "max_directories": 1000,
        "max_results": 500,
        "concurrency": SEARCH_CONCURRENCY,
    }
    assert (summary["max_file_bytes"], summary["max_file_bytes_default"]) == (100_000_000, 25_000_000)
    assert SECRET not in result.stdout and "app_password" not in result.stdout


def test_check_config_rejects_invalid_search_limit(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "--check-config", NEXTCLOUD_SEARCH_MAX_RESULTS="5000")
    assert result.returncode == 2
    assert result.stderr == "Configuration error: NEXTCLOUD_SEARCH_MAX_RESULTS must be between 25 and 500.\n"


# --------------------------------------------------------------------------- limits in the implementation
async def test_arguments_above_the_configured_caps_are_rejected(make_settings) -> None:
    async with dav(make_settings("dir:R"), deep_tree(2)) as client:
        with pytest.raises(InvalidArgumentError, match=r"max_depth must be between 0 and 6\."):
            await client.search_files("hit", max_depth=7)
        with pytest.raises(InvalidArgumentError, match=r"max_results must be between 1 and 100\."):
            await client.search_files("hit", max_results=101)
        with pytest.raises(InvalidArgumentError):
            await client.search_files("hit", max_depth=True)
    async with dav(make_settings("dir:R", search_max_depth=20, search_max_results=500), deep_tree(2)) as client:
        assert (await client.search_files("hit", max_depth=20, max_results=500))["complete"] is True
        with pytest.raises(InvalidArgumentError, match=r"max_depth must be between 0 and 20\."):
            await client.search_files("hit", max_depth=21)


async def test_search_deeper_than_six_levels(make_settings) -> None:
    fake = deep_tree(12)
    async with dav(make_settings("dir:R", search_max_depth=20), fake) as client:
        deep = await client.search_files("hit", max_depth=15)
        capped = await client.search_files("hit", max_depth=6)
    assert len(deep["results"]) == 12 and deep["complete"] is True and deep["incomplete_reasons"] == []
    # max_depth=6 descends six levels below R: R and L1..L6 are listed, L7 and deeper are not.
    assert paths(capped)[-1].endswith("L6/hit-6.md") and len(capped["results"]) == 6
    assert capped["complete"] is False and capped["incomplete_reasons"] == ["depth_limit"]


async def test_search_over_more_than_100_folders(make_settings) -> None:
    fake = wide_tree(250, hit_at=240)
    async with dav(make_settings("dir:R", search_max_directories=1000), fake) as client:
        found = await client.search_files("treffer", max_depth=1)
    async with dav(make_settings("dir:R"), fake) as client:
        default = await client.search_files("treffer", max_depth=1)
    assert paths(found) == ["R/d0240/treffer.md"] and found["directories_scanned"] == 251
    assert found["complete"] is True
    assert fake.max_concurrent <= SEARCH_CONCURRENCY
    # Without the new variable the 0.5.2 budget of 100 folders applies.
    assert default["directories_scanned"] == 100 and default["results"] == []
    assert default["complete"] is False and default["incomplete_reasons"] == ["directory_limit"]


async def test_configured_directory_budget_is_exact(make_settings) -> None:
    fake = wide_tree(40)
    for budget in (1, 7, 41):
        async with dav(make_settings("dir:R", search_max_directories=budget), fake) as client:
            result = await client.search_files("file", max_depth=2, max_results=100)
        assert result["directories_scanned"] == min(budget, 41)
        assert result["complete"] is (budget >= 41), budget


# --------------------------------------------------------------------------- completeness
async def test_complete_only_when_the_area_was_searched_entirely(make_settings) -> None:
    fake = FakeNextcloud(files={"R/a.md": b"x", "R/S/b.md": b"x", "R/S/T/c.md": b"x"})
    async with dav(make_settings("dir:R"), fake) as client:
        full = await client.search_files(".md", max_depth=3)
        shallow = await client.search_files(".md", max_depth=0)
        limited = await client.search_files(".md", max_results=2)
        exact = await client.search_files(".md", max_results=3)
        none = await client.search_files("nothing-matches")
    assert full["complete"] is True and full["incomplete_reasons"] == [] and len(full["results"]) == 3
    assert shallow["complete"] is False and shallow["incomplete_reasons"] == ["depth_limit"]
    assert limited["complete"] is False and limited["incomplete_reasons"] == ["result_limit"]
    # Exactly max_results hits and nothing left: the search was complete.
    assert exact["complete"] is True and len(exact["results"]) == 3
    assert none["results"] == [] and none["complete"] is True


async def test_several_reasons_are_reported_together(make_settings) -> None:
    fake = wide_tree(30)
    for i in range(30):
        fake.folders.add(f"R/d{i:04d}/deeper")
    async with dav(make_settings("dir:R", search_max_directories=10), fake) as client:
        result = await client.search_files("file", max_depth=1, max_results=25)
    assert result["incomplete_reasons"] == ["depth_limit", "directory_limit"]
    assert result["complete"] is False


async def test_folder_without_subfolders_at_the_depth_limit_stays_complete(make_settings) -> None:
    fake = FakeNextcloud(files={"R/S/file.md": b"x"})
    async with dav(make_settings("dir:R"), fake) as client:
        result = await client.search_files("file", max_depth=1)
    assert result["complete"] is True


# --------------------------------------------------------------------------- search below a folder
def project_tree() -> FakeNextcloud:
    return FakeNextcloud(
        files={
            "05_Projekte/Offen/Rechnung-1.pdf": b"x",
            "05_Projekte/Offen/Kunde A/Rechnung-2.pdf": b"x",
            "05_Projekte/Offen/Vertraulich/Rechnung-geheim.pdf": b"SECRET",
            "05_Projekte/Archiv/Rechnung-alt.pdf": b"x",
            "05_Projekte/Rechnung-root.pdf": b"x",
            "02_Finanzen/Rechnung-finanzen.pdf": b"x",
        }
    )


@pytest.fixture
def project_settings(make_settings) -> Settings:
    return make_settings("dir:05_Projekte", denied=("05_Projekte/Offen/Vertraulich",))


async def test_search_inside_a_subfolder_only(project_settings) -> None:
    fake = project_tree()
    async with dav(project_settings, fake) as client:
        scoped = await client.search_files("Rechnung", path="05_Projekte/Offen", max_depth=6)
        everything = await client.search_files("Rechnung")
        offen = await client.search_files("Offen", path="05_Projekte/Offen")
    assert scoped["path"] == "05_Projekte/Offen" and everything["path"] == ""
    assert sorted(paths(scoped)) == ["05_Projekte/Offen/Kunde A/Rechnung-2.pdf", "05_Projekte/Offen/Rechnung-1.pdf"]
    assert all(p.startswith("05_Projekte/Offen/") for p in paths(scoped))
    assert scoped["complete"] is True
    assert "05_Projekte/Archiv/Rechnung-alt.pdf" in paths(everything)
    # The start folder itself is not a candidate, only its contents.
    assert offen["results"] == []
    for result in (scoped, everything):
        assert not any("Vertraulich" in p or "02_Finanzen" in p for p in paths(result))
    assert not any("Vertraulich" in path for _, path in fake.requests)
    assert all(method == "PROPFIND" for method, _ in fake.requests)


@pytest.mark.parametrize(
    "path",
    [
        "02_Finanzen",
        "02_Finanzen/Eingangsrechnungen",
        "05_Projekte/Offen/Vertraulich",
        "05_Projekte/Offen/Vertraulich/Sub",
        "05_projekte/offen/vertraulich",
        "05_Projekte/Offen/Vertraulich/",
    ],
)
async def test_unreleased_or_denied_start_path_is_refused_without_network(project_settings, path: str) -> None:
    fake = project_tree()
    async with dav(project_settings, fake) as client:
        with pytest.raises(AccessDeniedError) as excinfo:
            await client.search_files("Rechnung", path=path)
    assert str(excinfo.value) == ACCESS_DENIED
    assert fake.requests == []


@pytest.mark.parametrize(
    "path",
    [
        "05_Projekte/../02_Finanzen",
        "05_Projekte/Offen/../Offen/Vertraulich",
        "05_Projekte%2FOffen",
        "05_Projekte/Offen/Vertraulich%2Fx",
        "/05_Projekte",
        "05_Projekte\\Offen",
        "05_Projekte/​Offen",
        "..",
        ".",
    ],
)
async def test_path_manipulation_is_rejected(project_settings, path: str) -> None:
    fake = project_tree()
    async with dav(project_settings, fake) as client:
        with pytest.raises((AccessDeniedError, InvalidArgumentError)):
            await client.search_files("Rechnung", path=path)
    assert fake.requests == []


async def test_unicode_variant_of_a_denied_path_stays_denied(make_settings) -> None:
    fake = FakeNextcloud(files={"A/Grün/x.md": b"x", "A/ok.md": b"x"})
    settings = make_settings("dir:A", denied=("A/Grün",))
    async with dav(settings, fake) as client:
        with pytest.raises(AccessDeniedError):
            await client.search_files("x", path="A/Grün")  # NFD form of the denied folder


async def test_file_as_start_path_gives_a_clear_error(make_settings) -> None:
    fake = FakeNextcloud(files={"06_Marketing/CI.md": b"x", "05_Projekte/Plan.md": b"x"})
    async with dav(make_settings("dir:05_Projekte", "file:06_Marketing/CI.md"), fake) as client:
        for path in ("05_Projekte/Plan.md", "06_Marketing/CI.md"):
            with pytest.raises(InvalidArgumentError, match=r"path must be a folder; this is a file\."):
                await client.search_files("x", path=path)


async def test_overlapping_shares_give_no_duplicates(make_settings) -> None:
    fake = FakeNextcloud(files={"A/B/Plan.md": b"x", "A/Plan-a.md": b"x", "A/B/C/Plan-c.md": b"x"})
    settings = make_settings("dir:A", "dir:A/B", "file:A/B/Plan.md")
    async with dav(settings, fake) as client:
        all_shares = await client.search_files("Plan")
        scoped = await client.search_files("Plan", path="A")
    for result in (all_shares, scoped):
        assert sorted(paths(result)) == ["A/B/C/Plan-c.md", "A/B/Plan.md", "A/Plan-a.md"]
        assert result["complete"] is True


async def test_search_from_a_folder_within_a_deeper_share(make_settings) -> None:
    fake = FakeNextcloud(files={"A/B/C/D/hit.md": b"x"})
    async with dav(make_settings("dir:A/B"), fake) as client:
        result = await client.search_files("hit", path="A/B/C", max_depth=1)
        with pytest.raises(AccessDeniedError):
            await client.search_files("hit", path="A")  # the parent of a share is not released
    assert paths(result) == ["A/B/C/D/hit.md"]


async def test_released_roots_stay_findable_without_path(make_settings) -> None:
    fake = FakeNextcloud(files={"00_Agent Test/test.txt": b"x", "06_Marketing/CI.md": b"x"})
    async with dav(make_settings("dir:00_Agent Test", "file:06_Marketing/CI.md"), fake) as client:
        agent = await client.search_files("Agent")
        ci = await client.search_files("CI")
    assert paths(agent) == ["00_Agent Test"] and paths(ci) == ["06_Marketing/CI.md"]


# --------------------------------------------------------------------------- MCP discovery
async def discover(settings: Settings, fake: FakeNextcloud | None = None):
    server = create_mcp(settings, transport=(fake or FakeNextcloud()).transport())
    async with Client(server) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        return client.server_info, client.instructions, tools


async def test_version_is_in_every_description_instructions_and_server_info(make_settings) -> None:
    info, instructions, tools = await discover(make_settings("dir:A"))
    assert info.version == __version__
    assert instructions == INSTRUCTIONS and instructions.startswith(f"Levuvo Nextcloud MCP v{__version__}. ")
    titles = {
        "list_files": "List files",
        "get_file_info": "Get file info",
        "search_files": "Search file names",
        "read_file": "Read file",
    }
    for name, title in titles.items():
        assert tools[name].description.startswith(f"Levuvo Nextcloud MCP v{__version__} - {title}. "), name


async def test_descriptions_and_schemas_show_the_active_limits(make_settings) -> None:
    _, _, default = await discover(make_settings("dir:A"))
    _, _, large = await discover(
        make_settings(
            "dir:A",
            max_file_bytes=100_000_000,
            search_max_depth=20,
            search_max_directories=1000,
            search_max_results=500,
        )
    )
    read = large["read_file"].description
    assert "Configured maximum file size: 100000000 bytes." in read
    assert "Default maximum file size: 25000000 bytes" in read
    assert "Configured maximum file size: 25000000 bytes." in default["read_file"].description
    search = large["search_files"].description
    for needle in (
        "Configured maximum depth: 20.",
        "Configured maximum directories per search: 1000.",
        "Configured maximum results: 500.",
        "max_depth (0-20, default 3)",
        "max_results (1-500, default 25)",
    ):
        assert needle in search, needle
    props = large["search_files"].input_schema["properties"]
    assert (props["max_depth"]["maximum"], props["max_depth"]["default"]) == (20, 3)
    assert (props["max_results"]["maximum"], props["max_results"]["default"]) == (500, 25)
    old = default["search_files"].input_schema["properties"]
    assert (old["max_depth"]["maximum"], old["max_results"]["maximum"]) == (6, 100)
    assert props["path"] == {**old["path"]} and props["path"]["default"] == ""


async def test_restart_with_changed_configuration_shows_new_values(clean_env) -> None:
    descriptions = []
    for depth in ("8", "15"):
        base_env(clean_env, NEXTCLOUD_SEARCH_MAX_DEPTH=depth, NEXTCLOUD_MAX_FILE_BYTES=f"{depth}000000")
        _, _, tools = await discover(Settings.from_env())
        descriptions.append(tools)
    first, second = descriptions
    assert "Configured maximum depth: 8." in first["search_files"].description
    assert "Configured maximum depth: 15." in second["search_files"].description
    assert first["search_files"].input_schema["properties"]["max_depth"]["maximum"] == 8
    assert second["search_files"].input_schema["properties"]["max_depth"]["maximum"] == 15
    assert "Configured maximum file size: 15000000 bytes." in second["read_file"].description


async def test_mcp_rejects_values_above_the_schema_limits(make_settings) -> None:
    server = create_mcp(make_settings("dir:R"), transport=deep_tree(2).transport())
    async with Client(server) as client:
        too_deep = await client.call_tool("search_files", {"query": "hit", "max_depth": 7})
        too_many = await client.call_tool("search_files", {"query": "hit", "max_results": 101})
        scoped = await client.call_tool("search_files", {"query": "hit", "path": "R/L1"})
        denied = await client.call_tool("search_files", {"query": "hit", "path": "Other"})
    assert too_deep.is_error and too_many.is_error
    assert not scoped.is_error and scoped.structured_content["path"] == "R/L1"
    assert paths(scoped.structured_content) == ["R/L1/hit-1.md", "R/L1/L2/hit-2.md"]
    assert denied.is_error and denied.content[0].text.endswith(ACCESS_DENIED)


async def test_no_secret_in_descriptions_or_instructions(make_settings) -> None:
    _, instructions, tools = await discover(make_settings("dir:A"))
    texts = [instructions] + [t.description for t in tools.values()] + [str(t.input_schema) for t in tools.values()]
    for text in texts:
        assert SECRET not in text and "app_password" not in text.lower()
