"""0.5.1: --check-nextcloud distinguishes rights on a share's mount point from rights on its content.

Live finding of 2026-11-06 (user-reported): released root ``SGDN``, contained file ``SG``. The
0.5.0 check reported a write warning only because of ``D``/``N`` on the mount point.

Semantics used (Nextcloud WebDAV documentation, "basic.html"):
* ``nc:is-mount-root``: "If so, then the node can only be unshared and not deleted." -> ``D`` on a
  mount root is documented as unshare.
* ``ocs:share-permissions``: "The permissions that the user has over the share" (1 read, 2 update,
  4 create, 8 delete, 16 share).
* ``N``/``V`` on a mount root are NOT documented -> must stay "nicht abschließend verifiziert".
"""

from __future__ import annotations

import json

import pytest
from conftest import FakeNextcloud

from levuvo_nextcloud_mcp import server as server_module
from levuvo_nextcloud_mcp import webdav as webdav_module
from levuvo_nextcloud_mcp.webdav import NextcloudWebDAV

OLD_KEYS = {"entry", "is_dir", "permissions", "writable_in_nextcloud"}


def share_props(*, root: bool | None, bits: int | None, mount_type: str | None = "shared") -> str:
    xml = ""
    if mount_type is not None:
        xml += f"<nc:mount-type>{mount_type}</nc:mount-type>"
    if root is not None:
        xml += f"<nc:is-mount-root>{'true' if root else 'false'}</nc:is-mount-root>"
    if bits is not None:
        xml += f"<ocs:share-permissions>{bits}</ocs:share-permissions>"
    return xml


def sgdn_share(child_permissions: str = "SG", child_bits: int = 1, root_bits: int = 1) -> FakeNextcloud:
    """Live situation: received read-only share ``SGDN`` with a file ``SG``."""
    fake = FakeNextcloud(files={"SGDN-Freigabe/test.txt": b"Hallo"})
    fake.permissions_by_path = {"SGDN-Freigabe": "SGDN", "SGDN-Freigabe/test.txt": child_permissions}
    fake.extra_props = {
        "SGDN-Freigabe": share_props(root=True, bits=root_bits),
        "SGDN-Freigabe/test.txt": share_props(root=False, bits=child_bits),
    }
    return fake


async def check(make_settings, fake: FakeNextcloud, *allowed: str, denied: tuple[str, ...] = ()) -> list[dict]:
    async with NextcloudWebDAV(make_settings(*allowed, denied=denied), transport=fake.transport()) as dav:
        return await dav.check_access()


# --------------------------------------------------------------------------- live case SGDN / SG
async def test_sgdn_share_root_with_sg_child_is_read_only_content_but_not_fully_verified(make_settings) -> None:
    fake = sgdn_share()
    [entry] = await check(make_settings, fake, "dir:SGDN-Freigabe")
    assert OLD_KEYS <= entry.keys()
    assert entry["permissions"] == "SGDN"
    assert entry["writable_in_nextcloud"] is True  # raw 0.5.0 field is kept unchanged
    assert entry["assessment"] == "read_only_content"
    assert entry["content_writable"] is False
    assert entry["mount_root"] is True and entry["mount_type"] == "shared" and entry["share_permissions"] == 1
    assert entry["children_checked"] == 1 and entry["children_with_write_permissions"] == []
    # N on a mount root is undocumented: the result must NOT be presented as verified.
    assert entry["verified"] is False
    assert any(point.startswith("N am Einhängepunkt") for point in entry["open_points"])
    assert any("unshare" in note for note in entry["notes"])
    assert all(method == "PROPFIND" for method, _ in fake.requests)
    assert all(b"share-permissions" in body and b"is-mount-root" in body for body in fake.propfind_bodies)


async def test_share_root_with_only_d_is_verified_read_only(make_settings) -> None:
    fake = sgdn_share()
    fake.permissions_by_path["SGDN-Freigabe"] = "SGD"
    [entry] = await check(make_settings, fake, "dir:SGDN-Freigabe")
    assert entry["assessment"] == "read_only_content"
    assert entry["content_writable"] is False and entry["verified"] is True and entry["open_points"] == []


# --------------------------------------------------------------------------- real write rights
async def test_child_with_write_rights_is_reported(make_settings) -> None:
    fake = sgdn_share(child_permissions="SGDNVW")
    [entry] = await check(make_settings, fake, "dir:SGDN-Freigabe")
    assert entry["assessment"] == "write_possible"
    assert entry["content_writable"] is True and entry["verified"] is True
    assert entry["children_with_write_permissions"] == ["SGDN-Freigabe/test.txt"]


