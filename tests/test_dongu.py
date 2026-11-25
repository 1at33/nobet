"""nobet-dongu: döngü kapısı. Örnek metinler sentetiktir; model çağrısı yok."""
import json
import os
import random
import subprocess

import pytest

from nobet import ayar, dongu
from nobet.dongu import Deneme, Metin

SAGLIKLI = (
    "Önbellek katmanı, sık okunan yapılandırma değerlerini bellekte tutarak disk erişimini azaltır.\n"
    "İlk sınamada okuma süresi belirgin biçimde düştü; yazma yolunda ölçülebilir bir fark çıkmadı.\n"
    "Ayrıştırıcı bozuk satırları atlamak yerine artık satır numarasıyla birlikte hata döndürüyor.\n"
    "Kuyruk boşaldığında işçi süreç uyumaya geçiyor, yeni iş gelince sinyalle uyandırılıyor.\n"
    "Zaman aşımı ortam değişkeninden okunuyor; verilmezse on beş dakikalık varsayılan geçerli.\n"
    "Karşılaştırma tablosuna iki sütun eklendi: ortalama gecikme ve en kötü durum süresi.\n"
)
SAGLIKLI_2 = (
    "Bu turda kimlik doğrulama akışındaki yarış durumu giderildi; kilit artık istek başına alınıyor.\n"
    "Eski oturum kayıtlarını silen görev haftada bir kez çalışacak biçimde zamanlandı.\n"
    "Günlük biçimi JSON satırlarına çevrildi, böylece arama aracı alanları doğrudan süzebiliyor.\n"
    "Belgelere geri dönüş adımları eklendi ve sürüm notları güncellendi.\n"
    "Bağımlılık ağacında kullanılmayan iki paket bulundu, ikisi de kaldırıldı.\n"
)
IZ = "7f3aq"  # döngü örneğinin içindeki iz: çıktıda görünmemeli
DONGU = (f"Adım {IZ}: görev durumu kontrol edildi, doğrulama komutu yeniden çalıştırıldı "
         "ve sonuç değişmediği için aynı adıma geri dönüldü.\n") * 14


def _yaz(p, metin):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(metin, encoding="utf-8", newline="\n")
    return p


def _ic(metin, **esik):
    e = {**dongu.varsayilan_esikler(), **esik}
    return dongu.ic_tekrar(Metin("m", metin), e)


def _olculer(metin, **esik):
    return {i.olcu for i in _ic(metin, **esik)[1]}


def _kos(capsys, *argv):
    kod = dongu.main([str(a) for a in argv])
    return kod, capsys.readouterr()


