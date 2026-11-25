"""Yazıcı ve reviewer profilleri: kullanıcının ayar.toml sağlayıcılarından türer.

Kodda firma ya da model adı yoktur.
Çapraz sağlayıcı reviewer tercih edilir. Tek sağlayıcıda başka bir model reviewer olabilir.
"""
from dataclasses import dataclass, field

AYNI_SAGLAYICI = "aynı sağlayıcı"


@dataclass(frozen=True)
class Profil:
    ad: str
    firma: str
    model: str
    roller: frozenset = field(default_factory=frozenset)
    secilebilir: bool = True
    neden: str = ""


class ProfilHatasi(ValueError):
    """Bilinmeyen profil."""


def profiller_kur(saglayicilar) -> dict:
    """Sağlayıcı modelleri -> profil adı (model metni) -> Profil. Sıra sağlayıcı sırasıdır."""
    tablo = {}
    for s in saglayicilar:
        for model in s.modeller:
            tablo[model] = Profil(model, s.ad, model, frozenset(s.roller), True, "")
    return tablo


def _tablo(profiller):
    if profiller is not None:
        return profiller
    from nobet.ayar import saglayicilar
    return profiller_kur(saglayicilar())


def reviewer_durumu(saglayicilar):
    """('yok'|'ayni'|'capraz', neden). İkinci reviewer modeli yoksa ölçüt kapsam dışıdır."""
    reviewerlar = [(s.ad, m) for s in saglayicilar if "reviewer" in s.roller for m in s.modeller]
    if len(reviewerlar) < 2:
        if not any(s.modeller for s in saglayicilar):
            return "yok", "model yok"
        return "yok", "ikinci model yok"
    if len({firma for firma, _ in reviewerlar}) == 1:
        return "ayni", ""
    return "capraz", ""


def ayni_firma_mi(yazici: str, reviewer: str, profiller=None) -> bool:
    """İki profil adı aynı firmadansa True. Bilinmeyen ad -> ProfilHatasi."""
    tablo = _tablo(profiller)
    for ad in (yazici, reviewer):
        if ad not in tablo:
            raise ProfilHatasi(f"bilinmeyen profil: {ad}")
    return tablo[yazici].firma == tablo[reviewer].firma


def profil_coz(ad: str, profiller=None) -> Profil:
    """Adı Profil'e çevir. Ad yoksa ProfilHatasi, mesajda ad geçer."""
    tablo = _tablo(profiller)
    if ad not in tablo:
        raise ProfilHatasi(f"bilinmeyen profil: {ad}")
    return tablo[ad]


def reviewer_adaylari(yazici: str, profiller=None) -> list:
    """Yazıcıyı inceleyebilecek profil adları, alfabetik.

    Önce başka sağlayıcının reviewer modelleri. Yoksa aynı sağlayıcının başka modeli.
    Bilinmeyen yazıcı -> ProfilHatasi.
    """
    tablo = _tablo(profiller)
    if yazici not in tablo:
        raise ProfilHatasi(f"bilinmeyen yazıcı: {yazici}")
    ben = tablo[yazici]

    def aday(ayni):
        return sorted(
            p.ad for p in tablo.values()
            if p.secilebilir and "reviewer" in p.roller and p.ad != yazici
            and (p.firma == ben.firma) == ayni
        )

    capraz = aday(False)
    return capraz if capraz else aday(True)


def profil_tablosu(profiller=None) -> str:
    """Her profil için bir satır: '<ad> <firma> <model>'."""
    satirlar = []
    for p in _tablo(profiller).values():
        satir = f"{p.ad} {p.firma} {p.model}"
        if not p.secilebilir:
            satir += " [seçilemez]"
        satirlar.append(satir)
    return "\n".join(satirlar)