async def test_child_with_write_share_bits_but_harmless_letters_is_reported(make_settings) -> None:
    fake = sgdn_share(child_bits=3)
    [entry] = await check(make_settings, fake, "dir:SGDN-Freigabe")
    assert entry["assessment"] == "write_possible"
    assert entry["children_with_write_permissions"] == ["SGDN-Freigabe/test.txt"]


@pytest.mark.parametrize("bits", [2, 4, 8, 31])
async def test_share_with_write_bits_is_reported_even_on_sgdn_root(make_settings, bits: int) -> None:
    fake = sgdn_share(root_bits=bits)
    [entry] = await check(make_settings, fake, "dir:SGDN-Freigabe")
    assert entry["assessment"] == "write_possible" and entry["content_writable"] is True


async def test_create_rights_on_root_are_reported(make_settings) -> None:
    fake = sgdn_share()
    fake.permissions_by_path["SGDN-Freigabe"] = "SGDNCK"
    [entry] = await check(make_settings, fake, "dir:SGDN-Freigabe")
    assert entry["assessment"] == "write_possible"
    assert any("CK" in note for note in entry["notes"])


async def test_d_on_entry_that_is_not_a_mount_root_is_reported(make_settings) -> None:
    fake = sgdn_share()
    fake.extra_props["SGDN-Freigabe"] = share_props(root=False, bits=1)
    [entry] = await check(make_settings, fake, "dir:SGDN-Freigabe")
    assert entry["assessment"] == "write_possible"


async def test_own_storage_with_full_rights_is_reported(make_settings, nextcloud) -> None:
    nextcloud.permissions = "RGDNVCK"
    nextcloud.extra_props = {p: share_props(root=False, bits=None, mount_type="") for p in nextcloud.folders}
    [entry] = await check(make_settings, nextcloud, "dir:05_Projekte/Offen")
    assert entry["assessment"] == "write_possible" and entry["verified"] is True
    assert any("eigenen Speicher" in note for note in entry["notes"])


# --------------------------------------------------------------------------- empty folder / file share
async def test_empty_share_folder(make_settings) -> None:
    fake = FakeNextcloud(folders={"Leer"})
    fake.permissions_by_path = {"Leer": "SGD"}
    fake.extra_props = {"Leer": share_props(root=True, bits=1)}
    [entry] = await check(make_settings, fake, "dir:Leer")
    assert entry["children_checked"] == 0 and entry["assessment"] == "read_only_content"
    assert any("leer" in note for note in entry["notes"])


async def test_direct_file_share(make_settings) -> None:
    fake = FakeNextcloud(files={"Vertrag.pdf": b"x"})
    fake.permissions_by_path = {"Vertrag.pdf": "SGDN"}
    fake.extra_props = {"Vertrag.pdf": share_props(root=True, bits=1)}
    [entry] = await check(make_settings, fake, "file:Vertrag.pdf")
    assert entry["is_dir"] is False and entry["children_checked"] == 0
    assert entry["assessment"] == "read_only_content" and entry["content_writable"] is False
    assert entry["verified"] is False  # N stays undocumented
    assert [method for method, _ in fake.requests] == ["PROPFIND"]


async def test_direct_file_share_with_write_right(make_settings) -> None:
    fake = FakeNextcloud(files={"Vertrag.pdf": b"x"})
    fake.permissions_by_path = {"Vertrag.pdf": "SGDNVW"}
    fake.extra_props = {"Vertrag.pdf": share_props(root=True, bits=3)}
    [entry] = await check(make_settings, fake, "file:Vertrag.pdf")
    assert entry["assessment"] == "write_possible"


# --------------------------------------------------------------------------- missing / incomplete data
async def test_missing_share_properties_are_unverified(make_settings) -> None:
    """Older server or proxy that only returns oc:permissions: never claim read-only."""
    fake = FakeNextcloud(files={"SGDN-Freigabe/test.txt": b"Hallo"})
    fake.permissions_by_path = {"SGDN-Freigabe": "SGDN"}
    [entry] = await check(make_settings, fake, "dir:SGDN-Freigabe")
    assert entry["assessment"] == "unverified"
    assert entry["content_writable"] is None and entry["verified"] is False
    assert any("is-mount-root" in point for point in entry["open_points"])
    assert any("share-permissions" in point for point in entry["open_points"])


async def test_missing_oc_permissions_are_unverified(make_settings) -> None:
    fake = FakeNextcloud(files={"Ordner/a.txt": b"a"})
    fake.permissions_by_path = {"Ordner": None, "Ordner/a.txt": None}
    [entry] = await check(make_settings, fake, "dir:Ordner")
    assert entry["permissions"] is None and entry["writable_in_nextcloud"] is False
    assert entry["assessment"] == "unverified" and entry["verified"] is False
    assert any("oc:permissions" in point for point in entry["open_points"])


