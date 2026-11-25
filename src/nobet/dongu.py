"""nobet-dongu: alt ajanın döngüye girdiğini metinden yakalayan kapı.

Ajan aynı çıktıyı tekrar tekrar üretiyorsa, metni düşük bilgili dolguyla şişiriyorsa, kanıtı
kopyalıyorsa ya da kanıt değişmeden aynı iddiayı yeniden sunuyorsa reddeder. Model çağırmaz;
ölçüler sıkıştırma oranı, Shannon entropisi ve kelime k-gram (shingle) Jaccard benzerliğidir.

Kullanım:
  nobet-dongu [seçenekler] GİRDİ...
      her GİRDİ verildiği sırayla bir denemedir; dizinse içindeki metin dosyaları birlikte bir deneme
  nobet-dongu [seçenekler] --serit İŞ_DİZİNİ
      nobet-akis şeridi: yazıcı raporları (yaz-N.md) sırayla denemedir, yaz-N.log'daki durum_hash
      kanıt özetidir; review-N.md yalnız iç tekrara bakılır
  nobet-dongu [seçenekler] --aralik A..B [--repo R]
      aralıktaki her commit (birleştirmeler hariç) bir deneme; metni eklenen satırlarıdır
  nobet-dongu [seçenekler] --oz-sinama [--tur N]
      rastgele tohumlu döngü ve temiz örneklerle eşiklerin hâlâ işe yaradığını sınar

Kapılar: ic_tekrar, deneme_tekrari, kopya_kanit, muhur (yalnız --muhur ile).
Eşikler: varsayılan < ayar.toml [dongu] < --esik AD=DEĞER. Kapı kapatma: --kapat KAPI ya da dongu.kapali.
Çıkış: 0 temiz, 1 döngü, 2 denetlenemedi ya da kullanım hatası.
Çıktı girdi metnini yazmaz; yalnız yeri (verilen yol, dosya adı ya da kısa sha) ve ölçüyü.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import zlib
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from nobet import ayar, bitti

DOSYA_SINIR = 5_000_000
VERI_UZANTI = frozenset({".json", ".jsonl", ".csv", ".tsv"})
KAPILAR = ("ic_tekrar", "deneme_tekrari", "kopya_kanit", "muhur")
# Çok dosyalı denemede ikili karşılaştırma pahalılaşır; bu sayının üstünde yalnız birebir kopya aranır.
_KOPYA_CIFT_SINIRI = 200
# Blok benzerliği için bloğun en az bu kadar k-gram'ı olmalı (tek kelimelik satırlar karşılaştırılmaz).
_EN_AZ_SHINGLE = 3

# ad: (varsayılan, alt sınır, üst sınır). Tür varsayılandan gelir: int sayı/uzunluk, float oran/bit.
ESIKLER = {
    "sikistirma_min": (0.16, 0.0, 1.0),       # zlib(metin)/metin bayt oranı; altı kendini tekrarlayan metin
    "sikistirma_veri_min": (0.10, 0.0, 1.0),  # .json/.jsonl/.csv/.tsv için (anahtar tekrarı doğaldır)
    "sikistirma_bayt": (260, 1, 10**9),       # bundan kısa metinde sıkıştırma oranına bakılmaz
    "entropi_min": (2.60, 0.0, 32.0),         # karakter Shannon entropisi (bit/karakter); altı dolgu
    "entropi_bayt": (120, 1, 10**9),          # bundan kısa metinde entropiye bakılmaz
    "tekillik_min": (0.38, 0.0, 1.0),         # tekil k-gram / tüm k-gram; altı cümle içi yankı
    "tekillik_kelime": (32, 1, 10**9),        # bundan az kelimede tekilliğe bakılmaz
    "shingle": (4, 1, 16),                    # k: kelime k-gram uzunluğu
    "blok_karakter": (35, 1, 10**6),          # blok sayılan en kısa satır (karakter)
    "blok_sayi": (3, 2, 10**6),               # blok denetimi için en az blok
    "blok_benzerlik": (0.82, 0.0, 1.0),       # ardışık iki bloğun Jaccard benzerliği; bu ve üstü "benzer"
    "blok_cift": (2, 1, 10**6),               # en az bu kadar benzer ardışık çift
    "blok_cift_oran": (0.25, 0.0, 1.0),       # ve benzer çiftlerin tüm ardışık çiftlere oranı
    "kopya_blok": (2, 1, 10**6),              # birebir tekrar eden blok sayısı
    "kopya_blok_oran": (0.35, 0.0, 1.0),      # ve bunların tüm bloklara oranı
    "deneme_benzerlik": (0.85, 0.0, 1.0),     # iki denemenin k-gram Jaccard benzerliği; bu ve üstü tekrar
    "deneme_kelime": (20, 1, 10**9),          # bundan az kelimeli deneme ya da dosya karşılaştırılmaz
    "kopya_benzerlik": (0.90, 0.0, 1.0),      # aynı denemedeki iki dosyanın benzerliği; bu ve üstü kopya
}
AYAR_ALANLARI = frozenset(ESIKLER) | {"kapali", "akis_denetle"}

_KELIME = re.compile(r"\w+")
_YAZ = re.compile(r"yaz-(\d+)\.md")
_REVIEW = re.compile(r"review-(\d+)\.md")
_MUHUR = re.compile(r"[0-9a-f]{64}")
# Yazıcının .git/config'i güvenilmez: diff sürücüsü ya da textconv komut çalıştırmasın.
_GIT_GUVENLI = ("-c", "core.fsmonitor=false", "-c", "core.quotepath=off", "-c", "core.hooksPath=" + os.devnull)


class DonguHatasi(Exception):
    """Döngü denetimi yapılamadı (çıkış 2)."""


class DenemeYok(DonguHatasi):
    """Denetlenecek deneme yok."""


@dataclass(frozen=True)
class Metin:
    """Bir denemedeki tek metin. yer kısa kimliktir (verilen yol, dosya adı ya da sha:yol)."""

    yer: str
    icerik: str
    veri: bool = False


@dataclass
class Deneme:
    """Sıradaki bir deneme. kanit: kanıt özeti (ör. worktree durum_hash); farklıysa yeni kanıt vardır."""

    ad: str
    metinler: list
    kanit: str | None = None


@dataclass(frozen=True)
class Ihlal:
    kapi: str
    yer: str
    olcu: str
    deger: float | None
    esik: float | None
    yon: str
    aciklama: str

    def satir(self):
        if self.deger is None:
            return f"{self.kapi}: {self.yer}: {self.aciklama}"
        return f"{self.kapi}: {self.yer}: {self.olcu} {_sayi(self.deger)} {self.yon} {_sayi(self.esik)} ({self.aciklama})"


@dataclass
class Sonuc:
    ihlaller: list
    olculer: list
    atlanan: list
    deneme: int
    metin: int
    esikler: dict
    kapali: frozenset
    muhur: str | None = None
    notlar: list = field(default_factory=list)

    def sozluk(self):
        return {
            "sonuc": "dongu" if self.ihlaller else "temiz",
            "ihlaller": [asdict(i) for i in self.ihlaller],
            "olculer": self.olculer,
            "atlanan": [{"yer": y, "neden": n} for y, n in self.atlanan],
            "deneme": self.deneme,
            "metin": self.metin,
            "esikler": self.esikler,
            "kapali": sorted(self.kapali),
            "muhur": self.muhur,
        }


def _sayi(x):
    if isinstance(x, float):
        return f"{x:.4f}".rstrip("0").rstrip(".") or "0"
    return str(x)


# --- eşikler ve ayar ------------------------------------------------------------------------

@dataclass(frozen=True)
class DonguAyari:
    esikler: dict
    kapali: frozenset = frozenset()
    akis_denetle: bool = False


def varsayilan_esikler():
    return {ad: v[0] for ad, v in ESIKLER.items()}


def esik_degeri(ad, deger):
    """Eşiği türüne ve aralığına göre doğrular. Bilinmeyen ad, yanlış tür ya da aralık dışı ValueError."""
    if ad not in ESIKLER:
        raise ValueError(f"bilinmeyen döngü eşiği: {ad}")
    varsayilan, alt, ust = ESIKLER[ad]
    if isinstance(deger, bool) or not isinstance(deger, (int, float)):
        raise ValueError(f"dongu.{ad} sayı olmalı")  # noqa: TRY004 - yapılandırma sözleşmesi
    if isinstance(varsayilan, int):
        if not isinstance(deger, int):
            raise ValueError(f"dongu.{ad} tam sayı olmalı")  # noqa: TRY004 - yapılandırma sözleşmesi
    else:
        deger = float(deger)
        if not math.isfinite(deger):
            raise ValueError(f"dongu.{ad} sonlu olmalı")
    if not alt <= deger <= ust:
        raise ValueError(f"dongu.{ad} {alt} ile {ust} arasında olmalı")
    return deger


def esik_argumani(metin):
    """--esik AD=DEĞER."""
    ad, esit, deger = metin.partition("=")
    ad = ad.strip()
    if not esit or not ad:
        raise ValueError(f"--esik AD=DEĞER biçiminde olmalı: {metin}")
    if ad not in ESIKLER:
        raise ValueError(f"bilinmeyen döngü eşiği: {ad}")
    try:
        sayi = int(deger) if isinstance(ESIKLER[ad][0], int) else float(deger)
    except ValueError:
        raise ValueError(f"--esik {ad}: sayı değil") from None
    return ad, esik_degeri(ad, sayi)


def _kapilar(deger):
    if not isinstance(deger, list) or not all(isinstance(k, str) for k in deger):
        raise ValueError("dongu.kapali metin listesi olmalı")
    for k in deger:
        if k not in KAPILAR:
            raise ValueError(f"dongu.kapali: bilinmeyen kapı {k} (geçerli: {', '.join(KAPILAR)})")
    return frozenset(deger)


def ayar_ayikla(ham):
    """ayar.toml [dongu] tablosunu doğrular. Bilinmeyen anahtar ValueError."""
    if not isinstance(ham, dict):
        raise ValueError("dongu tablo olmalı")  # noqa: TRY004 - yapılandırma sözleşmesi
    ekstra = sorted(set(ham) - AYAR_ALANLARI)
    if ekstra:
        raise ValueError("bilinmeyen dongu anahtarı: " + ", ".join(ekstra))
    esikler = varsayilan_esikler()
    for ad in ESIKLER:
        if ad in ham:
            esikler[ad] = esik_degeri(ad, ham[ad])
    akis = ham.get("akis_denetle", False)
    if not isinstance(akis, bool):
        raise ValueError("dongu.akis_denetle true ya da false olmalı")  # noqa: TRY004 - yapılandırma sözleşmesi
    return DonguAyari(esikler, _kapilar(ham.get("kapali", [])), akis)


def ayar_oku(dosya=None, env=None, ev=None):
    """[dongu] ayarı: dosya > NOBET_AYAR > varsayılan ayar.toml; tablo yoksa varsayılanlar."""
    return ayar_ayikla(ayar.ayar_verisi(dosya, env, ev).get("dongu", {}))


# --- ölçüler --------------------------------------------------------------------------------

def kelimeler(metin):
    """Unicode kelimeler (Türkçe harfler dahil), büyük/küçük harf farkı olmadan."""
    return _KELIME.findall(metin.casefold())


def shingle_listesi(kelime, k):
    if len(kelime) < k:
        return [tuple(kelime)] if kelime else []
    return [tuple(kelime[i:i + k]) for i in range(len(kelime) - k + 1)]


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def entropi(metin):
    """Karakter Shannon entropisi, bit/karakter."""
    if not metin:
        return 0.0
    n = len(metin)
    return -sum((c / n) * math.log2(c / n) for c in Counter(metin).values())


def sikistirma_orani(bayt):
    """zlib (seviye 9) çıktısının girdiye oranı: Kolmogorov karmaşıklığına kaba vekil."""
    return len(zlib.compress(bayt, 9)) / len(bayt) if bayt else 1.0


def _ozet(kelime):
    return hashlib.sha256(" ".join(kelime).encode("utf-8")).hexdigest()


# --- kapılar --------------------------------------------------------------------------------

def ic_tekrar(m, e):
    """(ölçüler, ihlaller): tek metinde yankı, dolgu ve birebir tekrar eden bloklar."""
    temiz = m.icerik.strip()
    ham = temiz.encode("utf-8")
    olcu = {"yer": m.yer, "bayt": len(ham)}
    ihlal = []
    if not ham:
        return olcu, ihlal
    k = e["shingle"]
    oran = sikistirma_orani(ham)
    olcu["sikistirma"] = round(oran, 4)
    esik = e["sikistirma_veri_min"] if m.veri else e["sikistirma_min"]
    if len(ham) >= e["sikistirma_bayt"] and oran < esik:
        ihlal.append(Ihlal("ic_tekrar", m.yer, "sikistirma", round(oran, 4), esik, "<",
                           "sıkıştırma oranı düşük: metin kendini tekrarlıyor"))
    ent = entropi(temiz)
    olcu["entropi"] = round(ent, 4)
    if len(ham) >= e["entropi_bayt"] and ent < e["entropi_min"]:
        ihlal.append(Ihlal("ic_tekrar", m.yer, "entropi", round(ent, 4), e["entropi_min"], "<",
                           "karakter entropisi düşük: az bilgili dolgu"))
    kel = kelimeler(temiz)
    olcu["kelime"] = len(kel)
    if len(kel) >= max(e["tekillik_kelime"], k):
        sl = shingle_listesi(kel, k)
        tek = len(set(sl)) / len(sl)
        olcu["tekillik"] = round(tek, 4)
        if tek < e["tekillik_min"]:
            ihlal.append(Ihlal("ic_tekrar", m.yer, "tekillik", round(tek, 4), e["tekillik_min"], "<",
                               "k-gram tekilliği düşük: cümle içi yankı"))
    bloklar = [s.strip() for s in temiz.splitlines() if len(s.strip()) >= e["blok_karakter"]]
    olcu["blok"] = len(bloklar)
    if len(bloklar) >= e["blok_sayi"]:
        kopya = sum(c - 1 for c in Counter(" ".join(b.casefold().split()) for b in bloklar).values() if c > 1)
        en_yuksek, cift, onceki = 0.0, 0, None
        for b in bloklar:
            sh = set(shingle_listesi(kelimeler(b), k))
            if onceki is not None and len(sh) >= _EN_AZ_SHINGLE and len(onceki) >= _EN_AZ_SHINGLE:
                j = jaccard(onceki, sh)
                en_yuksek = max(en_yuksek, j)
                cift += j >= e["blok_benzerlik"]
            onceki = sh
        olcu.update(blok_benzerlik=round(en_yuksek, 4), benzer_cift=cift, kopya_blok=kopya)
        if cift >= e["blok_cift"] and cift / (len(bloklar) - 1) >= e["blok_cift_oran"]:
            ihlal.append(Ihlal("ic_tekrar", m.yer, "blok_benzerlik", round(en_yuksek, 4), e["blok_benzerlik"],
                               ">=", f"{cift} ardışık blok çifti neredeyse aynı"))
        if kopya >= e["kopya_blok"] and kopya / len(bloklar) >= e["kopya_blok_oran"]:
            ihlal.append(Ihlal("ic_tekrar", m.yer, "kopya_blok", round(kopya / len(bloklar), 4),
                               e["kopya_blok_oran"], ">=", f"{kopya} blok birebir tekrar"))
    return olcu, ihlal


def deneme_tekrari(denemeler, e):
    """Her deneme kendinden önceki tüm denemelerle karşılaştırılır (A-B-A salınımı da yakalanır).
    İki denemenin kanıt özeti de biliniyor ve farklıysa tekrar sayılmaz: yeni kanıt vardır.
    deneme_kelime'den kısa deneme yalnız kanıt özeti bilinip aynıysa ve metin birebir aynıysa tekrar sayılır."""
    ihlal, onceki, k = [], [], e["shingle"]
    for d in denemeler:
        kel = kelimeler("\n".join(m.icerik for m in d.metinler))
        if not kel:
            continue
        kisa = len(kel) < e["deneme_kelime"]
        sh, oz = set(shingle_listesi(kel, k)), _ozet(kel)
        en, eslesen = 0.0, None
        for od, osh, ooz, okisa in onceki:
            ayni_kanit = d.kanit is not None and d.kanit == od.kanit
            if d.kanit is not None and od.kanit is not None and not ayni_kanit:
                continue
            if kisa or okisa:
                j = 1.0 if ayni_kanit and oz == ooz else 0.0
            else:
                j = 1.0 if oz == ooz else jaccard(sh, osh)
            if j > en:
                en, eslesen = j, od
        if eslesen is not None and en >= e["deneme_benzerlik"]:
            if d.kanit is not None and d.kanit == eslesen.kanit:
                neden = "kanıt özeti değişmeden aynı iddia yeniden sunuldu"
            else:
                neden = "deneme öncekinin neredeyse aynısı"
            ihlal.append(Ihlal("deneme_tekrari", f"{d.ad} ~ {eslesen.ad}", "benzerlik", round(en, 4),
                               e["deneme_benzerlik"], ">=", neden))
        onceki.append((d, sh, oz, kisa))
    return ihlal


