"""Çalışma ağacı kişisel veri denetimi. Değerler parçalı yazılır: tarama bu dosyayı yakalamasın."""

import json
import subprocess

import pytest

from nobet import tara

KISISEL = "kisi" + "@" + "posta-saglayici.com"
AD = "Zeynepgil"
EV_WIN = "C:" + "\\Users\\zeynep\\proje"
EV_UNIX = "/ho" + "me/zeynep/proje"
TC = "1000000" + "0146"  # sağlama haneleri geçerli, gerçek kişiye ait olmayan örnek


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    return r


def yaz(repo, ad, icerik):
    yol = repo / ad
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(icerik, encoding="utf-8")


def ekle(repo, *adlar):
    subprocess.run(["git", "-C", str(repo), "add", *adlar], check=True)


def turler(repo, adlar=()):
    return {(b.yer, b.tur) for b in tara.agac_tara(repo, adlar)[0]}


@pytest.fixture(autouse=True)
def gitleaks_yok(monkeypatch):
    monkeypatch.setenv("GITLEAKS", "gitleaks-olmayan-arac")


def test_tc_ornegi_gecerli():
    from nobet.gecmis import tc_gecerli
    assert tc_gecerli(TC)


def test_temiz_agac(repo):
    yaz(repo, "a.md", "merhaba\nornek@example.com\n/home/runner/work\n")
    ekle(repo, "a.md")
    assert tara.agac_tara(repo, [AD]) == ([], [])


def test_izlenen_izlenmeyen_ve_degisiklik_taranir(repo):
    yaz(repo, "izli.md", "temiz\n")
    ekle(repo, "izli.md")
    yaz(repo, "izli.md", f"yazan: {KISISEL}\n")  # commit'lenmemiş değişiklik
    yaz(repo, "yeni.txt", f"{AD} bey\n")          # izlenmeyen dosya
    assert turler(repo, [AD]) == {("dosya izli.md", "e-posta"), ("dosya yeni.txt", "ad")}


def test_gitignore_disarida_kalir(repo):
    yaz(repo, ".gitignore", "gizli/\n")
    yaz(repo, "gizli/not.md", KISISEL)
    assert turler(repo) == set()


def test_ev_yolu_ve_tc(repo):
    yaz(repo, "a.py", f'YOL = r"{EV_WIN}"\n')
    yaz(repo, "b.sh", f"cd {EV_UNIX}\n")
    yaz(repo, "c.txt", f"kimlik {TC}\n")
    yaz(repo, "d.md", "yer tutucu: C:" + "\\Users\\kullanici\\x ve /ho" + "me/user/x\n")
    assert turler(repo) == {("dosya a.py", "ev dizini yolu"), ("dosya b.sh", "ev dizini yolu"),
                            ("dosya c.txt", "TC kimlik no")}


def test_ev_yolu_kalibi():
    assert tara.ev_yolu_var("/Us" + "ers/ayse/kod")
    assert not tara.ev_yolu_var("/Users/example/kod")
    assert not tara.ev_yolu_var(r"[A-Za-z]:[\\/]Users|/home/|_BURASI")
    assert not tara.ev_yolu_var("/usr/home/")


def test_ikili_dosyada_tc_aranmaz_eposta_aranir(repo):
    (repo / "x.bin").write_bytes(b"\0\1" + TC.encode() + b" " + KISISEL.encode())
    assert turler(repo) == {("dosya x.bin", "e-posta")}


def test_cli_cikis_kodlari_ve_deger_yazmaz(repo, tmp_path, capsys):
    adlar = tmp_path / "adlar.txt"
    adlar.write_text(AD + "\n", encoding="utf-8")
    yaz(repo, "a.md", "temiz\n")
    assert tara.main(["--repo", str(repo), "--adlar", str(adlar)]) == 0
    yaz(repo, "b.md", f"{AD} {KISISEL}\n")
    assert tara.main(["--repo", str(repo), "--adlar", str(adlar), "--json"]) == 1
    cikti = capsys.readouterr().out
    assert AD not in cikti and KISISEL not in cikti
    son = json.loads(cikti.strip().splitlines()[-1])
    assert {b["tur"] for b in son["bulgular"]} == {"ad", "e-posta"}
    assert son["sir_taramasi"] == "yok"


def test_zorunlu_bayraklar(repo, tmp_path):
    yaz(repo, "a.md", "temiz\n")
    bos = tmp_path / "bos.txt"
    bos.write_text("", encoding="utf-8")
    assert tara.main(["--repo", str(repo), "--adlar", str(bos), "--adlar-zorunlu"]) == 2
    assert tara.main(["--repo", str(repo), "--adlar", str(tmp_path / "yok.txt")]) == 2
    assert tara.main(["--repo", str(repo), "--gitleaks-zorunlu"]) == 2


def test_gitleaks_bulgusu_temiz_sayilmaz(repo, tmp_path, monkeypatch):
    sahte = tmp_path / "gl"
    sahte.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    sahte.chmod(0o755)
    monkeypatch.setenv("GITLEAKS", str(sahte))
    yaz(repo, "a.md", "temiz\n")
    assert tara.gitleaks_tara(repo, False)[0] == "bulgu"
    assert tara.main(["--repo", str(repo)]) == 1


def test_ci_agaci_tariyor():
    from pathlib import Path
    ci = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "nobet.tara" in ci
