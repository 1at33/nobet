"""nobet-akis: şerit aç -> yaz -> denetle -> incele -> kaydet -> kapat, sahte yazıcı/reviewer CLI ile.

Gerçek git depoları tmp_path altında kurulur; model çağrısı yok.
"""
import http.server
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from nobet import akis

SAHTE = r'''
import argparse, json, os, pathlib, sys, time
a = argparse.ArgumentParser()
for ad in ("--rol", "--model", "--istem", "--cikti"):
    a.add_argument(ad)
a = a.parse_args()
istem = pathlib.Path(a.istem).read_text(encoding="utf-8") if a.istem else sys.stdin.read()
mod = os.environ.get("SAHTE_MOD", "iyi")
wt = pathlib.Path.cwd()
if os.environ.get("SAHTE_IZ"):
    with open(os.environ["SAHTE_IZ"], "a", encoding="utf-8") as f:
        f.write(f"{a.rol} {a.model} {'stdin' if not a.istem else 'dosya'}\n")
if os.environ.get("SAHTE_ISTEM"):
    pathlib.Path(os.environ["SAHTE_ISTEM"]).write_text(istem, encoding="utf-8")
if a.rol == "yazici":
    (wt / "src" / "a.py").write_text("yeni\n")
    if mod == "sahiplik-disi":
        (wt / "kok.txt").write_text("degisti\n")
    if mod == "test-degistir":
        (wt / "tests" / "test_a.py").write_text("bozuldu\n")
    if mod == "ortam":
        pathlib.Path(os.environ["SAHTE_ORTAM_DOSYASI"]).write_text(json.dumps(dict(os.environ)))
        print("token: " + os.environ.get("GITHUB_TOKEN", "yok"))
    if mod == "serit-boz":
        (pathlib.Path(os.environ["SAHTE_SERIT"]) / "sahiplik").write_text("**\n")
        (pathlib.Path(os.environ["SAHTE_SERIT"]) / "bitti-bag").write_text("sahte\n")
    if mod == "git-config":
        import subprocess
        subprocess.run(["git", "config", "core.hooksPath", "planli-hooklar"], check=True)
    if mod == "uyku":
        time.sleep(60)
    cevap = ("madde 1: KARŞILANDI | kanıt: `test -f src/a.py` → çıkış 0\n"
             "bitti: KARŞILANDI | kanıt: `nobet-akis denetle` → çıkış 0\n")
else:
    if mod == "reviewer-boz":
        (wt / "src" / "a.py").write_text("reviewer yazdi\n")
    cevap = f"inceleyen {a.model}\nmadde 1: KARŞILANDI | kanıt: `test -f src/a.py` → çıkış 0\nBULGU YOK\n"
print("sahte günlük satırı")
if a.cikti:
    pathlib.Path(a.cikti).write_text(cevap, encoding="utf-8")
else:
    print(cevap)
'''

SOZLESME = """# Sözleşme
## Maddeler
1. a.py var: `test -f src/a.py` → çıkış 0

```bitti
grep -q yeni src/a.py
```
"""


