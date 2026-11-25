"""nobet-haber: zarf şeması, dosya posta kutusu, ayar.toml'dan yönlendirme, sahte sağlayıcı komutuyla adaptör.

Model çağrısı yok: sağlayıcı komutu tmp_path'teki küçük bir Python betiğidir.
"""
import io
import json
import os
import re
import shlex
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from nobet import akis, ayar, haber

SAHTE = r'''
import argparse, json, os, pathlib, sys
a = argparse.ArgumentParser()
for ad in ("--rol", "--model", "--istem", "--cikti"):
    a.add_argument(ad)
a = a.parse_args()
istem = pathlib.Path(a.istem).read_text(encoding="utf-8") if a.istem else sys.stdin.read()
if os.environ.get("SAHTE_IZ"):
    with open(os.environ["SAHTE_IZ"], "a", encoding="utf-8") as f:
        f.write(f"{a.rol} {a.model}\n")
if os.environ.get("SAHTE_ORTAM"):
    pathlib.Path(os.environ["SAHTE_ORTAM"]).write_text(json.dumps(dict(os.environ)), encoding="utf-8")
if a.model in os.environ.get("SAHTE_KOTA", "").split(","):
    print("hata: rate limit exceeded, sonra dene")
    sys.exit(3)
mod = os.environ.get("SAHTE_MOD", "")
if mod == "agac":
    (pathlib.Path.cwd() / "src" / "a.py").write_text("reviewer yazdi\n")
if mod == "serit-boz":
    (pathlib.Path(os.environ["SAHTE_SERIT"]) / "sahiplik").write_text("**\n")
if mod == "hata":
    print("bozuldu")
    sys.exit(5)
govde = istem.split("----- mesaj -----")[1].split("----- mesaj sonu -----")[0].strip()
cevap = f"cevap {a.model} {a.rol}\nmesaj: {govde}"
if mod == "sir":
    cevap += "\nanahtar: sk-" + "A1b2C3d4" * 4
if mod == "ansi":
    cevap += "\n\x1b[31mkirmizi\x1b[0m\x07"
if mod == "konu":
    cevap += "\nrate limit kodunu inceledim"
print("gunluk satiri " + ("sk-" + "Z9y8X7w6" * 4 if mod == "sir" else ""))
if a.cikti:
    pathlib.Path(a.cikti).write_text(cevap, encoding="utf-8")
else:
    print(cevap)
'''

GUVENLI_AD = re.compile(r"[A-Za-z0-9._-]+")


@pytest.fixture
def ortam(tmp_path, monkeypatch):
    """Üç cli sağlayıcı: sag-a (yazar + inceler), sag-b ve sag-c (yalnız reviewer). Posta tmp altında."""
    for ad in ("SAHTE_MOD", "SAHTE_KOTA", "SAHTE_IZ", "SAHTE_ORTAM", "SAHTE_SERIT"):
        monkeypatch.delenv(ad, raising=False)
    monkeypatch.setenv("NOBET_HABER_DIZIN", str(tmp_path / "posta"))
    sahte = tmp_path / "sahte.py"
    sahte.write_text(SAHTE, encoding="utf-8")
    py = shlex.quote(sys.executable) + " " + shlex.quote(str(sahte))
    dosya_ile = json.dumps(py + " --rol {rol} --model {model} --istem {istem} --cikti {cikti}")
    stdin_ile = json.dumps(py + " --rol {rol} --model {model}")
    ayar_f = tmp_path / "ayar.toml"
    ayar_f.write_text(
        f'[[saglayici]]\nad = "sag-a"\ntur = "cli"\nkomut = {dosya_ile}\nmodeller = ["a-yazar", "a-inceler"]\n\n'
        f'[[saglayici]]\nad = "sag-b"\ntur = "cli"\nkomut = {stdin_ile}\nmodeller = ["b-inceler"]\n'
        'roller = ["reviewer"]\n\n'
        f'[[saglayici]]\nad = "sag-c"\ntur = "cli"\nkomut = {dosya_ile}\nmodeller = ["c-inceler"]\n'
        'roller = ["reviewer"]\n',
        encoding="utf-8")
    monkeypatch.setenv("NOBET_AYAR", str(ayar_f))
    calisma = tmp_path / "calisma"
    calisma.mkdir()
    return tmp_path, ayar_f, calisma


def taslak(**kw):
    z = {"is_id": "is-1", "tur": "gorev", "gonderen": {"profil": "yonetici", "rol": "yonetici"},
         "alici": {"profil": None, "rol": "yazici"}, "govde": {"metin": "merhaba"}}
    z.update(kw)
    return z


def tam(**kw):
    return haber.taslak_tamamla(taslak(**kw))


def sag():
    return ayar.saglayicilar()


