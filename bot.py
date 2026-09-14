"""
Kundalik bot — Telegram uchun haftalik reja va eslatma boti.

Foydalanish:
  1) @BotFather dan token oling
  2) BOT_TOKEN ni pastda yoki .bat faylda (set BOT_TOKEN=...) ko'rsating
  3) pip install aiogram tzdata
  4) python bot.py

Ro'yxatdan o'tish:
  /start bosilganda bot ism-familiya va tug'ilgan sanani so'raydi, yoshini hisoblaydi.
  /anketa — ma'lumotlarni qayta kiritish.

Admin buyruqlari (faqat ADMIN_IDS dagilar uchun):
  /stat    — kuniga nechta odam kirgan, nechta odam foydalangan
  /odamlar — ro'yxatdan o'tganlar: ism, yosh, username, kirgan kuni
  /id      — o'z Telegram ID'ingizni bilish (hamma uchun)
"""

import asyncio
import logging
import os
import re
import sqlite3
import sys
from contextlib import closing
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BotCommand, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

# ---------------------------------------------------------------- Sozlamalar
# Token: .bat dagi set BOT_TOKEN=... bo'lsa o'sha olinadi, bo'lmasa qo'shtirnoq ichidagi
BOT_TOKEN = os.environ.get("BOT_TOKEN") or "8832900587:AAEU_661ipfze3SYW7yq_rL4AGOiuZl4OB8"

# Adminlar: oxiridagi figurali qavs ichiga yoziladi. .bat dagi set ADMIN_IDS=... ham ishlaydi.
ADMIN_IDS = {int(x) for x in re.findall(r"\d+", os.environ.get("ADMIN_IDS", ""))} | {7811785578}

TZ = ZoneInfo("Asia/Tashkent")
DB_PATH = "kundalik.db"
ERTALABKI_XULOSA = "07:00"   # har kuni shu vaqtda bugungi reja yuboriladi; None qilsangiz o'chadi
HISOBOT_VAQTI = "23:59"      # har kuni shu vaqtda kundalik hisobot yuboriladi; None qilsangiz o'chadi
STAT_VAQTI = "20:00"         # har kuni shu vaqtda adminlarga statistika yuboriladi; None qilsangiz o'chadi
REYTING_KUNI = 0             # haftalik reyting qaysi kuni ketadi: 0 = Dushanba
REYTING_VAQTI = "09:00"      # soat nechada; None qilsangiz o'chadi
KUNLAR = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
HAR_KUNI = -1

KUN_ALIAS = {
    "dushanba": 0, "dush": 0, "du": 0, "душанба": 0,
    "seshanba": 1, "sesh": 1, "se": 1, "сешанба": 1,
    "chorshanba": 2, "chor": 2, "ch": 2, "чоршанба": 2,
    "payshanba": 3, "pay": 3, "pa": 3, "пайшанба": 3,
    "juma": 4, "ju": 4, "жума": 4,
    "shanba": 5, "sh": 5, "шанба": 5,
    "yakshanba": 6, "yak": 6, "ya": 6, "якшанба": 6,
    "harkuni": HAR_KUNI, "hammasi": HAR_KUNI, "ҳаркуни": HAR_KUNI,
}

YORDAM = (
    "📌 Vazifa qo'shish uchun shunchaki yozing. Kunni bir marta yozib, "
    "ostiga vaqt va vazifani tering:\n\n"
    "Dushanba\n"
    "08:00 Uyqudan turish\n"
    "08:30 Nonushta\n"
    "09:00 Matematika darsi\n"
    "Seshanba\n"
    "10:30 Sport zal\n"
    "Har kuni\n"
    "07:30 Nonushta\n\n"
    "Bir qatorda ham bo'ladi: Dushanba 08:00 Matematika darsi\n\n"
    "Buyruqlar:\n"
#     "/start :\n"
    "/royxat — butun haftalik reja\n"
    "/bugun — bugungi vazifalar\n"
    "/hisobot — bugungi hisobot (necha % bajarildi)\n"
    "/streak — necha kun ketma-ket 100% bajardingiz, darajangiz\n"
    "/reyting — haftalik TOP-10\n"
    "/natija — bugungi natijangiz (do'stlarga ulashish uchun)\n"
    "/ochir 5 — #5 vazifani o'chirish (bir nechtasini ham: /ochir 5 7 9)\n"
    "/tozalash — hammasini o'chirish\n"
    "/anketa — ism-familiya va tug'ilgan sanani o'zgartirish\n"
    "/yordam — shu xabar\n\n"
    "⏰ Eslatma kelganda ✅ Bajarildi yoki ⏯️ Qoldirildi tugmasini bosing — "
    "kechqurun shu asosda hisobot keladi."
)