def kopya_kanit(denemeler, e):
    """Çok dosyalı denemelerde: aynı denemedeki iki dosya birbirine çok benziyorsa (kopya_benzerlik)
    ya da bir dosya önceki bir denemedeki dosyanın birebir aynısıysa kopya kanıttır.
    Tek dosyalı denemeler deneme_tekrari'nın işidir."""
    ihlal, k, gecmis = [], e["shingle"], []
    for d in denemeler:
        adaylar = []
        for m in d.metinler:
            kel = kelimeler(m.icerik)
            if len(kel) >= e["deneme_kelime"]:
                adaylar.append((m, set(shingle_listesi(kel, k)), _ozet(kel)))
        if len(d.metinler) >= 2:
            yalniz_birebir = len(adaylar) > _KOPYA_CIFT_SINIRI
            for i, (m, sh, oz) in enumerate(adaylar):
                bulgu = None
                for m2, sh2, oz2 in adaylar[:i]:
                    j = 1.0 if oz == oz2 else (0.0 if yalniz_birebir else jaccard(sh, sh2))
                    if j >= e["kopya_benzerlik"]:
                        bulgu = Ihlal("kopya_kanit", f"{m.yer} ~ {m2.yer}", "benzerlik", round(j, 4),
                                      e["kopya_benzerlik"], ">=", "aynı denemede iki dosya birbirinin kopyası")
                        break
                if bulgu is None:
                    eski = next((m2 for m2, oz2 in gecmis if oz2 == oz), None)
                    if eski is not None:
                        bulgu = Ihlal("kopya_kanit", f"{m.yer} ~ {eski.yer}", "benzerlik", 1.0,
                                      e["kopya_benzerlik"], ">=", "önceki denemenin dosyası yeni kanıt diye sunuldu")
                if bulgu is not None:
                    ihlal.append(bulgu)
        gecmis += [(m, oz) for m, _, oz in adaylar]
    return ihlal


