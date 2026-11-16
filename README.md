# ✎ Ders Anlatıcı

**Tamamen senin bilgisayarında çalışır:** hocanın beyni bilgisayarına kurulan açık bir yapay zekadır (Ollama + Gemma 4). Hiçbir şirkete, anahtara ya da aboneliğe bağlı değildir; ilk açılışta bir kez indirilir, sonra internetsiz de çalışır.

Ders notlarını öğrenen, soruları sesli (istersen **senin sesinle**, ücretsiz yerel klonla) anlatan ve anlatırken **tahtaya el yazısıyla yazan** kişisel ders hocası. Sınıf ortamında, tahtanın yanında duran bir **hoca karakteri** konuşur, yazarken tahtaya uzanır, sen konuşunca susup dinler.

- **🎧 Konuşmalı ders:** Mikrofon sürekli açık, birebir özel ders gibi konuşursun. Hoca anlatırken konuşmaya başlarsan anında susar (söz kesme), seni dinler, cevaplar; uzun konularda parça parça anlatıp anlayıp anlamadığını sorar.
- **Uzman hoca:** Bilgisi yüklediğin PDF'lerle sınırlı değil. Dersin müfredatındaki her konuyu kaynak kitap düzeyinde anlatır; notların varsa hocanın gösterimini izler. **📚 Müfredat** ile bölüm müfredatındaki dersleri (içerik, haftalık konular, kaynak kitaplar) tek tıkla ekleyebilirsin; not yüklemeden de ders anlatımı ve sınav çalışır. %30 İngilizce program için terimleri İngilizceleriyle birlikte verir.

- Soru sor (yazarak ya da 🎤 sesli) → cevabı tek seferde metin olarak dökmez; konuşurken tahtaya satır satır yazar, formülleri çıkarır, grafiği eksenlerden başlayarak çizer.
- Ekran görüntüsü yapıştır (Ctrl+V), fotoğraf ya da PDF ekle → neyi gördüğünü söyleyip çözer.
- Ders notlarını yükle (PDF ya da defter fotoğrafı) → “12. sayfayı anlat” de, o sayfayı tahtada gösterip anlatır. Taranmış/fotoğraf sayfalar otomatik okunur.
- Anlatırken 🎤'a bas (ya da **Boşluk** tuşunu basılı tut) → durur, sorunu dinler, “anlamadım” dediğin yerden farklı bir yolla tekrar anlatır.

## Özellikler

| Sekme | Ne yapar |
|---|---|
| **Sohbet** | Soru çözme, ekran görüntüsü/fotoğraf/PDF ekleme, sesli soru, söz kesme |
| **Notlar** | Derse PDF/fotoğraf yükleme, sayfa görüntüleyici, “Bu sayfayı anlat”, “Soruya ekle”, **🎙 Ders kaydı yükle** (hocanın ses/video kaydını yazıya döküp başlıklı ders notuna çevirir), **📄 Formül kâğıdı** (notlardan + müfredattan, yazdırılabilir) |
| **Ders anlat** | Kaçırdığın dersi notlardan baştan sona bölüm bölüm anlatır (ders planı + otomatik geçiş) |
| **Sınav** | Notlardan vize/final tarzı soru üretir, cevabını (yazılı ya da çözüm fotoğrafı) puanlar, geri bildirimi sesli okur, “Tahtada çöz ve anlat” |
| **Takvim** | Sınav tarihini gir → sınava kadar günlük çalışma planı (öğren, 1-3-7 gün aralıklı tekrar, konu sınavları, son günler deneme + formül). “Bugün” kutusu tüm derslerin günlük görevlerini gösterir; her görevde **Başla** ile hoca o konuyu anlatır ya da sınav açılır |
| **Kayıtlar** | Her anlatım sesiyle kaydedilir: baştan izle, ⚡ ile tahtayı anında göster, kaldığın yerden devam et |