# ---------------------------------------------------------------- Baza
def run(sql, params=(), fetch=False):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            cur = conn.execute(sql, params)
            if fetch:
                return cur.fetchall()
            return cur.lastrowid, cur.rowcount


def ustun_qosh(jadval, ustun, tur):
    """Jadvalda ustun bo'lmasa qo'shadi (eski bazani yangilash uchun)."""
    mavjud = [r["name"] for r in run(f"PRAGMA table_info({jadval})", fetch=True)]
    if ustun not in mavjud:
        run(f"ALTER TABLE {jadval} ADD COLUMN {ustun} {tur}")


def init_db():
    # Har kunning natijasi (23:59 da yoziladi): streak va reyting shundan hisoblanadi
    run(
        """CREATE TABLE IF NOT EXISTS natijalar (
            user_id INTEGER NOT NULL,
            sana    TEXT    NOT NULL,
            jami    INTEGER NOT NULL,
            done    INTEGER NOT NULL,
            PRIMARY KEY (user_id, sana)
        )"""
    )
    run(
        """CREATE TABLE IF NOT EXISTS tasks (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            day     INTEGER NOT NULL,
            time    TEXT    NOT NULL,
            text    TEXT    NOT NULL
        )"""
    )
    run(
        """CREATE TABLE IF NOT EXISTS statuses (
            user_id INTEGER NOT NULL,
            task_id INTEGER NOT NULL,
            sana    TEXT    NOT NULL,
            status  TEXT    NOT NULL,
            PRIMARY KEY (task_id, sana)
        )"""
    )
    # Foydalanuvchilar: kim qachon kirgan + anketa (ism-familiya, tug'ilgan sana)
    run(
        """CREATE TABLE IF NOT EXISTS users (
            user_id    INTEGER PRIMARY KEY,
            name       TEXT,
            username   TEXT,
            first_seen TEXT NOT NULL,
            last_seen  TEXT NOT NULL,
            full_name  TEXT,
            birth_date TEXT
        )"""
    )
    ustun_qosh("users", "full_name", "TEXT")
    ustun_qosh("users", "birth_date", "TEXT")
    # Statistika uchun: kim qaysi kuni faol bo'lgan (har kun uchun bir marta)
    run(
        """CREATE TABLE IF NOT EXISTS activity (
            user_id INTEGER NOT NULL,
            sana    TEXT    NOT NULL,
            PRIMARY KEY (user_id, sana)
        )"""
    )
    # Statistika qo'shilishidan oldin reja kiritgan eski foydalanuvchilarni ham ro'yxatga olamiz
    run("INSERT OR IGNORE INTO users(user_id, first_seen, last_seen) "
        "SELECT DISTINCT user_id, '', '' FROM tasks")


def add_task(user_id, day, time_, text):
    tid, _ = run("INSERT INTO tasks(user_id, day, time, text) VALUES (?,?,?,?)",
                 (user_id, day, time_, text))
    return tid


def get_tasks(user_id):
    return run("SELECT * FROM tasks WHERE user_id=? ORDER BY day, time, id", (user_id,), fetch=True)


def get_tasks_for_day(user_id, weekday):
    return run("SELECT * FROM tasks WHERE user_id=? AND (day=? OR day=?) ORDER BY time, id",
               (user_id, weekday, HAR_KUNI), fetch=True)


def delete_task(user_id, task_id):
    _, n = run("DELETE FROM tasks WHERE user_id=? AND id=?", (user_id, task_id))
    return n


def clear_tasks(user_id):
    _, n = run("DELETE FROM tasks WHERE user_id=?", (user_id,))
    return n


def due_tasks(weekday, time_):
    return run("SELECT * FROM tasks WHERE time=? AND (day=? OR day=?)",
               (time_, weekday, HAR_KUNI), fetch=True)


def all_users():
    return [r["user_id"] for r in run("SELECT DISTINCT user_id FROM tasks", fetch=True)]


def set_status(user_id, task_id, sana, status):
    run("INSERT OR REPLACE INTO statuses(user_id, task_id, sana, status) VALUES (?,?,?,?)",
        (user_id, task_id, sana, status))


def get_statuses(user_id, sana):
    """{task_id: 'done' | 'skip'}"""
    rows = run("SELECT task_id, status FROM statuses WHERE user_id=? AND sana=?", (user_id, sana), fetch=True)
    return {r["task_id"]: r["status"] for r in rows}


