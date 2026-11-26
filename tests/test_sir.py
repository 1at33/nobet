"""nobet.sir kabul testi: gitleaks raporunu anahtar türü / entropi katmanlarına ayırma.

Sır benzeri değerler açıkça sentetiktir ve parçalı yazılır: tarama bu dosyayı yakalamasın.
Sahte gitleaks gerçek bir alt süreçtir (Python betiği + platforma uygun başlatıcı).
"""

import importlib
import json
import os
import sys

import pytest

SIR_DEGERI = "SENTETIK" + "-" + "Zq7" * 6  # sızmaması gereken sentetik sır değeri
HEX32 = "ab12" * 8
HEX64 = "9f3c" * 16
HEX40 = "7e1d" * 10
HEX31 = "ab12" * 7 + "ab1"
HEX_DISI = "ab12" * 7 + "ab1g"  # 32 karakter ama 'g' onaltılık değil
ENTROPI_DEGERI = "Qx9" + "Lm2" + "Vt7" + "Rk4" + "Wz8" + "Pn5"
BOS = {"anahtar_turu": 0, "entropi": 0, "suzulen": 0}


@pytest.fixture
def sir():
    return importlib.import_module("nobet.sir")


@pytest.fixture
def gecmis_hatasi():
    return importlib.import_module("nobet.gecmis").GecmisHatasi


def kayit(rule="generic-api-key", secret=ENTROPI_DEGERI, match=None, dosya="src/a.py"):
    return {
        "RuleID": rule,
        "Secret": secret,
        "Match": match if match is not None else f"deger = {secret}",
        "File": dosya,
    }


# ---------------------------------------------------------------- katmanla


def test_katmanla_anahtarlar_tam_uc(sir):
    assert set(sir.katmanla([kayit()]).keys()) == {"anahtar_turu", "entropi", "suzulen"}
    assert sir.katmanla([]) == BOS


def test_katmanla_belirli_kural_anahtar_turu(sir):
    k = sir.katmanla([kayit(rule="aws-access-token")])
    assert k == {"anahtar_turu": 1, "entropi": 0, "suzulen": 0}


def test_katmanla_generic_api_key_entropi(sir):
    k = sir.katmanla([kayit()])
    assert k == {"anahtar_turu": 0, "entropi": 1, "suzulen": 0}


def ozet(secret=HEX64, baglam="cache_key_sha256"):
    """Özet biçimli ve özet bağlamlı entropi kaydı."""
    return kayit(secret=secret, match=f"{baglam} = {secret}")


def test_katmanla_karisik_sayilar(sir):
    k = sir.katmanla([
        kayit(rule="aws-access-token"),
        kayit(rule="github-pat"),
        kayit(),
        ozet(),
        ozet(),
        ozet(),
    ])
    assert k == {"anahtar_turu": 2, "entropi": 1, "suzulen": 3}


@pytest.mark.parametrize("ad, secret, match, beklenen", [
    ("secret_key_64_onaltilik", HEX64, "SECRET_KEY = " + HEX64, "entropi"),
    ("github_token_40_onaltilik", HEX40, "github_token = " + HEX40, "entropi"),
    ("api_key_32_onaltilik", HEX32, "api_key = " + HEX32, "entropi"),
    ("cache_key_sha256", HEX64, "cache_key_sha256 = " + HEX64, "suzulen"),
    ("integrity_sha512", "sha512-" + "Zm9v" * 8, '"integrity": "sha512-' + "Zm9v" * 8 + '"', "suzulen"),
    ("auth_hash", HEX64, "auth_hash = " + HEX64, "entropi"),
])
def test_katmanla_gerekce_ornekleri(sir, ad, secret, match, beklenen):
    k = sir.katmanla([kayit(secret=secret, match=match)])
    sayilar = {"anahtar_turu": 0, "entropi": 0, "suzulen": 0}
    sayilar[beklenen] = 1
    assert k == sayilar, ad


