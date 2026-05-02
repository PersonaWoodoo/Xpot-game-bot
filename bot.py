import asyncio, random, sqlite3, hashlib, time, json, html, string, re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, Message, ChatMemberUpdated
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode

TOKEN = "8134237711:AAH5M0JJULkrl0yyOdvfCtIswRPqRtt_3hg"
ADMIN_IDS = [8478884644, 8293927811]
MIN_BET = 100
DAILY_BONUS_MIN, DAILY_BONUS_MAX = 100, 2000
WELCOME_BONUS = 1000
REF_REWARD, REF_REFERRAL_BONUS = 5000, 500
TRANSFER_FEE = 0.035
BANK_TERMS = {7: 0.01, 14: 0.02, 30: 0.05}

VIP_LEVELS = [
    ("🥉 Bronze", 0, 0), ("🥈 Silver", 100000, 1),
    ("🥇 Gold", 500000, 2), ("💎 Platinum", 2000000, 3),
    ("👑 Diamond", 10000000, 5),
]

# множители
TOWER_MULT = [1.20, 1.48, 1.86, 2.35, 2.95, 3.75, 4.85, 6.15]
GOLD_MULT = [1.15, 1.35, 1.62, 2.0, 2.55, 3.25, 4.2]
DIAMOND_MULT = [1.12, 1.28, 1.48, 1.72, 2.02, 2.4, 2.92, 3.6]
RED_NUMS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
FOOTBALL_MULT = {"гол": 1.6, "мимо": 2.2}
DARTS_MULT = {"центр": 2.0, "край": 1.5, "мимо": 0}

bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# ---------- БАЗА ДАННЫХ ----------
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()
cur.executescript("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 5000,
    total_wagered INTEGER DEFAULT 0, total_won INTEGER DEFAULT 0,
    total_lost INTEGER DEFAULT 0, referral_code TEXT UNIQUE,
    referrer_id INTEGER, last_daily_bonus TEXT, daily_streak INTEGER DEFAULT 0,
    welcome_bonus_claimed INTEGER DEFAULT 0, games_played_today INTEGER DEFAULT 0,
    custom_status TEXT, mute_games_until INTEGER DEFAULT 0,
    mute_chat_until INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS game_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, game_type TEXT,
    bet_amount INTEGER, multiplier REAL, win_amount INTEGER, result TEXT,
    details TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER,
    referred_id INTEGER, earned_amount INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS banned_users (
    user_id INTEGER PRIMARY KEY, banned_at INTEGER, reason TEXT, banned_until INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS promocodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE,
    bonus_amount INTEGER, max_uses INTEGER, used_count INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS used_promocodes (
    user_id INTEGER, code TEXT, used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS checks (
    code TEXT PRIMARY KEY, creator_id INTEGER, per_user INTEGER,
    remaining INTEGER, used TEXT
);
CREATE TABLE IF NOT EXISTS bank_deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, principal INTEGER,
    rate REAL, term_days INTEGER, opened_at INTEGER,
    status TEXT DEFAULT 'active', closed_at INTEGER
);
CREATE TABLE IF NOT EXISTS clans (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE,
    owner_id INTEGER, balance INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS clan_members (
    user_id INTEGER PRIMARY KEY, clan_id INTEGER,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")
conn.commit()

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
def parse_amount(text: str, balance: int = 0) -> int:
    t = text.lower().strip()
    if t in ("все", "всё"): return balance
    if t in ("пол", "половина"): return balance // 2
    mults = {'ккк': 1_000_000_000, 'кк': 1_000_000, 'к': 1_000,
             'kkk': 1_000_000_000, 'kk': 1_000_000, 'k': 1_000,
             'm': 1_000_000, 'b': 1_000_000_000}
    for suf, m in mults.items():
        if t.endswith(suf):
            num = t[:-len(suf)] or '1'
            try: return int(float(num) * m)
            except: return 0
    try: return int(t)
    except: return 0

def fmt_money(v: int) -> str:
    if v >= 1_000_000_000: return f"{v/1_000_000_000:.1f}ккк POCX"
    if v >= 1_000_000: return f"{v/1_000_000:.1f}кк POCX"
    if v >= 1_000: return f"{v/1_000:.1f}к POCX"
    return f"{v} POCX"

def add_pocx(uid: int, amount: int):
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, uid))
    if cur.rowcount == 0:
        cur.execute("INSERT INTO users (user_id, balance) VALUES (?,?)", (uid, 5000+amount))
    conn.commit()

def remove_pocx(uid: int, amount: int) -> bool:
    cur.execute("SELECT balance FROM users WHERE user_id = ?", (uid,))
    r = cur.fetchone()
    if not r or r[0] < amount: return False
    cur.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, uid))
    conn.commit()
    return True

def get_user(uid: int):
    cur.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
    r = cur.fetchone()
    if not r: return None
    return {"user_id": r[0], "username": r[1], "balance": r[2],
            "total_wagered": r[3] or 0, "total_won": r[4] or 0,
            "total_lost": r[5] or 0, "referral_code": r[6],
            "daily_streak": r[9] or 0, "welcome_bonus_claimed": r[10],
            "games_played_today": r[11] or 0, "custom_status": r[12],
            "mute_games_until": r[13] or 0, "mute_chat_until": r[14] or 0}

def get_vip(wagered: int):
    for lvl in reversed(VIP_LEVELS):
        if wagered >= lvl[1]: return lvl[0], lvl[2]
    return VIP_LEVELS[0][0], 0

def is_banned(uid: int) -> bool:
    cur.execute("SELECT banned_until FROM banned_users WHERE user_id = ?", (uid,))
    r = cur.fetchone()
    if not r: return False
    if r[0] > 0 and int(time.time()) > r[0]:
        cur.execute("DELETE FROM banned_users WHERE user_id = ?", (uid,)); conn.commit()
        return False
    return True

def is_muted_games(uid: int) -> bool:
    u = get_user(uid)
    if not u: return False
    if u["mute_games_until"] > 0 and int(time.time()) > u["mute_games_until"]:
        cur.execute("UPDATE users SET mute_games_until = 0 WHERE user_id = ?", (uid,)); conn.commit()
        return False
    return u["mute_games_until"] > 0

def is_muted_chat(uid: int) -> bool:
    u = get_user(uid)
    if not u: return False
    if u["mute_chat_until"] > 0 and int(time.time()) > u["mute_chat_until"]:
        cur.execute("UPDATE users SET mute_chat_until = 0 WHERE user_id = ?", (uid,)); conn.commit()
        return False
    return u["mute_chat_until"] > 0

def record_game(uid, game_type, bet, mult, win, result, details):
    cur.execute("UPDATE users SET total_wagered = total_wagered + ?, total_won = total_won + ?, total_lost = total_lost + ?, games_played_today = games_played_today + 1 WHERE user_id = ?",
                (bet, win if result == "win" else 0, bet if result == "loss" else 0, uid))
    cur.execute("INSERT INTO game_history (user_id, game_type, bet_amount, multiplier, win_amount, result, details) VALUES (?,?,?,?,?,?,?)",
                (uid, game_type, bet, mult, win, result, json.dumps(details)))
    conn.commit()

def resolve_user_id(arg: str) -> int:
    """Получить user_id из @username или числа"""
    arg = arg.strip().lstrip("@")
    if arg.isdigit():
        return int(arg)
    cur.execute("SELECT user_id FROM users WHERE username = ?", (arg,))
    r = cur.fetchone()
    return r[0] if r else None

def mention_user(uid: int, name: str = None) -> str:
    return f'<a href="tg://user?id={uid}">{html.escape(name or str(uid))}</a>'

# ---------- ГЛАВНОЕ МЕНЮ ----------
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🎮 Игры"), KeyboardButton(text="💰 Финансы")],
    [KeyboardButton(text="🏆 Топ"), KeyboardButton(text="🎁 Бонусы")],
    [KeyboardButton(text="👥 Рефералы"), KeyboardButton(text="📊 Статистика")],
    [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🏦 Банк")],
    [KeyboardButton(text="🏰 Кланы"), KeyboardButton(text="👑 Админ")],
    [KeyboardButton(text="◀️ Главное меню")]
], resize_keyboard=True)

