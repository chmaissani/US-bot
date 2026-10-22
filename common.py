"""
الإعدادات والبيانات والمؤشرات المشتركة بين البوت (bot.py) وأداة الاختبار (backtest.py).
"""
import time

import requests

# ---------------- الإعدادات ----------------
# أسهم المضاربة (سوينغ): أسهم أمريكية كبيرة وسيولتها عالية وتتحرك بقوة
SWING = [
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "AMD", "MU",
    "LRCX", "AMAT", "KLAC", "MRVL", "QCOM", "INTC", "TXN", "ADI", "ON", "SMCI",
    "ARM", "TSM", "ASML", "ORCL", "CRM", "NOW", "ADBE", "PANW", "CRWD", "FTNT",
    "SNOW", "PLTR", "NET", "DDOG", "ZS", "SHOP", "UBER", "DASH", "ABNB", "BKNG",
    "NFLX", "RDDT", "COIN", "MSTR", "HOOD", "SOFI", "PYPL", "XYZ", "ROKU", "DKNG",
    "RBLX", "LLY", "NVO", "ISRG", "VRTX", "REGN", "BA", "GE", "GEV", "CAT",
    "DE", "XOM", "OXY", "FCX", "NEM", "VRT", "ANET", "CEG", "STX", "DELL",
]
# أسهم الاستثمار طويل الأمد: شركات كبيرة راسخة + صناديق مؤشرات
INVEST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "AVGO", "TSM", "ASML", "LLY",
    "V", "MA", "COST", "WMT", "JNJ", "PG", "KO", "PEP", "HD", "MCD",
    "UNH", "ISRG", "ADBE", "ORCL", "TXN", "LIN", "SPGI", "BRK-B", "ABBV", "MRK",
]
INVEST_ETF = ["SPY", "QQQ", "SPUS", "HLAL"]
MARKET = "SPY"   # فلتر السوق: لا صفقات شراء جديدة إلا والسوق العام صاعد

# مكوّنات صندوق SP Funds S&P 500 Sharia (SPUS) بتاريخ 22/10/2026 — تُستخدم لعلامة ☪️
# المصدر: https://www.sp-funds.com/spus/ (القائمة تتغير كل ربع سنة، حدّثها من نفس الرابط)
SHARIAH_ASOF = "22/10/2026"
SHARIAH = set("""
NVDA AAPL MSFT GOOGL AVGO TSLA MU LLY AMD XOM JNJ ABBV CSCO MRK PG LRCX AMAT HD PANW TXN TMO GEV
CRWD IBM LIN ORCL MRVL KLAC SNDK CRM ADI ANET GILD PEP QCOM COP ABT UNP WELL TJX NOW STX ISRG DHR
ACN UBER VRTX NEM MCK BKNG FTNT MDT LOW TT GLW ADBE SYK FCX EQIX JCI CSX EMR MMM CDNS SNPS PWR WM
CEG EOG MDLZ VRT ROST REGN SLB CL SHW NSC LITE UPS ORLY CMI CTAS ITW ECL DASH BE TGT BSX APD MNST
COR URI CAH NUE MPWR FAST TEL NXPI CRH BDX TER EW GWW CIEN ADSK A EBAY AZO GRMN RSG FIX CARR ROK
NKE WAB OXY WDAY P WAT ROP MCHP FERG COHR ILMN NTAP IDXX ADM TWLO DHI KVUE FANG KMB STLD BIIB ODFL
VMC CTSH RMD HAL ON FLEX EXPE DXCM JBL GEHC WSM MTD EXPD MLM CHD IR FFIV OTIS DOV LH XYL PPG CPRT
ULTA Q HSY WST VRSN EL VLTO PHM TPR PTC HUBB PKG BBY RVTY CF DD RDDT CDW TPL NDSN INCY STE FSLR
JBHT EFX CSGP CRL IEX CHRW TSCO ZBRA IT WY MAS GPC GDDY AVY TRMB TYL FICO ALB RL LULU MKC LII COO
DECK GNRC ALLE SWKS TECH FDXF AOS ALGN ROL PODD PNR SPUS HLAL
""".split())

