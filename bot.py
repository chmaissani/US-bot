"""
رادار الأسهم الأمريكية — بوت توصيات تيليغرام
- مضاربة (سوينغ): تصحيح داخل اتجاه صاعد على الشموع اليومية، مع فلتر السوق العام (SPY)
  وتجنّب الأسهم التي تعلن نتائجها قريباً. صفقات شراء فقط، من أيام لأسابيع.
- استثمار: تقرير أسبوعي يصنّف شركات كبيرة راسخة وصناديق (منطقة تجميع / سعر عادل / متضخم / هابط)
  وتنبيه عندما يدخل سهم منطقة التجميع.
- علامة ☪️ للأسهم الموجودة في صندوق SPUS الشرعي.
يشتغل على GitHub Actions: كل 30 دقيقة وقت السوق لمتابعة الأهداف، وفحص يومي بعد الإغلاق.
"""
import io
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

from common import (SWING, INVEST, INVEST_ETF, MARKET, SHARIAH, SHARIAH_ASOF, TP_R, MAX_GAP_R,
                    TTL_DAYS, COOLDOWN_DAYS, Ind, yahoo, earnings_soon, market_ok, swing_setup,
                    invest_zone, fmt, pct)

SCAN_AFTER_UTC = (21, 15)    # الفحص اليومي بعد إغلاق السوق (21:15 UTC = 12:15 بعد منتصف الليل بتوقيت السعودية)
WEEKLY_REPORT_WEEKDAY = 5    # السبت (الإثنين = 0)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
API = f"https://api.telegram.org/bot{TOKEN}"
RLM = "‏"


# ---------------- الحالة ----------------
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(st):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


# ---------------- تيليغرام ----------------
def tg(method, files=None, **data):
    r = requests.post(f"{API}/{method}", data=data, files=files, timeout=30)
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not j.get("ok"):
        print(f"Telegram {method} failed: {r.status_code} {j.get('description', r.text[:200])}")
    return j.get("result")


def send(text, reply_to=None, photo=None):
    extra = {"parse_mode": "HTML"}
    if reply_to:
        extra["reply_to_message_id"] = reply_to
        extra["allow_sending_without_reply"] = "true"
    if photo is not None:
        res = tg("sendPhoto", files={"photo": ("chart.png", photo, "image/png")}, chat_id=CHAT_ID, caption=text[:1024], **extra)
        if res:
            if len(text) > 1024:
                tg("sendMessage", chat_id=CHAT_ID, text=text[1024:], **extra)
            return res.get("message_id")
    if len(text) > 4000:  # حد تيليغرام 4096 حرف: نقسم على الفقرات
        first, chunk = None, ""
        for part in text.split("\n\n"):
            if chunk and len(chunk) + len(part) > 3800:
                mid = send(chunk, reply_to=reply_to); first = first or mid; chunk = ""
            chunk += ("\n\n" if chunk else "") + part
        mid = send(chunk, reply_to=reply_to)
        return first or mid
    res = tg("sendMessage", chat_id=CHAT_ID, text=text, disable_web_page_preview="true", **extra)
    return res.get("message_id") if res else None


def discover_chat_id(st):
    if st.get("chat_id"):
        return st["chat_id"]
    for u in reversed(tg("getUpdates") or []):
        msg = u.get("message") or u.get("channel_post") or {}
        if msg.get("chat", {}).get("id"):
            st["chat_id"] = str(msg["chat"]["id"])
            return st["chat_id"]
    return ""


# ---------------- أدوات ----------------
def n_stocks(n):
    return "سهم واحد" if n == 1 else "سهمان" if n == 2 else f"{n} أسهم" if n <= 10 else f"{n} سهماً"


def halal(sym):
    return " ☪️" if sym in SHARIAH else ""


def lvl_line(name, v, entry):
    return f"{name}: <code>{fmt(v)}</code> ({pct((v - entry) / entry * 100)})"


