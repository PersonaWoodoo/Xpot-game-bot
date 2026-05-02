import asyncio
import random
import sqlite3
import hashlib
import time
import json
import os
import re
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    CallbackQuery, Message, LabeledPrice, PreCheckoutQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode

# ==================== КОНФИГУРАЦИЯ ====================
TOKEN = "8134237711:AAH5M0JJULkrl0yyOdvfCtIswRPqRtt_3hg"
ADMIN_IDS = [8478884644, 8293927811]
STARS_TO_POCX = 2500

MIN_BET = 100
MAX_BET = 10**12  # 1 триллион
HOUSE_EDGE = 0.01

DAILY_BONUS_MIN = 100
DAILY_BONUS_MAX = 2000
WELCOME_BONUS = 1000
REF_REWARD = 5000
REF_REFERRAL_BONUS = 500  # бонус приглашённому

CLAN_CREATION_COST = 250000      # POCX
CLAN_CREATION_STARS = 100        # Stars

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

bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# ==================== БАЗА ДАННЫХ (расширенная) ====================
conn = sqlite3.connect("pocx_bot.db", check_same_thread=False)
cursor = conn.cursor()

# Пользователи (добавлены поля для статуса, клана)
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
    clan_id INTEGER DEFAULT NULL,
    status TEXT DEFAULT NULL,
    custom_status TEXT DEFAULT NULL
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

# Кланы
cursor.execute("""
CREATE TABLE IF NOT EXISTS clans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    owner_id INTEGER,
    treasury INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    stars_used BOOLEAN DEFAULT 0
)
""")

# Казна чатов (общая, по chat_id)
cursor.execute("""
CREATE TABLE IF NOT EXISTS chat_treasury (
    chat_id INTEGER PRIMARY KEY,
    amount INTEGER DEFAULT 0
)
""")

# Статусы (для назначения админом)
cursor.execute("""
CREATE TABLE IF NOT EXISTS user_statuses (
    user_id INTEGER PRIMARY KEY,
    status TEXT,
    assigned_by INTEGER,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()
print("✅ База данных готова")

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def parse_amount(text: str) -> int:
    """Преобразует 1к -> 1000, 1кк -> 1_000_000, 1ккк -> 1_000_000_000 и т.д."""
    text = text.lower().strip()
    multipliers = {
        'ккк': 1_000_000_000,
        'кк': 1_000_000,
        'к': 1_000,
        'kkk': 1_000_000_000,
        'kk': 1_000_000,
        'k': 1_000,
        'm': 1_000_000,
        'b': 1_000_000_000,
    }
    for suffix, mult in multipliers.items():
        if text.endswith(suffix):
            num_part = text[:-len(suffix)]
            if num_part == '':
                num_part = '1'
            try:
                return int(float(num_part) * mult)
            except:
                return 0
    try:
        return int(text)
    except:
        return 0

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
        "clan_id": row[13],
        "status": row[14],
        "custom_status": row[15],
    }

def get_vip(wagered: int) -> tuple:
    current = VIP_LEVELS[0]
    for lvl in VIP_LEVELS:
        if wagered >= lvl[1]:
            current = lvl
    return current[0], current[2]

def check_cooldown(user_id: int) -> bool:
    cursor.execute("SELECT last_game_time FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    now = int(time.time())
    if res and res[0]:
        if now - res[0] < 5:
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

def record_game(user_id: int, game_type: str, bet: int, multiplier: float, win: int, result: str, details: dict):
    cursor.execute("""
        UPDATE users SET 
            total_wagered = total_wagered + ?,
            total_won = total_won + ?,
            total_lost = total_lost + ?
        WHERE user_id = ?
    """, (bet, win if result == "win" else 0, bet if result == "loss" else 0, user_id))
    cursor.execute("""
        INSERT INTO game_history (user_id, game_type, bet_amount, multiplier, win_amount, result, details)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, game_type, bet, multiplier, win, result, json.dumps(details)))
    conn.commit()

# ==================== ПРОВЕРКА ПОДПИСКИ ====================
async def check_subscription(user_id: int) -> tuple[bool, list]:
    not_subscribed = []
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel["chat_id"], user_id=user_id)
            if member.status in ["left", "kicked"]:
                not_subscribed.append(channel)
        except Exception:
            not_subscribed.append(channel)
    return len(not_subscribed) == 0, not_subscribed

def subscription_keyboard(not_subscribed: list) -> InlineKeyboardMarkup:
    kb = []
    for channel in not_subscribed:
        kb.append([InlineKeyboardButton(text=f"📢 Подписаться на {channel['name']}", url=channel["link"])])
    kb.append([InlineKeyboardButton(text="◀️ Проверить подписку", callback_data="check_subscription")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ==================== КЛАВИАТУРЫ (ТОЛЬКО ДЛЯ ЛС) ====================
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎮 Игры"), KeyboardButton(text="💰 Финансы")],
            [KeyboardButton(text="🏆 Топ"), KeyboardButton(text="🎁 Бонусы")],
            [KeyboardButton(text="👥 Рефералы"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="👑 Админ")],
            [KeyboardButton(text="⭐ Кланы")]
        ],
        resize_keyboard=True
    )

def games_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎲 Dice"), KeyboardButton(text="🚀 Crash")],
            [KeyboardButton(text="🎡 Рулетка"), KeyboardButton(text="🪙 Coin Flip")],
            [KeyboardButton(text="🃏 Hi-Lo"), KeyboardButton(text="◀️ Главное меню")]
        ],
        resize_keyboard=True
    )

def finance_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⭐ Пополнить Stars")],
            [KeyboardButton(text="◀️ Главное меню")]
        ],
        resize_keyboard=True
    )

def bonuses_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎁 Ежедневный бонус"), KeyboardButton(text="🆕 Приветственный бонус")],
            [KeyboardButton(text="🔑 Активировать промокод")],
            [KeyboardButton(text="◀️ Главное меню")]
        ],
        resize_keyboard=True
    )

def admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="💰 Выдать POCX")],
            [KeyboardButton(text="➖ Забрать POCX"), KeyboardButton(text="🔨 Забанить")],
            [KeyboardButton(text="🔓 Разбанить"), KeyboardButton(text="🎟 Создать промокод")],
            [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="👑 Назначить статус")],
            [KeyboardButton(text="🏦 Казна чата"), KeyboardButton(text="◀️ Главное меню")]
        ],
        resize_keyboard=True
    )

def cancel_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )

def clan_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои кланы"), KeyboardButton(text="📊 Топ кланов")],
            [KeyboardButton(text="➕ Создать клан"), KeyboardButton(text="🔍 Найти клан")],
            [KeyboardButton(text="💸 Пополнить казну клана"), KeyboardButton(text="🚪 Выйти из клана")],
            [KeyboardButton(text="◀️ Главное меню")]
        ],
        resize_keyboard=True
    )

# ==================== FSM ====================
class GameStates(StatesGroup):
    dice_bet = State()
    dice_chance = State()
    crash_bet = State()
    roulette_bet = State()
    roulette_choice = State()
    coin_choice = State()
    coin_bet = State()
    hilo_bet = State()
    donate_custom = State()
    admin_give = State()
    admin_take = State()
    admin_ban = State()
    admin_unban = State()
    admin_broadcast = State()
    admin_promo_code = State()
    admin_promo_reward = State()
    admin_promo_uses = State()
    promo_code = State()
    clan_create_name = State()
    clan_find = State()
    clan_treasury_add = State()
    chat_treasury_add = State()
    chat_treasury_withdraw = State()
    assign_status = State()
    assign_status_user = State()
    assign_status_text = State()

# ==================== MIDDLEWARE ====================
@dp.callback_query()
async def subscription_callback_middleware(callback: CallbackQuery):
    if callback.data == "check_subscription":
        return
    if is_banned(callback.from_user.id):
        await callback.answer("❌ Вы забанены!", show_alert=True)
        return
    ok, not_subscribed = await check_subscription(callback.from_user.id)
    if not ok:
        await callback.answer("❓ Подпишитесь на каналы!", show_alert=True)
        return

@dp.callback_query(F.data == "check_subscription")
async def check_sub(callback: CallbackQuery):
    ok, not_subscribed = await check_subscription(callback.from_user.id)
    if ok:
        await callback.message.delete()
        await callback.message.answer("✅ Спасибо за подписку!", reply_markup=main_menu())
    else:
        await callback.message.edit_text(
            "❓ Для использования бота необходимо подписаться на каналы:",
            reply_markup=subscription_keyboard(not_subscribed)
        )
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
    
    # Реферальная система (исправлена)
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref"):
        ref_code = args[1][3:]
        cursor.execute("SELECT user_id FROM users WHERE referral_code = ?", (ref_code,))
        ref = cursor.fetchone()
        if ref and ref[0] != uid:
            cursor.execute("SELECT 1 FROM referrals WHERE referrer_id = ? AND referred_id = ?", (ref[0], uid))
            if not cursor.fetchone():
                # Начисляем реферальную награду
                add_pocx(ref[0], REF_REWARD)
                # Приглашённый получает небольшой бонус
                add_pocx(uid, REF_REFERRAL_BONUS)
                cursor.execute("INSERT INTO referrals (referrer_id, referred_id, earned_amount) VALUES (?, ?, ?)", (ref[0], uid, REF_REWARD))
                conn.commit()
    
    # Проверка подписки
    ok, not_subscribed = await check_subscription(uid)
    if not ok:
        await message.answer(
            "❓ Для использования бота необходимо подписаться на каналы:",
            reply_markup=subscription_keyboard(not_subscribed)
        )
        return
    
    vip, _ = get_vip(user["total_wagered"])
    await message.answer(
        f"🎰 <b>POCX Casino Bot</b>\n\n"
        f"💰 Баланс: <b>{user['balance']:,} POCX</b>\n"
        f"💎 VIP: {vip}\n\n"
        f"🎮 Игры: Dice • Crash • Рулетка • Coin Flip • Hi-Lo\n\n"
        f"⭐ 1 Star = 2500 POCX\n"
        f"🔥 КД между играми: 5 секунд\n\n"
        f"👥 Реферальная ссылка:\n<code>https://t.me/{(await bot.get_me()).username}?start=ref{user['referral_code']}</code>\n\n"
        f"🎁 За каждого друга: +{REF_REWARD:,} POCX вам и +{REF_REFERRAL_BONUS:,} другу",
        reply_markup=main_menu()
    )

@dp.message(F.text == "◀️ Главное меню")
async def back_to_main(message: Message):
    user = get_user(message.from_user.id)
    vip, _ = get_vip(user["total_wagered"])
    await message.answer(
        f"🎰 <b>Главное меню</b>\n\n💰 Баланс: <b>{user['balance']:,} POCX</b> | {vip}",
        reply_markup=main_menu()
    )

# ==================== КОМАНДЫ ДЛЯ ЧАТОВ (ТЕКСТОВЫЕ) ====================
@dp.message(lambda msg: msg.chat.type != "private" and msg.text and msg.text.lower() in ["б", "бал", "баланс"])
async def chat_balance(message: Message):
    user = get_user(message.from_user.id)
    await message.reply(f"💰 Баланс: {user['balance']:,} POCX" if user else "💰 Баланс: 5000 POCX")

