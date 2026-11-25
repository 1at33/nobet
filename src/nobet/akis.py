"""nobet-akis: şerit aç, yazıcı ajanı çalıştır, kapıdan geçir, reviewer'a incelet, şeridi kapat.

Komutlar (çıkış 0 tamam, 1 ihlal ya da başarısız, 2 denetlenemedi ya da kullanım hatası):
  nobet-akis ac <repo> <ad> --sahiplik GLOB [--sahiplik GLOB]... [--test-izni GLOB]...
                [--sozlesme madde.md] [--bitti KOMUT] [--kabul KAYNAK=HEDEF]... [--worktree YOL]
      git worktree (dal nobet/<ad>, taban dalı nobet-taban/<ad>) ve iş dizini açar.
  nobet-akis kabul <ad> <yol>...           worktree'deki yeni test dosyalarını dondurur
  nobet-akis yaz <ad> <profil> <brief.md>  yazıcı ajanı worktree'de, sırsız ortamla çalıştırır
  nobet-akis denetle <ad> [--rapor R]      bitti komutu + kapı + sözleşme komutları + rapor şeması
  nobet-akis incele <ad> [--profil P] [--ek ek.md]
      reviewer (varsayılan: başka sağlayıcıdan ilk aday) farkı inceler; ağacı değiştirirse ret
  nobet-akis kaydet <ad> -m <mesaj>        yeşil ve güncel bitti + temiz kapı ise şerit dalına commit
  nobet-akis durum <ad>                    fark özeti, bitti durumu, kapı sonucu
  nobet-akis kapat <ad>                    temiz worktree'yi yalnız git ile kaldırır; dal kalır
  nobet-akis profiller                     ayar.toml'dan türeyen profiller

İş dizinleri: NOBET_AKIS_DIZIN > $XDG_STATE_HOME/nobet/akis > ~/.local/state/nobet/akis
(Windows: %LOCALAPPDATA%\\nobet\\akis); her şerit <kök>/isler/<ad>.

Ajan komutu kullanıcının ayar.toml'undaki [[saglayici]] komut şablonundan gelir; kabuk kullanılmaz.
Yer tutucular: {istem} istem dosyası (yoksa istem stdin'den verilir), {worktree}, {model},
{cikti} ajanın son cevabını yazacağı dosya (yoksa stdout), {rol} yazici|reviewer.
"""

import argparse
import contextlib
import datetime
import io
import json
import os
import posixpath
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from nobet import ayar, bitti, kapi, profil
from nobet.bitti import _HARIC
from nobet.gizli import maskele, temiz_ortam

AD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
YER_TUTUCULAR = ("istem", "worktree", "model", "cikti", "rol")
_YER = re.compile(r"\{([A-Za-z_]+)\}")
FARK_SINIRI = 200_000
KORUMA = "koruma.ihlal"


class AkisHatasi(Exception):
    """Akış adımı başlatılamadı ya da güvenli biçimde tamamlanamadı (çıkış 2)."""


# --- yardımcılar ---------------------------------------------------------------------------

def kok(env=None):
    """Şerit kayıtlarının kökü. Worktree dışında olmalı: yazıcı kendi izinlerini düzenleyemesin."""
    env = os.environ if env is None else env
    if env.get("NOBET_AKIS_DIZIN"):
        return Path(env["NOBET_AKIS_DIZIN"]).expanduser()
    if sys.platform == "win32":
        taban = Path(env["LOCALAPPDATA"]) if env.get("LOCALAPPDATA") else Path.home() / "AppData" / "Local"
        return taban / "nobet" / "akis"
    taban = Path(env["XDG_STATE_HOME"]) if env.get("XDG_STATE_HOME") else Path.home() / ".local" / "state"
    return taban / "nobet" / "akis"


def _ad_dogrula(ad):
    if not AD.fullmatch(ad or ""):
        raise AkisHatasi("geçersiz şerit adı (harf, rakam, - ve _; en çok 64 karakter)")
    return ad


def _git(cwd, *args, env=None):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, check=False, env=env)
    if r.returncode:
        hata = r.stderr.decode("utf-8", "replace").strip()
        raise AkisHatasi(f"git {args[0]} başarısız: {hata}")
    return r.stdout.decode("utf-8", "replace").strip()


def _yaz(yol, metin):
    """Atomik UTF-8 + LF yazım."""
    gecici = yol.with_name(f".{yol.name}.{os.getpid()}")
    gecici.write_text(metin, encoding="utf-8", newline="\n")
    os.replace(gecici, yol)


def _ekle(yol, satir):
    with open(yol, "a", encoding="utf-8", newline="\n") as f:
        f.write(satir.rstrip("\n") + "\n")


def _oku(d, ad):
    f = d / ad
    if not f.is_file():
        raise AkisHatasi(f"şerit kaydı eksik: {ad}")
    return f.read_text(encoding="utf-8").strip()


