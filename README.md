# ✎ Ders Anlatıcı

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

## En kolay kurulum (Windows)

1. Python yoksa https://www.python.org/downloads/ adresinden kur. Kurulumun ilk ekranında **"Add python.exe to PATH"** kutusunu işaretlemeyi unutma.
2. Zip'i bir klasöre çıkar, **Kurulum.bat** dosyasına çift tıkla (ilk seferde birkaç dakika sürer).
3. **Ders Anlatıcı.bat** dosyasına çift tıkla. Açılan Ayarlar penceresine ücretsiz Gemini anahtarını yapıştır.

Mac'te aynı adımlar **Kurulum.command** ve **Ders Anlatıcı.command** ile.

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

**API anahtarı:** Uygulamayı ilk açtığında Ayarlar penceresi kendiliğinden açılır. **Gemini anahtarı** alanına ücretsiz anahtarını yapıştırıp Kaydet'e bas, o kadar. Anahtarı almak için https://aistudio.google.com/apikey → Google hesabınla gir → **Create API key** → çıkan `AIza…` ile başlayan metni kopyala. (Claude anahtarı isteğe bağlıdır, daha derin anlatım için.) Anahtarlar bilgisayarındaki `.env` dosyasına kaydedilir; istersen o dosyayı elle de düzenleyebilirsin.

Ses ve konuşma tanıma **varsayılan olarak ücretsizdir**, anahtar istemez: hoca Microsoft Edge'in Türkçe sesiyle konuşur, sesli sorularını bilgisayarındaki Whisper yazıya çevirir (ilk sesli soruda ~1.6 GB model bir kez iner). Kendi sesini istiyorsan aşağıdaki **Ücretsiz ses** bölümüne bak.

## Çalıştırma

**Masaüstü uygulaması gibi (önerilen):** Windows'ta `Ders Anlatıcı.bat`, Mac'te `Ders Anlatıcı.command` dosyasına çift tıkla (ya da `python baslat.py`). Uygulama adres çubuğu olmayan kendi penceresinde açılır; pencereyi kapatınca kapanır. Mikrofon izni bir kez verilir.

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
| **Microsoft Edge** (varsayılan) | **ücretsiz** | hazır Türkçe ses: Emel (kadın) / Ahmet (erkek) | çok doğal ve hızlı, internet gerekir |
| **Kendi sesim (XTTS-v2 yerel klon)** | **ücretsiz** | **senin sesin** | `pip install -r requirements-klon.txt` (~2 GB model), sonra Ayarlar'da “Okuyarak kaydet” ile 15-30 sn sesini kaydet; hoca otomatik olarak senin sesine geçer. NVIDIA ekran kartı varsa hızlı, yoksa her cümle birkaç saniye sürer. Model lisansı ticari olmayan kullanım içindir |
| Tarayıcı | ücretsiz | robotik | kurulum gerekmez |
| ElevenLabs | ücretli (kredi) | en doğal klon | isteğe bağlı; `.env`'e `ELEVENLABS_API_KEY` eklersen seçilebilir |

Sesli soruların yazıya çevrilmesi de ücretsizdir: **Whisper** bilgisayarında çalışır (`large-v3-turbo` Türkçede çok isabetli; zayıf bilgisayarda `.env`'de `WHISPER_MODEL=small` yap).

> Not: Claude (hocanın beyni) ücretsiz değildir; kullanım kadar ödenir. Ses ve konuşma tanıma ise tamamen ücretsizdir.

### Anahtarsız deneme

Arayüzü API anahtarı olmadan, sahte Claude ve ses cevaplarıyla denemek için:

```bash
python tests/demo_server.py      # http://localhost:8765
```

## Nasıl çalışıyor?

```
Tarayıcı                         Sunucu (FastAPI)                     Servisler
────────                         ────────────────                     ─────────
Soru + ekler ──POST /api/ask──▶  notlar + hafıza + geçmiş ──stream──▶ Claude
                                 ◀── {"say":..., "board":[...]} satırları
             ◀──SSE adım──────── her adım için paralel ses üretimi ──▶ Edge / yerel klon
Oynatıcı: adımın sesi çalarken
tahta işlemleri sesin süresine
yayılarak el yazısıyla çizilir
```

- Claude cevabı **satır satır JSON adımları** olarak yazar: `say` (sesli söylenecek cümle) + `board` (aynı anda tahtaya yazılacaklar: başlık, el yazısı satırı, LaTeX formül, grafik, serbest çizim, altını çizme, kutulama, not sayfası gösterme, yeni sayfa). Talimatlar: `app/prompts.py`.
- İlk adım gelir gelmez sesi üretilmeye başlar; sen ilk cümleyi dinlerken model sonraki adımları yazmaya devam eder.
- Notlar küçükse tamamı modele verilir ve **önbelleğe alınır** (tekrarlayan sorularda ucuz ve hızlı). Çok büyükse soruyla ilgili sayfalar seçilir.
- Model: `claude-opus-5-5` (ayarlanabilir), sunucu tarafı yedek model (fallback) açık.

## Dosyalar

```
app/main.py      API uçları, anlatım akışı (SSE), ses üretimi
app/llm.py       Claude çağrıları, adım ayrıştırıcı, yapılandırılmış çıktılar (plan, sınav, puanlama, OCR)
app/prompts.py   Hoca talimatları ve tahta protokolü
app/notes.py     Dersler, PDF/fotoğraf → sayfa metni + görüntü, not bağlamı
app/voice.py     Ses: Edge TTS, XTTS yerel klon, Whisper (ücretsiz); ElevenLabs (isteğe bağlı)
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

## Test

```bash
pytest
```

## Maliyet notu

Ses ve konuşma tanıma ücretsizdir; tek ücretli kısım her soruda yapılan Claude çağrısıdır. Tasarruf için Ayarlar'dan **Hızlı** düşünme derinliğini seçebilirsin. Ders notları önbelleğe alındığı için aynı derste art arda sorulan sorular daha ucuza gelir.
