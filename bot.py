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
MAX_BET = 500000000
HOUSE_EDGE = 0.01

DAILY_BONUS_MIN = 100
DAILY_BONUS_MAX = 2000
WELCOME_BONUS = 1000
REF_REWARD = 5000
REF_REFERRAL_BONUS = 500

TREASURY_PRICE = 15000  # цена активации казны в чате
DEFAULT_TREASURY_REWARD = 500  # награда по умолчанию за приглашение

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
    last_game_time INTEGER DEFAULT 0,
    custom_status TEXT DEFAULT NULL,
    total_invites INTEGER DEFAULT 0
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

# Таблица казны для чатов (кто купил, настройки, баланс)
cursor.execute("""
CREATE TABLE IF NOT EXISTS chat_treasury (
    chat_id INTEGER PRIMARY KEY,
    owner_id INTEGER,
    balance INTEGER DEFAULT 0,
    reward_per_invite INTEGER DEFAULT 500,
    is_active BOOLEAN DEFAULT 0,
    purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_paid INTEGER DEFAULT 0
)
""")

# Таблица отслеживания уже награждённых пользователей (чтобы не начислять дважды)
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

# ==================== ФУНКЦИИ КАЗНЫ ====================
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
        "total_paid": row[6],
    }

def activate_treasury(chat_id: int, owner_id: int, amount: int = TREASURY_PRICE) -> bool:
    """Активация казны в чате (покупка за 15к POCX)"""
    user = get_user(owner_id)
    if not user or user["balance"] < amount:
        return False
    remove_pocx(owner_id, amount)
    cursor.execute("""
        INSERT OR REPLACE INTO chat_treasury (chat_id, owner_id, balance, is_active, reward_per_invite)
        VALUES (?, ?, ?, 1, ?)
    """, (chat_id, owner_id, amount, DEFAULT_TREASURY_REWARD))
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

def deactivate_treasury(chat_id: int):
    cursor.execute("UPDATE chat_treasury SET is_active = 0 WHERE chat_id = ?", (chat_id,))
    conn.commit()

def is_user_rewarded(chat_id: int, user_id: int) -> bool:
    cursor.execute("SELECT 1 FROM treasury_rewards WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
    return cursor.fetchone() is not None

def mark_user_rewarded(chat_id: int, user_id: int, invited_by: int):
    cursor.execute("INSERT OR IGNORE INTO treasury_rewards (chat_id, user_id, invited_by) VALUES (?, ?, ?)",
                   (chat_id, user_id, invited_by))
    conn.commit()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ====================
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
        "total_invites": row[14] or 0,
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
            total_lost = total_lost + ?
        WHERE user_id = ?
    """, (bet, win if result == "win" else 0, bet if result == "loss" else 0, user_id))
    cursor.execute("""
        INSERT INTO game_history (user_id, game_type, bet_amount, multiplier, win_amount, result, details)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, game_type, bet, mult, win, result, json.dumps(details)))
    conn.commit()

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
    kb.append([InlineKeyboardButton(text="◀️ Проверить подписку", callback_data="check_subscription")])
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
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="👑 Админ")],
            [KeyboardButton(text="🏦 Казны")]
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
        keyboard=[[KeyboardButton(text="⭐ Пополнить Stars")],
                  [KeyboardButton(text="◀️ Главное меню")]],
        resize_keyboard=True
    )

def bonuses_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎁 Ежедневный бонус"), KeyboardButton(text="🆕 Приветственный бонус")],
            [KeyboardButton(text="🔑 Активировать промокод")],
            [KeyboardButton(text="🧾 Чеки")],
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
            [KeyboardButton(text="◀️ Главное меню")]
        ],
        resize_keyboard=True
    )

def cancel_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )

def treasuries_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои казны"), KeyboardButton(text="🏪 Купить казну")],
            [KeyboardButton(text="⚙️ Настроить казну"), KeyboardButton(text="💰 Пополнить казну")],
            [KeyboardButton(text="📊 Статистика казны"), KeyboardButton(text="◀️ Главное меню")]
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
    check_create_amount = State()
    check_create_count = State()
    check_claim = State()
    assign_status_user = State()
    assign_status_text = State()
    treasury_purchase_chat = State()
    treasury_reward_set = State()
    treasury_add_amount = State()

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
    ok, not_sub = await check_subscription(uid)
    if not ok:
        await message.answer("❓ Подпишитесь на каналы:", reply_markup=subscription_keyboard(not_sub))
        return
    vip, _ = get_vip(user["total_wagered"])
    await message.answer(
        f"🎰 <b>POCX Casino Bot</b>\n\n"
        f"💰 Баланс: <b>{user['balance']:,} POCX</b>\n"
        f"💎 VIP: {vip}\n\n"
        f"🎮 Игры: Dice • Crash • Рулетка • Coin Flip • Hi-Lo\n\n"
        f"⭐ 1 Star = 2500 POCX\n"
        f"🔥 КД 5 сек\n\n"
        f"👥 Рефералка:\n<code>https://t.me/{(await bot.get_me()).username}?start=ref{user['referral_code']}</code>\n\n"
        f"🎁 За друга: +{REF_REWARD:,} вам, +{REF_REFERRAL_BONUS:,} другу",
        reply_markup=main_menu() if is_private(message) else None
    )

