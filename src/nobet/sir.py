"""gitleaks raporunu iki katmana ayırır: anahtar türü ve entropi.

Katman 1 (anahtar türü): belirli gitleaks kuralları; hiçbir koşulda süzülmez.
Katman 2 (entropi): genel `generic-api-key` kuralı. Bir kayıt yalnız üç koşulun hepsi
sağlanırsa süzülür: (1) `Secret` özet biçimindedir (32+ onaltılık ya da sha*- bütünlük
öneki), (2) `Match` içinde sözcük sınırlı bir özet bağlamı geçer (hash, digest, sha256,
integrity, checksum vb.), (3) `Match` içinde kimlik bilgisi sözcüğü geçmez. Biri eksikse
kayıt entropi bulgusudur; şüphede bulgu sayılır. Dosya adı süzmede kullanılmaz. Sır değeri
hiçbir yere yazılmaz: yalnız sayılar döner.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .gecmis import GecmisHatasi

ENTROPI_KURALI = "generic-api-key"
ONALTILIK = re.compile(r"[0-9a-fA-F]{32,}")
OZET_ONEKLERI = ("sha1-", "sha256-", "sha384-", "sha512-")
BAGLAM = re.compile(
    r"(?<![a-z])(?:sha1|sha224|sha256|sha384|sha512|sha|md5|hash|digest|integrity|checksum"
    r"|fingerprint)(?![a-z])",
    re.IGNORECASE | re.ASCII,
)
SIR_SOZCUKLERI = ("secret", "token", "passw", "credential", "auth")


def _suzulur(kayit):
    """Entropi katmanındaki kayıt yalnız üç koşul birlikte sağlanırsa gürültüdür."""
    gizli, eslesme = kayit.get("Secret"), kayit.get("Match")
    if not isinstance(gizli, str) or not isinstance(eslesme, str):
        return False
    if not (ONALTILIK.fullmatch(gizli) or gizli.startswith(OZET_ONEKLERI)):
        return False
    if not BAGLAM.search(eslesme):
        return False
    kucuk = eslesme.casefold()
    return not any(s in kucuk for s in SIR_SOZCUKLERI)


def katmanla(kayitlar):
    """Kayıt listesini sayar: {'anahtar_turu', 'entropi', 'suzulen'}."""
    sayi = {"anahtar_turu": 0, "entropi": 0, "suzulen": 0}
    for kayit in kayitlar:
        kural = kayit.get("RuleID") if isinstance(kayit, dict) else None
        if kural != ENTROPI_KURALI:
            sayi["anahtar_turu"] += 1
        elif _suzulur(kayit):
            sayi["suzulen"] += 1
        else:
            sayi["entropi"] += 1
    return sayi


def _aciklama(k):
    return (f"gitleaks: {k['anahtar_turu']} anahtar türü, {k['entropi']} entropi, "
            f"{k['suzulen']} süzülen")


def gitleaks_tara(repo, zorunlu):
    """(durum, açıklama, katmanlar). durum: 'temiz' | 'bulgu' | 'yok'. Hata GecmisHatasi."""
    gl = shutil.which(os.environ.get("GITLEAKS", "gitleaks"))
    if not gl:
        if zorunlu:
            raise GecmisHatasi("gitleaks kurulu değil (--gitleaks-zorunlu)")
        return "yok", "gitleaks kurulu değil, sır taraması yapılmadı", None
    with tempfile.TemporaryDirectory() as gecici:
        rapor = Path(gecici) / "rapor.json"
        r = subprocess.run(
            [gl, "detect", "--source", str(repo), "--no-git", "--no-banner", "--exit-code", "3",
             "--report-format", "json", "--report-path", str(rapor)],
            capture_output=True, check=False)
        if r.returncode == 0:
            k = {"anahtar_turu": 0, "entropi": 0, "suzulen": 0}
            return "temiz", "gitleaks temiz", k
        if r.returncode != 3:
            raise GecmisHatasi(f"gitleaks hata ({r.returncode})")
        try:
            kayitlar = json.loads(rapor.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError):
            kayitlar = None
    genel = "gitleaks bulgu verdi, rapor çözümlenemedi (ayrıntı için gitleaks'i elle çalıştırın)"
    if not isinstance(kayitlar, list) or not kayitlar:
        return "bulgu", genel, None
    k = katmanla(kayitlar)
    durum = "bulgu" if k["anahtar_turu"] + k["entropi"] > 0 else "temiz"
    return durum, _aciklama(k), k
