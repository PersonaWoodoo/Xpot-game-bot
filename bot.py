import asyncio
import random
import sqlite3
import hashlib
import time
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message, LabeledPrice, PreCheckoutQuery
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
REF_REWARD = 500

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

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ==================== УДАЛЕНИЕ СТАРОЙ БАЗЫ ====================
if os.path.exists("pocx_bot.db"):
    os.remove("pocx_bot.db")
    print("✅ Старая база данных удалена")

# ==================== БАЗА ДАННЫХ ====================
conn = sqlite3.connect("pocx_bot.db", check_same_thread=False)
cursor = conn.cursor()

# Таблица пользователей
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

# Таблица истории игр
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

# Таблица рефералов
cursor.execute("""
CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id INTEGER,
    referred_id INTEGER,
    earned_amount INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# Таблица забаненных
cursor.execute("""
CREATE TABLE IF NOT EXISTS banned_users (
    user_id INTEGER PRIMARY KEY,
    banned_at INTEGER,
    reason TEXT
)
""")

# Таблица промокодов
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

# Таблица использованных промокодов
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

def unban_user(user_id: int):
    cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))

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
    kb.append([InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_subscription")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message()
async def subscription_middleware(message: Message):
    if is_banned(message.from_user.id):
        await message.answer("❌ Вы забанены!")
        return
    ok, not_subscribed = await check_subscription(message.from_user.id)
    if not ok and message.text != "/start":
        await message.answer(
            "❓ Для использования бота необходимо подписаться на каналы:",
            reply_markup=subscription_keyboard(not_subscribed)
        )
        return

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
        await callback.message.edit_text("✅ Спасибо за подписку!", reply_markup=main_menu())
    else:
        await callback.message.edit_text(
            "❓ Для использования бота необходимо подписаться на каналы:",
            reply_markup=subscription_keyboard(not_subscribed)
        )
    await callback.answer()

# ==================== КЛАВИАТУРЫ ====================
def main_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Игры", callback_data="games")],
        [InlineKeyboardButton(text="💰 Финансы", callback_data="finance")],
        [InlineKeyboardButton(text="🏆 Топы", callback_data="top_menu")],
        [InlineKeyboardButton(text="🎁 Бонусы", callback_data="bonuses")],
        [InlineKeyboardButton(text="👥 Рефералы", callback_data="referrals")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="ℹ️ Профиль", callback_data="profile")]
    ])
    if 8478884644 in ADMIN_IDS or 8293927811 in ADMIN_IDS:
        kb.inline_keyboard.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")])
    return kb

def games_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Dice", callback_data="game_dice")],
        [InlineKeyboardButton(text="🚀 Crash", callback_data="game_crash")],
        [InlineKeyboardButton(text="🎡 Рулетка", callback_data="game_roulette")],
        [InlineKeyboardButton(text="🎰 Слоты", callback_data="game_slots")],
        [InlineKeyboardButton(text="🪙 Coin Flip", callback_data="game_coin")],
        [InlineKeyboardButton(text="🃏 Hi-Lo", callback_data="game_hilo")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main")]
    ])

def dice_menu():
    kb = InlineKeyboardMarkup(inline_row_width=2)
    for name, tgt, chance in [("50% (2x)", 50, 49.5), ("33% (3x)", 33, 33), ("25% (4x)", 25, 25), ("10% (10x)", 10, 10), ("5% (20x)", 5, 5), ("1% (99x)", 1, 1)]:
        kb.insert(InlineKeyboardButton(text=name, callback_data=f"dice_{tgt}_{chance}"))
    kb.add(InlineKeyboardButton(text="🔙 Назад", callback_data="games"))
    return kb

def roulette_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Красное (2x)", callback_data="rl_red")],
        [InlineKeyboardButton(text="⚫ Чёрное (2x)", callback_data="rl_black")],
        [InlineKeyboardButton(text="🟢 Зеро (35x)", callback_data="rl_green")],
        [InlineKeyboardButton(text="🔵 Чётное (2x)", callback_data="rl_even")],
        [InlineKeyboardButton(text="🟡 Нечётное (2x)", callback_data="rl_odd")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="games")]
    ])

def coin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🦅 Орёл", callback_data="coin_heads")],
        [InlineKeyboardButton(text="🔢 Решка", callback_data="coin_tails")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="games")]
    ])

def crash_control():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 ЗАБРАТЬ", callback_data="crash_out")],
        [InlineKeyboardButton(text="🔙 Выход", callback_data="games")]
    ])

def hilo_controls(can_cashout: bool = False):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬆️ Выше", callback_data="hilo_higher")],
        [InlineKeyboardButton(text="⬇️ Ниже", callback_data="hilo_lower")],
        [InlineKeyboardButton(text="➡️ Равно (10x)", callback_data="hilo_same")]
    ])
    if can_cashout:
        kb.inline_keyboard.append([InlineKeyboardButton(text="💰 Забрать", callback_data="hilo_cashout")])
    return kb

def top_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 За всё время", callback_data="top_all")],
        [InlineKeyboardButton(text="📅 За неделю", callback_data="top_week")],
        [InlineKeyboardButton(text="📆 За день", callback_data="top_day")],
        [InlineKeyboardButton(text="👥 Топ рефералов", callback_data="top_refs")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main")]
    ])

def bonuses_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="daily")],
        [InlineKeyboardButton(text="🆕 Приветственный бонус", callback_data="welcome")],
        [InlineKeyboardButton(text="🔑 Промокод", callback_data="promo")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main")]
    ])

def finance_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Пополнить (Stars)", callback_data="donate")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main")]
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="➕ Выдать POCX", callback_data="admin_give")],
        [InlineKeyboardButton(text="➖ Забрать POCX", callback_data="admin_take")],
        [InlineKeyboardButton(text="🔨 Забанить", callback_data="admin_ban")],
        [InlineKeyboardButton(text="🔓 Разбанить", callback_data="admin_unban")],
        [InlineKeyboardButton(text="🎟 Создать промокод", callback_data="admin_promo")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main")]
    ])

# ==================== FSM ====================
class GameStates(StatesGroup):
    dice_bet = State()
    crash_bet = State()
    roulette_bet = State()
    roulette_choice = State()
    slots_bet = State()
    coin_choice = State()
    coin_bet = State()
    hilo_bet = State()
    hilo_active = State()
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
            cursor.execute("INSERT OR IGNORE INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (ref[0], uid))
            add_pocx(ref[0], 500)
            conn.commit()
    
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
        f"🔥 КД между играми: 5 секунд",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "main")
async def cb_main(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    vip, _ = get_vip(user["total_wagered"])
    await callback.message.edit_text(
        f"🎰 <b>Главное меню</b>\n\n💰 Баланс: <b>{user['balance']:,} POCX</b> | {vip}",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@dp.callback_query(F.data == "games")
async def cb_games(callback: CallbackQuery):
    await callback.message.edit_text("🎮 <b>Выбери игру</b>", reply_markup=games_menu(), parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    vip, cb_pct = get_vip(user["total_wagered"])
    await callback.message.edit_text(
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 ID: {user['user_id']}\n"
        f"📛 Имя: {callback.from_user.first_name}\n"
        f"💰 Баланс: {user['balance']:,} POCX\n"
        f"💎 VIP: {vip} (кэшбэк {cb_pct}%)\n"
        f"📊 Всего поставлено: {user['total_wagered']:,} POCX\n"
        f"🏆 Выиграно: {user['total_won']:,} POCX\n"
        f"💸 Проиграно: {user['total_lost']:,} POCX\n"
        f"🔥 Серия дней: {user['daily_streak']}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="main")]]),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    cursor.execute("SELECT COUNT(*) FROM game_history WHERE user_id = ?", (callback.from_user.id,))
    played = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM game_history WHERE user_id = ? AND result = 'win'", (callback.from_user.id,))
    wins = cursor.fetchone()[0]
    cursor.execute("SELECT MAX(multiplier) FROM game_history WHERE user_id = ? AND result = 'win'", (callback.from_user.id,))
    best = cursor.fetchone()[0] or 0
    winrate = wins / max(played, 1) * 100
    roi = (user["total_won"] - user["total_lost"]) / max(user["total_wagered"], 1) * 100
    
    await callback.message.edit_text(
        f"📊 <b>Статистика</b>\n\n"
        f"🎮 Игр сыграно: {played}\n"
        f"✅ Побед: {wins} ({winrate:.1f}%)\n"
        f"📈 Лучший множитель: {best:.2f}x\n"
        f"📊 ROI: {roi:.1f}%\n"
        f"💰 Общий вейджер: {user['total_wagered']:,} POCX\n"
        f"🏆 Выиграно всего: {user['total_won']:,} POCX",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="main")]]),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "referrals")
async def cb_referrals(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (callback.from_user.id,))
    count = cursor.fetchone()[0]
    cursor.execute("SELECT COALESCE(SUM(earned_amount), 0) FROM referrals WHERE referrer_id = ?", (callback.from_user.id,))
    earned = cursor.fetchone()[0]
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref{user['referral_code']}"
    
    await callback.message.edit_text(
        f"👥 <b>Рефералы</b>\n\n"
        f"🔗 Ваша ссылка:\n<code>{link}</code>\n\n"
        f"👤 Рефералов: {count}\n"
        f"💰 Заработано: {earned:,} POCX\n\n"
        f"🎁 За каждого друга: +500 POCX",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="main")]]),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "bonuses")
async def cb_bonuses(callback: CallbackQuery):
    await callback.message.edit_text(
        "🎁 <b>Бонусы</b>\n\nЕжедневный бонус: 100-2000 POCX\nПриветственный: 1000 POCX",
        reply_markup=bonuses_menu(),
        parse_mode=ParseMode.HTML
    )

# ==================== DICE ====================
@dp.callback_query(F.data == "game_dice")
async def cb_dice(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🎲 <b>Dice</b>\n\nВыбери шанс:", reply_markup=dice_menu(), parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.callback_query(F.data.startswith("dice_"))
async def dice_choice(callback: CallbackQuery, state: FSMContext):
    _, tgt, chance = callback.data.split("_")
    await state.update_data(dice_tgt=int(tgt), dice_chance=float(chance))
    await state.set_state(GameStates.dice_bet)
    multi = round((100 / float(chance)) * (1 - HOUSE_EDGE), 2)
    await callback.message.edit_text(
        f"🎲 <b>Dice</b>\n\nШанс: {chance}%\n💰 Ставка: x{multi}\n\n💵 Введите ставку (от {MIN_BET:,} до {MAX_BET:,} POCX):",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@dp.message(GameStates.dice_bet)
async def dice_bet(message: Message, state: FSMContext):
    try:
        bet = int(message.text.replace(",", ""))
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.answer(f"❌ От {MIN_BET:,} до {MAX_BET:,} POCX!")
        return
    
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подожди 5 секунд!")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.answer("❌ Недостаточно POCX!", reply_markup=main_menu())
        await state.clear()
        return
    
    data = await state.get_data()
    tgt = data["dice_tgt"]
    chance = data["dice_chance"]
    
    r = random.randint(1, 100)
    multi = round((100 / chance) * (1 - HOUSE_EDGE), 2)
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
    
    await message.answer(msg, reply_markup=main_menu(), parse_mode=ParseMode.HTML)
    await state.clear()

# ==================== CRASH ====================
crash_games = {}

@dp.callback_query(F.data == "game_crash")
async def cb_crash(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.crash_bet)
    await callback.message.edit_text("🚀 <b>Crash</b>\n\n💵 Введите ставку (от 100 до 500,000 POCX):", parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.message(GameStates.crash_bet)
async def crash_bet(message: Message, state: FSMContext):
    try:
        bet = int(message.text.replace(",", ""))
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.answer(f"❌ От {MIN_BET:,} до {MAX_BET:,} POCX!")
        return
    
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подожди 5 секунд!")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.answer("❌ Недостаточно POCX!", reply_markup=main_menu())
        await state.clear()
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
    
    crash_games[message.from_user.id] = {"bet": bet, "crash_point": crash_point, "start_time": time.time(), "is_active": True}
    
    msg = await message.answer(
        f"🚀 <b>ВЗЛЁТ!</b>\n\n⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜ 1.00x\n\n💵 Ставка: {bet:,} POCX\n💰 Потенциал: {bet:,} POCX",
        reply_markup=crash_control(),
        parse_mode=ParseMode.HTML
    )
    asyncio.create_task(crash_animation(message.from_user.id, msg, bet, crash_point, state))

async def crash_animation(uid: int, msg: Message, bet: int, cp: float, state: FSMContext):
    start = time.time()
    while uid in crash_games and crash_games[uid].get("is_active", False):
        elapsed = time.time() - start
        cur = min(cp, round(2.71828 ** (elapsed * 0.1), 2))
        
        if cur >= cp:
            crash_games[uid]["is_active"] = False
            record_game(uid, "crash", bet, cp, 0, "loss", {"crash_point": cp})
            try:
                await msg.edit_text(
                    f"💥 <b>КРАШ на {cp:.2f}x!</b>\n\n💵 Ставка: {bet:,} POCX\n❌ Проигрыш",
                    reply_markup=main_menu(),
                    parse_mode=ParseMode.HTML
                )
            except:
                pass
            break
        
        await asyncio.sleep(0.3)
        try:
            bar_length = int(16 * (cur / cp))
            bar = "🟩" * bar_length + "⬜" * (16 - bar_length)
            await msg.edit_text(
                f"🚀 <b>{cur:.2f}x</b>\n\n[{bar}]\n\n💵 {bet:,} → 💰 {int(bet * cur):,} POCX",
                reply_markup=crash_control(),
                parse_mode=ParseMode.HTML
            )
        except:
            pass
    
    crash_games.pop(uid, None)
    await state.clear()

@dp.callback_query(F.data == "crash_out")
async def crash_cashout(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in crash_games:
        await callback.answer("Нет активной игры!", show_alert=True)
        return
    
    game = crash_games[uid]
    if not game.get("is_active", False):
        await callback.answer("Уже крашнулось!", show_alert=True)
        return
    
    elapsed = time.time() - game["start_time"]
    cur = min(game["crash_point"], round(2.71828 ** (elapsed * 0.1), 2))
    win = int(game["bet"] * cur)
    add_pocx(uid, win)
    record_game(uid, "crash", game["bet"], cur, win, "win", {"cashed_at": cur})
    game["is_active"] = False
    
    await callback.message.edit_text(
        f"🎉 <b>ВЫИГРЫШ!</b>\n\n📈 Забрано на <b>{cur:.2f}x</b>\n💵 Ставка: {game['bet']:,} POCX\n💰 Выигрыш: <b>{win:,} POCX</b>",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )
    crash_games.pop(uid)
    await callback.answer()

# ==================== РУЛЕТКА ====================
@dp.callback_query(F.data == "game_roulette")
async def cb_roulette(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.roulette_choice)
    await callback.message.edit_text("🎡 <b>Рулетка</b>\n\nВыбери тип ставки:", reply_markup=roulette_menu(), parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.callback_query(GameStates.roulette_choice, F.data.startswith("rl_"))
async def roulette_choice(callback: CallbackQuery, state: FSMContext):
    bet_type = callback.data[3:]
    await state.update_data(rl_type=bet_type)
    await state.set_state(GameStates.roulette_bet)
    labels = {"red": "🔴 Красное", "black": "⚫ Чёрное", "green": "🟢 Зеро", "even": "🔵 Чётное", "odd": "🟡 Нечётное"}
    await callback.message.edit_text(
        f"🎡 <b>Рулетка - {labels[bet_type]}</b>\n\n💵 Введите ставку (от {MIN_BET:,} до {MAX_BET:,} POCX):",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@dp.message(GameStates.roulette_bet)
async def roulette_bet(message: Message, state: FSMContext):
    try:
        bet = int(message.text.replace(",", ""))
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.answer(f"❌ От {MIN_BET:,} до {MAX_BET:,} POCX!")
        return
    
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подожди 5 секунд!")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.answer("❌ Недостаточно POCX!", reply_markup=main_menu())
        await state.clear()
        return
    
    data = await state.get_data()
    bet_type = data["rl_type"]
    
    spin_msg = await message.answer("🎡 Крутим рулетку... 🔄")
    for frame in ["🔄", "🎲", "🎯", "🎡"]:
        await asyncio.sleep(0.3)
        try:
            await spin_msg.edit_text(f"🎡 Крутим рулетку... {frame}")
        except:
            pass
    
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
    elif bet_type == "green" and number == 0:
        win, multiplier = True, 35.0
    elif bet_type == "even" and number != 0 and number % 2 == 0:
        win, multiplier = True, 2.0
    elif bet_type == "odd" and number != 0 and number % 2 == 1:
        win, multiplier = True, 2.0
    
    win_amount = int(bet * multiplier * (1 - HOUSE_EDGE)) if win else 0
    labels = {"red": "🔴 Красное", "black": "⚫ Чёрное", "green": "🟢 Зеро", "even": "🔵 Чётное", "odd": "🟡 Нечётное"}
    
    if win:
        add_pocx(message.from_user.id, win_amount)
    
    record_game(message.from_user.id, "roulette", bet, multiplier if win else 0, win_amount, "win" if win else "loss", {"number": number, "bet_type": bet_type})
    
    user = get_user(message.from_user.id)
    
    win_text = f"💰 Выигрыш: {win_amount:,} POCX ({multiplier}x)" if win else "😢 Вы проиграли"
    
    await spin_msg.edit_text(
        f"🎡 <b>Рулетка</b>\n\n"
        f"{color} <b>{number}</b>\n"
        f"Ставка: {labels[bet_type]}\n\n"
        f"{'🎉 ВЫИГРЫШ!' if win else '❌ ПРОИГРЫШ'}\n"
        f"{win_text}\n\n"
        f"💰 Баланс: {user['balance']:,} POCX",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )
    await state.clear()

# ==================== СЛОТЫ ====================
@dp.callback_query(F.data == "game_slots")
async def cb_slots(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.slots_bet)
    await callback.message.edit_text(
        "🎰 <b>Слоты</b>\n\n"
        "Таблица выплат:\n"
        "7️⃣7️⃣7️⃣ = 50x | 💎💎💎 = 25x | ⭐⭐⭐ = 15x\n"
        "🍇🍇🍇 = 10x | 🍊🍊🍊 = 8x | 🍋🍋🍋 = 5x | 🍒🍒🍒 = 3x\n"
        "Два одинаковых = 1.5x\n\n"
        f"💵 Введите ставку (от {MIN_BET:,} до {MAX_BET:,} POCX):",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@dp.message(GameStates.slots_bet)
async def slots_bet(message: Message, state: FSMContext):
    try:
        bet = int(message.text.replace(",", ""))
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.answer(f"❌ От {MIN_BET:,} до {MAX_BET:,} POCX!")
        return
    
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подожди 5 секунд!")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.answer("❌ Недостаточно POCX!", reply_markup=main_menu())
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
    for _ in range(5):
        await asyncio.sleep(0.25)
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
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )
    await state.clear()

# ==================== COIN FLIP ====================
@dp.callback_query(F.data == "game_coin")
async def cb_coin(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.coin_choice)
    await callback.message.edit_text("🪙 <b>Coin Flip</b>\n\nВыбери сторону:", reply_markup=coin_menu(), parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.callback_query(GameStates.coin_choice, F.data.startswith("coin_"))
async def coin_choice(callback: CallbackQuery, state: FSMContext):
    side = callback.data[5:]
    await state.update_data(coin_side=side)
    await state.set_state(GameStates.coin_bet)
    label = "🦅 Орёл" if side == "heads" else "🔢 Решка"
    await callback.message.edit_text(
        f"🪙 <b>Coin Flip - {label}</b>\n\n💵 Введите ставку (от {MIN_BET:,} до {MAX_BET:,} POCX):",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@dp.message(GameStates.coin_bet)
async def coin_bet(message: Message, state: FSMContext):
    try:
        bet = int(message.text.replace(",", ""))
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.answer(f"❌ От {MIN_BET:,} до {MAX_BET:,} POCX!")
        return
    
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подожди 5 секунд!")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.answer("❌ Недостаточно POCX!", reply_markup=main_menu())
        await state.clear()
        return
    
    data = await state.get_data()
    side = data["coin_side"]
    
    flip_msg = await message.answer("🪙 Подбрасываем монету...")
    frames = ["🪙", "🌀", "🪙", "🌀", "🪙"]
    for frame in frames:
        await asyncio.sleep(0.3)
        try:
            await flip_msg.edit_text(f"🪙 Подбрасываем...\n\n{frame}")
        except:
            pass
    
    result = random.choice(["heads", "tails"])
    win = result == side
    multiplier = round(2.0 * (1 - HOUSE_EDGE), 2) if win else 0
    win_amount = int(bet * multiplier) if win else 0
    
    if win:
        add_pocx(message.from_user.id, win_amount)
    
    record_game(message.from_user.id, "coinflip", bet, multiplier if win else 0, win_amount, "win" if win else "loss", {"result": result, "choice": side})
    
    user = get_user(message.from_user.id)
    res_label = "🦅 Орёл" if result == "heads" else "🔢 Решка"
    
    await flip_msg.edit_text(
        f"🪙 <b>Coin Flip</b>\n\n"
        f"{'🦅' if result == 'heads' else '🔢'} Выпало: <b>{res_label}</b>\n\n"
        f"{'🎉 ВЫИГРЫШ!' if win else '❌ ПРОИГРЫШ'}\n"
        f"{f'💰 Выигрыш: {win_amount:,} POCX (2x)' if win else '😢 Вы проиграли'}\n\n"
        f"💰 Баланс: {user['balance']:,} POCX",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )
    await state.clear()

# ==================== HI-LO ====================
hilo_games = {}

@dp.callback_query(F.data == "game_hilo")
async def cb_hilo(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.hilo_bet)
    await callback.message.edit_text(
        "🃏 <b>Hi-Lo</b>\n\n"
        "Правила:\n"
        "• Угадай, будет следующая карта выше или ниже\n"
        "• Каждая верная догадка умножает ставку на 1.5x\n"
        "• Равная карта = 10x!\n\n"
        f"💵 Введите ставку (от {MIN_BET:,} до {MAX_BET:,} POCX):",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@dp.message(GameStates.hilo_bet)
async def hilo_bet(message: Message, state: FSMContext):
    try:
        bet = int(message.text.replace(",", ""))
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.answer(f"❌ От {MIN_BET:,} до {MAX_BET:,} POCX!")
        return
    
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подожди 5 секунд!")
        return
    
    if not remove_pocx(message.from_user.id, bet):
        await message.answer("❌ Недостаточно POCX!", reply_markup=main_menu())
        await state.clear()
        return
    
    RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    SUITS = ["♠️", "♥️", "♦️", "♣️"]
    
    current_card = random.choice(RANKS)
    game = {"bet": bet, "current_card": current_card, "round": 1, "multiplier": 1.0, "is_active": True}
    hilo_games[message.from_user.id] = game
    await state.update_data(hilo_bet=bet)
    await state.set_state(GameStates.hilo_active)
    
    await message.answer(
        f"🃏 <b>Hi-Lo - Раунд 1</b>\n\n"
        f"Открытая карта: <b>{current_card}</b>\n"
        f"Множитель: 1.00x\n\n"
        f"Следующая карта будет...",
        reply_markup=hilo_controls(False),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(GameStates.hilo_active, F.data.in_({"hilo_higher", "hilo_lower", "hilo_same"}))
async def hilo_guess(callback: CallbackQuery, state: FSMContext):
    direction = callback.data[5:]
    uid = callback.from_user.id
    game = hilo_games.get(uid)
    
    if not game:
        await callback.answer("Нет активной игры!", show_alert=True)
        return
    
    RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    SUITS = ["♠️", "♥️", "♦️", "♣️"]
    
    old_rank = RANKS.index(game["current_card"])
    new_card = random.choice(RANKS)
    new_rank = RANKS.index(new_card)
    suit = random.choice(SUITS)
    
    if direction == "higher":
        win = new_rank > old_rank
    elif direction == "lower":
        win = new_rank < old_rank
    else:
        win = new_rank == old_rank
    
    game["current_card"] = new_card
    game["round"] += 1
    
    if win:
        round_multi = 10.0 if direction == "same" else 1.5
        game["multiplier"] = round(game["multiplier"] * round_multi * (1 - HOUSE_EDGE), 3)
        await callback.message.edit_text(
            f"🃏 <b>Hi-Lo - Раунд {game['round']}</b>\n\n"
            f"✅ Угадали!\n"
            f"Новая карта: <b>{new_card}{suit}</b>\n"
            f"Множитель: <b>{game['multiplier']}x</b>\n"
            f"💰 Можно забрать: <b>{int(game['bet'] * game['multiplier']):,} POCX</b>\n\n"
            f"Продолжаем?",
            reply_markup=hilo_controls(True),
            parse_mode=ParseMode.HTML
        )
    else:
        record_game(uid, "hi-lo", game["bet"], 0, 0, "loss", {"rounds": game["round"] - 1, "last_card": new_card})
        user = get_user(uid)
        await callback.message.edit_text(
            f"🃏 <b>Hi-Lo</b>\n\n"
            f"❌ Не угадали!\n"
            f"Карта была: <b>{new_card}{suit}</b>\n\n"
            f"💸 Проигрыш: {game['bet']:,} POCX\n"
            f"💰 Баланс: {user['balance']:,} POCX",
            reply_markup=main_menu(),
            parse_mode=ParseMode.HTML
        )
        hilo_games.pop(uid, None)
        await state.clear()
    await callback.answer()

@dp.callback_query(GameStates.hilo_active, F.data == "hilo_cashout")
async def hilo_cashout(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    game = hilo_games.get(uid)
    
    if not game:
        await callback.answer("Нечего забирать!", show_alert=True)
        return
    
    win = int(game["bet"] * game["multiplier"])
    add_pocx(uid, win)
    record_game(uid, "hi-lo", game["bet"], game["multiplier"], win, "win", {"rounds": game["round"] - 1})
    
    user = get_user(uid)
    await callback.message.edit_text(
        f"🃏 <b>Hi-Lo - ВЫИГРЫШ!</b>\n\n"
        f"📈 Множитель: <b>{game['multiplier']}x</b>\n"
        f"💵 Ставка: {game['bet']:,} POCX\n"
        f"💰 <b>Выигрыш: {win:,} POCX</b>\n\n"
        f"💰 Баланс: {user['balance']:,} POCX",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )
    hilo_games.pop(uid, None)
    await state.clear()
    await callback.answer()

# ==================== ТОПЫ ====================
@dp.callback_query(F.data == "top_menu")
async def cb_top_menu(callback: CallbackQuery):
    await callback.message.edit_text("🏆 <b>Топы</b>\n\nВыбери категорию:", reply_markup=top_menu(), parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.callback_query(F.data == "top_all")
async def cb_top_all(callback: CallbackQuery):
    cursor.execute("SELECT user_id, username, total_won FROM users ORDER BY total_won DESC LIMIT 10")
    rows = cursor.fetchall()
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Топ за всё время</b>\n"]
    for i, row in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = row[1] or f"ID{row[0]}"
        lines.append(f"{medal} {name} — <b>{row[2]:,} POCX</b>")
    await callback.message.edit_text("\n".join(lines), reply_markup=top_menu(), parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.callback_query(F.data == "top_week")
async def cb_top_week(callback: CallbackQuery):
    cursor.execute("""
        SELECT u.user_id, u.username, SUM(gh.win_amount) as total
        FROM game_history gh JOIN users u ON u.user_id = gh.user_id
        WHERE gh.created_at >= date('now', '-7 days') AND gh.result = 'win'
        GROUP BY gh.user_id ORDER BY total DESC LIMIT 10
    """)
    rows = cursor.fetchall()
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Топ за неделю</b>\n"]
    for i, row in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = row[1] or f"ID{row[0]}"
        lines.append(f"{medal} {name} — <b>{row[2]:,} POCX</b>")
    await callback.message.edit_text("\n".join(lines), reply_markup=top_menu(), parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.callback_query(F.data == "top_day")
async def cb_top_day(callback: CallbackQuery):
    cursor.execute("""
        SELECT u.user_id, u.username, SUM(gh.win_amount) as total
        FROM game_history gh JOIN users u ON u.user_id = gh.user_id
        WHERE gh.created_at >= date('now', '-1 day') AND gh.result = 'win'
        GROUP BY gh.user_id ORDER BY total DESC LIMIT 10
    """)
    rows = cursor.fetchall()
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Топ за день</b>\n"]
    for i, row in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = row[1] or f"ID{row[0]}"
        lines.append(f"{medal} {name} — <b>{row[2]:,} POCX</b>")
    await callback.message.edit_text("\n".join(lines), reply_markup=top_menu(), parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.callback_query(F.data == "top_refs")
async def cb_top_refs(callback: CallbackQuery):
    cursor.execute("""
        SELECT u.username, COUNT(r.referred_id), COALESCE(SUM(r.earned_amount), 0)
        FROM referrals r JOIN users u ON u.user_id = r.referrer_id
        GROUP BY r.referrer_id ORDER BY COUNT(r.referred_id) DESC LIMIT 10
    """)
    rows = cursor.fetchall()
    medals = ["🥇", "🥈", "🥉"]
    lines = ["👥 <b>Топ рефераловодов</b>\n"]
    for i, row in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = row[0] or "Аноним"
        lines.append(f"{medal} {name} — <b>{row[1]}</b> реф. | {row[2]:,} POCX</b>")
    await callback.message.edit_text("\n".join(lines), reply_markup=top_menu(), parse_mode=ParseMode.HTML)
    await callback.answer()

# ==================== ФИНАНСЫ ====================
@dp.callback_query(F.data == "finance")
async def cb_finance(callback: CallbackQuery):
    await callback.message.edit_text("💰 <b>Финансы</b>", reply_markup=finance_menu(), parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.callback_query(F.data == "donate")
async def cb_donate(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 1 Star - 2,500 POCX", callback_data="donate_1")],
        [InlineKeyboardButton(text="⭐⭐ 5 Stars - 12,500 POCX", callback_data="donate_5")],
        [InlineKeyboardButton(text="⭐⭐⭐ 10 Stars - 25,000 POCX", callback_data="donate_10")],
        [InlineKeyboardButton(text="💰 25 Stars - 62,500 POCX", callback_data="donate_25")],
        [InlineKeyboardButton(text="💎 50 Stars - 125,000 POCX", callback_data="donate_50")],
        [InlineKeyboardButton(text="✏️ Своя сумма", callback_data="donate_custom")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="finance")]
    ])
    await callback.message.edit_text(
        "💎 <b>Пополнение через Telegram Stars</b>\n\n⭐ 1 Star = 2500 POCX",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

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
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )

# ==================== БОНУСЫ ====================
@dp.callback_query(F.data == "daily")
async def cb_daily(callback: CallbackQuery):
    uid = callback.from_user.id
    cursor.execute("SELECT last_daily_bonus, daily_streak FROM users WHERE user_id = ?", (uid,))
    row = cursor.fetchone()
    last = row[0]
    streak = row[1] or 0
    
    if last:
        last_dt = datetime.fromisoformat(last)
        if datetime.now() - last_dt < timedelta(days=1):
            await callback.answer("❌ Бонус уже получен сегодня!", show_alert=True)
            return
    
    bonus = random.randint(DAILY_BONUS_MIN, DAILY_BONUS_MAX)
    bonus = int(bonus * (1 + min(streak * 0.05, 0.5)))
    add_pocx(uid, bonus)
    cursor.execute("UPDATE users SET last_daily_bonus = CURRENT_TIMESTAMP, daily_streak = daily_streak + 1 WHERE user_id = ?", (uid,))
    conn.commit()
    
    await callback.message.edit_text(
        f"🎁 <b>Ежедневный бонус!</b>\n\n"
        f"💰 +{bonus:,} POCX\n"
        f"🔥 Серия дней: {streak + 1}\n"
        f"📈 Бонус увеличен на {min(streak * 5, 50)}%!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="bonuses")]]),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "welcome")
async def cb_welcome(callback: CallbackQuery):
    uid = callback.from_user.id
    cursor.execute("SELECT welcome_bonus_claimed FROM users WHERE user_id = ?", (uid,))
    claimed = cursor.fetchone()[0]
    if claimed:
        await callback.answer("❌ Приветственный бонус уже получен!", show_alert=True)
        return
    
    add_pocx(uid, WELCOME_BONUS)
    cursor.execute("UPDATE users SET welcome_bonus_claimed = 1 WHERE user_id = ?", (uid,))
    conn.commit()
    
    await callback.message.edit_text(
        f"🎁 <b>Приветственный бонус!</b>\n\n💰 +{WELCOME_BONUS:,} POCX",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="bonuses")]]),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "promo")
async def cb_promo(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.promo_code)
    await callback.message.edit_text("🔑 <b>Введите промокод</b>", parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.message(GameStates.promo_code)
async def promo_use(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    cursor.execute("SELECT bonus_amount, max_uses, used_count, expires_at, is_active FROM promocodes WHERE code = ?", (code,))
    row = cursor.fetchone()
    if not row or not row[4] or row[2] >= row[1]:
        await message.answer("❌ Промокод недействителен!", reply_markup=main_menu())
        await state.clear()
        return
    if row[3] and datetime.fromisoformat(row[3]) < datetime.now():
        await message.answer("❌ Промокод истёк!", reply_markup=main_menu())
        await state.clear()
        return
    cursor.execute("SELECT 1 FROM used_promocodes WHERE user_id = ? AND code = ?", (message.from_user.id, code))
    if cursor.fetchone():
        await message.answer("❌ Вы уже использовали этот промокод!", reply_markup=main_menu())
        await state.clear()
        return
    
    bonus = row[0]
    add_pocx(message.from_user.id, bonus)
    cursor.execute("INSERT INTO used_promocodes (user_id, code) VALUES (?, ?)", (message.from_user.id, code))
    cursor.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?", (code,))
    conn.commit()
    
    await message.answer(f"✅ Промокод активирован!\n💰 +{bonus:,} POCX", reply_markup=main_menu())
    await state.clear()

# ==================== АДМИН-ПАНЕЛЬ ====================
@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await callback.message.edit_text("👑 <b>Админ-панель</b>", reply_markup=admin_menu(), parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
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
    
    await callback.message.edit_text(
        f"📊 <b>Статистика казино</b>\n\n"
        f"👥 Пользователей: {users}\n"
        f"🚫 Забанено: {banned}\n"
        f"💰 Общий баланс: {total_balance:,} POCX\n"
        f"📊 Общий вейджер: {total_wagered:,} POCX\n"
        f"🏆 Выиграно всего: {total_won:,} POCX\n"
        f"💸 Проиграно всего: {total_lost:,} POCX\n"
        f"📈 Прибыль казино: {total_lost - total_won:,} POCX",
        reply_markup=admin_menu(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_give")
async def cb_admin_give(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await state.set_state(GameStates.admin_give)
    await callback.message.edit_text("➕ <b>Выдача POCX</b>\n\nВведи ID и сумму через пробел\nПример: `123456789 50000`")
    await callback.answer()

@dp.message(GameStates.admin_give)
async def admin_give_execute(message: Message, state: FSMContext):
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
    await message.answer(f"✅ Выдано {amount:,} POCX пользователю {uid}")
    await state.clear()

@dp.callback_query(F.data == "admin_take")
async def cb_admin_take(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await state.set_state(GameStates.admin_take)
    await callback.message.edit_text("➖ <b>Списание POCX</b>\n\nВведи ID и сумму через пробел\nПример: `123456789 50000`")
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
    amount = int(parts[1])
    if not remove_pocx(uid, amount):
        await message.answer(f"❌ У пользователя {uid} недостаточно средств!")
        return
    await message.answer(f"✅ Списано {amount:,} POCX у пользователя {uid}")
    await state.clear()

@dp.callback_query(F.data == "admin_ban")
async def cb_admin_ban(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await state.set_state(GameStates.admin_ban)
    await callback.message.edit_text("🔨 <b>Бан пользователя</b>\n\nВведи ID пользователя\nПример: `123456789`")
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
async def cb_admin_unban(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await state.set_state(GameStates.admin_unban)
    await callback.message.edit_text("🔓 <b>Разбан пользователя</b>\n\nВведи ID пользователя\nПример: `123456789`")
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
async def cb_admin_promo(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await state.set_state(GameStates.admin_promo_code)
    await callback.message.edit_text("🎟 <b>Создание промокода</b>\n\nВведи код промокода (только буквы и цифры):")
    await callback.answer()

@dp.message(GameStates.admin_promo_code)
async def admin_promo_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    if not code or len(code) < 3 or len(code) > 24:
        await message.answer("❌ Код должен быть 3-24 символа!")
        return
    await state.update_data(promo_code=code)
    await state.set_state(GameStates.admin_promo_reward)
    await message.answer("💰 Введи сумму награды:")

@dp.message(GameStates.admin_promo_reward)
async def admin_promo_reward(message: Message, state: FSMContext):
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
        f"✅ Промокод создан!\n"
        f"🎫 Код: <code>{code}</code>\n"
        f"💰 Награда: {reward:,} POCX\n"
        f"🎯 Активаций: {uses}",
        reply_markup=admin_menu(),
        parse_mode=ParseMode.HTML
    )
    await state.clear()

@dp.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    await state.set_state(GameStates.admin_broadcast)
    await callback.message.edit_text("📢 <b>Рассылка</b>\n\nВведи текст рассылки:")
    await callback.answer()

@dp.message(GameStates.admin_broadcast)
async def admin_broadcast_execute(message: Message, state: FSMContext):
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
    await message.answer(f"✅ Рассылка завершена! Отправлено {sent} пользователям.")
    await state.clear()

# ==================== ЗАПУСК ====================
async def main():
    print("🤖 POCX Bot запущен!")
    print(f"👥 Админы: {ADMIN_IDS}")
    print(f"✅ База данных обнулена и создана заново")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
