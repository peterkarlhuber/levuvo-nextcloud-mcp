"""AP1: central access policy - normalisation, allow/deny semantics, startup validation."""

from __future__ import annotations

import unicodedata

import pytest

from levuvo_nextcloud_mcp.errors import AccessDeniedError, ConfigurationError, InvalidArgumentError
from levuvo_nextcloud_mcp.policy import (
    ACCESS_DENIED_MESSAGE,
    MAX_PATH_LENGTH,
    AccessPolicy,
    fold_key,
    normalize_path,
    parse_rule,
    parse_rules,
)


def policy(allowed: str, denied: str = "") -> AccessPolicy:
    return AccessPolicy(parse_rules(allowed, "NEXTCLOUD_ALLOWED_PATHS"), parse_rules(denied, "NEXTCLOUD_DENIED_PATHS"))


# --------------------------------------------------------------------------- normalisation
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("a", "a"),
        ("a/b/c.txt", "a/b/c.txt"),
        ("a/b/", "a/b"),
        ("Leerzeichen im Namen.md", "Leerzeichen im Namen.md"),
        ("#Raute?/und&Co+.txt", "#Raute?/und&Co+.txt"),
        ("100% sicher.txt", "100% sicher.txt"),  # a lone % is a normal character
        ("...", "..."),
        (unicodedata.normalize("NFD", "Geschäftsführung"), "Geschäftsführung"),
    ],
)
def test_normalize_accepts_and_canonicalises(raw: str, expected: str) -> None:
    assert normalize_path(raw) == expected
    assert unicodedata.is_normalized("NFC", normalize_path(raw))


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "/abs",
        "\\abs",
        "a\\b",
        "../x",
        "a/../b",
        "a/./b",
        "a//b",
        "a/b//",
        ".",
        "..",
        "a/\n",
        "a\x00b",
        "a\x7fb",
        "a‮b",  # bidi override
        "a​b",  # zero width space
        "a%2Fb",
        "a%2fb",
        "%2e%2e/x",
        "a%20b",
        "a%252Fb",
        "x" * (MAX_PATH_LENGTH + 1),
        "a/" + "y" * 256,
    ],
)
def test_normalize_rejects_dangerous_paths(bad: str) -> None:
    with pytest.raises(InvalidArgumentError):
        normalize_path(bad)


@pytest.mark.parametrize("bad", [None, 1, b"a", ["a"]])
def test_normalize_rejects_non_strings(bad: object) -> None:
    with pytest.raises(InvalidArgumentError):
        normalize_path(bad)


def test_normalize_empty_allowed_only_on_request() -> None:
    assert normalize_path("", allow_empty=True) == ""


def test_fold_key_is_conservative() -> None:
    assert fold_key("A/Intern") == fold_key("a/INTERN") == fold_key("A/Intern ") == fold_key("A/Intern.")
    assert fold_key(unicodedata.normalize("NFD", "Ä/ß")) == fold_key("ä/SS")
    assert fold_key("Ｉｎｔｅｒｎ") == fold_key("intern")  # fullwidth compatibility characters


# --------------------------------------------------------------------------- rule parsing
@pytest.mark.parametrize("setting", ["NEXTCLOUD_ALLOWED_PATHS", "NEXTCLOUD_DENIED_PATHS"])
@pytest.mark.parametrize(
    "raw, kind, path",
    [("dir:A/B", "dir", "A/B"), ("file:A/b.md", "file", "A/b.md"), ("A/B", "auto", "A/B"), (" dir:A ", "dir", "A")],
)
def test_identical_prefix_syntax_for_both_settings(setting: str, raw: str, kind: str, path: str) -> None:
    rule = parse_rule(raw, setting)
    assert (rule.kind, rule.path) == (kind, path)


@pytest.mark.parametrize("setting", ["NEXTCLOUD_ALLOWED_PATHS", "NEXTCLOUD_DENIED_PATHS"])
@pytest.mark.parametrize(
    "raw",
    ["DIR:A", "File:A", "folder:A", "files:A", "dir:file:A", "file:dir:A", "dir:", "file: A", "dir:/A", "dir:A/../B"],
)
def test_invalid_or_unknown_prefixes_fail_loudly(setting: str, raw: str) -> None:
    with pytest.raises(ConfigurationError) as info:
        parse_rule(raw, setting)
    assert setting in str(info.value)


def test_parse_rules_ignores_empty_items_only() -> None:
    assert [r.path for r in parse_rules("dir:A, ,file:B.md,", "X")] == ["A", "B.md"]


# --------------------------------------------------------------------------- allow semantics
def test_allow_is_exact_and_case_sensitive() -> None:
    p = policy("dir:05_Projekte,file:06_Marketing/CI.md")
    assert p.check("05_Projekte/Offen/Plan.md") == "05_Projekte/Offen/Plan.md"
    assert p.check("06_Marketing/CI.md") == "06_Marketing/CI.md"
    for path in (
        "05_projekte/Offen",
        "05_ProjekteX/a",
        "06_Marketing",
        "06_Marketing/CI.md/x",
        "06_Marketing/ci.md",
        "x",
    ):
        with pytest.raises(AccessDeniedError):
            p.check(path)


