# SAP, Odoo ve ERPNext: modül eşlemesi ve karşılıklar

Piyasada üç örnek aile işimize yarar: kurumsal dünyanın referansı **SAP (ECC ve S/4HANA)**, orta ölçekte yaygın açık kaynak **Odoo** ve açık kaynak, ücretsiz kurulabilen **ERPNext**. Kavramlar benzerdir; adlar ve ekran mantığı farklıdır. Bir sistemi iyi öğrenen mühendis diğerine hızla uyum sağlar.

## SAP modül haritası

| Kısaltma | Alanı | Başlıca içerik |
|---|---|---|
| **MM** | Malzeme yönetimi | Satın alma, stok yönetimi, fatura kontrolü, malzeme ana verisi, MRP (tüketime dayalı planlama dahil) |
| **PP** | Üretim planlama | MPS, MRP, BOM, rota, iş merkezi, üretim emri, kapasite planlama, kanban |
| **SD** | Satış ve dağıtım | Satış siparişi, fiyatlama, sevkiyat, faturalama |
| **WM / EWM** | Depo yönetimi | Depo yerleri, toplama ve yerleştirme, genişletilmiş depo yönetimi |
| **QM** | Kalite yönetimi | Muayene planı, muayene lotu, kullanım kararı |
| **PM** | Bakım | Ekipman, bakım emri, bakım planı |
| **FI** | Finansal muhasebe | Genel muhasebe, alacak/borç hesapları, varlık muhasebesi |
| **CO** | Maliyet muhasebesi | Maliyet merkezi, sipariş maliyeti, ürün maliyetleme, kâr merkezi |
| **HCM / HR** | İnsan kaynakları | Özlük, zaman yönetimi, bordro |
| **PS** | Proje sistemi | Proje yapısı, ağ planı, bütçe |

SAP'de entegrasyonun en güzel örneği, mal kabul hareketinin hem **MM** stoğunu hem **FI** muhasebesini hem de **CO** maliyetini aynı anda güncellemesidir. Planlayıcıların yaygın kullandığı işlem kodları: MD04 (stok/ihtiyaç listesi), MD01/MD02 (MRP çalıştırma), CO01 (üretim emri açma), MM01 (malzeme ana verisi), ME21N (satın alma siparişi), MIGO (mal hareketi), VA01 (satış siparişi). S/4HANA'da bellek içi veritabanı sayesinde MRP gerçek zamanlıya yakın çalışır ve ekranlar Fiori uygulamalarına taşınmıştır.

## Odoo modülleri

Odoo "uygulamalar (apps)" mantığıyla çalışır: Satın Alma (Purchase), Satış (Sales), Envanter (Inventory), Üretim (Manufacturing, MRP), Muhasebe (Accounting), Kalite, Bakım, Proje, İnsan Kaynakları ve e-ticaret. Üretim uygulamasında **Malzeme Listesi (Bill of Materials)**, **İş Merkezleri (Work Centers)**, **Rotalar (Operations)** ve **Üretim Emirleri (Manufacturing Orders)** bulunur. Planlama tarafında **Yeniden Sipariş Kuralları (reordering rules: min-max)** ve **Tedarik Planlayıcı (scheduler)** vardır: talep doğunca, sistem "tedarik rotalarına" (satın al, üret, depodan transfer et) göre otomatik talep ya da emir üretir. Odoo'da tam kapsamlı çok seviyeli MRP hesabı, SAP kadar ayrıntılı parti büyüklüğü seçenekleri sunmaz; çoğu iş akışı min-max kuralı ve "siparişe göre üret/ stoğa üret" seçimiyle yürür.

## ERPNext modülleri

ERPNext, Frappe çerçevesi üzerine kuruludur: Muhasebe (Accounts), Satın Alma (Buying), Satış (Selling), Stok (Stock), Üretim (Manufacturing), Varlıklar, Projeler, Kalite, İK. Üretimde **BOM**, **İş İstasyonu (Workstation)**, **Operasyon**, **İş Emri (Work Order)**, **Üretim Planı (Production Plan)** ve **Malzeme Talebi (Material Request)** belgeleri bulunur. Üretim Planı, satış siparişlerinden ve tahminlerden ihtiyaç hesaplayıp ham madde talebi ve iş emri önerir; bu, MRP'nin sade bir karşılığıdır.

## Kavram eşlemesi

| Kavram | SAP | Odoo | ERPNext |
|---|---|---|---|
| Malzeme ana verisi | Malzeme ana kaydı (MM01) | Ürün (Product) | Kalem (Item) |
| Ürün ağacı | BOM (CS01) | Malzeme Listesi | BOM |
| İş merkezi | İş merkezi (CR01) | İş merkezi | İş istasyonu |
| Rota | Rota (CA01) | Operasyonlar | Operasyon / BOM operasyonları |
| Üretim emri | Üretim siparişi (CO01) | Üretim emri (MO) | İş emri (Work Order) |
| Satın alma siparişi | ME21N | Satın alma siparişi (RFQ/PO) | Satın alma siparişi |
| Mal kabul | MIGO (101 hareketi) | Teslim alma (Receipt) | Satın alma makbuzu |
| Satış siparişi | VA01 | Satış siparişi | Satış siparişi |
| Stok hareketi | Malzeme belgesi | Stok hareketi | Stok girişi |
| MRP çalıştırma | MD01 / MD02 | Zamanlayıcı + yeniden sipariş kuralı | Üretim planı / Malzeme talebi |

## Seçim ölçütleri

- **SAP:** Büyük ve karmaşık işletmeler; çok kuruluşlu, çok ülkeli yapılar; sıkı yetkilendirme ve denetim ihtiyacı; yüksek lisans ve danışmanlık maliyeti.
- **Odoo:** Hızlı kurulum, modern arayüz, orta ölçek; modül bazlı fiyatlama; topluluk ve kurumsal sürüm farkı.
- **ERPNext:** Ücretsiz ve tamamen açık kaynak, küçük işletmeler, öğrenme ve eğitim ortamı için uygun; kendi sunucunda kurulabilir.

Eğitim amacıyla ERPNext ya da Odoo topluluk sürümü bilgisayarına kurulup denenebilir; SAP için eğitim ortamlarına üniversite programları (SAP Üniversite İttifakları) üzerinden erişilir.

## Öğrenme yolu önerisi

1. Önce kavramı öğren: MRP mantığı, P2P, O2C. 2. Bir sistemde bir senaryoyu baştan sona yap: malzeme oluştur, BOM kur, iş merkezi tanımla, satış siparişi gir, MRP çalıştır, üretim emri aç, mal girişi yap. 3. Aynı senaryoyu ikinci sistemde tekrar et; eşlemeyi kendin çıkar.

## Kısa özet

SAP'de MM, PP, SD, FI/CO, WM; Odoo'da uygulamalar; ERPNext'te modüller aynı iş sürecini farklı adlarla çözer. Asıl beceri, ekran bilgisi değil, arkasındaki süreç ve veri mantığını bilmektir.