def _degistir(metin, sira=0, yeni="farklı"):
    kelime = metin.split(" ")
    kelime[len(kelime) // 2 + sira] = yeni
    return " ".join(kelime)


# --- ic_tekrar ------------------------------------------------------------------------------

def test_dongu_metni_reddedilir():
    olcu, ihlal = _ic(DONGU)
    assert {i.olcu for i in ihlal} >= {"sikistirma", "tekillik", "blok_benzerlik", "kopya_blok"}
    assert olcu["sikistirma"] < 0.16
    assert all(i.kapi == "ic_tekrar" for i in ihlal)


def test_saglikli_metin_gecer():
    for metin in (SAGLIKLI, SAGLIKLI_2):
        olcu, ihlal = _ic(metin)
        assert ihlal == [], ihlal
        assert olcu["entropi"] > 3.5 and olcu["sikistirma"] > 0.3


def test_dusuk_entropili_dolgu():
    rnd = random.Random(3)
    dolgu = "".join(rnd.choice("ab ") for _ in range(400))
    assert "entropi" in _olculer(dolgu)


def test_cumle_ici_yanki_tek_satirda():
    yanki = "sonuç aynı kaldı ve komut yeniden çalıştırıldı " * 12  # tek satır: blok denetimi devrede değil
    olcu = _olculer(yanki)
    assert "tekillik" in olcu
    assert not olcu & {"blok_benzerlik", "kopya_blok"}


def test_ardisik_neredeyse_ayni_bloklar():
    govde = "görev listesindeki madde yeniden açıldı ve aynı kontrol bir kez daha uygulandı sonra " * 3
    metin = "\n".join(f"{govde}bitiş{i}" for i in range(8))
    olcu = _olculer(metin, sikistirma_min=0.0, tekillik_min=0.0)
    assert olcu == {"blok_benzerlik"}


def test_kisa_metin_olculmez():
    olcu, ihlal = _ic("tamam tamam tamam")
    assert ihlal == []
    assert "sikistirma" in olcu and "tekillik" not in olcu
    assert _ic("")[1] == []


def test_veri_dosyasi_gevsek_sikistirma():
    rnd = random.Random(0)
    satirlar = "".join(f'{{"ad": "olcum", "deger": {rnd.randint(0, 9999)}, "birim": "ms"}}\n' for _ in range(40))
    oran = dongu.sikistirma_orani(satirlar.strip().encode())
    assert 0.10 <= oran < 0.16
    e = dongu.varsayilan_esikler()
    ihlal_metin = dongu.ic_tekrar(Metin("a.txt", satirlar), e)[1]
    ihlal_veri = dongu.ic_tekrar(Metin("a.jsonl", satirlar, veri=True), e)[1]
    assert "sikistirma" in {i.olcu for i in ihlal_metin}
    assert "sikistirma" not in {i.olcu for i in ihlal_veri}


def test_turkce_unicode():
    assert dongu.kelimeler("ÖLÇÜM ağaç, Şişe-ığdır!") == ["ölçüm", "ağaç", "şişe", "ığdır"]
    assert dongu.kelimeler("ÖZET ÇĞŞÜ") == dongu.kelimeler("özet çğşü")
    assert _ic(SAGLIKLI)[1] == []
    turkce_dongu = "Çıktı ölçüldü, şerit güncellendi ve ağaç doğrulandı; işlem baştan başlatıldı.\n" * 15
    assert "sikistirma" in _olculer(turkce_dongu)


# --- deneme_tekrari -------------------------------------------------------------------------

def _deneme(ad, metin, kanit=None):
    return Deneme(ad, [Metin(ad, metin)], kanit)


def _kapilar(denemeler, **esik):
    return [(i.kapi, i.yer) for i in dongu.denetle(denemeler, esik).ihlaller]


def test_neredeyse_ayni_denemeler_reddedilir():
    ihlal = _kapilar([_deneme("d1", SAGLIKLI), _deneme("d2", _degistir(SAGLIKLI))])
    assert ihlal == [("deneme_tekrari", "d2 ~ d1")]


def test_salinim_ilk_denemeye_donus_yakalanir():
    ihlal = _kapilar([_deneme("d1", SAGLIKLI), _deneme("d2", SAGLIKLI_2), _deneme("d3", SAGLIKLI)])
    assert ihlal == [("deneme_tekrari", "d3 ~ d1")]


def test_farkli_denemeler_gecer():
    assert _kapilar([_deneme("d1", SAGLIKLI), _deneme("d2", SAGLIKLI_2)]) == []


def test_kisa_denemeler_karsilastirilmaz():
    assert _kapilar([_deneme("d1", "tamam"), _deneme("d2", "tamam")]) == []


def test_kanit_degistiyse_tekrar_sayilmaz_aynisiysa_sayilir():
    assert _kapilar([_deneme("d1", SAGLIKLI, "k1"), _deneme("d2", SAGLIKLI, "k2")]) == []
    s = dongu.denetle([_deneme("d1", SAGLIKLI, "k1"), _deneme("d2", SAGLIKLI, "k1")])
    assert [(i.kapi, i.yer) for i in s.ihlaller] == [("deneme_tekrari", "d2 ~ d1")]
    assert "kanıt" in s.ihlaller[0].aciklama
    # Kısa rapor da kanıt özeti aynıysa ve birebir aynıysa tekrar sayılır.
    assert _kapilar([_deneme("d1", "madde 1: KARŞILANDI", "k1"), _deneme("d2", "madde 1: KARŞILANDI", "k1")]) \
        == [("deneme_tekrari", "d2 ~ d1")]


# --- kopya_kanit ----------------------------------------------------------------------------

def test_ayni_denemede_kopya_dosya(tmp_path):
    d1 = tmp_path / "d1"
    _yaz(d1 / "rapor.md", SAGLIKLI_2)
    _yaz(d1 / "kanit" / "a.log", SAGLIKLI)
    _yaz(d1 / "kanit" / "b.log", SAGLIKLI + "Ek satır: yeniden koşuldu.\n")
    denemeler, _ = dongu.girdi_denemeleri([str(d1)])
    ihlal = [(i.kapi, i.yer) for i in dongu.denetle(denemeler).ihlaller]
    assert ihlal == [("kopya_kanit", f"{d1.as_posix()}/kanit/b.log ~ {d1.as_posix()}/kanit/a.log")]


def test_onceki_denemenin_kaniti_yeniden_sunulur(tmp_path):
    _yaz(tmp_path / "d1" / "rapor.md", SAGLIKLI_2)
    _yaz(tmp_path / "d1" / "test.log", SAGLIKLI)
    _yaz(tmp_path / "d2" / "rapor.md", "Bu kez hata giderildi ve bütün sınamalar geçti; ayrıntı aşağıdaki günlükte.\n"
         "Değişen dosyalar: ayrıştırıcı ve kuyruk işçisi. Yeni sınama eklenmedi, mevcutlar yeniden koşuldu.\n")
    _yaz(tmp_path / "d2" / "test.log", SAGLIKLI)
    denemeler, _ = dongu.girdi_denemeleri([str(tmp_path / "d1"), str(tmp_path / "d2")])
    s = dongu.denetle(denemeler)
    assert [i.kapi for i in s.ihlaller] == ["kopya_kanit"]
    assert "önceki denemenin" in s.ihlaller[0].aciklama


def test_ikili_buyuk_ve_gizli_dosyalar_atlanir(tmp_path, monkeypatch):
    d = tmp_path / "d"
    _yaz(d / "rapor.md", SAGLIKLI)
    (d / "resim.png").write_bytes(b"\x89PNG\r\n\x1a\n\0\0\0" + os.urandom(64))
    _yaz(d / ".gizli" / "x.md", DONGU)
    _yaz(d / "__pycache__" / "y.md", DONGU)
    sinir = len(SAGLIKLI.encode("utf-8"))
    _yaz(d / "buyuk.txt", "x" * (sinir + 1))
    monkeypatch.setattr(dongu, "DOSYA_SINIR", sinir)
    denemeler, atlanan = dongu.girdi_denemeleri([str(d)])
    assert [m.yer.rsplit("/", 1)[-1] for m in denemeler[0].metinler] == ["rapor.md"]
    assert sorted(atlanan) == [(f"{d.as_posix()}/buyuk.txt", "büyük"), (f"{d.as_posix()}/resim.png", "ikili")]


# --- komut satırı ---------------------------------------------------------------------------

def test_cli_cikis_kodlari(tmp_path, capsys):
    iyi = _yaz(tmp_path / "iyi.md", SAGLIKLI)
    iyi2 = _yaz(tmp_path / "iyi2.md", SAGLIKLI_2)
    kotu = _yaz(tmp_path / "kotu.md", DONGU)
    kod, cikti = _kos(capsys, iyi, iyi2)
    assert kod == 0 and "dongu: temiz (2 deneme, 2 metin)" in cikti.out
    kod, cikti = _kos(capsys, iyi, kotu)
    assert kod == 1 and "dongu: REDDEDİLDİ" in cikti.out
    assert "ihlal: ic_tekrar: " in cikti.out
    kod, cikti = _kos(capsys, tmp_path / "yok.md")
    assert kod == 2 and "girdi yok" in cikti.err
    bos = _yaz(tmp_path / "bos.md", "  \n")
    assert _kos(capsys, bos)[0] == 2
    kod, cikti = _kos(capsys, bos, iyi)
    assert kod == 0 and "(boş)" in cikti.out


@pytest.mark.parametrize("argv", [[], ["a.md", "--serit", "d"], ["--aralik", "A..B", "--oz-sinama"],
                                  ["--kapat", "yok", "a.md"], ["--muhur-salt-oku", "a.md"]])
def test_cli_kullanim_hatasi_2(argv, capsys):
    with pytest.raises(SystemExit) as e:
        dongu.main(argv)
    assert e.value.code == 2


def test_cli_json_ve_girdi_metni_yazilmaz(tmp_path, capsys):
    iyi = _yaz(tmp_path / "iyi.md", SAGLIKLI)
    kotu = _yaz(tmp_path / "kotu.md", DONGU)
    kod, cikti = _kos(capsys, "--json", iyi, kotu, kotu)
    assert kod == 1
    veri = json.loads(cikti.out)
    assert veri["sonuc"] == "dongu" and veri["deneme"] == 3 and veri["metin"] == 3
    assert {i["kapi"] for i in veri["ihlaller"]} == {"ic_tekrar", "deneme_tekrari"}
    assert veri["esikler"]["sikistirma_min"] == 0.16
    assert {o["yer"] for o in veri["olculer"]} == {str(iyi), str(kotu)}
    for metin in (cikti.out, _kos(capsys, iyi, kotu, kotu)[1].out):
        assert IZ not in metin and "görev durumu" not in metin and "Önbellek" not in metin


def test_esik_bayragi_ve_kapat(tmp_path, capsys):
    a = _yaz(tmp_path / "a.md", SAGLIKLI)
    b = _yaz(tmp_path / "b.md", _degistir(SAGLIKLI))
    assert _kos(capsys, a, b)[0] == 1
    assert _kos(capsys, "--esik", "deneme_benzerlik=0.99", a, b)[0] == 0
    assert _kos(capsys, "--kapat", "deneme_tekrari", a, b)[0] == 0
    kotu = _yaz(tmp_path / "kotu.md", DONGU)
    assert _kos(capsys, "--kapat", "ic_tekrar", kotu)[0] == 0
    # Sağlıklı metin de sıkı eşikle reddedilir: eşik gerçekten okunuyor.
    assert _kos(capsys, "--esik", "entropi_min=6", a)[0] == 1


@pytest.mark.parametrize("esik", ["yok=1", "shingle=2.5", "shingle=0", "deneme_benzerlik=1.5",
                                  "deneme_benzerlik=abc", "deneme_benzerlik", "entropi_min=nan"])
def test_gecersiz_esik_bayragi_2(esik, tmp_path, capsys):
    a = _yaz(tmp_path / "a.md", SAGLIKLI)
    kod, cikti = _kos(capsys, "--esik", esik, a)
    assert kod == 2 and "nobet-dongu:" in cikti.err


# --- ayar.toml [dongu] ----------------------------------------------------------------------

def test_ayar_esikleri_ve_bayrak_onceligi(tmp_path, capsys, monkeypatch):
    a = _yaz(tmp_path / "a.md", SAGLIKLI)
    b = _yaz(tmp_path / "b.md", _degistir(SAGLIKLI))
    ayar_f = _yaz(tmp_path / "ayar.toml", "[dongu]\ndeneme_benzerlik = 0.99\nkapali = [\"kopya_kanit\"]\n")
    assert _kos(capsys, "--ayar", ayar_f, a, b)[0] == 0
    monkeypatch.setenv("NOBET_AYAR", str(ayar_f))
    assert _kos(capsys, a, b)[0] == 0
    assert _kos(capsys, "--esik", "deneme_benzerlik=0.5", a, b)[0] == 1  # bayrak ayarı ezer
    ayar_ = dongu.ayar_oku()
    assert ayar_.esikler["deneme_benzerlik"] == 0.99 and ayar_.kapali == {"kopya_kanit"}
    assert ayar_.akis_denetle is False
    assert dongu.ayar_oku(env={}, ev=tmp_path).esikler == dongu.varsayilan_esikler()


@pytest.mark.parametrize(("metin", "mesaj"), [
    ("[dongu]\nbilinmeyen = 1\n", "bilinmeyen dongu anahtarı"),
    ("[dongu]\nshingle = 2.0\n", "tam sayı"),
    ("[dongu]\nsikistirma_min = true\n", "sayı olmalı"),
    ("[dongu]\nsikistirma_min = 2\n", "arasında"),
    ("[dongu]\nkapali = [\"hepsi\"]\n", "bilinmeyen kapı"),
    ("[dongu]\nkapali = \"ic_tekrar\"\n", "liste"),
    ("[dongu]\nakis_denetle = 1\n", "true ya da false"),
    ("dongu = 3\n", "tablo"),
])
def test_gecersiz_dongu_ayari(tmp_path, capsys, metin, mesaj):
    f = _yaz(tmp_path / "ayar.toml", metin)
    with pytest.raises(ValueError, match=mesaj):
        dongu.ayar_oku(f)
    # Sağlayıcıları okuyan ayar da [dongu] hatasını reddeder.
    with pytest.raises(ValueError, match=mesaj):
        ayar.saglayicilar(dosya=f, env={}, ev=tmp_path)
    a = _yaz(tmp_path / "a.md", SAGLIKLI)
    assert _kos(capsys, "--ayar", f, a)[0] == 2


def test_dongu_tablosu_saglayicilarla_birlikte(tmp_path):
    f = _yaz(tmp_path / "ayar.toml", '[dongu]\ntekillik_min = 0.3\n\n[[saglayici]]\nad = "c"\ntur = "cli"\n'
             'komut = "c"\nmodeller = ["m"]\n')
    assert [s.ad for s in ayar.saglayicilar(dosya=f, env={}, ev=tmp_path)] == ["c"]
    assert dongu.ayar_oku(f).esikler["tekillik_min"] == 0.3


# --- mühür ----------------------------------------------------------------------------------

def test_muhur_ayni_icerigi_ikinci_kez_reddeder(tmp_path, capsys):
    d = tmp_path / "d"
    _yaz(d / "rapor.md", SAGLIKLI)
    defter = d / "muhur.txt"  # girdi dizininde olsa da girdiye katılmaz
    assert _kos(capsys, "--muhur", defter, "--muhur-salt-oku", d)[0] == 0
    assert not defter.exists()
    assert _kos(capsys, "--muhur", defter, d)[0] == 0
    assert len(defter.read_text(encoding="utf-8").splitlines()) == 1
    kod, cikti = _kos(capsys, "--muhur", defter, d)
    assert kod == 1 and "ihlal: muhur:" in cikti.out
    # İçerik değişirse yeni mühür.
    _yaz(d / "rapor.md", SAGLIKLI_2)
    assert _kos(capsys, "--muhur", defter, d)[0] == 0
    # Döngülü girdi mühürlenmez.
    kotu = _yaz(tmp_path / "kotu.md", DONGU)
    assert _kos(capsys, "--muhur", defter, kotu)[0] == 1
    assert len(defter.read_text(encoding="utf-8").splitlines()) == 2
    defter.write_text("bozuk satır\n", encoding="utf-8")
    assert _kos(capsys, "--muhur", defter, d)[0] == 2


# --- şerit (nobet-akis iş dizini) -----------------------------------------------------------

def _serit(tmp_path, *denemeler):
    d = tmp_path / "serit"
    d.mkdir()
    for n, (rapor, kanit) in enumerate(denemeler, 1):
        _yaz(d / f"yaz-{n}.md", rapor)
        _yaz(d / f"yaz-{n}.log", f"tarih: x\nprofil: p\nsaglayici: s\ncikis: 0\ndurum_hash: {kanit}\n\ngünlük\n")
    return d


def test_serit_kanitsiz_tekrar(tmp_path, capsys):
    d = _serit(tmp_path, (SAGLIKLI, "a" * 64), (SAGLIKLI, "a" * 64))
    kod, cikti = _kos(capsys, "--serit", d)
    assert kod == 1 and "deneme_tekrari: yaz-2.md ~ yaz-1.md" in cikti.out


def test_serit_yeni_kanitla_ayni_rapor_gecer(tmp_path, capsys):
    d = _serit(tmp_path, (SAGLIKLI, "a" * 64), (SAGLIKLI, "b" * 64))
    _yaz(d / "review-1.md", SAGLIKLI_2)
    kod, cikti = _kos(capsys, "--serit", d)
    assert kod == 0 and "(2 deneme, 3 metin)" in cikti.out


def test_serit_review_ic_tekrari(tmp_path, capsys):
    d = _serit(tmp_path, (SAGLIKLI, "a" * 64))
    _yaz(d / "review-1.md", DONGU)
    kod, cikti = _kos(capsys, "--serit", d)
    assert kod == 1 and "ic_tekrar: review-1.md" in cikti.out


def test_serit_denemesiz_2(tmp_path, capsys):
    (tmp_path / "bos").mkdir()
    assert _kos(capsys, "--serit", tmp_path / "bos")[0] == 2
    assert _kos(capsys, "--serit", tmp_path / "yok")[0] == 2


# --- git aralığı ----------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path, monkeypatch):
    for ad, deger in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@example.com"),
                      ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@example.com"),
                      ("GIT_CONFIG_GLOBAL", os.devnull), ("GIT_CONFIG_NOSYSTEM", "1")):
        monkeypatch.setenv(ad, deger)
    r = tmp_path / "r"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    _commit(r, "baslangic.md", "başlangıç\n")
    return r


