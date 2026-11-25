"""Kabul testi: nobet/bitti.py (sozlesme: adim3-bitti).

Gercek git depolari tmp_path altinda kurulur; calisma klasorunun git'ine dokunulmaz.
"""
import ast
import hashlib
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from nobet.bitti import (
    BittiYok,
    BozukBitti,
    DurumHashHatasi,
    bitti_alan,
    bitti_gecerli,
    bitti_guncel,
    bitti_komutu,
    durum_hash,
    durum_hash_hesapla,
    komut_hash,
)

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
       "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false"]


# ---------------------------------------------------------------- yardimcilar
def git(repo, *args):
    r = subprocess.run(GIT + list(args), cwd=str(repo), capture_output=True, check=False)
    assert r.returncode == 0, r.stderr.decode(errors="replace")
    return r.stdout.decode("utf-8", errors="replace").strip()


def blob_hex(b: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()


def beklenen_durum(head: bytes, dosyalar: dict) -> str:
    h = hashlib.sha1()
    h.update(b"HEAD " + head + b"\n")
    for ad in sorted(dosyalar):
        h.update(b"%d:" % len(ad) + ad + b" " + blob_hex(dosyalar[ad]).encode() + b"\n")
    return h.hexdigest()


def depo_kur(yol: Path) -> Path:
    yol.mkdir(parents=True, exist_ok=True)
    git(yol, "init", "-q")
    (yol / "a.txt").write_bytes(b"alfa\n")
    (yol / ".gitignore").write_bytes(b"ignored.txt\nbuild/\n")
    git(yol, "add", "-A")
    git(yol, "commit", "-q", "-m", "ilk")
    return yol


def commit_et(yol: Path, mesaj="degisim"):
    git(yol, "add", "-A")
    git(yol, "commit", "-q", "-m", mesaj)


def head_sha(yol: Path) -> str:
    return git(yol, "rev-parse", "HEAD")


def log_yaz(is_dizini: Path, komut_h, cikis, durum, govde_komut="echo hi", ekstra=""):
    metin = "tarih: 2026-11-04T10:00:00+03:00\n"
    if komut_h is not None:
        metin += f"komut_hash: {komut_h}\n"
    if cikis is not None:
        metin += f"cikis: {cikis}\n"
    if durum is not None:
        metin += f"durum_hash: {durum}\n"
    metin += ekstra + f"\nkomut| {govde_komut}\ncikti| tamam\n"
    (is_dizini / "bitti.log").write_bytes(metin.encode("utf-8"))


class Ortam:
    """is_dizini + worktree (git deposu) + bitti.cmd."""

    def __init__(self, tmp_path: Path, komut="echo hi"):
        self.is_dizini = tmp_path / "is"
        self.is_dizini.mkdir()
        self.wt = depo_kur(tmp_path / "wt")
        self.komut = komut
        (self.is_dizini / "bitti.cmd").write_bytes((komut + "\n").encode())
        self.kh = blob_hex(komut.encode("utf-8"))

    def log(self, cikis="0", durum="BUGUN", **kw):
        if durum == "BUGUN":
            durum = durum_hash(self.wt)
        log_yaz(self.is_dizini, kw.pop("komut_h", self.kh), cikis, durum,
                govde_komut=self.komut, **kw)
        return durum

    def bag(self, *satirlar):
        (self.is_dizini / "bitti-bag").write_bytes(("".join(s + "\n" for s in satirlar)).encode())

    def guncel(self):
        return bitti_guncel(self.is_dizini, self.wt)

    def gecerli(self):
        return bitti_gecerli(self.is_dizini, self.wt)


@pytest.fixture
def ort(tmp_path):
    return Ortam(tmp_path)


# ------------------------------------------------------------- bitti_komutu
def test_komut_bitti_cmd_dosyasi(tmp_path):
    (tmp_path / "bitti.cmd").write_bytes(b"pytest -q\n")
    assert bitti_komutu(tmp_path) == "pytest -q"


def test_komut_bitti_cmd_sozlesmeye_ustun(tmp_path):
    (tmp_path / "bitti.cmd").write_bytes(b"cmd-komutu\n")
    (tmp_path / "sozlesme.md").write_bytes(b"x\n```bitti\nsozlesme-komutu\n```\n")
    assert bitti_komutu(tmp_path) == "cmd-komutu"


def test_komut_sondaki_satir_sonlari_atilir_aradakiler_korunur(tmp_path):
    (tmp_path / "bitti.cmd").write_bytes(b"echo a\n\necho b\n\n\n")
    assert bitti_komutu(tmp_path) == "echo a\n\necho b"


def test_komut_bastaki_bosluk_ve_satirlar_korunur(tmp_path):
    (tmp_path / "bitti.cmd").write_bytes(b"\n  echo a  \n")
    assert bitti_komutu(tmp_path) == "\n  echo a  "


def test_komut_sozlesme_blogu(tmp_path):
    (tmp_path / "sozlesme.md").write_bytes(
        b"# Baslik\n\n```bitti\npython -m pytest -q\nsatir2\n```\n\nson\n")
    assert bitti_komutu(tmp_path) == "python -m pytest -q\nsatir2"


def test_komut_sozlesme_acilis_ve_kapanis_sonunda_bosluk(tmp_path):
    (tmp_path / "sozlesme.md").write_bytes(b"```bitti \t \nkomut\n```   \nartik\n")
    assert bitti_komutu(tmp_path) == "komut"


def test_komut_sozlesme_ikinci_blok_yok_sayilir(tmp_path):
    (tmp_path / "sozlesme.md").write_bytes(
        b"```bitti\nbirinci\n```\n\n```bitti\nikinci\n```\n")
    assert bitti_komutu(tmp_path) == "birinci"


def test_komut_sozlesme_blok_ici_bos_satir_korunur(tmp_path):
    (tmp_path / "sozlesme.md").write_bytes(b"```bitti\na\n\nb\n\n```\n")
    assert bitti_komutu(tmp_path) == "a\n\nb"


def test_komut_sozlesme_baska_dilli_blok_bitti_degil(tmp_path):
    (tmp_path / "sozlesme.md").write_bytes(b"```python\nprint(1)\n```\n```bitti\nreal\n```\n")
    assert bitti_komutu(tmp_path) == "real"


def test_komut_sozlesme_girintili_acilis_sayilmaz(tmp_path):
    (tmp_path / "sozlesme.md").write_bytes(b"  ```bitti\nkomut\n```\n")
    with pytest.raises(BittiYok):
        bitti_komutu(tmp_path)


def test_komut_hicbiri_yok_BittiYok(tmp_path):
    with pytest.raises(BittiYok):
        bitti_komutu(tmp_path)


def test_komut_sozlesme_blok_yok_BittiYok(tmp_path):
    (tmp_path / "sozlesme.md").write_bytes(b"# Sozlesme\n```python\nx\n```\n")
    with pytest.raises(BittiYok):
        bitti_komutu(tmp_path)


def test_komut_kapanmamis_blok_BozukBitti(tmp_path):
    (tmp_path / "sozlesme.md").write_bytes(b"```bitti\npytest -q\n")
    with pytest.raises(BozukBitti):
        bitti_komutu(tmp_path)


def test_komut_yalniz_bosluk_cmd_BozukBitti(tmp_path):
    (tmp_path / "bitti.cmd").write_bytes(b"  \n\t\n")
    with pytest.raises(BozukBitti):
        bitti_komutu(tmp_path)


def test_komut_bos_cmd_sozlesmeye_dusmez_BozukBitti(tmp_path):
    (tmp_path / "bitti.cmd").write_bytes(b"")
    (tmp_path / "sozlesme.md").write_bytes(b"```bitti\nkomut\n```\n")
    with pytest.raises(BozukBitti):
        bitti_komutu(tmp_path)


def test_komut_yalniz_bosluk_blok_BozukBitti(tmp_path):
    (tmp_path / "sozlesme.md").write_bytes(b"```bitti\n   \n\n```\n")
    with pytest.raises(BozukBitti):
        bitti_komutu(tmp_path)


def test_komut_bos_blok_BozukBitti(tmp_path):
    (tmp_path / "sozlesme.md").write_bytes(b"```bitti\n```\n")
    with pytest.raises(BozukBitti):
        bitti_komutu(tmp_path)


def test_komut_istisnalar_ayri_siniflar():
    assert not issubclass(BittiYok, BozukBitti)
    assert not issubclass(BozukBitti, BittiYok)
    for s in (BittiYok, BozukBitti, DurumHashHatasi):
        assert issubclass(s, Exception)


# -------------------------------------------------------------- komut_hash
@pytest.mark.parametrize("komut", [
    "",
    "echo hi",
    "python -m pytest -q -p no:cacheprovider",
    "echo çğıöşü ÇĞİÖŞÜ",
    "satir1\nsatir2\n\nçay → kahve",
    "sonda satir sonu\n",
])
def test_komut_hash_git_hash_object_ile_ayni(komut):
    r = subprocess.run(["git", "hash-object", "--stdin"], input=komut.encode("utf-8"),
                       capture_output=True, check=True)
    beklenen = r.stdout.decode().strip()
    assert komut_hash(komut) == beklenen
    assert re.fullmatch(r"[0-9a-f]{40}", komut_hash(komut))


def test_komut_hash_bos_bilinen_deger():
    assert komut_hash("") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


# ----------------------------------------------------- durum_hash_hesapla
HEAD = b"0123456789abcdef0123456789abcdef01234567"


def test_hesapla_elle_hesaplanan_deger():
    dosyalar = {b"a.txt": b"alfa\n", b"dir/b.py": b"print(1)\n"}
    h = hashlib.sha1()
    h.update(b"HEAD " + HEAD + b"\n")
    h.update(b"5:a.txt " + blob_hex(b"alfa\n").encode() + b"\n")
    h.update(b"8:dir/b.py " + blob_hex(b"print(1)\n").encode() + b"\n")
    assert durum_hash_hesapla(HEAD, dosyalar) == h.hexdigest()


def test_hesapla_bos_dosya_bilinen_deger():
    # Sabit deger: HEAD satiri + "1:a " + bos blob (e69de29...) satiri.
    assert durum_hash_hesapla(b"h" * 40, {b"a": b""}) == "2d6244598cd6b2a6cf3d0002e999093ee92da66a"


def test_hesapla_dosyasiz_yalniz_head():
    assert durum_hash_hesapla(HEAD, {}) == hashlib.sha1(b"HEAD " + HEAD + b"\n").hexdigest()


def test_hesapla_bicim_40_kucuk_hex():
    assert re.fullmatch(r"[0-9a-f]{40}", durum_hash_hesapla(HEAD, {b"x": b"y"}))


def test_hesapla_ad_bayt_siralamasi():
    # Bayt sirasi: "B" (0x42) < "a" (0x61) < "a.z" (".": 0x2e) ... ve UTF-8 "ç" (0xc3 0xa7) en sonda.
    dosyalar = {
        "ç".encode(): b"1", b"a": b"2", b"B": b"3", b"a/z": b"4", b"a.z": b"5", b"a-z": b"6",
    }
    sirali = sorted(dosyalar)
    assert sirali == [b"B", b"a", b"a-z", b"a.z", b"a/z", "ç".encode()]
    assert durum_hash_hesapla(HEAD, dosyalar) == beklenen_durum(HEAD, dosyalar)


def test_hesapla_ekleme_sirasindan_bagimsiz():
    a = {b"x": b"1", b"y": b"2", b"z": b"3"}
    b = {b"z": b"3", b"x": b"1", b"y": b"2"}
    assert durum_hash_hesapla(HEAD, a) == durum_hash_hesapla(HEAD, b)


def test_hesapla_ad_uzunlugu_bayt_cinsinden():
    # "ç" 2 bayt: onek "2:" olmali ("1:" degil).
    dosyalar = {"ç".encode(): b"x"}
    h = hashlib.sha1(b"HEAD " + HEAD + b"\n")
    h.update(b"2:" + "ç".encode() + b" " + blob_hex(b"x").encode() + b"\n")
    assert durum_hash_hesapla(HEAD, dosyalar) == h.hexdigest()


class _TekrarliHarita(Mapping):
    """Ayni adi iki kez gezen Mapping: tekrar eden ad hesaba bir kez girmeli."""

    def __init__(self, veri, sira):
        self._v, self._s = veri, sira

    def __getitem__(self, k):
        return self._v[k]

    def __iter__(self):
        return iter(self._s)

    def __len__(self):
        return len(self._v)


def test_hesapla_tekrar_eden_ad_bir_kez():
    veri = {b"a": b"1", b"b": b"2"}
    tekrarli = _TekrarliHarita(veri, [b"b", b"a", b"b", b"a", b"a"])
    assert durum_hash_hesapla(HEAD, tekrarli) == beklenen_durum(HEAD, veri)


def test_hesapla_icerik_ve_head_etkiler():
    taban = durum_hash_hesapla(HEAD, {b"a": b"1"})
    assert durum_hash_hesapla(HEAD, {b"a": b"2"}) != taban
    assert durum_hash_hesapla(b"f" * 40, {b"a": b"1"}) != taban
    assert durum_hash_hesapla(HEAD, {b"b": b"1"}) != taban


def test_hesapla_bos_dosya_ile_dosyasiz_farkli():
    assert durum_hash_hesapla(HEAD, {b"a": b""}) != durum_hash_hesapla(HEAD, {})


# -------------------------------------------------------------- durum_hash
def test_durum_hash_bicim_ve_tekrar(tmp_path):
    wt = depo_kur(tmp_path / "r")
    h = durum_hash(wt)
    assert re.fullmatch(r"[0-9a-f]{40}", h)
    assert durum_hash(wt) == h


def test_durum_hash_bagimsiz_hesapla_ile_ayni(tmp_path):
    wt = depo_kur(tmp_path / "r")
    (wt / "çay.txt").write_bytes(b"demli\n")
    (wt / "alt").mkdir()
    (wt / "alt" / "b.py").write_bytes(b"x = 1\n")
    (wt / "ignored.txt").write_bytes(b"yok sayilir\n")
    head = head_sha(wt).encode()
    beklenen = {
        b"a.txt": b"alfa\n",
        b".gitignore": b"ignored.txt\nbuild/\n",
        "çay.txt".encode(): b"demli\n",
        b"alt/b.py": b"x = 1\n",
    }
    assert durum_hash(wt) == beklenen_durum(head, beklenen)


def test_durum_hash_izlenen_dosya_degisince(tmp_path):
    wt = depo_kur(tmp_path / "r")
    h0 = durum_hash(wt)
    (wt / "a.txt").write_bytes(b"beta\n")
    h1 = durum_hash(wt)
    assert h1 != h0
    (wt / "a.txt").write_bytes(b"alfa\n")
    assert durum_hash(wt) == h0


def test_durum_hash_izlenmeyen_dosya_eklenince_ve_degisince(tmp_path):
    wt = depo_kur(tmp_path / "r")
    h0 = durum_hash(wt)
    (wt / "yeni.txt").write_bytes(b"1")
    h1 = durum_hash(wt)
    assert h1 != h0
    (wt / "yeni.txt").write_bytes(b"2")
    h2 = durum_hash(wt)
    assert h2 not in (h0, h1)


def test_durum_hash_alt_dizindeki_izlenmeyen_dosya(tmp_path):
    wt = depo_kur(tmp_path / "r")
    h0 = durum_hash(wt)
    (wt / "d" / "e").mkdir(parents=True)
    (wt / "d" / "e" / "f.txt").write_bytes(b"x")
    assert durum_hash(wt) != h0


def test_durum_hash_index_ten_bagimsiz(tmp_path):
    wt = depo_kur(tmp_path / "r")
    (wt / "yeni.txt").write_bytes(b"1")
    h0 = durum_hash(wt)
    git(wt, "add", "yeni.txt")  # izlenmeyen -> izlenen (icerik ayni)
    assert durum_hash(wt) == h0


def test_durum_hash_silinen_dosya_atlanir(tmp_path):
    wt = depo_kur(tmp_path / "r")
    h0 = durum_hash(wt)
    (wt / "a.txt").unlink()
    h1 = durum_hash(wt)  # istisna firlatmaz
    assert re.fullmatch(r"[0-9a-f]{40}", h1)
    assert h1 != h0
    head = head_sha(wt).encode()
    assert h1 == beklenen_durum(head, {b".gitignore": b"ignored.txt\nbuild/\n"})


@pytest.mark.parametrize("yol", [
    "__pycache__/m.cpython-312.pyc",
    "pkg/__pycache__/x.py",
    "kok.pyc",
    "pkg/alt/mod.pyc",
    "node_modules/m/index.js",
    "web/node_modules/m/index.js",
    ".pytest_cache/v/cache/lastfailed",
    "pkg/.pytest_cache/README.md",
])
def test_durum_hash_haric_yollar_degistirmez(tmp_path, yol):
    wt = depo_kur(tmp_path / "r")
    h0 = durum_hash(wt)
    hedef = wt / yol
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_bytes(b"bir")
    assert durum_hash(wt) == h0
    hedef.write_bytes(b"iki degisti")
    assert durum_hash(wt) == h0


def test_durum_hash_izlenen_haric_dosya_degisimi_etkilemez(tmp_path):
    wt = depo_kur(tmp_path / "r")
    (wt / "izli.pyc").write_bytes(b"1")
    commit_et(wt)
    h0 = durum_hash(wt)
    (wt / "izli.pyc").write_bytes(b"2")
    assert durum_hash(wt) == h0


def test_durum_hash_gitignore_daki_dosya_degistirmez(tmp_path):
    wt = depo_kur(tmp_path / "r")
    h0 = durum_hash(wt)
    (wt / "ignored.txt").write_bytes(b"a")
    assert durum_hash(wt) == h0
    (wt / "ignored.txt").write_bytes(b"b")
    assert durum_hash(wt) == h0
    (wt / "build").mkdir()
    (wt / "build" / "out.bin").write_bytes(b"z")
    assert durum_hash(wt) == h0


def test_durum_hash_gitignore_kendisi_degisince_degisir(tmp_path):
    wt = depo_kur(tmp_path / "r")
    h0 = durum_hash(wt)
    (wt / ".gitignore").write_bytes(b"baska\n")
    assert durum_hash(wt) != h0


def test_durum_hash_head_degisince(tmp_path):
    wt = depo_kur(tmp_path / "r")
    h0 = durum_hash(wt)
    git(wt, "commit", "-q", "--allow-empty", "-m", "bos")  # dosya ayni, HEAD farkli
    assert durum_hash(wt) != h0


def test_durum_hash_commit_sonrasi_icerik_ayni_head_farkli(tmp_path):
    wt = depo_kur(tmp_path / "r")
    (wt / "n.txt").write_bytes(b"1")
    h_kirli = durum_hash(wt)
    commit_et(wt)
    assert durum_hash(wt) != h_kirli


def test_durum_hash_git_deposu_degil(tmp_path):
    duz = tmp_path / "duz"
    duz.mkdir()
    (duz / "a.txt").write_bytes(b"x")
    with pytest.raises(DurumHashHatasi):
        durum_hash(duz)


def test_durum_hash_olmayan_dizin(tmp_path):
    with pytest.raises(DurumHashHatasi):
        durum_hash(tmp_path / "yok")


def test_durum_hash_commit_yok(tmp_path):
    bos = tmp_path / "bos"
    bos.mkdir()
    git(bos, "init", "-q")
    (bos / "a.txt").write_bytes(b"x")
    with pytest.raises(DurumHashHatasi):
        durum_hash(bos)


# --------------------------------------------------------------- bitti_alan
LOG = (
    "tarih: 2026-11-04T10:00:00+03:00\n"
    "komut_hash: abc123\n"
    "cikis: 0\n"
    "durum_hash: dd11\n"
    "\n"
    "komut| echo hi\n"
    "cikti| cikis: 7\n"
)


def test_alan_basliktan_okur():
    assert bitti_alan(LOG, "komut_hash") == "abc123"
    assert bitti_alan(LOG, "cikis") == "0"
    assert bitti_alan(LOG, "durum_hash") == "dd11"


def test_alan_degerde_bosluk_ve_iki_nokta_korunur():
    assert bitti_alan(LOG, "tarih") == "2026-11-04T10:00:00+03:00"
    assert bitti_alan("not: bir  iki: uc \n", "not") == "bir  iki: uc "


def test_alan_yoksa_None():
    assert bitti_alan(LOG, "yok_alan") is None
    assert bitti_alan("", "cikis") is None


def test_alan_govdedeki_ayni_adli_satir_okunmaz_bos_satirdan_sonra():
    log = "tarih: x\n\ncikis: 5\nkomut| c\n"
    assert bitti_alan(log, "cikis") is None


def test_alan_komut_satirindan_sonrasi_okunmaz_bos_satir_olmadan():
    log = "tarih: x\nkomut| echo\ncikis: 5\n"
    assert bitti_alan(log, "cikis") is None
    assert bitti_alan(log, "tarih") == "x"


def test_alan_komut_satiri_alan_gibi_gorunse_de_baslik_biter():
    log = "komut| cikis: 9\ncikis: 3\n"
    assert bitti_alan(log, "cikis") is None


def test_alan_ilk_eslesen_satir_kazanir():
    assert bitti_alan("cikis: 1\ncikis: 2\n", "cikis") == "1"


def test_alan_tam_ad_eslesmesi():
    log = "cikis_kodu: 4\nxcikis: 5\n cikis: 6\ncikis:7\n"
    assert bitti_alan(log, "cikis") is None
    assert bitti_alan(log, "cikis_kodu") == "4"


def test_alan_bos_deger():
    assert bitti_alan("durum_hash: \ncikis: 0\n", "durum_hash") == ""


def test_alan_komut_oneki_yalniz_satir_basinda():
    # "komut_hash: ..." "komut|" ile baslamaz; baslik bolgesini bitirmez.
    assert bitti_alan("komut_hash: k1\ncikis: 2\n", "cikis") == "2"


# ------------------------------------------- bitti_guncel / bitti_gecerli (a)
def test_guncel_durum_hash_esit(ort):
    ort.log()
    assert ort.guncel() is True
    assert ort.gecerli() is True


def test_guncel_log_yok(ort):
    assert ort.guncel() is False
    assert ort.gecerli() is False


def test_guncel_komut_degisince(ort):
    ort.log()
    (ort.is_dizini / "bitti.cmd").write_bytes(b"echo baska\n")
    assert ort.guncel() is False
    assert ort.gecerli() is False


def test_guncel_komut_hash_alani_farkli(ort):
    ort.log(komut_h="0" * 40)
    assert ort.guncel() is False


def test_guncel_komut_hash_alani_yok(ort):
    log_yaz(ort.is_dizini, None, "0", durum_hash(ort.wt), govde_komut=ort.komut)
    assert ort.guncel() is False


def test_guncel_durum_hash_alani_bos_veya_yok(ort):
    log_yaz(ort.is_dizini, ort.kh, "0", "", govde_komut=ort.komut)
    assert ort.guncel() is False
    log_yaz(ort.is_dizini, ort.kh, "0", None, govde_komut=ort.komut)
    assert ort.guncel() is False


def test_guncel_bos_durum_hash_bagla_kurtarilmaz(ort):
    log_yaz(ort.is_dizini, ort.kh, "0", "", govde_komut=ort.komut)
    ort.bag(f"{ort.kh}\t\t{head_sha(ort.wt)}")
    assert ort.guncel() is False


def test_guncel_dosya_degisince_durum_eskirse_bag_yoksa_false(ort):
    ort.log()
    (ort.wt / "a.txt").write_bytes(b"degisti\n")
    assert ort.guncel() is False
    assert ort.gecerli() is False


def test_guncel_komut_sozlesme_blogundan(tmp_path):
    is_dizini = tmp_path / "is"
    is_dizini.mkdir()
    wt = depo_kur(tmp_path / "wt")
    (is_dizini / "sozlesme.md").write_bytes(b"x\n```bitti\npytest -q\n```\n")
    log_yaz(is_dizini, blob_hex(b"pytest -q"), "0", durum_hash(wt), govde_komut="pytest -q")
    assert bitti_guncel(is_dizini, wt) is True
    assert bitti_gecerli(is_dizini, wt) is True


def test_guncel_komut_tanimsiz_veya_bozuk(ort, tmp_path):
    ort.log()
    (ort.is_dizini / "bitti.cmd").unlink()
    assert ort.guncel() is False  # BittiYok
    (ort.is_dizini / "bitti.cmd").write_bytes(b"  \n")
    assert ort.guncel() is False  # BozukBitti
    (ort.is_dizini / "bitti.cmd").unlink()
    (ort.is_dizini / "sozlesme.md").write_bytes(b"```bitti\nkapanmadi\n")
    assert ort.guncel() is False


# ------------------------------------------- bitti_guncel / bitti_gecerli (b)
def _eski_log_sonra_commit(ort):
    """bitti.log D1 ile yazilir; sonra degisiklik commitlenir (HEAD S2, agac temiz). D1 artik eski."""
    d1 = ort.log()
    (ort.wt / "a.txt").write_bytes(b"commitlenen degisim\n")
    commit_et(ort.wt)
    s2 = head_sha(ort.wt)
    assert durum_hash(ort.wt) != d1
    return d1, s2


def test_bag_son_satir_eslesir_agac_temiz(ort):
    d1, s2 = _eski_log_sonra_commit(ort)
    assert ort.guncel() is False  # bag yok
    ort.bag(f"{ort.kh}\t{d1}\t{s2}")
    assert ort.guncel() is True
    assert ort.gecerli() is True


def test_bag_agac_kirli_izlenen_degisiklik(ort):
    d1, s2 = _eski_log_sonra_commit(ort)
    ort.bag(f"{ort.kh}\t{d1}\t{s2}")
    (ort.wt / "a.txt").write_bytes(b"kirli\n")
    assert ort.guncel() is False
    assert ort.gecerli() is False


def test_bag_agac_kirli_izlenmeyen_dosya(ort):
    d1, s2 = _eski_log_sonra_commit(ort)
    ort.bag(f"{ort.kh}\t{d1}\t{s2}")
    (ort.wt / "yeni.txt").write_bytes(b"x")
    assert ort.guncel() is False


def test_bag_haric_dosyalar_agaci_kirletmez(ort):
    d1, s2 = _eski_log_sonra_commit(ort)
    ort.bag(f"{ort.kh}\t{d1}\t{s2}")
    (ort.wt / "pkg" / "__pycache__").mkdir(parents=True)
    (ort.wt / "pkg" / "__pycache__" / "m.pyc").write_bytes(b"x")
    (ort.wt / "mod.pyc").write_bytes(b"x")
    (ort.wt / "node_modules").mkdir()
    (ort.wt / "node_modules" / "i.js").write_bytes(b"x")
    (ort.wt / ".pytest_cache").mkdir()
    (ort.wt / ".pytest_cache" / "v").write_bytes(b"x")
    assert ort.guncel() is True


def test_bag_sha_head_ten_farkli(ort):
    d1, _s2 = _eski_log_sonra_commit(ort)
    ort.bag("{}\t{}\t{}".format(ort.kh, d1, "1" * 40))
    assert ort.guncel() is False


def test_bag_sha_onceki_commit(ort):
    d1, _s2 = _eski_log_sonra_commit(ort)
    s1 = git(ort.wt, "rev-parse", "HEAD~1")
    ort.bag(f"{ort.kh}\t{d1}\t{s1}")
    assert ort.guncel() is False


def test_bag_komut_hash_farkli(ort):
    d1, s2 = _eski_log_sonra_commit(ort)
    ort.bag("{}\t{}\t{}".format("2" * 40, d1, s2))
    assert ort.guncel() is False


def test_bag_durum_hash_farkli(ort):
    _d1, s2 = _eski_log_sonra_commit(ort)
    ort.bag("{}\t{}\t{}".format(ort.kh, "3" * 40, s2))
    assert ort.guncel() is False


def test_bag_eslesen_satir_son_degil_onceki(ort):
    d1, s2 = _eski_log_sonra_commit(ort)
    ort.bag(f"{ort.kh}\t{d1}\t{s2}",
            "{}\t{}\t{}".format("4" * 40, "5" * 40, "6" * 40))
    assert ort.guncel() is False
    assert ort.gecerli() is False


def test_bag_son_satir_eslesir_oncekiler_onemsiz(ort):
    d1, s2 = _eski_log_sonra_commit(ort)
    ort.bag("{}\t{}\t{}".format("4" * 40, "5" * 40, "6" * 40),
            f"{ort.kh}\t{d1}\t{s2}")
    assert ort.guncel() is True


def test_bag_komut_degisti_bag_eski_komutla_eslesse_de_false(ort):
    d1, s2 = _eski_log_sonra_commit(ort)
    ort.bag(f"{ort.kh}\t{d1}\t{s2}")
    (ort.is_dizini / "bitti.cmd").write_bytes(b"echo baska\n")
    assert ort.guncel() is False


def test_bag_bos_veya_eksik_alanli(ort):
    d1, s2 = _eski_log_sonra_commit(ort)
    (ort.is_dizini / "bitti-bag").write_bytes(b"")
    assert ort.guncel() is False
    ort.bag(f"{ort.kh}\t{d1}")  # sha alani yok
    assert ort.guncel() is False
    ort.bag(f"{ort.kh} {d1} {s2}")  # sekme yerine bosluk
    assert ort.guncel() is False


def test_bag_gerek_yok_durum_esitse_bag_bozuk_olsa_da_true(ort):
    ort.log()
    ort.bag("cop")
    assert ort.guncel() is True


# --------------------------------------------------------- bitti_gecerli
def test_gecerli_cikis_sifir_degil_guncel_true_gecerli_false(ort):
    ort.log(cikis="1")
    assert ort.guncel() is True
    assert ort.gecerli() is False


def test_gecerli_cikis_alani_yok(ort):
    log_yaz(ort.is_dizini, ort.kh, None, durum_hash(ort.wt), govde_komut=ort.komut)
    assert ort.guncel() is True
    assert ort.gecerli() is False


@pytest.mark.parametrize("cikis", ["125", "2", "00", "", "sifir"])
def test_gecerli_yalniz_tam_0(ort, cikis):
    ort.log(cikis=cikis)
    assert ort.guncel() is True
    assert ort.gecerli() is False


def test_gecerli_bag_yolu_cikis_sifir_degil(ort):
    d1 = ort.log(cikis="1")
    (ort.wt / "a.txt").write_bytes(b"yeni\n")
    commit_et(ort.wt)
    ort.bag(f"{ort.kh}\t{d1}\t{head_sha(ort.wt)}")
    assert ort.guncel() is True
    assert ort.gecerli() is False


def test_gecerli_govdedeki_cikis_satiri_sayilmaz(ort):
    ort.log(cikis="1")
    metin = (ort.is_dizini / "bitti.log").read_bytes().decode()
    (ort.is_dizini / "bitti.log").write_bytes((metin + "cikis: 0\n").encode())
    assert ort.gecerli() is False


def test_gecerli_guncel_degilse_false(ort):
    ort.log(cikis="0")
    (ort.wt / "a.txt").write_bytes(b"degisti\n")
    assert ort.gecerli() is False


# ---------------------------------------------------- istisna sizmaz
def test_istisna_is_dizini_yok(tmp_path):
    wt = depo_kur(tmp_path / "wt")
    assert bitti_guncel(tmp_path / "yok", wt) is False
    assert bitti_gecerli(tmp_path / "yok", wt) is False


def test_istisna_worktree_git_deposu_degil(ort, tmp_path):
    ort.log()
    duz = tmp_path / "duz"
    duz.mkdir()
    assert bitti_guncel(ort.is_dizini, duz) is False
    assert bitti_gecerli(ort.is_dizini, duz) is False


def test_istisna_worktree_yok(ort, tmp_path):
    ort.log()
    assert bitti_guncel(ort.is_dizini, tmp_path / "yok") is False
    assert bitti_gecerli(ort.is_dizini, tmp_path / "yok") is False


def test_istisna_worktree_commitsiz_depo(ort, tmp_path):
    ort.log()
    bos = tmp_path / "bos"
    bos.mkdir()
    git(bos, "init", "-q")
    assert bitti_guncel(ort.is_dizini, bos) is False
    assert bitti_gecerli(ort.is_dizini, bos) is False


def test_istisna_bag_dosyasi_ikili_cop(ort):
    _d1, _s2 = _eski_log_sonra_commit(ort)
    (ort.is_dizini / "bitti-bag").write_bytes(b"\xff\xfe\x00\x01\xc3\x28\n")
    assert ort.guncel() is False
    assert ort.gecerli() is False


def test_istisna_log_ikili_cop(ort):
    (ort.is_dizini / "bitti.log").write_bytes(b"\xff\xfe\x00\xc3\x28\n\x80\n")
    assert ort.guncel() is False
    assert ort.gecerli() is False


def test_istisna_log_bos_dosya(ort):
    (ort.is_dizini / "bitti.log").write_bytes(b"")
    assert ort.guncel() is False
    assert ort.gecerli() is False


def test_istisna_bag_dizin_olarak(ort):
    _d1, _s2 = _eski_log_sonra_commit(ort)
    (ort.is_dizini / "bitti-bag").mkdir()
    assert ort.guncel() is False


def test_istisna_bitti_cmd_dizin_olarak(ort):
    ort.log()
    (ort.is_dizini / "bitti.cmd").unlink()
    (ort.is_dizini / "bitti.cmd").mkdir()
    assert ort.guncel() in (False,)
    assert ort.gecerli() in (False,)


# ---------------------------------------------------- yalniz standart kutuphane
def test_bitti_py_yalniz_standart_kutuphane():
    kaynak = Path(__file__).resolve().parent.parent / "src" / "nobet" / "bitti.py"
    agac = ast.parse(kaynak.read_text(encoding="utf-8"))
    izinli = set(sys.stdlib_module_names)
    bulunan = []
    for dugum in ast.walk(agac):
        if isinstance(dugum, ast.Import):
            bulunan += [(a.name.split(".")[0], 0) for a in dugum.names]
        elif isinstance(dugum, ast.ImportFrom):
            bulunan.append(((dugum.module or "").split(".")[0], dugum.level))
    assert bulunan, "bitti.py hicbir sey import etmiyor (subprocess/hashlib bekleniyor)"
    for ad, seviye in bulunan:
        assert seviye == 0, f"goreli import: {ad!r}"
        assert ad in izinli, f"standart kutuphane disi import: {ad!r}"


def test_durum_hash_info_exclude_ta_gizlenen_dosya_degistirir(tmp_path):
    wt = depo_kur(tmp_path / "r")
    h0 = durum_hash(wt)
    (wt / "gizli.py").write_bytes(b"x")
    (wt / ".git" / "info").mkdir(exist_ok=True)
    (wt / ".git" / "info" / "exclude").write_bytes(b"gizli.py\n")
    assert durum_hash(wt) != h0
    h1 = durum_hash(wt)
    (wt / "gizli.py").write_bytes(b"y")
    assert durum_hash(wt) != h1


def test_durum_hash_excludes_file_ta_gizlenen_dosya_degistirir(tmp_path):
    wt = depo_kur(tmp_path / "r")
    h0 = durum_hash(wt)
    genel = tmp_path / "genel-ignore"
    genel.write_bytes(b"gizli.py\n")
    git(wt, "config", "core.excludesFile", str(genel))
    (wt / "gizli.py").write_bytes(b"x")
    assert durum_hash(wt) != h0


@pytest.mark.skipif(sys.platform == "win32", reason="fsmonitor betiği sh ile yazıldı")
def test_durum_hash_fsmonitor_komutu_calistirmaz(tmp_path):
    wt = depo_kur(tmp_path / "r")
    iz = tmp_path / "fsm-calisti"
    betik = tmp_path / "fsm.sh"
    betik.write_text(f"#!/bin/sh\ntouch '{iz}'\nexit 0\n")
    betik.chmod(0o755)
    git(wt, "config", "core.fsmonitor", str(betik))
    durum_hash(wt)
    assert not iz.exists()