# ---------------------------------------------------------------- Foydalanuvchilar va anketa
def touch_user(user, sana):
    """Foydalanuvchi har xabar yozganda chaqiriladi: ro'yxatga oladi va bugungi faollikni belgilaydi."""
    name = " ".join(x for x in (user.first_name, user.last_name) if x)
    run("INSERT OR IGNORE INTO users(user_id, name, username, first_seen, last_seen) VALUES (?,?,?,?,?)",
        (user.id, name, user.username, sana, sana))
    run("UPDATE users SET name=?, username=?, last_seen=? WHERE user_id=?",
        (name, user.username, sana, user.id))
    run("INSERT OR IGNORE INTO activity(user_id, sana) VALUES (?,?)", (user.id, sana))


def get_user(user_id):
    rows = run("SELECT * FROM users WHERE user_id=?", (user_id,), fetch=True)
    return rows[0] if rows else None


def is_registered(user_id):
    u = get_user(user_id)
    return bool(u and u["full_name"])


def save_anketa(user_id, full_name, birth: date, sana):
    run("INSERT OR IGNORE INTO users(user_id, first_seen, last_seen) VALUES (?,?,?)", (user_id, sana, sana))
    run("UPDATE users SET full_name=?, birth_date=? WHERE user_id=?",
        (full_name, birth.isoformat(), user_id))


def parse_sana(text, today: date):
    """'15.03.2005' / '15/03/2005' / '2005-03-15' -> date yoki None."""
    t = text.strip()
    m = re.match(r"^(\d{1,2})[.\-/ ](\d{1,2})[.\-/ ](\d{4})$", t)
    if m:
        d, mo, y = map(int, m.groups())
    else:
        m = re.match(r"^(\d{4})[.\-/ ](\d{1,2})[.\-/ ](\d{1,2})$", t)
        if not m:
            return None
        y, mo, d = map(int, m.groups())
    try:
        s = date(y, mo, d)
    except ValueError:
        return None
    if y < 1900 or s > today:
        return None
    return s


def yosh(birth: date, today: date):
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def fmt_sana(s):
    """'2026-09-09' -> '09.09.2026'"""
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return s or "?"


class Anketa(StatesGroup):
    ism = State()
    sana = State()


# ---------------------------------------------------------------- Statistika
def _son(sql, params=()):
    return run(sql, params, fetch=True)[0]["n"]


def stat_matn(now):
    bugun = now.date()

    def kun(d):
        s = d.strftime("%Y-%m-%d")
        yangi = _son("SELECT COUNT(*) AS n FROM users WHERE first_seen=?", (s,))
        faol = _son("SELECT COUNT(*) AS n FROM activity WHERE sana=?", (s,))
        return yangi, faol

    def davr(kunlar):
        boshi = (bugun - timedelta(days=kunlar - 1)).strftime("%Y-%m-%d")
        yangi = _son("SELECT COUNT(*) AS n FROM users WHERE first_seen>=?", (boshi,))
        faol = _son("SELECT COUNT(DISTINCT user_id) AS n FROM activity WHERE sana>=?", (boshi,))
        return yangi, faol

    jami = _son("SELECT COUNT(*) AS n FROM users")
    anketali = _son("SELECT COUNT(*) AS n FROM users WHERE full_name IS NOT NULL AND full_name<>''")
    rejali = _son("SELECT COUNT(DISTINCT user_id) AS n FROM tasks")
    y1, f1 = kun(bugun)
    y2, f2 = kun(bugun - timedelta(days=1))
    y7, f7 = davr(7)
    y30, f30 = davr(30)

    lines = [
        f"📈 Statistika — {KUNLAR[now.weekday()]}, {now.strftime('%d.%m.%Y')}",
        "",
        f"Bugun: yangi {y1}, faol {f1}",
        f"Kecha: yangi {y2}, faol {f2}",
        f"Oxirgi 7 kun: yangi {y7}, faol {f7}",
        f"Oxirgi 30 kun: yangi {y30}, faol {f30}",
        "",
        f"👥 Jami foydalanuvchilar: {jami}",
        f"📋 Ro'yxatdan o'tganlar: {anketali}",
        f"📝 Reja kiritganlar: {rejali}",
        "",
        "Kunlar bo'yicha (yangi / faol):",
    ]
    for i in range(7):
        d = bugun - timedelta(days=i)
        y, f = kun(d)
        lines.append(f"{d.strftime('%d.%m')} {KUNLAR[d.weekday()][:3]} — {y} / {f}")
    lines.append("")
    lines.append("«Yangi» — botga birinchi marta yozganlar. "
                 "«Faol» — shu kuni kamida bitta xabar yozgan yoki tugma bosganlar. "
                 "Ro'yxat: /odamlar")
    return "\n".join(lines)