Ayrıca: hoca karakteri (sese göre ağız hareketi, yazma/dinleme/düşünme pozları), isteğe bağlı internette araştırma, hız ayarı (0.8×–1.5×), duraklat/devam (**P**), tahta sayfaları arasında gezinme, **tahtayı PDF indirme**, anlatım seviyesi (basit/normal/ileri), **hafıza**: zorlandığın konuları kaydeder, sonraki anlatımlarda ve sınavlarda bunlara ağırlık verir.

### 🧠 Bilgisayarında çalışan yapay zeka

- İlk açılışta uygulama bilgisayarına bakar ve uygun modeli seçer: ekran kartı ya da bellek çoksa `gemma4:26b` / `gemma4:12b`, normal bir dizüstünde `gemma4:e4b` (6,6 GB), zayıf bilgisayarda `gemma4:e2b`. Program (Ollama, ~1,6 GB) ve model `veri/yerel-yz/` klasörüne bir kez iner; üst çubukta ilerleme görünür. Kurulu bir Ollama varsa onu kullanır.
- Ayarlar → **🧠 Yapay zeka**: durum, bilgisayar bilgisi, model seçimi, “Kur / yeniden dene”. Hoca yavaş kalıyorsa daha küçük modeli seç.
- Model görüntü de okur: taranmış sayfalar, defter fotoğrafları ve ekran görüntüleri bilgisayarda okunur.
- Sen hocaya soru sorarken arka plan işleri (paket üretimi, sayfa okuma) bekler; canlı anlatım hep önceliklidir.
- **İsteğe bağlı:** Ayarlar'a Gemini anahtarı girersen yerel model kurulurken ya da çalışmazsa yardımcı olarak kullanılır. Zorunlu değildir.

### 📚 Kütüphane: kendi yapay zekan

- **Kitap ve makale ekle:** Kütüphane sekmesine kitap ya da makale PDF'lerini sürükleyip bırak. Ayrıca Not Kutusu içindeki **Kitaplar** alt klasörüne koyduğun dosyalar da kendiliğinden kütüphaneye eklenir (Masaüstü ve Not Kutusu'nun kökündeki dosyalar ders notu sayılır). Yalnızca metin katmanı olan PDF'ler okunur; taranmış sayfalar için OCR ayarı arayüzde yoktur.
- **Kaynak göstererek cevap:** Hoca bir soruyu cevaplarken kütüphanedeki ilgili bölümleri bulur ve hangi kitaptan, hangi sayfadan aldığını gösterir.
- **Anlamsal arama:** İlk kurulumda yaklaşık 640 MB'lık bir gömme modeli iner ve arama anlamla yapılır. Bu model olmadan da kelime aramasıyla çalışır.
- **Literatür taraması:** Haftada bir, derslerinin konularına göre Crossref, arXiv ve OpenAlex'ten yeni makaleleri bulur. Hemen taramak için Kütüphane sekmesinden **Şimdi güncelle**'ye bas.
- **Gizlilik:** Kitapların bilgisayarından çıkmaz; Gemini yedeği açıkken bile kitap bölümleri buluta gönderilmez (o sırada cevaplar kaynaksız verilir). Literatür taramasında yalnızca makalenin başlığı, özeti ve açık erişim PDF'i iner; kişisel bilgin gönderilmez.
- **Sınırlama:** Taranmış kitap sayfaları varsayılan olarak okunmaz. Ayarlar'dan açabilirsin, ama işlemesi yavaştır.

- **Yer kaplamaz:** bir kitap öğrenildikten sonra (metni ve sayfa numaraları veritabanına yazılınca) PDF kopyası silinir; Not Kutusu/Kitaplar'a bıraktığın dosya da silinir. Hoca kitabı yine bilir ve sayfa numarasıyla kaynak gösterir. Kopyaları saklamak istersen ayar: `kutuphane_dosya_sakla`.
- **Kitapları da kendisi bulur:** literatür taramasında derslerine uyan **serbest lisanslı (Creative Commons) ders kitaplarını** (OpenStax: istatistik, kalkülüs, fizik, ekonomi, maliyet muhasebesi, finans, yönetim, örgütsel davranış, girişimcilik, veri bilimi, Python…) indirip kütüphaneye ekler. Her taramada en fazla 2 kitap, diskte yer varsa. Telifli kitapları indirmez; onları sen eklersin. Kapatmak için ayar: `kitap_otomatik`.

