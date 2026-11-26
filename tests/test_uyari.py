"""Uyarı katmanı kabul testi: ikili dosyada e-posta kuralı ve açık paylaşım bağlantısı uyarısı.

Değerler parçalı yazılır ve sentetiktir: tarama bu dosyayı yakalamasın.
"""

import json
import subprocess

import pytest

from nobet import gecmis, tara

UYARI_EPOSTA = "e-posta (ikili, doğrulanmalı)"
UYARI_BAGLANTI = "açık paylaşım bağlantısı"

UZUN = "kisi" + "@" + "posta-saglayici.com"          # yerel >= 3, alan adı >= 2
KISA_YEREL = "ab" + "@" + "posta-saglayici.com"      # yerel < 3
KISA_ALAN = "kisi" + "@" + "c.com"                   # alan adı metni 1 karakter
IKI_ALAN = ["kisi" + "@" + "me.com", "123456" + "@" + "qq.com"]  # 3+ yerel, 2 karakterlik alan adı
BITISIK = {
    "rakamlar": UZUN + "5551234",
    "tire-x": UZUN + "-x",
    "tarih": UZUN + "2024-01-01",
    "cok-etiket-rakam": "kisi" + "@" + "posta.sirket-x.com1",
    "26-buyuk-harf": UZUN + "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
}
NOREPLY = "1+kisi" + "@" + "users.noreply.github.com"
IZINLI = "kisi" + "@" + "example.com"
KIMLIK = "SENTETIK" + "Kimlik123456"

GDRIVE = "drive.google" + ".com"
GDOCS = "docs.google" + ".com"
DROPBOX = "dropbox" + ".com"
DROPBOX_DL = "dl.dropboxusercontent" + ".com"

BAGLANTILAR = {
    "drive-uc": "https://" + GDRIVE + "/uc?export=download&id=" + KIMLIK,
    "drive-uc-semasiz": GDRIVE + "/uc?id=" + KIMLIK,
    "drive-open": "https://" + GDRIVE + "/open?id=" + KIMLIK,
    "drive-dosya": "https://" + GDRIVE + "/file/d/" + KIMLIK + "/view",
    "drive-klasor": "https://" + GDRIVE + "/drive/folders/" + KIMLIK,
    "docs-document": "https://" + GDOCS + "/document/d/" + KIMLIK + "/edit",
    "docs-spreadsheets": "https://" + GDOCS + "/spreadsheets/d/" + KIMLIK + "/edit",
    "dropbox-s": "https://www." + DROPBOX + "/s/" + KIMLIK + "/not.pdf",
    "dropbox-sh": "https://www." + DROPBOX + "/sh/" + KIMLIK + "/not",
    "dropbox-scl": "https://www." + DROPBOX + "/scl/fi/" + KIMLIK + "/not.pdf",
    "dropbox-dl": "https://" + DROPBOX_DL + "/" + KIMLIK + "/not.pdf",
    "dropbox-semasiz": DROPBOX + "/s/" + KIMLIK + "/not.pdf",
    "imzali-amz": "https://depo.example.net/nesne?X-Amz-" + "Signature=" + KIMLIK,
    "imzali-aws": ("https://depo.example.net/nesne?AWSAccess" + "KeyId=" + KIMLIK
                   + "&Expires=1&Signa" + "ture=" + KIMLIK),
}
BAGLANTI_ID = sorted(BAGLANTILAR)


