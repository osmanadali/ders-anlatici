# ERP'de stok yönetimi, depo ve maliyet

Stok, ERP'nin hem fiziksel hem mali omurgasıdır: her mal hareketi stok miktarını ve stok değerini birlikte değiştirir. Bu rehber stok hareketlerini, stok denetim yöntemlerini, depo yönetimini ve ürün maliyetinin ERP'de nasıl hesaplandığını özetler.

## Stok hareketleri

Her hareket bir **hareket türü** ile ifade edilir ve miktar ile değeri etkiler:

- **Mal girişi (satın almadan, üretimden):** Stoku artırır.
- **Mal çıkışı (satışa, üretime tüketim):** Stoku azaltır.
- **Depolar arası transfer:** Toplam stok değişmez, yer değişir.
- **Stok düzeltmesi (sayım farkı, fire, imha):** Fark kaydı; muhasebede stok farkı hesabına yansır.
- **İade:** Tedarikçiye iade ya da müşteriden iade.

Her hareketin bir **belgesi** olur; mevcut stok, bu belgelerin toplamıdır. Bu nedenle stok doğruluğu için "kayıt dışı" depo hareketi yapılmaması çok önemlidir.

## Stok durumları

Aynı malzeme stokta farklı durumlarda bulunabilir: **serbest kullanım** (kullanılabilir), **kalite kontrolde** (muayene bekleyen), **bloke** (hasarlı, tartışmalı), **transfer yolunda**, **müşteri/tedarikçi konsinye** stoğu. MRP yalnızca serbest kullanım (ve isteğe bağlı kalite) stokunu net ihtiyaç hesabında kullanır.

## Parti ve seri takibi

- **Parti (lot/batch) yönetimi:** Aynı üretim grubuna ait mallar aynı parti numarasıyla izlenir; gıda, ilaç, kimya gibi sektörlerde son kullanma tarihi (raf ömrü) takibi ve geri çağırma için şarttır. İlk giren ilk çıkar (FIFO) ya da ilk son kullanma ilk çıkar (FEFO) stratejileri uygulanır.
- **Seri numarası:** Her parçanın tekil numarası olur; garanti ve izlenebilirlik için kullanılır.

## Stok denetimi ve sayım

Stok kayıtları ile fiziksel stok farklı çıkabilir. İki sayım yaklaşımı vardır: **yıllık envanter sayımı** (tüm depo kapatılır) ve **döngüsel sayım (cycle counting)**: ürünler ABC sınıflarına göre farklı sıklıkta sayılır (A sınıfı sık, C sınıfı seyrek). Döngüsel sayım, hataların kaynağını da bulmaya yarar. MRP'nin güvenilir olması için kayıt doğruluğunun yüksek olması gerekir.

## Stok kontrol politikaları ve ERP parametreleri

ERP'deki malzeme parametreleri aslında klasik stok kontrol modellerinin uygulamasıdır:

- **Yeniden sipariş noktası (ROP):** Stok bu seviyeye düşünce sipariş verilir: ROP = tedarik süresi talebi + emniyet stoku. Tüketime dayalı planlama bunu kullanır.
- **Emniyet stoku:** Talep ve tedarik süresi belirsizliğine karşı tampon; normal dağılım varsayımıyla emniyet stoku = z × σ(tedarik süresi talebi), z servis düzeyine bağlıdır (örneğin %95 için yaklaşık 1,645).
- **EOQ:** √(2DS/H); D yıllık talep, S sipariş maliyeti, H birim başına yıllık stok tutma maliyeti.
- **Min-max (s, S):** Stok s'nin altına düşünce S düzeyine tamamlayacak kadar sipariş verilir.
- **ABC analizi:** Yıllık kullanım değeri baz alınarak A (yaklaşık %80 değer, %20 kalem), B, C sınıfları; sınıfa göre kontrol sıkılığı belirlenir.

**Stok devir hızı** = yıllık satılan malın maliyeti / ortalama stok değeri. **Stokta kalma günü** = 365 / devir hızı.

## Depo yönetimi (WM, EWM, WMS)

Temel stok modülü yalnızca "hangi depoda, ne kadar" bilgisini tutar. **Depo yönetim sistemi (WMS)** daha da ayrıntıya iner: depo, koridor, raf, göz; yerleştirme stratejileri (sabit yer, rastgele yer, yakın yer); toplama stratejileri (parti toplama, dalga toplama, bölge toplama); el terminali ve barkodla doğrulama. Amaç, depo içi taşıma mesafesini ve süresini azaltmak, toplama hatasını düşürmektir. Endüstri mühendisliği perspektifi: depo yerleşimi, ürün konumlandırma (hızlı dönen ürünler çıkışa yakın), toplama rotası optimizasyonu.

## Maliyet hesabı

**Stok değerleme yöntemleri:**
- **Standart fiyat:** Dönem başında belirlenen sabit fiyatla değerleme; gerçek fiyat farkı ayrı bir fiyat farkı hesabında görünür. Planlı maliyet kontrolüne uygundur.
- **Hareketli ortalama fiyat:** Her mal girişinde ortalama fiyat yeniden hesaplanır. Fiyatı dalgalı kalemlerde tercih edilir.
- **FIFO:** İlk giren maliyeti ilk çıkar (bazı sistemlerde yalnızca muhasebe düzeyinde).

**Ürün maliyetleme (product costing):** Bir mamulün standart maliyeti ERP'de BOM ve rotadan türetilir:

*Malzeme maliyeti* = Σ bileşen miktarı × bileşen birim maliyeti
*İşçilik ve makine maliyeti* = Σ operasyon süresi × faaliyet tarifesi (saatlik)
*Genel üretim giderleri* = tarife ya da dağıtım anahtarıyla eklenir

Toplam = malzeme + işçilik/makine + genel üretim gideri. Bu "maliyet tablosu" bir **maliyet kalemi yapısında** (örneğin hammadde, işçilik, genel gider) tutulur.

**Sipariş maliyeti ve sapma analizi:** Üretim emri kapandığında gerçek maliyet (tüketilen malzeme ve onaylanan saat) ile standart maliyet karşılaştırılır; fark **miktar sapması** (daha fazla malzeme ya da süre kullanıldı) ve **fiyat sapması** (daha pahalı alındı) olarak ayrıştırılır. Mühendis sapmanın nedenini arar: hatalı rota süresi, hurda, verimsizlik ya da fiyat artışı.

**Maliyet merkezleri ve faaliyet tabanlı maliyetleme (ABC):** Genel giderler maliyet merkezlerinde toplanır, faaliyet sürücüleri (makine saati, hazırlık sayısı gibi) ile ürünlere dağıtılır.

## Muhasebe entegrasyonu

Mal girişi: Stok (borç) / mal kabul geçici hesabı (alacak). Fatura: Mal kabul geçici hesabı (borç) / satıcılar (alacak). Satış çıkışı: Satılan malın maliyeti (borç) / stok (alacak). Bu otomatik hesap belirleme, malzeme türüne bağlı "değerleme sınıfı" ile yapılır.

## Kısa özet

Stok hareketleri hem fiziksel hem mali kayıtları aynı anda günceller. ROP, emniyet stoku, EOQ ve ABC analizi ERP'de parametre olarak karşılık bulur. Ürün maliyeti BOM ve rotadan hesaplanır; sapma analizi mühendisin süreç iyileştirmesi için en kıymetli veridir.