def _simdi():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _ayni_yol(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _icinde(yol, kok_):
    a = os.path.normcase(os.path.realpath(yol))
    b = os.path.normcase(os.path.realpath(kok_))
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


def _sure(ad, varsayilan):
    return kapi.sure_saniye(os.environ.get(ad, varsayilan))


def _sirsiz_ortam():
    """Alt süreç ortamı: sır gibi görünenler çıkar; yalnız NOBET_ORTAM_IZIN adları korunur."""
    izin = [a.strip() for a in os.environ.get("NOBET_ORTAM_IZIN", "").split(",") if a.strip()]
    return temiz_ortam(os.environ, izin)


def _sonraki(d, onek):
    sayilar = [int(m.group(1)) for f in d.iterdir() if (m := re.fullmatch(rf"{onek}-(\d+)\.log", f.name))]
    return 1 + max(sayilar, default=0)


def serit(ad, worktree_olmali=True):
    """(iş dizini, worktree)."""
    d = kok() / "isler" / _ad_dogrula(ad)
    if not d.is_dir():
        raise AkisHatasi(f"şerit yok: {ad}")
    wt = Path(_oku(d, "worktree"))
    if worktree_olmali and not (wt / ".git").exists():
        raise AkisHatasi(f"worktree yok: {wt}")
    return d, wt


# --- süreç çalıştırma: zaman aşımı ve süreç ağacı ------------------------------------------

def _agac_kapat(p):
    """Zaman aşımında yalnız bu çağrının süreç grubunu kapatır (ad/desenle süreç seçilmez)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, check=False)
        return
    for sinyal in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(p.pid, sinyal)
        except (ProcessLookupError, PermissionError):
            return
        try:
            p.wait(timeout=3)
            return
        except subprocess.TimeoutExpired:
            continue


def calistir(argv, cwd, env, girdi, sure):
    """(çıkış kodu, birleşik çıktı baytları). Zaman aşımı 124, başlatılamayan komut 127."""
    ek = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    try:
        p = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL if girdi is None else subprocess.PIPE, **ek)
    except OSError as e:
        return 127, f"[nobet-akis: başlatılamadı: {e.strerror or type(e).__name__}]\n".encode()
    try:
        out, _ = p.communicate(girdi, timeout=sure)
        return p.returncode, out
    except subprocess.TimeoutExpired:
        _agac_kapat(p)
        try:
            out, _ = p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
            out = b""
        return 124, (out or b"") + b"\n[nobet-akis: zaman asimi]\n"
    except BaseException:
        _agac_kapat(p)
        raise


# --- ajan çağrısı: kullanıcının sağlayıcı komutu ya da API ----------------------------------

def komut_kur(sablon, degerler):
    """Şablonu argv'ye çevirir. Kabuk yok: değerler tek argüman olarak yerine konur."""
    try:
        parcalar = shlex.split(sablon)
    except ValueError as e:
        raise AkisHatasi(f"komut şablonu ayrıştırılamadı: {e}") from None
    if not parcalar:
        raise AkisHatasi("komut şablonu boş")
    for p in parcalar:
        for ad in _YER.findall(p):
            if ad not in YER_TUTUCULAR:
                gecerli = ", ".join("{" + y + "}" for y in YER_TUTUCULAR)
                raise AkisHatasi(f"bilinmeyen yer tutucu {{{ad}}} (geçerli: {gecerli})")
    return [_YER.sub(lambda m: degerler[m.group(1)], p) for p in parcalar]


class _YonlendirmeYok(urllib.request.HTTPRedirectHandler):
    """Yönlendirme izlenmez: Authorization başlığı başka bir adrese taşınmasın."""

    def redirect_request(self, *args, **kwargs):
        return None


def api_cagir(s, model, istem, sure):
    """OpenAI uyumlu /chat/completions; yalnız reviewer rolü. (kod, cevap, günlük)."""
    url = s.taban_url.rstrip("/") + "/chat/completions"
    parca = urllib.parse.urlsplit(url)
    if parca.scheme not in ("https", "http") or not parca.hostname:
        raise AkisHatasi(f"{s.ad}: taban_url http(s) olmalı")
    basliklar = {"Content-Type": "application/json"}
    if s.anahtar_env:
        anahtar = os.environ.get(s.anahtar_env)
        if not anahtar:
            raise AkisHatasi(f"{s.ad}: {s.anahtar_env} ortamda yok")
        if parca.scheme == "http" and parca.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise AkisHatasi(f"{s.ad}: anahtar şifresiz http ile yalnız yerel adrese gider")
        basliklar["Authorization"] = "Bearer " + anahtar
    govde = json.dumps({"model": model, "messages": [{"role": "user", "content": istem}]}).encode("utf-8")
    istek = urllib.request.Request(url, data=govde, headers=basliklar, method="POST")
    try:
        with urllib.request.build_opener(_YonlendirmeYok).open(istek, timeout=sure) as yanit:
            veri = json.loads(yanit.read().decode("utf-8"))
        cevap = veri["choices"][0]["message"]["content"]
        if not isinstance(cevap, str):
            raise TypeError("content metin değil")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError) as e:
        return 1, "", maskele(f"[nobet-akis: api çağrısı başarısız: {type(e).__name__}: {e}]\n", os.environ)
    cevap = maskele(cevap, os.environ)
    return 0, cevap, cevap