games_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🗼 Башня"), KeyboardButton(text="🥇 Золото")],
    [KeyboardButton(text="💎 Алмазы"), KeyboardButton(text="💣 Мины")],
    [KeyboardButton(text="🎴 Очко"), KeyboardButton(text="🎡 Рулетка")],
    [KeyboardButton(text="📈 Краш"), KeyboardButton(text="🎲 Кубик")],
    [KeyboardButton(text="🎯 Кости"), KeyboardButton(text="⚽ Футбол")],
    [KeyboardButton(text="🏀 Баскет"), KeyboardButton(text="🎯 Дартс")],
    [KeyboardButton(text="◀️ Главное меню")]
], resize_keyboard=True)

# ---------- СТАРТ ----------
@dp.message(Command("start"))
async def start(msg: Message):
    uid = msg.from_user.id
    uname = msg.from_user.username
    user = get_user(uid)
    if not user:
        code = hashlib.md5(f"{uid}{time.time()}".encode()).hexdigest()[:8]
        cur.execute("INSERT INTO users (user_id, username, referral_code, balance) VALUES (?,?,?,5000)", (uid, uname, code))
        conn.commit()
        user = get_user(uid)
    # рефералы и чеки из ссылки
    args = msg.text.split()
    if len(args) > 1:
        if args[1].startswith("ref"):
            ref_code = args[1][3:]
            ref = cur.execute("SELECT user_id FROM users WHERE referral_code = ?", (ref_code,)).fetchone()
            if ref and ref[0] != uid:
                if not cur.execute("SELECT 1 FROM referrals WHERE referrer_id=? AND referred_id=?", (ref[0], uid)).fetchone():
                    add_pocx(ref[0], REF_REWARD); add_pocx(uid, REF_REFERRAL_BONUS)
                    cur.execute("INSERT INTO referrals (referrer_id, referred_id, earned_amount) VALUES (?,?,?)", (ref[0], uid, REF_REWARD))
                    conn.commit()
        elif args[1].startswith("check_"):
            code = args[1][6:]
            row = cur.execute("SELECT per_user, remaining, used FROM checks WHERE code=?", (code,)).fetchone()
            if row and row[1] > 0:
                used = json.loads(row[2]) if row[2] else []
                if str(uid) not in used:
                    add_pocx(uid, row[0]); used.append(str(uid))
                    cur.execute("UPDATE checks SET remaining=remaining-1, used=? WHERE code=?", (json.dumps(used), code)); conn.commit()
    vip, _ = get_vip(user["total_wagered"])
    await msg.answer(
        f"🎰 <b>POCX Casino</b>\n💰 {fmt_money(user['balance'])} | {vip}\n"
        f"🎮 Игры, 🏦 Банк, 🏰 Кланы\n"
        f"💸 Передать: ответь на сообщение и напиши <code>передать [сумма]</code>",
        reply_markup=main_kb
    )

@dp.message(F.text == "◀️ Главное меню")
async def back_menu(msg: Message):
    user = get_user(msg.from_user.id); vip, _ = get_vip(user["total_wagered"])
    await msg.answer(f"🎰 Главное меню\n💰 {fmt_money(user['balance'])} | {vip}", reply_markup=main_kb)

# ---------- ПРОФИЛЬ / СТАТИСТИКА / ТОП ----------
@dp.message(F.text.in_({"👤 Профиль", "профиль", "п"}))
async def profile(msg: Message):
    u = get_user(msg.from_user.id); vip, _ = get_vip(u["total_wagered"])
    await msg.answer(f"👤 {msg.from_user.first_name}\n💰 {fmt_money(u['balance'])}\n💎 {vip}\n🏷 {u.get('custom_status','-')}")

@dp.message(F.text.in_({"📊 Статистика", "статистика", "ст"}))
async def stats(msg: Message):
    u = get_user(msg.from_user.id)
    played = cur.execute("SELECT COUNT(*) FROM game_history WHERE user_id=?", (msg.from_user.id,)).fetchone()[0]
    wins = cur.execute("SELECT COUNT(*) FROM game_history WHERE user_id=? AND result='win'", (msg.from_user.id,)).fetchone()[0]
    best = cur.execute("SELECT MAX(multiplier) FROM game_history WHERE user_id=? AND result='win'", (msg.from_user.id,)).fetchone()[0] or 0
    await msg.answer(f"📊 Игр: {played} | Побед: {wins} | Лучший x{best:.2f}\n💰 Вейджер: {fmt_money(u['total_wagered'])}")

@dp.message(F.text.in_({"🏆 Топ", "топ", "т"}))
async def top(msg: Message):
    rows = cur.execute("SELECT user_id, username, total_won FROM users ORDER BY total_won DESC LIMIT 10").fetchall()
    medals = ["🥇","🥈","🥉"]
    text = "🏆 <b>Топ-10</b>\n"
    for i, r in enumerate(rows):
        m = medals[i] if i < 3 else f"{i+1}."
        name = r[1] or f"ID{r[0]}"
        text += f"{m} {name} — {fmt_money(r[2])}\n"
    await msg.answer(text)

# ---------- БОНУСЫ ----------
@dp.message(F.text.in_({"🎁 Бонусы", "бонусы", "бонус", "бн"}))
async def bon_menu(msg: Message):
    await msg.answer("🎁 Ежедневный бонус / 🆕 Приветственный / 🔑 Промокод / 🧾 Чеки", reply_markup=ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎁 Ежедневный бонус"), KeyboardButton(text="🆕 Приветственный бонус")],
        [KeyboardButton(text="🔑 Промокод"), KeyboardButton(text="🧾 Чеки")],
        [KeyboardButton(text="◀️ Главное меню")]
    ], resize_keyboard=True))

@dp.message(F.text == "🎁 Ежедневный бонус")
async def daily(msg: Message):
    uid = msg.from_user.id
    row = cur.execute("SELECT last_daily_bonus, daily_streak FROM users WHERE user_id=?", (uid,)).fetchone()
    last, streak = row[0] if row else None, row[1] if row else 0
    if last and datetime.now() - datetime.fromisoformat(last) < timedelta(days=1):
        await msg.answer("❌ Уже получил!"); return
    bonus = int(random.randint(DAILY_BONUS_MIN, DAILY_BONUS_MAX) * (1 + min(streak*0.05, 0.5)))
    add_pocx(uid, bonus)
    cur.execute("UPDATE users SET last_daily_bonus=CURRENT_TIMESTAMP, daily_streak=daily_streak+1 WHERE user_id=?", (uid,))
    conn.commit()
    await msg.answer(f"🎁 +{bonus:,} POCX | 🔥 {streak+1} дн.")

@dp.message(F.text == "🆕 Приветственный бонус")
async def welc(msg: Message):
    uid = msg.from_user.id
    if get_user(uid)["welcome_bonus_claimed"]:
        await msg.answer("❌ Уже получен!"); return
    add_pocx(uid, WELCOME_BONUS)
    cur.execute("UPDATE users SET welcome_bonus_claimed=1 WHERE user_id=?", (uid,)); conn.commit()
    await msg.answer(f"🎁 +{WELCOME_BONUS} POCX")

# ---------- ПРОМОКОДЫ ----------
@dp.message(F.text == "🔑 Промокод")
async def promo_ask(msg: Message, state: FSMContext):
    await state.set_state(GameStates.promo_code)  # определим FSM ниже
    await msg.answer("Введи код:")

# ---------- ЧЕКИ ----------
@dp.message(F.text == "🧾 Чеки")
async def checks_info(msg: Message):
    await msg.answer(
        "📋 <b>Чеки</b>\n"
        "<code>чек создать [сумма] [кол-во]</code>\n"
        "<code>чек активировать [код]</code>\n"
        "<code>чек мои</code>"
    )

