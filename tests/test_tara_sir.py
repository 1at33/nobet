"""nobet-tara ile nobet.sir bağlantısı: katmanlar JSON'a girer, çıkış kodu süzülmüş sonuca bakar.

Sır benzeri değerler sentetiktir ve parçalı yazılır: tarama bu dosyayı yakalamasın.
"""

import json
import os
import subprocess
import sys

import pytest

from nobet import tara

HEX64 = "9f3c" * 16
BETIK = """\
import os, sys
yol = sys.argv[sys.argv.index("--report-path") + 1]
with open(yol, "w", encoding="utf-8") as f:
    f.write(os.environ["SAHTE_RAPOR"])
sys.exit(3)
"""


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    (r / "a.md").write_text("temiz\n", encoding="utf-8")
    return r


@pytest.fixture
def sahte(tmp_path, monkeypatch):
    """Raporu SAHTE_RAPOR ortam değişkeninden yazan ve 3 ile çıkan sahte gitleaks."""
    betik = tmp_path / "sahte.py"
    betik.write_text(BETIK, encoding="utf-8")
    if os.name == "nt":
        gl = tmp_path / "gl.cmd"
        gl.write_text(f'@"{sys.executable}" "{betik}" %*\r\n', encoding="utf-8")
    else:
        gl = tmp_path / "gl"
        gl.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{betik}" "$@"\n', encoding="utf-8")
    gl.chmod(0o755)
    monkeypatch.setenv("GITLEAKS", str(gl))

    def kur(kayitlar):
        monkeypatch.setenv("SAHTE_RAPOR", json.dumps(kayitlar))

    return kur


def kos(repo, capsys):
    kod = tara.main(["--repo", str(repo), "--json"])
    return kod, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_yalniz_suzulen_ozet_temiz_sayilir(repo, sahte, capsys):
    sahte([{"RuleID": "generic-api-key", "Secret": HEX64, "Match": f"cache_key_sha256 = {HEX64}", "File": "a.py"}])
    kod, son = kos(repo, capsys)
    assert kod == 0
    assert son["sir_taramasi"] == "temiz"
    assert son["sir_katmanlari"] == {"anahtar_turu": 0, "entropi": 0, "suzulen": 1}


def test_baglamsiz_onaltilik_bulgu_kalir(repo, sahte, capsys):
    ad = "SECRET" + "_KEY"
    sahte([{"RuleID": "generic-api-key", "Secret": HEX64, "Match": f"{ad} = {HEX64}", "File": "a.py"}])
    kod, son = kos(repo, capsys)
    assert kod == 1
    assert son["sir_taramasi"] == "bulgu"
    assert son["sir_katmanlari"] == {"anahtar_turu": 0, "entropi": 1, "suzulen": 0}
    assert HEX64 not in json.dumps(son)


def test_gitleaks_yokken_katman_yok(repo, monkeypatch, capsys):
    monkeypatch.setenv("GITLEAKS", "gitleaks-olmayan-arac")
    kod, son = kos(repo, capsys)
    assert kod == 0
    assert son["sir_taramasi"] == "yok" and son["sir_katmanlari"] is None