def odamlar_qatorlar(today: date):
    rows = run("SELECT * FROM users ORDER BY first_seen DESC, user_id", fetch=True)
    reg = [r for r in rows if r["full_name"]]
    lines = [f"👥 Jami: {len(rows)} ta, ro'yxatdan o'tgan: {len(reg)} ta", ""]
    for i, r in enumerate(reg, 1):
        if r["birth_date"]:
            b = date.fromisoformat(r["birth_date"])
            yosh_s = f"{yosh(b, today)} yosh ({b.strftime('%d.%m.%Y')})"
        else:
            yosh_s = "sana yo'q"
        un = f", @{r['username']}" if r["username"] else ""
        lines.append(f"{i}. {r['full_name']} — {yosh_s}{un}, kirgan: {fmt_sana(r['first_seen'])}")
    if not reg:
        lines.append("Hali hech kim anketa to'ldirmagan.")
    return lines


async def uzun_xabar(message: Message, lines):
    """Telegram 4096 belgidan uzun xabarni qabul qilmaydi — bo'laklab yuboramiz."""
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 4000:
            await message.answer(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await message.answer(chunk)


class FaollikMiddleware(BaseMiddleware):
    """Har bir xabar va tugma bosilishini statistika uchun qayd etadi."""

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is not None and not user.is_bot:
            try:
                touch_user(user, datetime.now(TZ).strftime("%Y-%m-%d"))
            except Exception as e:
                logging.warning("Statistika yozilmadi: %s", e)
        return await handler(event, data)


# ---------------------------------------------------------------- Matn tahlili
# "Dushanba 08:00 Matematika" yoki "Dushanba 08:00-Matematika"
LINE_RE = re.compile(r"^\s*(.+?)\s+(\d{1,2})[:.](\d{2})\s*[-–—:]?\s*(.+?)\s*$")
# "08:00 Matematika" yoki "08:00-Matematika" (kun yuqoridagi qatorda yozilgan)
TIME_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*[-–—:]?\s*(.+?)\s*$")

FORMAT_MISOL = (
    "To'g'ri format:\n"
    "Dushanba\n08:00 Matematika darsi\n09:00 Ingliz tili\n\n"
    "yoki bir qatorda: Dushanba 08:00 Matematika darsi"
)


def day_name(day):
    return "Har kuni" if day == HAR_KUNI else KUNLAR[day]


def parse_day(text: str):
    """'Dushanba', 'dush', 'Har kuni', 'Dushanba:' -> kun raqami yoki None."""
    t = re.sub(r"[\s:\-–—]+", "", text.lower())
    return KUN_ALIAS.get(t)


def _vaqt(hh, mm):
    h, mi = int(hh), int(mm)
    if 0 <= h < 24 and 0 <= mi < 60:
        return f"{h:02d}:{mi:02d}"
    return None


def parse_line(line: str, joriy_kun=None):
    """Bir qatorni tahlil qiladi -> (kun, 'HH:MM', matn) yoki None.
    joriy_kun — yuqoridagi qatorda yozilgan kun (bo'lsa)."""
    m = LINE_RE.match(line)
    if m:
        day_raw, hh, mm, text = m.groups()
        day, t = parse_day(day_raw), _vaqt(hh, mm)
        if day is not None and t:
            return day, t, text
    m = TIME_RE.match(line)
    if m and joriy_kun is not None:
        hh, mm, text = m.groups()
        t = _vaqt(hh, mm)
        if t:
            return joriy_kun, t, text
    return None


def add_from_text(user_id, text):
    added, bad = [], []
    joriy_kun = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        kun = parse_day(line)          # faqat kun nomi yozilgan qator: "Dushanba"
        if kun is not None:
            joriy_kun = kun
            continue
        parsed = parse_line(line, joriy_kun)
        if parsed is None:
            bad.append(line)
            continue
        day, t, task = parsed
        joriy_kun = day                # keyingi qatorlar shu kunga tegishli
        tid = add_task(user_id, day, t, task)
        added.append(f"#{tid} {day_name(day)} {t} — {task}")
    return added, bad


BELGI = {"done": "✅", "skip": "⏯️"}


def bugungi_matn(rows, now, st=None):
    sarlavha = f"📅 Bugun — {KUNLAR[now.weekday()]}, {now.strftime('%d.%m.%Y')}"
    if not rows:
        return sarlavha + "\nBugunga vazifa yo'q."
    st = st or {}
    return sarlavha + "\n" + "\n".join(
        f"{BELGI.get(st.get(r['id']), '⬜')} {r['time']} — {r['text']}" for r in rows)


def hisobot_matn(user_id, now):
    """Kunlik hisobot: necha foiz bajarildi / qoldirildi / bajarilmadi."""
    wd, sana = now.weekday(), now.strftime("%Y-%m-%d")
    rows = get_tasks_for_day(user_id, wd)
    if not rows:
        return None
    st = get_statuses(user_id, sana)
    jami = len(rows)
    done = sum(1 for r in rows if st.get(r["id"]) == "done")
    skip = sum(1 for r in rows if st.get(r["id"]) == "skip")
    yoq = jami - done - skip
    foiz = lambda n: round(n * 100 / jami)
    lines = [
        f"📊 Kundalik hisobot — {KUNLAR[wd]}, {now.strftime('%d.%m.%Y')}",
        f"Bugun {jami} ta vazifa kiritilgan edi:",
        f"✅ Bajarildi: {done} ta ({foiz(done)}%)",
        f"⏯️ Qoldirildi: {skip} ta ({foiz(skip)}%)",
        f"❌ Bajarilmadi: {yoq} ta ({foiz(yoq)}%)",
    ]
    qolgan = [r for r in rows if r["id"] not in st]
    if qolgan:
        lines.append("\nBajarilmaganlar:\n" + "\n".join(f"  {r['time']} — {r['text']}" for r in qolgan))
    return "\n".join(lines)

# ---------------------------------------------------------------- Streak, daraja, reyting
DARAJALAR = [(30, "🏆 Ustoz"), (14, "💎 Intizomli"), (7, "🥇 Faol"), (3, "🔥 Boshlovchi")]


def natija_yoz(user_id, now):
    """Kun oxirida bugungi natijani saqlaydi."""
    rows = get_tasks_for_day(user_id, now.weekday())
    if not rows:
        return
    st = get_statuses(user_id, now.strftime("%Y-%m-%d"))
    done = sum(1 for r in rows if st.get(r["id"]) == "done")
    run("INSERT OR REPLACE INTO natijalar(user_id, sana, jami, done) VALUES (?,?,?,?)",
        (user_id, now.strftime("%Y-%m-%d"), len(rows), done))


def streak(user_id, today: date):
    """Ketma-ket necha kun 100% bajargan."""
    rows = run("SELECT sana, jami, done FROM natijalar WHERE user_id=?", (user_id,), fetch=True)
    days = {r["sana"]: (r["jami"] > 0 and r["done"] >= r["jami"]) for r in rows}
    d = today
    if today.isoformat() not in days:   # bugungi natija hali yozilmagan — kechadan boshlaymiz
        d = today - timedelta(days=1)
    n = 0
    while days.get(d.isoformat()):
        n += 1
        d -= timedelta(days=1)
    return n


def daraja(n):
    for kun, nom in DARAJALAR:
        if n >= kun:
            return nom
    return "🌱 Yangi"


def reyting_matn(today: date, kunlar=7):
    boshi = (today - timedelta(days=kunlar - 1)).isoformat()
    rows = run(
        """SELECT n.user_id, SUM(n.done) AS done, SUM(n.jami) AS jami, u.full_name
           FROM natijalar n LEFT JOIN users u ON u.user_id = n.user_id
           WHERE n.sana >= ? GROUP BY n.user_id HAVING SUM(n.jami) > 0
           ORDER BY 1.0 * SUM(n.done) / SUM(n.jami) DESC, SUM(n.done) DESC LIMIT 10""",
        (boshi,), fetch=True)
    if not rows:
        return "Bu hafta hali natijalar yo'q."
    medal = ["🥇", "🥈", "🥉"]
    lines = [f"🏅 Haftalik reyting ({fmt_sana(boshi)} — {today.strftime('%d.%m.%Y')})", ""]
    for i, r in enumerate(rows):
        ism = r["full_name"] or "Nomsiz"
        foiz = round(r["done"] * 100 / r["jami"])
        lines.append(f"{medal[i] if i < 3 else str(i + 1) + '.'} {ism} — {foiz}% ({r['done']}/{r['jami']})")
    return "\n".join(lines)


def natija_matn(user_id, now, bot_username):
    """Do'stlarga ulashish uchun qisqa karta."""
    rows = get_tasks_for_day(user_id, now.weekday())
    st = get_statuses(user_id, now.strftime("%Y-%m-%d"))
    done = sum(1 for r in rows if st.get(r["id"]) == "done")
    foiz = round(done * 100 / len(rows)) if rows else 0
    n = streak(user_id, now.date())
    return (f"📊 Bugun: {foiz}% ({done}/{len(rows)})\n"
            f"🔥 Streak: {n} kun\n"
            f"{daraja(n)}\n\n@{bot_username}")
def status_tugmalar(task_id, sana):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Bajarildi", callback_data=f"st:done:{task_id}:{sana}"),
        InlineKeyboardButton(text="⏯️ Qoldirildi", callback_data=f"st:skip:{task_id}:{sana}"),
    ]])


