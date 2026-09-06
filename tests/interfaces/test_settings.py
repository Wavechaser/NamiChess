import json

import pytest

from namichess.interfaces.orientation import Orientation
from namichess.interfaces.settings import (
    MAX_SETTINGS_BYTES,
    InterfaceSettings,
    SettingsError,
    SettingsStore,
)


def test_missing_settings_default_and_round_trip_preserves_unrelated_fields(tmp_path) -> None:
    path = tmp_path / "NamiChess" / "settings.json"
    store = SettingsStore(path)
    assert store.load().settings == InterfaceSettings()
    store.save_orientation(Orientation.TURN)
    assert store.load().settings == InterfaceSettings(Orientation.TURN)
    path.write_text('{"version":1,"orientation":"black","theme":"plain"}', encoding="utf-8")
    store.save_orientation(Orientation.WHITE)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "orientation": "white", "theme": "plain", "version": 1,
    }


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("{", "valid UTF-8 JSON"),
        ('[]', "JSON object"),
        ('{"version":2}', "version must be 1"),
        ('{"version":true}', "version must be 1"),
        ('{"version":1.0}', "version must be 1"),
        ('{"version":1,"orientation":"sideways"}', "orientation must be"),
    ],
)
def test_invalid_settings_fall_back_without_overwriting_and_refuse_save(tmp_path, contents, message) -> None:
    path = tmp_path / "settings.json"
    path.write_text(contents, encoding="utf-8")
    store = SettingsStore(path)
    loaded = store.load()
    assert loaded.settings == InterfaceSettings()
    assert message in (loaded.message or "")
    with pytest.raises(SettingsError, match=message):
        store.save_orientation(Orientation.BLACK)
    assert path.read_text(encoding="utf-8") == contents


def test_oversized_settings_are_not_decoded_or_replaced(tmp_path) -> None:
    path = tmp_path / "settings.json"
    contents = b" " * (MAX_SETTINGS_BYTES + 1)
    path.write_bytes(contents)
    store = SettingsStore(path)
    assert "size limit" in (store.load().message or "")
    with pytest.raises(SettingsError, match="size limit"):
        store.save_orientation(Orientation.BLACK)
    assert path.read_bytes() == contents


def test_invalid_utf8_settings_are_not_replaced(tmp_path) -> None:
    path = tmp_path / "settings.json"
    contents = b'{"version":1,"orientation":"white"}\xff'
    path.write_bytes(contents)
    store = SettingsStore(path)
    assert "valid UTF-8 JSON" in (store.load().message or "")
    with pytest.raises(SettingsError, match="valid UTF-8 JSON"):
        store.save_orientation(Orientation.BLACK)
    assert path.read_bytes() == contents


def test_deeply_nested_settings_are_not_replaced(tmp_path) -> None:
    path = tmp_path / "settings.json"
    contents = ("[" * 1_000 + "]" * 1_000).encode("utf-8")
    path.write_bytes(contents)
    store = SettingsStore(path)
    assert "JSON object" in (store.load().message or "")
    with pytest.raises(SettingsError, match="JSON object"):
        store.save_orientation(Orientation.BLACK)
    assert path.read_bytes() == contents


def test_save_refuses_to_expand_a_valid_settings_document_beyond_the_limit(tmp_path) -> None:
    path = tmp_path / "settings.json"
    prefix = '{"version":1,"padding":"'
    suffix = '"}'
    contents = (prefix + "x" * (MAX_SETTINGS_BYTES - len(prefix) - len(suffix)) + suffix).encode("utf-8")
    path.write_bytes(contents)
    with pytest.raises(SettingsError, match="size limit"):
        SettingsStore(path).save_orientation(Orientation.BLACK)
    assert path.read_bytes() == contents


def test_failed_atomic_replace_keeps_previous_settings(tmp_path, monkeypatch) -> None:
    path = tmp_path / "settings.json"
    contents = b'{"version":1,"orientation":"white"}\n'
    path.write_bytes(contents)

    def fail_replace(source, destination):
        raise OSError("fixture replacement failure")

    monkeypatch.setattr("namichess.interfaces.settings.os.replace", fail_replace)
    with pytest.raises(SettingsError, match="could not save settings"):
        SettingsStore(path).save_orientation(Orientation.BLACK)
    assert path.read_bytes() == contents
    assert list(tmp_path.glob(".settings.json.*.tmp")) == []
