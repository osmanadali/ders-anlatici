"""Hesap araçlarının sonuçlarını Excel (.xlsx, formüllü / Solver'a hazır) ve çalıştırılabilir Python (.py) olarak üretir."""
from __future__ import annotations

import io
import json
import pprint
from typing import Any

from openpyxl.styles import Font

from . import hesap

# Arayüzde "Örnek yükle" için geçerli girdiler (testte hepsi çalıştırılır)
ORNEKLER: dict[str, dict] = {
    "dogrusal_programlama": {"amac": "max", "c": [3, 5], "A_ub": [[1, 0], [0, 2], [3, 2]], "b_ub": [4, 12, 18], "degisken_adlari": ["x1", "x2"]},
    "ulastirma": {"arz": [20, 30, 25], "talep": [10, 25, 15, 25], "maliyet": [[8, 6, 10, 9], [9, 12, 13, 7], [14, 9, 16, 5]]},
    "atama": {"maliyet": [[9, 2, 7, 8], [6, 4, 3, 7], [5, 8, 1, 8], [7, 6, 9, 4]], "amac": "min"},
    "johnson": {"isler": [[3, 6], [5, 2], [1, 2], [6, 6], [7, 5]]},
    "tek_makine": {"kural": "SPT", "sureler": [6, 2, 8, 3], "teslim": [9, 5, 20, 8]},
    "cpm": {"faaliyetler": [{"ad": "A", "sure": 3, "onculler": []}, {"ad": "B", "sure": 4, "onculler": ["A"]}, {"ad": "C", "sure": 2, "onculler": ["A"]},
                            {"ad": "D", "sure": 5, "onculler": ["B", "C"]}]},
    "eoq": {"talep_yillik": 12000, "siparis_maliyeti": 100, "elde_tutma": 6, "birim_maliyet": 20, "gun_sayisi": 300, "tedarik_gun": 5,
            "gunluk_ss": 6, "servis_duzeyi": 0.95},
    "kuyruk": {"lam": 8, "mu": 5, "c": 2},
    "simulasyon": {"lam": 4, "mu": 5, "musteri": 5000, "tohum": 1},
    "kontrol_karti": {"tip": "xbar_r", "alt_gruplar": [[5.02, 5.01, 4.94, 4.99, 4.96], [5.01, 5.03, 5.07, 4.95, 4.96], [4.99, 5.00, 4.93, 4.92, 4.99],
                                                       [5.03, 4.91, 5.01, 4.98, 4.89], [4.95, 4.92, 5.03, 5.05, 5.01]]},
    "yeterlilik": {"LSL": 9.0, "USL": 11.0, "ortalama": 10.1, "sigma": 0.25},
    "istatistik": {"veri": [12.1, 11.8, 12.4, 12.0, 11.9, 12.3], "guven": 0.95, "mu0": 12.0},
    "ogrenme_egrisi": {"t1": 100, "oran": 0.8, "n": 8},
    "basabas": {"sabit_maliyet": 50000, "birim_fiyat": 25, "birim_degisken_maliyet": 15, "hedef_kar": 10000},
    "nbd_igo": {"nakit_akislari": [-10000, 3000, 4000, 5000, 3000], "faiz": 0.1},
    "mrp": {"urun": "A", "ana_cizelge": [0, 0, 0, 0, 40, 0, 0, 60], "bom": [{"ust": "A", "bilesen": "B", "adet": 2}, {"ust": "A", "bilesen": "C", "adet": 1}],
            "malzemeler": [{"ad": "A", "stok": 10, "tedarik_suresi": 1}, {"ad": "B", "stok": 20, "tedarik_suresi": 2, "parti": "FOQ", "parti_miktari": 100},
                           {"ad": "C", "stok": 5, "tedarik_suresi": 1}]},
}


# ================================================================ Excel
def _stiller():
    from openpyxl.styles import Alignment, Font, PatternFill

    return (Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="0F9B84"), PatternFill("solid", fgColor="FFF2CC"),
            Font(bold=True, size=14), Alignment(wrap_text=True, vertical="top"))


def _duz(x: Any, on: str = "") -> list[tuple[str, Any]]:
    """İç içe girdiyi (anahtar, değer) satırlarına açar."""
    if isinstance(x, dict):
        out = []
        for k, v in x.items():
            out += _duz(v, f"{on}.{k}" if on else str(k))
        return out
    if isinstance(x, list) and x and all(isinstance(i, (int, float)) for i in x):
        return [(on, ", ".join(str(i) for i in x))]
    if isinstance(x, list):
        out = []
        for i, v in enumerate(x):
            out += _duz(v, f"{on}[{i + 1}]")
        return out
    return [(on, x)]