@dp.message(lambda m: m.text and m.text.lower().startswith("чек создать"))
async def check_create(msg: Message):
    parts = msg.text.split()
    if len(parts) < 4: await msg.answer("❌ <code>чек создать 1000 5</code>"); return
    try:
        amt = parse_amount(parts[2])
        cnt = int(parts[3])
        if amt <= 0 or amt > 5_000_000 or cnt <= 0 or cnt > 50: raise ValueError
    except: await msg.answer("❌ Сумма 1-5M, кол-во 1-50"); return
    total = amt * cnt
    if not remove_pocx(msg.from_user.id, total): await msg.answer("❌ Недостаточно средств"); return
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    cur.execute("INSERT INTO checks (code, creator_id, per_user, remaining, used) VALUES (?,?,?,?,'[]')", (code, msg.from_user.id, amt, cnt))
    conn.commit()
    link = f"t.me/{(await bot.get_me()).username}?start=check_{code}"
    await msg.answer(f"✅ Чек <code>{code}</code>\n🔗 {link}\n💰 {fmt_money(amt)} x{cnt}")

@dp.message(lambda m: m.text and m.text.lower().startswith("чек активировать"))
async def check_claim(msg: Message):
    parts = msg.text.split()
    if len(parts) < 3: await msg.answer("❌ <code>чек активировать КОД</code>"); return
    code = parts[2].upper()
    row = cur.execute("SELECT per_user, remaining, used FROM checks WHERE code=?", (code,)).fetchone()
    if not row or row[1] <= 0: await msg.answer("❌ Недействителен"); return
    used = json.loads(row[2]) if row[2] else []
    if str(msg.from_user.id) in used: await msg.answer("❌ Уже использован"); return
    add_pocx(msg.from_user.id, row[0]); used.append(str(msg.from_user.id))
    cur.execute("UPDATE checks SET remaining=remaining-1, used=? WHERE code=?", (json.dumps(used), code)); conn.commit()
    await msg.answer(f"✅ +{fmt_money(row[0])}")

@dp.message(F.text.lower() == "чек мои")
async def check_my(msg: Message):
    rows = cur.execute("SELECT code, per_user, remaining FROM checks WHERE creator_id=? ORDER BY rowid DESC LIMIT 10", (msg.from_user.id,)).fetchall()
    if not rows: await msg.answer("📋 Нет чеков")
    else:
        text = "📋 Ваши чеки:\n"
        for r in rows: text += f"<code>{r[0]}</code> – {fmt_money(r[1])} (ост.{r[2]})\n"
        await msg.answer(text)

# ---------- РЕФЕРАЛЫ ----------
@dp.message(F.text.in_({"👥 Рефералы", "рефералы", "р"}))
async def ref(msg: Message):
    u = get_user(msg.from_user.id)
    cnt = cur.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (msg.from_user.id,)).fetchone()[0]
    earned = cur.execute("SELECT COALESCE(SUM(earned_amount),0) FROM referrals WHERE referrer_id=?", (msg.from_user.id,)).fetchone()[0]
    link = f"t.me/{(await bot.get_me()).username}?start=ref{u['referral_code']}"
    await msg.answer(f"👥 Рефералы\n🔗 {link}\n👤 Приглашено: {cnt}\n💰 Заработано: {fmt_money(earned)}")

# ---------- ПЕРЕДАЧА ----------
@dp.message(lambda m: m.text and m.text.lower().split()[0] in ("передать","п","дать","накинуть") and m.reply_to_message)
async def transfer(msg: Message):
    parts = msg.text.split()
    if len(parts) < 2: await msg.reply("❌ Укажи сумму"); return
    try:
        amount = parse_amount(parts[1])
        if amount < 100: raise ValueError
    except: await msg.reply("❌ Сумма от 100"); return
    user = get_user(msg.from_user.id)
    fee = int(amount * TRANSFER_FEE)
    total = amount + fee
    if user["balance"] < total: await msg.reply(f"❌ Нужно {fmt_money(total)} (комиссия {TRANSFER_FEE*100:.1f}%)"); return
    target = msg.reply_to_message.from_user.id
    if target == msg.from_user.id: await msg.reply("❌ Нельзя себе"); return
    remove_pocx(msg.from_user.id, total); add_pocx(target, amount)
    await msg.reply(f"✅ Переведено {fmt_money(amount)} -> {msg.reply_to_message.from_user.first_name}\n💸 Комиссия {fmt_money(fee)}")

# ---------- КЛАНЫ ----------
@dp.message(F.text.in_({"🏰 Кланы", "кланы", "клан"}))
async def clans_info(msg: Message):
    await msg.answer(
        "🏰 <b>Кланы</b>\n"
        "<code>клан создать [название]</code>\n"
        "<code>клан вступить [название]</code>\n"
        "<code>клан выйти</code>\n"
        "<code>клан баланс</code>\n"
        "<code>клан пополнить [сумма]</code>\n"
        "<code>клан инфо [название]</code>"
    )

@dp.message(lambda m: m.text.lower().startswith("клан создать"))
async def clan_create(msg: Message):
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 3: await msg.answer("❌ Название клана"); return
    name = parts[2].strip()
    if cur.execute("SELECT 1 FROM clans WHERE name=?", (name,)).fetchone(): await msg.answer("❌ Уже существует"); return
    cur.execute("INSERT INTO clans (name, owner_id) VALUES (?,?)", (name, msg.from_user.id))
    cur.execute("INSERT OR REPLACE INTO clan_members (user_id, clan_id) VALUES (?, last_insert_rowid())", (msg.from_user.id,))
    conn.commit()
    await msg.answer(f"🏰 Клан '{name}' создан!")

@dp.message(lambda m: m.text.lower().startswith("клан вступить"))
async def clan_join(msg: Message):
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 3: await msg.answer("❌ Название клана"); return
    name = parts[2].strip()
    clan = cur.execute("SELECT id FROM clans WHERE name=?", (name,)).fetchone()
    if not clan: await msg.answer("❌ Не найден"); return
    cur.execute("INSERT OR REPLACE INTO clan_members (user_id, clan_id) VALUES (?,?)", (msg.from_user.id, clan[0]))
    conn.commit()
    await msg.answer(f"🏰 Ты вступил в клан '{name}'!")

@dp.message(lambda m: m.text.lower() == "клан выйти")
async def clan_leave(msg: Message):
    cur.execute("DELETE FROM clan_members WHERE user_id=?", (msg.from_user.id,))
    if cur.rowcount: await msg.answer("Ты покинул клан")
    else: await msg.answer("Ты не в клане")
    conn.commit()

@dp.message(lambda m: m.text.lower() == "клан баланс")
async def clan_balance(msg: Message):
    member = cur.execute("SELECT clan_id FROM clan_members WHERE user_id=?", (msg.from_user.id,)).fetchone()
    if not member: await msg.answer("Не в клане"); return
    clan = cur.execute("SELECT name, balance FROM clans WHERE id=?", (member[0],)).fetchone()
    await msg.answer(f"🏰 Клан {clan[0]}: {fmt_money(clan[1])}")

@dp.message(lambda m: m.text.lower().startswith("клан пополнить"))
async def clan_deposit(msg: Message):
    parts = msg.text.split()
    if len(parts) < 3: await msg.answer("❌ <code>клан пополнить 1000</code>"); return
    try:
        amt = parse_amount(parts[2])
    except: await msg.answer("❌ Сумма"); return
    if not remove_pocx(msg.from_user.id, amt): await msg.answer("❌ Недостаточно средств"); return
    member = cur.execute("SELECT clan_id FROM clan_members WHERE user_id=?", (msg.from_user.id,)).fetchone()
    if not member: await msg.answer("Ты не в клане"); add_pocx(msg.from_user.id, amt); return
    cur.execute("UPDATE clans SET balance = balance + ? WHERE id=?", (amt, member[0])); conn.commit()
    await msg.answer(f"🏰 Внесено {fmt_money(amt)} в клан")

@dp.message(lambda m: m.text.lower().startswith("клан инфо"))
async def clan_info(msg: Message):
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 3: await msg.answer("Укажите название"); return
    name = parts[2]
    clan = cur.execute("SELECT id, owner_id, balance FROM clans WHERE name=?", (name,)).fetchone()
    if not clan: await msg.answer("❌ Не найден"); return
    members = cur.execute("SELECT user_id FROM clan_members WHERE clan_id=?", (clan[0],)).fetchall()
    owner_name = (await bot.get_chat(clan[1])).first_name
    text = f"🏰 Клан {name}\n👑 Владелец: {owner_name}\n💰 Баланс: {fmt_money(clan[2])}\n👥 Участников: {len(members)}"
    await msg.answer(text)

