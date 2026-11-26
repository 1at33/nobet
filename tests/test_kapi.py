"""Sert kapı, rapor şeması ve madde komutları testleri."""
import subprocess
import sys

import pytest

from nobet import kapi


def git(wt, *args):
    subprocess.run(["git", "-C", str(wt), *args], check=True, capture_output=True)


@pytest.fixture
def serit(tmp_path):
    """(iş dizini, worktree): tabanda src/a.py, tests/test_a.py, kok.txt; sahiplik src/** + tests/**."""
    d, wt = tmp_path / "is", tmp_path / "wt"
    d.mkdir()
    (wt / "src").mkdir(parents=True)
    (wt / "tests").mkdir()
    git(wt, "init", "-q")
    git(wt, "config", "core.autocrlf", "false")
    (wt / "src" / "a.py").write_text("a\n")
    (wt / "tests" / "test_a.py").write_text("t\n")
    (wt / "kok.txt").write_text("k\n")
    git(wt, "add", "-A")
    git(wt, "-c", "user.name=t", "-c", "user.email=t@l", "commit", "-qm", "ilk")
    taban = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout
    (d / "taban").write_text(taban)
    (d / "sahiplik").write_text("src/**\ntests/**\n")
    return d, wt


def sozlesme(d, maddeler):
    (d / "sozlesme.md").write_text(
        "# soz\n## Maddeler\n" + "".join(f"{m}\n" for m in maddeler) + "\n```bitti\ntrue\n```\n",
        encoding="utf-8",
    )


# --- glob ---------------------------------------------------------------------------------

@pytest.mark.parametrize("glob,yol,beklenen", [
    ("src/**", "src/a/b.py", True),
    ("src/**", "srcx/a.py", False),
    ("**/*.py", "a.py", True),
    ("**/*.py", "x/y/a.py", True),
    ("src/*.py", "src/a/b.py", False),
    ("a?.txt", "ab.txt", True),
    ("docs", "docs/x.md", True),
])
def test_eslesir(glob, yol, beklenen):
    assert kapi.eslesir(yol, [glob]) is beklenen


# --- denetle ------------------------------------------------------------------------------

def test_temiz(serit, capsys):
    d, wt = serit
    (wt / "src" / "a.py").write_text("b\n")
    (wt / "tests" / "test_yeni.py").write_text("n\n")
    assert kapi.denetle(d, wt) == 0
    assert "kapi: temiz" in capsys.readouterr().out


def test_sahiplik_disi_ekleme_ve_silme(serit, capsys):
    d, wt = serit
    (wt / "disari.txt").write_text("x\n")
    (wt / "kok.txt").unlink()
    assert kapi.denetle(d, wt) == 1
    out = capsys.readouterr().out
    assert "kapi_ihlal: disari.txt (sahiplik dışı (A))" in out
    assert "kapi_ihlal: kok.txt (sahiplik dışı (D))" in out


def test_onbellek_sayilmaz(serit):
    d, wt = serit
    (wt / "__pycache__").mkdir()
    (wt / "__pycache__" / "x.pyc").write_bytes(b"c")
    assert kapi.denetle(d, wt) == 0


def test_mevcut_test_degisti_ve_izin(serit, capsys):
    d, wt = serit
    (wt / "tests" / "test_a.py").write_text("degisti\n")
    assert kapi.denetle(d, wt) == 1
    assert "mevcut test değişti" in capsys.readouterr().out
    (d / "test-izni").write_text("tests/test_a.py\n")
    assert kapi.denetle(d, wt) == 0
    assert "kapi_izin: tests/test_a.py" in capsys.readouterr().out


def test_yeniden_adlandirma_silme_sayilir(serit, capsys):
    d, wt = serit
    git(wt, "mv", "tests/test_a.py", "tests/test_b.py")
    assert kapi.denetle(d, wt) == 1
    assert "kapi_ihlal: tests/test_a.py (mevcut test silindi)" in capsys.readouterr().out


def test_kabul_dondurma(serit, capsys):
    d, wt = serit
    (d / "sahiplik").write_text("src/**\n")
    (wt / "tests" / "test_kabul.py").write_text("kabul\n")
    assert kapi.kabul_yaz(d, wt, ["./tests/test_kabul.py"]) == 0
    assert kapi.denetle(d, wt) == 0  # sahiplik dışında ama kabul: muaf
    (wt / "tests" / "test_kabul.py").write_text("hile\n")
    assert kapi.denetle(d, wt) == 1
    assert "kabul testi değişti" in capsys.readouterr().out
    (wt / "tests" / "test_kabul.py").unlink()
    assert kapi.denetle(d, wt) == 1
    assert "kabul testi silindi" in capsys.readouterr().out
    with pytest.raises(kapi.Denetlenemedi):
        kapi.kabul_yaz(d, wt, ["tests/yok.py"])


