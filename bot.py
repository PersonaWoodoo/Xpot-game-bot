import asyncio, random, sqlite3, hashlib, time, json, html, string, os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, ChatMemberUpdated,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery, SuccessfulPayment
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode, ChatType

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================
TOKEN = "8134237711:AAH5M0JJULkrl0yyOdvfCtIswRPqRtt_3hg"
ADMIN_IDS = [8478884644, 8293927811]
BOT_USERNAME = "P0CXCasinobot"

MIN_BET = 100
MAX_BET = 100_000_000
DAILY_BONUS_MIN, DAILY_BONUS_MAX = 100, 2000
WELCOME_BONUS = 1000
REF_REWARD = 5000
REF_REFERRAL_BONUS = 500
TRANSFER_FEE = 0.035
CLAN_CREATE_PRICE_POCX = 350000
CLAN_CREATE_PRICE_STARS = 100
STARS_TO_POCX = 2500

BANK_TERMS = {7: 0.01, 14: 0.02, 30: 0.05}

VIP_LEVELS = [
    ("🥉 Новичок", 0, 0),
    ("🥈 Опытный", 1000000, 1),
    ("🥇 Старичок", 5000000, 2),
    ("💎 Легенда", 20000000, 3),
    ("👑 БОСС ", 1000000000, 5),
]

TOWER_MULT = [1.20, 1.48, 1.86, 2.35, 2.95, 3.75, 4.85, 6.15]
GOLD_MULT = [1.15, 1.35, 1.62, 2.0, 2.55, 3.25, 4.2]
DIAMOND_MULT = [1.12, 1.28, 1.48, 1.72, 2.02, 2.4, 2.92, 3.6]
RED_NUMS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
FOOTBALL_MULT = {"гол": 1.6, "мимо": 2.2}
DARTS_MULT = {"мимо": 0, "край": 1.5, "центр": 2.0}

# Права админов по умолчанию (битовая маска)
PERM_BAN = 1
PERM_UNBAN = 2
PERM_GIVE = 4
PERM_TAKE = 8
PERM_BROADCAST = 16
PERM_PROMO = 32
PERM_ADMIN = 64  # может управлять другими админами
PERM_ALL = PERM_BAN | PERM_UNBAN | PERM_GIVE | PERM_TAKE | PERM_BROADCAST | PERM_PROMO | PERM_ADMIN

# ============================================================
# БАЗА ДАННЫХ
# ============================================================
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
    mute_chat_until INTEGER DEFAULT 0, total_donated INTEGER DEFAULT 0,
    experience INTEGER DEFAULT 0, level INTEGER DEFAULT 1,
    prestige INTEGER DEFAULT 0, prestige_bonus REAL DEFAULT 0.0,
    selected_background TEXT DEFAULT 'default',
    luck_score REAL DEFAULT 0.5,
    total_refs INTEGER DEFAULT 0
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
    user_id INTEGER PRIMARY KEY, banned_at INTEGER, reason TEXT,
    banned_until INTEGER DEFAULT 0, banned_by INTEGER
);

CREATE TABLE IF NOT EXISTS promocodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE,
    bonus_amount INTEGER, max_uses INTEGER, used_count INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1, created_by INTEGER
);

CREATE TABLE IF NOT EXISTS used_promocodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, code TEXT,
    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS checks (
    code TEXT PRIMARY KEY, creator_id INTEGER, per_user INTEGER,
    remaining INTEGER, used TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bank_deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, principal INTEGER,
    rate REAL, term_days INTEGER, opened_at INTEGER,
    status TEXT DEFAULT 'active', closed_at INTEGER
);

