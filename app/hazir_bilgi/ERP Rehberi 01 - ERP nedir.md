# ERP nedir? Neden vardır?

ERP (Enterprise Resource Planning, Kurumsal Kaynak Planlaması), bir işletmenin satın alma, üretim, stok, satış, finans, muhasebe ve insan kaynakları gibi bütün birimlerinin aynı veritabanı üzerinde, birbirine bağlı süreçlerle çalışmasını sağlayan yazılım ailesidir. Temel fikir "tek doğru veri kaynağı"dır (single source of truth): bir depocu mal kabul işlemini girdiğinde stok miktarı, satın alma siparişinin durumu, tedarikçi borcu ve muhasebe kaydı aynı anda güncellenir.

## Tarihsel gelişim

ERP bir günde ortaya çıkmadı; üretim planlamasının adım adım genişlemesinin sonucudur.

- **Stok kontrol (1960'lar):** Sipariş noktası ve EOQ gibi istatistiksel yöntemlerle stok yönetimi.
- **MRP (Material Requirements Planning, 1960'ların sonu - 1970'ler):** Ana üretim çizelgesinden ürün ağacı yoluyla bileşen ihtiyaçlarının zamana bağlı hesaplanması. Soru basittir: "Neyi, ne kadar, ne zaman sipariş etmeliyim?"
- **MRP II (Manufacturing Resource Planning, 1980'ler):** MRP'ye kapasite planlaması, finansal planlama ve satış-operasyon planlaması eklendi. Artık yalnızca malzeme değil, makine ve işçi kapasitesi de hesaba katılıyordu.
- **ERP (1990'lar):** Üretimin ötesine geçerek finans, insan kaynakları, satış ve dağıtımı da kapsayan bütünleşik paketler. Yıl 2000 sorunu, birçok şirketi eski sistemlerini ERP ile değiştirmeye itti.
- **ERP II ve bulut (2000'ler - bugün):** Müşteri ilişkileri (CRM), tedarik zinciri (SCM) ve ürün yaşam döngüsü (PLM) ile entegrasyon; bulut tabanlı (SaaS) sunum; analitik ve yapay zekâ destekleri.

## ERP'nin sağladığı faydalar

1. **Süreç bütünlüğü:** Aynı işlem iki kez girilmez; bölümler arası kopukluk azalır.
2. **Gerçek zamanlı görünürlük:** Stok, sipariş ve maliyet bilgisi anında görülür; karar gecikmesi azalır.
3. **Standartlaşma:** Süreçler "en iyi uygulamalar" (best practice) çerçevesinde tanımlanır.
4. **Maliyet kontrolü:** Fiili maliyet ile standart maliyet karşılaştırılabilir.
5. **Denetlenebilirlik:** Her belge kimin tarafından ne zaman oluşturulduğuyla izlenir.

Aynı zamanda riskleri vardır: yüksek uygulama maliyeti, süreçleri yazılıma uydurma zorunluluğu, kullanıcı direnci ve veri kalitesi sorunları. ERP projelerinin başarısızlığının nedeni çoğu zaman teknoloji değil, yönetim desteği eksikliği, kötü veri ve yetersiz eğitimdir.

## Modüler yapı

Bir ERP paketi, ortak bir veri tabanını paylaşan modüllerden oluşur. Tipik modüller şunlardır:

| Modül | Konusu |
|---|---|
| Satın alma / Malzeme yönetimi | Talep, sipariş, mal kabul, tedarikçi |
| Satış ve dağıtım | Teklif, sipariş, sevkiyat, fatura |
| Üretim planlama | MPS, MRP, üretim emri, iş merkezi |
| Stok / depo | Stok hareketleri, sayım, depo yerleri |
| Finans ve muhasebe | Genel muhasebe, alacak/borç, varlıklar |
| Maliyet muhasebesi | Maliyet merkezleri, ürün maliyeti |
| Kalite yönetimi | Muayene planları, uygunsuzluk |
| Bakım | Planlı ve plansız bakım emirleri |
| İnsan kaynakları | Özlük, bordro, izin |

## Endüstri mühendisi için ERP'nin anlamı

Endüstri mühendisi ERP'de üç farklı rolde bulunur: (1) **süreç tasarımcısı** olarak işletmenin gerçek iş akışlarını ERP süreçleriyle eşleştirir; (2) **planlama uzmanı** olarak MRP parametrelerini (tedarik süresi, parti büyüklüğü, emniyet stoku) doğru belirler; (3) **veri sahibi** olarak ürün ağacı, rota ve iş merkezi bilgilerinin doğruluğunu sağlar. ERP bir "sihirli kutu" değildir: yanlış parametreyle çalışan MRP, yanlış siparişleri çok hızlı üretir. "Çöp girerse çöp çıkar" (garbage in, garbage out) ilkesi burada tam geçerlidir.

## Dağıtım biçimleri

- **Yerinde (on-premise):** Şirketin kendi sunucularında çalışır; özelleştirme esnektir, bakım yükü şirkettedir.
- **Bulut (SaaS):** Abonelikle kullanılır; güncellemeler sağlayıcıdan gelir; özelleştirme sınırlıdır.
- **Hibrit:** Bazı modüller yerinde, bazıları bulutta çalışır (iki katmanlı ERP).

## Sık karşılaşılan kavramlar

- **Best practice:** ERP'nin hazır sunduğu standart süreç.
- **Customizing / konfigürasyon:** Yazılımı kod yazmadan parametrelerle ayarlama.
- **Özel geliştirme (customization):** Standart olmayan ek kod; yükseltmeyi zorlaştırdığı için mümkün olduğunca az yapılır.
- **Fit-gap analizi:** İşletme ihtiyacı ile ERP'nin standart yeteneği arasındaki uyum ve boşluğun çıkarılması.
- **Master data (ana veri):** Malzeme, müşteri, tedarikçi gibi yavaş değişen temel kayıtlar.
- **Transaction data (hareket verisi):** Sipariş, mal girişi, fatura gibi günlük işlem kayıtları.

## Kısa özet

ERP, işletmenin bütün kaynaklarını tek veritabanında ve bağlı süreçlerde yöneten yazılımdır. Kökeni MRP'ye dayanır; üretimin malzeme ve kapasite planlamasından finansa kadar genişlemiştir. Endüstri mühendisi için ERP, süreç bilgisini, planlama bilgisini ve veri disiplinini birleştiren bir çalışma alanıdır. Sonraki rehberlerde süreçleri (satın alma, satış, üretim), ana verileri ve MRP mantığını ayrıntılı işleyeceğiz.