@dp.message(F.text == "◀️ Главное меню")
async def back_main(message: Message):
    user = get_user(message.from_user.id)
    vip, _ = get_vip(user["total_wagered"])
    await message.answer(
        f"🎰 <b>Главное меню</b>\n\n💰 Баланс: <b>{user['balance']:,} POCX</b> | {vip}",
        reply_markup=main_menu()
    )

# ==================== КАЗНЫ (ОСНОВНЫЕ ФУНКЦИИ) ====================
@dp.message(F.text == "🏦 Казны")
async def treasuries(message: Message):
    await message.answer(
        "🏦 <b>Казны</b>\n\n"
        "• <b>Купить казну</b> - активировать казну в чате за 15,000 POCX\n"
        "• <b>Настроить казну</b> - изменить награду за приглашение\n"
        "• <b>Пополнить казну</b> - добавить средства в казну\n"
        "• <b>Мои казны</b> - список ваших казн\n"
        "• <b>Статистика казны</b> - баланс и настройки",
        reply_markup=treasuries_menu(),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "🏪 Купить казну")
async def buy_treasury_start(message: Message, state: FSMContext):
    if message.chat.type == "private":
        await message.answer("❌ Купить казну можно только в чате! Добавьте бота в чат и повторите.")
        return
    await state.set_state(GameStates.treasury_purchase_chat)
    await message.answer(
        f"💰 <b>Покупка казны в чате</b>\n\n"
        f"Цена: {TREASURY_PRICE:,} POCX\n\n"
        f"После покупки казна будет активирована в этом чате.\n"
        f"За каждого нового участника, приглашённого по ссылке, пригласивший будет получать награду из казны.\n\n"
        f"Для подтверждения покупки введите <code>ДА</code>:",
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_menu()
    )

@dp.message(GameStates.treasury_purchase_chat)
async def buy_treasury_confirm(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=treasuries_menu())
        return
    if message.text.upper() != "ДА":
        await message.answer("❌ Введите <code>ДА</code> для подтверждения")
        return
    
    chat_id = message.chat.id
    existing = get_chat_treasury(chat_id)
    if existing and existing["is_active"]:
        await message.answer("❌ В этом чате уже активирована казна!")
        await state.clear()
        return
    
    if activate_treasury(chat_id, message.from_user.id, TREASURY_PRICE):
        await message.answer(
            f"✅ <b>Казна успешно активирована!</b>\n\n"
            f"💰 Баланс казны: {TREASURY_PRICE:,} POCX\n"
            f"🎁 Награда за приглашение: {DEFAULT_TREASURY_REWARD:,} POCX\n\n"
            f"Используйте <code>⚙️ Настроить казну</code> чтобы изменить награду.",
            parse_mode=ParseMode.HTML,
            reply_markup=treasuries_menu()
        )
    else:
        await message.answer("❌ Недостаточно средств для покупки казны!", reply_markup=treasuries_menu())
    await state.clear()

@dp.message(F.text == "⚙️ Настроить казну")
async def setup_treasury_start(message: Message, state: FSMContext):
    if message.chat.type == "private":
        await message.answer("❌ Настройка казны доступна только в чате!")
        return
    treasury = get_chat_treasury(message.chat.id)
    if not treasury or not treasury["is_active"]:
        await message.answer("❌ В этом чате казна не активирована!\nКупите казну: <code>🏪 Купить казну</code>", parse_mode=ParseMode.HTML)
        return
    if treasury["owner_id"] != message.from_user.id and message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Только владелец казны может настраивать её!")
        return
    await state.set_state(GameStates.treasury_reward_set)
    await message.answer(
        f"⚙️ <b>Настройка казны</b>\n\n"
        f"Текущая награда за приглашение: {treasury['reward_per_invite']:,} POCX\n\n"
        f"Введите новую сумму награды (от 100 до 100,000 POCX):",
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_menu()
    )

@dp.message(GameStates.treasury_reward_set)
async def set_treasury_reward(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=treasuries_menu())
        return
    try:
        reward = parse_amount(message.text)
        if reward < 100 or reward > 100000:
            raise ValueError
    except:
        await message.answer("❌ Введите сумму от 100 до 100,000 POCX!")
        return
    set_treasury_reward(message.chat.id, reward)
    await message.answer(f"✅ Награда за приглашение изменена на {reward:,} POCX!", reply_markup=treasuries_menu())
    await state.clear()

