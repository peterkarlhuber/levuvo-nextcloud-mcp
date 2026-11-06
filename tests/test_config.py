"""AP5: configuration loading, .env handling and fail-closed startup validation."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import pytest

from levuvo_nextcloud_mcp import settings as settings_module
from levuvo_nextcloud_mcp.errors import ConfigurationError
from levuvo_nextcloud_mcp.settings import ENV_FILE_VARIABLE, Settings, load_env_file, warn_if_permissive

SRC = Path(__file__).resolve().parents[1] / "src" / "levuvo_nextcloud_mcp"


def base_env(monkeypatch: pytest.MonkeyPatch, **extra: str) -> None:
    values = {
        "NEXTCLOUD_URL": "https://storage.levuvo.com/",
        "NEXTCLOUD_USERNAME": "agent.levuvo",
        "NEXTCLOUD_APP_PASSWORD": "DUMMY_TEST_SECRET",
        "NEXTCLOUD_ALLOWED_PATHS": "dir:01_Unternehmen, file:06_Marketing/CI.pdf",
    }
    values.update(extra)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_from_env_reads_both_permission_settings(clean_env: pytest.MonkeyPatch) -> None:
    base_env(clean_env, NEXTCLOUD_DENIED_PATHS="dir:01_Unternehmen/Privat,")
    s = Settings.from_env()
    assert s.base_url == "https://storage.levuvo.com"
    assert [(r.kind, r.path) for r in s.policy.allowed] == [("dir", "01_Unternehmen"), ("file", "06_Marketing/CI.pdf")]
    assert [(r.kind, r.path) for r in s.policy.denied] == [("dir", "01_Unternehmen/Privat")]
    assert s.dav_user == "agent.levuvo"


def test_user_id_overrides_webdav_user(clean_env: pytest.MonkeyPatch) -> None:
    base_env(clean_env, NEXTCLOUD_USERNAME="agent@levuvo.com", NEXTCLOUD_USER_ID="agent.levuvo")
    s = Settings.from_env()
    assert (s.username, s.dav_user) == ("agent@levuvo.com", "agent.levuvo")


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"NEXTCLOUD_ALLOWED_PATHS": ""}, "NEXTCLOUD_ALLOWED_PATHS is empty"),
        ({"NEXTCLOUD_ALLOWED_PATHS": " , "}, "NEXTCLOUD_ALLOWED_PATHS is empty"),
        ({"NEXTCLOUD_APP_PASSWORD": ""}, "NEXTCLOUD_APP_PASSWORD"),
        ({"NEXTCLOUD_APP_PASSWORD": "EIGENES_NEXTCLOUD_APP_PASSWORT"}, "placeholder"),
        ({"NEXTCLOUD_USERNAME": ""}, "NEXTCLOUD_USERNAME"),
        ({"NEXTCLOUD_USER_ID": "a/b"}, "NEXTCLOUD_USER_ID"),
        ({"NEXTCLOUD_URL": "http://storage.levuvo.com"}, "HTTPS"),
        ({"NEXTCLOUD_URL": "https://user:pw@storage.levuvo.com"}, "HTTPS"),
        ({"NEXTCLOUD_URL": "https://storage.levuvo.com/nextcloud"}, "must not contain a path"),
        ({"NEXTCLOUD_URL": ""}, "NEXTCLOUD_URL"),
        ({"NEXTCLOUD_MAX_FILE_BYTES": "lots"}, "must be a number"),
        ({"NEXTCLOUD_MAX_FILE_BYTES": "0"}, "between"),
        ({"NEXTCLOUD_MAX_FILE_BYTES": "40000000"}, "between"),
        ({"NEXTCLOUD_TIMEOUT_SECONDS": "500"}, "between"),
        ({"NEXTCLOUD_DENIED_PATHS": "DIR:01_Unternehmen/Privat"}, "unknown prefix"),
        ({"NEXTCLOUD_DENIED_PATHS": "02_Finanzen"}, "does not lie below any share"),
        ({"NEXTCLOUD_ALLOWED_PATHS": "dir:/01_Unternehmen"}, "invalid path"),
    ],
)
def test_invalid_configuration_fails_closed(clean_env: pytest.MonkeyPatch, overrides: dict, message: str) -> None:
    base_env(clean_env, **overrides)
    with pytest.raises(ConfigurationError, match=re.escape(message)):
        Settings.from_env()


def test_removed_legacy_variable_is_not_read(clean_env: pytest.MonkeyPatch) -> None:
    base_env(clean_env, NEXTCLOUD_ALLOWED_PATHS="")
    clean_env.setenv("NEXTCLOUD_ALLOWED_" + "ROOTS", "dir:01_Unternehmen")
    with pytest.raises(ConfigurationError, match="NEXTCLOUD_ALLOWED_PATHS is empty"):
        Settings.from_env()
    for source in SRC.glob("*.py"):
        assert "ALLOWED_" + "ROOTS" not in source.read_text(encoding="utf-8"), source


def test_repr_never_contains_password(make_settings) -> None:
    s = make_settings("dir:A")
    assert "DUMMY_TEST_SECRET" not in repr(s)


def test_explicit_env_file_is_loaded_without_overriding_environment(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "levuvo.env"
    env_file.write_text(
        "NEXTCLOUD_URL=https://storage.levuvo.com\nNEXTCLOUD_USERNAME=from-file\n"
        "NEXTCLOUD_APP_PASSWORD=file-secret\nNEXTCLOUD_ALLOWED_PATHS=dir:A\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    clean_env.setenv(ENV_FILE_VARIABLE, str(env_file))
    clean_env.setenv("NEXTCLOUD_USERNAME", "from-env")
    assert load_env_file() == env_file
    s = Settings.from_env()
    assert s.username == "from-env"
    assert [r.path for r in s.policy.allowed] == ["A"]


def test_missing_explicit_env_file_is_an_error(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clean_env.setenv(ENV_FILE_VARIABLE, str(tmp_path / "fehlt.env"))
    with pytest.raises(ConfigurationError, match=ENV_FILE_VARIABLE):
        load_env_file()


def test_no_env_file_outside_source_checkout(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_module = tmp_path / "site-packages" / "levuvo_nextcloud_mcp" / "settings.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("", encoding="utf-8")
    (tmp_path / ".env").write_text("NEXTCLOUD_USERNAME=should-not-load\n", encoding="utf-8")
    clean_env.setattr(settings_module, "__file__", str(fake_module))
    assert load_env_file() is None
    assert "NEXTCLOUD_USERNAME" not in os.environ


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_permissive_env_file_triggers_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("X=1\n", encoding="utf-8")
    env_file.chmod(0o644)
    with caplog.at_level(logging.WARNING):
        assert warn_if_permissive(env_file) is True
    assert "chmod 600" in caplog.text
    env_file.chmod(0o600)
    assert warn_if_permissive(env_file) is False
