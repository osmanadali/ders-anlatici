# ERP uygulama projesi: aşamalar, roller ve riskler

ERP projeleri bir yazılım kurulumundan çok bir **kurumsal değişim projesidir**. Süreçler, roller ve alışkanlıklar değişir. Bu nedenle başarı, teknik beceri kadar proje yönetimi ve değişim yönetimine bağlıdır. Bu rehber klasik projenin aşamalarını ve endüstri mühendisinin rolünü özetler.

## 1. Hazırlık ve seçim

- **İhtiyaç analizi ve hedefler:** Neyi çözmek istiyoruz? (stok doğruluğu, teslim süresi, raporlama, mevzuat uyumu). Ölçülebilir hedefler konur: örneğin stok devir hızını 6'dan 9'a çıkarmak.
- **Mevcut durum (as-is) süreç analizi:** Süreç haritaları çıkarılır (akış şemaları, BPMN). Endüstri mühendisinin güçlü olduğu alan budur.
- **Yazılım ve iş ortağı seçimi:** Teklif talebi (RFP), fit-gap değerlendirmesi, demolar, referans ziyaretleri, **toplam sahip olma maliyeti (TCO)**: lisans, danışmanlık, donanım/bulut, eğitim, bakım, 5-7 yıllık dönem.
- **Proje yapısı:** Yönlendirme komitesi, proje yöneticisi, süreç sahipleri (satın alma, üretim, finans…), anahtar kullanıcılar, danışman ekibi.

## 2. Tasarım (blueprint / gelecek durum)

- **To-be süreç tasarımı:** İşletmenin süreçleri ERP standart süreçleriyle eşleştirilir. Mümkün olduğunca standardı benimsemek, özelleştirmeyi azaltır.
- **Fit-gap analizi:** Karşılanan ihtiyaçlar, konfigürasyonla karşılananlar, özel geliştirme gerektirenler, süreç değiştirilerek giderilenler listelenir.
- **Organizasyon yapısı:** Şirket kodu, fabrika, depo, satın alma organizasyonu gibi yapıların tasarımı; bu yapı sonradan değiştirmesi zor temel karardır.
- **Ana veri tasarımı:** Malzeme kodlama standardı, BOM ve rota derinliği, ölçü birimleri.
- **Yetki ve görev ayrımı:** Bir kişi hem sipariş oluşturup hem onaylayamaz.

## 3. Konfigürasyon ve geliştirme

Parametrelerin ayarlanması, raporlar, formlar, arayüzler (entegrasyon: bankalar, e-fatura, e-irsaliye, üretim sahası sistemleri) ve gerektiğinde özel geliştirmeler. Kural: önce standart, sonra konfigürasyon, en son geliştirme.

## 4. Veri geçişi (migration)

Eski sistemden ana veri ve açık hareketlerin (açık sipariş, açılış stokları, açılış bakiyeleri) aktarılması. Adımlar: veri temizliği → eşleme (mapping) → dönüştürme → yükleme → doğrulama (sayım ve mutabakat). Projelerin en çok zaman alan ve en sık geciken aşamasıdır; veri sahipleri işe erken alınmalıdır.

## 5. Test

- **Birim testi:** Tek fonksiyon ya da konfigürasyon.
- **Entegrasyon (süreç) testi:** Uçtan uca senaryo: satın alma talebinden ödemeye, satış siparişinden tahsilata, MRP'den üretim emrine.
- **Kullanıcı kabul testi (UAT):** İş kullanıcıları gerçek senaryoları dener ve onaylar.
- **Performans ve yük testi:** Gece MRP çalıştırması, yoğun saat işlemleri.

## 6. Eğitim ve değişim yönetimi

Son kullanıcı eğitimi, el kitapları, simülasyon ortamında alıştırma. Değişim yönetimi: iletişim planı, direnç yönetimi, "şampiyon kullanıcılar". Eğitimsiz geçiş, en yaygın başarısızlık nedenlerinden biridir.

## 7. Canlıya geçiş (go-live) stratejileri

| Strateji | Açıklama | Risk |
|---|---|---|
| **Big bang** | Tüm modüller ve birimler aynı anda geçer | Yüksek risk, kısa süre |
| **Aşamalı (phased)** | Modül modül ya da fabrika fabrika geçilir | Daha az risk, uzun süre, geçici arayüzler |
| **Paralel çalışma** | Eski ve yeni sistem bir süre birlikte | Çift iş yükü, güvenli |
| **Pilot** | Önce bir birimde denenir | Öğrenme fırsatı |

Geçiş öncesi **go/no-go** kontrol listesi, geçiş hafta sonu planı ve geri dönüş (rollback) planı hazırlanır.

## 8. Canlı destek ve sürekli iyileştirme

İlk haftalar yoğun destek (hypercare); destek masası, değişiklik talebi yönetimi, düzenli sürüm güncellemeleri, kullanıcı geri bildirimi, süreç performans göstergelerinin izlenmesi. ERP bitmiş bir iş değil, sürekli gelişen bir platformdur.

## Başarı ve başarısızlık faktörleri

**Başarı faktörleri:** Üst yönetim desteği, net kapsam, iyi veri, deneyimli proje yöneticisi, süreç sahiplerinin katılımı, gerçekçi takvim, yeterli eğitim.

**Başarısızlık nedenleri:** Kapsamın sürekli genişlemesi (scope creep), aşırı özelleştirme, veri kalitesinin ihmali, kullanıcı katılımının zayıflığı, projenin "BT projesi" sanılması, gerçekçi olmayan süre ve bütçe.

## Endüstri mühendisinin rolleri

- **Süreç analisti:** As-is/to-be süreç haritaları, darboğaz analizi, gereksinim toplama.
- **Planlama ve üretim danışmanı:** MRP parametrelerinin (tedarik süresi, emniyet stoku, parti kuralı) belirlenmesi ve doğrulanması.
- **Ana veri yöneticisi:** BOM, rota ve iş merkezi verilerinin doğruluğu.
- **Test sorumlusu / anahtar kullanıcı:** Senaryo tasarımı ve kabul.
- **Proje yöneticisi:** Takvim, bütçe, risk (PERT/CPM, kazanılmış değer analizi).
- **Sonrası:** KPI izleme, sürekli iyileştirme, yalın ve Altı Sigma projeleriyle ERP verisini kullanarak israfı azaltma.

## Projelerde sık kullanılan ölçütler

- Bütçe ve takvim sapması, kritik hata sayısı, kullanıcı kabul oranı, veri geçişi doğruluğu (%), canlıya geçiş sonrası destek taleplerinin zamanla düşmesi.
- Hedefe ulaşma: stok devir hızı, zamanında teslim oranı, kapanış süresi (günler), planlama çevrim süresi.

## Kısa özet

ERP projesi hazırlık-seçim, tasarım, konfigürasyon, veri geçişi, test, eğitim, canlıya geçiş ve iyileştirme aşamalarından geçer. Teknik taraf kadar insan ve veri tarafı da belirleyicidir; endüstri mühendisi süreç ve planlama bilgisiyle projenin merkezinde yer alır.
