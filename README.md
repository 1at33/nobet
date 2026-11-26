# nobet

Alt ajanlarla iş yaptıranlar için **sert kapı**. Yazıcı ajan işini bitirdiğini söylediğinde nobet şu
sorulara betikle cevap verir: sahiplik dışında bir dosyaya dokundu mu, mevcut bir testi değiştirdi ya da sildi mi,
dondurulmuş kabul testi değişti mi, "bitti" kanıtı güncel ve çıkış kodu 0 mı, rapor sözleşmedeki her maddeyi
gerçek komut çıktısıyla karşılıyor mu. İhlal varsa **reddeder**, uyarmaz. Denetleyemezse de reddeder (fail-closed).

Yalnız standart kütüphane, Python 3.11+. `git` komutlarını çağırır. Kapının kendisi model çağırmaz; isteğe bağlı
orkestrasyon kabuğu (`nobet-akis`) yalnız senin `ayar.toml`'da tanımladığın ajan komutlarını çalıştırır.

**English summary.** `nobet` is a dependency-free hard gate for multi-agent coding workflows. Given a writer
agent's worktree and a lane directory (ownership globs, base sha, frozen acceptance-test hashes, contract), it
rejects out-of-scope edits, modified or deleted existing tests, changed frozen acceptance tests, stale or failing
"done" evidence, and reports whose claims don't match real command output. It also scrubs secrets from the
environment passed to sub-agents, picks a cross-provider reviewer from the user's own provider list, and scans
the working tree and git history for personal data (e-mail, national ID, a private name list, home-directory paths).
A heuristic loop gate, `nobet-dongu`, rejects agent outputs that repeat themselves (zlib compression ratio, Shannon
entropy, word 4-gram Jaccard), near-identical attempts, copy-pasted evidence and claims re-submitted without new
evidence.
An optional orchestration shell, `nobet-akis`, runs the whole loop with your own providers: open a lane (git
worktree + lane directory), run the writer agent command with a scrubbed environment, run the done-evidence, gate,
contract commands and report check, ask a reviewer from another provider, commit and remove the lane via git only.
A messaging layer, `nobet-haber`, lets agents of different providers exchange stdlib-validated JSON envelopes
through a file mailbox (atomic writes, per-recipient inbox, claim/ack states); the recipient is routed only to
profiles in your `ayar.toml` (cross-provider reviewer first, quota failover) and run with your configured
command, a scrubbed environment and masked logs.
Exit codes: 0 clean, 1 violation, 2 could not check. Docs and identifiers are Turkish.

## Kurulum

```
pip install -e .            # nobet, nobet-akis, nobet-dongu, nobet-haber, nobet-tara ve nobet-gecmis komutları
pip install -e ".[dev]"     # + pytest, ruff
```

## Parçalar