async def test_subfolders_are_only_checked_one_level_deep(make_settings) -> None:
    fake = FakeNextcloud(files={"S/Unter/tief.txt": b"x"})
    fake.permissions_by_path = {"S": "SGD", "S/Unter": "SGD", "S/Unter/tief.txt": "SGDNVW"}
    fake.extra_props = {"S": share_props(root=True, bits=1), "S/Unter": share_props(root=False, bits=1)}
    [entry] = await check(make_settings, fake, "dir:S")
    # S/Unter has D but is not a mount root -> definite write finding on the immediate child.
    assert entry["assessment"] == "write_possible"
    assert entry["children_with_write_permissions"] == ["S/Unter"]
    assert any("tiefere Unterordner" in point for point in entry["open_points"])


async def test_truncated_listing_is_not_verified(make_settings, monkeypatch) -> None:
    monkeypatch.setattr(webdav_module, "MAX_DIRECTORY_ITEMS", 1)
    fake = FakeNextcloud(files={"S/a.txt": b"a", "S/b.txt": b"b", "S/c.txt": b"c"})
    fake.permissions_by_path = {"S": "SGD"}
    fake.extra_props = {"S": share_props(root=True, bits=1)}
    [entry] = await check(make_settings, fake, "dir:S")
    assert entry["children_truncated"] is True and entry["verified"] is False


async def test_denied_children_are_neither_requested_nor_listed(make_settings) -> None:
    fake = sgdn_share()
    fake.files["SGDN-Freigabe/Geheim/x.txt"] = b"x"
    fake.folders.add("SGDN-Freigabe/Geheim")
    fake.permissions_by_path["SGDN-Freigabe/Geheim"] = "SGDNVCK"
    [entry] = await check(make_settings, fake, "dir:SGDN-Freigabe", denied=("dir:SGDN-Freigabe/Geheim",))
    assert entry["children_with_write_permissions"] == []
    assert "SGDN-Freigabe/Geheim" not in fake.paths_requested()
    assert any("NEXTCLOUD_DENIED_PATHS" in note for note in entry["notes"])


# --------------------------------------------------------------------------- WebDAV errors
@pytest.mark.parametrize("status", [404, 500, 503])
async def test_webdav_errors_are_reported_per_entry(make_settings, status: int) -> None:
    fake = sgdn_share()
    fake.files["Andere/a.txt"] = b"a"
    fake.folders.add("Andere")
    fake.status_override = {"Andere": status}
    report = await check(make_settings, fake, "dir:SGDN-Freigabe", "dir:Andere")
    assert [e["entry"] for e in report] == ["dir:SGDN-Freigabe", "dir:Andere"]
    assert report[0]["assessment"] == "read_only_content"
    assert report[1]["assessment"] == "error" and report[1]["verified"] is False and report[1]["notes"]
    assert OLD_KEYS <= report[1].keys()


# --------------------------------------------------------------------------- CLI output (stderr wording, exit code)
def run_check(monkeypatch, capsys, make_settings, fake: FakeNextcloud, *allowed: str) -> tuple[int, list, str]:
    real = NextcloudWebDAV
    monkeypatch.setattr(server_module, "NextcloudWebDAV", lambda settings: real(settings, transport=fake.transport()))
    code = server_module.asyncio.run(server_module._check_nextcloud(make_settings(*allowed)))
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def test_cli_sgdn_shows_hint_not_warning(monkeypatch, capsys, make_settings) -> None:
    code, report, err = run_check(monkeypatch, capsys, make_settings, sgdn_share(), "dir:SGDN-Freigabe")
    assert code == 0
    assert "WARNUNG" not in err
    assert "HINWEIS" in err and "nicht abschließend verifiziert" in err and "manuelle Prüfung" in err
    assert report[0]["assessment"] == "read_only_content"


def test_cli_real_write_rights_show_warning(monkeypatch, capsys, make_settings) -> None:
    fake = sgdn_share(child_permissions="SGDNVW")
    code, _, err = run_check(monkeypatch, capsys, make_settings, fake, "dir:SGDN-Freigabe")
    assert code == 0 and "WARNUNG" in err and "dir:SGDN-Freigabe" in err


def test_cli_webdav_error_exits_with_1(monkeypatch, capsys, make_settings) -> None:
    fake = sgdn_share()
    fake.status_override = {"SGDN-Freigabe": 500}
    code, report, err = run_check(monkeypatch, capsys, make_settings, fake, "dir:SGDN-Freigabe")
    assert code == 1 and "Nextcloud-Prüfung fehlgeschlagen" in err
    assert report[0]["assessment"] == "error"