### 📥 Notu tanıyıp doğru derse ekler

- **📥 Not ekle** düğmesi (ya da dosyayı pencereye sürükle-bırak): ders seçmene gerek yok. Uygulama notun hangi derse ait olduğunu bulur: dosya adındaki/notun içindeki ders kodu (ör. ENM 463), konu benzerliği (müfredattaki ders içerikleri ve dersin önceki notları), kararsız kalırsa yerel yapay zeka. Ders henüz yoksa müfredattan (içerik ve haftalık konularıyla) oluşturur. Birlikte yüklenen notlar aynı derse gider. Yanlış derse giderse notun yanındaki **↪** ile taşı.
- **Masaüstündeki “Not Kutusu” klasörü:** uygulama açıkken bu klasöre bıraktığın PDF/fotoğraflar birkaç saniyede doğru derse eklenir ve “Eklendi/<ders>” klasörüne taşınır. Ders paketi (.json) bırakırsan kurulur.
- **İndirilenler'deki ders paketleri** (…ders_paketi….json) bir kez kendiliğinden kurulur; paketin dersi yoksa oluşturulur. PDF'leri yüklemeden de plan, özet, konu anlatımı ve deneme sınavları kullanılabilir.

### 📦 Uygulama kendi ders paketini üretir

Notlarını yükledikten sonra **Sınav** sekmesinde **📦 Konu anlatımı, özet ve deneme sınavları üret** düğmesine bas (ya da hiçbir şey yapma: yeni not eklendiğinde ~90 sn sonra kendiliğinden güncellenir; Ayarlar'dan kapatılabilir). Uygulama bu bilgisayardaki yapay zekayla (Gemini'ye ya da başka bir şirkete gerek yok; anahtar girdiysen Gemini yalnızca yedektir) şunları üretir:

- taranmış sayfaların metni, **her belgenin özeti** (bölümler, kavramlar, olası sorular; hoca bunları her soruda bilir),
- **ders planı**, **sınav rehberi**, **sınav odaklı konu anlatımı** (tanımlar, sayılı listeler eksiksiz, “Sınavda nasıl sorulabilir”), **kısa sınav özeti** (en çok ~1500 kelime; klasik soru varsa cevap şablonuyla),
- **hocanın sınav formatına uygun deneme sınavları** (varsayılan 2, en çok 5): “Sınav formatı” kutusuna hocanın söylediğini yaz (ör. “10 D/Y, 10 test 5 şıklı, 1 metin sorusu, 2 klasik”). Her deneme ayrıca notlara karşı denetlenir; cevap anahtarı, açıklama ve kaynak sayfası vardır, doğru şıkların harfleri dengelenir.

Yerel model küçük ve yavaş olduğu için iş küçük adımlara bölünür ve her adım diske yazılır: uygulama kapanırsa ya da yapay zeka hata verirse düğmeye yeniden basınca **kaldığı yerden devam eder**. Sonraki çalıştırmalarda yalnızca değişen/yeni belgeler yeniden özetlenir. Hazır ders paketinden gelen içerik (plan, rehber, paket denemeleri) korunur; hepsini yenilemek için **Baştan üret** kutusunu işaretle. Gemini anahtarı girilmiş olsa bile her istek yerel modelin bağlamına sığacak boyutta hazırlanır, böylece iş yarıda yerel yapay zekaya geçse de düzgün sürer; uzun belgeler parça parça anlatılır, tek seferde sığmayan büyük deneme sınavları bölüm bölüm üretilip denetlenir. "Baştan üret" yarıda kalırsa sonraki başlatmada da baştan üretim kurallarıyla kaldığı yerden sürer.

## En kolay kurulum (Windows)

