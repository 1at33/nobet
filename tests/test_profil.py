"""Profiller ayar.toml sağlayıcılarından türer. Kodda hazır tablo yoktur."""
import ast
import re
from pathlib import Path

import pytest

from nobet import profil as profil_mod
from nobet.ayar import Saglayici
from nobet.profil import (
    AYNI_SAGLAYICI,
    ProfilHatasi,
    ayni_firma_mi,
    profil_coz,
    profil_tablosu,
    profiller_kur,
    reviewer_adaylari,
    reviewer_durumu,
)


def _s(ad, tur, modeller, roller=("yazici", "reviewer"), komut="", url=""):
    if tur == "cli":
        komut = komut or ad
    else:
        url = url or "http://127.0.0.1:9/v1"
    return Saglayici(ad, tur, komut, url, "", tuple(modeller), frozenset(roller))


def _tablo(*saglayicilar):
    return profiller_kur(saglayicilar)


def test_kaynakta_hazir_tablo_yok():
    """Eski profil tablosu geri gelirse bu test düşer."""
    metin = Path(profil_mod.__file__).read_text(encoding="utf-8")
    assert "PROFILLER" not in metin
    # Sağlayıcı listesi tutmadan model kimliği biçimini yakalar: harf, isteğe bağlı tire, rakam.
    model_bicimi = re.compile(r"^(?:gpt-|claude|grok|llama|[a-z]+-?\d)", re.IGNORECASE)
    sabitler = (dugum.value for dugum in ast.walk(ast.parse(metin)) if isinstance(dugum, ast.Constant)
                and isinstance(dugum.value, str))
    assert not any(model_bicimi.match(sabit) for sabit in sabitler)


def test_profil_adi_model_metnidir():
    """Profil adı, kullanıcının yazdığı model metnidir."""
    tablo = _tablo(_s("ornek", "cli", ["model-a"]))
    assert set(tablo) == {"model-a"}
    assert tablo["model-a"].firma == "ornek"
    assert "x-model-a" not in tablo


def test_ayni_ve_farkli_firma():
    tablo = _tablo(_s("bulut", "api", ["a", "b"]), _s("yerel", "yerel", ["c"]))
    assert ayni_firma_mi("a", "b", tablo) is True
    assert ayni_firma_mi("a", "c", tablo) is False
    with pytest.raises(ProfilHatasi, match="yok-boyle"):
        ayni_firma_mi("a", "yok-boyle", tablo)


def test_bilinmeyen_profil():
    with pytest.raises(ProfilHatasi, match="yok-boyle"):
        profil_coz("yok-boyle", {})


def test_capraz_saglayici_tercih_edilir():
    tablo = _tablo(
        _s("bulut", "api", ["yazici-model", "bulut-b"]),
        _s("cli", "cli", ["cli-model"]),
    )
    aday = reviewer_adaylari("yazici-model", tablo)
    assert aday == ["cli-model"]
    assert "bulut-b" not in aday


def test_tek_saglayicida_baska_model():
    tablo = _tablo(_s("yerel", "yerel", ["kucuk", "buyuk"]))
    assert reviewer_durumu([_s("yerel", "yerel", ["kucuk", "buyuk"])])[0] == "ayni"
    assert reviewer_adaylari("kucuk", tablo) == ["buyuk"]
    assert AYNI_SAGLAYICI == "aynı sağlayıcı"


def test_ikinci_model_yok():
    bir = [_s("yerel", "yerel", ["tek"])]
    assert reviewer_durumu(bir) == ("yok", "ikinci model yok")
    assert reviewer_durumu(()) == ("yok", "model yok")
    assert reviewer_adaylari("tek", _tablo(*bir)) == []


def test_tabloda_secilemez_satir_yok():
    tablo = _tablo(_s("bulut", "api", ["a"]), _s("yerel", "yerel", ["b"], roller=("yazici",)))
    satirlar = profil_tablosu(tablo).split("\n")
    assert [s.split()[0] for s in satirlar] == ["a", "b"]
    assert satirlar == ["a bulut a", "b yerel b"]
    assert all(not s.endswith("[seçilemez]") for s in satirlar)