@dp.message(F.text == "💰 Пополнить казну")
async def add_to_treasury_start(message: Message, state: FSMContext):
    if message.chat.type == "private":
        await message.answer("❌ Пополнение казны доступно только в чате!")
        return
    treasury = get_chat_treasury(message.chat.id)
    if not treasury or not treasury["is_active"]:
        await message.answer("❌ В этом чате казна не активирована!", reply_markup=treasuries_menu())
        return
    await state.set_state(GameStates.treasury_add_amount)
    await message.answer(
        f"💰 <b>Пополнение казны</b>\n\n"
        f"Текущий баланс казны: {treasury['balance']:,} POCX\n\n"
        f"Введите сумму пополнения (минимум 1,000 POCX):",
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_menu()
    )

@dp.message(GameStates.treasury_add_amount)
async def add_to_treasury_execute(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=treasuries_menu())
        return
    try:
        amount = parse_amount(message.text)
        if amount < 1000:
            raise ValueError
    except:
        await message.answer("❌ Введите сумму от 1,000 POCX!")
        return
    user = get_user(message.from_user.id)
    if user["balance"] < amount:
        await message.answer(f"❌ Недостаточно средств! Нужно {amount:,} POCX")
        return
    remove_pocx(message.from_user.id, amount)
    add_to_chat_treasury(message.chat.id, amount)
    treasury = get_chat_treasury(message.chat.id)
    await message.answer(
        f"✅ Казна пополнена на {amount:,} POCX!\n"
        f"💰 Новый баланс казны: {treasury['balance']:,} POCX",
        reply_markup=treasuries_menu()
    )
    await state.clear()

@dp.message(F.text == "📋 Мои казны")
async def my_treasuries(message: Message):
    cursor.execute("SELECT chat_id, balance, reward_per_invite, is_active FROM chat_treasury WHERE owner_id = ?", (message.from_user.id,))
    rows = cursor.fetchall()
    if not rows:
        await message.answer("❌ У вас нет активных казн!", reply_markup=treasuries_menu())
        return
    text = "📋 <b>Ваши казны</b>\n\n"
    for row in rows:
        status = "✅ Активна" if row[3] else "❌ Неактивна"
        text += f"🏦 Чат: {row[0]}\n   Баланс: {row[1]:,} POCX\n   Награда: {row[2]:,} POCX\n   Статус: {status}\n\n"
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=treasuries_menu())

@dp.message(F.text == "📊 Статистика казны")
async def treasury_stats(message: Message):
    if message.chat.type == "private":
        await message.answer("❌ Статистика доступна только в чате!")
        return
    treasury = get_chat_treasury(message.chat.id)
    if not treasury:
        await message.answer("❌ В этом чате казна не активирована!", reply_markup=treasuries_menu())
        return
    cursor.execute("SELECT COUNT(*) FROM treasury_rewards WHERE chat_id = ?", (message.chat.id,))
    total_rewards = cursor.fetchone()[0]
    await message.answer(
        f"📊 <b>Статистика казны</b>\n\n"
        f"🏦 Чат: {message.chat.title or message.chat.id}\n"
        f"👑 Владелец: {treasury['owner_id']}\n"
        f"💰 Баланс: {treasury['balance']:,} POCX\n"
        f"🎁 Награда за приглашение: {treasury['reward_per_invite']:,} POCX\n"
        f"🎉 Выдано наград: {total_rewards}\n"
        f"📅 Куплена: {treasury['purchased_at']}",
        parse_mode=ParseMode.HTML,
        reply_markup=treasuries_menu()
    )

# ==================== ОБРАБОТЧИК НОВЫХ УЧАСТНИКОВ ====================
@dp.chat_member()
async def on_new_chat_member(event: ChatMemberUpdated):
    # Проверяем, что новый участник добавлен
    if event.new_chat_member.status in ["member", "administrator", "creator"]:
        if event.old_chat_member.status == event.new_chat_member.status:
            return
    else:
        return
    
    chat_id = event.chat.id
    new_user_id = event.new_chat_member.user.id
    
    # Проверяем, есть ли казна в чате
    treasury = get_chat_treasury(chat_id)
    if not treasury or not treasury["is_active"]:
        return
    
    # Проверяем, не награждали ли уже этого пользователя
    if is_user_rewarded(chat_id, new_user_id):
        return
    
    # Определяем, кто пригласил
    inviter_id = None
    if event.invite_link and event.invite_link.inviter:
        inviter_id = event.invite_link.inviter.id
    
    # Если не удалось определить пригласившего, не начисляем
    if not inviter_id:
        return
    
    # Проверяем, достаточно ли средств в казне
    reward = treasury["reward_per_invite"]
    if treasury["balance"] < reward:
        return
    
    # Начисляем награду
    if remove_from_chat_treasury(chat_id, reward):
        add_pocx(inviter_id, reward)
        mark_user_rewarded(chat_id, new_user_id, inviter_id)
        cursor.execute("UPDATE users SET total_invites = total_invites + 1 WHERE user_id = ?", (inviter_id,))
        conn.commit()
        
        # Уведомляем пригласившего (в лс)
        try:
            await bot.send_message(
                inviter_id,
                f"🎉 <b>Вы получили награду за приглашение!</b>\n\n"
                f"👤 Новый участник: {event.new_chat_member.user.first_name}\n"
                f"🏦 Чат: {event.chat.title}\n"
                f"💰 Награда: +{reward:,} POCX\n"
                f"📊 Баланс казны: {treasury['balance'] - reward:,} POCX",
                parse_mode=ParseMode.HTML
            )
        except:
            pass

