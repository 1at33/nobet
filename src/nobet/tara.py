"""Çalışma ağacında kişisel veri ve sır denetimi (commit öncesi ve yayın öncesi).

`nobet-gecmis` commit'lenmiş her şeye bakar; bu araç henüz commit'lenmemiş olanı da görür:
izlenen dosyaların diskteki hali ve `.gitignore` dışındaki izlenmeyen dosyalar. Aranan:
geçerli T.C. kimlik no, izinli olmayan e-posta, ad listesindeki adlar ve kullanıcı adı taşıyan
ev dizini yolları (`C:\\Users\\<ad>`, `/home/<ad>`, `/Users/<ad>`). gitleaks kuruluysa sır
taraması da yapılır; `--gitleaks-zorunlu` ile kurulu olmaması hatadır.
gitleaks raporu iki katmana ayrılır (`nobet.sir`): belirli anahtar türleri her zaman bulgudur,
genel entropi kuralından gelen sağlama özeti gürültüsü süzülür.

Çıktı bulgunun değerini asla yazmaz, yalnız yerini ve türünü.
Çıkış kodu: 0 temiz, 1 bulgu, 2 kullanım ya da araç hatası.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .gecmis import (
    Bulgu,
    GecmisHatasi,
    _ad_desenleri,
    ayir,
    git,
    kisisel_adlar,
    metin_bulgulari,
)
from .sir import gitleaks_tara

DOSYA_SINIR = 5_000_000
# Ev dizini kökü ve ardından gelen kullanıcı adı; ortak yer tutucular izinlidir.
EV_YOLU = re.compile(
    r"(?:\b[A-Za-z]:[\\/]+Users[\\/]+|(?<![\w.])/home/|(?<![\w.])/Users/)([A-Za-z0-9][\w.-]*)",
)
IZINLI_EV = frozenset({
    "runner", "user", "kullanici", "kullanıcı", "ornek", "örnek", "example", "username", "public",
    "shared", "default", "you", "sen", "ad", "x", "me",
})


def ev_yolu_var(metin):
    """Yer tutucu olmayan bir kullanıcı adıyla ev dizini yolu geçiyor mu."""
    return any(m.group(1).casefold() not in IZINLI_EV for m in EV_YOLU.finditer(metin))


def dosyalar(repo):
    """İzlenen ve (.gitignore dışındaki) izlenmeyen dosyalar, repo köküne göre."""
    ham = git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return sorted({p for p in ham.decode("utf-8", "replace").split("\0") if p})


def agac_tara(repo, adlar):
    """(bulgular, atlanan yollar). Dosyalar diskteki halleriyle okunur."""
    repo = Path(repo)
    desenler = _ad_desenleri(adlar)
    bulgu, atlanan = set(), []
    for yol in dosyalar(repo):
        tam = repo / yol
        try:
            if tam.is_symlink() or not tam.is_file():
                continue
            if tam.stat().st_size > DOSYA_SINIR:
                atlanan.append(yol)
                continue
            ham = tam.read_bytes()
        except OSError:
            atlanan.append(yol)
            continue
        ikili = b"\0" in ham[:8000]
        metin = ham.decode("latin-1" if ikili else "utf-8", "replace")
        yer = f"dosya {yol}"
        bulgu |= metin_bulgulari(yer, metin, desenler, ikili=ikili)
        if not ikili and ev_yolu_var(metin):
            bulgu.add(Bulgu(yer, "ev dizini yolu"))
        if ev_yolu_var(yol):
            bulgu.add(Bulgu(f"yol {yol}", "ev dizini yolu"))
    return sorted(bulgu), atlanan


def ayristir(argv=None):
    p = argparse.ArgumentParser(prog="nobet-tara", description=__doc__.splitlines()[0])
    p.add_argument("--repo", default=".", help="yerel repo (varsayılan: bulunulan dizin)")
    p.add_argument("--adlar", help="her satırı bir ad olan dosya (repo dışında tutulur)")
    p.add_argument("--adlar-zorunlu", action="store_true", help="ad listesi yoksa temiz sayma, 2 ile çık")
    p.add_argument("--gitleaks-zorunlu", action="store_true", help="gitleaks yoksa temiz sayma, 2 ile çık")
    p.add_argument("--json", action="store_true", help="sonucu JSON bas")
    return p.parse_args(argv)


def calistir(a):
    if a.adlar:
        if not Path(a.adlar).is_file():
            raise GecmisHatasi("--adlar dosyası okunamıyor")
        adlar = kisisel_adlar(a.adlar)
    else:
        adlar = kisisel_adlar()
    if not adlar and a.adlar_zorunlu:
        raise GecmisHatasi("ad listesi yok ya da boş (--adlar-zorunlu)")
    bulgular, atlanan = agac_tara(a.repo, adlar)
    sir, sir_aciklama, sir_katmanlari = gitleaks_tara(a.repo, a.gitleaks_zorunlu)
    bulgular, uyarilar = ayir(bulgular)
    temiz = not bulgular and sir != "bulgu"
    if a.json:
        print(json.dumps({"bulgular": [{"yer": b.yer, "tur": b.tur} for b in bulgular],
                          "uyarilar": [{"yer": b.yer, "tur": b.tur} for b in uyarilar],
                          "atlanan": atlanan, "ad_taramasi": bool(adlar), "sir_taramasi": sir,
                          "sir_katmanlari": sir_katmanlari},
                         ensure_ascii=False))
    else:
        for b in bulgular:
            print(f"{b.tur}: {b.yer}")
        for b in uyarilar:
            print(f"uyarı: {b.tur}: {b.yer}")
        if atlanan:
            print(f"uyarı: {len(atlanan)} dosya taranmadı: {', '.join(atlanan[:5])}")
        if not adlar:
            print("uyarı: ad listesi yok, ad taraması yapılmadı")
        print(sir_aciklama)
        print(f"{len(bulgular)} bulgu")
    return 0 if temiz else 1


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        return calistir(ayristir(argv))
    except GecmisHatasi as hata:
        print(f"hata: {hata}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