@dp.message(lambda msg: msg.chat.type != "private" and msg.text and msg.text.lower() in ["п", "проф", "профиль"])
async def chat_profile(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.reply("👤 Профиль не найден")
        return
    vip, _ = get_vip(user["total_wagered"])
    await message.reply(
        f"👤 <b>Профиль</b>\n\n"
        f"💰 Баланс: {user['balance']:,} POCX\n"
        f"💎 VIP: {vip}\n"
        f"📊 Вейджер: {user['total_wagered']:,} POCX\n"
        f"🏆 Выиграно: {user['total_won']:,} POCX\n"
        f"💸 Проиграно: {user['total_lost']:,} POCX",
        parse_mode=ParseMode.HTML
    )

@dp.message(lambda msg: msg.chat.type != "private" and msg.text and msg.text.lower() in ["т", "топ", "топы"])
async def chat_top(message: Message):
    cursor.execute("SELECT user_id, username, total_won FROM users ORDER BY total_won DESC LIMIT 10")
    rows = cursor.fetchall()
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Топ игроков</b>\n"]
    for i, row in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = row[1] or f"ID{row[0]}"
        lines.append(f"{medal} {name} — <b>{row[2]:,} POCX</b>")
    await message.reply("\n".join(lines), parse_mode=ParseMode.HTML)

@dp.message(lambda msg: msg.chat.type != "private" and msg.text and msg.text.lower() in ["р", "реф", "рефералы"])
async def chat_refs(message: Message):
    user = get_user(message.from_user.id)
    cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (message.from_user.id,))
    count = cursor.fetchone()[0]
    cursor.execute("SELECT COALESCE(SUM(earned_amount), 0) FROM referrals WHERE referrer_id = ?", (message.from_user.id,))
    earned = cursor.fetchone()[0]
    await message.reply(f"👥 <b>Рефералы</b>\n\n👤 Приглашено: {count}\n💰 Заработано: {earned:,} POCX", parse_mode=ParseMode.HTML)

@dp.message(lambda msg: msg.chat.type != "private" and msg.text and msg.text.lower() in ["бн", "бонус", "бонусы"])
async def chat_bonus(message: Message):
    uid = message.from_user.id
    cursor.execute("SELECT last_daily_bonus, daily_streak FROM users WHERE user_id = ?", (uid,))
    row = cursor.fetchone()
    last = row[0] if row else None
    streak = row[1] if row else 0
    
    if last:
        last_dt = datetime.fromisoformat(last)
        if datetime.now() - last_dt < timedelta(days=1):
            await message.reply("❌ Бонус уже получен сегодня!")
            return
    
    bonus = random.randint(100, 2000)
    add_pocx(uid, bonus)
    cursor.execute("UPDATE users SET last_daily_bonus = CURRENT_TIMESTAMP, daily_streak = daily_streak + 1 WHERE user_id = ?", (uid,))
    conn.commit()
    await message.reply(f"🎁 +{bonus:,} POCX\n🔥 Серия: {streak + 1}")

@dp.message(lambda msg: msg.chat.type != "private" and msg.text and msg.text.lower() in ["ст", "стата", "статистика"])
async def chat_stats(message: Message):
    user = get_user(message.from_user.id)
    cursor.execute("SELECT COUNT(*) FROM game_history WHERE user_id = ?", (message.from_user.id,))
    played = cursor.fetchone()[0] if user else 0
    cursor.execute("SELECT COUNT(*) FROM game_history WHERE user_id = ? AND result = 'win'", (message.from_user.id,))
    wins = cursor.fetchone()[0] if user else 0
    winrate = wins / max(played, 1) * 100
    await message.reply(f"📊 <b>Статистика</b>\n\n🎮 Игр: {played}\n✅ Побед: {wins} ({winrate:.1f}%)", parse_mode=ParseMode.HTML)

@dp.message(lambda msg: msg.chat.type != "private" and msg.text and msg.text.lower() in ["и", "игры"])
async def chat_games(message: Message):
    await message.reply(
        "🎮 <b>Игры</b>\n\n"
        "• <code>dice [шанс] [сумма]</code> - шанс 1,5,10,25,33,50\n"
        "• <code>краш [сумма]</code> - Crash\n"
        "• <code>руль [красное/черное/чет/нечет/зеро] [сумма]</code>\n"
        "• <code>монета [орёл/решка] [сумма]</code> - 2x\n"
        "• <code>хило [выше/ниже/равно] [сумма]</code>\n\n"
        "Пример: <code>dice 5 1000</code>\n\n"
        "💰 Сокращения ставок: 1к = 1000, 10к = 10000, 1кк = 1_000_000 и т.д.",
        parse_mode=ParseMode.HTML
    )

@dp.message(lambda msg: msg.chat.type != "private" and msg.text and msg.text.lower() in ["помощь", "help", "/help"])
async def chat_help(message: Message):
    await message.reply(
        "📖 <b>Доступные команды в чате:</b>\n\n"
        "• <code>б</code> или <code>баланс</code> – показать баланс\n"
        "• <code>п</code> или <code>профиль</code> – профиль\n"
        "• <code>т</code> или <code>топ</code> – топ игроков\n"
        "• <code>р</code> или <code>рефералы</code> – реферальная статистика\n"
        "• <code>бн</code> или <code>бонус</code> – ежедневный бонус\n"
        "• <code>ст</code> или <code>статистика</code> – игровая статистика\n"
        "• <code>и</code> или <code>игры</code> – список игр\n"
        "• <code>помощь</code> – это сообщение\n\n"
        "🎮 <b>Игровые команды:</b>\n"
        "• <code>dice [шанс] [сумма]</code>\n"
        "• <code>краш [сумма]</code>\n"
        "• <code>руль [ставка] [сумма]</code>\n"
        "• <code>монета [орёл/решка] [сумма]</code>\n"
        "• <code>хило [выше/ниже/равно] [сумма]</code>\n\n"
        "💰 Сумму можно указывать с суффиксами: 1к = 1000, 10кк = 10_000_000 и т.д.",
        parse_mode=ParseMode.HTML
    )

# ==================== DICE (исправлен) ====================
def dice_game_impl(bet: int, chance: int) -> tuple:
    tgt = chance
    multi = round((100 / chance) * (1 - HOUSE_EDGE), 2)
    r = random.randint(1, 100)
    win = r < tgt
    win_amount = int(bet * multi) if win else 0
    return win, win_amount, multi, r