def test_katmanla_kosul1_onaltilik_32_ve_ustu(sir):
    assert sir.katmanla([ozet(HEX32)])["suzulen"] == 1
    assert sir.katmanla([ozet(HEX32.upper())])["suzulen"] == 1
    assert sir.katmanla([ozet("Ab12" * 16)])["suzulen"] == 1


def test_katmanla_kosul1_31_karakter_suzulmez(sir):
    assert len(HEX31) == 31
    assert sir.katmanla([ozet(HEX31)]) == {"anahtar_turu": 0, "entropi": 1, "suzulen": 0}


def test_katmanla_kosul1_onaltilik_olmayan_harf_suzulmez(sir):
    assert len(HEX_DISI) == 32
    assert sir.katmanla([ozet(HEX_DISI)]) == {"anahtar_turu": 0, "entropi": 1, "suzulen": 0}


@pytest.mark.parametrize("onek", ["sha1-", "sha256-", "sha384-", "sha512-"])
def test_katmanla_kosul1_sha_oneki(sir, onek):
    secret = onek + "Zm9v" + "YmFy" * 3 + "+/="
    k = sir.katmanla([kayit(secret=secret, match="integrity: " + secret)])
    assert k == {"anahtar_turu": 0, "entropi": 0, "suzulen": 1}


def test_katmanla_kosul1_baska_onek_suzulmez(sir):
    secret = "sha224-" + "Zm9v" * 4
    k = sir.katmanla([kayit(secret=secret, match="integrity: " + secret)])
    assert k == {"anahtar_turu": 0, "entropi": 1, "suzulen": 0}


@pytest.mark.parametrize("match", [
    "shared_key = {s}", "hashed = {s}", "share = {s}", "washer = {s}", "x = {s}", "deger = {s}",
])
def test_katmanla_kosul2_sozcuk_siniri_baglam_degil(sir, match):
    k = sir.katmanla([kayit(secret=HEX64, match=match.format(s=HEX64))])
    assert k == {"anahtar_turu": 0, "entropi": 1, "suzulen": 0}


@pytest.mark.parametrize("match", [
    "cache_hash = {s}", "sha256: {s}", "MD5 = {s}", '"integrity": "{s}"', "Checksum={s}",
    "file_digest = {s}", "fingerprint: {s}", "sha1 {s}", "sha {s}", "sha224 = {s}", "sha384 = {s}",
    "sha512 = {s}", "Hash = {s}",
])
def test_katmanla_kosul2_baglam_sozcukleri(sir, match):
    k = sir.katmanla([kayit(secret=HEX64, match=match.format(s=HEX64))])
    assert k == {"anahtar_turu": 0, "entropi": 0, "suzulen": 1}


@pytest.mark.parametrize("sozcuk", ["token", "auth", "passw", "secret", "credential"])
def test_katmanla_kosul3_kimlik_sozcugu_suzmeyi_engeller(sir, sozcuk):
    for yazim in (sozcuk, sozcuk.upper(), sozcuk.capitalize()):
        k = sir.katmanla([kayit(secret=HEX64, match=f"cache_{yazim}_sha256 = {HEX64}")])
        assert k == {"anahtar_turu": 0, "entropi": 1, "suzulen": 0}, yazim


@pytest.mark.parametrize("eksik", ["Secret", "Match"])
@pytest.mark.parametrize("deger", ["yok", None, 42, ["a"], b"bayt"])
def test_katmanla_secret_ya_da_match_eksik_ya_da_metin_degil(sir, eksik, deger):
    r = ozet()
    if deger == "yok":
        del r[eksik]
    else:
        r[eksik] = deger
    assert sir.katmanla([r]) == {"anahtar_turu": 0, "entropi": 1, "suzulen": 0}


def test_katmanla_file_etkisiz_lock_dosyasi_baglamsiz_suzulmez(sir):
    for ad in ["package-lock.json", "yarn.lock", "go.sum", "checksums.txt", "web/Cargo.lock"]:
        k = sir.katmanla([kayit(dosya=ad, secret=HEX64, match="api_key = " + HEX64)])
        assert k == {"anahtar_turu": 0, "entropi": 1, "suzulen": 0}, ad
        k = sir.katmanla([kayit(dosya=ad, secret=ENTROPI_DEGERI, match="x " + ENTROPI_DEGERI)])
        assert k == {"anahtar_turu": 0, "entropi": 1, "suzulen": 0}, ad