1. Python yoksa https://www.python.org/downloads/ adresinden kur. Kurulumun ilk ekranında **"Add python.exe to PATH"** kutusunu işaretlemeyi unutma.
2. Zip'i bir klasöre çıkar, **Kurulum.bat** dosyasına çift tıkla (ilk seferde birkaç dakika sürer).
3. **Ders Anlatici.bat** dosyasına (ya da masaüstündeki kısayola) çift tıkla. İlk açılışta yapay zeka kendiliğinden kurulur (bir kerelik ~8 GB indirme; üst çubukta ilerleme görünür). Anahtar gerekmez.

Mac'te aynı adımlar **Kurulum.command** ve **Ders Anlatici.command** ile.

## Kurulum (elle)

Python 3.10+ gerekir.

```bash
git clone <bu repo>
cd ders-anlatici
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
```

**Anahtar gerekmez.** Hocanın beyni bilgisayarındaki yerel yapay zekadır ve ilk açılışta kendiliğinden kurulur. İstersen Ayarlar'a isteğe bağlı bir Gemini anahtarı (https://aistudio.google.com/apikey) girebilirsin; yalnızca yardımcı olarak kullanılır. Anahtarlar bilgisayarındaki `.env` dosyasına kaydedilir.

Ses ve konuşma tanıma **varsayılan olarak ücretsizdir**, anahtar istemez: hoca Microsoft Edge'in Türkçe sesiyle konuşur, sesli sorularını bilgisayarındaki Whisper yazıya çevirir (ilk sesli soruda ~1.6 GB model bir kez iner). Kendi sesini istiyorsan aşağıdaki **Ücretsiz ses** bölümüne bak.

## Çalıştırma

**Masaüstü uygulaması gibi (önerilen):** Windows'ta `Ders Anlatici.bat`, Mac'te `Ders Anlatici.command` dosyasına çift tıkla (ya da `python baslat.py`). Uygulama adres çubuğu olmayan kendi penceresinde açılır; pencereyi kapatınca kapanır. Mikrofon izni bir kez verilir.

**Tarayıcıda:**

```bash
uvicorn app.main:app --port 8000
```

ve **http://localhost:8000** (Chrome/Edge önerilir). Adres çubuğundaki “Uygulamayı yükle” simgesiyle de masaüstüne/başlat menüsüne kurabilirsin.

**Konuşmalı ders için kulaklık kullan:** hoparlörden çıkan hoca sesi mikrofona geri girerse hoca kendi sesini “söz kesme” sanabilir. Hoparlörle kullanacaksan Ayarlar'dan mikrofon hassasiyetini düşür.

İlk kullanım:
1. **📚 Müfredat** ile bölümünün derslerini ekle (ya da **+ Ders** ile elle oluştur).
2. **Notlar** sekmesinden hocanın PDF'lerini / defter fotoğraflarını yükle (isteğe bağlı ama önerilir).
3. **🎧 Konuşmalı ders**'i aç ve konuşmaya başla; ya da **Ders anlat** ile baştan dinle, **Sınav** ile kendini test et.

### 📱 Telefondan kullanım

Telefon tarayıcıları mikrofonu yalnızca güvenli (https) adreste açar, bu yüzden ücretsiz bir Cloudflare tüneli kullanılır:

1. Bilgisayara bir kez **cloudflared** kur: `winget install Cloudflare.cloudflared` (Windows) ya da `brew install cloudflared` (Mac).
2. **Telefondan Kullan.bat** dosyasına çift tıkla (ya da `python baslat.py --telefon`).
3. Ekranda çıkan adresi/QR kodu telefonda aç, şifreyi gir (uygulamadaki **📱** düğmesi de QR'ı gösterir). Tarayıcı menüsünden “Ana ekrana ekle” ile uygulama gibi kullan.

Bilgisayar açık kaldığı sürece telefondan konuşmalı ders dahil her şey çalışır. Uzaktan girişler şifre ister (kendi şifreni `.env` içinde `ERISIM_SIFRESI=` ile de belirleyebilirsin).

### 💸 Ücretsiz ses seçenekleri

Ayarlar → **Ses kaynağı**:

| Seçenek | Ücret | Sesin | Not |
|---|---|---|---|
| **Microsoft Edge** (varsayılan) | **ücretsiz** | hazır Türkçe ses: Emel (kadın) / Ahmet (erkek) | çok doğal ve hızlı, internet gerekir; **internet yoksa kendiliğinden Piper'a geçer** |
| **İnternetsiz ses (Piper)** | **ücretsiz** | hazır Türkçe ses (dfki) | tamamen bilgisayarda, çok hızlı; Edge kadar doğal değil |
| **Kendi sesim (XTTS-v2 yerel klon)** | **ücretsiz** | **senin sesin** | `pip install -r requirements-klon.txt` (~2 GB model), sonra Ayarlar'da “Okuyarak kaydet” ile 15-30 sn sesini kaydet; hoca otomatik olarak senin sesine geçer. NVIDIA ekran kartı varsa hızlı, yoksa her cümle birkaç saniye sürer. Model lisansı ticari olmayan kullanım içindir |
| Tarayıcı | ücretsiz | robotik | kurulum gerekmez |
| ElevenLabs | ücretli (kredi) | en doğal klon | isteğe bağlı; `.env`'e `ELEVENLABS_API_KEY` eklersen seçilebilir |

Sesli soruların yazıya çevrilmesi de ücretsizdir: **Whisper** bilgisayarında çalışır (`large-v3-turbo` Türkçede çok isabetli; zayıf bilgisayarda `.env`'de `WHISPER_MODEL=small` yap).

> Hocanın beyni, ses ve konuşma tanıma tamamen ücretsizdir ve bilgisayarında çalışır.

### Anahtarsız deneme

Arayüzü yapay zeka kurmadan, sahte yapay zeka ve ses cevaplarıyla denemek için:

```bash
python tests/demo_server.py      # http://localhost:8765
```

## Nasıl çalışıyor?

```
Tarayıcı                         Sunucu (FastAPI)                     Servisler
────────                         ────────────────                     ─────────
Soru + ekler ──POST /api/ask──▶  notlar + hafıza + geçmiş ──stream──▶ yerel yapay zeka (Ollama)
                                 ◀── {"say":..., "board":[...]} satırları
             ◀──SSE adım──────── her adım için paralel ses üretimi ──▶ Edge / yerel klon
Oynatıcı: adımın sesi çalarken
tahta işlemleri sesin süresine
yayılarak el yazısıyla çizilir
```

- Yapay zeka cevabı **satır satır JSON adımları** olarak yazar: `say` (sesli söylenecek cümle) + `board` (aynı anda tahtaya yazılacaklar: başlık, el yazısı satırı, LaTeX formül, grafik, serbest çizim, altını çizme, kutulama, not sayfası gösterme, yeni sayfa). Talimatlar: `app/prompts.py`.
- İlk adım gelir gelmez sesi üretilmeye başlar; sen ilk cümleyi dinlerken model sonraki adımları yazmaya devam eder.
- Notlar modelin bağlamına sığıyorsa tamamı verilir; sığmıyorsa soruyla ilgili sayfalar seçilir. Uzun konuşmalarda en eski turlar kırpılır, sistem talimatı ve son soru hep korunur.
- Model: donanıma göre `gemma4:e2b … gemma4:26b` (Ayarlar'dan seçilebilir).

## Dosyalar

```
app/main.py      API uçları, anlatım akışı (SSE), ses üretimi
app/llm.py       Beyin yönlendirme (yerel / isteğe bağlı Gemini), adım ayrıştırıcı, yapılandırılmış çıktılar
app/yerel.py     Yerel yapay zeka: donanıma göre model, Ollama'yı indirme/başlatma, model indirme
app/llm_yerel.py Ollama sohbet akışı, JSON şemalı çıktılar, görüntü/PDF, bağlama sığdırma
app/paket.py     Ders paketi üretimi (özetler, konu anlatımı, kısa özet, deneme sınavları)
app/siniflandir.py  Notun dersini bulma (kod, paket, benzerlik, yapay zeka)
app/klasor.py    Not Kutusu ve İndirilenler'den kendiliğinden içe aktarma
app/kutuphane.py Yerel bilgi bankası: kitap/makale okuma, parçalama, gömme, hibrit arama, kaynak gösterme
app/literatur.py Haftalık literatür taraması (Crossref, arXiv, OpenAlex) ve otomatik güncelleme
app/hazir.py     Hazır ders paketleri
app/prompts.py   Hoca talimatları ve tahta protokolü
app/notes.py     Dersler, PDF/fotoğraf → sayfa metni + görüntü, not bağlamı
app/voice.py     Ses: Edge TTS, Piper (internetsiz), XTTS yerel klon, Whisper (ücretsiz); ElevenLabs (isteğe bağlı)
app/store.py     Kayıtlar ve hafıza (zayıf konular)
app/curriculum.py, app/mufredat/  Hazır bölüm müfredatları → ders profilleri
                 (gazi_endustri.json: Gazi Ü. Endüstri Müh. %30 İngilizce, 2026 planı, OBS Bologna'dan)
app/auth.py      Telefondan erişim için şifre
baslat.py        Masaüstü penceresinde başlatıcı
static/board.js  El yazısı tahta: metin açılımı, çizgi çizgi grafik/şekil çizimi, PDF dışa aktarma
static/player.js Ses + tahta senkron oynatıcı (duraklat, hız, söz kesme)
static/teacher.js      Hoca karakteri (SVG, ağız senkronu, pozlar)
static/conversation.js Konuşmalı mod: ses etkinliği algılama, söz kesme, WAV kaydı
static/formul.html     Yazdırılabilir formül kâğıdı
static/app.js    Arayüz
tests/           Birim + API testleri (sahte servislerle), demo sunucu
```

Veriler (`veri/` klasörü: notlar, kayıtlar, ses dosyaları, hafıza) yalnızca senin bilgisayarında tutulur.

## 🌱 Hoca kendini nasıl geliştirir

- **Geri bildirim:** Hocanın her cevabının altındaki 👍 / 👎 düğmeleri (👎'da "anlamadım, çok hızlı, yanlış, çok uzun" ya da kendi notun) `veri/ogrenme/geri_bildirim.jsonl` dosyasına yazılır. Aynı dersteki benzer sorularda beğendiğin anlatımlar "iyi örnek", beğenmediklerin "kaçın" olarak kısa bir blokla hocaya verilir (en fazla ~1100 karakter).
- **Kendi kendine çalışma:** Bilgisayar boşken (son etkinlikten en az 5 dk sonra, saatte en fazla 20 soru) hoca kütüphane parçalarından ve ders notlarından soru-cevap üretir, ikinci bir çağrıyla kaynakla karşılaştırıp doğrular; yalnızca doğrulananlar soru bankasına girir. Bunlar cevaplarda "doğrulanmış bilgi" olarak kullanılır; Sınav sekmesindeki **🏦 Soru bankasından sor** ile de çözebilirsin. Ayarlar'dan kapatılabilir (yalnızca yerel yapay zekada çalışır).
- **Seni tanıma:** "örnek ver", "daha yavaş", "kısaca", "formülle" gibi isteklerin ve 👎 notların sayılır; bir tercih en az 3 kez görülünce hocaya 1-2 satırlık "öğrencinin tercihleri" eklenir. Ayarlar'dan **Öğrenci profilimi sıfırla** ile silinir.
- **Öğretme tarzı:** Ayarlar'dan "Anlat" (varsayılan) ya da "Sokratik" (hoca önce küçük sorularla yönlendirir, takılırsan ipucu verir, 2-3 turda ilerlemezsen açıklar). Her iki tarzda uzun anlatımların sonunda hoca tek bir kısa kontrol sorusu sorar.

## Test

```bash
pytest
```

## Maliyet notu

Hiçbir şey ücretli değildir: yapay zeka, ses ve konuşma tanıma bilgisayarında çalışır. Tek bedel ilk kurulumdaki indirme (~8 GB) ve bilgisayarın işlemci/ekran kartı gücüdür.