| Modül | Ne yapar |
|---|---|
| `nobet.kapi` | **Sert kapı.** `denetle`: tabana göre değişen dosyalar sahiplik glob'u dışındaysa, mevcut bir test dosyası değişmiş ya da silinmişse, dondurulmuş kabul testi değişmişse ihlal. `kabul`: kabul testlerini içerik hash'iyle dondurur. `rapor`: yazıcı/reviewer raporunu şemaya göre denetler ve sözleşme maddelerini gerçek komut çıkışıyla karşılaştırır. `assume-unchanged` / `skip-worktree` ile gizlenmiş dosyaları da yakalar. |
| `nobet.bitti` | **"Bitti" kanıtı.** Sözleşmedeki ```` ```bitti ```` bloğunu ya da `bitti.cmd`'yi okur; kanıt logunun komut hash'i, worktree içerik özeti ve çıkış kodu güncel mi bakar. Komut çalıştırmaz: yazıcının "testler geçti" demesi değil, kabuğun koştuğu komutun kaydı sayılır. |
| `nobet.gizli` | **Sır temizleme.** Alt sürece verilecek ortamdan, değeri sır gibi görünen (bilinen anahtar kalıbı ya da yüksek entropili uzun dize) ya da adı `key/token/secret/passw/credential/auth` içeren değişkenleri çıkarır; açıkça izin verilenler korunur. git'in ortam ayarı ailesi (`GIT_CONFIG_COUNT`, `GIT_CONFIG_KEY_n`, `GIT_CONFIG_VALUE_n`) bir üyesi silinirse bütünüyle çıkarılır; yarım kalırsa alt süreçteki git düşer. Girdiyi değiştirmez, temiz kopya döndürür. |
| `nobet.profil` | **Yazıcı/reviewer profilleri.** `ayar.toml` içindeki `[[saglayici]]` girdilerinden türer; kodda model listesi yoktur. `reviewer_adaylari` önce başka sağlayıcıyı seçer, yoksa aynı sağlayıcının öteki modelini. |
| `nobet.akis` | **Orkestrasyon kabuğu (`nobet-akis`).** Şerit açar, yazıcıyı çalıştırır, bitti + kapı + sözleşme + rapor sırasını koşar, başka sağlayıcıdan reviewer çağırır, şeridi yalnız git ile kapatır. Kapı kararlarını kendisi vermez; yukarıdaki modülleri çağırır. Ayrıntı: [Orkestrasyon](#orkestrasyon-nobet-akis). |
| `nobet.dongu` | **Döngü kapısı (`nobet-dongu`).** Ajan çıktısında ve denemeler arasında tekrar, düşük bilgili dolgu, kopya kanıt ve kanıtsız tekrar iddiayı sıkıştırma oranı, entropi ve k-gram Jaccard ile ölçer; eşik aşılırsa reddeder. Sezgiseldir, sert kapının yerine geçmez. Ayrıntı: [Döngü kapısı](#döngü-kapısı-nobet-dongu). |
| `nobet.haber` | **Haberleşme (`nobet-haber`).** Sağlayıcılar arası ajan mesajları: standart kütüphaneyle doğrulanan zarf, alıcı başına dosya posta kutusu (atomik yazım, alma/onay durumu), `ayar.toml` profillerinden yönlendirme (önce başka sağlayıcıdan reviewer, kotada devir) ve profilin komutunu sırsız ortamla çalıştıran adaptör. Ayrıntı: [Haberleşme](#haberleşme-nobet-haber). |
| `nobet.tara` | **Çalışma ağacında kişisel veri.** İzlenen dosyaların diskteki hali ve `.gitignore` dışındaki izlenmeyen dosyalar: geçerli T.C. kimlik no, izinli olmayan e-posta, ad listesindeki adlar, kullanıcı adı taşıyan ev dizini yolları (`C:\Users\<ad>`, `/home/<ad>`, `/Users/<ad>`). gitleaks kuruluysa sır taraması da yapar. Commit öncesi ve yayın öncesi çalıştırılır. Uyarı katmanı için aşağıya bakın. |
| `nobet.gecmis` | **Git geçmişinde kişisel veri.** Ağaç taramasının göremediğine bakar: yazar/committer e-postaları, commit mesajı ve `Co-authored-by` satırları, tag'ler, sonradan silinen dosyalar; `--github` ile dalsız kalmış commit'ler. Bulgunun değerini asla yazmaz, yalnız yerini. |
| Uyarı katmanı | `nobet-tara` ve `nobet-gecmis` ortak. **Uyarı** bulgu gibi raporlanır (`uyarı: <tür>: <yer>`, JSON'da `uyarilar` anahtarı) ama çıkış kodunu değiştirmez; `N bulgu` sayacı yalnız kesin bulguları sayar. İki uyarı türü vardır. (1) `e-posta (ikili, doğrulanmalı)`: ikili dosyada adres yalnız ASCII karakterlerle aranır, ASCII olmayan bayt adresin sınırıdır; son etiketi 2 ile 24 harf olmayan kalıplar (rastgele bayt) hiç sayılmaz; yerel kısmı 1-2 karakter olan ya da alan adı (son noktadan önceki kısım) tek karakter olan adres kesin bulgu yerine uyarıya düşer; yerel kısmı en az 3, alan adı en az 2 karakter olan adres metin dosyasındaki gibi `e-posta` olarak kesin kalır. Metin dosyalarında e-posta kuralı değişmedi. (2) `açık paylaşım bağlantısı`: metin dosyada bağlantıya sahip herkesin erişebildiği Google Drive/Docs dosya ve klasör bağlantıları, Dropbox paylaşım yolları ve imzalı nesne deposu bağlantıları. Yalın alan adı uyarı üretmez, ikili dosyada aranmaz. |
| Sır katmanları | `nobet-tara` gitleaks raporunu iki katmana ayırır (`nobet.sir`; JSON'da `sir_katmanlari`: `anahtar_turu`, `entropi`, `suzulen`). **Anahtar türü:** belirli gitleaks kuralları (AWS, GitHub vb.); her zaman bulgudur, hiçbir koşulda süzülmez. **Entropi:** genel `generic-api-key` kuralı. Bir kayıt yalnız üç koşulun hepsi sağlanırsa süzülür: değer özet biçimindedir (32+ onaltılık ya da `sha1-`/`sha256-`/`sha384-`/`sha512-` bütünlük değeri), eşleşen satırda `hash`, `digest`, `sha256`, `integrity`, `checksum` gibi bir özet sözcüğü geçer ve satırda `secret`, `token`, `passw`, `credential`, `auth` geçmez. Biri eksikse bulgu sayılır: gizli anahtar ya da token adlı bir değişkene atanmış onaltılık değer süzülmez, adı `sha256` ile biten bir önbellek anahtarı süzülür. Dosya adına bakılmaz. Çıktıda yalnız üç sayı yazılır, sır değeri hiçbir yere yazılmaz; hepsi süzüldüyse sonuç temizdir. gitleaks 3 ile çıkıp rapor okunamazsa sonuç bulgudur. |

## Kullanım

```
nobet denetle <iş dizini> <worktree>
nobet kabul   <iş dizini> <worktree> <test yolu>...
nobet rapor   <iş dizini> <rapor.md> <bitti_gecerli 0|1> [madde.log|-] [yazici|reviewer]
nobet-tara    [--repo .] [--adlar dosya] [--adlar-zorunlu] [--gitleaks-zorunlu] [--json]
nobet-gecmis  [--repo .] [--aralik A..B] [--adlar dosya] [--adlar-zorunlu] [--json]
nobet-dongu   GİRDİ... | --serit <iş dizini> | --aralik A..B [--repo .] | --oz-sinama   [--esik AD=DEĞER]... [--json]
```

Kabuğun kullandığı yardımcı alt komutlar: `madde-kos`, `madde-cmd`, `kapsam-disi`, `bicim`, `sozlesme-dogrula`;
`rapor` için `--kaydet`. Argümansız ya da hatalı çağrı kullanım metnini basıp 2 ile çıkar.

`<iş dizini>` şeridin kayıt klasörüdür:

| Dosya | İçerik |
|---|---|
| `sahiplik` | satır başı glob; yazıcının dokunabileceği yollar |
| `test-izni` | satır başı glob; değişmesine izin verilen mevcut test dosyaları |
| `kabul` | `<blob hash>\t<yol>`; içeriği dondurulmuş kabul testleri (`nobet kabul` yazar) |
| taban sha'sı, sözleşme | şeridin açıldığı commit ve numaralı maddeler (`` `komut` → çıkış N ``) |

`nobet-akis ac` bu düzeni kendisi üretir (ayrıca `repo`, `worktree`, `dal`, `bitti.cmd`); kendi kabuğunu
yazıyorsan aynı dosyaları sen yazarsın.

Test takımı yazıcının kapıyı atlatma yollarını (test silme, yeniden adlandırma, gizli index bayrağı, boş bitti
bloğu, çift numaralı sözleşme maddesi) birer vaka olarak tutar.

## Ayar

Sağlayıcılar yalnız kullanıcının dosyasından gelir: `NOBET_AYAR` (yol) > `$XDG_CONFIG_HOME/nobet/ayar.toml`
(Windows: `%APPDATA%\nobet\ayar.toml`). Örnek: [ornek/ayar.ornek.toml](ornek/ayar.ornek.toml). Dosyada
yalnız `[[saglayici]]` tabloları, isteğe bağlı `[dongu]` tablosu ([döngü kapısı](#döngü-kapısı-nobet-dongu)
eşikleri) ve isteğe bağlı `[haber]` tablosu ([haberleşme](#haberleşme-nobet-haber)) olur; bilinmeyen anahtar hatadır. Anahtar değeri yazılırsa reddedilir,
yalnız değişkenin adı (`anahtar_env`) yazılır.

| Değişken | Etki |
|---|---|
| `NOBET_AYAR` | ayar dosyasının yolu |
| `NOBET_BITTI_SURE` | sözleşme maddesi komutlarının zaman aşımı (varsayılan `15m`; `s/m/h/d`) |
| `NOBET_ORTAM_IZIN` | sözleşme komutlarına, bitti komutuna ve ajanlara geçmesine izin verilen sır adlı değişkenler (virgülle); varsayılan: hiçbiri |
| `NOBET_AKIS_SURE` | `nobet-akis` ajan çağrısının zaman aşımı (varsayılan `45m`) |
| `NOBET_AKIS_DIZIN` | `nobet-akis` iş dizinlerinin kökü |
| `NOBET_HABER_DIZIN` | `nobet-haber` posta kökü |
| `NOBET_HABER_SURE` | `nobet-haber isle` ajan çağrısının zaman aşımı (varsayılan `45m`) |
| `NOBET_ADLAR` | `nobet-tara` ve `nobet-gecmis` ad listesi; verilmezse `$XDG_CONFIG_HOME/nobet/kisisel-adlar.txt`. Repo dışında tutun. |
| `GITLEAKS` | gitleaks çalıştırılabilir adı ya da yolu (varsayılan `gitleaks`, PATH'ten) |

## Orkestrasyon (nobet-akis)

Tam döngü, kendi sağlayıcılarınla:

```
nobet-akis ac <repo> <ad> --sahiplik 'src/**' [--test-izni GLOB]... [--sozlesme madde.md] [--bitti KOMUT]
              [--kabul KAYNAK=HEDEF]... [--worktree YOL]
