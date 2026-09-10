
"""
Kundalik bot — Telegram uchun haftalik reja va eslatma boti.

Foydalanish:
  1) @BotFather dan token oling
  2) BOT_TOKEN ni pastda yoki muhit o'zgaruvchisida ko'rsating
  3) pip install -r requirements.txt
  4) python bot.py
"""

import asyncio
import logging
import os
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (BotCommand, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

# ---------------------------------------------------------------- Sozlamalar
BOT_TOKEN = "8832900587:AAEU_661ipfze3SYW7yq_rL4AGOiuZl4OB8"
TZ = ZoneInfo("Asia/Tashkent")
DB_PATH = "kundalik.db"
ERTALABKI_XULOSA = "07:00"   # har kuni shu vaqtda bugungi reja yuboriladi; None qilsangiz o'chadi
HISOBOT_VAQTI = "23:59"      # har kuni shu vaqtda kundalik hisobot yuboriladi; None qilsangiz o'chadi

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
    "📌 Vazifa qo'shish uchun shunchaki yozing (har qatorda bittadan):\n\n"
    "Dushanba 08:00 Matematika darsi\n"
    "Dushanba 09:00 Ingliz tili\n"
    "Seshanba 10:30 Sport zal\n"
    "Har kuni 07:30 Nonushta\n\n"
    "Buyruqlar:\n"
    "/royxat — butun haftalik reja\n"
    "/bugun — bugungi vazifalar\n"
    "/hisobot — bugungi hisobot (necha % bajarildi)\n"
    "/ochir 5 — #5 vazifani o'chirish (bir nechtasini ham: /ochir 5 7 9)\n"
    "/tozalash — hammasini o'chirish\n"
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


def init_db():
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


# ---------------------------------------------------------------- Matn tahlili
LINE_RE = re.compile(r"^\s*(.+?)\s+(\d{1,2})[:.](\d{2})\s+(.+?)\s*$")


def day_name(day):
    return "Har kuni" if day == HAR_KUNI else KUNLAR[day]


def parse_line(line: str):
    """'Dushanba 08:00 Matematika' -> (0, '08:00', 'Matematika') yoki None."""
    m = LINE_RE.match(line)
    if not m:
        return None
    day_raw, hh, mm, text = m.groups()
    day = KUN_ALIAS.get(re.sub(r"\s+", "", day_raw.lower()))
    h, mi = int(hh), int(mm)
    if day is None or not (0 <= h < 24 and 0 <= mi < 60):
        return None
    return day, f"{h:02d}:{mi:02d}", text


def add_from_text(user_id, text):
    added, bad = [], []
    for line in text.splitlines():
        if not line.strip():
            continue
        parsed = parse_line(line)
        if parsed is None:
            bad.append(line.strip())
            continue
        day, t, task = parsed
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


def status_tugmalar(task_id, sana):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Bajarildi", callback_data=f"st:done:{task_id}:{sana}"),
        InlineKeyboardButton(text="⏯️ Qoldirildi", callback_data=f"st:skip:{task_id}:{sana}"),
    ]])


# ---------------------------------------------------------------- Buyruqlar
router = Router()


@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Salom! Men kundalik botman. Haftalik rejangizni kiriting — "
        "belgilangan kun va soatda eslatib turaman."
    )


@router.message(Command("yordam", "help"))
async def yordam(message: Message):
    await message.answer(YORDAM)


async def _add(message: Message, body: str):
    if not body.strip():
        await message.answer("Format: Dushanba 08:00 Matematika darsi")
        return
    added, bad = add_from_text(message.from_user.id, body)
    parts = []
    if added:
        parts.append("✅ Qo'shildi:\n" + "\n".join(added))
    if bad:
        parts.append("⚠️ Tushunilmadi:\n" + "\n".join(bad) +
                     "\n\nTo'g'ri format: Dushanba 08:00 Matematika darsi")
    await message.answer("\n\n".join(parts))


@router.message(Command("qosh", "add"))
async def qosh(message: Message):
    parts = message.text.split(maxsplit=1)
    await _add(message, parts[1] if len(parts) > 1 else "")


@router.message(Command("royxat", "list"))
async def royxat(message: Message):
    rows = get_tasks(message.from_user.id)
    if not rows:
        await message.answer("Reja hali bo'sh. Vazifa qo'shing:\nDushanba 08:00 Matematika darsi")
        return
    out, joriy_kun = ["📅 Haftalik reja:"], None
    for r in rows:
        if r["day"] != joriy_kun:
            joriy_kun = r["day"]
            out.append(f"\n{day_name(joriy_kun)}")
        out.append(f"  {r['time']} — {r['text']}  (#{r['id']})")
    await message.answer("\n".join(out))


@router.message(Command("bugun", "today"))
async def bugun(message: Message):
    now = datetime.now(TZ)
    rows = get_tasks_for_day(message.from_user.id, now.weekday())
    st = get_statuses(message.from_user.id, now.strftime("%Y-%m-%d"))
    await message.answer(bugungi_matn(rows, now, st))


@router.message(Command("hisobot", "report"))
async def hisobot(message: Message):
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
async def oddiy_matn(message: Message):
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
                        await safe_send(bot, uid, matn)

        if hhmm == "00:00":
            yuborilgan = {k for k in yuborilgan if k[-1] == sana}

        # keyingi daqiqaning boshigacha uxlaymiz
        await asyncio.sleep(max(1, 60 - datetime.now(TZ).second))


# ---------------------------------------------------------------- Ishga tushirish
async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if "BU_YERGA" in BOT_TOKEN or ":" not in BOT_TOKEN:
        sys.exit("BOT_TOKEN ko'rsatilmagan. @BotFather dan token olib, bot.py yoki muhit o'zgaruvchisiga qo'ying.")
    init_db()
    bot = Bot(BOT_TOKEN)
    await bot.set_my_commands([          # Telegramdagi "Menu" tugmasi
        BotCommand(command="royxat",   description="📅 Haftalik reja"),
        BotCommand(command="bugun",    description="📌 Bugungi vazifalar"),
        BotCommand(command="hisobot",  description="📊 Bugungi hisobot"),
        BotCommand(command="ochir",    description="🗑 Vazifani o'chirish (raqami bilan)"),
        BotCommand(command="tozalash", description="♻️ Hammasini o'chirish"),
        BotCommand(command="yordam",   description="❓ Qanday foydalanish"),
    ])
    dp = Dispatcher()
    dp.include_router(router)
    dp["eslatma_task"] = asyncio.create_task(eslatma_loop(bot))
    logging.info("Bot ishga tushdi. Vaqt zonasi: %s", TZ)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())