def cli(capsys, *argv, stdin=None, monkeypatch=None):
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8"))
    kod = haber.main(["--json", *argv])
    cikti = capsys.readouterr()
    satirlar = [s for s in cikti.out.splitlines() if s.strip()]
    return kod, (json.loads(satirlar[-1]) if satirlar else None), cikti.err


def gonder_dosya(tmp_path, zarf, ad="zarf.json"):
    f = tmp_path / ad
    f.write_text(json.dumps(zarf, ensure_ascii=False), encoding="utf-8")
    return str(f)


# --- şema -----------------------------------------------------------------------------------

def test_gecerli_zarf_ve_sema_ayni_alanlar():
    z = haber.olustur(is_id="is-1", tur="soru", gonderen={"profil": "a-yazar", "rol": "yazici"},
                      alici={"profil": "yonetici", "rol": "yonetici"}, metin="çok satırlı\n\tmetin",
                      govde={"ek_bilgi": {"liste": [1, 2.5, None, True]}},
                      ekler=[{"yol": "docs/fark.txt", "sha256": "a" * 64}])
    assert haber.dogrula(z) is z
    s = haber.sema()
    assert s["required"] == list(haber.ZARF_ALANLARI)
    assert set(s["properties"]) == set(haber.ZARF_ALANLARI)
    assert s["properties"]["tur"]["enum"] == list(haber.TURLER)
    assert s["$defs"]["taraf"]["properties"]["rol"]["enum"] == list(haber.ROLLER)
    json.dumps(s)


def _bozuk(**degisen):
    z = tam()
    for yol, deger in degisen.items():
        hedef = z
        parcalar = yol.split("__")
        for p in parcalar[:-1]:
            hedef = hedef[p]
        if deger is KALDIR:
            del hedef[parcalar[-1]]
        else:
            hedef[parcalar[-1]] = deger
    return z


KALDIR = object()


@pytest.mark.parametrize("degisen", [
    {"fazla": 1},
    {"govde": KALDIR},
    {"surum": True},
    {"surum": 2},
    {"id": "../../etc/passwd"},
    {"id": "A" * 32},
    {"ebeveyn": ""},
    {"is_id": "../x"},
    {"is_id": "a" * 65},
    {"tur": "komut"},
    {"gonderen__komut": "rm"},
    {"gonderen__rol": "kok"},
    {"gonderen__profil": "a\x1b[2Jb"},
    {"gonderen__profil": "a\u202eb"},
    {"gonderen__profil": " bosluk"},
    {"gonderen__profil": "baskasi"},             # yonetici rolü yalnız 'yonetici' profiliyle
    {"alici__rol": "reviewer"},                   # yazici alanı yok
    {"zaman": "2026-13-40T00:00:00Z"},
    {"zaman": "2026-01-01 00:00:00"},
    {"govde": {"baska": "x"}},
    {"govde": {"metin": 5}},
    {"govde__Kotu-Anahtar": 1},
    {"govde__metin": "x" * (haber.METIN_SINIRI + 1)},
    {"govde__metin": "nul\x00karakter"},
    {"govde__metin": "yarim \ud800 vekil"},
    {"govde__sayi": float("nan")},
    {"govde__nesne": object()},
    {"govde__derin": {"a": {"b": {"c": {"d": {"e": {"f": {"g": 1}}}}}}}},
    {"ekler": [{"yol": "../disari", "sha256": "a" * 64}]},
    {"ekler": [{"yol": "/etc/passwd", "sha256": "a" * 64}]},
    {"ekler": [{"yol": "C:/Windows/x", "sha256": "a" * 64}]},
    {"ekler": [{"yol": "a\\..\\b", "sha256": "a" * 64}]},
    {"ekler": [{"yol": "a//b", "sha256": "a" * 64}]},
    {"ekler": [{"yol": "a", "sha256": "A" * 64}]},
    {"ekler": [{"yol": "a", "sha256": "a" * 64, "komut": "x"}]},
    {"ekler": [{"yol": f"d/{i}", "sha256": "a" * 64} for i in range(haber.EK_SINIRI + 1)]},
    {"govde__liste": ["x" * 1000] * 600},         # boyut sınırı
])
def test_gecersiz_zarf_reddedilir(degisen):
    with pytest.raises(haber.ZarfHatasi):
        haber.dogrula(_bozuk(**degisen))


def test_ebeveyn_kendisi_olamaz():
    z = tam()
    z["ebeveyn"] = z["id"]
    with pytest.raises(haber.ZarfHatasi, match="kendisi"):
        haber.dogrula(z)


@pytest.mark.parametrize("veri", [
    b'{"a": 1, "a": 2}',
    b'{"a": NaN}',
    b'{"a": Infinity}',
    b"[" * 200_000,
    b"\xff\xfe{}",
    b'{"a": ' + b"9" * 5000 + b"}",
    b"x" * (haber.ZARF_SINIRI + 1),
    b"{bozuk",
])
def test_coz_saldiri_girdileri(veri):
    with pytest.raises(haber.ZarfHatasi):
        haber.coz(veri)