def g(repo, *args, eposta=NOREPLY):
    ortam = ["-c", "user.name=t", "-c", f"user.email={eposta}",
             "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
    komut = ["git", "-C", str(repo), *ortam, *args]
    if args[0] == "commit":
        komut.append(f"--author=t <{eposta}>")
    return subprocess.run(komut, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    return r


@pytest.fixture(autouse=True)
def gitleaks_yok(monkeypatch):
    monkeypatch.setenv("GITLEAKS", "gitleaks-olmayan-arac")


def yaz_ham(repo, ad, ham):
    (repo / ad).write_bytes(ham)


def commitle(repo, *adlar):
    g(repo, "add", *adlar)
    g(repo, "commit", "-q", "-m", "c")


def ikili(icerik):
    """İlk 8000 baytta \\0 taşıyan ham içerik."""
    return b"\0\0" + icerik + b"\0"


def agac(repo):
    return {(b.yer, b.tur) for b in tara.agac_tara(repo, [])[0]}


def gecmis_turleri(repo):
    return {(b.yer, b.tur) for b in gecmis.tara(repo, [])[0]}


def metin(deger, ikili_mi):
    return {(b.yer, b.tur) for b in gecmis.metin_bulgulari("y", deger, [], ikili=ikili_mi)}


def hem_agac_hem_gecmis(repo, ad, ham):
    """Aynı içerik: çalışma ağacında (commit'siz) ve git geçmişinde aynı sonucu vermeli."""
    yaz_ham(repo, ad, ham)
    a = agac(repo)
    commitle(repo, ad)
    return a, gecmis_turleri(repo)


# ---------- 1. sabit ve ayir ----------

def test_uyari_turleri_degeri():
    assert gecmis.UYARI_TURLERI == frozenset({UYARI_EPOSTA, UYARI_BAGLANTI})


def test_ayir_kesin_ve_uyariyi_ayirir_sirayi_korur():
    bulgular = sorted([
        gecmis.Bulgu("dosya a", "e-posta"),
        gecmis.Bulgu("dosya b", UYARI_EPOSTA),
        gecmis.Bulgu("dosya c", "ad"),
        gecmis.Bulgu("dosya d", UYARI_BAGLANTI),
        gecmis.Bulgu("dosya e", "TC kimlik no"),
        gecmis.Bulgu("commit 1", "yazar e-postası"),
    ])
    kesin, uyari = gecmis.ayir(bulgular)
    assert isinstance(kesin, list) and isinstance(uyari, list)
    assert kesin == [b for b in bulgular if b.tur not in gecmis.UYARI_TURLERI]
    assert uyari == [b for b in bulgular if b.tur in gecmis.UYARI_TURLERI]
    assert {b.tur for b in uyari} == {UYARI_EPOSTA, UYARI_BAGLANTI}
    assert len(kesin) == 4


def test_ayir_sirasiz_girdiyi_kendisi_siralar():
    bulgular = [
        gecmis.Bulgu("dosya z", UYARI_BAGLANTI),
        gecmis.Bulgu("dosya y", "ad"),
        gecmis.Bulgu("dosya b", UYARI_EPOSTA),
        gecmis.Bulgu("dosya x", "e-posta"),
        gecmis.Bulgu("dosya a", "e-posta"),
        gecmis.Bulgu("dosya c", UYARI_BAGLANTI),
    ]
    kesin, uyari = gecmis.ayir(bulgular)
    assert kesin == sorted(b for b in bulgular if b.tur not in gecmis.UYARI_TURLERI)
    assert uyari == sorted(b for b in bulgular if b.tur in gecmis.UYARI_TURLERI)
    assert len(kesin) == 3 and len(uyari) == 3


def test_ayir_bos_ve_tek_tur():
    assert gecmis.ayir([]) == ([], [])
    yalniz_kesin = [gecmis.Bulgu("x", "ad")]
    assert gecmis.ayir(yalniz_kesin) == (yalniz_kesin, [])
    yalniz_uyari = [gecmis.Bulgu("x", UYARI_BAGLANTI)]
    assert gecmis.ayir(yalniz_uyari) == ([], yalniz_uyari)


# ---------- 2. Kural 1: ikili içerikte e-posta ----------

@pytest.mark.parametrize("ham", [
    "abc" + "@" + "xyz.I.N",          # tek harfli son etiket
    "abc" + "@" + "def.p..",          # harf olmayan / boş son etiket
    "a" + "@" + "b.c",                # tek harfli TLD
    "x" + "@" + "y.9z",               # rakamlı TLD
    "abc" + "@" + "def.123",          # tümü rakam TLD
    "abc" + "@" + "caf\xe9.com",      # ASCII olmayan harfli "adres"
], ids=["tek-harf-etiket", "p-nokta-nokta", "a-b-c", "rakamli-9z", "rakam-tld", "ascii-disi"])
def test_rastgele_bayt_kalibi_bulgu_vermez(ham):
    assert metin("\0\1 " + ham + " \2\0", True) == set()


def test_uzun_adres_kesin_eposta():
    assert metin("\0 " + UZUN + " \0", True) == {("y", "e-posta")}


@pytest.mark.parametrize("adres", [KISA_YEREL, KISA_ALAN], ids=["kisa-yerel", "kisa-alan"])
def test_kisa_ama_gecerli_adres_uyari(adres):
    assert metin("\0 " + adres + " \0", True) == {("y", UYARI_EPOSTA)}


@pytest.mark.parametrize("adres", IKI_ALAN, ids=["me", "qq"])
def test_iki_karakterlik_alan_adi_kesin(adres):
    assert metin("\0 " + adres + " \0", True) == {("y", "e-posta")}


@pytest.mark.parametrize("ad", sorted(BITISIK))
def test_adresin_ardindan_gelen_karakter_eslesmeyi_engellemez(ad):
    assert metin("\0\xe9 " + BITISIK[ad] + " \0", True) == {("y", "e-posta")}
    assert metin("\0" + BITISIK[ad] + "\0", True) == {("y", "e-posta")}


@pytest.mark.parametrize("ad", ["rakamlar", "26-buyuk-harf"])
def test_bitisik_adres_dosyada_agac_ve_gecmis_kesin(repo, ad):
    a, h = hem_agac_hem_gecmis(repo, "m.bin", ikili(b"\xe9" + BITISIK[ad].encode() + b"\xff"))
    assert a == h == {("dosya m.bin", "e-posta")}


def test_ascii_disi_bayt_adresin_yaninda_adresi_gizlemez():
    for adres, tur in [(UZUN, "e-posta"), (KISA_YEREL, UYARI_EPOSTA)]:
        for yan in ["\xe9", "\xff", "\xe9\xff\x80"]:
            assert metin("\0" + yan + adres + yan + "\0", True) == {("y", tur)}


@pytest.mark.parametrize("adres", [IZINLI, NOREPLY, "noreply" + "@" + "github.com"],
                         ids=["example", "users-noreply", "noreply"])
def test_izinli_adres_ikilide_de_bulgu_degil(adres):
    assert metin("\0\xe9 " + adres + " \xff\0", True) == set()


def test_metin_dosyasinda_kisa_adres_eskisi_gibi_kesin():
    for adres in [KISA_YEREL, KISA_ALAN, UZUN]:
        assert metin("iletisim: " + adres + "\n", False) == {("y", "e-posta")}


def test_ikili_dosya_agac_ve_gecmis_uzun_adres_kesin(repo):
    a, h = hem_agac_hem_gecmis(repo, "m.bin", ikili(b"\xe9" + UZUN.encode() + b"\xff"))
    assert a == h == {("dosya m.bin", "e-posta")}


def test_ikili_dosya_agac_ve_gecmis_kisa_adres_uyari(repo):
    a, h = hem_agac_hem_gecmis(repo, "m.bin", ikili(b"\xe9" + KISA_YEREL.encode() + b"\xff"))
    assert a == h == {("dosya m.bin", UYARI_EPOSTA)}


def test_ikili_dosya_agac_ve_gecmis_rastgele_bayt_temiz(repo):
    et = b"@"  # parcali: agac taramasi bu test dosyasini yakalamasin
    ham = ikili(b"abc" + et + b"xyz.I.N \xe9 a" + et + b"b.c x" + et + b"y.9z abc" + et + b"caf\xe9.com")
    a, h = hem_agac_hem_gecmis(repo, "m.bin", ham)
    assert a == h == set()


def test_ikili_dosya_agac_ve_gecmis_izinli_adres_temiz(repo):
    a, h = hem_agac_hem_gecmis(repo, "m.bin", ikili(NOREPLY.encode() + b" " + IZINLI.encode()))
    assert a == h == set()


def test_metin_dosyasi_kisa_adres_agac_ve_gecmis_kesin(repo):
    a, h = hem_agac_hem_gecmis(repo, "n.md", ("iletisim: " + KISA_YEREL + "\n").encode())
    assert a == h == {("dosya n.md", "e-posta")}


# ---------- 3. Kural 2: açık paylaşım bağlantısı ----------

@pytest.mark.parametrize("ad", BAGLANTI_ID)
def test_baglanti_bicimi_uyari_uretir(ad):
    assert metin("bak: " + BAGLANTILAR[ad] + " bitti\n", False) == {("y", UYARI_BAGLANTI)}


@pytest.mark.parametrize("ad", BAGLANTI_ID)
def test_baglanti_buyuk_kucuk_harf_duyarsiz(ad):
    assert metin("bak: " + BAGLANTILAR[ad].upper() + "\n", False) == {("y", UYARI_BAGLANTI)}
    assert metin("bak: " + BAGLANTILAR[ad].lower() + "\n", False) == {("y", UYARI_BAGLANTI)}


@pytest.mark.parametrize("ad", BAGLANTI_ID)
def test_baglanti_ikili_icerikte_aranmaz(ad):
    assert metin("\0 " + BAGLANTILAR[ad] + " \0", True) == set()


@pytest.mark.parametrize("yalin", [
    GDRIVE, "https://" + GDRIVE, GDOCS, DROPBOX, "https://www." + DROPBOX,
    "https://" + DROPBOX_DL,
], ids=["drive", "drive-https", "docs", "dropbox", "dropbox-www", "dropbox-dl"])
def test_yalin_alan_adi_uyari_uretmez(yalin):
    assert metin("site: " + yalin + " adresinde\n", False) == set()


def test_baglanti_dosyada_agac_ve_gecmis(repo):
    satir = "kaynak: " + BAGLANTILAR["drive-dosya"] + "\n"
    a, h = hem_agac_hem_gecmis(repo, "n.md", satir.encode("utf-8"))
    assert a == h == {("dosya n.md", UYARI_BAGLANTI)}


def test_baglanti_ikili_dosyada_agac_ve_gecmis_aranmaz(repo):
    a, h = hem_agac_hem_gecmis(repo, "m.bin", ikili(BAGLANTILAR["dropbox-s"].encode()))
    assert a == h == set()


def test_baglanti_ve_kesin_ayni_dosyada_ikisi_de_raporlanir(repo):
    satir = "k: " + BAGLANTILAR["drive-open"] + " " + UZUN + "\n"
    a, h = hem_agac_hem_gecmis(repo, "n.md", satir.encode("utf-8"))
    assert a == h == {("dosya n.md", "e-posta"), ("dosya n.md", UYARI_BAGLANTI)}


def test_tara_donus_bicimi_ve_sira(repo):
    yaz_ham(repo, "a.md", ("k: " + BAGLANTILAR["dropbox-sh"] + "\n").encode("utf-8"))
    yaz_ham(repo, "b.md", (UZUN + "\n").encode("utf-8"))
    bulgular, atlanan = tara.agac_tara(repo, [])
    assert atlanan == []
    assert bulgular == sorted(bulgular)
    assert {b.tur for b in bulgular} == {"e-posta", UYARI_BAGLANTI}
    commitle(repo, "a.md", "b.md")
    bulgular, atlanan = gecmis.tara(repo, [])
    assert atlanan == []
    assert bulgular == sorted(bulgular)
    assert {b.tur for b in bulgular} == {"e-posta", UYARI_BAGLANTI}


# ---------- 4. CLI ----------

def tara_cli(repo, *ek):
    return tara.main(["--repo", str(repo), *ek])


def gecmis_cli(repo, *ek):
    return gecmis.main(["--repo", str(repo), *ek])


def cli_hazirla(repo, kesin=False, uyari=False):
    """Çalışma ağacı ve geçmişte aynı içerik: kesin (e-posta) ve/veya uyarı (ikili kısa adres)."""
    if kesin:
        yaz_ham(repo, "n.md", (UZUN + "\n").encode("utf-8"))
        commitle(repo, "n.md")
    if uyari:
        yaz_ham(repo, "m.bin", ikili(b"\xe9" + KISA_YEREL.encode() + b"\xff"))
        commitle(repo, "m.bin")
    if not (kesin or uyari):
        yaz_ham(repo, "t.md", b"merhaba\n")
        commitle(repo, "t.md")


@pytest.fixture(params=["tara", "gecmis"])
def cli(request):
    return tara_cli if request.param == "tara" else gecmis_cli


def json_cikti(capsys):
    cikti = capsys.readouterr()
    return json.loads(cikti.out), cikti


def test_yalniz_uyari_cikis_0(repo, cli, capsys):
    cli_hazirla(repo, uyari=True)
    assert cli(repo) == 0
    assert cli(repo, "--json") == 0


def test_yalniz_uyari_json(repo, cli, capsys):
    cli_hazirla(repo, uyari=True)
    assert cli(repo, "--json") == 0
    veri, _ = json_cikti(capsys)
    assert veri["bulgular"] == []
    assert veri["uyarilar"] == [{"yer": "dosya m.bin", "tur": UYARI_EPOSTA}]
    assert "atlanan" in veri and "ad_taramasi" in veri


def test_yalniz_baglanti_uyarisi_json(repo, cli, capsys):
    yaz_ham(repo, "n.md", ("k: " + BAGLANTILAR["docs-document"] + "\n").encode("utf-8"))
    commitle(repo, "n.md")
    assert cli(repo, "--json") == 0
    veri, _ = json_cikti(capsys)
    assert veri["bulgular"] == []
    assert veri["uyarilar"] == [{"yer": "dosya n.md", "tur": UYARI_BAGLANTI}]


def test_uyari_yokken_uyarilar_bos_liste(repo, cli, capsys):
    cli_hazirla(repo)
    assert cli(repo, "--json") == 0
    veri, _ = json_cikti(capsys)
    assert veri["uyarilar"] == []
    assert veri["bulgular"] == []


def test_yalniz_kesin_varken_uyarilar_bos(repo, cli, capsys):
    cli_hazirla(repo, kesin=True)
    assert cli(repo, "--json") == 1
    veri, _ = json_cikti(capsys)
    assert veri["bulgular"] == [{"yer": "dosya n.md", "tur": "e-posta"}]
    assert veri["uyarilar"] == []


def test_kesin_ve_uyari_birlikte_cikis_1_ayri_listeler(repo, cli, capsys):
    cli_hazirla(repo, kesin=True, uyari=True)
    assert cli(repo, "--json") == 1
    veri, _ = json_cikti(capsys)
    assert veri["bulgular"] == [{"yer": "dosya n.md", "tur": "e-posta"}]
    assert veri["uyarilar"] == [{"yer": "dosya m.bin", "tur": UYARI_EPOSTA}]


def test_duz_cikti_uyari_satiri_ve_sayac_yalniz_kesin(repo, cli, capsys):
    cli_hazirla(repo, uyari=True)
    assert cli(repo) == 0
    satirlar = capsys.readouterr().out.splitlines()
    assert f"uyarı: {UYARI_EPOSTA}: dosya m.bin" in satirlar
    assert satirlar[-1] == "0 bulgu"


def test_duz_cikti_kesin_ve_uyari_birlikte(repo, cli, capsys):
    cli_hazirla(repo, kesin=True, uyari=True)
    assert cli(repo) == 1
    satirlar = capsys.readouterr().out.splitlines()
    assert f"uyarı: {UYARI_EPOSTA}: dosya m.bin" in satirlar
    assert "e-posta: dosya n.md" in satirlar
    assert satirlar[-1] == "1 bulgu"


def test_duz_cikti_baglanti_uyarisi(repo, cli, capsys):
    yaz_ham(repo, "n.md", ("k: " + BAGLANTILAR["imzali-amz"] + "\n").encode("utf-8"))
    commitle(repo, "n.md")
    assert cli(repo) == 0
    satirlar = capsys.readouterr().out.splitlines()
    assert f"uyarı: {UYARI_BAGLANTI}: dosya n.md" in satirlar
    assert satirlar[-1] == "0 bulgu"


@pytest.mark.parametrize("bicim", [[], ["--json"]], ids=["duz", "json"])
def test_cikti_degeri_yazmaz(repo, cli, capsys, bicim):
    yaz_ham(repo, "m.bin", ikili(b"\xe9" + KISA_YEREL.encode() + b"\xff"))
    yaz_ham(repo, "n.md", (UZUN + " " + BAGLANTILAR["drive-uc"] + " "
                           + BAGLANTILAR["dropbox-scl"] + "\n").encode("utf-8"))
    commitle(repo, "m.bin", "n.md")
    assert cli(repo, *bicim) == 1
    cikti = capsys.readouterr()
    tum = cikti.out + cikti.err
    for deger in [KISA_YEREL, UZUN, KIMLIK, "ab" + "@", GDRIVE + "/uc", DROPBOX + "/scl"]:
        assert deger not in tum