def muhur_hesapla(denemeler, ek=()):
    """Girdi içeriklerinin sırasız SHA-256 mührü (dosya adları ve sırası mühre girmez)."""
    ozetler = sorted(hashlib.sha256(m.icerik.encode("utf-8")).hexdigest()
                     for m in [*(m for d in denemeler for m in d.metinler), *ek])
    return hashlib.sha256("\n".join(ozetler).encode("ascii")).hexdigest()


def _muhur_defteri(yol):
    kayit = {}
    if not yol.exists():
        return kayit
    try:
        satirlar = yol.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as e:
        raise DonguHatasi(f"mühür defteri okunamadı: {yol}") from e
    for satir in satirlar:
        if not satir.strip():
            continue
        parca = satir.split("\t")
        if len(parca) != 2 or not _MUHUR.fullmatch(parca[0]):
            raise DonguHatasi(f"mühür defteri bozuk: {yol}")
        kayit.setdefault(parca[0], parca[1])
    return kayit


# --- denetim --------------------------------------------------------------------------------

def denetle(denemeler, esikler=None, kapali=frozenset(), ek=(), atlanan=(), muhur_dosyasi=None,
            muhur_salt_oku=False):
    """Kapıları sırayla koşar. ek: yalnız iç tekrara bakılan metinler (ör. reviewer cevapları)."""
    e = varsayilan_esikler() if esikler is None else {**varsayilan_esikler(), **esikler}
    kapali = frozenset(kapali)
    atlanan = list(atlanan)
    metinler = [m for d in denemeler for m in d.metinler] + list(ek)
    for m in metinler:
        if not m.icerik.strip():
            atlanan.append((m.yer, "boş"))
    if not any(m.icerik.strip() for m in metinler):
        raise DenemeYok("denetlenecek metin yok")
    ihlaller, olculer = [], []
    for m in metinler:
        if not m.icerik.strip():
            continue
        olcu, ihlal = ic_tekrar(m, e)
        olculer.append(olcu)
        if "ic_tekrar" not in kapali:
            ihlaller += ihlal
    if "deneme_tekrari" not in kapali:
        ihlaller += deneme_tekrari(denemeler, e)
    if "kopya_kanit" not in kapali:
        ihlaller += kopya_kanit(denemeler, e)
    muhur = None
    if muhur_dosyasi is not None and "muhur" not in kapali:
        yol = Path(muhur_dosyasi)
        muhur = muhur_hesapla(denemeler, ek)
        defter = _muhur_defteri(yol)
        if muhur in defter:
            ihlaller.append(Ihlal("muhur", muhur[:12], "muhur", None, None, "",
                                  f"aynı içerik daha önce mühürlendi ({defter[muhur]}): yeniden sunuluyor"))
        elif not ihlaller and not muhur_salt_oku:
            zaman = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
            with open(yol, "a", encoding="utf-8", newline="\n") as f:
                f.write(f"{muhur}\t{zaman}\n")
    return Sonuc(ihlaller, olculer, atlanan, len(denemeler), len(metinler), e, kapali, muhur)


