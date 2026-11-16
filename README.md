# ✎ Ders Anlatıcı

Ders notlarını öğrenen, soruları **senin sesinle** (ElevenLabs klonu) anlatan ve anlatırken **tahtaya el yazısıyla yazan** kişisel ders hocası.

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

Ayrıca: hız ayarı (0.8×–1.5×), duraklat/devam (**P**), tahta sayfaları arasında gezinme, **tahtayı PDF indirme**, anlatım seviyesi (basit/normal/ileri), **hafıza**: zorlandığın konuları kaydeder, sonraki anlatımlarda ve sınavlarda bunlara ağırlık verir.

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

```bash
uvicorn app.main:app --port 8000
```

Tarayıcıda **http://localhost:8000** adresini aç (Chrome/Edge önerilir; mikrofon için tarayıcı izin isteyecek).

İlk kullanım:
1. **+ Ders** ile ders oluştur.
2. **Notlar** sekmesinden PDF'leri / defter fotoğraflarını yükle.
3. **Sohbet**'ten sor ya da **Ders anlat** ile baştan dinle.

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
static/board.js  El yazısı tahta: metin açılımı, çizgi çizgi grafik/şekil çizimi, PDF dışa aktarma
static/player.js Ses + tahta senkron oynatıcı (duraklat, hız, söz kesme)
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