def _harf(i: int) -> str:
    from openpyxl.utils import get_column_letter

    return get_column_letter(i)


def _baslik_satiri(ws, satir: int, degerler: list, f, fill, kol0: int = 1) -> None:
    for j, v in enumerate(degerler):
        c = ws.cell(satir, kol0 + j, v)
        c.font, c.fill = f, fill


def _girdi_sonuc_sayfalari(wb, arac: str, girdi: dict, sonuc: hesap.Sonuc) -> None:
    hf, hfill, _, _, wrap = _stiller()
    ws = wb.create_sheet("Girdiler")
    _baslik_satiri(ws, 1, ["Girdi", "Değer"], hf, hfill)
    for i, (k, v) in enumerate(_duz(girdi), 2):
        ws.cell(i, 1, k)
        ws.cell(i, 2, v if isinstance(v, (int, float, str)) or v is None else str(v))
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 40
    ws2 = wb.create_sheet("Sonuç")
    ws2["A1"], ws2["A1"].font = sonuc.baslik, Font(bold=True, size=14)
    _baslik_satiri(ws2, 3, ["Sayı", "Değer"], hf, hfill)
    for i, (k, v) in enumerate(_duz(sonuc.sayilar), 4):
        ws2.cell(i, 1, k)
        ws2.cell(i, 2, v if isinstance(v, (int, float, str)) or v is None else str(v))
    r = 5 + len(_duz(sonuc.sayilar))
    _baslik_satiri(ws2, r, ["Adımlar"], hf, hfill)
    for i, a in enumerate(sonuc.adimlar, r + 1):
        ws2.cell(i, 1, a)
    ws2.column_dimensions["A"].width = 60
    ws2.column_dimensions["B"].width = 30


def _x_lp(wb, g: dict, s: hesap.Sonuc) -> None:
    hf, hfill, giris, baslik_f, wrap = _stiller()
    ws = wb.create_sheet("Model", 0)
    c = g["c"]
    n = len(c)
    ad = g.get("degisken_adlari") if len(g.get("degisken_adlari") or []) == n else [f"x{i + 1}" for i in range(n)]
    ws["A1"], ws["A1"].font = "Doğrusal programlama modeli (Excel Solver'a hazır)", baslik_f
    ws["A3"], ws["A4"], ws["A5"], ws["A6"] = "Değişken", "Karar değişkeni değeri", "Amaç katsayısı", "Amaç fonksiyonu z"
    for j in range(n):
        col = _harf(2 + j)
        ws[f"{col}3"] = ad[j]
        ws[f"{col}3"].font, ws[f"{col}3"].fill = hf, hfill
        ws[f"{col}4"] = s.sayilar["degiskenler"][ad[j]]  # Solver'ın değiştireceği hücreler (başlangıç: bulunan çözüm)
        ws[f"{col}4"].fill = giris
        ws[f"{col}5"] = c[j]
    son = _harf(1 + n)
    ws["B6"] = f"=SUMPRODUCT(B4:{son}4,B5:{son}5)"
    ws["B6"].font = Font(bold=True)
    r0 = 9
    _baslik_satiri(ws, r0 - 1, ["Kısıt"] + ad + ["Sol taraf", "İşaret", "Sağ taraf", "Bolluk"], hf, hfill)
    satirlar = [(r, "<=", b) for r, b in zip(g.get("A_ub") or [], g.get("b_ub") or [])] + [(r, "=", b) for r, b in zip(g.get("A_eq") or [], g.get("b_eq") or [])]
    for i, (row, isr, b) in enumerate(satirlar):
        r = r0 + i
        ws.cell(r, 1, f"Kısıt {i + 1}")
        for j, v in enumerate(row):
            ws.cell(r, 2 + j, v)
        ls = _harf(2 + n)
        ws.cell(r, 2 + n, f"=SUMPRODUCT($B$4:${son}$4,B{r}:{son}{r})")
        ws.cell(r, 3 + n, isr)
        ws.cell(r, 4 + n, b)
        ws.cell(r, 5 + n, f"=ABS({_harf(4 + n)}{r}-{ls}{r})")
    son_r = r0 + len(satirlar) - 1
    y = son_r + 2
    tip = "Tam sayı (int)" if g.get("tamsayi") else "İkili (bin)" if g.get("ikili") else "Negatif olmayan"
    yon = [
        "EXCEL SOLVER YÖNERGESİ (Veri sekmesi > Çözücü; yoksa Dosya > Seçenekler > Eklentiler > Çözücü Eklentisi):",
        f"1) Hedefi Ayarla: $B$6 — Hedef: {'Maks' if g.get('amac', 'max') == 'max' else 'Min'}.",
        f"2) Değişken Hücreleri Değiştirerek: $B$4:${son}$4.",
        f"3) Kısıtlar: Ekle ile her satır için sol taraf ({_harf(2 + n)}) ile sağ taraf ({_harf(4 + n)}{r0}:{_harf(4 + n)}{son_r}) hücrelerini işaretine göre bağla (<= ya da =).",
        f"4) 'Kısıtsız Değişkenleri Negatif Olmayan Yap' kutusunu işaretle. Değişken tipi: {tip}" + (" (kısıt olarak $B$4:$" + son + "$4 int/bin ekle)." if tip != "Negatif olmayan" else "."),
        "5) Çözüm Yöntemi: Basit LP Simpleks (tam sayılıysa Evrimsel değil, 'Basit LP' + int kısıtı). Çöz'e bas.",
        f"Bulunan optimum (scipy/HiGHS): z* = {s.sayilar['z']}. Sarı hücreler Solver'ın değiştireceği hücrelerdir.",
    ]
    for i, t in enumerate(yon):
        ws.cell(y + i, 1, t)
    ws.column_dimensions["A"].width = 26
    for j in range(2, n + 7):
        ws.column_dimensions[_harf(j)].width = 14


