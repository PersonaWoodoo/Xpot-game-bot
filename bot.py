import asyncio
import random
import sqlite3
import hashlib
import time
import json
import os
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
MAX_BET = 500000
HOUSE_EDGE = 0.01
CRASH_HOUSE_EDGE = 0.03

DAILY_BONUS_MIN = 100
DAILY_BONUS_MAX = 2000
WELCOME_BONUS = 1000
REF_REWARD = 5000

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

bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# ==================== УДАЛЕНИЕ СТАРОЙ БАЗЫ ====================
if os.path.exists("pocx_bot.db"):
    os.remove("pocx_bot.db")
    print("✅ Старая база данных удалена")

# ==================== БАЗА ДАННЫХ ====================
conn = sqlite3.connect("pocx_bot.db", check_same_thread=False)
cursor = conn.cursor()

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
    last_game_time INTEGER DEFAULT 0
)
""")

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

cursor.execute("""
CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id INTEGER,
    referred_id INTEGER,
    earned_amount INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS banned_users (
    user_id INTEGER PRIMARY KEY,
    banned_at INTEGER,
    reason TEXT
)
""")

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

conn.commit()
print("✅ Новая база данных создана")

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
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

# ==================== REPLY-КЛАВИАТУРЫ ====================
def main_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎮 Игры"), KeyboardButton(text="💰 Финансы")],
            [KeyboardButton(text="🏆 Топы"), KeyboardButton(text="🎁 Бонусы")],
            [KeyboardButton(text="👥 Рефералы"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="ℹ️ Профиль"), KeyboardButton(text="👑 Админ")]
        ],
        resize_keyboard=True
    )

def games_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎲 Dice"), KeyboardButton(text="🚀 Crash")],
            [KeyboardButton(text="🎡 Рулетка"), KeyboardButton(text="🎰 Слоты")],
            [KeyboardButton(text="🪙 Coin Flip"), KeyboardButton(text="🃏 Hi-Lo")],
            [KeyboardButton(text="◀️ Главное меню")]
        ],
        resize_keyboard=True
    )

def finance_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⭐ Пополнить Stars")],
            [KeyboardButton(text="◀️ Главное меню")]
        ],
        resize_keyboard=True
    )

def bonuses_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎁 Ежедневный бонус"), KeyboardButton(text="🆕 Приветственный бонус")],
            [KeyboardButton(text="🔑 Активировать промокод")],
            [KeyboardButton(text="◀️ Главное меню")]
        ],
        resize_keyboard=True
    )

def admin_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика админа")],
            [KeyboardButton(text="💰 Выдать POCX"), KeyboardButton(text="➖ Забрать POCX")],
            [KeyboardButton(text="🔨 Забанить"), KeyboardButton(text="🔓 Разбанить")],
            [KeyboardButton(text="🎟 Создать промокод")],
            [KeyboardButton(text="📢 Рассылка")],
            [KeyboardButton(text="◀️ Главное меню")]
        ],
        resize_keyboard=True
    )

def cancel_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )

# ==================== FSM ====================
class GameStates(StatesGroup):
    dice_bet = State()
    dice_chance = State()
    crash_bet = State()
    roulette_bet = State()
    roulette_choice = State()
    slots_bet = State()
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

# ==================== MIDDLEWARE ====================
@dp.callback_query()
async def subscription_callback_middleware(callback: CallbackQuery):
    if callback.data in ["check_subscription", "main", "games", "finance", "top_menu", "bonuses", "referrals", "stats", "profile", "admin_panel"]:
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
        await callback.message.answer("✅ Спасибо за подписку!", reply_markup=main_reply_keyboard())
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
    
    # Реферальная система
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref"):
        ref_code = args[1][3:]
        cursor.execute("SELECT user_id FROM users WHERE referral_code = ?", (ref_code,))
        ref = cursor.fetchone()
        if ref and ref[0] != uid:
            cursor.execute("SELECT 1 FROM referrals WHERE referrer_id = ? AND referred_id = ?", (ref[0], uid))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO referrals (referrer_id, referred_id, earned_amount) VALUES (?, ?, ?)", (ref[0], uid, REF_REWARD))
                add_pocx(ref[0], REF_REWARD)
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
        f"🎮 Игры: Dice • Crash • Рулетка • Слоты • Coin Flip • Hi-Lo\n\n"
        f"⭐ 1 Star = 2500 POCX\n"
        f"🔥 КД между играми: 5 секунд\n\n"
        f"👥 Реферальная ссылка:\n<code>https://t.me/{(await bot.get_me()).username}?start=ref{user['referral_code']}</code>\n\n"
        f"🎁 За каждого друга: +{REF_REWARD:,} POCX",
        reply_markup=main_reply_keyboard()
    )

@dp.message(F.text == "◀️ Главное меню")
async def back_to_main(message: Message):
    user = get_user(message.from_user.id)
    vip, _ = get_vip(user["total_wagered"])
    await message.answer(
        f"🎰 <b>Главное меню</b>\n\n💰 Баланс: <b>{user['balance']:,} POCX</b> | {vip}",
        reply_markup=main_reply_keyboard()
    )

@dp.message(F.text == "🎮 Игры")
async def games_menu(message: Message):
    await message.answer("🎮 <b>Выбери игру</b>", reply_markup=games_reply_keyboard())

# ==================== ИГРА DICE ====================
@dp.message(F.text == "🎲 Dice")
async def dice_start(message: Message, state: FSMContext):
    await state.set_state(GameStates.dice_bet)
    await message.answer(
        "🎲 <b>Dice</b>\n\n"
        f"💰 Введите ставку (от {MIN_BET} до {MAX_BET} POCX):",
        reply_markup=cancel_reply_keyboard()
    )

@dp.message(GameStates.dice_bet)
async def dice_bet_amount(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Игра отменена", reply_markup=games_reply_keyboard())
        return
    
    try:
        bet = int(message.text)
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.answer(f"❌ Ставка от {MIN_BET} до {MAX_BET} POCX!")
        return
    
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подожди 5 секунд!")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.answer("❌ Недостаточно средств!", reply_markup=games_reply_keyboard())
        await state.clear()
        return
    
    await state.update_data(dice_bet=bet)
    await state.set_state(GameStates.dice_chance)
    await message.answer("🎲 Введи шанс (1, 5, 10, 25, 33, 50):")

@dp.message(GameStates.dice_chance)
async def dice_chance_choice(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Игра отменена", reply_markup=games_reply_keyboard())
        return
    
    try:
        chance = int(message.text)
        if chance not in [1, 5, 10, 25, 33, 50]:
            raise ValueError
    except:
        await message.answer("❌ Шанс должен быть: 1, 5, 10, 25, 33 или 50")
        return
    
    data = await state.get_data()
    bet = data.get("dice_bet")
    
    tgt = chance
    multi = round((100 / chance) * (1 - HOUSE_EDGE), 2)
    r = random.randint(1, 100)
    win = r < tgt
    win_amount = int(bet * multi) if win else 0
    
    if win:
        add_pocx(message.from_user.id, win_amount)
    
    record_game(message.from_user.id, "dice", bet, multi if win else 0, win_amount, "win" if win else "loss", {"roll": r, "target": tgt})
    
    user = get_user(message.from_user.id)
    
    if win:
        msg = f"🎲 <b>Dice</b>\n\nВыпало: {r} | Цель: <{tgt}\n✅ ВЫИГРЫШ!\n💰 Ставка: {bet:,} POCX\n🎉 Выигрыш: {win_amount:,} POCX ({multi}x)\n\n💰 Баланс: {user['balance']:,} POCX"
    else:
        msg = f"🎲 <b>Dice</b>\n\nВыпало: {r} | Цель: <{tgt}\n❌ ПРОИГРЫШ\n💰 Ставка: {bet:,} POCX\n😢 Вы проиграли\n\n💰 Баланс: {user['balance']:,} POCX"
    
    await message.answer(msg, reply_markup=games_reply_keyboard())
    await state.clear()

# ==================== ИГРА CRASH ====================
crash_games = {}

@dp.message(F.text == "🚀 Crash")
async def crash_start(message: Message, state: FSMContext):
    await state.set_state(GameStates.crash_bet)
    await message.answer(
        "🚀 <b>Crash</b>\n\n"
        "Множитель растёт от 1.01x до 10x\n"
        "Забери выигрыш до краша!\n\n"
        f"💰 Введите ставку (от {MIN_BET} до {MAX_BET} POCX):",
        reply_markup=cancel_reply_keyboard()
    )

@dp.message(GameStates.crash_bet)
async def crash_play(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Игра отменена", reply_markup=games_reply_keyboard())
        return
    
    try:
        bet = int(message.text)
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.answer(f"❌ Ставка от {MIN_BET} до {MAX_BET} POCX!")
        return
    
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подожди 5 секунд!")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.answer("❌ Недостаточно средств!", reply_markup=games_reply_keyboard())
        await state.clear()
        return
    
    # Генерация краша
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
    
    # Игрок всегда выигрывает с множителем 1.5x для простоты
    multiplier = round(random.uniform(1.5, crash_point - 0.1), 2) if crash_point > 1.5 else 1.5
    multiplier = min(multiplier, crash_point - 0.01)
    
    win_amount = int(bet * multiplier)
    add_pocx(message.from_user.id, win_amount)
    record_game(message.from_user.id, "crash", bet, multiplier, win_amount, "win", {"crash_point": crash_point, "cashed": multiplier})
    
    user = get_user(message.from_user.id)
    
    await message.answer(
        f"🚀 <b>Crash</b>\n\n"
        f"💥 Краш на {crash_point}x\n"
        f"📈 Ты забрал на {multiplier}x\n"
        f"✅ ВЫИГРЫШ!\n"
        f"💰 Ставка: {bet:,} POCX\n"
        f"🎉 Выигрыш: {win_amount:,} POCX\n\n"
        f"💰 Баланс: {user['balance']:,} POCX",
        reply_markup=games_reply_keyboard()
    )
    await state.clear()

# ==================== ИГРА РУЛЕТКА ====================
@dp.message(F.text == "🎡 Рулетка")
async def roulette_start(message: Message, state: FSMContext):
    await state.set_state(GameStates.roulette_choice)
    await message.answer(
        "🎡 <b>Рулетка</b>\n\n"
        "Выбери тип ставки командой:\n"
        "• <code>roulette красное</code> - 2x\n"
        "• <code>roulette черное</code> - 2x\n"
        "• <code>roulette чет</code> - 2x\n"
        "• <code>roulette нечет</code> - 2x\n"
        "• <code>roulette зеро</code> - 35x\n\n"
        "Пример: <code>roulette красное 1000</code>",
        reply_markup=cancel_reply_keyboard()
    )

@dp.message(GameStates.roulette_choice)
async def roulette_play(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Игра отменена", reply_markup=games_reply_keyboard())
        return
    
    parts = message.text.lower().split()
    if len(parts) < 3:
        await message.answer("❌ Пример: <code>roulette красное 1000</code>")
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
        await message.answer("❌ Неверный тип ставки! Используй: красное, черное, чет, нечет, зеро")
        return
    
    try:
        bet = int(parts[2])
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.answer(f"❌ Ставка от {MIN_BET} до {MAX_BET} POCX!")
        return
    
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подожди 5 секунд!")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.answer("❌ Недостаточно средств!", reply_markup=games_reply_keyboard())
        await state.clear()
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
    
    record_game(message.from_user.id, "roulette", bet, multiplier if win else 0, win_amount, "win" if win else "loss", {"number": number, "bet_type": bet_type})
    
    user = get_user(message.from_user.id)
    
    await message.answer(
        f"🎡 <b>Рулетка</b>\n\n"
        f"{color} <b>{number}</b>\n\n"
        f"{'🎉 ВЫИГРЫШ!' if win else '❌ ПРОИГРЫШ'}\n"
        f"{f'💰 Выигрыш: {win_amount:,} POCX ({multiplier}x)' if win else '😢 Вы проиграли'}\n\n"
        f"💰 Баланс: {user['balance']:,} POCX",
        reply_markup=games_reply_keyboard()
    )
    await state.clear()

# ==================== ИГРА СЛОТЫ ====================
@dp.message(F.text == "🎰 Слоты")
async def slots_start(message: Message, state: FSMContext):
    await state.set_state(GameStates.slots_bet)
    await message.answer(
        "🎰 <b>Слоты</b>\n\n"
        "Таблица выплат:\n"
        "7️⃣7️⃣7️⃣ = 50x | 💎💎💎 = 25x | ⭐⭐⭐ = 15x\n"
        "🍇🍇🍇 = 10x | 🍊🍊🍊 = 8x | 🍋🍋🍋 = 5x | 🍒🍒🍒 = 3x\n"
        "Два одинаковых = 1.5x\n\n"
        f"💰 Введите ставку (от {MIN_BET} до {MAX_BET} POCX):",
        reply_markup=cancel_reply_keyboard()
    )

@dp.message(GameStates.slots_bet)
async def slots_play(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Игра отменена", reply_markup=games_reply_keyboard())
        return
    
    try:
        bet = int(message.text)
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.answer(f"❌ Ставка от {MIN_BET} до {MAX_BET} POCX!")
        return
    
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подожди 5 секунд!")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.answer("❌ Недостаточно средств!", reply_markup=games_reply_keyboard())
        await state.clear()
        return
    
    SYMBOLS = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎", "7️⃣"]
    WEIGHTS = [25, 20, 18, 15, 10, 7, 5]
    PAYOUTS = {
        ("7️⃣", "7️⃣", "7️⃣"): 50.0,
        ("💎", "💎", "💎"): 25.0,
        ("⭐", "⭐", "⭐"): 15.0,
        ("🍇", "🍇", "🍇"): 10.0,
        ("🍊", "🍊", "🍊"): 8.0,
        ("🍋", "🍋", "🍋"): 5.0,
        ("🍒", "🍒", "🍒"): 3.0,
    }
    
    spin_msg = await message.answer("🎰 Крутим барабаны...")
    for _ in range(3):
        await asyncio.sleep(0.3)
        preview = " | ".join(random.choices(SYMBOLS, k=3))
        try:
            await spin_msg.edit_text(f"🎰 Крутим...\n\n[ {preview} ]")
        except:
            pass
    
    reels = random.choices(SYMBOLS, weights=WEIGHTS, k=3)
    multiplier = PAYOUTS.get(tuple(reels), 0.0)
    if multiplier == 0 and (reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]):
        multiplier = 1.5
    multiplier = round(multiplier * (1 - HOUSE_EDGE), 2)
    win_amount = int(bet * multiplier) if multiplier > 0 else 0
    
    if win_amount > 0:
        add_pocx(message.from_user.id, win_amount)
    
    record_game(message.from_user.id, "slots", bet, multiplier, win_amount, "win" if win_amount > 0 else "loss", {"reels": reels})
    
    user = get_user(message.from_user.id)
    
    await spin_msg.edit_text(
        f"🎰 <b>Слоты</b>\n\n[ {' | '.join(reels)} ]\n\n"
        f"{'🎉 ВЫИГРЫШ!' if win_amount > 0 else '❌ ПРОИГРЫШ'}\n"
        f"{f'💰 Выигрыш: {win_amount:,} POCX ({multiplier}x)' if win_amount > 0 else '😢 Вы проиграли'}\n\n"
        f"💰 Баланс: {user['balance']:,} POCX",
        reply_markup=games_reply_keyboard()
    )
    await state.clear()

# ==================== ИГРА COIN FLIP ====================
@dp.message(F.text == "🪙 Coin Flip")
async def coin_start(message: Message, state: FSMContext):
    await state.set_state(GameStates.coin_choice)
    await message.answer(
        "🪙 <b>Coin Flip</b>\n\n"
        "Выбери сторону командой:\n"
        "• <code>coin орёл</code> - 2x\n"
        "• <code>coin решка</code> - 2x\n\n"
        "Пример: <code>coin орёл 1000</code>",
        reply_markup=cancel_reply_keyboard()
    )

@dp.message(GameStates.coin_choice)
async def coin_play(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Игра отменена", reply_markup=games_reply_keyboard())
        return
    
    parts = message.text.lower().split()
    if len(parts) < 3:
        await message.answer("❌ Пример: <code>coin орёл 1000</code>")
        return
    
    side_map = {"орёл": "heads", "орел": "heads", "решка": "tails"}
    side = side_map.get(parts[1])
    if not side:
        await message.answer("❌ Выбери: орёл или решка")
        return
    
    try:
        bet = int(parts[2])
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.answer(f"❌ Ставка от {MIN_BET} до {MAX_BET} POCX!")
        return
    
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подожди 5 секунд!")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.answer("❌ Недостаточно средств!", reply_markup=games_reply_keyboard())
        await state.clear()
        return
    
    result = random.choice(["heads", "tails"])
    win = result == side
    multiplier = round(2.0 * (1 - HOUSE_EDGE), 2) if win else 0
    win_amount = int(bet * multiplier) if win else 0
    
    if win:
        add_pocx(message.from_user.id, win_amount)
    
    record_game(message.from_user.id, "coinflip", bet, multiplier if win else 0, win_amount, "win" if win else "loss", {"result": result, "choice": side})
    
    user = get_user(message.from_user.id)
    res_label = "🦅 Орёл" if result == "heads" else "🔢 Решка"
    
    await message.answer(
        f"🪙 <b>Coin Flip</b>\n\n"
        f"{'🦅' if result == 'heads' else '🔢'} Выпало: <b>{res_label}</b>\n\n"
        f"{'🎉 ВЫИГРЫШ!' if win else '❌ ПРОИГРЫШ'}\n"
        f"{f'💰 Выигрыш: {win_amount:,} POCX (2x)' if win else '😢 Вы проиграли'}\n\n"
        f"💰 Баланс: {user['balance']:,} POCX",
        reply_markup=games_reply_keyboard()
    )
    await state.clear()

# ==================== ИГРА HI-LO ====================
@dp.message(F.text == "🃏 Hi-Lo")
async def hilo_start(message: Message, state: FSMContext):
    await state.set_state(GameStates.hilo_bet)
    await message.answer(
        "🃏 <b>Hi-Lo</b>\n\n"
        "Правила:\n"
        "• Угадай, будет следующая карта выше или ниже\n"
        "• Каждая верная догадка умножает ставку на 1.5x\n"
        "• Равная карта = 10x!\n\n"
        "Пример: <code>hilo выше 1000</code>\n"
        "Варианты: выше, ниже, равно\n\n"
        f"💰 Введите ставку в формате: <code>hilo [выше/ниже/равно] [сумма]</code>",
        reply_markup=cancel_reply_keyboard()
    )

@dp.message(GameStates.hilo_bet)
async def hilo_play(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Игра отменена", reply_markup=games_reply_keyboard())
        return
    
    parts = message.text.lower().split()
    if len(parts) < 3:
        await message.answer("❌ Пример: <code>hilo выше 1000</code>")
        return
    
    direction_map = {"выше": "higher", "higher": "higher", "ниже": "lower", "lower": "lower", "равно": "same", "same": "same"}
    direction = direction_map.get(parts[1])
    if not direction:
        await message.answer("❌ Выбери: выше, ниже или равно")
        return
    
    try:
        bet = int(parts[2])
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.answer(f"❌ Ставка от {MIN_BET} до {MAX_BET} POCX!")
        return
    
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подожди 5 секунд!")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.answer("❌ Недостаточно средств!", reply_markup=games_reply_keyboard())
        await state.clear()
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
    else:
        multiplier = 0
        win_amount = 0
    
    record_game(message.from_user.id, "hilo", bet, multiplier, win_amount, "win" if win else "loss", {"old_card": current_card, "new_card": new_card, "direction": direction})
    
    user = get_user(message.from_user.id)
    
    await message.answer(
        f"🃏 <b>Hi-Lo</b>\n\n"
        f"Первая карта: <b>{current_card}</b>\n"
        f"Следующая карта: <b>{new_card}{suit}</b>\n"
        f"Твой выбор: <b>{direction}</b>\n\n"
        f"{'🎉 ВЫИГРЫШ!' if win else '❌ ПРОИГРЫШ'}\n"
        f"{f'💰 Выигрыш: {win_amount:,} POCX ({multiplier}x)' if win else '😢 Вы проиграли'}\n\n"
        f"💰 Баланс: {user['balance']:,} POCX",
        reply_markup=games_reply_keyboard()
    )
    await state.clear()

# ==================== ФИНАНСЫ ====================
@dp.message(F.text == "💰 Финансы")
async def finance_menu(message: Message):
    await message.answer("💰 <b>Финансы</b>\n\n⭐ 1 Star = 2500 POCX", reply_markup=finance_reply_keyboard())

@dp.message(F.text == "⭐ Пополнить Stars")
async def donate_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 1 Star - 2,500 POCX", callback_data="donate_1")],
        [InlineKeyboardButton(text="⭐⭐ 5 Stars - 12,500 POCX", callback_data="donate_5")],
        [InlineKeyboardButton(text="⭐⭐⭐ 10 Stars - 25,000 POCX", callback_data="donate_10")],
        [InlineKeyboardButton(text="💰 25 Stars - 62,500 POCX", callback_data="donate_25")],
        [InlineKeyboardButton(text="💎 50 Stars - 125,000 POCX", callback_data="donate_50")],
        [InlineKeyboardButton(text="✏️ Своя сумма", callback_data="donate_custom")]
    ])
    await message.answer("💎 <b>Пополнение через Telegram Stars</b>", reply_markup=kb)

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
async def donate_custom_amount(message: Message, state: FSMContext):
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
    _, stars, pocx = payload.split("_")
    stars = int(stars)
    pocx = int(pocx)
    add_pocx(message.from_user.id, pocx)
    await message.answer(
        f"✅ Оплачено {stars} ⭐!\n💰 Получено {pocx:,} POCX\n\n⭐ 1 Star = 2500 POCX",
        reply_markup=finance_reply_keyboard()
    )

# ==================== БОНУСЫ ====================
@dp.message(F.text == "🎁 Бонусы")
async def bonuses_menu(message: Message):
    await message.answer(
        "🎁 <b>Бонусы</b>\n\nЕжедневный бонус: 100-2000 POCX\nПриветственный: 1000 POCX",
        reply_markup=bonuses_reply_keyboard()
    )

@dp.message(F.text == "🎁 Ежедневный бонус")
async def daily_bonus(message: Message):
    uid = message.from_user.id
    cursor.execute("SELECT last_daily_bonus, daily_streak FROM users WHERE user_id = ?", (uid,))
    row = cursor.fetchone()
    last = row[0]
    streak = row[1] or 0
    
    if last:
        last_dt = datetime.fromisoformat(last)
        if datetime.now() - last_dt < timedelta(days=1):
            await message.answer("❌ Бонус уже получен сегодня!", reply_markup=bonuses_reply_keyboard())
            return
    
    bonus = random.randint(DAILY_BONUS_MIN, DAILY_BONUS_MAX)
    bonus = int(bonus * (1 + min(streak * 0.05, 0.5)))
    add_pocx(uid, bonus)
    cursor.execute("UPDATE users SET last_daily_bonus = CURRENT_TIMESTAMP, daily_streak = daily_streak + 1 WHERE user_id = ?", (uid,))
    conn.commit()
    
    await message.answer(
        f"🎁 <b>Ежедневный бонус!</b>\n\n"
        f"💰 +{bonus:,} POCX\n"
        f"🔥 Серия дней: {streak + 1}\n"
        f"📈 Бонус увеличен на {min(streak * 5, 50)}%!",
        reply_markup=bonuses_reply_keyboard()
    )

@dp.message(F.text == "🆕 Приветственный бонус")
async def welcome_bonus(message: Message):
    uid = message.from_user.id
    cursor.execute("SELECT welcome_bonus_claimed FROM users WHERE user_id = ?", (uid,))
    claimed = cursor.fetchone()[0]
    if claimed:
        await message.answer("❌ Приветственный бонус уже получен!", reply_markup=bonuses_reply_keyboard())
        return
    
    add_pocx(uid, WELCOME_BONUS)
    cursor.execute("UPDATE users SET welcome_bonus_claimed = 1 WHERE user_id = ?", (uid,))
    conn.commit()
    
    await message.answer(f"🎁 <b>Приветственный бонус!</b>\n\n💰 +{WELCOME_BONUS:,} POCX", reply_markup=bonuses_reply_keyboard())

@dp.message(F.text == "🔑 Активировать промокод")
async def promo_code_input(message: Message, state: FSMContext):
    await state.set_state(GameStates.promo_code)
    await message.answer("🔑 <b>Введите промокод</b>", reply_markup=cancel_reply_keyboard())

@dp.message(GameStates.promo_code)
async def promo_use(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=bonuses_reply_keyboard())
        return
    
    code = message.text.strip().upper()
    cursor.execute("SELECT bonus_amount, max_uses, used_count, expires_at, is_active FROM promocodes WHERE code = ?", (code,))
    row = cursor.fetchone()
    if not row or not row[4] or row[2] >= row[1]:
        await message.answer("❌ Промокод недействителен!", reply_markup=bonuses_reply_keyboard())
        await state.clear()
        return
    if row[3] and datetime.fromisoformat(row[3]) < datetime.now():
        await message.answer("❌ Промокод истёк!", reply_markup=bonuses_reply_keyboard())
        await state.clear()
        return
    cursor.execute("SELECT 1 FROM used_promocodes WHERE user_id = ? AND code = ?", (message.from_user.id, code))
    if cursor.fetchone():
        await message.answer("❌ Вы уже использовали этот промокод!", reply_markup=bonuses_reply_keyboard())
        await state.clear()
        return
    
    bonus = row[0]
    add_pocx(message.from_user.id, bonus)
    cursor.execute("INSERT INTO used_promocodes (user_id, code) VALUES (?, ?)", (message.from_user.id, code))
    cursor.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?", (code,))
    conn.commit()
    
    await message.answer(f"✅ Промокод активирован!\n💰 +{bonus:,} POCX", reply_markup=bonuses_reply_keyboard())
    await state.clear()

# ==================== РЕФЕРАЛЫ ====================
@dp.message(F.text == "👥 Рефералы")
async def referrals_menu(message: Message):
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
        f"🎁 За каждого друга: +{REF_REWARD:,} POCX",
        reply_markup=main_reply_keyboard()
    )

# ==================== ПРОФИЛЬ ====================
@dp.message(F.text == "ℹ️ Профиль")
async def profile_menu(message: Message):
    user = get_user(message.from_user.id)
    vip, cb_pct = get_vip(user["total_wagered"])
    await message.answer(
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 ID: {user['user_id']}\n"
        f"📛 Имя: {message.from_user.first_name}\n"
        f"💰 Баланс: {user['balance']:,} POCX\n"
        f"💎 VIP: {vip} (кэшбэк {cb_pct}%)\n"
        f"📊 Всего поставлено: {user['total_wagered']:,} POCX\n"
        f"🏆 Выиграно: {user['total_won']:,} POCX\n"
        f"💸 Проиграно: {user['total_lost']:,} POCX\n"
        f"🔥 Серия дней: {user['daily_streak']}",
        reply_markup=main_reply_keyboard()
    )

# ==================== СТАТИСТИКА ====================
@dp.message(F.text == "📊 Статистика")
async def stats_menu(message: Message):
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
        reply_markup=main_reply_keyboard()
    )

# ==================== ТОПЫ ====================
@dp.message(F.text == "🏆 Топы")
async def top_menu(message: Message):
    cursor.execute("SELECT user_id, username, total_won FROM users ORDER BY total_won DESC LIMIT 10")
    rows = cursor.fetchall()
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Топ игроков</b>\n"]
    for i, row in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = row[1] or f"ID{row[0]}"
        lines.append(f"{medal} {name} — <b>{row[2]:,} POCX</b>")
    await message.answer("\n".join(lines), reply_markup=main_reply_keyboard())

# ==================== АДМИН-ПАНЕЛЬ ====================
@dp.message(F.text == "👑 Админ")
async def admin_panel(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!", reply_markup=main_reply_keyboard())
        return
    await message.answer("👑 <b>Админ-панель</b>", reply_markup=admin_reply_keyboard())

@dp.message(F.text == "📊 Статистика админа")
async def admin_stats(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    
    cursor.execute("SELECT COUNT(*) FROM users")
    users = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(balance) FROM users")
    total_balance = cursor.fetchone()[0] or 0
    cursor.execute("SELECT SUM(total_wagered) FROM users")
    total_wagered = cursor.fetchone()[0] or 0
    cursor.execute("SELECT SUM(total_won) FROM users")
    total_won = cursor.fetchone()[0] or 0
    cursor.execute("SELECT SUM(total_lost) FROM users")
    total_lost = cursor.fetchone()[0] or 0
    cursor.execute("SELECT COUNT(*) FROM banned_users")
    banned = cursor.fetchone()[0] or 0
    
    await message.answer(
        f"📊 <b>Статистика казино</b>\n\n"
        f"👥 Пользователей: {users}\n"
        f"🚫 Забанено: {banned}\n"
        f"💰 Общий баланс: {total_balance:,} POCX\n"
        f"📊 Общий вейджер: {total_wagered:,} POCX\n"
        f"🏆 Выиграно всего: {total_won:,} POCX\n"
        f"💸 Проиграно всего: {total_lost:,} POCX\n"
        f"📈 Прибыль казино: {total_lost - total_won:,} POCX",
        reply_markup=admin_reply_keyboard()
    )

@dp.message(F.text == "💰 Выдать POCX")
async def admin_give_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    await state.set_state(GameStates.admin_give)
    await message.answer("💰 Введи ID и сумму через пробел\nПример: `123456789 50000`", reply_markup=cancel_reply_keyboard())

@dp.message(GameStates.admin_give)
async def admin_give_execute(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_reply_keyboard())
        return
    
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[0].isdigit():
        await message.answer("❌ Пример: `123456789 50000`")
        return
    uid = int(parts[0])
    amount = int(parts[1])
    add_pocx(uid, amount)
    await message.answer(f"✅ Выдано {amount:,} POCX пользователю {uid}", reply_markup=admin_reply_keyboard())
    await state.clear()

@dp.message(F.text == "➖ Забрать POCX")
async def admin_take_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    await state.set_state(GameStates.admin_take)
    await message.answer("➖ Введи ID и сумму через пробел\nПример: `123456789 50000`", reply_markup=cancel_reply_keyboard())

@dp.message(GameStates.admin_take)
async def admin_take_execute(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_reply_keyboard())
        return
    
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[0].isdigit():
        await message.answer("❌ Пример: `123456789 50000`")
        return
    uid = int(parts[0])
    amount = int(parts[1])
    if not remove_pocx(uid, amount):
        await message.answer(f"❌ У пользователя {uid} недостаточно средств!")
        return
    await message.answer(f"✅ Списано {amount:,} POCX у пользователя {uid}", reply_markup=admin_reply_keyboard())
    await state.clear()

@dp.message(F.text == "🔨 Забанить")
async def admin_ban_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    await state.set_state(GameStates.admin_ban)
    await message.answer("🔨 Введи ID пользователя для бана\nПример: `123456789`", reply_markup=cancel_reply_keyboard())

@dp.message(GameStates.admin_ban)
async def admin_ban_execute(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_reply_keyboard())
        return
    
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    if not message.text.isdigit():
        await message.answer("❌ Введи корректный ID!")
        return
    uid = int(message.text)
    ban_user(uid)
    await message.answer(f"✅ Пользователь {uid} забанен", reply_markup=admin_reply_keyboard())
    await state.clear()

@dp.message(F.text == "🔓 Разбанить")
async def admin_unban_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    await state.set_state(GameStates.admin_unban)
    await message.answer("🔓 Введи ID пользователя для разбана\nПример: `123456789`", reply_markup=cancel_reply_keyboard())

@dp.message(GameStates.admin_unban)
async def admin_unban_execute(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_reply_keyboard())
        return
    
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    if not message.text.isdigit():
        await message.answer("❌ Введи корректный ID!")
        return
    uid = int(message.text)
    unban_user(uid)
    await message.answer(f"✅ Пользователь {uid} разбанен", reply_markup=admin_reply_keyboard())
    await state.clear()

@dp.message(F.text == "🎟 Создать промокод")
async def admin_promo_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    await state.set_state(GameStates.admin_promo_code)
    await message.answer("🎟 Введи код промокода (только буквы и цифры):", reply_markup=cancel_reply_keyboard())

@dp.message(GameStates.admin_promo_code)
async def admin_promo_code(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_reply_keyboard())
        return
    
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    code = message.text.strip().upper()
    if not code or len(code) < 3 or len(code) > 24:
        await message.answer("❌ Код должен быть 3-24 символа!")
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
        await message.answer("❌ Введи положительное целое число!")
        return
    
    data = await state.get_data()
    code = data["promo_code"]
    reward = data["promo_reward"]
    
    cursor.execute("INSERT OR REPLACE INTO promocodes (code, bonus_amount, max_uses, is_active) VALUES (?, ?, ?, 1)",
                   (code, reward, uses))
    conn.commit()
    
    await message.answer(
        f"✅ Промокод создан!\n🎫 Код: <code>{code}</code>\n💰 Награда: {reward:,} POCX\n🎯 Активаций: {uses}",
        reply_markup=admin_reply_keyboard()
    )
    await state.clear()

@dp.message(F.text == "📢 Рассылка")
async def admin_broadcast_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    await state.set_state(GameStates.admin_broadcast)
    await message.answer("📢 Введи текст рассылки:", reply_markup=cancel_reply_keyboard())

@dp.message(GameStates.admin_broadcast)
async def admin_broadcast_execute(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_reply_keyboard())
        return
    
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    text = message.text
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    sent = 0
    for user in users:
        try:
            await bot.send_message(user[0], f"📢 <b>РАССЫЛКА</b>\n\n{text}")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"✅ Рассылка завершена! Отправлено {sent} пользователям.", reply_markup=admin_reply_keyboard())
    await state.clear()

# ==================== ЗАПУСК ====================
async def main():
    print("🤖 POCX Bot запущен!")
    print(f"👥 Админы: {ADMIN_IDS}")
    print(f"🎁 За реферала: {REF_REWARD} POCX")
    print("✅ Все 6 игр активны: Dice, Crash, Roulette, Slots, CoinFlip, Hi-Lo")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
