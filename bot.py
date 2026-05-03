import asyncio, random, sqlite3, hashlib, time, json, html, string
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, ChatMemberUpdated,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode

# ==================== КОНФИГУРАЦИЯ ====================
TOKEN = "8134237711:AAH5M0JJULkrl0yyOdvfCtIswRPqRtt_3hg"
ADMIN_IDS = [8478884644, 8293927811]
BOT_USERNAME = "POCXXBOT"
MIN_BET = 100
DAILY_BONUS_MIN, DAILY_BONUS_MAX = 100, 2000
WELCOME_BONUS = 1000
REF_REWARD = 5000
REF_PERCENT = 0.02
TRANSFER_FEE = 0.035
CLAN_CREATE_PRICE = 350000
STARS_TO_POCX = 2500
BANK_TERMS = {7: 0.01, 14: 0.02, 30: 0.05}
EARLY_WITHDRAW_FEE = 0.10

VIP_LEVELS = [
    ("🥉 Новичок", 0, 0),
    ("🥈 Освоенный", 500_000, 1),
    ("🥇 Легенда", 5_000_000, 2),
    ("💎 Главный", 20_000_000, 3),
    ("👑 BOSS", 500_000_000, 5),
    ("⭐ Elite — Бог казино", 5_000_000_000, 10),
]

TOWER_MULT = [1.15, 1.35, 1.62, 1.95, 2.35, 2.85, 3.50, 4.50]
GOLD_MULT = [1.10, 1.25, 1.45, 1.75, 2.15, 2.65, 3.50]
DIAMOND_MULT = [1.08, 1.22, 1.40, 1.62, 1.90, 2.25, 2.70, 3.40]
RED_NUMS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
FOOTBALL_MULT = {"гол": 1.5, "мимо": 2.0}
DARTS_MULT = {"мимо": 0, "край": 1.3, "центр": 1.8}

bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# ==================== БАЗА ДАННЫХ ====================
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
    total_refs INTEGER DEFAULT 0, ref_earned INTEGER DEFAULT 0,
    last_command_time INTEGER DEFAULT 0
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
    banned_until INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS promocodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE,
    bonus_amount INTEGER, max_uses INTEGER, used_count INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS used_promocodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, code TEXT
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
    owner_id INTEGER, balance INTEGER DEFAULT 0, tag TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS clan_members (
    user_id INTEGER, clan_id INTEGER, role TEXT DEFAULT 'member',
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, clan_id)
);
CREATE TABLE IF NOT EXISTS clan_bans (
    user_id INTEGER, clan_id INTEGER, banned_by INTEGER,
    banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, clan_id)
);
CREATE TABLE IF NOT EXISTS admin_roles (
    user_id INTEGER PRIMARY KEY, permissions INTEGER DEFAULT 0,
    give_limit INTEGER DEFAULT 100000
);
CREATE TABLE IF NOT EXISTS clan_invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT, clan_id INTEGER,
    invited_by INTEGER, invited_user INTEGER,
    status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chat_treasury (
    chat_id INTEGER PRIMARY KEY, owner_id INTEGER, balance INTEGER DEFAULT 0,
    reward_per_invite INTEGER DEFAULT 100, is_active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS treasury_rewards (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER,
    invited_by INTEGER, rewarded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chat_id, user_id)
);
""")
conn.commit()

# ==================== ХЕЛПЕРЫ ====================
def parse_amount(text: str, balance: int = 0) -> int:
    t = text.lower().strip().replace(",", ".").replace(" ", "")
    if t in ("все", "всё", "all"): return balance
    if t in ("пол", "половина", "half"): return balance // 2
    mults = {'ккк': 1_000_000_000, 'кк': 1_000_000, 'к': 1_000,
             'kkk': 1_000_000_000, 'kk': 1_000_000, 'k': 1_000,
             'm': 1_000_000, 'b': 1_000_000_000}
    for suf, m in mults.items():
        if t.endswith(suf):
            try: return int(float(t[:-len(suf)] or '1') * m)
            except: return 0
    try: return int(float(t))
    except: return 0

def fmt_money(v: int) -> str:
    if v >= 1_000_000_000: return f"{v/1_000_000_000:.1f}ккк POCX"
    if v >= 1_000_000: return f"{v/1_000_000:.1f}кк POCX"
    if v >= 1_000: return f"{v/1_000:.1f}к POCX"
    return f"{v} POCX"

def add_pocx(uid: int, amt: int):
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, uid))
    if cur.rowcount == 0:
        cur.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (uid, 5000 + amt))
    conn.commit()

def remove_pocx(uid: int, amt: int) -> bool:
    cur.execute("SELECT balance FROM users WHERE user_id = ?", (uid,))
    r = cur.fetchone()
    if not r or r[0] < amt: return False
    cur.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amt, uid))
    conn.commit(); return True

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
        "total_donated": r[15] or 0, "total_refs": r[16] or 0,
        "ref_earned": r[17] or 0, "last_command_time": r[18] or 0
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

def check_cooldown(uid: int) -> bool:
    u = get_user(uid)
    if not u: return True
    now = int(time.time())
    if now - u["last_command_time"] < 5:
        return False
    cur.execute("UPDATE users SET last_command_time = ? WHERE user_id = ?", (now, uid))
    conn.commit()
    return True

def record_game(uid, game_type, bet, mult, win, result, details):
    cur.execute("""UPDATE users SET 
        total_wagered = total_wagered + ?, 
        total_won = total_won + ?, 
        total_lost = total_lost + ?,
        games_played_today = games_played_today + 1 
        WHERE user_id = ?""",
        (bet, win if result == "win" else 0, bet if result == "loss" else 0, uid))
    cur.execute("""INSERT INTO game_history (user_id, game_type, bet_amount, multiplier, win_amount, result, details) 
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (uid, game_type, bet, mult, win, result, json.dumps(details, ensure_ascii=False)))
    conn.commit()

def resolve_user_id(arg: str):
    arg = arg.strip().lstrip("@")
    if arg.isdigit(): return int(arg)
    cur.execute("SELECT user_id FROM users WHERE username = ?", (arg,))
    r = cur.fetchone()
    return r[0] if r else None

def mention_user(uid: int, name: str = None) -> str:
    return f'<a href="tg://user?id={uid}">{html.escape(name or str(uid))}</a>'

def has_perm(uid: int) -> bool:
    if uid in ADMIN_IDS: return True
    return cur.execute("SELECT 1 FROM admin_roles WHERE user_id = ?", (uid,)).fetchone() is not None

def check_withdraw_deps(uid):
    now = int(time.time())
    deps = cur.execute("SELECT id, principal, rate, term_days, opened_at FROM bank_deposits WHERE user_id = ? AND status = 'active'", (uid,)).fetchall()
    total, closed = 0, 0
    for d in deps:
        if now - d[4] >= d[3] * 86400:
            payout = int(d[1] * (1 + d[2]))
            add_pocx(uid, payout); total += payout; closed += 1
            cur.execute("UPDATE bank_deposits SET status = 'closed', closed_at = ? WHERE id = ?", (now, d[0]))
    conn.commit(); return closed, total

async def check_bio_subscription(user_id: int) -> bool:
    try:
        chat = await bot.get_chat(user_id)
        bio = chat.bio or ""
        return BOT_USERNAME.lower() in bio.lower()
    except:
        return False

def get_chat_treasury(chat_id: int):
    cur.execute("SELECT * FROM chat_treasury WHERE chat_id = ?", (chat_id,))
    r = cur.fetchone()
    if not r: return None
    return {"chat_id": r[0], "owner_id": r[1], "balance": r[2], "reward_per_invite": r[3], "is_active": r[4]}

# ==================== FSM ====================
class GameStates(StatesGroup):
    waiting_clan_rename = State()
    waiting_clan_deposit = State()
    waiting_clan_kick = State()
    waiting_clan_role = State()
    waiting_clan_invite = State()
    waiting_clan_ban = State()
    waiting_clan_unban = State()
    admin_give = State(); admin_take = State()
    admin_ban = State(); admin_unban = State()
    admin_broadcast = State(); admin_promo_code = State()
    admin_promo_reward = State(); admin_promo_uses = State()
    admin_mute_games = State(); admin_mute_chat = State()
    admin_add_admin = State(); bank_amount = State()
    donate_custom = State(); waiting_clan_name = State()

# Игровые сессии
TOWER_GAMES = {}; GOLD_GAMES = {}; DIAMOND_GAMES = {}; MINES_GAMES = {}; OCHKO_GAMES = {}

# ==================== КЛАВИАТУРЫ ====================
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🎮 Игры"), KeyboardButton(text="👤 Профиль")],
    [KeyboardButton(text="🏆 Топ"), KeyboardButton(text="📊 Статистика")],
    [KeyboardButton(text="🎁 Бонусы"), KeyboardButton(text="💰 Донат")],
    [KeyboardButton(text="🏦 Банк"), KeyboardButton(text="🏰 Кланы")],
    [KeyboardButton(text="👥 Рефералы"), KeyboardButton(text="🏦 Казна")],
    [KeyboardButton(text="👑 Админ"), KeyboardButton(text="❓ Помощь")],
    [KeyboardButton(text="◀️ Главное меню")]
], resize_keyboard=True)

games_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🗼 Башня", callback_data="game_tower"),
     InlineKeyboardButton(text="🥇 Золото", callback_data="game_gold")],
    [InlineKeyboardButton(text="💎 Алмазы", callback_data="game_diamond"),
     InlineKeyboardButton(text="💣 Мины", callback_data="game_mines")],
    [InlineKeyboardButton(text="🎴 Очко", callback_data="game_ochko"),
     InlineKeyboardButton(text="🎡 Рулетка", callback_data="game_roulette")],
    [InlineKeyboardButton(text="📈 Краш", callback_data="game_crash"),
     InlineKeyboardButton(text="🎲 Кубик", callback_data="game_cube")],
    [InlineKeyboardButton(text="🎯 Кости", callback_data="game_dice"),
     InlineKeyboardButton(text="⚽ Футбол", callback_data="game_football")],
    [InlineKeyboardButton(text="🏀 Баскет", callback_data="game_basket"),
     InlineKeyboardButton(text="🎯 Дартс", callback_data="game_darts")],
    [InlineKeyboardButton(text="🎰 Слоты", callback_data="game_slots"),
     InlineKeyboardButton(text="🪙 Монетка", callback_data="game_coinflip")],
    [InlineKeyboardButton(text="✂️ КНБ", callback_data="game_rps")],
    [InlineKeyboardButton(text="🔙 Закрыть", callback_data="close_menu")]
])