def test_coz_bom_kabul():
    assert haber.coz(b"\xef\xbb\xbf{\"a\": 1}") == {"a": 1}


# --- posta kutusu ---------------------------------------------------------------------------

def test_posta_gidis_donus(tmp_path):
    posta = haber.Posta(tmp_path / "p")
    z = haber.dogrula(tam(alici={"profil": "a-yazar", "rol": "yazici"}))
    yol = posta.birak("a-yazar", z)
    assert yol.parent.name == "gelen" and yol.name == f"{z['id']}.json"
    assert not list((yol.parent.parent / ".gecici").iterdir())
    [(durum, _, okunan, hata)] = posta.liste("a-yazar")
    assert (durum, okunan, hata) == ("gelen", z, "")
    with pytest.raises(haber.ZarfVar):
        posta.birak("a-yazar", z)
    assert posta.onayla("a-yazar", z["id"]) == "gelen"
    assert posta.bul("a-yazar", z["id"])[0] == "islenen"
    with pytest.raises(haber.ZarfVar):  # işlenmiş zarf tekrar gönderilemez
        posta.birak("a-yazar", z)
    assert posta.liste("a-yazar") == []
    assert [k[1] for k in posta.kutular()] == ["a-yazar"]


def test_es_zamanli_yazim_atomik_ve_eksiksiz(tmp_path):
    posta = haber.Posta(tmp_path / "p")
    hatalar, bitti = [], threading.Event()

    def yazar(n):
        try:
            for i in range(25):
                posta.birak("ortak", haber.dogrula(tam(alici={"profil": "a-yazar", "rol": "yazici"},
                                                        govde={"metin": f"{n}-{i} " + "y" * 4000})))
        except Exception as e:  # noqa: BLE001 - testte her hata toplanır
            hatalar.append(e)

    def okur():
        while not bitti.is_set():
            for _, _, zarf, hata in posta.liste("ortak"):
                if zarf is None:
                    hatalar.append(AssertionError(hata))  # yarım dosya görünmemeli

    iplikler = [threading.Thread(target=yazar, args=(n,)) for n in range(8)]
    o = threading.Thread(target=okur)
    o.start()
    for t in iplikler:
        t.start()
    for t in iplikler:
        t.join()
    bitti.set()
    o.join()
    assert hatalar == []
    liste = posta.liste("ortak")
    assert len(liste) == 200 and all(z is not None for _, _, z, _ in liste)
    assert not list((posta.kutu("ortak") / ".gecici").iterdir())


def test_ayni_zarf_es_zamanli_bir_kez_yazilir_ve_bir_kez_alinir(tmp_path):
    posta = haber.Posta(tmp_path / "p")
    z = haber.dogrula(tam())
    sonuc, kilit = [], threading.Lock()

    def yaz():
        try:
            posta.birak("ortak", z)
            r = "tamam"
        except haber.ZarfVar:
            r = "var"
        with kilit:
            sonuc.append(r)

    def al():
        r = posta.tasi("ortak", z["id"], "gelen", "isleniyor")
        with kilit:
            sonuc.append(r)

    for hedef in (yaz, al):
        sonuc.clear()
        iplikler = [threading.Thread(target=hedef) for _ in range(16)]
        for t in iplikler:
            t.start()
        for t in iplikler:
            t.join()
        assert sonuc.count("tamam" if hedef is yaz else True) == 1


@pytest.mark.parametrize("ad", ["../../etc", "..", ".", "CON", "nul", "a/b\\c:d*?", "çok uzun " * 20,
                                "kötü\u202ead", "x\x00y"])
def test_kutu_adi_guvenli_ve_windows_uyumlu(tmp_path, ad):
    k = haber.kutu_adi(ad)
    assert re.fullmatch(r"p-[a-z0-9_-]+-[0-9a-f]{12}", k) and len(k) <= 60
    assert k.split(".")[0].upper() not in {"CON", "PRN", "AUX", "NUL", "COM1", "LPT1"}
    posta = haber.Posta(tmp_path / "p")
    assert posta.kutu(ad, olustur_=True).parent == tmp_path / "p" / "kutular"
    assert haber.kutu_adi(ad) != haber.kutu_adi(ad + "x")


def test_kimlik_ile_yol_kurulamaz(tmp_path):
    posta = haber.Posta(tmp_path / "p")
    for kotu in ("../../x", "..", "a" * 31 + "/", "A" * 32):
        with pytest.raises(haber.ZarfHatasi):
            posta.bul("a-yazar", kotu)


