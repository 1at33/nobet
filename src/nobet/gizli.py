"""Alt ajana giden ortamın sır temizleme kararları; ortamı okumayan ve değiştirmeyen işlevler."""

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping

_KALIP = re.compile(
    r"(?<![A-Za-z0-9])(?:sk-|ghp_|gho_|ghs_|ghu_|github_pat_|"
    r"xoxb-|xoxp-|xoxa-|glpat-)[A-Za-z0-9_-]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|AIza[0-9A-Za-z_-]{35}"
    r"|-----BEGIN [^\r\n]*PRIVATE KEY-----"
)
_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_DEGER_KARAKTERLERI = re.compile(r"[A-Za-z0-9+/=_-]+")
_HARF = re.compile(r"[A-Za-z]")
_RAKAM = re.compile(r"[0-9]")
_GECERLI_AD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_AD_KURALI = re.compile(r"key|token|secret|passw|credential|auth", re.IGNORECASE)
# git'in ortamdan ayar enjeksiyonu: GIT_CONFIG_COUNT + GIT_CONFIG_KEY_n/VALUE_n birlikte anlamlıdır.
_GIT_AYAR = re.compile(r"GIT_CONFIG_(?:COUNT|KEY_\d+|VALUE_\d+)")


class GecersizAd(ValueError):
    """Sır taşıyan ortam değişkeninin adı geçerli bir tanımlayıcı değil."""


def gizli_mi(deger: str) -> bool:
    """Değeri kalıp ve karakter dağılımıyla sınıflandır; yalnız bool döndür."""
    if _KALIP.search(deger):
        return True
    if _UUID.fullmatch(deger):
        return False
    if (
        len(deger) < 32
        or deger.startswith("/")
        or not _DEGER_KARAKTERLERI.fullmatch(deger)
    ):
        return False
    if not _HARF.search(deger) or not _RAKAM.search(deger):
        return False
    uzunluk = len(deger)
    entropi = -sum(
        (adet / uzunluk) * math.log2(adet / uzunluk)
        for adet in Counter(deger).values()
    )
    return entropi >= 4.0


def silinecekler(ortam: Mapping[str, str], izin: Iterable[str] = ()) -> list[str]:
    """İzin verilenleri atlayıp silinecek adları ortam sırasıyla döndür."""
    izinli_adlar = set(izin)
    sonuc = []
    for ad, deger in ortam.items():
        if ad in izinli_adlar:
            continue
        deger_gizli = gizli_mi(deger)
        ad_gecerli = _GECERLI_AD.fullmatch(ad) is not None
        if deger_gizli and not ad_gecerli:
            raise GecersizAd("nobet: geçersiz ortam değişkeni adı")
        if deger_gizli or (ad_gecerli and _AD_KURALI.search(ad)):
            sonuc.append(ad)
    # KEY_n adı kuralla silinince COUNT kalırsa alt süreçteki her git çağrısı düşer; değerler de sır
    # taşıyabilir (ör. http.extraHeader). Ailenin bir üyesi silindiyse izinsiz bütün üyeleri silinir.
    if any(_GIT_AYAR.fullmatch(ad) for ad in sonuc):
        sonuc += [ad for ad in ortam if _GIT_AYAR.fullmatch(ad) and ad not in izinli_adlar and ad not in sonuc]
    return sonuc


def temiz_ortam(
    ortam: Mapping[str, str], izin: Iterable[str] = ()
) -> dict[str, str]:
    """Silinecek çiftleri çıkararak yeni bir dict üret; girdiyi değiştirme.

    Açıkça izin verilen değişkenler, değerleriyle birlikte kopyada korunur.
    """
    silinecek_adlar = set(silinecekler(ortam, izin))
    return {ad: deger for ad, deger in ortam.items() if ad not in silinecek_adlar}


_PARCA = re.compile(r"[A-Za-z0-9+/=_.:-]{16,}")


def maskele(metin: str, ortam: Mapping[str, str] | None = None) -> str:
    """Metindeki sır gibi görünen parçaları ve adı sır kuralına uyan değişkenlerin değerlerini `[gizli]` yap.

    Çıktı günlüğe yazılmadan önce kullanılır; en iyi çaba, tam koruma değildir.
    """
    for ad, deger in (ortam or {}).items():
        if deger and len(deger) >= 6 and _AD_KURALI.search(ad):
            metin = metin.replace(deger, "[gizli]")
    metin = _KALIP.sub("[gizli]", metin)
    return _PARCA.sub(lambda m: "[gizli]" if gizli_mi(m.group(0)) else m.group(0), metin)