# --- girdiler -------------------------------------------------------------------------------

def _metin_oku(yol, yer, atlanan):
    try:
        if yol.stat().st_size > DOSYA_SINIR:
            atlanan.append((yer, "büyük"))
            return None
        ham = yol.read_bytes()
    except OSError as e:
        raise DonguHatasi(f"okunamadı: {yer}: {e.strerror or type(e).__name__}") from None
    if b"\0" in ham[:8000]:
        atlanan.append((yer, "ikili"))
        return None
    return Metin(yer, ham.decode("utf-8", "replace").lstrip("﻿"), yol.suffix.lower() in VERI_UZANTI)


def _ayni_dosya(a, b):
    try:
        return a.samefile(b)
    except OSError:
        return False


def girdi_denemeleri(girdiler, haric=()):
    """(denemeler, atlanan). Her girdi bir deneme; dizinde gizli adlar, __pycache__ ve bağlar atlanır."""
    haric = [Path(h) for h in haric]
    denemeler, atlanan = [], []
    for g in girdiler:
        p = Path(g)
        if p.is_dir():
            metinler = []
            for kok, dizinler, dosyalar in os.walk(p):
                dizinler[:] = sorted(x for x in dizinler if not x.startswith(".") and x != "__pycache__")
                for ad in sorted(dosyalar):
                    f = Path(kok) / ad
                    if ad.startswith(".") or f.is_symlink() or any(_ayni_dosya(f, h) for h in haric):
                        continue
                    m = _metin_oku(f, (p / f.relative_to(p)).as_posix(), atlanan)
                    if m is not None:
                        metinler.append(m)
            denemeler.append(Deneme(g, metinler))
        elif p.is_file():
            m = _metin_oku(p, g, atlanan)
            denemeler.append(Deneme(g, [m] if m is not None else []))
        else:
            raise DonguHatasi(f"girdi yok: {g}")
    return denemeler, atlanan


