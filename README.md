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
An optional orchestration shell, `nobet-akis`, runs the whole loop with your own providers: open a lane (git
worktree + lane directory), run the writer agent command with a scrubbed environment, run the done-evidence, gate,
contract commands and report check, ask a reviewer from another provider, commit and remove the lane via git only.
Exit codes: 0 clean, 1 violation, 2 could not check. Docs and identifiers are Turkish.

## Kurulum

```
pip install -e .            # nobet, nobet-akis, nobet-tara ve nobet-gecmis komutları
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
| `nobet.tara` | **Çalışma ağacında kişisel veri.** İzlenen dosyaların diskteki hali ve `.gitignore` dışındaki izlenmeyen dosyalar: geçerli T.C. kimlik no, izinli olmayan e-posta, ad listesindeki adlar, kullanıcı adı taşıyan ev dizini yolları (`C:\Users\<ad>`, `/home/<ad>`, `/Users/<ad>`). gitleaks kuruluysa sır taraması da yapar. Commit öncesi ve yayın öncesi çalıştırılır. |
| `nobet.gecmis` | **Git geçmişinde kişisel veri.** Ağaç taramasının göremediğine bakar: yazar/committer e-postaları, commit mesajı ve `Co-authored-by` satırları, tag'ler, sonradan silinen dosyalar; `--github` ile dalsız kalmış commit'ler. Bulgunun değerini asla yazmaz, yalnız yerini. |

## Kullanım

```
nobet denetle <iş dizini> <worktree>
nobet kabul   <iş dizini> <worktree> <test yolu>...
nobet rapor   <iş dizini> <rapor.md> <bitti_gecerli 0|1> [madde.log|-] [yazici|reviewer]
nobet-tara    [--repo .] [--adlar dosya] [--adlar-zorunlu] [--gitleaks-zorunlu] [--json]
nobet-gecmis  [--repo .] [--aralik A..B] [--adlar dosya] [--adlar-zorunlu] [--json]
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
yalnız `[[saglayici]]` tabloları olur; bilinmeyen anahtar hatadır. Anahtar değeri yazılırsa reddedilir,
yalnız değişkenin adı (`anahtar_env`) yazılır.

| Değişken | Etki |
|---|---|
| `NOBET_AYAR` | ayar dosyasının yolu |
| `NOBET_BITTI_SURE` | sözleşme maddesi komutlarının zaman aşımı (varsayılan `15m`; `s/m/h/d`) |
| `NOBET_ORTAM_IZIN` | sözleşme komutlarına, bitti komutuna ve ajanlara geçmesine izin verilen sır adlı değişkenler (virgülle); varsayılan: hiçbiri |
| `NOBET_AKIS_SURE` | `nobet-akis` ajan çağrısının zaman aşımı (varsayılan `45m`) |
| `NOBET_AKIS_DIZIN` | `nobet-akis` iş dizinlerinin kökü |
| `NOBET_ADLAR` | `nobet-tara` ve `nobet-gecmis` ad listesi; verilmezse `$XDG_CONFIG_HOME/nobet/kisisel-adlar.txt`. Repo dışında tutun. |
| `GITLEAKS` | gitleaks çalıştırılabilir adı ya da yolu (varsayılan `gitleaks`, PATH'ten) |

## Orkestrasyon (nobet-akis)

Tam döngü, kendi sağlayıcılarınla:

```
nobet-akis ac <repo> <ad> --sahiplik 'src/**' [--test-izni GLOB]... [--sozlesme madde.md] [--bitti KOMUT]
              [--kabul KAYNAK=HEDEF]... [--worktree YOL]
nobet-akis yaz     <ad> <profil> <brief.md>      # yazıcı ajan worktree'de çalışır
nobet-akis denetle <ad> [--rapor rapor.md]       # bitti -> kapı -> bitti.log -> madde-kos -> rapor
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
  yapar; "KARŞILANDI" diyen rapor da böylece reddedilir. Denetlenemeyen adım çıkış 2'dir.
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
`yaz-N.log/.md`, `bitti.log`, `madde.log`, `rapor-N.md`, `istem-review-N.md`, `review-N.log/.md/.meta/.sema`,
`bitti-bag`, `kaydet.log`, `koruma.ihlal`, `durum-isaret`.

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