def test_sahiplik_yok_fail_closed_eski_uyari(serit, capsys, monkeypatch):
    d, wt = serit
    (d / "sahiplik").unlink()
    (wt / "her.txt").write_text("x\n")
    with pytest.raises(kapi.Denetlenemedi, match="sahiplik dosyası yok"):
        kapi.denetle(d, wt)
    monkeypatch.setattr(kapi, "ESKI", True)
    assert kapi.denetle(d, wt) == 0
    assert "UYARI: sahiplik dosyası yok" in capsys.readouterr().out


def test_taban_cozulemez_fail_closed(serit):
    d, wt = serit
    (d / "taban").write_text("0" * 40 + "\n")
    with pytest.raises(kapi.Denetlenemedi):
        kapi.denetle(d, wt)


@pytest.mark.parametrize("icerik", ["taban\n", None])
def test_taban_yok_ya_da_bozuk_fail_closed(serit, monkeypatch, capsys, icerik):
    d, wt = serit
    if icerik is None:
        (d / "taban").unlink()
    else:
        (d / "taban").write_text(icerik)
    with pytest.raises(kapi.Denetlenemedi, match="taban"):
        kapi.denetle(d, wt)
    monkeypatch.setattr(kapi, "ESKI", True)
    assert kapi.denetle(d, wt) == 0
    assert "taban yok" in capsys.readouterr().out


# --- review bulguları (2026-11-04) --------------------------------------------------------

@pytest.mark.parametrize("bayrak", ["--assume-unchanged", "--skip-worktree"])
def test_index_bayragi_gizlemez(serit, capsys, bayrak):
    d, wt = serit
    (wt / "tests" / "test_a.py").write_text("zayif\n")
    git(wt, "update-index", bayrak, "tests/test_a.py")
    assert kapi.denetle(d, wt) == 1
    assert "index bayrağıyla gizlenmiş" in capsys.readouterr().out


def test_bayrakli_ama_degismemis_dosya_temiz(serit):
    d, wt = serit
    git(wt, "update-index", "--skip-worktree", "tests/test_a.py")
    assert kapi.denetle(d, wt) == 0


def test_kendini_gizleyen_gitignore(serit, capsys):
    d, wt = serit
    (wt / "pkg").mkdir()
    (wt / "pkg" / ".gitignore").write_text("*\n")
    (wt / "pkg" / "conftest.py").write_text("x\n")
    assert kapi.denetle(d, wt) == 1
    assert "kendini yok sayan yeni .gitignore" in capsys.readouterr().out


def test_info_exclude_gizlemez(serit, capsys):
    d, wt = serit
    (wt / "gizli.py").write_text("x\n")
    (wt / ".git" / "info").mkdir(exist_ok=True)
    with open(wt / ".git" / "info" / "exclude", "a") as f:
        f.write("gizli.py\n")
    assert kapi.denetle(d, wt) == 1
    assert "kapi_ihlal: gizli.py (sahiplik dışı (A))" in capsys.readouterr().out


def test_bom_sahiplik(serit):
    d, wt = serit
    (d / "sahiplik").write_bytes(b"\xef\xbb\xbfsrc/**\n")
    (wt / "src" / "a.py").write_text("b\n")
    assert kapi.denetle(d, wt) == 0


@pytest.mark.parametrize("yol,beklenen", [
    ("latest.md", False), ("src/contest.py", False), ("FooTest.java", True), ("conftest.py", True),
    ("pytest.ini", True), ("a/test.py", True), ("test-run.sh", True), ("x_spec.rb", True),
    ("__tests__/a.js", True), ("src/app.py", False),
])
def test_test_kalibi(yol, beklenen):
    assert bool(kapi.TEST.search(yol)) is beklenen


def test_kabul_kisitlari(serit):
    d, wt = serit
    (wt / "src" / "kod.py").write_text("k\n")
    (wt / "tests" / "test_yeni.py").write_text("k\n")
    with pytest.raises(kapi.Denetlenemedi, match="tabanda var olan"):
        kapi.kabul_yaz(d, wt, ["tests/test_a.py"])
    with pytest.raises(kapi.Denetlenemedi, match="yalnız test dosyası"):
        kapi.kabul_yaz(d, wt, ["src/kod.py"])
    with pytest.raises(kapi.Denetlenemedi, match="worktree dışında"):
        kapi.kabul_yaz(d, wt, ["../disari.py"])
    assert kapi.kabul_yaz(d, wt, [str(wt / "tests" / "test_yeni.py")]) == 0
    assert "\ttests/test_yeni.py" in (d / "kabul").read_text(encoding="utf-8")