def serit_denemeleri(d):
    """(denemeler, ek, atlanan) nobet-akis iş dizininden. Deneme yoksa DenemeYok."""
    d = Path(d)
    if not d.is_dir():
        raise DonguHatasi(f"şerit dizini yok: {d}")

    def numarali(desen):
        return sorted((int(m.group(1)), f) for f in d.iterdir()
                      if (m := desen.fullmatch(f.name)) and f.is_file() and not f.is_symlink())

    yazlar = numarali(_YAZ)
    if not yazlar:
        raise DenemeYok("şeritte yazıcı raporu yok (yaz-N.md)")
    atlanan, denemeler, ek = [], [], []
    for n, f in yazlar:
        m = _metin_oku(f, f.name, atlanan)
        log = d / f"yaz-{n}.log"
        kanit = None
        if log.is_file() and not log.is_symlink():
            alan = bitti.bitti_alan(log.read_text(encoding="utf-8", errors="replace"), "durum_hash")
            kanit = (alan or "").strip() or None
        denemeler.append(Deneme(f.name, [m] if m is not None else [], kanit))
    for _, f in numarali(_REVIEW):
        m = _metin_oku(f, f.name, atlanan)
        if m is not None:
            ek.append(m)
    return denemeler, ek, atlanan


def _git(repo, *args):
    r = subprocess.run(["git", *_GIT_GUVENLI, "-C", str(repo), *args], capture_output=True, check=False)
    if r.returncode:
        hata = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise DonguHatasi(f"git {args[0]} başarısız: {hata[-1] if hata else r.returncode}")
    return r.stdout.decode("utf-8", "replace")