def _x_ulastirma(wb, g: dict, s: hesap.Sonuc) -> None:
    hf, hfill, giris, baslik_f, _ = _stiller()
    ws = wb.create_sheet("Model", 0)
    arz, talep, C, plan = g["arz"], g["talep"], g["maliyet"], s.sayilar["plan"]
    m, n = len(arz), len(talep)
    ws["A1"], ws["A1"].font = "Ulaştırma modeli (Solver'a hazır)", baslik_f
    ws["A3"] = "Birim maliyet"
    _baslik_satiri(ws, 4, ["Kaynak \\ Hedef"] + [f"H{j + 1}" for j in range(n)], hf, hfill)
    for i in range(m):
        ws.cell(5 + i, 1, f"K{i + 1}")
        for j in range(n):
            ws.cell(5 + i, 2 + j, C[i][j])
    p0 = 5 + m + 2
    ws.cell(p0 - 1, 1, "Taşıma planı (Solver'ın değiştireceği hücreler; başlangıç: bulunan çözüm)")
    _baslik_satiri(ws, p0, ["Kaynak \\ Hedef"] + [f"H{j + 1}" for j in range(n)] + ["Toplam gönderilen", "Arz"], hf, hfill)
    for i in range(m):
        r = p0 + 1 + i
        ws.cell(r, 1, f"K{i + 1}")
        for j in range(n):
            ws.cell(r, 2 + j).value = plan[i][j]
            ws.cell(r, 2 + j).fill = giris
        ws.cell(r, 2 + n, f"=SUM(B{r}:{_harf(1 + n)}{r})")
        ws.cell(r, 3 + n, arz[i])
    rt, rd = p0 + 1 + m, p0 + 2 + m
    ws.cell(rt, 1, "Toplam alınan")
    ws.cell(rd, 1, "Talep")
    for j in range(n):
        col = _harf(2 + j)
        ws.cell(rt, 2 + j, f"=SUM({col}{p0 + 1}:{col}{p0 + m})")
        ws.cell(rd, 2 + j, talep[j])
    ws.cell(rd + 2, 1, "Toplam taşıma maliyeti")
    ws.cell(rd + 2, 2, f"=SUMPRODUCT(B5:{_harf(1 + n)}{4 + m},B{p0 + 1}:{_harf(1 + n)}{p0 + m})")
    ws.cell(rd + 2, 2).font = Font(bold=True)
    fazla = sum(arz) - sum(talep)
    yon = [
        "SOLVER YÖNERGESİ:",
        f"1) Hedef: ${'B'}${rd + 2} — Min. Değişken hücreler: B{p0 + 1}:{_harf(1 + n)}{p0 + m}.",
        f"2) Kısıtlar: satır toplamları ({_harf(2 + n)}{p0 + 1}:{_harf(2 + n)}{p0 + m}) {'<=' if fazla >= 0 else '='} arz ({_harf(3 + n)}{p0 + 1}:{_harf(3 + n)}{p0 + m}); "
        f"sütun toplamları (B{rt}:{_harf(1 + n)}{rt}) {'=' if fazla >= 0 else '<='} talep (B{rd}:{_harf(1 + n)}{rd}).",
        "3) Negatif olmayan + Basit LP Simpleks. (Arz ≠ talep ise fazla olan taraf '<=' olur; sanal kaynak/hedef gerekmez.)",
    ]
    for i, t in enumerate(yon):
        ws.cell(rd + 4 + i, 1, t)
    ws.column_dimensions["A"].width = 24