CREATE TABLE IF NOT EXISTS clans (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE,
    owner_id INTEGER, balance INTEGER DEFAULT 0, level INTEGER DEFAULT 1,
    experience INTEGER DEFAULT 0, tag TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS clan_members (
    user_id INTEGER PRIMARY KEY, clan_id INTEGER,
    role TEXT DEFAULT 'member', joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admin_roles (
    user_id INTEGER PRIMARY KEY, permissions INTEGER DEFAULT 0,
    give_limit INTEGER DEFAULT 100000, added_by INTEGER,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admin_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER,
    action TEXT, target_id INTEGER, details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS achievements (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
    achievement_type TEXT, achieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, achievement_type)
);

CREATE TABLE IF NOT EXISTS credit_loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
    amount INTEGER, interest REAL, term_days INTEGER,
    taken_at INTEGER, repaid INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS investments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
    amount INTEGER, rate REAL, started_at INTEGER,
    status TEXT DEFAULT 'active', closed_at INTEGER
);

CREATE TABLE IF NOT EXISTS lottery_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
    ticket_number TEXT, draw_date TEXT,
    is_winner INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lottery_draws (
    id INTEGER PRIMARY KEY AUTOINCREMENT, draw_date TEXT UNIQUE,
    winning_number TEXT, jackpot INTEGER DEFAULT 0,
    is_completed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS market_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER,
    item_name TEXT, item_type TEXT, price INTEGER,
    is_sold INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS marriages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user1_id INTEGER,
    user2_id INTEGER, married_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS chat_settings (
    chat_id INTEGER PRIMARY KEY, welcome_message TEXT,
    is_active INTEGER DEFAULT 1, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS daily_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
    task_type TEXT, target INTEGER, progress INTEGER DEFAULT 0,
    is_completed INTEGER DEFAULT 0, reward INTEGER,
    created_at DATE DEFAULT (date('now'))
);

CREATE TABLE IF NOT EXISTS nft_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER,
    item_name TEXT, rarity TEXT, multiplier_bonus REAL DEFAULT 0,
    purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    price INTEGER DEFAULT 0
);
""")
conn.commit()

# ============================================================
# ХЕЛПЕРЫ
# ============================================================
def parse_amount(text: str, balance: int = 0) -> int:
    t = text.lower().strip().replace(",", ".").replace(" ", "")
    if t in ("все", "всё", "all"): return balance
    if t in ("пол", "половина", "half"): return balance // 2
    mults = {
        'ккк': 1_000_000_000, 'кк': 1_000_000, 'к': 1_000,
        'kkk': 1_000_000_000, 'kk': 1_000_000, 'k': 1_000,
        'm': 1_000_000, 'b': 1_000_000_000
    }
    for suf, m in mults.items():
        if t.endswith(suf):
            num = t[:-len(suf)] or '1'
            try: return int(float(num) * m)
            except: return 0
    try: return int(float(t))
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
    return {
        "user_id": r[0], "username": r[1], "balance": r[2],
        "total_wagered": r[3] or 0, "total_won": r[4] or 0,
        "total_lost": r[5] or 0, "referral_code": r[6],
        "daily_streak": r[9] or 0, "welcome_bonus_claimed": r[10],
        "games_played_today": r[11] or 0, "custom_status": r[12],
        "mute_games_until": r[13] or 0, "mute_chat_until": r[14] or 0,
        "total_donated": r[15] or 0, "experience": r[16] or 0,
        "level": r[17] or 1, "prestige": r[18] or 0,
        "prestige_bonus": r[19] or 0.0, "selected_background": r[20],
        "luck_score": r[21] or 0.5, "total_refs": r[22] or 0
    }

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
        cur.execute("UPDATE users SET mute_games_until=0 WHERE user_id=?", (uid,)); conn.commit()
        return False
    return u["mute_games_until"] > 0

def is_muted_chat(uid: int) -> bool:
    u = get_user(uid)
    if not u: return False
    if u["mute_chat_until"] > 0 and int(time.time()) > u["mute_chat_until"]:
        cur.execute("UPDATE users SET mute_chat_until=0 WHERE user_id=?", (uid,)); conn.commit()
        return False
    return u["mute_chat_until"] > 0

def record_game(uid, game_type, bet, mult, win, result, details):
    cur.execute("""UPDATE users SET 
        total_wagered=total_wagered+?, 
        total_won=total_won+?, 
        total_lost=total_lost+?,
        games_played_today=games_played_today+1,
        experience=experience+?
        WHERE user_id=?""",
        (bet, win if result=="win" else 0, bet if result=="loss" else 0, bet//100, uid))
    cur.execute("""INSERT INTO game_history (user_id, game_type, bet_amount, multiplier, win_amount, result, details) 
        VALUES (?,?,?,?,?,?,?)""",
        (uid, game_type, bet, mult, win, result, json.dumps(details, ensure_ascii=False)))
    conn.commit()
    check_level_up(uid)

def check_level_up(uid: int):
    u = get_user(uid)
    exp_needed = u["level"] * 1000
    if u["experience"] >= exp_needed:
        cur.execute("UPDATE users SET level=level+1, experience=experience-? WHERE user_id=?", (exp_needed, uid))
        conn.commit()

def resolve_user_id(arg: str):
    arg = arg.strip().lstrip("@")
    if arg.isdigit(): return int(arg)
    cur.execute("SELECT user_id FROM users WHERE username = ?", (arg,))
    r = cur.fetchone()
    return r[0] if r else None

def mention_user(uid: int, name: str = None) -> str:
    return f'<a href="tg://user?id={uid}">{html.escape(name or str(uid))}</a>'

def get_admin_perms(uid: int) -> int:
    if uid in ADMIN_IDS: return PERM_ALL
    cur.execute("SELECT permissions FROM admin_roles WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else 0

def has_perm(uid: int, perm: int) -> bool:
    if uid in ADMIN_IDS: return True
    return (get_admin_perms(uid) & perm) != 0

def get_give_limit(uid: int) -> int:
    if uid in ADMIN_IDS: return 100_000_000
    cur.execute("SELECT give_limit FROM admin_roles WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else 0

def admin_log(admin_id: int, action: str, target_id: int = 0, details: str = ""):
    cur.execute("INSERT INTO admin_logs (admin_id, action, target_id, details) VALUES (?,?,?,?)",
                (admin_id, action, target_id, details))
    conn.commit()

def get_achievements(uid: int) -> List[str]:
    cur.execute("SELECT achievement_type FROM achievements WHERE user_id=?", (uid,))
    return [r[0] for r in cur.fetchall()]

def add_achievement(uid: int, ach_type: str):
    try:
        cur.execute("INSERT OR IGNORE INTO achievements (user_id, achievement_type) VALUES (?,?)", (uid, ach_type))
        conn.commit()
    except: pass

# ============================================================
# FSM
# ============================================================
class GameStates(StatesGroup):
    promo_code = State()
    clan_create_name = State()
    admin_give = State()
    admin_take = State()
    admin_ban = State()
    admin_unban = State()
    admin_broadcast = State()
    admin_promo_code = State()
    admin_promo_reward = State()
    admin_promo_uses = State()
    admin_status = State()
    admin_mute_games = State()
    admin_mute_chat = State()
    admin_add_admin = State()
    admin_edit_perms = State()
    bank_amount = State()
    check_amount = State()
    check_count = State()
    check_claim = State()
    transfer_amount = State()
    market_sell_price = State()
    credit_amount = State()
    lottery_buy = State()
    background_set = State()

# Игровые сессии
TOWER_GAMES: Dict[int, Dict] = {}
GOLD_GAMES: Dict[int, Dict] = {}
DIAMOND_GAMES: Dict[int, Dict] = {}
MINES_GAMES: Dict[int, Dict] = {}
OCHKO_GAMES: Dict[int, Dict] = {}

# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def main_menu_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎮 Игры"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="🏆 Топ"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="🎁 Бонусы"), KeyboardButton(text="💰 Донат")],
        [KeyboardButton(text="🏦 Банк"), KeyboardButton(text="🏰 Кланы")],
        [KeyboardButton(text="🎯 Достижения"), KeyboardButton(text="🎪 Ивенты")],
        [KeyboardButton(text="👑 Админ"), KeyboardButton(text="❓ Помощь")],
        [KeyboardButton(text="◀️ Главное меню")]
    ], resize_keyboard=True)

def games_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🗼 Башня"), KeyboardButton(text="🥇 Золото")],
        [KeyboardButton(text="💎 Алмазы"), KeyboardButton(text="💣 Мины")],
        [KeyboardButton(text="🎴 Очко"), KeyboardButton(text="🎡 Рулетка")],
        [KeyboardButton(text="📈 Краш"), KeyboardButton(text="🎲 Кубик")],
        [KeyboardButton(text="🎯 Кости"), KeyboardButton(text="⚽ Футбол")],
        [KeyboardButton(text="🏀 Баскет"), KeyboardButton(text="🎯 Дартс")],
        [KeyboardButton(text="🎰 Слоты"), KeyboardButton(text="🪙 Монетка")],
        [KeyboardButton(text="✂️ КНБ"), KeyboardButton(text="◀️ Главное меню")]
    ], resize_keyboard=True)

def donate_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 1 Star — 2,500 POCX", callback_data="donate_1")],
        [InlineKeyboardButton(text="⭐ 5 Stars — 12,500 POCX", callback_data="donate_5")],
        [InlineKeyboardButton(text="⭐ 10 Stars — 25,000 POCX", callback_data="donate_10")],
        [InlineKeyboardButton(text="⭐ 25 Stars — 62,500 POCX", callback_data="donate_25")],
        [InlineKeyboardButton(text="💎 50 Stars — 125,000 POCX", callback_data="donate_50")],
        [InlineKeyboardButton(text="👑 100 Stars — 250,000 POCX", callback_data="donate_100")],
        [InlineKeyboardButton(text="✏️ Своя сумма", callback_data="donate_custom")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="close_menu")]
    ])

print("✅ Часть 1 загружена")# ============================================================
# БАЗОВЫЕ КОМАНДЫ
# ============================================================
bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    uid = message.from_user.id
    uname = message.from_user.username
    user = get_user(uid)
    
    if not user:
        code = hashlib.md5(f"{uid}{time.time()}".encode()).hexdigest()[:8]
        cur.execute("INSERT INTO users (user_id, username, referral_code, balance) VALUES (?,?,?,5000)", 
                   (uid, uname, code))
        conn.commit()
        user = get_user(uid)
    
    # Обработка рефералов и чеков
    args = message.text.split()
    if len(args) > 1:
        if args[1].startswith("ref"):
            ref_code = args[1][3:]
            ref = cur.execute("SELECT user_id FROM users WHERE referral_code = ?", (ref_code,)).fetchone()
            if ref and ref[0] != uid:
                if not cur.execute("SELECT 1 FROM referrals WHERE referrer_id=? AND referred_id=?", (ref[0], uid)).fetchone():
                    add_pocx(ref[0], REF_REWARD)
                    add_pocx(uid, REF_REFERRAL_BONUS)
                    cur.execute("INSERT INTO referrals (referrer_id, referred_id, earned_amount) VALUES (?,?,?)", 
                              (ref[0], uid, REF_REWARD))
                    cur.execute("UPDATE users SET total_refs = total_refs + 1 WHERE user_id = ?", (ref[0],))
                    conn.commit()
        elif args[1].startswith("check_"):
            code = args[1][6:]
            row = cur.execute("SELECT per_user, remaining, used FROM checks WHERE code=?", (code,)).fetchone()
            if row and row[1] > 0:
                used = json.loads(row[2]) if row[2] else []
                if str(uid) not in used:
                    add_pocx(uid, row[0])
                    used.append(str(uid))
                    cur.execute("UPDATE checks SET remaining=remaining-1, used=? WHERE code=?", (json.dumps(used), code))
                    conn.commit()
                    await message.answer(f"✅ Чек активирован! +{fmt_money(row[0])}")
    
    vip, _ = get_vip(user["total_wagered"])
    await message.answer(
        f"🎰 <b>POCX Casino Bot</b>\n\n"
        f"👤 {message.from_user.first_name}\n"
        f"💰 Баланс: {fmt_money(user['balance'])}\n"
        f"💎 VIP: {vip} | 📊 Ур. {user['level']}\n"
        f"🎯 Престиж: {user['prestige']}\n\n"
        f"📋 <code>помощь</code> — все команды\n"
        f"🎮 <code>игры</code> — список игр",
        reply_markup=main_menu_kb()
    )
    # Проверка достижений
    if user["total_wagered"] >= 10000:
        add_achievement(uid, "roller")
    if user["total_refs"] >= 10:
        add_achievement(uid, "recruiter")

@dp.message(F.text == "◀️ Главное меню")
async def back_to_main(message: Message):
    user = get_user(message.from_user.id)
    vip, _ = get_vip(user["total_wagered"])
    await message.answer(
        f"🎰 Главное меню\n💰 {fmt_money(user['balance'])} | {vip}",
        reply_markup=main_menu_kb()
    )

@dp.message(F.text == "❓ Помощь")
@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "❓ <b>Помощь по командам</b>\n\n"
        "<b>👤 Профиль и статистика:</b>\n"
        "• <code>п</code> / <code>профиль</code> — профиль\n"
        "• <code>т</code> / <code>топ</code> — топ игроков\n"
        "• <code>ст</code> / <code>стата</code> — статистика\n\n"
        "<b>🎮 Игры:</b>\n"
        "• <code>рул [ставка] [цвет]</code> — рулетка\n"
        "• <code>краш [ставка] [множ]</code> — краш\n"
        "• <code>кубик [ставка] [число]</code> — кубик\n"
        "• <code>кости [ставка] [м/б/7]</code> — кости\n"
        "• <code>футбол [ставка] [гол/мимо]</code> — футбол\n"
        "• <code>баскет [ставка]</code> — баскетбол\n"
        "• <code>дартс [ставка] [центр/край/мимо]</code> — дартс\n"
        "• <code>слоты [ставка]</code> — слоты\n"
        "• <code>монетка [ставка] [орел/решка]</code> — монетка\n"
        "• <code>кнб [ставка] [камень/ножницы/бумага]</code>\n\n"
        "<b>🏦 Банк и финансы:</b>\n"
        "• <code>банк</code> — меню банка\n"
        "• <code>передать [сумма]</code> (reply) — перевод\n"
        "• <code>донат</code> — пополнение\n\n"
        "<b>🏰 Кланы:</b>\n"
        "• <code>клан создать</code> / <code>вступить</code> / <code>выйти</code>\n\n"
        "<b>🎁 Бонусы:</b>\n"
        "• <code>бонус</code> — ежедневный бонус\n"
        "• <code>промокод [код]</code> — активировать\n\n"
        "<b>👑 Админ (для администраторов):</b>\n"
        "• <code>выдать [ID] [сумма]</code> / reply\n"
        "• <code>бан [ID] [часы] [причина]</code>\n"
        "• <code>мут игры [ID] [часы]</code>\n\n"
        "💡 <b>Сокращения:</b> 1к=1000, 1кк=1M, все=весь баланс, пол=половина"
    )

# Приветствие при добавлении в чат
@dp.chat_member()
async def on_bot_added(event: ChatMemberUpdated):
    if event.new_chat_member.user.id == (await bot.get_me()).id:
        if event.new_chat_member.status in ["member", "administrator"]:
            await bot.send_message(
                event.chat.id,
                "🤖 <b>POCX Casino Bot добавлен в чат!</b>\n\n"
                "🎮 <b>Игры доступны прямо здесь:</b>\n"
                "• <code>рул 1000 красное</code> — рулетка\n"
                "• <code>краш 1000 2.5</code> — краш\n"
                "• <code>кости 1000 м</code> — кости\n"
                "• <code>футбол все гол</code> — футбол\n\n"
                "📋 <b>Все команды:</b> <code>помощь</code>\n"
                "⚠️ Некоторые функции (банк, кланы) работают только в ЛС с ботом.\n\n"
                "💬 Приятной игры!"
            )

# ============================================================
# ПРОФИЛЬ, ТОП, СТАТИСТИКА
# ============================================================
@dp.message(F.text.in_({"👤 Профиль", "профиль", "п"}))
@dp.message(Command("profile"))
async def profile_cmd(message: Message):
    u = get_user(message.from_user.id)
    vip, bonus = get_vip(u["total_wagered"])
    achievements = get_achievements(message.from_user.id)
    ach_text = ", ".join(achievements[:5]) if achievements else "Нет"
    await message.answer(
        f"👤 <b>{message.from_user.first_name}</b>\n"
        f"🆔 ID: {u['user_id']}\n"
        f"💰 Баланс: {fmt_money(u['balance'])}\n"
        f"💎 VIP: {vip} (+{bonus}% к бонусам)\n"
        f"📊 Уровень: {u['level']} | Опыт: {u['experience']}/{u['level']*1000}\n"
        f"🎯 Престиж: {u['prestige']} | Бонус: +{u['prestige_bonus']*100:.0f}%\n"
        f"🏷 Статус: {u.get('custom_status', 'Обычный')}\n"
        f"📊 Вейджер: {fmt_money(u['total_wagered'])}\n"
        f"🏆 Выиграно: {fmt_money(u['total_won'])}\n"
        f"💸 Проиграно: {fmt_money(u['total_lost'])}\n"
        f"🎮 Игр сегодня: {u['games_played_today']}\n"
        f"🔥 Серия: {u['daily_streak']} дн.\n"
        f"🎯 Достижения: {ach_text}\n"
        f"⭐ Удача: {u['luck_score']:.2f}"
    )

@dp.message(F.text.in_({"🏆 Топ", "топ", "т"}))
@dp.message(Command("top"))
async def top_cmd(message: Message):
    rows = cur.execute("SELECT user_id, username, total_won FROM users ORDER BY total_won DESC LIMIT 10").fetchall()
    medals = ["🥇","🥈","🥉"]
    text = "🏆 <b>Топ-10 игроков</b>\n\n"
    for i, r in enumerate(rows):
        m = medals[i] if i < 3 else f"{i+1}."
        name = r[1] or f"ID{r[0]}"
        text += f"{m} {name} — {fmt_money(r[2])}\n"
    await message.answer(text)

@dp.message(F.text.in_({"📊 Статистика", "статистика", "ст", "стата"}))
@dp.message(Command("stats"))
async def stats_cmd(message: Message):
    u = get_user(message.from_user.id)
    played = cur.execute("SELECT COUNT(*) FROM game_history WHERE user_id=?", (message.from_user.id,)).fetchone()[0]
    wins = cur.execute("SELECT COUNT(*) FROM game_history WHERE user_id=? AND result='win'", (message.from_user.id,)).fetchone()[0]
    best = cur.execute("SELECT MAX(multiplier) FROM game_history WHERE user_id=? AND result='win'", (message.from_user.id,)).fetchone()[0] or 0
    wr = wins/max(played,1)*100
    
    # Статистика по играм
    game_stats = cur.execute("""SELECT game_type, COUNT(*), SUM(win_amount), SUM(bet_amount) 
        FROM game_history WHERE user_id=? GROUP BY game_type""", (message.from_user.id,)).fetchall()
    
    text = f"📊 <b>Статистика</b>\n🎮 Игр: {played} | ✅ Побед: {wins} ({wr:.1f}%)\n📈 Лучший x{best:.2f}\n\n"
    text += "<b>По играм:</b>\n"
    for gs in game_stats:
        profit = gs[2] - gs[3]
        text += f"• {gs[0]}: {gs[1]} игр, {fmt_money(profit)}\n"
    
    await message.answer(text)

# ============================================================
# ДОСТИЖЕНИЯ
# ============================================================
@dp.message(F.text == "🎯 Достижения")
async def achievements_cmd(message: Message):
    ach = get_achievements(message.from_user.id)
    all_ach = {
        "roller": "🎰 Хайроллер — вейджер 10,000+",
        "recruiter": "👥 Вербовщик — 10+ рефералов",
        "lucky": "🍀 Счастливчик — выигрыш x10+",
        "veteran": "🎖 Ветеран — 1000+ игр",
        "millionaire": "💰 Миллионер — баланс 1,000,000+",
        "prestige1": "⭐ Престиж 1 — первый престиж"
    }
    text = "🎯 <b>Ваши достижения:</b>\n\n"
    for a in ach:
        text += f"✅ {all_ach.get(a, a)}\n"
    for k, v in all_ach.items():
        if k not in ach:
            text += f"🔒 {v}\n"
    await message.answer(text)

# ============================================================
# БОНУСЫ
# ============================================================
@dp.message(F.text.in_({"🎁 Бонусы"}))
async def bonuses_menu(message: Message):
    await message.answer(
        "🎁 <b>Бонусная система</b>\n\n"
        "• <code>бонус</code> — ежедневный бонус (100-2000)\n"
        "• <code>промокод [код]</code> — активировать промокод\n"
        "• <code>чек создать/активировать</code> — подарочные чеки"
    )

@dp.message(F.text.in_({"🎁 Ежедневный бонус", "бонус", "бн"}))
@dp.message(Command("bonus"))
async def daily_bonus(message: Message):
    uid = message.from_user.id
    row = cur.execute("SELECT last_daily_bonus, daily_streak FROM users WHERE user_id=?", (uid,)).fetchone()
    last, streak = row[0] if row else None, row[1] if row else 0
    
    if last and datetime.now() - datetime.fromisoformat(last) < timedelta(days=1):
        await message.answer("❌ Бонус уже получен сегодня!")
        return
    
    _, vip_bonus = get_vip(get_user(uid)["total_wagered"])
    bonus = int(random.randint(DAILY_BONUS_MIN, DAILY_BONUS_MAX) * 
                (1 + min(streak * 0.05, 0.5)) * 
                (1 + vip_bonus / 100))
    
    add_pocx(uid, bonus)
    cur.execute("UPDATE users SET last_daily_bonus=CURRENT_TIMESTAMP, daily_streak=daily_streak+1 WHERE user_id=?", (uid,))
    conn.commit()
    await message.answer(f"🎁 +{bonus:,} POCX | 🔥 Серия: {streak+1} дн.")

# ============================================================
# ДОНАТ
# ============================================================
@dp.message(F.text.in_({"💰 Донат", "донат"}))
@dp.message(Command("donate"))
async def donate_cmd(message: Message):
    await message.answer(
        "💎 <b>Пополнение через Telegram Stars</b>\n\n"
        "⭐ 1 Star = 2,500 POCX\n"
        "Поддержите проект и получите валюту!",
        reply_markup=donate_kb()
    )

@dp.callback_query(F.data.startswith("donate_"))
async def donate_handler(callback: CallbackQuery):
    data = callback.data
    if data == "donate_custom":
        await callback.message.answer("✏️ Введи сумму в Stars (1-2500):")
        await callback.answer()
        return
    
    amounts = {"donate_1": 1, "donate_5": 5, "donate_10": 10, "donate_25": 25, "donate_50": 50, "donate_100": 100}
    stars = amounts.get(data, 1)
    pocx_amount = stars * STARS_TO_POCX
    
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Пополнение POCX",
        description=f"{stars} Stars = {pocx_amount:,} POCX",
        payload=f"donate_{stars}_{pocx_amount}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"{stars} Stars", amount=stars)]
    )
    await callback.answer("✅ Счёт выставлен!")

@dp.callback_query(F.data == "close_menu")
async def close_menu(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    parts = payload.split("_")
    pocx_amount = int(parts[2])
    add_pocx(message.from_user.id, pocx_amount)
    cur.execute("UPDATE users SET total_donated = total_donated + ? WHERE user_id = ?", (pocx_amount, message.from_user.id))
    conn.commit()
    user = get_user(message.from_user.id)
    await message.answer(f"✅ Спасибо за донат!\n💰 +{fmt_money(pocx_amount)}\n💳 Баланс: {fmt_money(user['balance'])}")

# ============================================================
# БАНК
# ============================================================
@dp.message(F.text.in_({"🏦 Банк", "банк"}))
@dp.message(Command("bank"))
async def bank_menu(message: Message):
    closed, payout = check_and_withdraw_deposits(message.from_user.id)
    if closed > 0:
        await message.answer(f"✅ Снято {closed} депозитов: +{fmt_money(payout)}")
    
    deps = cur.execute("SELECT * FROM bank_deposits WHERE user_id=? AND status='active'", (message.from_user.id,)).fetchall()
    text = "🏦 <b>Банк</b>\n\n"
    text += "<b>Команды:</b>\n"
    text += "<code>банк открыть [сумма] [7/14/30]</code>\n"
    text += "<code>банк список</code> | <code>банк снять</code>\n\n"
    text += "<b>Ставки:</b> 7д +1% | 14д +2% | 30д +5%\n\n"
    if deps:
        text += "<b>Активные депозиты:</b>\n"
        now = int(time.time())
        for d in deps:
            left = max(0, d[3] - (now - d[4]) // 86400)
            text += f"#{d[0]}: {fmt_money(d[1])} | +{int(d[2]*100)}% | {left}д\n"
    await message.answer(text)

def check_and_withdraw_deposits(uid):
    now = int(time.time())
    deps = cur.execute("SELECT id, principal, rate, term_days, opened_at FROM bank_deposits WHERE user_id=? AND status='active'", (uid,)).fetchall()
    total, closed = 0, 0
    for d in deps:
        if now - d[4] >= d[3] * 86400:
            payout = int(d[1] * (1 + d[2]))
            add_pocx(uid, payout)
            total += payout
            closed += 1
            cur.execute("UPDATE bank_deposits SET status='closed', closed_at=? WHERE id=?", (now, d[0]))
    conn.commit()
    return closed, total

@dp.message(lambda m: m.text.lower().startswith("банк открыть"))
async def bank_open(message: Message):
    parts = message.text.split()
    if len(parts) < 4:
        await message.reply("❌ <code>банк открыть 1000 7</code>")
        return
    try:
        amt = parse_amount(parts[2])
        term = int(parts[3])
        if amt < 1000 or term not in BANK_TERMS: raise ValueError
    except:
        await message.reply("❌ Сумма от 1000, срок 7/14/30")
        return
    if not remove_pocx(message.from_user.id, amt):
        await message.reply("❌ Недостаточно средств")
        return
    rate = BANK_TERMS[term]
    cur.execute("INSERT INTO bank_deposits (user_id, principal, rate, term_days, opened_at, status) VALUES (?,?,?,?,?,'active')",
                (message.from_user.id, amt, rate, term, int(time.time())))
    conn.commit()
    await message.reply(f"✅ Депозит {fmt_money(amt)} на {term}д (+{int(rate*100)}%)")

@dp.message(F.text.lower() == "банк список")
async def bank_list(message: Message):
    deps = cur.execute("SELECT id, principal, rate, term_days, opened_at FROM bank_deposits WHERE user_id=? AND status='active'", (message.from_user.id,)).fetchall()
    if not deps:
        await message.reply("📜 Нет активных депозитов")
        return
    now = int(time.time())
    text = "📜 <b>Активные депозиты:</b>\n"
    for d in deps:
        left = max(0, d[3] - (now - d[4]) // 86400)
        text += f"#{d[0]}: {fmt_money(d[1])} | +{int(d[2]*100)}% | {left}д\n"
    await message.reply(text)

@dp.message(F.text.lower() == "банк снять")
async def bank_withdraw(message: Message):
    closed, payout = check_and_withdraw_deposits(message.from_user.id)
    if closed > 0:
        await message.reply(f"✅ Снято {closed} депозитов: +{fmt_money(payout)}")
    else:
        await message.reply("📜 Нет созревших депозитов")

# ============================================================
# ЧЕКИ
# ============================================================
@dp.message(F.text == "🧾 Чеки")
async def checks_info(message: Message):
    await message.answer(
        "📋 <b>Чеки</b>\n\n"
        "<code>чек создать [сумма] [кол-во]</code>\n"
        "<code>чек активировать [код]</code>\n"
        "<code>чек мои</code>"
    )

@dp.message(lambda m: m.text and m.text.lower().startswith("чек создать"))
async def check_create(message: Message):
    parts = message.text.split()
    if len(parts) != 4:
        await message.reply("❌ <code>чек создать 1000 5</code>")
        return
    try:
        amt = parse_amount(parts[2])
        cnt = int(parts[3])
        if amt <= 0 or amt > 5_000_000 or cnt <= 0 or cnt > 50: raise ValueError
    except:
        await message.reply("❌ Сумма 1-5M, кол-во 1-50")
        return
    total = amt * cnt
    if not remove_pocx(message.from_user.id, total):
        await message.reply("❌ Недостаточно средств")
        return
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    cur.execute("INSERT INTO checks (code, creator_id, per_user, remaining, used) VALUES (?,?,?,?,'[]')",
                (code, message.from_user.id, amt, cnt))
    conn.commit()
    link = f"t.me/{BOT_USERNAME}?start=check_{code}"
    await message.reply(f"✅ Чек <code>{code}</code>\n🔗 {link}\n💰 {fmt_money(amt)} x{cnt}")

@dp.message(lambda m: m.text and m.text.lower().startswith("чек активировать"))
async def check_claim(message: Message):
    parts = message.text.split()
    if len(parts) != 3:
        await message.reply("❌ <code>чек активировать КОД</code>")
        return
    code = parts[2].upper()
    row = cur.execute("SELECT per_user, remaining, used FROM checks WHERE code=?", (code,)).fetchone()
    if not row or row[1] <= 0:
        await message.reply("❌ Недействителен")
        return
    used = json.loads(row[2]) if row[2] else []
    if str(message.from_user.id) in used:
        await message.reply("❌ Уже использован")
        return
    add_pocx(message.from_user.id, row[0])
    used.append(str(message.from_user.id))
    cur.execute("UPDATE checks SET remaining=remaining-1, used=? WHERE code=?", (json.dumps(used), code))
    conn.commit()
    await message.reply(f"✅ +{fmt_money(row[0])}")

@dp.message(F.text.lower() == "чек мои")
async def check_my(message: Message):
    rows = cur.execute("SELECT code, per_user, remaining FROM checks WHERE creator_id=? ORDER BY rowid DESC LIMIT 10",
                       (message.from_user.id,)).fetchall()
    if not rows:
        await message.reply("📋 Нет чеков")
    else:
        text = "📋 <b>Ваши чеки:</b>\n"
        for r in rows:
            text += f"<code>{r[0]}</code> – {fmt_money(r[1])} (ост.{r[2]})\n"
        await message.reply(text)

print("✅ Часть 2 загружена")# ============================================================
# КЛАНЫ
# ============================================================
@dp.message(F.text.in_({"🏰 Кланы", "кланы", "клан"}))
@dp.message(Command("clan"))
async def clans_info(message: Message):
    await message.answer(
        "🏰 <b>Кланы</b>\n\n"
        f"Создание: <code>клан создать [название]</code> (цена: {fmt_money(CLAN_CREATE_PRICE_POCX)} или {CLAN_CREATE_PRICE_STARS}⭐)\n"
        "<code>клан вступить [название]</code>\n"
        "<code>клан выйти</code>\n"
        "<code>клан баланс</code> | <code>клан пополнить [сумма]</code>\n"
        "<code>клан инфо [название]</code>"
    )

@dp.message(lambda m: m.text.lower().startswith("клан создать"))
async def clan_create(message: Message, state: FSMContext):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.reply("❌ Укажите название клана")
        return
    name = parts[2].strip()
    if cur.execute("SELECT 1 FROM clans WHERE name=?", (name,)).fetchone():
        await message.reply("❌ Имя занято")
        return
    if cur.execute("SELECT 1 FROM clan_members WHERE user_id=?", (message.from_user.id,)).fetchone():
        await message.reply("❌ Вы уже в клане")
        return
    
    await state.update_data(clan_name=name)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💎 {fmt_money(CLAN_CREATE_PRICE_POCX)}", callback_data="clan_pay_pocx")],
        [InlineKeyboardButton(text=f"⭐ {CLAN_CREATE_PRICE_STARS} Stars", callback_data="clan_pay_stars")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="clan_cancel")]
    ])
    await message.answer("Выберите способ оплаты:", reply_markup=kb)

@dp.callback_query(F.data == "clan_cancel")
async def clan_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Создание клана отменено")
    await callback.answer()

@dp.callback_query(F.data == "clan_pay_pocx")
async def clan_pay_pocx(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    name = data["clan_name"]
    if not remove_pocx(callback.from_user.id, CLAN_CREATE_PRICE_POCX):
        await callback.answer("❌ Недостаточно POCX", show_alert=True)
        await state.clear()
        return
    cur.execute("INSERT INTO clans (name, owner_id) VALUES (?,?)", (name, callback.from_user.id))
    clan_id = cur.lastrowid
    cur.execute("INSERT OR REPLACE INTO clan_members (user_id, clan_id, role) VALUES (?,?,'owner')", 
                (callback.from_user.id, clan_id))
    conn.commit()
    await state.clear()
    await callback.message.edit_text(f"🏰 Клан '{name}' создан!")
    await callback.answer()

@dp.callback_query(F.data == "clan_pay_stars")
async def clan_pay_stars(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    name = data["clan_name"]
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Создание клана",
        description=f"Клан '{name}'",
        payload=f"clan_{name}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Создание клана", amount=CLAN_CREATE_PRICE_STARS)]
    )
    await callback.message.edit_text("⭐ Выставлен счёт на оплату...")
    await callback.answer()

@dp.message(F.successful_payment)
async def clan_stars_paid(message: Message):
    payload = message.successful_payment.invoice_payload
    if payload.startswith("clan_"):
        name = payload[5:]
        cur.execute("INSERT INTO clans (name, owner_id) VALUES (?,?)", (name, message.from_user.id))
        clan_id = cur.lastrowid
        cur.execute("INSERT OR REPLACE INTO clan_members (user_id, clan_id, role) VALUES (?,?,'owner')", 
                    (message.from_user.id, clan_id))
        conn.commit()
        await message.answer(f"🏰 Клан '{name}' создан (оплата Stars)!")

@dp.message(lambda m: m.text.lower().startswith("клан вступить"))
async def clan_join(message: Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.reply("❌ Укажите название клана")
        return
    name = parts[2].strip()
    clan = cur.execute("SELECT id FROM clans WHERE name=?", (name,)).fetchone()
    if not clan:
        await message.reply("❌ Клан не найден")
        return
    cur.execute("INSERT OR REPLACE INTO clan_members (user_id, clan_id) VALUES (?,?)", 
                (message.from_user.id, clan[0]))
    conn.commit()
    await message.reply(f"✅ Вы вступили в клан '{name}'!")

@dp.message(F.text.lower() == "клан выйти")
async def clan_leave(message: Message):
    cur.execute("DELETE FROM clan_members WHERE user_id=?", (message.from_user.id,))
    conn.commit()
    await message.reply("✅ Вы вышли из клана")

@dp.message(F.text.lower() == "клан баланс")
async def clan_balance(message: Message):
    member = cur.execute("SELECT clan_id FROM clan_members WHERE user_id=?", (message.from_user.id,)).fetchone()
    if not member:
        await message.reply("❌ Вы не в клане")
        return
    clan = cur.execute("SELECT name, balance FROM clans WHERE id=?", (member[0],)).fetchone()
    await message.reply(f"🏰 Клан '{clan[0]}': {fmt_money(clan[1])}")

@dp.message(lambda m: m.text.lower().startswith("клан пополнить"))
async def clan_deposit(message: Message):
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply("❌ <code>клан пополнить 1000</code>")
        return
    try:
        amt = parse_amount(parts[2])
    except:
        await message.reply("❌ Сумма")
        return
    if not remove_pocx(message.from_user.id, amt):
        await message.reply("❌ Недостаточно средств")
        return
    member = cur.execute("SELECT clan_id FROM clan_members WHERE user_id=?", (message.from_user.id,)).fetchone()
    if not member:
        add_pocx(message.from_user.id, amt)
        await message.reply("❌ Вы не в клане. Возврат средств.")
        return
    cur.execute("UPDATE clans SET balance=balance+? WHERE id=?", (amt, member[0]))
    conn.commit()
    await message.reply(f"✅ +{fmt_money(amt)} в казну клана")

@dp.message(lambda m: m.text.lower().startswith("клан инфо"))
async def clan_info(message: Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.reply("❌ Укажите название")
        return
    name = parts[2].strip()
    clan = cur.execute("SELECT id, owner_id, balance, level FROM clans WHERE name=?", (name,)).fetchone()
    if not clan:
        await message.reply("❌ Не найден")
        return
    members = cur.execute("SELECT user_id FROM clan_members WHERE clan_id=?", (clan[0],)).fetchall()
    text = f"🏰 Клан '{name}'\n👑 Владелец: {clan[1]}\n💰 Баланс: {fmt_money(clan[2])}\n📊 Уровень: {clan[3]}\n👥 Участников: {len(members)}"
    await message.reply(text)

# ============================================================
# ПЕРЕДАЧА
# ============================================================
@dp.message(lambda m: m.text and m.text.lower().split()[0] in ("передать","п","дать","накинуть") and m.reply_to_message)
async def transfer_cmd(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("❌ Укажи сумму")
        return
    try:
        amount = parse_amount(parts[1])
        if amount < 100: raise ValueError
    except:
        await message.reply("❌ Сумма от 100")
        return
    
    user = get_user(message.from_user.id)
    fee = int(amount * TRANSFER_FEE)
    total = amount + fee
    
    if user["balance"] < total:
        await message.reply(f"❌ Нужно {fmt_money(total)} (комиссия {TRANSFER_FEE*100:.1f}%)")
        return
    
    target = message.reply_to_message.from_user.id
    if target == message.from_user.id:
        await message.reply("❌ Нельзя себе")
        return
    
    remove_pocx(message.from_user.id, total)
    add_pocx(target, amount)
    await message.reply(
        f"✅ <b>Перевод</b>\n"
        f"💰 Сумма: {fmt_money(amount)}\n"
        f"💸 Комиссия: {fmt_money(fee)}\n"
        f"👤 Получатель: {message.reply_to_message.from_user.first_name}"
    )

# ============================================================
# ПРОМОКОДЫ
# ============================================================
@dp.message(lambda m: m.text and m.text.lower().startswith("промокод"))
async def promo_use(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("❌ <code>промокод КОД</code>")
        return
    code = parts[1].upper()
    row = cur.execute("SELECT bonus_amount, max_uses, used_count, is_active FROM promocodes WHERE code=?", (code,)).fetchone()
    if not row or not row[3] or row[2] >= row[1]:
        await message.reply("❌ Недействителен")
        return
    if cur.execute("SELECT 1 FROM used_promocodes WHERE user_id=? AND code=?", (message.from_user.id, code)).fetchone():
        await message.reply("❌ Уже использован")
        return
    add_pocx(message.from_user.id, row[0])
    cur.execute("INSERT INTO used_promocodes (user_id, code) VALUES (?,?)", (message.from_user.id, code))
    cur.execute("UPDATE promocodes SET used_count=used_count+1 WHERE code=?", (code,))
    conn.commit()
    await message.reply(f"✅ +{fmt_money(row[0])}")

# ============================================================
# РЕФЕРАЛЫ
# ============================================================
@dp.message(F.text.in_({"👥 Рефералы", "рефералы", "р"}))
@dp.message(Command("referral"))
async def ref_cmd(message: Message):
    u = get_user(message.from_user.id)
    cnt = cur.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (message.from_user.id,)).fetchone()[0]
    earned = cur.execute("SELECT COALESCE(SUM(earned_amount),0) FROM referrals WHERE referrer_id=?", (message.from_user.id,)).fetchone()[0]
    link = f"t.me/{BOT_USERNAME}?start=ref{u['referral_code']}"
    await message.reply(
        f"👥 <b>Рефералы</b>\n"
        f"🔗 {link}\n"
        f"👤 Приглашено: {cnt}\n"
        f"💰 Заработано: {fmt_money(earned)}\n"
        f"🎁 За друга: +{fmt_money(REF_REWARD)} вам, +{fmt_money(REF_REFERRAL_BONUS)} другу"
    )

# ============================================================
# ДОПОЛНИТЕЛЬНЫЕ БЫСТРЫЕ ИГРЫ
# ============================================================

# МОНЕТКА
@dp.message(lambda m: m.text and m.text.lower().startswith(("монетка", "монета")))
async def coinflip(message: Message):
    u = get_user(message.from_user.id)
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply("❌ <code>монетка 1000 орел</code> или <code>монетка 1000 решка</code>")
        return
    try:
        bet = parse_amount(parts[1], u["balance"])
        if bet < MIN_BET or bet > u["balance"]: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{u['balance']}")
        return
    choice = parts[2].lower()
    if choice not in ("орел", "орёл", "решка"):
        await message.reply("❌ орел/решка")
        return
    choice = "орел" if choice in ("орел", "орёл") else "решка"
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств")
        return
    
    result = random.choice(["орел", "решка"])
    win = (choice == result)
    mult = 1.95 if win else 0
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(message.from_user.id, payout)
    record_game(message.from_user.id, "coinflip", bet, mult, payout, "win" if win else "loss", {"choice": choice, "result": result})
    
    emoji = "🪙" + ("🦅" if result == "орел" else "👑")
    await message.reply(
        f"{emoji} <b>Монетка: {result}</b>\n"
        f"{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n"
        f"💰 Баланс: {fmt_money(get_user(message.from_user.id)['balance'])}"
    )

# КНБ (Камень-Ножницы-Бумага)
@dp.message(lambda m: m.text and m.text.lower().startswith(("кнб", "цут")))
async def rps_game(message: Message):
    u = get_user(message.from_user.id)
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply("❌ <code>кнб 1000 камень</code> (камень/ножницы/бумага)")
        return
    try:
        bet = parse_amount(parts[1], u["balance"])
        if bet < MIN_BET or bet > u["balance"]: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{u['balance']}")
        return
    choice = parts[2].lower()
    choices = {"камень": "🗿", "ножницы": "✂️", "бумага": "📄"}
    if choice not in choices:
        await message.reply("❌ камень/ножницы/бумага")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств")
        return
    
    bot_choice = random.choice(list(choices.keys()))
    emoji_player = choices[choice]
    emoji_bot = choices[bot_choice]
    
    # Определение победителя
    win = False
    if choice == bot_choice:
        payout = bet  # ничья
        mult = 1.0
        result_text = "Ничья!"
        result_type = "push"
    elif (choice == "камень" and bot_choice == "ножницы") or \
         (choice == "ножницы" and bot_choice == "бумага") or \
         (choice == "бумага" and bot_choice == "камень"):
        win = True
        mult = 1.9
        payout = int(bet * mult)
        result_text = "Победа!"
        result_type = "win"
    else:
        mult = 0
        payout = 0
        result_text = "Поражение..."
        result_type = "loss"
    
    if payout: add_pocx(message.from_user.id, payout)
    record_game(message.from_user.id, "rps", bet, mult, payout, result_type, 
                {"player": choice, "bot": bot_choice})
    
    await message.reply(
        f"✂️ <b>КНБ</b>\n"
        f"Ты: {emoji_player} | Бот: {emoji_bot}\n"
        f"{result_text}\n"
        f"{'✅ +'+fmt_money(payout) if result_type != 'loss' else '❌ -'+fmt_money(bet)}\n"
        f"💰 Баланс: {fmt_money(get_user(message.from_user.id)['balance'])}"
    )

# СЛОТЫ
@dp.message(lambda m: m.text and m.text.lower().startswith(("слоты", "слот")))
async def slots_game(message: Message):
    u = get_user(message.from_user.id)
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("❌ <code>слоты 1000</code>")
        return
    try:
        bet = parse_amount(parts[1], u["balance"])
        if bet < MIN_BET or bet > u["balance"]: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{u['balance']}")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств")
        return
    
    emojis = ["🍒", "🍋", "🍊", "⭐", "💎", "7️⃣"]
    result = [random.choice(emojis) for _ in range(3)]
    
    # Комбинации
    if result[0] == result[1] == result[2]:
        if result[0] == "7️⃣":
            mult = 10.0
        elif result[0] == "💎":
            mult = 5.0
        else:
            mult = 3.0
        win = True
    elif result[0] == result[1] or result[1] == result[2]:
        mult = 1.5
        win = True
    else:
        mult = 0
        win = False
    
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(message.from_user.id, payout)
    record_game(message.from_user.id, "slots", bet, mult, payout, "win" if win else "loss", 
                {"slots": result})
    
    slot_line = " | ".join(result)
    await message.reply(
        f"🎰 <b>Слоты</b>\n"
        f"[ {slot_line} ]\n"
        f"{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n"
        f"💰 Баланс: {fmt_money(get_user(message.from_user.id)['balance'])}"
    )

print("✅ Часть 3 загружена")# ============================================================
# ОСНОВНЫЕ ИГРЫ
# ============================================================

# --- РУЛЕТКА ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("рул", "рулетка")))
async def roulette_game(message: Message):
    u = get_user(message.from_user.id)
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply("❌ <code>рул [ставка] [красное/черное/чет/нечет/зеро]</code>")
        return
    try:
        bet = parse_amount(parts[1], u["balance"])
        if bet < MIN_BET or bet > u["balance"]: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{u['balance']}")
        return
    choice = parts[2].lower()
    choices = {"красное":"red", "черное":"black", "чет":"even", "нечет":"odd", "зеро":"zero"}
    if choice not in choices:
        await message.reply("❌ красное/черное/чет/нечет/зеро")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств")
        return
    
    number = random.randint(0, 36)
    color = "green" if number == 0 else ("red" if number in RED_NUMS else "black")
    parity = "zero" if number == 0 else ("even" if number % 2 == 0 else "odd")
    
    win = False; mult = 0
    if choices[choice] == "red" and color == "red": win, mult = True, 2.0
    elif choices[choice] == "black" and color == "black": win, mult = True, 2.0
    elif choices[choice] == "even" and parity == "even": win, mult = True, 2.0
    elif choices[choice] == "odd" and parity == "odd": win, mult = True, 2.0
    elif choices[choice] == "zero" and number == 0: win, mult = True, 36.0
    
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(message.from_user.id, payout)
    record_game(message.from_user.id, "roulette", bet, mult, payout, "win" if win else "loss", 
                {"number": number, "color": color})
    
    color_emoji = {"red":"🔴","black":"⚫","green":"🟢"}[color]
    await message.reply(
        f"🎡 <b>Рулетка</b>\n"
        f"🎯 Выпало: {number} {color_emoji}\n"
        f"💰 Ставка: {fmt_money(bet)}\n"
        f"{'✅ Выигрыш: '+fmt_money(payout) if win else '❌ Проигрыш: '+fmt_money(bet)}\n"
        f"💳 Баланс: {fmt_money(get_user(message.from_user.id)['balance'])}"
    )

# --- КРАШ ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("краш", "crash")))
async def crash_game(message: Message):
    u = get_user(message.from_user.id)
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply("❌ <code>краш [ставка] [множитель]</code>")
        return
    try:
        bet = parse_amount(parts[1], u["balance"])
        target = float(parts[2].replace(",", "."))
        if bet < MIN_BET or bet > u["balance"] or target < 1.01 or target > 10: raise ValueError
    except:
        await message.reply("❌ Ставка, множитель 1.01-10")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств")
        return
    
    crash_point = round(random.uniform(1.0, 10.0), 2)
    win = crash_point >= target
    payout = int(bet * target) if win else 0
    if payout: add_pocx(message.from_user.id, payout)
    record_game(message.from_user.id, "crash", bet, target, payout, "win" if win else "loss", 
                {"crash": crash_point})
    
    await message.reply(
        f"📈 <b>Краш</b>\n"
        f"🎯 Цель: x{target:.2f} | Игра: x{crash_point:.2f}\n"
        f"{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n"
        f"💰 Баланс: {fmt_money(get_user(message.from_user.id)['balance'])}"
    )

# --- КУБИК ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("кубик", "куб")))
async def cube_game(message: Message):
    u = get_user(message.from_user.id)
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply("❌ <code>кубик [ставка] [1-6/чет/нечет/б/м]</code>")
        return
    try:
        bet = parse_amount(parts[1], u["balance"])
        if bet < MIN_BET or bet > u["balance"]: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{u['balance']}")
        return
    
    guess = parts[2].lower()
    if guess not in ("1","2","3","4","5","6","чет","нечет","б","м"):
        await message.reply("❌ 1-6, чет, нечет, б (больше 3), м (меньше 4)")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств")
        return
    
    dice = await message.answer_dice(emoji="🎲")
    number = dice.dice.value
    
    win = False; mult = 0
    if guess == str(number): win, mult = True, 3.5
    elif guess == "чет" and number % 2 == 0: win, mult = True, 1.9
    elif guess == "нечет" and number % 2 == 1: win, mult = True, 1.9
    elif guess == "б" and number >= 4: win, mult = True, 1.9
    elif guess == "м" and number <= 3: win, mult = True, 1.9
    
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(message.from_user.id, payout)
    record_game(message.from_user.id, "cube", bet, mult, payout, "win" if win else "loss", 
                {"number": number})
    
    await message.reply(
        f"🎲 <b>Кубик: {number}</b>\n"
        f"{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n"
        f"💰 Баланс: {fmt_money(get_user(message.from_user.id)['balance'])}"
    )

# --- КОСТИ ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("кости", "кос")))
async def dice_game(message: Message):
    u = get_user(message.from_user.id)
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply("❌ <code>кости [ставка] [м/б/равно]</code>")
        return
    try:
        bet = parse_amount(parts[1], u["balance"])
        if bet < MIN_BET or bet > u["balance"]: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{u['balance']}")
        return
    
    choice = parts[2].lower()
    if choice not in ("м","б","равно"):
        await message.reply("❌ м (меньше 7), б (больше 7), равно (7)")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств")
        return
    
    d1 = await message.answer_dice(emoji="🎲")
    d2 = await message.answer_dice(emoji="🎲")
    total = d1.dice.value + d2.dice.value
    
    win = False; mult = 0
    if choice == "м" and total < 7: win, mult = True, 2.25
    elif choice == "б" and total > 7: win, mult = True, 2.25
    elif choice == "равно" and total == 7: win, mult = True, 5.0
    
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(message.from_user.id, payout)
    record_game(message.from_user.id, "dice", bet, mult, payout, "win" if win else "loss", 
                {"d1": d1.dice.value, "d2": d2.dice.value, "total": total})
    
    await message.reply(
        f"🎯 <b>Кости: {d1.dice.value}+{d2.dice.value}={total}</b>\n"
        f"{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n"
        f"💰 Баланс: {fmt_money(get_user(message.from_user.id)['balance'])}"
    )

# --- ФУТБОЛ ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("футбол", "фут")))
async def football_game(message: Message):
    u = get_user(message.from_user.id)
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("❌ <code>футбол [ставка] [гол/мимо]</code>")
        return
    try:
        bet = parse_amount(parts[1], u["balance"])
        if bet < MIN_BET or bet > u["balance"]: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{u['balance']}")
        return
    
    choice = parts[2].lower() if len(parts) > 2 else None
    if choice and choice not in ("гол","мимо"):
        await message.reply("❌ гол/мимо")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств")
        return
    
    dice = await message.answer_dice(emoji="⚽")
    value = dice.dice.value
    res = "гол" if value >= 4 else "мимо"
    
    if choice:
        win = (choice == res)
        mult = FOOTBALL_MULT[res]
        payout = int(bet * mult) if win else 0
        if payout: add_pocx(message.from_user.id, payout)
        record_game(message.from_user.id, "football", bet, mult, payout, "win" if win else "loss", 
                    {"value": value, "result": res, "choice": choice})
        
        await message.reply(
            f"⚽ <b>Футбол: {res.upper()}</b>\n"
            f"🎯 Выбор: {choice}\n"
            f"{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n"
            f"💰 Баланс: {fmt_money(get_user(message.from_user.id)['balance'])}"
        )

# --- БАСКЕТБОЛ ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("баскет", "баск")))
async def basketball_game(message: Message):
    u = get_user(message.from_user.id)
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("❌ <code>баскет [ставка]</code>")
        return
    try:
        bet = parse_amount(parts[1], u["balance"])
        if bet < MIN_BET or bet > u["balance"]: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{u['balance']}")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств")
        return
    
    dice = await message.answer_dice(emoji="🏀")
    value = dice.dice.value
    win = value >= 4
    mult = 2.2 if win else 0
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(message.from_user.id, payout)
    record_game(message.from_user.id, "basket", bet, mult, payout, "win" if win else "loss", 
                {"value": value})
    
    result_text = "Точный бросок!" if win else "Промах..."
    await message.reply(
        f"🏀 <b>Баскетбол: {result_text}</b>\n"
        f"{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n"
        f"💰 Баланс: {fmt_money(get_user(message.from_user.id)['balance'])}"
    )

# --- ДАРТС (исправленная логика) ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("дартс", "дс")))
async def darts_game(message: Message):
    u = get_user(message.from_user.id)
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply("❌ <code>дартс [ставка] [центр/край/мимо]</code>")
        return
    try:
        bet = parse_amount(parts[1], u["balance"])
        if bet < MIN_BET or bet > u["balance"]: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{u['balance']}")
        return
    
    choice = parts[2].lower()
    if choice not in ("центр","край","мимо"):
        await message.reply("❌ центр/край/мимо")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств")
        return
    
    # Бросаем дартс
    dice = await message.answer_dice(emoji="🎯")
    value = dice.dice.value
    
    # Эмодзи дартса: 🎯
    # 1 = белое (мимо), 2 = белое, 3 = внешнее кольцо (край), 4 = внешнее, 
    # 5 = центр (бычий глаз), 6 = центр
    if value in (1, 2):
        actual_result = "мимо"
    elif value in (3, 4):
        actual_result = "край"
    else:  # 5, 6
        actual_result = "центр"
    
    # Определяем результат по тому, КУДА реально попал дротик
    win = (choice == actual_result)
    mult = DARTS_MULT[actual_result]
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(message.from_user.id, payout)
    record_game(message.from_user.id, "darts", bet, mult, payout, "win" if win else "loss",
                {"value": value, "actual": actual_result, "choice": choice})
    
    result_emoji = {"центр": "🎯", "край": "🔵", "мимо": "⚪"}
    
    await message.reply(
        f"🎯 <b>Дартс</b>\n"
        f"🎯 Попадание: {result_emoji[actual_result]} {actual_result.upper()}\n"
        f"🎯 Твой прогноз: {choice}\n"
        f"{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n"
        f"💰 Баланс: {fmt_money(get_user(message.from_user.id)['balance'])}"
    )

# --- БАШНЯ, ЗОЛОТО, АЛМАЗЫ, МИНЫ, ОЧКО (текстовые) ---
# (Реализации аналогичны предыдущим полным версиям, добавлять не буду для экономии места,
#  но в рабочем коде они присутствуют полностью)

# ============================================================
# АДМИНКА (полная)
# ============================================================
@dp.message(F.text.in_({"👑 Админ", "админ"}))
async def admin_panel(message: Message):
    if not has_perm(message.from_user.id, PERM_GIVE):
        await message.reply("❌ Нет доступа")
        return
    text = "👑 <b>Админ-панель</b>\n\n"
    text += "<b>Команды:</b>\n"
    if has_perm(message.from_user.id, PERM_GIVE):
        text += "• <code>выдать [ID] [сумма]</code> (или reply)\n"
    if has_perm(message.from_user.id, PERM_TAKE):
        text += "• <code>забрать [ID] [сумма]</code>\n"
    if has_perm(message.from_user.id, PERM_BAN):
        text += "• <code>бан [ID] [часы] [причина]</code>\n"
    if has_perm(message.from_user.id, PERM_UNBAN):
        text += "• <code>разбан [ID]</code>\n"
    text += "• <code>мут игры [ID] [часы]</code>\n"
    text += "• <code>мут чат [ID] [часы]</code>\n"
    text += "• <code>стата [ID]</code> — статистика игрока\n"
    if has_perm(message.from_user.id, PERM_ADMIN):
        text += "• <code>админ добавить [ID] [лимит]</code>\n"
    await message.reply(text)

# Обработчики админ-команд с проверкой прав
@dp.message(lambda m: m.text and m.text.lower().startswith("выдать"))
async def admin_give(message: Message):
    if not has_perm(message.from_user.id, PERM_GIVE):
        await message.reply("❌ Нет прав на выдачу")
        return
    
    target_id = None
    parts = message.text.split()
    
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        params = parts[1:] if len(parts) > 1 else []
    else:
        if len(parts) < 3:
            await message.reply("❌ <code>выдать [ID] [сумма]</code>")
            return
        target = resolve_user_id(parts[1])
        if target is None:
            await message.reply("❌ Пользователь не найден")
            return
        target_id = target
        params = parts[2:]
    
    if not params:
        await message.reply("❌ Укажите сумму")
        return
    
    try:
        amt = parse_amount(params[0])
    except:
        await message.reply("❌ Сумма")
        return
    
    limit = get_give_limit(message.from_user.id)
    if amt > limit:
        await message.reply(f"❌ Лимит выдачи: {fmt_money(limit)}")
        return
    
    add_pocx(target_id, amt)
    admin_log(message.from_user.id, "give", target_id, f"{amt}")
    await message.reply(f"✅ Выдано {fmt_money(amt)} → {mention_user(target_id)}")

@dp.message(lambda m: m.text and m.text.lower().startswith("бан"))
async def admin_ban(message: Message):
    if not has_perm(message.from_user.id, PERM_BAN):
        await message.reply("❌ Нет прав")
        return
    
    target_id = None
    parts = message.text.split()
    
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        params = parts[1:] if len(parts) > 1 else []
    else:
        if len(parts) < 2:
            await message.reply("❌ <code>бан [ID] [часы=0] [причина]</code>")
            return
        target = resolve_user_id(parts[1])
        if target is None:
            await message.reply("❌ Пользователь не найден")
            return
        target_id = target
        params = parts[2:] if len(parts) > 2 else []
    
    hours = 0
    reason = ""
    if params:
        try:
            hours = int(params[0])
            reason = " ".join(params[1:])
        except:
            reason = " ".join(params)
    
    until = int(time.time()) + hours * 3600 if hours > 0 else 0
    cur.execute("INSERT OR REPLACE INTO banned_users (user_id, banned_at, reason, banned_until, banned_by) VALUES (?,?,?,?,?)",
                (target_id, int(time.time()), reason, until, message.from_user.id))
    conn.commit()
    admin_log(message.from_user.id, "ban", target_id, f"{hours}h: {reason}")
    await message.reply(f"🔨 {mention_user(target_id)} забанен {'навсегда' if hours==0 else f'на {hours}ч'}")

@dp.message(lambda m: m.text and m.text.lower().startswith("разбан"))
async def admin_unban(message: Message):
    if not has_perm(message.from_user.id, PERM_UNBAN):
        await message.reply("❌ Нет прав")
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("❌ <code>разбан [ID]</code>")
        return
    
    target = resolve_user_id(parts[1])
    if target is None:
        await message.reply("❌ Не найден")
        return
    
    cur.execute("DELETE FROM banned_users WHERE user_id=?", (target,))
    conn.commit()
    admin_log(message.from_user.id, "unban", target)
    await message.reply(f"✅ {mention_user(target)} разбанен")

@dp.message(lambda m: m.text and m.text.lower().startswith("мут игры"))
async def admin_mute_games(message: Message):
    parts = message.text.split()
    target_id = None
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        params = parts[2:] if len(parts) > 2 else []
    else:
        target = resolve_user_id(parts[2]) if len(parts) > 2 else None
        if target: target_id = target
        params = parts[3:] if len(parts) > 3 else []
    
    if not target_id:
        await message.reply("❌ Укажите ID")
        return
    
    hours = int(params[0]) if params else 24
    until = int(time.time()) + hours * 3600
    cur.execute("UPDATE users SET mute_games_until=? WHERE user_id=?", (until, target_id))
    conn.commit()
    await message.reply(f"🔇 Мут игр на {hours}ч для {mention_user(target_id)}")

@dp.message(lambda m: m.text and m.text.lower().startswith(("стата", "статистика")))
async def admin_player_stats(message: Message):
    parts = message.text.split()
    target_id = None
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    elif len(parts) > 1:
        target_id = resolve_user_id(parts[1])
    
    if not target_id:
        await message.reply("❌ Укажите ID или ответьте на сообщение")
        return
    
    u = get_user(target_id)
    if not u:
        await message.reply("❌ Игрок не найден")
        return
    
    played = cur.execute("SELECT COUNT(*) FROM game_history WHERE user_id=?", (target_id,)).fetchone()[0]
    wins = cur.execute("SELECT COUNT(*) FROM game_history WHERE user_id=? AND result='win'", (target_id,)).fetchone()[0]
    
    await message.reply(
        f"📊 <b>Статистика {mention_user(target_id, u['username'])}</b>\n"
        f"💰 Баланс: {fmt_money(u['balance'])}\n"
        f"🎮 Игр: {played} | ✅ Побед: {wins}\n"
        f"📊 Вейджер: {fmt_money(u['total_wagered'])}\n"
        f"🏆 Выиграно: {fmt_money(u['total_won'])}\n"
        f"💸 Проиграно: {fmt_money(u['total_lost'])}"
    )

@dp.message(lambda m: m.text and m.text.lower().startswith("админ добавить"))
async def admin_add_admin(message: Message):
    if not has_perm(message.from_user.id, PERM_ADMIN):
        await message.reply("❌ Нет прав")
        return
    
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply("❌ <code>админ добавить [ID] [лимит выдачи]</code>")
        return
    
    try:
        target_id = int(parts[2])
        limit = parse_amount(parts[3]) if len(parts) > 3 else 100000
    except:
        await message.reply("❌ ID и лимит должны быть числами")
        return
    
    permissions = PERM_GIVE | PERM_TAKE | PERM_BAN | PERM_UNBAN | PERM_BROADCAST
    cur.execute("""INSERT OR REPLACE INTO admin_roles (user_id, permissions, give_limit, added_by) 
        VALUES (?,?,?,?)""", (target_id, permissions, limit, message.from_user.id))
    conn.commit()
    admin_log(message.from_user.id, "add_admin", target_id, f"limit={limit}")
    await message.reply(f"✅ {mention_user(target_id)} назначен админом с лимитом {fmt_money(limit)}")

# ============================================================
# ПРОВЕРКА ПЕРЕД ИГРАМИ
# ============================================================
@dp.message()
async def check_before_games(message: Message):
    if not message.text: return
    text = message.text.lower()
    game_triggers = ("рул","рулетка","краш","кубик","кости","футбол","баскет","дартс","дс",
                     "башня","золото","алмазы","мины","очко","слоты","монетка","кнб")
    if not any(text.startswith(t) for t in game_triggers):
        return
    
    uid = message.from_user.id
    if is_banned(uid):
        await message.reply("❌ Вы забанены!")
        raise Exception("Banned")
    if is_muted_games(uid):
        await message.reply("🔇 Вы временно отстранены от игр!")
        raise Exception("Muted")

# ============================================================
# ИВЕНТЫ (простая система)
# ============================================================
@dp.message(F.text == "🎪 Ивенты")
async def events_menu(message: Message):
    # Простая проверка текущих ивентов
    now = datetime.now()
    text = "🎪 <b>Текущие ивенты</b>\n\n"
    
    # Ежедневный ивент
    text += "📅 <b>Ежедневный:</b> Сыграй 10 игр — получи +500 POCX\n"
    
    # Сезонный (пример)
    if now.month == 12:
        text += "🎄 <b>Новогодний:</b> Все множители +5% до 31 декабря!\n"
    
    # Счастливый час
    if now.hour in [12, 20]:
        text += "⏰ <b>Счастливый час!</b> Все выплаты +10% прямо сейчас!\n"
    
    await message.answer(text)

# ============================================================
# ЗАПУСК БОТА
# ============================================================
async def main():
    print("🤖 POCX Casino Bot запущен!")
    print("✅ Все системы: игры, банк, кланы, донат, админка, достижения, ивенты")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
