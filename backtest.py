"""
مقارنة استراتيجيات مضاربة (سوينغ) على 10 سنوات من البيانات اليومية الحقيقية، بنفس قواعد التنفيذ:
إشارة عند الإغلاق ← دخول عند افتتاح اليوم التالي ← عمولة وانزلاق 0.1%.
الحكم على بيانات «خارج العينة»: نختار على 2016–2022 ونتأكد على 2023 حتى اليوم.
يرسل النتيجة على تيليغرام.
"""
import os
import sys
import time
from datetime import datetime, timezone

from common import SWING, MARKET, Ind, yahoo, market_ok, sma, rsi

FEE = 0.001
SPLIT = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000


def load_all():
    data = {}
    for sym in [MARKET] + SWING:
        try:
            s = Ind(yahoo(sym, "1d", "10y"))
            s.rsi2 = rsi(s.c, 2)
            s.sma5 = sma(s.c, 5)
            s.sma20 = sma(s.c, 20)
            s.vma20 = sma(s.v, 20)
            data[sym] = s
            print(f"{sym}: {len(s.c)} days")
        except Exception as e:  # noqa: BLE001
            print(f"{sym}: {e}")
        time.sleep(0.2)
    return data


def rs_rank(data):
    """قوة نسبية: ترتيب عائد 6 أشهر لكل سهم بين كل الأسهم في نفس اليوم (0 = الأضعف، 1 = الأقوى)."""
    by_t = {}
    for sym, s in data.items():
        if sym == MARKET:
            continue
        for i in range(126, len(s.c)):
            by_t.setdefault(s.t[i], []).append((s.c[i] / s.c[i - 126] - 1, sym))
    rank = {}
    for t, lst in by_t.items():
        lst.sort()
        n = len(lst)
        for k, (_, sym) in enumerate(lst):
            rank[(sym, t)] = k / max(1, n - 1)
    return rank


# ---------------- إشارات الدخول ----------------
def entry_signal(kind, s, i, p):
    if s.sma200[i] is None or s.atr[i] is None or i < 210:
        return False
    c = s.c[i]
    if kind == "pullback":   # الاستراتيجية الحالية
        return (c > s.sma200[i] and s.sma50[i] > s.sma200[i] and s.adx[i] >= p.get("adx", 20)
                and min(s.rsi[i - 5:i]) < p.get("lvl", 40) and s.rsi[i] > s.rsi[i - 1] and s.rsi[i] >= p.get("lvl", 40))
    if kind == "rsi2":       # ارتداد قصير بعد هبوط حاد داخل اتجاه صاعد (Connors)
        return c > s.sma200[i] and s.rsi2[i] < p.get("lvl", 10)
    if kind == "dip3":       # 3 أيام هبوط متتالية داخل اتجاه صاعد
        return c > s.sma200[i] and s.c[i] < s.c[i - 1] < s.c[i - 2] < s.c[i - 3] and c < s.sma5[i]
    if kind == "breakout":   # اختراق قمة 50 يوم بحجم تداول مرتفع
        return (c > s.sma200[i] and c >= max(s.c[i - 50:i + 1]) and s.vma20[i - 1]
                and s.v[i] >= p.get("vol", 1.5) * s.vma20[i - 1])
    return False


# ---------------- الخروج ----------------
def simulate(s, i, exit_kind, p):
    """يدخل عند افتتاح i+1. يرجع (نسبة الربح %, عدد الأيام, الربح بوحدات المخاطرة) أو None."""
    n = len(s.c)
    if i + 1 >= n:
        return None
    entry = s.o[i + 1]
    at = s.atr[i]
    stop = entry - p.get("stop_atr", 2.5) * at
    r = entry - stop
    max_days = p.get("days", 10)
    if exit_kind == "targets":                 # الطريقة الحالية: 3 أهداف وتعادل بعد الأول
        tp = [entry + k * r for k in p.get("tps", (1, 2, 4))]
        hits, j, res = 0, i + 1, None
        while j < n and j <= i + max_days:
            if s.l[j] <= stop:
                res = stop; break
            while hits < 3 and s.h[j] >= tp[hits]:
                hits += 1
                if hits == 1:
                    stop = entry
            if hits == 3:
                res = tp[2]; break
            j += 1
        j = min(j, n - 1)
        res = s.c[j] if res is None else res
        gain = sum((tp[k] - entry) / 3 for k in range(min(hits, 3))) + (res - entry) * (1 - min(hits, 3) / 3)
    else:
        j = i + 1
        trail = stop
        res = None
        while j < n:
            if s.l[j] <= trail:
                res = min(trail, s.o[j]); break
            if exit_kind == "sma5" and s.c[j] > s.sma5[j]:          # اخرج عند الإغلاق فوق متوسط 5
                res = s.c[j]; break
            if exit_kind == "trail":                                 # وقف متحرك 3 ATR تحت أعلى إغلاق
                trail = max(trail, max(s.c[i + 1:j + 1]) - 3 * s.atr[j])
            if j - i >= max_days:
                res = s.c[j]; break
            j += 1
        j = min(j, n - 1)
        res = s.c[j] if res is None else res
        gain = res - entry
    return gain / entry * 100 - FEE * 100, j - i, gain / r - FEE * entry / r, j