def _x_atama(wb, g: dict, s: hesap.Sonuc) -> None:
    hf, hfill, giris, baslik_f, _ = _stiller()
    ws = wb.create_sheet("Model", 0)
    C = g["maliyet"]
    m, n = len(C), len(C[0])
    ws["A1"], ws["A1"].font = "Atama modeli (Solver'a hazır)", baslik_f
    _baslik_satiri(ws, 3, ["Kişi \\ İş"] + [f"İş {j + 1}" for j in range(n)], hf, hfill)
    for i in range(m):
        ws.cell(4 + i, 1, f"Kişi {i + 1}")
        for j in range(n):
            ws.cell(4 + i, 2 + j, C[i][j])
    p0 = 4 + m + 2
    ws.cell(p0 - 1, 1, "Atama (1 = atandı; Solver'ın değiştireceği hücreler)")
    _baslik_satiri(ws, p0, ["Kişi \\ İş"] + [f"İş {j + 1}" for j in range(n)] + ["Satır toplamı"], hf, hfill)
    secili = {(i - 1, j - 1) for i, j in s.sayilar["atamalar"]}
    for i in range(m):
        r = p0 + 1 + i
        ws.cell(r, 1, f"Kişi {i + 1}")
        for j in range(n):
            ws.cell(r, 2 + j, 1 if (i, j) in secili else 0).fill = giris
        ws.cell(r, 2 + n, f"=SUM(B{r}:{_harf(1 + n)}{r})")
    rt = p0 + 1 + m
    ws.cell(rt, 1, "Sütun toplamı")
    for j in range(n):
        col = _harf(2 + j)
        ws.cell(rt, 2 + j, f"=SUM({col}{p0 + 1}:{col}{p0 + m})")
    ws.cell(rt + 2, 1, "Toplam")
    ws.cell(rt + 2, 2, f"=SUMPRODUCT(B4:{_harf(1 + n)}{3 + m},B{p0 + 1}:{_harf(1 + n)}{p0 + m})")
    yon = ["SOLVER YÖNERGESİ:", f"1) Hedef: $B${rt + 2} — {'Maks' if g.get('amac') == 'max' else 'Min'}. Değişken hücreler: B{p0 + 1}:{_harf(1 + n)}{p0 + m}.",
           "2) Kısıtlar: değişken hücreler ikili (bin); satır toplamları <= 1; sütun toplamları <= 1 (kare matriste = 1).", "3) Basit LP Simpleks ya da tam sayı kısıtıyla çöz."]
    for i, t in enumerate(yon):
        ws.cell(rt + 4 + i, 1, t)
    ws.column_dimensions["A"].width = 24


def _x_eoq(wb, g: dict, s: hesap.Sonuc) -> None:
    hf, hfill, giris, baslik_f, _ = _stiller()
    ws = wb.create_sheet("Model", 0)
    ws["A1"], ws["A1"].font = "EOQ modeli (gerçek Excel formülleri)", baslik_f
    satir = [("Yıllık talep D", g["talep_yillik"]), ("Sipariş maliyeti S", g["siparis_maliyeti"]), ("Elde tutma H", g["elde_tutma"]),
             ("Birim maliyet c", g.get("birim_maliyet")), ("Çalışma günü", g.get("gun_sayisi", 365)), ("Tedarik süresi L (gün)", g.get("tedarik_gun")),
             ("Günlük talep ss", g.get("gunluk_ss")), ("Servis düzeyi", g.get("servis_duzeyi"))]
    _baslik_satiri(ws, 3, ["Girdi", "Değer"], hf, hfill)
    for i, (a, v) in enumerate(satir, 4):
        ws.cell(i, 1, a)
        ws.cell(i, 2, v).fill = giris  # B4..B11
    _baslik_satiri(ws, 13, ["Sonuç", "Formül sonucu"], hf, hfill)
    f = [("EOQ = √(2DS/H)", "=SQRT(2*B4*B5/B6)"), ("Yıllık sipariş sayısı D/Q", "=B4/B14"), ("Sipariş aralığı (gün)", "=B8/B15"),
         ("Yıllık sipariş maliyeti", "=B15*B5"), ("Yıllık elde tutma maliyeti", "=B14/2*B6"), ("Değişken maliyet", "=B17+B18")]
    if g.get("birim_maliyet") is not None:
        f.append(("Toplam maliyet D·c + değişken", "=B4*B7+B19"))
    for i, (a, fo) in enumerate(f, 14):
        ws.cell(i, 1, a)
        ws.cell(i, 2, fo)
    i = 14 + len(f)
    if g.get("tedarik_gun") is not None:
        ws.cell(i, 1, "Günlük talep d")
        ws.cell(i, 2, "=B4/B8")
        i += 1
        if g.get("gunluk_ss") is not None and g.get("servis_duzeyi") is not None:
            ws.cell(i, 1, "z = NORMSINV(servis düzeyi)")
            ws.cell(i, 2, "=NORMSINV(B11)")
            ws.cell(i + 1, 1, "Emniyet stoku = z·σ·√L")
            ws.cell(i + 1, 2, f"=B{i}*B10*SQRT(B9)")
            ws.cell(i + 2, 1, "Yeniden sipariş noktası r = d·L + SS")
            ws.cell(i + 2, 2, f"=B{i - 1}*B9+B{i + 1}")
        else:
            ws.cell(i, 1, "Yeniden sipariş noktası r = d·L")
            ws.cell(i, 2, f"=B{i - 1}*B9")
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 18