@pytest.mark.parametrize("metin,parca", [
    ("# s\n## Arayüz\n1. adım\n## Ölçüt\n1. ikinci liste\n", "madde 1 iki kez"),
    ("# s\n## Maddeler\n1. a\n1. b\n", "madde 1 iki kez"),
    ("# s\n## Maddeler\n1. a: `pytest -q` çıkış 0\n", "koşulamaz"),
    ("# s\n## Maddeler\n1. a: `true` çıkış 0 olmalı\n", "koşulamaz"),
])
def test_sozlesme_dogrula_hata(metin, parca):
    assert any(parca in h for h in kapi.sozlesme_dogrula(metin))


def test_sozlesme_alt_baslik_ve_kod_citi(tmp_path):
    (tmp_path / "sozlesme.md").write_text(
        "# s\n## Kabul maddeleri\n### Grup A\n1. a: `true` → çıkış: 0\n```\n# yorum\n2. kod içi\n```\n"
        "### Grup B\n2. b\n## Notlar\n3. bölüm dışı ama madde var\n", encoding="utf-8")
    assert kapi.sozlesme_maddeleri(tmp_path) == [1, 2]
    assert kapi.calisir_maddeler(tmp_path) == {1: ("true", 0)}


def test_sozlesme_dogrula_duz_anlatim_hata_degil():
    # 113 gerçek sözleşmede ölçüldü: davranış anlatan "çıkış 1" düz metindir, koşulamaz hatası değil.
    assert kapi.sozlesme_dogrula("# s\n1. `--gorev` yoksa davranış aynı; `ORNEK_OTURUM` boşsa çıkış 1 ve yan etki yok\n") == []


def test_basliksiz_sozlesme_butun_numarali_satirlar(tmp_path):
    (tmp_path / "sozlesme.md").write_text("# s\n1. a: `true` → çıkış 0\nmetin\n2. b\n  3. girintili\n", encoding="utf-8")
    assert kapi.sozlesme_maddeleri(tmp_path) == [1, 2]
    assert kapi.calisir_maddeler(tmp_path) == {1: ("true", 0)}


def test_bozuk_sozlesme_rapor_fail_closed(tmp_path):
    (tmp_path / "sozlesme.md").write_text("# s\n1. bir\n1. yine bir\n", encoding="utf-8")
    with pytest.raises(kapi.Denetlenemedi, match="sözleşme biçimi"):
        rapor(tmp_path, "bitti: KARŞILANMADI | neden: x\n", gecerli=False)


def test_kosulmayan_madde_red(tmp_path, capsys):
    sozlesme(tmp_path, ["1. a: `true` → çıkış 0", "2. b: `true` → çıkış 0"])
    log = tmp_path / "madde.log"
    log.write_text("1\t0\t0\n")
    metin = ("madde 1: KARŞILANDI | kanıt: `true` → 0\nmadde 2: KARŞILANDI | kanıt: `true` → 0\n"
             "bitti: KARŞILANDI | kanıt: `b` → 0\n")
    assert rapor(tmp_path, metin, madde_log=log) == 1
    assert any("madde 2: sözleşme komutu koşulmadı" in h for h in hatalar(capsys))


def test_kalin_ve_alinti_satir(soz):
    metin = ("> **madde 1**: **KARŞILANDI** | kanıt: `x` ⇒ y\n- __madde 2__: KARŞILANMADI | neden: z\n"
             "**bitti:** KARŞILANDI | kanıt: `b` → 0\n")
    assert rapor(soz, metin) == 0


def test_bom_rapor(soz):
    assert rapor(soz, "﻿" + IYI) == 0


# --- sözleşme ve madde komutları ----------------------------------------------------------

def test_calisir_maddeler(tmp_path):
    sozlesme(tmp_path, [
        "1. geçer: `py -m pytest -q` → çıkış 0",
        "2. ascii: `false` -> cikis 1",
        "3. komut yok: `src/gizli.py` sade",
        "  4. girintili sayılmaz: `true` → çıkış 0",
    ])
    assert kapi.sozlesme_maddeleri(tmp_path) == [1, 2, 3]
    assert kapi.calisir_maddeler(tmp_path) == {1: ("py -m pytest -q", 0), 2: ("false", 1)}


def test_madde_cmd(tmp_path, capsys):
    sozlesme(tmp_path, ["1. a: `true` → çıkış 0", "2. b: `exit 3` → çıkış 3"])
    assert kapi.madde_cmd(tmp_path, tmp_path / "c") == 0
    assert capsys.readouterr().out.splitlines() == ["1\t0", "2\t3"]
    assert (tmp_path / "c" / "madde-2.cmd").read_text(encoding="utf-8") == "exit 3\n"