# ---------- БАНК ----------
@dp.message(F.text.in_({"🏦 Банк", "банк"}))
async def bank_info(msg: Message):
    closed, payout = check_and_withdraw_deposits(msg.from_user.id)
    if closed: await msg.answer(f"✅ Снято {closed} депозитов: +{fmt_money(payout)}")
    await msg.answer(
        "🏦 <b>Банк</b>\n"
        "<code>банк открыть [сумма] [срок:7/14/30]</code>\n"
        "<code>банк список</code>\n"
        "<code>банк снять</code>\n"
        "📈 7д +1% | 14д +2% | 30д +5%"
    )

def check_and_withdraw_deposits(uid):
    now = int(time.time())
    deps = cur.execute("SELECT id, principal, rate, term_days, opened_at FROM bank_deposits WHERE user_id=? AND status='active'", (uid,)).fetchall()
    total, closed = 0, 0
    for d in deps:
        if now - d[4] >= d[3] * 86400:
            payout = int(d[1] * (1 + d[2]))
            add_pocx(uid, payout); total += payout; closed += 1
            cur.execute("UPDATE bank_deposits SET status='closed', closed_at=? WHERE id=?", (now, d[0]))
    conn.commit()
    return closed, total

@dp.message(lambda m: m.text.lower().startswith("банк открыть"))
async def bank_open(msg: Message):
    parts = msg.text.split()
    if len(parts) < 4: await msg.answer("❌ <code>банк открыть 1000 7</code>"); return
    try:
        amt = parse_amount(parts[2]); term = int(parts[3])
        if amt < 1000 or term not in BANK_TERMS: raise ValueError
    except: await msg.answer("❌ Сумма от 1000, срок 7/14/30"); return
    if not remove_pocx(msg.from_user.id, amt): await msg.answer("❌ Недостаточно средств"); return
    rate = BANK_TERMS[term]
    cur.execute("INSERT INTO bank_deposits (user_id, principal, rate, term_days, opened_at, status) VALUES (?,?,?,?,?,'active')",
                (msg.from_user.id, amt, rate, term, int(time.time())))
    conn.commit()
    await msg.answer(f"✅ Депозит {fmt_money(amt)} на {term}д (+{int(rate*100)}%)")

