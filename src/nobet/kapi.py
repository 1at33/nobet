"""nobet sert kapısı: derleyici gibi, ihlal varsa reddeder (uyarı değil).

Komutlar:
  nobet denetle <iş dizini> <worktree> [--eski]
      sahiplik dışı değişiklik, mevcut test dosyası değişikliği/silinmesi ve dondurulmuş
      kabul testi değişikliği. Çıkış 0 temiz, 1 ihlal, 2 denetlenemedi (fail-closed).
  nobet kabul <iş dizini> <worktree> <yol>...
      kabul testlerini içerik hash'iyle dondurur (isler/<şerit>/kabul).
  nobet rapor <iş dizini> <rapor.md> <bitti_gecerli 0|1> [madde.log|-] [yazici|reviewer]
      raporu şemaya göre denetler; madde.log verilirse sözleşme komutlarının gerçek çıkışıyla
      karşılaştırır (kanıt içeriği). reviewer rolünde bitti satırı ve bitti kanıtı aranmaz.
      Çıkış 0 geçerli, 1 geçersiz.
  nobet madde-kos <iş dizini> <worktree>      sözleşme komutlarını koşar (madde.log)
  nobet kapsam-disi <iş dizini> <worktree>   ilerleme ölçümü: sahiplik dışı yollar
  nobet bicim yaz|review                     yazıcı/reviewer rapor biçimi metni
  nobet rapor ... --kaydet                   geçerse kopyayı rapor-N.md yap, değilse sil
  nobet sozlesme-dogrula <madde.md>
      sözleşme biçimi (tekrarlı numara, koşulamayan "çıkış N"); çıkış 0 geçerli, 1 hata.
  nobet madde-cmd <iş dizini> <çıkış dizini>
      sözleşmede "`komut` → çıkış N" biçimindeki maddeleri madde-N.cmd olarak yazar;
      stdout'a "N<TAB>N_beklenen" satırları (inceleme aracı; orkestratörün madde-kos adımı kullanır).

İzinler yalnız vekilin iş dizinindeki dosyalarla verilir (worktree'den değil):
  sahiplik   satır başı glob; yazıcının dokunabileceği yollar
  test-izni  satır başı glob; değişmesine izin verilen mevcut test dosyaları
  kabul      <blob hash>\\t<yol>; içeriği dondurulmuş kabul testleri
"""

import os
import posixpath
import re
import subprocess
import sys
from pathlib import Path

HARIC = re.compile(r"(^|/)(__pycache__|\.pytest_cache|node_modules)(/|$)|\.pyc$")
# Test dosyası ve test davranışını değiştiren yapılandırma (conftest, pytest.ini) aynı korumayı alır.
TEST = re.compile(
    r"(^|/)(tests?/|__tests__/|spec/|test_[^/]*$|test-[^/]*$|tests?\.py$|conftest\.py$|pytest\.ini$"
    r"|[^/]*_test\.[a-z]+$|[^/]*_spec\.[a-z]+$|[^/]*(?-i:Test).[a-z]+$|[^/]*\.(test|spec)\.[a-z]+$)",
    re.IGNORECASE,
)
# Yeni olsa bile pytest'i yükleme sırasında etkileyip sonucu değiştirebilen dosyalar.
SONUC_DEGISTIREN = re.compile(r"(^|/)(sitecustomize\.py|usercustomize\.py|conftest\.py|[^/]*\.pth)$", re.IGNORECASE)
# pytest'in kendi yapılandırma dosyaları: her değişiklik (yeni dahil) test sonucunu değiştirebilir.
PYTEST_AYAR = re.compile(r"(^|/)\.?pytest\.(ini|toml)$", re.IGNORECASE)
# Ortak yapılandırma dosyaları: yalnız pytest bölümü taşıyorsa (önce ya da sonra) test sonucunu değiştirebilir.
ORTAK_AYAR = re.compile(r"(^|/)(pyproject\.toml|setup\.cfg|tox\.ini)$", re.IGNORECASE)
PYTEST_BOLUM = re.compile(rb"^[ \t]*\[(tool\.pytest|tool:pytest|pytest)(\]|\.|$)", re.MULTILINE)
# Test dizinindeki paket dosyası test modülü yüklenirken çalışır.
TEST_PAKET = re.compile(r"(^|/)(tests?|__tests__|spec)/(.*/)?__init__\.py$", re.IGNORECASE)
HEX = re.compile(r"[0-9a-fA-F]{7,40}")
# --eski: taban sha'sı ya da sahiplik dosyası olmayan eski şerit/test fikstürü; yalnız uyarı.
# Yalnız komut satırı bayrağıyla açılır: ortam değişkeni ajanın ortamından kapıyı sessizce gevşetebilirdi.
ESKI = False