def pnl_pct(rec, exit_px):
    third, m, hits = 1 / 3, 0.0, min(rec["hits"], 3)
    for i in range(hits):
        m += (rec["tp"][i] - rec["entry"]) / rec["entry"] * third
    m += (exit_px - rec["entry"]) / rec["entry"] * (1 - third * hits)
    return m * 100


def chart_png(sym, cs, rec):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError:
        return None
    d = cs[-70:]
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=120)
    bg, up, dn, ac = "#0f1418", "#2fbf8a", "#e5534b", "#d9a441"
    fig.patch.set_facecolor(bg); ax.set_facecolor(bg)
    for i, k in enumerate(d):
        col = up if k[4] >= k[1] else dn
        ax.plot([i, i], [k[3], k[2]], color=col, lw=1)
        ax.add_patch(Rectangle((i - .32, min(k[1], k[4])), .64, max(abs(k[4] - k[1]), 1e-9), color=col))
    x0, x1 = len(d) - 1, len(d) + 12
    e, sl, tp3 = rec["entry"], rec["sl"], rec["tp"][2]
    ax.add_patch(Rectangle((x0, e), x1 - x0, tp3 - e, color=up, alpha=.18))
    ax.add_patch(Rectangle((x0, sl), x1 - x0, e - sl, color=dn, alpha=.22))
    for v, col, lb in [(e, ac, "ENTRY"), (sl, dn, "SL"), (rec["tp"][0], up, "TP1"), (rec["tp"][1], up, "TP2"), (tp3, up, "TP3")]:
        ax.axhline(v, color=col, lw=.8, ls="--", alpha=.8)
        ax.text(x1 + .3, v, f" {lb} {fmt(v)}", color=bg, fontsize=8, va="center", family="monospace",
                bbox=dict(boxstyle="square,pad=0.25", fc=col, ec="none"))
    ax.set_xlim(-1, x1 + 9); ax.set_xticks([])
    ax.tick_params(colors="#8b9aa5", labelsize=8)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.grid(axis="y", color="#26313a", lw=.6)
    ax.set_title(f"{sym} · Daily · LONG", color="#e7ecef", fontsize=11, loc="left", family="monospace")
    buf = io.BytesIO(); fig.tight_layout(); fig.savefig(buf, format="png", facecolor=bg); plt.close(fig)
    return buf.getvalue()


# ---------------- المضاربة: الرسائل ----------------
def signal_text(rec):
    e = rec["entry"]
    tps = "\n".join(lvl_line(f"الهدف {i + 1}", v, e) for i, v in enumerate(rec["tp"]))
    sh = (f"{RLM}☪️ ضمن صندوق SPUS الشرعي (قائمة {SHARIAH_ASOF})" if rec["sym"] in SHARIAH
          else f"{RLM}غير مدرج في صندوق SPUS الشرعي: إما غير متوافق أو خارج مؤشر S&P 500، تحقق بنفسك")
    return (f"📈 <b>توصية مضاربة</b> — <b>{rec['sym']}</b>{halal(rec['sym'])}\n\n"
            f"{RLM}النوع: <b>شراء</b> (سوينغ: من أيام لأسابيع)\n"
            f"{RLM}الدخول: عند افتتاح الجلسة القادمة، قرب <code>{fmt(e)}</code>\n"
            f"{RLM}{lvl_line('وقف الخسارة', rec['sl'], e)}\n{RLM}" + tps.replace("\n", f"\n{RLM}") + "\n"
            f"{RLM}المدة القصوى: {TTL_DAYS} يوم تداول\n\n"
            f"{RLM}📊 أسباب التوصية:\n" + "".join(f"{RLM}• {w}\n" for w in rec["why"]) + "\n"
            f"{sh}\n"
            f"{RLM}💡 بِع ثلث الكمية عند كل هدف، وانقل الوقف لسعر دخولك بعد الهدف 1.\n"
            f"{RLM}💰 حجم الصفقة: خاطر بـ 1% من محفظتك. عدد الأسهم = (1% من المحفظة) ÷ (الدخول − الوقف)\n"
            f"{RLM}⚠️ إذا افتتح السهم بفجوة كبيرة، يلغي البوت التوصية ويخبرك.")