def test_madde_log_bozuk(tmp_path):
    (tmp_path / "m.log").write_text("1\tx\t0\n")
    with pytest.raises(kapi.Denetlenemedi):
        kapi.madde_log_oku(tmp_path / "m.log")


# --- rapor şeması -------------------------------------------------------------------------

IYI = (
    "Özet\n"
    "madde 1: KARŞILANDI | kanıt: `py -m pytest -q` → 3 passed\n"
    "madde 2: KARŞILANMADI | neden: kapsam dışı\n"
    "bitti: KARŞILANDI | kanıt: `orkestrator bitti x` → cikis 0\n"
)


def rapor(tmp_path, metin, gecerli=True, madde_log="-", rol="yazici"):
    r = tmp_path / "rapor.md"
    r.write_text(metin, encoding="utf-8")
    return kapi.rapor(tmp_path, r, gecerli, madde_log, rol)


@pytest.fixture
def soz(tmp_path):
    sozlesme(tmp_path, ["1. bir: `test 1 = 1` → çıkış 0", "2. iki"])
    return tmp_path


def hatalar(capsys):
    return [s for s in capsys.readouterr().out.splitlines() if s.startswith("rapor_hata: ")]


def test_rapor_gecerli(soz, capsys):
    assert rapor(soz, IYI) == 0
    assert "rapor: geçerli (2 madde, bitti yeşil)" in capsys.readouterr().out


def test_rapor_kucuk_harf_ascii(soz):
    metin = ("madde 1: karşılandı | kanıt: `x` -> y\nmadde 2: KARSILANMADI | neden: z\n"
             "bitti: KARSILANDI | kanit: `b` => cikis 0\n")
    assert rapor(soz, metin) == 0


@pytest.mark.parametrize("metin,parca", [
    ("madde 1: KARŞILANDI | kanıt: `x` → y\nbitti: KARŞILANDI | kanıt: `b` → 0\n", "madde 2: raporda yok"),
    ("madde 1: KARŞILANDI geçti\nmadde 2: KARŞILANMADI | neden: a\nbitti: KARŞILANDI | kanıt: `b` → 0\n",
     "madde 1: KARŞILANDI ama kanıt yok"),
    ("madde 1: KARŞILANDI | kanıt: `x` →\nmadde 2: KARŞILANMADI | neden: a\nbitti: KARŞILANDI | kanıt: `b` → 0\n",
     "madde 1: KARŞILANDI ama kanıt yok"),
    ("madde 1: KARŞILANDI | kanıt: `x` → y\nmadde 2: KARŞILANMADI\nbitti: KARŞILANDI | kanıt: `b` → 0\n",
     "madde 2: KARŞILANMADI ama neden yok"),
    (IYI + "madde 3: KARŞILANDI | kanıt: `x` → y\n", "madde 3: sözleşmede yok"),
    (IYI + "madde 1: KARŞILANDI | kanıt: `x` → y\n", "madde 1: 2 kez raporlanmış"),
    ("madde 1: KARŞILANDI | kanıt: `x` → y\nmadde 2: KARŞILANMADI | neden: a\n", "bitti satırı yok"),
    (IYI + "bitti: KARŞILANDI | kanıt: `b` → 0\n", "bitti satırı iki kez"),
])
def test_rapor_red(soz, capsys, metin, parca):
    assert rapor(soz, metin) == 1
    assert any(parca in h for h in hatalar(capsys)), parca


def test_rapor_kirmizi_bittide_karsilandi_red(soz, capsys):
    assert rapor(soz, IYI, gecerli=False) == 1
    assert any("bitti kanıtı yeşil ve güncel değil" in h for h in hatalar(capsys))


def test_rapor_yesil_bittiye_karsilanmadi_celiski(soz, capsys):
    metin = "madde 1: KARŞILANMADI | neden: a\nmadde 2: KARŞILANMADI | neden: b\nbitti: KARŞILANMADI | neden: c\n"
    assert rapor(soz, metin, gecerli=True) == 1
    assert rapor(soz, metin, gecerli=False) == 0


def test_rapor_madde_log_celiski(soz, capsys):
    log = soz / "madde.log"
    log.write_text("1\t1\t0\n2\t0\t0\n")
    metin = ("madde 1: KARŞILANDI | kanıt: `x` → y\nmadde 2: KARŞILANMADI | neden: a\n"
             "bitti: KARŞILANDI | kanıt: `b` → 0\n")
    assert rapor(soz, metin, madde_log=log) == 1
    h = hatalar(capsys)
    assert any("madde 1: KARŞILANDI ama sözleşme komutu çıkış 1 verdi (beklenen 0)" in s for s in h)
    assert any("madde 2: KARŞILANMADI ama sözleşme komutu beklenen çıkışı (0) verdi" in s for s in h)
    log.write_text("1\t0\t0\n2\t1\t0\n")
    assert rapor(soz, metin, madde_log=log) == 0