def ajan_kos(s, model, rol, istem, wt, sure):
    """Ajanı çalıştırır: (kod, cevap, günlük). Çıktılar kayda düşmeden maskelenir."""
    if s.tur != "cli":
        if rol == "yazici":
            raise AkisHatasi(f"{s.ad}: tur={s.tur} dosya düzenleyemez; yazıcı için tur=cli sağlayıcı kullan")
        return api_cagir(s, model, istem, sure)
    with tempfile.TemporaryDirectory(prefix="nobet-akis-") as gecici:
        istem_f, cikti_f = Path(gecici) / "istem.md", Path(gecici) / "cevap.md"
        istem_f.write_text(istem, encoding="utf-8", newline="\n")
        argv = komut_kur(s.komut, {"istem": str(istem_f), "worktree": str(wt), "model": model,
                                   "cikti": str(cikti_f), "rol": rol})
        girdi = None if "{istem}" in s.komut else istem.encode("utf-8")
        kod, out = calistir(argv, wt, _sirsiz_ortam(), girdi, sure)
        gunluk = maskele(out.decode("utf-8", "replace"), os.environ)
        cevap = gunluk
        if "{cikti}" in s.komut:
            cevap = maskele(cikti_f.read_text(encoding="utf-8", errors="replace"), os.environ) if cikti_f.is_file() else ""
    return kod, cevap, gunluk


def _saglayici_bul(profil_adi, rol, saglayicilar=None):
    saglayicilar = ayar.saglayicilar() if saglayicilar is None else saglayicilar
    tablo = profil.profiller_kur(saglayicilar)
    try:
        p = profil.profil_coz(profil_adi, tablo)
    except profil.ProfilHatasi as e:
        raise AkisHatasi(f"{e} (bkz. nobet-akis profiller)") from None
    if rol not in p.roller:
        raise AkisHatasi(f"{profil_adi} profilinin {rol} rolü yok")
    s = next(x for x in saglayicilar if x.ad == p.firma)
    return s, tablo


# --- koruma mührü: ajan çalışırken şerit kaydı ve git meta verisi ---------------------------

def _muhur_yollari(d, wt):
    ortak = Path(_git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    ozel = Path(_git(wt, "rev-parse", "--path-format=absolute", "--git-dir"))
    return [d, ortak / "hooks"], [ortak / "config", ozel / "config.worktree"]


def _hal(f):
    """("dosya", içerik) | ("yok",) | ("diger",): bağ ya da dizin içeriğine girilmez."""
    if f.is_symlink() or (f.exists() and not f.is_file()):
        return ("diger",)
    return ("dosya", f.read_bytes()) if f.is_file() else ("yok",)


def muhur_al(d, wt):
    """Ajan öncesi: şerit dizini, git config ve hook dosyalarının hali."""
    dizinler, dosyalar = _muhur_yollari(d, wt)
    hal = {}
    for k in dizinler:
        if k.is_dir():
            for f in k.iterdir():
                hal[f] = _hal(f)
    for f in dosyalar:
        hal[f] = _hal(f)
    return d, dizinler, hal


def muhur_dogrula(muhur):
    """Ajan sonrası: değişeni bildirir. Değişen ya da silinen dosyanın mühürlü içeriği geri yazılır;
    eklenen dosya yalnız şerit dizinindeyse silinir, git meta verisinde yalnız bildirilir."""
    d, dizinler, hal = muhur
    ihlal = []
    for f, once in hal.items():
        simdi = _hal(f)
        if simdi == once:
            continue
        ihlal.append(f"{f.name} " + ("eklendi" if once == ("yok",) else "değişti"))
        if once[0] == "dosya" and (f.is_symlink() or not f.is_dir()):
            if os.path.lexists(f):
                f.unlink()  # bağ ise yalnız bağ kalkar
            f.write_bytes(once[1])
    for k in dizinler:
        if k.is_dir():
            for f in k.iterdir():
                if f in hal:
                    continue
                ihlal.append(f"{f.name} eklendi ({k.name})")
                if k == d and (f.is_symlink() or f.is_file()):
                    f.unlink()
    return ihlal


def _koruma_yaz(d, rol, ihlal):
    for satir in ihlal:
        _ekle(d / KORUMA, f"{_simdi()}\t{rol}\t{satir}")
        print(f"koruma_ihlal: {rol}: {satir}")


def _koruma_ihlalleri(d):
    f = d / KORUMA
    return [s for s in f.read_text(encoding="utf-8").splitlines() if s.strip()] if f.is_file() else []


# --- fark -----------------------------------------------------------------------------------

def fark_metni(wt, taban, ozet=False):
    """Tabana göre fark (commit'li, commit'lenmemiş ve yeni dosyalar). Gerçek index'e dokunmaz."""
    with tempfile.TemporaryDirectory(prefix="nobet-akis-") as gecici:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(gecici) / "index"))
        _git(wt, "read-tree", "HEAD", env=env)
        _git(wt, "add", "-A", "--", ".", *_HARIC, env=env)
        args = ["diff", "--cached", "--no-color", "--no-ext-diff"] + (["--stat"] if ozet else [])
        return _git(wt, *args, taban, "--", ".", *_HARIC, env=env)


def _agac_ozeti(wt):
    durum = _git(wt, "status", "--porcelain", "--", ".", *_HARIC)
    try:
        dh = bitti.durum_hash(wt)
    except bitti.DurumHashHatasi:
        dh = ""
    return _git(wt, "rev-parse", "HEAD"), durum, dh


