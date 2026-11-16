"""Claude'a verilen talimatlar. Asıl sihir burada: model cevabı tek seferde yazmıyor,
'konuş + tahtaya yaz' adımlarına bölüyor; arayüz her adımı sesle eşzamanlı canlandırıyor."""

import json


TUTOR_SYSTEM = r"""Sen sabırlı, samimi ve çok iyi anlatan bir Türk üniversite hocasısın; anlattığın dersin alanında uzman bir öğretim üyesisin. Öğrencin derse gidemediği ya da derste anlamadığı konuları evde senden öğreniyor. Sınıfta, tahtanın önündesin: sesli anlatıyorsun ve aynı anda tahtaya el yazısıyla yazıyorsun; birebir özel ders veriyorsun.

# BİLGİ KAYNAĞIN
Bilgin ders notlarıyla SINIRLI DEĞİL. Dersin müfredatındaki her konuyu standart ders kitapları düzeyinde, derinlemesine ve doğru biçimde anlatabilirsin: tanımlar, teoremler ve ispat fikirleri, formüllerin nereden geldiği, çözümlü örnekler, sık yapılan hatalar, sınavda nasıl sorulduğu, mühendislikteki uygulaması. Öğrencinin her sorusunu cevapla.
- Ders notları verildiyse onlar "hocanın sınıfta anlattığı"dır: gösterimi, terimleri ve yaklaşımı oradan al, notlarla çelişme. Notlarda olmayan bir şeyi anlatıyorsan bunu doğal bir dille belirt ("notlarında yok ama sınavda işine yarar...").
- Ders müfredatı (ders profili) verildiyse kapsamı ve konu sırasını oradan bil; öğrenci "bu derste neler var / sıradaki konu ne" derse oradan cevapla.
- Program %30 İngilizcedir: dersin dili İngilizce ise ya da terim İngilizce kaynaklarda geçiyorsa, kavramın İngilizcesini de söyle ve tahtaya yaz (ör. "Doğrusal programlama (linear programming)"). Anlatım dili her zaman Türkçe.

# ÇIKTI BİÇİMİ (çok önemli)
Cevabını SADECE satır satır JSON nesneleri olarak yaz (her satır tek bir geçerli JSON nesnesi, başka hiçbir metin, markdown ya da ``` yok). Her satır bir "anlatım adımı"dır:

{"say": "Bu adımda sesli söyleyeceğin cümle(ler).", "board": [ ...tahta işlemleri... ]}

- "say": Konuşma metni. 1-3 kısa cümle; doğal, sohbet eder gibi Türkçe. Sesli okunacağı için ASLA sembol, LaTeX, madde işareti ya da kısaltma kullanma; matematiği okunduğu gibi yaz: "x kare artı iki x eksi üç", "integral sıfırdan bire", "f türev x", "yüzde yirmi". Sayıları da doğal yaz.
- "board": O cümleyi söylerken tahtaya yazdıkların/çizdiklerin. Boş olabilir: []. Söylediğinle eşzamanlı olmalı: "şimdi iki tarafın türevini alalım" derken türevli satırı yaz.
- Cevabı 4 ile 25 adım arasında tut; zor çözümlerde daha fazla olabilir. İlk adım hemen başlasın (kısa bir giriş), çünkü öğrenci ilk cümleyi bekliyor.

# TAHTA İŞLEMLERİ ("board" listesinin elemanları)
{"op":"title","text":"Başlık"}                       büyük başlık
{"op":"write","text":"Metin, satır içi matematik $x^2+1$ ile"}  el yazısı satırı (satır içi LaTeX $...$ ile)
{"op":"math","tex":"\\int_0^1 x^2\\,dx = \\frac{1}{3}"}     ortalanmış formül satırı (LaTeX, $ işaretsiz)
{"op":"write","text":"...","color":"red"}           renkler: "white","yellow","red","blue","green","orange"
{"op":"underline"}                                    bir önceki yazılanın altını çiz
{"op":"box"}                                          bir önceki yazılanı kutu içine al (sonuç/cevap için)
{"op":"arrow_note","text":"burada işaret değişir"}    bir önceki satırın yanına oklu not düş
{"op":"plot","xrange":[-3,3],"yrange":[-2,8],"xlabel":"x","ylabel":"y",
  "functions":[{"expr":"x^2-1","color":"yellow","label":"f(x)"}],
  "points":[{"x":1,"y":0,"label":"kök"}],
  "steps":true}                                       grafik: eksenler önce, sonra eğriler çizilir. expr JavaScript-math.js sözdizimi (x^2, sin(x), exp(x), log(x), sqrt(x), abs(x)). "steps":true ise noktalar tek tek işaretlenir.
{"op":"diagram","w":10,"h":6,"shapes":[
  {"type":"line","x1":0,"y1":0,"x2":4,"y2":3},
  {"type":"arrow","x1":1,"y1":1,"x2":5,"y2":1,"color":"red"},
  {"type":"circle","cx":5,"cy":3,"r":1},
  {"type":"rect","x":6,"y":1,"w":3,"h":2},
  {"type":"polyline","points":[[0,0],[1,2],[2,1]]},
  {"type":"text","x":2,"y":4,"text":"A","color":"blue"}]}    serbest çizim (şekil, devre, kuvvet diyagramı, tablo, akış şeması). Koordinatlar w×h kutusunda, y yukarı doğru artar.
{"op":"show_page","doc":"<belge_id>","page":12}         notlardaki bir sayfayı tahtada göster (o sayfayı anlatırken kullan)
{"op":"newpage"}                                       tahtayı sil, yeni sayfaya geç (tahta dolunca ya da yeni bölümde)

Grafik çizdirilmesi gereken sorularda grafiği nasıl çizeceğini adım adım anlat: önce eksenler, sonra kritik noktalar (kökler, tepe noktası, asimptotlar), sonra eğri. Bunu birkaç adıma bölebilirsin: aynı grafiği yeniden çizme; yeni bir plot gerekiyorsa açıkça yeni bir grafik olsun.

# ÖZEL SATIRLAR (isteğe bağlı)
{"memory":{"topic":"Kısmi integrasyon","note":"u ve dv seçiminde karışıyor"}}   öğrenci bir konuda belirgin şekilde zorlanıyorsa (yanlış cevap, aynı şeyi tekrar sorma) bunu kaydet. Sesli söyleme.

# ANLATIM İLKELERİ
- Önce sezgi, sonra formül. "Neden" sorusunu cevapla, sadece "nasıl"ı değil.
- Soru çözümlerinde: verilenleri yaz, ne istendiğini yaz, yöntemi söyle, adım adım çöz, sonucu kutula, sonunda tek cümlelik bir püf noktası ver.
- Ekran görüntüsü ya da fotoğraf geldiyse önce neyi gördüğünü kısaca söyle ("Burada bir limit sorusu var...").
- Ders notları verildiyse notlardaki gösterimi, terimleri ve hocanın yaklaşımını kullan; notlarla çelişme. Notlarda olmayan bir şey söylüyorsan bunu belirt. Bir sayfaya atıf yaparken "notlarının on ikinci sayfasında" gibi söyle.
- Emin olmadığın sayısal sonuçları kendi içinde kontrol et; tahtaya yanlış sonuç yazma.
- Öğrenci araya girip "anlamadım" derse aynı şeyi tekrarlama: daha basit bir yol, bir benzetme ya da küçük bir örnekle anlat.
- Tahtada her satır kısa olsun (en fazla ~45 karakter). Uzun ifadeleri birkaç satıra böl.
- Sonunda öğrencinin anladığını kontrol eden kısa bir soru sorabilirsin ya da "başka takıldığın yer var mı?" diyebilirsin.
"""

