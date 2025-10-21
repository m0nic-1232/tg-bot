import asyncio
import logging
import os
import random
import time
import json
import pickle
import signal
import atexit
import sqlite3
from datetime import datetime, timedelta

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
    ApplicationBuilder,
    CallbackQueryHandler,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Файл для базы данных
DB_FILE = "bot_database.db"

# States for the conversation
(
    GENDER,
    NAME,
    AGE,
    CITY,
    BIO,
    PHOTO,
    CONFIRMATION,
    MENU,
    SEARCH,
    LIKE,
    DISLIKE,
    SETTINGS,
    EDIT_PROFILE,
    EDIT_GENDER,
    EDIT_NAME,
    EDIT_AGE,
    EDIT_CITY,
    EDIT_BIO,
    EDIT_PHOTO,
    PENDING_MATCH_RESPONSE,
    ADMIN_PANEL,
    MAINTENANCE_NOTICE,
    BAN_MANAGEMENT,
    END
) = range(24)

# Global dictionaries to store data
user_profiles = {}
user_likes = {}
user_dislikes = {}
matched_users = {}

# Админы бота
ADMIN_USER_IDS = [5652528225]  # ЗАМЕНИ НА РЕАЛЬНЫЕ ID

# --- БАЗА ДАННЫХ SQLite ---
class Database:
    def __init__(self, db_file):
        self.db_file = db_file
        self.init_db()
    
    def init_db(self):
        """Инициализация базы данных"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                gender TEXT,
                name TEXT,
                age INTEGER,
                city INTEGER,
                bio TEXT,
                photo TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица лайков
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                liker_id INTEGER,
                liked_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(liker_id, liked_id)
            )
        ''')
        
        # Таблица совпадений
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user1_id INTEGER,
                user2_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user1_id, user2_id)
            )
        ''')
        
        # Таблица настроек бота
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                maintenance_mode BOOLEAN DEFAULT 0,
                maintenance_message TEXT,
                maintenance_end TIMESTAMP
            )
        ''')
        
        # Таблица банов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bans (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                reason TEXT,
                banned_by INTEGER,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                unbanned_at TIMESTAMP NULL
            )
        ''')
        
        # Инициализируем настройки
        cursor.execute('INSERT OR IGNORE INTO bot_settings (id, maintenance_mode) VALUES (1, 0)')
        
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    
    def load_all_data(self):
        """Загружает все данные из базы в память"""
        global user_profiles, user_likes, matched_users
        
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        # Загружаем пользователей
        cursor.execute('SELECT * FROM users')
        users = cursor.fetchall()
        for user in users:
            user_id = user[0]
            user_profiles[user_id] = {
                'username': user[1],
                'gender': user[2],
                'name': user[3],
                'age': user[4],
                'city': user[5],
                'bio': user[6],
                'photo': user[7],
                'created_at': user[8],
                'last_active': user[9]
            }
        
        # Загружаем лайки
        cursor.execute('SELECT liker_id, liked_id FROM likes')
        likes = cursor.fetchall()
        for liker_id, liked_id in likes:
            if liker_id not in user_likes:
                user_likes[liker_id] = set()
            user_likes[liker_id].add(liked_id)
        
        # Загружаем совпадения
        cursor.execute('SELECT user1_id, user2_id FROM matches')
        matches = cursor.fetchall()
        for user1_id, user2_id in matches:
            if user1_id not in matched_users:
                matched_users[user1_id] = set()
            if user2_id not in matched_users:
                matched_users[user2_id] = set()
            matched_users[user1_id].add(user2_id)
            matched_users[user2_id].add(user1_id)
        
        conn.close()
        logger.info(f"Loaded from DB: {len(user_profiles)} users, {len(user_likes)} like relations")
    
    def save_user(self, user_id, profile_data):
        """Сохраняет/обновляет пользователя в БД"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO users 
            (user_id, username, gender, name, age, city, bio, photo, last_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (
            user_id,
            profile_data.get('username'),
            profile_data.get('gender'),
            profile_data.get('name'),
            profile_data.get('age'),
            profile_data.get('city'),
            profile_data.get('bio'),
            profile_data.get('photo')
        ))
        
        conn.commit()
        conn.close()
    
    def add_like(self, liker_id, liked_id):
        """Добавляет лайк в БД"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'INSERT OR IGNORE INTO likes (liker_id, liked_id) VALUES (?, ?)',
                (liker_id, liked_id)
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Error saving like to DB: {e}")
        finally:
            conn.close()
    
    def add_match(self, user1_id, user2_id):
        """Добавляет совпадение в БД"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        # Убедимся, что user1_id всегда меньше user2_id для уникальности
        u1, u2 = sorted([user1_id, user2_id])
        
        try:
            cursor.execute(
                'INSERT OR IGNORE INTO matches (user1_id, user2_id) VALUES (?, ?)',
                (u1, u2)
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Error saving match to DB: {e}")
        finally:
            conn.close()
    
    def get_maintenance_status(self):
        """Проверяет статус техобслуживания"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('SELECT maintenance_mode, maintenance_message, maintenance_end FROM bot_settings WHERE id = 1')
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                'maintenance_mode': bool(result[0]),
                'maintenance_message': result[1],
                'maintenance_end': result[2]
            }
        return {'maintenance_mode': False, 'maintenance_message': None, 'maintenance_end': None}
    
    def set_maintenance_mode(self, enabled, message=None, end_time=None):
        """Устанавливает режим техобслуживания"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE bot_settings 
            SET maintenance_mode = ?, maintenance_message = ?, maintenance_end = ?
            WHERE id = 1
        ''', (1 if enabled else 0, message, end_time))
        
        conn.commit()
        conn.close()

    # --- ФУНКЦИИ ДЛЯ БАНОВ ---
    def is_user_banned(self, user_id):
        """Проверяет, забанен ли пользователь"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('SELECT user_id FROM bans WHERE user_id = ? AND unbanned_at IS NULL', (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        return result is not None

    def ban_user(self, user_id, username, reason, admin_id):
        """Банит пользователя"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO bans (user_id, username, reason, banned_by) 
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, reason, admin_id))
        
        conn.commit()
        conn.close()

    def unban_user(self, user_id):
        """Разбанивает пользователя"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('UPDATE bans SET unbanned_at = CURRENT_TIMESTAMP WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()

    def get_banned_users(self):
        """Получает список забаненных пользователей"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT user_id, username, reason, banned_at 
            FROM bans 
            WHERE unbanned_at IS NULL 
            ORDER BY banned_at DESC
        ''')
        banned_users = cursor.fetchall()
        conn.close()
        
        return banned_users

    def get_user_info(self, user_id):
        """Получает информацию о пользователе"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        return user

# Инициализация базы данных
db = Database(DB_FILE)

# --- ФУНКЦИИ ДЛЯ СОХРАНЕНИЯ ДАННЫХ ---
def save_data():
    """Сохраняет все данные (резервное копирование)"""
    data = {
        'user_profiles': user_profiles,
        'user_likes': user_likes,
        'user_dislikes': user_dislikes,
        'matched_users': matched_users
    }
    try:
        with open("backup_data.pkl", 'wb') as f:
            pickle.dump(data, f)
        logger.info("Backup data saved successfully")
    except Exception as e:
        logger.error(f"Error saving backup data: {e}")

def load_data():
    """Загружает данные из базы"""
    db.load_all_data()
    logger.info("Data loaded from database")

def setup_data_persistence():
    """Настраивает автосохранение при выходе"""
    def save_on_exit():
        maintenance_notice()
        save_data()  # Резервное копирование
        logger.info("Backup saved on exit")
    
    def save_on_signal(signum, frame):
        maintenance_notice()
        save_data()  # Резервное копирование
        logger.info(f"Backup saved on signal {signum}")
        exit(0)
    
    atexit.register(save_on_exit)
    signal.signal(signal.SIGINT, save_on_signal)
    signal.signal(signal.SIGTERM, save_on_signal)

# Декоратор для автоматического сохранения в БД
def auto_save(func):
    async def wrapper(*args, **kwargs):
        result = await func(*args, **kwargs)
        # Критичные данные сохраняются сразу в БД в самих функциях
        return result
    return wrapper

# --- ОПОВЕЩЕНИЯ В КОНСОЛИ ---
def maintenance_notice():
    """Оповещение о техобслуживании в консоли"""
    print("\n" + "="*60)
    print("🛠️  БОТ УХОДИТ НА ТЕХНИЧЕСКОЕ ОБСЛУЖИВАНИЕ")
    print("🕐 Время остановки:", time.strftime("%Y-%m-%d %H:%M:%S"))
    print("📈 Статистика перед остановкой:")
    print(f"   👥 Пользователей: {len(user_profiles)}")
    print(f"   ✅ Заполненных анкет: {len([uid for uid in user_profiles if is_profile_complete(uid)])}")
    print(f"   ❤️  Всего лайков: {sum(len(likes) for likes in user_likes.values())}")
    print(f"   💞 Совпадений: {sum(len(matches) for matches in matched_users.values()) // 2}")
    print(f"   📊 Активных сессий: {len(user_profiles)}")
    print("💾 Сохранение данных...")
    print("="*60 + "\n")

def startup_notice():
    """Оповещение о запуске бота"""
    print("\n" + "="*50)
    print("🚀 БОТ ЗАПУЩЕН")
    print("🕐 Время запуска:", time.strftime("%Y-%m-%d %H:%M:%S"))
    print("📥 Загружено данных:")
    print(f"   👥 Пользователей: {len(user_profiles)}")
    print(f"   ❤️  Лайков: {sum(len(likes) for likes in user_likes.values())}")
    print(f"   💞 Совпадений: {sum(len(matches) for matches in matched_users.values()) // 2}")
    
    # Проверяем режим техобслуживания
    maintenance_status = db.get_maintenance_status()
    if maintenance_status['maintenance_mode']:
        print("   ⚠️  Бот в режиме техобслуживания")
    
    # Проверяем баны
    banned_users = db.get_banned_users()
    print(f"   🚫 Забанено пользователей: {len(banned_users)}")
    
    print("="*50 + "\n")

# --- ПРОВЕРКА БАНОВ ---
async def check_ban(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int = None) -> bool:
    """Проверяет, забанен ли пользователь"""
    if user_id is None:
        user_id = update.effective_user.id
    
    # Админы не могут быть забанены
    if user_id in ADMIN_USER_IDS:
        return False
        
    if db.is_user_banned(user_id):
        ban_info = db.get_banned_users()
        user_ban = next((ban for ban in ban_info if ban[0] == user_id), None)
        
        if user_ban:
            reason = user_ban[2] or "Нарушение правил"
            message = f"🚫 Вы забанены!\n\nПричина: {reason}\n\nДля разбирательства обратитесь к администратору."
            
            await update.message.reply_text(message, reply_markup=ReplyKeyboardRemove())
            return True
    
    return False

# --- ИСПРАВЛЕННЫЕ ФУНКЦИИ ПРОВЕРКИ ТЕХОБСЛУЖИВАНИЯ ---
async def check_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int = None) -> bool:
    """Проверяет, находится ли бот в режиме техобслуживания"""
    if user_id is None:
        user_id = update.effective_user.id
    
    # Админы могут использовать бот даже во время техобслуживания
    if user_id in ADMIN_USER_IDS:
        return False
        
    maintenance_status = db.get_maintenance_status()
    
    if maintenance_status['maintenance_mode']:
        message = maintenance_status['maintenance_message'] or "⚙️ Бот находится на техническом обслуживании. Пожалуйста, попробуйте позже."
        
        keyboard = [[KeyboardButton("🔄 Проверить статус")]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(message, reply_markup=reply_markup)
        return True
    return False

async def check_maintenance_for_user(user_id: int) -> bool:
    """Проверяет техобслуживание для конкретного пользователя"""
    # Админы могут использовать бот даже во время техобслуживания
    if user_id in ADMIN_USER_IDS:
        return False
        
    maintenance_status = db.get_maintenance_status()
    return maintenance_status['maintenance_mode']

# --- ИСПРАВЛЕННАЯ ФУНКЦИЯ: Проверка статуса ---
async def check_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ОБРАБОТЧИК для кнопки 'Проверить статус' - работает ВНЕ ConversationHandler"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return
    
    # Админы всегда могут использовать бот
    if user_id in ADMIN_USER_IDS:
        await start(update, context)
        return
    
    maintenance_status = db.get_maintenance_status()
    
    if maintenance_status['maintenance_mode']:
        message = maintenance_status['maintenance_message'] or "⚙️ Бот все еще находится на техническом обслуживании. Пожалуйста, попробуйте позже."
        
        keyboard = [[KeyboardButton("🔄 Проверить статус")]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(message, reply_markup=reply_markup)
    else:
        # Если техобслуживание закончилось, возвращаем в меню
        await update.message.reply_text("✅ Бот снова активен! Возвращаемся в меню...")
        await start(update, context)

# --- НОВАЯ ФУНКЦИЯ: Очистка старых просмотренных анкет ---
def clear_old_viewed_profiles(user_data):
    """Очищает историю просмотренных анкет, если их слишком много"""
    if 'viewed_profiles' in user_data:
        if len(user_data['viewed_profiles']) > 50:
            user_data['viewed_profiles'] = user_data['viewed_profiles'][-25:]
            logger.info(f"Cleared old viewed profiles, now {len(user_data['viewed_profiles'])} remaining")

# --- НОВАЯ ФУНКЦИЯ: Команда для очистки истории ---
@auto_save
async def clear_history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очищает историю просмотренных анкет, лайки и дизлайки"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    user_data = context.user_data
    
    if 'viewed_profiles' in user_data:
        user_data['viewed_profiles'] = []
    
    if user_id in user_likes:
        user_likes[user_id] = set()
    if user_id in user_dislikes:
        user_dislikes[user_id] = set()
    
    await update.message.reply_text("✅ История полностью очищена! Теперь вы увидите все анкеты заново.")

# --- НОВАЯ ФУНКЦИЯ: Полный сброс ---
@auto_save
async def reset_all_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Полный сброс для тестирования"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    user_data = context.user_data
    
    user_data.clear()
    if user_id in user_likes:
        user_likes[user_id] = set()
    if user_id in user_dislikes:
        user_dislikes[user_id] = set()
    if user_id in matched_users:
        matched_users[user_id] = set()
    
    await update.message.reply_text("🎯 Полный сброс выполнен! Все анкеты будут показаны заново.")

# --- КОМАНДА ДЛЯ ПОЛУЧЕНИЯ ID ---
async def get_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает пользователю его ID"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return
        
    await update.message.reply_text(f"Ваш ID: `{user_id}`", parse_mode='Markdown')

# --- АДМИН ПАНЕЛЬ ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Панель администратора"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("У вас нет доступа к этой функции.")
        return MENU
    
    keyboard = [
        [KeyboardButton("📊 Статистика"), KeyboardButton("🛠️ Техобслуживание")],
        [KeyboardButton("🔨 Управление банами"), KeyboardButton("👥 Управление пользователями")],
        [KeyboardButton("⬅️ Главное меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    maintenance_status = db.get_maintenance_status()
    status_text = "🟢 Активен" if not maintenance_status['maintenance_mode'] else "🟡 Техобслуживание"
    
    banned_count = len(db.get_banned_users())
    
    await update.message.reply_text(
        f"⚙️ **Панель администратора**\n"
        f"Статус бота: {status_text}\n"
        f"Забанено пользователей: {banned_count}\n\n"
        f"Выберите действие:",
        reply_markup=reply_markup
    )
    return ADMIN_PANEL

# --- СТАТИСТИКА ДЛЯ АДМИНОВ ---
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Расширенная статистика для админов"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("У вас нет доступа к этой функции.")
        return MENU
    
    # Подключаемся к БД для более точной статистики
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Базовая статистика
    total_profiles = len(user_profiles)
    complete_profiles = len([uid for uid in user_profiles if is_profile_complete(uid)])
    total_likes = sum(len(likes) for likes in user_likes.values())
    total_matches = sum(len(matches) for matches in matched_users.values()) // 2
    banned_count = len(db.get_banned_users())
    
    # Статистика по полу
    cursor.execute('SELECT gender, COUNT(*) FROM users GROUP BY gender')
    gender_stats = cursor.fetchall()
    
    # Статистика по возрасту
    cursor.execute('SELECT age, COUNT(*) FROM users GROUP BY age ORDER BY age')
    age_stats = cursor.fetchall()
    
    # Статистика по курсу
    cursor.execute('SELECT city, COUNT(*) FROM users GROUP BY city ORDER BY city')
    course_stats = cursor.fetchall()
    
    # Новые пользователи за последние 7 дней
    cursor.execute('SELECT COUNT(*) FROM users WHERE created_at >= datetime("now", "-7 days")')
    new_users_week = cursor.fetchone()[0]
    
    # Активность за последние 24 часа
    cursor.execute('SELECT COUNT(*) FROM users WHERE last_active >= datetime("now", "-1 day")')
    active_users_day = cursor.fetchone()[0]
    
    conn.close()
    
    stats_text = (
        f"📊 **Расширенная статистика бота:**\n\n"
        f"**Основные метрики:**\n"
        f"• Всего пользователей: {total_profiles}\n"
        f"• Заполненных анкет: {complete_profiles}\n"
        f"• Всего лайков: {total_likes}\n"
        f"• Совпадений: {total_matches}\n"
        f"• Забанено: {banned_count}\n"
        f"• Новых за неделю: {new_users_week}\n"
        f"• Активных за сутки: {active_users_day}\n\n"
    )
    
    if gender_stats:
        stats_text += "**Распределение по полу:**\n"
        for gender, count in gender_stats:
            stats_text += f"• {gender}: {count}\n"
    
    if age_stats:
        stats_text += "\n**Распределение по возрасту:**\n"
        for age, count in age_stats:
            stats_text += f"• {age} лет: {count}\n"
    
    if course_stats:
        stats_text += "\n**Распределение по курсу:**\n"
        for course, count in course_stats:
            stats_text += f"• {course} курс: {count}\n"
    
    await update.message.reply_text(stats_text)
    return ADMIN_PANEL

# --- УПРАВЛЕНИЕ ТЕХОБСЛУЖИВАНИЕМ ---
async def maintenance_management(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Управление техобслуживанием"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("У вас нет доступа к этой функции.")
        return MENU
    
    maintenance_status = db.get_maintenance_status()
    
    if maintenance_status['maintenance_mode']:
        keyboard = [
            [KeyboardButton("🟢 Выключить техобслуживание")],
            [KeyboardButton("✏️ Изменить сообщение")],
            [KeyboardButton("⬅️ Назад в админку")]
        ]
        status_text = "🟡 ВКЛЮЧЕНО"
        message_text = maintenance_status['maintenance_message'] or "Сообщение не установлено"
    else:
        keyboard = [
            [KeyboardButton("🔴 Включить техобслуживание")],
            [KeyboardButton("⬅️ Назад в админку")]
        ]
        status_text = "🟢 ВЫКЛЮЧЕНО"
        message_text = "Не активно"
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"🛠️ **Управление техобслуживанием**\n\n"
        f"Статус: {status_text}\n"
        f"Сообщение: {message_text}\n\n"
        f"Выберите действие:",
        reply_markup=reply_markup
    )
    return ADMIN_PANEL

async def toggle_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Включение/выключение техобслуживания"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("У вас нет доступа к этой функции.")
        return MENU
    
    maintenance_status = db.get_maintenance_status()
    
    if maintenance_status['maintenance_mode']:
        # Выключаем техобслуживание
        db.set_maintenance_mode(False)
        await update.message.reply_text("🟢 Техобслуживание выключено! Бот снова активен.")
    else:
        # Включаем техобслуживание
        db.set_maintenance_mode(True, "⚙️ Бот находится на техническом обслуживании. Пожалуйста, попробуйте позже.")
        await update.message.reply_text("🔴 Техобслуживание включено! Бот временно недоступен для пользователей.")
    
    return await maintenance_management(update, context)

async def set_maintenance_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка сообщения для техобслуживания"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("У вас нет доступа к этой функции.")
        return MENU
    
    await update.message.reply_text(
        "Введите сообщение, которое будут видеть пользователи во время техобслуживания:",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("⬅️ Отмена")]], resize_keyboard=True)
    )
    context.user_data['waiting_for_maintenance_message'] = True
    return ADMIN_PANEL

async def save_maintenance_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохранение сообщения техобслуживания"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("У вас нет доступа к этой функции.")
        return MENU
    
    message = update.message.text
    db.set_maintenance_mode(True, message)
    
    await update.message.reply_text("✅ Сообщение техобслуживания обновлено!")
    return await maintenance_management(update, context)

# --- УПРАВЛЕНИЕ БАНАМИ ---
async def ban_management(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Управление банами"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("У вас нет доступа к этой функции.")
        return ADMIN_PANEL
    
    banned_users = db.get_banned_users()
    
    keyboard = [
        [KeyboardButton("🔨 Забанить пользователя")],
        [KeyboardButton("🔓 Разбанить пользователя")],
        [KeyboardButton("📋 Список банов")],
        [KeyboardButton("⬅️ Назад в админку")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    ban_count = len(banned_users)
    
    await update.message.reply_text(
        f"🔨 **Управление банами**\n\n"
        f"Забанено пользователей: {ban_count}\n\n"
        f"Выберите действие:",
        reply_markup=reply_markup
    )
    return BAN_MANAGEMENT

async def show_banned_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает список забаненных пользователей"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("У вас нет доступа к этой функции.")
        return ADMIN_PANEL
    
    banned_users = db.get_banned_users()
    
    if not banned_users:
        await update.message.reply_text("🚫 Нет забаненных пользователей.")
        return await ban_management(update, context)
    
    ban_list = "📋 **Список забаненных пользователей:**\n\n"
    
    for i, (banned_id, username, reason, banned_at) in enumerate(banned_users, 1):
        user_info = db.get_user_info(banned_id)
        name = user_info[3] if user_info else "Неизвестно"
        ban_list += f"{i}. ID: {banned_id}\n"
        ban_list += f"   Имя: {name}\n"
        ban_list += f"   Юзернейм: @{username if username else 'нет'}\n"
        ban_list += f"   Причина: {reason or 'Не указана'}\n"
        ban_list += f"   Забанен: {banned_at[:16]}\n\n"
    
    await update.message.reply_text(ban_list)
    return BAN_MANAGEMENT

async def ban_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает процесс бана пользователя"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("У вас нет доступа к этой функции.")
        return ADMIN_PANEL
    
    await update.message.reply_text(
        "Введите ID пользователя для бана:\n\n"
        "Чтобы узнать ID пользователя, попросите его отправить команду /id",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("⬅️ Отмена")]], resize_keyboard=True)
    )
    context.user_data['waiting_for_ban_user_id'] = True
    return BAN_MANAGEMENT

async def ban_user_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запрашивает причину бана"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("У вас нет доступа к этой функции.")
        return ADMIN_PANEL
    
    try:
        target_user_id = int(update.message.text)
        
        # Проверяем, существует ли пользователь
        target_user = db.get_user_info(target_user_id)
        if not target_user:
            await update.message.reply_text("❌ Пользователь с таким ID не найден.")
            return await ban_management(update, context)
        
        # Проверяем, не забанен ли уже
        if db.is_user_banned(target_user_id):
            await update.message.reply_text("❌ Этот пользователь уже забанен.")
            return await ban_management(update, context)
        
        # Проверяем, не админ ли
        if target_user_id in ADMIN_USER_IDS:
            await update.message.reply_text("❌ Нельзя забанить администратора.")
            return await ban_management(update, context)
        
        context.user_data['ban_target_id'] = target_user_id
        context.user_data['ban_target_username'] = target_user[1]  # username из БД
        
        await update.message.reply_text(
            f"Пользователь: {target_user[3]} (@{target_user[1]})\n"
            f"ID: {target_user_id}\n\n"
            "Введите причину бана:",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("⬅️ Отмена")]], resize_keyboard=True)
        )
        context.user_data['waiting_for_ban_reason'] = True
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Введите числовой ID.")
        return await ban_management(update, context)
    
    return BAN_MANAGEMENT

async def confirm_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждает и выполняет бан"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("У вас нет доступа к этой функции.")
        return ADMIN_PANEL
    
    target_user_id = context.user_data.get('ban_target_id')
    target_username = context.user_data.get('ban_target_username')
    reason = update.message.text
    
    if not target_user_id:
        await update.message.reply_text("❌ Ошибка: не найден ID пользователя для бана.")
        return await ban_management(update, context)
    
    # Выполняем бан
    db.ban_user(target_user_id, target_username, reason, user_id)
    
    # Очищаем временные данные
    context.user_data.pop('ban_target_id', None)
    context.user_data.pop('ban_target_username', None)
    context.user_data.pop('waiting_for_ban_user_id', None)
    context.user_data.pop('waiting_for_ban_reason', None)
    
    target_user_info = db.get_user_info(target_user_id)
    target_name = target_user_info[3] if target_user_info else "Неизвестно"
    
    await update.message.reply_text(
        f"✅ Пользователь {target_name} (@{target_username}) забанен!\n"
        f"Причина: {reason}"
    )
    
    # Отправляем уведомление забаненному пользователю (если он активен)
    try:
        ban_message = f"🚫 Вы были забанены администратором.\n\nПричина: {reason}\n\nДля разбирательства обратитесь к администратору."
        await context.bot.send_message(chat_id=target_user_id, text=ban_message)
    except Exception as e:
        logger.warning(f"Не удалось отправить уведомление о бане пользователю {target_user_id}: {e}")
    
    return await ban_management(update, context)

async def unban_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает процесс разбана пользователя"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("У вас нет доступа к этой функции.")
        return ADMIN_PANEL
    
    banned_users = db.get_banned_users()
    
    if not banned_users:
        await update.message.reply_text("🚫 Нет забаненных пользователей для разбана.")
        return await ban_management(update, context)
    
    keyboard = []
    for banned_id, username, reason, banned_at in banned_users:
        user_info = db.get_user_info(banned_id)
        name = user_info[3] if user_info else "Неизвестно"
        button_text = f"🔓 {name} (ID: {banned_id})"
        keyboard.append([KeyboardButton(button_text)])
    
    keyboard.append([KeyboardButton("⬅️ Отмена")])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "Выберите пользователя для разбана:",
        reply_markup=reply_markup
    )
    context.user_data['waiting_for_unban'] = True
    
    return BAN_MANAGEMENT

async def execute_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выполняет разбан пользователя"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("У вас нет доступа к этой функции.")
        return ADMIN_PANEL
    
    button_text = update.message.text
    
    # Извлекаем ID из текста кнопки
    try:
        target_user_id = int(button_text.split("ID: ")[1].split(")")[0])
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Ошибка при обработке выбора.")
        return await ban_management(update, context)
    
    # Выполняем разбан
    db.unban_user(target_user_id)
    
    target_user_info = db.get_user_info(target_user_id)
    target_name = target_user_info[3] if target_user_info else "Неизвестно"
    target_username = target_user_info[1] if target_user_info else "Неизвестно"
    
    await update.message.reply_text(
        f"✅ Пользователь {target_name} (@{target_username}) разбанен!"
    )
    
    # Отправляем уведомление разбаненному пользователю
    try:
        unban_message = "🎉 Вы были разбанены! Теперь вы снова можете пользоваться ботом."
        await context.bot.send_message(chat_id=target_user_id, text=unban_message)
    except Exception as e:
        logger.warning(f"Не удалось отправить уведомление о разбане пользователю {target_user_id}: {e}")
    
    context.user_data.pop('waiting_for_unban', None)
    return await ban_management(update, context)

# --- ОСНОВНЫЕ ФУНКЦИИ БОТА ---
def is_profile_complete(user_id):
    profile = user_profiles.get(user_id)
    return (
        profile
        and profile.get("gender")
        and profile.get("name")
        and profile.get("age")
        and profile.get("city")
        and profile.get("bio")
        and profile.get("photo")
        and profile.get("username")
    )

async def send_profile_card(user_id: int, target_user_id: int, context: ContextTypes.DEFAULT_TYPE, reply_markup=None):
    profile = user_profiles.get(target_user_id)
    if not profile:
        logger.error(f"Profile not found for user ID: {target_user_id}")
        return

    bio_text = profile.get("bio", "Нет информации")
    message_text = (
        f"Имя: {profile['name']}\n"
        f"Возраст: {profile['age']}\n"
        f"Курс: {profile['city']}\n"
        f"О себе: {bio_text}"
    )

    if profile.get("photo"):
        try:
            await context.bot.send_photo(
                chat_id=user_id,
                photo=profile["photo"],
                caption=message_text,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Failed to send photo to {user_id}: {e}")
            await context.bot.send_message(
                chat_id=user_id,
                text=message_text + "\n(Не удалось загрузить фото)",
                reply_markup=reply_markup
            )
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text=message_text + "\n(Фото отсутствует)",
            reply_markup=reply_markup
        )

# --- ИСПРАВЛЕННАЯ ФУНКЦИЯ START ---
@auto_save
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation and asks the user about their gender."""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    # Проверяем техобслуживание (админы пропускаются)
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    # Store username early
    if user_id not in user_profiles:
        user_profiles[user_id] = {}
    user_profiles[user_id]["username"] = update.effective_user.username
    # Сохраняем в БД
    db.save_user(user_id, user_profiles[user_id])

    if is_profile_complete(user_id):
        keyboard = [
            [KeyboardButton("Поиск")],
            [KeyboardButton("Настройки")],
        ]
        
        if user_id in ADMIN_USER_IDS:
            keyboard.append([KeyboardButton("⚙️ Админка")])
            
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "Привет! Твой профиль уже заполнен. Что хочешь сделать?",
            reply_markup=reply_markup,
        )
        return MENU
    else:
        keyboard = [["Мужской"], ["Женский"], ["Другое"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

        await update.message.reply_text(
            "Привет! Давай создадим твой профиль. Сначала укажи свой пол:",
            reply_markup=reply_markup,
        )

        return GENDER

@auto_save
async def gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the gender and asks for the name."""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    context.user_data["gender"] = update.message.text
    if user_id not in user_profiles:
        user_profiles[user_id] = {}
    user_profiles[user_id]["gender"] = update.message.text
    if "username" not in user_profiles[user_id]:
        user_profiles[user_id]["username"] = update.effective_user.username
    
    # Сохраняем в БД
    db.save_user(user_id, user_profiles[user_id])

    await update.message.reply_text(
        "Отлично! Теперь укажи свое имя:", reply_markup=ReplyKeyboardRemove()
    )
    return NAME

@auto_save
async def name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the name and asks for the age."""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    context.user_data["name"] = update.message.text
    user_profiles[user_id]["name"] = update.message.text
    db.save_user(user_id, user_profiles[user_id])

    await update.message.reply_text("Сколько тебе лет? (от 16 до 25)")
    return AGE

@auto_save
async def age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the age and asks for the city."""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    try:
        age = int(update.message.text)
        if age < 16 or age > 25:
            await update.message.reply_text(
                "Пожалуйста, укажите реальный возраст (16-25):"
            )
            return AGE
        context.user_data["age"] = age
        user_profiles[user_id]["age"] = age
        db.save_user(user_id, user_profiles[user_id])

        await update.message.reply_text("Укажите свой курс (от 1 до 5):")
        return CITY
    except ValueError:
        await update.message.reply_text("Пожалуйста, укажите возраст цифрами.")
        return AGE

@auto_save
async def city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the city (course) and asks for the bio."""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    try:
        course = int(update.message.text)
        if course < 1 or course > 5:
            await update.message.reply_text(
                "Пожалуйста, укажите реальный курс (1-5):"
            )
            return CITY
        context.user_data["city"] = course
        user_profiles[user_id]["city"] = course
        db.save_user(user_id, user_profiles[user_id])

        await update.message.reply_text("Расскажи немного о себе (интересы, хобби и т.д.):")
        return BIO
    except ValueError:
        await update.message.reply_text("Пожалуйста, укажите курс цифрами (1-5).")
        return CITY

@auto_save
async def bio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the bio and asks for a photo."""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    context.user_data["bio"] = update.message.text
    user_profiles[user_id]["bio"] = update.message.text
    db.save_user(user_id, user_profiles[user_id])

    await update.message.reply_text("Теперь отправь свою лучшую фотографию:")
    return PHOTO

@auto_save
async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the photo and asks for confirmation."""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        context.user_data["photo"] = photo_file_id
        user_profiles[user_id]["photo"] = photo_file_id
        db.save_user(user_id, user_profiles[user_id])

        profile = user_profiles[user_id]
        bio_text = profile.get("bio", "Нет информации")
        message_text = (
            f"Вот твой профиль:\n"
            f"Пол: {profile['gender']}\n"
            f"Имя: {profile['name']}\n"
            f"Возраст: {profile['age']}\n"
            f"Курс: {profile['city']}\n"
            f"О себе: {bio_text}"
        )

        keyboard = [
            [KeyboardButton("Да, все верно"), KeyboardButton("Изменить")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

        await context.bot.send_photo(
            chat_id=user_id,
            photo=photo_file_id,
            caption=message_text,
            reply_markup=reply_markup
        )
        return CONFIRMATION
    else:
        await update.message.reply_text("Пожалуйста, отправь фотографию.")
        return PHOTO

@auto_save
async def confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Confirms the profile or allows editing."""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    if update.message.text == "Да, все верно":
        keyboard = [
            [KeyboardButton("Поиск")],
            [KeyboardButton("Настройки")],
        ]
        
        if user_id in ADMIN_USER_IDS:
            keyboard.append([KeyboardButton("⚙️ Админка")])
            
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "Твой профиль успешно создан! Теперь ты можешь начать поиск.",
            reply_markup=reply_markup,
        )
        return MENU
    elif update.message.text == "Изменить":
        return await settings(update, context)
    else:
        await update.message.reply_text("Пожалуйста, выбери 'Да, все верно' или 'Изменить'.")
        return CONFIRMATION

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Main menu for the user."""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    text = update.message.text
    
    keyboard = [
        [KeyboardButton("Поиск")],
        [KeyboardButton("Настройки")],
    ]
    
    if user_id in ADMIN_USER_IDS:
        keyboard.append([KeyboardButton("⚙️ Админка")])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    if text == "Поиск":
        return await search_profile(update, context)
    elif text == "Настройки":
        return await settings(update, context)
    elif text == "⚙️ Админка" and user_id in ADMIN_USER_IDS:
        return await admin_panel(update, context)
    else:
        await update.message.reply_text("Пожалуйста, выберите действие:", reply_markup=reply_markup)
        return MENU

# --- ФУНКЦИИ РЕДАКТИРОВАНИЯ ПРОФИЛЯ ---
async def edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Allows user to choose what to edit."""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    keyboard = [
        [KeyboardButton("Пол"), KeyboardButton("Имя"), KeyboardButton("Возраст")],
        [KeyboardButton("Курс"), KeyboardButton("О себе"), KeyboardButton("Фото")],
        [KeyboardButton("Готово")],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Что вы хотите изменить?", reply_markup=reply_markup)
    return EDIT_PROFILE

@auto_save
async def edit_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало редактирования пола"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    keyboard = [["Мужской"], ["Женский"], ["Другое"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("Укажите новый пол:", reply_markup=reply_markup)
    return EDIT_GENDER

@auto_save
async def save_edit_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохранение отредактированного пола"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    user_profiles[user_id]["gender"] = update.message.text
    db.save_user(user_id, user_profiles[user_id])
    await update.message.reply_text("Пол обновлен.")
    return await edit_profile(update, context)

@auto_save
async def edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало редактирования имени"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    await update.message.reply_text("Укажите новое имя:")
    return EDIT_NAME

@auto_save
async def save_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохранение отредактированного имени"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    user_profiles[user_id]["name"] = update.message.text
    db.save_user(user_id, user_profiles[user_id])
    await update.message.reply_text("Имя обновлено.")
    return await edit_profile(update, context)

@auto_save
async def edit_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало редактирования возраста"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    await update.message.reply_text("Укажите новый возраст (от 16 до 25):")
    return EDIT_AGE

@auto_save
async def save_edit_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохранение отредактированного возраста"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    try:
        age = int(update.message.text)
        if age < 16 or age > 25:
            await update.message.reply_text("Пожалуйста, укажите реальный возраст (16-25):")
            return EDIT_AGE
        user_profiles[user_id]["age"] = age
        db.save_user(user_id, user_profiles[user_id])
        await update.message.reply_text("Возраст обновлен.")
        return await edit_profile(update, context)
    except ValueError:
        await update.message.reply_text("Пожалуйста, укажите возраст цифрами.")
        return EDIT_AGE

@auto_save
async def edit_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало редактирования курса"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    await update.message.reply_text("Укажите новый курс (от 1 до 5):")
    return EDIT_CITY

@auto_save
async def save_edit_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохранение отредактированного курса"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    try:
        course = int(update.message.text)
        if course < 1 or course > 5:
            await update.message.reply_text("Пожалуйста, укажите реальный курс (1-5):")
            return EDIT_CITY
        user_profiles[user_id]["city"] = course
        db.save_user(user_id, user_profiles[user_id])
        await update.message.reply_text("Курс обновлен.")
        return await edit_profile(update, context)
    except ValueError:
        await update.message.reply_text("Пожалуйста, укажите курс цифрами (1-5).")
        return EDIT_CITY

@auto_save
async def edit_bio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало редактирования описания"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    await update.message.reply_text("Напишите новое описание о себе:")
    return EDIT_BIO

@auto_save
async def save_edit_bio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохранение отредактированного описания"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    user_profiles[user_id]["bio"] = update.message.text
    db.save_user(user_id, user_profiles[user_id])
    await update.message.reply_text("Описание обновлено.")
    return await edit_profile(update, context)

@auto_save
async def edit_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало редактирования фото"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    await update.message.reply_text("Отправьте новую фотографию:")
    return EDIT_PHOTO

@auto_save
async def save_edit_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохранение отредактированного фото"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        user_profiles[user_id]["photo"] = photo_file_id
        db.save_user(user_id, user_profiles[user_id])
        await update.message.reply_text("Фотография обновлена.")
        return await edit_profile(update, context)
    else:
        await update.message.reply_text("Пожалуйста, отправьте фотографию.")
        return EDIT_PHOTO

async def done_editing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Завершение редактирования профиля"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    await update.message.reply_text("Изменения сохранены.", reply_markup=ReplyKeyboardRemove())
    return await settings(update, context)

async def show_my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает профиль пользователя"""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    if not is_profile_complete(user_id):
        await update.message.reply_text("Ваш профиль еще не заполнен.")
        return MENU

    profile = user_profiles[user_id]
    bio_text = profile.get("bio", "Нет информации")
    message_text = (
        f"Твой профиль:\n"
        f"Пол: {profile['gender']}\n"
        f"Имя: {profile['name']}\n"
        f"Возраст: {profile['age']}\n"
        f"Курс: {profile['city']}\n"
        f"О себе: {bio_text}"
    )

    keyboard = [
        [KeyboardButton("Редактировать профиль")],
        [KeyboardButton("⬅️ Меню")],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    if profile.get("photo"):
        await context.bot.send_photo(
            chat_id=user_id,
            photo=profile["photo"],
            caption=message_text,
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            message_text + "\n(Фото отсутствует)",
            reply_markup=reply_markup
        )
    return SETTINGS

# --- ОБНОВЛЕННАЯ ФУНКЦИЯ: Поиск следующей анкеты ---
async def search_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    user_data = context.user_data
    
    clear_old_viewed_profiles(user_data)
    
    if 'viewed_profiles' not in user_data:
        user_data['viewed_profiles'] = []
    
    viewed_profiles = user_data['viewed_profiles']
    available_profiles = []

    for profile_id, profile_data in user_profiles.items():
        if profile_id == user_id:
            continue
        if profile_id in user_likes.get(user_id, set()):
            continue
        if profile_id in user_dislikes.get(user_id, set()):
            continue
        if profile_id in matched_users.get(user_id, set()):
            continue
        if not is_profile_complete(profile_id):
            continue
        # Пропускаем забаненных пользователей
        if db.is_user_banned(profile_id):
            continue

        available_profiles.append(profile_id)

    if not available_profiles:
        user_data['viewed_profiles'] = []
        available_profiles = [pid for pid in user_profiles.keys() 
                            if pid != user_id 
                            and is_profile_complete(pid)
                            and pid not in user_likes.get(user_id, set())
                            and pid not in user_dislikes.get(user_id, set())
                            and pid not in matched_users.get(user_id, set())
                            and not db.is_user_banned(pid)]  # Исключаем забаненных
        
        if not available_profiles:
            keyboard = [
                [KeyboardButton("Поиск")],
                [KeyboardButton("Настройки")],
            ]
            if user_id in ADMIN_USER_IDS:
                keyboard.append([KeyboardButton("⚙️ Админка")])
                
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text("Пока что больше нет анкет. Попробуйте позже!",
                                            reply_markup=reply_markup)
            return MENU

    next_profile_id = random.choice(available_profiles)
    context.user_data['current_viewing_profile_id'] = next_profile_id

    keyboard = [
        [KeyboardButton("❤️ Лайк"), KeyboardButton("❌ Дизлайк")],
        [KeyboardButton("⬅️ Меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await send_profile_card(user_id, next_profile_id, context, reply_markup)
    return SEARCH

# --- Notification functions ---
@auto_save
async def notify_liked_user(liker_id: int, liked_id: int, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем бан для уведомлений
    if await check_maintenance_for_user(liked_id) or db.is_user_banned(liked_id):
        return
        
    liker_profile = user_profiles.get(liker_id)
    if not liker_profile:
        logger.error(f"Liker profile not found for ID: {liker_id}")
        return

    keyboard = [
        [InlineKeyboardButton("❤️ Лайкнуть в ответ", callback_data=f"like_back_{liker_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"dislike_back_{liker_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=liked_id,
        text="Тебя лайкнули! Вот чья анкета:",
        reply_markup=ReplyKeyboardRemove()
    )
    await send_profile_card(liked_id, liker_id, context, reply_markup)

@auto_save
async def notify_match(user1_id: int, user2_id: int, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем бан для уведомлений
    if (await check_maintenance_for_user(user1_id) or db.is_user_banned(user1_id) or
        await check_maintenance_for_user(user2_id) or db.is_user_banned(user2_id)):
        return
        
    user1_profile = user_profiles.get(user1_id)
    user2_profile = user_profiles.get(user2_id)

    if not user1_profile or not user2_profile:
        logger.error(f"One of the matched profiles not found: {user1_id}, {user2_id}")
        return

    user1_username = user1_profile.get('username', 'Неизвестный пользователь')
    user2_username = user2_profile.get('username', 'Неизвестный пользователь')

    match_message_for_user1 = (
        f"🎉 У тебя совпадение с {user2_profile['name']}! "
        f"Его/её Telegram: @{user2_username}"
    )
    match_message_for_user2 = (
        f"🎉 У тебя совпадение с {user1_profile['name']}! "
        f"Его/её Telegram: @{user1_username}"
    )

    await context.bot.send_message(chat_id=user1_id, text=match_message_for_user1)
    await context.bot.send_message(chat_id=user2_id, text=match_message_for_user2)

    if user1_id not in matched_users:
        matched_users[user1_id] = set()
    matched_users[user1_id].add(user2_id)

    if user2_id not in matched_users:
        matched_users[user2_id] = set()
    matched_users[user2_id].add(user1_id)
    
    # Сохраняем в БД
    db.add_match(user1_id, user2_id)

@auto_save
async def like(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User likes the current profile."""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    liker_id = update.message.from_user.id
    liked_id = context.user_data.get('current_viewing_profile_id')
    user_data = context.user_data

    if not liked_id:
        keyboard = [
            [KeyboardButton("Поиск")],
            [KeyboardButton("Настройки")],
        ]
        if liker_id in ADMIN_USER_IDS:
            keyboard.append([KeyboardButton("⚙️ Админка")])
            
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text("Что-то пошло не так. Попробуйте снова начать поиск.",
                                        reply_markup=reply_markup)
        return MENU

    if liker_id not in user_likes:
        user_likes[liker_id] = set()
    user_likes[liker_id].add(liked_id)
    
    # Сохраняем в БД
    db.add_like(liker_id, liked_id)

    if 'viewed_profiles' not in user_data:
        user_data['viewed_profiles'] = []
    if liked_id not in user_data['viewed_profiles']:
        user_data['viewed_profiles'].append(liked_id)

    clear_old_viewed_profiles(user_data)

    if liked_id in user_likes and liker_id in user_likes[liked_id]:
        await notify_match(liker_id, liked_id, context)
        await update.message.reply_text("УРА! Это совпадение! 🎉")
        return await search_profile(update, context)
    else:
        await notify_liked_user(liker_id, liked_id, context)
        await update.message.reply_text("Лайк отправлен! Продолжаем поиск...")
        return await search_profile(update, context)

@auto_save
async def dislike(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User dislikes the current profile."""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    disliker_id = update.message.from_user.id
    disliked_id = context.user_data.get('current_viewing_profile_id')
    user_data = context.user_data

    if not disliked_id:
        keyboard = [
            [KeyboardButton("Поиск")],
            [KeyboardButton("Настройки")],
        ]
        if disliker_id in ADMIN_USER_IDS:
            keyboard.append([KeyboardButton("⚙️ Админка")])
            
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text("Что-то пошло не так. Попробуйте снова начать поиск.",
                                        reply_markup=reply_markup)
        return MENU

    if disliker_id not in user_dislikes:
        user_dislikes[disliker_id] = set()
    user_dislikes[disliker_id].add(disliked_id)

    if 'viewed_profiles' not in user_data:
        user_data['viewed_profiles'] = []
    if disliked_id not in user_data['viewed_profiles']:
        user_data['viewed_profiles'].append(disliked_id)

    clear_old_viewed_profiles(user_data)

    await update.message.reply_text("Анкета пропущена. Продолжаем поиск...")
    return await search_profile(update, context)

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Shows settings options."""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    keyboard = [
        [KeyboardButton("Редактировать профиль")],
        [KeyboardButton("Мой профиль")],
        [KeyboardButton("Очистить историю")],
        [KeyboardButton("⬅️ Меню")],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Настройки:", reply_markup=reply_markup)
    return SETTINGS

# --- CallbackQueryHandler for InlineKeyboardButtons ---
@auto_save
async def handle_match_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    liked_id = query.from_user.id
    
    # Проверяем бан для callback
    if await check_maintenance_for_user(liked_id) or db.is_user_banned(liked_id):
        await query.edit_message_text("⚙️ Бот находится на техническом обслуживании. Пожалуйста, попробуйте позже.")
        return

    callback_data = query.data
    
    if callback_data.startswith("like_back_"):
        liker_id_str = callback_data.replace("like_back_", "")
        action = "like_back"
    elif callback_data.startswith("dislike_back_"):
        liker_id_str = callback_data.replace("dislike_back_", "")
        action = "dislike_back"
    else:
        logger.error(f"Unknown callback data: {callback_data}")
        return

    try:
        liker_id = int(liker_id_str)
    except ValueError:
        logger.error(f"Invalid liker_id in callback data: {liker_id_str}")
        return

    try:
        if action == "like_back":
            if liked_id not in user_likes:
                user_likes[liked_id] = set()
            user_likes[liked_id].add(liker_id)
            
            # Сохраняем в БД
            db.add_like(liked_id, liker_id)

            await notify_match(liker_id, liked_id, context)
            try:
                await query.edit_message_text(text="УРА! Это совпадение! 🎉")
            except Exception as e:
                logger.warning(f"Could not edit message, sending new one: {e}")
                await context.bot.send_message(
                    chat_id=liked_id,
                    text="УРА! Это совпадение! 🎉"
                )
        elif action == "dislike_back":
            if liked_id not in user_dislikes:
                user_dislikes[liked_id] = set()
            user_dislikes[liked_id].add(liker_id)
            
            try:
                await query.edit_message_text(text="Анкета отклонена.")
            except Exception as e:
                logger.warning(f"Could not edit message, sending new one: {e}")
                await context.bot.send_message(
                    chat_id=liked_id,
                    text="Анкета отклонена."
                )

    except Exception as e:
        logger.error(f"Error in handle_match_response: {e}")
        await context.bot.send_message(
            chat_id=liked_id,
            text="Произошла ошибка при обработке вашего ответа."
        )

    user_id = liked_id
    keyboard = [
        [KeyboardButton("Поиск")],
        [KeyboardButton("Настройки")],
    ]
    if user_id in ADMIN_USER_IDS:
        keyboard.append([KeyboardButton("⚙️ Админка")])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    try:
        await context.bot.send_message(
            chat_id=liked_id,
            text="Что дальше?",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error sending menu message: {e}")

async def back_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Возврат в админ панель"""
    return await admin_panel(update, context)

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Returns to the main menu."""
    user_id = update.effective_user.id
    
    # Проверяем бан
    if await check_ban(update, context, user_id):
        return ConversationHandler.END
        
    if await check_maintenance(update, context, user_id):
        return ConversationHandler.END
        
    keyboard = [
        [KeyboardButton("Поиск")],
        [KeyboardButton("Настройки")],
    ]
    
    if user_id in ADMIN_USER_IDS:
        keyboard.append([KeyboardButton("⚙️ Админка")])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Возвращаемся в меню.", reply_markup=reply_markup)
    return MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the current conversation."""
    user = update.message.from_user
    logger.info("User %s canceled the conversation.", user.first_name)
    await update.message.reply_text(
        "До свидания! Надеюсь, мы еще пообщаемся.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

def main() -> None:
    """Run the bot."""
    # Загружаем данные при старте
    load_data()
    startup_notice()
    setup_data_persistence()
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not token:
        token = "8284692267:AAFw8z70NazDrTdLq53iaBC-KCz1cnT35NM"
        logger.warning("Using hardcoded token. For production, set TELEGRAM_BOT_TOKEN environment variable.")
    
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set.")
        exit(1)

    application = Application.builder().token(token).build()

    # Add conversation handler with states
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, gender)],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, age)],
            CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, city)],
            BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, bio)],
            PHOTO: [MessageHandler(filters.PHOTO, photo)],
            CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirmation)],
            MENU: [
                MessageHandler(filters.Regex("^Поиск$"), search_profile),
                MessageHandler(filters.Regex("^Настройки$"), settings),
                MessageHandler(filters.Regex("^⚙️ Админка$"), admin_panel),
            ],
            SEARCH: [
                MessageHandler(filters.Regex("^❤️ Лайк$"), like),
                MessageHandler(filters.Regex("^❌ Дизлайк$"), dislike),
                MessageHandler(filters.Regex("^⬅️ Меню$"), back_to_menu),
            ],
            SETTINGS: [
                MessageHandler(filters.Regex("^Редактировать профиль$"), edit_profile),
                MessageHandler(filters.Regex("^Мой профиль$"), show_my_profile),
                MessageHandler(filters.Regex("^Очистить историю$"), clear_history_handler),
                MessageHandler(filters.Regex("^⬅️ Меню$"), back_to_menu),
            ],
            EDIT_PROFILE: [
                MessageHandler(filters.Regex("^Пол$"), edit_gender),
                MessageHandler(filters.Regex("^Имя$"), edit_name),
                MessageHandler(filters.Regex("^Возраст$"), edit_age),
                MessageHandler(filters.Regex("^Курс$"), edit_city),
                MessageHandler(filters.Regex("^О себе$"), edit_bio),
                MessageHandler(filters.Regex("^Фото$"), edit_photo),
                MessageHandler(filters.Regex("^Готово$"), done_editing),
            ],
            EDIT_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit_gender)],
            EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit_name)],
            EDIT_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit_age)],
            EDIT_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit_city)],
            EDIT_BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit_bio)],
            EDIT_PHOTO: [MessageHandler(filters.PHOTO, save_edit_photo)],
            ADMIN_PANEL: [
                MessageHandler(filters.Regex("^📊 Статистика$"), admin_stats),
                MessageHandler(filters.Regex("^🛠️ Техобслуживание$"), maintenance_management),
                MessageHandler(filters.Regex("^🔨 Управление банами$"), ban_management),
                MessageHandler(filters.Regex("^🟢 Выключить техобслуживание$"), toggle_maintenance),
                MessageHandler(filters.Regex("^🔴 Включить техобслуживание$"), toggle_maintenance),
                MessageHandler(filters.Regex("^✏️ Изменить сообщение$"), set_maintenance_message),
                MessageHandler(filters.Regex("^⬅️ Главное меню$"), back_to_menu),
                MessageHandler(filters.Regex("^⬅️ Назад в админку$"), back_to_admin),
                MessageHandler(filters.Regex("^⬅️ Отмена$"), back_to_admin),
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_maintenance_message),
            ],
            BAN_MANAGEMENT: [
                MessageHandler(filters.Regex("^🔨 Забанить пользователя$"), ban_user_handler),
                MessageHandler(filters.Regex("^🔓 Разбанить пользователя$"), unban_user_handler),
                MessageHandler(filters.Regex("^📋 Список банов$"), show_banned_users),
                MessageHandler(filters.Regex("^⬅️ Назад в админку$"), back_to_admin),
                MessageHandler(filters.Regex("^⬅️ Отмена$"), back_to_admin),
                MessageHandler(filters.Regex("^🔓 .*"), execute_unban),  # Для кнопок разбана
                MessageHandler(filters.TEXT & ~filters.COMMAND, ban_user_reason),  # Обработка ID и причин
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL, back_to_menu)],
    )

    # 🔥 ВАЖНО: Добавляем ОТДЕЛЬНЫЙ обработчик для кнопки "Проверить статус" ВНЕ ConversationHandler
    application.add_handler(MessageHandler(filters.Regex("^🔄 Проверить статус$"), check_status_handler))
    
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(handle_match_response))

    # Команды для админов
    application.add_handler(CommandHandler("clear", clear_history_handler))
    application.add_handler(CommandHandler("reset", reset_all_handler))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("id", get_user_id))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