def test_katmanla_file_olmasa_da_suzer(sir):
    r = ozet()
    del r["File"]
    assert sir.katmanla([r]) == {"anahtar_turu": 0, "entropi": 0, "suzulen": 1}
    r["File"] = "src/baska.py"
    assert sir.katmanla([r]) == {"anahtar_turu": 0, "entropi": 0, "suzulen": 1}


def test_katmanla_anahtar_turu_ozet_ve_baglamli_olsa_da_suzulmez(sir):
    k = sir.katmanla([
        kayit(rule="aws-access-token", secret=HEX64, match="cache_key_sha256 = " + HEX64),
        kayit(rule="github-pat", secret="sha512-" + "Zm9v" * 8,
              match='"integrity": "sha512-' + "Zm9v" * 8 + '"', dosya="package-lock.json"),
    ])
    assert k == {"anahtar_turu": 2, "entropi": 0, "suzulen": 0}


def test_katmanla_bozuk_kayitlar_anahtar_turu_sayilir(sir):
    kayitlar = ["metin", 42, None, ["liste"], {}, {"Secret": HEX32}, {"RuleID": ""}, {"RuleID": None}]
    k = sir.katmanla(kayitlar)
    assert k == {"anahtar_turu": len(kayitlar), "entropi": 0, "suzulen": 0}


def test_katmanla_bos_rule_id_suzulmez(sir):
    k = sir.katmanla([{"RuleID": "", "Secret": HEX32, "Match": "x", "File": "yarn.lock"}])
    assert k == {"anahtar_turu": 1, "entropi": 0, "suzulen": 0}


# ------------------------------------------------- sahte gitleaks düzeneği

SAHTE_BETIK = '''\
import json
import os
import sys

args = sys.argv[1:]
with open(os.environ["SAHTE_ARGS"], "w", encoding="utf-8") as f:
    json.dump(args, f)
kaynak = os.environ.get("SAHTE_RAPOR")
if kaynak and "--report-path" in args:
    yol = args[args.index("--report-path") + 1]
    with open(kaynak, "r", encoding="utf-8") as src, open(yol, "w", encoding="utf-8") as dst:
        dst.write(src.read())
sys.exit(int(os.environ.get("SAHTE_KOD", "0")))
'''


class Sahte:
    def __init__(self, dizin, monkeypatch):
        self.dizin = dizin
        self.monkeypatch = monkeypatch
        self.args_dosyasi = dizin / "args.json"
        betik = dizin / "sahte_gitleaks.py"
        betik.write_text(SAHTE_BETIK, encoding="utf-8")
        if os.name == "nt":  # Windows sh betiğini doğrudan çalıştıramaz
            baslatici = dizin / "gl.cmd"
            baslatici.write_text(f'@"{sys.executable}" "{betik}" %*\r\n', encoding="utf-8")
        else:
            baslatici = dizin / "gl"
            baslatici.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{betik}" "$@"\n', encoding="utf-8")
        baslatici.chmod(0o755)
        self.baslatici = baslatici
        monkeypatch.setenv("GITLEAKS", str(baslatici))
        monkeypatch.setenv("SAHTE_ARGS", str(self.args_dosyasi))
        monkeypatch.delenv("SAHTE_RAPOR", raising=False)

    def ayarla(self, kod, rapor=None, ham=None):
        """rapor: JSON'a çevrilecek nesne; ham: dosyaya olduğu gibi yazılacak metin."""
        self.monkeypatch.setenv("SAHTE_KOD", str(kod))
        if rapor is not None or ham is not None:
            kaynak = self.dizin / "rapor_kaynak.json"
            kaynak.write_text(ham if ham is not None else json.dumps(rapor), encoding="utf-8")
            self.monkeypatch.setenv("SAHTE_RAPOR", str(kaynak))
        else:
            self.monkeypatch.delenv("SAHTE_RAPOR", raising=False)

    def argumanlar(self):
        return json.loads(self.args_dosyasi.read_text(encoding="utf-8"))