def test_kutuda_bozuk_ve_sahte_dosya(tmp_path):
    posta = haber.Posta(tmp_path / "p")
    z = haber.dogrula(tam())
    posta.birak("a-yazar", z)
    gelen = posta.kutu("a-yazar") / "gelen"
    baska = haber.dogrula(tam())
    (gelen / f"{'b' * 32}.json").write_bytes(haber.serilestir(baska))  # ad ile kimlik farklı
    (gelen / f"{'c' * 32}.json").write_text("{bozuk", encoding="utf-8")
    (gelen / "notlar.txt").write_text("x", encoding="utf-8")
    satirlar = posta.liste("a-yazar")
    gecerli = [s for s in satirlar if s[2] is not None]
    assert [s[2]["id"] for s in gecerli] == [z["id"]]
    assert len(satirlar) == 4


@pytest.mark.skipif(sys.platform == "win32", reason="sembolik bağ yetkisi gerekir")
def test_sembolik_bag_okunmaz_ve_kutu_bagi_reddedilir(tmp_path):
    posta = haber.Posta(tmp_path / "p")
    posta.kutu("a-yazar", olustur_=True)
    gizli = tmp_path / "gizli.json"
    z = haber.dogrula(tam())
    gizli.write_bytes(haber.serilestir(z))
    os.symlink(gizli, posta.kutu("a-yazar") / "gelen" / f"{z['id']}.json")
    [(_, _, zarf, hata)] = posta.liste("a-yazar")
    assert zarf is None and "düzenli dosya değil" in hata
    os.symlink(tmp_path, tmp_path / "p" / "kutular" / haber.kutu_adi("b-inceler"))
    with pytest.raises(haber.HaberHatasi):
        posta.kutu("b-inceler", olustur_=True)


# --- yönlendirici ---------------------------------------------------------------------------

def test_yazici_rolle_adreslenir_ve_ilk_cli_yazici_secilir(ortam):
    h, z = haber.yonlendir(haber.dogrula(tam()), sag())
    assert (h.profil, h.rol, h.saglayici.ad) == ("a-yazar", "yazici", "sag-a")
    assert z["alici"] == {"profil": "a-yazar", "rol": "yazici"}


def test_reviewer_baska_saglayicidan_secilir(ortam):
    z = haber.dogrula(tam(alici={"profil": None, "rol": "reviewer"}, yazici="a-yazar"))
    h, _ = haber.yonlendir(z, sag())
    assert (h.profil, h.saglayici.ad, h.ayni_saglayici) == ("b-inceler", "sag-b", False)


def test_zarf_ayni_saglayicidan_kolay_reviewer_secemez(ortam):
    z = haber.dogrula(tam(alici={"profil": "a-inceler", "rol": "reviewer"}, yazici="a-yazar"))
    with pytest.raises(haber.YonlendirmeHatasi, match="reviewer olamaz"):
        haber.yonlendir(z, sag())
    z = haber.dogrula(tam(alici={"profil": "a-yazar", "rol": "reviewer"}, yazici="a-yazar"))
    with pytest.raises(haber.YonlendirmeHatasi):
        haber.yonlendir(z, sag())


def test_tek_saglayicida_ayni_saglayici_reviewer_ve_capraz_zorunlu():
    s = ayar.saglayicilari_ayikla({"saglayici": [
        {"ad": "tek", "tur": "cli", "komut": "x {istem}", "modeller": ["m-1", "m-2"]}]})
    z = haber.dogrula(tam(alici={"profil": None, "rol": "reviewer"}, yazici="m-1"))
    h, _ = haber.yonlendir(z, s)
    assert (h.profil, h.ayni_saglayici) == ("m-2", True)
    with pytest.raises(haber.YonlendirmeHatasi, match="uygun profil yok"):
        haber.yonlendir(z, s, capraz_zorunlu=True)


def test_kotasi_biten_saglayici_secilmez(ortam):
    z = haber.dogrula(tam(alici={"profil": None, "rol": "reviewer"}, yazici="a-yazar"))
    h, _ = haber.yonlendir(z, sag(), haric=frozenset({"sag-b"}))
    assert h.profil == "c-inceler"
    h, _ = haber.yonlendir(z, sag(), haric=frozenset({"sag-b", "sag-c"}))
    assert (h.profil, h.ayni_saglayici) == ("a-inceler", True)
    with pytest.raises(haber.YonlendirmeHatasi):
        haber.yonlendir(haber.dogrula(tam()), sag(), haric=frozenset({"sag-a"}))