# ---------------------------------------------------------------- Buyruqlar
router = Router()
router.message.outer_middleware(FaollikMiddleware())
router.callback_query.outer_middleware(FaollikMiddleware())


# ---- Ro'yxatdan o'tish (anketa)
async def anketa_boshla(message: Message, state: FSMContext, kirish: str):
    await state.set_state(Anketa.ism)
    await message.answer(kirish + "\n\n👤 Ism va familiyangizni yozing (masalan: Aliyev Vali):")


async def royxat_kerak(message: Message, state: FSMContext) -> bool:
    """Ro'yxatdan o'tmagan bo'lsa anketani boshlaydi va True qaytaradi."""
    if is_registered(message.from_user.id):
        return False
    await anketa_boshla(message, state, "Avval tanishib olaylik.")
    return True


@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    u = get_user(message.from_user.id)
    if u and u["full_name"]:
        await state.clear()
        await message.answer(
            f"Xush kelibsiz, {u['full_name']}! Haftalik rejangizni kiriting — "
            "belgilangan kun va soatda eslatib turaman.\n\n"
            "/yordam — qanday foydalanish\n/anketa — ism yoki sanani o'zgartirish"
        )
        return
    await anketa_boshla(message, state, "Salom! Men kundalik botman. Avval tanishib olaylik.")


