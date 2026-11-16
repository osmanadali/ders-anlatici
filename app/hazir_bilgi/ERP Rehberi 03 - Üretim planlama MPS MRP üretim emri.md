# Üretim planlama zinciri: MPS, MRP ve üretim emri

ERP'nin üretim tarafı, müşteri talebinden başlayıp atölyede bir üretim emrinin tamamlanmasına kadar uzanan hiyerarşik bir planlama zinciridir. Her seviye bir üsttekinin çıktısını girdi olarak alır ve daha ayrıntılıdır.

## Planlama hiyerarşisi

1. **Satış ve operasyon planlaması (S&OP):** Aylık/üç aylık düzeyde talep, üretim ve stok planının üst yönetimle uzlaştırılması. Ürün aileleri düzeyindedir.
2. **Toplu üretim planlaması (aggregate planning):** Ürün aileleri için aylık üretim, fazla mesai, taşeron ve stok kararları.
3. **Ana üretim çizelgesi (MPS, Master Production Schedule):** Bitmiş ürün düzeyinde, haftalık/günlük "hangi üründen ne kadar, hangi hafta tamamlanacak" planı.
4. **Malzeme ihtiyaç planlaması (MRP):** MPS'i bileşen ve hammadde ihtiyaçlarına patlatır.
5. **Kapasite ihtiyaç planlaması (CRP):** MRP'nin ürettiği emirlerin iş merkezlerinde yükünü hesaplar.
6. **Üretim emri (production order) ve atölye kontrolü:** Emirlerin serbest bırakılması, çizelgelenmesi, izlenmesi.

## MPS'in girdileri ve mantığı

MPS, **tahminler**, **kesin müşteri siparişleri** ve **eldeki stok** üzerinden kurulur. Bir hafta için mantık şöyledir:

- Brüt ihtiyaç = o haftanın tahmini ile kesin siparişinden büyük olanı (zaman aralığına bağlı kurallar uygulanır).
- Öngörülen eldeki stok = önceki hafta sonu stoku + planlanan üretim − brüt ihtiyaç.
- Öngörülen eldeki stok emniyet stokunun altına düşeceği hafta, MPS miktarı (parti kuralıyla) planlanır.
- **ATP (Available to Promise):** Henüz taahhüt edilmemiş, müşteriye söz verilebilecek miktar.

**Zaman çitleri (time fences):** Yakın dönemde MPS donuktur (değişiklik yöneticinin iznine bağlıdır); orta dönemde sınırlı esnektir; uzak dönemde sistem serbestçe değiştirebilir. Sık plan değişikliği "sinirlilik" (nervousness) yaratır.

## MRP mantığı

MRP dört soruya cevap verir: *Neye ihtiyacım var? Ne kadar ihtiyacım var? Elimde ve yolda ne var? Ne zaman sipariş vermeliyim?* Girdileri üçtür: MPS, **ürün ağacı (BOM)** ve **stok kayıtları**. Her malzeme için, seviye seviye (üstten alta, düşük seviye koduna göre) şu tablo doldurulur:

| Satır | Anlamı |
|---|---|
| Brüt ihtiyaç | Üst seviye emirlerinden ve bağımsız taleplerden gelen ihtiyaç |
| Planlanan alımlar | Zaten verilmiş, beklenen siparişler (scheduled receipts) |
| Öngörülen eldeki stok | Dönem sonu beklenen stok |
| Net ihtiyaç | Brüt ihtiyaç + emniyet stoku − (elde stok + beklenen alımlar), negatif olamaz |
| Planlanan sipariş girişi | Net ihtiyacı parti kuralıyla karşılayan miktar, ihtiyaç haftasında |
| Planlanan sipariş çıkışı | Aynı miktar, **tedarik süresi kadar öne çekilmiş** hafta |

Planlanan sipariş çıkışı, bir alt seviye malzemenin **brüt ihtiyacına** dönüşür (ürün ağacındaki adetle çarpılarak). Böylece ihtiyaç ağacın en altına kadar yayılır. Bir malzeme ağacın birden çok yerinde kullanılıyorsa, en alt seviyesine göre ("düşük seviye kodu") bir kez hesaplanır ve tüm ihtiyaçlar toplanır.

**Küçük örnek:** MPS: 6. haftada 100 adet mamul P. Bir P'de iki parça B var. P'nin tedarik süresi 1 hafta, B'ninki 2 hafta, B stoku 50. P için planlanan sipariş çıkışı 5. haftada 100. B'nin brüt ihtiyacı 5. haftada 200; stok 50 olduğundan net ihtiyaç 150; B'nin planlanan sipariş çıkışı 3. haftada 150 (L4L kuralıyla).

## Parti büyüklüğü (lot sizing) kuralları

- **L4L (lot-for-lot):** Net ihtiyaç kadar sipariş; stok tutma minimum, sipariş sayısı yüksek.
- **Sabit sipariş miktarı (FOQ):** Her seferinde sabit parti, net ihtiyacı aşan kısmı stoğa gider.
- **EOQ:** Ekonomik sipariş miktarı sabit parti olarak kullanılır; düzgün talep varsayar.
- **Silver-Meal ve Wagner-Whitin:** Dönemlik değişen talepte sipariş ve stok tutma maliyetini dengeleyen dinamik yöntemler; Wagner-Whitin optimumdur, Silver-Meal sezgiseldir.
- **Dönem sipariş miktarı (POQ):** Belirli sayıda dönemin ihtiyacını birleştirir.

## Üretim emri yaşam döngüsü

MRP, üretilen malzemeler için **planlı sipariş (planned order)** üretir. Planlayıcı bunu **üretim emrine (production order)** dönüştürür; emir, ürün ağacındaki bileşenleri ve rotadaki operasyonları kopyalar. Tipik durumlar: oluşturuldu → serbest bırakıldı (release) → bileşenler çekildi (goods issue) → operasyon onayları (confirmation) → mal girişi (goods receipt) → teknik olarak kapatıldı → maliyet sapması hesaplanıp kapatıldı. Satın alınan malzemelerde planlı sipariş satın alma talebine dönüşür.

## Planlama zorlukları

- **Sınırsız kapasite varsayımı:** Klasik MRP kapasiteyi kısıt olarak görmez; CRP ve gelişmiş planlama sistemleri (APS) bunu giderir.
- **Sabit tedarik süresi varsayımı:** Gerçekte süreler değişkendir; emniyet süresi ve emniyet stoku bunu karşılar.
- **Veri doğruluğu:** Stok kayıt doğruluğu %95-98'in altına düşerse MRP güvenilmez; döngüsel sayım uygulanır.
- **Sinirlilik:** Üst seviyedeki küçük değişiklik alt seviyede büyük dalgalanma yaratabilir.

## Kısa özet

S&OP ve MPS "ne üreteceğiz" sorusunu, MRP "bunun için ne zaman ne sipariş edeceğiz" sorusunu cevaplar. MRP, brüt ihtiyaçtan net ihtiyaca, parti kuralından tedarik süresi öteleme ile planlanan sipariş çıkışına kadar tablo mantığıyla yürür. Üretim emri bu planın uygulamaya dönmüş hâlidir.