def eklenen_satirlar(fark):
    """`git show -U0` çıktısından {yol: eklenen satırlar} ve ikili dosya yolları."""
    eklenen, ikili, yol, baslik, git_yolu = {}, [], None, False, None
    for satir in fark.split("\n"):
        if satir.startswith("diff --git "):
            baslik, yol = True, None
            git_yolu = satir.rsplit(" b/", 1)[-1] if " b/" in satir else None
        elif baslik and satir.startswith("+++ "):
            hedef = satir[4:]
            yol = hedef[2:] if hedef.startswith("b/") else None
        elif baslik and satir.startswith("Binary files "):
            if git_yolu:
                ikili.append(git_yolu)
        elif satir.startswith("@@"):
            baslik = False
        elif not baslik and yol is not None and satir.startswith("+"):
            eklenen.setdefault(yol, []).append(satir[1:])
    return eklenen, ikili


def aralik_denemeleri(repo, aralik):
    """(denemeler, atlanan): aralıktaki birleştirme olmayan her commit bir deneme, eskiden yeniye."""
    if not aralik or aralik.startswith("-"):
        raise DonguHatasi("aralık '-' ile başlayamaz")
    shalar = _git(repo, "rev-list", "--reverse", "--no-merges", "--end-of-options", aralik, "--").split()
    if not shalar:
        raise DenemeYok(f"aralıkta commit yok: {aralik}")
    denemeler, atlanan = [], []
    for sha in shalar:
        kisa = sha[:8]
        fark = _git(repo, "show", "--format=", "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames",
                    "-U0", sha, "--")
        eklenen, ikili = eklenen_satirlar(fark)
        atlanan += [(f"{kisa}:{y}", "ikili") for y in ikili]
        metinler = [Metin(f"{kisa}:{y}", "\n".join(s), Path(y).suffix.lower() in VERI_UZANTI)
                    for y, s in sorted(eklenen.items())]
        denemeler.append(Deneme(kisa, metinler))
    return denemeler, atlanan