# استراتيجية المضاربة (شموع يومية): اختراق قمة 50 يوم لسهم قوي + وقف متحرك
# اختُبرت على 10 سنوات و70 سهماً: 2016–2022 متوسط +1.68% للصفقة (PF 1.49)، 2023–2026 متوسط +3.22% (PF 1.76)
BREAKOUT_DAYS = 50      # الإغلاق عند أعلى مستوى في 50 يوماً
VOL_MULT = 1.5          # حجم التداول 1.5 ضعف متوسط 20 يوماً على الأقل
RS_MIN = 0.7            # من أقوى 30% من الأسهم بأداء آخر 6 أشهر
STOP_ATR = 2.5          # الوقف الأولي تحت سعر الدخول
TRAIL_ATR = 3.0         # الوقف المتحرك: 3 أضعاف ATR تحت أعلى إغلاق منذ الدخول
MAX_DAYS = 40           # أقصى مدة للصفقة بأيام التداول

# (الاستراتيجية القديمة: تصحيح داخل اتجاه صاعد — أضعف في الاختبار، تُركت للمقارنة)
RSI_LEVEL = 40          # RSI(14) نزل تحت هذا المستوى خلال آخر 5 أيام ثم ارتد فوقه
MIN_ADX = 20            # أقل قوة اتجاه
SL_ATR = (1.5, 2.5)     # الوقف بين 1.5 و 2.5 ضعف ATR خلف قاع آخر 10 أيام
TP_R = (1, 2, 4)        # الأهداف كمضاعفات للمخاطرة
MAX_GAP_R = 0.5         # إلغاء التوصية إذا افتتح السهم بفجوة أكبر من نصف المخاطرة
TTL_DAYS = 15           # أقصى مدة للصفقة بأيام التداول
COOLDOWN_DAYS = 3       # انتظار بعد إغلاق صفقة قبل فتح جديدة على نفس السهم
EARNINGS_DAYS = 7       # لا توصية إذا كانت نتائج الشركة خلال هذه الأيام


# ---------------- البيانات ----------------
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}


def yahoo(ticker, interval="1d", rng="2y", tries=3):
    """شموع من Yahoo: [[وقت الفتح ms, open, high, low, close, volume], ...] من الأقدم للأحدث."""
    last = None
    for attempt in range(tries):
        for host in ("query1", "query2"):
            try:
                r = requests.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{ticker}",
                                 params={"interval": interval, "range": rng, "includePrePost": "false"},
                                 headers=UA, timeout=20)
                if r.status_code == 429:
                    last = "429"
                    continue
                r.raise_for_status()
                res = r.json()["chart"]["result"][0]
                q = res["indicators"]["quote"][0]
                out = []
                for i, t in enumerate(res.get("timestamp") or []):
                    o, h, l, c, v = (q[k][i] for k in ("open", "high", "low", "close", "volume"))
                    if None in (o, h, l, c):
                        continue
                    out.append([int(t) * 1000, float(o), float(h), float(l), float(c), float(v or 0)])
                if out:
                    return out
                last = "empty"
            except Exception as e:  # noqa: BLE001
                last = type(e).__name__
        time.sleep(1.5 * (attempt + 1))
    return stooq(ticker) if interval == "1d" else _fail(ticker, last)


def stooq(ticker):
    """بديل للشموع اليومية إذا فشل Yahoo."""
    sym = ticker.lower().replace("-", ".") + ".us"
    r = requests.get("https://stooq.com/q/d/l/", params={"s": sym, "i": "d"}, headers=UA, timeout=20)
    rows = r.text.strip().splitlines()[1:] if r.ok else []
    out = []
    for row in rows:
        p = row.split(",")
        if len(p) < 6:
            continue
        try:
            t = int(time.mktime(time.strptime(p[0], "%Y-%m-%d"))) * 1000
            out.append([t, float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5] or 0)])
        except ValueError:
            continue
    return out[-600:] if out else _fail(ticker, "stooq")


def _fail(ticker, why):
    raise RuntimeError(f"no data for {ticker} ({why})")