# ==================== ОСТАЛЬНЫЕ ИГРЫ (кратко) ====================
def dice_impl(bet: int, chance: int):
    mult = round((100 / chance) * (1 - HOUSE_EDGE), 2)
    r = random.randint(1, 100)
    win = r < chance
    win_amt = int(bet * mult) if win else 0
    return win, win_amt, mult, r

@dp.message(lambda msg: msg.text and msg.text.lower().startswith("dice"))
async def dice_game(message: Message):
    parts = message.text.lower().split()
    if len(parts) != 3:
        await message.reply("❌ Формат: <code>dice [шанс] [сумма]</code>\nПример: <code>dice 5 1000</code>")
        return
    try:
        chance = int(parts[1])
        if chance not in [1,5,10,25,33,50]:
            raise ValueError
        bet = parse_amount(parts[2])
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.reply(f"❌ Шанс: 1,5,10,25,33,50 | Ставка: {MIN_BET}-{MAX_BET}")
        return
    if not check_cooldown(message.from_user.id):
        await message.reply("⏳ Подожди 5 секунд!")
        return
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств!")
        return
    win, win_amt, mult, r = dice_impl(bet, chance)
    if win:
        add_pocx(message.from_user.id, win_amt)
    record_game(message.from_user.id, "dice", bet, mult if win else 0, win_amt, "win" if win else "loss", {"roll": r, "target": chance})
    user = get_user(message.from_user.id)
    if win:
        await message.reply(f"🎲 <b>Dice</b>\nВыпало: {r} | Цель: <{chance}\n✅ +{win_amt:,} POCX ({mult}x)\n\n💰 Баланс: {user['balance']:,} POCX", parse_mode=ParseMode.HTML)
    else:
        await message.reply(f"🎲 <b>Dice</b>\nВыпало: {r} | Цель: <{chance}\n❌ -{bet:,} POCX\n\n💰 Баланс: {user['balance']:,} POCX", parse_mode=ParseMode.HTML)

@dp.message(lambda msg: msg.text and msg.text.lower().startswith("краш"))
async def crash_game(message: Message):
    parts = message.text.lower().split()
    if len(parts) != 2:
        await message.reply("❌ Формат: <code>краш [сумма]</code>")
        return
    try:
        bet = parse_amount(parts[1])
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.reply(f"❌ Ставка от {MIN_BET}")
        return
    if not check_cooldown(message.from_user.id):
        await message.reply("⏳ 5 секунд!")
        return
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств!")
        return
    r = random.random()
    if r < 0.06:
        crash = 1.00
    elif r < 0.55:
        crash = round(random.uniform(1.01, 1.80), 2)
    elif r < 0.80:
        crash = round(random.uniform(1.81, 2.80), 2)
    elif r < 0.93:
        crash = round(random.uniform(2.81, 4.50), 2)
    elif r < 0.985:
        crash = round(random.uniform(4.51, 9.50), 2)
    else:
        crash = round(random.uniform(9.51, 10.0), 2)
    mult = round(crash * 0.85, 2)
    mult = max(1.01, mult)
    win_amt = int(bet * mult)
    add_pocx(message.from_user.id, win_amt)
    record_game(message.from_user.id, "crash", bet, mult, win_amt, "win", {"crash": crash})
    user = get_user(message.from_user.id)
    await message.reply(f"🚀 <b>Crash</b>\n💥 Краш на {crash}x\n📈 Ты забрал на {mult}x\n✅ +{win_amt:,} POCX\n\n💰 Баланс: {user['balance']:,} POCX", parse_mode=ParseMode.HTML)

@dp.message(lambda msg: msg.text and msg.text.lower().startswith("руль"))
async def roulette_game(message: Message):
    parts = message.text.lower().split()
    if len(parts) != 3:
        await message.reply("❌ Формат: <code>руль [красное/черное/чет/нечет/зеро] [сумма]</code>")
        return
    types = {"красное":"red","красный":"red","черное":"black","черный":"black",
             "чет":"even","чёт":"even","нечет":"odd","нечёт":"odd","зеро":"zero","zero":"zero"}
    bet_type = types.get(parts[1])
    if not bet_type:
        await message.reply("❌ Ставка: красное, черное, чет, нечет, зеро")
        return
    try:
        bet = parse_amount(parts[2])
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.reply(f"❌ Ставка от {MIN_BET}")
        return
    if not check_cooldown(message.from_user.id):
        await message.reply("⏳ 5 секунд!")
        return
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств!")
        return
    num = random.randint(0, 36)
    RED = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    BLACK = {2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35}
    color = "🟢" if num == 0 else ("🔴" if num in RED else "⚫")
    win, mult = False, 0
    if bet_type == "red" and num in RED:
        win, mult = True, 2.0
    elif bet_type == "black" and num in BLACK:
        win, mult = True, 2.0
    elif bet_type == "zero" and num == 0:
        win, mult = True, 35.0
    elif bet_type == "even" and num != 0 and num % 2 == 0:
        win, mult = True, 2.0
    elif bet_type == "odd" and num != 0 and num % 2 == 1:
        win, mult = True, 2.0
    win_amt = int(bet * mult) if win else 0
    if win:
        add_pocx(message.from_user.id, win_amt)
    record_game(message.from_user.id, "roulette", bet, mult if win else 0, win_amt, "win" if win else "loss", {"num": num})
    user = get_user(message.from_user.id)
    if win:
        await message.reply(f"🎡 <b>Рулетка</b>\n{color} {num}\n✅ +{win_amt:,} POCX ({mult}x)\n\n💰 Баланс: {user['balance']:,} POCX", parse_mode=ParseMode.HTML)
    else:
        await message.reply(f"🎡 <b>Рулетка</b>\n{color} {num}\n❌ -{bet:,} POCX\n\n💰 Баланс: {user['balance']:,} POCX", parse_mode=ParseMode.HTML)