def reasons(sg):
    return [
        "السهم في اتجاه صاعد: السعر فوق متوسط 200 يوم، ومتوسط 50 فوق متوسط 200",
        f"قوة الاتجاه: ADX عند {sg['adx']:.0f}",
        f"تصحيح انتهى: RSI نزل إلى {sg['dip']:.0f} ثم ارتد إلى {sg['rsi']:.0f}",
        "السوق العام (SPY) صاعد",
        "لا توجد نتائج مالية للشركة خلال الأيام القادمة",
    ]


# ---------------- المضاربة: المتابعة ----------------
def finish(rec, exit_px, why, st):
    rec.update(status="closed", exit=exit_px, why_close=why, closed_at=int(time.time() * 1000), res=pnl_pct(rec, exit_px))
    icon = "🏁" if rec["res"] > 0 else "⛔"
    send(f"{icon} <b>{rec['sym']}</b> — انتهت التوصية\n{RLM}{why}\n{RLM}النتيجة: <b>{pct(rec['res'])}</b>", reply_to=rec.get("msg"))
    st.setdefault("history", []).insert(0, rec)
    st.setdefault("last_close", {})[rec["sym"]] = rec["closed_at"]


def track(st):
    active = st.setdefault("active", {})
    for sym in list(active):
        rec = active[sym]
        try:
            bars = yahoo(sym, "5m", "5d")
        except Exception as e:  # noqa: BLE001
            print(f"track {sym}: {e}")
            continue
        if rec["status"] == "pending":
            nxt = [b for b in bars if b[0] >= rec["activate_after"]]
            if not nxt:
                if time.time() * 1000 - rec["t"] > 5 * 86400000:
                    rec["status"] = "cancelled"
                    send(f"⚪️ <b>{sym}</b> — أُلغيت التوصية (لم تُفتح جلسة جديدة)", reply_to=rec.get("msg"))
                    del active[sym]
                continue
            op = nxt[0][1]
            gap = op - rec["entry"]
            if abs(gap) > MAX_GAP_R * rec["r"]:
                send(f"⚪️ <b>{sym}</b> — أُلغيت التوصية\n{RLM}افتتح السهم بفجوة {'صاعدة' if gap > 0 else 'هابطة'} "
                     f"عند <code>{fmt(op)}</code> ({pct(gap / rec['entry'] * 100)})، والدخول صار غير مناسب.", reply_to=rec.get("msg"))
                rec["status"] = "cancelled"
                st.setdefault("last_close", {})[sym] = int(time.time() * 1000)
                del active[sym]
                continue
            # تفعيل الصفقة عند الافتتاح مع إزاحة المستويات بقدر الفجوة
            rec["entry"], rec["sl"] = op, rec["sl"] + gap
            rec["tp"] = [v + gap for v in rec["tp"]]
            rec.update(status="active", entry_t=nxt[0][0], last=nxt[0][0])
            send(f"✅ <b>{sym}</b> — تفعّلت التوصية عند الافتتاح <code>{fmt(op)}</code>\n"
                 f"{RLM}{lvl_line('الوقف', rec['sl'], op)}\n{RLM}"
                 + f"\n{RLM}".join(lvl_line(f"الهدف {i + 1}", v, op) for i, v in enumerate(rec["tp"])), reply_to=rec.get("msg"))
        for b in bars:
            if b[0] < rec["last"]:
                continue
            rec["last"] = b[0]
            hi, lo = b[2], b[3]
            stop = rec["entry"] if rec["hits"] else rec["sl"]
            if lo <= stop:
                finish(rec, stop, f"خروج على التعادل بعد الهدف {rec['hits']}" if rec["hits"] else "ضرب وقف الخسارة", st)
                break
            while rec["hits"] < 3 and hi >= rec["tp"][rec["hits"]]:
                rec["hits"] += 1
                i = rec["hits"]
                tail = "انقل الوقف لسعر دخولك 🔒" if i == 1 else "بِع ثلثاً آخر واترك الباقي للهدف 3" if i == 2 else ""
                send(f"🎯 <b>{sym}</b> — تحقق الهدف {i} ✅\n{RLM}السعر: <code>{fmt(rec['tp'][i - 1])}</code> "
                     f"({pct((rec['tp'][i - 1] - rec['entry']) / rec['entry'] * 100)})\n{RLM}{tail}", reply_to=rec.get("msg"))
            if rec["hits"] >= 3:
                finish(rec, rec["tp"][2], "تحققت كل الأهداف 🏆", st)
                break
        if rec["status"] == "active" and time.time() * 1000 - rec.get("entry_t", rec["t"]) > TTL_DAYS * 1.45 * 86400000:
            finish(rec, bars[-1][4], f"انتهت المدة القصوى ({TTL_DAYS} يوم تداول)", st)
        if rec["status"] == "closed":
            del active[sym]


