"""Bitti kanıtını çözümle ve doğrula; komutu çalıştırma, dosya yazma."""

import hashlib
import os
import re
import stat
import subprocess
from collections.abc import Mapping
from pathlib import Path


class BittiYok(Exception):
    """Bitti komutu tanımlanmamış."""


class BozukBitti(Exception):
    """Bitti komutu boş veya sözleşmedeki blok kapanmamış."""


class DurumHashHatasi(Exception):
    """Worktree içeriğinin özeti güvenilir biçimde hesaplanamadı."""


_HARIC = (
    ":(exclude,glob)**/__pycache__/**",
    ":(exclude,glob)**/.pytest_cache/**",
    ":(exclude,glob)**/*.pyc",
    ":(exclude,glob)**/node_modules/**",
)


# Yazıcının .git/config'i güvenilmez: fsmonitor/hook komut çalıştırır, fsmonitor değişikliği gizler.
_GIT_GUVENLI = ("-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "-c", "core.hooksPath=" + os.devnull)


def _metin(yol: Path) -> str:
    # Text mode'un Windows CRLF dönüşümünü özellikle kullanma.
    return yol.read_bytes().decode("utf-8")


def bitti_komutu(is_dizini: Path) -> str:
    """Önce bitti.cmd'yi, yoksa sözleşmedeki ilk bitti bloğunu oku."""
    kaynak = is_dizini / "bitti.cmd"
    if kaynak.is_file():
        komut = _metin(kaynak)
    else:
        kaynak = is_dizini / "sozlesme.md"
        if not kaynak.is_file():
            raise BittiYok("Bitti komutu yok")
        satirlar = _metin(kaynak).split("\n")
        for bas, satir in enumerate(satirlar):
            if re.fullmatch(r"```bitti[\t\r\v\f ]*", satir):
                break
        else:
            raise BittiYok("Sözleşmede bitti bloğu yok")
        for son in range(bas + 1, len(satirlar)):
            if re.fullmatch(r"```[\t\r\v\f ]*", satirlar[son]):
                komut = "\n".join(satirlar[bas + 1 : son])
                break
        else:
            raise BozukBitti("Bitti bloğu kapanmamış")
    komut = komut.rstrip("\n")
    if not komut.strip():
        raise BozukBitti("Bitti komutu boş")
    return komut


def _blob_hash(icerik: bytes) -> bytes:
    return hashlib.sha1(b"blob %d\0" % len(icerik) + icerik).hexdigest().encode("ascii")


def komut_hash(komut: str) -> str:
    """UTF-8 komutun git hash-object --stdin ile aynı blob özetini ver."""
    return _blob_hash(komut.encode("utf-8")).decode("ascii")


def durum_hash_hesapla(head: bytes, dosyalar: Mapping[bytes, bytes]) -> str:
    """HEAD ve ham bayt ad/içerik çiftlerini sıralayarak saf özet hesapla."""
    ozet = hashlib.sha1(b"HEAD " + head + b"\n")
    for ad in sorted(set(dosyalar)):
        ozet.update(b"%d:" % len(ad) + ad + b" " + _blob_hash(dosyalar[ad]) + b"\n")
    return ozet.hexdigest()


def _git(worktree: Path, *args: str) -> bytes:
    sonuc = subprocess.run(
        ["git", *_GIT_GUVENLI, *args], cwd=worktree, check=False, capture_output=True,
        shell=False, timeout=30,
    )
    if sonuc.returncode != 0:
        raise DurumHashHatasi("Git komutu başarısız: " + args[0])
    return sonuc.stdout


def durum_hash(worktree: Path) -> str:
    """İzlenen ve ignore edilmemiş dosyaların ham çalışma kopyasını özetle.

    Yalnız .gitignore kuralları geçerli: .git/info/exclude ve core.excludesFile yazıcı denetimindedir."""
    try:
        liste = _git(
            worktree, "-c", "core.excludesFile=", "ls-files", "-z", "--cached", "--others",
            "--exclude-per-directory=.gitignore", "--", ".", *_HARIC,
        )
        head = _git(worktree, "rev-parse", "HEAD").rstrip(b"\n")
        kok = os.fsencode(os.path.abspath(worktree))
        dosyalar = {}
        for ad in sorted(set(liste.split(b"\0")) - {b""}):
            # Adlar git'ten çıktığı haliyle hem sıralamada hem hash'te kalır.
            yol = os.path.join(kok, ad)
            try:
                bilgi = os.stat(yol)
            except (FileNotFoundError, NotADirectoryError):
                continue
            if not stat.S_ISREG(bilgi.st_mode):
                continue
            with open(yol, "rb") as dosya:
                dosyalar[ad] = dosya.read()
        return durum_hash_hesapla(head, dosyalar)
    except Exception as hata:
        raise DurumHashHatasi("Durum hash'i hesaplanamadı") from hata


def bitti_alan(log_metni: str, alan: str) -> str | None:
    """Yalnız log başlığındaki ilk tam alan eşleşmesini döndür."""
    onek = alan + ": "
    for satir in log_metni.split("\n"):
        if satir == "" or satir.startswith("komut|"):
            break
        if satir.startswith(onek):
            return satir[len(onek) :]
    return None


def bitti_guncel(is_dizini: Path, worktree: Path) -> bool:
    """İçerik özeti veya son commit bağı güncelse True; hatada False."""
    try:
        kh = komut_hash(bitti_komutu(is_dizini))
        log = _metin(is_dizini / "bitti.log")
        if bitti_alan(log, "komut_hash") != kh:
            return False
        dh = bitti_alan(log, "durum_hash")
        if not dh:
            return False
        if durum_hash(worktree) == dh:
            return True
        bag = _metin(is_dizini / "bitti-bag")
        # tail -n 1: yalnız tek sonlandırıcı LF atılır; boş son satır korunur.
        son = bag.removesuffix("\n").rsplit("\n", 1)[-1].split("\t")
        if len(son) != 3 or son[:2] != [kh, dh]:
            return False
        head = _git(worktree, "rev-parse", "HEAD").rstrip(b"\n").decode("ascii")
        if son[2] != head:
            return False
        return not _git(worktree, "status", "--porcelain", "--", ".", *_HARIC)
    except Exception:  # noqa: BLE001  # tek hatalı girdi koşuyu durdurmamalı
        return False


def bitti_gecerli(is_dizini: Path, worktree: Path) -> bool:
    """Güncel kanıtın çıkış kodu tam olarak 0 ise True; hatada False."""
    try:
        return bitti_guncel(is_dizini, worktree) and bitti_alan(
            _metin(is_dizini / "bitti.log"), "cikis"
        ) == "0"
    except Exception:  # noqa: BLE001  # tek hatalı girdi koşuyu durdurmamalı
        return False