@router.message(Command("anketa"))
async def anketa(message: Message, state: FSMContext):
    await anketa_boshla(message, state, "Ma'lumotlarni yangilaymiz.")


@router.message(Anketa.ism, F.text, ~F.text.startswith("/"))
async def anketa_ism(message: Message, state: FSMContext):
    ism = " ".join(message.text.split())
    if len(ism.split()) < 2 or len(ism) > 100 or any(ch.isdigit() for ch in ism):
        await message.answer("Ism va familiyani to'liq yozing, masalan: Aliyev Vali")
        return
    await state.update_data(ism=ism)
    await state.set_state(Anketa.sana)
    await message.answer(
        f"Rahmat, {ism}!\n\n🎂 Endi tug'ilgan sanangizni yozing — kun.oy.yil ko'rinishida "
        "(masalan: 15.03.2005):"
    )


@router.message(Anketa.sana, F.text, ~F.text.startswith("/"))
async def anketa_sana(message: Message, state: FSMContext):
    today = datetime.now(TZ).date()
    s = parse_sana(message.text, today)
    if not s:
        await message.answer("Sana tushunilmadi. Kun.oy.yil ko'rinishida yozing, masalan: 15.03.2005")
        return
    data = await state.get_data()
    ism = data.get("ism")
    if not ism:  # bot qayta yoqilgan bo'lsa ism yo'qolgan bo'lishi mumkin
        await anketa_boshla(message, state, "Boshidan boshlaymiz.")
        return
    save_anketa(message.from_user.id, ism, s, today.strftime("%Y-%m-%d"))
    await state.clear()
    await message.answer(
        f"✅ Ro'yxatdan o'tdingiz!\n👤 {ism}\n🎂 {s.strftime('%d.%m.%Y')} ({yosh(s, today)} yosh)\n\n" + YORDAM
    )


# ---- Umumiy buyruqlar
@router.message(Command("yordam", "help"))
async def yordam(message: Message):
    await message.answer(YORDAM)

@router.message(Command("streak"))
async def streak_cmd(message: Message, state: FSMContext):
    if await royxat_kerak(message, state):
        return
    n = streak(message.from_user.id, datetime.now(TZ).date())
    matn = f"🔥 Streak: {n} kun\nDaraja: {daraja(n)}"
    keyingi = next(((k, nom) for k, nom in reversed(DARAJALAR) if k > n), None)
    if keyingi:
        matn += f"\n\nKeyingi daraja {keyingi[1]} — yana {keyingi[0] - n} kun 100% bajaring."
    await message.answer(matn)


@router.message(Command("reyting"))
async def reyting_cmd(message: Message, state: FSMContext):
    if await royxat_kerak(message, state):
        return
    await message.answer(reyting_matn(datetime.now(TZ).date()))


@router.message(Command("natija"))
async def natija_cmd(message: Message, state: FSMContext):
    if await royxat_kerak(message, state):
        return
    me = await message.bot.me()
    await message.answer(natija_matn(message.from_user.id, datetime.now(TZ), me.username))

@router.message(Command("id"))
async def my_id(message: Message):
    await message.answer(f"Sizning Telegram ID: {message.from_user.id}")


