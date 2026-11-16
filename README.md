# ✎ Ders Anlatıcı

Ders notlarını öğrenen, soruları **senin sesinle** (ElevenLabs klonu) anlatan ve anlatırken **tahtaya el yazısıyla yazan** kişisel ders hocası. Sınıf ortamında, tahtanın yanında duran bir **hoca karakteri** konuşur, yazarken tahtaya uzanır, sen konuşunca susup dinler.

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
| **Notlar** | Derse PDF/fotoğraf yükleme, sayfa görüntüleyici, “Bu sayfayı anlat”, “Soruya ekle” |
| **Ders anlat** | Kaçırdığın dersi notlardan baştan sona bölüm bölüm anlatır (ders planı + otomatik geçiş) |
| **Sınav** | Notlardan vize/final tarzı soru üretir, cevabını (yazılı ya da çözüm fotoğrafı) puanlar, geri bildirimi sesli okur, “Tahtada çöz ve anlat” |
| **Kayıtlar** | Her anlatım sesiyle kaydedilir: baştan izle, ⚡ ile tahtayı anında göster, kaldığın yerden devam et |

Ayrıca: hoca karakteri (sese göre ağız hareketi, yazma/dinleme/düşünme pozları), isteğe bağlı internette araştırma, hız ayarı (0.8×–1.5×), duraklat/devam (**P**), tahta sayfaları arasında gezinme, **tahtayı PDF indirme**, anlatım seviyesi (basit/normal/ileri), **hafıza**: zorlandığın konuları kaydeder, sonraki anlatımlarda ve sınavlarda bunlara ağırlık verir.

## Kurulum

Python 3.10+ gerekir.

```bash
git clone <bu repo>
cd ders-anlatici
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
```

`.env` dosyasına iki anahtarı yaz:

- `ANTHROPIC_API_KEY`: https://console.anthropic.com → API Keys
- `ELEVENLABS_API_KEY`: https://elevenlabs.io → Profil → API Keys (anahtarın *Text to Speech*, *Speech to Text* ve *Voices: read* izinleri olsun)

`VOICE_ID` varsayılan olarak **Osman Adalı** Türkçe klonudur. Başka ses (ör. Türkçe bir kadın sesi) seçmek için uygulamada **⚙ Ayarlar → Anlatıcı sesi** listesini kullan; liste hesabındaki klonları ve sesleri gösterir.

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

### Anahtarsız deneme

Arayüzü API anahtarı olmadan, sahte Claude/ElevenLabs cevaplarıyla denemek için:

```bash
python tests/demo_server.py      # http://localhost:8765
```

## Nasıl çalışıyor?

```
Tarayıcı                         Sunucu (FastAPI)                     Servisler
────────                         ────────────────                     ─────────
Soru + ekler ──POST /api/ask──▶  notlar + hafıza + geçmiş ──stream──▶ Claude
                                 ◀── {"say":..., "board":[...]} satırları
             ◀──SSE adım──────── her adım için paralel ses üretimi ──▶ ElevenLabs (klon)
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
app/voice.py     ElevenLabs TTS (klon ses) ve STT (sesli soru)
app/store.py     Kayıtlar ve hafıza (zayıf konular)
app/curriculum.py, app/mufredat/  Hazır bölüm müfredatları → ders profilleri
baslat.py        Masaüstü penceresinde başlatıcı
static/board.js  El yazısı tahta: metin açılımı, çizgi çizgi grafik/şekil çizimi, PDF dışa aktarma
static/player.js Ses + tahta senkron oynatıcı (duraklat, hız, söz kesme)
static/teacher.js      Hoca karakteri (SVG, ağız senkronu, pozlar)
static/conversation.js Konuşmalı mod: ses etkinliği algılama, söz kesme, WAV kaydı
static/app.js    Arayüz
tests/           Birim + API testleri (sahte servislerle), demo sunucu
```

Veriler (`veri/` klasörü: notlar, kayıtlar, ses dosyaları, hafıza) yalnızca senin bilgisayarında tutulur.

## Test

```bash
pytest
```

## Maliyet notu

Her soru bir Claude çağrısı + konuşulan karakter kadar ElevenLabs kredisi harcar. Kredi tasarrufu için: Ayarlar'dan **Flash v2.5** ses modelini ve **Hızlı** düşünme derinliğini seçebilir ya da klon sesi kapatıp tarayıcı sesini kullanabilirsin.
