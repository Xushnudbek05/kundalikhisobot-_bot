# Kundalik bot (Telegram)

Haftalik rejani kiritasiz — bot belgilangan kun va soatda eslatib turadi.
Har kuni ertalab 07:00 da bugungi rejani ham yuboradi.

## O'rnatish

1. Telegramda **@BotFather** ga kiring → `/newbot` → bot nomi va username bering → tokenni nusxalang.
2. Python 3.9+ o'rnatilgan bo'lsin.
3. Kutubxonani o'rnating:
   ```
   pip install -r requirements.txt
   ```
4. Tokenni ko'rsating — ikki usuldan biri:
   - `bot.py` ichida `BU_YERGA_BOTFATHER_TOKENINI_QOYING` o'rniga tokenni yozing, **yoki**
   - muhit o'zgaruvchisi orqali:
     ```
     # Windows (cmd)
     set BOT_TOKEN=123456:ABC...
     # Linux / macOS
     export BOT_TOKEN=123456:ABC...
     ```
5. Ishga tushiring:
   ```
   python bot.py
   ```

## Botdan foydalanish

Botga shunchaki yozasiz (bir nechta qatorni birdaniga yuborsa bo'ladi):

```
Dushanba 08:00 Matematika darsi
Dushanba 09:00 Ingliz tili
Seshanba 10:30 Sport zal
Har kuni 07:30 Nonushta
```

Kun nomlari: `Dushanba, Seshanba, Chorshanba, Payshanba, Juma, Shanba, Yakshanba, Har kuni`
(qisqartma ham ishlaydi: `Du, Se, Chor, Pay, Ju, Sh, Yak`; kirill yozuvi ham qabul qilinadi).

| Buyruq | Vazifasi |
|---|---|
| `/royxat` | butun haftalik reja |
| `/bugun` | bugungi vazifalar |
| `/ochir 5` | #5 vazifani o'chirish (`/ochir 5 7 9` — bir nechtasini) |
| `/tozalash` | hammasini o'chirish |
| `/yordam` | qisqa yo'riqnoma |

## Muhim

- Bot ishlashi uchun `python bot.py` **doim yoqiq turishi** kerak — kompyuter o'chsa, eslatma kelmaydi.
  Doimiy ishlashi uchun VPS/serverga qo'yish tavsiya etiladi (`nohup python bot.py &` yoki `systemd`).
- Vaqt zonasi: `Asia/Tashkent` (`bot.py` dagi `TZ` da o'zgartirish mumkin).
- Ertalabki xulosa vaqti: `ERTALABKI_XULOSA = "07:00"` (kerak bo'lmasa `None` qiling).
- Ma'lumotlar `kundalik.db` faylida saqlanadi — bot qayta ishga tushsa ham reja yo'qolmaydi.