def test_reviewer_rolu(soz, capsys):
    metin = "Bulgu yok\nmadde 1: KARŞILANDI | kanıt: `a` → b\nmadde 2: KARŞILANMADI | neden: c\n"
    assert rapor(soz, metin, gecerli=False, rol="reviewer") == 0  # bitti satırı ve kanıtı aranmaz
    assert rapor(soz, metin + "madde 1: KARŞILANDI | kanıt: `a` → b\n", gecerli=False, rol="reviewer") == 0
    assert rapor(soz, metin + "madde 1: KARŞILANMADI | neden: x\n", gecerli=False, rol="reviewer") == 1
    assert any("çelişkili" in h for h in hatalar(capsys))
    assert rapor(soz, "BULGU YOK\n", gecerli=False, rol="reviewer") == 1


def test_reviewer_sozlesmesiz_gecer(tmp_path):
    assert rapor(tmp_path, "BULGU YOK\n", gecerli=False, rol="reviewer") == 0


# --- komut satırı -------------------------------------------------------------------------

def test_main_kullanim():
    assert kapi.main([]) == 2
    assert kapi.main(["rapor", "d", "r", "2"]) == 2
    assert kapi.main(["rapor", "d", "r", "1", "-", "baska"]) == 2


def test_cli_lf_ve_cikis_kodu(serit, tmp_path):
    d, wt = serit
    (wt / "disari.txt").write_text("x\n")
    r = subprocess.run([sys.executable, "-I", kapi.__file__, "denetle", str(d), str(wt)], capture_output=True, check=False)
    assert r.returncode == 1
    assert b"\r\n" not in r.stdout
    assert b"kapi_ihlal: disari.txt" in r.stdout
    (d / "taban").write_text("0" * 40 + "\n")
    r = subprocess.run([sys.executable, "-I", kapi.__file__, "denetle", str(d), str(wt)], capture_output=True, check=False)
    assert r.returncode == 2


def test_madde_cikti_sir_maskelenir(tmp_path, monkeypatch):
    sir = "gh" + "p_" + "Q7w9E2r4T6y8U1i3O5p7A9s2D4f6G8h1J3k5"
    d, wt = tmp_path / "is", tmp_path / "wt"
    d.mkdir()
    wt.mkdir()
    monkeypatch.setattr(kapi, "calisir_maddeler", lambda _d: {1: (f"echo token={sir}; echo $VERI_TOKEN", 0)})
    monkeypatch.setenv("VERI_TOKEN", "ortamdaki-gizli-deger")
    assert kapi.madde_kos(d, wt) == 0
    log = (d / "madde-cikti.log").read_text(encoding="utf-8")
    assert sir not in log and "ortamdaki-gizli-deger" not in log and "[gizli]" in log


def test_eski_yalniz_bayrakla(serit, monkeypatch, capsys):
    d, wt = serit
    (d / "sahiplik").unlink()
    monkeypatch.setattr(kapi, "ESKI", False)
    monkeypatch.setenv("NOBET_ESKI", "1")
    with pytest.raises(kapi.Denetlenemedi):
        kapi.main(["denetle", str(d), str(wt)])
    assert "artık okunmuyor" in capsys.readouterr().err
    assert kapi.main(["denetle", str(d), str(wt), "--eski"]) == 0
    monkeypatch.setattr(kapi, "ESKI", False)


def test_madde_komutu_sir_ortamini_gormez(tmp_path, monkeypatch):
    d, wt = tmp_path / "is", tmp_path / "wt"
    d.mkdir()
    wt.mkdir()
    monkeypatch.setattr(kapi, "calisir_maddeler",
                        lambda _d: {1: ('test -z "$ORNEK_API_KEY" && test "$IZINLI_TOKEN" = acik', 0)})
    monkeypatch.setenv("ORNEK_API_KEY", "gizli-deger-123")
    monkeypatch.setenv("IZINLI_TOKEN", "acik")
    monkeypatch.setenv("NOBET_ORTAM_IZIN", "IZINLI_TOKEN")
    kapi.madde_kos(d, wt)
    assert (d / "madde.log").read_text(encoding="utf-8").split("\t")[1] == "0"