nobet-akis yaz     <ad> <profil> <brief.md>      # yazıcı ajan worktree'de çalışır
nobet-akis denetle <ad> [--rapor rapor.md] [--dongu]  # bitti -> kapı -> [döngü] -> bitti.log -> madde-kos -> rapor
nobet-akis incele  <ad> [--profil P] [--ek ek.md]  # reviewer; verilmezse başka sağlayıcıdan ilk aday
nobet-akis kaydet  <ad> -m "mesaj"               # yeşil + güncel bitti ve temiz kapı ise şerit dalına commit
nobet-akis kapat   <ad>                          # temiz worktree'yi git ile kaldırır; dal kalır
nobet-akis durum   <ad>  |  nobet-akis kabul <ad> <yol>...  |  nobet-akis profiller
```

- **ac** önce yan etkisiz doğrular (şerit adı, glob'lar, sözleşme biçimi, bitti komutu var mı, kabul hedefi test
  dosyası mı), sonra `nobet-taban/<ad>` ve `nobet/<ad>` dallarını, worktree'yi (varsayılan: repo'nun yanında
  `<repo>-nobet-<ad>`) ve iş dizinini açar. `--kabul` kaynağı worktree'ye kopyalanır ve hash'iyle dondurulur.
  Herhangi bir adım düşerse açılan her şey geri alınır.
- **yaz** istemi brief + sahiplik + sözleşme + rapor biçiminden kurar. Ajan worktree'de, stdin'siz (ya da istem
  stdin'den), `NOBET_AKIS_SURE` zaman aşımıyla ve **sırsız ortamla** (`gizli.temiz_ortam`; gerekenler yalnız
  `NOBET_ORTAM_IZIN` ile açılır; sağlayıcının kendi anahtarı da buna dahil) çalışır. Zaman aşımında yalnız bu
  çağrının süreç grubu kapatılır. Çıktı kayda düşmeden maskelenir.
- **Koruma mührü:** ajan (yazıcı ya da reviewer) çalışmadan önce iş dizini, repo'nun `.git/config`'i, worktree'nin
  `config.worktree`'si ve hook dosyaları mühürlenir. Ajan bunları değiştirirse mühürlü içerik geri yazılır, iş
  dizinine eklenen dosya silinir, git meta verisine eklenen dosya yalnız bildirilir; ihlal `koruma.ihlal`'e yazılır
  ve `denetle`/`kaydet` reddeder. Dosyayı inceleyip elle silmeden şerit geçmez.
- **denetle** sırası: bitti komutu (sırsız ortam, `NOBET_BITTI_SURE`) -> worktree özeti -> `nobet denetle` ->
  `bitti.log` -> `madde-kos` -> son yazıcı raporuna `rapor` (geçerse `rapor-N.md`). Kapı ihlali bitti'yi kırmızı
  yapar; "KARŞILANDI" diyen rapor da böylece reddedilir. Denetlenemeyen adım çıkış 2'dir. `--dongu` ya da
  `ayar.toml`'da `[dongu] akis_denetle = true` ile yazıcı denemeleri [döngü kapısından](#döngü-kapısı-nobet-dongu)
  da geçer; döngü bitti'yi kırmızı yapar, `kaydet` commit atmaz. Varsayılan kapalıdır.
- **incele** farkı (commit'li, commit'lenmemiş, yeni dosyalar; gerçek index'e dokunmadan) isteme koyar. Reviewer
  `profil.reviewer_adaylari` ile önce başka sağlayıcıdan seçilir; aynı sağlayıcı yalnız bilgi olarak
  `review-N.meta`'ya yazılır. Reviewer worktree'yi değiştirirse review sayılmaz (değişiklik geri alınmaz,
  bildirilir). Cevap reviewer şemasıyla denetlenir (`review-N.sema`).
- **kapat** yalnız kayıttaki worktree bu repoya kayıtlı, ana çalışma ağacı değil ve dalı `nobet/<ad>` ise çalışır;
  commit'lenmemiş değişiklikte durur. İçerideki sembolik bağ/junction'lar önce yalnız bağ olarak kaldırılır
  (hedefe inilmez), worktree yalnız `git worktree remove` ile kalkar; kalkmazsa elle silme yapılmaz, bildirilir.
  Yeşil ve güncel bitti kanıtı varsa `durum-isaret` = `teslim`.

**Ajan komutu.** Model ya da firma adı kodda yoktur. Profil adı `ayar.toml`'daki model metnidir; komut o modelin
`[[saglayici]]` girdisinden gelir:

| `tur` | Yazıcı | Reviewer |
|---|---|---|
| `cli` | `komut` şablonu, kabuksuz (`shlex` ile bölünür) | aynı |
| `api`, `yerel` | yok (dosya düzenleyemez) | OpenAI uyumlu `POST <taban_url>/chat/completions`; anahtar `anahtar_env`'den, şifresiz http yalnız yerel adrese |

Şablondaki yer tutucular tek argüman olarak yerine konur:

| Yer tutucu | Değer |
|---|---|
| `{istem}` | istem dosyası; şablonda yoksa istem stdin'den verilir |
| `{worktree}` | şeridin worktree'si (aynı zamanda çalışma dizini) |
| `{model}` | profil adı (ayar.toml'daki model metni) |
| `{cikti}` | ajanın son cevabını yazacağı dosya; yoksa stdout rapor sayılır |
| `{rol}` | `yazici` ya da `reviewer` (iki rol için farklı bayrak gerekiyorsa sarmalayıcı betiğe ver) |

Örnek: `komut = "ornek-cli calistir --model {model} --dizin {worktree} --istem-dosyasi {istem} --son-cevap {cikti}"`.
Windows yollarında ters bölü yerine `/` kullan ya da yolu tek tırnağa al.

**Windows'ta iki tuzak** (gerçek şeritle görüldü):

- **`.cmd` sarmalayıcısı başlamaz.** Komut kabuksuz çalıştığı için npm'in kurduğu `ornek-cli.cmd` gibi
  sarmalayıcılar bulunamaz; yazıcı `çıkış 127` ile döner. Şablonda aracın gerçek `.exe` dosyasını mutlak
  yolla yaz (npm paketlerinde genellikle `node_modules/<paket>/.../bin/<ad>.exe`). Araç güncellenince yol
  değişebilir, yeniden bak.
- **Başsız (headless) ajan komut çalıştıramayabilir.** Bazı CLI'ların başsız kipi "düzenlemeleri kabul et"
  izin kipinde kabuk komutlarına izin vermez. O zaman reviewer testleri koşamaz, yalnız kodu okur ve
  bunu raporuna yazar. CLI'ın izinli araç listesine test ve salt okunur git komutlarını ekle. Reviewer
  ağacı değiştirirse `incele` yine reddeder.

İş dizinleri `NOBET_AKIS_DIZIN` > `$XDG_STATE_HOME/nobet/akis` > `~/.local/state/nobet/akis`
(Windows: `%LOCALAPPDATA%\nobet\akis`) altında `isler/<ad>`'dır; worktree dışında durur. Kayıtlar: `istem-yaz-N.md`,
`yaz-N.log/.md` (log başlığında denemenin `durum_hash`'i), `bitti.log`, `madde.log`, `rapor-N.md`, `istem-review-N.md`, `review-N.log/.md/.meta/.sema`,
`bitti-bag`, `kaydet.log`, `koruma.ihlal`, `durum-isaret`.

## Döngü kapısı (nobet-dongu)

Alt ajan döngüye girince çıktısı tanınır: aynı raporu küçük değişikliklerle yeniden yazar, metni düşük bilgili
dolguyla şişirir, eski kanıt dosyasını yeni koşu diye sunar ya da ağaçta hiçbir şey değişmeden aynı "bitti"
iddiasını tekrarlar. `nobet-dongu` bunları model çağırmadan, metnin kendisinden ölçer ve eşik aşılırsa reddeder.

```
nobet-dongu deneme-1/ deneme-2/ deneme-3/        # her girdi bir deneme; dizin = içindeki metin dosyaları
nobet-dongu rapor-1.md rapor-2.md                # tek dosyalı denemeler, verilen sırayla
nobet-dongu --serit <iş dizini>                  # nobet-akis şeridi: yaz-N.md denemeler, yaz-N.log'daki durum_hash kanıt
nobet-dongu --aralik A..B [--repo .]             # her commit bir deneme; metin = eklenen satırlar
nobet-dongu --oz-sinama [--tur 8]                # eşikler hâlâ döngü yakalıyor mu (rastgele tohumlu örnekler)
  [--esik AD=DEĞER]... [--kapat KAPI]... [--ayar ayar.toml] [--muhur defter.txt [--muhur-salt-oku]] [--json]