def test_api_saglayici_yazici_olamaz_bilinmeyen_profil_ve_sahte_gonderen():
    s = ayar.saglayicilari_ayikla({"saglayici": [
        {"ad": "uzak", "tur": "api", "taban_url": "https://ornek.example/v1", "modeller": ["u-1"]},
        {"ad": "yerel", "tur": "cli", "komut": "x", "modeller": ["y-1"], "roller": ["reviewer"]}]})
    for alici in ({"profil": "u-1", "rol": "yazici"}, {"profil": "hayali", "rol": "yazici"},
                  {"profil": None, "rol": "yazici"}):
        with pytest.raises(haber.YonlendirmeHatasi):
            haber.yonlendir(haber.dogrula(tam(alici=alici)), s)
    sahte = tam(gonderen={"profil": "y-1", "rol": "yazici"}, alici={"profil": "yonetici", "rol": "yonetici"})
    with pytest.raises(haber.YonlendirmeHatasi, match="yazici rolü yok"):
        haber.yonlendir(haber.dogrula(sahte), s)
    h, z = haber.yonlendir(haber.dogrula(tam(gonderen={"profil": "y-1", "rol": "reviewer"},
                                              alici={"profil": None, "rol": "yonetici"})), s)
    assert (h.profil, h.saglayici, z["alici"]["profil"]) == ("yonetici", None, "yonetici")


def test_haber_ayari_dogrulanir(tmp_path):
    f = tmp_path / "a.toml"
    for metin, hata in (("[haber]\nbilinmeyen = 1\n", "bilinmeyen haber"),
                        ("[haber]\ndevir = true\n", "devir"),
                        ("[haber]\ndevir = 9\n", "devir"),
                        ("[haber]\ncapraz_zorunlu = \"evet\"\n", "capraz_zorunlu")):
        f.write_text(metin, encoding="utf-8")
        with pytest.raises(ValueError, match=hata):
            ayar.toml_oku(f)
    f.write_text("[haber]\ncapraz_zorunlu = true\ndevir = 0\n", encoding="utf-8")
    assert haber.ayar_ayikla(ayar.toml_oku(f)["haber"]) == haber.HaberAyari(True, 0)


# --- adaptör ve isle ------------------------------------------------------------------------

def test_gorev_gonder_isle_cevap_yoneticiye(ortam, capsys, monkeypatch):
    tmp, _, calisma = ortam
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_" + "q1W2e3R4" * 5)
    monkeypatch.setenv("OZEL_SECRET", "gizli-deger-123456")
    monkeypatch.setenv("SAHTE_ORTAM", str(tmp / "ortam.json"))
    monkeypatch.setenv("SAHTE_MOD", "sir")
    zarf = taslak(govde={"metin": "src'yi düzelt; anahtar gizli-deger-123456"})
    kod, veri, _ = cli(capsys, "gonder", gonder_dosya(tmp, zarf))
    assert kod == 0 and veri["profil"] == "a-yazar" and veri["saglayici"] == "sag-a"
    disk = Path(veri["dosya"]).read_text(encoding="utf-8")
    assert "gizli-deger-123456" not in disk and "[gizli]" in disk  # diske maskeli yazılır

    kod, veri, _ = cli(capsys, "isle", "a-yazar", "--dizin", str(calisma))
    assert kod == 0, veri
    assert veri["sonuc"] == "sonuc" and veri["cevap_kutu"] == "yonetici"
    ortam_ = json.loads((tmp / "ortam.json").read_text(encoding="utf-8"))
    assert "GITHUB_TOKEN" not in ortam_ and "OZEL_SECRET" not in ortam_
    posta = haber.Posta()
    assert posta.bul("a-yazar", veri["id"])[0] == "islenen"
    [(_, _, cevap, _)] = posta.liste("yonetici")
    assert cevap["tur"] == "sonuc" and cevap["ebeveyn"] == veri["id"]
    assert cevap["gonderen"] == {"profil": "a-yazar", "rol": "yazici"}
    assert cevap["govde"]["cikis"] == 0
    assert "cevap a-yazar yazici" in cevap["govde"]["metin"] and "sk-A1b2" not in cevap["govde"]["metin"]
    gunluk = (posta.kutu("a-yazar") / "gunluk" / f"{veri['id']}-1.log").read_text(encoding="utf-8")
    assert "sk-Z9y8" not in gunluk and "[gizli]" in gunluk and "saglayici: sag-a" in gunluk
    for kok_, dizinler, dosyalar in os.walk(tmp / "posta"):
        for ad in dizinler + dosyalar:
            assert GUVENLI_AD.fullmatch(ad), ad  # Windows'ta geçerli adlar


def test_reviewer_kota_devri_baska_saglayiciya(ortam, capsys, monkeypatch):
    tmp, _, calisma = ortam
    monkeypatch.setenv("SAHTE_KOTA", "b-inceler")
    monkeypatch.setenv("SAHTE_IZ", str(tmp / "iz.txt"))
    z = taslak(alici={"profil": None, "rol": "reviewer"}, yazici="a-yazar", govde={"metin": "farkı incele"})
    kod, veri, _ = cli(capsys, "gonder", gonder_dosya(tmp, z))
    assert kod == 0 and veri["profil"] == "b-inceler"
    kod, veri, _ = cli(capsys, "isle", "b-inceler", "--dizin", str(calisma))
    assert kod == 0, veri
    assert [d["saglayici"] for d in veri["devir"]] == ["sag-b", "sag-c"]
    assert (tmp / "iz.txt").read_text(encoding="utf-8").split("\n")[:2] == ["reviewer b-inceler",
                                                                            "reviewer c-inceler"]
    [(_, _, cevap, _)] = haber.Posta().liste("yonetici")
    assert cevap["gonderen"]["profil"] == "c-inceler" and cevap["govde"]["devir"][0]["profil"] == "b-inceler"