class Denetlenemedi(Exception):
    """Kapı kararı verilemedi; fail-closed."""


# Yazıcının .git/config'i güvenilmez: fsmonitor komut çalıştırır ve değişikliği gizler, hook'lar kapıda koşmasın.
GIT_GUVENLI = ("-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "-c", "core.hooksPath=" + os.devnull)


def git(wt, *args):
    return subprocess.run(["git", *GIT_GUVENLI, "-C", str(wt), *args], capture_output=True, check=False)


def desen(g):
    """Orkestratör ledger'ındaki sahiplik glob'uyla aynı anlam: ** dizin geçer, * tek parça."""
    r, i = "", 0
    while i < len(g):
        if g[i:i + 3] == "**/":
            r, i = r + "(?:.*/)?", i + 3
            continue
        if g[i:i + 2] == "**":
            r, i = r + ".*", i + 2
            continue
        c = g[i]
        r += "[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c)
        i += 1
    return re.compile("^" + r + "$")


def kaliplar(dosya):
    if not dosya.is_file():
        return None
    satirlar = dosya.read_text(encoding="utf-8-sig").splitlines()  # -sig: Not Defteri BOM'u ilk kalıbı bozmasın
    return [s.strip() for s in satirlar if s.strip() and not s.strip().startswith("#")]


def eslesir(yol, kalip):
    for g in kalip:
        if desen(g).match(yol) or yol.startswith(g.rstrip("/") + "/"):
            return True
    return False


def degisenler(wt, taban):
    """{yol: durum}; durum A/M/D, taban'a göre (izlenen + izlenmeyen), yeniden adlandırma = D + A."""
    r = git(wt, "diff", "--no-renames", "--name-status", "-z", taban)
    if r.returncode:
        raise Denetlenemedi("git diff taban başarısız: " + r.stderr.decode("utf-8", "replace").strip())
    parca = [p.decode("utf-8", "replace") for p in r.stdout.split(b"\0") if p]
    sonuc = {}
    for i in range(0, len(parca) - 1, 2):
        sonuc[parca[i + 1]] = parca[i][0]
    # Yalnız .gitignore kuralları: .git/info/exclude ve core.excludesFile yazıcının gizleme yolu olmasın.
    r = git(wt, "-c", "core.excludesFile=", "ls-files", "--others", "--exclude-per-directory=.gitignore", "-z")
    if r.returncode:
        raise Denetlenemedi("git ls-files başarısız")
    for p in r.stdout.split(b"\0"):
        if p:
            sonuc.setdefault(p.decode("utf-8", "replace"), "A")
    # Kendini de gizleyen yeni .gitignore (ör. içinde "*"): izlenmeyen ama yok sayılan .gitignore dosyası.
    r = git(wt, "-c", "core.excludesFile=", "ls-files", "--others", "--ignored",
            "--exclude-per-directory=.gitignore", "-z")
    if r.returncode:
        raise Denetlenemedi("git ls-files --ignored başarısız")
    for p in r.stdout.split(b"\0"):
        y = p.decode("utf-8", "replace")
        if y and posixpath.basename(y) == ".gitignore":
            sonuc[y] = "G"
    return {y: s for y, s in sonuc.items() if not HARIC.search(y)}


def gizli_index(wt):
    """assume-unchanged (küçük harf etiket) ya da skip-worktree (S) bayraklı ve diskte index'ten farklı yollar.
    Bu bayraklar değişikliği git diff/status'tan gizler; sparse checkout'ta diskte olmayan yol sorun değildir."""
    r = git(wt, "ls-files", "-v", "-s", "-z")
    if r.returncode:
        raise Denetlenemedi("git ls-files -v başarısız")
    gizli = []
    for kayit in r.stdout.split(b"\0"):
        if not kayit:
            continue
        bas, _, yol = kayit.decode("utf-8", "replace").partition("\t")
        alan = bas.split()
        if len(alan) < 3:
            continue
        etiket, ndx_blob = alan[0], alan[2]
        if not (etiket.islower() or etiket.upper() == "S"):
            continue
        if (wt / yol).is_file() and blob(wt, yol) != ndx_blob:
            gizli.append(yol)
    return gizli


def kabul_oku(d):
    f = d / "kabul"
    if not f.is_file():
        return {}
    kayit = {}
    for satir in f.read_text(encoding="utf-8-sig").splitlines():
        if not satir.strip() or satir.startswith("#"):
            continue
        h, _, yol = satir.partition("\t")
        if not HEX.fullmatch(h) or not yol:
            raise Denetlenemedi("kabul dosyası bozuk satır: " + satir)
        kayit[yol] = h
    return kayit


def blob(wt, yol):
    # --no-filters: yazıcının .gitattributes + filter.*.clean ikilisi değişmiş testi eski içerik gibi göstermesin.
    r = git(wt, "hash-object", "--no-filters", "--", yol)
    if r.returncode:
        raise Denetlenemedi("hash-object başarısız: " + yol)
    return r.stdout.decode().strip()


def yerel_filtreler(wt):
    """Yazıcının yazabildiği repo/worktree yapılandırmasındaki filter sürücüleri. Clean filtresi git diff'in
    gördüğü içeriği değiştirir (değişen test eski haliyle görünür); kapı bunları güvenilmez sayar."""
    adlar = set()
    for kapsam in ("--local", "--worktree"):
        r = git(wt, "config", kapsam, "--name-only", "--get-regexp", r"^filter\.")
        if r.returncode not in (0, 1):  # 1 = eşleşme yok; --worktree kapalıysa 128, yerel kapsam yeter
            if kapsam == "--local":
                raise Denetlenemedi("git config okunamadı")
            continue
        for satir in r.stdout.decode("utf-8", "replace").splitlines():
            if satir.strip():
                adlar.add(satir.strip())
    return sorted(adlar)


def taban_icerik(wt, taban, yol):
    r = git(wt, "cat-file", "blob", f"{taban}:{yol}")
    return r.stdout if r.returncode == 0 else b""


def sonuc_riski(wt, taban, yol, durum):
    """Yeni ya da değişen dosya test sonucunu değiştirebiliyorsa nedeni; değilse None."""
    if SONUC_DEGISTIREN.search(yol) or PYTEST_AYAR.search(yol):
        return "test sonucunu değiştirebilen dosya"
    if durum == "A" and TEST_PAKET.search(yol):
        return "test sonucunu değiştirebilen dosya (test paketi __init__)"
    if ORTAK_AYAR.search(yol):
        simdi = b""
        if durum != "D":
            try:
                simdi = (wt / yol).read_bytes()
            except OSError:
                simdi = b""
        if PYTEST_BOLUM.search(simdi) or PYTEST_BOLUM.search(taban_icerik(wt, taban, yol)):
            return "pytest yapılandırması değişti"
    if posixpath.basename(yol) == ".gitignore" and durum != "D":
        return ".gitignore değişti (dosya gizleyebilir)"
    return None


def denetle(d, wt):
    ihlal = []
    for ad in yerel_filtreler(wt):
        ihlal.append((".git/config", f"yerel git filtresi ({ad}): içerik karşılaştırmasını değiştirebilir"))
    kabul = kabul_oku(d)
    for yol, h in sorted(kabul.items()):
        if not (wt / yol).is_file():
            ihlal.append((yol, "kabul testi silindi"))
        elif blob(wt, yol) != h:
            ihlal.append((yol, "kabul testi değişti"))

    for yol in gizli_index(wt):
        ihlal.append((yol, "index bayrağıyla gizlenmiş değişiklik (assume-unchanged/skip-worktree)"))

    taban_f = d / "taban"
    taban = taban_f.read_text(encoding="utf-8").strip() if taban_f.is_file() else ""
    if not HEX.fullmatch(taban):
        if not ESKI:
            raise Denetlenemedi("taban sha'sı yok ya da bozuk (eski şerit için --eski)")
        print("kapi: UYARI: taban yok; sahiplik/test denetimi atlandı (--eski)")
    else:
        if git(wt, "cat-file", "-e", taban + "^{commit}").returncode:
            raise Denetlenemedi("taban commit çözülemedi: " + taban)
        deg = degisenler(wt, taban)
        sah = kaliplar(d / "sahiplik")
        izin = kaliplar(d / "test-izni") or []
        if sah is None:
            if not ESKI:
                raise Denetlenemedi("sahiplik dosyası yok (isler/<şerit>/sahiplik; eski şerit için --eski)")
            print("kapi: UYARI: sahiplik dosyası yok; sahiplik denetlenmedi (--eski)")
        for yol, durum in sorted(deg.items()):
            if yol in kabul:
                continue
            if durum == "G":
                ihlal.append((yol, "kendini yok sayan yeni .gitignore"))
                continue
            if sah is not None and not eslesir(yol, sah):
                ihlal.append((yol, f"sahiplik dışı ({durum})"))
            # Değişen/silinen test dosyası aşağıdaki mevcut kuralla zaten raporlanır; çift kayıt açma.
            risk = None if (durum != "A" and TEST.search(yol)) else sonuc_riski(wt, taban, yol, durum)
            if risk:
                if eslesir(yol, izin):
                    print(f"kapi_izin: {yol} (test-izni)")
                else:
                    ihlal.append((yol, risk))
            if durum != "A" and TEST.search(yol):
                if eslesir(yol, izin):
                    print(f"kapi_izin: {yol} (test-izni)")
                else:
                    ne = {"M": "değişti", "D": "silindi", "T": "türü değişti"}.get(durum, f"durumu {durum}")
                    ihlal.append((yol, "mevcut test " + ne))
    for yol, neden in ihlal:
        print(f"kapi_ihlal: {yol} ({neden})")
    if not ihlal:
        print("kapi: temiz")
    return 1 if ihlal else 0


def kabul_yaz(d, wt, yollar):
    eski = kabul_oku(d)
    yeni = []
    taban_f = d / "taban"
    taban = taban_f.read_text(encoding="utf-8").strip() if taban_f.is_file() else ""
    kok = Path(os.path.realpath(wt))
    for ham in yollar:
        p = Path(ham)
        if p.is_absolute():
            try:
                p = Path(os.path.realpath(p)).relative_to(kok)
            except ValueError:
                raise Denetlenemedi("kabul yolu worktree dışında: " + ham) from None
        yol = posixpath.normpath(str(p).replace("\\", "/"))
        if yol.startswith(("../", "/")) or yol in ("..", "."):
            raise Denetlenemedi("kabul yolu worktree dışında: " + ham)
        if not (wt / yol).is_file():
            raise Denetlenemedi("kabul testi yok: " + yol)
        # Yalnız test dosyası: kabul muafiyeti sahiplik dışı kodu (ör. src/x.py) içeri almasın.
        if not TEST.search(yol):
            raise Denetlenemedi("kabul yalnız test dosyası olabilir (test kalıbına uymuyor): " + yol)
        # Yalnız yeni dosya dondurulur: tabandaki dosyayı dondurmak mevcut test korumasını atlatırdı.
        if HEX.fullmatch(taban) and git(wt, "cat-file", "-e", f"{taban}:{yol}").returncode == 0:
            raise Denetlenemedi("tabanda var olan dosya kabul testi olarak dondurulamaz: " + yol)
        eski[yol] = blob(wt, yol)
        yeni.append(yol)
    satirlar = [f"{h}\t{y}" for y, h in sorted(eski.items())]
    (d / "kabul").write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    for y in yeni:
        print("kabul donduruldu: " + y)
    return 0


# --- Rapor şeması ---------------------------------------------------------
# Satır biçimi (büyük/küçük harf ve ı/i, ş/s farkı önemsiz):
#   madde 3: KARŞILANDI | kanıt: `py -m pytest -q` → 12 passed
#   madde 4: KARŞILANMADI | neden: ...
#   bitti: KARŞILANDI | kanıt: `orkestrator bitti <şerit>` → cikis 0
DURUM = r"(KAR[ŞS]ILANDI|KAR[ŞS]ILANMADI)"
# Satır başı süsü (madde işareti, alıntı, kalın) ve etiket çevresindeki ** / __ tolere edilir.
_SUS = r"^\s*(?:[-*>]\s*|\*\*\s*|__\s*)*"
_KAPA = r"\s*(?:\*\*|__)?\s*:\s*(?:\*\*|__)?\s*"
MADDE_SATIR = re.compile(_SUS + r"madde\s+(\d+)" + _KAPA + DURUM + r"\b(.*)$", re.IGNORECASE)
BITTI_SATIR = re.compile(_SUS + r"bitti" + _KAPA + DURUM + r"\b(.*)$", re.IGNORECASE)
KANIT = re.compile(r"kan[ıi]t\s*:\s*`([^`]+)`\s*(?:→|⇒|->|=>|:)\s*(\S.*)$", re.IGNORECASE)
NEDEN = re.compile(r"(neden|kan[ıi]t)\s*:\s*\S", re.IGNORECASE)


def karsilandi(durum):
    return not durum.upper().replace("Ş", "S").endswith("MADI")


CALISIR = re.compile(r"`([^`]+)`\s*(?:→|⇒|->|=>)\s*[çc][ıi]k[ıi][şs]\s*:?\s*(\d+)", re.IGNORECASE)
# Komutun hemen ardından oksuz "çıkış N" (ör. "`pytest` çıkış 0"): koşulmak istenmiş ama biçim tutmamış.
# Düz anlatım ("--gorev yoksa çıkış 1") hata sayılmaz: 113 gerçek sözleşmede ölçüldü (2026-11-04).
CIKIS_IZI = re.compile(r"`[^`]+`\s*[,:]?\s*[çc][ıi]k[ıi][şs]\s*:?\s*\d", re.IGNORECASE)
NUMARALI = re.compile(r"^(\d+)[.)]\s")
BASLIK = re.compile(r"^(#{1,6})\s+(.*)$")


def _ayristir(metin):
    """(madde bölümündeki satırlar, bütün numaralı satırlar, madde başlığı var mı). Kod çitleri atlanır;
    madde bölümü "madde" geçen başlıkla açılır, aynı ya da üst seviye başlıkla kapanır (alt başlık kapatmaz).
    Numaralı satır: satır başında `N.` ya da `N)` (girintili alt liste sayılmaz)."""
    bolum, hepsi, seviye, cit, baslik = [], [], None, False, False
    for satir in metin.splitlines():
        if satir.lstrip().startswith("```"):
            cit = not cit
            continue
        if cit:
            continue
        b = BASLIK.match(satir)
        if b:
            lv = len(b.group(1))
            if seviye is not None and lv <= seviye:
                seviye = None
            if seviye is None and re.search(r"madde", b.group(2), re.IGNORECASE):
                seviye, baslik = lv, True
            continue
        m = NUMARALI.match(satir)
        if m:
            hepsi.append((int(m.group(1)), satir))
            if seviye is not None:
                bolum.append((int(m.group(1)), satir))
    return bolum, hepsi, baslik


def _maddeler(metin):
    """"madde" başlığı varsa yalnız o bölüm; yoksa kod çiti dışındaki bütün numaralı satırlar."""
    bolum, hepsi, baslik = _ayristir(metin)
    return bolum if baslik else hepsi


def sozlesme_dogrula(metin):
    """Sözleşme biçim hataları: aynı numara iki kez (hangisinin madde olduğu belirsiz) ve
    "çıkış N" yazıp "`komut` → çıkış N" biçimine uymayan madde (sessizce koşulmazdı)."""
    maddeler = _maddeler(metin)
    hatalar = []
    sayilar = [n for n, _ in maddeler]
    for n in sorted({n for n in sayilar if sayilar.count(n) > 1}):
        hatalar.append(f"madde {n} iki kez (birden çok numaralı liste varsa maddeleri '## Maddeler' başlığına al)")
    for n, satir in maddeler:
        if CIKIS_IZI.search(satir) and not CALISIR.search(satir):
            hatalar.append(f"madde {n}: 'çıkış N' var ama '`komut` → çıkış N' biçiminde değil; koşulamaz")
    return hatalar


def sozlesme_metni_oku(d):
    f = d / "sozlesme.md"
    return f.read_text(encoding="utf-8-sig", errors="replace") if f.is_file() else ""


def sozlesme_satirlari(d):
    """[(numara, satır)]: madde satırları (bkz. _maddeler); biçim hatası fail-closed."""
    metin = sozlesme_metni_oku(d)
    if not metin:
        return []
    hatalar = sozlesme_dogrula(metin)
    if hatalar:
        raise Denetlenemedi("sözleşme biçimi: " + "; ".join(hatalar))
    return _maddeler(metin)


def sozlesme_maddeleri(d):
    return [n for n, _ in sozlesme_satirlari(d)]


def calisir_maddeler(d):
    """{numara: (komut, beklenen çıkış)}; yalnız "`komut` → çıkış N" yazılmış maddeler."""
    sonuc = {}
    for n, satir in sozlesme_satirlari(d):
        m = CALISIR.search(satir)
        if m and m.group(1).strip():
            sonuc[n] = (m.group(1).strip(), int(m.group(2)))
    return sonuc


def madde_cmd(d, cikis):
    cikis.mkdir(parents=True, exist_ok=True)
    for n, (komut, bek) in sorted(calisir_maddeler(d).items()):
        (cikis / f"madde-{n}.cmd").write_text(komut + "\n", encoding="utf-8")
        print(f"{n}\t{bek}")
    return 0


def sure_saniye(deger):
    """NOBET_BITTI_SURE biçimi (GNU timeout gibi): 90, 90s, 15m, 1h, 1d."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*", deger or "")
    if not m:
        raise Denetlenemedi("geçersiz süre: " + str(deger))
    return float(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def _maskele():
    """gizli.maskele; kapi.py paket dışında tek betik olarak da koşar (python -I kapi.py)."""
    try:
        from nobet.gizli import maskele
    except ImportError:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_nobet_gizli", Path(__file__).with_name("gizli.py"))
        modul = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modul)
        maskele = modul.maskele
    return maskele


def _sirsiz_ortam():
    """Sözleşme komutları için ortam: sır gibi görünen değişkenler çıkarılır (gizli.temiz_ortam).

    NOBET_ORTAM_IZIN (virgülle) yalnız orkestratörün açıkça geçirdiği adları korur."""
    try:
        from nobet.gizli import temiz_ortam
    except ImportError:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_nobet_gizli", Path(__file__).with_name("gizli.py"))
        modul = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modul)
        temiz_ortam = modul.temiz_ortam
    izin = [a.strip() for a in os.environ.get("NOBET_ORTAM_IZIN", "").split(",") if a.strip()]
    return temiz_ortam(os.environ, izin)


def madde_kos(d, wt):
    """Sözleşmenin "`komut` → çıkış N" maddelerini worktree'de koşar (stdin yok, NOBET_BITTI_SURE zaman aşımı).
    Ortam çağıran kabuktan gelir ama sır gibi görünen değişkenler çıkarılır (NOBET_ORTAM_IZIN ile açılır).
    madde.log: N<TAB>gerçek<TAB>beklenen; madde-cikti.log: çıktı kuyruğu."""
    sure = sure_saniye(os.environ.get("NOBET_BITTI_SURE", "15m"))
    log, cikti = [], []
    for n, (komut, bek) in sorted(calisir_maddeler(d).items()):
        try:
            r = subprocess.run(["sh", "-c", komut], cwd=str(wt), stdin=subprocess.DEVNULL, env=_sirsiz_ortam(),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=sure, check=False)
            k, out = r.returncode, r.stdout
        except subprocess.TimeoutExpired as e:
            k, out = 124, e.stdout or b""
        log.append(f"{n}\t{k}\t{bek}\n")
        cikti.append(f"madde {n}: çıkış {k} (beklenen {bek})\n")
        # Komut çıktısı iş dizinine düşer: sır gibi görünen değerler maskelenir.
        kuyruk = _maskele()(out.decode("utf-8", "replace"), os.environ).splitlines()[-10:]
        cikti += ["cikti| " + x + "\n" for x in kuyruk]
    for ad, satirlar in (("madde-cikti.log", cikti), ("madde.log", log)):
        gecici = d / f".{ad}.{os.getpid()}"
        gecici.write_text("".join(satirlar), encoding="utf-8", newline="\n")
        os.replace(gecici, d / ad)
    return 0


def kapsam_disi(d, wt):
    """ilerleme ölçümü: sahiplik dışı değişen yollar (red değil, ölçüm). Sahiplik ya da geçerli taban yoksa boş."""
    sah = kaliplar(d / "sahiplik")
    taban_f = d / "taban"
    taban = taban_f.read_text(encoding="utf-8").strip() if taban_f.is_file() else ""
    if not sah or not HEX.fullmatch(taban) or not Path(wt).is_dir():
        return 0
    kabul = kabul_oku(d)
    for yol in sorted(degisenler(wt, taban)):
        if yol not in kabul and not eslesir(yol, sah):
            print(yol)
    return 0


BICIM = {
    "yaz": 'Bitince raporu bu satırlarla ver (rapor kapısıyla denetlenir): her madde için "madde N: KARŞILANDI | kanıt: `komut` → çıktı satırı" ya da "madde N: KARŞILANMADI | neden: ..."; sonda "bitti: KARŞILANDI | kanıt: `bitti komutu` → çıkış 0" ya da "bitti: KARŞILANMADI | neden: ...". Karşılanmayanı gizleme: sözleşmede "`komut` → çıkış N" yazan maddeleri betik yeniden koşar, çelişen rapor reddedilir. Sahiplik dışına, mevcut testlere ve kabul testine dokunma: kapı reddeder.',
    "review": 'Her sözleşme maddesini tek tek denetle: KARŞILANDI / KARŞILANMADI + kendi çalıştırdığın kanıt. Kuşkucu ol: yazıcının raporu kanıt değildir; kendin doğrulamadığın maddeyi KARŞILANDI sayma. Her madde için tam bu satırı yaz (şema denetlenir, eksik madde reviewi geçersiz yapar): "madde N: KARŞILANDI | kanıt: `komut` → çıktı satırı" ya da "madde N: KARŞILANMADI | neden: ...". Bulgular bu satırlardan ayrı.',
}


def rapor_kaydet(d, kopya):
    """Geçerli raporun kopyasını rapor-N.md yapar, rapor.log'a git blob hash'iyle satır ekler."""
    import datetime
    import hashlib
    n = 1 + sum(1 for f in d.iterdir() if re.fullmatch(r"rapor-\d+\.md", f.name))
    hedef = d / f"rapor-{n}.md"
    os.replace(kopya, hedef)
    veri = hedef.read_bytes()
    h = hashlib.sha1(b"blob %d\0" % len(veri) + veri).hexdigest()
    tarih = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    with open(d / "rapor.log", "a", encoding="utf-8", newline="\n") as f:
        f.write(f"{tarih}\tgecerli\trapor-{n}.md\t{h}\n")
    print("rapor kaydedildi: " + str(hedef))


def madde_log_oku(yol):
    """{numara: (gerçek, beklenen)}; satır: N<TAB>gerçek<TAB>beklenen."""
    sonuc = {}
    if not yol or yol == "-":
        return sonuc
    for satir in Path(yol).read_text(encoding="utf-8").splitlines():
        p = satir.split("\t")
        if len(p) >= 3 and all(x.strip().isdigit() for x in p[:3]):
            sonuc[int(p[0])] = (int(p[1]), int(p[2]))
        elif satir.strip():
            raise Denetlenemedi("madde.log bozuk satır: " + satir)
    return sonuc


def kanit_hatasi(etiket, durum, kalan):
    if karsilandi(durum):
        if not KANIT.search(kalan):
            return f"{etiket}: KARŞILANDI ama kanıt yok ya da biçimsiz (beklenen: kanıt: `komut` → çıktı)"
    elif not NEDEN.search(kalan):
        return f"{etiket}: KARŞILANMADI ama neden yok (beklenen: neden: ...)"
    return None


def rapor(d, rapor_yolu, gecerli, madde_log="-", rol="yazici"):
    reviewer = rol == "reviewer"
    metin = Path(rapor_yolu).read_text(encoding="utf-8-sig", errors="replace")
    hatalar, gorulen, bitti_satir = [], {}, None
    for satir in metin.splitlines():
        m = MADDE_SATIR.match(satir)
        if m:
            gorulen.setdefault(int(m.group(1)), []).append((m.group(2), m.group(3)))
            continue
        b = BITTI_SATIR.match(satir)
        if b:
            if bitti_satir is not None:
                hatalar.append("bitti satırı iki kez")
            bitti_satir = (b.group(1), b.group(2))
    beklenen = sozlesme_maddeleri(d)
    for n in beklenen:
        if n not in gorulen:
            hatalar.append(f"madde {n}: raporda yok")
    for n, satirlar in sorted(gorulen.items()):
        if beklenen and n not in beklenen:
            hatalar.append(f"madde {n}: sözleşmede yok")
        tekil = {karsilandi(durum) for durum, _ in satirlar}
        # Reviewer CLI çıktısı son cevabı tekrarlayabilir: aynı hükmün tekrarı reviewer'da serbest.
        if len(satirlar) > 1 and (not reviewer or len(tekil) > 1):
            hatalar.append(f"madde {n}: {len(satirlar)} kez raporlanmış" + (" (çelişkili)" if len(tekil) > 1 else ""))
        for durum, kalan in satirlar:
            h = kanit_hatasi(f"madde {n}", durum, kalan)
            if h:
                hatalar.append(h)
    if bitti_satir is None:
        if not reviewer:
            hatalar.append("bitti satırı yok (beklenen: bitti: KARŞILANDI | kanıt: `...` → ...)")
    else:
        h = kanit_hatasi("bitti", *bitti_satir)
        if h:
            hatalar.append(h)
    if not reviewer:
        iddia = (bitti_satir and karsilandi(bitti_satir[0])) or any(
            karsilandi(durum) for s in gorulen.values() for durum, _ in s
        )
        if iddia and not gecerli:
            hatalar.append("KARŞILANDI iddiası var ama bitti kanıtı yeşil ve güncel değil (bitti kapısını koş)")
        if bitti_satir and not karsilandi(bitti_satir[0]) and gecerli:
            hatalar.append("bitti: KARŞILANMADI yazılmış ama bitti kanıtı yeşil; rapor betikle çelişiyor")
    # Kanıt içeriği: sözleşme komutunu betik koştu; iddia gerçek çıkışla çelişirse ret.
    kosulan = madde_log_oku(madde_log)
    if madde_log and madde_log != "-":
        for n in sorted(set(calisir_maddeler(d)) - set(kosulan)):
            hatalar.append(f"madde {n}: sözleşme komutu koşulmadı (madde.log'da yok)")
    for n, (gercek, bek) in sorted(kosulan.items()):
        print(f"madde_kos: madde {n} çıkış {gercek} (beklenen {bek})")
        for durum, _ in gorulen.get(n, []):
            if karsilandi(durum) and gercek != bek:
                hatalar.append(f"madde {n}: KARŞILANDI ama sözleşme komutu çıkış {gercek} verdi (beklenen {bek})")
            elif not karsilandi(durum) and gercek == bek:
                hatalar.append(f"madde {n}: KARŞILANMADI ama sözleşme komutu beklenen çıkışı ({bek}) verdi; rapor betikle çelişiyor")
                break
    for h in hatalar:
        print("rapor_hata: " + h)
    if not hatalar:
        ek = "reviewer" if reviewer else f"bitti {'yeşil' if gecerli else 'kırmızı'}"
        print(f"rapor: geçerli ({len(gorulen)} madde, {ek})")
    return 1 if hatalar else 0


def main(argv):
    global ESKI
    if "--eski" in argv:
        ESKI = True
        argv = [a for a in argv if a != "--eski"]
    if os.environ.get("NOBET_ESKI"):
        print("kapi: UYARI: NOBET_ESKI artık okunmuyor; eski şerit için --eski bayrağını verin", file=sys.stderr)
    if len(argv) >= 3 and argv[0] == "denetle":
        return denetle(Path(argv[1]), Path(argv[2]))
    if len(argv) >= 4 and argv[0] == "kabul":
        return kabul_yaz(Path(argv[1]), Path(argv[2]), argv[3:])
    kaydet = "--kaydet" in argv
    argv = [a for a in argv if a != "--kaydet"]
    if 4 <= len(argv) <= 6 and argv[0] == "rapor" and argv[3] in ("0", "1"):
        rol = argv[5] if len(argv) == 6 else "yazici"
        if rol not in ("yazici", "reviewer"):
            print("rol yazici|reviewer olmalı", file=sys.stderr)
            return 2
        d, kopya = Path(argv[1]), Path(argv[2])
        try:
            sonuc = rapor(d, kopya, argv[3] == "1", argv[4] if len(argv) >= 5 else "-", rol)
        except Denetlenemedi:
            if kaydet:
                kopya.unlink(missing_ok=True)
            raise
        if kaydet:
            rapor_kaydet(d, kopya) if sonuc == 0 else kopya.unlink(missing_ok=True)
        return sonuc
    if len(argv) == 3 and argv[0] == "madde-kos":
        return madde_kos(Path(argv[1]), Path(argv[2]))
    if len(argv) == 3 and argv[0] == "kapsam-disi":
        return kapsam_disi(Path(argv[1]), Path(argv[2]))
    if len(argv) == 2 and argv[0] == "bicim" and argv[1] in BICIM:
        print(BICIM[argv[1]])
        return 0
    if len(argv) == 3 and argv[0] == "madde-cmd":
        return madde_cmd(Path(argv[1]), Path(argv[2]))
    if len(argv) == 2 and argv[0] == "sozlesme-dogrula":
        hatalar = sozlesme_dogrula(Path(argv[1]).read_text(encoding="utf-8-sig", errors="replace"))
        for h in hatalar:
            print("sozlesme_hata: " + h)
        return 1 if hatalar else 0
    print(__doc__, file=sys.stderr)
    return 2


def cli():
    """Komut satırı girişi (`nobet`). Çıkış 0 temiz, 1 ihlal, 2 denetlenemedi."""
    # newline="\n": Windows'ta print \r\n yazmasın (kabuk TSV ayrıştırması \r'yi değere katar).
    # reconfigure yalnız TextIOWrapper'dadır; StringIO ya da None üzerinde AttributeError olur.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    try:
        sys.exit(main(sys.argv[1:]))
    except (Denetlenemedi, OSError, UnicodeDecodeError) as e:
        print("nobet: denetlenemedi: " + str(e))
        sys.exit(2)


if __name__ == "__main__":
    cli()