def _kapi(d, wt):
    """(sonuç, çıktı satırları); kapi.denetle çıktısını yakalar ve basar."""
    tampon = io.StringIO()
    with contextlib.redirect_stdout(tampon):
        sonuc = kapi.denetle(d, wt)
    print(tampon.getvalue(), end="")
    return sonuc, [s for s in tampon.getvalue().splitlines() if s.strip()]


# --- komutlar -------------------------------------------------------------------------------

def _glob_listesi(kaliplar, ad):
    sonuc = []
    for g in kaliplar or ():
        g = g.strip()
        if not g or "\n" in g or "\r" in g or g.startswith("#"):
            raise AkisHatasi(f"{ad}: geçersiz glob: {g!r}")
        if g.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", g) or ".." in g.replace("\\", "/").split("/"):
            raise AkisHatasi(f"{ad}: glob repo köküne göreli olmalı: {g}")
        sonuc.append(g)
    return sonuc


def _kabul_cifti(deger):
    kaynak, esit, hedef = deger.rpartition("=")
    if not esit or not kaynak or not hedef:
        raise AkisHatasi(f"--kabul KAYNAK=HEDEF biçiminde olmalı: {deger}")
    yol = posixpath.normpath(hedef.replace("\\", "/"))
    if yol.startswith(("/", "../")) or yol in (".", "..") or re.match(r"^[A-Za-z]:", yol):
        raise AkisHatasi(f"kabul hedefi worktree'ye göreli olmalı: {hedef}")
    if not kapi.TEST.search(yol):
        raise AkisHatasi(f"kabul hedefi test dosyası olmalı: {yol}")
    if not Path(kaynak).is_file():
        raise AkisHatasi(f"kabul kaynağı yok: {kaynak}")
    return Path(kaynak), yol


def _worktree_listesi(repo):
    """[(yol, dal ref'i ya da '')]; ilk kayıt ana çalışma ağacıdır."""
    kayitlar, yol, dal = [], None, ""
    for satir in _git(repo, "worktree", "list", "--porcelain").splitlines() + [""]:
        if satir.startswith("worktree "):
            yol, dal = satir[len("worktree "):], ""
        elif satir.startswith("branch "):
            dal = satir[len("branch "):]
        elif not satir and yol is not None:
            kayitlar.append((yol, dal))
            yol = None
    return kayitlar


def ac(repo, ad, sahiplik, test_izni=(), sozlesme=None, bitti_komut=None, kabuller=(), worktree=None):
    _ad_dogrula(ad)
    # Önce yan etkisiz doğrulama: biçim hatası şerit açmadan reddedilir.
    sah = _glob_listesi(sahiplik, "sahiplik")
    if not sah:
        raise AkisHatasi("en az bir --sahiplik glob'u gerekli")
    izin = _glob_listesi(test_izni, "test-izni")
    kayit = {"sahiplik": "\n".join(sah) + "\n"}
    if izin:
        kayit["test-izni"] = "\n".join(izin) + "\n"
    if sozlesme is not None:
        metin = Path(sozlesme).read_text(encoding="utf-8-sig")
        hatalar = kapi.sozlesme_dogrula(metin)
        for h in hatalar:
            print("sozlesme_hata: " + h)
        if hatalar:
            raise AkisHatasi("sözleşme biçimi hatalı; şerit açılmadı")
        kayit["sozlesme.md"] = metin
    if bitti_komut is not None:
        if not bitti_komut.strip():
            raise AkisHatasi("--bitti boş olamaz")
        kayit["bitti.cmd"] = bitti_komut.rstrip("\n") + "\n"
    with tempfile.TemporaryDirectory(prefix="nobet-akis-") as gecici:
        for ad_, icerik in kayit.items():
            (Path(gecici) / ad_).write_text(icerik, encoding="utf-8", newline="\n")
        try:
            bitti.bitti_komutu(Path(gecici))
        except (bitti.BittiYok, bitti.BozukBitti) as e:
            raise AkisHatasi(f"bitti komutu gerekli (--bitti ya da sözleşmede ```bitti bloğu): {e}") from None
    kabul = [_kabul_cifti(k) for k in kabuller]

    ust = _git(Path(repo), "rev-parse", "--show-toplevel")
    ana = Path(_worktree_listesi(ust)[0][0])
    taban = _git(ust, "rev-parse", "--verify", "HEAD^{commit}")
    dal, taban_dal = f"nobet/{ad}", f"nobet-taban/{ad}"
    for b in (dal, taban_dal):
        if subprocess.run(["git", "-C", ust, "show-ref", "--verify", "--quiet", f"refs/heads/{b}"],
                          capture_output=True, check=False).returncode == 0:
            raise AkisHatasi(f"dal zaten var: {b}")
    wt = Path(os.path.abspath(worktree)) if worktree else ana.parent / f"{ana.name}-nobet-{ad}"
    if wt.exists() or os.path.lexists(wt):
        raise AkisHatasi(f"worktree yolu dolu: {wt}")
    if _icinde(wt, ana) or _icinde(wt, kok()):
        raise AkisHatasi("worktree ana repo ya da şerit kökü içinde olamaz")
    if _git(ust, "status", "--porcelain"):
        print("UYARI: repoda commit'lenmemiş değişiklik var; worktree yalnız HEAD'i alır.", file=sys.stderr)

    isler = kok() / "isler"
    isler.mkdir(parents=True, exist_ok=True)
    d = isler / ad
    try:
        d.mkdir()
    except FileExistsError:
        raise AkisHatasi(f"şerit zaten var: {ad}") from None
    olusan = []
    try:
        _git(ust, "branch", taban_dal, taban)
        olusan.append(taban_dal)
        olusan.append(dal)
        _git(ust, "worktree", "add", "-q", "-b", dal, str(wt), taban)
        for ad_, icerik in {"repo": f"{ana}\n", "worktree": f"{wt}\n", "taban": f"{taban}\n",
                            "dal": f"{dal}\n", **kayit}.items():
            _yaz(d / ad_, icerik)
        for kaynak, hedef in kabul:
            (wt / hedef).parent.mkdir(parents=True, exist_ok=True)
            if (wt / hedef).exists():
                raise AkisHatasi(f"kabul hedefi worktree'de zaten var: {hedef}")
            (wt / hedef).write_bytes(kaynak.read_bytes())
        if kabul:
            kapi.kabul_yaz(d, wt, [h for _, h in kabul])
    except BaseException:
        _ac_geri_al(ana, wt, olusan, d, isler)
        raise
    print(f"şerit açıldı: {ad}\nworktree: {wt}\niş dizini: {d}\ntaban: {taban}")
    return 0