def _x_kuyruk(wb, g: dict, s: hesap.Sonuc) -> None:
    hf, hfill, giris, baslik_f, _ = _stiller()
    ws = wb.create_sheet("Model", 0)
    ws["A1"], ws["A1"].font = "M/M/c kuyruk modeli (Erlang C, gerçek Excel formülleri)", baslik_f
    for i, (a, v) in enumerate([("Geliş hızı λ", g["lam"]), ("Hizmet hızı μ", g["mu"]), ("Sunucu sayısı c", g.get("c", 1))], 3):
        ws.cell(i, 1, a)
        ws.cell(i, 2, v).fill = giris  # B3, B4, B5
    c = int(g.get("c", 1))
    F = [("Trafik yoğunluğu a = λ/μ", "=B3/B4"), ("Kullanım ρ = a/c", "=B6/B5"),
         ("P0", f"=1/(SUM(E3:E{2 + c})+B6^B5/(FACT(B5)*(1-B7)))"), ("Beklemek zorunda kalma olasılığı (Erlang C)", "=B6^B5/(FACT(B5)*(1-B7))*B8"),
         ("Lq = C·ρ/(1−ρ)", "=B9*B7/(1-B7)"), ("Wq = Lq/λ", "=B10/B3"), ("W = Wq + 1/μ", "=B11+1/B4"), ("L = λ·W", "=B3*B12")]
    for i, (a, fo) in enumerate(F, 6):
        ws.cell(i, 1, a)
        ws.cell(i, 2, fo)
    _baslik_satiri(ws, 2, ["k", "aᵏ/k!"], hf, hfill, 4)
    for k in range(c):  # yardımcı sütun D:E (P0 toplamı için)
        ws.cell(3 + k, 4, k)
        ws.cell(3 + k, 5, f"=$B$6^D{3 + k}/FACT(D{3 + k})")
    ws.cell(15, 1, "Kararlılık için ρ < 1 olmalı.")
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 16


def _x_cpm(wb, g: dict, s: hesap.Sonuc) -> None:
    hf, hfill, giris, baslik_f, _ = _stiller()
    ws = wb.create_sheet("Model", 0)
    ws["A1"], ws["A1"].font = "CPM tablosu (ileri/geri geçiş formülleri)", baslik_f
    _baslik_satiri(ws, 3, ["Faaliyet", "Öncüller", "Süre", "ES", "EF", "LS", "LF", "Bolluk", "Kritik?"], hf, hfill)
    F = g["faaliyetler"]
    satir = {f["ad"]: 4 + i for i, f in enumerate(F)}
    son = 3 + len(F)
    pert_te = {}
    for f in F:
        if f.get("a") is not None and f.get("m") is not None and f.get("b") is not None:
            pert_te[f["ad"]] = (f["a"] + 4 * f["m"] + f["b"]) / 6
    for f in F:
        r = satir[f["ad"]]
        ws.cell(r, 1, f["ad"])
        ws.cell(r, 2, ", ".join(f.get("onculler") or []))
        ws.cell(r, 3, pert_te.get(f["ad"], f.get("sure"))).fill = giris
        ons = [f"E{satir[o]}" for o in f.get("onculler") or [] if o in satir]
        ws.cell(r, 4, f"=MAX({','.join(ons)})" if ons else 0)
        ws.cell(r, 5, f"=D{r}+C{r}")
        ardil = [f"F{satir[b['ad']]}" for b in F if f["ad"] in (b.get("onculler") or [])]
        ws.cell(r, 7, f"=MIN({','.join(ardil)})" if ardil else f"=MAX($E$4:$E${son})")
        ws.cell(r, 6, f"=G{r}-C{r}")
        ws.cell(r, 8, f"=F{r}-D{r}")
        ws.cell(r, 9, f'=IF(ABS(H{r})<0.000001,"Kritik","")')
    ws.cell(son + 2, 1, "Proje süresi")
    ws.cell(son + 2, 2, f"=MAX(E4:E{son})")
    ws.cell(son + 3, 1, "ES = öncüllerin en büyük EF'si; LF = ardılların en küçük LS'si; bolluk = LS − ES.")
    ws.column_dimensions["A"].width = 18