@dp.message(F.text.lower() == "банк список")
async def bank_list(msg: Message):
    deps = cur.execute("SELECT id, principal, rate, term_days, opened_at FROM bank_deposits WHERE user_id=? AND status='active'", (msg.from_user.id,)).fetchall()
    if not deps: await msg.answer("Нет активных"); return
    now = int(time.time())
    text = "📜 <b>Депозиты</b>\n"
    for d in deps:
        left = max(0, d[3] - (now - d[4])//86400)
        text += f"#{d[0]}: {fmt_money(d[1])} | +{int(d[2]*100)}% | {left}д\n"
    await msg.answer(text)

@dp.message(F.text.lower() == "банк снять")
async def bank_withdraw(msg: Message):
    closed, payout = check_and_withdraw_deposits(msg.from_user.id)
    if closed: await msg.answer(f"✅ Снято {closed} депозитов: +{fmt_money(payout)}")
    else: await msg.answer("Нет созревших")

# ==================== АДМИНКА (текстовые команды) ====================
@dp.message(F.text.in_({"👑 Админ", "админ"}))
async def admin_menu(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: await msg.answer("❌ Нет доступа"); return
    await msg.answer(
        "👑 <b>Админ-панель</b>\n"
        "<code>выдать [ID/@uname] [сумма]</code>\n"
        "<code>забрать [ID/@uname] [сумма]</code>\n"
        "<code>бан [ID/@uname] [часы(0=навсегда)] [причина]</code>\n"
        "<code>разбан [ID/@uname]</code>\n"
        "<code>мут игры [ID/@uname] [часы]</code>\n"
        "<code>мут чат [ID/@uname] [часы]</code>\n"
        "<code>размут игры [ID/@uname]</code>\n"
        "<code>размут чат [ID/@uname]</code>\n"
        "<code>стата [ID/@uname]</code>\n"
        "Также можно отвечать на сообщение с командой без указания ID"
    )

# Общий парсер для админских команд с поддержкой reply
async def admin_command(msg: Message, action: str):
    if msg.from_user.id not in ADMIN_IDS: return
    # Определяем цель: если reply, то из ответа, иначе из текста
    target_id = None
    if msg.reply_to_message:
        target_id = msg.reply_to_message.from_user.id
        # если в тексте есть сумма/доп.параметры, они будут после команды
        parts = msg.text.split()
        # первая часть = команда, остальное параметры
        params = parts[1:] if len(parts) > 1 else []
    else:
        parts = msg.text.split()
        if len(parts) < 2: await msg.reply("❌ Укажите ID/@username"); return
        target = resolve_user_id(parts[1])
        if target is None: await msg.reply("❌ Пользователь не найден"); return
        target_id = target
        params = parts[2:] if len(parts) > 2 else []
    # Выполняем действие
    if action == "выдать":
        if not params: await msg.reply("❌ Укажите сумму"); return
        try: amt = parse_amount(params[0]); add_pocx(target_id, amt)
        except: await msg.reply("❌ Сумма"); return
        await msg.reply(f"✅ Выдано {fmt_money(amt)} -> {mention_user(target_id)}")
    elif action == "забрать":
        if not params: await msg.reply("❌ Укажите сумму"); return
        try: amt = parse_amount(params[0])
        except: await msg.reply("❌ Сумма"); return
        if remove_pocx(target_id, amt): await msg.reply(f"✅ Забрано {fmt_money(amt)} у {mention_user(target_id)}")
        else: await msg.reply("❌ Недостаточно средств")
    elif action == "бан":
        hours = 0; reason = ""
        if params:
            try: hours = int(params[0]); reason = " ".join(params[1:])
            except: reason = " ".join(params)
        until = int(time.time()) + hours*3600 if hours > 0 else 0
        cur.execute("INSERT OR REPLACE INTO banned_users (user_id, banned_at, reason, banned_until) VALUES (?,?,?,?)",
                    (target_id, int(time.time()), reason, until))
        conn.commit()
        await msg.reply(f"✅ Пользователь {mention_user(target_id)} забанен {'навсегда' if hours==0 else f'на {hours}ч'}")
    elif action == "разбан":
        cur.execute("DELETE FROM banned_users WHERE user_id=?", (target_id,)); conn.commit()
        await msg.reply(f"✅ Разбанен")
    elif action == "мут игры":
        hours = int(params[0]) if params else 24
        until = int(time.time()) + hours*3600
        cur.execute("UPDATE users SET mute_games_until=? WHERE user_id=?", (until, target_id)); conn.commit()
        await msg.reply(f"🔇 Мут игр на {hours}ч для {mention_user(target_id)}")
    elif action == "мут чат":
        hours = int(params[0]) if params else 24
        until = int(time.time()) + hours*3600
        cur.execute("UPDATE users SET mute_chat_until=? WHERE user_id=?", (until, target_id)); conn.commit()
        await msg.reply(f"🔇 Мут чата на {hours}ч")
    elif action == "размут игры":
        cur.execute("UPDATE users SET mute_games_until=0 WHERE user_id=?", (target_id,)); conn.commit()
        await msg.reply("✅ Мут игр снят")
    elif action == "размут чат":
        cur.execute("UPDATE users SET mute_chat_until=0 WHERE user_id=?", (target_id,)); conn.commit()
        await msg.reply("✅ Мут чата снят")
    elif action == "стата":
        u = get_user(target_id)
        if not u: await msg.reply("❌ Не найден"); return
        vip, _ = get_vip(u["total_wagered"])
        text = (f"👤 {mention_user(target_id, u['username'])}\n"
                f"💰 {fmt_money(u['balance'])} | 💎 {vip}\n"
                f"📊 Вейджер: {fmt_money(u['total_wagered'])}\n"
                f"🏆 Выиграно: {fmt_money(u['total_won'])}\n"
                f"💸 Проиграно: {fmt_money(u['total_lost'])}\n"
                f"🎮 Игр сегодня: {u['games_played_today']}\n"
                f"🔥 Серия: {u['daily_streak']}")
        await msg.reply(text)

# Регистрируем обработчики админ-команд
@dp.message(lambda m: m.text and m.text.lower().startswith("выдать"))
async def cmd_give(msg: Message): await admin_command(msg, "выдать")
@dp.message(lambda m: m.text and m.text.lower().startswith("забрать"))
async def cmd_take(msg: Message): await admin_command(msg, "забрать")
@dp.message(lambda m: m.text and m.text.lower().startswith("бан"))
async def cmd_ban(msg: Message): await admin_command(msg, "бан")
@dp.message(lambda m: m.text and m.text.lower().startswith("разбан"))
async def cmd_unban(msg: Message): await admin_command(msg, "разбан")
@dp.message(lambda m: m.text and m.text.lower().startswith("мут игры"))
async def cmd_mute_games(msg: Message): await admin_command(msg, "мут игры")
@dp.message(lambda m: m.text and m.text.lower().startswith("мут чат"))
async def cmd_mute_chat(msg: Message): await admin_command(msg, "мут чат")
@dp.message(lambda m: m.text and m.text.lower().startswith("размут игры"))
async def cmd_unmute_games(msg: Message): await admin_command(msg, "размут игры")
@dp.message(lambda m: m.text and m.text.lower().startswith("размут чат"))
async def cmd_unmute_chat(msg: Message): await admin_command(msg, "размут чат")
@dp.message(lambda m: m.text and m.text.lower().startswith("стата"))
async def cmd_stat(msg: Message): await admin_command(msg, "стата")
# ---------- FSM (только для промокода) ----------
class GameStates(StatesGroup):
    promo_code = State()

# ---------- ИГРЫ (текстовые команды) ----------
# Проверка и парсинг ставки с поддержкой "все" и "пол"
def extract_bet_and_params(text: str, balance: int):
    """Возвращает (bet, params_list) или (None, None)"""
    parts = text.split()
    if len(parts) < 2: return None, None
    try:
        bet = parse_amount(parts[1], balance)
    except:
        return None, None
    return bet, parts[2:]

# Общая функция для мгновенных игр
async def instant_game(msg: Message, game_type: str, bet: int, choice: str, 
                       win_check_func, multiplier, outcome_details):
    """Списывает ставку, начисляет выигрыш, записывает игру, выводит результат."""
    if not remove_pocx(msg.from_user.id, bet):
        await msg.reply("❌ Недостаточно средств")
        return
    win, mult, details = win_check_func(choice)
    payout = int(bet * mult) if win else 0
    if payout > 0:
        add_pocx(msg.from_user.id, payout)
    record_game(msg.from_user.id, game_type, bet, mult if win else 0, payout, "win" if win else "loss", details)
    result_text = "✅ Победа" if win else "❌ Поражение"
    await msg.reply(
        f"{result_text}\n💰 Ставка: {fmt_money(bet)}\n"
        f"🎯 {outcome_details}\n"
        f"💵 Выплата: {fmt_money(payout)}\n"
        f"💳 Баланс: {fmt_money(get_user(msg.from_user.id)['balance'])}"
    )

# --- РУЛЕТКА ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("рул", "рулетка")))
async def roulette(msg: Message):
    u = get_user(msg.from_user.id)
    bet, params = extract_bet_and_params(msg.text, u["balance"])
    if not bet or bet < MIN_BET or not params:
        await msg.reply("❌ <code>рул [ставка] [красное/черное/чет/нечет/зеро]</code>"); return
    choice = params[0].lower()
    map_choice = {"красное":"red","черное":"black","чет":"even","нечет":"odd","зеро":"zero"}
    if choice not in map_choice:
        await msg.reply("❌ Выбор: красное/черное/чет/нечет/зеро"); return
    async def win_check(ch):
        number = random.randint(0, 36)
        color = "green" if number == 0 else ("red" if number in RED_NUMS else "black")
        parity = "zero" if number == 0 else ("even" if number % 2 == 0 else "odd")
        win = False
        mult = 0
        if map_choice[ch] == "red" and color == "red": win, mult = True, 2.0
        elif map_choice[ch] == "black" and color == "black": win, mult = True, 2.0
        elif map_choice[ch] == "even" and parity == "even": win, mult = True, 2.0
        elif map_choice[ch] == "odd" and parity == "odd": win, mult = True, 2.0
        elif map_choice[ch] == "zero" and number == 0: win, mult = True, 36.0
        return win, mult, {"number": number, "color": color}
    await instant_game(msg, "roulette", bet, choice, win_check, 0, f"Выпало {random.randint(0,36)}")  # заглушка, внутри переопределим

# Перепишем проще без лишней вложенности
@dp.message(lambda m: m.text and m.text.lower().startswith(("рул", "рулетка")))
async def roulette2(msg: Message):
    u = get_user(msg.from_user.id)
    bet, params = extract_bet_and_params(msg.text, u["balance"])
    if not bet or bet < MIN_BET or len(params) < 1:
        await msg.reply("❌ <code>рул 1000 красное</code>"); return
    choice = params[0].lower()
    choices = {"красное":"red","черное":"black","чет":"even","нечет":"odd","зеро":"zero"}
    if choice not in choices:
        await msg.reply("❌ Выбор: красное/черное/чет/нечет/зеро"); return
    number = random.randint(0, 36)
    color = "green" if number == 0 else ("red" if number in RED_NUMS else "black")
    parity = "zero" if number == 0 else ("even" if number % 2 == 0 else "odd")
    win = False
    mult = 0
    if choices[choice] == "red" and color == "red": win, mult = True, 2.0
    elif choices[choice] == "black" and color == "black": win, mult = True, 2.0
    elif choices[choice] == "even" and parity == "even": win, mult = True, 2.0
    elif choices[choice] == "odd" and parity == "odd": win, mult = True, 2.0
    elif choices[choice] == "zero" and number == 0: win, mult = True, 36.0
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(msg.from_user.id, payout)
    record_game(msg.from_user.id, "roulette", bet, mult, payout, "win" if win else "loss", {"number":number,"color":color})
    color_emoji = {"red":"🔴","black":"⚫","green":"🟢"}[color]
    await msg.reply(f"🎡 Рулетка: {number} {color_emoji}\n{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n💰 {fmt_money(get_user(msg.from_user.id)['balance'])}")

# --- КРАШ ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("краш", "crash")))
async def crash(msg: Message):
    u = get_user(msg.from_user.id)
    bet, params = extract_bet_and_params(msg.text, u["balance"])
    if not bet or bet < MIN_BET or len(params) < 1:
        await msg.reply("❌ <code>краш 1000 2.5</code>"); return
    try: target = float(params[0].replace(",","."))
    except: await msg.reply("❌ Множитель число"); return
    if target < 1.01 or target > 10: await msg.reply("❌ 1.01-10.0"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    crash_point = round(random.uniform(1.0, 10.0), 2)
    win = crash_point >= target
    payout = int(bet * target) if win else 0
    if payout: add_pocx(msg.from_user.id, payout)
    record_game(msg.from_user.id, "crash", bet, target, payout, "win" if win else "loss", {"crash":crash_point})
    await msg.reply(f"📈 Краш: x{crash_point} (цель x{target})\n{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n💰 {fmt_money(get_user(msg.from_user.id)['balance'])}")

# --- КУБИК ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("кубик", "куб")))
async def cube(msg: Message):
    u = get_user(msg.from_user.id)
    bet, params = extract_bet_and_params(msg.text, u["balance"])
    if not bet or bet < MIN_BET or len(params) < 1:
        await msg.reply("❌ <code>кубик 1000 5</code> (или чет/нечет/б/м)"); return
    guess = params[0].lower()
    if guess not in ("1","2","3","4","5","6","чет","нечет","б","м"):
        await msg.reply("❌ Вариант: 1-6, чет, нечет, б (больше 3), м (меньше 4)"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    dice = await msg.answer_dice(emoji="🎲")
    number = dice.dice.value
    win = False; mult = 0
    if guess == str(number): win, mult = True, 3.5
    elif guess == "чет" and number % 2 == 0: win, mult = True, 1.9
    elif guess == "нечет" and number % 2 == 1: win, mult = True, 1.9
    elif guess == "б" and number >= 4: win, mult = True, 1.9
    elif guess == "м" and number <= 3: win, mult = True, 1.9
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(msg.from_user.id, payout)
    record_game(msg.from_user.id, "cube", bet, mult, payout, "win" if win else "loss", {"number":number})
    await msg.reply(f"🎲 Кубик: {number}\n{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n💰 {fmt_money(get_user(msg.from_user.id)['balance'])}")

# --- КОСТИ ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("кости", "кос")))
async def dice_game(msg: Message):
    u = get_user(msg.from_user.id)
    bet, params = extract_bet_and_params(msg.text, u["balance"])
    if not bet or bet < MIN_BET or len(params) < 1:
        await msg.reply("❌ <code>кости 1000 м</code> (м/б/равно)"); return
    choice = params[0].lower()
    if choice not in ("м","б","равно"): await msg.reply("❌ м (меньше 7), б (больше 7), равно (7)"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    d1 = await msg.answer_dice(emoji="🎲"); d2 = await msg.answer_dice(emoji="🎲")
    total = d1.dice.value + d2.dice.value
    win = False; mult = 0
    if choice == "м" and total < 7: win, mult = True, 2.25
    elif choice == "б" and total > 7: win, mult = True, 2.25
    elif choice == "равно" and total == 7: win, mult = True, 5.0
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(msg.from_user.id, payout)
    record_game(msg.from_user.id, "dice", bet, mult, payout, "win" if win else "loss", {"d1":d1.dice.value,"d2":d2.dice.value,"total":total})
    await msg.reply(f"🎯 Кости: {d1.dice.value}+{d2.dice.value}={total}\n{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n💰 {fmt_money(get_user(msg.from_user.id)['balance'])}")

# --- ФУТБОЛ ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("футбол", "фут")))
async def football(msg: Message):
    u = get_user(msg.from_user.id)
    bet, params = extract_bet_and_params(msg.text, u["balance"])
    if not bet or bet < MIN_BET or len(params) < 1:
        await msg.reply("❌ <code>футбол 1000 гол</code> или <code>футбол 1000 мимо</code>"); return
    choice = params[0].lower()
    if choice not in ("гол","мимо"): await msg.reply("❌ гол или мимо"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    dice = await msg.answer_dice(emoji="⚽")
    res = "гол" if dice.dice.value >= 4 else "мимо"
    win = (choice == res)
    mult = FOOTBALL_MULT[res]
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(msg.from_user.id, payout)
    record_game(msg.from_user.id, "football", bet, mult, payout, "win" if win else "loss", {"value":dice.dice.value,"result":res})
    await msg.reply(f"⚽ {res}\n{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n💰 {fmt_money(get_user(msg.from_user.id)['balance'])}")

# --- БАСКЕТБОЛ ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("баскет", "баск")))
async def basketball(msg: Message):
    u = get_user(msg.from_user.id)
    bet, _ = extract_bet_and_params(msg.text, u["balance"])
    if not bet or bet < MIN_BET:
        await msg.reply("❌ <code>баскет 1000</code>"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    dice = await msg.answer_dice(emoji="🏀")
    win = dice.dice.value >= 4
    mult = 2.2 if win else 0
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(msg.from_user.id, payout)
    record_game(msg.from_user.id, "basket", bet, mult, payout, "win" if win else "loss", {"value":dice.dice.value})
    result_text = "Точный бросок" if win else "Промах"
    await msg.reply(f"🏀 {result_text}\n{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n💰 {fmt_money(get_user(msg.from_user.id)['balance'])}")

# --- ДАРТС ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("дартс", "дс")))
async def darts(msg: Message):
    u = get_user(msg.from_user.id)
    bet, params = extract_bet_and_params(msg.text, u["balance"])
    if not bet or bet < MIN_BET or len(params) < 1:
        await msg.reply("❌ <code>дартс 1000 центр</code> (центр/край/мимо)"); return
    choice = params[0].lower()
    if choice not in ("центр","край","мимо"): await msg.reply("❌ центр, край, мимо"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    dice = await msg.answer_dice(emoji="🎯")
    val = dice.dice.value
    if val in (1,2): res = "мимо"
    elif val in (3,4): res = "край"
    else: res = "центр"
    win = (choice == res)
    mult = DARTS_MULT[res]
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(msg.from_user.id, payout)
    record_game(msg.from_user.id, "darts", bet, mult, payout, "win" if win else "loss", {"value":val,"result":res})
    await msg.reply(f"🎯 Дартс: {res}\n{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n💰 {fmt_money(get_user(msg.from_user.id)['balance'])}")

# --- БАШНЯ (текстовая без кнопок) ---
@dp.message(lambda m: m.text and m.text.lower().startswith("башня"))
async def tower_start(msg: Message):
    u = get_user(msg.from_user.id)
    parts = msg.text.split()
    if len(parts) < 2: await msg.reply("❌ <code>башня [ставка] [мины 1-3]</code>"); return
    bet = parse_amount(parts[1], u["balance"])
    mines = int(parts[2]) if len(parts) > 2 else 1
    if bet < MIN_BET or bet > u["balance"] or mines < 1 or mines > 3:
        await msg.reply(f"❌ Ставка от {MIN_BET}, мины 1-3"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    # Генерация уровней заранее
    levels = []
    for _ in range(8):
        traps = random.sample(range(1,6), mines)
        levels.append(traps)
    game = {"bet": bet, "mines": mines, "level": 0, "levels": levels}
    TOWER_GAMES[msg.from_user.id] = game
    await msg.reply(f"🗼 Башня: этаж 1/8 | Ставка {fmt_money(bet)}\nВыбери секцию (1-5), <code>башня забрать</code>, <code>башня сдаться</code>")

@dp.message(lambda m: m.text and m.text.lower().startswith("башня"))
async def tower_action(msg: Message):
    parts = msg.text.lower().split()
    if len(parts) == 1: return
    cmd = parts[1]
    game = TOWER_GAMES.get(msg.from_user.id)
    if not game:
        if cmd.isdigit(): await msg.reply("Нет активной игры")
        return
    if cmd == "забрать":
        level = game["level"]
        if level == 0: await msg.reply("Сначала сделай ход"); return
        mult = TOWER_MULT[level-1] if level <= len(TOWER_MULT) else TOWER_MULT[-1]
        payout = int(game["bet"] * mult)
        add_pocx(msg.from_user.id, payout)
        record_game(msg.from_user.id, "tower", game["bet"], mult, payout, "win", {"level":level})
        del TOWER_GAMES[msg.from_user.id]
        await msg.reply(f"✅ Забрал {fmt_money(payout)} (x{mult:.2f})")
    elif cmd == "сдаться":
        bet = game["bet"]
        if game["level"] == 0:
            add_pocx(msg.from_user.id, bet)
            await msg.reply(f"❌ Возврат {fmt_money(bet)}")
        else:
            await msg.reply(f"❌ Сдался на этаже {game['level']+1}")
        del TOWER_GAMES[msg.from_user.id]
    elif cmd.isdigit():
        choice = int(cmd)
        if choice < 1 or choice > 5: return
        traps = game["levels"][game["level"]]
        if choice in traps:
            record_game(msg.from_user.id, "tower", game["bet"], 0, 0, "loss", {"level":game["level"]+1})
            await msg.reply(f"💥 Мина! Этаж {game['level']+1}. Потеряно {fmt_money(game['bet'])}")
            del TOWER_GAMES[msg.from_user.id]
        else:
            game["level"] += 1
            if game["level"] >= 8:
                mult = TOWER_MULT[-1]; payout = int(game["bet"] * mult)
                add_pocx(msg.from_user.id, payout)
                record_game(msg.from_user.id, "tower", game["bet"], mult, payout, "win", {"level":8})
                await msg.reply(f"🏁 Вершина! +{fmt_money(payout)} (x{mult:.2f})")
                del TOWER_GAMES[msg.from_user.id]
            else:
                cur_mult = TOWER_MULT[game["level"]-1] if game["level"] <= len(TOWER_MULT) else TOWER_MULT[-1]
                cur_win = int(game["bet"] * cur_mult)
                await msg.reply(f"🗼 Этаж {game['level']+1}/8 | x{cur_mult:.2f} | Потенциал {fmt_money(cur_win)}\nВыбирай (1-5) или <code>башня забрать</code>")
    TOWER_GAMES[msg.from_user.id] = game  # обновили

# --- ЗОЛОТО (текстовые) ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("золото","зол")))
async def gold_start(msg: Message):
    u = get_user(msg.from_user.id)
    parts = msg.text.split()
    if len(parts) < 2: await msg.reply("❌ <code>золото [ставка]</code>"); return
    bet = parse_amount(parts[1], u["balance"])
    if bet < MIN_BET or bet > u["balance"]: await msg.reply(f"❌ Ставка от {MIN_BET}"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    game = {"bet": bet, "step": 0, "traps": [random.randint(1,4) for _ in range(7)]}
    GOLD_GAMES[msg.from_user.id] = game
    await msg.reply(f"🥇 Золото: раунд 1/7 | Ставка {fmt_money(bet)}\nВыбери плитку (1-4), <code>золото забрать</code>, <code>золото сдаться</code>")

@dp.message(lambda m: m.text and m.text.lower().startswith(("золото","зол")))
async def gold_action(msg: Message):
    parts = msg.text.lower().split()
    if len(parts) == 1: return
    cmd = parts[1]
    game = GOLD_GAMES.get(msg.from_user.id)
    if not game: return
    if cmd == "забрать":
        if game["step"] == 0: await msg.reply("Сделай ход"); return
        mult = GOLD_MULT[game["step"]-1]
        payout = int(game["bet"] * mult)
        add_pocx(msg.from_user.id, payout)
        record_game(msg.from_user.id, "gold", game["bet"], mult, payout, "win", {"step":game["step"]})
        del GOLD_GAMES[msg.from_user.id]
        await msg.reply(f"✅ Забрал {fmt_money(payout)}")
    elif cmd == "сдаться":
        if game["step"] == 0: add_pocx(msg.from_user.id, game["bet"]); await msg.reply("Возврат")
        else: await msg.reply("Сдался")
        del GOLD_GAMES[msg.from_user.id]
    elif cmd.isdigit():
        pick = int(cmd)
        if pick < 1 or pick > 4: return
        trap = game["traps"][game["step"]]
        if pick == trap:
            record_game(msg.from_user.id, "gold", game["bet"], 0, 0, "loss", {"step":game["step"]+1})
            await msg.reply(f"💥 Ловушка! Раунд {game['step']+1}. Потеряно {fmt_money(game['bet'])}")
            del GOLD_GAMES[msg.from_user.id]
        else:
            game["step"] += 1
            if game["step"] >= 7:
                mult = GOLD_MULT[-1]; payout = int(game["bet"] * mult)
                add_pocx(msg.from_user.id, payout)
                record_game(msg.from_user.id, "gold", game["bet"], mult, payout, "win", {"step":7})
                await msg.reply(f"🏁 Победа! +{fmt_money(payout)}")
                del GOLD_GAMES[msg.from_user.id]
            else:
                cur_mult = GOLD_MULT[game["step"]-1]
                cur_win = int(game["bet"] * cur_mult)
                await msg.reply(f"🥇 Раунд {game['step']+1}/7 | x{cur_mult:.2f} | Потенциал {fmt_money(cur_win)}\nВыбирай или <code>золото забрать</code>")
    GOLD_GAMES[msg.from_user.id] = game

# --- АЛМАЗЫ (текстовые) ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("алмазы","алм")))
async def diamond_start(msg: Message):
    u = get_user(msg.from_user.id)
    parts = msg.text.split()
    if len(parts) < 2: await msg.reply("❌ <code>алмазы [ставка] [мины 1-2]</code>"); return
    bet = parse_amount(parts[1], u["balance"])
    mines = int(parts[2]) if len(parts) > 2 else 1
    if bet < MIN_BET or bet > u["balance"] or mines not in (1,2): await msg.reply(f"❌ Ставка, мины 1-2"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    game = {"bet": bet, "mines": mines, "step": 0, "traps": [random.sample(range(1,6), mines) for _ in range(8)]}
    DIAMOND_GAMES[msg.from_user.id] = game
    await msg.reply(f"💎 Алмазы: шаг 1/8 | Ставка {fmt_money(bet)}\nВыбери (1-5), <code>алмазы забрать</code>, <code>алмазы сдаться</code>")

@dp.message(lambda m: m.text and m.text.lower().startswith(("алмазы","алм")))
async def diamond_action(msg: Message):
    parts = msg.text.lower().split()
    if len(parts) == 1: return
    cmd = parts[1]
    game = DIAMOND_GAMES.get(msg.from_user.id)
    if not game: return
    if cmd == "забрать":
        if game["step"] == 0: await msg.reply("Сделай ход"); return
        mult = DIAMOND_MULT[game["step"]-1] if game["step"] <= len(DIAMOND_MULT) else DIAMOND_MULT[-1]
        payout = int(game["bet"] * mult)
        add_pocx(msg.from_user.id, payout)
        record_game(msg.from_user.id, "diamonds", game["bet"], mult, payout, "win", {"step":game["step"]})
        del DIAMOND_GAMES[msg.from_user.id]
        await msg.reply(f"✅ Забрал {fmt_money(payout)}")
    elif cmd == "сдаться":
        if game["step"] == 0: add_pocx(msg.from_user.id, game["bet"]); await msg.reply("Возврат")
        else: await msg.reply("Сдался")
        del DIAMOND_GAMES[msg.from_user.id]
    elif cmd.isdigit():
        pick = int(cmd)
        if pick not in range(1,6): return
        traps = game["traps"][game["step"]]
        if pick in traps:
            record_game(msg.from_user.id, "diamonds", game["bet"], 0, 0, "loss", {"step":game["step"]+1})
            await msg.reply(f"💥 Мина! Шаг {game['step']+1}. Потеряно {fmt_money(game['bet'])}")
            del DIAMOND_GAMES[msg.from_user.id]
        else:
            game["step"] += 1
            if game["step"] >= 8:
                mult = DIAMOND_MULT[-1]; payout = int(game["bet"] * mult)
                add_pocx(msg.from_user.id, payout)
                record_game(msg.from_user.id, "diamonds", game["bet"], mult, payout, "win", {"step":8})
                await msg.reply(f"🏁 Победа! +{fmt_money(payout)}")
                del DIAMOND_GAMES[msg.from_user.id]
            else:
                cur_mult = DIAMOND_MULT[game["step"]-1] if game["step"] <= len(DIAMOND_MULT) else DIAMOND_MULT[-1]
                cur_win = int(game["bet"] * cur_mult)
                await msg.reply(f"💎 Шаг {game['step']+1}/8 | x{cur_mult:.2f} | Потенциал {fmt_money(cur_win)}\nВыбирай или <code>алмазы забрать</code>")
    DIAMOND_GAMES[msg.from_user.id] = game

# --- МИНЫ (текстовые) ---
@dp.message(lambda m: m.text and m.text.lower().startswith("мины"))
async def mines_start(msg: Message):
    u = get_user(msg.from_user.id)
    parts = msg.text.split()
    if len(parts) < 3: await msg.reply("❌ <code>мины [ставка] [кол-во мин 1-5]</code>"); return
    bet = parse_amount(parts[1], u["balance"])
    mines_cnt = int(parts[2])
    if bet < MIN_BET or bet > u["balance"] or mines_cnt < 1 or mines_cnt > 5:
        await msg.reply(f"❌ Ставка, мины 1-5"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    cells = list(range(1,10))
    mine_positions = set(random.sample(cells, mines_cnt))
    game = {"bet": bet, "mines": mine_positions, "cnt": mines_cnt, "opened": set()}
    MINES_GAMES[msg.from_user.id] = game
    await msg.reply(f"💣 Мины: {mines_cnt} мин | Ставка {fmt_money(bet)}\nОткрывай клетки (1-9), <code>мины забрать</code>, <code>мины сдаться</code>")

@dp.message(lambda m: m.text and m.text.lower().startswith("мины"))
async def mines_action(msg: Message):
    parts = msg.text.lower().split()
    if len(parts) == 1: return
    cmd = parts[1]
    game = MINES_GAMES.get(msg.from_user.id)
    if not game: return
    if cmd == "забрать":
        opened = len(game["opened"])
        if opened == 0: await msg.reply("Открой хотя бы одну"); return
        mult = mines_multiplier(opened, game["cnt"])
        payout = int(game["bet"] * mult)
        add_pocx(msg.from_user.id, payout)
        record_game(msg.from_user.id, "mines", game["bet"], mult, payout, "win", {"opened":opened})
        del MINES_GAMES[msg.from_user.id]
        await msg.reply(f"✅ Забрал {fmt_money(payout)} (x{mult:.2f})")
    elif cmd == "сдаться":
        if len(game["opened"]) == 0: add_pocx(msg.from_user.id, game["bet"]); await msg.reply("Возврат")
        else: await msg.reply("Сдался")
        del MINES_GAMES[msg.from_user.id]
    elif cmd.isdigit():
        cell = int(cmd)
        if cell not in range(1,10): return
        if cell in game["opened"]: await msg.reply("Уже открыто"); return
        if cell in game["mines"]:
            record_game(msg.from_user.id, "mines", game["bet"], 0, 0, "loss", {"opened":len(game["opened"])})
            await msg.reply(f"💥 Мина! Конец. Потеряно {fmt_money(game['bet'])}")
            del MINES_GAMES[msg.from_user.id]
        else:
            game["opened"].add(cell)
            safe = 9 - game["cnt"]
            if len(game["opened"]) >= safe:
                mult = mines_multiplier(safe, game["cnt"]); payout = int(game["bet"] * mult)
                add_pocx(msg.from_user.id, payout)
                record_game(msg.from_user.id, "mines", game["bet"], mult, payout, "win", {"opened":safe})
                await msg.reply(f"🏁 Все безопасные! +{fmt_money(payout)}")
                del MINES_GAMES[msg.from_user.id]
            else:
                cur_mult = mines_multiplier(len(game["opened"]), game["cnt"])
                cur_win = int(game["bet"] * cur_mult)
                await msg.reply(f"💣 Открыто {len(game['opened'])} | x{cur_mult:.2f} | Потенциал {fmt_money(cur_win)}\nПродолжай (1-9), <code>мины забрать</code>")
    MINES_GAMES[msg.from_user.id] = game

def mines_multiplier(opened: int, mines: int) -> float:
    if opened <= 0: return 1.0
    safe = 9 - mines
    base = 9.0 / max(1.0, safe)
    return round((base ** opened) * 0.95, 2)

# --- ОЧКО (текстовое) ---
@dp.message(lambda m: m.text and m.text.lower().startswith("очко"))
async def ochko(msg: Message):
    u = get_user(msg.from_user.id)
    parts = msg.text.split()
    if len(parts) < 2: await msg.reply("❌ <code>очко [ставка]</code>"); return
    bet = parse_amount(parts[1], u["balance"])
    if bet < MIN_BET or bet > u["balance"]: await msg.reply(f"❌ Ставка"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    # создаем колоду
    ranks = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
    suits = ["♠","♥","♦","♣"]
    deck = [(r,s) for r in ranks for s in suits]
    random.shuffle(deck)
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    game = {"bet": bet, "deck": deck, "player": player, "dealer": dealer}
    OCHKO_GAMES[msg.from_user.id] = game
    # Проверка блэкджека
    pval = hand_value(player)
    dval = hand_value(dealer)
    if pval == 21:
        if dval == 21:
            add_pocx(msg.from_user.id, bet)
            record_game(msg.from_user.id, "ochko", bet, 1, bet, "push", {"player":21,"dealer":21})
            await msg.reply("🎴 Ничья! Блэкджек у обоих, возврат")
        else:
            mult = 2.5; payout = int(bet * mult)
            add_pocx(msg.from_user.id, payout)
            record_game(msg.from_user.id, "ochko", bet, mult, payout, "win", {"player":21})
            await msg.reply(f"🎴 Блэкджек! +{fmt_money(payout)}")
        del OCHKO_GAMES[msg.from_user.id]
        return
    await msg.reply(f"🎴 Очко\nДилер: {dealer[0][0]}{dealer[0][1]} ??\nТы: {' '.join(r+s for r,s in player)} ({pval})\n<code>очко взять</code> или <code>очко стоп</code>")

@dp.message(lambda m: m.text and m.text.lower().startswith("очко"))
async def ochko_action(msg: Message):
    parts = msg.text.lower().split()
    if len(parts) < 2: return
    cmd = parts[1]
    game = OCHKO_GAMES.get(msg.from_user.id)
    if not game: return
    if cmd == "взять":
        game["player"].append(game["deck"].pop())
        pval = hand_value(game["player"])
        if pval > 21:
            record_game(msg.from_user.id, "ochko", game["bet"], 0, 0, "loss", {"player":pval})
            await msg.reply(f"💥 Перебор ({pval})! Потеряно {fmt_money(game['bet'])}")
            del OCHKO_GAMES[msg.from_user.id]
        else:
            await msg.reply(f"Ты взял карту. Твоя рука: {' '.join(r+s for r,s in game['player'])} ({pval})\n<code>очко взять</code> / <code>очко стоп</code>")
    elif cmd == "стоп":
        # Дилер добирает
        while hand_value(game["dealer"]) < 17:
            game["dealer"].append(game["deck"].pop())
        pval = hand_value(game["player"]); dval = hand_value(game["dealer"])
        if dval > 21 or pval > dval: outcome, mult = "win", 2.0
        elif pval == dval: outcome, mult = "push", 1.0
        else: outcome, mult = "loss", 0.0
        payout = int(game["bet"] * mult)
        if payout: add_pocx(msg.from_user.id, payout)
        record_game(msg.from_user.id, "ochko", game["bet"], mult, payout, outcome, {"player":pval,"dealer":dval})
        res_text = "Победа" if outcome=="win" else ("Ничья" if outcome=="push" else "Поражение")
        await msg.reply(f"🎴 {res_text}\nДилер: {' '.join(r+s for r,s in game['dealer'])} ({dval})\nТы: {pval}\nВыплата: {fmt_money(payout)}\n💰 {fmt_money(get_user(msg.from_user.id)['balance'])}")
        del OCHKO_GAMES[msg.from_user.id]

def hand_value(cards):
    total = 0; aces = 0
    for r,s in cards:
        if r in "JQK": total += 10
        elif r == "A": total += 11; aces += 1
        else: total += int(r)
    while total > 21 and aces > 0:
        total -= 10; aces -= 1
    return total

# ---------- Промокод FSM ----------
@dp.message(GameStates.promo_code)
async def promo_use(msg: Message, state: FSMContext):
    code = msg.text.strip().upper()
    row = cur.execute("SELECT bonus_amount, max_uses, used_count, is_active FROM promocodes WHERE code=?", (code,)).fetchone()
    if not row or not row[3] or row[2] >= row[1]:
        await msg.answer("❌ Недействителен"); await state.clear(); return
    if cur.execute("SELECT 1 FROM used_promocodes WHERE user_id=? AND code=?", (msg.from_user.id, code)).fetchone():
        await msg.answer("❌ Уже использован"); await state.clear(); return
    add_pocx(msg.from_user.id, row[0])
    cur.execute("INSERT INTO used_promocodes (user_id, code) VALUES (?,?)", (msg.from_user.id, code))
    cur.execute("UPDATE promocodes SET used_count=used_count+1 WHERE code=?", (code,)); conn.commit()
    await msg.answer(f"✅ +{fmt_money(row[0])}")
    await state.clear()

# ---------- ПРОВЕРКА ПЕРЕД ИГРАМИ (баны/муты) ----------
@dp.message()
async def check_before_games(msg: Message):
    # Если сообщение начинается с игровой команды, проверяем
    text = msg.text.lower() if msg.text else ""
    game_triggers = ("рул","рулетка","краш","кубик","кости","футбол","баскет","дартс","дс","башня","золото","алмазы","мины","очко")
    if not any(text.startswith(t) for t in game_triggers): return
    uid = msg.from_user.id
    if is_banned(uid):
        await msg.reply("❌ Вы забанены!"); return
    if is_muted_games(uid):
        await msg.reply("🔇 Вы временно отстранены от игр!"); return

# ---------- ЗАПУСК ----------
async def main():
    print("✅ Бот запущен!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