def _ac_geri_al(ana, wt, dallar, d, isler):
    """Yarım açılışı geri alır: worktree git ile, dallar (bu çağrı açtı) git ile, iş dizini yalnız kendisi."""
    if (wt / ".git").exists():
        subprocess.run(["git", "-C", str(ana), "worktree", "remove", "--force", str(wt)], capture_output=True, check=False)
    subprocess.run(["git", "-C", str(ana), "worktree", "prune"], capture_output=True, check=False)
    for b in dallar:
        subprocess.run(["git", "-C", str(ana), "branch", "-D", b], capture_output=True, check=False)
    if d.parent == isler and d.is_dir() and not d.is_symlink():
        shutil.rmtree(d)
    print("şerit açılamadı; geri alındı", file=sys.stderr)


def kabul(ad, yollar):
    d, wt = serit(ad)
    return kapi.kabul_yaz(d, wt, yollar)


def _yaz_istemi(d, brief):
    parcalar = [brief.rstrip()]
    sah = kapi.kaliplar(d / "sahiplik") or []
    parcalar.append("Sahiplik (yalnız bu yollara dokunabilirsin):\n" + "\n".join(f"- {g}" for g in sah))
    izin = kapi.kaliplar(d / "test-izni") or []
    if izin:
        parcalar.append("Değiştirilmesine izin verilen mevcut testler:\n" + "\n".join(f"- {g}" for g in izin))
    soz = kapi.sozlesme_metni_oku(d)
    if soz.strip():
        parcalar.append("Kabul sözleşmesi (işe başlamadan sabitlendi, değiştirme):\n" + soz.rstrip())
    parcalar.append(kapi.BICIM["yaz"])
    return "\n\n".join(parcalar) + "\n"


def _ajan_adimi(d, wt, s, model, rol, istem, onek):
    """İstemi kaydeder, mühürler, ajanı çalıştırır, mührü doğrular. (n, kod, cevap, ihlal)."""
    n = _sonraki(d, onek)
    _yaz(d / f"istem-{onek}-{n}.md", istem)
    muhur = muhur_al(d, wt)
    kod, cevap, gunluk = ajan_kos(s, model, rol, istem, wt, _sure("NOBET_AKIS_SURE", "45m"))
    ihlal = muhur_dogrula(muhur)
    _yaz(d / f"{onek}-{n}.log",
         f"tarih: {_simdi()}\nprofil: {model}\nsaglayici: {s.ad}\ncikis: {kod}\n\n{gunluk}")
    _yaz(d / f"{onek}-{n}.md", cevap)
    if ihlal:
        _koruma_yaz(d, rol, ihlal)
    return n, kod, cevap, ihlal


def yaz(ad, profil_adi, brief):
    d, wt = serit(ad)
    s, _ = _saglayici_bul(profil_adi, "yazici")
    metin = Path(brief).read_text(encoding="utf-8-sig")
    if not metin.strip():
        raise AkisHatasi("brief boş")
    _yaz(d / "yazici", profil_adi + "\n")
    n, kod, cevap, ihlal = _ajan_adimi(d, wt, s, profil_adi, "yazici", _yaz_istemi(d, metin), "yaz")
    print("\n".join(cevap.splitlines()[-40:]))
    print(f"--- {s.ad}/{profil_adi} · kayıt: {d / f'yaz-{n}.log'}")
    if ihlal:
        print("yazıcı şerit kaydını ya da git meta verisini değiştirdi; denetle reddedecek")
        return 1
    if kod:
        print(f"yazıcı çıkış {kod}" + (" (zaman aşımı)" if kod == 124 else ""))
        return 1
    print(f"sıradaki adım: nobet-akis denetle {ad}")
    return 0


def _son_rapor(d):
    sayilar = [int(m.group(1)) for f in d.iterdir() if (m := re.fullmatch(r"yaz-(\d+)\.md", f.name))]
    return d / f"yaz-{max(sayilar)}.md" if sayilar else None