def git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def ortam(tmp_path, monkeypatch):
    """Repo (src/a.py, tests/test_a.py, kok.txt), şerit kökü, sahte CLI ve iki sağlayıcılı ayar."""
    for ad, deger in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@example.com"),
                      ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@example.com"),
                      ("GIT_CONFIG_GLOBAL", os.devnull), ("GIT_CONFIG_NOSYSTEM", "1")):
        monkeypatch.setenv(ad, deger)
    monkeypatch.setenv("NOBET_AKIS_DIZIN", str(tmp_path / "akis"))
    monkeypatch.delenv("SAHTE_MOD", raising=False)
    repo = tmp_path / "proje"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "core.autocrlf", "false")
    (repo / "src" / "a.py").write_text("eski\n")
    (repo / "tests" / "test_a.py").write_text("t\n")
    (repo / "kok.txt").write_text("k\n")
    (repo / ".gitignore").write_text("dis-bag\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "ilk")
    sahte = tmp_path / "sahte.py"
    sahte.write_text(SAHTE, encoding="utf-8")
    py = shlex.quote(sys.executable) + " " + shlex.quote(str(sahte))
    ayar = tmp_path / "ayar.toml"
    ayar.write_text(
        "[[saglayici]]\nad = \"birinci\"\ntur = \"cli\"\n"
        f"komut = {json.dumps(py + ' --rol {rol} --model {model} --istem {istem} --cikti {cikti}')}\n"
        "modeller = [\"b-yazar\", \"b-inceler\"]\n\n"
        "[[saglayici]]\nad = \"ikinci\"\ntur = \"cli\"\n"
        f"komut = {json.dumps(py + ' --rol {rol} --model {model}')}\n"
        "modeller = [\"i-inceler\"]\nroller = [\"reviewer\"]\n",
        encoding="utf-8")
    monkeypatch.setenv("NOBET_AYAR", str(ayar))
    soz = tmp_path / "sozlesme.md"
    soz.write_text(SOZLESME, encoding="utf-8")
    brief = tmp_path / "brief.md"
    brief.write_text("src/a.py içeriğini 'yeni' yap.\n", encoding="utf-8")
    kabul_k = tmp_path / "kabul_kaynak.py"
    kabul_k.write_text("def test_kabul():\n    pass\n", encoding="utf-8")
    return tmp_path, repo, soz, brief, kabul_k


def ac(ortam_, ad="s1", *ek):
    _, repo, soz, _, kabul_k = ortam_
    return akis.main(["ac", str(repo), ad, "--sahiplik", "src/**", "--sozlesme", str(soz),
                      "--kabul", f"{kabul_k}=tests/test_kabul.py", *ek])


def serit(ortam_, ad="s1"):
    d = ortam_[0] / "akis" / "isler" / ad
    return d, Path((d / "worktree").read_text(encoding="utf-8").strip())


# --- mutlu yol ------------------------------------------------------------------------------

def test_mutlu_yol(ortam, capsys):
    _, repo, _, brief, _ = ortam
    assert ac(ortam) == 0
    d, wt = serit(ortam)
    assert (wt / "tests" / "test_kabul.py").is_file()
    assert "tests/test_kabul.py" in (d / "kabul").read_text()
    assert (d / "taban").read_text().strip() == git(repo, "rev-parse", "HEAD")
    assert akis.main(["yaz", "s1", "b-yazar", str(brief)]) == 0
    assert akis.main(["denetle", "s1"]) == 0, capsys.readouterr().out
    assert (d / "rapor-1.md").is_file()
    assert "cikis: 0" in (d / "bitti.log").read_text()
    assert akis.main(["incele", "s1"]) == 0, capsys.readouterr().out
    assert akis.main(["kaydet", "s1", "-m", "a.py yenilendi"]) == 0
    assert akis.main(["kapat", "s1"]) == 0, capsys.readouterr().out
    assert not wt.exists()
    assert (d / "durum-isaret").read_text().strip() == "teslim"
    assert git(repo, "show", "nobet/s1:src/a.py") == "yeni"
    assert git(repo, "show", "nobet/s1:tests/test_kabul.py").startswith("def test_kabul")
    # Ana çalışma ağacı değişmedi.
    assert (repo / "src" / "a.py").read_text() == "eski\n"


def test_bitti_komutu_yoksa_serit_acilmaz(ortam, capsys):
    tmp, repo, *_ = ortam
    assert akis.main(["ac", str(repo), "s2", "--sahiplik", "src/**"]) == 2
    assert not (tmp / "akis" / "isler" / "s2").exists()
    assert subprocess.run(["git", "-C", str(repo), "show-ref", "--verify", "--quiet", "refs/heads/nobet/s2"],
                          check=False).returncode != 0


def test_bozuk_sozlesme_serit_acmaz(ortam, capsys):
    tmp, repo, *_ = ortam
    bozuk = tmp / "bozuk.md"
    bozuk.write_text("## Maddeler\n1. a\n1. b\n\n```bitti\ntrue\n```\n", encoding="utf-8")
    assert akis.main(["ac", str(repo), "s3", "--sahiplik", "src/**", "--sozlesme", str(bozuk)]) == 2
    assert "iki kez" in capsys.readouterr().out
    assert not (tmp / "akis" / "isler" / "s3").exists()
    assert "nobet" not in git(repo, "branch", "--list")


def test_kabul_tabandaki_dosya_olamaz_geri_alinir(ortam, capsys):
    tmp, repo, soz, _, kabul_k = ortam
    assert akis.main(["ac", str(repo), "s4", "--sahiplik", "src/**", "--sozlesme", str(soz),
                      "--kabul", f"{kabul_k}=tests/test_a.py"]) == 2
    assert not (tmp / "akis" / "isler" / "s4").exists()
    assert "nobet" not in git(repo, "branch", "--list")
    assert len(git(repo, "worktree", "list").splitlines()) == 1


# --- kapı reddi -----------------------------------------------------------------------------

def test_sahiplik_disi_dosya_reddedilir(ortam, monkeypatch, capsys):
    assert ac(ortam) == 0
    monkeypatch.setenv("SAHTE_MOD", "sahiplik-disi")
    assert akis.main(["yaz", "s1", "b-yazar", str(ortam[3])]) == 0
    assert akis.main(["denetle", "s1"]) == 1
    d, _ = serit(ortam)
    log = (d / "bitti.log").read_text()
    assert "kapi_ihlal: kok.txt (sahiplik dışı (M))" in log
    assert "cikis: 1" in log
    assert not (d / "rapor-1.md").exists()  # KARŞILANDI iddiası kırmızı kanıtla çelişir
    assert akis.main(["kaydet", "s1", "-m", "x"]) == 1


def test_mevcut_test_degisirse_reddedilir(ortam, monkeypatch, capsys):
    assert ac(ortam, "s1", "--sahiplik", "tests/**") == 0
    monkeypatch.setenv("SAHTE_MOD", "test-degistir")
    assert akis.main(["yaz", "s1", "b-yazar", str(ortam[3])]) == 0
    assert akis.main(["denetle", "s1"]) == 1
    d, _ = serit(ortam)
    assert "kapi_ihlal: tests/test_a.py (mevcut test değişti)" in (d / "bitti.log").read_text()


def test_yazici_serit_kaydini_bozarsa_geri_yuklenir(ortam, monkeypatch, capsys):
    assert ac(ortam) == 0
    d, _ = serit(ortam)
    monkeypatch.setenv("SAHTE_MOD", "serit-boz")
    monkeypatch.setenv("SAHTE_SERIT", str(d))
    assert akis.main(["yaz", "s1", "b-yazar", str(ortam[3])]) == 1
    assert (d / "sahiplik").read_text() == "src/**\n"
    assert not (d / "bitti-bag").exists()
    assert "sahiplik değişti" in (d / akis.KORUMA).read_text()
    assert akis.main(["denetle", "s1"]) == 1
    assert "koruma_ihlal:" in (d / "bitti.log").read_text()


def test_yazici_git_config_degistirirse_geri_yazilir(ortam, monkeypatch, capsys):
    """.git/config'e yazılan ayar (ör. hooksPath, fsmonitor) sonraki git çağrısında kod çalıştırabilir."""
    _, repo, *_ = ortam
    assert ac(ortam) == 0
    once = (repo / ".git" / "config").read_bytes()
    monkeypatch.setenv("SAHTE_MOD", "git-config")
    assert akis.main(["yaz", "s1", "b-yazar", str(ortam[3])]) == 1
    assert (repo / ".git" / "config").read_bytes() == once
    d, _ = serit(ortam)
    assert "config değişti" in (d / akis.KORUMA).read_text()
    assert akis.main(["kaydet", "s1", "-m", "x"]) == 1


# --- reviewer -------------------------------------------------------------------------------

def test_reviewer_baska_saglayicidan_secilir(ortam, monkeypatch, capsys):
    iz = ortam[0] / "iz.txt"
    monkeypatch.setenv("SAHTE_IZ", str(iz))
    assert ac(ortam) == 0
    assert akis.main(["yaz", "s1", "b-yazar", str(ortam[3])]) == 0
    assert akis.main(["incele", "s1"]) == 0, capsys.readouterr().out
    d, _ = serit(ortam)
    meta = json.loads((d / "review-1.meta").read_text())
    assert meta["reviewer"] == "i-inceler"
    assert (meta["yazici_saglayici"], meta["reviewer_saglayici"], meta["ayni_saglayici"]) == ("birinci", "ikinci", False)
    # İkinci sağlayıcının şablonunda {istem} yok: istem stdin'den gitti ve farkı taşıyor.
    assert iz.read_text().splitlines() == ["yazici b-yazar dosya", "reviewer i-inceler stdin"]
    assert "inceleyen i-inceler" in (d / "review-1.md").read_text()
    assert "rapor: geçerli" in (d / "review-1.sema").read_text()
    # Açıkça aynı sağlayıcı seçilirse bilgi verilir ve ölçüm alanına yazılır.
    assert akis.main(["incele", "s1", "--profil", "b-inceler"]) == 0
    assert "aynı sağlayıcıda" in capsys.readouterr().out
    assert json.loads((d / "review-2.meta").read_text())["ayni_saglayici"] is True
    assert akis.main(["incele", "s1", "--profil", "b-yazar"]) == 2


def test_review_istemi_farki_tasir(ortam, monkeypatch, capsys):
    istem = ortam[0] / "istem.txt"
    assert ac(ortam) == 0
    assert akis.main(["yaz", "s1", "b-yazar", str(ortam[3])]) == 0
    monkeypatch.setenv("SAHTE_ISTEM", str(istem))
    assert akis.main(["incele", "s1"]) == 0
    metin = istem.read_text(encoding="utf-8")
    assert "DOSYA DEĞİŞTİRME" in metin and "+yeni" in metin and "tests/test_kabul.py" in metin


def test_reviewer_agaci_degistirirse_sayilmaz(ortam, monkeypatch, capsys):
    assert ac(ortam) == 0
    assert akis.main(["yaz", "s1", "b-yazar", str(ortam[3])]) == 0
    monkeypatch.setenv("SAHTE_MOD", "reviewer-boz")
    assert akis.main(["incele", "s1"]) == 1
    d, wt = serit(ortam)
    assert json.loads((d / "review-1.meta").read_text())["agac_degisti"] is True
    assert not (d / "review-1.sema").exists()
    assert (wt / "src" / "a.py").read_text() == "reviewer yazdi\n"  # geri alınmaz, yalnız bildirilir


def test_api_reviewer(ortam, monkeypatch, capsys):
    gelen = {}

    class Isleyici(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            gelen["yol"] = self.path
            gelen["yetki"] = self.headers.get("Authorization")
            gelen["govde"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            cevap = json.dumps({"choices": [{"message": {"content":
                    "madde 1: KARŞILANDI | kanıt: `test -f src/a.py` → çıkış 0\nBULGU YOK\n"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(cevap)))
            self.end_headers()
            self.wfile.write(cevap)

        def log_message(self, *a):
            pass

    sunucu = http.server.HTTPServer(("127.0.0.1", 0), Isleyici)
    threading.Thread(target=sunucu.serve_forever, daemon=True).start()
    try:
        ayar = Path(os.environ["NOBET_AYAR"])
        ayar.write_text(ayar.read_text(encoding="utf-8") +
                        f'\n[[saglayici]]\nad = "uzak"\ntur = "api"\ntaban_url = "http://127.0.0.1:{sunucu.server_port}/v1"\n'
                        'anahtar_env = "TEST_UZAK_ANAHTAR"\nmodeller = ["u-inceler"]\nroller = ["reviewer"]\n',
                        encoding="utf-8")
        monkeypatch.setenv("TEST_UZAK_ANAHTAR", "deneme-degeri")
        assert ac(ortam) == 0
        assert akis.main(["yaz", "s1", "b-yazar", str(ortam[3])]) == 0
        assert akis.main(["incele", "s1", "--profil", "u-inceler"]) == 0, capsys.readouterr().out
    finally:
        sunucu.shutdown()
    assert gelen["yol"] == "/v1/chat/completions"
    assert gelen["yetki"] == "Bearer deneme-degeri"
    assert gelen["govde"]["model"] == "u-inceler"
    # API sağlayıcısı yazıcı olamaz.
    assert akis.main(["yaz", "s1", "u-inceler", str(ortam[3])]) == 2


# --- sırlar ve zaman aşımı ------------------------------------------------------------------

def test_sir_ortami_yaziciya_gecmez(ortam, monkeypatch, capsys):
    jeton = "ghp_" + "A1b2C3d4E5f6G7h8I9j0" * 2
    dosya = ortam[0] / "ortam.json"
    monkeypatch.setenv("SAHTE_MOD", "ortam")
    monkeypatch.setenv("SAHTE_ORTAM_DOSYASI", str(dosya))
    monkeypatch.setenv("GITHUB_TOKEN", jeton)
    monkeypatch.setenv("OZEL_SECRET", "kisa")
    monkeypatch.setenv("ZARARSIZ_DEGER", "1")
    monkeypatch.setenv("IZINLI_TOKEN", "acik")
    monkeypatch.setenv("NOBET_ORTAM_IZIN", "IZINLI_TOKEN")
    assert ac(ortam) == 0
    assert akis.main(["yaz", "s1", "b-yazar", str(ortam[3])]) == 0
    gorulen = json.loads(dosya.read_text())
    assert "GITHUB_TOKEN" not in gorulen and "OZEL_SECRET" not in gorulen
    assert gorulen["ZARARSIZ_DEGER"] == "1" and gorulen["IZINLI_TOKEN"] == "acik"
    d, _ = serit(ortam)
    for f in d.iterdir():
        if f.is_file():
            assert jeton not in f.read_text(encoding="utf-8", errors="replace"), f.name


def test_zaman_asimi_surec_agacini_kapatir(ortam, monkeypatch, capsys):
    assert ac(ortam) == 0
    monkeypatch.setenv("SAHTE_MOD", "uyku")
    monkeypatch.setenv("NOBET_AKIS_SURE", "1")
    bas = time.monotonic()
    assert akis.main(["yaz", "s1", "b-yazar", str(ortam[3])]) == 1
    assert time.monotonic() - bas < 30
    d, _ = serit(ortam)
    assert "cikis: 124" in (d / "yaz-1.log").read_text()


def test_komut_sablonu():
    argv = akis.komut_kur("ajan --cd {worktree} -m {model}", {"worktree": "a b", "model": "m", "istem": "",
                                                              "cikti": "", "rol": ""})
    assert argv == ["ajan", "--cd", "a b", "-m", "m"]
    with pytest.raises(akis.AkisHatasi, match="bilinmeyen yer tutucu"):
        akis.komut_kur("ajan {anahtar}", {})


def test_anahtar_sifresiz_uzak_adrese_gitmez(monkeypatch):
    from nobet.ayar import Saglayici
    s = Saglayici("u", "api", "", "http://ornek.example/v1", "TEST_UZAK_ANAHTAR", ("m",), frozenset({"reviewer"}))
    monkeypatch.setenv("TEST_UZAK_ANAHTAR", "x")
    with pytest.raises(akis.AkisHatasi, match="yerel adrese"):
        akis.api_cagir(s, "m", "istem", 1)


# --- kapat ----------------------------------------------------------------------------------

def test_kapat_kirli_agacta_durur(ortam, capsys):
    assert ac(ortam) == 0
    assert akis.main(["yaz", "s1", "b-yazar", str(ortam[3])]) == 0
    assert akis.main(["kapat", "s1"]) == 1
    _, wt = serit(ortam)
    assert (wt / "src" / "a.py").read_text() == "yeni\n"


@pytest.mark.skipif(sys.platform == "win32", reason="sembolik bağ yetkisi gerekir")
def test_kapat_serit_disina_dokunmaz(ortam, capsys):
    tmp = ortam[0]
    disari = tmp / "disari"
    disari.mkdir()
    (disari / "korunan.txt").write_text("dokunma\n")
    assert ac(ortam) == 0
    _, wt = serit(ortam)
    (wt / "dis-bag").symlink_to(disari, target_is_directory=True)  # .gitignore'da: ağaç temiz sayılır
    (wt / "tests" / "test_kabul.py").unlink()  # kabul dosyası izlenmiyor; ağaç temiz kalsın
    assert akis.main(["kapat", "s1"]) == 0, capsys.readouterr()
    assert not wt.exists()
    assert (disari / "korunan.txt").read_text() == "dokunma\n"


def test_kapat_bozuk_kayitta_baska_dizine_dokunmaz(ortam, capsys):
    tmp, repo, *_ = ortam
    baska = tmp / "baska"
    baska.mkdir()
    (baska / "dosya.txt").write_text("x\n")
    assert ac(ortam) == 0
    d, wt = serit(ortam)
    for hedef in (repo, baska):
        (d / "worktree").write_text(f"{hedef}\n", encoding="utf-8")
        assert akis.main(["kapat", "s1"]) == 2
    assert (baska / "dosya.txt").is_file()
    assert (repo / "src" / "a.py").is_file() and (repo / ".git").exists()
    assert wt.is_dir()