def clan_main_kb(user_id: int) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(text="🏰 Мой клан", callback_data="clan_my")]]
    kb.append([InlineKeyboardButton(text="🔍 Поиск клана", callback_data="clan_search")])
    kb.append([InlineKeyboardButton(text="➕ Создать клан", callback_data="clan_create_menu")])
    kb.append([InlineKeyboardButton(text="📋 Топ кланов", callback_data="clan_top")])
    kb.append([InlineKeyboardButton(text="🔙 Закрыть", callback_data="clan_close")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def clan_manage_kb(clan_id: int, user_id: int) -> InlineKeyboardMarkup:
    is_owner = cur.execute("SELECT 1 FROM clans WHERE id = ? AND owner_id = ?", (clan_id, user_id)).fetchone()
    is_deputy = cur.execute("SELECT 1 FROM clan_members WHERE clan_id = ? AND user_id = ? AND role = 'deputy'", (clan_id, user_id)).fetchone()
    kb = []
    if is_owner:
        kb.append([InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"clan_rename_{clan_id}")])
        kb.append([InlineKeyboardButton(text="👑 Назначить зама", callback_data=f"clan_role_{clan_id}")])
        kb.append([InlineKeyboardButton(text="👢 Кикнуть", callback_data=f"clan_kick_{clan_id}")])
        kb.append([InlineKeyboardButton(text="🔨 Забанить", callback_data=f"clan_ban_{clan_id}")])
        kb.append([InlineKeyboardButton(text="🔓 Разбанить", callback_data=f"clan_unban_{clan_id}")])
        kb.append([InlineKeyboardButton(text="🗑 Расформировать", callback_data=f"clan_delete_{clan_id}")])
    if is_owner or is_deputy:
        kb.append([InlineKeyboardButton(text="🔗 Пригласить", callback_data=f"clan_invite_{clan_id}")])
    kb.append([InlineKeyboardButton(text="💰 Пополнить казну", callback_data=f"clan_deposit_{clan_id}")])
    kb.append([InlineKeyboardButton(text="👥 Участники", callback_data=f"clan_members_{clan_id}")])
    kb.append([InlineKeyboardButton(text="🚪 Выйти из клана", callback_data=f"clan_leave_{clan_id}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="clan_back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

donate_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⭐ 1 Star — 2,500 POCX", callback_data="donate_1")],
    [InlineKeyboardButton(text="⭐⭐ 5 Stars — 12,500 POCX", callback_data="donate_5")],
    [InlineKeyboardButton(text="⭐⭐⭐ 10 Stars — 25,000 POCX", callback_data="donate_10")],
    [InlineKeyboardButton(text="💰 25 Stars — 62,500 POCX", callback_data="donate_25")],
    [InlineKeyboardButton(text="💎 50 Stars — 125,000 POCX", callback_data="donate_50")],
    [InlineKeyboardButton(text="✏️ Своя сумма", callback_data="donate_custom")],
    [InlineKeyboardButton(text="🔙 Закрыть", callback_data="close_menu")]
])

admin_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="💰 Выдать", callback_data="admin_give"),
     InlineKeyboardButton(text="➖ Забрать", callback_data="admin_take")],
    [InlineKeyboardButton(text="🔨 Бан", callback_data="admin_ban"),
     InlineKeyboardButton(text="🔓 Разбан", callback_data="admin_unban")],
    [InlineKeyboardButton(text="🔇 Мут игр", callback_data="admin_mute_games"),
     InlineKeyboardButton(text="🔇 Мут чат", callback_data="admin_mute_chat")],
    [InlineKeyboardButton(text="🎟 Промокод", callback_data="admin_promo"),
     InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
    [InlineKeyboardButton(text="👑 Назначить", callback_data="admin_add_admin"),
     InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
    [InlineKeyboardButton(text="🔙 Закрыть", callback_data="close_menu")]
])

# ==================== СТАРТ ====================
@dp.message(Command("start"))
async def start(msg: Message):
    uid = msg.from_user.id; uname = msg.from_user.username
    user = get_user(uid)
    if not user:
        code = hashlib.md5(f"{uid}{time.time()}".encode()).hexdigest()[:8]
        cur.execute("INSERT INTO users (user_id, username, referral_code, balance) VALUES (?, ?, ?, 5000)", (uid, uname, code))
        conn.commit(); user = get_user(uid)
    
    args = msg.text.split()
    if len(args) > 1:
        if args[1].startswith("ref_"):
            ref_code = args[1][4:]
            ref = cur.execute("SELECT user_id FROM users WHERE referral_code = ?", (ref_code,)).fetchone()
            if ref and ref[0] != uid:
                if not cur.execute("SELECT 1 FROM referrals WHERE referrer_id = ? AND referred_id = ?", (ref[0], uid)).fetchone():
                    add_pocx(ref[0], REF_REWARD)
                    add_pocx(uid, 500)
                    cur.execute("INSERT INTO referrals (referrer_id, referred_id, earned_amount) VALUES (?, ?, ?)", (ref[0], uid, REF_REWARD))
                    cur.execute("UPDATE users SET total_refs = total_refs + 1, ref_earned = ref_earned + ? WHERE user_id = ?", (REF_REWARD, ref[0]))
                    conn.commit()
        elif args[1].startswith("check_"):
            code = args[1][6:]
            row = cur.execute("SELECT per_user, remaining, used FROM checks WHERE code = ?", (code,)).fetchone()
            if row and row[1] > 0:
                used = json.loads(row[2]) if row[2] else []
                if str(uid) not in used:
                    add_pocx(uid, row[0]); used.append(str(uid))
                    cur.execute("UPDATE checks SET remaining = remaining - 1, used = ? WHERE code = ?", (json.dumps(used), code))
                    conn.commit()
    
    vip, _ = get_vip(get_user(uid)["total_wagered"])
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{get_user(uid)['referral_code']}"
    await msg.answer(
        f"🎰 <b>POCX Casino</b>\n\n"
        f"💰 Баланс: {fmt_money(get_user(uid)['balance'])}\n"
        f"💎 VIP: {vip}\n\n"
        f"👥 Реф. ссылка:\n{ref_link}\n\n"
        f"💡 <code>помощь</code> — все команды",
        reply_markup=main_kb
    )

@dp.message(F.text == "◀️ Главное меню")
async def back_main(msg: Message):
    u = get_user(msg.from_user.id); vip, _ = get_vip(u["total_wagered"])
    await msg.answer(f"🎰 Главное меню\n💰 {fmt_money(u['balance'])} | {vip}", reply_markup=main_kb)

@dp.message(F.text == "❓ Помощь")
async def help_cmd(msg: Message):
    await msg.answer(
        "❓ <b>Помощь</b>\n\n"
        "<b>🎮 Игры:</b>\n"
        "<code>рул [ставка] [красное/черное/чет/нечет/зеро]</code>\n"
        "<code>краш [ставка] [множ]</code>\n"
        "<code>кубик [ставка] [1-6/чет/нечет/б/м]</code>\n"
        "<code>кости [ставка] [м/б/равно]</code>\n"
        "<code>футбол [ставка] [гол/мимо]</code>\n"
        "<code>баскет [ставка]</code>\n"
        "<code>дартс [ставка] [центр/край/мимо]</code>\n"
        "<code>слоты [ставка]</code> | <code>монетка [ставка] [орел/решка]</code>\n"
        "<code>кнб [ставка] [камень/ножницы/бумага]</code>\n"
        "<code>башня [ставка] [мины 1-3]</code>\n"
        "<code>золото [ставка]</code>\n"
        "<code>алмазы [ставка] [мины 1-2]</code>\n"
        "<code>мины [ставка] [мины 1-5]</code>\n"
        "<code>очко [ставка]</code>\n\n"
        "<b>💰 Финансы:</b>\n"
        "<code>б</code> — баланс | <code>передать [сумма]</code> (reply)\n"
        "<code>донат</code> — пополнение\n\n"
        "<b>🏦 Банк:</b> <code>банк</code>\n"
        "<b>🏰 Кланы:</b> <code>кланы</code>\n"
        "<b>👥 Рефералы:</b> <code>реф</code> или <code>/ref</code>\n"
        "<b>🎁 Бонусы:</b> <code>бонус</code> | <code>промокод КОД</code>\n\n"
        "💡 <b>Сокращения:</b> 1к=1000, все=весь баланс, пол=половина"
    )

@dp.chat_member()
async def on_bot_added(event: ChatMemberUpdated):
    if event.new_chat_member.user.id == (await bot.get_me()).id:
        await bot.send_message(
            event.chat.id,
            "🤖 <b>POCX Casino Bot добавлен!</b>\n\n"
            "🎮 Игры прямо в чате:\n"
            "<code>рул 1000 красное</code>\n"
            "<code>краш 1000 2.5</code>\n"
            "<code>кости 1000 м</code>\n\n"
            "📋 <code>помощь</code> — все команды"
        )