@pytest.fixture
def sahte(tmp_path, monkeypatch):
    arac = tmp_path / "arac"
    arac.mkdir()
    return Sahte(arac, monkeypatch)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "taranan"
    r.mkdir()
    return r


# ----------------------------------------------------------- gitleaks_tara


def test_arac_yok_zorunlu_degil(sir, repo, monkeypatch):
    monkeypatch.setenv("GITLEAKS", "gitleaks-olmayan-arac-xyz")
    assert sir.gitleaks_tara(repo, False) == (
        "yok", "gitleaks kurulu değil, sır taraması yapılmadı", None)


def test_arac_yok_zorunlu(sir, gecmis_hatasi, repo, monkeypatch):
    monkeypatch.setenv("GITLEAKS", "gitleaks-olmayan-arac-xyz")
    with pytest.raises(gecmis_hatasi) as hata:
        sir.gitleaks_tara(repo, True)
    assert "gitleaks kurulu değil" in str(hata.value)


def test_cikis_0_temiz(sir, repo, sahte):
    sahte.ayarla(0)
    durum, aciklama, k = sir.gitleaks_tara(repo, False)
    assert (durum, aciklama, k) == ("temiz", "gitleaks temiz", BOS)


def test_cikis_3_anahtar_turu_bulgu(sir, repo, sahte):
    sahte.ayarla(3, [kayit(rule="aws-access-token"), kayit(), ozet(HEX32)])
    durum, _, k = sir.gitleaks_tara(repo, False)
    assert durum == "bulgu"
    assert k == {"anahtar_turu": 1, "entropi": 1, "suzulen": 1}


def test_cikis_3_yalniz_entropi_bulgu(sir, repo, sahte):
    sahte.ayarla(3, [kayit()])
    durum, _, k = sir.gitleaks_tara(repo, False)
    assert durum == "bulgu"
    assert k == {"anahtar_turu": 0, "entropi": 1, "suzulen": 0}


def test_cikis_3_yalniz_suzulenler_temiz(sir, repo, sahte):
    sahte.ayarla(3, [ozet(HEX32), ozet("sha512-" + "Zm9v" * 4, "integrity"),
                     ozet(HEX64, "cache_hash")])
    durum, _, k = sir.gitleaks_tara(repo, False)
    assert durum == "temiz"
    assert k == {"anahtar_turu": 0, "entropi": 0, "suzulen": 3}
    assert k["suzulen"] > 0


def test_cikis_3_rapor_yazilmamis_guvenli_taraf(sir, repo, sahte):
    sahte.ayarla(3)
    durum, _, k = sir.gitleaks_tara(repo, False)
    assert durum == "bulgu" and k is None


@pytest.mark.parametrize("ham", ["{bozuk json", "", '{"RuleID": "x"}', '"metin"', "42", "[]"])
def test_cikis_3_gecersiz_rapor_guvenli_taraf(sir, repo, sahte, ham):
    sahte.ayarla(3, ham=ham)
    durum, _, k = sir.gitleaks_tara(repo, False)
    assert durum == "bulgu" and k is None


@pytest.mark.parametrize("kod", [1, 2, 4, 126])
def test_baska_cikis_kodu_hata(sir, gecmis_hatasi, repo, sahte, kod):
    sahte.ayarla(kod, [kayit(rule="aws-access-token", secret=SIR_DEGERI)])
    with pytest.raises(gecmis_hatasi) as hata:
        sir.gitleaks_tara(repo, False)
    assert str(hata.value) == f"gitleaks hata ({kod})"
    assert SIR_DEGERI not in str(hata.value)


