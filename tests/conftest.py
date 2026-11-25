"""Pytest: testler geliştiricinin ayar.toml dosyasına ve şerit kayıtlarına bağlanmasın."""
import sys
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


@pytest.fixture(autouse=True)
def nobet_ayar_izole(monkeypatch, tmp_path):
    monkeypatch.delenv("NOBET_AYAR", raising=False)
    monkeypatch.delenv("NOBET_AKIS_DIZIN", raising=False)
    monkeypatch.delenv("NOBET_ORTAM_IZIN", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    if sys.platform == "win32":
        monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