@dp.message(lambda msg: msg.text and msg.text.lower().startswith("монета"))
async def coin_game(message: Message):
    parts = message.text.lower().split()
    if len(parts) != 3:
        await message.reply("❌ Формат: <code>монета [орёл/решка] [сумма]</code>")
        return
    sides = {"орёл":"heads","орел":"heads","решка":"tails"}
    side = sides.get(parts[1])
    if not side:
        await message.reply("❌ Выбери: орёл или решка")
        return
    try:
        bet = parse_amount(parts[2])
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.reply(f"❌ Ставка от {MIN_BET}")
        return
    if not check_cooldown(message.from_user.id):
        await message.reply("⏳ 5 секунд!")
        return
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств!")
        return
    result = random.choice(["heads","tails"])
    win = result == side
    mult = round(2.0 * (1 - HOUSE_EDGE), 2) if win else 0
    win_amt = int(bet * mult) if win else 0
    if win:
        add_pocx(message.from_user.id, win_amt)
    record_game(message.from_user.id, "coinflip", bet, mult if win else 0, win_amt, "win" if win else "loss", {"result": result})
    user = get_user(message.from_user.id)
    res_label = "🦅 Орёл" if result == "heads" else "🔢 Решка"
    if win:
        await message.reply(f"🪙 <b>Coin Flip</b>\nВыпало: {res_label}\n✅ +{win_amt:,} POCX (2x)\n\n💰 Баланс: {user['balance']:,} POCX", parse_mode=ParseMode.HTML)
    else:
        await message.reply(f"🪙 <b>Coin Flip</b>\nВыпало: {res_label}\n❌ -{bet:,} POCX\n\n💰 Баланс: {user['balance']:,} POCX", parse_mode=ParseMode.HTML)

@dp.message(lambda msg: msg.text and msg.text.lower().startswith("хило"))
async def hilo_game(message: Message):
    parts = message.text.lower().split()
    if len(parts) != 3:
        await message.reply("❌ Формат: <code>хило [выше/ниже/равно] [сумма]</code>")
        return
    dirs = {"выше":"higher","ниже":"lower","равно":"same"}
    direction = dirs.get(parts[1])
    if not direction:
        await message.reply("❌ Выбери: выше, ниже или равно")
        return
    try:
        bet = parse_amount(parts[2])
        if bet < MIN_BET or bet > MAX_BET:
            raise ValueError
    except:
        await message.reply(f"❌ Ставка от {MIN_BET}")
        return
    if not check_cooldown(message.from_user.id):
        await message.reply("⏳ 5 секунд!")
        return
    if not remove_pocx(message.from_user.id, bet):
        await message.reply("❌ Недостаточно средств!")
        return
    RANKS = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
    SUITS = ["♠️","♥️","♦️","♣️"]
    current = random.choice(RANKS)
    old_idx = RANKS.index(current)
    new_card = random.choice(RANKS)
    new_idx = RANKS.index(new_card)
    suit = random.choice(SUITS)
    if direction == "higher":
        win = new_idx > old_idx
    elif direction == "lower":
        win = new_idx < old_idx
    else:
        win = new_idx == old_idx
    if win:
        round_multi = 10.0 if direction == "same" else 1.5
        mult = round(round_multi * (1 - HOUSE_EDGE), 3)
        win_amt = int(bet * mult)
        add_pocx(message.from_user.id, win_amt)
        user = get_user(message.from_user.id)
        await message.reply(f"🃏 <b>Hi-Lo</b>\nПервая: {current}\nСледующая: {new_card}{suit}\n✅ +{win_amt:,} POCX ({mult}x)\n\n💰 Баланс: {user['balance']:,} POCX", parse_mode=ParseMode.HTML)
    else:
        user = get_user(message.from_user.id)
        await message.reply(f"🃏 <b>Hi-Lo</b>\nПервая: {current}\nСледующая: {new_card}{suit}\n❌ -{bet:,} POCX\n\n💰 Баланс: {user['balance']:,} POCX", parse_mode=ParseMode.HTML)