@dp.message(lambda msg: msg.text and msg.text.lower().startswith("dice"))
async def dice_game(message: Message):
    parts = message.text.lower().split()
    if len(parts) != 3:
        await message.reply("❌ Формат: <code>dice [шанс] [сумма]</code>\nПример: <code>dice 5 1000</code>")
        return
    
    try:
        chance = int(parts[1])
        if chance not in [1, 5, 10, 25, 33, 50]:
            raise ValueError
        bet = parse_amount(parts[2])
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.reply(f"❌ Шанс: 1,5,10,25,33,50 | Ставка: от {MIN_BET} до {MAX_BET}")
        return
    
    if not check_cooldown(message.from_user.id):
        await message.reply("⏳ Подожди 5 секунд!")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств!")
        return
    
    win, win_amount, multi, r = dice_game_impl(bet, chance)
    
    if win:
        add_pocx(message.from_user.id, win_amount)
    
    record_game(message.from_user.id, "dice", bet, multi if win else 0, win_amount, "win" if win else "loss", {"roll": r, "target": chance})
    
    if win:
        await message.reply(f"🎲 <b>Dice</b>\nВыпало: {r} | Цель: <{chance}\n✅ +{win_amount} POCX ({multi}x)", parse_mode=ParseMode.HTML)
    else:
        await message.reply(f"🎲 <b>Dice</b>\nВыпало: {r} | Цель: <{chance}\n❌ -{bet} POCX", parse_mode=ParseMode.HTML)

# ==================== CRASH (с поддержкой сокращений ставок) ====================
@dp.message(lambda msg: msg.text and msg.text.lower().startswith("краш"))
async def crash_game(message: Message):
    parts = message.text.lower().split()
    if len(parts) != 2:
        await message.reply("❌ Формат: <code>краш [сумма]</code>\nПример: <code>краш 1000</code>")
        return
    
    try:
        bet = parse_amount(parts[1])
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.reply(f"❌ Ставка от {MIN_BET} до {MAX_BET}")
        return
    
    if not check_cooldown(message.from_user.id):
        await message.reply("⏳ Подожди 5 секунд!")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств!")
        return
    
    r = random.random()
    if r < 0.06:
        crash_point = 1.00
    elif r < 0.55:
        crash_point = round(random.uniform(1.01, 1.80), 2)
    elif r < 0.80:
        crash_point = round(random.uniform(1.81, 2.80), 2)
    elif r < 0.93:
        crash_point = round(random.uniform(2.81, 4.50), 2)
    elif r < 0.985:
        crash_point = round(random.uniform(4.51, 9.50), 2)
    else:
        crash_point = round(random.uniform(9.51, 10.0), 2)
    
    multiplier = round(crash_point * 0.85, 2)
    multiplier = max(1.01, multiplier)
    win_amount = int(bet * multiplier)
    add_pocx(message.from_user.id, win_amount)
    record_game(message.from_user.id, "crash", bet, multiplier, win_amount, "win", {"crash_point": crash_point})
    
    await message.reply(f"🚀 <b>Crash</b>\n\n💥 Краш на {crash_point}x\n📈 Ты забрал на {multiplier}x\n✅ +{win_amount} POCX", parse_mode=ParseMode.HTML)

# ==================== РУЛЕТКА ====================
@dp.message(lambda msg: msg.text and msg.text.lower().startswith("руль"))
async def roulette_game(message: Message):
    parts = message.text.lower().split()
    if len(parts) != 3:
        await message.reply("❌ Формат: <code>руль [красное/черное/чет/нечет/зеро] [сумма]</code>")
        return
    
    bet_type_map = {
        "красное": "red", "красный": "red",
        "черное": "black", "черный": "black",
        "чет": "even", "чёт": "even",
        "нечет": "odd", "нечёт": "odd",
        "зеро": "zero", "zero": "zero"
    }
    
    bet_type = bet_type_map.get(parts[1])
    if not bet_type:
        await message.reply("❌ Ставка: красное, черное, чет, нечет, зеро")
        return
    
    try:
        bet = parse_amount(parts[2])
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.reply(f"❌ Ставка от {MIN_BET} до {MAX_BET}")
        return
    
    if not check_cooldown(message.from_user.id):
        await message.reply("⏳ Подожди 5 секунд!")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств!")
        return
    
    number = random.randint(0, 36)
    RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
    BLACK = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}
    
    color = "🟢" if number == 0 else ("🔴" if number in RED else "⚫")
    
    win = False
    multiplier = 0
    if bet_type == "red" and number in RED:
        win, multiplier = True, 2.0
    elif bet_type == "black" and number in BLACK:
        win, multiplier = True, 2.0
    elif bet_type == "zero" and number == 0:
        win, multiplier = True, 35.0
    elif bet_type == "even" and number != 0 and number % 2 == 0:
        win, multiplier = True, 2.0
    elif bet_type == "odd" and number != 0 and number % 2 == 1:
        win, multiplier = True, 2.0
    
    win_amount = int(bet * multiplier) if win else 0
    
    if win:
        add_pocx(message.from_user.id, win_amount)
    
    record_game(message.from_user.id, "roulette", bet, multiplier if win else 0, win_amount, "win" if win else "loss", {"number": number})
    
    if win:
        await message.reply(f"🎡 <b>Рулетка</b>\n{color} {number}\n✅ +{win_amount} POCX ({multiplier}x)", parse_mode=ParseMode.HTML)
    else:
        await message.reply(f"🎡 <b>Рулетка</b>\n{color} {number}\n❌ -{bet} POCX", parse_mode=ParseMode.HTML)

# ==================== COIN FLIP ====================
@dp.message(lambda msg: msg.text and msg.text.lower().startswith("монета"))
async def coin_game(message: Message):
    parts = message.text.lower().split()
    if len(parts) != 3:
        await message.reply("❌ Формат: <code>монета [орёл/решка] [сумма]</code>")
        return
    
    side_map = {"орёл": "heads", "орел": "heads", "решка": "tails"}
    side = side_map.get(parts[1])
    if not side:
        await message.reply("❌ Выбери: орёл или решка")
        return
    
    try:
        bet = parse_amount(parts[2])
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.reply(f"❌ Ставка от {MIN_BET} до {MAX_BET}")
        return
    
    if not check_cooldown(message.from_user.id):
        await message.reply("⏳ Подожди 5 секунд!")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств!")
        return
    
    result = random.choice(["heads", "tails"])
    win = result == side
    multiplier = round(2.0 * (1 - HOUSE_EDGE), 2) if win else 0
    win_amount = int(bet * multiplier) if win else 0
    
    if win:
        add_pocx(message.from_user.id, win_amount)
    
    record_game(message.from_user.id, "coinflip", bet, multiplier if win else 0, win_amount, "win" if win else "loss", {"result": result})
    
    res_label = "🦅 Орёл" if result == "heads" else "🔢 Решка"
    
    if win:
        await message.reply(f"🪙 <b>Coin Flip</b>\nВыпало: {res_label}\n✅ +{win_amount} POCX (2x)", parse_mode=ParseMode.HTML)
    else:
        await message.reply(f"🪙 <b>Coin Flip</b>\nВыпало: {res_label}\n❌ -{bet} POCX", parse_mode=ParseMode.HTML)