# ---------------- المضاربة: الفحص اليومي ----------------
REASON_AR = {
    "market": "السوق العام هابط", "no_trend": "بدون اتجاه صاعد", "weak": "اتجاه ضعيف",
    "no_pullback": "اتجاه جيد وننتظر تصحيحاً", "near": "التصحيح حصل وننتظر الارتداد ⏳",
    "earnings": "نتائج مالية قريبة", "data": "بيانات غير كافية", "error": "تعذر جلب البيانات",
}


def daily_scan(st, spy):
    m = Ind(spy)
    mi = len(m.c) - 1
    mkt = market_ok(m, mi)
    earn = earnings_soon()
    active = st.setdefault("active", {})
    last_close = st.setdefault("last_close", {})
    status, new = {}, []
    now_ms = int(time.time() * 1000)
    for sym in SWING:
        if sym in active:
            continue
        if now_ms - last_close.get(sym, 0) < COOLDOWN_DAYS * 1.45 * 86400000:
            continue
        try:
            cs = yahoo(sym, "1d", "2y")
            s = Ind(cs)
            dg = {}
            sg = swing_setup(s, len(s.c) - 1, mkt, dg)
            why = dg.get("why")
            if sg and earn is not None and sym in earn:
                sg, why = None, "earnings"
            status[sym] = why
            if not sg:
                continue
            rec = {"sym": sym, "entry": sg["entry"], "sl": sg["sl"], "r": sg["r"], "tp": sg["tp"],
                   "why": reasons(sg) if earn is not None else reasons(sg)[:-1],
                   "t": now_ms, "activate_after": s.t[-1] + 20 * 3600000, "hits": 0, "status": "pending"}
            rec["msg"] = send(signal_text(rec), photo=chart_png(sym, cs, rec))
            active[sym] = rec
            new.append(sym)
        except Exception as e:  # noqa: BLE001
            print(f"{sym}: {e}")
            status[sym] = "error"
    st["market"] = {"spy_ok": mkt, "spy": m.c[mi], "spy200": m.sma200[mi], "coins": status,
                    "earn_ok": earn is not None}
    if new:
        st["last_signal"] = now_ms
    return new