def test_kota_devir_kapaliysa_kota_cevabi_ve_cikis_1(ortam, capsys, monkeypatch):
    tmp, ayar_f, calisma = ortam
    ayar_f.write_text(ayar_f.read_text(encoding="utf-8") + "\n[haber]\ndevir = 0\n", encoding="utf-8")
    monkeypatch.setenv("SAHTE_KOTA", "a-yazar")
    assert cli(capsys, "gonder", gonder_dosya(tmp, taslak()))[0] == 0
    kod, veri, _ = cli(capsys, "isle", "a-yazar", "--dizin", str(calisma))
    assert kod == 1 and veri["sonuc"] == "kota" and veri["devir"] == []
    [(_, _, cevap, _)] = haber.Posta().liste("yonetici")
    assert cevap["tur"] == "kota" and "rate limit" in cevap["govde"]["metin"]


def test_basarili_cevapta_kota_kelimesi_kota_sayilmaz(ortam, capsys, monkeypatch):
    tmp, _, calisma = ortam
    monkeypatch.setenv("SAHTE_MOD", "konu")
    assert cli(capsys, "gonder", gonder_dosya(tmp, taslak()))[0] == 0
    kod, veri, _ = cli(capsys, "isle", "a-yazar", "--dizin", str(calisma))
    assert kod == 0 and veri["sonuc"] == "sonuc" and veri["devir"] == []


def test_en_uzun_cevap_zarfa_sigar():
    """Kesilmiş en uzun cevap (4 baytlık karakterler) yine geçerli zarftır; işlenen zarf kuyrukta takılmaz."""
    metin = haber.temizle("\U0001F600" * (haber.METIN_SINIRI * 2))
    haber.olustur(is_id="is-1", tur="sonuc", gonderen={"profil": "a-yazar", "rol": "yazici"},
                  alici={"profil": "yonetici", "rol": "yonetici"}, metin=metin, govde={"cikis": 0})


def test_ajan_hatasi_hata_cevabi(ortam, capsys, monkeypatch):
    tmp, _, calisma = ortam
    monkeypatch.setenv("SAHTE_MOD", "hata")
    assert cli(capsys, "gonder", gonder_dosya(tmp, taslak()))[0] == 0
    kod, veri, _ = cli(capsys, "isle", "a-yazar", "--dizin", str(calisma))
    assert kod == 1 and veri["sonuc"] == "hata" and veri["cikis"] == 5


def test_terminal_kacislari_cevaptan_atilir(ortam, capsys, monkeypatch):
    tmp, _, calisma = ortam
    monkeypatch.setenv("SAHTE_MOD", "ansi")
    assert cli(capsys, "gonder", gonder_dosya(tmp, taslak()))[0] == 0
    assert cli(capsys, "isle", "a-yazar", "--dizin", str(calisma))[0] == 0
    [(_, _, cevap, _)] = haber.Posta().liste("yonetici")
    assert "kirmizi" in cevap["govde"]["metin"] and "\x1b" not in cevap["govde"]["metin"]
    assert "\x07" not in cevap["govde"]["metin"]


def test_ek_calisma_dizini_disinda_ya_da_hash_tutmazsa_ajan_calismaz(ortam, capsys, monkeypatch):
    tmp, _, calisma = ortam
    monkeypatch.setenv("SAHTE_IZ", str(tmp / "iz.txt"))
    (calisma / "fark.txt").write_text("fark\n", encoding="utf-8")
    dogru = haber._sha256(calisma / "fark.txt")
    for ekler in ([{"yol": "fark.txt", "sha256": "0" * 64}], [{"yol": "yok.txt", "sha256": dogru}]):
        assert cli(capsys, "gonder", gonder_dosya(tmp, taslak(ekler=ekler)))[0] == 0
        kod, veri, _ = cli(capsys, "isle", "a-yazar", "--dizin", str(calisma))
        assert kod == 1 and veri["sonuc"] == "hata"
    assert not (tmp / "iz.txt").exists()
    if sys.platform != "win32":
        os.symlink(tmp / "ayar.toml", calisma / "bag.txt")
        z = taslak(ekler=[{"yol": "bag.txt", "sha256": haber._sha256(tmp / "ayar.toml")}])
        assert cli(capsys, "gonder", gonder_dosya(tmp, z))[0] == 0
        kod, veri, _ = cli(capsys, "isle", "a-yazar", "--dizin", str(calisma))
        assert kod == 1 and not (tmp / "iz.txt").exists()
    assert cli(capsys, "gonder", gonder_dosya(tmp, taslak(ekler=[{"yol": "fark.txt", "sha256": dogru}])))[0] == 0
    assert cli(capsys, "isle", "a-yazar", "--dizin", str(calisma))[0] == 0
    assert (tmp / "iz.txt").read_text(encoding="utf-8").strip() == "yazici a-yazar"