# ==================== ЛС МЕНЮ ====================
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

# ==================== ЧЕКИ ====================
@dp.message(F.text == "🧾 Чеки")
async def checks_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать чек", callback_data="check_create")],
        [InlineKeyboardButton(text="📥 Активировать чек", callback_data="check_claim")],
        [InlineKeyboardButton(text="📋 Мои чеки", callback_data="check_my")]
    ])
    await message.answer("🧾 <b>Чеки</b>\n\nСоздавайте и активируйте чеки на POCX", reply_markup=kb, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "check_create")
async def check_create_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.check_create_amount)
    await callback.message.edit_text("💰 Введи сумму на одну активацию чека (макс 5,000,000 POCX):")
    await callback.answer()

@dp.message(GameStates.check_create_amount)
async def check_create_amount(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
        if amount <= 0 or amount > 5_000_000:
            raise ValueError
    except:
        await message.answer("❌ Введи сумму от 1 до 5,000,000 POCX!")
        return
    await state.update_data(check_amount=amount)
    await state.set_state(GameStates.check_create_count)
    await message.answer("🔢 Введи количество активаций (макс 50):")

@dp.message(GameStates.check_create_count)
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
    code = hashlib.md5(f"{message.from_user.id}{time.time()}{random.random()}".encode()).hexdigest()[:8].upper()
    cursor.execute("INSERT INTO checks (code, creator_id, per_user, remaining, used, password) VALUES (?, ?, ?, ?, ?, ?)",
                   (code, message.from_user.id, amount, count, "[]", None))
    conn.commit()
    await message.answer(
        f"✅ <b>Чек создан!</b>\n\n"
        f"🎫 Код: <code>{code}</code>\n"
        f"💰 Сумма: {amount:,} POCX\n"
        f"📊 Активаций: {count}\n\n"
        f"Команда для активации: <code>/activate {code}</code>",
        parse_mode=ParseMode.HTML
    )
    await state.clear()

@dp.callback_query(F.data == "check_claim")
async def check_claim_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.check_claim)
    await callback.message.edit_text("🔑 Введи код чека:")
    await callback.answer()

@dp.message(GameStates.check_claim)
async def check_claim(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    cursor.execute("SELECT per_user, remaining, used, password FROM checks WHERE code = ?", (code,))
    row = cursor.fetchone()
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
    cursor.execute("SELECT code, per_user, remaining FROM checks WHERE creator_id = ? ORDER BY rowid DESC LIMIT 10", (callback.from_user.id,))
    rows = cursor.fetchall()
    if not rows:
        await callback.message.edit_text("📋 У вас нет созданных чеков.")
        await callback.answer()
        return
    text = "📋 <b>Ваши чеки</b>\n\n"
    for row in rows:
        text += f"🎫 <code>{row[0]}</code> | {row[1]:,} POCX | осталось: {row[2]}\n"
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML)
    await callback.answer()

@dp.message(Command("activate"))
async def activate_check_command(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Используй: <code>/activate КОД</code>", parse_mode=ParseMode.HTML)
        return
    code = parts[1].upper()
    cursor.execute("SELECT per_user, remaining, used, password FROM checks WHERE code = ?", (code,))
    row = cursor.fetchone()
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

# ==================== ПЕРЕВОДЫ С КОМИССИЕЙ ====================
@dp.message(lambda msg: msg.text and msg.text.lower().startswith("д ") and msg.reply_to_message)
async def transfer_command(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        await message.reply("❌ Используй: <code>д [сумма]</code> в ответ на сообщение пользователя", parse_mode=ParseMode.HTML)
        return
    try:
        amount = parse_amount(parts[1])
        if amount <= 0:
            raise ValueError
    except:
        await message.reply("❌ Введи корректную сумму!")
        return
    user = get_user(message.from_user.id)
    if user["balance"] < amount:
        await message.reply("❌ Недостаточно средств!")
        return
    commission = int(amount * 0.03)
    total = amount + commission
    if user["balance"] < total:
        await message.reply(f"❌ Недостаточно средств с учётом комиссии 3%! Нужно {total:,} POCX")
        return
    target_id = message.reply_to_message.from_user.id
    remove_pocx(message.from_user.id, total)
    add_pocx(target_id, amount)
    await message.reply(f"✅ Переведено {amount:,} POCX пользователю\n💸 Комиссия: {commission:,} POCX")

# ==================== РЕФЕРАЛЫ ====================
@dp.message(F.text == "👥 Рефералы")
async def referrals(message: Message):
    user = get_user(message.from_user.id)
    count = cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (message.from_user.id,)).fetchone()[0]
    earned = cursor.execute("SELECT COALESCE(SUM(earned_amount),0) FROM referrals WHERE referrer_id = ?", (message.from_user.id,)).fetchone()[0]
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref{user['referral_code']}"
    await message.answer(
        f"👥 <b>Рефералы</b>\n\n"
        f"🔗 Ссылка:\n<code>{link}</code>\n\n"
        f"👤 Приглашено: {count}\n"
        f"💰 Заработано: {earned:,} POCX\n\n"
        f"🎁 За друга: +{REF_REWARD:,} вам, +{REF_REFERRAL_BONUS:,} другу",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )

# ==================== СТАТИСТИКА ====================
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
        f"🏆 Выиграно всего: {user['total_won']:,} POCX",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )

# ==================== ПРОФИЛЬ ====================
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

# ==================== ТЕКСТОВЫЕ КОМАНДЫ В ЧАТАХ ====================
@dp.message(lambda msg: msg.chat.type != "private" and msg.text and msg.text.lower() in ["б", "бал", "баланс"])
async def chat_balance(message: Message):
    user = get_user(message.from_user.id)
    await message.reply(f"💰 Баланс: {user['balance']:,} POCX")

@dp.message(lambda msg: msg.chat.type != "private" and msg.text and msg.text.lower() in ["п", "проф", "профиль"])
async def chat_profile(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        return
    vip, _ = get_vip(user["total_wagered"])
    status = user.get("custom_status") or "Обычный"
    await message.reply(
        f"👤 <b>Профиль</b>\n\n💰 {user['balance']:,} POCX\n💎 {vip}\n🏷 {status}\n📊 Вейджер: {user['total_wagered']:,}\n🏆 Выиграно: {user['total_won']:,}\n💸 Проиграно: {user['total_lost']:,}",
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
    cnt = cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (message.from_user.id,)).fetchone()[0]
    earned = cursor.execute("SELECT COALESCE(SUM(earned_amount),0) FROM referrals WHERE referrer_id = ?", (message.from_user.id,)).fetchone()[0]
    await message.reply(f"👥 <b>Рефералы</b>\n\n👤 Приглашено: {cnt}\n💰 Заработано: {earned:,} POCX", parse_mode=ParseMode.HTML)

@dp.message(lambda msg: msg.chat.type != "private" and msg.text and msg.text.lower() in ["бн", "бонус", "бонусы"])
async def chat_bonus(message: Message):
    uid = message.from_user.id
    row = cursor.execute("SELECT last_daily_bonus, daily_streak FROM users WHERE user_id = ?", (uid,)).fetchone()
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
    played = cursor.execute("SELECT COUNT(*) FROM game_history WHERE user_id = ?", (message.from_user.id,)).fetchone()[0] if user else 0
    wins = cursor.execute("SELECT COUNT(*) FROM game_history WHERE user_id = ? AND result = 'win'", (message.from_user.id,)).fetchone()[0] if user else 0
    wr = wins / max(played, 1) * 100
    await message.reply(f"📊 <b>Статистика</b>\n\n🎮 Игр: {played}\n✅ Побед: {wins} ({wr:.1f}%)", parse_mode=ParseMode.HTML)

@dp.message(lambda msg: msg.chat.type != "private" and msg.text and msg.text.lower() in ["и", "игры"])
async def chat_games(message: Message):
    await message.reply(
        "🎮 <b>Игры</b>\n\n"
        "• <code>dice [шанс] [сумма]</code> — шанс 1,5,10,25,33,50\n"
        "• <code>краш [сумма]</code>\n"
        "• <code>руль [красное/черное/чет/нечет/зеро] [сумма]</code>\n"
        "• <code>монета [орёл/решка] [сумма]</code> — 2x\n"
        "• <code>хило [выше/ниже/равно] [сумма]</code>\n\n"
        "💰 Сокращения: 1к=1000, 1кк=1_000_000\n"
        "Пример: <code>dice 5 1к</code>",
        parse_mode=ParseMode.HTML
    )

@dp.message(lambda msg: msg.chat.type != "private" and msg.text and msg.text.lower() in ["помощь", "help", "/help"])
async def chat_help(message: Message):
    await message.reply(
        "📖 <b>Команды в чате:</b>\n\n"
        "• <code>б</code> — баланс\n"
        "• <code>п</code> — профиль\n"
        "• <code>т</code> — топ\n"
        "• <code>р</code> — рефералы\n"
        "• <code>бн</code> — бонус\n"
        "• <code>ст</code> — статистика\n"
        "• <code>и</code> — список игр\n"
        "• <code>помощь</code> — это сообщение\n\n"
        "🎮 Игровые команды — см. <code>и</code>\n\n"
        "🏦 <b>Казны в чатах:</b> купите казну за 15,000 POCX, настройте награду и получайте награды за приглашение новых участников!",
        parse_mode=ParseMode.HTML
    )

# ==================== ФИНАНСЫ (STARS) ====================
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
    _, stars, pocx = payload.split("_")
    stars = int(stars)
    pocx = int(pocx)
    add_pocx(message.from_user.id, pocx)
    await message.answer(
        f"✅ Оплачено {stars} ⭐!\n💰 Получено {pocx:,} POCX\n\n⭐ 1 Star = 2500 POCX",
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML
    )

# ==================== АДМИН-ПАНЕЛЬ ====================
@dp.message(F.text == "👑 Админ")
async def admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!", reply_markup=main_menu())
        return
    await message.answer("👑 <b>Админ-панель</b>", reply_markup=admin_menu(), parse_mode=ParseMode.HTML)

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    users = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_balance = cursor.execute("SELECT SUM(balance) FROM users").fetchone()[0] or 0
    total_wagered = cursor.execute("SELECT SUM(total_wagered) FROM users").fetchone()[0] or 0
    total_won = cursor.execute("SELECT SUM(total_won) FROM users").fetchone()[0] or 0
    total_lost = cursor.execute("SELECT SUM(total_lost) FROM users").fetchone()[0] or 0
    banned = cursor.execute("SELECT COUNT(*) FROM banned_users").fetchone()[0] or 0
    await message.answer(
        f"📊 <b>Статистика казино</b>\n\n"
        f"👥 Пользователей: {users}\n"
        f"🚫 Забанено: {banned}\n"
        f"💰 Общий баланс: {total_balance:,} POCX\n"
        f"📊 Общий вейджер: {total_wagered:,} POCX\n"
        f"🏆 Выиграно: {total_won:,} POCX\n"
        f"💸 Проиграно: {total_lost:,} POCX\n"
        f"📈 Прибыль: {total_lost - total_won:,} POCX",
        reply_markup=admin_menu(),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "💰 Выдать POCX")
async def admin_give_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    await state.set_state(GameStates.admin_give)
    await message.answer("💰 Введи ID и сумму через пробел\nПример: `123456789 50000`", reply_markup=cancel_menu())

@dp.message(GameStates.admin_give)
async def admin_give_execute(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_menu())
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
    amount = parse_amount(parts[1])
    add_pocx(uid, amount)
    await message.answer(f"✅ Выдано {amount:,} POCX пользователю {uid}", reply_markup=admin_menu())
    await state.clear()

@dp.message(F.text == "➖ Забрать POCX")
async def admin_take_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    await state.set_state(GameStates.admin_take)
    await message.answer("➖ Введи ID и сумму через пробел\nПример: `123456789 50000`", reply_markup=cancel_menu())

@dp.message(GameStates.admin_take)
async def admin_take_execute(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_menu())
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
    amount = parse_amount(parts[1])
    if not remove_pocx(uid, amount):
        await message.answer(f"❌ У пользователя {uid} недостаточно средств!")
        return
    await message.answer(f"✅ Списано {amount:,} POCX у пользователя {uid}", reply_markup=admin_menu())
    await state.clear()

@dp.message(F.text == "🔨 Забанить")
async def admin_ban_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    await state.set_state(GameStates.admin_ban)
    await message.answer("🔨 Введи ID пользователя\nПример: `123456789`", reply_markup=cancel_menu())

@dp.message(GameStates.admin_ban)
async def admin_ban_execute(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_menu())
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
    await message.answer(f"✅ Пользователь {uid} забанен", reply_markup=admin_menu())
    await state.clear()

@dp.message(F.text == "🔓 Разбанить")
async def admin_unban_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    await state.set_state(GameStates.admin_unban)
    await message.answer("🔓 Введи ID пользователя\nПример: `123456789`", reply_markup=cancel_menu())

@dp.message(GameStates.admin_unban)
async def admin_unban_execute(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_menu())
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
    await message.answer(f"✅ Пользователь {uid} разбанен", reply_markup=admin_menu())
    await state.clear()

@dp.message(F.text == "🎟 Создать промокод")
async def admin_promo_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    await state.set_state(GameStates.admin_promo_code)
    await message.answer("🎟 Введи код промокода (3-24 символа):", reply_markup=cancel_menu())

@dp.message(GameStates.admin_promo_code)
async def admin_promo_code(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_menu())
        return
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
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_menu())
        return
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
        reply_markup=admin_menu(),
        parse_mode=ParseMode.HTML
    )
    await state.clear()

@dp.message(F.text == "📢 Рассылка")
async def admin_broadcast_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа!")
        return
    await state.set_state(GameStates.admin_broadcast)
    await message.answer("📢 Введи текст рассылки:", reply_markup=cancel_menu())

@dp.message(GameStates.admin_broadcast)
async def admin_broadcast_execute(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_menu())
        return
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
    await message.answer(f"✅ Рассылка завершена! Отправлено {sent} пользователям.", reply_markup=admin_menu())
    await state.clear()

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
    cursor.execute("UPDATE users SET custom_status = ? WHERE user_id = ?", (status_text, target))
    conn.commit()
    await message.answer(f"✅ Пользователю {target} назначен статус: {status_text}", reply_markup=admin_menu())
    await state.clear()

# ==================== ЗАПУСК ====================
async def main():
    print("🤖 POCX Bot запущен!")
    print(f"👥 Админы: {ADMIN_IDS}")
    print("✅ Игры: Dice, Crash, Рулетка, Coin Flip, Hi-Lo")
    print("✅ Казны: покупка за 15,000 POCX, награды за приглашения")
    print("✅ Чеки, переводы с комиссией 3%")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
