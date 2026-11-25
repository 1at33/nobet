"""Kabul testi: nobet/gizli.py (sozlesme: adim2-gizli).

Sir benzeri butun degerler calisma aninda uretilir; dosyada duz metin sir yoktur.
"""
import ast
import copy
import string
from pathlib import Path

import pytest

from nobet.gizli import GecersizAd, gizli_mi, silinecekler, temiz_ortam

# Tekrarsiz karakter havuzu (yuksek entropi icin): 62 farkli karakter.
HAVUZ = string.ascii_uppercase + string.ascii_lowercase + string.digits


def govde(n, kayma=0):
    """n karakter; ilk 62 karakterde tekrar yok."""
    return "".join(HAVUZ[(i + kayma) % len(HAVUZ)] for i in range(n))


def yuksek(n=40):
    """Harf + rakam iceren, onek kalibi olmayan yuksek entropili deger."""
    # Basta rakam, sonra harfler: hicbir kalip onekiyle baslamaz.
    return govde(n, kayma=52)


ONEKLER = [
    "s" + "k-",
    "gh" + "p_",
    "gh" + "o_",
    "gh" + "s_",
    "gh" + "u_",
    "github" + "_pat_",
    "xo" + "xb-",
    "xo" + "xp-",
    "xo" + "xa-",
    "gl" + "pat-",
]


# ---------------------------------------------------------------- kalip ailesi
@pytest.mark.parametrize("onek", ONEKLER)
def test_kalip_oneki_gizli(onek):
    assert gizli_mi(onek + govde(20)) is True


@pytest.mark.parametrize("onek", ONEKLER)
def test_kalip_oneki_alt_sinir_16_karakter(onek):
    assert gizli_mi(onek + govde(16)) is True
    # 15 karakter: kalip yok, uzunluk < 32 -> False
    assert gizli_mi(onek + govde(15)) is False


@pytest.mark.parametrize("onek", ONEKLER)
@pytest.mark.parametrize("onceki", ["x", "Z", "7"])
def test_kalip_oneki_harf_rakamdan_sonra_eslesmez(onek, onceki):
    assert gizli_mi(onceki + onek + govde(16)) is False  # toplam < 32: entropi yoluna da dusmez


@pytest.mark.parametrize("onceki", [" ", "=", "_", "-", ":", "\""])
def test_kalip_oneki_harf_rakam_disi_karakterden_sonra_eslesir(onceki):
    assert gizli_mi(onceki + "s" + "k-" + govde(20)) is True


def test_kalip_cevrede_metin_icinde_eslesir():
    deger = "Authorization: Bearer " + "gh" + "p_" + govde(30) + " tail"
    assert gizli_mi(deger) is True


def test_kalip_kisa_degerde_bile_eslesir():
    # Kalip uzunluk kuralindan once degerlendirilir (32'den kisa olsa da True).
    deger = "s" + "k-" + govde(16)
    assert len(deger) < 32
    assert gizli_mi(deger) is True


def test_kalip_aws_akia():
    assert gizli_mi("AK" + "IA" + "ABCDEFGHIJKLMNOP") is True
    assert gizli_mi("AK" + "IA" + "ABCDEFGHIJ234567") is True


def test_kalip_aws_akia_eksik_veya_kucuk_harf_eslesmez():
    assert gizli_mi("AK" + "IA" + "ABCDEFGHIJKLMNO") is False  # 15
    assert gizli_mi("AK" + "IA" + "abcdefghijklmnop") is False  # kucuk harf


def test_kalip_google_aiza():
    assert gizli_mi("AI" + "za" + govde(35)) is True
    assert gizli_mi("AI" + "za" + govde(34)) is False


def test_kalip_private_key_basligi():
    for tur in ("RSA ", "EC ", "OPENSSH ", ""):
        baslik = "-----BEGIN " + tur + "PRIV" + "ATE KEY-----"
        assert gizli_mi(baslik) is True
        assert gizli_mi(baslik + "\nabc") is True


def test_private_key_basligi_olmayan_metin_false():
    assert gizli_mi("-----BEGIN CERTIFICATE-----") is False
    assert gizli_mi("-----BEGIN " + "PRIV" + "ATE KEY----") is False  # eksik tire


# ----------------------------------------------------------------------- UUID
def test_uuid_false():
    assert gizli_mi("123e4567-e89b-12d3-a456-426614174000") is False
    assert gizli_mi("123E4567-E89B-12D3-A456-426614174000") is False