def _x_kontrol(wb, g: dict, s: hesap.Sonuc) -> None:
    if g.get("tip") != "xbar_r":
        return
    hf, hfill, giris, baslik_f, _ = _stiller()
    ws = wb.create_sheet("Model", 0)
    G = g["alt_gruplar"]
    n = len(G[0])
    ws["A1"], ws["A1"].font = "X̄-R kontrol kartı (formüllü)", baslik_f
    _baslik_satiri(ws, 3, ["Alt grup"] + [f"x{j + 1}" for j in range(n)] + ["X̄", "R"], hf, hfill)
    k = len(G)
    for i, row in enumerate(G):
        r = 4 + i
        ws.cell(r, 1, i + 1)
        for j, v in enumerate(row):
            ws.cell(r, 2 + j, v).fill = giris
        a, b = "B", _harf(1 + n)
        ws.cell(r, 2 + n, f"=AVERAGE({a}{r}:{b}{r})")
        ws.cell(r, 3 + n, f"=MAX({a}{r}:{b}{r})-MIN({a}{r}:{b}{r})")
    xc, rc = _harf(2 + n), _harf(3 + n)
    r0 = 4 + k + 1
    A2, D3, D4 = hesap._A2[n], hesap._D3[n], hesap._D4[n]
    rows = [("n", n), ("A2", A2), ("D3", D3), ("D4", D4), ("X̿ (merkez)", f"=AVERAGE({xc}4:{xc}{3 + k})"), ("R̄", f"=AVERAGE({rc}4:{rc}{3 + k})"),
            ("X̄ ÜKS = X̿ + A2·R̄", f"=B{r0 + 4}+B{r0 + 1}*B{r0 + 5}"), ("X̄ AKS = X̿ − A2·R̄", f"=B{r0 + 4}-B{r0 + 1}*B{r0 + 5}"),
            ("R ÜKS = D4·R̄", f"=B{r0 + 3}*B{r0 + 5}"), ("R AKS = D3·R̄", f"=B{r0 + 2}*B{r0 + 5}")]
    for i, (a, v) in enumerate(rows):
        ws.cell(r0 + i, 1, a)
        ws.cell(r0 + i, 2, v)
    ws.column_dimensions["A"].width = 26


EXCEL_OZEL = {"dogrusal_programlama": _x_lp, "ulastirma": _x_ulastirma, "atama": _x_atama, "eoq": _x_eoq, "kuyruk": _x_kuyruk, "cpm": _x_cpm,
              "kontrol_karti": _x_kontrol}


def excel_uret(arac: str, girdi: dict, sonuc: hesap.Sonuc) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    ozel = EXCEL_OZEL.get(arac)
    if ozel:
        ozel(wb, girdi, sonuc)
    _girdi_sonuc_sayfalari(wb, arac, girdi, sonuc)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ================================================================ Python
def _lit(x: Any) -> str:
    return pprint.pformat(x, width=100, sort_dicts=False)


def _p_lp(g: dict, s: hesap.Sonuc) -> str:
    return f'''import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp

# Doğrusal programlama: {"en büyükle" if g.get("amac", "max") == "max" else "en küçükle"}  (PuLP kuruluysa aynı modeli pulp.LpProblem ile de yazabilirsin)
AMAC = {g.get("amac", "max")!r}
c = np.array({_lit(g["c"])}, float)                 # amaç katsayıları
A_ub = {_lit(g.get("A_ub") or [])}                 # <= kısıt katsayıları
b_ub = {_lit(g.get("b_ub") or [])}
A_eq = {_lit(g.get("A_eq") or [])}                 # = kısıtları
b_eq = {_lit(g.get("b_eq") or [])}
TAMSAYI = {bool(g.get("tamsayi") or g.get("ikili"))!r}
IKILI = {bool(g.get("ikili"))!r}
adlar = {_lit(list(s.sayilar["degiskenler"].keys()))}

isaret = -1.0 if AMAC == "max" else 1.0              # scipy küçükler; enbüyüklemek için c'yi eksiyle çarp
if TAMSAYI:
    kisitlar = []
    if A_ub:
        kisitlar.append(LinearConstraint(np.array(A_ub, float), -np.inf, np.array(b_ub, float)))
    if A_eq:
        kisitlar.append(LinearConstraint(np.array(A_eq, float), np.array(b_eq, float), np.array(b_eq, float)))
    r = milp(isaret * c, constraints=kisitlar, integrality=np.ones(len(c)), bounds=Bounds(0, 1 if IKILI else np.inf))
    ok, x, fun = r.success, r.x, r.fun
else:
    r = linprog(isaret * c, A_ub=A_ub or None, b_ub=b_ub or None, A_eq=A_eq or None, b_eq=b_eq or None,
                bounds=(0, 1 if IKILI else None), method="highs")
    ok, x, fun = r.status == 0, r.x, r.fun
if not ok:
    raise SystemExit("Model çözülemedi (uygun çözüm yok ya da sınırsız)")

print("Optimum çözüm:")
for ad, v in zip(adlar, x):
    print(f"  {{ad}} = {{v:.4f}}")
print(f"z* = {{isaret * fun:.4f}}")
'''