def test_ajan_ciktisindaki_zarf_baska_profile_cevap_yollar(ortam, capsys, monkeypatch):
    """Reviewer'ın yazıcıya sorusu: gönderen ayar'da doğrulanır, cevap reviewer'a yazici alanıyla döner."""
    calisma = ortam[2]
    z = taslak(tur="soru", gonderen={"profil": "b-inceler", "rol": "reviewer"},
               alici={"profil": "a-yazar", "rol": "yazici"}, govde={"metin": "neden böyle?"})
    kod, veri, _ = cli(capsys, "gonder", "-", stdin=json.dumps(z).encode("utf-8"), monkeypatch=monkeypatch)
    assert kod == 0 and veri["profil"] == "a-yazar"
    kod, veri, _ = cli(capsys, "isle", "a-yazar", "--dizin", str(calisma))
    assert kod == 0 and veri["cevap_kutu"] == "b-inceler"
    [(_, _, cevap, _)] = haber.Posta().liste("b-inceler")
    assert cevap["yazici"] == "a-yazar" and cevap["alici"] == {"profil": "b-inceler", "rol": "reviewer"}


def test_isle_bos_kutu_ve_bilgi_zarfi_islenmez(ortam, capsys):
    tmp, _, calisma = ortam
    kod, veri, _ = cli(capsys, "isle", "a-yazar", "--dizin", str(calisma))
    assert kod == 0 and veri["sonuc"] == "bos"
    z = taslak(tur="sonuc", alici={"profil": "a-yazar", "rol": "yazici"})
    kod, veri, _ = cli(capsys, "gonder", gonder_dosya(tmp, z))
    assert kod == 0
    assert cli(capsys, "isle", "a-yazar", "--dizin", str(calisma))[1]["sonuc"] == "bos"
    kod, _, err = cli(capsys, "isle", "a-yazar", "--dizin", str(calisma), "--id", veri["id"])
    assert kod == 1 and "işlenmez" in err
    kod, son, _ = cli(capsys, "onayla", "a-yazar", veri["id"])
    assert kod == 0 and son["durum"] == "islenen"


def test_isle_yonlenmeyen_zarfi_reddeder(ortam, capsys):
    """Kutuya elle konmuş, artık o profile yönlenmeyen zarf ajan çalışmadan reddedilir."""
    calisma = ortam[2]
    posta = haber.Posta()
    z = haber.dogrula(tam(alici={"profil": "a-inceler", "rol": "reviewer"}, yazici="a-yazar"))
    posta.birak("a-inceler", z)
    kod, veri, _ = cli(capsys, "isle", "a-inceler", "--dizin", str(calisma))
    assert kod == 1 and veri["sonuc"] == "reddedildi"
    assert posta.bul("a-inceler", z["id"])[0] == "reddedilen"


# --- komut satırı ---------------------------------------------------------------------------

def test_cli_cikis_kodlari(ortam, capsys):
    tmp, ayar_f, _ = ortam
    kod, veri, err = cli(capsys, "dogrula", gonder_dosya(tmp, taslak(tur="komut")))
    assert kod == 1 and veri["sonuc"] == "ret" and "tur" in err
    kod, veri, _ = cli(capsys, "dogrula", gonder_dosya(tmp, taslak()))
    assert kod == 0 and veri["profil"] == "a-yazar" and "dosya" not in veri
    assert haber.Posta().kutular() == []  # dogrula yazmaz
    assert cli(capsys, "gonder", str(tmp / "yok.json"))[0] == 2
    assert cli(capsys, "liste", "a-yazar")[0:2] == (0, [])
    assert cli(capsys, "onayla", "a-yazar", "f" * 32)[0] == 1
    assert cli(capsys, "oku", "a-yazar", "../../ayar")[0] == 1
    assert cli(capsys, "isle", "yonetici", "--dizin", str(tmp))[0] == 1
    _, veri, _ = cli(capsys, "gonder", gonder_dosya(tmp, taslak()))
    assert cli(capsys, "isle", "a-yazar", "--dizin", str(tmp / "yok"))[0] == 2
    assert haber.Posta().bul("a-yazar", veri["id"])[0] == "gelen"  # denetlenemedi: kuyruğa geri
    with pytest.raises(SystemExit) as e:
        haber.main([])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        haber.main(["isle", "a-yazar"])  # --dizin ya da --serit zorunlu
    assert e.value.code == 2
    ayar_f.write_text(ayar_f.read_text(encoding="utf-8") + "\n[haber]\nbilinmeyen = 1\n", encoding="utf-8")
    assert cli(capsys, "dogrula", gonder_dosya(tmp, taslak()))[0] == 2