def test_allow_nfc_and_nfd_spellings_refer_to_same_released_path() -> None:
    p = policy("dir:Geschäftsführung")
    assert p.check(unicodedata.normalize("NFD", "Geschäftsführung/x.md")) == "Geschäftsführung/x.md"


def test_nfd_config_entry_is_normalised() -> None:
    p = policy("dir:" + unicodedata.normalize("NFD", "Ablage/Übersicht"))
    assert p.check("Ablage/Übersicht/a.txt") == "Ablage/Übersicht/a.txt"


# --------------------------------------------------------------------------- deny semantics
@pytest.mark.parametrize("deny", ["05_Projekte/Intern", "dir:05_Projekte/Intern", "file:05_Projekte/Intern"])
@pytest.mark.parametrize(
    "probe",
    [
        "05_Projekte/Intern",
        "05_Projekte/Intern/geheim.md",
        "05_Projekte/intern/geheim.md",
        "05_Projekte/INTERN/x/y/z.txt",
        "05_Projekte/Intern./geheim.md",
        "05_Projekte/Intern /geheim.md",
        "05_Projekte/Ｉｎｔｅｒｎ/geheim.md",
    ],
)
def test_deny_blocks_all_spellings_and_subtree_regardless_of_prefix(deny: str, probe: str) -> None:
    p = policy("dir:05_Projekte", deny)
    with pytest.raises(AccessDeniedError) as info:
        p.check(probe)
    assert str(info.value) == ACCESS_DENIED_MESSAGE


def test_deny_with_umlaut_blocks_nfd_variant() -> None:
    p = policy("dir:05_Projekte", "05_Projekte/Geschäftsführung")
    for form in ("NFC", "NFD", "NFKD"):
        with pytest.raises(AccessDeniedError):
            p.check(unicodedata.normalize(form, "05_Projekte/Geschäftsführung/Gehälter.txt"))
    with pytest.raises(AccessDeniedError):
        p.check("05_Projekte/GESCHÄFTSFÜHRUNG/Gehälter.txt")


def test_deny_does_not_block_siblings_with_common_prefix() -> None:
    p = policy("dir:05_Projekte", "dir:05_Projekte/Intern")
    assert p.check("05_Projekte/Internes_Wiki.md") == "05_Projekte/Internes_Wiki.md"
    assert p.check("05_Projekte/Intern2/a.md") == "05_Projekte/Intern2/a.md"


def test_deny_of_single_file_inside_allowed_folder() -> None:
    p = policy("dir:06_Marketing", "file:06_Marketing/Intern.md")
    assert p.check("06_Marketing/CI.md") == "06_Marketing/CI.md"
    with pytest.raises(AccessDeniedError):
        p.check("06_Marketing/intern.md")


def test_denied_and_unreleased_paths_share_one_message() -> None:
    p = policy("dir:A", "A/B")
    with pytest.raises(AccessDeniedError) as denied:
        p.check("A/B/c")
    with pytest.raises(AccessDeniedError) as unreleased:
        p.check("Z/c")
    assert str(denied.value) == str(unreleased.value)


# --------------------------------------------------------------------------- startup validation
@pytest.mark.parametrize(
    "allowed, denied, message",
    [
        ("", "", "is empty"),
        ("dir:A,file:A", "", "the same path"),
        ("dir:A,dir:a", "", "the same path"),
        ("dir:Ä," + unicodedata.normalize("NFD", "dir:Ä"), "", "the same path"),
        ("dir:A", "A/x,dir:A/X", "the same path"),
        ("dir:A", "B/x", "does not lie below any share"),
        ("dir:A", "Ab/x", "does not lie below any share"),
        ("file:A/b.md", "A/b.md/c", "does not lie below any share"),
        ("dir:A,file:A/b.md", "A", "completely blocked"),
        ("dir:A/B", "a", "completely blocked"),
        ("file:A/b.md,file:A/b.md/c", "", "single file"),
    ],
)
def test_contradictory_or_ineffective_configuration_is_rejected(allowed: str, denied: str, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        policy(allowed, denied)


def test_nested_allows_and_effective_denies_are_valid() -> None:
    p = policy("dir:A,dir:A/C,file:A/C/d.md,dir:Z", "A/B,file:Z/x.md")
    with pytest.raises(AccessDeniedError):
        p.check("A/B/c.md")
    with pytest.raises(AccessDeniedError):
        p.check("Z/x.md")
    assert p.check("A/x.md") == "A/x.md"
    assert p.check("A/C/d.md") == "A/C/d.md"


def test_matching_allows_never_returns_rules_for_denied_or_empty_paths() -> None:
    p = policy("dir:A", "A/B")
    assert p.matching_allows("") == ()
    assert p.matching_allows("A/B/c") == ()
    assert [r.path for r in p.matching_allows("A/c")] == ["A"]