def _p_ulastirma(g: dict, s: hesap.Sonuc) -> str:
    return f'''import numpy as np
from scipy.optimize import linprog

# Ulaştırma problemi: arz/talep dengesizse sanal kaynak/hedef (maliyet 0) eklenir.
arz = {_lit(g["arz"])}
talep = {_lit(g["talep"])}
C = {_lit(g["maliyet"])}
m, n = len(arz), len(talep)
arz, talep, C = list(map(float, arz)), list(map(float, talep)), [list(map(float, r)) for r in C]
fark = sum(arz) - sum(talep)
if fark > 0:
    talep.append(fark); C = [r + [0.0] for r in C]       # sanal hedef
elif fark < 0:
    arz.append(-fark); C.append([0.0] * n)                # sanal kaynak
M, N = len(arz), len(talep)
Aeq, beq = [], []
for i in range(M):                                        # her kaynağın toplam gönderisi = arz
    r = np.zeros(M * N); r[i * N:(i + 1) * N] = 1; Aeq.append(r); beq.append(arz[i])
for j in range(N):                                        # her hedefin toplam alımı = talep
    r = np.zeros(M * N); r[j::N] = 1; Aeq.append(r); beq.append(talep[j])
res = linprog(np.array(C).ravel(), A_eq=np.array(Aeq), b_eq=np.array(beq), bounds=(0, None), method="highs")
X = res.x.reshape(M, N)
print("Taşıma planı (satır = kaynak, sütun = hedef):")
print(np.round(X[:m, :n], 4))
print(f"Toplam maliyet = {{res.fun:.4f}}")
'''


def _p_atama(g: dict, s: hesap.Sonuc) -> str:
    return f'''import numpy as np
from scipy.optimize import linear_sum_assignment

# Atama problemi (Macar yöntemine eşdeğer çözüm)
C = np.array({_lit(g["maliyet"])}, float)
satir, sutun = linear_sum_assignment(C, maximize={g.get("amac") == "max"!r})
for i, j in zip(satir, sutun):
    print(f"Kişi {{i + 1}} -> İş {{j + 1}}: {{C[i, j]:g}}")
print(f"Toplam = {{C[satir, sutun].sum():.4f}}")
'''


def _p_eoq(g: dict, s: hesap.Sonuc) -> str:
    return f'''import math
from statistics import NormalDist

D = {g["talep_yillik"]!r}        # yıllık talep
S = {g["siparis_maliyeti"]!r}    # sipariş maliyeti
H = {g["elde_tutma"]!r}          # birim başına yıllık elde tutma maliyeti
c = {g.get("birim_maliyet")!r}   # birim maliyet (yoksa None)
gun = {g.get("gun_sayisi", 365)!r}
L = {g.get("tedarik_gun")!r}     # tedarik süresi (gün)
ss_gun = {g.get("gunluk_ss")!r}  # günlük talep standart sapması
servis = {g.get("servis_duzeyi")!r}

Q = math.sqrt(2 * D * S / H)                      # EOQ
n = D / Q
sip, elde = n * S, Q / 2 * H
print(f"EOQ = {{Q:.4f}}, yıllık sipariş sayısı = {{n:.4f}}, aralık = {{gun / n:.2f}} gün")
print(f"Sipariş maliyeti = {{sip:.2f}}, elde tutma = {{elde:.2f}}, değişken toplam = {{sip + elde:.2f}}")
if c is not None:
    print(f"Toplam maliyet = {{D * c + sip + elde:.2f}}")
if L is not None:
    d = D / gun
    emniyet = 0.0
    if ss_gun is not None and servis is not None:
        z = NormalDist().inv_cdf(servis)
        emniyet = z * ss_gun * math.sqrt(L)            # emniyet stoku = z·σ·√L
        print(f"z = {{z:.4f}}, emniyet stoku = {{emniyet:.2f}}")
    print(f"Yeniden sipariş noktası r = d·L + emniyet = {{d * L + emniyet:.2f}}")
'''