# --- Test sonucunu değiştiren yeni dosyalar ve güvenilmez git yapılandırması ---
@pytest.mark.parametrize("yol", [
    "src/sitecustomize.py", "src/usercustomize.py", "src/x.pth", "src/conftest.py", "tests/yeni/conftest.py",
])
def test_yeni_sonuc_degistiren_dosya_ihlal(serit, capsys, yol):
    d, wt = serit
    (wt / yol).parent.mkdir(parents=True, exist_ok=True)
    (wt / yol).write_text("x\n")
    assert kapi.denetle(d, wt) == 1
    assert f"kapi_ihlal: {yol} (test sonucunu değiştirebilen dosya)" in capsys.readouterr().out


def test_sonuc_degistiren_dosya_test_izni_ile_gecer(serit, capsys):
    d, wt = serit
    (wt / "src" / "sitecustomize.py").write_text("x\n")
    (d / "test-izni").write_text("src/sitecustomize.py\n")
    assert kapi.denetle(d, wt) == 0
    assert "kapi_izin: src/sitecustomize.py (test-izni)" in capsys.readouterr().out


def test_sonuc_degistiren_dosya_kabulde_gecer(serit):
    d, wt = serit
    (wt / "tests" / "conftest.py").write_text("x\n")
    kapi.kabul_yaz(d, wt, ["tests/conftest.py"])
    assert kapi.denetle(d, wt) == 0


def test_mevcut_conftest_degisimi_ihlal_kalir(serit, capsys):
    d, wt = serit
    (wt / "tests" / "conftest.py").write_text("a\n")
    git(wt, "add", "-A")
    git(wt, "-c", "user.name=t", "-c", "user.email=t@l", "commit", "-qm", "conftest")
    (d / "taban").write_text(subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"],
                                            capture_output=True, text=True, check=False).stdout)
    (wt / "tests" / "conftest.py").write_text("b\n")
    assert kapi.denetle(d, wt) == 1
    assert "mevcut test değişti" in capsys.readouterr().out


@pytest.mark.skipif(sys.platform == "win32", reason="fsmonitor betiği sh ile yazıldı")
def test_fsmonitor_yapilandirmasi_gizlemez(serit, capsys):
    d, wt = serit
    iz = wt.parent / "fsm-calisti"
    betik = wt.parent / "fsm.sh"
    betik.write_text(f"#!/bin/sh\ntouch '{iz}'\nexit 0\n")  # hiçbir şey değişmedi der
    betik.chmod(0o755)
    git(wt, "config", "core.fsmonitor", str(betik))
    if subprocess.run(["git", "-C", str(wt), "update-index", "--fsmonitor"], capture_output=True, check=False).returncode:
        pytest.skip("kurulu git fsmonitor hook'unu desteklemiyor")
    iz.unlink(missing_ok=True)  # kurulum adımı betiği zaten çalıştırmış olabilir
    (wt / "tests" / "test_a.py").write_text("degisti\n")
    assert kapi.denetle(d, wt) == 1
    assert "mevcut test değişti" in capsys.readouterr().out
    assert not iz.exists(), "fsmonitor komutu kapı sürecinde çalıştı"


# --- A1 review'u (Tamga terra-zor, 2026-11-25): pytest yapılandırması, git filtresi, .gitignore ile gizleme ---
def _taban_commit(d, wt, dosyalar):
    for yol, icerik in dosyalar.items():
        (wt / yol).parent.mkdir(parents=True, exist_ok=True)
        (wt / yol).write_text(icerik)
    git(wt, "add", "-A")
    git(wt, "-c", "user.name=t", "-c", "user.email=t@l", "commit", "-qm", "taban")
    (d / "taban").write_text(subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"],
                                            capture_output=True, text=True, check=False).stdout)


@pytest.mark.parametrize("yol", ["pytest.ini", "src/pytest.toml", ".pytest.ini"])
def test_yeni_pytest_ayari_ihlal(serit, capsys, yol):
    d, wt = serit
    (d / "sahiplik").write_text("**\n")
    (wt / yol).parent.mkdir(parents=True, exist_ok=True)
    (wt / yol).write_text("[pytest]\naddopts = -k yok\n")
    assert kapi.denetle(d, wt) == 1
    assert f"kapi_ihlal: {yol} (test sonucunu değiştirebilen dosya)" in capsys.readouterr().out


@pytest.mark.parametrize("yol,icerik", [
    ("pyproject.toml", "[tool.pytest.ini_options]\naddopts = '-k yok'\n"),
    ("setup.cfg", "[tool:pytest]\naddopts = -k yok\n"),
    ("tox.ini", "[pytest]\naddopts = -k yok\n"),
])
def test_ortak_ayara_pytest_bolumu_eklemek_ihlal(serit, capsys, yol, icerik):
    d, wt = serit
    (d / "sahiplik").write_text("**\n")
    _taban_commit(d, wt, {yol: "[project]\nname = 'x'\n"})
    (wt / yol).write_text(icerik)
    assert kapi.denetle(d, wt) == 1
    assert f"kapi_ihlal: {yol} (pytest yapılandırması değişti)" in capsys.readouterr().out


