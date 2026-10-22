"""
اختبار استراتيجية المضاربة على 10 سنوات من البيانات اليومية الحقيقية، بنفس قواعد البوت تماماً:
إشارة عند الإغلاق ← دخول عند افتتاح اليوم التالي ← إلغاء عند الفجوة الكبيرة ← بيع ثلث عند كل هدف،
ونقل الوقف لسعر الدخول بعد الهدف 1 ← حد أقصى 15 يوم تداول. يرسل النتيجة على تيليغرام.
ملاحظة: فلتر النتائج المالية لا يمكن اختباره تاريخياً، فالنتيجة الفعلية قد تكون أفضل قليلاً.
"""
import os
import time
from collections import defaultdict
from datetime import datetime, timezone

from common import SWING, MARKET, Ind, yahoo, market_ok, swing_setup

FEE = 0.001  # عمولة وانزلاق ذهاباً وإياباً (0.1%)


def load_all():
    data = {}
    for sym in [MARKET] + SWING:
        try:
            data[sym] = Ind(yahoo(sym, "1d", "10y"))
            print(f"{sym}: {len(data[sym].c)} days")
        except Exception as e:  # noqa: BLE001
            print(f"{sym}: {e}")
        time.sleep(0.3)
    return data


def run(data, rsi_level=40, min_adx=20, use_market=True, tps=(1, 2, 4), ttl=15, gap_r=0.5, cool=3):
    m = data[MARKET]
    mi_by_t = {t: i for i, t in enumerate(m.t)}
    trades = []
    for sym, s in data.items():
        if sym == MARKET:
            continue
        i, n, last_exit = 210, len(s.c), -999
        while i < n - 1:
            if i - last_exit < cool:
                i += 1; continue
            mi = mi_by_t.get(s.t[i])
            mk = market_ok(m, mi) if use_market else True
            sg = swing_setup(s, i, mk, rsi_level=rsi_level, min_adx=min_adx)
            if not sg:
                i += 1; continue
            op = s.o[i + 1]; gap = op - sg["entry"]; r = sg["r"]
            if abs(gap) > gap_r * r:
                i += 1; continue
            entry, sl = op, sg["sl"] + gap
            tp = [entry + k * r for k in tps]
            hits, stop, res, j, why = 0, sl, None, i + 1, "ttl"
            while j < n and j <= i + ttl:
                hi, lo = s.h[j], s.l[j]
                if lo <= stop:
                    res, why = stop, ("be" if hits else "sl"); break
                while hits < 3 and hi >= tp[hits]:
                    hits += 1
                    if hits == 1:
                        stop = entry
                if hits == 3:
                    res, why = tp[2], "tp"; break
                j += 1
            j = min(j, n - 1)
            if res is None:
                res = s.c[j]
            gain = sum((tp[k] - entry) / 3 for k in range(min(hits, 3))) + (res - entry) * (1 - min(hits, 3) / 3)
            trades.append({"sym": sym, "t": s.t[i], "R": gain / r - FEE * entry / r, "pct": gain / entry * 100 - FEE * 100,
                           "why": why, "days": j - i})
            last_exit = j
            i = j + 1
    return trades


def stats(tr):
    if not tr:
        return {"n": 0}
    tr = sorted(tr, key=lambda x: x["t"])
    eq = pk = dd = 0.0
    for t in tr:
        eq += t["R"]; pk = max(pk, eq); dd = max(dd, pk - eq)
    wins = sum(1 for t in tr if t["pct"] > 0)
    years = (tr[-1]["t"] - tr[0]["t"]) / (365.25 * 86400000) or 1
    return {"n": len(tr), "per_month": len(tr) / years / 12, "win": wins / len(tr) * 100,
            "expR": sum(t["R"] for t in tr) / len(tr), "sumR": sum(t["R"] for t in tr), "dd": dd,
            "days": sum(t["days"] for t in tr) / len(tr), "avg_pct": sum(t["pct"] for t in tr) / len(tr)}


def fmt_stats(name, st):
    if not st["n"]:
        return f"• {name}: لا صفقات"
    return (f"‏• <b>{name}</b>\n‏  صفقات {st['n']} ({st['per_month']:.1f} بالشهر) · نجاح <b>{st['win']:.0f}%</b> · "
            f"متوسط {st['avg_pct']:+.2f}% · لكل صفقة {st['expR']:+.2f}R · الإجمالي {st['sumR']:+.0f}R · أسوأ تراجع {st['dd']:.0f}R · "
            f"مدة {st['days']:.0f} يوم")


def main():
    data = load_all()
    variants = [
        ("الإعداد الحالي", {}),
        ("بدون فلتر السوق", {"use_market": False}),
        ("تصحيح أعمق RSI 35", {"rsi_level": 35}),
        ("تصحيح أخف RSI 45", {"rsi_level": 45}),
        ("اتجاه أقوى ADX 25", {"min_adx": 25}),
        ("أهداف أقرب 1/2/3", {"tps": (1, 2, 3)}),
    ]
    out = [f"🧪 <b>اختبار استراتيجية المضاربة</b>\n‏{len(data) - 1} سهم · آخر 10 سنوات · عمولة 0.1%\n"]
    base = None
    for name, kw in variants:
        tr = run(data, **kw)
        if base is None:
            base = tr
        out.append(fmt_stats(name, stats(tr)))
    by_year = defaultdict(list)
    for t in base:
        by_year[datetime.fromtimestamp(t["t"] / 1000, timezone.utc).year].append(t)
    out.append("\n📅 <b>الإعداد الحالي سنة بسنة</b>")
    for y in sorted(by_year):
        s = stats(by_year[y])
        out.append(f"‏{y}: {s['n']} صفقة · نجاح {s['win']:.0f}% · {s['expR']:+.2f}R")
    m = data[MARKET]
    spy = (m.c[-1] / m.c[210] - 1) * 100
    out.append(f"\n‏للمقارنة: الاحتفاظ بـ SPY في نفس الفترة {spy:+.0f}%")
    out.append("‏ملاحظة: فلتر النتائج المالية غير مشمول بالاختبار.")
    text = "\n".join(out)
    print(text)
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if token:
        import bot
        bot.TOKEN, bot.API = token, f"https://api.telegram.org/bot{token}"
        st = bot.load_state()
        bot.CHAT_ID = chat or bot.discover_chat_id(st)
        if bot.CHAT_ID:
            bot.send(text)


if __name__ == "__main__":
    main()