def denetle(ad, rapor_yolu=None):
    """Sıra (fail-closed): bitti komutu -> durum özeti -> sert kapı -> bitti.log -> sözleşme komutları -> rapor."""
    d, wt = serit(ad)
    try:
        komut = bitti.bitti_komutu(d)
    except (bitti.BittiYok, bitti.BozukBitti) as e:
        raise AkisHatasi(f"bitti komutu: {e}") from None
    kod, out = calistir(["sh", "-c", komut], wt, _sirsiz_ortam(), None, _sure("NOBET_BITTI_SURE", "15m"))
    baslik, denetlenemedi = [], False
    try:
        dh = bitti.durum_hash(wt)
    except bitti.DurumHashHatasi:
        dh, kod = "", 125
        baslik.append("neden: durum_hash hesaplanamadı")
    try:
        kk, satirlar = _kapi(d, wt)
    except kapi.Denetlenemedi as e:
        kk, satirlar, denetlenemedi = 2, [f"kapi: denetlenemedi: {e}"], True
        print(satirlar[0])
    baslik += satirlar
    koruma = _koruma_ihlalleri(d)
    baslik += [f"koruma_ihlal: {s}" for s in koruma]
    if (kk or koruma) and kod == 0:
        kod = 1
    kuyruk = maskele(out.decode("utf-8", "replace"), os.environ).splitlines()[-20:]
    log = (f"tarih: {_simdi()}\nkomut_hash: {bitti.komut_hash(komut)}\ncikis: {kod}\ndurum_hash: {dh}\n"
           + "".join(s + "\n" for s in baslik) + "\n"
           + "".join("komut| " + s + "\n" for s in komut.split("\n"))
           + "".join("cikti| " + s + "\n" for s in kuyruk))
    _yaz(d / "bitti.log", log)
    print(f"bitti: çıkış {kod}")
    if denetlenemedi:
        return 2
    kapi.madde_kos(d, wt)
    rapor_f = Path(rapor_yolu) if rapor_yolu else _son_rapor(d)
    if rapor_f is None or not rapor_f.is_file() or not rapor_f.read_text(encoding="utf-8", errors="replace").strip():
        print("rapor_hata: yazıcı raporu yok (nobet-akis yaz ya da --rapor)")
        rs = 1
    else:
        kopya = d / f".rapor-{os.getpid()}.md"
        shutil.copyfile(rapor_f, kopya)
        try:
            rs = kapi.rapor(d, kopya, bitti.bitti_gecerli(d, wt), str(d / "madde.log"), "yazici")
        except BaseException:
            kopya.unlink(missing_ok=True)
            raise
        kapi.rapor_kaydet(d, kopya) if rs == 0 else kopya.unlink(missing_ok=True)
    sonuc = 0 if kod == 0 and kk == 0 and rs == 0 and not koruma else 1
    print("denetle: " + ("geçti" if sonuc == 0 else "REDDEDİLDİ"))
    return sonuc


REVIEW_SABLONU = """Kod incelemesi yap. DOSYA DEĞİŞTİRME, commit atma.
İncelenecek değişiklik: şeridin tabanına ({taban}) göre fark, aşağıda (commit'li, commit'lenmemiş ve yeni dosyalar).
Kodu '{yazici}' profili yazdı. Testleri çalıştırabilirsin.
Bulguları önem sırasıyla, her biri için dosya:satır, sorun, somut başarısızlık senaryosu ve önerilen düzeltmeyle yaz.
Mevcut testler ürün davranışını değiştirecek şekilde değiştirilmiş mi ayrıca bak. Bulgu yoksa 'BULGU YOK' yaz.
"""


def _review_istemi(d, wt, yazici, ek):
    taban = _oku(d, "taban")
    fark = fark_metni(wt, taban)
    if len(fark) > FARK_SINIRI:
        fark = fark[:FARK_SINIRI] + f"\n[fark {FARK_SINIRI} karakterde kesildi; tamamı: git diff {taban}]"
    parcalar = [REVIEW_SABLONU.format(taban=taban, yazici=yazici).rstrip()]
    if ek:
        parcalar.append(ek.rstrip())
    soz = kapi.sozlesme_metni_oku(d)
    if soz.strip():
        parcalar.append("Kabul sözleşmesi:\n" + soz.rstrip())
    parcalar.append(kapi.BICIM["review"])
    parcalar.append("```diff\n" + fark + "\n```")
    return "\n\n".join(parcalar) + "\n"