# ==================== HI-LO ====================
@dp.message(lambda msg: msg.text and msg.text.lower().startswith("хило"))
async def hilo_game(message: Message):
    parts = message.text.lower().split()
    if len(parts) != 3:
        await message.reply("❌ Формат: <code>хило [выше/ниже/равно] [сумма]</code>")
        return
    
    direction_map = {"выше": "higher", "ниже": "lower", "равно": "same"}
    direction = direction_map.get(parts[1])
    if not direction:
        await message.reply("❌ Выбери: выше, ниже или равно")
        return
    
    try:
        bet = parse_amount(parts[2])
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.reply(f"❌ Ставка от {MIN_BET} до {MAX_BET}")
        return
    
    if not check_cooldown(message.from_user.id):
        await message.reply("⏳ Подожди 5 секунд!")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств!")
        return
    
    RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    SUITS = ["♠️", "♥️", "♦️", "♣️"]
    
    current_card = random.choice(RANKS)
    old_rank = RANKS.index(current_card)
    new_card = random.choice(RANKS)
    new_rank = RANKS.index(new_card)
    suit = random.choice(SUITS)
    
    if direction == "higher":
        win = new_rank > old_rank
    elif direction == "lower":
        win = new_rank < old_rank
    else:
        win = new_rank == old_rank
    
    if win:
        round_multi = 10.0 if direction == "same" else 1.5
        multiplier = round(round_multi * (1 - HOUSE_EDGE), 3)
        win_amount = int(bet * multiplier)
        add_pocx(message.from_user.id, win_amount)
        await message.reply(f"🃏 <b>Hi-Lo</b>\nПервая: {current_card}\nСледующая: {new_card}{suit}\n✅ +{win_amount} POCX ({multiplier}x)", parse_mode=ParseMode.HTML)
    else:
        await message.reply(f"🃏 <b>Hi-Lo</b>\nПервая: {current_card}\nСледующая: {new_card}{suit}\n❌ -{bet} POCX", parse_mode=ParseMode.HTML)

# ==================== КЛАВИАТУРА В ЛС ====================
@dp.message(F.text == "🎮 Игры")
async def games(message: Message):
    await message.answer("🎮 <b>Выбери игру</b>", reply_markup=games_menu())

@dp.message(F.text == "💰 Финансы")
async def finance(message: Message):
    await message.answer("💰 <b>Финансы</b>\n\n⭐ 1 Star = 2500 POCX", reply_markup=finance_menu())

@dp.message(F.text == "🏆 Топ")
async def top(message: Message):
    cursor.execute("SELECT user_id, username, total_won FROM users ORDER BY total_won DESC LIMIT 10")
    rows = cursor.fetchall()
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Топ игроков</b>\n"]
    for i, row in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = row[1] or f"ID{row[0]}"
        lines.append(f"{medal} {name} — <b>{row[2]:,} POCX</b>")
    await message.answer("\n".join(lines), reply_markup=main_menu(), parse_mode=ParseMode.HTML)

@dp.message(F.text == "🎁 Бонусы")
async def bonuses(message: Message):
    await message.answer("🎁 <b>Бонусы</b>\n\nЕжедневный бонус: 100-2000 POCX\nПриветственный: 1000 POCX", reply_markup=bonuses_menu())

@dp.message(F.text == "👥 Рефералы")
async def referrals(message: Message):
    user = get_user(message.from_user.id)
    cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (message.from_user.id,))
    count = cursor.fetchone()[0]
    cursor.execute("SELECT COALESCE(SUM(earned_amount), 0) FROM referrals WHERE referrer_id = ?", (message.from_user.id,))
    earned = cursor.fetchone()[0]
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref{user['referral_code']}"
    
    await message.answer(
        f"👥 <b>Рефералы</b>\n\n"
        f"🔗 Ваша ссылка:\n<code>{link}</code>\n\n"
        f"👤 Рефералов: {count}\n"
        f"💰 Заработано: {earned:,} POCX\n\n"
        f"🎁 За каждого друга: +{REF_REWARD:,} POCX вам и +{REF_REFERRAL_BONUS:,} другу",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "📊 Статистика")
async def stats(message: Message):
    user = get_user(message.from_user.id)
    cursor.execute("SELECT COUNT(*) FROM game_history WHERE user_id = ?", (message.from_user.id,))
    played = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM game_history WHERE user_id = ? AND result = 'win'", (message.from_user.id,))
    wins = cursor.fetchone()[0]
    cursor.execute("SELECT MAX(multiplier) FROM game_history WHERE user_id = ? AND result = 'win'", (message.from_user.id,))
    best = cursor.fetchone()[0] or 0
    winrate = wins / max(played, 1) * 100
    roi = (user["total_won"] - user["total_lost"]) / max(user["total_wagered"], 1) * 100
    
    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"🎮 Игр сыграно: {played}\n"
        f"✅ Побед: {wins} ({winrate:.1f}%)\n"
        f"📈 Лучший множитель: {best:.2f}x\n"
        f"📊 ROI: {roi:.1f}%\n"
        f"💰 Общий вейджер: {user['total_wagered']:,} POCX\n"
        f"🏆 Выиграно всего: {user['total_won']:,} POCX",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "👤 Профиль")
async def profile(message: Message):
    user = get_user(message.from_user.id)
    vip, cb_pct = get_vip(user["total_wagered"])
    status = user.get("custom_status") or "Обычный игрок"
    await message.answer(
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 ID: {user['user_id']}\n"
        f"📛 Имя: {message.from_user.first_name}\n"
        f"💰 Баланс: {user['balance']:,} POCX\n"
        f"💎 VIP: {vip} (кэшбэк {cb_pct}%)\n"
        f"🏷 Статус: {status}\n"
        f"📊 Всего поставлено: {user['total_wagered']:,} POCX\n"
        f"🏆 Выиграно: {user['total_won']:,} POCX\n"
        f"💸 Проиграно: {user['total_lost']:,} POCX\n"
        f"🔥 Серия дней: {user['daily_streak']}",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )

# ==================== КЛАНЫ ====================
@dp.message(F.text == "⭐ Кланы")
async def clans_menu(message: Message):
    await message.answer("🏰 <b>Кланы</b>\n\nВыбери действие:", reply_markup=clan_menu(), parse_mode=ParseMode.HTML)

@dp.message(F.text == "➕ Создать клан")
async def clan_create_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS and get_user(message.from_user.id)["balance"] < CLAN_CREATION_COST and not await can_use_stars(message.from_user.id, CLAN_CREATION_STARS):
        await message.answer(f"❌ Недостаточно средств. Нужно {CLAN_CREATION_COST:,} POCX или {CLAN_CREATION_STARS} ⭐")
        return
    await state.set_state(GameStates.clan_create_name)
    await message.answer("🏰 Введи название клана (от 3 до 20 символов):", reply_markup=cancel_menu())

@dp.message(GameStates.clan_create_name)
async def clan_create_name(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Создание отменено", reply_markup=clan_menu())
        return
    name = message.text.strip()
    if len(name) < 3 or len(name) > 20:
        await message.answer("❌ Название должно быть 3-20 символов!")
        return
    cursor.execute("SELECT 1 FROM clans WHERE name = ?", (name,))
    if cursor.fetchone():
        await message.answer("❌ Клан с таким названием уже существует!")
        return
    
    uid = message.from_user.id
    user = get_user(uid)
    # Списываем средства
    if user["balance"] >= CLAN_CREATION_COST:
        remove_pocx(uid, CLAN_CREATION_COST)
        stars_used = 0
    else:
        # использовать Stars
        await bot.send_invoice(
            chat_id=uid,
            title="Создание клана",
            description=f"Создание клана {name}",
            payload=f"clan_creation_{name}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Создание клана", amount=CLAN_CREATION_STARS)],
            start_parameter="clan_creation"
        )
        await state.update_data(clan_name=name)
        return
    
    cursor.execute("INSERT INTO clans (name, owner_id, stars_used) VALUES (?, ?, ?)", (name, uid, stars_used))
    cursor.execute("UPDATE users SET clan_id = ? WHERE user_id = ?", (cursor.lastrowid, uid))
    conn.commit()
    await message.answer(f"✅ Клан <b>{name}</b> создан!", reply_markup=clan_menu(), parse_mode=ParseMode.HTML)
    await state.clear()

@dp.message(F.text == "📋 Мои кланы")
async def my_clans(message: Message):
    user = get_user(message.from_user.id)
    if not user["clan_id"]:
        await message.answer("❌ Ты не состоишь ни в одном клане!")
        return
    cursor.execute("SELECT * FROM clans WHERE id = ?", (user["clan_id"],))
    clan = cursor.fetchone()
    if not clan:
        await message.answer("❌ Клан не найден!")
        return
    cursor.execute("SELECT COUNT(*) FROM users WHERE clan_id = ?", (clan[0],))
    members = cursor.fetchone()[0]
    await message.answer(
        f"🏰 <b>Клан:</b> {clan[1]}\n"
        f"👑 Владелец: {clan[2]}\n"
        f"👥 Участников: {members}\n"
        f"💰 Казна: {clan[3]:,} POCX",
        parse_mode=ParseMode.HTML,
        reply_markup=clan_menu()
    )

@dp.message(F.text == "📊 Топ кланов")
async def top_clans(message: Message):
    cursor.execute("SELECT name, treasury, (SELECT COUNT(*) FROM users WHERE users.clan_id = clans.id) as members FROM clans ORDER BY treasury DESC LIMIT 10")
    rows = cursor.fetchall()
    if not rows:
        await message.answer("🏆 Пока нет кланов")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Топ кланов по казне</b>\n"]
    for i, row in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        lines.append(f"{medal} {row[0]} — {row[2]} уч. | казна {row[1]:,} POCX")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=clan_menu())

@dp.message(F.text == "🔍 Найти клан")
async def find_clan_start(message: Message, state: FSMContext):
    await state.set_state(GameStates.clan_find)
    await message.answer("🔍 Введи название клана или его ID:", reply_markup=cancel_menu())

@dp.message(GameStates.clan_find)
async def find_clan(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Поиск отменен", reply_markup=clan_menu())
        return
    query = message.text.strip()
    if query.isdigit():
        cursor.execute("SELECT * FROM clans WHERE id = ?", (int(query),))
    else:
        cursor.execute("SELECT * FROM clans WHERE name LIKE ?", (f"%{query}%",))
    clan = cursor.fetchone()
    if not clan:
        await message.answer("❌ Клан не найден!")
        return
    cursor.execute("SELECT COUNT(*) FROM users WHERE clan_id = ?", (clan[0],))
    members = cursor.fetchone()[0]
    await message.answer(
        f"🏰 <b>Клан:</b> {clan[1]}\n"
        f"👑 Владелец: {clan[2]}\n"
        f"👥 Участников: {members}\n"
        f"💰 Казна: {clan[3]:,} POCX\n\n"
        f"Чтобы вступить, напиши владельцу или администратору.",
        parse_mode=ParseMode.HTML
    )
    await state.clear()

@dp.message(F.text == "💸 Пополнить казну клана")
async def clan_treasury_add_start(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if not user["clan_id"]:
        await message.answer("❌ Ты не состоишь в клане!")
        return
    await state.set_state(GameStates.clan_treasury_add)
    await message.answer("💰 Введи сумму для пополнения казны клана (можно с суффиксами 1к, 1кк):", reply_markup=cancel_menu())

@dp.message(GameStates.clan_treasury_add)
async def clan_treasury_add(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=clan_menu())
        return
    amount = parse_amount(message.text)
    if amount <= 0:
        await message.answer("❌ Введи корректную сумму!")
        return
    user = get_user(message.from_user.id)
    if user["balance"] < amount:
        await message.answer("❌ Недостаточно средств!")
        return
    remove_pocx(message.from_user.id, amount)
    cursor.execute("UPDATE clans SET treasury = treasury + ? WHERE id = ?", (amount, user["clan_id"]))
    conn.commit()
    await message.answer(f"✅ Клан пополнен на {amount:,} POCX!", reply_markup=clan_menu())
    await state.clear()

@dp.message(F.text == "🚪 Выйти из клана")
async def clan_leave(message: Message):
    user = get_user(message.from_user.id)
    if not user["clan_id"]:
        await message.answer("❌ Ты не состоишь в клане!")
        return
    cursor.execute("SELECT owner_id FROM clans WHERE id = ?", (user["clan_id"],))
    owner = cursor.fetchone()[0]
    if owner == message.from_user.id:
        await message.answer("❌ Владелец не может выйти из клана. Передай права или удали клан командой для админа.")
        return
    cursor.execute("UPDATE users SET clan_id = NULL WHERE user_id = ?", (message.from_user.id,))
    conn.commit()
    await message.answer("✅ Ты вышел из клана.", reply_markup=clan_menu())

# ==================== КАЗНА ЧАТА ====================
@dp.message(F.text == "🏦 Казна чата")
async def chat_treasury_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Только для админов!")
        return
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="➕ Пополнить казну"), KeyboardButton(text="💸 Вывести из казны")],
        [KeyboardButton(text="◀️ Назад")]
    ], resize_keyboard=True)
    await message.answer("🏦 <b>Управление казной чата</b>", reply_markup=kb, parse_mode=ParseMode.HTML)