def _commit(r, ad, metin=None, ikili=None):
    if ikili is not None:
        (r / ad).write_bytes(ikili)
    else:
        _yaz(r / ad, metin)
    subprocess.run(["git", "-C", str(r), "add", ad], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", ad], check=True)


def test_aralik_tekrar_eden_commitler(repo, capsys):
    _commit(repo, "a.md", SAGLIKLI)
    _commit(repo, "b.md", _degistir(SAGLIKLI))
    kod, cikti = _kos(capsys, "--repo", repo, "--aralik", "HEAD~2..HEAD")
    assert kod == 1 and "deneme_tekrari:" in cikti.out
    assert "Önbellek" not in cikti.out


def test_aralik_saglikli_ve_ikili(repo, capsys):
    _commit(repo, "a.md", SAGLIKLI)
    _commit(repo, "veri.bin", ikili=b"\0\1\2" * 50)
    _commit(repo, "b.md", SAGLIKLI_2)
    kod, cikti = _kos(capsys, "--repo", repo, "--aralik", "HEAD~3..HEAD", "--json")
    veri = json.loads(cikti.out)
    assert kod == 0 and veri["deneme"] == 3
    assert [a["neden"] for a in veri["atlanan"]] == ["ikili"]
    assert veri["atlanan"][0]["yer"].endswith(":veri.bin")


def test_aralik_ic_tekrar_ve_hatali_aralik(repo, capsys):
    _commit(repo, "kotu.md", DONGU)
    kod, cikti = _kos(capsys, "--repo", repo, "--aralik", "HEAD~1..HEAD")
    assert kod == 1 and ":kotu.md: sikistirma" in cikti.out
    assert _kos(capsys, "--repo", repo, "--aralik", "yok..HEAD")[0] == 2
    assert _kos(capsys, "--repo", repo, "--aralik", "HEAD..HEAD")[0] == 2


def test_eklenen_satirlar_ayristirma():
    fark = ("diff --git a/x.md b/x.md\nindex 1..2 100644\n--- a/x.md\n+++ b/x.md\n@@ -0,0 +1,2 @@\n"
            "+yeni satır\n+++ artı ile başlayan satır\n"
            "diff --git a/s.md b/s.md\ndeleted file mode 100644\n--- a/s.md\n+++ /dev/null\n@@ -1 +0,0 @@\n-eski\n"
            "diff --git a/r.bin b/r.bin\nBinary files /dev/null and b/r.bin differ\n")
    eklenen, ikili = dongu.eklenen_satirlar(fark)
    assert eklenen == {"x.md": ["yeni satır", "++ artı ile başlayan satır"]}
    assert ikili == ["r.bin"]


# --- öz sınama (rastgele tohumlu kör sınama) ------------------------------------------------

def test_oz_sinama_varsayilan_esiklerle_gecer():
    vakalar, tohum = dongu.oz_sinama(tur=6)
    assert len(vakalar) == 30 and all(v["gecti"] for v in vakalar), [v for v in vakalar if not v["gecti"]]
    assert len(tohum) == 64


def test_oz_sinama_gevsek_esigi_yakalar(capsys):
    assert _kos(capsys, "--oz-sinama", "--tur", "2")[0] == 0
    kod, cikti = _kos(capsys, "--oz-sinama", "--tur", "2", "--esik", "deneme_benzerlik=1")
    assert kod == 1 and "tekrar_deneme" in cikti.out
    kod, cikti = _kos(capsys, "--oz-sinama", "--tur", "1", "--kapat", "kopya_kanit", "--json")
    veri = json.loads(cikti.out)
    assert kod == 0 and veri["sonuc"] == "gecti"
    assert [v["gecti"] for v in veri["vakalar"] if v["vaka"] == "kopya_kanit"] == [None]


def test_aralik_secenek_gibi_baslayamaz(tmp_path):
    with pytest.raises(dongu.DonguHatasi):
        dongu.aralik_denemeleri(tmp_path, "--output=x")