def incele(ad, profil_adi=None, ek_yolu=None):
    d, wt = serit(ad)
    if not (d / "yazici").is_file():
        raise AkisHatasi("yazıcı kaydı yok: önce nobet-akis yaz")
    yazici = _oku(d, "yazici")
    saglayicilar = ayar.saglayicilar()
    tablo = profil.profiller_kur(saglayicilar)
    try:
        if profil_adi is None:
            adaylar = profil.reviewer_adaylari(yazici, tablo)
            if not adaylar:
                raise AkisHatasi("reviewer adayı yok: ayar.toml'a reviewer rolünde başka bir model ekle")
            profil_adi = adaylar[0]
        elif profil_adi == yazici:
            raise AkisHatasi("reviewer yazıcıyla aynı model olamaz")
        s, _ = _saglayici_bul(profil_adi, "reviewer", saglayicilar)
        ayni = profil.ayni_firma_mi(yazici, profil_adi, tablo)
    except profil.ProfilHatasi as e:
        raise AkisHatasi(str(e)) from None
    if ayni:
        print(f"bilgi: reviewer ve yazıcı aynı sağlayıcıda ({s.ad})")
    ek = Path(ek_yolu).read_text(encoding="utf-8-sig") if ek_yolu else ""
    once = _agac_ozeti(wt)
    n, kod, cevap, ihlal = _ajan_adimi(d, wt, s, profil_adi, "reviewer", _review_istemi(d, wt, yazici, ek), "review")
    agac = _agac_ozeti(wt) != once
    meta = {"review": n, "tarih": _simdi(), "yazici": yazici, "reviewer": profil_adi,
            "yazici_saglayici": tablo[yazici].firma, "reviewer_saglayici": s.ad, "ayni_saglayici": ayni,
            "agac_degisti": agac, "cikis": kod}
    _yaz(d / f"review-{n}.meta", json.dumps(meta, ensure_ascii=False) + "\n")
    print(cevap.rstrip())
    print(f"--- {s.ad}/{profil_adi} · kayıt: {d / f'review-{n}.log'}")
    if ihlal:
        return 1
    if agac:
        print(f"DİKKAT: reviewer worktree'yi değiştirdi; review sayılmadı. Geri alınmadı: git -C \"{wt}\" status")
        return 1
    if kod:
        print(f"reviewer çıkış {kod}; review sayılmadı")
        return 1
    tampon = io.StringIO()
    with contextlib.redirect_stdout(tampon):
        sonuc = kapi.rapor(d, d / f"review-{n}.md", False, "-", "reviewer")
    _yaz(d / f"review-{n}.sema", tampon.getvalue())
    print(tampon.getvalue(), end="")
    return sonuc


def kaydet(ad, mesaj):
    d, wt = serit(ad)
    if not mesaj.strip():
        raise AkisHatasi("commit mesajı boş")
    if _koruma_ihlalleri(d):
        print(f"koruma ihlali kayıtlı ({d / KORUMA}); commit atılmadı")
        return 1
    if not bitti.bitti_gecerli(d, wt):
        print("bitti kanıtı yeşil ve güncel değil: önce nobet-akis denetle; commit atılmadı")
        return 1
    if _kapi(d, wt)[0]:
        print("kapı reddetti; commit atılmadı")
        return 1
    log = (d / "bitti.log").read_text(encoding="utf-8")
    kh, dh = bitti.bitti_alan(log, "komut_hash"), bitti.bitti_alan(log, "durum_hash")
    _git(wt, "add", "-A", "--", ".", *_HARIC)
    if subprocess.run(["git", "-C", str(wt), "diff", "--cached", "--quiet"], check=False).returncode == 0:
        print("commit'lenecek değişiklik yok")
        return 0
    _git(wt, "commit", "-q", "-m", mesaj)
    sha = _git(wt, "rev-parse", "HEAD")
    # bitti-bag: denetimden geçmiş commit; bitti_guncel'in commit sonrası kolu bunu okur.
    _ekle(d / "bitti-bag", f"{kh}\t{dh}\t{sha}")
    _ekle(d / "kaydet.log", f"{_simdi()}\t{sha}")
    print(_git(wt, "log", "--oneline", "-1"))
    return 0


def durum(ad):
    d, wt = serit(ad)
    taban = _oku(d, "taban")
    print(f"şerit: {ad}\nworktree: {wt}\ndal: {_oku(d, 'dal')}\ntaban: {taban}")
    print(fark_metni(wt, taban, ozet=True) or "(fark yok)")
    for s in _koruma_ihlalleri(d):
        print("koruma_ihlal: " + s)
    if not (d / "bitti.log").is_file():
        print("bitti: koşulmadı")
    elif bitti.bitti_gecerli(d, wt):
        print("bitti: yeşil ve güncel")
    else:
        print("bitti: " + ("güncel ama kırmızı" if bitti.bitti_guncel(d, wt) else "güncel değil"))
    return _kapi(d, wt)[0]


def _baglari_kaldir(wt):
    """Worktree içindeki sembolik bağ/junction'ları yalnız bağ olarak siler; hedefe dokunulmaz.
    Böylece worktree kaldırma bağın gösterdiği yere (worktree dışı) inemez."""
    isjunction = getattr(os.path, "isjunction", lambda _p: False)
    for kok_, dizinler, dosyalar in os.walk(wt, topdown=True, followlinks=False):
        for ad in list(dizinler) + dosyalar:
            p = os.path.join(kok_, ad)
            if not (os.path.islink(p) or isjunction(p)):
                continue
            if not _icinde(os.path.dirname(p), wt):
                raise AkisHatasi(f"bağ worktree dışında: {p}")
            try:
                os.unlink(p)
            except (IsADirectoryError, PermissionError):
                os.rmdir(p)  # Windows dizin bağı / junction: yalnız bağ kalkar
            if ad in dizinler:
                dizinler.remove(ad)
            print(f"bağ kaldırıldı (hedefe dokunulmadı): {os.path.relpath(p, wt)}")