```

Dizinde gizli adlar, `__pycache__`, sembolik bağlar, ikili dosyalar (ilk 8000 baytta NUL) ve 5 MB'tan büyük
dosyalar atlanır; atlananlar çıktıda yeriyle listelenir. Çıkış 0 temiz, 1 döngü, 2 denetlenemedi (girdi yok, hiç
metin yok, okunamayan dosya, bozuk ayar ya da mühür defteri) ya da kullanım hatası. Çıktı girdi metnini yazmaz;
yalnız yeri (verilen yol, dosya adı, `sha8:yol`) ve sayıları. `--json` aynı sonucu makine için verir.

**Kapılar** (k = `shingle`, kelimeler Unicode `\w+` ve büyük/küçük harf farksız):

| Kapı | Ölçü (tek satırda matematik) | Varsayılan eşik |
|---|---|---|
| `ic_tekrar` | sıkıştırma: `len(zlib(m, 9)) / len(m)`, Kolmogorov karmaşıklığına kaba vekil | `< 0.16` ret (`.json/.jsonl/.csv/.tsv`: `< 0.10`); yalnız ≥ 260 bayt |
| | karakter Shannon entropisi `H = -Σ p(c)·log2 p(c)` | `< 2.60` bit/karakter ret; yalnız ≥ 120 bayt |
| | k-gram tekilliği: `\|tekil k-gram\| / \|tüm k-gram\|` | `< 0.38` ret; yalnız ≥ 32 kelime |
| | ardışık satır blokları (≥ 35 karakter) arasında k-gram Jaccard `\|A∩B\| / \|A∪B\|` | ≥ 3 blokta, `≥ 0.82` benzer en az 2 çift ve çiftlerin `≥ %25`'i |
| | birebir tekrar eden blok sayısı (boşluk ve harf büyüklüğü normalize) | en az 2 ve blokların `≥ %35`'i |
| `deneme_tekrari` | her deneme önceki **tüm** denemelerle k-gram Jaccard (A-B-A salınımı da yakalanır) | `≥ 0.85` ret; < 20 kelimelik deneme karşılaştırılmaz |
| | kanıt özeti (şeritte `durum_hash`) iki denemede biliniyor ve farklıysa tekrar sayılmaz; aynıysa kısa rapor da birebir aynıysa ret | |
| `kopya_kanit` | çok dosyalı denemede iki dosyanın k-gram Jaccard'ı ya da önceki bir denemedeki dosyanın birebir aynısı | `≥ 0.90` ret |
| `muhur` | yalnız `--muhur DEFTER`: girdi içeriklerinin sırasız SHA-256 mührü daha önce deftere yazıldıysa ret; temiz koşu mührü deftere ekler | eşik yok |

`--serit` kipinde `review-N.md` yalnız `ic_tekrar`'a girer. k = 4.

**Eşikler** yukarıdaki varsayılanlardır; öncelik: varsayılan < `ayar.toml` `[dongu]` < `--esik AD=DEĞER`. Bilinmeyen
ad, yanlış tür (sayı alanına `true`, tam sayı alanına `2.5`) ve aralık dışı değer hatadır (çıkış 2):

```toml
[dongu]
sikistirma_min = 0.16        # sikistirma_veri_min = 0.10, sikistirma_bayt = 260
entropi_min = 2.60           # entropi_bayt = 120
tekillik_min = 0.38          # tekillik_kelime = 32, shingle = 4
blok_benzerlik = 0.82        # blok_karakter = 35, blok_sayi = 3, blok_cift = 2, blok_cift_oran = 0.25
kopya_blok = 2               # kopya_blok_oran = 0.35
deneme_benzerlik = 0.85      # deneme_kelime = 20
kopya_benzerlik = 0.90
kapali = []                  # ic_tekrar | deneme_tekrari | kopya_kanit | muhur
akis_denetle = false         # true: nobet-akis denetle döngü kapısını her zaman koşar
```

Eşikleri gevşettiysen `nobet-dongu --oz-sinama` her turda rastgele tohumdan (os.urandom + SHA-256) yeni bir döngü
metni, neredeyse aynı iki deneme, kopya kanıt ve iki temiz örnek üretir; kapı bunları seçili eşiklerle doğru
sınıflandırmazsa 1 ile çıkar. Örnekler önceden bilinmez; eşiğin yalnız sabit test metnine göre ayarlanmasını önler.

**Sınırlar.** Kapı sezgiseldir. Metne rastgele gürültü ekleyen ya da her denemede cümleleri yeniden yazan bir
ajan (ya da saldırgan) ölçüleri kolayca geçer; tersine kalıp raporlar, tablo ve günlük dosyaları yanlış alarm
verebilir (eşiği yükselt ya da kapıyı `--kapat` ile kapat). Anlamı, doğruluğu ve testlerin gerçekten geçtiğini
denetlemez: [sert kapının](#parçalar) (sahiplik, test dokunulmazlığı, bitti kanıtı, rapor-kanıt karşılaştırması)
yerine geçmez, ona eklenir. Çift karşılaştırma deneme sayısında karesel büyür; çok uzun aralıkları parçala.

## Haberleşme (nobet-haber)

Farklı sağlayıcılardaki ajanlar birbirine süreç açmaz; her mesaj bir **zarftır** ve alıcının posta kutusuna
düşer. `nobet-haber isle` kutudaki görevi alıcı profilin `ayar.toml` komutuyla çalıştırır, cevabı yeni bir zarf
olarak gönderenin kutusuna yollar. Model ya da firma adı kodda yoktur; alıcı yalnız `ayar.toml` profillerinden biridir.

```
nobet-haber [--json] [--ayar A] dogrula ZARF|-          # şema + yönlendirme, yazmaz
nobet-haber [--json] gonder ZARF|-                      # doğrula, maskele, yönlendir, kutuya yaz
nobet-haber [--json] isle PROFIL (--dizin D | --serit AD) [--id ID]
nobet-haber [--json] liste PROFIL [--hepsi]  |  oku PROFIL ID  |  onayla PROFIL ID  |  kutular  |  sema
```

Çıkış 0 tamam, 1 ret (geçersiz zarf, yönlendirilemedi, tekrar gönderim, ajan hatası, kota, koruma ihlali),
2 denetlenemedi (okunamayan dosya, bozuk ayar, çalışma dizini yok) ya da kullanım hatası.

**Zarf** (`nobet-haber sema` JSON Schema'sını basar; normatif olan doğrulayıcıdır, `jsonschema` gerekmez):

```json
{"surum": 1, "id": "<32 hex>", "is_id": "serit-1", "ebeveyn": null, "tur": "gorev",
 "gonderen": {"profil": "yonetici", "rol": "yonetici"}, "alici": {"profil": null, "rol": "reviewer"},
 "yazici": "cli-model", "zaman": "2026-01-01T00:00:00Z",
 "govde": {"metin": "farkı incele"}, "ekler": [{"yol": "docs/fark.txt", "sha256": "<64 hex>"}]}
