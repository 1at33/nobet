"""ayar.toml: sağlayıcılar yalnız kullanıcının dosyasından gelir, anahtar değeri reddedilir."""
import sys

import pytest

from nobet.ayar import saglayicilar, varsayilan_dosya
from nobet.gizli import gizli_mi

IKI = (
    '[[saglayici]]\nad = "bulut"\ntur = "api"\ntaban_url = "https://ornek.example/v1"\n'
    'anahtar_env = "BULUT_KEY"\nmodeller = ["b1", "b2"]\n\n'
    '[[saglayici]]\nad = "yerel"\ntur = "cli"\nkomut = "yerel-cli"\nmodeller = ["y1"]\nroller = ["reviewer"]\n'
)


def _yaz(tmp_path, metin, ad="ayar.toml"):
    dosya = tmp_path / ad
    dosya.write_text(metin, encoding="utf-8")
    return dosya


def test_dosya_yoksa_bos(tmp_path):
    assert saglayicilar(env={}, ev=tmp_path) == ()


def test_iki_saglayici_okunur(tmp_path):
    s = saglayicilar(dosya=_yaz(tmp_path, IKI), env={}, ev=tmp_path)
    assert [x.ad for x in s] == ["bulut", "yerel"]
    assert s[0].anahtar_env == "BULUT_KEY" and s[0].roller == frozenset({"yazici", "reviewer"})
    assert s[1].roller == frozenset({"reviewer"}) and s[1].komut == "yerel-cli"


def test_env_dosyayi_secer_cli_envi_eger(tmp_path):
    env_dosya = _yaz(tmp_path, IKI, "env.toml")
    cli_dosya = _yaz(tmp_path, '[[saglayici]]\nad = "c"\ntur = "cli"\nkomut = "c"\nmodeller = ["c1"]\n', "cli.toml")
    assert [x.ad for x in saglayicilar(env={"NOBET_AYAR": str(env_dosya)}, ev=tmp_path)] == ["bulut", "yerel"]
    assert [x.ad for x in saglayicilar(dosya=cli_dosya, env={"NOBET_AYAR": str(env_dosya)}, ev=tmp_path)] == ["c"]
    with pytest.raises(ValueError, match="NOBET_AYAR"):
        saglayicilar(env={"NOBET_AYAR": " "}, ev=tmp_path)


def test_varsayilan_yol(tmp_path):
    yol = varsayilan_dosya(tmp_path, {"XDG_CONFIG_HOME": str(tmp_path / "x"), "APPDATA": str(tmp_path / "a")})
    beklenen = (tmp_path / "a") if sys.platform == "win32" else (tmp_path / "x")
    assert yol == beklenen / "nobet" / "ayar.toml"


def test_anahtar_degeri_reddedilir(tmp_path):
    gorunen = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
    assert gizli_mi(gorunen)
    dosya = _yaz(tmp_path, '[[saglayici]]\nad = "bulut"\ntur = "api"\n'
                 f'taban_url = "https://ornek.example/v1"\nanahtar_env = "{gorunen}"\nmodeller = ["m"]\n')
    with pytest.raises(ValueError, match="anahtar"):
        saglayicilar(dosya=dosya, env={}, ev=tmp_path)


@pytest.mark.parametrize(("metin", "mesaj"), [
    ('gomme = {}\n', "bilinmeyen ayar anahtarı"),
    ('[[saglayici]]\nad = "a"\ntur = "cli"\nmodeller = ["m"]\n', "komut ister"),
    ('[[saglayici]]\nad = "a"\ntur = "api"\nmodeller = ["m"]\n', "taban_url ister"),
    ('[[saglayici]]\nad = "a"\ntur = "uydu"\nkomut = "a"\nmodeller = ["m"]\n', "tur"),
    ('[[saglayici]]\nad = "a"\ntur = "cli"\nkomut = "a"\nmodeller = []\n', "modeller"),
    ('[[saglayici]]\nad = "a"\ntur = "cli"\nkomut = "a"\nmodeller = ["m"]\nroller = ["hakem"]\n', "roller"),
    (('[[saglayici]]\nad = "a"\ntur = "cli"\nkomut = "a"\nmodeller = ["m"]\n'
      '[[saglayici]]\nad = "a"\ntur = "cli"\nkomut = "b"\nmodeller = ["n"]\n'), "adı tekrar"),
    (('[[saglayici]]\nad = "a"\ntur = "cli"\nkomut = "a"\nmodeller = ["m"]\n'
      '[[saglayici]]\nad = "b"\ntur = "cli"\nkomut = "b"\nmodeller = ["m"]\n'), "birden fazla"),
    ('[[saglayici]\n', "bozuk"),
])
def test_gecersiz_ayar_reddedilir(tmp_path, metin, mesaj):
    with pytest.raises(ValueError, match=mesaj):
        saglayicilar(dosya=_yaz(tmp_path, metin), env={}, ev=tmp_path)


def test_profiller_ayardan_turer(tmp_path, monkeypatch):
    from nobet.profil import profil_tablosu, reviewer_adaylari
    monkeypatch.setenv("NOBET_AYAR", str(_yaz(tmp_path, IKI)))
    assert reviewer_adaylari("b1") == ["y1"]
    assert profil_tablosu().split("\n") == ["b1 bulut b1", "b2 bulut b2", "y1 yerel y1"]