def test_cli_oku_liste_kutular_sema(ortam, capsys):
    tmp, _, _ = ortam
    _, veri, _ = cli(capsys, "gonder", gonder_dosya(tmp, taslak()))
    kod, oku, _ = cli(capsys, "oku", "a-yazar", veri["id"])
    assert kod == 0 and oku["durum"] == "gelen" and oku["zarf"]["id"] == veri["id"]
    kod, liste, _ = cli(capsys, "liste", "a-yazar")
    assert kod == 0 and [x["id"] for x in liste] == [veri["id"]]
    kod, kutular, _ = cli(capsys, "kutular")
    assert kod == 0 and kutular[0]["profil"] == "a-yazar" and kutular[0]["gelen"] == 1
    assert haber.main(["sema"]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == "nobet-haber zarfı"
    assert haber.main(["liste", "a-yazar"]) == 0
    assert veri["id"] in capsys.readouterr().out


def test_konsol_betigi_alt_surecte(ortam):
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(
        filter(None, [str(Path(__file__).resolve().parents[1] / "src"), os.environ.get("PYTHONPATH")])))
    r = subprocess.run([sys.executable, "-m", "nobet.haber", "--json", "dogrula", "-"], input=json.dumps(taslak()),
                       capture_output=True, text=True, encoding="utf-8", env=env, check=False)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["profil"] == "a-yazar"


# --- nobet-akis şeridiyle (isteğe bağlı) ----------------------------------------------------

def _git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def serit(ortam, monkeypatch):
    tmp = ortam[0]
    for ad, deger in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@example.com"),
                      ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@example.com"),
                      ("GIT_CONFIG_GLOBAL", os.devnull), ("GIT_CONFIG_NOSYSTEM", "1")):
        monkeypatch.setenv(ad, deger)
    monkeypatch.setenv("NOBET_AKIS_DIZIN", str(tmp / "akis"))
    repo = tmp / "proje"
    (repo / "src").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "src" / "a.py").write_text("eski\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "ilk")
    assert akis.main(["ac", str(repo), "s1", "--sahiplik", "src/**", "--bitti", "true"]) == 0
    d = tmp / "akis" / "isler" / "s1"
    return d, Path((d / "worktree").read_text(encoding="utf-8").strip())


def test_serit_reviewer_agaci_degistirirse_cevap_sayilmaz(ortam, serit, capsys, monkeypatch):
    tmp = ortam[0]
    wt = serit[1]
    capsys.readouterr()
    monkeypatch.setenv("SAHTE_MOD", "agac")
    z = taslak(is_id="s1", alici={"profil": None, "rol": "reviewer"}, yazici="a-yazar")
    assert cli(capsys, "gonder", gonder_dosya(tmp, z))[0] == 0
    kod, veri, _ = cli(capsys, "isle", "b-inceler", "--serit", "s1")
    assert kod == 1 and veri["sonuc"] == "hata" and any("worktree" in i for i in veri["ihlal"])
    assert (wt / "src" / "a.py").read_text() == "reviewer yazdi\n"  # geri alınmaz, bildirilir


def test_serit_koruma_muhru_ve_is_kimligi(ortam, serit, capsys, monkeypatch):
    tmp = ortam[0]
    d = serit[0]
    capsys.readouterr()
    z = taslak(is_id="baska-is")
    _, veri, _ = cli(capsys, "gonder", gonder_dosya(tmp, z))
    kod, _, err = cli(capsys, "isle", "a-yazar", "--serit", "s1")
    assert kod == 1 and "şerit adıyla" in err
    assert haber.Posta().bul("a-yazar", veri["id"])[0] == "gelen"  # kuyruğa geri döndü
    assert cli(capsys, "onayla", "a-yazar", veri["id"])[0] == 0

    monkeypatch.setenv("SAHTE_MOD", "serit-boz")
    monkeypatch.setenv("SAHTE_SERIT", str(d))
    assert cli(capsys, "gonder", gonder_dosya(tmp, taslak(is_id="s1")))[0] == 0
    kod, veri, _ = cli(capsys, "isle", "a-yazar", "--serit", "s1")
    assert kod == 1 and veri["sonuc"] == "hata" and veri["ihlal"]
    assert (d / "sahiplik").read_text(encoding="utf-8") == "src/**\n"  # mühürlü içerik geri yazıldı
    assert "haber-yazici" in (d / akis.KORUMA).read_text(encoding="utf-8")
    assert akis.main(["kaydet", "s1", "-m", "x"]) == 1  # koruma ihlali şeridi kilitler
