"""ERP alıştırması: rastgele (ama tohumdan yeniden üretilebilir) MRP senaryosu.

Senaryo kimliği tohumu taşır; çözüm istemciye gönderilmez, kontrol sırasında sunucuda yeniden hesaplanır.
Öğrenci her kalem için haftalık NET İHTİYAÇ satırını doldurur; hesap.mrp_patlat ile karşılaştırılır.
"""
from __future__ import annotations

import random
import re

from . import hesap

ADLAR = {"A": "Mamul A", "B": "Alt montaj B", "C": "Alt montaj C", "D": "Parça D", "E": "Parça E"}


def _kur(kimlik: str) -> tuple[hesap.MRPGirdi, dict]:
    m = re.fullmatch(r"s(\d{1,9})-([12])", kimlik or "")
    if not m:
        raise ValueError("Geçersiz alıştırma kimliği")
    seed, seviye = int(m.group(1)), int(m.group(2))
    r = random.Random(seed)
    T = r.choice([6, 7, 8])
    bom = [hesap.MRPBilesen(ust="A", bilesen="B", adet=r.randint(1, 2)), hesap.MRPBilesen(ust="A", bilesen="C", adet=r.randint(1, 3))]
    if seviye == 2:
        bom += [hesap.MRPBilesen(ust="B", bilesen="D", adet=r.randint(1, 3)),
                hesap.MRPBilesen(ust="C", bilesen="D", adet=r.randint(1, 2)),
                hesap.MRPBilesen(ust="C", bilesen="E", adet=r.randint(1, 2))]
    kalemler = ["A", "B", "C"] + (["D", "E"] if seviye == 2 else [])
    # ana üretim çizelgesi: ilk 2 hafta boş, geri kalanında ~%60 dolu, 5'in katları
    mps = [0.0, 0.0] + [float(r.choice([10, 20, 30, 40])) if r.random() < 0.75 else 0.0 for _ in range(T - 2)]
    if not any(mps):
        mps[T - 1] = 20.0
    foq_kalem = r.choice(kalemler[1:])
    mal = []
    for k in kalemler:
        parti, q = "L4L", 0.0
        if k == foq_kalem:
            parti, q = "FOQ", float(r.choice([40, 50, 60]))
        mal.append(hesap.MRPMalzeme(
            ad=k, stok=float(r.choice([0, 5, 10, 20, 30] if k != "A" else [0, 0, 10])), tedarik_suresi=r.choice([1, 1, 2]) if k != "A" else 1,
            parti=parti, parti_miktari=q,
            planlanan_alimlar=({str(r.randint(1, 3)): float(r.choice([10, 20]))} if r.random() < 0.4 and k != "A" else {})))
    return hesap.MRPGirdi(urun="A", ana_cizelge=mps, bom=bom, malzemeler=mal), {"T": T}


def yeni(tohum: int | None = None, seviye: int = 2) -> dict:
    """Çözümsüz senaryo: öğrenciye gösterilecek her şey."""
    if seviye not in (1, 2):
        seviye = 2
    tohum = tohum if tohum is not None else random.randint(1, 999_999)
    kimlik = f"s{int(tohum) % 1_000_000_000}-{seviye}"
    g, bilgi = _kur(kimlik)
    sev = {"A": 0}
    for b in g.bom:
        sev[b.bilesen] = max(sev.get(b.bilesen, 0), sev[b.ust] + 1) if b.ust in sev else 1
    for _ in range(2):  # ikinci geçiş: D, C'nin altında 2. seviyede kalsın
        for b in g.bom:
            sev[b.bilesen] = max(sev.get(b.bilesen, 0), sev.get(b.ust, 0) + 1)
    return {
        "id": kimlik, "hafta_sayisi": bilgi["T"], "urun": "A", "ana_cizelge": g.ana_cizelge,
        "bom": [b.model_dump() for b in g.bom],
        "kalemler": [{"ad": m.ad, "tanim": ADLAR.get(m.ad, m.ad), "seviye": sev.get(m.ad, 0), "stok": m.stok,
                      "tedarik_suresi": m.tedarik_suresi, "parti": m.parti, "parti_miktari": m.parti_miktari,
                      "planlanan_alimlar": m.planlanan_alimlar} for m in g.malzemeler],
        "gorev": ("Her kalem için haftalık NET İHTİYAÇ satırını doldur. Net ihtiyaç = brüt ihtiyaç − (elde stok + beklenen alım), "
                  "negatifse 0. Bileşenlerin brüt ihtiyacı, üst kalemin planlanan sipariş ÇIKIŞINDAN (tedarik süresi kadar öne çekilmiş) gelir. "
                  "FOQ kalemde sipariş, sabit miktarın katları olarak verilir; fazlası stoğa gider. Tablo boşsa 0 yaz."),
    }


def cozum(kimlik: str) -> dict:
    g, _ = _kur(kimlik)
    return hesap.mrp_patlat(g).sayilar["plan"]


def kontrol(kimlik: str, cevap: dict) -> dict:
    """cevap: {kalem: [hafta1, hafta2, ...]} → hücre hücre doğru/yanlış, puan ve açıklama."""
    g, bilgi = _kur(kimlik)
    T = bilgi["T"]
    s = hesap.mrp_patlat(g)
    plan = s.sayilar["plan"]
    dogru, toplam, puan, yanlis_kalem = {}, 0, 0, []
    for ad, p in plan.items():
        satir = (cevap or {}).get(ad) or []
        ok = []
        for t in range(T):
            try:
                v = float(satir[t]) if t < len(satir) and satir[t] not in (None, "") else None
            except (TypeError, ValueError):
                v = None
            ok.append(v is not None and abs(v - p["net"][t]) < 0.01)
        dogru[ad] = ok
        toplam += T
        puan += sum(ok)
        if not all(ok):
            yanlis_kalem.append(ad)
    aciklama = []
    for ad in yanlis_kalem:
        p = plan[ad]
        aciklama.append(f"{ADLAR.get(ad, ad)}: brüt {p['brut']} → net {p['net']}; planlanan sipariş çıkışı {p['planlanan_siparis_cikisi']}. "
                        f"Net = brüt + emniyet − (elde stok + beklenen alım); ardından sipariş çıkışı tedarik süresi kadar öne alınır.")
    if not yanlis_kalem:
        aciklama.append("Tebrikler: bütün hücreler doğru. Şimdi parti kuralını değiştirip (L4L, EOQ, Silver-Meal) toplam maliyete etkisini düşün.")
    return {"id": kimlik, "dogru": dogru, "puan": puan, "toplam": toplam, "tamam": puan == toplam,
            "cozum": {a: p["net"] for a, p in plan.items()}, "adimlar": s.adimlar, "aciklama": aciklama}