def earnings_soon(days=EARNINGS_DAYS):
    """الأسهم التي تعلن نتائجها خلال الأيام القادمة (من تقويم ناسداك). يرجع set أو None إذا فشل."""
    found, ok = set(), False
    for d in range(days + 1):
        day = time.strftime("%Y-%m-%d", time.gmtime(time.time() + d * 86400))
        try:
            r = requests.get("https://api.nasdaq.com/api/calendar/earnings", params={"date": day},
                             headers={**UA, "Accept": "application/json"}, timeout=15)
            rows = ((r.json().get("data") or {}).get("rows")) or []
            ok = ok or r.ok
            found.update(x.get("symbol", "").upper() for x in rows)
        except Exception:  # noqa: BLE001
            continue
    return found if ok else None


# ---------------- المؤشرات ----------------
def sma(a, n):
    out, s = [None] * len(a), 0.0
    for i, v in enumerate(a):
        s += v
        if i >= n:
            s -= a[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(a, n):
    k, o, e = 2 / (n + 1), [], None
    for i, v in enumerate(a):
        e = v if i == 0 else v * k + e * (1 - k)
        o.append(e)
    return o


def rsi(c, n=14):
    o = [50.0] * len(c)
    if len(c) <= n:
        return o
    g = l = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]
        g += max(d, 0); l += max(-d, 0)
    g /= n; l /= n
    o[n] = 100 - 100 / (1 + (g / l if l else 1e9))
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l = (l * (n - 1) + max(-d, 0)) / n
        o[i] = 100 - 100 / (1 + (g / l if l else 1e9))
    return o


def atr_series(h, l, c, n=14):
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    o = [None] * len(c)
    if len(c) < n:
        return o
    a = sum(tr[:n]) / n; o[n - 1] = a
    for i in range(n, len(tr)):
        a = (a * (n - 1) + tr[i]) / n; o[i] = a
    return o


def adx_series(h, l, c, n=14):
    o = [0.0] * len(c)
    tr, pdm, ndm = [0.0], [0.0], [0.0]
    for i in range(1, len(c)):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm.append(up if up > dn and up > 0 else 0.0)
        ndm.append(dn if dn > up and dn > 0 else 0.0)
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    if len(c) <= 2 * n:
        return o
    a_tr, p, m = sum(tr[1:n + 1]), sum(pdm[1:n + 1]), sum(ndm[1:n + 1])
    dxs, val = [], 0.0
    for i in range(n + 1, len(c)):
        a_tr = a_tr - a_tr / n + tr[i]; p = p - p / n + pdm[i]; m = m - m / n + ndm[i]
        pdi = 100 * p / a_tr if a_tr else 0; mdi = 100 * m / a_tr if a_tr else 0
        dx = 100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0
        if len(dxs) < n:
            dxs.append(dx); val = sum(dxs) / len(dxs)
        else:
            val = (val * (n - 1) + dx) / n
        o[i] = val
    return o


class Ind:
    """كل المؤشرات اليومية لسهم واحد، محسوبة مرة واحدة."""
    def __init__(self, cs):
        self.t = [x[0] for x in cs]; self.o = [x[1] for x in cs]; self.h = [x[2] for x in cs]
        self.l = [x[3] for x in cs]; self.c = [x[4] for x in cs]; self.v = [x[5] for x in cs]
        self.sma50 = sma(self.c, 50); self.sma200 = sma(self.c, 200)
        self.rsi = rsi(self.c); self.atr = atr_series(self.h, self.l, self.c)
        self.adx = adx_series(self.h, self.l, self.c)


def market_ok(m, i):
    """السوق العام (SPY) صاعد: السعر فوق متوسط 200 ومتوسط 50 فوق متوسط 200."""
    if i is None or m.sma200[i] is None:
        return False
    return m.c[i] > m.sma200[i] and m.sma50[i] > m.sma200[i]