def test_cagri_argumanlari(sir, repo, sahte):
    sahte.ayarla(0)
    sir.gitleaks_tara(repo, False)
    a = sahte.argumanlar()
    assert a[0] == "detect"
    assert a[a.index("--source") + 1] == str(repo)
    assert "--no-git" in a
    assert "--no-banner" in a
    assert a[a.index("--exit-code") + 1] == "3"
    assert a[a.index("--report-format") + 1] == "json"
    yol = a[a.index("--report-path") + 1]
    assert yol and not yol.startswith("--")
    assert "--redact" not in a


def test_rapor_dosyasi_donuste_diskte_kalmaz(sir, repo, sahte):
    for kod, rapor in [(0, None), (3, [kayit(rule="aws-access-token")]), (3, [ozet(HEX32)])]:
        sahte.ayarla(kod, rapor)
        sir.gitleaks_tara(repo, False)
        yol = sahte.argumanlar()[sahte.argumanlar().index("--report-path") + 1]
        assert not os.path.exists(yol)
        assert not os.path.exists(os.path.dirname(yol)) or not os.listdir(os.path.dirname(yol))


def test_rapor_dosyasi_hata_durumunda_da_kalmaz(sir, gecmis_hatasi, repo, sahte):
    sahte.ayarla(1, [kayit(rule="aws-access-token")])
    with pytest.raises(gecmis_hatasi):
        sir.gitleaks_tara(repo, False)
    yol = sahte.argumanlar()[sahte.argumanlar().index("--report-path") + 1]
    assert not os.path.exists(yol)


def test_sir_degeri_hicbir_yere_yazilmaz(sir, gecmis_hatasi, repo, sahte, capsys):
    rapor = [
        kayit(rule="aws-access-token", secret=SIR_DEGERI, match="k = " + SIR_DEGERI),
        kayit(secret=SIR_DEGERI, match="v = " + SIR_DEGERI),
    ]
    sahte.ayarla(3, rapor)
    durum, aciklama, k = sir.gitleaks_tara(repo, False)
    assert durum == "bulgu"
    assert k == {"anahtar_turu": 1, "entropi": 1, "suzulen": 0}
    assert SIR_DEGERI not in aciklama
    for sayi in k.values():
        assert str(sayi) in aciklama
    cikti = capsys.readouterr()
    assert SIR_DEGERI not in cikti.out and SIR_DEGERI not in cikti.err

    sahte.ayarla(1, rapor)
    with pytest.raises(gecmis_hatasi) as hata:
        sir.gitleaks_tara(repo, False)
    assert SIR_DEGERI not in str(hata.value)
    cikti = capsys.readouterr()
    assert SIR_DEGERI not in cikti.out and SIR_DEGERI not in cikti.err


def test_aciklama_uc_sayiyi_icerir(sir, repo, sahte):
    # Birbirinden ayırt edilir sayılar: 3 anahtar türü, 5 entropi, 7 süzülen.
    rapor = ([kayit(rule="aws-access-token") for _ in range(3)]
             + [kayit(secret=ENTROPI_DEGERI + str(i)) for i in range(5)]
             + [ozet(HEX32) for _ in range(7)])
    sahte.ayarla(3, rapor)
    durum, aciklama, k = sir.gitleaks_tara(repo, False)
    assert durum == "bulgu"
    assert k == {"anahtar_turu": 3, "entropi": 5, "suzulen": 7}
    for sayi in ("3", "5", "7"):
        assert sayi in aciklama


def test_temiz_sonucta_da_aciklama_sayilari_icerir(sir, repo, sahte):
    sahte.ayarla(3, [ozet(HEX32) for _ in range(4)])
    durum, aciklama, k = sir.gitleaks_tara(repo, False)
    assert durum == "temiz"
    assert k == {"anahtar_turu": 0, "entropi": 0, "suzulen": 4}
    assert "4" in aciklama
    assert HEX32 not in aciklama


def test_cikis_3_asiri_ic_ice_json_guvenli_taraf(sir, repo, sahte):
    sahte.ayarla(3, ham="[" * 100000)
    durum, _, k = sir.gitleaks_tara(repo, False)
    assert durum == "bulgu" and k is None