```

| Alan | Kural |
|---|---|
| `tur` | `gorev`, `soru` (ajan çalıştırır); `sonuc`, `hata`, `kota` (bilgi; okunur ve onaylanır) |
| `gonderen`, `alici` | `profil` + `rol` (`yonetici`, `yazici`, `reviewer`). Yöneticinin profili `yonetici`. Alıcının profili `null` ise yönlendirici seçer |
| `yazici` | incelenen işin yazıcı profili; reviewer'a giden zarfta zorunlu |
| `is_id` | `nobet-akis` şerit adıyla aynı biçim; `--serit` ile işlenirken şerit adına eşit olmalı |
| `govde` | `metin` zorunlu; ek anahtarlar `[a-z_][a-z0-9_]*`, en çok 6 düzey |
| `ekler` | göreli, `/` ayraçlı, `..`/sürücü harfi/ters bölü yok; `isle` ajanı çalıştırmadan önce dosyanın çalışma dizini içinde ve hash'inin tuttuğuna bakar |

Zarf alanları güvenilmez girdidir (başka ajanın çıktısı). Fazla ya da eksik alan, yanlış tür, 512 KiB'ı aşan
zarf, 100 000 karakteri aşan metin, tekrar eden JSON anahtarı, `NaN`, aşırı iç içe yapı, kontrol karakteri ve
terminal kaçışı reddedilir. Zarf komut, yol, çalışma dizini ya da sağlayıcı seçemez.

**Posta kutusu.** `<kök>/kutular/<kutu>/{gelen,isleniyor,islenen,reddedilen}/<id>.json`; kök
`NOBET_HABER_DIZIN` > `$XDG_STATE_HOME/nobet/haber` > `~/.local/state/nobet/haber` (Windows:
`%LOCALAPPDATA%\nobet\haber`). Kutu adı profil adından türetilir (küçük harf özet + ad hash'i): profil adı yol
olarak kullanılmaz, Windows'ta da geçerlidir. Yazım atomiktir (geçici dosya fsync, hedefe üzerine yazmadan hard
link); aynı kimlik ikinci kez yazılmaz, eşzamanlı yeniden gönderimde de: karar kutu kökündeki kalıcı `kilit`
dosyası üzerinde işletim sistemi kilidiyle verilir. Bu dosya silinmemelidir; kilit 10 saniyede alınamazsa `gonder`
hata verir, zarf yazılmaz (yeniden denenebilir). Posta kökünün bulunduğu dosya sistemi dosya kilidini
desteklemelidir (desteklemiyorsa `gonder` hata verir). `isle` zarfı tek rename ile `isleniyor/`'a alır, iki işleyici
aynı zarfı alamaz; işlenemezse (denetlenemedi) `gelen/`'e döner (bu geri kuyruk, kilit meşgulse kısa süre
bekleyebilir). Diske yalnız maskeli `govde` yazılır; ajan
günlükleri `gunluk/<id>-N.log` maskelidir. Sembolik bağ olan kutu ya da zarf dosyası okunmaz.

**Yönlendirme** (`ayar.toml` profilleri, `nobet.profil` ile):

- `yazici`: yazıcı rolü olan `tur=cli` profil; profil verilmezse `ayar.toml` sırasıyla ilki.
- `reviewer`: `profil.reviewer_adaylari` listesi, yani önce başka sağlayıcı, yoksa aynı sağlayıcının öteki
  modeli. Listede olmayan profil reddedilir: ajan, zarfa kendi sağlayıcısından bir reviewer yazarak çapraz
  incelemeyi atlatamaz. `[haber] capraz_zorunlu = true` aynı sağlayıcıya düşmeyi de reddeder.
- Gönderen `yazici`/`reviewer` ise profil `ayar.toml`'da o rolle olmalıdır.
- **Kota devri:** sağlayıcı sıfır olmayan çıkışla kota/hız sınırı iletisi verirse (`rate limit`, `quota
  exceeded`, `429`...) o sağlayıcı dışlanır, zarf aynı rol için yeniden yönlendirilir; en çok `[haber] devir`
  kez (varsayılan 1, 0 kapatır). Zincir cevap zarfının `govde.devir` alanına yazılır.

**Adaptör.** Ajan `nobet-akis` ile aynı yoldan çalışır (`akis.ajan_kos`): komut `[[saglayici]]` şablonundan,
kabuksuz; ortam `gizli.temiz_ortam` ile sırsız (`NOBET_ORTAM_IZIN`), çalışma dizini yalnız `--dizin` ya da
`--serit` ile operatörün verdiği yer; `{rol}` `yazici` ya da `reviewer`. API sağlayıcı yalnız reviewer olur.
Cevap maskelenir, terminal kaçışları atılır, sınırda kesilir.

**nobet-akis ile (isteğe bağlı).** `isle --serit AD` ajanı şeridin worktree'sinde çalıştırır ve akış kabuğunun
korumasını uygular: iş dizini, git config ve hook'lar mühürlenir; ajan değiştirirse geri yazılır ve
`koruma.ihlal`'e işlenir (`denetle`/`kaydet` reddeder). Reviewer worktree'yi değiştirirse cevap `hata` olur.
`nobet-akis` komutlarının davranışı değişmez.

```toml
[haber]
capraz_zorunlu = false   # true: reviewer başka sağlayıcıdan değilse ret
devir = 1                # kota sinyalinde en çok kaç kez başka sağlayıcıya devredilir (0-5)
```

**Sınırlar.** Tek makine, dosya sistemi; ağ servisi, oturum sürdürme, çok turlu düzeltme döngüsü ve durum
makinesi yoktur (tek adım: zarf al, çalıştır, cevapla; döngüyü sen ya da `nobet-akis` kurar). Mesaj gövdesi
istem enjeksiyonu taşıyabilir; ajana veri olarak verildiği söylenir ama bu bir koruma değildir, gerçek sınır
ajan CLI'nin kendi sandbox'ı ve `--serit` korumasıdır. Maskeleme en iyi çabadır.

## Kişisel veri koruması (CI ve yayın öncesi)

Yayından önce iki tarama birlikte koşar; ikisi de bulgunun değerini yazmaz, yalnız yerini:

```
nobet-tara   --repo . --adlar ~/.config/nobet/kisisel-adlar.txt --adlar-zorunlu   # bugünkü dosyalar
nobet-gecmis --repo . --adlar ~/.config/nobet/kisisel-adlar.txt --adlar-zorunlu   # tüm geçmiş
```

CI'daki `kisisel-veri` işi ikisini de çalıştırır. Ad listesi repoya girmez: depo ayarlarında `KISISEL_ADLAR`
gizli değişkenine (her satır bir ad) koyarsanız CI onu kullanır; yoksa ad taraması atlanır, öteki denetimler
yine koşar. Kendi repolarınızda da aynı işi kullanabilirsiniz: `pip install -e .` (PyPI'da yayımlanınca `pip install nobet`), ardından iki komut.

## Sınırlar

- **Sözleşme komutları çalışır.** `madde-kos` sözleşmedeki komutları `sh -c` ile worktree'de koşar. Komutlara giden
  ortamdan sır gibi görünen değişkenler (adı key/token/secret/passw/credential/auth içeren ya da değeri anahtara
  benzeyen) çıkarılır; gerekenler `NOBET_ORTAM_IZIN` ile açılır. Komut çıktısının kuyruğu `madde-cikti.log`'a
  yazılmadan önce sır gibi görünen değerler `[gizli]` olarak maskelenir (en iyi çaba). Sözleşmeyi orkestratör
  yazar, yazıcı ajan değil; komutlar yalıtılmış değildir.
- **Kapıyı gevşetmek yalnız bayrakla olur.** Taban sha'sı ya da sahiplik dosyası olmayan eski şeritte hata yerine
  uyarı için `nobet denetle ... --eski` verilir. Eski `NOBET_ESKI` ortam değişkeni okunmaz (yalnız uyarı basılır):
  ajanın ortamından kapı sessizce gevşetilemez.

- **Orkestrasyon kabuğu iskelettir.** `nobet-akis` tek şeridi baştan sona yürütür; paralel şerit planlama, aynı
  oturuma düzeltme gönderme, kota/yedek yazıcıya geçiş, reviewer isabet karnesi ve iş takip sistemi bağlantısı
  yoktur. Bunlar gerekiyorsa kendi kabuğunu yazıp aynı iş dizini düzeniyle `nobet` alt komutlarını çağır.
- **Ajan yalıtılmış değildir.** Yazıcı kendi kullanıcınla çalışır; worktree dışındaki dosyalara erişebilir. Koruma
  mührü yalnız ajan çalışırken iş dizinini, `.git/config`'i ve hook'ları kapsar; gerçek yalıtım için ajan CLI'nin
  kendi sandbox'ını ya da ayrı kullanıcı/konteyner kullan.
- **Platform:** CI'da Windows ve Linux denenir; macOS denenmedi.
- **Kararlılık:** `v0.x`; arayüzler haber verilmeden değişebilir. Belgeler ve tanımlayıcılar Türkçedir.

## Lisans

MIT. Atıflar: [NOTICE](NOTICE).