# ---- Admin buyruqlari
async def admin_emas(message: Message) -> bool:
    uid = message.from_user.id
    if uid in ADMIN_IDS:
        return False
    if not ADMIN_IDS:
        await message.answer(
            f"Admin hali ko'rsatilmagan. Sizning ID: {uid}\n"
            f"bot.py dagi ADMIN_IDS qatoriga yoki .bat faylga set ADMIN_IDS={uid} qo'shib, botni qayta yoqing."
        )
    else:
        await message.answer("Bu buyruq faqat admin uchun.")
    return True


@router.message(Command("stat", "statistika"))
async def stat(message: Message):
    if await admin_emas(message):
        return
    await message.answer(stat_matn(datetime.now(TZ)))


@router.message(Command("odamlar", "users"))
async def odamlar(message: Message):
    if await admin_emas(message):
        return
    await uzun_xabar(message, odamlar_qatorlar(datetime.now(TZ).date()))


# ---- Reja bilan ishlash
async def _add(message: Message, body: str):
    if not body.strip():
        await message.answer(FORMAT_MISOL)
        return
    added, bad = add_from_text(message.from_user.id, body)
    parts = []
    if added:
        parts.append("✅ Qo'shildi:\n" + "\n".join(added))
    if bad:
        parts.append("⚠️ Tushunilmadi:\n" + "\n".join(bad) + "\n\n" + FORMAT_MISOL)
    await message.answer("\n\n".join(parts))


@router.message(Command("qosh", "add"))
async def qosh(message: Message, state: FSMContext):
    if await royxat_kerak(message, state):
        return
    parts = message.text.split(maxsplit=1)
    await _add(message, parts[1] if len(parts) > 1 else "")


@router.message(Command("royxat", "list"))
async def royxat(message: Message, state: FSMContext):
    if await royxat_kerak(message, state):
        return
    rows = get_tasks(message.from_user.id)
    if not rows:
        await message.answer("Reja hali bo'sh. Vazifa qo'shing:\nDushanba\n08:00 Matematika darsi")
        return
    out, joriy_kun = ["📅 Haftalik reja:"], None
    for r in rows:
        if r["day"] != joriy_kun:
            joriy_kun = r["day"]
            out.append(f"\n{day_name(joriy_kun)}")
        out.append(f"  {r['time']} — {r['text']}  (#{r['id']})")
    await message.answer("\n".join(out))


@router.message(Command("bugun", "today"))
async def bugun(message: Message, state: FSMContext):
    if await royxat_kerak(message, state):
        return
    now = datetime.now(TZ)
    rows = get_tasks_for_day(message.from_user.id, now.weekday())
    st = get_statuses(message.from_user.id, now.strftime("%Y-%m-%d"))
    await message.answer(bugungi_matn(rows, now, st))


@router.message(Command("hisobot", "report"))
async def hisobot(message: Message, state: FSMContext):
    if await royxat_kerak(message, state):
        return
    matn = hisobot_matn(message.from_user.id, datetime.now(TZ))
    await message.answer(matn or "Bugunga vazifa yo'q — hisobot bo'sh.")


@router.callback_query(F.data.startswith("st:"))
async def status_bosildi(call: CallbackQuery):
    _, status, task_id, sana = call.data.split(":")
    set_status(call.from_user.id, int(task_id), sana, status)
    label = "✅ Bajarildi" if status == "done" else "⏯️ Qoldirildi"
    birinchi_qator = (call.message.text or "").split("\n")[0]
    try:
        await call.message.edit_text(f"{birinchi_qator}\n{label}",
                                     reply_markup=status_tugmalar(task_id, sana))
    except Exception:
        pass  # bir xil tugma ikki marta bosilsa Telegram "o'zgarmadi" deydi — e'tibor bermaymiz
    await call.answer("Qayd etildi")


@router.message(Command("ochir", "delete"))
async def ochir(message: Message):
    ids = [int(x) for x in re.findall(r"\d+", message.text)]
    if not ids:
        await message.answer("Raqamini yozing, masalan: /ochir 5\nRaqamlar /royxat da (#5) ko'rinishida turadi.")
        return
    deleted = [i for i in ids if delete_task(message.from_user.id, i)]
    missing = [i for i in ids if i not in deleted]
    text = []
    if deleted:
        text.append("🗑 O'chirildi: " + ", ".join(f"#{i}" for i in deleted))
    if missing:
        text.append("Topilmadi: " + ", ".join(f"#{i}" for i in missing))
    await message.answer("\n".join(text))


@router.message(Command("tozalash", "clear"))
async def tozalash(message: Message):
    n = clear_tasks(message.from_user.id)
    await message.answer(f"🗑 {n} ta vazifa o'chirildi. Reja bo'sh." if n else "Reja allaqachon bo'sh.")