def test_uuid_benzeri_ama_uuid_degil_ayri_degerlendirilir():
    # UUID'e 1 karakter eklenirse UUID istisnasi gecmez; yine de < 32 degil (37)
    # ama entropisi dusuk oldugundan False kalir. Burada yalniz cokmedigini sinariz.
    assert isinstance(gizli_mi("123e4567-e89b-12d3-a456-4266141740000"), bool)


# -------------------------------------------------------- uzunluk/karakter/vb.
def test_32den_kisa_false():
    assert gizli_mi(yuksek(31)) is False


def test_32_uzunluk_sinirinda_true():
    assert gizli_mi(yuksek(32)) is True


def test_bos_deger_false():
    assert gizli_mi("") is False


def test_slash_ile_baslayan_false():
    assert gizli_mi("/" + yuksek(40)) is False


def test_slash_ortada_olabilir():
    d = yuksek(20) + "/" + yuksek(20, )
    assert gizli_mi(d) is True


@pytest.mark.parametrize("kotu", [" ", "!", ".", "@", "\n", "ç", ":"])
def test_izinli_karakter_disi_false(kotu):
    d = yuksek(20) + kotu + yuksek(20)
    assert gizli_mi(d) is False


@pytest.mark.parametrize("izinli", ["+", "/", "=", "_", "-"])
def test_izinli_ozel_karakterler_engel_degil(izinli):
    d = yuksek(20) + izinli + yuksek(20)
    assert gizli_mi(d) is True


def test_harfsiz_false():
    assert gizli_mi("0123456789" * 4 + "+/=_-" * 2) is False
    assert gizli_mi("1234567890123456789012345678901234567890") is False


def test_rakamsiz_false():
    # 52 farkli harf: entropi ~5.7 olsa da rakam yok.
    d = string.ascii_letters
    assert len(d) >= 32
    assert gizli_mi(d) is False


# --------------------------------------------------------------------- entropi
def test_dusuk_entropi_tekrar_false():
    assert gizli_mi("a1" * 20) is False
    assert gizli_mi("A" * 39 + "1") is False


def test_yuksek_entropi_true():
    assert gizli_mi(yuksek(40)) is True
    assert gizli_mi(yuksek(64)) is True


def test_entropi_esigi_tam_4_true():
    # 16 farkli karakter, her biri 2 kez, uzunluk 32 -> entropi tam 4.0 (>= dahil).
    d = "0123456789abcdef" * 2
    assert len(d) == 32
    assert gizli_mi(d) is True


def test_entropi_esigin_altinda_false():
    # 15 farkli karakter (en fazla log2(15) ~ 3.91 < 4.0), harf + rakam var.
    d = "0123456789abcde" * 2 + "00"
    assert len(d) == 32
    assert gizli_mi(d) is False


def test_entropi_esigin_hemen_ustunde_true():
    # 17 farkli karakter, dengeli dagilim: entropi > 4.0.
    d = "0123456789abcdefg" + "0123456789abcdef"[:15]
    assert len(d) == 32
    assert gizli_mi(d) is True


# -------------------------------------------------------------- silinecekler
def test_silinecekler_bos_ortam():
    assert silinecekler({}) == []


def test_silinecekler_sirali_adlar_doner():
    ortam = {"PATH": "/usr/bin", "HOME": "/home/x", "ISIM": "kullanici"}
    assert silinecekler(ortam) == []


def test_silinecekler_izin_listesi_atlar():
    ortam = {"API_KEY": "x", "MY_TOKEN": "y", "PATH": "z"}
    assert silinecekler(ortam, izin=["API_KEY"]) == ["MY_TOKEN"]
    assert silinecekler(ortam, izin=("API_KEY", "MY_TOKEN")) == []
    assert silinecekler(ortam, izin=iter(["API_KEY"])) == ["MY_TOKEN"]


def test_silinecekler_izin_sir_degeri_de_atlar():
    deger = "gh" + "p_" + govde(30)
    assert silinecekler({"ESKI": deger}, izin=["ESKI"]) == []


def test_silinecekler_izin_gecersiz_adda_hata_vermez():
    deger = "gh" + "p_" + govde(30)
    assert silinecekler({"KOTU-AD": deger}, izin=["KOTU-AD"]) == []