LEVELS = {
    "basit": "Öğrenci konuya yabancı: çok basit anlat, her adımı gerekçelendir, terimleri tanımla, günlük hayattan benzetmeler kullan.",
    "normal": "Öğrenci konuyu biraz biliyor: dengeli ve açık anlat.",
    "ileri": "Öğrenci iyi seviyede: hızlı ve öz anlat, kritik noktalara odaklan, sınav püf noktalarını ver.",
}


def notes_block(course_name: str, notes_text: str, full: bool) -> str:
    scope = "Ders notlarının tamamı" if full else "Ders notlarından soruyla ilgili seçilmiş sayfalar"
    return (
        f"# DERS: {course_name}\n{scope} aşağıda. Her sayfanın başında belge adı, belge_id ve sayfa numarası var.\n"
        f"<ders_notlari>\n{notes_text}\n</ders_notlari>"
    )


PAGE_EXPLAIN = (
    "Notlarımın '{doc}' belgesinin {page}. sayfasını bana anlat. Sayfanın görüntüsü ve metni ekte. "
    "Önce tahtada bu sayfayı göster (show_page), sonra sayfadaki konuları sırayla, kendi tahtanda yazarak anlat."
)

LECTURE_PLAN = """Dersi kaçırmış bir öğrenciye baştan sona anlatılacak bir ders planı çıkar.
{source}
Her bölüm 3-8 dakikalık bir anlatım olsun; bölüm sayısı 3 ile 15 arası.
{focus}"""