# ==================== БАЗОВЫЕ КОМАНДЫ (С КУЛДАУНОМ) ====================
@dp.message(lambda m: m.text and m.text.lower().strip() in ["б", "баланс"])
@dp.message(Command("balance"))
async def balance_cmd(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    u = get_user(msg.from_user.id)
    await msg.reply(f"💰 <b>Баланс:</b> {fmt_money(u['balance'])}")

@dp.message(lambda m: m.text and m.text.lower().strip() in ["👤 профиль", "профиль", "п"])
@dp.message(Command("profile"))
async def profile_cmd(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    u = get_user(msg.from_user.id); vip, _ = get_vip(u["total_wagered"])
    await msg.answer(
        f"👤 <b>{msg.from_user.first_name}</b>\n"
        f"💰 Баланс: {fmt_money(u['balance'])}\n"
        f"💎 VIP: {vip}\n"
        f"🏷 Статус: {u.get('custom_status', 'Обычный')}\n"
        f"📊 Вейджер: {fmt_money(u['total_wagered'])}\n"
        f"🏆 Выиграно: {fmt_money(u['total_won'])}\n"
        f"💸 Проиграно: {fmt_money(u['total_lost'])}\n"
        f"🎮 Игр сегодня: {u['games_played_today']}\n"
        f"🔥 Серия: {u['daily_streak']} дн.\n"
        f"👥 Рефералов: {u['total_refs']}"
    )

@dp.message(lambda m: m.text and m.text.lower().strip() in ["🏆 топ", "топ", "т"])
@dp.message(Command("top"))
async def top_cmd(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    rows = cur.execute("SELECT user_id, username, total_won FROM users ORDER BY total_won DESC LIMIT 10").fetchall()
    medals = ["🥇", "🥈", "🥉"]
    text = "🏆 <b>Топ-10</b>\n\n"
    for i, r in enumerate(rows):
        m = medals[i] if i < 3 else f"{i+1}."
        name = r[1] or f"ID{r[0]}"
        text += f"{m} {name} — {fmt_money(r[2])}\n"
    await msg.answer(text)

@dp.message(lambda m: m.text and m.text.lower().strip() in ["📊 статистика", "ст", "стата", "статистика"])
@dp.message(Command("stats"))
async def stats_cmd(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    u = get_user(msg.from_user.id)
    played = cur.execute("SELECT COUNT(*) FROM game_history WHERE user_id = ?", (msg.from_user.id,)).fetchone()[0]
    wins = cur.execute("SELECT COUNT(*) FROM game_history WHERE user_id = ? AND result = 'win'", (msg.from_user.id,)).fetchone()[0]
    best = cur.execute("SELECT MAX(multiplier) FROM game_history WHERE user_id = ? AND result = 'win'", (msg.from_user.id,)).fetchone()[0] or 0
    await msg.answer(
        f"📊 <b>Статистика</b>\n"
        f"🎮 Игр: {played}\n"
        f"✅ Побед: {wins} ({wins/max(played,1)*100:.1f}%)\n"
        f"📈 Лучший множитель: x{best:.2f}\n"
        f"💰 Вейджер: {fmt_money(u['total_wagered'])}\n"
        f"🏆 Выиграно: {fmt_money(u['total_won'])}\n"
        f"💸 Проиграно: {fmt_money(u['total_lost'])}"
    )

# ==================== ИГРЫ МЕНЮ ====================
@dp.message(F.text == "🎮 Игры")
async def games_menu_cmd(msg: Message):
    await msg.answer("🎮 <b>Выберите игру:</b>", reply_markup=games_kb)

@dp.callback_query(F.data.startswith("game_"))
async def game_info(callback: CallbackQuery):
    game_texts = {
        "game_tower": "🗼 <b>Башня</b>\n<code>башня [ставка] [мины 1-3]</code>",
        "game_gold": "🥇 <b>Золото</b>\n<code>золото [ставка]</code>",
        "game_diamond": "💎 <b>Алмазы</b>\n<code>алмазы [ставка] [мины 1-2]</code>",
        "game_mines": "💣 <b>Мины</b>\n<code>мины [ставка] [мины 1-5]</code>",
        "game_ochko": "🎴 <b>Очко</b>\n<code>очко [ставка]</code>",
        "game_roulette": "🎡 <b>Рулетка</b>\n<code>рул [ставка] [красное/черное/чет/нечет/зеро]</code>",
        "game_crash": "📈 <b>Краш</b>\n<code>краш [ставка] [множ]</code>",
        "game_cube": "🎲 <b>Кубик</b>\n<code>кубик [ставка] [1-6/чет/нечет/б/м]</code>",
        "game_dice": "🎯 <b>Кости</b>\n<code>кости [ставка] [м/б/равно]</code>",
        "game_football": "⚽ <b>Футбол</b>\n<code>футбол [ставка] [гол/мимо]</code>",
        "game_basket": "🏀 <b>Баскет</b>\n<code>баскет [ставка]</code>",
        "game_darts": "🎯 <b>Дартс</b>\n<code>дартс [ставка] [центр/край/мимо]</code>",
        "game_slots": "🎰 <b>Слоты</b>\n<code>слоты [ставка]</code>",
        "game_coinflip": "🪙 <b>Монетка</b>\n<code>монетка [ставка] [орел/решка]</code>",
        "game_rps": "✂️ <b>КНБ</b>\n<code>кнб [ставка] [камень/ножницы/бумага]</code>",
    }
    text = game_texts.get(callback.data, "Игра не найдена")
    await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(F.data == "close_menu")
async def close_menu(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

# ==================== БОНУС ====================
@dp.message(lambda m: m.text and m.text.lower().strip() in ["🎁 бонусы", "бонус", "бн"])
@dp.message(Command("bonus"))
async def bonus_cmd(msg: Message):
    uid = msg.from_user.id
    if not check_cooldown(uid): return
    
    # Проверка подписи профиля
    bio_ok = await check_bio_subscription(uid)
    if not bio_ok:
        await msg.answer(
            "🏝 <b>Ежедневный бонус</b>\n\n"
            "·····················\n"
            f"<b>{msg.from_user.first_name}</b>, чтобы получать дневные подарки, нужно:\n"
            "·················\n"
            f"1⃣ Добавить юзера @{BOT_USERNAME} в описание своего профиля в «О себе».\n"
            "·················\n"
            f"2⃣ Написать любую команду в личные сообщения @{BOT_USERNAME}.\n\n"
            "ℹ️ Чтобы получать ежедневные подарки, необходимо выполнить указанные выше условия. Если у вас возникают трудности, нажав на кнопку «Помощь», вы сможете найти ответы на свои вопросы."
        )
        return
    
    row = cur.execute("SELECT last_daily_bonus, daily_streak FROM users WHERE user_id = ?", (uid,)).fetchone()
    last, streak = row[0] if row else None, row[1] if row else 0
    if last and datetime.now() - datetime.fromisoformat(last) < timedelta(days=1):
        await msg.answer("❌ Бонус уже получен сегодня!"); return
    
    bonus = int(random.randint(DAILY_BONUS_MIN, DAILY_BONUS_MAX) * (1 + min(streak * 0.05, 0.5)))
    add_pocx(uid, bonus)
    cur.execute("UPDATE users SET last_daily_bonus = CURRENT_TIMESTAMP, daily_streak = daily_streak + 1 WHERE user_id = ?", (uid,)); conn.commit()
    await msg.answer(f"🎁 +{bonus:,} POCX | 🔥 Серия: {streak+1} дн.")

# ==================== ДОНАТ ====================
@dp.message(F.text.in_({"💰 Донат", "донат"}))
async def donate_menu(msg: Message):
    await msg.answer("💎 <b>Пополнение через Telegram Stars</b>\n⭐ 1 Star = 2,500 POCX", reply_markup=donate_kb)

@dp.callback_query(F.data.startswith("donate_"))
async def donate_handler(callback: CallbackQuery, state: FSMContext):
    if callback.data == "donate_custom":
        await state.set_state(GameStates.donate_custom)
        await callback.message.answer("✏️ Введи сумму в Stars (1-2500):")
        await callback.answer(); return
    amounts = {"donate_1": 1, "donate_5": 5, "donate_10": 10, "donate_25": 25, "donate_50": 50}
    stars = amounts.get(callback.data, 1); pocx = stars * STARS_TO_POCX
    await bot.send_invoice(
        chat_id=callback.from_user.id, title="Пополнение POCX",
        description=f"{stars} Stars = {pocx:,} POCX",
        payload=f"donate_{stars}_{pocx}", provider_token="", currency="XTR",
        prices=[LabeledPrice(label=f"{stars} Stars", amount=stars)]
    )
    await callback.answer("✅ Счёт!")

@dp.message(GameStates.donate_custom)
async def donate_custom_amount(msg: Message, state: FSMContext):
    try:
        stars = int(msg.text)
        if stars < 1 or stars > 2500: raise ValueError
    except: await msg.answer("❌ 1-2500 Stars!"); return
    pocx = stars * STARS_TO_POCX
    await bot.send_invoice(
        chat_id=msg.from_user.id, title="Пополнение POCX",
        description=f"{stars} Stars = {pocx:,} POCX",
        payload=f"donate_{stars}_{pocx}", provider_token="", currency="XTR",
        prices=[LabeledPrice(label=f"{stars} Stars", amount=stars)]
    )
    await msg.answer("✅ Счёт выставлен!"); await state.clear()

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery): await query.answer(ok=True)

@dp.message(F.successful_payment)
async def success_pay(msg: Message):
    payload = msg.successful_payment.invoice_payload
    if payload.startswith("donate_"):
        pocx = int(payload.split("_")[2])
        add_pocx(msg.from_user.id, pocx)
        cur.execute("UPDATE users SET total_donated = total_donated + ? WHERE user_id = ?", (pocx, msg.from_user.id))
        conn.commit()
        await msg.answer(f"✅ +{fmt_money(pocx)}\n💰 Баланс: {fmt_money(get_user(msg.from_user.id)['balance'])}")

# ==================== БАНК ====================
@dp.message(F.text.in_({"🏦 Банк", "банк"}))
async def bank_menu(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    closed, payout = check_withdraw_deps(msg.from_user.id)
    if closed: await msg.answer(f"✅ Снято {closed} депозитов: +{fmt_money(payout)}")
    await msg.answer(
        "🏦 <b>Банк</b>\n\n"
        "📈 <b>Ставки:</b>\n"
        "• 7 дней: +1%\n"
        "• 14 дней: +2%\n"
        "• 30 дней: +5%\n\n"
        "📋 <b>Команды:</b>\n"
        "<code>банк открыть [сумма] [7/14/30]</code> — открыть депозит\n"
        "<code>банк список</code> — список депозитов\n"
        "<code>банк снять [ID]</code> — досрочно (-10%)\n"
        "<code>банк снять все</code> — снять всё досрочно (-10%)\n"
        "<code>банк автовыплата</code> — снять созревшие"
    )

@dp.message(lambda m: m.text and m.text.lower().startswith("банк открыть"))
async def bank_open(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    parts = msg.text.split()
    if len(parts) < 4: await msg.reply("❌ <code>банк открыть 1000 7</code>"); return
    try:
        amt = parse_amount(parts[2]); term = int(parts[3])
        if amt < 1000 or term not in BANK_TERMS: raise ValueError
    except: await msg.reply("❌ Сумма от 1000, срок 7/14/30"); return
    if not remove_pocx(msg.from_user.id, amt): await msg.reply("❌ Недостаточно средств"); return
    cur.execute("INSERT INTO bank_deposits (user_id, principal, rate, term_days, opened_at, status) VALUES (?,?,?,?,?,'active')",
                (msg.from_user.id, amt, BANK_TERMS[term], term, int(time.time()))); conn.commit()
    await msg.reply(f"✅ Депозит #{cur.lastrowid}: {fmt_money(amt)} на {term}д (+{int(BANK_TERMS[term]*100)}%)")

@dp.message(F.text.lower() == "банк список")
async def bank_list(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    deps = cur.execute("SELECT id, principal, rate, term_days, opened_at FROM bank_deposits WHERE user_id=? AND status='active'", (msg.from_user.id,)).fetchall()
    if not deps: await msg.reply("📜 Нет активных депозитов"); return
    now = int(time.time()); text = "📜 <b>Активные депозиты:</b>\n"
    for d in deps:
        left = max(0, d[3] - (now - d[4]) // 86400)
        text += f"#{d[0]}: {fmt_money(d[1])} | +{int(d[2]*100)}% | {left}д\n"
    await msg.reply(text)

@dp.message(lambda m: m.text and m.text.lower().startswith("банк снять"))
async def bank_withdraw_early(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    parts = msg.text.split()
    if len(parts) < 3: await msg.reply("❌ <code>банк снять [ID]</code> или <code>банк снять все</code>"); return
    
    if parts[2].lower() == "все":
        # Снять все досрочно
        deps = cur.execute("SELECT id, principal FROM bank_deposits WHERE user_id=? AND status='active'", (msg.from_user.id,)).fetchall()
        if not deps: await msg.reply("Нет активных депозитов"); return
        total_return = 0; now = int(time.time())
        for d in deps:
            payout = int(d[1] * (1 - EARLY_WITHDRAW_FEE))
            add_pocx(msg.from_user.id, payout); total_return += payout
            cur.execute("UPDATE bank_deposits SET status='closed', closed_at=? WHERE id=?", (now, d[0]))
        conn.commit()
        await msg.reply(f"✅ Снято {len(deps)} депозитов досрочно\n💰 Возврат: {fmt_money(total_return)} (-10%)")
    else:
        # Снять по ID
        try: dep_id = int(parts[2])
        except: await msg.reply("❌ ID должен быть числом"); return
        dep = cur.execute("SELECT id, principal FROM bank_deposits WHERE id=? AND user_id=? AND status='active'", (dep_id, msg.from_user.id)).fetchone()
        if not dep: await msg.reply("❌ Депозит не найден"); return
        payout = int(dep[1] * (1 - EARLY_WITHDRAW_FEE))
        add_pocx(msg.from_user.id, payout)
        cur.execute("UPDATE bank_deposits SET status='closed', closed_at=? WHERE id=?", (int(time.time()), dep_id))
        conn.commit()
        await msg.reply(f"✅ Депозит #{dep_id} снят досрочно\n💰 Возврат: {fmt_money(payout)} (-10%)")

@dp.message(F.text.lower() == "банк автовыплата")
async def bank_auto_withdraw(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    closed, payout = check_withdraw_deps(msg.from_user.id)
    if closed: await msg.reply(f"✅ Снято {closed} созревших депозитов: +{fmt_money(payout)}")
    else: await msg.reply("📜 Нет созревших депозитов")

# ==================== РЕФЕРАЛЫ ====================
@dp.message(F.text.in_({"👥 Рефералы", "рефералы", "реф", "рефка"}))
@dp.message(Command("ref"))
async def ref_cmd(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    u = get_user(msg.from_user.id)
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{u['referral_code']}"
    await msg.answer(
        "🫂 <b>ПРИГЛАСИТЬ ДРУЗЕЙ</b>\n"
        "·····················\n"
        "🎁 Приглашайте друзей по своей ссылке и получайте бонусы:\n"
        f"• {fmt_money(REF_REWARD)} за каждого друга\n"
        f"• {int(REF_PERCENT*100)}% от проигрыша друзей\n\n"
        "🔗 <b>Твоя ссылка:</b>\n"
        f"⤷ {ref_link}\n\n"
        f"💰 <b>Уже заработано:</b>\n"
        f"⤷ {fmt_money(u['ref_earned'])}\n"
        f"🧲 <b>Приглашено друзей:</b>\n"
        f"⤷ {u['total_refs']} чел.\n\n"
        "ℹ️ Чтобы друг был зачислен, он должен сыграть хотя бы одну игру или собрать ежедневный бонус."
    )

# ==================== ПЕРЕДАЧА ====================
@dp.message(lambda m: m.text and m.text.lower().split()[0] in ("передать", "п", "дать", "накинуть") and m.reply_to_message)
async def transfer(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    parts = msg.text.split()
    if len(parts) < 2: await msg.reply("❌ Укажи сумму"); return
    try: amount = parse_amount(parts[1]); assert amount >= 100
    except: await msg.reply("❌ Сумма от 100"); return
    u = get_user(msg.from_user.id); fee = int(amount * TRANSFER_FEE); total = amount + fee
    if u["balance"] < total: await msg.reply(f"❌ Нужно {fmt_money(total)} (ком. {TRANSFER_FEE*100:.1f}%)"); return
    target = msg.reply_to_message.from_user.id
    if target == msg.from_user.id: await msg.reply("❌ Нельзя себе"); return
    remove_pocx(msg.from_user.id, total); add_pocx(target, amount)
    await msg.reply(f"✅ {fmt_money(amount)} → {msg.reply_to_message.from_user.first_name}\n💸 Комиссия {fmt_money(fee)}")

# ==================== ПРОМОКОДЫ ====================
@dp.message(lambda m: m.text and m.text.lower().startswith("промокод"))
async def promo_use(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    parts = msg.text.split()
    if len(parts) < 2: await msg.reply("❌ <code>промокод КОД</code>"); return
    code = parts[1].upper()
    row = cur.execute("SELECT bonus_amount, max_uses, used_count, is_active FROM promocodes WHERE code=?", (code,)).fetchone()
    if not row or not row[3] or row[2] >= row[1]: await msg.reply("❌ Недействителен"); return
    if cur.execute("SELECT 1 FROM used_promocodes WHERE user_id=? AND code=?", (msg.from_user.id, code)).fetchone(): await msg.reply("❌ Уже использован"); return
    add_pocx(msg.from_user.id, row[0])
    cur.execute("INSERT INTO used_promocodes (user_id, code) VALUES (?,?)", (msg.from_user.id, code))
    cur.execute("UPDATE promocodes SET used_count=used_count+1 WHERE code=?", (code,)); conn.commit()
    await msg.reply(f"✅ +{fmt_money(row[0])}")

# ==================== ЧЕКИ ====================
@dp.message(lambda m: m.text and m.text.lower().startswith("чек создать"))
async def check_create(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    parts = msg.text.split()
    if len(parts) != 4: await msg.reply("❌ <code>чек создать 1000 5</code>"); return
    try:
        amt = parse_amount(parts[2]); cnt = int(parts[3])
        if amt <= 0 or amt > 5_000_000 or cnt <= 0 or cnt > 50: raise ValueError
    except: await msg.reply("❌ Сумма 1-5M, кол-во 1-50"); return
    if not remove_pocx(msg.from_user.id, amt * cnt): await msg.reply("❌ Недостаточно средств"); return
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    cur.execute("INSERT INTO checks (code, creator_id, per_user, remaining, used) VALUES (?,?,?,?,'[]')", (code, msg.from_user.id, amt, cnt))
    conn.commit()
    await msg.reply(f"✅ Чек <code>{code}</code>\n🔗 https://t.me/{BOT_USERNAME}?start=check_{code}\n💰 {fmt_money(amt)} x{cnt}")

@dp.message(lambda m: m.text and m.text.lower().startswith("чек активировать"))
async def check_claim(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    parts = msg.text.split()
    if len(parts) != 3: await msg.reply("❌ <code>чек активировать КОД</code>"); return
    code = parts[2].upper()
    row = cur.execute("SELECT per_user, remaining, used FROM checks WHERE code=?", (code,)).fetchone()
    if not row or row[1] <= 0: await msg.reply("❌ Недействителен"); return
    used = json.loads(row[2]) if row[2] else []
    if str(msg.from_user.id) in used: await msg.reply("❌ Уже использован"); return
    add_pocx(msg.from_user.id, row[0]); used.append(str(msg.from_user.id))
    cur.execute("UPDATE checks SET remaining=remaining-1, used=? WHERE code=?", (json.dumps(used), code)); conn.commit()
    await msg.reply(f"✅ +{fmt_money(row[0])}")

@dp.message(F.text.lower() == "чек мои")
async def check_my(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    rows = cur.execute("SELECT code, per_user, remaining FROM checks WHERE creator_id=? ORDER BY rowid DESC LIMIT 10", (msg.from_user.id,)).fetchall()
    if not rows: await msg.reply("📋 Нет чеков")
    else:
        text = "📋 Ваши чеки:\n"
        for r in rows: text += f"<code>{r[0]}</code> – {fmt_money(r[1])} (ост.{r[2]})\n"
        await msg.reply(text)

# ==================== АДМИНКА ====================
@dp.message(F.text.in_({"👑 Админ", "админ"}))
async def admin_panel(msg: Message):
    if not has_perm(msg.from_user.id): await msg.answer("❌ Нет доступа"); return
    await msg.answer("👑 <b>Админ-панель</b>", reply_markup=admin_kb)

@dp.callback_query(F.data == "admin_give")
async def admin_give_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.admin_give)
    await callback.message.edit_text("💰 Введи ID и сумму через пробел:")
    await callback.answer()

@dp.message(GameStates.admin_give)
async def admin_give_exec(msg: Message, state: FSMContext):
    parts = msg.text.split()
    if len(parts) != 2: await msg.answer("❌ ID СУММА"); return
    try: uid = int(parts[0]); amt = parse_amount(parts[1])
    except: await msg.answer("❌ Числа"); return
    add_pocx(uid, amt); await state.clear()
    await msg.answer(f"✅ Выдано {fmt_money(amt)} → {uid}")

@dp.message(lambda m: has_perm(m.from_user.id) and m.reply_to_message and m.text and m.text.lower().startswith("выдать"))
async def admin_give_reply(msg: Message):
    parts = msg.text.split()
    if len(parts) < 2: await msg.reply("❌ <code>выдать 1000</code>"); return
    try: amt = parse_amount(parts[1])
    except: await msg.reply("❌ Сумма"); return
    add_pocx(msg.reply_to_message.from_user.id, amt)
    await msg.reply(f"✅ +{fmt_money(amt)}")

@dp.callback_query(F.data == "admin_take")
async def admin_take_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.admin_take)
    await callback.message.edit_text("➖ Введи ID и сумму:")
    await callback.answer()

@dp.message(GameStates.admin_take)
async def admin_take_exec(msg: Message, state: FSMContext):
    parts = msg.text.split()
    if len(parts) != 2: return
    try: uid = int(parts[0]); amt = parse_amount(parts[1])
    except: return
    if remove_pocx(uid, amt): await msg.answer(f"✅ -{fmt_money(amt)} у {uid}")
    else: await msg.answer("❌ Недостаточно средств")
    await state.clear()

@dp.callback_query(F.data == "admin_ban")
async def admin_ban_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.admin_ban)
    await callback.message.edit_text("🔨 Введи ID [часы] [причина]:")
    await callback.answer()

@dp.message(GameStates.admin_ban)
async def admin_ban_exec(msg: Message, state: FSMContext):
    parts = msg.text.split(maxsplit=2)
    try:
        uid = int(parts[0])
        hours = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        reason = parts[2] if len(parts) > 2 else ""
    except: await msg.answer("❌ ID"); return
    until = int(time.time()) + hours * 3600 if hours > 0 else 0
    cur.execute("INSERT OR REPLACE INTO banned_users (user_id, banned_at, reason, banned_until) VALUES (?,?,?,?)", (uid, int(time.time()), reason, until))
    conn.commit(); await state.clear()
    await msg.answer(f"🔨 {uid} забанен {'навсегда' if hours==0 else f'на {hours}ч'}")

@dp.message(lambda m: has_perm(m.from_user.id) and m.reply_to_message and m.text and m.text.lower().startswith("бан"))
async def admin_ban_reply(msg: Message):
    parts = msg.text.split()
    hours = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    reason = " ".join(parts[2:]) if len(parts) > 2 else ""
    until = int(time.time()) + hours * 3600 if hours > 0 else 0
    uid = msg.reply_to_message.from_user.id
    cur.execute("INSERT OR REPLACE INTO banned_users (user_id, banned_at, reason, banned_until) VALUES (?,?,?,?)", (uid, int(time.time()), reason, until))
    conn.commit()
    await msg.reply(f"🔨 {uid} забанен")

@dp.callback_query(F.data == "admin_unban")
async def admin_unban_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.admin_unban)
    await callback.message.edit_text("🔓 Введи ID:")
    await callback.answer()

@dp.message(GameStates.admin_unban)
async def admin_unban_exec(msg: Message, state: FSMContext):
    try: uid = int(msg.text)
    except: await msg.answer("❌ ID"); return
    cur.execute("DELETE FROM banned_users WHERE user_id=?", (uid,)); conn.commit()
    await state.clear(); await msg.answer(f"✅ {uid} разбанен")

@dp.callback_query(F.data == "admin_mute_games")
async def admin_mute_games_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.admin_mute_games)
    await callback.message.edit_text("🔇 Введи ID и часы:")
    await callback.answer()

@dp.message(GameStates.admin_mute_games)
async def admin_mute_games_exec(msg: Message, state: FSMContext):
    parts = msg.text.split()
    try: uid = int(parts[0]); hours = int(parts[1]) if len(parts) > 1 else 24
    except: await msg.answer("❌ ID ЧАСЫ"); return
    until = int(time.time()) + hours * 3600
    cur.execute("UPDATE users SET mute_games_until=? WHERE user_id=?", (until, uid)); conn.commit()
    await state.clear(); await msg.answer(f"🔇 Мут игр {uid} на {hours}ч")

@dp.callback_query(F.data == "admin_mute_chat")
async def admin_mute_chat_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.admin_mute_chat)
    await callback.message.edit_text("🔇 Введи ID и часы для мута чата:")
    await callback.answer()

@dp.message(GameStates.admin_mute_chat)
async def admin_mute_chat_exec(msg: Message, state: FSMContext):
    parts = msg.text.split()
    try: uid = int(parts[0]); hours = int(parts[1]) if len(parts) > 1 else 24
    except: await msg.answer("❌ ID ЧАСЫ"); return
    until = int(time.time()) + hours * 3600
    cur.execute("UPDATE users SET mute_chat_until=? WHERE user_id=?", (until, uid)); conn.commit()
    await state.clear(); await msg.answer(f"🔇 Мут чата {uid} на {hours}ч")

@dp.callback_query(F.data == "admin_promo")
async def admin_promo_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.admin_promo_code)
    await callback.message.edit_text("🎟 Введи код промокода:")
    await callback.answer()

@dp.message(GameStates.admin_promo_code)
async def admin_promo_code_input(msg: Message, state: FSMContext):
    code = msg.text.strip().upper()
    if len(code) < 3 or len(code) > 24: await msg.answer("❌ 3-24 символа"); return
    await state.update_data(promo_code=code)
    await state.set_state(GameStates.admin_promo_reward)
    await msg.answer("💰 Сумма награды:")

@dp.message(GameStates.admin_promo_reward)
async def admin_promo_reward_input(msg: Message, state: FSMContext):
    try: reward = parse_amount(msg.text); assert reward > 0
    except: await msg.answer("❌ Положительное число"); return
    await state.update_data(promo_reward=reward)
    await state.set_state(GameStates.admin_promo_uses)
    await msg.answer("🔢 Количество активаций:")

@dp.message(GameStates.admin_promo_uses)
async def admin_promo_uses_input(msg: Message, state: FSMContext):
    try: uses = int(msg.text); assert uses > 0
    except: await msg.answer("❌ Число > 0"); return
    data = await state.get_data()
    cur.execute("INSERT INTO promocodes (code, bonus_amount, max_uses, is_active) VALUES (?,?,?,1)", (data["promo_code"], data["promo_reward"], uses))
    conn.commit(); await state.clear()
    await msg.answer(f"✅ Промокод <code>{data['promo_code']}</code> создан!\n💰 {fmt_money(data['promo_reward'])} x{uses}")

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.admin_broadcast)
    await callback.message.edit_text("📢 Введи текст рассылки:")
    await callback.answer()

@dp.message(GameStates.admin_broadcast)
async def admin_broadcast_exec(msg: Message, state: FSMContext):
    users = cur.execute("SELECT user_id FROM users").fetchall()
    sent = 0
    for u in users:
        try: await bot.send_message(u[0], f"📢 <b>Рассылка</b>\n\n{msg.text}"); sent += 1; await asyncio.sleep(0.05)
        except: pass
    await state.clear(); await msg.answer(f"✅ Отправлено {sent}/{len(users)}")

@dp.callback_query(F.data == "admin_add_admin")
async def admin_add_admin_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.admin_add_admin)
    await callback.message.edit_text("👑 Введи ID пользователя и лимит выдачи:")
    await callback.answer()

@dp.message(GameStates.admin_add_admin)
async def admin_add_admin_exec(msg: Message, state: FSMContext):
    parts = msg.text.split()
    try: uid = int(parts[0]); limit = parse_amount(parts[1]) if len(parts) > 1 else 100000
    except: await msg.answer("❌ ID ЛИМИТ"); return
    cur.execute("INSERT OR REPLACE INTO admin_roles (user_id, permissions, give_limit) VALUES (?, ?, ?)", (uid, 7, limit))
    conn.commit(); await state.clear()
    await msg.answer(f"✅ Админ {uid} назначен с лимитом {fmt_money(limit)}")

@dp.callback_query(F.data == "admin_stats")
async def admin_stats_cb(callback: CallbackQuery):
    users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_bal = cur.execute("SELECT SUM(balance) FROM users").fetchone()[0] or 0
    total_wag = cur.execute("SELECT SUM(total_wagered) FROM users").fetchone()[0] or 0
    total_won = cur.execute("SELECT SUM(total_won) FROM users").fetchone()[0] or 0
    total_lost = cur.execute("SELECT SUM(total_lost) FROM users").fetchone()[0] or 0
    banned = cur.execute("SELECT COUNT(*) FROM banned_users").fetchone()[0]
    clans = cur.execute("SELECT COUNT(*) FROM clans").fetchone()[0]
    await callback.message.edit_text(
        f"📊 <b>Статистика</b>\n"
        f"👥 Игроков: {users}\n"
        f"🚫 Банов: {banned}\n"
        f"🏰 Кланов: {clans}\n"
        f"💰 Общий баланс: {fmt_money(total_bal)}\n"
        f"📊 Вейджер: {fmt_money(total_wag)}\n"
        f"🏆 Выиграно: {fmt_money(total_won)}\n"
        f"💸 Проиграно: {fmt_money(total_lost)}\n"
        f"📈 Прибыль: {fmt_money(total_lost - total_won)}",
        reply_markup=admin_kb
    )
    await callback.answer()

# ==================== КЛАНЫ ====================
@dp.message(F.text.in_({"🏰 Кланы", "кланы", "клан"}))
async def clans_menu(msg: Message):
    await msg.answer("🏰 <b>Кланы</b>\nУправление кланами через инлайн-кнопки.", reply_markup=clan_main_kb(msg.from_user.id))

@dp.callback_query(F.data == "clan_my")
async def clan_my(callback: CallbackQuery):
    uid = callback.from_user.id
    member = cur.execute("SELECT clan_id FROM clan_members WHERE user_id = ?", (uid,)).fetchone()
    if not member:
        await callback.message.edit_text("❌ Вы не в клане.\nИспользуйте <code>клан вступить [название]</code>", reply_markup=clan_main_kb(uid))
        await callback.answer(); return
    clan = cur.execute("SELECT * FROM clans WHERE id = ?", (member[0],)).fetchone()
    members_count = cur.execute("SELECT COUNT(*) FROM clan_members WHERE clan_id = ?", (clan[0],)).fetchone()[0]
    owner = get_user(clan[2])
    text = (
        f"🏰 <b>{clan[1]}</b>\n\n"
        f"👑 Владелец: {mention_user(clan[2], owner['username'])}\n"
        f"💰 Казна: {fmt_money(clan[3])}\n"
        f"👥 Участников: {members_count}\n"
        f"🏷 Тэг: {clan[4] or 'нет'}"
    )
    await callback.message.edit_text(text, reply_markup=clan_manage_kb(clan[0], uid))
    await callback.answer()

@dp.callback_query(F.data == "clan_create_menu")
async def clan_create_menu(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.waiting_clan_name)
    await callback.message.edit_text(f"➕ Введите название нового клана (стоимость: {fmt_money(CLAN_CREATE_PRICE)}):")
    await callback.answer()

@dp.message(GameStates.waiting_clan_name)
async def clan_create_name(msg: Message, state: FSMContext):
    name = msg.text.strip()
    if cur.execute("SELECT 1 FROM clans WHERE name = ?", (name,)).fetchone(): await msg.answer("❌ Занято"); return
    if not remove_pocx(msg.from_user.id, CLAN_CREATE_PRICE): await msg.answer(f"❌ Нужно {fmt_money(CLAN_CREATE_PRICE)}"); await state.clear(); return
    cur.execute("INSERT INTO clans (name, owner_id) VALUES (?, ?)", (name, msg.from_user.id))
    clan_id = cur.lastrowid
    cur.execute("INSERT OR REPLACE INTO clan_members (user_id, clan_id, role) VALUES (?, ?, 'owner')", (msg.from_user.id, clan_id))
    conn.commit(); await state.clear()
    await msg.answer(f"🏰 Клан '{name}' создан!", reply_markup=clan_main_kb(msg.from_user.id))

@dp.callback_query(F.data == "clan_top")
async def clan_top(callback: CallbackQuery):
    rows = cur.execute("SELECT name, balance, (SELECT COUNT(*) FROM clan_members WHERE clan_id = clans.id) as cnt FROM clans ORDER BY balance DESC LIMIT 10").fetchall()
    text = "📋 <b>Топ кланов</b>\n\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. {r[0]} — {fmt_money(r[1])} | {r[2]} чел.\n"
    await callback.message.edit_text(text, reply_markup=clan_main_kb(callback.from_user.id))
    await callback.answer()

@dp.callback_query(F.data == "clan_back")
async def clan_back(callback: CallbackQuery):
    await callback.message.edit_text("🏰 <b>Кланы</b>", reply_markup=clan_main_kb(callback.from_user.id))
    await callback.answer()

@dp.callback_query(F.data == "clan_close")
async def clan_close(callback: CallbackQuery):
    await callback.message.delete(); await callback.answer()

@dp.callback_query(F.data.startswith("clan_leave_"))
async def clan_leave(callback: CallbackQuery):
    clan_id = int(callback.data.split("_")[2])
    cur.execute("DELETE FROM clan_members WHERE user_id = ? AND clan_id = ?", (callback.from_user.id, clan_id))
    conn.commit()
    await callback.message.edit_text("✅ Вы вышли из клана", reply_markup=clan_main_kb(callback.from_user.id))
    await callback.answer()

@dp.callback_query(F.data.startswith("clan_deposit_"))
async def clan_deposit_start(callback: CallbackQuery, state: FSMContext):
    clan_id = int(callback.data.split("_")[2])
    await state.update_data(deposit_clan_id=clan_id)
    await state.set_state(GameStates.waiting_clan_deposit)
    await callback.message.edit_text("💰 Введите сумму для пополнения казны клана:")
    await callback.answer()

@dp.message(GameStates.waiting_clan_deposit)
async def clan_deposit_amount(msg: Message, state: FSMContext):
    try: amt = parse_amount(msg.text); assert amt >= 100
    except: await msg.answer("❌ Сумма от 100"); return
    data = await state.get_data(); clan_id = data["deposit_clan_id"]
    if not remove_pocx(msg.from_user.id, amt): await msg.answer("❌ Недостаточно средств"); await state.clear(); return
    cur.execute("UPDATE clans SET balance = balance + ? WHERE id = ?", (amt, clan_id)); conn.commit()
    await state.clear()
    await msg.answer(f"✅ +{fmt_money(amt)} в казну клана", reply_markup=clan_main_kb(msg.from_user.id))

@dp.callback_query(F.data.startswith("clan_members_"))
async def clan_members_list(callback: CallbackQuery):
    clan_id = int(callback.data.split("_")[2])
    members = cur.execute("SELECT cm.user_id, cm.role, u.username FROM clan_members cm JOIN users u ON cm.user_id = u.user_id WHERE cm.clan_id = ?", (clan_id,)).fetchall()
    text = "👥 <b>Участники клана:</b>\n\n"
    for m in members:
        role = "👑" if m[1] == "owner" else ("⭐" if m[1] == "deputy" else "👤")
        text += f"{role} {mention_user(m[0], m[2])} — {m[1]}\n"
    await callback.message.edit_text(text, reply_markup=clan_manage_kb(clan_id, callback.from_user.id))
    await callback.answer()

@dp.callback_query(F.data.startswith("clan_rename_"))
async def clan_rename_start(callback: CallbackQuery, state: FSMContext):
    clan_id = int(callback.data.split("_")[2])
    await state.update_data(rename_clan_id=clan_id)
    await state.set_state(GameStates.waiting_clan_rename)
    await callback.message.edit_text("✏️ Введите новое название клана:")
    await callback.answer()

@dp.message(GameStates.waiting_clan_rename)
async def clan_rename_exec(msg: Message, state: FSMContext):
    name = msg.text.strip()
    data = await state.get_data(); clan_id = data["rename_clan_id"]
    cur.execute("UPDATE clans SET name = ? WHERE id = ?", (name, clan_id)); conn.commit()
    await state.clear()
    await msg.answer(f"✅ Клан переименован в '{name}'!")

@dp.callback_query(F.data.startswith("clan_role_"))
async def clan_role_start(callback: CallbackQuery, state: FSMContext):
    clan_id = int(callback.data.split("_")[2])
    await state.update_data(role_clan_id=clan_id)
    await state.set_state(GameStates.waiting_clan_role)
    await callback.message.edit_text("👑 Введите ID пользователя для назначения заместителем:")
    await callback.answer()

@dp.message(GameStates.waiting_clan_role)
async def clan_role_exec(msg: Message, state: FSMContext):
    try: target_id = int(msg.text)
    except: await msg.answer("❌ ID пользователя"); return
    data = await state.get_data(); clan_id = data["role_clan_id"]
    cur.execute("UPDATE clan_members SET role = 'deputy' WHERE user_id = ? AND clan_id = ?", (target_id, clan_id))
    if cur.rowcount == 0: await msg.answer("❌ Пользователь не в клане")
    else: conn.commit(); await msg.answer("✅ Заместитель назначен!")
    await state.clear()

@dp.callback_query(F.data.startswith("clan_kick_"))
async def clan_kick_start(callback: CallbackQuery, state: FSMContext):
    clan_id = int(callback.data.split("_")[2])
    await state.update_data(kick_clan_id=clan_id)
    await state.set_state(GameStates.waiting_clan_kick)
    await callback.message.edit_text("👢 Введите ID пользователя для исключения:")
    await callback.answer()

@dp.message(GameStates.waiting_clan_kick)
async def clan_kick_exec(msg: Message, state: FSMContext):
    try: target_id = int(msg.text)
    except: await msg.answer("❌ ID"); return
    data = await state.get_data(); clan_id = data["kick_clan_id"]
    cur.execute("DELETE FROM clan_members WHERE user_id = ? AND clan_id = ? AND role != 'owner'", (target_id, clan_id))
    if cur.rowcount: conn.commit(); await msg.answer("✅ Исключён")
    else: await msg.answer("❌ Не найден или владелец")
    await state.clear()

@dp.callback_query(F.data.startswith("clan_ban_"))
async def clan_ban_start(callback: CallbackQuery, state: FSMContext):
    clan_id = int(callback.data.split("_")[2])
    await state.update_data(ban_clan_id=clan_id)
    await state.set_state(GameStates.waiting_clan_ban)
    await callback.message.edit_text("🔨 Введите ID для бана в клане:")
    await callback.answer()

@dp.message(GameStates.waiting_clan_ban)
async def clan_ban_exec(msg: Message, state: FSMContext):
    try: target_id = int(msg.text)
    except: await msg.answer("❌ ID"); return
    data = await state.get_data(); clan_id = data["ban_clan_id"]
    cur.execute("INSERT OR REPLACE INTO clan_bans (user_id, clan_id, banned_by) VALUES (?, ?, ?)", (target_id, clan_id, msg.from_user.id))
    cur.execute("DELETE FROM clan_members WHERE user_id = ? AND clan_id = ? AND role != 'owner'", (target_id, clan_id))
    conn.commit(); await state.clear()
    await msg.answer("✅ Забанен в клане!")

@dp.callback_query(F.data.startswith("clan_unban_"))
async def clan_unban_start(callback: CallbackQuery, state: FSMContext):
    clan_id = int(callback.data.split("_")[2])
    await state.update_data(unban_clan_id=clan_id)
    await state.set_state(GameStates.waiting_clan_unban)
    await callback.message.edit_text("🔓 Введите ID для разбана:")
    await callback.answer()

@dp.message(GameStates.waiting_clan_unban)
async def clan_unban_exec(msg: Message, state: FSMContext):
    try: target_id = int(msg.text)
    except: await msg.answer("❌ ID"); return
    data = await state.get_data(); clan_id = data["unban_clan_id"]
    cur.execute("DELETE FROM clan_bans WHERE user_id = ? AND clan_id = ?", (target_id, clan_id)); conn.commit()
    await state.clear(); await msg.answer("✅ Разбанен!")

@dp.callback_query(F.data.startswith("clan_invite_"))
async def clan_invite_start(callback: CallbackQuery, state: FSMContext):
    clan_id = int(callback.data.split("_")[2])
    await state.update_data(invite_clan_id=clan_id)
    await state.set_state(GameStates.waiting_clan_invite)
    await callback.message.edit_text("🔗 Введите ID или @username для приглашения:")
    await callback.answer()

@dp.message(GameStates.waiting_clan_invite)
async def clan_invite_exec(msg: Message, state: FSMContext):
    target = resolve_user_id(msg.text)
    if target is None: await msg.answer("❌ Не найден"); return
    data = await state.get_data(); clan_id = data["invite_clan_id"]
    cur.execute("INSERT OR IGNORE INTO clan_invites (clan_id, invited_by, invited_user) VALUES (?, ?, ?)", (clan_id, msg.from_user.id, target))
    conn.commit()
    clan_name = cur.execute("SELECT name FROM clans WHERE id = ?", (clan_id,)).fetchone()[0]
    try: await bot.send_message(target, f"🔗 Вас пригласили в клан '{clan_name}'!\nИспользуйте <code>клан вступить {clan_name}</code>")
    except: pass
    await state.clear(); await msg.answer(f"✅ Приглашение отправлено!")

@dp.callback_query(F.data.startswith("clan_delete_"))
async def clan_delete(callback: CallbackQuery):
    clan_id = int(callback.data.split("_")[2])
    cur.execute("DELETE FROM clan_members WHERE clan_id = ?", (clan_id,))
    cur.execute("DELETE FROM clan_bans WHERE clan_id = ?", (clan_id,))
    cur.execute("DELETE FROM clan_invites WHERE clan_id = ?", (clan_id,))
    cur.execute("DELETE FROM clans WHERE id = ?", (clan_id,))
    conn.commit()
    await callback.message.edit_text("🗑 Клан расформирован", reply_markup=clan_main_kb(callback.from_user.id))
    await callback.answer()

@dp.message(lambda m: m.text and m.text.lower().startswith("клан вступить"))
async def clan_join_text(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 3: await msg.reply("❌ <code>клан вступить [название]</code>"); return
    name = parts[2].strip()
    clan = cur.execute("SELECT id FROM clans WHERE name = ?", (name,)).fetchone()
    if not clan: await msg.reply("❌ Не найден"); return
    if cur.execute("SELECT 1 FROM clan_bans WHERE user_id = ? AND clan_id = ?", (msg.from_user.id, clan[0])).fetchone():
        await msg.reply("❌ Вы забанены в этом клане"); return
    cur.execute("INSERT OR REPLACE INTO clan_members (user_id, clan_id) VALUES (?, ?)", (msg.from_user.id, clan[0]))
    conn.commit(); await msg.reply(f"✅ Вы вступили в '{name}'!")

# ==================== КАЗНА ЧАТА ====================
@dp.message(F.text.in_({"🏦 Казна", "казна"}))
async def treasury_cmd(msg: Message):
    if msg.chat.type == ChatType.PRIVATE:
        await msg.answer("❌ Команда работает только в чатах!")
        return
    treasury = get_chat_treasury(msg.chat.id)
    if not treasury:
        await msg.answer("🏦 <b>Казна чата не активирована!</b>\nВладелец чата может активировать её через админ-панель бота.")
        return
    if msg.from_user.id != treasury["owner_id"]:
        await msg.answer(
            f"🏦 <b>Казна чата</b>\n"
            f"💰 Баланс: {fmt_money(treasury['balance'])}\n"
            f"🎁 Награда за приглашение: {treasury['reward_per_invite']} POCX"
        )
        return
    # Владелец
    await msg.answer(
        f"🏦 <b>Управление казной</b>\n"
        f"💰 Баланс: {fmt_money(treasury['balance'])}\n"
        f"🎁 Награда: {treasury['reward_per_invite']} POCX\n\n"
        "<code>казна пополнить [сумма]</code>\n"
        "<code>казна награда [сумма]</code>"
    )

@dp.message(lambda m: m.text and m.text.lower().startswith("казна пополнить"))
async def treasury_add(msg: Message):
    if msg.chat.type == ChatType.PRIVATE: return
    parts = msg.text.split()
    if len(parts) < 3: await msg.reply("❌ <code>казна пополнить 1000</code>"); return
    try: amt = parse_amount(parts[2])
    except: await msg.reply("❌ Сумма"); return
    treasury = get_chat_treasury(msg.chat.id)
    if not treasury or msg.from_user.id != treasury["owner_id"]:
        await msg.reply("❌ Только владелец казны может пополнять"); return
    if not remove_pocx(msg.from_user.id, amt): await msg.reply("❌ Недостаточно средств"); return
    add_to_chat_treasury(msg.chat.id, amt)
    await msg.reply(f"✅ +{fmt_money(amt)} в казну чата")

# ==================== ИГРЫ ====================

# --- РУЛЕТКА ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("рул", "рулетка")))
async def roulette_game(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    if is_banned(msg.from_user.id): await msg.reply("❌ Вы забанены!"); return
    if is_muted_games(msg.from_user.id): await msg.reply("🔇 Вы в муте игр!"); return
    u = get_user(msg.from_user.id)
    parts = msg.text.split()
    if len(parts) < 3: await msg.reply("❌ <code>рул [ставка] [красное/черное/чет/нечет/зеро]</code>"); return
    try: bet = parse_amount(parts[1], u["balance"]); assert bet >= MIN_BET and bet <= u["balance"]
    except: await msg.reply(f"❌ Ставка {MIN_BET}-{u['balance']}"); return
    choice = parts[2].lower()
    choices = {"красное":"red","черное":"black","чет":"even","нечет":"odd","зеро":"zero"}
    if choice not in choices: await msg.reply("❌ красное/черное/чет/нечет/зеро"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    
    if random.random() < 0.027: number = 0
    else: number = random.randint(1, 36)
    
    color = "green" if number == 0 else ("red" if number in RED_NUMS else "black")
    parity = "zero" if number == 0 else ("even" if number % 2 == 0 else "odd")
    
    win = False; mult = 0
    if choices[choice] == "red" and color == "red": win, mult = True, 2.0
    elif choices[choice] == "black" and color == "black": win, mult = True, 2.0
    elif choices[choice] == "even" and parity == "even": win, mult = True, 2.0
    elif choices[choice] == "odd" and parity == "odd": win, mult = True, 2.0
    elif choices[choice] == "zero" and number == 0: win, mult = True, 36.0
    
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(msg.from_user.id, payout)
    record_game(msg.from_user.id, "roulette", bet, mult, payout, "win" if win else "loss", {"number": number, "color": color})
    
    color_emoji = {"red":"🔴","black":"⚫","green":"🟢"}[color]
    await msg.reply(
        f"🎡 <b>Рулетка: {number} {color_emoji}</b>\n"
        f"💰 Ставка: {fmt_money(bet)}\n"
        f"{'✅ Выигрыш: '+fmt_money(payout) if win else '❌ Проигрыш: '+fmt_money(bet)}\n"
        f"💳 Баланс: {fmt_money(get_user(msg.from_user.id)['balance'])}"
    )

# --- КРАШ ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("краш", "crash")))
async def crash_game(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    if is_banned(msg.from_user.id): await msg.reply("❌ Вы забанены!"); return
    if is_muted_games(msg.from_user.id): await msg.reply("🔇 Вы в муте игр!"); return
    u = get_user(msg.from_user.id)
    parts = msg.text.split()
    if len(parts) < 3: await msg.reply("❌ <code>краш [ставка] [множ]</code>"); return
    try: bet = parse_amount(parts[1], u["balance"]); target = float(parts[2].replace(",",".")); assert bet >= MIN_BET and target >= 1.01 and target <= 10
    except: await msg.reply("❌ Ставка, множитель 1.01-10"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    
    r = random.random()
    if r < 0.7: crash_point = round(random.uniform(1.0, 3.0), 2)
    elif r < 0.9: crash_point = round(random.uniform(3.0, 5.0), 2)
    else: crash_point = round(random.uniform(5.0, 10.0), 2)
    
    win = crash_point >= target
    payout = int(bet * target) if win else 0
    if payout: add_pocx(msg.from_user.id, payout)
    record_game(msg.from_user.id, "crash", bet, target, payout, "win" if win else "loss", {"crash": crash_point})
    
    await msg.reply(
        f"📈 <b>Краш: x{crash_point}</b> (цель x{target})\n"
        f"{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n"
        f"💰 {fmt_money(get_user(msg.from_user.id)['balance'])}"
    )

# --- КУБИК ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("кубик", "куб")))
async def cube_game(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    if is_banned(msg.from_user.id): await msg.reply("❌ Вы забанены!"); return
    if is_muted_games(msg.from_user.id): await msg.reply("🔇 Вы в муте игр!"); return
    u = get_user(msg.from_user.id)
    parts = msg.text.split()
    if len(parts) < 3: await msg.reply("❌ <code>кубик [ставка] [1-6/чет/нечет/б/м]</code>"); return
    try: bet = parse_amount(parts[1], u["balance"]); assert bet >= MIN_BET and bet <= u["balance"]
    except: await msg.reply(f"❌ Ставка"); return
    guess = parts[2].lower()
    if guess not in ("1","2","3","4","5","6","чет","нечет","б","м"): await msg.reply("❌ 1-6, чет, нечет, б, м"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    
    dice = await msg.answer_dice(emoji="🎲")
    number = dice.dice.value
    
    win = False; mult = 0
    if guess == str(number): win, mult = True, 3.0
    elif guess == "чет" and number % 2 == 0: win, mult = True, 1.8
    elif guess == "нечет" and number % 2 == 1: win, mult = True, 1.8
    elif guess == "б" and number >= 4: win, mult = True, 1.8
    elif guess == "м" and number <= 3: win, mult = True, 1.8
    
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(msg.from_user.id, payout)
    record_game(msg.from_user.id, "cube", bet, mult, payout, "win" if win else "loss", {"number": number})
    
    await msg.reply(f"🎲 <b>Кубик: {number}</b>\n{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n💰 {fmt_money(get_user(msg.from_user.id)['balance'])}")

# --- КОСТИ ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("кости", "кос")))
async def dice_game(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    if is_banned(msg.from_user.id): await msg.reply("❌ Вы забанены!"); return
    if is_muted_games(msg.from_user.id): await msg.reply("🔇 Вы в муте игр!"); return
    u = get_user(msg.from_user.id)
    parts = msg.text.split()
    if len(parts) < 3: await msg.reply("❌ <code>кости [ставка] [м/б/равно]</code>"); return
    try: bet = parse_amount(parts[1], u["balance"]); assert bet >= MIN_BET and bet <= u["balance"]
    except: await msg.reply(f"❌ Ставка"); return
    choice = parts[2].lower()
    if choice not in ("м","б","равно"): await msg.reply("❌ м/б/равно"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    
    d1 = await msg.answer_dice(emoji="🎲"); d2 = await msg.answer_dice(emoji="🎲")
    total = d1.dice.value + d2.dice.value
    
    win = False; mult = 0
    if choice == "м" and total < 7: win, mult = True, 2.0
    elif choice == "б" and total > 7: win, mult = True, 2.0
    elif choice == "равно" and total == 7: win, mult = True, 4.5
    
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(msg.from_user.id, payout)
    record_game(msg.from_user.id, "dice", bet, mult, payout, "win" if win else "loss", {"d1":d1.dice.value,"d2":d2.dice.value,"total":total})
    
    await msg.reply(f"🎯 <b>Кости: {d1.dice.value}+{d2.dice.value}={total}</b>\n{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n💰 {fmt_money(get_user(msg.from_user.id)['balance'])}")

# --- ФУТБОЛ ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("футбол", "фут")))
async def football_game(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    if is_banned(msg.from_user.id): await msg.reply("❌ Вы забанены!"); return
    if is_muted_games(msg.from_user.id): await msg.reply("🔇 Вы в муте игр!"); return
    u = get_user(msg.from_user.id)
    parts = msg.text.split()
    if len(parts) < 2: await msg.reply("❌ <code>футбол [ставка] [гол/мимо]</code>"); return
    try: bet = parse_amount(parts[1], u["balance"]); assert bet >= MIN_BET and bet <= u["balance"]
    except: await msg.reply(f"❌ Ставка"); return
    choice = parts[2].lower() if len(parts) > 2 else None
    if choice and choice not in ("гол","мимо"): await msg.reply("❌ гол/мимо"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    
    dice = await msg.answer_dice(emoji="⚽"); value = dice.dice.value
    res = "гол" if value >= 4 else "мимо"
    
    if choice:
        win = (choice == res); mult = FOOTBALL_MULT[res]
        payout = int(bet * mult) if win else 0
        if payout: add_pocx(msg.from_user.id, payout)
        record_game(msg.from_user.id, "football", bet, mult, payout, "win" if win else "loss", {"value": value, "result": res, "choice": choice})
        await msg.reply(f"⚽ <b>Футбол: {res.upper()}</b>\n🎯 Выбор: {choice}\n{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n💰 {fmt_money(get_user(msg.from_user.id)['balance'])}")

# --- БАСКЕТБОЛ ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("баскет", "баск")))
async def basketball_game(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    if is_banned(msg.from_user.id): await msg.reply("❌ Вы забанены!"); return
    if is_muted_games(msg.from_user.id): await msg.reply("🔇 Вы в муте игр!"); return
    u = get_user(msg.from_user.id)
    parts = msg.text.split()
    if len(parts) < 2: await msg.reply("❌ <code>баскет [ставка]</code>"); return
    try: bet = parse_amount(parts[1], u["balance"]); assert bet >= MIN_BET and bet <= u["balance"]
    except: await msg.reply(f"❌ Ставка"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    
    dice = await msg.answer_dice(emoji="🏀"); value = dice.dice.value
    win = value >= 4; mult = 2.0 if win else 0
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(msg.from_user.id, payout)
    record_game(msg.from_user.id, "basket", bet, mult, payout, "win" if win else "loss", {"value": value})
    
    await msg.reply(f"🏀 <b>Баскет: {'Точный бросок!' if win else 'Промах'}</b>\n{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n💰 {fmt_money(get_user(msg.from_user.id)['balance'])}")

# --- ДАРТС ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("дартс", "дс")))
async def darts_game(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    if is_banned(msg.from_user.id): await msg.reply("❌ Вы забанены!"); return
    if is_muted_games(msg.from_user.id): await msg.reply("🔇 Вы в муте игр!"); return
    u = get_user(msg.from_user.id)
    parts = msg.text.split()
    if len(parts) < 3: await msg.reply("❌ <code>дартс [ставка] [центр/край/мимо]</code>"); return
    try: bet = parse_amount(parts[1], u["balance"]); assert bet >= MIN_BET and bet <= u["balance"]
    except: await msg.reply(f"❌ Ставка"); return
    choice = parts[2].lower()
    if choice not in ("центр","край","мимо"): await msg.reply("❌ центр/край/мимо"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    
    dice = await msg.answer_dice(emoji="🎯"); value = dice.dice.value
    if value in (1, 2): actual = "мимо"
    elif value in (3, 4): actual = "край"
    else: actual = "центр"
    
    win = (choice == actual); mult = DARTS_MULT[actual]
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(msg.from_user.id, payout)
    record_game(msg.from_user.id, "darts", bet, mult, payout, "win" if win else "loss", {"value": value, "actual": actual, "choice": choice})
    
    result_emoji = {"центр":"🎯","край":"🔵","мимо":"⚪"}
    await msg.reply(f"🎯 <b>Дартс: {result_emoji[actual]} {actual.upper()}</b>\n🎯 Прогноз: {choice}\n{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n💰 {fmt_money(get_user(msg.from_user.id)['balance'])}")

# --- СЛОТЫ ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("слоты", "слот")))
async def slots_game(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    if is_banned(msg.from_user.id): await msg.reply("❌ Вы забанены!"); return
    if is_muted_games(msg.from_user.id): await msg.reply("🔇 Вы в муте игр!"); return
    u = get_user(msg.from_user.id)
    parts = msg.text.split()
    if len(parts) < 2: await msg.reply("❌ <code>слоты [ставка]</code>"); return
    try: bet = parse_amount(parts[1], u["balance"]); assert bet >= MIN_BET and bet <= u["balance"]
    except: await msg.reply(f"❌ Ставка"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    
    emojis = ["🍒","🍋","🍊","⭐","💎","7️⃣"]
    r = random.random()
    if r < 0.02:
        symbol = "7️⃣" if random.random() < 0.1 else random.choice(emojis[:3])
        result = [symbol, symbol, symbol]
        mult = 8.0 if symbol == "7️⃣" else 4.0; win = True
    elif r < 0.17:
        symbol = random.choice(emojis[:4])
        result = [symbol, symbol, random.choice([e for e in emojis if e != symbol])]
        mult, win = 1.4, True
    else:
        result = [random.choice(emojis) for _ in range(3)]
        mult, win = 0, False
    
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(msg.from_user.id, payout)
    record_game(msg.from_user.id, "slots", bet, mult, payout, "win" if win else "loss", {"slots": result})
    
    await msg.reply(f"🎰 <b>Слоты: {' | '.join(result)}</b>\n{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n💰 {fmt_money(get_user(msg.from_user.id)['balance'])}")

# --- МОНЕТКА ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("монетка", "монета")))
async def coinflip_game(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    if is_banned(msg.from_user.id): await msg.reply("❌ Вы забанены!"); return
    if is_muted_games(msg.from_user.id): await msg.reply("🔇 Вы в муте игр!"); return
    u = get_user(msg.from_user.id)
    parts = msg.text.split()
    if len(parts) < 3: await msg.reply("❌ <code>монетка [ставка] [орел/решка]</code>"); return
    try: bet = parse_amount(parts[1], u["balance"]); assert bet >= MIN_BET and bet <= u["balance"]
    except: await msg.reply(f"❌ Ставка"); return
    choice = parts[2].lower()
    if choice not in ("орел","орёл","решка"): await msg.reply("❌ орел/решка"); return
    choice = "орел" if choice in ("орел","орёл") else "решка"
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    
    result = random.choice(["орел","решка"])
    win = (choice == result); mult = 1.9 if win else 0
    payout = int(bet * mult) if win else 0
    if payout: add_pocx(msg.from_user.id, payout)
    record_game(msg.from_user.id, "coinflip", bet, mult, payout, "win" if win else "loss", {"choice": choice, "result": result})
    
    emoji = "🦅" if result == "орел" else "👑"
    await msg.reply(f"🪙 <b>Монетка: {emoji} {result}</b>\n{'✅ +'+fmt_money(payout) if win else '❌ -'+fmt_money(bet)}\n💰 {fmt_money(get_user(msg.from_user.id)['balance'])}")

# --- КНБ ---
@dp.message(lambda m: m.text and m.text.lower().startswith(("кнб", "цут")))
async def rps_game(msg: Message):
    if not check_cooldown(msg.from_user.id): return
    if is_banned(msg.from_user.id): await msg.reply("❌ Вы забанены!"); return
    if is_muted_games(msg.from_user.id): await msg.reply("🔇 Вы в муте игр!"); return
    u = get_user(msg.from_user.id)
    parts = msg.text.split()
    if len(parts) < 3: await msg.reply("❌ <code>кнб [ставка] [камень/ножницы/бумага]</code>"); return
    try: bet = parse_amount(parts[1], u["balance"]); assert bet >= MIN_BET and bet <= u["balance"]
    except: await msg.reply(f"❌ Ставка"); return
    choice = parts[2].lower()
    choices = {"камень":"🗿","ножницы":"✂️","бумага":"📄"}
    if choice not in choices: await msg.reply("❌ камень/ножницы/бумага"); return
    if not remove_pocx(msg.from_user.id, bet): await msg.reply("❌ Недостаточно средств"); return
    
    bot_choice = random.choice(list(choices.keys()))
    if choice == bot_choice: outcome, mult, payout = "push", 1.0, bet
    elif (choice == "камень" and bot_choice == "ножницы") or (choice == "ножницы" and bot_choice == "бумага") or (choice == "бумага" and bot_choice == "камень"):
        outcome, mult, payout = "win", 1.8, int(bet * 1.8)
    else: outcome, mult, payout = "loss", 0, 0
    if payout: add_pocx(msg.from_user.id, payout)
    record_game(msg.from_user.id, "rps", bet, mult, payout, outcome, {"player": choice, "bot": bot_choice})
    
    await msg.reply(f"✂️ <b>КНБ</b>\nТы: {choices[choice]} | Бот: {choices[bot_choice]}\n{'Ничья' if outcome=='push' else ('Победа!' if outcome=='win' else 'Поражение')}\n{'✅ +'+fmt_money(payout) if outcome!='loss' else '❌ -'+fmt_money(bet)}\n💰 {fmt_money(get_user(msg.from_user.id)['balance'])}")

# ==================== ЗАПУСК ====================
async def main():
    print("🤖 POCX Casino запущен!")
    print("✅ Игры в чатах и ЛС, кулдаун 5с, банк, кланы, рефералы, казна")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
