"""Git geçmişinde kişisel veri denetimi.

Ağaçtaki dosya taraması yalnız güncel hali görür. Bu araç onun göremediklerine bakar:
yazar ve committer e-postaları, commit mesajı ve `Co-authored-by` satırları, tag'ler,
sonradan silinen dosyalar. `--github` ile force-push'la dalsız kalan commit'ler de taranır.

Çıktı bulgunun değerini asla yazmaz: CI günlüğü sızıntının kendisi olmasın.
Çıkış kodu: 0 temiz, 1 bulgu, 2 kullanım ya da araç hatası.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

EPOSTA = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
TC_ADAY = re.compile(r"(?<!\d)[1-9]\d{10}(?!\d)")


def tc_gecerli(s):
    """T.C. kimlik numarası sağlama hanelerini doğrula."""
    d = [int(c) for c in s]
    return (d[9] == ((sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10)) and d[10] == sum(d[:10]) % 10


def varsayilan_adlar_dosyasi(env=None, ev=None):
    """NOBET_ADLAR > $XDG_CONFIG_HOME/nobet/kisisel-adlar.txt (Windows: %APPDATA%). Repo dışında tutulur."""
    env = os.environ if env is None else env
    if env.get("NOBET_ADLAR"):
        return Path(env["NOBET_ADLAR"]).expanduser()
    ev = Path.home() if ev is None else Path(ev)
    if sys.platform == "win32":
        kok = Path(env["APPDATA"]) if env.get("APPDATA") else ev / "AppData" / "Roaming"
    else:
        kok = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else ev / ".config"
    return kok / "nobet" / "kisisel-adlar.txt"


def kisisel_adlar(path=None):
    """Her satırı bir ad olan liste. path verilmezse varsayılan dosya çağrı anında okunur."""
    if path is None:
        path = varsayilan_adlar_dosyasi()
    try:
        return [a.strip() for a in Path(path).read_text(encoding="utf-8").splitlines() if a.strip()]
    except OSError:
        return []

BLOB_SINIR = 30_000_000
# RFC 2606 ayrılmış alanlar ve kişiye bağlanmayan otomasyon adresleri.
IZINLI_ALAN = re.compile(
    r"@(?:users\.noreply\.github\.com|example\.(?:com|org|net)|[\w.-]+\.(?:example|test|invalid|localhost))$",
    re.IGNORECASE,
)
IZINLI_ADRES = frozenset({"noreply@github.com", "noreply@anthropic.com", "cursoragent@cursor.com"})


class GecmisHatasi(RuntimeError):
    """Tarama yapılamadı; temiz sayılmamalı."""


@dataclass(frozen=True, order=True)
class Bulgu:
    yer: str
    tur: str


def git(repo, *args, girdi=None):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, input=girdi, check=False)
    if r.returncode:
        hata = r.stderr.decode("utf-8", "replace").strip()
        raise GecmisHatasi(f"git {args[0]} başarısız: {hata}")
    return r.stdout


def _eposta_izinli(adres):
    a = adres.strip().strip("<>").rstrip(".").casefold()
    return a in IZINLI_ADRES or bool(IZINLI_ALAN.search(a))


def _ad_desenleri(adlar):
    return [re.compile(rf"(?<!\w){re.escape(a)}(?!\w)", re.IGNORECASE) for a in adlar]


def metin_bulgulari(yer, metin, desenler, ikili=False):
    bulgu = set()
    if not ikili and any(tc_gecerli(m) for m in TC_ADAY.findall(metin)):
        bulgu.add(Bulgu(yer, "TC kimlik no"))
    if any(not _eposta_izinli(m) for m in EPOSTA.findall(metin)):
        bulgu.add(Bulgu(yer, "e-posta"))
    if any(d.search(metin) for d in desenler):
        bulgu.add(Bulgu(yer, "ad"))
    return bulgu


def _kapsam(aralik):
    return [aralik] if aralik else ["--all"]


def commit_bulgulari(repo, aralik, desenler):
    ham = git(repo, "log", *_kapsam(aralik), "--format=%H%x00%ae%x00%ce%x00%B%x1e").decode("utf-8", "replace")
    bulgu = set()
    for kayit in ham.split("\x1e"):
        parca = kayit.strip().split("\x00", 3)
        if len(parca) != 4:
            continue
        sha, yazar, committer, mesaj = parca
        yer = f"commit {sha[:10]}"
        if not _eposta_izinli(yazar):
            bulgu.add(Bulgu(yer, "yazar e-postası"))
        if not _eposta_izinli(committer):
            bulgu.add(Bulgu(yer, "committer e-postası"))
        bulgu |= metin_bulgulari(f"{yer} mesajı", mesaj, desenler)
    return bulgu


def tag_bulgulari(repo, desenler):
    ham = git(repo, "for-each-ref", "refs/tags", "--format=%(refname:short)%00%(taggeremail)%00%(contents)%1e")
    bulgu = set()
    for kayit in ham.decode("utf-8", "replace").split("\x1e"):
        parca = kayit.strip().split("\x00", 2)
        if len(parca) != 3:
            continue
        ad, eposta, icerik = parca
        if eposta and not _eposta_izinli(eposta):
            bulgu.add(Bulgu(f"tag {ad}", "tagger e-postası"))
        if eposta:
            bulgu |= metin_bulgulari(f"tag {ad} mesajı", icerik, desenler)
    return bulgu


def blob_bulgulari(repo, aralik, desenler):
    nesneler = git(repo, "rev-list", "--objects", *_kapsam(aralik)).decode("utf-8", "replace")
    kontrol = git(repo, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize) %(rest)",
                  girdi=nesneler.encode("utf-8"))
    yollar, atlanan = {}, []
    for sat in kontrol.decode("utf-8", "replace").splitlines():
        sha, tur, boy, *yol = sat.split(" ", 3)
        if tur != "blob":
            continue
        ad = yol[0] if yol else sha[:10]
        if int(boy) > BLOB_SINIR:
            atlanan.append(ad)
        else:
            yollar.setdefault(sha, ad)
    bulgu = set()
    if not yollar:
        return bulgu, atlanan
    akis = git(repo, "cat-file", "--batch", girdi=("\n".join(yollar) + "\n").encode())
    i = 0
    while i < len(akis):
        j = akis.index(b"\n", i)
        sha, _, boy = akis[i:j].decode().split()
        ham = akis[j + 1:j + 1 + int(boy)]
        i = j + 2 + int(boy)
        ikili = b"\0" in ham[:8000]
        metin = ham.decode("latin-1" if ikili else "utf-8", "replace")
        bulgu |= metin_bulgulari(f"dosya {yollar[sha]}", metin, desenler, ikili=ikili)
    return bulgu, atlanan


def tara(repo, adlar, aralik=None):
    """(bulgular, atlanan yollar). Aralık yoksa tüm ref'ler ve tag'ler taranır."""
    desenler = _ad_desenleri(adlar)
    bulgu = commit_bulgulari(repo, aralik, desenler)
    if not aralik:
        bulgu |= tag_bulgulari(repo, desenler)
    blob, atlanan = blob_bulgulari(repo, aralik, desenler)
    return sorted(bulgu | blob), atlanan


def github_shalari(slug):
    """Aktivite ve olay kayıtlarındaki commit'ler; force-push'ta dalsız kalanlar buradan bulunur."""
    sha = re.compile(r"^[0-9a-f]{40}$")
    uclar = [(f"repos/{slug}/activity?per_page=100", ".[] | .before, .after"),
             (f"repos/{slug}/events?per_page=100",
              '.[] | select(.type=="PushEvent") | .payload.before, .payload.head')]
    bulunan = set()
    for ucl, sorgu in uclar:
        r = subprocess.run(["gh", "api", "--paginate", ucl, "--jq", sorgu], capture_output=True, check=False)
        if r.returncode:
            raise GecmisHatasi(f"gh api başarısız: {ucl}")
        bulunan |= {s for s in r.stdout.decode().split() if sha.match(s) and set(s) != {"0"}}
    return sorted(bulunan)


def uzak_tara(url, adlar, shalar):
    """Uzak reponun aynasını geçici dizine alır, dalsız commit'leri de çekip tarar.

    Çekilemeyen commit taranmamış demektir; temiz sayılmaz, hata verir.
    """
    with tempfile.TemporaryDirectory() as gecici:
        ayna = Path(gecici) / "ayna.git"
        r = subprocess.run(["git", "clone", "-q", "--mirror", url, str(ayna)], capture_output=True, check=False)
        if r.returncode:
            raise GecmisHatasi("ayna klonu alınamadı")
        cekilemeyen = 0
        for s in shalar:
            var = subprocess.run(["git", "-C", str(ayna), "cat-file", "-e", f"{s}^{{commit}}"],
                                 capture_output=True, check=False)
            if var.returncode == 0:  # nesne var ama ref'siz olabilir; --all görsün diye ref ver
                git(ayna, "update-ref", f"refs/eski/{s}", s)
                continue
            f = subprocess.run(["git", "-C", str(ayna), "fetch", "-q", "--no-tags", "origin", f"{s}:refs/eski/{s}"],
                               capture_output=True, check=False)
            cekilemeyen += bool(f.returncode)
        sonuc = tara(ayna, adlar)
    if cekilemeyen:
        raise GecmisHatasi(f"{cekilemeyen} commit çekilemedi; tarama eksik")
    return sonuc


def _adlari_oku(a):
    if a.adlar:
        if not Path(a.adlar).is_file():
            raise GecmisHatasi("--adlar dosyası okunamıyor")
        return kisisel_adlar(a.adlar)
    return kisisel_adlar()


def ayristir(argv=None):
    p = argparse.ArgumentParser(prog="nobet-gecmis", description=__doc__.splitlines()[0])
    p.add_argument("--repo", default=".", help="yerel repo (varsayılan: bulunulan dizin)")
    p.add_argument("--aralik", help="yalnız bu commit aralığı, örn. eski..yeni (CI için)")
    p.add_argument("--github", metavar="SAHIP/REPO", help="uzak repoyu silinen commit'leriyle birlikte tara")
    p.add_argument("--adlar", help="her satırı bir ad olan dosya (repo dışında tutulur)")
    p.add_argument("--adlar-zorunlu", action="store_true", help="ad listesi yoksa temiz sayma, 2 ile çık")
    p.add_argument("--json", action="store_true", help="sonucu JSON bas")
    return p.parse_args(argv)


def calistir(a):
    if a.github and a.aralik:
        raise GecmisHatasi("--github ile --aralik birlikte kullanılmaz")
    adlar = _adlari_oku(a)
    if not adlar and a.adlar_zorunlu:
        raise GecmisHatasi("ad listesi boş ya da yok; ad taraması yapılamaz")
    if a.github:
        bulgular, atlanan = uzak_tara(f"https://github.com/{a.github}.git", adlar, github_shalari(a.github))
    else:
        bulgular, atlanan = tara(a.repo, adlar, a.aralik)
    if a.json:
        print(json.dumps({"bulgular": [{"yer": b.yer, "tur": b.tur} for b in bulgular], "atlanan": atlanan,
                          "ad_taramasi": bool(adlar)}, ensure_ascii=False))
    else:
        for b in bulgular:
            print(f"{b.tur}: {b.yer}")
        if atlanan:
            print(f"uyarı: {len(atlanan)} büyük dosya taranmadı: {', '.join(atlanan[:5])}")
        if not adlar:
            print("uyarı: ad listesi yok, ad taraması yapılmadı")
        print(f"{len(bulgular)} bulgu")
    return 1 if bulgular else 0


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