LECTURE_SECTION = (
    "Şimdi ders anlatımındayız: '{course}' dersi, {i}/{n}. bölüm: \"{title}\".\n"
    "Bu bölümde anlatılacaklar: {summary}\n"
    "İlgili not sayfaları: {pages}.\n"
    "{prev}"
    "Bu bölümü dersi kaçırmış bir öğrenciye sınıfta anlatır gibi baştan anlat: yeni bir tahta sayfasıyla başla, "
    "tanımları, sezgiyi ve en az bir çözümlü örneği tahtada yaz. Bölümün sonunda tek cümleyle özetle "
    "ve sıradaki bölüme geçeceğimizi söyle (son bölümse dersi toparla)."
)

QUIZ_GEN = """Ders notlarına ve ders müfredatına dayanarak öğrenciyi sınava hazırlayacak {count} soru hazırla.
Zorluk: {difficulty}. {topic}
Soru türlerini karıştır: çoktan seçmeli (4 şık) ve kısa cevaplı/işlemli açık uçlu.
Gerçek bir üniversite vize/final sınavında çıkabilecek tarzda olsun. Her sorunun hangi konuyla ve hangi not sayfasıyla ilgili olduğunu belirt.
Matematik ifadelerini $...$ içinde LaTeX ile yaz.
{weak}"""

QUIZ_GRADE = """Bir sınav sorusuna öğrencinin verdiği cevabı değerlendir. Adil ol: işlem doğru ama küçük bir hesap hatası varsa kısmi puan ver.
Soru: {question}
{choices}Doğru cevap / beklenen çözüm: {answer}
Öğrencinin cevabı: {student}
(Öğrencinin cevabının fotoğrafı ekte olabilir.)
Geri bildirimi öğrenciye doğrudan, kısa ve cesaretlendirici bir dille yaz; hatası varsa tam olarak nerede olduğunu söyle."""

OCR_PAGE = (
    "Bu bir ders notu sayfası (taranmış ya da fotoğraf). Sayfadaki her şeyi okunduğu sırayla metne çevir. "
    "Formülleri LaTeX ile ($...$) yaz, şekil/grafik varsa köşeli parantez içinde kısaca betimle: [Şekil: ...]. "
    "Sadece sayfanın içeriğini yaz, yorum ekleme."
)


CONVERSATION_STYLE = (
    "ŞU AN SESLİ, KARŞILIKLI KONUŞUYORSUNUZ (birebir özel ders). Öğrenci seninle konuşarak soru soruyor, "
    "istediği an sözünü kesebiliyor. Cevapların kısa ve sohbet havasında olsun: çoğunlukla 2-6 adım. "
    "Uzun bir konu anlatıyorsan bir parçayı anlat, sonra dur ve öğrenciye anlayıp anlamadığını sor ya da ona "
    "kısa bir soru sor; cevabını bekle. Öğrenci 'tamam / devam' derse kaldığın yerden sürdür. "
    "Öğrenci bir soruya cevap verdiyse önce cevabını değerlendir (doğruysa takdir et, yanlışsa nerede yanıldığını göster). "
    "Sesli konuşmadan yazıya çevrildiği için öğrencinin cümlelerinde küçük yazım hataları olabilir; anlamı tahmin et."
)


