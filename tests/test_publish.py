"""Tests for the shareable progress page (services/publish.py)."""
from __future__ import annotations

import pytest

from app import app_settings
from app.services import exports as exports_service
from app.services import publish
from app.services import weeks as weeks_service


@pytest.fixture
def isolated_settings(isolated_db, tmp_path, monkeypatch):
    """Redirect app_settings JSON into tmp so publish_dir never touches real settings."""
    monkeypatch.setattr(app_settings, "_SETTINGS_PATH", tmp_path / "app_settings.json")
    return tmp_path


def test_build_progress_html_has_data(isolated_settings):
    weeks_service.create_week("2026-W22")
    html = publish.build_progress_html()
    assert "2026-W22" in html
    assert "Canola" in html and "Corn" in html
    assert "updated" in html.lower()
    assert "<!DOCTYPE html>" in html
    assert 'http-equiv="refresh"' in html   # self-refreshing


def test_publish_progress_writes_file(isolated_settings, tmp_path):
    weeks_service.create_week("2026-W22")
    dest_dir = tmp_path / "drive"
    out = publish.publish_progress(dest_dir)
    assert out.name == "magpie-progress.html"
    assert out.parent == dest_dir
    assert "2026-W22" in out.read_text(encoding="utf-8")


def test_publish_requires_a_folder(isolated_settings):
    # No dir argument and none configured → clear error.
    assert publish.get_publish_dir() is None
    with pytest.raises(ValueError):
        publish.publish_progress()


def test_get_set_publish_dir(isolated_settings, tmp_path):
    publish.set_publish_dir(tmp_path / "drive")
    assert publish.get_publish_dir() == str(tmp_path / "drive")


def test_export_auto_publishes_when_dir_set(isolated_settings, tmp_path, monkeypatch):
    monkeypatch.setattr(exports_service, "EXPORTS_DIR", tmp_path / "exports")
    drive = tmp_path / "drive"
    publish.set_publish_dir(drive)
    weeks_service.create_week("2026-W22")

    res = exports_service.build_week_package("canola", "2026-W22")
    assert not res.errors
    assert (drive / "magpie-progress.html").exists()  # auto-published


def test_export_succeeds_without_publish_dir(isolated_settings, tmp_path, monkeypatch):
    monkeypatch.setattr(exports_service, "EXPORTS_DIR", tmp_path / "exports")
    weeks_service.create_week("2026-W22")
    # No publish dir set — export must still succeed, no crash.
    res = exports_service.build_week_package("canola", "2026-W22")
    assert not res.errors
    assert publish.get_publish_dir() is None