def _p_kuyruk(g: dict, s: hesap.Sonuc) -> str:
    return f'''import math

lam, mu, c = {g["lam"]!r}, {g["mu"]!r}, {int(g.get("c", 1))!r}   # geliş hızı, hizmet hızı, sunucu sayısı
a = lam / mu
rho = a / c
if rho >= 1:
    raise SystemExit("Sistem kararsız: rho >= 1")
son = a ** c / (math.factorial(c) * (1 - rho))
P0 = 1 / (sum(a ** k / math.factorial(k) for k in range(c)) + son)
Pw = son * P0                      # Erlang C: beklemek zorunda kalma olasılığı
Lq = Pw * rho / (1 - rho)
Wq = Lq / lam
W = Wq + 1 / mu
L = lam * W
print(f"rho = {{rho:.4f}}, P0 = {{P0:.5f}}, Erlang C = {{Pw:.5f}}")
print(f"L = {{L:.4f}}, Lq = {{Lq:.4f}}, W = {{W:.4f}}, Wq = {{Wq:.4f}}")
'''


def _p_cpm(g: dict, s: hesap.Sonuc) -> str:
    return f'''# CPM / PERT: ileri geçiş (ES, EF) ve geri geçiş (LS, LF)
faaliyetler = {_lit(g["faaliyetler"])}

def sure(f):
    if f.get("a") is not None and f.get("m") is not None and f.get("b") is not None:
        return (f["a"] + 4 * f["m"] + f["b"]) / 6   # PERT beklenen süre
    return f["sure"]

F = {{f["ad"]: f for f in faaliyetler}}
te = {{a: sure(f) for a, f in F.items()}}
ES, EF, sira = {{}}, {{}}, []                          # sira: topolojik (ileri geçiş) sırası
bekle = list(F)
while bekle:                                         # öncülleri hazır olanları sırayla işle
    ilerledi = False
    for a in list(bekle):
        if all(o in EF for o in F[a].get("onculler", [])):
            ES[a] = max((EF[o] for o in F[a].get("onculler", [])), default=0)
            EF[a] = ES[a] + te[a]
            sira.append(a)
            bekle.remove(a)
            ilerledi = True
    if not ilerledi:
        raise SystemExit("Öncül ilişkilerinde döngü var: " + ", ".join(bekle))
T = max(EF.values())
ardil = {{a: [b for b in F if a in F[b].get("onculler", [])] for a in F}}
LS, LF = {{}}, {{}}
for a in reversed(sira):                            # geri geçiş: topolojik sıranın tersi
    LF[a] = min((LS[b] for b in ardil[a]), default=T)
    LS[a] = LF[a] - te[a]
for a in sorted(F, key=lambda x: ES[x]):
    bolluk = LS[a] - ES[a]
    print(f"{{a}}: süre {{te[a]:.2f}} ES {{ES[a]:.2f}} EF {{EF[a]:.2f}} LS {{LS[a]:.2f}} LF {{LF[a]:.2f}} bolluk {{bolluk:.2f}}" + ("  <- kritik" if abs(bolluk) < 1e-9 else ""))
print(f"Proje süresi = {{T:.2f}}")
'''


def _p_genel(arac: str, g: dict, s: hesap.Sonuc) -> str:
    return f'''# {s.baslik}
# Bu araç için özel çözüm şablonu yok; girdiler ve uygulamanın bulduğu sonuç aşağıda, kendi çözümünü bununla karşılaştırabilirsin.
# Aynı hesabı uygulamanın kendi koduyla çalıştırmak için (proje klasöründe): from app import hesap; hesap.calistir({arac!r}, GIRDI)
GIRDI = {_lit(g)}

BEKLENEN = {_lit(s.sayilar)}

ADIMLAR = {_lit(s.adimlar)}

print({s.baslik!r})
for k, v in BEKLENEN.items():
    print(f"  {{k}}: {{v}}")
print()
print("\\n".join(ADIMLAR))
'''


PY_OZEL = {"dogrusal_programlama": _p_lp, "ulastirma": _p_ulastirma, "atama": _p_atama, "eoq": _p_eoq, "kuyruk": _p_kuyruk, "cpm": _p_cpm}


def python_uret(arac: str, girdi: dict, sonuc: hesap.Sonuc) -> str:
    kod = PY_OZEL[arac](girdi, sonuc) if arac in PY_OZEL else _p_genel(arac, girdi, sonuc)
    return f'"""{sonuc.baslik} — Ders Anlatıcı tarafından üretildi (python {arac}.py).\nGerekenler: pip install numpy scipy\n"""\n' + kod