def test_ortak_ayardan_pytest_bolumu_silmek_ihlal(serit, capsys):
    d, wt = serit
    (d / "sahiplik").write_text("**\n")
    _taban_commit(d, wt, {"pyproject.toml": "[project]\nname = 'x'\n[tool.pytest.ini_options]\nxfail_strict = true\n"})
    (wt / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    assert kapi.denetle(d, wt) == 1
    assert "pytest yapılandırması değişti" in capsys.readouterr().out


def test_pytest_bolumsuz_pyproject_degisimi_serbest(serit):
    d, wt = serit
    (d / "sahiplik").write_text("**\n")
    _taban_commit(d, wt, {"pyproject.toml": "[project]\nname = 'x'\n"})
    (wt / "pyproject.toml").write_text("[project]\nname = 'x'\ndependencies = ['y']\n")
    assert kapi.denetle(d, wt) == 0


def test_pytest_ayari_test_izni_ile_gecer(serit, capsys):
    d, wt = serit
    (d / "sahiplik").write_text("**\n")
    (wt / "pytest.ini").write_text("[pytest]\n")
    (d / "test-izni").write_text("pytest.ini\n")
    assert kapi.denetle(d, wt) == 0
    assert "kapi_izin: pytest.ini (test-izni)" in capsys.readouterr().out


@pytest.mark.parametrize("yol", ["tests/__init__.py", "tests/alt/__init__.py"])
def test_yeni_test_paketi_init_ihlal(serit, capsys, yol):
    d, wt = serit
    (wt / yol).parent.mkdir(parents=True, exist_ok=True)
    (wt / yol).write_text("import os\n")
    assert kapi.denetle(d, wt) == 1
    assert "test paketi __init__" in capsys.readouterr().out


def test_kaynak_paket_init_serbest(serit):
    d, wt = serit
    (wt / "src" / "pkg").mkdir()
    (wt / "src" / "pkg" / "__init__.py").write_text("x = 1\n")
    assert kapi.denetle(d, wt) == 0


def test_clean_filtresi_kabul_testini_gizleyemez(serit, capsys, tmp_path):
    d, wt = serit
    (d / "sahiplik").write_text("**\n")
    (wt / "tests" / "test_k.py").write_text("orj\n")
    kapi.kabul_yaz(d, wt, ["tests/test_k.py"])
    (wt / "tests" / "test_k.py").write_text("degisti\n")
    eski = tmp_path / "eski"
    eski.write_text("orj\n")
    git(wt, "config", "filter.f.clean", f"cat '{eski.as_posix()}'")
    (wt / "tests" / ".gitattributes").write_text("test_k.py filter=f\n")
    assert kapi.denetle(d, wt) == 1
    out = capsys.readouterr().out
    assert "kapi_ihlal: tests/test_k.py (kabul testi değişti)" in out
    assert "yerel git filtresi (filter.f.clean)" in out


def test_blob_filtre_uygulamaz(serit, tmp_path):
    _d, wt = serit
    eski = tmp_path / "eski"
    eski.write_text("orj\n")
    git(wt, "config", "filter.f.clean", f"cat '{eski.as_posix()}'")
    (wt / ".gitattributes").write_text("*.py filter=f\n")
    (wt / "src" / "a.py").write_text("degisti\n")
    ham = subprocess.run(["git", "hash-object", "--no-filters", str(wt / "src" / "a.py")],
                         capture_output=True, text=True, check=True).stdout.strip()
    assert kapi.blob(wt, "src/a.py") == ham


def test_izlenen_gitignore_degisimi_ihlal(serit, capsys):
    d, wt = serit
    (d / "sahiplik").write_text("**\n")
    _taban_commit(d, wt, {".gitignore": "*.log\n"})
    (wt / ".gitignore").write_text("*.log\nsitecustomize.py\n")
    (wt / "src" / "sitecustomize.py").write_text("x\n")
    assert kapi.denetle(d, wt) == 1
    assert "kapi_ihlal: .gitignore (.gitignore değişti (dosya gizleyebilir))" in capsys.readouterr().out


def test_yeni_alt_gitignore_ihlal(serit, capsys):
    d, wt = serit
    (wt / "src" / ".gitignore").write_text("sitecustomize.py\n")
    (wt / "src" / "sitecustomize.py").write_text("x\n")
    assert kapi.denetle(d, wt) == 1
    assert "kapi_ihlal: src/.gitignore (.gitignore değişti (dosya gizleyebilir))" in capsys.readouterr().out


def test_alt_gitignore_silinmesi_ihlal(serit, capsys):
    """Üst kuralı "!" ile açan alt .gitignore silinince izlenmeyen dosya gizlenir (B4 review, 2026-11-26)."""
    d, wt = serit
    (d / "sahiplik").write_text("**\n")
    _taban_commit(d, wt, {".gitignore": "*.cfg\n", "src/.gitignore": "!ozel.cfg\n"})
    (wt / "src" / ".gitignore").unlink()
    (wt / "src" / "ozel.cfg").write_text("x\n")
    assert kapi.denetle(d, wt) == 1
    assert "kapi_ihlal: src/.gitignore (.gitignore değişti (dosya gizleyebilir))" in capsys.readouterr().out


def test_kosulabilir_madde_yok_bicimsel_kanit_red(tmp_path, capsys):
    sozlesme(tmp_path, ["1. bir", "2. iki"])
    metin = ("madde 1: KARŞILANDI | kanıt: `echo ok` → ok\nmadde 2: KARŞILANDI | kanıt: `echo ok` → ok\n"
             "bitti: KARŞILANDI | kanıt: `b` → 0\n")
    assert rapor(tmp_path, metin) == 1
    assert any("koşulabilir madde yok" in h for h in hatalar(capsys))


def test_kosulabilir_madde_yok_sozlesmesiz_etkilenmez(tmp_path):
    assert rapor(tmp_path, "bitti: KARŞILANDI | kanıt: `b` → 0\n") == 0


def test_kosulabilir_madde_yok_reviewer_etkilenmez(tmp_path):
    sozlesme(tmp_path, ["1. bir", "2. iki"])
    metin = "madde 1: KARŞILANDI | kanıt: `a` → b\nmadde 2: KARŞILANMADI | neden: c\n"
    assert rapor(tmp_path, metin, gecerli=False, rol="reviewer") == 0


@pytest.mark.parametrize("komut", ["true", ":", "exit 0", "# sadece yorum"])
def test_anlamsiz_komut_kosulabilir_sayilmaz(tmp_path, capsys, komut):
    sozlesme(tmp_path, [f"1. bir: `{komut}` → çıkış 0"])
    metin = "madde 1: KARŞILANDI | kanıt: `echo ok` → ok\nbitti: KARŞILANDI | kanıt: `b` → 0\n"
    assert rapor(tmp_path, metin) == 1
    assert any("komutu anlamsız" in h for h in hatalar(capsys))


def test_anlamsiz_komutla_birlikte_anlamli_madde_gecer(tmp_path):
    sozlesme(tmp_path, ["1. bir: `true` → çıkış 0", "2. iki: `test 1 = 1` → çıkış 0"])
    metin = ("madde 1: KARŞILANDI | kanıt: `x` → y\nmadde 2: KARŞILANDI | kanıt: `x` → y\n"
             "bitti: KARŞILANDI | kanıt: `b` → 0\n")
    assert rapor(tmp_path, metin) == 0


@pytest.mark.parametrize("son", ["0abc", "0x", "1_000"])
def test_cikis_sayisindan_sonra_sinir_ister(tmp_path, capsys, son):
    sozlesme(tmp_path, [f"1. bir: `test 1 = 1` → çıkış {son}"])
    assert kapi.calisir_maddeler(tmp_path) == {}
    metin = "madde 1: KARŞILANDI | kanıt: `echo ok` → ok\nbitti: KARŞILANDI | kanıt: `b` → 0\n"
    assert rapor(tmp_path, metin) == 1
    assert any("koşulabilir madde yok" in h for h in hatalar(capsys))


def test_cikis_sayisi_sonrasi_noktalama_ve_aciklama_serbest(tmp_path):
    (tmp_path / "sozlesme.md").write_text("# s\n1. bir: `test 1 = 1` → çıkış 0.\n2. iki: `test 2 = 2` → çıkış 3 olmalı\n",
                                          encoding="utf-8")
    assert kapi.calisir_maddeler(tmp_path) == {1: ("test 1 = 1", 0), 2: ("test 2 = 2", 3)}


def test_bosluk_komutu_kosulabilir_sayilmaz(tmp_path):
    sozlesme(tmp_path, ["1. bir: ` ` → çıkış 0"])
    metin = "madde 1: KARŞILANDI | kanıt: `echo ok` → ok\nbitti: KARŞILANDI | kanıt: `b` → 0\n"
    assert rapor(tmp_path, metin) == 1