@pytest.mark.parametrize(
    "ad",
    ["KEY", "Token", "my_secret", "PASSWORD", "AUTH_X", "credential",
     "key", "TOKEN", "MY_SECRET", "password", "Passwd", "AUTH", "CREDENTIALS",
     "X_api_KEY_2", "oauth_url"],
)
def test_silinecekler_ad_kurali_buyuk_kucuk_harf_duyarsiz(ad):
    assert silinecekler({ad: "sade"}) == [ad]


@pytest.mark.parametrize("ad", ["PATH", "HOME", "LANG", "USER", "_X", "a1"])
def test_silinecekler_ad_kuralina_uymayan_kalir(ad):
    assert silinecekler({ad: "sade"}) == []


def test_silinecekler_git_ayar_ailesi_birlikte_silinir():
    """KEY_n silinip COUNT kalırsa git 'missing config key' ile düşer."""
    ortam = {"GIT_CONFIG_COUNT": "1", "PATH": "/bin", "GIT_CONFIG_KEY_0": "x.y", "GIT_CONFIG_VALUE_0": "z"}
    assert silinecekler(ortam) == ["GIT_CONFIG_KEY_0", "GIT_CONFIG_COUNT", "GIT_CONFIG_VALUE_0"]
    assert silinecekler({"GIT_CONFIG_COUNT": "0"}) == []


def test_silinecekler_sir_degeri_masum_adla_silinir():
    deger = "gh" + "p_" + govde(30)
    assert silinecekler({"HARIKA": deger}) == ["HARIKA"]


def test_silinecekler_yuksek_entropili_deger_ile_silinir():
    assert silinecekler({"BELGE": yuksek(40)}) == ["BELGE"]


def test_silinecekler_sira_korunur():
    sir = "gh" + "p_" + govde(30)
    ortam = {"Z_TOKEN": "a", "PATH": "b", "A_KEY": "c", "M": sir, "B_SECRET": "d"}
    assert silinecekler(ortam) == ["Z_TOKEN", "A_KEY", "M", "B_SECRET"]


def test_silinecekler_yalniz_ad_doner_deger_donmez():
    sir = "gh" + "p_" + govde(30)
    sonuc = silinecekler({"A": sir, "B_KEY": "gizlice"})
    assert isinstance(sonuc, list)
    assert all(isinstance(s, str) for s in sonuc)
    assert sonuc == ["A", "B_KEY"]
    assert sir not in sonuc and "gizlice" not in sonuc


def test_gecersiz_ad_sir_deger_gecersizad_firlatir():
    sir = "gh" + "p_" + govde(30)
    for ad in ("KOTU-AD", "1AD", "A B", "", "AD.X", "ADÇ"):
        with pytest.raises(GecersizAd):
            silinecekler({ad: sir})


def test_gecersizad_valueerror_alt_sinifi():
    assert issubclass(GecersizAd, ValueError)


def test_gecersiz_ad_sira_onemsiz_firlatir():
    sir = "gh" + "p_" + govde(30)
    with pytest.raises(GecersizAd):
        silinecekler({"IYI_KEY": "a", "KOTU-AD": sir})


def test_gecersiz_ad_sradan_deger_firlatmaz_ve_listeye_girmez():
    ortam = {"KOTU-KEY": "sade", "BASKA-TOKEN": "sade", "OK_KEY": "sade"}
    assert silinecekler(ortam) == ["OK_KEY"]


def test_gecersiz_ad_masum_ve_adinda_key_olsa_da_girmez():
    assert silinecekler({"1_KEY": "sade"}) == []


# ----------------------------------------------------- istisna mesajinda sir yok
def test_istisna_mesajinda_sir_degeri_yok():
    sir = "gh" + "p_" + govde(30)
    with pytest.raises(GecersizAd) as bilgi:
        silinecekler({"KOTU-AD": sir})
    metin = str(bilgi.value) + repr(bilgi.value) + "".join(map(str, bilgi.value.args))
    assert sir not in metin
    assert govde(30) not in metin


def test_istisna_mesajinda_yuksek_entropili_sir_yok():
    sir = yuksek(48)
    with pytest.raises(GecersizAd) as bilgi:
        silinecekler({"a b": sir})
    metin = str(bilgi.value) + repr(bilgi.value)
    assert sir not in metin
    assert sir[8:24] not in metin


def test_istisna_temiz_ortamdan_da_sizmaz():
    sir = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
    with pytest.raises(GecersizAd) as bilgi:
        temiz_ortam({"BAD NAME": sir})
    assert sir not in str(bilgi.value) + repr(bilgi.value)