def kapat(ad):
    """Worktree yalnız `git worktree remove` ile kalkar; elle silme yok. Kirli ağaçta durur."""
    d, wt = serit(ad, worktree_olmali=False)
    ana, dal = Path(_oku(d, "repo")), _oku(d, "dal")
    kayitlar = _worktree_listesi(ana)
    if kayitlar and _ayni_yol(kayitlar[0][0], wt):
        raise AkisHatasi("ana çalışma ağacı kaldırılmaz; şerit kaydı bozuk")
    eslesen = [k for k in kayitlar[1:] if _ayni_yol(k[0], wt)]
    if not os.path.lexists(wt):
        _git(ana, "worktree", "prune")
        print("worktree zaten yok")
        return 0
    if wt.is_symlink():
        raise AkisHatasi(f"{wt} sembolik bağ; dokunmadım")
    if not eslesen:
        raise AkisHatasi(f"{wt} bu repoya kayıtlı bir worktree değil; dokunmadım")
    if eslesen[0][1] != f"refs/heads/{dal}":
        raise AkisHatasi(f"worktree dalı şeridinki değil ({eslesen[0][1] or 'ayrık HEAD'}); dokunmadım")
    kanit = False
    if wt.is_dir():
        kalan = _git(wt, "status", "--porcelain", "--", ".", *_HARIC)
        if kalan:
            print("commit'lenmemiş değişiklik var, kaldırmadım (önce nobet-akis kaydet):\n" + kalan)
            return 1
        kanit = bitti.bitti_gecerli(d, wt)
        _baglari_kaldir(wt)
    r = subprocess.run(["git", "-C", str(ana), "worktree", "remove", "--force", str(wt)],
                       capture_output=True, check=False)
    if r.returncode:
        print(r.stderr.decode("utf-8", "replace").strip(), file=sys.stderr)
        if os.path.lexists(wt):
            print(f"YARIM KLASÖR: {wt} kaldırılamadı; elle bak (silmedim)", file=sys.stderr)
        return 1
    _git(ana, "worktree", "prune")
    if kanit:
        _yaz(d / "durum-isaret", "teslim\n")
    print(f"worktree kaldırıldı; dal {dal} duruyor" + (" (teslim: yeşil bitti kanıtı)" if kanit else ""))
    return 0


def profiller():
    tablo = profil.profil_tablosu()
    print(tablo or "profil yok: ayar.toml'a [[saglayici]] ekle (bkz. ornek/ayar.ornek.toml)")
    return 0


# --- komut satırı ---------------------------------------------------------------------------

def _ayristirici():
    p = argparse.ArgumentParser(prog="nobet-akis", description="nobet orkestrasyon kabuğu",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    alt = p.add_subparsers(dest="komut", required=True)
    a = alt.add_parser("ac", help="şerit aç")
    a.add_argument("repo")
    a.add_argument("ad")
    a.add_argument("--sahiplik", action="append", default=[], required=True)
    a.add_argument("--test-izni", action="append", default=[])
    a.add_argument("--sozlesme")
    a.add_argument("--bitti")
    a.add_argument("--kabul", action="append", default=[], metavar="KAYNAK=HEDEF")
    a.add_argument("--worktree")
    k = alt.add_parser("kabul", help="kabul testini dondur")
    k.add_argument("ad")
    k.add_argument("yollar", nargs="+")
    y = alt.add_parser("yaz", help="yazıcı ajanı çalıştır")
    y.add_argument("ad")
    y.add_argument("profil")
    y.add_argument("brief")
    dn = alt.add_parser("denetle", help="bitti + kapı + sözleşme + rapor")
    dn.add_argument("ad")
    dn.add_argument("--rapor")
    i = alt.add_parser("incele", help="reviewer çalıştır")
    i.add_argument("ad")
    i.add_argument("--profil")
    i.add_argument("--ek")
    kd = alt.add_parser("kaydet", help="şerit dalına commit")
    kd.add_argument("ad")
    kd.add_argument("-m", "--mesaj", required=True)
    for ad_, yardim in (("durum", "şerit durumu"), ("kapat", "worktree'yi kaldır")):
        alt.add_parser(ad_, help=yardim).add_argument("ad")
    alt.add_parser("profiller", help="profiller")
    return p


def main(argv=None):
    ns = _ayristirici().parse_args(argv)
    try:
        if ns.komut == "ac":
            return ac(ns.repo, ns.ad, ns.sahiplik, ns.test_izni, ns.sozlesme, ns.bitti, ns.kabul, ns.worktree)
        if ns.komut == "kabul":
            return kabul(ns.ad, ns.yollar)
        if ns.komut == "yaz":
            return yaz(ns.ad, ns.profil, ns.brief)
        if ns.komut == "denetle":
            return denetle(ns.ad, ns.rapor)
        if ns.komut == "incele":
            return incele(ns.ad, ns.profil, ns.ek)
        if ns.komut == "kaydet":
            return kaydet(ns.ad, ns.mesaj)
        if ns.komut == "durum":
            return durum(ns.ad)
        if ns.komut == "kapat":
            return kapat(ns.ad)
        return profiller()
    except (AkisHatasi, kapi.Denetlenemedi, ValueError, OSError) as e:
        print(f"nobet-akis: {e}", file=sys.stderr)
        return 2


def cli():
    """Komut satırı girişi (`nobet-akis`)."""
    for akis_ in (sys.stdout, sys.stderr):
        if hasattr(akis_, "reconfigure"):
            akis_.reconfigure(encoding="utf-8", newline="\n")
    sys.exit(main())


if __name__ == "__main__":
    cli()
