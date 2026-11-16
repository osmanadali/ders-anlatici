"""Mühendis hesap araçları: internetsiz, güvenli, gerçekten HESAP yapan küçük çözücüler.

Küçük yerel model sayı uydurabilir; bu yüzden sayıları burada hesaplarız. Her araç:
  - bir Pydantic giriş şeması (modelin dolduracağı alanlar),
  - saf bir Python fonksiyonu,
  - sonuç: sayılar + adım adım ara hesaplar (Türkçe).
Hiçbir araç dosya, ağ ya da eval kullanmaz.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Callable, Literal

import numpy as np
from pydantic import BaseModel, Field, ValidationError


class HesapHatasi(ValueError):
    """Girdi eksik/geçersiz ya da problem çözülemedi (ör. uygun çözüm yok)."""


class Sonuc(BaseModel):
    arac: str
    baslik: str
    sayilar: dict[str, Any]
    adimlar: list[str]


def _s(x: float, n: int = 4) -> str:
    """Sayıyı okunur yazar (gereksiz sıfırsız)."""
    if isinstance(x, (int, np.integer)):
        return str(int(x))
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return str(x)
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:.{n}f}".rstrip("0").rstrip(".")


def _yuvarla(x: Any, n: int = 6) -> Any:
    if isinstance(x, (float, np.floating)):
        return round(float(x), n) + 0.0  # -0.0 görünmesin
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (list, tuple, np.ndarray)):
        return [_yuvarla(i, n) for i in x]
    if isinstance(x, dict):
        return {k: _yuvarla(v, n) for k, v in x.items()}
    return x


def _norm_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _norm_ppf(p: float) -> float:
    from scipy.stats import norm

    return float(norm.ppf(p))


# ================================================================ 1) Doğrusal / tam sayılı programlama
class DPGirdi(BaseModel):
    amac: Literal["max", "min"] = Field("max", description="max (en büyükle) ya da min (en küçükle)")
    c: list[float] = Field(description="amaç fonksiyonu katsayıları, değişken sırasıyla")
    A_ub: list[list[float]] = Field(default_factory=list, description="≤ kısıtlarının katsayı satırları")
    b_ub: list[float] = Field(default_factory=list, description="≤ kısıtlarının sağ tarafları")
    A_eq: list[list[float]] = Field(default_factory=list, description="= kısıtlarının katsayı satırları")
    b_eq: list[float] = Field(default_factory=list, description="= kısıtlarının sağ tarafları")
    tamsayi: bool = Field(False, description="değişkenler tam sayı mı")
    ikili: bool = Field(False, description="değişkenler 0/1 mi")
    degisken_adlari: list[str] = Field(default_factory=list, description="x1, x2 yerine adlar (isteğe bağlı)")


def dogrusal_programlama(g: DPGirdi) -> Sonuc:
    from scipy.optimize import Bounds, LinearConstraint, linprog, milp

    n = len(g.c)
    if n == 0:
        raise HesapHatasi("Amaç fonksiyonu katsayıları boş")
    if len(g.A_ub) != len(g.b_ub) or len(g.A_eq) != len(g.b_eq):
        raise HesapHatasi("Kısıt sayısı ile sağ taraf sayısı uyuşmuyor")
    for satir in g.A_ub + g.A_eq:
        if len(satir) != n:
            raise HesapHatasi("Kısıt satırlarının uzunluğu değişken sayısına eşit olmalı")
    ad = g.degisken_adlari if len(g.degisken_adlari) == n else [f"x{i + 1}" for i in range(n)]
    isaret = -1.0 if g.amac == "max" else 1.0
    c = isaret * np.array(g.c, float)
    adimlar = [
        f"Model: {'en büyükle' if g.amac == 'max' else 'en küçükle'} z = " + " + ".join(f"{_s(v)}·{a}" for v, a in zip(g.c, ad)),
    ]
    for r, b in zip(g.A_ub, g.b_ub):
        adimlar.append("Kısıt: " + " + ".join(f"{_s(v)}·{a}" for v, a in zip(r, ad) if v) + f" ≤ {_s(b)}")
    for r, b in zip(g.A_eq, g.b_eq):
        adimlar.append("Kısıt: " + " + ".join(f"{_s(v)}·{a}" for v, a in zip(r, ad) if v) + f" = {_s(b)}")
    adimlar.append("Değişkenler " + ("0/1" if g.ikili else "tam sayı ve ≥ 0" if g.tamsayi else "≥ 0"))
    golge = None
    if g.tamsayi or g.ikili:
        cons = []
        if g.A_ub:
            cons.append(LinearConstraint(np.array(g.A_ub, float), -np.inf, np.array(g.b_ub, float)))
        if g.A_eq:
            cons.append(LinearConstraint(np.array(g.A_eq, float), np.array(g.b_eq, float), np.array(g.b_eq, float)))
        ub = 1 if g.ikili else np.inf
        res = milp(c, constraints=cons, integrality=np.ones(n), bounds=Bounds(0, ub))
        ok, x, fun = res.success, res.x, res.fun
        adimlar.append("Tam sayılı model dal-sınır (HiGHS) ile çözüldü.")
    else:
        res = linprog(c, A_ub=g.A_ub or None, b_ub=g.b_ub or None, A_eq=g.A_eq or None, b_eq=g.b_eq or None,
                      bounds=(0, 1 if g.ikili else None), method="highs")
        ok, x, fun = res.status == 0, res.x, res.fun
        if ok and g.A_ub:
            # linprog küçükleme biçiminde çözdü: z'nin sağ tarafa duyarlılığı = işaret × marjinal
            golge = [float(isaret * m) for m in res.ineqlin.marginals]
        adimlar.append("Doğrusal model simpleks/iç nokta (HiGHS) ile çözüldü.")
    if not ok:
        durum = {2: "uygun çözüm yok", 3: "sınırsız"}.get(getattr(res, "status", 0), "çözülemedi")
        raise HesapHatasi(f"Model {durum}")
    z = isaret * float(fun)
    cozum = {a: _yuvarla(float(v), 6) for a, v in zip(ad, x)}
    adimlar.append("Optimum: " + ", ".join(f"{a} = {_s(v)}" for a, v in cozum.items()) + f"; z* = {_s(z)}")
    sayilar: dict[str, Any] = {"z": _yuvarla(z), "degiskenler": cozum}
    if g.A_ub:
        yk = (np.array(g.A_ub, float) @ x).tolist()
        sayilar["kisit_kullanimi"] = _yuvarla(yk)
        sayilar["bolluk"] = _yuvarla([b - u for b, u in zip(g.b_ub, yk)])
        adimlar.append("Kısıt kullanımları: " + ", ".join(f"{_s(u)}/{_s(b)}" for u, b in zip(yk, g.b_ub)))
    if golge is not None:
        sayilar["golge_fiyat"] = _yuvarla(golge)
        adimlar.append("Gölge fiyatlar (sağ taraf 1 birim artarsa z değişimi): " + ", ".join(_s(v) for v in golge))
    return Sonuc(arac="dogrusal_programlama", baslik="Doğrusal/tam sayılı programlama", sayilar=sayilar, adimlar=adimlar)


# ================================================================ 2) Ulaştırma
class UlastirmaGirdi(BaseModel):
    arz: list[float] = Field(description="kaynakların arzları")
    talep: list[float] = Field(description="hedeflerin talepleri")
    maliyet: list[list[float]] = Field(description="birim taşıma maliyeti matrisi [kaynak][hedef]")


def ulastirma(g: UlastirmaGirdi) -> Sonuc:
    from scipy.optimize import linprog

    m, n = len(g.arz), len(g.talep)
    if m == 0 or n == 0 or len(g.maliyet) != m or any(len(r) != n for r in g.maliyet):
        raise HesapHatasi("Maliyet matrisi arz/talep sayısıyla uyuşmuyor")
    arz, talep = list(map(float, g.arz)), list(map(float, g.talep))
    C = [list(map(float, r)) for r in g.maliyet]
    adimlar = [f"Toplam arz = {_s(sum(arz))}, toplam talep = {_s(sum(talep))}"]
    if abs(sum(arz) - sum(talep)) > 1e-9:
        fark = sum(arz) - sum(talep)
        if fark > 0:
            talep.append(fark)
            C = [r + [0.0] for r in C]
            adimlar.append(f"Arz fazla: {_s(fark)} birimlik sanal (dummy) hedef eklendi, maliyeti 0.")
        else:
            arz.append(-fark)
            C.append([0.0] * n)
            adimlar.append(f"Talep fazla: {_s(-fark)} birimlik sanal (dummy) kaynak eklendi, maliyeti 0.")
    M, N = len(arz), len(talep)
    c = np.array(C).ravel()
    Aeq, beq = [], []
    for i in range(M):
        r = np.zeros(M * N)
        r[i * N:(i + 1) * N] = 1
        Aeq.append(r)
        beq.append(arz[i])
    for j in range(N):
        r = np.zeros(M * N)
        r[j::N] = 1
        Aeq.append(r)
        beq.append(talep[j])
    res = linprog(c, A_eq=np.array(Aeq), b_eq=np.array(beq), bounds=(0, None), method="highs")
    if res.status != 0:
        raise HesapHatasi("Ulaştırma modeli çözülemedi")
    X = np.round(res.x.reshape(M, N), 6)
    gercek = [[_yuvarla(float(X[i, j])) for j in range(n)] for i in range(m)]
    adimlar.append("Maliyeti en küçükleyen taşıma planı (HiGHS ile, simpleksin ulaştırma uzmanlaşmış hâli yerine genel LP):")
    for i in range(m):
        for j in range(n):
            if X[i, j] > 1e-9:
                adimlar.append(f"  Kaynak {i + 1} → Hedef {j + 1}: {_s(float(X[i, j]))} birim × {_s(C[i][j])} = {_s(float(X[i, j]) * C[i][j])}")
    toplam = float(res.fun)
    adimlar.append(f"Toplam taşıma maliyeti = {_s(toplam)}")
    return Sonuc(arac="ulastirma", baslik="Ulaştırma problemi", sayilar={"toplam_maliyet": _yuvarla(toplam), "plan": gercek},
                 adimlar=adimlar)


# ================================================================ 3) Atama
class AtamaGirdi(BaseModel):
    maliyet: list[list[float]] = Field(description="atama maliyet (ya da kazanç) matrisi [kişi][iş]")
    amac: Literal["min", "max"] = Field("min", description="min maliyet ya da max kazanç")


def atama(g: AtamaGirdi) -> Sonuc:
    from scipy.optimize import linear_sum_assignment

    C = np.array(g.maliyet, float)
    if C.ndim != 2 or C.size == 0:
        raise HesapHatasi("Maliyet matrisi geçersiz")
    r, k = linear_sum_assignment(C, maximize=(g.amac == "max"))
    toplam = float(C[r, k].sum())
    adimlar = [f"Matris {C.shape[0]}×{C.shape[1]}; amaç: {'en büyükleme' if g.amac == 'max' else 'en küçükleme'} (Macar yöntemi eşdeğeri)."]
    if C.shape[0] != C.shape[1]:
        adimlar.append("Matris kare değil: fazla satır/sütun atanmadan kalır (sanal 0 satır/sütun mantığı).")
    for i, j in zip(r, k):
        adimlar.append(f"  Kişi {i + 1} → İş {j + 1}: {_s(float(C[i, j]))}")
    adimlar.append(f"Toplam = {_s(toplam)}")
    return Sonuc(arac="atama", baslik="Atama problemi", sayilar={"toplam": _yuvarla(toplam),
                 "atamalar": [[int(i) + 1, int(j) + 1] for i, j in zip(r, k)]}, adimlar=adimlar)


# ================================================================ 4) Çizelgeleme
class JohnsonGirdi(BaseModel):
    isler: list[list[float]] = Field(description="her iş için [1. makine süresi, 2. makine süresi]")


def johnson(g: JohnsonGirdi) -> Sonuc:
    isler = g.isler
    if not isler or any(len(r) != 2 for r in isler):
        raise HesapHatasi("Her iş için iki süre gerekir")
    n = len(isler)
    bas, son = [], []
    for i in sorted(range(n), key=lambda i: (min(isler[i]), i)):
        (bas if isler[i][0] <= isler[i][1] else son).append(i)
    bas.sort(key=lambda i: (isler[i][0], i))
    son.sort(key=lambda i: (-isler[i][1], i))
    sira = bas + son
    t1 = t2 = 0.0
    adimlar = ["Johnson kuralı: en küçük süre 1. makinedeyse işi başa, 2. makinedeyse sona koy."]
    for i in sira:
        t1 += isler[i][0]
        t2 = max(t2, t1) + isler[i][1]
        adimlar.append(f"  İş {i + 1}: M1 biter {_s(t1)}, M2 biter {_s(t2)}")
    adimlar.append(f"Sıra: {' → '.join(str(i + 1) for i in sira)}; toplam tamamlanma (Cmax) = {_s(t2)}")
    return Sonuc(arac="johnson", baslik="Johnson kuralı (2 makine akış tipi)", sayilar={"sira": [i + 1 for i in sira],
                 "cmax": _yuvarla(t2)}, adimlar=adimlar)


class TekMakineGirdi(BaseModel):
    kural: Literal["SPT", "EDD"] = Field("SPT", description="SPT (en kısa işlem süresi) ya da EDD (en erken teslim)")
    sureler: list[float] = Field(description="işlem süreleri")
    teslim: list[float] = Field(default_factory=list, description="teslim tarihleri (EDD için gerekli)")


def tek_makine(g: TekMakineGirdi) -> Sonuc:
    p = g.sureler
    n = len(p)
    if n == 0:
        raise HesapHatasi("İşlem süreleri boş")
    d = g.teslim if len(g.teslim) == n else [0.0] * n
    if g.kural == "EDD" and len(g.teslim) != n:
        raise HesapHatasi("EDD için teslim tarihleri gerekli")
    sira = sorted(range(n), key=(lambda i: (d[i], i)) if g.kural == "EDD" else (lambda i: (p[i], i)))
    t = 0.0
    akis, gec, maxg, ngec = [], [], 0.0, 0
    adimlar = [f"{g.kural} kuralı ile sıralama."]
    for i in sira:
        t += p[i]
        akis.append(t)
        ge = max(0.0, t - d[i]) if len(g.teslim) == n else 0.0
        gec.append(ge)
        maxg = max(maxg, ge)
        ngec += ge > 0
        adimlar.append(f"  İş {i + 1}: biter {_s(t)}" + (f", teslim {_s(d[i])}, gecikme {_s(ge)}" if len(g.teslim) == n else ""))
    ort = sum(akis) / n
    adimlar.append(f"Ortalama akış zamanı = {_s(ort)}")
    sayi = {"sira": [i + 1 for i in sira], "ortalama_akis": _yuvarla(ort), "cmax": _yuvarla(t)}
    if len(g.teslim) == n:
        sayi.update(toplam_gecikme=_yuvarla(sum(gec)), maks_gecikme=_yuvarla(maxg), geciken_is=int(ngec))
        adimlar.append(f"Toplam gecikme = {_s(sum(gec))}, maksimum gecikme = {_s(maxg)}, geciken iş sayısı = {int(ngec)}")
    return Sonuc(arac="tek_makine", baslik=f"Tek makine çizelgeleme ({g.kural})", sayilar=sayi, adimlar=adimlar)


class Faaliyet(BaseModel):
    ad: str
    sure: float | None = Field(None, description="kesin süre (PERT'te boş bırakılabilir)")
    onculler: list[str] = Field(default_factory=list)
    a: float | None = Field(None, description="PERT iyimser süre")
    m: float | None = Field(None, description="PERT olası süre")
    b: float | None = Field(None, description="PERT kötümser süre")


class CPMGirdi(BaseModel):
    faaliyetler: list[Faaliyet]
    hedef_sure: float | None = Field(None, description="PERT: bu sürede bitme olasılığı istenirse hedef")


def cpm(g: CPMGirdi) -> Sonuc:
    F = {f.ad: f for f in g.faaliyetler}
    if len(F) != len(g.faaliyetler) or not F:
        raise HesapHatasi("Faaliyet adları benzersiz ve dolu olmalı")
    te, var = {}, {}
    pert = False
    for f in g.faaliyetler:
        if f.a is not None and f.m is not None and f.b is not None:
            te[f.ad] = (f.a + 4 * f.m + f.b) / 6
            var[f.ad] = ((f.b - f.a) / 6) ** 2
            pert = True
        elif f.sure is not None:
            te[f.ad], var[f.ad] = float(f.sure), 0.0
        else:
            raise HesapHatasi(f"{f.ad} faaliyetinin süresi yok")
        for o in f.onculler:
            if o not in F:
                raise HesapHatasi(f"{f.ad} için bilinmeyen öncül: {o}")
    # topolojik sıra
    sira, gor, gecici = [], set(), set()

    def ziyaret(a: str):
        if a in gor:
            return
        if a in gecici:
            raise HesapHatasi("Öncelik ağında döngü var")
        gecici.add(a)
        for o in F[a].onculler:
            ziyaret(o)
        gecici.discard(a)
        gor.add(a)
        sira.append(a)

    for a in F:
        ziyaret(a)
    ES, EF = {}, {}
    for a in sira:
        ES[a] = max((EF[o] for o in F[a].onculler), default=0.0)
        EF[a] = ES[a] + te[a]
    T = max(EF.values())
    ardil = {a: [b for b in F if a in F[b].onculler] for a in F}
    LF, LS = {}, {}
    for a in reversed(sira):
        LF[a] = min((LS[b] for b in ardil[a]), default=T)
        LS[a] = LF[a] - te[a]
    bolluk = {a: LS[a] - ES[a] for a in F}
    kritik = [a for a in sira if abs(bolluk[a]) < 1e-9]
    adimlar = ["İleri geçiş: ES = öncüllerin en büyük EF'si; EF = ES + süre." + ("  (PERT: te = (a + 4m + b)/6)" if pert else ""),
               "Geri geçiş: LF = ardılların en küçük LS'si; LS = LF − süre; bolluk = LS − ES."]
    for a in sira:
        adimlar.append(f"  {a}: süre {_s(te[a], 3)}, ES {_s(ES[a], 3)}, EF {_s(EF[a], 3)}, LS {_s(LS[a], 3)}, LF {_s(LF[a], 3)}, bolluk {_s(bolluk[a], 3)}")
    adimlar.append(f"Kritik yol (bolluğu 0): {' → '.join(kritik)}; proje süresi = {_s(T, 3)}")
    sayi: dict[str, Any] = {"proje_suresi": _yuvarla(T), "kritik_yol": kritik, "bolluk": _yuvarla(bolluk),
                            "ES": _yuvarla(ES), "EF": _yuvarla(EF), "LS": _yuvarla(LS), "LF": _yuvarla(LF)}
    if pert:
        v = sum(var[a] for a in kritik)
        sayi["kritik_yol_varyansi"] = _yuvarla(v)
        adimlar.append(f"Kritik yol varyansı = {_s(v, 4)}, standart sapma = {_s(math.sqrt(v), 4)}")
        if g.hedef_sure is not None and v > 0:
            z = (g.hedef_sure - T) / math.sqrt(v)
            p = _norm_cdf(z)
            sayi["hedefte_bitme_olasiligi"] = _yuvarla(p)
            adimlar.append(f"P(T ≤ {_s(g.hedef_sure)}) = Φ(z), z = ({_s(g.hedef_sure)} − {_s(T, 3)})/{_s(math.sqrt(v), 4)} = {_s(z, 3)} → {_s(p, 4)}")
    return Sonuc(arac="cpm", baslik="CPM / PERT", sayilar=sayi, adimlar=adimlar)


# ================================================================ 5) Envanter
class EOQGirdi(BaseModel):
    talep_yillik: float = Field(description="yıllık talep D")
    siparis_maliyeti: float = Field(description="sipariş başına sabit maliyet S")
    elde_tutma: float = Field(description="birim başına yıllık elde tutma maliyeti H (yoksa birim_maliyet×oran)")
    birim_maliyet: float | None = Field(None, description="birim satın alma maliyeti c (toplam maliyet için)")
    gun_sayisi: float = Field(365, description="yıldaki çalışma günü")
    tedarik_gun: float | None = Field(None, description="tedarik süresi L (gün)")
    gunluk_ss: float | None = Field(None, description="günlük talebin standart sapması")
    servis_duzeyi: float | None = Field(None, description="döngü servis düzeyi, ör. 0.95")


def eoq(g: EOQGirdi) -> Sonuc:
    D, S, H = g.talep_yillik, g.siparis_maliyeti, g.elde_tutma
    if D <= 0 or S <= 0 or H <= 0:
        raise HesapHatasi("D, S ve H pozitif olmalı")
    Q = math.sqrt(2 * D * S / H)
    n = D / Q
    sipM, eldeM = n * S, Q / 2 * H
    adimlar = [f"EOQ = √(2·D·S/H) = √(2·{_s(D)}·{_s(S)}/{_s(H)}) = {_s(Q)}",
               f"Yıllık sipariş sayısı = D/Q = {_s(n)}; sipariş aralığı = {_s(g.gun_sayisi / n)} gün",
               f"Sipariş maliyeti = {_s(sipM)}, elde tutma = {_s(eldeM)} (eşittir) → değişken toplam = {_s(sipM + eldeM)}"]
    sayi: dict[str, Any] = {"EOQ": _yuvarla(Q), "siparis_sayisi": _yuvarla(n), "siparis_maliyeti": _yuvarla(sipM),
                            "elde_tutma_maliyeti": _yuvarla(eldeM), "degisken_maliyet": _yuvarla(sipM + eldeM)}
    if g.birim_maliyet is not None:
        tc = D * g.birim_maliyet + sipM + eldeM
        sayi["toplam_maliyet"] = _yuvarla(tc)
        adimlar.append(f"Toplam maliyet = D·c + değişken = {_s(tc)}")
    if g.tedarik_gun is not None:
        d = D / g.gun_sayisi
        L = g.tedarik_gun
        ss = 0.0
        if g.gunluk_ss is not None and g.servis_duzeyi is not None:
            z = _norm_ppf(g.servis_duzeyi)
            ss = z * g.gunluk_ss * math.sqrt(L)
            adimlar.append(f"Emniyet stoku = z·σ·√L = {_s(z, 3)}·{_s(g.gunluk_ss)}·√{_s(L)} = {_s(ss)}")
            sayi["z"] = _yuvarla(z)
        r = d * L + ss
        sayi.update(emniyet_stogu=_yuvarla(ss), yeniden_siparis_noktasi=_yuvarla(r), gunluk_talep=_yuvarla(d))
        adimlar.append(f"Günlük talep d = {_s(d, 3)}; yeniden sipariş noktası r = d·L + emniyet = {_s(r)}  → (Q, r) = ({_s(Q)}, {_s(r)})")
    return Sonuc(arac="eoq", baslik="EOQ, yeniden sipariş noktası ve emniyet stoku", sayilar=sayi, adimlar=adimlar)


# ================================================================ 6) Kuyruk
class KuyrukGirdi(BaseModel):
    lam: float = Field(description="geliş hızı λ (birim zamanda)")
    mu: float = Field(description="bir sunucunun hizmet hızı μ")
    c: int = Field(1, description="sunucu sayısı (1 = M/M/1)")


def kuyruk(g: KuyrukGirdi) -> Sonuc:
    lam, mu, c = g.lam, g.mu, g.c
    if lam <= 0 or mu <= 0 or c < 1:
        raise HesapHatasi("λ, μ pozitif ve c ≥ 1 olmalı")
    a = lam / mu
    rho = a / c
    if rho >= 1:
        raise HesapHatasi(f"Sistem kararsız: ρ = {_s(rho)} ≥ 1")
    adimlar = [f"Trafik yoğunluğu a = λ/μ = {_s(a)}; kullanım ρ = λ/(c·μ) = {_s(rho)}"]
    if c == 1:
        L, Lq = rho / (1 - rho), rho ** 2 / (1 - rho)
        W, Wq = 1 / (mu - lam), rho / (mu - lam)
        P0 = 1 - rho
        pw = rho
        adimlar += [f"M/M/1: L = ρ/(1−ρ) = {_s(L)}, Lq = ρ²/(1−ρ) = {_s(Lq)}",
                    f"W = 1/(μ−λ) = {_s(W)}, Wq = ρ/(μ−λ) = {_s(Wq)}", f"Beklemek zorunda kalma olasılığı = ρ = {_s(pw)}"]
    else:
        toplam = sum(a ** k / math.factorial(k) for k in range(c))
        son = a ** c / (math.factorial(c) * (1 - rho))
        P0 = 1 / (toplam + son)
        pw = son * P0  # Erlang C
        Lq = pw * rho / (1 - rho)
        Wq = Lq / lam
        W = Wq + 1 / mu
        L = lam * W
        adimlar += [f"M/M/{c}: P0 = {_s(P0, 5)}", f"Erlang C (beklemek zorunda kalma olasılığı) = {_s(pw, 5)}",
                    f"Lq = C·ρ/(1−ρ) = {_s(Lq)}; Wq = Lq/λ = {_s(Wq)}; W = Wq + 1/μ = {_s(W)}; L = λ·W = {_s(L)}"]
    return Sonuc(arac="kuyruk", baslik=f"M/M/{c} kuyruk modeli", sayilar={
        "rho": _yuvarla(rho), "P0": _yuvarla(P0), "beklemek_zorunda_olasilik": _yuvarla(pw), "L": _yuvarla(L),
        "Lq": _yuvarla(Lq), "W": _yuvarla(W), "Wq": _yuvarla(Wq)}, adimlar=adimlar)


class SimGirdi(BaseModel):
    lam: float = Field(description="geliş hızı λ")
    mu: float = Field(description="hizmet hızı μ")
    musteri: int = Field(20000, description="benzetilecek müşteri sayısı")
    tohum: int = Field(1, description="rastgele sayı tohumu")


def simulasyon(g: SimGirdi) -> Sonuc:
    """Tek sunuculu kuyruğun kesikli olay benzetimi (Lindley özyinelemesi, numpy)."""
    if g.lam <= 0 or g.mu <= 0 or not (10 <= g.musteri <= 2_000_000):
        raise HesapHatasi("Geçersiz benzetim girdisi")
    rng = np.random.default_rng(g.tohum)
    ara = rng.exponential(1 / g.lam, g.musteri)
    hiz = rng.exponential(1 / g.mu, g.musteri)
    bekle = np.zeros(g.musteri)
    for i in range(1, g.musteri):
        bekle[i] = max(0.0, bekle[i - 1] + hiz[i - 1] - ara[i])
    gelis = np.cumsum(ara)
    bitis = gelis + bekle + hiz
    meşgul = float(hiz.sum() / bitis[-1])
    Wq, W = float(bekle.mean()), float((bekle + hiz).mean())
    adimlar = [f"{g.musteri} müşteri, tohum {g.tohum}: bekleme_i = max(0, bekleme_(i−1) + hizmet_(i−1) − aralık_i)",
               f"Ortalama bekleme Wq ≈ {_s(Wq)}, sistemde kalma W ≈ {_s(W)}, sunucu doluluğu ≈ {_s(meşgul)}"]
    sayi = {"Wq": _yuvarla(Wq), "W": _yuvarla(W), "doluluk": _yuvarla(meşgul)}
    if g.lam < g.mu:
        rho = g.lam / g.mu
        sayi["Wq_kuram"] = _yuvarla(rho / (g.mu - g.lam))
        adimlar.append(f"Kuram (M/M/1): Wq = {_s(rho / (g.mu - g.lam))}, W = {_s(1 / (g.mu - g.lam))} (benzetim bunlara yakın olmalı)")
    return Sonuc(arac="simulasyon", baslik="Tek sunuculu kuyruk benzetimi", sayilar=sayi, adimlar=adimlar)


# ================================================================ 7) Kalite
_A2 = {2: 1.880, 3: 1.023, 4: 0.729, 5: 0.577, 6: 0.483, 7: 0.419, 8: 0.373, 9: 0.337, 10: 0.308}
_D3 = {2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0.076, 8: 0.136, 9: 0.184, 10: 0.223}
_D4 = {2: 3.267, 3: 2.574, 4: 2.282, 5: 2.114, 6: 2.004, 7: 1.924, 8: 1.864, 9: 1.816, 10: 1.777}
_D2 = {2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326, 6: 2.534, 7: 2.704, 8: 2.847, 9: 2.970, 10: 3.078}


class KontrolKartiGirdi(BaseModel):
    tip: Literal["xbar_r", "p", "c"] = Field(description="xbar_r (X̄-R), p (hatalı oranı), c (kusur sayısı)")
    alt_gruplar: list[list[float]] = Field(default_factory=list, description="X̄-R için alt grup ölçümleri (satır = alt grup)")
    hatali: list[float] = Field(default_factory=list, description="p kartı: her örnekteki hatalı sayısı")
    n: float | None = Field(None, description="p kartı: örnek büyüklüğü")
    kusur: list[float] = Field(default_factory=list, description="c kartı: her birimdeki kusur sayısı")


def kontrol_karti(g: KontrolKartiGirdi) -> Sonuc:
    if g.tip == "xbar_r":
        G = g.alt_gruplar
        if len(G) < 2:
            raise HesapHatasi("En az 2 alt grup gerekir")
        n = len(G[0])
        if n not in _A2 or any(len(r) != n for r in G):
            raise HesapHatasi("Alt grup büyüklüğü 2-10 arasında ve eşit olmalı")
        xb = [sum(r) / n for r in G]
        R = [max(r) - min(r) for r in G]
        xbb, Rb = sum(xb) / len(xb), sum(R) / len(R)
        ux, lx = xbb + _A2[n] * Rb, xbb - _A2[n] * Rb
        ur, lr = _D4[n] * Rb, _D3[n] * Rb
        sigma = Rb / _D2[n]
        dis = [i + 1 for i, v in enumerate(xb) if v > ux or v < lx] + [f"R{i + 1}" for i, v in enumerate(R) if v > ur or v < lr]
        adimlar = [f"Alt grup ortalamaları X̄ = {[_yuvarla(v, 4) for v in xb]}", f"Aralıklar R = {[_yuvarla(v, 4) for v in R]}",
                   f"X̄̄ = {_s(xbb)}, R̄ = {_s(Rb)} (n={n}: A2={_A2[n]}, D3={_D3[n]}, D4={_D4[n]})",
                   f"X̄ kartı: UCL = X̄̄ + A2·R̄ = {_s(ux)}, LCL = {_s(lx)}", f"R kartı: UCL = D4·R̄ = {_s(ur)}, LCL = D3·R̄ = {_s(lr)}",
                   f"Süreç standart sapma tahmini σ̂ = R̄/d2 = {_s(sigma)}",
                   "Sınır dışı noktalar: " + (", ".join(map(str, dis)) if dis else "yok")]
        return Sonuc(arac="kontrol_karti", baslik="X̄-R kontrol kartı", sayilar={
            "xbar_cizgi": _yuvarla(xbb), "xbar_UCL": _yuvarla(ux), "xbar_LCL": _yuvarla(lx), "R_cizgi": _yuvarla(Rb),
            "R_UCL": _yuvarla(ur), "R_LCL": _yuvarla(lr), "sigma_tahmin": _yuvarla(sigma), "sinir_disi": dis}, adimlar=adimlar)
    if g.tip == "p":
        if not g.hatali or not g.n or g.n <= 0:
            raise HesapHatasi("p kartı için hatalı sayıları ve n gerekir")
        k = len(g.hatali)
        pb = sum(g.hatali) / (k * g.n)
        s = math.sqrt(pb * (1 - pb) / g.n)
        u, l = pb + 3 * s, max(0.0, pb - 3 * s)
        dis = [i + 1 for i, d in enumerate(g.hatali) if d / g.n > u or d / g.n < l]
        adimlar = [f"p̄ = Σhatalı/(k·n) = {_s(sum(g.hatali))}/({k}·{_s(g.n)}) = {_s(pb, 5)}", f"σ_p = √(p̄(1−p̄)/n) = {_s(s, 5)}",
                   f"UCL = p̄ + 3σ_p = {_s(u, 5)}, LCL = max(0, p̄ − 3σ_p) = {_s(l, 5)}",
                   "Sınır dışı örnekler: " + (", ".join(map(str, dis)) if dis else "yok")]
        return Sonuc(arac="kontrol_karti", baslik="p kontrol kartı", sayilar={"p_bar": _yuvarla(pb), "UCL": _yuvarla(u),
                     "LCL": _yuvarla(l), "sinir_disi": dis}, adimlar=adimlar)
    if not g.kusur:
        raise HesapHatasi("c kartı için kusur sayıları gerekir")
    cb = sum(g.kusur) / len(g.kusur)
    s = math.sqrt(cb)
    u, l = cb + 3 * s, max(0.0, cb - 3 * s)
    dis = [i + 1 for i, d in enumerate(g.kusur) if d > u or d < l]
    adimlar = [f"c̄ = {_s(sum(g.kusur))}/{len(g.kusur)} = {_s(cb, 4)}", f"UCL = c̄ + 3√c̄ = {_s(u, 4)}, LCL = max(0, c̄ − 3√c̄) = {_s(l, 4)}",
               "Sınır dışı birimler: " + (", ".join(map(str, dis)) if dis else "yok")]
    return Sonuc(arac="kontrol_karti", baslik="c kontrol kartı", sayilar={"c_bar": _yuvarla(cb), "UCL": _yuvarla(u), "LCL": _yuvarla(l),
                 "sinir_disi": dis}, adimlar=adimlar)


class YeterlilikGirdi(BaseModel):
    LSL: float | None = Field(None, description="alt şartname sınırı")
    USL: float | None = Field(None, description="üst şartname sınırı")
    ortalama: float | None = Field(None, description="süreç ortalaması (veri yoksa)")
    sigma: float | None = Field(None, description="süreç standart sapması (veri yoksa)")
    veri: list[float] = Field(default_factory=list, description="ölçümler (ortalama/sapma bunlardan hesaplanır)")


def yeterlilik(g: YeterlilikGirdi) -> Sonuc:
    if g.LSL is None and g.USL is None:
        raise HesapHatasi("En az bir şartname sınırı gerekir")
    if len(g.veri) >= 2:
        mu = sum(g.veri) / len(g.veri)
        sg = float(np.std(g.veri, ddof=1))
        adimlar = [f"Veriden: ortalama = {_s(mu)}, örnek standart sapma s = {_s(sg)}"]
    elif g.ortalama is not None and g.sigma:
        mu, sg = g.ortalama, g.sigma
        adimlar = [f"Verilen: ortalama = {_s(mu)}, σ = {_s(sg)}"]
    else:
        raise HesapHatasi("Veri ya da (ortalama, sigma) gerekir")
    if sg <= 0:
        raise HesapHatasi("Standart sapma pozitif olmalı")
    sayi: dict[str, Any] = {"ortalama": _yuvarla(mu), "sigma": _yuvarla(sg)}
    cpu = (g.USL - mu) / (3 * sg) if g.USL is not None else None
    cpl = (mu - g.LSL) / (3 * sg) if g.LSL is not None else None
    if cpu is not None and cpl is not None:
        cp = (g.USL - g.LSL) / (6 * sg)
        sayi["Cp"] = _yuvarla(cp)
        adimlar.append(f"Cp = (USL−LSL)/(6σ) = ({_s(g.USL)}−{_s(g.LSL)})/(6·{_s(sg)}) = {_s(cp)}")
    if cpu is not None:
        sayi["Cpu"] = _yuvarla(cpu)
        adimlar.append(f"Cpu = (USL−μ)/(3σ) = {_s(cpu)}")
    if cpl is not None:
        sayi["Cpl"] = _yuvarla(cpl)
        adimlar.append(f"Cpl = (μ−LSL)/(3σ) = {_s(cpl)}")
    cpk = min(v for v in (cpu, cpl) if v is not None)
    sayi["Cpk"] = _yuvarla(cpk)
    adimlar.append(f"Cpk = min(Cpu, Cpl) = {_s(cpk)} → " + ("yeterli (≥1,33)" if cpk >= 1.33 else "sınırda (1–1,33)" if cpk >= 1 else "yetersiz (<1)"))
    ppm = 0.0
    if g.USL is not None:
        ppm += (1 - _norm_cdf((g.USL - mu) / sg)) * 1e6
    if g.LSL is not None:
        ppm += _norm_cdf((g.LSL - mu) / sg) * 1e6
    sayi["ppm_beklenen"] = _yuvarla(ppm, 1)
    adimlar.append(f"Normal varsayımıyla şartname dışı ≈ {_s(ppm, 1)} ppm")
    return Sonuc(arac="yeterlilik", baslik="Süreç yeterliliği (Cp, Cpk)", sayilar=sayi, adimlar=adimlar)


# ================================================================ 8) İstatistik
class IstatistikGirdi(BaseModel):
    veri: list[float] = Field(description="örnek verisi")
    guven: float = Field(0.95, description="güven düzeyi")
    mu0: float | None = Field(None, description="tek örneklem t-testi için hipotez ortalaması")
    veri2: list[float] = Field(default_factory=list, description="ikinci örnek (iki örneklem Welch t-testi)")


def istatistik(g: IstatistikGirdi) -> Sonuc:
    from scipy import stats

    x = np.array(g.veri, float)
    n = len(x)
    if n < 2:
        raise HesapHatasi("En az 2 gözlem gerekir")
    m, s = float(x.mean()), float(x.std(ddof=1))
    se = s / math.sqrt(n)
    t = float(stats.t.ppf(1 - (1 - g.guven) / 2, n - 1))
    lo, hi = m - t * se, m + t * se
    adimlar = [f"n = {n}, ortalama = {_s(m)}, s = {_s(s)}, ortalamanın standart hatası = s/√n = {_s(se)}",
               f"%{_s(g.guven * 100)} güven aralığı: x̄ ± t(α/2, {n - 1})·s/√n = {_s(m)} ± {_s(t, 4)}·{_s(se)} = [{_s(lo)}, {_s(hi)}]"]
    sayi: dict[str, Any] = {"n": n, "ortalama": _yuvarla(m), "ss": _yuvarla(s), "GA_alt": _yuvarla(lo), "GA_ust": _yuvarla(hi)}
    if g.mu0 is not None:
        r = stats.ttest_1samp(x, g.mu0)
        sayi.update(t=_yuvarla(float(r.statistic)), p_degeri=_yuvarla(float(r.pvalue)))
        adimlar.append(f"Tek örneklem t-testi (H0: μ = {_s(g.mu0)}): t = {_s(float(r.statistic), 4)}, p = {_s(float(r.pvalue), 5)}")
    if len(g.veri2) >= 2:
        r = stats.ttest_ind(x, np.array(g.veri2, float), equal_var=False)
        sayi.update(welch_t=_yuvarla(float(r.statistic)), welch_p=_yuvarla(float(r.pvalue)))
        adimlar.append(f"İki örneklem Welch t-testi: t = {_s(float(r.statistic), 4)}, p = {_s(float(r.pvalue), 5)}")
    return Sonuc(arac="istatistik", baslik="Temel istatistik ve t-testi", sayilar=sayi, adimlar=adimlar)


# ================================================================ 9) Öğrenme eğrisi, başabaş, mühendislik ekonomisi
class OgrenmeGirdi(BaseModel):
    t1: float = Field(description="ilk birimin süresi/maliyeti")
    oran: float = Field(description="öğrenme oranı, ör. 0.80 (%80)")
    n: int = Field(description="istenen birim numarası")


def ogrenme_egrisi(g: OgrenmeGirdi) -> Sonuc:
    if not (0 < g.oran < 1) or g.n < 1 or g.t1 <= 0:
        raise HesapHatasi("Oran 0-1 arasında, n ≥ 1, t1 > 0 olmalı")
    b = math.log(g.oran) / math.log(2)
    tn = g.t1 * g.n ** b
    kum = sum(g.t1 * k ** b for k in range(1, g.n + 1))
    adimlar = [f"Wright modeli: T_n = T1·n^b, b = ln(oran)/ln 2 = {_s(b, 5)}",
               f"T_{g.n} = {_s(g.t1)}·{g.n}^{_s(b, 4)} = {_s(tn)}",
               f"İlk {g.n} birimin toplamı = {_s(kum)}; ortalama = {_s(kum / g.n)}"]
    return Sonuc(arac="ogrenme_egrisi", baslik="Öğrenme eğrisi", sayilar={"b": _yuvarla(b), "Tn": _yuvarla(tn),
                 "kumulatif": _yuvarla(kum), "ortalama": _yuvarla(kum / g.n)}, adimlar=adimlar)


class BasabasGirdi(BaseModel):
    sabit_maliyet: float
    birim_fiyat: float
    birim_degisken_maliyet: float
    hedef_kar: float = Field(0.0, description="istenen kâr (varsa)")


def basabas(g: BasabasGirdi) -> Sonuc:
    kat = g.birim_fiyat - g.birim_degisken_maliyet
    if kat <= 0:
        raise HesapHatasi("Birim katkı payı pozitif değil")
    q = g.sabit_maliyet / kat
    adimlar = [f"Birim katkı payı = {_s(g.birim_fiyat)} − {_s(g.birim_degisken_maliyet)} = {_s(kat)}",
               f"Başabaş miktarı = sabit/katkı = {_s(g.sabit_maliyet)}/{_s(kat)} = {_s(q)}",
               f"Başabaş geliri = {_s(q * g.birim_fiyat)}"]
    sayi = {"katki": _yuvarla(kat), "basabas_miktar": _yuvarla(q), "basabas_gelir": _yuvarla(q * g.birim_fiyat)}
    if g.hedef_kar:
        qk = (g.sabit_maliyet + g.hedef_kar) / kat
        sayi["hedef_kar_miktari"] = _yuvarla(qk)
        adimlar.append(f"{_s(g.hedef_kar)} kâr için miktar = (sabit + kâr)/katkı = {_s(qk)}")
    return Sonuc(arac="basabas", baslik="Başabaş analizi", sayilar=sayi, adimlar=adimlar)


class NBDGirdi(BaseModel):
    nakit_akislari: list[float] = Field(description="t=0'dan başlayan net nakit akışları (yatırım negatif)")
    faiz: float = Field(description="MARR / iskonto oranı, ör. 0.10")


def nbd_igo(g: NBDGirdi) -> Sonuc:
    from scipy.optimize import brentq

    cf, i = g.nakit_akislari, g.faiz
    if len(cf) < 2:
        raise HesapHatasi("En az iki dönemlik nakit akışı gerekir")
    f = lambda r: sum(v / (1 + r) ** t for t, v in enumerate(cf))  # noqa: E731
    nbd = f(i)
    adimlar = [f"NBD = Σ A_t/(1+i)^t, i = {_s(i)}: " + " + ".join(f"{_s(v)}/{_s(1 + i, 4)}^{t}" for t, v in enumerate(cf)),
               f"NBD = {_s(nbd)} → " + ("kabul (NBD > 0)" if nbd > 0 else "ret (NBD < 0)" if nbd < 0 else "kayıtsız")]
    sayi: dict[str, Any] = {"NBD": _yuvarla(nbd)}
    n = len(cf) - 1
    if i > 0:
        yd = nbd * i * (1 + i) ** n / ((1 + i) ** n - 1)
        sayi["yillik_deger"] = _yuvarla(yd)
        adimlar.append(f"Eşdeğer yıllık değer (EUAW) = NBD·(A/P, i, n) = {_s(yd)}")
    igo = None
    try:
        igo = brentq(f, -0.99, 10.0)
    except ValueError:
        pass
    if igo is not None:
        sayi["IGO"] = _yuvarla(igo)
        adimlar.append(f"İç getiri oranı (NBD = 0 yapan i) = %{_s(igo * 100, 3)} → " + ("MARR'dan büyük, kabul" if igo > i else "MARR'dan küçük, ret"))
    else:
        adimlar.append("İç getiri oranı bulunamadı (nakit akışı işaret değiştirmiyor).")
    kum, geri = 0.0, None
    for t, v in enumerate(cf):
        onceki = kum
        kum += v
        if geri is None and kum >= 0 and t > 0:
            geri = t - 1 + (-onceki / v if v else 0)
    if geri is not None:
        sayi["geri_odeme"] = _yuvarla(geri)
        adimlar.append(f"İskontosuz geri ödeme süresi ≈ {_s(geri, 3)} dönem")
    return Sonuc(arac="nbd_igo", baslik="Mühendislik ekonomisi: NBD ve İGO", sayilar=sayi, adimlar=adimlar)


# ================================================================ 10) MRP
class MRPMalzeme(BaseModel):
    ad: str
    stok: float = 0
    tedarik_suresi: int = Field(0, description="hafta")
    parti: Literal["L4L", "FOQ", "EOQ", "SM", "WW"] = Field("L4L", description="L4L, FOQ (sabit miktar), EOQ, SM (Silver-Meal), WW (Wagner-Whitin)")
    parti_miktari: float = Field(0, description="FOQ için sabit parti")
    siparis_maliyeti: float = Field(0, description="EOQ/SM/WW için sipariş maliyeti S")
    elde_tutma: float = Field(0, description="EOQ/SM/WW için birim-hafta elde tutma maliyeti h")
    emniyet_stogu: float = 0
    planlanan_alimlar: dict[str, float] = Field(default_factory=dict, description="{'hafta': miktar} kesinleşmiş siparişler")


class MRPBilesen(BaseModel):
    ust: str
    bilesen: str
    adet: float = 1


class MRPGirdi(BaseModel):
    urun: str = Field(description="ana (mamul) ürün adı")
    ana_cizelge: list[float] = Field(description="ana üretim çizelgesi: haftalık brüt ihtiyaç (1. haftadan)")
    bom: list[MRPBilesen] = Field(description="ürün ağacı: üst → bileşen × adet")
    malzemeler: list[MRPMalzeme] = Field(default_factory=list, description="stok/tedarik/parti bilgisi (verilmeyen malzeme: stok 0, süre 0, L4L)")


def _parti_planla(N: list[float], m: MRPMalzeme) -> list[float]:
    """Net ihtiyaç dizisinden (sıfır tabanlı) planlanan sipariş girişlerini üretir: SM ve WW."""
    T = len(N)
    S, h = m.siparis_maliyeti, m.elde_tutma
    out = [0.0] * T
    if m.parti == "SM":
        t = 0
        while t < T:
            if N[t] <= 0:
                t += 1
                continue
            k, tut, onceki = t, 0.0, float(S)
            while k + 1 < T:
                yeni_tut = tut + h * (k + 1 - t) * N[k + 1]
                ort = (S + yeni_tut) / (k + 2 - t)
                if ort > onceki:
                    break
                k, tut, onceki = k + 1, yeni_tut, ort
            out[t] = sum(N[t:k + 1])
            t = k + 1
        return out
    # Wagner-Whitin dinamik programlama
    f = [0.0] + [math.inf] * T
    kaynak = [0] * (T + 1)
    for j in range(1, T + 1):
        for i in range(1, j + 1):
            maliyet = f[i - 1] + S + h * sum((k - i) * N[k - 1] for k in range(i, j + 1))
            if maliyet < f[j]:
                f[j], kaynak[j] = maliyet, i
    j = T
    while j > 0:
        i = kaynak[j]
        out[i - 1] = sum(N[i - 1:j])
        j = i - 1
    # talebi olmayan başlangıç haftalarında sipariş açma: ilk talebe kaydır
    for t in range(T):
        if out[t] > 0 and N[t] <= 0:
            k = next((k for k in range(t, T) if N[k] > 0), None)
            if k is not None:
                out[k] += out[t]
                out[t] = 0.0
    return out


def mrp_malzeme_plani(brut: list[float], m: MRPMalzeme) -> dict:
    """Tek malzeme için MRP kaydı: brüt → net → planlanan sipariş girişi/çıkışı."""
    T = len(brut)
    sr = [0.0] * T
    for k, v in (m.planlanan_alimlar or {}).items():
        try:
            w = int(k)
        except ValueError:
            continue
        if 1 <= w <= T:
            sr[w - 1] += float(v)
    q_sabit = m.parti_miktari
    if m.parti == "EOQ":
        ort = sum(brut) / T if T else 0
        if m.siparis_maliyeti > 0 and m.elde_tutma > 0 and ort > 0:
            q_sabit = math.ceil(math.sqrt(2 * ort * m.siparis_maliyeti / m.elde_tutma))
    # 1) sıralı net ihtiyaç (parti kuralı uygulanmadan: eldeki stok + kesinleşmiş alımlar)
    oh = m.stok
    net_dizi = []
    for t in range(T):
        gerek = brut[t] + m.emniyet_stogu - (oh + sr[t])
        n = max(0.0, gerek)
        net_dizi.append(n)
        oh = oh + sr[t] - brut[t] + n  # L4L varsayımıyla ilerlet
    por = [0.0] * T
    net = [0.0] * T
    if m.parti in ("SM", "WW"):
        por = _parti_planla(net_dizi, m)
        net = net_dizi
    else:
        oh = m.stok
        for t in range(T):
            gerek = brut[t] + m.emniyet_stogu - (oh + sr[t])
            if gerek > 1e-9:
                net[t] = gerek
                if m.parti in ("FOQ", "EOQ") and q_sabit > 0:
                    por[t] = math.ceil(gerek / q_sabit - 1e-9) * q_sabit
                else:
                    por[t] = gerek
            oh = oh + sr[t] + por[t] - brut[t]
    proj, oh = [], m.stok
    for t in range(T):
        oh = oh + sr[t] + por[t] - brut[t]
        proj.append(oh)
    cikis = [0.0] * T
    gecikmis = 0.0
    for t in range(T):
        if por[t] > 0:
            r = t - int(m.tedarik_suresi)
            if r < 0:
                gecikmis += por[t]
                r = 0  # geçmişe düşen sipariş: 1. haftaya çekilir (acil) ve uyarılır
            cikis[r] += por[t]
    return {"ad": m.ad, "brut": brut, "planlanan_alim": sr, "net": net, "planlanan_siparis_girisi": por,
            "planlanan_siparis_cikisi": cikis, "eldeki_stok": proj, "gecikmis_siparis": gecikmis, "q": q_sabit}


def mrp_patlat(g: MRPGirdi) -> Sonuc:
    T = len(g.ana_cizelge)
    if T == 0:
        raise HesapHatasi("Ana üretim çizelgesi boş")
    mal = {m.ad: m for m in g.malzemeler}
    ust_bilesen: dict[str, list[MRPBilesen]] = {}
    for b in g.bom:
        ust_bilesen.setdefault(b.ust, []).append(b)
    # düşük seviye kodu (en derin seviye)
    seviye: dict[str, int] = {g.urun: 0}

    def derinles(a: str, d: int, yol: tuple):
        if a in yol:
            raise HesapHatasi("Ürün ağacında döngü var")
        seviye[a] = max(seviye.get(a, 0), d)
        for b in ust_bilesen.get(a, []):
            derinles(b.bilesen, d + 1, yol + (a,))

    derinles(g.urun, 0, ())
    sira = sorted(seviye, key=lambda a: (seviye[a], a))
    brut = {a: [0.0] * T for a in sira}
    brut[g.urun] = [float(x) for x in g.ana_cizelge]
    plan: dict[str, dict] = {}
    adimlar = ["MRP: seviye seviye (düşük seviye koduna göre) patlatılır: brüt → net → parti → tedarik süresi kadar öne çekme.",
               "Net ihtiyaç = brüt + emniyet stoku − (eldeki stok + kesinleşmiş alım). Ana ürünün planlanan sipariş çıkışı bileşenlerin brüt ihtiyacını belirler."]
    for a in sira:
        m = mal.get(a) or MRPMalzeme(ad=a)
        p = mrp_malzeme_plani(brut[a], m)
        plan[a] = p
        for b in ust_bilesen.get(a, []):
            for t in range(T):
                brut[b.bilesen][t] += p["planlanan_siparis_cikisi"][t] * b.adet
        adimlar.append(f"Seviye {seviye[a]} — {a} (stok {_s(m.stok)}, tedarik {m.tedarik_suresi} hf, parti {m.parti}"
                       + (f"={_s(p['q'])}" if m.parti in ('FOQ', 'EOQ') else "") + ")")
        adimlar.append("   brüt:   " + _satir(p["brut"]))
        adimlar.append("   net:    " + _satir(p["net"]))
        adimlar.append("   plan. sipariş girişi: " + _satir(p["planlanan_siparis_girisi"]))
        adimlar.append("   plan. sipariş çıkışı: " + _satir(p["planlanan_siparis_cikisi"]))
        if p["gecikmis_siparis"] > 0:
            adimlar.append(f"   UYARI: {_s(p['gecikmis_siparis'])} birimlik sipariş tedarik süresi yüzünden 1. haftadan önce verilmeliydi (acil).")
    sayi = {a: _yuvarla({k: v for k, v in p.items() if k != "ad"}) for a, p in plan.items()}
    return Sonuc(arac="mrp", baslik="MRP patlatma", sayilar={"plan": sayi, "seviyeler": seviye}, adimlar=adimlar)


def _satir(v: list[float]) -> str:
    return "[" + ", ".join(_s(x, 2) for x in v) + "]"


# ================================================================ kayıt ve çalıştırma
@dataclass
class Arac:
    ad: str
    aciklama: str
    sema: type[BaseModel]
    fn: Callable[[Any], Sonuc]


ARACLAR: dict[str, Arac] = {a.ad: a for a in [
    Arac("dogrusal_programlama", "doğrusal/tam sayılı/0-1 programlama (max/min, ≤ = kısıtlar, gölge fiyat)", DPGirdi, dogrusal_programlama),
    Arac("ulastirma", "ulaştırma problemi (arz, talep, birim maliyet matrisi)", UlastirmaGirdi, ulastirma),
    Arac("atama", "atama problemi (Macar yöntemi)", AtamaGirdi, atama),
    Arac("johnson", "2 makineli akış tipi çizelgeleme, Johnson kuralı", JohnsonGirdi, johnson),
    Arac("tek_makine", "tek makine çizelgeleme SPT/EDD, gecikme", TekMakineGirdi, tek_makine),
    Arac("cpm", "CPM/PERT: kritik yol, bolluk, proje süresi, olasılık", CPMGirdi, cpm),
    Arac("eoq", "EOQ, yeniden sipariş noktası, emniyet stoku, (Q,r)", EOQGirdi, eoq),
    Arac("kuyruk", "M/M/1 ve M/M/c kuyruk (Erlang C)", KuyrukGirdi, kuyruk),
    Arac("simulasyon", "tek sunuculu kuyruk kesikli olay benzetimi", SimGirdi, simulasyon),
    Arac("kontrol_karti", "X̄-R, p, c kontrol kartı sınırları", KontrolKartiGirdi, kontrol_karti),
    Arac("yeterlilik", "süreç yeterliliği Cp, Cpk, ppm", YeterlilikGirdi, yeterlilik),
    Arac("istatistik", "ortalama, ss, güven aralığı, t-testi", IstatistikGirdi, istatistik),
    Arac("ogrenme_egrisi", "öğrenme eğrisi (Wright)", OgrenmeGirdi, ogrenme_egrisi),
    Arac("basabas", "başabaş analizi", BasabasGirdi, basabas),
    Arac("nbd_igo", "mühendislik ekonomisi: NBD, İGO, geri ödeme", NBDGirdi, nbd_igo),
    Arac("mrp", "MRP patlatma: BOM + ana çizelge + stok + tedarik süresi + parti (L4L/FOQ/EOQ/SM/WW)", MRPGirdi, mrp_patlat),
]}


def _alan_ozeti(model: type[BaseModel]) -> str:
    parcalar = []
    for ad, f in model.model_fields.items():
        parcalar.append(f"{ad} ({f.description})" if f.description else ad)
    return "; ".join(parcalar)


def arac_listesi_metni() -> str:
    """Modele gösterilen kısa araç listesi ve şemaları."""
    return "\n".join(f"- {a.ad}: {a.aciklama}. Alanlar: {_alan_ozeti(a.sema)}" for a in ARACLAR.values())


def calistir(ad: str, girdiler: dict | str) -> Sonuc:
    arac = ARACLAR.get(ad)
    if arac is None:
        raise HesapHatasi(f"Bilinmeyen araç: {ad}")
    if isinstance(girdiler, str):
        try:
            girdiler = json.loads(girdiler)
        except json.JSONDecodeError as e:
            raise HesapHatasi("Girdiler geçerli JSON değil") from e
    if not isinstance(girdiler, dict):
        raise HesapHatasi("Girdiler bir nesne olmalı")
    try:
        g = arac.sema.model_validate(girdiler)
    except ValidationError as e:
        raise HesapHatasi("Girdi geçersiz/eksik: " + "; ".join(f"{'.'.join(map(str, x['loc']))}" for x in e.errors()[:4])) from e
    try:
        return arac.fn(g)
    except HesapHatasi:
        raise
    except (ArithmeticError, ValueError, TypeError, IndexError, KeyError) as e:
        raise HesapHatasi(f"Hesaplanamadı: {e}") from e


def sonuc_metni(s: Sonuc) -> str:
    return f"{s.baslik}\nSayılar: {json.dumps(s.sayilar, ensure_ascii=False)}\nAdımlar:\n" + "\n".join(s.adimlar)
