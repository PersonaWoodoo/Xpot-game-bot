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
HOUSE_EDGE = 0.01

DAILY_BONUS_MIN = 100
DAILY_BONUS_MAX = 2000
WELCOME_BONUS = 1000
REF_REWARD = 5000
REF_REFERRAL_BONUS = 500

# Банковские проценты (мизерные, чтобы не было дюпа)
BANK_TERMS = {
    7: 0.01,    # 1% за 7 дней
    14: 0.02,   # 2% за 14 дней
    30: 0.05,   # 5% за 30 дней
}

# Каналы для подписки
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

# Коэффициенты для игр
TOWER_MULTIPLIERS = [1.20, 1.48, 1.86, 2.35, 2.95, 3.75, 4.85, 6.15]
GOLD_MULTIPLIERS = [1.15, 1.35, 1.62, 2.0, 2.55, 3.25, 4.2]
DIAMOND_MULTIPLIERS = [1.12, 1.28, 1.48, 1.72, 2.02, 2.4, 2.92, 3.6]
LEGACY_GOLD_MULTIPLIERS = [2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]
RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
FOOTBALL_MULTIPLIERS = {"gol": 1.6, "mimo": 2.2}

bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# ==================== БАЗА ДАННЫХ ====================
conn = sqlite3.connect("pocx_bot.db", check_same_thread=False)
cursor = conn.cursor()

# Пользователи
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance INTEGER DEFAULT 5000,
    total_wagered INTEGER DEFAULT 0,
    total_won INTEGER DEFAULT 0,
    total_lost INTEGER DEFAULT 0,
    referral_code TEXT UNIQUE,
    referrer_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_daily_bonus TIMESTAMP,
    welcome_bonus_claimed BOOLEAN DEFAULT 0,
    daily_streak INTEGER DEFAULT 0,
    last_game_time INTEGER DEFAULT 0,
    custom_status TEXT DEFAULT NULL,
    games_played_today INTEGER DEFAULT 0,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# История игр
cursor.execute("""
CREATE TABLE IF NOT EXISTS game_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    game_type TEXT,
    bet_amount INTEGER,
    multiplier REAL,
    win_amount INTEGER,
    result TEXT,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# Рефералы
cursor.execute("""
CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id INTEGER,
    referred_id INTEGER,
    earned_amount INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# Забаненные
cursor.execute("""
CREATE TABLE IF NOT EXISTS banned_users (
    user_id INTEGER PRIMARY KEY,
    banned_at INTEGER,
    reason TEXT
)
""")

# Промокоды
cursor.execute("""
CREATE TABLE IF NOT EXISTS promocodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE,
    bonus_amount INTEGER,
    max_uses INTEGER,
    used_count INTEGER DEFAULT 0,
    expires_at TIMESTAMP,
    is_active BOOLEAN DEFAULT 1
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS used_promocodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    code TEXT,
    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# Чеки
cursor.execute("""
CREATE TABLE IF NOT EXISTS checks (
    code TEXT PRIMARY KEY,
    creator_id INTEGER,
    per_user INTEGER,
    remaining INTEGER,
    used TEXT,
    password TEXT
)
""")

# Банковские депозиты
cursor.execute("""
CREATE TABLE IF NOT EXISTS bank_deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    principal INTEGER,
    rate REAL,
    term_days INTEGER,
    opened_at INTEGER,
    status TEXT DEFAULT 'active',
    closed_at INTEGER
)
""")

# Казны чатов
cursor.execute("""
CREATE TABLE IF NOT EXISTS chat_treasury (
    chat_id INTEGER PRIMARY KEY,
    owner_id INTEGER,
    balance INTEGER DEFAULT 0,
    reward_per_invite INTEGER DEFAULT 100,
    is_active BOOLEAN DEFAULT 0,
    purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# Награждённые за приглашения
cursor.execute("""
CREATE TABLE IF NOT EXISTS treasury_rewards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    user_id INTEGER,
    invited_by INTEGER,
    rewarded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chat_id, user_id)
)
""")

conn.commit()
print("✅ База данных готова")

# ==================== ИГРОВЫЕ СЕССИИ ====================
TOWER_GAMES: Dict[int, Dict[str, Any]] = {}
GOLD_GAMES: Dict[int, Dict[str, Any]] = {}
DIAMOND_GAMES: Dict[int, Dict[str, Any]] = {}
MINES_GAMES: Dict[int, Dict[str, Any]] = {}
OCHKO_GAMES: Dict[int, Dict[str, Any]] = {}

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def parse_amount(text: str) -> int:
    text = text.lower().strip()
    mults = {'ккк': 1_000_000_000, 'кк': 1_000_000, 'к': 1_000,
             'kkk': 1_000_000_000, 'kk': 1_000_000, 'k': 1_000,
             'm': 1_000_000, 'b': 1_000_000_000}
    for suf, m in mults.items():
        if text.endswith(suf):
            num = text[:-len(suf)] or '1'
            try:
                return int(float(num) * m)
            except:
                return 0
    try:
        return int(text)
    except:
        return 0

def fmt_money(value: int) -> str:
    if value >= 1_000_000_000:
        return f"{value/1_000_000_000:.1f}ккк POCX"
    if value >= 1_000_000:
        return f"{value/1_000_000:.1f}кк POCX"
    if value >= 1_000:
        return f"{value/1_000:.1f}к POCX"
    return f"{value} POCX"

def add_pocx(user_id: int, amount: int):
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    if cursor.rowcount == 0:
        cursor.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, 5000))
    conn.commit()

def remove_pocx(user_id: int, amount: int) -> bool:
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    if not res or res[0] < amount:
        return False
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    return True

def get_user(user_id: int) -> dict:
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "user_id": row[0],
        "username": row[1],
        "balance": row[2],
        "total_wagered": row[3],
        "total_won": row[4],
        "total_lost": row[5],
        "referral_code": row[6],
        "referrer_id": row[7],
        "daily_streak": row[11] or 0,
        "welcome_bonus_claimed": row[10],
        "custom_status": row[13],
        "games_played_today": row[14] or 0,
        "last_activity": row[15],
    }

def get_vip(wagered: int) -> tuple:
    for lvl in reversed(VIP_LEVELS):
        if wagered >= lvl[1]:
            return lvl[0], lvl[2]
    return VIP_LEVELS[0][0], 0

def check_cooldown(user_id: int) -> bool:
    cursor.execute("SELECT last_game_time FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    now = int(time.time())
    if res and res[0] and now - res[0] < 5:
        return False
    cursor.execute("UPDATE users SET last_game_time = ? WHERE user_id = ?", (now, user_id))
    if cursor.rowcount == 0:
        cursor.execute("INSERT INTO users (user_id, last_game_time) VALUES (?, ?)", (user_id, now))
    conn.commit()
    return True

def is_banned(user_id: int) -> bool:
    cursor.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,))
    return cursor.fetchone() is not None

def ban_user(user_id: int, reason: str = ""):
    cursor.execute("INSERT OR IGNORE INTO banned_users (user_id, banned_at, reason) VALUES (?, ?, ?)",
                   (user_id, int(time.time()), reason))
    conn.commit()

def unban_user(user_id: int):
    cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
    conn.commit()