# --- öz sınama ------------------------------------------------------------------------------

_SOZLUK = (
    "kayıt", "dizin", "komut", "çıktı", "sınama", "değişken", "işlev", "modül", "dosya", "satır", "hata",
    "düzeltme", "ölçüm", "eşik", "kapı", "şerit", "rapor", "kanıt", "önbellek", "bağımlılık", "sürüm",
    "yapılandırma", "ağaç", "dal", "birleştirme", "uyarı", "zaman", "süreç", "girdi", "biçim", "denetim",
    "yol", "anahtar", "değer", "tablo", "liste", "sayı", "metin", "özet", "karşılaştırma", "sıralama",
    "arama", "okuma", "yazma", "silme", "ekleme", "taşıma", "kopyalama", "doğrulama", "ayrıştırma", "kuyruk",
    "yığın", "bellek", "disk", "ağ", "istek", "yanıt", "başlık", "gövde", "kodlama", "çözme", "sıkıştırma",
    "örnek", "senaryo", "adım", "sonuç", "neden", "etki", "öncelik", "sınır", "aralık", "parça", "bütün",
    "katman",
)


def _cesitli(rnd, cumle):
    parcalar = []
    for _ in range(cumle):
        kelime = rnd.sample(_SOZLUK, rnd.randint(7, 12)) + [f"{rnd.getrandbits(32):08x}"]
        rnd.shuffle(kelime)
        parcalar.append(" ".join(kelime).capitalize() + ".")
    return "\n".join(parcalar)


