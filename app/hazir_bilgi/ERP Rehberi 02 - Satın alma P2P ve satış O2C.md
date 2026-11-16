# Temel ERP süreçleri: Satın alma (P2P) ve satış (O2C)

ERP'yi anlamanın en iyi yolu, bir belgenin başlangıcından muhasebeleşmesine kadar izlediği yolu takip etmektir. İki klasik zincir vardır: **Procure to Pay (P2P, satın almadan ödemeye)** ve **Order to Cash (O2C, siparişten tahsilata)**.

## Procure to Pay (P2P)

Hammadde, yardımcı malzeme ya da hizmet temin etmenin ERP'deki adımları:

1. **İhtiyacın doğması:** Ya MRP planlı sipariş önerisi üretir ya da bir kullanıcı elle **satın alma talebi (purchase requisition)** açar.
2. **Tedarikçi seçimi ve teklif:** Talep onaylanır; gerekirse birden çok tedarikçiden teklif alınır (RFQ, request for quotation) ve karşılaştırılır.
3. **Satın alma siparişi (purchase order, PO):** Seçilen tedarikçiye miktar, fiyat, teslim tarihi ve ödeme koşullarıyla sipariş verilir. Sipariş, açık bir taahhüttür ve "beklenen girişler" olarak MRP'ye geri beslenir.
4. **Mal kabul (goods receipt, GR):** Mal depoya geldiğinde sipariş referansıyla girilir. Bu işlem stok miktarını artırır; muhasebede genellikle "stok" hesabı borçlanır, "mal kabul / fatura alınmamış mal" geçici hesabı alacaklanır.
5. **Fatura kontrolü (invoice verification):** Tedarikçi faturası geldiğinde **üç yönlü eşleştirme (three-way match)** yapılır: sipariş, mal kabul ve fatura miktar ve fiyat bakımından uyuşmalıdır. Uyuşmazlıkta fatura bloke edilir.
6. **Ödeme:** Vadesi gelen borç ödenir; tedarikçi hesabı kapanır.

**Mühendis gözüyle kritik noktalar:** (a) tedarik süresi (sipariş verilmesinden mal kabule kadar geçen süre) MRP'nin en hassas parametrelerinden biridir; gerçekte ölçülen süre ile ana veriye girilen süre ayrışırsa sistem sürekli geç ya da erken sipariş önerir. (b) Sipariş miktarını belirleyen parti büyüklüğü kuralı (L4L, EOQ, sabit miktar, minimum sipariş miktarı) doğrudan stok maliyetini belirler. (c) Tedarikçi performansı (zamanında teslim, kalite) sistemden raporlanabilir ve tedarikçi değerlendirmesine girdi olur.

## Order to Cash (O2C)

Müşteriden gelen talebin paraya dönüşmesi:

1. **Müşteri talebi ve teklif (inquiry, quotation):** Fiyat ve teslim tarihi sözü verilir.
2. **Satış siparişi (sales order):** Müşteri siparişi sisteme girilir. ERP burada **stok uygunluğu kontrolü (availability check, ATP: Available to Promise)** yapar: istenen tarihte yeterli stok ya da üretim kapasitesi var mı?
3. **Planlama:** Stokta yoksa sipariş, ana üretim çizelgesine ya da satın almaya talep olarak yansır (MTS/MTO ayrımı: stoğa üretim ya da siparişe üretim).
4. **Sevkiyat (delivery):** Depoda toplama (picking), paketleme ve yükleme yapılır; **mal çıkışı (goods issue)** stoku azaltır ve maliyeti stoktan satılan malın maliyetine taşır.
5. **Faturalama (billing):** Müşteriye fatura kesilir; alacak ve gelir kaydı oluşur.
6. **Tahsilat (payment receipt):** Müşteri ödemesi alacağı kapatır.

**Mühendis gözüyle kritik noktalar:** ATP mantığı, müşteriye verilen teslim sözünün güvenilirliğini belirler. Müşteri talebinin tahmin hatası, emniyet stoku ve stok devir hızıyla doğrudan ilişkilidir. Teslim süresi kısaldıkça rekabet gücü artar, fakat stok maliyeti de artabilir; bu denge endüstri mühendisliğinin klasik ödünleşimlerindendir.

## Belge akışı ve izlenebilirlik

ERP'de her adım bir belge üretir ve belgeler birbirine bağlanır: talep → sipariş → mal kabul → fatura. Bu "belge akışı" sayesinde bir faturadan başlayarak siparişe ve talebe geri gidilebilir (geriye doğru izlenebilirlik). Denetimde ve hata ayıklamada en önemli araçlardan biridir.

## Süreç performans göstergeleri

- P2P: sipariş çevrim süresi, tedarikçi zamanında teslim oranı, fatura eşleşme hata oranı, ortalama ödeme günü.
- O2C: sipariş karşılama oranı (fill rate), zamanında ve eksiksiz teslim (OTIF), alacak tahsil süresi (DSO), iade oranı.

## Sık görülen sorunlar

- **Serbest metinli, onaysız talepler:** Ana veride tanımlı olmayan malzemeler için "serbest kalem" açılması maliyet analizini bozar.
- **Mal kabulsüz fatura:** Mal gelmeden fatura işlemi muhasebe-stok uyumsuzluğu yaratır.
- **Gecikmeli mal çıkışı girişi:** Fiziksel sevkiyat yapılmış ama sistemde işlenmemişse stok yüksek görünür, MRP gereksiz sipariş vermez ya da eksik görür.
- **Birim dönüşümleri:** Satın alma birimi (koli) ile stok birimi (adet) arasındaki dönüşüm hatası büyük stok farklarına yol açar.

## Kısa özet

P2P zinciri ihtiyacı satın alma talebine, siparişe, mal kabule, faturaya ve ödemeye çevirir. O2C zinciri müşteri siparişini stok kontrolü, sevkiyat, fatura ve tahsilata taşır. İkisinde de fiziksel hareket (mal giriş-çıkış) ile mali kayıt eş zamanlı oluşur; endüstri mühendisi tedarik süresi, parti büyüklüğü ve stok seviyesi parametrelerinin doğruluğundan sorumludur.