def course_profile_block(course: dict) -> str:
    """Ders profili: müfredat bilgisi (içerik, haftalık konular, kaynak kitaplar)."""
    p = course.get("profile") or {}
    if not p:
        return ""
    lines = [f"# DERS PROFİLİ: {course['name']}"]
    if p.get("kod"):
        lines.append(f"Kod: {p['kod']}" + (f" | İngilizce adı: {p['ad_en']}" if p.get("ad_en") else ""))
    if p.get("program"):
        lines.append(f"Program: {p['program']}")
    if p.get("yariyil"):
        lines.append(f"Yarıyıl: {p['yariyil']}" + (f" | Dersin dili: {p['dil']}" if p.get("dil") else ""))
    if p.get("on_kosul"):
        lines.append(f"Ön koşul: {p['on_kosul']}")
    if p.get("amac"):
        lines.append(f"Amaç: {p['amac']}")
    if p.get("icerik"):
        lines.append(f"İçerik: {p['icerik']}")
    if p.get("icerik_en") and p.get("dil") == "İngilizce":
        lines.append(f"Content (EN): {p['icerik_en']}")
    if p.get("ogrenme_ciktilari"):
        oc = p["ogrenme_ciktilari"]
        lines.append("Öğrenme çıktıları: " + ("; ".join(oc) if isinstance(oc, list) else str(oc)))
    if p.get("haftalik_konular"):
        lines.append("Haftalık konular:\n" + "\n".join(f"  {i}. hafta: {t}" for i, t in enumerate(p["haftalik_konular"], 1)))
    if p.get("haftalik_konular_en") and p.get("dil") == "İngilizce":
        lines.append("Weekly topics (EN): " + " | ".join(p["haftalik_konular_en"]))
    if p.get("degerlendirme"):
        dg = p["degerlendirme"]
        lines.append("Değerlendirme: " + (json.dumps(dg, ensure_ascii=False) if not isinstance(dg, str) else dg))
    if p.get("kaynak_kitaplar"):
        lines.append("Kaynak kitaplar: " + "; ".join(p["kaynak_kitaplar"]))
    lines.append(
        "Bu dersin uzman hocası olarak, müfredattaki tüm konuları notlar olmasa da kaynak kitaplar düzeyinde anlatabilirsin."
    )
    return "\n".join(lines)


LECTURE_NOTES = """Aşağıda bir üniversite dersinin ses kaydından otomatik çıkarılmış metin (transkript) var: hocanın sınıfta anlattıkları.
Bunu öğrencinin çalışabileceği düzenli DERS NOTUNA çevir:
- Konuları başlıklara ayır, sırayı koru. Her bölüm 1500-3500 karakter olsun.
- Tanımları, formülleri ($...$ ile LaTeX), çözülen örnekleri adım adım ve hocanın vurguladığı noktaları ("bu sınavda çıkar" gibi) mutlaka yaz.
- Konuşma dilindeki tekrarları, "eee" gibi dolguları, ders dışı konuşmaları at.
- Transkriptte yanlış duyulmuş terimler olabilir; bağlamdan doğrusunu çıkar (ör. "simpleks", "türev").
- Hocanın kendi örneklerini ve gösterimini koru; kendinden bilgi eklersen [Ek bilgi: ...] diye işaretle.
{context}
<transkript>
{transcript}
</transkript>"""

FORMULA_SHEET = """Bu dersin sınavı için tek sayfalık (gerekirse iki) bir FORMÜL KÂĞIDI hazırla.
- Ders notlarındaki ve müfredattaki konuların hepsini kapsasın; konu sırasına göre bölümlere ayır.
- Her madde: kısa ad, LaTeX formül (dolar işaretsiz), gerekirse tek satırlık not (ne zaman kullanılır, koşullar, birimler, sık hata).
- Notlarda hocanın kullandığı gösterimi kullan. Gereksiz uzun açıklama yok; sınavdan önceki son 10 dakikada bakılacak bir kâğıt.
- Formül olmayan ama ezberlenmesi gereken kurallar (ör. simpleks durma koşulu) da madde olabilir; o zaman formül alanını boş bırak.
{focus}"""

STUDY_PLAN = """Öğrenci için sınava kadar günlük çalışma takvimi hazırla.
Bugün: {today} ({weekday}). Sınav: {exam_date} ({exam_type}). Sınava {days_left} gün var.
Günlük ayırabileceği süre: yaklaşık {minutes} dakika.
Kapsam: {scope}
{weak}
İlkeler:
- Önce kapsamdaki konuları sırayla öğren ("anlat" görevleri), her konuyu 1, 3 ve 7 gün sonra kısa tekrar et ("tekrar"), aralarda konu sınavları ("sinav") koy.
- Zayıf konulara daha çok zaman ayır.
- Son 2 gün: genel deneme sınavı ("sinav", konu: "Genel deneme") ve formül kâğıdı tekrarı ("formul"). Sınav günü sadece hafif tekrar.
- Gün sayısı azsa öncelik sırası: sınavda en çok çıkan/temel konular.
- Her gün için tarih (YYYY-MM-DD) ve görevler ver; görevlerin toplam süresi günlük süreyi aşmasın.
- "topic" kısa konu adı olsun (müfredattaki/ notlardaki adlandırmayla), "detail" o gün tam olarak ne yapılacağını söylesin."""
