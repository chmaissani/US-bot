"""
رادار الأسهم الأمريكية — بوت توصيات تيليغرام
- مضاربة (سوينغ): اختراق قمة 50 يوماً لسهم من أقوى 30% بحجم تداول مرتفع والسوق العام (SPY) صاعد،
  مع وقف متحرك 3×ATR تحت أعلى إغلاق. صفقات شراء فقط، تمتد عادة 2 إلى 6 أسابيع.
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

from common import (SWING, INVEST, INVEST_ETF, MARKET, SHARIAH, SHARIAH_ASOF, STOP_ATR, TRAIL_ATR, MAX_DAYS,
                    BREAKOUT_DAYS, Ind, yahoo, earnings_soon, market_ok, rs_ranks, breakout_setup,
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
    return (exit_px - rec["entry"]) / rec["entry"] * 100 - 0.1


def chart_png(sym, cs, rec):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError:
        return None
    d = cs[-90:]
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=120)
    bg, up, dn, ac = "#0f1418", "#2fbf8a", "#e5534b", "#d9a441"
    fig.patch.set_facecolor(bg); ax.set_facecolor(bg)
    for i, k in enumerate(d):
        col = up if k[4] >= k[1] else dn
        ax.plot([i, i], [k[3], k[2]], color=col, lw=1)
        ax.add_patch(Rectangle((i - .32, min(k[1], k[4])), .64, max(abs(k[4] - k[1]), 1e-9), color=col))
    n = len(d)
    hi50 = max(x[4] for x in cs[-BREAKOUT_DAYS - 1:-1])
    ax.plot([n - BREAKOUT_DAYS - 1, n - 1], [hi50, hi50], color="#8b9aa5", lw=.9, ls=":")
    ax.text(n - BREAKOUT_DAYS - 1, hi50, " 50-day high", color="#8b9aa5", fontsize=8, va="bottom")
    x0, x1 = n - 1, n + 10
    e, sl = rec["entry"], rec["sl"]
    ax.add_patch(Rectangle((x0, sl), x1 - x0, e - sl, color=dn, alpha=.22))
    ax.annotate("", xy=(x1, e + (e - sl) * 1.5), xytext=(x0, e), arrowprops=dict(arrowstyle="->", color=up, lw=1.5))
    for v, col, lb in [(e, ac, "ENTRY"), (sl, dn, "STOP")]:
        ax.axhline(v, color=col, lw=.8, ls="--", alpha=.8)
        ax.text(x1 + .3, v, f" {lb} {fmt(v)}", color=bg, fontsize=8, va="center", family="monospace",
                bbox=dict(boxstyle="square,pad=0.25", fc=col, ec="none"))
    ax.set_xlim(-1, x1 + 10); ax.set_xticks([])
    ax.tick_params(colors="#8b9aa5", labelsize=8)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.grid(axis="y", color="#26313a", lw=.6)
    ax.set_title(f"{sym} · Daily · BREAKOUT", color="#e7ecef", fontsize=11, loc="left", family="monospace")
    buf = io.BytesIO(); fig.tight_layout(); fig.savefig(buf, format="png", facecolor=bg); plt.close(fig)
    return buf.getvalue()


# ---------------- المضاربة: الرسائل ----------------
def signal_text(rec):
    e = rec["entry"]
    sh = (f"{RLM}☪️ ضمن صندوق SPUS الشرعي (قائمة {SHARIAH_ASOF})" if rec["sym"] in SHARIAH
          else f"{RLM}غير مدرج في صندوق SPUS الشرعي: إما غير متوافق أو خارج مؤشر S&P 500، تحقق بنفسك")
    return (f"🚀 <b>توصية مضاربة: اختراق</b> — <b>{rec['sym']}</b>{halal(rec['sym'])}\n\n"
            f"{RLM}النوع: <b>شراء</b> (سوينغ: عادة من أسبوعين لـ 6 أسابيع)\n"
            f"{RLM}الدخول: عند افتتاح الجلسة القادمة، قرب <code>{fmt(e)}</code>\n"
            f"{RLM}{lvl_line('الوقف الأولي', rec['sl'], e)}\n"
            f"{RLM}الهدف: <b>بدون هدف ثابت</b>، وقف متحرك يرتفع مع السعر ويخبرك البوت كل يوم بمكانه\n"
            f"{RLM}المدة القصوى: {MAX_DAYS} يوم تداول\n\n"
            f"{RLM}📊 أسباب التوصية:\n" + "".join(f"{RLM}• {w}\n" for w in rec["why"]) + "\n"
            f"{sh}\n"
            f"{RLM}💡 هذه الاستراتيجية تربح نحو 4 صفقات من 10، والربح يأتي من الصفقات التي تركب موجة طويلة. "
            "لا تبِع مبكراً، والتزم بالوقف.\n"
            f"{RLM}💰 حجم الصفقة: خاطر بـ 1% من محفظتك. عدد الأسهم = (1% من المحفظة) ÷ (الدخول − الوقف)\n"
            f"{RLM}📌 سعر الدخول الفعلي هو سعر الافتتاح، والبوت يعيد حساب الوقف عليه ويرسله لك.")


def reasons(sg, earn_ok):
    r = [
        f"أغلق عند أعلى مستوى في {BREAKOUT_DAYS} يوماً (اختراق)",
        f"حجم التداول {sg['vol_x']:.1f} ضعف المعتاد",
        f"من أقوى الأسهم: صعد {sg['ret6m']:+.0f}% في 6 أشهر، أقوى من {sg['rs'] * 100:.0f}% من القائمة",
        "السعر فوق متوسط 200 يوم، والسوق العام (SPY) صاعد",
    ]
    if earn_ok:
        r.append("لا توجد نتائج مالية للشركة خلال الأيام القادمة")
    return r


# ---------------- المضاربة: المتابعة ----------------
def finish(rec, exit_px, why, st):
    rec.update(status="closed", exit=exit_px, why_close=why, closed_at=int(time.time() * 1000), res=pnl_pct(rec, exit_px))
    icon = "🏁" if rec["res"] > 0 else "⛔"
    send(f"{icon} <b>{rec['sym']}</b> — انتهت التوصية\n{RLM}{why}\n{RLM}سعر الخروج: <code>{fmt(exit_px)}</code>\n"
         f"{RLM}النتيجة: <b>{pct(rec['res'])}</b>", reply_to=rec.get("msg"))
    st.setdefault("history", []).insert(0, rec)
    st.setdefault("last_close", {})[rec["sym"]] = rec["closed_at"]


def track(st):
    """متابعة وقت السوق على شموع 5 دقائق: تفعيل عند الافتتاح وضرب الوقف المتحرك."""
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
                    send(f"⚪️ <b>{sym}</b> — أُلغيت التوصية (لم تُفتح جلسة جديدة)", reply_to=rec.get("msg"))
                    del active[sym]
                continue
            op = nxt[0][1]
            rec["entry"] = op
            rec["sl"] = op - STOP_ATR * rec["atr"]
            rec.update(status="active", entry_t=nxt[0][0], last=nxt[0][0], max_close=op, days=0)
            send(f"✅ <b>{sym}</b> — تفعّلت التوصية عند الافتتاح <code>{fmt(op)}</code>\n"
                 f"{RLM}{lvl_line('الوقف الأولي', rec['sl'], op)}", reply_to=rec.get("msg"))
        for b in bars:
            if b[0] < rec["last"]:
                continue
            rec["last"] = b[0]
            if b[3] <= rec["sl"]:
                px = min(rec["sl"], b[1])
                moved = rec["sl"] > rec["entry"] - STOP_ATR * rec["atr"] + 1e-9
                finish(rec, px, "ضرب الوقف المتحرك" if moved else "ضرب الوقف الأولي", st)
                break
        if rec["status"] == "closed":
            del active[sym]


def update_trails(st, series):
    """بعد الإغلاق اليومي: رفع الوقف المتحرك، وإغلاق الصفقات التي تجاوزت المدة القصوى."""
    active = st.get("active", {})
    for sym in list(active):
        rec = active[sym]
        s = series.get(sym)
        if rec["status"] != "active" or s is None:
            continue
        closes = [c for t, c in zip(s.t, s.c) if t >= rec["entry_t"] - 86400000 * 0.5]
        if not closes:
            continue
        rec["days"] = len(closes)
        rec["max_close"] = max([rec.get("max_close", rec["entry"])] + closes)
        new_sl = rec["max_close"] - TRAIL_ATR * s.atr[-1]
        if new_sl > rec["sl"]:
            rec["sl_prev"], rec["sl"] = rec["sl"], new_sl
        rec["now"] = s.c[-1]
        if rec["days"] >= MAX_DAYS:
            finish(rec, s.c[-1], f"انتهت المدة القصوى ({MAX_DAYS} يوم تداول)", st)
            del active[sym]


AR_DAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
AR_MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
EARN_WARN_DAYS = 4   # التنبيه قبل النتائج بهذا العدد من الأيام (يغطي عطلة نهاية الأسبوع)


def earnings_warnings(st, earn):
    """تنبيه مرة واحدة لكل صفقة مفتوحة إذا اقتربت نتائج الشركة المالية."""
    if not earn:
        return
    today = datetime.now(timezone.utc).date()
    for sym, rec in st.get("active", {}).items():
        if sym not in earn or rec.get("earn_warned") == earn[sym][0]:
            continue
        day, when = earn[sym]
        d = datetime.strptime(day, "%Y-%m-%d").date()
        left = (d - today).days
        if left > EARN_WARN_DAYS:
            continue
        rec["earn_warned"] = day
        when_ar = {"pre": "قبل افتتاح السوق", "after": "بعد إغلاق السوق"}.get(when, "")
        last_chance = ("آخر فرصة للتصرف: إغلاق الجلسة التي قبله" if when == "pre"
                       else "آخر فرصة للتصرف: قبل إغلاق نفس اليوم" if when == "after" else "")
        now_px = rec.get("now", rec["entry"])
        send(f"⚠️ <b>{sym}</b> — نتائج مالية قريبة\n\n"
             f"{RLM}الشركة تعلن نتائجها يوم <b>{AR_DAYS[d.weekday()]} {d.day} {AR_MONTHS[d.month - 1]}</b> {when_ar}\n"
             + (f"{RLM}{last_chance}\n" if last_chance else "") +
             f"{RLM}صفقتك الآن: {pct((now_px - rec['entry']) / rec['entry'] * 100)} · الوقف <code>{fmt(rec['sl'])}</code>\n\n"
             f"{RLM}بعد النتائج قد يفتح السهم بفجوة كبيرة صعوداً أو هبوطاً، <b>والوقف لا يحمي من الفجوة</b>: "
             "إذا افتتح تحت الوقف يكون الخروج بسعر الافتتاح.\n\n"
             f"{RLM}خياراتك:\n"
             f"{RLM}• تكمل الصفقة: اختبار الاستراتيجية شمل صفقات مرّت بالنتائج\n"
             f"{RLM}• تخفّف الكمية لتقليل أثر الفجوة\n"
             f"{RLM}• تخرج قبل النتائج وتنتظر توصية جديدة\n"
             f"{RLM}البوت يكمل متابعة الصفقة بالطريقة العادية مهما اخترت.", reply_to=rec.get("msg"))


# ---------------- المضاربة: الفحص اليومي ----------------
REASON_AR = {
    "market": "السوق العام هابط", "no_trend": "تحت متوسط 200 يوم", "weak_rs": "ليس من أقوى 30%",
    "no_breakout": "بعيد عن قمة 50 يوماً", "near": "قريب من الاختراق (أقل من 3%) ⏳",
    "low_volume": "اخترق بحجم تداول ضعيف", "earnings": "نتائج مالية قريبة",
    "data": "بيانات غير كافية", "error": "تعذر جلب البيانات",
}


def daily_scan(st, spy):
    m = Ind(spy)
    mkt = market_ok(m, len(m.c) - 1)
    earn = earnings_soon()
    active = st.setdefault("active", {})
    last_close = st.setdefault("last_close", {})
    series, cs_all = {}, {}
    for sym in SWING:
        try:
            cs = yahoo(sym, "1d", "2y")
            series[sym], cs_all[sym] = Ind(cs), cs
        except Exception as e:  # noqa: BLE001
            print(f"{sym}: {e}")
        time.sleep(0.15)
    update_trails(st, series)
    rs = rs_ranks(series)
    status, new = {sym: "error" for sym in SWING if sym not in series}, []
    now_ms = int(time.time() * 1000)
    for sym, s in series.items():
        if sym in active or now_ms - last_close.get(sym, 0) < 1.2 * 86400000:
            continue
        dg = {}
        sg = breakout_setup(s, len(s.c) - 1, mkt, rs.get(sym), dg)
        why = dg.get("why")
        if sg and earn is not None and sym in earn:
            sg, why = None, "earnings"
        status[sym] = why
        if not sg:
            continue
        e = sg["close"]
        rec = {"sym": sym, "entry": e, "sl": e - STOP_ATR * sg["atr"], "atr": sg["atr"],
               "why": reasons(sg, earn is not None), "t": now_ms, "activate_after": s.t[-1] + 20 * 3600000,
               "status": "pending", "strategy": "breakout"}
        rec["msg"] = send(signal_text(rec), photo=chart_png(sym, cs_all[sym], rec))
        active[sym] = rec
        new.append(sym)
    earnings_warnings(st, earn)
    st["market"] = {"spy_ok": mkt, "coins": status, "earn_ok": earn is not None}
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
        if r["status"] == "pending":
            act.append(f"⏳ {r['sym']} · بانتظار الافتتاح")
            continue
        now_px = r.get("now", r["entry"])
        up = " 🔼" if r.get("sl_prev") and r["sl"] > r["sl_prev"] else ""
        act.append(f"{RLM}📈 <b>{r['sym']}</b> {pct((now_px - r['entry']) / r['entry'] * 100)} · "
                   f"الوقف المتحرك <code>{fmt(r['sl'])}</code>{up} · يوم {r.get('days', 0)}/{MAX_DAYS}")
        r.pop("sl_prev", None)
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
           + ("\n<b>الصفقات المفتوحة</b> (🔼 = ارتفع الوقف اليوم، حدّثه عندك):\n" + "\n".join(act) + "\n" if act else "")
           + (f"\n{RLM}نسبة النجاح: <b>{round(wins / len(hist) * 100)}%</b> من {len(hist)} توصية\n" if hist else "")
           + f"\n🌡 <b>حالة السوق</b>\n{mk}\n"
           + (f"{RLM}• قريبة من إشارة ⏳: {', '.join(near)}\n" if near else "")
           + "".join(f"{RLM}• {REASON_AR[k]}: {n_stocks(len(groups[k]))}\n" for k in ["no_breakout", "low_volume", "weak_rs", "no_trend", "earnings", "market", "error"] if k in groups)
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
             f"{RLM}📈 <b>المضاربة</b>: يفحص {n_stocks(len(SWING))} بعد إغلاق السوق كل يوم، ويرسل توصيات شراء عند اختراق الأسهم القوية، "
             "ويتابع الوقف المتحرك وقت السوق.\n"
             f"{RLM}💼 <b>الاستثمار</b>: تقرير كل سبت لـ {len(INVEST)} شركة كبيرة و{len(INVEST_ETF)} صناديق، وتنبيه عند فرصة تجميع.\n"
             f"{RLM}☪️ علامة للأسهم الموجودة في صندوق SPUS الشرعي.")
        st["hello"] = True

    if not st.get("breakout_v"):
        old = [r["sym"] for r in st.get("active", {}).values() if r.get("strategy") != "breakout"]
        for sym in old:
            st["active"].pop(sym, None)
        send("🔄 <b>تغيير استراتيجية المضاربة</b>\n\n"
             f"{RLM}اختبار 10 سنوات على 70 سهماً أظهر أن الاستراتيجية القديمة ضعيفة، فانتقل البوت إلى "
             "<b>اختراق قمة 50 يوماً لسهم قوي، مع وقف متحرك</b>:\n"
             f"{RLM}• 2016–2022: متوسط +1.68% للصفقة\n{RLM}• 2023–الآن: متوسط +3.22% للصفقة\n"
             f"{RLM}• تربح نحو 4 صفقات من 10، والربح من الصفقات الطويلة\n"
             f"{RLM}• بدون أهداف ثابتة: الوقف يرتفع مع السعر، والبوت يخبرك بمكانه يومياً"
             + (f"\n\n{RLM}أُلغيت توصيات الاستراتيجية القديمة: {', '.join(old)}" if old else ""))
        st["breakout_v"] = True

    if not st.get("v_earnwarn"):
        send("🔧 <b>تحديث البوت</b>\n\n"
             f"{RLM}• تنبيه قبل النتائج المالية بأيام لكل صفقة مفتوحة، مع خياراتك\n"
             f"{RLM}• «فرصة استثمارية» صارت تشترط أن يكون السهم في تصحيح فعلي، لا مجرد بعيد عن قمته")
        st["v_earnwarn"] = True

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
