import asyncio
import random
import sqlite3
import hashlib
import time
import json
import os
import html
import string
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    CallbackQuery, Message, LabeledPrice, PreCheckoutQuery,
    ChatMemberUpdated
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode

# ==================== КОНФИГУРАЦИЯ ====================
TOKEN = "8134237711:AAH5M0JJULkrl0yyOdvfCtIswRPqRtt_3hg"
ADMIN_IDS = [8478884644, 8293927811]
STARS_TO_POCX = 2500

MIN_BET = 100
MAX_BET = 100_000_000

DAILY_BONUS_MIN = 100
DAILY_BONUS_MAX = 2000
WELCOME_BONUS = 1000
REF_REWARD = 5000
REF_REFERRAL_BONUS = 500

BANK_TERMS = {
    7: 0.01,
    14: 0.02,
    30: 0.05,
}

REQUIRED_CHANNELS = [
    {"chat_id": "@POCXCHANEL", "link": "https://t.me/POCXCHANEL", "name": "📢 POCX Канал"},
    {"chat_id": "@POCXCHAT", "link": "https://t.me/POCXCHAT", "name": "💬 POCX Чат"},
]

VIP_LEVELS = [
    ("🥉 Bronze", 0, 0),
    ("🥈 Silver", 100000, 1),
    ("🥇 Gold", 500000, 2),
    ("💎 Platinum", 2000000, 3),
    ("👑 Diamond", 10000000, 5),
]

TOWER_MULTIPLIERS = [1.20, 1.48, 1.86, 2.35, 2.95, 3.75, 4.85, 6.15]
GOLD_MULTIPLIERS = [1.15, 1.35, 1.62, 2.0, 2.55, 3.25, 4.2]
DIAMOND_MULTIPLIERS = [1.12, 1.28, 1.48, 1.72, 2.02, 2.4, 2.92, 3.6]
RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
FOOTBALL_MULTIPLIERS = {"gol": 1.6, "mimo": 2.2}

bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# --- Проверка чата ---
def is_private_chat(message_or_callback) -> bool:
    if hasattr(message_or_callback, 'message') and message_or_callback.message:
        return message_or_callback.message.chat.type == "private"
    if hasattr(message_or_callback, 'chat'):
        return message_or_callback.chat.type == "private"
    return False

def is_group_chat(message_or_callback) -> bool:
    return not is_private_chat(message_or_callback)