@dp.message(F.text == "➕ Пополнить казну")
async def chat_treasury_add_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    await state.set_state(GameStates.chat_treasury_add)
    await message.answer("💰 Введи сумму пополнения казны чата:", reply_markup=cancel_menu())

@dp.message(GameStates.chat_treasury_add)
async def chat_treasury_add(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_menu())
        return
    amount = parse_amount(message.text)
    if amount <= 0:
        await message.answer("❌ Введи положительное число!")
        return
    # Здесь можно указать конкретный chat_id, но для упрощения – используем чат, откуда команда
    chat_id = message.chat.id
    cursor.execute("INSERT INTO chat_treasury (chat_id, amount) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET amount = amount + ?", (chat_id, amount, amount))
    conn.commit()
    await message.answer(f"✅ Казна чата пополнена на {amount:,} POCX!", reply_markup=admin_menu())
    await state.clear()

@dp.message(F.text == "💸 Вывести из казны")
async def chat_treasury_withdraw_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    await state.set_state(GameStates.chat_treasury_withdraw)
    await message.answer("💰 Введи сумму вывода из казны чата:", reply_markup=cancel_menu())

@dp.message(GameStates.chat_treasury_withdraw)
async def chat_treasury_withdraw(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_menu())
        return
    amount = parse_amount(message.text)
    if amount <= 0:
        await message.answer("❌ Введи положительное число!")
        return
    chat_id = message.chat.id
    cursor.execute("SELECT amount FROM chat_treasury WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    if not row or row[0] < amount:
        await message.answer("❌ В казне недостаточно средств!")
        return
    cursor.execute("UPDATE chat_treasury SET amount = amount - ? WHERE chat_id = ?", (amount, chat_id))
    add_pocx(message.from_user.id, amount)
    conn.commit()
    await message.answer(f"✅ Выведено {amount:,} POCX из казны чата!", reply_markup=admin_menu())
    await state.clear()

@dp.message(F.text == "◀️ Назад")
async def back_from_treasury(message: Message):
    await message.answer("👑 <b>Админ-панель</b>", reply_markup=admin_menu())

# ==================== АДМИН: НАЗНАЧИТЬ СТАТУС ====================
@dp.message(F.text == "👑 Назначить статус")
async def assign_status_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    await state.set_state(GameStates.assign_status_user)
    await message.answer("👤 Введи ID пользователя:", reply_markup=cancel_menu())

@dp.message(GameStates.assign_status_user)
async def assign_status_user(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_menu())
        return
    if not message.text.isdigit():
        await message.answer("❌ Введи числовой ID!")
        return
    await state.update_data(target_user=int(message.text))
    await state.set_state(GameStates.assign_status_text)
    await message.answer("🏷 Введи текст статуса (например, 'Легенда', 'VIP', 'Проверенный'):")

@dp.message(GameStates.assign_status_text)
async def assign_status_text(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_menu())
        return
    status_text = message.text.strip()
    data = await state.get_data()
    target = data["target_user"]
    cursor.execute("INSERT OR REPLACE INTO user_statuses (user_id, status, assigned_by) VALUES (?, ?, ?)", (target, status_text, message.from_user.id))
    cursor.execute("UPDATE users SET custom_status = ? WHERE user_id = ?", (status_text, target))
    conn.commit()
    await message.answer(f"✅ Пользователю {target} назначен статус: {status_text}", reply_markup=admin_menu())
    await state.clear()

# ==================== ОСТАЛЬНЫЕ РАЗДЕЛЫ (БОНУСЫ, ПРОМОКОДЫ, STARS ПОПОЛНЕНИЕ) ====================
@dp.message(F.text == "🎁 Ежедневный бонус")
async def daily_bonus(message: Message):
    uid = message.from_user.id
    cursor.execute("SELECT last_daily_bonus, daily_streak FROM users WHERE user_id = ?", (uid,))
    row = cursor.fetchone()
    last = row[0] if row else None
    streak = row[1] if row else 0
    
    if last:
        last_dt = datetime.fromisoformat(last)
        if datetime.now() - last_dt < timedelta(days=1):
            await message.answer("❌ Бонус уже получен сегодня!", reply_markup=bonuses_menu())
            return
    
    bonus = random.randint(DAILY_BONUS_MIN, DAILY_BONUS_MAX)
    bonus = int(bonus * (1 + min(streak * 0.05, 0.5)))
    add_pocx(uid, bonus)
    cursor.execute("UPDATE users SET last_daily_bonus = CURRENT_TIMESTAMP, daily_streak = daily_streak + 1 WHERE user_id = ?", (uid,))
    conn.commit()
    
    await message.answer(
        f"🎁 <b>Ежедневный бонус!</b>\n\n💰 +{bonus:,} POCX\n🔥 Серия дней: {streak + 1}",
        reply_markup=bonuses_menu(),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "🆕 Приветственный бонус")
async def welcome_bonus(message: Message):
    uid = message.from_user.id
    cursor.execute("SELECT welcome_bonus_claimed FROM users WHERE user_id = ?", (uid,))
    row = cursor.fetchone()
    if row and row[0]:
        await message.answer("❌ Приветственный бонус уже получен!", reply_markup=bonuses_menu())
        return
    
    add_pocx(uid, WELCOME_BONUS)
    cursor.execute("UPDATE users SET welcome_bonus_claimed = 1 WHERE user_id = ?", (uid,))
    conn.commit()
    
    await message.answer(f"🎁 <b>Приветственный бонус!</b>\n\n💰 +{WELCOME_BONUS:,} POCX", reply_markup=bonuses_menu(), parse_mode=ParseMode.HTML)

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
    cursor.execute("SELECT bonus_amount, max_uses, used_count, expires_at, is_active FROM promocodes WHERE code = ?", (code,))
    row = cursor.fetchone()
    if not row or not row[4] or row[2] >= row[1]:
        await message.answer("❌ Промокод недействителен!", reply_markup=bonuses_menu())
        await state.clear()
        return
    if row[3] and datetime.fromisoformat(row[3]) < datetime.now():
        await message.answer("❌ Промокод истёк!", reply_markup=bonuses_menu())
        await state.clear()
        return
    cursor.execute("SELECT 1 FROM used_promocodes WHERE user_id = ? AND code = ?", (message.from_user.id, code))
    if cursor.fetchone():
        await message.answer("❌ Вы уже использовали этот промокод!", reply_markup=bonuses_menu())
        await state.clear()
        return
    
    bonus = row[0]
    add_pocx(message.from_user.id, bonus)
    cursor.execute("INSERT INTO used_promocodes (user_id, code) VALUES (?, ?)", (message.from_user.id, code))
    cursor.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?", (code,))
    conn.commit()
    
    await message.answer(f"✅ Промокод активирован!\n💰 +{bonus:,} POCX", reply_markup=bonuses_menu())
    await state.clear()

# ==================== ПОПОЛНЕНИЕ STARS ====================
@dp.message(F.text == "⭐ Пополнить Stars")
async def donate(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 1 Star - 2,500 POCX", callback_data="donate_1")],
        [InlineKeyboardButton(text="⭐⭐ 5 Stars - 12,500 POCX", callback_data="donate_5")],
        [InlineKeyboardButton(text="⭐⭐⭐ 10 Stars - 25,000 POCX", callback_data="donate_10")],
        [InlineKeyboardButton(text="💰 25 Stars - 62,500 POCX", callback_data="donate_25")],
        [InlineKeyboardButton(text="💎 50 Stars - 125,000 POCX", callback_data="donate_50")],
        [InlineKeyboardButton(text="✏️ Своя сумма", callback_data="donate_custom")]
    ])
    await message.answer("💎 <b>Пополнение через Telegram Stars</b>\n\n⭐ 1 Star = 2500 POCX", reply_markup=kb, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("donate_"))