def run(data, rank, kind, exit_kind, **p):
    m = data[MARKET]
    mi = {t: k for k, t in enumerate(m.t)}
    trades = []
    for sym, s in data.items():
        if sym == MARKET:
            continue
        i, n = 210, len(s.c)
        while i < n - 1:
            if p.get("market", True) and not market_ok(m, mi.get(s.t[i])):
                i += 1; continue
            if p.get("rs") is not None and rank.get((sym, s.t[i]), 0) < p["rs"]:
                i += 1; continue
            if not entry_signal(kind, s, i, p):
                i += 1; continue
            out = simulate(s, i, exit_kind, p)
            if not out:
                break
            pct, days, R, j = out
            trades.append({"t": s.t[i], "pct": pct, "R": R, "days": days})
            i = j + 1
    return trades


def stats(tr):
    if not tr:
        return None
    w = [t for t in tr if t["pct"] > 0]
    gp = sum(t["pct"] for t in w); gl = -sum(t["pct"] for t in tr if t["pct"] <= 0)
    years = max((max(t["t"] for t in tr) - min(t["t"] for t in tr)) / (365.25 * 86400000), 0.5)
    return {"n": len(tr), "pm": len(tr) / years / 12, "win": len(w) / len(tr) * 100,
            "avg": sum(t["pct"] for t in tr) / len(tr), "pf": gp / gl if gl else 99,
            "days": sum(t["days"] for t in tr) / len(tr)}


STRATS = [
    ("الحالية: تصحيح + 3 أهداف", "pullback", "targets", {"days": 15}),
    ("الحالية + أقوى 30% أسهم", "pullback", "targets", {"days": 15, "rs": 0.7}),
    ("RSI2 تحت 10، خروج فوق متوسط 5", "rsi2", "sma5", {"lvl": 10, "days": 10}),
    ("RSI2 تحت 5، خروج فوق متوسط 5", "rsi2", "sma5", {"lvl": 5, "days": 10}),
    ("RSI2 تحت 10 + أقوى 50% أسهم", "rsi2", "sma5", {"lvl": 10, "days": 10, "rs": 0.5}),
    ("RSI2 تحت 10 + أقوى 30% أسهم", "rsi2", "sma5", {"lvl": 10, "days": 10, "rs": 0.7}),
    ("RSI2 تحت 10 + 3 أهداف", "rsi2", "targets", {"lvl": 10, "days": 10, "stop_atr": 2.0}),
    ("3 أيام هبوط، خروج فوق متوسط 5", "dip3", "sma5", {"days": 10}),
    ("3 أيام هبوط + أقوى 30% أسهم", "dip3", "sma5", {"days": 10, "rs": 0.7}),
    ("اختراق قمة 50 يوم + وقف متحرك", "breakout", "trail", {"days": 40}),
    ("اختراق + أقوى 30% + وقف متحرك", "breakout", "trail", {"days": 40, "rs": 0.7}),
]


def main():
    data = load_all()
    if MARKET not in data or len(data) < 20:
        sys.exit("❌ فشل جلب بيانات الأسهم من Yahoo")
    rank = rs_rank(data)
    rows = []
    for name, kind, ex, p in STRATS:
        tr = run(data, rank, kind, ex, **p)
        a = stats([t for t in tr if t["t"] < SPLIT]); b = stats([t for t in tr if t["t"] >= SPLIT])
        rows.append((name, a, b))
        print(name, a, b)

    def f(st):
        if not st:
            return "لا صفقات"
        return f"{st['n']} صفقة ({st['pm']:.1f}/شهر) · نجاح {st['win']:.0f}% · متوسط {st['avg']:+.2f}% · PF {st['pf']:.2f} · {st['days']:.0f} يوم"
    rows.sort(key=lambda r: -(r[2]["avg"] if r[2] else -99))
    out = ["🧪 <b>مقارنة استراتيجيات الأسهم</b>",
           f"‏{len(data) - 1} سهم · 10 سنوات · عمولة 0.1% · الدخول عند افتتاح اليوم التالي",
           "‏مرتبة حسب أدائها على 2023 حتى اليوم (بيانات لم تُستخدم في الاختيار)\n"]
    for k, (name, a, b) in enumerate(rows, 1):
        out.append(f"‏<b>{k}. {name}</b>\n‏   2016–2022: {f(a)}\n‏   2023–الآن: <b>{f(b)}</b>\n")
    m = data[MARKET]
    k0 = next(k for k, t in enumerate(m.t) if t >= SPLIT)
    out.append(f"‏للمقارنة: الاحتفاظ بـ SPY من 2023 حتى الآن {(m.c[-1] / m.c[k0] - 1) * 100:+.0f}%")
    out.append("‏PF = مجموع الأرباح ÷ مجموع الخسائر (فوق 1.3 جيد، تحت 1 خاسر)")
    text = "\n".join(out)
    print(text)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("⚠️ TELEGRAM_BOT_TOKEN غير موجود، النتيجة في السجل فقط"); return
    import bot
    bot.TOKEN, bot.API = token, f"https://api.telegram.org/bot{token}"
    bot.CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "") or bot.discover_chat_id(bot.load_state())
    if not bot.CHAT_ID:
        sys.exit("❌ البوت لا يعرف محادثتك: افتح البوت في تيليغرام واضغط Start، ثم أعد التشغيل. (النتيجة موجودة أعلاه في السجل)")
    if not bot.send(text):
        sys.exit("❌ فشل الإرسال لتيليغرام، تأكد من الـ Token. (النتيجة موجودة أعلاه في السجل)")
    print("✅ أُرسلت النتيجة إلى تيليغرام")


if __name__ == "__main__":
    main()