def record_game(user_id: int, game_type: str, bet: int, mult: float, win: int, result: str, details: dict):
    cursor.execute("""
        UPDATE users SET 
            total_wagered = total_wagered + ?,
            total_won = total_won + ?,
            total_lost = total_lost + ?,
            games_played_today = games_played_today + 1,
            last_activity = CURRENT_TIMESTAMP
        WHERE user_id = ?
    """, (bet, win if result == "win" else 0, bet if result == "loss" else 0, user_id))
    cursor.execute("""
        INSERT INTO game_history (user_id, game_type, bet_amount, multiplier, win_amount, result, details)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, game_type, bet, mult, win, result, json.dumps(details)))
    conn.commit()

def update_activity(user_id: int):
    cursor.execute("UPDATE users SET last_activity = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
    conn.commit()

# ==================== БАНКОВСКИЕ ФУНКЦИИ ====================
def add_deposit(user_id: int, amount: int, term_days: int) -> tuple[bool, str]:
    rate = BANK_TERMS.get(term_days)
    if rate is None:
        return False, "Неверный срок депозита."
    if not remove_pocx(user_id, amount):
        return False, "Недостаточно средств."
    cursor.execute("""
        INSERT INTO bank_deposits (user_id, principal, rate, term_days, opened_at, status)
        VALUES (?, ?, ?, ?, ?, 'active')
    """, (user_id, amount, rate, term_days, int(time.time())))
    conn.commit()
    return True, f"Депозит открыт на {term_days} дней под {int(rate*100)}% годовых."

def list_user_deposits(user_id: int) -> list:
    cursor.execute("SELECT * FROM bank_deposits WHERE user_id = ? AND status = 'active' ORDER BY id DESC", (user_id,))
    return cursor.fetchall()

def check_and_withdraw_deposits(user_id: int) -> tuple[int, int]:
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

# ==================== КАЗНА ДЛЯ ЧАТОВ ====================
def get_chat_treasury(chat_id: int) -> dict:
    cursor.execute("SELECT * FROM chat_treasury WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "chat_id": row[0],
        "owner_id": row[1],
        "balance": row[2],
        "reward_per_invite": row[3],
        "is_active": row[4],
        "purchased_at": row[5],
    }

def activate_treasury(chat_id: int, owner_id: int) -> bool:
    if not remove_pocx(owner_id, 15000):
        return False
    cursor.execute("""
        INSERT OR REPLACE INTO chat_treasury (chat_id, owner_id, balance, is_active, reward_per_invite)
        VALUES (?, ?, ?, 1, 100)
    """, (chat_id, owner_id, 15000))
    conn.commit()
    return True

def add_to_chat_treasury(chat_id: int, amount: int):
    cursor.execute("UPDATE chat_treasury SET balance = balance + ? WHERE chat_id = ?", (amount, chat_id))
    conn.commit()

def remove_from_chat_treasury(chat_id: int, amount: int) -> bool:
    treasury = get_chat_treasury(chat_id)
    if not treasury or treasury["balance"] < amount:
        return False
    cursor.execute("UPDATE chat_treasury SET balance = balance - ? WHERE chat_id = ?", (amount, chat_id))
    conn.commit()
    return True

def set_treasury_reward(chat_id: int, reward: int):
    cursor.execute("UPDATE chat_treasury SET reward_per_invite = ? WHERE chat_id = ?", (reward, chat_id))
    conn.commit()

def is_user_rewarded(chat_id: int, user_id: int) -> bool:
    cursor.execute("SELECT 1 FROM treasury_rewards WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
    return cursor.fetchone() is not None

def mark_user_rewarded(chat_id: int, user_id: int, invited_by: int):
    cursor.execute("INSERT OR IGNORE INTO treasury_rewards (chat_id, user_id, invited_by) VALUES (?, ?, ?)",
                   (chat_id, user_id, invited_by))
    conn.commit()

# ==================== АКТИВНЫЙ ИГРОК (ЕЖЕЧАСНЫЙ БОНУС) ====================
async def hourly_active_bonus():
    while True:
        await asyncio.sleep(3600)  # 1 час
        # Находим самого активного игрока за последний час
        hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
        cursor.execute("""
            SELECT user_id, games_played_today FROM users 
            WHERE last_activity > ? 
            ORDER BY games_played_today DESC LIMIT 1
        """, (hour_ago,))
        row = cursor.fetchone()
        if row:
            user_id, games = row
            bonus = random.randint(1000, 10000)
            add_pocx(user_id, bonus)
            try:
                await bot.send_message(user_id, f"🎁 <b>Вы самый активный игрок за последний час!</b>\n\n🎮 Сыграно игр: {games}\n💰 Бонус: +{bonus:,} POCX", parse_mode=ParseMode.HTML)
            except:
                pass
            # Сбрасываем счётчик игр
            cursor.execute("UPDATE users SET games_played_today = 0 WHERE user_id = ?", (user_id,))
            conn.commit()
        else:
            # Если нет активных игроков, даём бонус случайному
            cursor.execute("SELECT user_id FROM users ORDER BY RANDOM() LIMIT 1")
            row = cursor.fetchone()
            if row:
                bonus = random.randint(1000, 10000)
                add_pocx(row[0], bonus)
                try:
                    await bot.send_message(row[0], f"🎁 <b>Ежечасный бонус!</b>\n\n💰 +{bonus:,} POCX", parse_mode=ParseMode.HTML)
                except:
                    pass

# ==================== ПРОВЕРКА ПОДПИСКИ ====================
async def check_subscription(user_id: int) -> tuple[bool, list]:
    not_subscribed = []
    for ch in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=ch["chat_id"], user_id=user_id)
            if member.status in ["left", "kicked"]:
                not_subscribed.append(ch)
        except:
            not_subscribed.append(ch)
    return len(not_subscribed) == 0, not_subscribed

def subscription_keyboard(not_subscribed: list) -> InlineKeyboardMarkup:
    kb = []
    for ch in not_subscribed:
        kb.append([InlineKeyboardButton(text=f"📢 Подписаться на {ch['name']}", url=ch["link"])])
    kb.append([InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ==================== КЛАВИАТУРЫ ====================
def is_private(msg: Message) -> bool:
    return msg.chat.type == "private"

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎮 Игры"), KeyboardButton(text="💰 Финансы")],
            [KeyboardButton(text="🏆 Топ"), KeyboardButton(text="🎁 Бонусы")],
            [KeyboardButton(text="👥 Рефералы"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🏦 Банк")],
            [KeyboardButton(text="👑 Админ"), KeyboardButton(text="🏦 Казна")]
        ],
        resize_keyboard=True
    )

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
         InlineKeyboardButton(text="🔙 Назад", callback_data="main")]
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_row_width=2, inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
         InlineKeyboardButton(text="💰 Выдать POCX", callback_data="admin_give")],
        [InlineKeyboardButton(text="➖ Забрать POCX", callback_data="admin_take"),
         InlineKeyboardButton(text="🔨 Забанить", callback_data="admin_ban")],
        [InlineKeyboardButton(text="🔓 Разбанить", callback_data="admin_unban"),
         InlineKeyboardButton(text="🎟 Создать промокод", callback_data="admin_promo")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"),
         InlineKeyboardButton(text="👑 Назначить статус", callback_data="admin_status")],
        [InlineKeyboardButton(text="🏦 Управление казной", callback_data="admin_treasury"),
         InlineKeyboardButton(text="🔙 Назад", callback_data="main")]
    ])

def treasury_admin_menu():
    return InlineKeyboardMarkup(inline_row_width=2, inline_keyboard=[
        [InlineKeyboardButton(text="➕ Пополнить казну", callback_data="treasury_add"),
         InlineKeyboardButton(text="💸 Вывести из казны", callback_data="treasury_withdraw")],
        [InlineKeyboardButton(text="⚙️ Настроить награду", callback_data="treasury_set_reward"),
         InlineKeyboardButton(text="📊 Статистика казны", callback_data="treasury_stats")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])

def cancel_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )

# ==================== FSM ====================
class GameStates(StatesGroup):
    tower_bet = State()
    gold_bet = State()
    diamond_bet = State()
    mines_bet = State()
    mines_mines = State()
    ochko_confirm = State()
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
    promo_code = State()
    bank_deposit_amount = State()
    bank_deposit_term = State()
    treasury_reward_set = State()
    treasury_add = State()
    treasury_withdraw = State()

# ==================== ПРИВЕТСТВИЕ ПРИ ДОБАВЛЕНИИ В ЧАТ ====================
@dp.chat_member()
async def on_bot_added_to_chat(event: ChatMemberUpdated):
    if event.new_chat_member.user.id == (await bot.get_me()).id:
        if event.new_chat_member.status == "member" and event.old_chat_member.status != "member":
            await bot.send_message(
                event.chat.id,
                "🤖 <b>Бот успешно добавлен в чат!</b>\n\n"
                "📋 <b>Доступные команды в чате:</b>\n"
                "• <code>б</code> или <code>баланс</code> – показать баланс\n"
                "• <code>п</code> или <code>профиль</code> – профиль\n"
                "• <code>т</code> или <code>топ</code> – топ игроков\n"
                "• <code>р</code> или <code>рефералы</code> – рефералы\n"
                "• <code>бн</code> или <code>бонус</code> – ежедневный бонус\n"
                "• <code>ст</code> или <code>статистика</code> – статистика\n"
                "• <code>и</code> или <code>игры</code> – список игр\n\n"
                "🎮 <b>Игровые команды:</b>\n"
                "• <code>башня 1000 2</code> – Башня (ставка, бомбы 1-3)\n"
                "• <code>золото 1000</code> – Золото\n"
                "• <code>алмазы 1000 2</code> – Алмазы\n"
                "• <code>мины 1000 3</code> – Мины (ставка, кол-во мин)\n"
                "• <code>очко 1000</code> – Очко\n"
                "• <code>рул 1000 красное</code> – Рулетка\n"
                "• <code>краш 1000 2.5</code> – Краш (ставка, множитель)\n"
                "• <code>кубик 1000 5</code> – Кубик\n"
                "• <code>кости 1000 м</code> – Кости (м/б/равно)\n"
                "• <code>футбол 1000 гол</code> – Футбол\n"
                "• <code>баскет 1000</code> – Баскет\n\n"
                "💰 Сокращения ставок: 1к=1000, 1кк=1_000_000\n\n"
                "❓ Для помощи в ЛС напишите <code>/start</code>",
                parse_mode=ParseMode.HTML
            )

# ==================== MIDDLEWARE ====================
@dp.callback_query()
async def sub_middleware(callback: CallbackQuery):
    if callback.data in ["check_subscription"]:
        return
    if is_banned(callback.from_user.id):
        await callback.answer("❌ Вы забанены!", show_alert=True)
        return
    ok, _ = await check_subscription(callback.from_user.id)
    if not ok:
        await callback.answer("❓ Подпишитесь на каналы!", show_alert=True)
        return

@dp.callback_query(F.data == "check_subscription")
async def check_sub(callback: CallbackQuery):
    ok, not_sub = await check_subscription(callback.from_user.id)
    if ok:
        await callback.message.delete()
        await callback.message.answer("✅ Спасибо за подписку!", reply_markup=main_menu())
    else:
        await callback.message.edit_text("❓ Подпишитесь на каналы:", reply_markup=subscription_keyboard(not_sub))
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
    if len(args) > 1 and args[1].startswith("ref"):
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
                # Уведомление о новом реферале
                await bot.send_message(ref[0], f"👥 <b>Новый реферал!</b>\n\n🆔 ID: {uid}\n👤 Username: @{uname or 'нет'}\n💰 Начислено: +{REF_REWARD:,} POCX\n💎 Ваш баланс: {get_user(ref[0])['balance']:,} POCX", parse_mode=ParseMode.HTML)
    ok, not_sub = await check_subscription(uid)
    if not ok:
        await message.answer("❓ Подпишитесь на каналы:", reply_markup=subscription_keyboard(not_sub))
        return
    vip, _ = get_vip(user["total_wagered"])
    await message.answer(
        f"🎰 <b>POCX Casino Bot</b>\n\n"
        f"💰 Баланс: <b>{user['balance']:,} POCX</b>\n"
        f"💎 VIP: {vip}\n\n"
        f"🎮 Игры: Башня • Золото • Алмазы • Мины • Очко • Рулетка • Краш • Кубик • Кости • Футбол • Баскет\n\n"
        f"⭐ 1 Star = 2500 POCX\n"
        f"🔥 КД 5 сек\n\n"
        f"👥 Рефералка:\n<code>https://t.me/{(await bot.get_me()).username}?start=ref{user['referral_code']}</code>\n\n"
        f"🎁 За друга: +{REF_REWARD:,} вам, +{REF_REFERRAL_BONUS:,} другу",
        reply_markup=main_menu() if is_private(message) else None
    )

# ==================== ОСНОВНЫЕ МЕНЮ ====================
@dp.message(F.text == "◀️ Главное меню")
async def back_main(message: Message):
    user = get_user(message.from_user.id)
    vip, _ = get_vip(user["total_wagered"])
    await message.answer(
        f"🎰 <b>Главное меню</b>\n\n💰 Баланс: <b>{user['balance']:,} POCX</b> | {vip}",
        reply_markup=main_menu()
    )

@dp.message(F.text == "🎮 Игры")
async def games(message: Message):
    await message.answer("🎮 <b>Выбери игру</b>", reply_markup=games_menu())

@dp.message(F.text == "💰 Финансы")
async def finance(message: Message):
    await message.answer("💰 <b>Финансы</b>\n\n⭐ 1 Star = 2500 POCX")
    # Отправляем инлайн-кнопки для доната
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 1 Star - 2,500 POCX", callback_data="donate_1")],
        [InlineKeyboardButton(text="⭐⭐ 5 Stars - 12,500 POCX", callback_data="donate_5")],
        [InlineKeyboardButton(text="⭐⭐⭐ 10 Stars - 25,000 POCX", callback_data="donate_10")],
        [InlineKeyboardButton(text="💰 25 Stars - 62,500 POCX", callback_data="donate_25")],
        [InlineKeyboardButton(text="💎 50 Stars - 125,000 POCX", callback_data="donate_50")],
        [InlineKeyboardButton(text="✏️ Своя сумма", callback_data="donate_custom")]
    ])
    await message.answer("💎 <b>Пополнение через Telegram Stars</b>", reply_markup=kb)

@dp.message(F.text == "🏆 Топ")
async def top(message: Message):
    # Глобальный топ
    cursor.execute("SELECT user_id, username, total_won FROM users ORDER BY total_won DESC LIMIT 10")
    rows = cursor.fetchall()
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Топ игроков (глобальный)</b>\n"]
    for i, row in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = row[1] or f"ID{row[0]}"
        lines.append(f"{medal} {name} — <b>{row[2]:,} POCX</b>")
    # Топ в чате (если команда в чате)
    if not is_private(message):
        cursor.execute("SELECT user_id, username, total_won FROM users WHERE user_id IN (SELECT user_id FROM users) ORDER BY total_won DESC LIMIT 10")
        rows2 = cursor.fetchall()
        lines.append("\n🏆 <b>Топ игроков в этом чате</b>\n")
        for i, row in enumerate(rows2[:5]):
            medal = medals[i] if i < 3 else f"{i+1}."
            name = row[1] or f"ID{row[0]}"
            lines.append(f"{medal} {name} — <b>{row[2]:,} POCX</b>")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

@dp.message(F.text == "🎁 Бонусы")
async def bonuses(message: Message):
    await message.answer(
        "🎁 <b>Бонусы</b>\n\n"
        "• 🎁 Ежедневный бонус: 100-2000 POCX\n"
        "• 🆕 Приветственный бонус: 1000 POCX\n"
        "• 👥 За реферала: 5000 POCX вам, 500 другу\n"
        "• 🏆 Ежечасный бонус активному игроку: 1000-10000 POCX",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🎁 Ежедневный бонус"), KeyboardButton(text="🆕 Приветственный бонус")],
                [KeyboardButton(text="🔑 Активировать промокод"), KeyboardButton(text="🧾 Чеки")],
                [KeyboardButton(text="◀️ Главное меню")]
            ],
            resize_keyboard=True
        )
    )

@dp.message(F.text == "👥 Рефералы")
async def referrals(message: Message):
    user = get_user(message.from_user.id)
    cnt = cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (message.from_user.id,)).fetchone()[0]
    earned = cursor.execute("SELECT COALESCE(SUM(earned_amount),0) FROM referrals WHERE referrer_id = ?", (message.from_user.id,)).fetchone()[0]
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref{user['referral_code']}"
    await message.answer(
        f"👥 <b>Рефералы</b>\n\n"
        f"🔗 Ссылка:\n<code>{link}</code>\n\n"
        f"👤 Приглашено: {cnt}\n"
        f"💰 Заработано: {earned:,} POCX\n\n"
        f"🎁 За друга: +{REF_REWARD:,} вам, +{REF_REFERRAL_BONUS:,} другу",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "📊 Статистика")
async def stats(message: Message):
    user = get_user(message.from_user.id)
    played = cursor.execute("SELECT COUNT(*) FROM game_history WHERE user_id = ?", (message.from_user.id,)).fetchone()[0]
    wins = cursor.execute("SELECT COUNT(*) FROM game_history WHERE user_id = ? AND result = 'win'", (message.from_user.id,)).fetchone()[0]
    best = cursor.execute("SELECT MAX(multiplier) FROM game_history WHERE user_id = ? AND result = 'win'", (message.from_user.id,)).fetchone()[0] or 0
    wr = wins / max(played, 1) * 100
    roi = (user["total_won"] - user["total_lost"]) / max(user["total_wagered"], 1) * 100
    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"🎮 Игр: {played}\n"
        f"✅ Побед: {wins} ({wr:.1f}%)\n"
        f"📈 Лучший множитель: {best:.2f}x\n"
        f"📊 ROI: {roi:.1f}%\n"
        f"💰 Вейджер: {user['total_wagered']:,} POCX\n"
        f"🏆 Выиграно: {user['total_won']:,} POCX",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "👤 Профиль")
async def profile(message: Message):
    user = get_user(message.from_user.id)
    vip, _ = get_vip(user["total_wagered"])
    status = user.get("custom_status") or "Обычный игрок"
    await message.answer(
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 ID: {user['user_id']}\n"
        f"📛 Имя: {message.from_user.first_name}\n"
        f"💰 Баланс: {user['balance']:,} POCX\n"
        f"💎 VIP: {vip}\n"
        f"🏷 Статус: {status}\n"
        f"📊 Вейджер: {user['total_wagered']:,} POCX\n"
        f"🏆 Выиграно: {user['total_won']:,} POCX\n"
        f"💸 Проиграно: {user['total_lost']:,} POCX\n"
        f"🔥 Серия дней: {user['daily_streak']}",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )

# ==================== БАНК ====================
@dp.message(F.text == "🏦 Банк")
async def bank_menu(message: Message):
    # Проверяем созревшие депозиты
    closed, payout = check_and_withdraw_deposits(message.from_user.id)
    if closed > 0:
        await message.answer(f"✅ Снято {closed} депозитов на сумму {payout:,} POCX")
    kb = InlineKeyboardMarkup(inline_row_width=2, inline_keyboard=[
        [InlineKeyboardButton(text="➕ Открыть депозит", callback_data="bank_open")],
        [InlineKeyboardButton(text="📜 Мои депозиты", callback_data="bank_list")],
        [InlineKeyboardButton(text="💸 Снять созревшие", callback_data="bank_withdraw")]
    ])
    await message.answer("🏦 <b>Банк</b>\n\nПроценты начисляются после окончания срока депозита.\n• 7 дней: +1%\n• 14 дней: +2%\n• 30 дней: +5%", reply_markup=kb, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "bank_open")
async def bank_open(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.bank_deposit_amount)
    await callback.message.edit_text("💰 Введи сумму депозита (минимум 1000 POCX):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="bank_cancel")]]))
    await callback.answer()

@dp.callback_query(F.data == "bank_cancel")
async def bank_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("❌ Отменено", reply_markup=main_menu())
    await callback.answer()

@dp.message(GameStates.bank_deposit_amount)
async def bank_deposit_amount(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
        if amount < 1000:
            raise ValueError
    except:
        await message.answer("❌ Введи сумму от 1000 POCX!")
        return
    user = get_user(message.from_user.id)
    if user["balance"] < amount:
        await message.answer(f"❌ Недостаточно средств! Нужно {amount:,} POCX")
        return
    await state.update_data(amount=amount)
    await state.set_state(GameStates.bank_deposit_term)
    kb = InlineKeyboardMarkup(inline_row_width=2, inline_keyboard=[
        [InlineKeyboardButton(text="7 дней (+1%)", callback_data="bank_term_7")],
        [InlineKeyboardButton(text="14 дней (+2%)", callback_data="bank_term_14")],
        [InlineKeyboardButton(text="30 дней (+5%)", callback_data="bank_term_30")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="bank_cancel")]
    ])
    await message.answer("📅 Выбери срок депозита:", reply_markup=kb)

@dp.callback_query(F.data.startswith("bank_term_"))
async def bank_term(callback: CallbackQuery, state: FSMContext):
    term_days = int(callback.data.split("_")[2])
    data = await state.get_data()
    amount = data.get("amount")
    ok, msg = add_deposit(callback.from_user.id, amount, term_days)
    await state.clear()
    if not ok:
        await callback.message.edit_text(f"❌ {msg}")
    else:
        await callback.message.edit_text(f"✅ {msg}\n💰 Сумма: {amount:,} POCX\n📅 Срок: {term_days} дней")
    await callback.answer()

@dp.callback_query(F.data == "bank_list")
async def bank_list(callback: CallbackQuery):
    deposits = list_user_deposits(callback.from_user.id)
    if not deposits:
        await callback.message.edit_text("📜 У вас нет активных депозитов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="bank_back")]]))
        await callback.answer()
        return
    now = int(time.time())
    lines = ["📜 <b>Ваши депозиты</b>\n"]
    for dep in deposits:
        dep_id, user_id, principal, rate, term_days, opened_at, status, closed_at = dep
        remaining_days = max(0, term_days - (now - opened_at) // 86400)
        payout = int(principal * (1 + rate))
        lines.append(f"#{dep_id}: {fmt_money(principal)} | +{int(rate*100)}% | осталось {remaining_days} дн. | выплата: {fmt_money(payout)}")
    await callback.message.edit_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="bank_back")]]))
    await callback.answer()

@dp.callback_query(F.data == "bank_withdraw")
async def bank_withdraw(callback: CallbackQuery):
    closed, payout = check_and_withdraw_deposits(callback.from_user.id)
    if closed == 0:
        await callback.answer("Нет созревших депозитов!", show_alert=True)
    else:
        user = get_user(callback.from_user.id)
        await callback.message.edit_text(f"✅ Снято {closed} депозитов на сумму {payout:,} POCX!\n💰 Новый баланс: {user['balance']:,} POCX", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="bank_back")]]))
    await callback.answer()

@dp.callback_query(F.data == "bank_back")
async def bank_back(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("🏦 <b>Банк</b>", reply_markup=main_menu())
    await callback.answer()

# ==================== АДМИН-ПАНЕЛЬ ====================
@dp.message(F.text == "👑 Админ")
async def admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!", reply_markup=main_menu())
        return
    await message.answer("👑 <b>Админ-панель</b>", reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    users = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_balance = cursor.execute("SELECT SUM(balance) FROM users").fetchone()[0] or 0
    total_wagered = cursor.execute("SELECT SUM(total_wagered) FROM users").fetchone()[0] or 0
    total_won = cursor.execute("SELECT SUM(total_won) FROM users").fetchone()[0] or 0
    total_lost = cursor.execute("SELECT SUM(total_lost) FROM users").fetchone()[0] or 0
    banned = cursor.execute("SELECT COUNT(*) FROM banned_users").fetchone()[0] or 0
    active_deposits = cursor.execute("SELECT COUNT(*) FROM bank_deposits WHERE status = 'active'").fetchone()[0]
    await callback.message.edit_text(
        f"📊 <b>Статистика казино</b>\n\n"
        f"👥 Пользователей: {users}\n"
        f"🚫 Забанено: {banned}\n"
        f"💰 Общий баланс: {fmt_money(total_balance)}\n"
        f"📊 Общий вейджер: {fmt_money(total_wagered)}\n"
        f"🏆 Выиграно: {fmt_money(total_won)}\n"
        f"💸 Проиграно: {fmt_money(total_lost)}\n"
        f"📈 Прибыль: {fmt_money(total_lost - total_won)}\n"
        f"🏦 Активных депозитов: {active_deposits}",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_give")
async def admin_give_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await state.set_state(GameStates.admin_give)
    await callback.message.edit_text("💰 Введи ID и сумму через пробел\nПример: `123456789 50000`\nИли ответь на сообщение пользователя команду `выдать 50000`")
    await callback.answer()

@dp.message(GameStates.admin_give)
async def admin_give_execute(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    # Проверяем, есть ли ответ на сообщение
    if message.reply_to_message:
        uid = message.reply_to_message.from_user.id
        try:
            amount = parse_amount(message.text.split()[1] if len(message.text.split()) > 1 else message.text)
        except:
            await message.answer("❌ Пример: `выдать 50000` в ответ на сообщение")
            await state.clear()
            return
    else:
        parts = message.text.split()
        if len(parts) != 2 or not parts[0].isdigit():
            await message.answer("❌ Пример: `123456789 50000` или ответь на сообщение")
            await state.clear()
            return
        uid = int(parts[0])
        amount = parse_amount(parts[1])
    add_pocx(uid, amount)
    user = get_user(uid)
    await message.answer(f"✅ Выдано {amount:,} POCX пользователю {uid}\n💰 Новый баланс: {user['balance']:,} POCX")
    await state.clear()

@dp.message(lambda msg: msg.text and msg.text.lower().startswith("выдать ") and msg.reply_to_message)
async def admin_give_reply(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    try:
        amount = parse_amount(message.text.split()[1])
    except:
        await message.answer("❌ Пример: `выдать 50000`")
        return
    uid = message.reply_to_message.from_user.id
    add_pocx(uid, amount)
    user = get_user(uid)
    await message.answer(f"✅ Выдано {amount:,} POCX пользователю {uid}\n💰 Новый баланс: {user['balance']:,} POCX")

@dp.callback_query(F.data == "admin_take")
async def admin_take_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await state.set_state(GameStates.admin_take)
    await callback.message.edit_text("➖ Введи ID и сумму через пробел\nПример: `123456789 50000`")
    await callback.answer()

@dp.message(GameStates.admin_take)
async def admin_take_execute(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[0].isdigit():
        await message.answer("❌ Пример: `123456789 50000`")
        return
    uid = int(parts[0])
    amount = parse_amount(parts[1])
    if not remove_pocx(uid, amount):
        await message.answer(f"❌ У пользователя {uid} недостаточно средств!")
        return
    await message.answer(f"✅ Списано {amount:,} POCX у пользователя {uid}")
    await state.clear()

@dp.callback_query(F.data == "admin_ban")
async def admin_ban_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await state.set_state(GameStates.admin_ban)
    await callback.message.edit_text("🔨 Введи ID пользователя\nПример: `123456789`")
    await callback.answer()

@dp.message(GameStates.admin_ban)
async def admin_ban_execute(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    if not message.text.isdigit():
        await message.answer("❌ Введи корректный ID!")
        return
    uid = int(message.text)
    ban_user(uid)
    await message.answer(f"✅ Пользователь {uid} забанен")
    await state.clear()

@dp.callback_query(F.data == "admin_unban")
async def admin_unban_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await state.set_state(GameStates.admin_unban)
    await callback.message.edit_text("🔓 Введи ID пользователя\nПример: `123456789`")
    await callback.answer()

@dp.message(GameStates.admin_unban)
async def admin_unban_execute(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    if not message.text.isdigit():
        await message.answer("❌ Введи корректный ID!")
        return
    uid = int(message.text)
    unban_user(uid)
    await message.answer(f"✅ Пользователь {uid} разбанен")
    await state.clear()

@dp.callback_query(F.data == "admin_promo")
async def admin_promo_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await state.set_state(GameStates.admin_promo_code)
    await callback.message.edit_text("🎟 Введи код промокода (3-24 символа):")
    await callback.answer()

@dp.message(GameStates.admin_promo_code)
async def admin_promo_code(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    code = message.text.strip().upper()
    if len(code) < 3 or len(code) > 24:
        await message.answer("❌ Код 3-24 символа!")
        return
    await state.update_data(promo_code=code)
    await state.set_state(GameStates.admin_promo_reward)
    await message.answer("💰 Введи сумму награды:")

@dp.message(GameStates.admin_promo_reward)
async def admin_promo_reward(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    try:
        reward = int(message.text)
        if reward <= 0:
            raise ValueError
    except:
        await message.answer("❌ Введи корректную сумму!")
        return
    await state.update_data(promo_reward=reward)
    await state.set_state(GameStates.admin_promo_uses)
    await message.answer("🔢 Введи количество активаций:")

@dp.message(GameStates.admin_promo_uses)
async def admin_promo_uses(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    try:
        uses = int(message.text)
        if uses <= 0:
            raise ValueError
    except:
        await message.answer("❌ Введи число > 0!")
        return
    data = await state.get_data()
    code = data["promo_code"]
    reward = data["promo_reward"]
    cursor.execute("INSERT INTO promocodes (code, bonus_amount, max_uses, is_active) VALUES (?, ?, ?, 1)", (code, reward, uses))
    conn.commit()
    await message.answer(
        f"✅ Промокод создан!\n🎫 Код: <code>{code}</code>\n💰 Награда: {reward:,} POCX\n🎯 Активаций: {uses}",
        parse_mode=ParseMode.HTML
    )
    await state.clear()

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await state.set_state(GameStates.admin_broadcast)
    await callback.message.edit_text("📢 Введи текст рассылки:")
    await callback.answer()

@dp.message(GameStates.admin_broadcast)
async def admin_broadcast_execute(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    text = message.text
    users = cursor.execute("SELECT user_id FROM users").fetchall()
    sent = 0
    for user in users:
        try:
            await bot.send_message(user[0], f"📢 <b>РАССЫЛКА</b>\n\n{text}")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"✅ Рассылка завершена! Отправлено {sent} пользователям.")
    await state.clear()

@dp.callback_query(F.data == "admin_status")
async def admin_status_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await state.set_state(GameStates.admin_status)
    await callback.message.edit_text("👑 Введи ID пользователя и статус через пробел\nПример: `123456789 Легенда`")
    await callback.answer()

@dp.message(GameStates.admin_status)
async def admin_status_execute(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2 or not parts[0].isdigit():
        await message.answer("❌ Пример: `123456789 Легенда`")
        return
    uid = int(parts[0])
    status_text = parts[1][:50]
    cursor.execute("UPDATE users SET custom_status = ? WHERE user_id = ?", (status_text, uid))
    conn.commit()
    await message.answer(f"✅ Пользователю {uid} назначен статус: {status_text}")
    await state.clear()

@dp.callback_query(F.data == "admin_treasury")
async def admin_treasury(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await callback.message.edit_text("🏦 <b>Управление казной</b>", reply_markup=treasury_admin_menu())
    await callback.answer()

@dp.callback_query(F.data == "treasury_add")
async def treasury_add_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await state.set_state(GameStates.treasury_add)
    await callback.message.edit_text("💰 Введи ID чата и сумму пополнения через пробел\nПример: `-100123456789 50000`")
    await callback.answer()

@dp.message(GameStates.treasury_add)
async def treasury_add_execute(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[0].lstrip("-").isdigit():
        await message.answer("❌ Пример: `-100123456789 50000`")
        return
    chat_id = int(parts[0])
    amount = parse_amount(parts[1])
    treasury = get_chat_treasury(chat_id)
    if not treasury:
        await message.answer("❌ В этом чате казна не активирована!")
        await state.clear()
        return
    add_to_chat_treasury(chat_id, amount)
    await message.answer(f"✅ Казне чата {chat_id} добавлено {amount:,} POCX")
    await state.clear()

@dp.callback_query(F.data == "treasury_withdraw")
async def treasury_withdraw_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await state.set_state(GameStates.treasury_withdraw)
    await callback.message.edit_text("💸 Введи ID чата и сумму вывода через пробел\nПример: `-100123456789 50000`")
    await callback.answer()

@dp.message(GameStates.treasury_withdraw)
async def treasury_withdraw_execute(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[0].lstrip("-").isdigit():
        await message.answer("❌ Пример: `-100123456789 50000`")
        return
    chat_id = int(parts[0])
    amount = parse_amount(parts[1])
    if not remove_from_chat_treasury(chat_id, amount):
        await message.answer("❌ В казне недостаточно средств!")
        await state.clear()
        return
    add_pocx(message.from_user.id, amount)
    await message.answer(f"✅ Из казны чата {chat_id} выведено {amount:,} POCX")
    await state.clear()

@dp.callback_query(F.data == "treasury_set_reward")
async def treasury_set_reward_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await state.set_state(GameStates.treasury_reward_set)
    await callback.message.edit_text("⚙️ Введи ID чата и сумму награды за приглашение через пробел\nПример: `-100123456789 500`")
    await callback.answer()

@dp.message(GameStates.treasury_reward_set)
async def treasury_set_reward_execute(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[0].lstrip("-").isdigit():
        await message.answer("❌ Пример: `-100123456789 500`")
        return
    chat_id = int(parts[0])
    reward = parse_amount(parts[1])
    if reward < 1 or reward > 15000:
        await message.answer("❌ Награда должна быть от 1 до 15,000 POCX!")
        return
    set_treasury_reward(chat_id, reward)
    await message.answer(f"✅ Награда за приглашение в чате {chat_id} установлена на {reward} POCX")
    await state.clear()

@dp.callback_query(F.data == "treasury_stats")
async def treasury_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    cursor.execute("SELECT chat_id, owner_id, balance, reward_per_invite, is_active FROM chat_treasury")
    rows = cursor.fetchall()
    if not rows:
        await callback.message.edit_text("📊 Нет активных казн")
        await callback.answer()
        return
    lines = ["📊 <b>Статистика казн</b>\n"]
    for row in rows:
        chat_id, owner_id, balance, reward, is_active = row
        status = "✅" if is_active else "❌"
        cursor.execute("SELECT COUNT(*) FROM treasury_rewards WHERE chat_id = ?", (chat_id,))
        rewards_given = cursor.fetchone()[0]
        lines.append(f"🏦 Чат: {chat_id}\n   Владелец: {owner_id}\n   Баланс: {balance:,} POCX\n   Награда: {reward} POCX\n   Выдано наград: {rewards_given}\n   Статус: {status}\n")
    await callback.message.edit_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=admin_menu())
    await callback.answer()

# ==================== ОБРАБОТЧИК НОВЫХ УЧАСТНИКОВ (КАЗНА) ====================
@dp.chat_member()
async def on_new_chat_member(event: ChatMemberUpdated):
    if event.new_chat_member.status in ["member", "administrator", "creator"]:
        if event.old_chat_member.status == event.new_chat_member.status:
            return
    else:
        return
    chat_id = event.chat.id
    new_user_id = event.new_chat_member.user.id
    treasury = get_chat_treasury(chat_id)
    if not treasury or not treasury["is_active"]:
        return
    if is_user_rewarded(chat_id, new_user_id):
        return
    inviter_id = None
    if event.invite_link and event.invite_link.inviter:
        inviter_id = event.invite_link.inviter.id
    if not inviter_id:
        return
    reward = treasury["reward_per_invite"]
    if treasury["balance"] < reward:
        return
    if remove_from_chat_treasury(chat_id, reward):
        add_pocx(inviter_id, reward)
        mark_user_rewarded(chat_id, new_user_id, inviter_id)
        cursor.execute("UPDATE users SET total_invites = total_invites + 1 WHERE user_id = ?", (inviter_id,))
        conn.commit()
        try:
            await bot.send_message(
                inviter_id,
                f"🎉 <b>Вы получили награду за приглашение!</b>\n\n"
                f"👤 Новый участник: {event.new_chat_member.user.first_name}\n"
                f"🏦 Чат: {event.chat.title}\n"
                f"💰 Награда: +{reward:,} POCX",
                parse_mode=ParseMode.HTML
            )
        except:
            pass

# ==================== БОНУСЫ ====================
@dp.message(F.text == "🎁 Ежедневный бонус")
async def daily_bonus(message: Message):
    uid = message.from_user.id
    row = cursor.execute("SELECT last_daily_bonus, daily_streak FROM users WHERE user_id = ?", (uid,)).fetchone()
    last = row[0] if row else None
    streak = row[1] if row else 0
    if last:
        last_dt = datetime.fromisoformat(last)
        if datetime.now() - last_dt < timedelta(days=1):
            await message.answer("❌ Бонус уже получен сегодня!")
            return
    bonus = random.randint(DAILY_BONUS_MIN, DAILY_BONUS_MAX)
    bonus = int(bonus * (1 + min(streak * 0.05, 0.5)))
    add_pocx(uid, bonus)
    cursor.execute("UPDATE users SET last_daily_bonus = CURRENT_TIMESTAMP, daily_streak = daily_streak + 1 WHERE user_id = ?", (uid,))
    conn.commit()
    await message.answer(f"🎁 <b>Ежедневный бонус!</b>\n\n💰 +{bonus:,} POCX\n🔥 Серия дней: {streak + 1}", parse_mode=ParseMode.HTML)

@dp.message(F.text == "🆕 Приветственный бонус")
async def welcome_bonus(message: Message):
    uid = message.from_user.id
    row = cursor.execute("SELECT welcome_bonus_claimed FROM users WHERE user_id = ?", (uid,)).fetchone()
    if row and row[0]:
        await message.answer("❌ Приветственный бонус уже получен!")
        return
    add_pocx(uid, WELCOME_BONUS)
    cursor.execute("UPDATE users SET welcome_bonus_claimed = 1 WHERE user_id = ?", (uid,))
    conn.commit()
    await message.answer(f"🎁 <b>Приветственный бонус!</b>\n\n💰 +{WELCOME_BONUS:,} POCX", parse_mode=ParseMode.HTML)

@dp.message(F.text == "🔑 Активировать промокод")
async def promo_input(message: Message, state: FSMContext):
    await state.set_state(GameStates.promo_code)
    await message.answer("🔑 <b>Введите промокод</b>", reply_markup=cancel_menu(), parse_mode=ParseMode.HTML)

@dp.message(GameStates.promo_code)
async def promo_use(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=bonuses_menu())
        return
    code = message.text.strip().upper()
    row = cursor.execute("SELECT bonus_amount, max_uses, used_count, expires_at, is_active FROM promocodes WHERE code = ?", (code,)).fetchone()
    if not row or not row[4] or row[2] >= row[1]:
        await message.answer("❌ Промокод недействителен!")
        await state.clear()
        return
    if row[3] and datetime.fromisoformat(row[3]) < datetime.now():
        await message.answer("❌ Промокод истёк!")
        await state.clear()
        return
    if cursor.execute("SELECT 1 FROM used_promocodes WHERE user_id = ? AND code = ?", (message.from_user.id, code)).fetchone():
        await message.answer("❌ Вы уже использовали этот промокод!")
        await state.clear()
        return
    bonus = row[0]
    add_pocx(message.from_user.id, bonus)
    cursor.execute("INSERT INTO used_promocodes (user_id, code) VALUES (?, ?)", (message.from_user.id, code))
    cursor.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?", (code,))
    conn.commit()
    await message.answer(f"✅ Промокод активирован!\n💰 +{bonus:,} POCX")
    await state.clear()

# ==================== ЧЕКИ ====================
@dp.message(F.text == "🧾 Чеки")
async def checks_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать чек", callback_data="check_create")],
        [InlineKeyboardButton(text="📥 Активировать чек", callback_data="check_claim")],
        [InlineKeyboardButton(text="📋 Мои чеки", callback_data="check_my")]
    ])
    await message.answer("🧾 <b>Чеки</b>", reply_markup=kb, parse_mode=ParseMode.HTML)

def generate_check_code() -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

@dp.callback_query(F.data == "check_create")
async def check_create_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.admin_promo_code)  # используем готовое состояние
    await callback.message.edit_text("💰 Введи сумму на одну активацию чека (макс 5,000,000 POCX):")
    await callback.answer()

@dp.message(GameStates.admin_promo_code)
async def check_create_amount(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
        if amount <= 0 or amount > 5_000_000:
            raise ValueError
    except:
        await message.answer("❌ Введи сумму от 1 до 5,000,000 POCX!")
        return
    await state.update_data(check_amount=amount)
    await state.set_state(GameStates.admin_promo_reward)
    await message.answer("🔢 Введи количество активаций (макс 50):")

@dp.message(GameStates.admin_promo_reward)
async def check_create_count(message: Message, state: FSMContext):
    try:
        count = int(message.text)
        if count <= 0 or count > 50:
            raise ValueError
    except:
        await message.answer("❌ Введи число от 1 до 50!")
        return
    data = await state.get_data()
    amount = data["check_amount"]
    total = amount * count
    user = get_user(message.from_user.id)
    if user["balance"] < total:
        await message.answer(f"❌ Недостаточно средств! Нужно {total:,} POCX")
        return
    remove_pocx(message.from_user.id, total)
    code = generate_check_code()
    cursor.execute("INSERT INTO checks (code, creator_id, per_user, remaining, used, password) VALUES (?, ?, ?, ?, ?, ?)",
                   (code, message.from_user.id, amount, count, "[]", None))
    conn.commit()
    check_link = f"https://t.me/{(await bot.get_me()).username}?start=check_{code}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎫 Активировать чек", url=check_link)],
        [InlineKeyboardButton(text="📋 Копировать код", callback_data=f"copy_code_{code}")]
    ])
    await message.answer(
        f"✅ <b>Чек создан!</b>\n\n"
        f"🎫 Код: <code>{code}</code>\n"
        f"💰 Сумма: {amount:,} POCX\n"
        f"📊 Активаций: {count}\n\n"
        f"🔗 Ссылка для активации:\n{check_link}",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    await state.clear()

@dp.callback_query(F.data == "check_claim")
async def check_claim_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.admin_status)  # используем готовое состояние
    await callback.message.edit_text("🔑 Введи код чека:")
    await callback.answer()

@dp.message(GameStates.admin_status)
async def check_claim(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    row = cursor.execute("SELECT per_user, remaining, used, password FROM checks WHERE code = ?", (code,)).fetchone()
    if not row:
        await message.answer("❌ Чек не найден!")
        await state.clear()
        return
    per_user, remaining, used_str, password = row
    if remaining <= 0:
        await message.answer("❌ Чек уже использован!")
        await state.clear()
        return
    used = json.loads(used_str) if used_str else []
    if str(message.from_user.id) in used:
        await message.answer("❌ Вы уже активировали этот чек!")
        await state.clear()
        return
    add_pocx(message.from_user.id, per_user)
    used.append(str(message.from_user.id))
    cursor.execute("UPDATE checks SET remaining = remaining - 1, used = ? WHERE code = ?",
                   (json.dumps(used), code))
    conn.commit()
    await message.answer(f"✅ Чек активирован!\n💰 +{per_user:,} POCX")
    await state.clear()

@dp.callback_query(F.data == "check_my")
async def check_my(callback: CallbackQuery):
    rows = cursor.execute("SELECT code, per_user, remaining FROM checks WHERE creator_id = ? ORDER BY rowid DESC LIMIT 10", (callback.from_user.id,)).fetchall()
    if not rows:
        await callback.message.edit_text("📋 У вас нет созданных чеков.")
        await callback.answer()
        return
    text = "📋 <b>Ваши чеки</b>\n\n"
    for row in rows:
        text += f"🎫 <code>{row[0]}</code> | {row[1]:,} POCX | осталось: {row[2]}\n"
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.callback_query(F.data.startswith("copy_code_"))
async def copy_code(callback: CallbackQuery):
    code = callback.data.split("_")[2]
    await callback.answer(f"🎫 Код: {code}", show_alert=True)

@dp.message(Command("activate"))
async def activate_check(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Используй: <code>/activate КОД</code>", parse_mode=ParseMode.HTML)
        return
    code = parts[1].upper()
    row = cursor.execute("SELECT per_user, remaining, used, password FROM checks WHERE code = ?", (code,)).fetchone()
    if not row:
        await message.answer("❌ Чек не найден!")
        return
    per_user, remaining, used_str, password = row
    if remaining <= 0:
        await message.answer("❌ Чек уже использован!")
        return
    used = json.loads(used_str) if used_str else []
    if str(message.from_user.id) in used:
        await message.answer("❌ Вы уже активировали этот чек!")
        return
    add_pocx(message.from_user.id, per_user)
    used.append(str(message.from_user.id))
    cursor.execute("UPDATE checks SET remaining = remaining - 1, used = ? WHERE code = ?",
                   (json.dumps(used), code))
    conn.commit()
    await message.answer(f"✅ Чек активирован!\n💰 +{per_user:,} POCX")

# ==================== ПЕРЕВОДЫ ====================
@dp.message(lambda msg: msg.text and msg.text.lower().startswith("д ") and msg.reply_to_message)
async def transfer_command(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        await message.reply("❌ Используй: <code>д [сумма]</code> в ответ на сообщение", parse_mode=ParseMode.HTML)
        return
    try:
        amount = parse_amount(parts[1])
        if amount <= 0:
            raise ValueError
    except:
        await message.reply("❌ Введи корректную сумму!")
        return
    user = get_user(message.from_user.id)
    commission = int(amount * 0.03)
    total = amount + commission
    if user["balance"] < total:
        await message.reply(f"❌ Недостаточно средств! Нужно {total:,} POCX (включая комиссию 3%)")
        return
    target_id = message.reply_to_message.from_user.id
    remove_pocx(message.from_user.id, total)
    add_pocx(target_id, amount)
    await message.reply(f"✅ Переведено {amount:,} POCX пользователю\n💸 Комиссия: {commission:,} POCX")

# ==================== КАЗНА ДЛЯ ВЛАДЕЛЬЦЕВ ЧАТА ====================
@dp.message(F.text == "🏦 Казна")
async def treasury_command(message: Message):
    if is_private(message):
        await message.answer("❌ Команда работает только в чатах!")
        return
    treasury = get_chat_treasury(message.chat.id)
    if not treasury:
        await message.answer(
            "🏦 <b>В этом чате казна не активирована!</b>\n\n"
            "Владелец чата может активировать казну за 15,000 POCX.\n"
            "После активации приглашающие будут получать награду за новых участников.",
            parse_mode=ParseMode.HTML
        )
        return
    if message.from_user.id != treasury["owner_id"]:
        await message.answer(
            f"🏦 <b>Статистика казны</b>\n\n"
            f"💰 Баланс: {treasury['balance']:,} POCX\n"
            f"🎁 Награда за приглашение: {treasury['reward_per_invite']} POCX",
            parse_mode=ParseMode.HTML
        )
        return
    kb = InlineKeyboardMarkup(inline_row_width=2, inline_keyboard=[
        [InlineKeyboardButton(text="💸 Пополнить казну", callback_data="treasury_owner_add")],
        [InlineKeyboardButton(text="⚙️ Настроить награду", callback_data="treasury_owner_reward")],
        [InlineKeyboardButton(text="📊 Статистика казны", callback_data="treasury_owner_stats")]
    ])
    await message.answer(
        f"🏦 <b>Управление казной</b>\n\n"
        f"💰 Баланс казны: {treasury['balance']:,} POCX\n"
        f"🎁 Текущая награда: {treasury['reward_per_invite']} POCX",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "treasury_owner_add")
async def treasury_owner_add(callback: CallbackQuery, state: FSMContext):
    treasury = get_chat_treasury(callback.message.chat.id)
    if not treasury or callback.from_user.id != treasury["owner_id"]:
        await callback.answer("❌ Только владелец казны может пополнять!", show_alert=True)
        return
    await state.set_state(GameStates.treasury_add)
    await callback.message.edit_text("💰 Введи сумму пополнения казны (минимум 1000 POCX):")
    await callback.answer()

@dp.message(GameStates.treasury_add)
async def treasury_owner_add_execute(message: Message, state: FSMContext):
    treasury = get_chat_treasury(message.chat.id)
    if not treasury or message.from_user.id != treasury["owner_id"]:
        await message.answer("❌ Только владелец казны может пополнять!")
        await state.clear()
        return
    try:
        amount = parse_amount(message.text)
        if amount < 1000:
            raise ValueError
    except:
        await message.answer("❌ Введи сумму от 1000 POCX!")
        return
    user = get_user(message.from_user.id)
    if user["balance"] < amount:
        await message.answer(f"❌ Недостаточно средств! Нужно {amount:,} POCX")
        return
    remove_pocx(message.from_user.id, amount)
    add_to_chat_treasury(message.chat.id, amount)
    treasury = get_chat_treasury(message.chat.id)
    await message.answer(f"✅ Казны пополнена на {amount:,} POCX!\n💰 Новый баланс: {treasury['balance']:,} POCX")
    await state.clear()

@dp.callback_query(F.data == "treasury_owner_reward")
async def treasury_owner_reward(callback: CallbackQuery, state: FSMContext):
    treasury = get_chat_treasury(callback.message.chat.id)
    if not treasury or callback.from_user.id != treasury["owner_id"]:
        await callback.answer("❌ Только владелец казны может настраивать!", show_alert=True)
        return
    await state.set_state(GameStates.treasury_reward_set)
    await callback.message.edit_text(f"⚙️ Текущая награда: {treasury['reward_per_invite']} POCX\nВведи новую сумму (от 1 до 15,000 POCX):")
    await callback.answer()

@dp.message(GameStates.treasury_reward_set)
async def treasury_owner_reward_execute(message: Message, state: FSMContext):
    treasury = get_chat_treasury(message.chat.id)
    if not treasury or message.from_user.id != treasury["owner_id"]:
        await message.answer("❌ Только владелец казны может настраивать!")
        await state.clear()
        return
    try:
        reward = parse_amount(message.text)
        if reward < 1 or reward > 15000:
            raise ValueError
    except:
        await message.answer("❌ Введи сумму от 1 до 15,000 POCX!")
        return
    set_treasury_reward(message.chat.id, reward)
    await message.answer(f"✅ Награда за приглашение изменена на {reward} POCX")
    await state.clear()

@dp.callback_query(F.data == "treasury_owner_stats")
async def treasury_owner_stats(callback: CallbackQuery):
    treasury = get_chat_treasury(callback.message.chat.id)
    if not treasury:
        await callback.answer("❌ Казна не активирована!", show_alert=True)
        return
    rewards_given = cursor.execute("SELECT COUNT(*) FROM treasury_rewards WHERE chat_id = ?", (callback.message.chat.id,)).fetchone()[0]
    total_paid = cursor.execute("SELECT COALESCE(SUM(reward_per_invite),0) FROM treasury_rewards WHERE chat_id = ?", (callback.message.chat.id,)).fetchone()[0]
    await callback.message.edit_text(
        f"📊 <b>Статистика казны</b>\n\n"
        f"👑 Владелец: {treasury['owner_id']}\n"
        f"💰 Баланс: {treasury['balance']:,} POCX\n"
        f"🎁 Награда: {treasury['reward_per_invite']} POCX\n"
        f"🎉 Выдано наград: {rewards_given}\n"
        f"💸 Всего выплачено: {total_paid:,} POCX",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="treasury_owner_back")]])
    )
    await callback.answer()

@dp.callback_query(F.data == "treasury_owner_back")
async def treasury_owner_back(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("🏦 <b>Главное меню</b>", reply_markup=main_menu())
    await callback.answer()

# ==================== ИГРЫ (ТЕКСТОВЫЕ КОМАНДЫ) ====================

# ----------------------------- HELPER ФУНКЦИИ ДЛЯ ИГР -----------------------------
def reserve_bet_fake(user_id: int, bet: int) -> tuple[bool, int]:
    ok = remove_pocx(user_id, bet)
    if ok:
        return True, get_user(user_id)["balance"]
    return False, 0

def finalize_reserved_bet_fake(user_id: int, bet: int, payout: int, choice: str, outcome: str) -> int:
    if payout > 0:
        add_pocx(user_id, payout)
    record_game(user_id, choice, bet, payout/bet if payout else 0, payout, "win" if payout>0 else "loss", {"outcome": outcome})
    return get_user(user_id)["balance"]

def settle_instant_bet_fake(user_id: int, bet: int, payout: int, choice: str, outcome: str) -> tuple[bool, int]:
    ok = remove_pocx(user_id, bet)
    if not ok:
        return False, get_user(user_id)["balance"]
    if payout > 0:
        add_pocx(user_id, payout)
    record_game(user_id, choice, bet, payout/bet if payout else 0, payout, "win" if payout>0 else "loss", {"outcome": outcome})
    return True, get_user(user_id)["balance"]

def roulette_roll(choice: str) -> tuple[bool, float, str]:
    number = random.randint(0, 36)
    color = "green" if number == 0 else ("red" if number in RED_NUMBERS else "black")
    parity = "zero" if number == 0 else ("even" if number % 2 == 0 else "odd")
    win = False
    multiplier = 0.0
    if choice == "red" and color == "red":
        win, multiplier = True, 2.0
    elif choice == "black" and color == "black":
        win, multiplier = True, 2.0
    elif choice == "even" and parity == "even":
        win, multiplier = True, 2.0
    elif choice == "odd" and parity == "odd":
        win, multiplier = True, 2.0
    elif choice == "zero" and number == 0:
        win, multiplier = True, 36.0
    pretty_color = {"red": "🔴 красное", "black": "⚫ черное", "green": "🟢 зеро"}[color]
    outcome = f"Выпало {number} ({pretty_color})"
    return win, multiplier, outcome

def crash_roll() -> float:
    u = random.random()
    raw = 0.99 / (1.0 - u)
    return round(max(1.0, min(50.0, raw)), 2)

def mines_multiplier(opened_count: int, mines_count: int) -> float:
    if opened_count <= 0:
        return 1.0
    safe_cells = 9 - mines_count
    base = 9.0 / max(1.0, safe_cells)
    mult = (base ** opened_count) * 0.95
    return round(mult, 2)

def tower_text(level: int, bet: int) -> str:
    cur_mult = TOWER_MULTIPLIERS[level - 1] if level > 0 else 0
    cur_win = bet * cur_mult if level > 0 else 0
    next_mult = TOWER_MULTIPLIERS[level] if level < len(TOWER_MULTIPLIERS) else TOWER_MULTIPLIERS[-1]
    return (
        f"🗼 <b>Башня</b>\n\n"
        f"💰 Ставка: {fmt_money(bet)}\n"
        f"🎯 Этаж: {level}/8\n"
        f"📈 Текущий множитель: x{cur_mult:.2f}\n"
        f"💎 Потенциальный выигрыш: {fmt_money(cur_win)}\n"
        f"⬆️ Следующий этаж: x{next_mult:.2f}\n\n"
        f"Выбери безопасную секцию (1-3):"
    )

def gold_text(step: int, bet: int) -> str:
    cur_mult = GOLD_MULTIPLIERS[step - 1] if step > 0 else 0
    cur_win = bet * cur_mult if step > 0 else 0
    next_mult = GOLD_MULTIPLIERS[step] if step < len(GOLD_MULTIPLIERS) else GOLD_MULTIPLIERS[-1]
    return (
        f"🥇 <b>Золото</b>\n\n"
        f"💰 Ставка: {fmt_money(bet)}\n"
        f"🎯 Раунд: {step+1}/7\n"
        f"📈 Текущий множитель: x{cur_mult:.2f}\n"
        f"💎 Потенциальный выигрыш: {fmt_money(cur_win)}\n"
        f"⬆️ Следующий раунд: x{next_mult:.2f}\n\n"
        f"Выбери плитку (1-4):"
    )

def diamond_text(step: int, bet: int) -> str:
    cur_mult = DIAMOND_MULTIPLIERS[step - 1] if step > 0 else 0
    cur_win = bet * cur_mult if step > 0 else 0
    next_mult = DIAMOND_MULTIPLIERS[step] if step < len(DIAMOND_MULTIPLIERS) else DIAMOND_MULTIPLIERS[-1]
    return (
        f"💎 <b>Алмазы</b>\n\n"
        f"💰 Ставка: {fmt_money(bet)}\n"
        f"🎯 Шаг: {step+1}/8\n"
        f"📈 Текущий множитель: x{cur_mult:.2f}\n"
        f"💎 Потенциальный выигрыш: {fmt_money(cur_win)}\n"
        f"⬆️ Следующий шаг: x{next_mult:.2f}\n\n"
        f"Выбери кристалл (1-5):"
    )

# ==================== ЗАПУСК БОТА ====================
async def main():
    print("🤖 POCX Bot запущен!")
    print(f"👥 Админы: {ADMIN_IDS}")
    print("✅ Игры: Башня, Золото, Алмазы, Мины, Очко, Рулетка, Краш, Кубик, Кости, Футбол, Баскет")
    print("✅ Банк, Чеки, Промокоды, Рефералы, Казны чатов")
    print("✅ Ежечасный бонус активному игроку")
    print("✅ Текстовые команды в чатах: б, п, т, р, бн, ст, и, помощь")
    asyncio.create_task(hourly_active_bonus())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