async def process_donate(callback: CallbackQuery, state: FSMContext):
    if callback.data == "donate_custom":
        await state.set_state(GameStates.donate_custom)
        await callback.message.edit_text("💰 Введи количество Stars (1-1000):")
        await callback.answer()
        return
    
    stars = int(callback.data.split("_")[1])
    pocx = stars * 2500
    
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Пополнение POCX",
        description=f"Получи {pocx:,} POCX за {stars} ⭐\nКурс: 1⭐ = 2500 POCX",
        payload=f"stars_{stars}_{pocx}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"{stars} Telegram Stars", amount=stars)],
        start_parameter="donate"
    )
    await callback.answer()

@dp.message(GameStates.donate_custom)
async def donate_custom(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введи число!")
        return
    stars = int(message.text)
    if stars < 1 or stars > 1000:
        await message.answer("❌ От 1 до 1000 Stars!")
        return
    
    pocx = stars * 2500
    await bot.send_invoice(
        chat_id=message.from_user.id,
        title="Пополнение POCX",
        description=f"Получи {pocx:,} POCX за {stars} ⭐\nКурс: 1⭐ = 2500 POCX",
        payload=f"stars_{stars}_{pocx}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"{stars} Telegram Stars", amount=stars)],
        start_parameter="donate"
    )
    await state.clear()

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(query.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    if payload.startswith("clan_creation_"):
        name = payload[15:]
        uid = message.from_user.id
        cursor.execute("INSERT INTO clans (name, owner_id, stars_used) VALUES (?, ?, 1)", (name, uid))
        cursor.execute("UPDATE users SET clan_id = ? WHERE user_id = ?", (cursor.lastrowid, uid))
        conn.commit()
        await message.answer(f"✅ Клан <b>{name}</b> создан за Stars!", reply_markup=clan_menu(), parse_mode=ParseMode.HTML)
        return
    # обычное пополнение
    _, stars, pocx = payload.split("_")
    stars = int(stars)
    pocx = int(pocx)
    add_pocx(message.from_user.id, pocx)
    await message.answer(
        f"✅ Оплачено {stars} ⭐!\n💰 Получено {pocx:,} POCX\n\n⭐ 1 Star = 2500 POCX",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )

# ==================== АДМИН-ПАНЕЛЬ (остальное) ====================
@dp.message(F.text == "👑 Админ")
async def admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!", reply_markup=main_menu())
        return
    await message.answer("👑 <b>Админ-панель</b>", reply_markup=admin_menu(), parse_mode=ParseMode.HTML)

# ... (остальные админ-функции: выдать, забрать, бан, разбан, промокоды, рассылка – они уже были в коде, здесь я их не повторяю для краткости, но они должны остаться)

# ==================== ЗАПУСК ====================
async def main():
    print("🤖 POCX Bot запущен!")
    print(f"👥 Админы: {ADMIN_IDS}")
    print("✅ Игры: Dice, Crash, Рулетка, Coin Flip, Hi-Lo")
    print("✅ Кланы, казна чатов, назначение статусов")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
