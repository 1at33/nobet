"""Kullanıcının sağlayıcıları: yazıcı ve reviewer profilleri buradan türer.

Dosya: NOBET_AYAR (dosya yolu) > $XDG_CONFIG_HOME/nobet/ayar.toml > ~/.config/nobet/ayar.toml.
Windows: %APPDATA%\\nobet\\ayar.toml. Standart kütüphane (tomllib); bağımlılık yok.

Kodda sağlayıcı ya da model adı varsayılmaz. Bilinmeyen anahtar ValueError'dur.
Anahtar değeri yazılmaz, yalnız ortam değişkeninin adı (anahtar_env).
"""
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from nobet.gizli import gizli_mi

IZINLI = frozenset({"saglayici"})
_SAG_TUR = frozenset({"cli", "api", "yerel"})
_ROLLER = frozenset({"yazici", "reviewer"})
_SAG_ALAN = frozenset({"ad", "tur", "komut", "taban_url", "anahtar_env", "modeller", "roller"})
_ENV_AD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class Saglayici:
    """Kullanıcının bir aboneliği. anahtar_env değişkenin adıdır; değer tutulmaz."""

    ad: str
    tur: str
    komut: str
    taban_url: str
    anahtar_env: str
    modeller: tuple
    roller: frozenset


def varsayilan_dosya(ev, env):
    """Yapılandırma dosyasının varsayılan yolu. Dosyanın varlığı ayrı denetlenir."""
    if sys.platform == "win32":
        kok = Path(env["APPDATA"]) if env.get("APPDATA") else ev / "AppData" / "Roaming"
        return kok / "nobet" / "ayar.toml"
    kok = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else ev / ".config"
    return kok / "nobet" / "ayar.toml"


def _sir_degil(metin, alan):
    if gizli_mi(metin):
        raise ValueError(f"{alan} anahtar değeri olamaz; yalnız değişkenin adı yazılır")


def _zorunlu_metin(deger, alan):
    if not isinstance(deger, str) or not deger.strip():
        raise ValueError(f"{alan} metin olmalı")
    metin = deger.strip()
    _sir_degil(metin, alan)
    return metin


def _istege_bagli(ham, alan):
    if alan not in ham or ham[alan] is None:
        return ""
    return _zorunlu_metin(ham[alan], alan)


def _anahtar_alani(ham):
    if "anahtar_env" not in ham:
        return ""
    deger = ham.get("anahtar_env")
    if not isinstance(deger, str) or not deger.strip():
        raise ValueError("anahtar_env boş olamaz")
    metin = deger.strip()
    _sir_degil(metin, "anahtar_env")
    if not _ENV_AD.fullmatch(metin):
        raise ValueError("anahtar_env ortam değişkeninin adı olmalı, değeri değil")
    return metin


def _metin_listesi(deger, alan):
    if not isinstance(deger, list) or not deger:
        raise ValueError(f"{alan} boş olmayan liste olmalı")
    return tuple(_zorunlu_metin(oge, f"{alan}[{i}]") for i, oge in enumerate(deger))


def _roller(deger):
    if deger is None:
        return frozenset(_ROLLER)
    if not isinstance(deger, list) or not deger:
        raise ValueError("roller boş olmayan liste olmalı")
    roller = []
    for r in deger:
        if not isinstance(r, str) or r.strip() not in _ROLLER:
            raise ValueError("roller yalnız yazici ve reviewer")
        roller.append(r.strip())
    return frozenset(roller)


def _saglayici(ham, sira):
    if not isinstance(ham, dict):
        raise ValueError(f"saglayici[{sira}] tablo olmalı")  # noqa: TRY004 - yapılandırma sözleşmesi
    ekstra = sorted(set(ham) - _SAG_ALAN)
    if ekstra:
        raise ValueError("bilinmeyen sağlayıcı anahtarı: " + ", ".join(ekstra))
    ad = _zorunlu_metin(ham.get("ad"), "saglayici.ad")
    tur = ham.get("tur")
    if not isinstance(tur, str) or tur.strip() not in _SAG_TUR:
        raise ValueError("saglayici.tur cli, api ya da yerel olmalı")
    tur = tur.strip()
    komut = _istege_bagli(ham, "komut")
    url = _istege_bagli(ham, "taban_url")
    if tur == "cli":
        if not komut:
            raise ValueError(f"{ad}: tur=cli komut ister")
        if url:
            raise ValueError(f"{ad}: tur=cli taban_url almaz")
    else:
        if not url:
            raise ValueError(f"{ad}: tur={tur} taban_url ister")
        if komut:
            raise ValueError(f"{ad}: tur={tur} komut almaz")
    return Saglayici(ad, tur, komut, url, _anahtar_alani(ham),
                     _metin_listesi(ham.get("modeller"), "modeller"),
                     _roller(ham.get("roller") if "roller" in ham else None))


def saglayicilari_ayikla(veri):
    """[[saglayici]] tablolarını doğrula. Ad ve model tekrarı reddedilir."""
    if not isinstance(veri, dict):
        raise ValueError("ayar tablo olmalı")  # noqa: TRY004 - yapılandırma sözleşmesi
    ekstra = sorted(set(veri) - IZINLI)
    if ekstra:
        raise ValueError("bilinmeyen ayar anahtarı: " + ", ".join(ekstra))
    ham = veri.get("saglayici", [])
    if not isinstance(ham, list):
        raise ValueError("saglayici liste olmalı")  # noqa: TRY004 - yapılandırma sözleşmesi
    saglayicilar = tuple(_saglayici(s, i) for i, s in enumerate(ham))
    adlar, modeller = set(), set()
    for s in saglayicilar:
        if s.ad in adlar:
            raise ValueError(f"sağlayıcı adı tekrar: {s.ad}")
        adlar.add(s.ad)
        for m in s.modeller:
            if m in modeller:
                raise ValueError(f"model birden fazla sağlayıcıda: {m}")
            modeller.add(m)
    return saglayicilar


def toml_oku(yol):
    """Ayar dosyasını oku ve doğrula. Okunamayan ya da bozuk dosya ValueError."""
    yol = Path(yol)
    try:
        with yol.open("rb") as dosya:
            veri = tomllib.load(dosya)
    except FileNotFoundError as exc:
        raise ValueError(f"ayar dosyası yok: {yol}") from exc
    except (tomllib.TOMLDecodeError, UnicodeError) as exc:
        raise ValueError(f"ayar.toml bozuk: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"ayar.toml okunamadı: {exc.strerror or type(exc).__name__}") from exc
    saglayicilari_ayikla(veri)
    return veri


def saglayicilar(dosya=None, env=None, ev=None):
    """Sağlayıcıları çöz: dosya > NOBET_AYAR > varsayılan. Varsayılan dosya yoksa boş."""
    env = os.environ if env is None else env
    ev = Path.home() if ev is None else Path(ev)
    if dosya is not None:
        return saglayicilari_ayikla(toml_oku(dosya))
    env_dosya = env.get("NOBET_AYAR")
    if env_dosya is not None:
        metin = env_dosya.strip() if isinstance(env_dosya, str) else ""
        if not metin:
            raise ValueError("NOBET_AYAR boş olamaz")
        return saglayicilari_ayikla(toml_oku(Path(metin).expanduser()))
    yol = varsayilan_dosya(ev, env)
    if yol.is_file():
        return saglayicilari_ayikla(toml_oku(yol))
    return ()