def swing_setup(s, i, mkt_ok, diag=None, rsi_level=RSI_LEVEL, min_adx=MIN_ADX):
    """إعداد المضاربة على شمعة اليوم i المغلقة. يرجع dict أو None (والسبب في diag['why'])."""
    diag = {} if diag is None else diag
    if i < 210 or s.sma200[i] is None or s.atr[i] is None:
        diag["why"] = "data"; return None
    px = s.c[i]
    if not mkt_ok:
        diag["why"] = "market"; return None
    if not (px > s.sma200[i] and s.sma50[i] > s.sma200[i]):
        diag["why"] = "no_trend"; return None
    if s.adx[i] < min_adx:
        diag["why"] = "weak"; return None
    dipped = min(s.rsi[i - 5:i]) < rsi_level
    if not dipped:
        diag["why"] = "no_pullback"; return None
    if not (s.rsi[i] > s.rsi[i - 1] and s.rsi[i] >= rsi_level):
        diag["why"] = "near"; return None
    at = s.atr[i]
    lo = min(s.l[i - 9:i + 1])
    smin, smax = SL_ATR
    sl = min(px - smin * at, max(lo - 0.2 * at, px - smax * at))
    r = px - sl
    diag["why"] = "signal"
    return {"entry": px, "sl": sl, "r": r, "tp": [px + k * r for k in TP_R], "atr": at,
            "adx": s.adx[i], "rsi": s.rsi[i], "dip": min(s.rsi[i - 5:i]),
            "sma50": s.sma50[i], "sma200": s.sma200[i]}


def rs_ranks(series):
    """ترتيب القوة النسبية (عائد 126 يوماً) بين الأسهم على آخر يوم: {رمز: 0..1}."""
    rets = []
    for sym, s in series.items():
        if len(s.c) > 127:
            rets.append((s.c[-1] / s.c[-127] - 1, sym))
    rets.sort()
    n = len(rets)
    return {sym: k / max(1, n - 1) for k, (_, sym) in enumerate(rets)}


def breakout_setup(s, i, mkt_ok, rs, diag=None):
    """إشارة الاختراق على شمعة اليوم i المغلقة. rs = ترتيب قوة السهم (0..1)."""
    diag = {} if diag is None else diag
    if i < 210 or s.sma200[i] is None or s.atr[i] is None:
        diag["why"] = "data"; return None
    vma = sum(s.v[i - 20:i]) / 20
    c = s.c[i]
    if not mkt_ok:
        diag["why"] = "market"; return None
    if c <= s.sma200[i]:
        diag["why"] = "no_trend"; return None
    if rs is None or rs < RS_MIN:
        diag["why"] = "weak_rs"; return None
    hi = max(s.c[i - BREAKOUT_DAYS:i])
    if c < hi:
        diag["why"] = "near" if c >= 0.97 * hi else "no_breakout"; return None
    if not vma or s.v[i] < VOL_MULT * vma:
        diag["why"] = "low_volume"; return None
    diag["why"] = "signal"
    return {"close": c, "atr": s.atr[i], "rs": rs, "vol_x": s.v[i] / vma, "hi50": hi,
            "ret6m": (c / s.c[i - 126] - 1) * 100}


def weekly_rsi(s, n=14):
    """RSI أسبوعي من الشموع اليومية (آخر إغلاق لكل أسبوع)."""
    weeks, last_key = [], None
    for t, c in zip(s.t, s.c):
        key = time.strftime("%G-%V", time.gmtime(t / 1000))
        if key != last_key:
            weeks.append(c); last_key = key
        else:
            weeks[-1] = c
    r = rsi(weeks, n)
    return r[-1] if len(weeks) > n else None


def invest_zone(s):
    """تصنيف السهم للمستثمر طويل الأمد. يرجع (رمز المنطقة، تفاصيل)."""
    i = len(s.c) - 1
    if s.sma200[i] is None or i < 220:
        return "na", {}
    px = s.c[i]
    hi52 = max(s.h[max(0, i - 251):i + 1])
    dd = (px / hi52 - 1) * 100
    slope_up = s.sma200[i] > s.sma200[i - 20]
    wr = weekly_rsi(s)
    vs200 = (px / s.sma200[i] - 1) * 100
    ret1y = (px / s.c[max(0, i - 251)] - 1) * 100
    info = {"px": px, "dd": dd, "vs200": vs200, "wrsi": wr, "ret1y": ret1y, "hi52": hi52}
    if not slope_up and px < s.sma200[i]:
        return "down", info
    if (wr is not None and wr >= 75) or vs200 >= 30:
        return "hot", info
    if slope_up and px >= 0.9 * s.sma200[i] and (-30 <= dd <= -8 or (wr is not None and wr <= 45)):
        return "buy", info
    return "hold", info


def fmt(p):
    return f"{p:,.2f}"


def pct(v):
    return f"{v:+.2f}%"