# ---------------------------------------------------------------- temiz_ortam
def test_temiz_ortam_silinenleri_cikarir_digerlerini_tutar():
    sir = "gh" + "p_" + govde(30)
    ortam = {"PATH": "/bin", "API_KEY": "x", "NOT": sir, "HOME": "/h"}
    sonuc = temiz_ortam(ortam)
    assert sonuc == {"PATH": "/bin", "HOME": "/h"}
    assert isinstance(sonuc, dict)


def test_temiz_ortam_girdiyi_degistirmez():
    sir = "gh" + "p_" + govde(30)
    ortam = {"PATH": "/bin", "API_KEY": "x", "NOT": sir}
    onceki = copy.deepcopy(ortam)
    sonuc = temiz_ortam(ortam)
    assert ortam == onceki
    assert list(ortam) == list(onceki)
    assert sonuc is not ortam


def test_temiz_ortam_hicbiri_silinmezse_kopya_doner():
    ortam = {"PATH": "/bin", "HOME": "/h"}
    sonuc = temiz_ortam(ortam)
    assert sonuc == ortam
    assert sonuc is not ortam
    sonuc["YENI"] = "1"
    assert "YENI" not in ortam


def test_temiz_ortam_izin_listesi():
    ortam = {"API_KEY": "x", "MY_TOKEN": "y", "PATH": "z"}
    assert temiz_ortam(ortam, izin=["API_KEY"]) == {"API_KEY": "x", "PATH": "z"}


def test_temiz_ortam_sira_korunur():
    ortam = {"C": "1", "A": "2", "B": "3"}
    assert list(temiz_ortam(ortam)) == ["C", "A", "B"]


def test_temiz_ortam_gecersiz_ad_sir_firlatir():
    sir = "gh" + "p_" + govde(30)
    with pytest.raises(GecersizAd):
        temiz_ortam({"KOTU-AD": sir})


# ------------------------------------------------------------------- import
IZINLI_MODULLER = {"re", "math", "collections", "typing", "collections.abc"}


def test_gizli_py_yalniz_izinli_modulleri_import_eder():
    yol = Path(__file__).resolve().parent.parent / "src" / "nobet" / "gizli.py"
    agac = ast.parse(yol.read_text(encoding="utf-8"))
    bulunan = []
    for dugum in ast.walk(agac):
        if isinstance(dugum, ast.Import):
            bulunan += [a.name for a in dugum.names]
        elif isinstance(dugum, ast.ImportFrom):
            assert dugum.level == 0, "goreli import yasak"
            bulunan.append(dugum.module)
    kotu = [m for m in bulunan if m not in IZINLI_MODULLER]
    assert kotu == [], f"izinsiz import: {kotu}"


def test_gizli_py_dinamik_import_kullanmaz():
    yol = Path(__file__).resolve().parent.parent / "src" / "nobet" / "gizli.py"
    agac = ast.parse(yol.read_text(encoding="utf-8"))
    for dugum in ast.walk(agac):
        if isinstance(dugum, ast.Call):
            f = dugum.func
            ad = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
            assert ad not in {"__import__", "import_module"}


# ---------------------------------------------------------------- maskele

def test_maskele_kalip_entropi_ve_ortam_degeri():
    from nobet.gizli import maskele
    tok = "gh" + "p_" + "Q7w9E2r4T6y8U1i3O5p7A9s2D4f6G8h1J3k5"
    rastgele = "Zq8" + "Xw2Lm4Np6Rt9Vb3Kc7Hd5Jf1Gs0Ty8Ue"
    metin = f"token={tok}\ndeger {rastgele}\nsifre gizlisifre99 ve normal_bir_satir_burada\n"
    sonuc = maskele(metin, {"VERI_SIFRE_PASSWORD": "gizlisifre99", "PATH": "/usr/bin"})
    assert tok not in sonuc and rastgele not in sonuc and "gizlisifre99" not in sonuc
    assert sonuc.count("[gizli]") == 3
    assert "normal_bir_satir_burada" in sonuc


def test_maskele_bos_ortam_ve_kisa_deger():
    from nobet.gizli import maskele
    assert maskele("abc", None) == "abc"
    assert maskele("anahtar=xy", {"API_KEY": "xy"}) == "anahtar=xy"  # 6 karakterden kısa değer dokunulmaz