def invest_check(st, weekly=False):
    """يصنّف أسهم الاستثمار. ينبه عند دخول سهم منطقة التجميع، ويرسل التقرير الكامل أسبوعياً."""
    zones, info = {}, {}
    for sym in INVEST + INVEST_ETF:
        try:
            z, d = invest_zone(Ind(yahoo(sym, "1d", "2y")))
        except Exception as e:  # noqa: BLE001
            print(f"invest {sym}: {e}")
            continue
        zones[sym], info[sym] = z, d
    prev = st.get("invest_zones", {})
    for sym, z in zones.items():
        if z == "buy" and prev.get(sym) not in (None, "buy") and not weekly:
            d = info[sym]
            send(f"🟢 <b>فرصة استثمارية: {sym}</b>{halal(sym)}\n\n"
                 f"{RLM}دخل السهم منطقة التجميع: الاتجاه طويل الأمد صاعد، والسعر نزل.\n"
                 f"{RLM}السعر: <code>{fmt(d['px'])}</code> · أقل من قمة 52 أسبوع بـ {abs(d['dd']):.0f}%"
                 + (f" · RSI أسبوعي {d['wrsi']:.0f}" if d.get("wrsi") is not None else "") + "\n"
                 f"{RLM}💡 للاستثمار طويل الأمد: اشترِ على 3 دفعات خلال 4 إلى 6 أسابيع بدل دفعة وحدة.")
    st["invest_zones"] = zones
    if weekly:
        send(invest_report(zones, info))


def invest_report(zones, info):
    def line(sym):
        d = info[sym]
        w = f" · RSI أسبوعي {d['wrsi']:.0f}" if d.get("wrsi") is not None else ""
        return f"{RLM}• <b>{sym}</b>{halal(sym)} {fmt(d['px'])} · من القمة {d['dd']:.0f}% · سنة {d['ret1y']:+.0f}%{w}"
    groups = [("buy", "🟢 <b>منطقة تجميع</b>: اتجاه طويل صاعد والسعر نزل"),
              ("hold", "🟡 <b>سعر عادل</b>: احتفظ ولا تستعجل الشراء"),
              ("hot", "🔴 <b>متضخم</b>: لا تطارد السعر، انتظر تصحيحاً"),
              ("down", "⚫ <b>اتجاه هابط</b>: تجنّبه حالياً")]
    parts = ["💼 <b>تقرير الاستثمار الأسبوعي</b>"]
    for z, title in groups:
        stocks = [s for s in INVEST if zones.get(s) == z]
        if stocks:
            parts.append(f"\n{title}\n" + "\n".join(line(s) for s in stocks))
    etfs = [s for s in INVEST_ETF if s in zones]
    if etfs:
        tag = {"buy": "🟢", "hold": "🟡", "hot": "🔴", "down": "⚫"}
        parts.append("\n📦 <b>الصناديق</b>\n" + "\n".join(f"{tag.get(zones[s], '')} {line(s)[1:]}" for s in etfs))
    parts.append(f"\n{RLM}☪️ = ضمن صندوق SPUS الشرعي (قائمة {SHARIAH_ASOF})\n"
                 f"{RLM}💡 للاستثمار: اشترِ على دفعات، ولا تستثمر مالاً تحتاجه خلال 3 سنوات.")
    return "\n".join(parts)