# ==================== БАЗА ДАННЫХ ====================
conn = sqlite3.connect("pocx_bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 5000,
    total_wagered INTEGER DEFAULT 0, total_won INTEGER DEFAULT 0,
    total_lost INTEGER DEFAULT 0, referral_code TEXT UNIQUE,
    referrer_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_daily_bonus TIMESTAMP, welcome_bonus_claimed BOOLEAN DEFAULT 0,
    daily_streak INTEGER DEFAULT 0, last_game_time INTEGER DEFAULT 0,
    custom_status TEXT DEFAULT NULL, games_played_today INTEGER DEFAULT 0,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_muted BOOLEAN DEFAULT 0,
    mute_until INTEGER DEFAULT 0, total_donated INTEGER DEFAULT 0
)""")

cursor.execute("""CREATE TABLE IF NOT EXISTS game_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, game_type TEXT,
    bet_amount INTEGER, multiplier REAL, win_amount INTEGER, result TEXT,
    details TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""")

cursor.execute("""CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER,
    referred_id INTEGER, earned_amount INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""")

cursor.execute("""CREATE TABLE IF NOT EXISTS banned_users (
    user_id INTEGER PRIMARY KEY, banned_at INTEGER, reason TEXT,
    banned_until INTEGER DEFAULT 0
)""")

cursor.execute("""CREATE TABLE IF NOT EXISTS promocodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE,
    bonus_amount INTEGER, max_uses INTEGER, used_count INTEGER DEFAULT 0,
    expires_at TIMESTAMP, is_active BOOLEAN DEFAULT 1
)""")

cursor.execute("""CREATE TABLE IF NOT EXISTS used_promocodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, code TEXT,
    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""")

cursor.execute("""CREATE TABLE IF NOT EXISTS checks (
    code TEXT PRIMARY KEY, creator_id INTEGER, per_user INTEGER,
    remaining INTEGER, used TEXT, password TEXT
)""")

cursor.execute("""CREATE TABLE IF NOT EXISTS bank_deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, principal INTEGER,
    rate REAL, term_days INTEGER, opened_at INTEGER,
    status TEXT DEFAULT 'active', closed_at INTEGER
)""")

cursor.execute("""CREATE TABLE IF NOT EXISTS chat_treasury (
    chat_id INTEGER PRIMARY KEY, owner_id INTEGER, balance INTEGER DEFAULT 0,
    reward_per_invite INTEGER DEFAULT 100, is_active BOOLEAN DEFAULT 0,
    purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""")

cursor.execute("""CREATE TABLE IF NOT EXISTS treasury_rewards (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER,
    invited_by INTEGER, rewarded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chat_id, user_id)
)""")

cursor.execute("""CREATE TABLE IF NOT EXISTS admin_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER,
    action TEXT, target_id INTEGER, details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""")

conn.commit()

# ==================== FSM ====================
class GameStates(StatesGroup):
    tower_bet = State()
    tower_choice = State()
    gold_bet = State()
    gold_choice = State()
    diamond_bet = State()
    diamond_choice = State()
    mines_bet = State()
    mines_mines = State()
    mines_choice = State()
    ochko_confirm = State()
    ochko_game = State()
    roulette_bet = State()
    roulette_choice = State()
    crash_bet = State()
    crash_target = State()
    cube_bet = State()
    cube_guess = State()
    dice_bet = State()
    dice_guess = State()
    football_bet = State()
    basket_bet = State()
    admin_give = State()
    admin_take = State()
    admin_ban = State()
    admin_unban = State()
    admin_broadcast = State()
    admin_promo_code = State()
    admin_promo_reward = State()
    admin_promo_uses = State()
    admin_status = State()
    admin_mute = State()
    admin_msg = State()
    admin_search = State()
    admin_balance_set = State()
    promo_code = State()
    bank_deposit_amount = State()
    bank_deposit_term = State()
    treasury_reward_set = State()
    treasury_add = State()
    treasury_withdraw = State()
    donate_custom = State()
    check_create_amount = State()
    check_create_count = State()
    check_claim = State()
    transfer_amount = State()

# ==================== ИГРОВЫЕ СЕССИИ ====================
TOWER_GAMES: Dict[int, Dict[str, Any]] = {}
GOLD_GAMES: Dict[int, Dict[str, Any]] = {}
DIAMOND_GAMES: Dict[int, Dict[str, Any]] = {}
MINES_GAMES: Dict[int, Dict[str, Any]] = {}
OCHKO_GAMES: Dict[int, Dict[str, Any]] = {}

# ==================== ХЕЛПЕРЫ ====================
def parse_amount(text: str) -> int:
    text = text.lower().strip()
    mults = {'ккк': 1_000_000_000, 'кк': 1_000_000, 'к': 1_000,
             'kkk': 1_000_000_000, 'kk': 1_000_000, 'k': 1_000,
             'm': 1_000_000, 'b': 1_000_000_000}
    for suf, m in mults.items():
        if text.endswith(suf):
            num = text[:-len(suf)] or '1'
            try: return int(float(num) * m)
            except: return 0
    try: return int(text)
    except: return 0

def fmt_money(value: int) -> str:
    if value >= 1_000_000_000: return f"{value/1_000_000_000:.1f}ккк POCX"
    if value >= 1_000_000: return f"{value/1_000_000:.1f}кк POCX"
    if value >= 1_000: return f"{value/1_000:.1f}к POCX"
    return f"{value} POCX"

def add_pocx(user_id: int, amount: int):
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    cursor.execute("UPDATE users SET total_donated = total_donated + ? WHERE user_id = ?", (amount, user_id))
    if cursor.rowcount == 0:
        cursor.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, 5000))
    conn.commit()

def remove_pocx(user_id: int, amount: int) -> bool:
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    if not res or res[0] < amount: return False
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    return True

def get_user(user_id: int) -> dict:
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row: return None
    return {
        "user_id": row[0], "username": row[1], "balance": row[2],
        "total_wagered": row[3], "total_won": row[4], "total_lost": row[5],
        "referral_code": row[6], "referrer_id": row[7],
        "daily_streak": row[11] or 0, "welcome_bonus_claimed": row[10],
        "custom_status": row[13], "games_played_today": row[14] or 0,
        "last_activity": row[15], "is_muted": row[16],
        "mute_until": row[17], "total_donated": row[18] or 0,
    }

def get_vip(wagered: int) -> tuple:
    for lvl in reversed(VIP_LEVELS):
        if wagered >= lvl[1]: return lvl[0], lvl[2]
    return VIP_LEVELS[0][0], 0

def is_banned(user_id: int) -> bool:
    cursor.execute("SELECT banned_until FROM banned_users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row: return False
    if row[0] > 0 and int(time.time()) > row[0]:
        cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
        conn.commit()
        return False
    return True

def is_muted(user_id: int) -> bool:
    user = get_user(user_id)
    if not user or not user["is_muted"]: return False
    if user["mute_until"] > 0 and int(time.time()) > user["mute_until"]:
        cursor.execute("UPDATE users SET is_muted = 0, mute_until = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        return False
    return True

def ban_user(user_id: int, reason: str = "", duration_hours: int = 0):
    until = int(time.time()) + duration_hours * 3600 if duration_hours > 0 else 0
    cursor.execute("INSERT OR REPLACE INTO banned_users (user_id, banned_at, reason, banned_until) VALUES (?, ?, ?, ?)",
                   (user_id, int(time.time()), reason, until))
    conn.commit()

def mute_user(user_id: int, hours: int = 24):
    until = int(time.time()) + hours * 3600
    cursor.execute("UPDATE users SET is_muted = 1, mute_until = ? WHERE user_id = ?", (until, user_id))
    conn.commit()

def unmute_user(user_id: int):
    cursor.execute("UPDATE users SET is_muted = 0, mute_until = 0 WHERE user_id = ?", (user_id,))
    conn.commit()

def unban_user(user_id: int):
    cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
    conn.commit()

def admin_log(admin_id: int, action: str, target_id: int = 0, details: str = ""):
    cursor.execute("INSERT INTO admin_logs (admin_id, action, target_id, details) VALUES (?, ?, ?, ?)",
                   (admin_id, action, target_id, details))
    conn.commit()

def record_game(user_id: int, game_type: str, bet: int, mult: float, win: int, result: str, details: dict):
    cursor.execute("""UPDATE users SET total_wagered = total_wagered + ?,
        total_won = total_won + ?, total_lost = total_lost + ?,
        games_played_today = games_played_today + 1, last_activity = CURRENT_TIMESTAMP
        WHERE user_id = ?""",
        (bet, win if result == "win" else 0, bet if result == "loss" else 0, user_id))
    cursor.execute("INSERT INTO game_history (user_id, game_type, bet_amount, multiplier, win_amount, result, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (user_id, game_type, bet, mult, win, result, json.dumps(details)))
    conn.commit()

def generate_check_code() -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

# --- Банк ---
def add_deposit(user_id: int, amount: int, term_days: int) -> tuple:
    rate = BANK_TERMS.get(term_days)
    if rate is None: return False, "Неверный срок депозита."
    if not remove_pocx(user_id, amount): return False, "Недостаточно средств."
    cursor.execute("INSERT INTO bank_deposits (user_id, principal, rate, term_days, opened_at, status) VALUES (?, ?, ?, ?, ?, 'active')",
                   (user_id, amount, rate, term_days, int(time.time())))
    conn.commit()
    return True, f"✅ Депозит открыт! Сумма: {fmt_money(amount)}, срок: {term_days}д, ставка: {int(rate*100)}%"

def list_user_deposits(user_id: int) -> list:
    cursor.execute("SELECT * FROM bank_deposits WHERE user_id = ? AND status = 'active' ORDER BY id DESC", (user_id,))
    return cursor.fetchall()

def check_and_withdraw_deposits(user_id: int) -> tuple:
    now = int(time.time())
    cursor.execute("SELECT id, principal, rate, term_days, opened_at FROM bank_deposits WHERE user_id = ? AND status = 'active'", (user_id,))
    deposits = cursor.fetchall()
    total_payout = 0
    closed = 0
    for dep in deposits:
        dep_id, principal, rate, term_days, opened_at = dep
        if now - opened_at >= term_days * 86400:
            payout = int(principal * (1 + rate))
            add_pocx(user_id, payout)
            cursor.execute("UPDATE bank_deposits SET status = 'closed', closed_at = ? WHERE id = ?", (now, dep_id))
            total_payout += payout
            closed += 1
    conn.commit()
    return closed, total_payout

# --- Казна ---
def get_chat_treasury(chat_id: int) -> dict:
    cursor.execute("SELECT * FROM chat_treasury WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    if not row: return None
    return {"chat_id": row[0], "owner_id": row[1], "balance": row[2], "reward_per_invite": row[3], "is_active": row[4]}

def add_to_chat_treasury(chat_id: int, amount: int):
    cursor.execute("UPDATE chat_treasury SET balance = balance + ? WHERE chat_id = ?", (amount, chat_id))
    conn.commit()

def remove_from_chat_treasury(chat_id: int, amount: int) -> bool:
    treasury = get_chat_treasury(chat_id)
    if not treasury or treasury["balance"] < amount: return False
    cursor.execute("UPDATE chat_treasury SET balance = balance - ? WHERE chat_id = ?", (amount, chat_id))
    conn.commit()
    return True

# ==================== ПРОВЕРКА ПОДПИСКИ ====================
async def check_subscription(user_id: int) -> tuple:
    not_subscribed = []
    for ch in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=ch["chat_id"], user_id=user_id)
            if member.status in ["left", "kicked"]: not_subscribed.append(ch)
        except: not_subscribed.append(ch)
    return len(not_subscribed) == 0, not_subscribed

def subscription_keyboard(not_subscribed: list) -> InlineKeyboardMarkup:
    kb = []
    for ch in not_subscribed:
        kb.append([InlineKeyboardButton(text=f"Подписаться на {ch['name']}", url=ch["link"])])
    kb.append([InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ==================== КЛАВИАТУРЫ ====================
def main_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎮 Игры"), KeyboardButton(text="💰 Финансы")],
        [KeyboardButton(text="🏆 Топ"), KeyboardButton(text="🎁 Бонусы")],
        [KeyboardButton(text="👥 Рефералы"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🏦 Банк")],
        [KeyboardButton(text="👑 Админ"), KeyboardButton(text="🏦 Казна")]
    ], resize_keyboard=True)

def games_menu():
    return InlineKeyboardMarkup(inline_row_width=2, inline_keyboard=[
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
         InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_row_width=2, inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
         InlineKeyboardButton(text="💰 Выдать", callback_data="admin_give")],
        [InlineKeyboardButton(text="➖ Забрать", callback_data="admin_take"),
         InlineKeyboardButton(text="💳 Установить баланс", callback_data="admin_balance_set")],
        [InlineKeyboardButton(text="🔨 Бан", callback_data="admin_ban"),
         InlineKeyboardButton(text="🔓 Разбан", callback_data="admin_unban")],
        [InlineKeyboardButton(text="🔇 Мут", callback_data="admin_mute"),
         InlineKeyboardButton(text="🔊 Размут", callback_data="admin_unmute")],
        [InlineKeyboardButton(text="🎟 Промокод", callback_data="admin_promo"),
         InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="💬 Сообщение", callback_data="admin_msg"),
         InlineKeyboardButton(text="👑 Статус", callback_data="admin_status")],
        [InlineKeyboardButton(text="🔍 Поиск", callback_data="admin_search"),
         InlineKeyboardButton(text="🎁 Масс-бонус", callback_data="admin_mass_bonus")],
        [InlineKeyboardButton(text="📋 Промокоды", callback_data="admin_promo_list"),
         InlineKeyboardButton(text="👥 Топ-100", callback_data="admin_top100")],
        [InlineKeyboardButton(text="📈 Аналитика", callback_data="admin_analytics"),
         InlineKeyboardButton(text="🧹 Очистка", callback_data="admin_cleanup")],
        [InlineKeyboardButton(text="🏦 Казна", callback_data="admin_treasury"),
         InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])

def treasury_admin_menu():
    return InlineKeyboardMarkup(inline_row_width=2, inline_keyboard=[
        [InlineKeyboardButton(text="➕ Пополнить", callback_data="treasury_add"),
         InlineKeyboardButton(text="💸 Вывести", callback_data="treasury_withdraw")],
        [InlineKeyboardButton(text="⚙️ Награда", callback_data="treasury_set_reward"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="treasury_stats")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])

def cancel_menu():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)

# ==================== MIDDLEWARE ====================
@dp.callback_query()
async def sub_middleware(callback: CallbackQuery, state: FSMContext):
    if callback.data in ["check_subscription"]: return
    if is_banned(callback.from_user.id):
        await callback.answer("❌ Вы забанены!", show_alert=True)
        return
    if is_muted(callback.from_user.id):
        await callback.answer("🔇 Вы в муте! Игры временно недоступны.", show_alert=True)
        return
    ok, _ = await check_subscription(callback.from_user.id)
    if not ok:
        await callback.answer("Подпишитесь на каналы!", show_alert=True)
        return

@dp.callback_query(F.data == "check_subscription")
async def check_sub(callback: CallbackQuery):
    ok, not_sub = await check_subscription(callback.from_user.id)
    if ok:
        await callback.message.delete()
        await callback.message.answer("✅ Спасибо за подписку!", reply_markup=main_menu())
    else:
        await callback.message.edit_text("Подпишитесь на каналы:", reply_markup=subscription_keyboard(not_sub))
    await callback.answer()

# ==================== СТАРТ ====================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    uid = message.from_user.id
    uname = message.from_user.username
    user = get_user(uid)
    if not user:
        code = hashlib.md5(f"{uid}{time.time()}".encode()).hexdigest()[:8]
        cursor.execute("INSERT INTO users (user_id, username, referral_code, balance) VALUES (?, ?, ?, ?)", (uid, uname, code, 5000))
        conn.commit()
        user = get_user(uid)
    
    args = message.text.split()
    if len(args) > 1:
        if args[1].startswith("ref"):
            ref_code = args[1][3:]
            cursor.execute("SELECT user_id FROM users WHERE referral_code = ?", (ref_code,))
            ref = cursor.fetchone()
            if ref and ref[0] != uid:
                cursor.execute("SELECT 1 FROM referrals WHERE referrer_id = ? AND referred_id = ?", (ref[0], uid))
                if not cursor.fetchone():
                    add_pocx(ref[0], REF_REWARD)
                    add_pocx(uid, REF_REFERRAL_BONUS)
                    cursor.execute("INSERT INTO referrals (referrer_id, referred_id, earned_amount) VALUES (?, ?, ?)", (ref[0], uid, REF_REWARD))
                    conn.commit()
                    try:
                        await bot.send_message(ref[0], f"👥 Новый реферал!\n👤 @{uname or 'нет'}\n💰 +{REF_REWARD:,} POCX")
                    except: pass
        elif args[1].startswith("check_"):
            code = args[1][6:]
            row = cursor.execute("SELECT per_user, remaining, used FROM checks WHERE code = ?", (code,)).fetchone()
            if row and row[1] > 0:
                used = json.loads(row[2]) if row[2] else []
                if str(uid) not in used:
                    add_pocx(uid, row[0])
                    used.append(str(uid))
                    cursor.execute("UPDATE checks SET remaining = remaining - 1, used = ? WHERE code = ?", (json.dumps(used), code))
                    conn.commit()
                    await message.answer(f"✅ Чек активирован! +{fmt_money(row[0])}")
    
    ok, not_sub = await check_subscription(uid)
    if not ok:
        await message.answer("Подпишитесь на каналы:", reply_markup=subscription_keyboard(not_sub))
        return
    
    vip, _ = get_vip(user["total_wagered"])
    bot_info = await bot.get_me()
    await message.answer(
        f"🎰 <b>POCX Casino</b>\n\n"
        f"💰 Баланс: {fmt_money(user['balance'])}\n"
        f"💎 VIP: {vip}\n"
        f"🎮 Игр: 11 | 🏦 Банк | 🎟 Промо\n\n"
        f"🔗 Реф: t.me/{bot_info.username}?start=ref{user['referral_code']}",
        reply_markup=main_menu() if is_private_chat(message) else None
    )

# ==================== ГЛАВНОЕ МЕНЮ ====================
@dp.message(F.text == "◀️ Главное меню")
async def back_main(message: Message):
    user = get_user(message.from_user.id)
    vip, _ = get_vip(user["total_wagered"])
    await message.answer(f"🎰 Главное меню\n💰 {fmt_money(user['balance'])} | {vip}", reply_markup=main_menu())

@dp.callback_query(F.data == "main_menu")
async def main_menu_cb(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    vip, _ = get_vip(user["total_wagered"])
    await callback.message.edit_text(f"🎰 Главное меню\n💰 {fmt_money(user['balance'])} | {vip}")
    await callback.answer()

@dp.callback_query(F.data == "admin_back")
async def admin_back_cb(callback: CallbackQuery):
    await callback.message.edit_text("👑 Админ-панель", reply_markup=admin_menu())
    await callback.answer()

# ==================== ИГРЫ МЕНЮ ====================
@dp.message(F.text == "🎮 Игры")
async def games(message: Message):
    if is_group_chat(message):
        await message.answer(
            "🎮 <b>Игры</b>\n\n"
            "📱 <b>Текстовые (работают везде):</b>\n"
            "• <code>рул 1000 красное</code> — Рулетка\n"
            "• <code>краш 1000 2.5</code> — Краш\n"
            "• <code>кубик 1000 5</code> — Кубик\n"
            "• <code>кости 1000 м</code> — Кости\n"
            "• <code>футбол 1000 гол</code> — Футбол\n"
            "• <code>баскет 1000</code> — Баскет\n\n"
            "🔒 <b>Только в ЛС:</b>\n"
            "• Башня, Золото, Алмазы, Мины, Очко\n\n"
            "✍️ Сокращения: 1к=1000, 1кк=1M, 1ккк=1B",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer("🎮 <b>Выбери игру</b>", reply_markup=games_menu())

@dp.callback_query(F.data.startswith("game_"))
async def game_selection(callback: CallbackQuery):
    game_map = {
        "game_tower": ("🗼 Башня", "башня 1000 2"),
        "game_gold": ("🥇 Золото", "золото 1000"),
        "game_diamond": ("💎 Алмазы", "алмазы 1000 2"),
        "game_mines": ("💣 Мины", "мины 1000 3"),
        "game_ochko": ("🎴 Очко", "очко 1000"),
        "game_roulette": ("🎡 Рулетка", "рул 1000 красное"),
        "game_crash": ("📈 Краш", "краш 1000 2.5"),
        "game_cube": ("🎲 Кубик", "кубик 1000 5"),
        "game_dice": ("🎯 Кости", "кости 1000 м"),
        "game_football": ("⚽ Футбол", "футбол 1000 гол"),
        "game_basket": ("🏀 Баскет", "баскет 1000"),
    }
    name, example = game_map.get(callback.data, ("", ""))
    await callback.message.answer(f"<b>{name}</b>\n\nПример: <code>{example}</code>", parse_mode=ParseMode.HTML)
    await callback.answer()

# ==================== ПРОФИЛЬ / СТАТИСТИКА / ТОП ====================
@dp.message(F.text == "👤 Профиль")
async def profile(message: Message):
    user = get_user(message.from_user.id)
    vip, bonus = get_vip(user["total_wagered"])
    status = user.get("custom_status") or "Обычный игрок"
    mute_status = "🔇 В муте" if user["is_muted"] else "✅ Активен"
    await message.answer(
        f"👤 <b>{message.from_user.first_name}</b>\n"
        f"🆔 ID: {user['user_id']}\n"
        f"💰 Баланс: {fmt_money(user['balance'])}\n"
        f"💎 VIP: {vip} (+{bonus}% к бонусам)\n"
        f"🏷 Статус: {status}\n"
        f"🔊 Статус: {mute_status}\n"
        f"📊 Вейджер: {fmt_money(user['total_wagered'])}\n"
        f"🏆 Выиграно: {fmt_money(user['total_won'])}\n"
        f"💸 Проиграно: {fmt_money(user['total_lost'])}\n"
        f"🔥 Серия: {user['daily_streak']} дн.\n"
        f"💳 Донатов: {fmt_money(user['total_donated'])}",
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "📊 Статистика")
async def stats(message: Message):
    user = get_user(message.from_user.id)
    played = cursor.execute("SELECT COUNT(*) FROM game_history WHERE user_id = ?", (message.from_user.id,)).fetchone()[0]
    wins = cursor.execute("SELECT COUNT(*) FROM game_history WHERE user_id = ? AND result='win'", (message.from_user.id,)).fetchone()[0]
    best = cursor.execute("SELECT MAX(multiplier) FROM game_history WHERE user_id = ? AND result='win'", (message.from_user.id,)).fetchone()[0] or 0
    wr = wins/max(played,1)*100
    await message.answer(
        f"📊 <b>Статистика</b>\n"
        f"🎮 Игр: {played}\n"
        f"✅ Побед: {wins} ({wr:.1f}%)\n"
        f"📈 Лучший x{best:.2f}\n"
        f"💰 Вейджер: {fmt_money(user['total_wagered'])}\n"
        f"🏆 Выиграно: {fmt_money(user['total_won'])}",
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "🏆 Топ")
async def top(message: Message):
    cursor.execute("SELECT user_id, username, total_won FROM users ORDER BY total_won DESC LIMIT 10")
    rows = cursor.fetchall()
    medals = ["🥇","🥈","🥉"]
    lines = ["🏆 <b>Топ-10 игроков</b>\n"]
    for i, row in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = row[1] or f"ID{row[0]}"
        lines.append(f"{medal} {name} — {fmt_money(row[2])}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

# ==================== БОНУСЫ ====================
@dp.message(F.text == "🎁 Бонусы")
async def bonuses(message: Message):
    if is_group_chat(message):
        await message.answer("🎁 Бонусы\n• /bonus — ежедневный\n• /promo CODE — промокод\n• Подробнее в ЛС")
    else:
        await message.answer(
            "🎁 <b>Бонусы</b>\n\n"
            "🎁 Ежедневный: 100-2000 POCX\n"
            "🆕 Приветственный: 1000 POCX\n"
            "👥 Реферал: 5000 вам + 500 другу",
            reply_markup=ReplyKeyboardMarkup(keyboard=[
                [KeyboardButton(text="🎁 Ежедневный бонус"), KeyboardButton(text="🆕 Приветственный бонус")],
                [KeyboardButton(text="🔑 Промокод"), KeyboardButton(text="🧾 Чеки")],
                [KeyboardButton(text="◀️ Главное меню")]
            ], resize_keyboard=True)
        )

@dp.message(F.text == "🎁 Ежедневный бонус")
async def daily_bonus(message: Message):
    uid = message.from_user.id
    row = cursor.execute("SELECT last_daily_bonus, daily_streak FROM users WHERE user_id = ?", (uid,)).fetchone()
    last = row[0] if row else None
    streak = row[1] if row else 0
    if last:
        last_dt = datetime.fromisoformat(last)
        if datetime.now() - last_dt < timedelta(days=1):
            await message.answer("❌ Бонус уже получен!")
            return
    bonus = random.randint(DAILY_BONUS_MIN, DAILY_BONUS_MAX)
    bonus = int(bonus * (1 + min(streak * 0.05, 0.5)))
    add_pocx(uid, bonus)
    cursor.execute("UPDATE users SET last_daily_bonus = CURRENT_TIMESTAMP, daily_streak = daily_streak + 1 WHERE user_id = ?", (uid,))
    conn.commit()
    await message.answer(f"🎁 +{bonus:,} POCX | 🔥 Серия: {streak+1} дн.", parse_mode=ParseMode.HTML)

@dp.message(F.text == "🆕 Приветственный бонус")
async def welcome_bonus(message: Message):
    uid = message.from_user.id
    row = cursor.execute("SELECT welcome_bonus_claimed FROM users WHERE user_id = ?", (uid,)).fetchone()
    if row and row[0]:
        await message.answer("❌ Уже получен!")
        return
    add_pocx(uid, WELCOME_BONUS)
    cursor.execute("UPDATE users SET welcome_bonus_claimed = 1 WHERE user_id = ?", (uid,))
    conn.commit()
    await message.answer(f"🎁 +{WELCOME_BONUS:,} POCX", parse_mode=ParseMode.HTML)

# ==================== ПРОМОКОДЫ ====================
@dp.message(F.text == "🔑 Промокод")
async def promo_input(message: Message, state: FSMContext):
    await state.set_state(GameStates.promo_code)
    await message.answer("🔑 Введи код:", reply_markup=cancel_menu())

@dp.message(GameStates.promo_code)
async def promo_use(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено", reply_markup=main_menu())
        return
    code = message.text.strip().upper()
    row = cursor.execute("SELECT bonus_amount, max_uses, used_count, is_active FROM promocodes WHERE code = ?", (code,)).fetchone()
    if not row or not row[3] or row[2] >= row[1]:
        await message.answer("❌ Промокод недействителен!")
        await state.clear()
        return
    if cursor.execute("SELECT 1 FROM used_promocodes WHERE user_id = ? AND code = ?", (message.from_user.id, code)).fetchone():
        await message.answer("❌ Уже использован!")
        await state.clear()
        return
    add_pocx(message.from_user.id, row[0])
    cursor.execute("INSERT INTO used_promocodes (user_id, code) VALUES (?, ?)", (message.from_user.id, code))
    cursor.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?", (code,))
    conn.commit()
    await message.answer(f"✅ +{fmt_money(row[0])}")
    await state.clear()

# ==================== ЧЕКИ ====================
@dp.message(F.text == "🧾 Чеки")
async def checks_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать", callback_data="check_create")],
        [InlineKeyboardButton(text="📥 Активировать", callback_data="check_claim")],
        [InlineKeyboardButton(text="📋 Мои", callback_data="check_my")]
    ])
    await message.answer("🧾 <b>Чеки</b>", reply_markup=kb, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "check_create")
async def check_create_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.check_create_amount)
    await callback.message.edit_text("💰 Сумма на 1 активацию:")
    await callback.answer()

@dp.message(GameStates.check_create_amount)
async def check_create_amount(message: Message, state: FSMContext):
    try:
        amt = parse_amount(message.text)
        if amt <= 0 or amt > 5_000_000: raise ValueError
    except:
        await message.answer("❌ От 1 до 5,000,000")
        return
    await state.update_data(check_amt=amt)
    await state.set_state(GameStates.check_create_count)
    await message.answer("🔢 Количество активаций (1-50):")

@dp.message(GameStates.check_create_count)
async def check_create_count(message: Message, state: FSMContext):
    try:
        cnt = int(message.text)
        if cnt <= 0 or cnt > 50: raise ValueError
    except:
        await message.answer("❌ 1-50")
        return
    data = await state.get_data()
    amt = data["check_amt"]
    total = amt * cnt
    user = get_user(message.from_user.id)
    if user["balance"] < total:
        await message.answer(f"❌ Нужно {fmt_money(total)}")
        return
    remove_pocx(message.from_user.id, total)
    code = generate_check_code()
    cursor.execute("INSERT INTO checks (code, creator_id, per_user, remaining, used, password) VALUES (?,?,?,?,'[]',NULL)",
                   (code, message.from_user.id, amt, cnt))
    conn.commit()
    bot_info = await bot.get_me()
    link = f"t.me/{bot_info.username}?start=check_{code}"
    await message.answer(f"✅ Чек создан!\n🎫 <code>{code}</code>\n🔗 {link}\n💰 {fmt_money(amt)} x{cnt}", parse_mode=ParseMode.HTML)
    await state.clear()

@dp.callback_query(F.data == "check_claim")
async def check_claim_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.check_claim)
    await callback.message.edit_text("🔑 Код чека:")
    await callback.answer()

@dp.message(GameStates.check_claim)
async def check_claim(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    row = cursor.execute("SELECT per_user, remaining, used FROM checks WHERE code = ?", (code,)).fetchone()
    if not row or row[1] <= 0:
        await message.answer("❌ Не найден")
        await state.clear()
        return
    used = json.loads(row[2]) if row[2] else []
    if str(message.from_user.id) in used:
        await message.answer("❌ Уже активирован")
        await state.clear()
        return
    add_pocx(message.from_user.id, row[0])
    used.append(str(message.from_user.id))
    cursor.execute("UPDATE checks SET remaining = remaining - 1, used = ? WHERE code = ?", (json.dumps(used), code))
    conn.commit()
    await message.answer(f"✅ +{fmt_money(row[0])}")
    await state.clear()

@dp.callback_query(F.data == "check_my")
async def check_my(callback: CallbackQuery):
    rows = cursor.execute("SELECT code, per_user, remaining FROM checks WHERE creator_id = ? ORDER BY rowid DESC LIMIT 10", (callback.from_user.id,)).fetchall()
    if not rows:
        await callback.message.edit_text("📋 Нет чеков")
        await callback.answer()
        return
    text = "📋 <b>Ваши чеки</b>\n\n"
    for r in rows:
        text += f"🎫 <code>{r[0]}</code> | {fmt_money(r[1])} | ост: {r[2]}\n"
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML)
    await callback.answer()

# ==================== РЕФЕРАЛЫ ====================
@dp.message(F.text == "👥 Рефералы")
async def referrals(message: Message):
    user = get_user(message.from_user.id)
    cnt = cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (message.from_user.id,)).fetchone()[0]
    earned = cursor.execute("SELECT COALESCE(SUM(earned_amount),0) FROM referrals WHERE referrer_id = ?", (message.from_user.id,)).fetchone()[0]
    bot_info = await bot.get_me()
    link = f"t.me/{bot_info.username}?start=ref{user['referral_code']}"
    await message.answer(f"👥 Рефералы\n🔗 {link}\n👤 {cnt} чел.\n💰 {fmt_money(earned)}", parse_mode=ParseMode.HTML)

# ==================== БАНК (продолжение в части 2) ====================
# ==================== БАНК ====================
@dp.message(F.text == "🏦 Банк")
async def bank_menu(message: Message):
    closed, payout = check_and_withdraw_deposits(message.from_user.id)
    if closed > 0:
        await message.answer(f"✅ Снято {closed} депозитов: +{fmt_money(payout)}")
    
    if is_group_chat(message):
        await message.answer(
            "🏦 <b>Банк</b>\n\n"
            "📱 <b>Команды (ЛС):</b>\n"
            "• /bank open — открыть депозит\n"
            "• /bank list — мои депозиты\n"
            "• /bank withdraw — снять\n\n"
            "📅 7д (+1%) | 14д (+2%) | 30д (+5%)",
            parse_mode=ParseMode.HTML
        )
        return
    
    kb = InlineKeyboardMarkup(inline_row_width=2, inline_keyboard=[
        [InlineKeyboardButton(text="➕ Открыть депозит", callback_data="bank_open")],
        [InlineKeyboardButton(text="📜 Мои депозиты", callback_data="bank_list")],
        [InlineKeyboardButton(text="💸 Снять созревшие", callback_data="bank_withdraw")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    await message.answer("🏦 <b>Банк</b>\n7д +1% | 14д +2% | 30д +5%", reply_markup=kb, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "bank_open")
async def bank_open(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.bank_deposit_amount)
    await callback.message.edit_text("💰 Сумма депозита (мин. 1000):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="bank_cancel")]]))
    await callback.answer()

@dp.callback_query(F.data == "bank_cancel")
async def bank_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("❌ Отменено")
    await callback.answer()

@dp.message(GameStates.bank_deposit_amount)
async def bank_deposit_amount(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
        if amount < 1000: raise ValueError
    except:
        await message.answer("❌ От 1000 POCX!")
        return
    user = get_user(message.from_user.id)
    if user["balance"] < amount:
        await message.answer(f"❌ Нужно {fmt_money(amount)}")
        await state.clear()
        return
    await state.update_data(bank_amount=amount)
    await state.set_state(GameStates.bank_deposit_term)
    kb = InlineKeyboardMarkup(inline_row_width=2, inline_keyboard=[
        [InlineKeyboardButton(text="7д (+1%)", callback_data="bank_term_7")],
        [InlineKeyboardButton(text="14д (+2%)", callback_data="bank_term_14")],
        [InlineKeyboardButton(text="30д (+5%)", callback_data="bank_term_30")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="bank_cancel")]
    ])
    await message.answer("📅 Срок депозита:", reply_markup=kb)

@dp.callback_query(F.data.startswith("bank_term_"))
async def bank_term(callback: CallbackQuery, state: FSMContext):
    term = int(callback.data.split("_")[2])
    data = await state.get_data()
    amount = data["bank_amount"]
    ok, msg = add_deposit(callback.from_user.id, amount, term)
    await state.clear()
    await callback.message.edit_text(msg)
    await callback.answer()

@dp.callback_query(F.data == "bank_list")
async def bank_list(callback: CallbackQuery):
    deps = list_user_deposits(callback.from_user.id)
    if not deps:
        await callback.message.edit_text("📜 Нет активных депозитов", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]]))
        await callback.answer()
        return
    now = int(time.time())
    lines = ["📜 <b>Депозиты</b>\n"]
    for d in deps:
        remaining_days = max(0, d[4] - (now - d[5]) // 86400)
        payout = int(d[2] * (1 + d[3]))
        lines.append(f"#{d[0]}: {fmt_money(d[2])} | +{int(d[3]*100)}% | ост. {remaining_days}д | выпл: {fmt_money(payout)}")
    await callback.message.edit_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]]))
    await callback.answer()

@dp.callback_query(F.data == "bank_withdraw")
async def bank_withdraw(callback: CallbackQuery):
    closed, payout = check_and_withdraw_deposits(callback.from_user.id)
    if closed == 0:
        await callback.answer("Нет созревших депозитов!", show_alert=True)
    else:
        user = get_user(callback.from_user.id)
        await callback.message.edit_text(f"✅ Снято {closed} депозитов: +{fmt_money(payout)}\n💰 Баланс: {fmt_money(user['balance'])}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]]))
    await callback.answer()

# ==================== ФИНАНСЫ / ДОНАТ ====================
@dp.message(F.text == "💰 Финансы")
async def finance(message: Message):
    if is_group_chat(message):
        await message.answer("💰 Финансы\n⭐ 1 Star = 2,500 POCX\nДля пополнения перейди в ЛС: @POCXCasinoBot")
        return
    await message.answer("💰 <b>Финансы</b>\n⭐ 1 Star = 2,500 POCX", parse_mode=ParseMode.HTML)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 1 Star — 2,500 POCX", callback_data="donate_1")],
        [InlineKeyboardButton(text="⭐⭐ 5 Stars — 12,500 POCX", callback_data="donate_5")],
        [InlineKeyboardButton(text="⭐⭐⭐ 10 Stars — 25,000 POCX", callback_data="donate_10")],
        [InlineKeyboardButton(text="💰 25 Stars — 62,500 POCX", callback_data="donate_25")],
        [InlineKeyboardButton(text="💎 50 Stars — 125,000 POCX", callback_data="donate_50")],
        [InlineKeyboardButton(text="✏️ Своя сумма", callback_data="donate_custom")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    await message.answer("💎 <b>Пополнение через Telegram Stars</b>", reply_markup=kb, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("donate_"))
async def donate_handler(callback: CallbackQuery, state: FSMContext):
    if callback.data == "donate_custom":
        await state.set_state(GameStates.donate_custom)
        await callback.message.edit_text("✏️ Введи сумму в Stars:")
        await callback.answer()
        return
    
    amounts = {"donate_1": 1, "donate_5": 5, "donate_10": 10, "donate_25": 25, "donate_50": 50}
    stars = amounts.get(callback.data, 1)
    pocx_amount = stars * STARS_TO_POCX
    
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Пополнение POCX",
        description=f"{stars} Stars = {pocx_amount:,} POCX",
        payload=f"donate_{stars}_{pocx_amount}",
        provider_token="",  # Для Telegram Stars оставляем пустым
        currency="XTR",
        prices=[LabeledPrice(label=f"{stars} Stars", amount=stars)]
    )
    await callback.answer("✅ Счёт выставлен!")

@dp.message(GameStates.donate_custom)
async def donate_custom_amount(message: Message, state: FSMContext):
    try:
        stars = int(message.text)
        if stars < 1 or stars > 2500: raise ValueError
    except:
        await message.answer("❌ От 1 до 2500 Stars!")
        return
    pocx_amount = stars * STARS_TO_POCX
    await bot.send_invoice(
        chat_id=message.from_user.id,
        title="Пополнение POCX",
        description=f"{stars} Stars = {pocx_amount:,} POCX",
        payload=f"donate_{stars}_{pocx_amount}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"{stars} Stars", amount=stars)]
    )
    await message.answer("✅ Счёт выставлен!")
    await state.clear()

@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    parts = payload.split("_")
    pocx_amount = int(parts[2])
    add_pocx(message.from_user.id, pocx_amount)
    user = get_user(message.from_user.id)
    await message.answer(f"✅ Спасибо за донат!\n💰 +{fmt_money(pocx_amount)}\n💳 Баланс: {fmt_money(user['balance'])}")

# ==================== КАЗНА ЧАТА ====================
@dp.message(F.text == "🏦 Казна")
async def treasury_command(message: Message):
    if is_private_chat(message):
        await message.answer("❌ Команда только в чатах!")
        return
    treasury = get_chat_treasury(message.chat.id)
    if not treasury:
        await message.answer("🏦 Казна не активирована! Владелец чата может активировать за 15,000 POCX.")
        return
    if message.from_user.id != treasury["owner_id"]:
        await message.answer(f"🏦 Казна чата\n💰 Баланс: {fmt_money(treasury['balance'])}\n🎁 Награда: {treasury['reward_per_invite']} POCX")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Пополнить", callback_data="treasury_owner_add")],
        [InlineKeyboardButton(text="⚙️ Награда", callback_data="treasury_owner_reward")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="treasury_owner_stats")]
    ])
    await message.answer(f"🏦 Управление казной\n💰 {fmt_money(treasury['balance'])}\n🎁 {treasury['reward_per_invite']} POCX", reply_markup=kb)

# ==================== ИГРЫ ====================

# --- РУЛЕТКА ---
@dp.message(lambda m: m.text and m.text.lower().startswith("рул"))
async def roulette_start(message: Message, state: FSMContext):
    parts = message.text.lower().split()
    if len(parts) < 3:
        await message.reply("❌ Формат: <code>рул [ставка] [красное/черное/чет/нечет/зеро]</code>", parse_mode=ParseMode.HTML)
        return
    
    user = get_user(message.from_user.id)
    try:
        bet = parse_amount(parts[1])
        if bet < MIN_BET or bet > user["balance"]: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{user['balance']}")
        return
    
    choice = parts[2]
    choices = {"красное": "red", "черное": "black", "чет": "even", "нечет": "odd", "зеро": "zero"}
    if choice not in choices:
        await message.reply("❌ Выбери: красное/черное/чет/нечет/зеро")
        return
    
    number = random.randint(0, 36)
    color = "green" if number == 0 else ("red" if number in RED_NUMBERS else "black")
    parity = "zero" if number == 0 else ("even" if number % 2 == 0 else "odd")
    
    win = False
    mult = 0
    choice_en = choices[choice]
    if choice_en == "red" and color == "red": win, mult = True, 2
    elif choice_en == "black" and color == "black": win, mult = True, 2
    elif choice_en == "even" and parity == "even": win, mult = True, 2
    elif choice_en == "odd" and parity == "odd": win, mult = True, 2
    elif choice_en == "zero" and number == 0: win, mult = True, 36
    
    payout = int(bet * mult) if win else 0
    remove_pocx(message.from_user.id, bet)
    if payout > 0: add_pocx(message.from_user.id, payout)
    record_game(message.from_user.id, "roulette", bet, mult, payout, "win" if win else "loss", {"number": number, "color": color})
    
    color_emoji = {"red": "🔴", "black": "⚫", "green": "🟢"}[color]
    await message.reply(
        f"🎡 <b>Рулетка</b>\n"
        f"🎯 Выпало: {number} {color_emoji}\n"
        f"💰 Ставка: {fmt_money(bet)}\n"
        f"{'✅ Выигрыш: ' + fmt_money(payout) if win else '❌ Проигрыш'}\n"
        f"💳 Баланс: {fmt_money(get_user(message.from_user.id)['balance'])}",
        parse_mode=ParseMode.HTML
    )

# --- КРАШ ---
@dp.message(lambda m: m.text and m.text.lower().startswith("краш"))
async def crash_start(message: Message):
    parts = message.text.lower().split()
    if len(parts) < 3:
        await message.reply("❌ Формат: <code>краш [ставка] [множитель]</code>", parse_mode=ParseMode.HTML)
        return
    
    user = get_user(message.from_user.id)
    try:
        bet = parse_amount(parts[1])
        target = float(parts[2].replace(",", "."))
        if bet < MIN_BET or bet > user["balance"] or target < 1.01 or target > 10: raise ValueError
    except:
        await message.reply("❌ Ставка >100, множитель 1.01-10")
        return
    
    u = random.random()
    crash = round(0.99 / (1.0 - u), 2)
    crash = max(1.0, min(50.0, crash))
    
    win = crash >= target
    payout = int(bet * target) if win else 0
    remove_pocx(message.from_user.id, bet)
    if payout > 0: add_pocx(message.from_user.id, payout)
    record_game(message.from_user.id, "crash", bet, target, payout, "win" if win else "loss", {"crash": crash})
    
    await message.reply(
        f"📈 <b>Краш</b>\n"
        f"🎯 Цель: x{target:.2f} | Игра: x{crash:.2f}\n"
        f"{'✅ +' + fmt_money(payout) if win else '❌ -' + fmt_money(bet)}\n"
        f"💳 Баланс: {fmt_money(get_user(message.from_user.id)['balance'])}",
        parse_mode=ParseMode.HTML
    )

# --- КУБИК ---
@dp.message(lambda m: m.text and m.text.lower().startswith("кубик"))
async def cube_start(message: Message):
    parts = message.text.lower().split()
    if len(parts) < 3:
        await message.reply("❌ Формат: <code>кубик [ставка] [1-6/чет/нечет/б/м]</code>", parse_mode=ParseMode.HTML)
        return
    
    user = get_user(message.from_user.id)
    try:
        bet = parse_amount(parts[1])
        if bet < MIN_BET or bet > user["balance"]: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{user['balance']}")
        return
    
    guess = parts[2]
    dice_msg = await message.answer_dice(emoji="🎲")
    number = int(dice_msg.dice.value)
    
    win = False
    mult = 0
    if guess == str(number): win, mult = True, 3.5
    elif guess == "чет" and number % 2 == 0: win, mult = True, 1.9
    elif guess == "нечет" and number % 2 == 1: win, mult = True, 1.9
    elif guess == "б" and number >= 4: win, mult = True, 1.9
    elif guess == "м" and number <= 3: win, mult = True, 1.9
    
    payout = int(bet * mult) if win else 0
    remove_pocx(message.from_user.id, bet)
    if payout > 0: add_pocx(message.from_user.id, payout)
    record_game(message.from_user.id, "cube", bet, mult, payout, "win" if win else "loss", {"number": number})
    
    await message.reply(
        f"🎲 <b>Кубик</b>\n"
        f"🎯 Выпало: {number}\n"
        f"{'✅ +' + fmt_money(payout) if win else '❌ -' + fmt_money(bet)}\n"
        f"💳 Баланс: {fmt_money(get_user(message.from_user.id)['balance'])}",
        parse_mode=ParseMode.HTML
    )

# --- КОСТИ ---
@dp.message(lambda m: m.text and m.text.lower().startswith("кости"))
async def dice_start(message: Message):
    parts = message.text.lower().split()
    if len(parts) < 3:
        await message.reply("❌ Формат: <code>кости [ставка] [м/б/равно]</code>", parse_mode=ParseMode.HTML)
        return
    
    user = get_user(message.from_user.id)
    try:
        bet = parse_amount(parts[1])
        if bet < MIN_BET or bet > user["balance"]: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{user['balance']}")
        return
    
    choice = parts[2]
    if choice not in ["м", "б", "равно"]:
        await message.reply("❌ м/б/равно")
        return
    
    d1_msg = await message.answer_dice(emoji="🎲")
    d2_msg = await message.answer_dice(emoji="🎲")
    d1, d2 = int(d1_msg.dice.value), int(d2_msg.dice.value)
    total = d1 + d2
    
    win = False
    mult = 0
    if choice == "м" and total < 7: win, mult = True, 2.25
    elif choice == "б" and total > 7: win, mult = True, 2.25
    elif choice == "равно" and total == 7: win, mult = True, 5
    
    payout = int(bet * mult) if win else 0
    remove_pocx(message.from_user.id, bet)
    if payout > 0: add_pocx(message.from_user.id, payout)
    record_game(message.from_user.id, "dice", bet, mult, payout, "win" if win else "loss", {"d1": d1, "d2": d2, "total": total})
    
    await message.reply(
        f"🎯 <b>Кости</b>\n"
        f"🎲 {d1} + {d2} = {total}\n"
        f"{'✅ +' + fmt_money(payout) if win else '❌ -' + fmt_money(bet)}\n"
        f"💳 Баланс: {fmt_money(get_user(message.from_user.id)['balance'])}",
        parse_mode=ParseMode.HTML
    )

# --- ФУТБОЛ ---
@dp.message(lambda m: m.text and m.text.lower().startswith("футбол"))
async def football_start(message: Message):
    parts = message.text.lower().split()
    if len(parts) < 2:
        await message.reply("❌ Формат: <code>футбол [ставка] [гол/мимо]</code>", parse_mode=ParseMode.HTML)
        return
    
    user = get_user(message.from_user.id)
    try:
        bet = parse_amount(parts[1])
        if bet < MIN_BET or bet > user["balance"]: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{user['balance']}")
        return
    
    choice = parts[2] if len(parts) > 2 else None
    if choice and choice not in ["гол", "мимо"]:
        await message.reply("❌ гол/мимо")
        return
    
    dice_msg = await message.answer_dice(emoji="⚽")
    value = int(dice_msg.dice.value)
    result = "гол" if value >= 3 else "мимо"
    
    if choice:
        win = result == choice
        mult = FOOTBALL_MULTIPLIERS[choice]
        payout = int(bet * mult) if win else 0
        remove_pocx(message.from_user.id, bet)
        if payout > 0: add_pocx(message.from_user.id, payout)
        record_game(message.from_user.id, "football", bet, mult, payout, "win" if win else "loss", {"value": value, "result": result})
        
        await message.reply(
            f"⚽ <b>Футбол</b>\n"
            f"🎯 Результат: {result.upper()}\n"
            f"🎯 Выбор: {choice.upper()}\n"
            f"{'✅ +' + fmt_money(payout) if win else '❌ -' + fmt_money(bet)}\n"
            f"💳 Баланс: {fmt_money(get_user(message.from_user.id)['balance'])}",
            parse_mode=ParseMode.HTML
        )

# --- БАСКЕТ ---
@dp.message(lambda m: m.text and m.text.lower().startswith("баскет"))
async def basket_start(message: Message):
    parts = message.text.lower().split()
    if len(parts) < 2:
        await message.reply("❌ Формат: <code>баскет [ставка]</code>", parse_mode=ParseMode.HTML)
        return
    
    user = get_user(message.from_user.id)
    try:
        bet = parse_amount(parts[1])
        if bet < MIN_BET or bet > user["balance"]: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{user['balance']}")
        return
    
    dice_msg = await message.answer_dice(emoji="🏀")
    value = int(dice_msg.dice.value)
    win = value >= 4
    result_text = "Точный бросок" if win else "Промах"
    payout = int(bet * 2.2) if win else 0
    remove_pocx(message.from_user.id, bet)
    if payout > 0: add_pocx(message.from_user.id, payout)
    record_game(message.from_user.id, "basket", bet, 2.2, payout, "win" if win else "loss", {"value": value})
    
    await message.reply(
        f"🏀 <b>Баскет</b>\n"
        f"🎯 {result_text}\n"
        f"{'✅ +' + fmt_money(payout) if win else '❌ -' + fmt_money(bet)}\n"
        f"💳 Баланс: {fmt_money(get_user(message.from_user.id)['balance'])}",
        parse_mode=ParseMode.HTML
    )

# --- БАШНЯ (ТОЛЬКО ЛС) ---
@dp.message(lambda m: m.text and m.text.lower().startswith("башня"))
async def tower_start(message: Message, state: FSMContext):
    if is_group_chat(message):
        await message.reply("❌ Башня доступна только в ЛС!")
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("❌ Формат: <code>башня [ставка] [мины 1-3]</code>", parse_mode=ParseMode.HTML)
        return
    
    user = get_user(message.from_user.id)
    try:
        bet = parse_amount(parts[1])
        mines = int(parts[2]) if len(parts) > 2 else 1
        if bet < MIN_BET or bet > user["balance"] or mines < 1 or mines > 3: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{user['balance']}, мины 1-3")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств!")
        return
    
    game = {"bet": bet, "mines": mines, "level": 0, "path": []}
    TOWER_GAMES[message.from_user.id] = game
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(i), callback_data=f"tower_pick_{i}") for i in range(1, 6)],
        [InlineKeyboardButton(text="❌ Сдаться", callback_data="tower_cancel")]
    ])
    await message.answer(f"🗼 Башня | Этаж 1/9 | Ставка: {fmt_money(bet)} | Мины: {mines}", reply_markup=kb)

@dp.callback_query(F.data.startswith("tower_pick_"))
async def tower_pick(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = TOWER_GAMES.get(user_id)
    if not game:
        await callback.answer("Игра не найдена!", show_alert=True)
        return
    
    pick = int(callback.data.split("_")[2])
    level = game["level"]
    if level >= 9: return
    
    # Генерация бомб для уровня (если ещё нет)
    if len(game["path"]) <= level:
        bombs = random.sample(range(1, 6), game["mines"])
        game["path"].append(bombs)
    
    if pick in game["path"][level]:
        # Проигрыш
        record_game(user_id, "tower", game["bet"], 0, 0, "loss", {"level": level+1})
        await callback.message.edit_text(f"💥 Мина! Этаж {level+1}/9\n❌ -{fmt_money(game['bet'])}")
        del TOWER_GAMES[user_id]
    else:
        game["level"] += 1
        if game["level"] >= 9:
            mult = TOWER_MULTIPLIERS[-1]
            payout = int(game["bet"] * mult)
            add_pocx(user_id, payout)
            record_game(user_id, "tower", game["bet"], mult, payout, "win", {"level": 9})
            await callback.message.edit_text(f"🏁 Победа! 9/9\n✅ +{fmt_money(payout)} (x{mult})")
            del TOWER_GAMES[user_id]
        else:
            cur_mult = TOWER_MULTIPLIERS[game["level"]]
            cur_win = int(game["bet"] * cur_mult)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=str(i), callback_data=f"tower_pick_{i}") for i in range(1, 6)],
                [InlineKeyboardButton(text=f"💰 Забрать ({fmt_money(cur_win)})", callback_data="tower_collect"),
                 InlineKeyboardButton(text="❌ Сдаться", callback_data="tower_cancel")]
            ])
            await callback.message.edit_text(
                f"🗼 Башня | Этаж {game['level']+1}/9 | x{cur_mult:.2f}\n"
                f"💰 Можно забрать: {fmt_money(cur_win)}",
                reply_markup=kb
            )
    await callback.answer()

@dp.callback_query(F.data == "tower_collect")
async def tower_collect(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = TOWER_GAMES.get(user_id)
    if not game:
        await callback.answer("Игра не найдена!", show_alert=True)
        return
    
    mult = TOWER_MULTIPLIERS[game["level"]]
    payout = int(game["bet"] * mult)
    add_pocx(user_id, payout)
    record_game(user_id, "tower", game["bet"], mult, payout, "win", {"level": game["level"]})
    await callback.message.edit_text(f"💰 Забрано: {fmt_money(payout)} (x{mult:.2f})")
    del TOWER_GAMES[user_id]
    await callback.answer()

@dp.callback_query(F.data == "tower_cancel")
async def tower_cancel(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = TOWER_GAMES.get(user_id)
    if not game:
        await callback.answer("Игра не найдена!", show_alert=True)
        return
    
    if game["level"] == 0:
        add_pocx(user_id, game["bet"])
        await callback.message.edit_text(f"❌ Возврат: {fmt_money(game['bet'])}")
    else:
        await callback.message.edit_text(f"❌ Сдался на этаже {game['level']+1}")
    del TOWER_GAMES[user_id]
    await callback.answer()

# --- ЗОЛОТО (ТОЛЬКО ЛС) ---
@dp.message(lambda m: m.text and m.text.lower().startswith("золото"))
async def gold_start(message: Message):
    if is_group_chat(message):
        await message.reply("❌ Золото доступно только в ЛС!")
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("❌ Формат: <code>золото [ставка]</code>", parse_mode=ParseMode.HTML)
        return
    
    user = get_user(message.from_user.id)
    try:
        bet = parse_amount(parts[1])
        if bet < MIN_BET or bet > user["balance"]: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{user['balance']}")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств!")
        return
    
    game = {"bet": bet, "step": 0}
    GOLD_GAMES[message.from_user.id] = game
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(i), callback_data=f"gold_pick_{i}") for i in range(1, 5)],
        [InlineKeyboardButton(text="❌ Сдаться", callback_data="gold_cancel")]
    ])
    await message.answer(f"🥇 Золото | Раунд 1/7 | Ставка: {fmt_money(bet)}", reply_markup=kb)

@dp.callback_query(F.data.startswith("gold_pick_"))
async def gold_pick(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = GOLD_GAMES.get(user_id)
    if not game:
        await callback.answer("Игра не найдена!", show_alert=True)
        return
    
    pick = int(callback.data.split("_")[2])
    trap = random.randint(1, 4)
    
    if pick == trap:
        record_game(user_id, "gold", game["bet"], 0, 0, "loss", {"step": game["step"]})
        await callback.message.edit_text(f"💥 Ловушка! Раунд {game['step']+1}\n❌ -{fmt_money(game['bet'])}")
        del GOLD_GAMES[user_id]
    else:
        game["step"] += 1
        if game["step"] >= 7:
            mult = GOLD_MULTIPLIERS[-1]
            payout = int(game["bet"] * mult)
            add_pocx(user_id, payout)
            record_game(user_id, "gold", game["bet"], mult, payout, "win", {"step": 7})
            await callback.message.edit_text(f"🏁 Победа! 7/7\n✅ +{fmt_money(payout)} (x{mult})")
            del GOLD_GAMES[user_id]
        else:
            cur_mult = GOLD_MULTIPLIERS[game["step"]]
            cur_win = int(game["bet"] * cur_mult)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=str(i), callback_data=f"gold_pick_{i}") for i in range(1, 5)],
                [InlineKeyboardButton(text=f"💰 Забрать ({fmt_money(cur_win)})", callback_data="gold_collect"),
                 InlineKeyboardButton(text="❌ Сдаться", callback_data="gold_cancel")]
            ])
            await callback.message.edit_text(
                f"🥇 Золото | Раунд {game['step']+1}/7 | x{cur_mult:.2f}\n"
                f"💰 Можно забрать: {fmt_money(cur_win)}",
                reply_markup=kb
            )
    await callback.answer()

@dp.callback_query(F.data == "gold_collect")
async def gold_collect(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = GOLD_GAMES.get(user_id)
    if not game:
        await callback.answer("Игра не найдена!", show_alert=True)
        return
    
    mult = GOLD_MULTIPLIERS[game["step"]]
    payout = int(game["bet"] * mult)
    add_pocx(user_id, payout)
    record_game(user_id, "gold", game["bet"], mult, payout, "win", {"step": game["step"]})
    await callback.message.edit_text(f"💰 Забрано: {fmt_money(payout)} (x{mult:.2f})")
    del GOLD_GAMES[user_id]
    await callback.answer()

@dp.callback_query(F.data == "gold_cancel")
async def gold_cancel(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = GOLD_GAMES.get(user_id)
    if not game:
        await callback.answer("Игра не найдена!", show_alert=True)
        return
    
    if game["step"] == 0:
        add_pocx(user_id, game["bet"])
        await callback.message.edit_text(f"❌ Возврат: {fmt_money(game['bet'])}")
    else:
        await callback.message.edit_text(f"❌ Сдался на раунде {game['step']+1}")
    del GOLD_GAMES[user_id]
    await callback.answer()

# --- АЛМАЗЫ (ТОЛЬКО ЛС) ---
@dp.message(lambda m: m.text and m.text.lower().startswith("алмазы"))
async def diamond_start(message: Message):
    if is_group_chat(message):
        await message.reply("❌ Алмазы доступны только в ЛС!")
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("❌ Формат: <code>алмазы [ставка] [мины 1-2]</code>", parse_mode=ParseMode.HTML)
        return
    
    user = get_user(message.from_user.id)
    try:
        bet = parse_amount(parts[1])
        mines = int(parts[2]) if len(parts) > 2 else 1
        if bet < MIN_BET or bet > user["balance"] or mines < 1 or mines > 2: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{user['balance']}, мины 1-2")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств!")
        return
    
    game = {"bet": bet, "mines": mines, "step": 0}
    DIAMOND_GAMES[message.from_user.id] = game
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(i), callback_data=f"diamond_pick_{i}") for i in range(1, 6)],
        [InlineKeyboardButton(text="❌ Сдаться", callback_data="diamond_cancel")]
    ])
    await message.answer(f"💎 Алмазы | Шаг 1/8 | Ставка: {fmt_money(bet)} | Мины: {mines}", reply_markup=kb)

@dp.callback_query(F.data.startswith("diamond_pick_"))
async def diamond_pick(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = DIAMOND_GAMES.get(user_id)
    if not game:
        await callback.answer("Игра не найдена!", show_alert=True)
        return
    
    pick = int(callback.data.split("_")[2])
    traps = random.sample(range(1, 6), game["mines"])
    
    if pick in traps:
        record_game(user_id, "diamond", game["bet"], 0, 0, "loss", {"step": game["step"]})
        await callback.message.edit_text(f"💥 Мина! Шаг {game['step']+1}\n❌ -{fmt_money(game['bet'])}")
        del DIAMOND_GAMES[user_id]
    else:
        game["step"] += 1
        if game["step"] >= 8:
            mult = DIAMOND_MULTIPLIERS[-1]
            payout = int(game["bet"] * mult)
            add_pocx(user_id, payout)
            record_game(user_id, "diamond", game["bet"], mult, payout, "win", {"step": 8})
            await callback.message.edit_text(f"🏁 Победа! 8/8\n✅ +{fmt_money(payout)} (x{mult})")
            del DIAMOND_GAMES[user_id]
        else:
            cur_mult = DIAMOND_MULTIPLIERS[game["step"]]
            cur_win = int(game["bet"] * cur_mult)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=str(i), callback_data=f"diamond_pick_{i}") for i in range(1, 6)],
                [InlineKeyboardButton(text=f"💰 Забрать ({fmt_money(cur_win)})", callback_data="diamond_collect"),
                 InlineKeyboardButton(text="❌ Сдаться", callback_data="diamond_cancel")]
            ])
            await callback.message.edit_text(
                f"💎 Алмазы | Шаг {game['step']+1}/8 | x{cur_mult:.2f}\n"
                f"💰 Можно забрать: {fmt_money(cur_win)}",
                reply_markup=kb
            )
    await callback.answer()

@dp.callback_query(F.data == "diamond_collect")
async def diamond_collect(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = DIAMOND_GAMES.get(user_id)
    if not game:
        await callback.answer("Игра не найдена!", show_alert=True)
        return
    
    mult = DIAMOND_MULTIPLIERS[game["step"]]
    payout = int(game["bet"] * mult)
    add_pocx(user_id, payout)
    record_game(user_id, "diamond", game["bet"], mult, payout, "win", {"step": game["step"]})
    await callback.message.edit_text(f"💰 Забрано: {fmt_money(payout)} (x{mult:.2f})")
    del DIAMOND_GAMES[user_id]
    await callback.answer()

@dp.callback_query(F.data == "diamond_cancel")
async def diamond_cancel(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = DIAMOND_GAMES.get(user_id)
    if not game:
        await callback.answer("Игра не найдена!", show_alert=True)
        return
    
    if game["step"] == 0:
        add_pocx(user_id, game["bet"])
        await callback.message.edit_text(f"❌ Возврат: {fmt_money(game['bet'])}")
    else:
        await callback.message.edit_text(f"❌ Сдался на шаге {game['step']+1}")
    del DIAMOND_GAMES[user_id]
    await callback.answer()

# --- МИНЫ (ТОЛЬКО ЛС) ---
@dp.message(lambda m: m.text and m.text.lower().startswith("мины"))
async def mines_start(message: Message, state: FSMContext):
    if is_group_chat(message):
        await message.reply("❌ Мины доступны только в ЛС!")
        return
    
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply("❌ Формат: <code>мины [ставка] [кол-во мин 1-5]</code>", parse_mode=ParseMode.HTML)
        return
    
    user = get_user(message.from_user.id)
    try:
        bet = parse_amount(parts[1])
        mines_count = int(parts[2])
        if bet < MIN_BET or bet > user["balance"] or mines_count < 1 or mines_count > 5: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{user['balance']}, мины 1-5")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств!")
        return
    
    cells = list(range(1, 10))
    mines = set(random.sample(cells, mines_count))
    
    game = {"bet": bet, "mines": mines, "mines_count": mines_count, "opened": set(), "field": {i: "❔" for i in cells}}
    MINES_GAMES[message.from_user.id] = game
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❔", callback_data=f"mines_cell_{i}") for i in range(1, 4)],
        [InlineKeyboardButton(text="❔", callback_data=f"mines_cell_{i}") for i in range(4, 7)],
        [InlineKeyboardButton(text="❔", callback_data=f"mines_cell_{i}") for i in range(7, 10)],
        [InlineKeyboardButton(text="❌ Сдаться", callback_data="mines_cancel")]
    ])
    await message.answer(f"💣 Мины | Мин: {mines_count} | Ставка: {fmt_money(bet)}", reply_markup=kb)

@dp.callback_query(F.data.startswith("mines_cell_"))
async def mines_cell(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = MINES_GAMES.get(user_id)
    if not game:
        await callback.answer("Игра не найдена!", show_alert=True)
        return
    
    cell = int(callback.data.split("_")[2])
    if cell in game["opened"]:
        await callback.answer("Уже открыто!", show_alert=True)
        return
    
    if cell in game["mines"]:
        # Проигрыш
        for m in game["mines"]:
            game["field"][m] = "💣"
        game["field"][cell] = "💥"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=game["field"][i], callback_data="noop") for i in range(1, 4)],
            [InlineKeyboardButton(text=game["field"][i], callback_data="noop") for i in range(4, 7)],
            [InlineKeyboardButton(text=game["field"][i], callback_data="noop") for i in range(7, 10)]
        ])
        await callback.message.edit_text(f"💥 Мина! ❌ -{fmt_money(game['bet'])}", reply_markup=kb)
        record_game(user_id, "mines", game["bet"], 0, 0, "loss", {"mines": len(game["mines"]), "opened": len(game["opened"])})
        del MINES_GAMES[user_id]
    else:
        game["opened"].add(cell)
        game["field"][cell] = "✅"
        safe_total = 9 - game["mines_count"]
        
        if len(game["opened"]) >= safe_total:
            mult = mines_multiplier(len(game["opened"]), game["mines_count"])
            payout = int(game["bet"] * mult)
            add_pocx(user_id, payout)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=game["field"][i], callback_data="noop") for i in range(1, 4)],
                [InlineKeyboardButton(text=game["field"][i], callback_data="noop") for i in range(4, 7)],
                [InlineKeyboardButton(text=game["field"][i], callback_data="noop") for i in range(7, 10)]
            ])
            await callback.message.edit_text(f"🏁 Все безопасные!\n✅ +{fmt_money(payout)} (x{mult:.2f})", reply_markup=kb)
            record_game(user_id, "mines", game["bet"], mult, payout, "win", {"opened": len(game["opened"])})
            del MINES_GAMES[user_id]
        else:
            mult = mines_multiplier(len(game["opened"]), game["mines_count"])
            cur_win = int(game["bet"] * mult)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=game["field"][i], callback_data=f"mines_cell_{i}" if game["field"][i] == "❔" else "noop") for i in range(1, 4)],
                [InlineKeyboardButton(text=game["field"][i], callback_data=f"mines_cell_{i}" if game["field"][i] == "❔" else "noop") for i in range(4, 7)],
                [InlineKeyboardButton(text=game["field"][i], callback_data=f"mines_cell_{i}" if game["field"][i] == "❔" else "noop") for i in range(7, 10)],
                [InlineKeyboardButton(text=f"💰 Забрать ({fmt_money(cur_win)})", callback_data="mines_collect"),
                 InlineKeyboardButton(text="❌ Сдаться", callback_data="mines_cancel")]
            ])
            await callback.message.edit_text(
                f"💣 Мины | Открыто: {len(game['opened'])} | x{mult:.2f}\n"
                f"💰 Можно забрать: {fmt_money(cur_win)}",
                reply_markup=kb
            )
    await callback.answer()

@dp.callback_query(F.data == "mines_collect")
async def mines_collect(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = MINES_GAMES.get(user_id)
    if not game:
        await callback.answer("Игра не найдена!", show_alert=True)
        return
    
    mult = mines_multiplier(len(game["opened"]), game["mines_count"])
    payout = int(game["bet"] * mult)
    add_pocx(user_id, payout)
    record_game(user_id, "mines", game["bet"], mult, payout, "win", {"opened": len(game["opened"])})
    await callback.message.edit_text(f"💰 Забрано: {fmt_money(payout)} (x{mult:.2f})")
    del MINES_GAMES[user_id]
    await callback.answer()

@dp.callback_query(F.data == "mines_cancel")
async def mines_cancel(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = MINES_GAMES.get(user_id)
    if not game:
        await callback.answer("Игра не найдена!", show_alert=True)
        return
    
    if len(game["opened"]) == 0:
        add_pocx(user_id, game["bet"])
        await callback.message.edit_text(f"❌ Возврат: {fmt_money(game['bet'])}")
    else:
        await callback.message.edit_text(f"❌ Сдался, открыто: {len(game['opened'])}")
    del MINES_GAMES[user_id]
    await callback.answer()

@dp.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()

def mines_multiplier(opened: int, mines: int) -> float:
    if opened <= 0: return 1.0
    safe = 9 - mines
    base = 9.0 / max(1.0, safe)
    return round((base ** opened) * 0.95, 2)

# --- ОЧКО (ТОЛЬКО ЛС) ---
@dp.message(lambda m: m.text and m.text.lower().startswith("очко"))
async def ochko_start(message: Message):
    if is_group_chat(message):
        await message.reply("❌ Очко доступно только в ЛС!")
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("❌ Формат: <code>очко [ставка]</code>", parse_mode=ParseMode.HTML)
        return
    
    user = get_user(message.from_user.id)
    try:
        bet = parse_amount(parts[1])
        if bet < MIN_BET or bet > user["balance"]: raise ValueError
    except:
        await message.reply(f"❌ Ставка {MIN_BET}-{user['balance']}")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств!")
        return
    
    # Колода
    ranks = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
    suits = ["♠","♥","♦","♣"]
    deck = [(r, s) for r in ranks for s in suits]
    random.shuffle(deck)
    
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    
    game = {"bet": bet, "deck": deck, "player": player, "dealer": dealer}
    OCHKO_GAMES[message.from_user.id] = game
    
    pval = hand_value(player)
    if pval == 21:
        dval = hand_value(dealer)
        if dval == 21:
            add_pocx(message.from_user.id, bet)
            record_game(message.from_user.id, "ochko", bet, 1, bet, "push", {"player": pval, "dealer": dval})
            await message.answer(f"🎴 Ничья! Блэкджек у обоих\n💰 Возврат: {fmt_money(bet)}")
        else:
            payout = int(bet * 2.5)
            add_pocx(message.from_user.id, payout)
            record_game(message.from_user.id, "ochko", bet, 2.5, payout, "win", {"player": 21})
            await message.answer(f"🎴 Блэкджек!\n✅ +{fmt_money(payout)}")
        del OCHKO_GAMES[message.from_user.id]
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Взять", callback_data="ochko_hit"),
         InlineKeyboardButton(text="✋ Стоп", callback_data="ochko_stand")]
    ])
    dealer_text = f"{dealer[0][0]}{dealer[0][1]} ??"
    await message.answer(
        f"🎴 <b>Очко</b>\n"
        f"💰 Ставка: {fmt_money(bet)}\n\n"
        f"Дилер: {dealer_text}\n"
        f"Ты: {' '.join(f'{r}{s}' for r,s in player)} ({pval})",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "ochko_hit")
async def ochko_hit(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = OCHKO_GAMES.get(user_id)
    if not game:
        await callback.answer("Игра не найдена!", show_alert=True)
        return
    
    game["player"].append(game["deck"].pop())
    pval = hand_value(game["player"])
    
    if pval > 21:
        record_game(user_id, "ochko", game["bet"], 0, 0, "loss", {"player": pval, "dealer": hand_value(game["dealer"])})
        await callback.message.edit_text(f"💥 Перебор! {pval}\n❌ -{fmt_money(game['bet'])}")
        del OCHKO_GAMES[user_id]
    else:
        dealer_text = f"{game['dealer'][0][0]}{game['dealer'][0][1]} ??"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Взять", callback_data="ochko_hit"),
             InlineKeyboardButton(text="✋ Стоп", callback_data="ochko_stand")]
        ])
        await callback.message.edit_text(
            f"🎴 <b>Очко</b>\n"
            f"💰 Ставка: {fmt_money(game['bet'])}\n\n"
            f"Дилер: {dealer_text}\n"
            f"Ты: {' '.join(f'{r}{s}' for r,s in game['player'])} ({pval})",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    await callback.answer()

@dp.callback_query(F.data == "ochko_stand")
async def ochko_stand(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = OCHKO_GAMES.get(user_id)
    if not game:
        await callback.answer("Игра не найдена!", show_alert=True)
        return
    
    # Дилер добирает
    while hand_value(game["dealer"]) < 17:
        game["dealer"].append(game["deck"].pop())
    
    pval = hand_value(game["player"])
    dval = hand_value(game["dealer"])
    
    if dval > 21 or pval > dval:
        outcome = "win"
        mult = 2.0
    elif pval == dval:
        outcome = "push"
        mult = 1.0
    else:
        outcome = "loss"
        mult = 0.0
    
    payout = int(game["bet"] * mult)
    if payout > 0: add_pocx(user_id, payout)
    record_game(user_id, "ochko", game["bet"], mult, payout, outcome, {"player": pval, "dealer": dval})
    
    result_text = "Победа" if outcome == "win" else ("Ничья" if outcome == "push" else "Проигрыш")
    await callback.message.edit_text(
        f"🎴 <b>Очко</b>\n\n"
        f"Дилер: {' '.join(f'{r}{s}' for r,s in game['dealer'])} ({dval})\n"
        f"Ты: {' '.join(f'{r}{s}' for r,s in game['player'])} ({pval})\n\n"
        f"Результат: {result_text}\n"
        f"{'✅ +' + fmt_money(payout) if payout > 0 else '❌ -' + fmt_money(game['bet'])}\n"
        f"💳 Баланс: {fmt_money(get_user(user_id)['balance'])}",
        parse_mode=ParseMode.HTML
    )
    del OCHKO_GAMES[user_id]
    await callback.answer()

def hand_value(cards: list) -> int:
    total = 0
    aces = 0
    for r, s in cards:
        if r in ["J","Q","K"]: total += 10
        elif r == "A": total += 11; aces += 1
        else: total += int(r)
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total

# ==================== АДМИН-ПАНЕЛЬ (РАСШИРЕННАЯ) ====================
@dp.message(F.text == "👑 Админ")
async def admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    await message.answer("👑 <b>Админ-панель</b>", reply_markup=admin_menu() if is_private_chat(message) else None, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    users = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_bal = cursor.execute("SELECT SUM(balance) FROM users").fetchone()[0] or 0
    total_wag = cursor.execute("SELECT SUM(total_wagered) FROM users").fetchone()[0] or 0
    total_won = cursor.execute("SELECT SUM(total_won) FROM users").fetchone()[0] or 0
    total_lost = cursor.execute("SELECT SUM(total_lost) FROM users").fetchone()[0] or 0
    banned = cursor.execute("SELECT COUNT(*) FROM banned_users").fetchone()[0]
    deps = cursor.execute("SELECT COUNT(*) FROM bank_deposits WHERE status='active'").fetchone()[0]
    await callback.message.edit_text(
        f"📊 <b>Статистика</b>\n"
        f"👥 Игроков: {users}\n"
        f"🚫 Банов: {banned}\n"
        f"💰 Общий баланс: {fmt_money(total_bal)}\n"
        f"📊 Вейджер: {fmt_money(total_wag)}\n"
        f"🏆 Выиграно: {fmt_money(total_won)}\n"
        f"💸 Проиграно: {fmt_money(total_lost)}\n"
        f"📈 Прибыль: {fmt_money(total_lost - total_won)}\n"
        f"🏦 Депозитов: {deps}",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_give")
async def admin_give_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    await state.set_state(GameStates.admin_give)
    await callback.message.edit_text("💰 Введи ID и сумму через пробел:")
    await callback.answer()

@dp.message(GameStates.admin_give)
async def admin_give_exec(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("❌ ID СУММА")
        return
    uid = int(parts[0])
    amt = parse_amount(parts[1])
    add_pocx(uid, amt)
    admin_log(message.from_user.id, "give", uid, f"{amt}")
    await message.answer(f"✅ +{fmt_money(amt)} игроку {uid}")
    await state.clear()

@dp.callback_query(F.data == "admin_take")
async def admin_take_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    await state.set_state(GameStates.admin_take)
    await callback.message.edit_text("➖ Введи ID и сумму:")
    await callback.answer()

@dp.message(GameStates.admin_take)
async def admin_take_exec(message: Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) != 2: return
    uid, amt = int(parts[0]), parse_amount(parts[1])
    if remove_pocx(uid, amt):
        admin_log(message.from_user.id, "take", uid, f"{amt}")
        await message.answer(f"✅ -{fmt_money(amt)} у игрока {uid}")
    else:
        await message.answer("❌ Недостаточно средств!")
    await state.clear()

@dp.callback_query(F.data == "admin_ban")
async def admin_ban_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    await state.set_state(GameStates.admin_ban)
    await callback.message.edit_text("🔨 Введи ID [часы]:")
    await callback.answer()

@dp.message(GameStates.admin_ban)
async def admin_ban_exec(message: Message, state: FSMContext):
    parts = message.text.split()
    uid = int(parts[0])
    hours = int(parts[1]) if len(parts) > 1 else 0
    ban_user(uid, "", hours)
    admin_log(message.from_user.id, "ban", uid, f"{hours}h")
    await message.answer(f"✅ Игрок {uid} забанен" + (f" на {hours}ч" if hours else " навсегда"))
    await state.clear()

@dp.callback_query(F.data == "admin_unban")
async def admin_unban_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    await state.set_state(GameStates.admin_unban)
    await callback.message.edit_text("🔓 Введи ID:")
    await callback.answer()

@dp.message(GameStates.admin_unban)
async def admin_unban_exec(message: Message, state: FSMContext):
    uid = int(message.text)
    unban_user(uid)
    admin_log(message.from_user.id, "unban", uid)
    await message.answer(f"✅ Игрок {uid} разбанен")
    await state.clear()

@dp.callback_query(F.data == "admin_mute")
async def admin_mute_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    await state.set_state(GameStates.admin_mute)
    await callback.message.edit_text("🔇 Введи ID [часы, по умолчанию 24]:")
    await callback.answer()

@dp.message(GameStates.admin_mute)
async def admin_mute_exec(message: Message, state: FSMContext):
    parts = message.text.split()
    uid = int(parts[0])
    hours = int(parts[1]) if len(parts) > 1 else 24
    mute_user(uid, hours)
    admin_log(message.from_user.id, "mute", uid, f"{hours}h")
    await message.answer(f"✅ Игрок {uid} в муте на {hours}ч")
    await state.clear()

@dp.callback_query(F.data == "admin_unmute")
async def admin_unmute_cb(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    await callback.message.edit_text("🔊 Введи ID для размута:")
    await callback.answer()

@dp.callback_query(F.data == "admin_balance_set")
async def admin_balance_set_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    await state.set_state(GameStates.admin_balance_set)
    await callback.message.edit_text("💳 Введи ID и новый баланс:")
    await callback.answer()

@dp.message(GameStates.admin_balance_set)
async def admin_balance_set_exec(message: Message, state: FSMContext):
    parts = message.text.split()
    uid, amt = int(parts[0]), parse_amount(parts[1])
    cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (amt, uid))
    conn.commit()
    admin_log(message.from_user.id, "balance_set", uid, f"{amt}")
    await message.answer(f"✅ Баланс игрока {uid} установлен на {fmt_money(amt)}")
    await state.clear()

@dp.callback_query(F.data == "admin_msg")
async def admin_msg_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    await state.set_state(GameStates.admin_msg)
    await callback.message.edit_text("💬 Введи ID и сообщение:")
    await callback.answer()

@dp.message(GameStates.admin_msg)
async def admin_msg_exec(message: Message, state: FSMContext):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return
    uid = int(parts[0])
    try:
        await bot.send_message(uid, f"📨 <b>Сообщение от администрации:</b>\n\n{parts[1]}", parse_mode=ParseMode.HTML)
        await message.answer(f"✅ Сообщение отправлено игроку {uid}")
    except:
        await message.answer(f"❌ Не удалось отправить сообщение игроку {uid}")
    await state.clear()

@dp.callback_query(F.data == "admin_search")
async def admin_search_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    await state.set_state(GameStates.admin_search)
    await callback.message.edit_text("🔍 Введи ID или username:")
    await callback.answer()

@dp.message(GameStates.admin_search)
async def admin_search_exec(message: Message, state: FSMContext):
    query = message.text.strip()
    user = None
    if query.isdigit():
        user = get_user(int(query))
    else:
        row = cursor.execute("SELECT user_id FROM users WHERE username = ?", (query.lstrip("@"),)).fetchone()
        if row: user = get_user(row[0])
    
    if not user:
        await message.answer("❌ Игрок не найден!")
    else:
        vip, _ = get_vip(user["total_wagered"])
        await message.answer(
            f"👤 <b>{user['username'] or 'Нет'}</b>\n"
            f"🆔 ID: {user['user_id']}\n"
            f"💰 Баланс: {fmt_money(user['balance'])}\n"
            f"💎 VIP: {vip}\n"
            f"📊 Вейджер: {fmt_money(user['total_wagered'])}\n"
            f"🏆 Выиграно: {fmt_money(user['total_won'])}\n"
            f"🚫 Бан: {'Да' if is_banned(user['user_id']) else 'Нет'}\n"
            f"🔇 Мут: {'Да' if is_muted(user['user_id']) else 'Нет'}",
            parse_mode=ParseMode.HTML
        )
    await state.clear()

@dp.callback_query(F.data == "admin_mass_bonus")
async def admin_mass_bonus(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    users = cursor.execute("SELECT user_id FROM users").fetchall()
    bonus = random.randint(100, 1000)
    count = 0
    for u in users:
        add_pocx(u[0], bonus)
        count += 1
    await callback.message.edit_text(f"🎁 Всем {count} игрокам выдано по {fmt_money(bonus)}!")
    await callback.answer()

@dp.callback_query(F.data == "admin_promo_list")
async def admin_promo_list(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    rows = cursor.execute("SELECT code, bonus_amount, used_count, max_uses, is_active FROM promocodes ORDER BY id DESC LIMIT 15").fetchall()
    if not rows:
        await callback.message.edit_text("📋 Нет промокодов")
    else:
        text = "📋 <b>Промокоды</b>\n\n"
        for r in rows:
            status = "✅" if r[4] else "❌"
            text += f"{status} <code>{r[0]}</code> | {fmt_money(r[1])} | {r[2]}/{r[3]}\n"
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_menu())
    await callback.answer()

@dp.callback_query(F.data == "admin_top100")
async def admin_top100(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    rows = cursor.execute("SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT 100").fetchall()
    text = "👥 <b>Топ-100 по балансу</b>\n\n"
    for i, r in enumerate(rows[:20], 1):
        name = r[1] or f"ID{r[0]}"
        text += f"{i}. {name} — {fmt_money(r[2])}\n"
    text += f"\n... и ещё {len(rows)-20}"
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_menu())
    await callback.answer()

@dp.callback_query(F.data == "admin_analytics")
async def admin_analytics(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    # Статистика по играм
    games = cursor.execute("SELECT game_type, COUNT(*), SUM(win_amount), SUM(bet_amount) FROM game_history GROUP BY game_type").fetchall()
    text = "📈 <b>Аналитика по играм</b>\n\n"
    for g in games:
        profit = g[3] - g[2]
        text += f"🎮 {g[0]}: {g[1]} игр, прибыль {fmt_money(profit)}\n"
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_menu())
    await callback.answer()

@dp.callback_query(F.data == "admin_cleanup")
async def admin_cleanup(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    # Очистка старых игр (старше 30 дней)
    thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
    deleted = cursor.execute("DELETE FROM game_history WHERE created_at < ?", (thirty_days_ago,)).rowcount
    conn.commit()
    await callback.message.edit_text(f"🧹 Удалено {deleted} старых записей игр!", reply_markup=admin_menu())
    await callback.answer()

@dp.callback_query(F.data == "admin_promo")
async def admin_promo_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    await state.set_state(GameStates.admin_promo_code)
    await callback.message.edit_text("🎟 Введи код промокода:")
    await callback.answer()

@dp.message(GameStates.admin_promo_code)
async def admin_promo_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    if len(code) < 3 or len(code) > 24:
        await message.answer("❌ 3-24 символа!")
        return
    await state.update_data(promo_code=code)
    await state.set_state(GameStates.admin_promo_reward)
    await message.answer("💰 Сумма награды:")

@dp.message(GameStates.admin_promo_reward)
async def admin_promo_reward(message: Message, state: FSMContext):
    try:
        reward = int(message.text)
        if reward <= 0: raise ValueError
    except:
        await message.answer("❌ Положительное число!")
        return
    await state.update_data(promo_reward=reward)
    await state.set_state(GameStates.admin_promo_uses)
    await message.answer("🔢 Количество активаций:")

@dp.message(GameStates.admin_promo_uses)
async def admin_promo_uses(message: Message, state: FSMContext):
    try:
        uses = int(message.text)
        if uses <= 0: raise ValueError
    except:
        await message.answer("❌ Число > 0!")
        return
    data = await state.get_data()
    cursor.execute("INSERT INTO promocodes (code, bonus_amount, max_uses, is_active) VALUES (?, ?, ?, 1)", (data["promo_code"], data["promo_reward"], uses))
    conn.commit()
    await message.answer(f"✅ Промокод <code>{data['promo_code']}</code> создан!\n💰 {fmt_money(data['promo_reward'])} x{uses}", parse_mode=ParseMode.HTML)
    await state.clear()

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    await state.set_state(GameStates.admin_broadcast)
    await callback.message.edit_text("📢 Введи текст рассылки:")
    await callback.answer()

@dp.message(GameStates.admin_broadcast)
async def admin_broadcast_exec(message: Message, state: FSMContext):
    users = cursor.execute("SELECT user_id FROM users").fetchall()
    sent = 0
    for u in users:
        try:
            await bot.send_message(u[0], f"📢 <b>Рассылка</b>\n\n{message.text}", parse_mode=ParseMode.HTML)
            sent += 1
            await asyncio.sleep(0.05)
        except: pass
    await message.answer(f"✅ Отправлено {sent}/{len(users)}")
    await state.clear()

@dp.callback_query(F.data == "admin_status")
async def admin_status_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    await state.set_state(GameStates.admin_status)
    await callback.message.edit_text("👑 Введи ID и статус:")
    await callback.answer()

@dp.message(GameStates.admin_status)
async def admin_status_exec(message: Message, state: FSMContext):
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2: return
    uid = int(parts[0])
    cursor.execute("UPDATE users SET custom_status = ? WHERE user_id = ?", (parts[1][:50], uid))
    conn.commit()
    await message.answer(f"✅ Статус игрока {uid}: {parts[1][:50]}")
    await state.clear()

@dp.callback_query(F.data == "admin_treasury")
async def admin_treasury_cb(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    await callback.message.edit_text("🏦 Управление казной", reply_markup=treasury_admin_menu())
    await callback.answer()

@dp.callback_query(F.data == "treasury_add")
async def treasury_add_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    await state.set_state(GameStates.treasury_add)
    await callback.message.edit_text("💰 Введи ID чата и сумму:")
    await callback.answer()

@dp.message(GameStates.treasury_add)
async def treasury_add_exec(message: Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) != 2: return
    chat_id, amt = int(parts[0]), parse_amount(parts[1])
    add_to_chat_treasury(chat_id, amt)
    await message.answer(f"✅ +{fmt_money(amt)} в казну чата {chat_id}")
    await state.clear()

@dp.callback_query(F.data == "treasury_withdraw")
async def treasury_withdraw_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    await state.set_state(GameStates.treasury_withdraw)
    await callback.message.edit_text("💸 Введи ID чата и сумму:")
    await callback.answer()

@dp.message(GameStates.treasury_withdraw)
async def treasury_withdraw_exec(message: Message, state: FSMContext):
    parts = message.text.split()
    chat_id, amt = int(parts[0]), parse_amount(parts[1])
    if remove_from_chat_treasury(chat_id, amt):
        add_pocx(message.from_user.id, amt)
        await message.answer(f"✅ -{fmt_money(amt)} из казны чата {chat_id}")
    else:
        await message.answer("❌ Недостаточно средств!")
    await state.clear()

@dp.callback_query(F.data == "treasury_set_reward")
async def treasury_set_reward_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    await state.set_state(GameStates.treasury_reward_set)
    await callback.message.edit_text("⚙️ Введи ID чата и награду:")
    await callback.answer()

@dp.message(GameStates.treasury_reward_set)
async def treasury_set_reward_exec(message: Message, state: FSMContext):
    parts = message.text.split()
    chat_id, reward = int(parts[0]), parse_amount(parts[1])
    cursor.execute("UPDATE chat_treasury SET reward_per_invite = ? WHERE chat_id = ?", (reward, chat_id))
    conn.commit()
    await message.answer(f"✅ Награда за приглашение в чате {chat_id}: {reward} POCX")
    await state.clear()

@dp.callback_query(F.data == "treasury_stats")
async def treasury_stats_cb(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("❌", show_alert=True)
    rows = cursor.execute("SELECT chat_id, owner_id, balance, reward_per_invite, is_active FROM chat_treasury").fetchall()
    if not rows:
        await callback.message.edit_text("📊 Нет активных казн")
    else:
        text = "📊 <b>Казны чатов</b>\n\n"
        for r in rows:
            rewards = cursor.execute("SELECT COUNT(*) FROM treasury_rewards WHERE chat_id = ?", (r[0],)).fetchone()[0]
            text += f"🏦 Чат {r[0]}: {fmt_money(r[2])} | {rewards} наград\n"
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=treasury_admin_menu())
    await callback.answer()

# ==================== ТЕКСТОВЫЕ КОМАНДЫ ДЛЯ ЧАТОВ ====================
@dp.message(lambda m: m.text and m.text.lower().strip() in ["б", "баланс"])
async def text_balance(message: Message):
    user = get_user(message.from_user.id)
    await message.reply(f"💰 {fmt_money(user['balance'])}", parse_mode=ParseMode.HTML)

@dp.message(lambda m: m.text and m.text.lower().strip() in ["п", "профиль"])
async def text_profile(message: Message):
    user = get_user(message.from_user.id)
    vip, _ = get_vip(user["total_wagered"])
    await message.reply(f"👤 {message.from_user.first_name}\n💰 {fmt_money(user['balance'])}\n💎 {vip}", parse_mode=ParseMode.HTML)

@dp.message(lambda m: m.text and m.text.lower().strip() in ["т", "топ"])
async def text_top(message: Message):
    rows = cursor.execute("SELECT username, total_won FROM users ORDER BY total_won DESC LIMIT 5").fetchall()
    text = "🏆 Топ:\n"
    medals = ["🥇","🥈","🥉"]
    for i, r in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = r[0] or f"ID{r[0]}"
        text += f"{medal} {name} — {fmt_money(r[1])}\n"
    await message.reply(text, parse_mode=ParseMode.HTML)

@dp.message(lambda m: m.text and m.text.lower().strip() in ["бн", "бонус"])
async def text_bonus(message: Message):
    uid = message.from_user.id
    row = cursor.execute("SELECT last_daily_bonus, daily_streak FROM users WHERE user_id = ?", (uid,)).fetchone()
    last = row[0] if row else None
    streak = row[1] if row else 0
    if last and datetime.now() - datetime.fromisoformat(last) < timedelta(days=1):
        await message.reply("❌ Уже получен!")
        return
    bonus = int(random.randint(DAILY_BONUS_MIN, DAILY_BONUS_MAX) * (1 + min(streak*0.05, 0.5)))
    add_pocx(uid, bonus)
    cursor.execute("UPDATE users SET last_daily_bonus=CURRENT_TIMESTAMP, daily_streak=daily_streak+1 WHERE user_id=?", (uid,))
    conn.commit()
    await message.reply(f"🎁 +{bonus:,} | Серия: {streak+1} дн.", parse_mode=ParseMode.HTML)

# ==================== ЕЖЕЧАСНЫЙ БОНУС ====================
async def hourly_active_bonus():
    while True:
        await asyncio.sleep(3600)
        row = cursor.execute("SELECT user_id, games_played_today FROM users ORDER BY games_played_today DESC LIMIT 1").fetchone()
        if row and row[1] > 0:
            bonus = random.randint(1000, 10000)
            add_pocx(row[0], bonus)
            try:
                await bot.send_message(row[0], f"🎁 Самый активный за час!\n🎮 Игр: {row[1]}\n💰 +{bonus:,} POCX")
            except: pass
            cursor.execute("UPDATE users SET games_played_today = 0")
            conn.commit()

# ==================== ЗАПУСК ====================
async def main():
    print("🤖 POCX Casino Bot запущен!")
    print("✅ 11 игр, банк, чеки, промокоды, казна, донаты, рефералы")
    print("✅ Админка расширенная: мут, поиск, масс-бонус, очистка, аналитика")
    print("✅ Группы: текстовые команды | ЛС: полный функционал")
    asyncio.create_task(hourly_active_bonus())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