@router.message(F.text, ~F.text.startswith("/"))
async def oddiy_matn(message: Message, state: FSMContext):
    if await royxat_kerak(message, state):
        return
    await _add(message, message.text)


# ---------------------------------------------------------------- Eslatma tsikli
async def safe_send(bot: Bot, user_id: int, text: str, reply_markup=None):
    try:
        await bot.send_message(user_id, text, reply_markup=reply_markup)
    except Exception as e:  # foydalanuvchi botni bloklagan bo'lishi mumkin va h.k.
        logging.warning("Yuborilmadi (%s): %s", user_id, e)


async def eslatma_loop(bot: Bot):
    yuborilgan = set()  # bir vazifa bir kunda ikki marta ketmasligi uchun
    while True:
        now = datetime.now(TZ)
        hhmm, wd, sana = now.strftime("%H:%M"), now.weekday(), now.strftime("%Y-%m-%d")

        for r in due_tasks(wd, hhmm):
            key = (r["id"], sana)
            if key not in yuborilgan:
                yuborilgan.add(key)
                await safe_send(bot, r["user_id"], f"⏰ {hhmm} — {r['text']}",
                                reply_markup=status_tugmalar(r["id"], sana))

        if ERTALABKI_XULOSA and hhmm == ERTALABKI_XULOSA:
            for uid in all_users():
                key = ("xulosa", uid, sana)
                if key not in yuborilgan:
                    yuborilgan.add(key)
                    rows = get_tasks_for_day(uid, wd)
                    if rows:
                        await safe_send(bot, uid, bugungi_matn(rows, now))

        if HISOBOT_VAQTI and hhmm == HISOBOT_VAQTI:
            for uid in all_users():
                key = ("hisobot", uid, sana)
                if key not in yuborilgan:
                    yuborilgan.add(key)
                    matn = hisobot_matn(uid, now)
                    if matn:
                        natija_yoz(uid, now)
                        n = streak(uid, now.date())
                        matn += f"\n\n🔥 Streak: {n} kun — {daraja(n)}"
                        await safe_send(bot, uid, matn)

        if REYTING_VAQTI and wd == REYTING_KUNI and hhmm == REYTING_VAQTI:
            key = ("reyting", sana)
            if key not in yuborilgan:
                yuborilgan.add(key)
                matn = reyting_matn(now.date() - timedelta(days=1))
                for uid in all_users():
                    await safe_send(bot, uid, matn)

        if STAT_VAQTI and hhmm == STAT_VAQTI and ADMIN_IDS:
            key = ("stat", sana)
            if key not in yuborilgan:
                yuborilgan.add(key)
                matn = stat_matn(now)
                for aid in ADMIN_IDS:
                    await safe_send(bot, aid, matn)

        if hhmm == "00:00":
            yuborilgan = {k for k in yuborilgan if k[-1] == sana}

        # keyingi daqiqaning boshigacha uxlaymiz
        await asyncio.sleep(max(1, 60 - datetime.now(TZ).second))


# ---------------------------------------------------------------- Ishga tushirish
async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if "BU_YERGA" in BOT_TOKEN or ":" not in BOT_TOKEN:
        sys.exit("BOT_TOKEN ko'rsatilmagan. @BotFather dan token olib, bot.py yoki .bat faylga qo'ying.")
    init_db()
    bot = Bot(BOT_TOKEN)
    await bot.set_my_commands([          # Telegramdagi "Menu" tugmasi
        BotCommand(command="start",    description="🚀 Boshlash"),
        BotCommand(command="royxat",   description="📅 Haftalik reja"),
        BotCommand(command="bugun",    description="📌 Bugungi vazifalar"),
        BotCommand(command="hisobot",  description="📊 Bugungi hisobot"),
        BotCommand(command="streak",   description="🔥 Streak va daraja"),
        BotCommand(command="reyting",  description="🏅 Haftalik reyting"),
        BotCommand(command="ochir",    description="🗑 Vazifani o'chirish (raqami bilan)"),
        BotCommand(command="tozalash", description="♻️ Hammasini o'chirish"),
        BotCommand(command="anketa",   description="👤 Ism va tug'ilgan sanani o'zgartirish"),
        BotCommand(command="yordam",   description="❓ Qanday foydalanish"),
    ])
    dp = Dispatcher()
    dp.include_router(router)
    dp["eslatma_task"] = asyncio.create_task(eslatma_loop(bot))
    logging.info("Bot ishga tushdi. Vaqt zonasi: %s. Adminlar: %s", TZ, sorted(ADMIN_IDS) or "yo'q")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