def session_summary(st, new):
    day_ago = (time.time() - 86400) * 1000
    hist = st.get("history", [])
    today = [r for r in hist if r.get("closed_at", 0) >= day_ago]
    wins = sum(1 for r in hist if r["res"] > 0)
    lines = [f"{'✅' if r['res'] > 0 else '❌'} {r['sym']}: {pct(r['res'])}" for r in today]
    act = []
    for r in st.get("active", {}).values():
        state = "بانتظار الافتتاح" if r["status"] == "pending" else f"أهداف {r['hits']}/3"
        act.append(f"⏳ {r['sym']} · {state}")
    m = st.get("market", {})
    mk = (f"{RLM}السوق العام (SPY): <b>{'صاعد 📈' if m.get('spy_ok') else 'غير صاعد ↔️ (لا صفقات شراء جديدة)'}</b>"
          if m else "")
    groups = {}
    for sym, why in (m.get("coins") or {}).items():
        groups.setdefault(why, []).append(sym)
    near = groups.get("near", [])
    txt = ("📋 <b>ملخص جلسة اليوم</b>\n\n"
           + (f"{RLM}توصيات جديدة: {', '.join(new)}\n" if new else f"{RLM}لا توصيات جديدة اليوم.\n")
           + ("\n" + "\n".join(lines) + "\n" if lines else "")
           + ("\n<b>النشطة:</b>\n" + "\n".join(act) + "\n" if act else "")
           + (f"\n{RLM}نسبة النجاح: <b>{round(wins / len(hist) * 100)}%</b> من {len(hist)} توصية\n" if hist else "")
           + f"\n🌡 <b>حالة السوق</b>\n{mk}\n"
           + (f"{RLM}• قريبة من إشارة ⏳: {', '.join(near)}\n" if near else "")
           + "".join(f"{RLM}• {REASON_AR[k]}: {n_stocks(len(groups[k]))}\n" for k in ["no_pullback", "weak", "no_trend", "earnings", "market", "error"] if k in groups)
           + ("" if m.get("earn_ok", True) else f"{RLM}⚠️ تعذر قراءة تقويم النتائج المالية اليوم، فلم يُطبَّق فلتر النتائج\n"))
    send(txt)


# ---------------- التشغيل ----------------
def main():
    global CHAT_ID
    if not TOKEN:
        sys.exit("❌ TELEGRAM_BOT_TOKEN غير موجود. أضفه في Settings → Secrets and variables → Actions.")
    st = load_state()
    if not CHAT_ID:
        CHAT_ID = discover_chat_id(st)
    if not CHAT_ID:
        sys.exit("❌ ما قدرت أعرف محادثتك. افتح البوت في تيليغرام واضغط Start، ثم شغّل الـ workflow مرة ثانية.")
    force = os.environ.get("FORCE", "")
    if not st.get("hello") or os.environ.get("TEST_MODE") == "true":
        send("✅ <b>رادار الأسهم الأمريكية</b> متصل!\n\n"
             f"{RLM}📈 <b>المضاربة</b>: يفحص {n_stocks(len(SWING))} بعد إغلاق السوق كل يوم، ويرسل توصيات شراء سوينغ (من أيام لأسابيع)، "
             "ويتابع الأهداف والوقف وقت السوق.\n"
             f"{RLM}💼 <b>الاستثمار</b>: تقرير كل سبت لـ {len(INVEST)} شركة كبيرة و{len(INVEST_ETF)} صناديق، وتنبيه عند فرصة تجميع.\n"
             f"{RLM}☪️ علامة للأسهم الموجودة في صندوق SPUS الشرعي.")
        st["hello"] = True

    now = datetime.now(timezone.utc)
    track(st)

    # الفحص اليومي بعد الإغلاق، مرة واحدة لكل يوم تداول
    today = now.strftime("%Y-%m-%d")
    after_close = (now.hour, now.minute) >= SCAN_AFTER_UTC
    if force in ("scan", "all") or (now.weekday() < 5 and after_close and st.get("scan_day") != today):
        try:
            spy = yahoo(MARKET, "1d", "2y")
            traded_today = datetime.fromtimestamp(spy[-1][0] / 1000, timezone.utc).strftime("%Y-%m-%d") == today
            if traded_today or force:
                new = daily_scan(st, spy)
                invest_check(st, weekly=False)
                session_summary(st, new)
            else:
                print("no session today (holiday)")
            st["scan_day"] = today
        except Exception as e:  # noqa: BLE001
            print(f"scan error: {e}")

    # التقرير الأسبوعي للاستثمار
    week = now.strftime("%G-%V")
    if force in ("invest", "all") or (now.weekday() == WEEKLY_REPORT_WEEKDAY and st.get("report_week") != week):
        invest_check(st, weekly=True)
        st["report_week"] = week

    st["history"] = st.get("history", [])[:200]
    save_state(st)


if __name__ == "__main__":
    main()
