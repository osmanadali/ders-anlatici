# ERP'de ana veri: malzeme, ürün ağacı, rota, iş merkezi

ERP'nin kalitesi, içindeki ana verinin kalitesi kadardır. **Ana veri (master data)**, yavaş değişen ve birçok işlemde tekrar tekrar kullanılan temel kayıtlardır. Üretim ve lojistikte dört kayıt grubu çok önemlidir: malzeme ana verisi, ürün ağacı (BOM), rota ve iş merkezi.

## Malzeme ana verisi (material master)

Bir malzemenin kimlik kartıdır; farklı bölümler kendi bakış açısına ait alanları doldurur ("görünümler"):

- **Temel veri:** Malzeme numarası, tanım, temel ölçü birimi, malzeme türü (hammadde, yarı mamul, mamul, ticari mal, sarf malzeme), ağırlık.
- **Satın alma:** Satın alma birimi, sorumlu satın almacı, tedarikçi bilgisi, planlanan teslim süresi.
- **MRP görünümü:** MRP türü (tüketime dayalı sipariş noktası ya da MRP), **parti büyüklüğü kuralı**, emniyet stoku, yeniden sipariş noktası, asgari ve azami parti, planlanan teslim süresi (satın alınan için) ya da iç üretim süresi.
- **Depolama:** Depo yeri, raf ömrü, parti yönetimi, seri numarası zorunluluğu.
- **Muhasebe / maliyet:** Değerleme sınıfı, **fiyat kontrolü** (standart fiyat ya da hareketli ortalama fiyat), standart maliyet.
- **Kalite:** Muayene türü ve planı.
- **Satış:** Satış birimi, fiyat grubu, vergi sınıflandırması.

**Mühendisin dikkat edeceği noktalar:** Planlanan teslim süresi ve emniyet stoku gerçek ölçümlerden güncellenmelidir. Parti büyüklüğü kuralı, ürünün özelliğine göre seçilmelidir: pahalı ve düzensiz talepte L4L; ucuz, düzenli ve çok kullanılan kalemlerde EOQ ya da sabit parti uygun olabilir. A-B-C analizi (değer bazlı) ve XYZ analizi (talep değişkenliği bazlı) bu seçimi destekler.

## Ürün ağacı (BOM, Bill of Materials)

BOM, bir mamulün hangi bileşenlerden, hangi miktarlarda oluştuğunu gösteren hiyerarşik reçetedir. Her satırda bileşen, miktar, ölçü birimi, geçerlilik tarihi, hurda payı ve bileşenin kalemi (stok kalemi, stok tutulmayan kalem, hizmet) bulunur.

- **Seviyeler:** 0. seviye mamul, 1. seviye doğrudan bileşenler, 2. seviye bunların bileşenleri… Yapı, düz bir liste değil bir ağaçtır ve ortak bileşenler birden çok yerde yer alabilir.
- **Tek seviyeli ve çok seviyeli BOM:** Çok seviyeli ağaç MRP patlatmasında tek tek dolaşılır.
- **Mühendislik BOM'u (EBOM) ve imalat BOM'u (MBOM):** Tasarım, parçaları işlevsel gruplamayla verir; imalat BOM'u ise montaj sırasına ve atölyeye göre düzenlenir. PLM sistemi EBOM'u üretir, ERP MBOM'u kullanır.
- **Varyant BOM:** Çok seçenekli ürünlerde (renk, motor, donanım) ortak yapı ve seçeneklere bağlı bileşenlerle yönetilir. Modüler (planlama) BOM, aile planlama için kullanılır.
- **Phantom (hayalî) montaj:** Fiziksel olarak stoklanmayan, yalnızca ağaçta gruplama sağlayan ara montaj; MRP bunu "şeffaf" geçer ve bileşenlerini doğrudan üst seviyeye bağlar.
- **Hurda payı:** Bileşen ihtiyacı, hurda yüzdesiyle büyütülür (net adet / (1 − hurda oranı)).

## Rota (routing, iş planı)

Rota, bir malzemenin hangi operasyonlardan, hangi sırayla ve hangi iş merkezlerinde geçerek üretileceğini tanımlar. Her operasyonda iş merkezi, **hazırlık süresi (setup)**, **birim işlem süresi** (adet başına makine ve işçilik), kontrol anahtarı (dış işlem, otomatik mal girişi, geri bildirim zorunluluğu) ve gerekirse alternatif iş merkezi bulunur. BOM'daki her bileşen, hangi operasyonda tüketileceğine atanabilir; böylece bileşen doğru zamanda atölyeye çekilir.

Rota; **üretim süresinin hesabına** (hazırlık + işlem + taşıma + bekleme), **kapasite yüküne** ve **ürün maliyetine** temel olur. Endüstri mühendisi, rotadaki süreleri zaman etüdü ve gerçekleşen üretim onaylarıyla düzenli olarak güncellemelidir.

## İş merkezi (work center)

İş merkezi, kapasitesi planlanabilen ve maliyeti toplanabilen bir üretim birimidir: bir makine, bir makine grubu, bir hat ya da bir işçi ekibi olabilir. Başlıca alanlar:

- **Kapasite:** Vardiya modeline göre günlük kullanılabilir saat (kullanım oranı ve verimlilik katsayılarıyla düzeltilmiş).
- **Maliyet merkezi bağı ve faaliyet türleri:** Makine saati, işçilik saati ve hazırlık saati gibi, saat başına ücretlendirilen faaliyetler; ürün maliyeti operasyon süresi × faaliyet tarifesi olarak hesaplanır.
- **Takvim:** Çalışma günleri, tatiller.

Kapasite hesabı: *Kullanılabilir kapasite = vardiya saati × makine sayısı × kullanım oranı × verimlilik.* Kapasite yükü, rotadaki sürelerin üretim emri miktarıyla çarpımının toplamıdır. Yük kapasiteyi aşarsa iş merkezi "aşırı yüklü"dür; çözüm olarak fazla mesai, alternatif makine, dış işlem ya da çizelge kaydırma kullanılır.

## Diğer önemli ana veriler

- **Tedarikçi ve müşteri ana verisi:** Ödeme koşulları, vergi bilgileri, sevkiyat koşulları.
- **Satın alma bilgi kaydı:** Tedarikçi-malzeme ilişkisi, fiyat, teslim süresi.
- **Depo yapısı:** Depo, depo yeri, raf; depo yönetim sistemlerinde depo tipi ve bölmeler.

## Veri yönetişimi (data governance)

Ana veriyi kimin oluşturduğu, kimin onayladığı, hangi alanın hangi bölümce bakıldığı yazılı kurallara bağlanmalıdır. Tekrarlanan malzeme kodları, tanım tutarsızlığı ve eksik ölçü birimi, ERP projelerinin en sık sorunlarıdır. Veri temizliği, geçiş (migration) projesinin en uzun ve en kritik aşamasıdır.

## Kısa özet

Malzeme ana verisi neyi, BOM neyle, rota nasıl, iş merkezi nerede ve ne kadar sürede üretileceğini söyler. MRP bu dört kaynağı birlikte okur; biri yanlışsa plan da yanlış çıkar. Endüstri mühendisi bu verilerin sahibi gibi davranmalı, parametreleri gerçek ölçümlerle beslemelidir.