def oz_sinama(esikler=None, kapali=frozenset(), tur=8, tohum=None):
    """Kapıların seçili eşiklerle rastgele döngü örneklerini yakaladığını, temiz örnekleri geçirdiğini sınar.
    (vakalar, tohum özeti). Her vaka: {"tur", "vaka", "beklenen", "gercek", "gecti"}."""
    e = varsayilan_esikler() if esikler is None else {**varsayilan_esikler(), **esikler}
    tohum = os.urandom(32) if tohum is None else tohum
    ana = hashlib.sha256(tohum).hexdigest()
    vakalar = []

    def kapi_ihlali(denemeler, kapi):
        return any(i.kapi == kapi for i in denetle(denemeler, e, kapali - {kapi}).ihlaller)

    for r in range(tur):
        rnd = random.Random(f"{ana}:{r}")
        a, b, c = (f"{rnd.getrandbits(40):010x}" for _ in range(3))
        dongu_cumlesi = f"Adım {a} {b} {c} doğrulandı ve aynı kontrol adımına yeniden dönüldü {a} {b}.\n"
        temiz = _cesitli(rnd, 24)
        kelime = temiz.split(" ")
        kelime[len(kelime) // 2] = c
        neredeyse = " ".join(kelime)
        ornekler = (
            ("dongu_metni", "ic_tekrar", True, [Deneme("d1", [Metin("d1", dongu_cumlesi * (12 + r % 5))])]),
            ("temiz_metin", "ic_tekrar", False, [Deneme("d1", [Metin("d1", temiz)])]),
            ("tekrar_deneme", "deneme_tekrari", True,
             [Deneme("d1", [Metin("d1", temiz)]), Deneme("d2", [Metin("d2", neredeyse)])]),
            ("farkli_denemeler", "deneme_tekrari", False,
             [Deneme("d1", [Metin("d1", temiz)]), Deneme("d2", [Metin("d2", _cesitli(rnd, 24))])]),
            ("kopya_kanit", "kopya_kanit", True,
             [Deneme("d1", [Metin("d1/rapor", _cesitli(rnd, 6)), Metin("d1/a.log", temiz),
                            Metin("d1/b.log", neredeyse)])]),
        )
        for vaka, kapi, beklenen, denemeler in ornekler:
            if kapi in kapali:
                vakalar.append({"tur": r, "vaka": vaka, "beklenen": beklenen, "gercek": None, "gecti": None})
                continue
            gercek = kapi_ihlali(denemeler, kapi)
            vakalar.append({"tur": r, "vaka": vaka, "beklenen": beklenen, "gercek": gercek,
                            "gecti": gercek == beklenen})
    return vakalar, ana


# --- komut satırı ---------------------------------------------------------------------------

def ayristir(argv=None):
    p = argparse.ArgumentParser(prog="nobet-dongu", description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("girdiler", nargs="*", metavar="GİRDİ", help="sırayla denemeler (dosya ya da dizin)")
    p.add_argument("--serit", metavar="İŞ_DİZİNİ", help="nobet-akis şeridinin iş dizini")
    p.add_argument("--aralik", metavar="A..B", help="git aralığı; her commit bir deneme")
    p.add_argument("--repo", default=".", help="--aralik için repo (varsayılan: bulunulan dizin)")
    p.add_argument("--oz-sinama", action="store_true", help="eşikleri rastgele örneklerle sına")
    p.add_argument("--tur", type=int, default=8, help="--oz-sinama tur sayısı (varsayılan 8)")
    p.add_argument("--esik", action="append", default=[], metavar="AD=DEĞER", help="eşiği değiştir")
    p.add_argument("--kapat", action="append", default=[], choices=KAPILAR, metavar="KAPI",
                   help="kapıyı kapat: " + ", ".join(KAPILAR))
    p.add_argument("--ayar", metavar="DOSYA", help="ayar.toml (varsayılan: NOBET_AYAR ya da kullanıcı ayarı)")
    p.add_argument("--muhur", metavar="DOSYA", help="mühür defteri: aynı içerik ikinci kez sunulursa ret")
    p.add_argument("--muhur-salt-oku", action="store_true", help="mühür defterine yazma, yalnız bak")
    p.add_argument("--json", action="store_true", help="sonucu JSON bas")
    a = p.parse_args(argv)
    kaynak = sum((bool(a.girdiler), a.serit is not None, a.aralik is not None, a.oz_sinama))
    if kaynak != 1:
        p.error("tek kaynak ver: GİRDİ..., --serit, --aralik ya da --oz-sinama")
    if a.tur < 1:
        p.error("--tur en az 1")
    if a.muhur_salt_oku and not a.muhur:
        p.error("--muhur-salt-oku --muhur ister")
    return a


def _bas(s, json_):
    if json_:
        print(json.dumps(s.sozluk(), ensure_ascii=False))
        return
    for i in s.ihlaller:
        print("ihlal: " + i.satir())
    for yer, neden in s.atlanan:
        print(f"atlandı: {yer} ({neden})")
    if s.ihlaller:
        print(f"dongu: REDDEDİLDİ ({len(s.ihlaller)} ihlal; {s.deneme} deneme, {s.metin} metin)")
    else:
        print(f"dongu: temiz ({s.deneme} deneme, {s.metin} metin)")


def calistir(a):
    ayar_ = ayar_oku(a.ayar)
    esikler = dict(ayar_.esikler)
    for metin in a.esik:
        ad, deger = esik_argumani(metin)
        esikler[ad] = deger
    kapali = ayar_.kapali | frozenset(a.kapat)
    if a.oz_sinama:
        vakalar, ana = oz_sinama(esikler, kapali, a.tur)
        kalan = [v for v in vakalar if v["gecti"] is False]
        if a.json:
            print(json.dumps({"sonuc": "gecti" if not kalan else "kaldi", "tohum": ana[:16], "vakalar": vakalar,
                              "esikler": esikler, "kapali": sorted(kapali)}, ensure_ascii=False))
        else:
            for v in kalan:
                print(f"oz_sinama: tur {v['tur']}: {v['vaka']}: beklenen "
                      f"{'ihlal' if v['beklenen'] else 'temiz'}, gerçek {'ihlal' if v['gercek'] else 'temiz'}")
            sayilan = [v for v in vakalar if v["gecti"] is not None]
            print(f"oz_sinama: {len(sayilan) - len(kalan)}/{len(sayilan)} vaka geçti (tohum {ana[:16]})")
        return 1 if kalan else 0
    if a.serit is not None:
        denemeler, ek, atlanan = serit_denemeleri(a.serit)
    elif a.aralik is not None:
        (denemeler, atlanan), ek = aralik_denemeleri(a.repo, a.aralik), ()
    else:
        (denemeler, atlanan), ek = girdi_denemeleri(a.girdiler, [a.muhur] if a.muhur else ()), ()
    s = denetle(denemeler, esikler, kapali, ek, atlanan, a.muhur, a.muhur_salt_oku)
    _bas(s, a.json)
    return 1 if s.ihlaller else 0


def main(argv=None):
    """Komut satırı girişi (`nobet-dongu`). Çıkış 0 temiz, 1 döngü, 2 denetlenemedi ya da kullanım."""
    for akis in (sys.stdout, sys.stderr):
        if hasattr(akis, "reconfigure"):
            akis.reconfigure(encoding="utf-8", newline="\n")
    a = ayristir(argv)
    try:
        return calistir(a)
    except (DonguHatasi, ValueError, OSError) as e:
        print(f"nobet-dongu: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
