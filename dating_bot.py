import asyncio
import logging
import os
import random
import time
import json
import pickle
import signal
import atexit

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

# Файл для сохранения данных
DATA_FILE = "bot_data.pkl"

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
    END
) = range(21)

# Global dictionaries to store data
user_profiles = {}
user_likes = {}
user_dislikes = {}
matched_users = {}

# Админы бота
ADMIN_USER_IDS = [5652528225]  # ЗАМЕНИ НА РЕАЛЬНЫЕ ID

# --- ФУНКЦИИ ДЛЯ СОХРАНЕНИЯ ДАННЫХ ---
def save_data():
    """Сохраняет все данные в файл"""
    data = {
        'user_profiles': user_profiles,
        'user_likes': user_likes,
        'user_dislikes': user_dislikes,
        'matched_users': matched_users
    }
    try:
        with open(DATA_FILE, 'wb') as f:
            pickle.dump(data, f)
        logger.info("Data saved successfully")
    except Exception as e:
        logger.error(f"Error saving data: {e}")

def load_data():
    """Загружает данные из файла"""
    global user_profiles, user_likes, user_dislikes, matched_users
    try:
        with open(DATA_FILE, 'rb') as f:
            data = pickle.load(f)
            user_profiles = data.get('user_profiles', {})
            user_likes = data.get('user_likes', {})
            user_dislikes = data.get('user_dislikes', {})
            matched_users = data.get('matched_users', {})
        logger.info(f"Data loaded: {len(user_profiles)} profiles, {sum(len(l) for l in user_likes.values())} likes")
    except FileNotFoundError:
        logger.info("No existing data file, starting fresh")
    except Exception as e:
        logger.error(f"Error loading data: {e}")

def setup_data_persistence():
    """Настраивает автосохранение при выходе"""
    def save_on_exit():
        save_data()
        logger.info("Data saved on exit")
    
    def save_on_signal(signum, frame):
        save_data()
        logger.info(f"Data saved on signal {signum}")
        exit(0)
    
    atexit.register(save_on_exit)
    signal.signal(signal.SIGINT, save_on_signal)
    signal.signal(signal.SIGTERM, save_on_signal)

# Декоратор для автоматического сохранения
def auto_save(func):
    async def wrapper(*args, **kwargs):
        result = await func(*args, **kwargs)
        save_data()
        return result
    return wrapper

# --- НОВАЯ ФУНКЦИЯ: Очистка старых просмотренных анкет ---
def clear_old_viewed_profiles(user_data):
    """Очищает историю просмотренных анкет, если их слишком много"""
    if 'viewed_profiles' in user_data:
        # Если просмотренных больше 50, очищаем самые старые
        if len(user_data['viewed_profiles']) > 50:
            user_data['viewed_profiles'] = user_data['viewed_profiles'][-25:]
            logger.info(f"Cleared old viewed profiles, now {len(user_data['viewed_profiles'])} remaining")

# --- НОВАЯ ФУНКЦИЯ: Команда для очистки истории ---
@auto_save
async def clear_history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очищает историю просмотренных анкет, лайки и дизлайки"""
    user_id = update.effective_user.id
    user_data = context.user_data
    
    # Очищаем историю просмотренных анкет
    if 'viewed_profiles' in user_data:
        user_data['viewed_profiles'] = []
    
    # Очищаем лайки и дизлайки текущего пользователя
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
    user_data = context.user_data
    
    # Очищаем всё
    user_data.clear()
    if user_id in user_likes:
        user_likes[user_id] = set()
    if user_id in user_dislikes:
        user_dislikes[user_id] = set()
    if user_id in matched_users:
        matched_users[user_id] = set()
    
    await update.message.reply_text("🎯 Полный сброс выполнен! Все анкеты будут показаны заново.")

# --- НОВАЯ ФУНКЦИЯ: Статистика бота ---
async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику бота только админам"""
    user_id = update.effective_user.id
    
    # Проверяем, что пользователь в списке админов
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("У вас нет доступа к этой команде.")
        return
    
    # Собираем статистику
    total_profiles = len(user_profiles)
    complete_profiles = len([uid for uid in user_profiles if is_profile_complete(uid)])
    total_likes = sum(len(likes) for likes in user_likes.values())
    total_matches = sum(len(matches) for matches in matched_users.values()) // 2
    
    stats_text = (
        f"📊 **Статистика бота:**\n"
        f"• Всего пользователей: {total_profiles}\n"
        f"• Заполненных анкет: {complete_profiles}\n"
        f"• Всего лайков: {total_likes}\n"
        f"• Совпадений: {total_matches}\n"
        f"\n**По полу:**\n"
    )
    
    gender_stats = {}
    for profile in user_profiles.values():
        gender = profile.get('gender', 'Не указан')
        gender_stats[gender] = gender_stats.get(gender, 0) + 1
    
    for gender, count in gender_stats.items():
        stats_text += f"• {gender}: {count}\n"
    
    await update.message.reply_text(stats_text)

# Function to check if the user profile is complete
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

# --- Helper function to display a profile ---
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

# --- ОБНОВЛЕННАЯ ФУНКЦИЯ: Поиск следующей анкеты ---
async def search_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    user_data = context.user_data
    
    # Очищаем старые просмотренные анкеты
    clear_old_viewed_profiles(user_data)
    
    # Инициализируем список просмотренных анкет, если его нет
    if 'viewed_profiles' not in user_data:
        user_data['viewed_profiles'] = []
    
    viewed_profiles = user_data['viewed_profiles']
    available_profiles = []

    # Get profiles that the current user hasn't liked or disliked, and isn't themselves
    for profile_id, profile_data in user_profiles.items():
        if profile_id == user_id:
            continue
        # Пропускаем, если пользователь уже лайкнул или дизлайкнул эту анкету
        if profile_id in user_likes.get(user_id, set()):
            continue
        if profile_id in user_dislikes.get(user_id, set()):
            continue
        # Пропускаем, если это уже совпадение
        if profile_id in matched_users.get(user_id, set()):
            continue
            
        # Пропускаем, если профиль неполный
        if not is_profile_complete(profile_id):
            continue

        available_profiles.append(profile_id)

    if not available_profiles:
        # Если нет доступных анкет, очищаем историю просмотренных
        user_data['viewed_profiles'] = []
        available_profiles = [pid for pid in user_profiles.keys() 
                            if pid != user_id 
                            and is_profile_complete(pid)
                            and pid not in user_likes.get(user_id, set())
                            and pid not in user_dislikes.get(user_id, set())
                            and pid not in matched_users.get(user_id, set())]
        
        if not available_profiles:
            await update.message.reply_text("Пока что больше нет анкет. Попробуйте позже!",
                                            reply_markup=ReplyKeyboardMarkup([
                                                [KeyboardButton("Поиск")],
                                                [KeyboardButton("Настройки")]
                                            ], resize_keyboard=True))
            return MENU

    # Выбираем случайную анкету из доступных
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
    liker_profile = user_profiles.get(liker_id)
    if not liker_profile:
        logger.error(f"Liker profile not found for ID: {liker_id}")
        return

    # Используем InlineKeyboardButtons для ответа на лайк
    keyboard = [
        [InlineKeyboardButton("❤️ Лайкнуть в ответ", callback_data=f"like_back_{liker_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"dislike_back_{liker_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправляем анкету лайкнувшего пользователя лайкнутому пользователю
    await context.bot.send_message(
        chat_id=liked_id,
        text="Тебя лайкнули! Вот чья анкета:",
        reply_markup=ReplyKeyboardRemove()
    )
    await send_profile_card(liked_id, liker_id, context, reply_markup)

@auto_save
async def notify_match(user1_id: int, user2_id: int, context: ContextTypes.DEFAULT_TYPE):
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

    # Add to matched_users
    if user1_id not in matched_users:
        matched_users[user1_id] = set()
    matched_users[user1_id].add(user2_id)

    if user2_id not in matched_users:
        matched_users[user2_id] = set()
    matched_users[user2_id].add(user1_id)

# --- Conversation Handlers ---
@auto_save
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation and asks the user about their gender."""
    user_id = update.message.from_user.id
    # Store username early
    if user_id not in user_profiles:
        user_profiles[user_id] = {}
    user_profiles[user_id]["username"] = update.message.from_user.username

    if is_profile_complete(user_id):
        keyboard = [
            [KeyboardButton("Поиск")],
            [KeyboardButton("Настройки")],
        ]
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
    user_id = update.message.from_user.id
    context.user_data["gender"] = update.message.text
    if user_id not in user_profiles:
        user_profiles[user_id] = {}
    user_profiles[user_id]["gender"] = update.message.text
    if "username" not in user_profiles[user_id]:
        user_profiles[user_id]["username"] = update.message.from_user.username

    await update.message.reply_text(
        "Отлично! Теперь укажи свое имя:", reply_markup=ReplyKeyboardRemove()
    )
    return NAME

@auto_save
async def name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the name and asks for the age."""
    user_id = update.message.from_user.id
    context.user_data["name"] = update.message.text
    user_profiles[user_id]["name"] = update.message.text

    await update.message.reply_text("Сколько тебе лет? (от 16 до 25)")
    return AGE

@auto_save
async def age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the age and asks for the city."""
    user_id = update.message.from_user.id
    try:
        age = int(update.message.text)
        if age < 16 or age > 25:
            await update.message.reply_text(
                "Пожалуйста, укажите реальный возраст (16-25):"
            )
            return AGE
        context.user_data["age"] = age
        user_profiles[user_id]["age"] = age

        await update.message.reply_text("Укажите свой курс (от 1 до 5):")
        return CITY
    except ValueError:
        await update.message.reply_text("Пожалуйста, укажите возраст цифрами.")
        return AGE

@auto_save
async def city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the city (course) and asks for the bio."""
    user_id = update.message.from_user.id
    try:
        course = int(update.message.text)
        if course < 1 or course > 5:
            await update.message.reply_text(
                "Пожалуйста, укажите реальный курс (1-5):"
            )
            return CITY
        context.user_data["city"] = course
        user_profiles[user_id]["city"] = course

        await update.message.reply_text("Расскажи немного о себе (интересы, хобби и т.д.):")
        return BIO
    except ValueError:
        await update.message.reply_text("Пожалуйста, укажите курс цифрами (1-5).")
        return CITY

@auto_save
async def bio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the bio and asks for a photo."""
    user_id = update.message.from_user.id
    context.user_data["bio"] = update.message.text
    user_profiles[user_id]["bio"] = update.message.text

    await update.message.reply_text("Теперь отправь свою лучшую фотографию:")
    return PHOTO

@auto_save
async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the photo and asks for confirmation."""
    user_id = update.message.from_user.id
    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        context.user_data["photo"] = photo_file_id
        user_profiles[user_id]["photo"] = photo_file_id

        # Display the profile for confirmation
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
    user_id = update.message.from_user.id
    if update.message.text == "Да, все верно":
        keyboard = [
            [KeyboardButton("Поиск")],
            [KeyboardButton("Настройки")],
        ]
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
    text = update.message.text
    if text == "Поиск":
        return await search_profile(update, context)
    elif text == "Настройки":
        return await settings(update, context)
    else:
        keyboard = [
            [KeyboardButton("Поиск")],
            [KeyboardButton("Настройки")],
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Пожалуйста, выберите действие:", reply_markup=reply_markup)
        return MENU

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the 'Поиск' command, initiating profile search."""
    return await search_profile(update, context)

@auto_save
async def like(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User likes the current profile."""
    liker_id = update.message.from_user.id
    liked_id = context.user_data.get('current_viewing_profile_id')
    user_data = context.user_data

    if not liked_id:
        await update.message.reply_text("Что-то пошло не так. Попробуйте снова начать поиск.",
                                        reply_markup=ReplyKeyboardMarkup([
                                            [KeyboardButton("Поиск")],
                                            [KeyboardButton("Настройки")]
                                        ], resize_keyboard=True))
        return MENU

    if liker_id not in user_likes:
        user_likes[liker_id] = set()
    user_likes[liker_id].add(liked_id)

    # Добавляем в просмотренные анкеты
    if 'viewed_profiles' not in user_data:
        user_data['viewed_profiles'] = []
    if liked_id not in user_data['viewed_profiles']:
        user_data['viewed_profiles'].append(liked_id)

    # Очищаем старые просмотренные анкеты
    clear_old_viewed_profiles(user_data)

    # Check for mutual like (liked_id liked liker_id previously)
    if liked_id in user_likes and liker_id in user_likes[liked_id]:
        # It's a match!
        await notify_match(liker_id, liked_id, context)
        await update.message.reply_text("УРА! Это совпадение! 🎉")
        return await search_profile(update, context)
    else:
        # Not a mutual like yet, notify the liked_id
        await notify_liked_user(liker_id, liked_id, context)
        await update.message.reply_text("Лайк отправлен! Продолжаем поиск...")
        return await search_profile(update, context)

@auto_save
async def dislike(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User dislikes the current profile."""
    disliker_id = update.message.from_user.id
    disliked_id = context.user_data.get('current_viewing_profile_id')
    user_data = context.user_data

    if not disliked_id:
        await update.message.reply_text("Что-то пошло не так. Попробуйте снова начать поиск.",
                                        reply_markup=ReplyKeyboardMarkup([
                                            [KeyboardButton("Поиск")],
                                            [KeyboardButton("Настройки")]
                                        ], resize_keyboard=True))
        return MENU

    if disliker_id not in user_dislikes:
        user_dislikes[disliker_id] = set()
    user_dislikes[disliker_id].add(disliked_id)

    # Добавляем в просмотренные анкеты
    if 'viewed_profiles' not in user_data:
        user_data['viewed_profiles'] = []
    if disliked_id not in user_data['viewed_profiles']:
        user_data['viewed_profiles'].append(disliked_id)

    # Очищаем старые просмотренные анкеты
    clear_old_viewed_profiles(user_data)

    await update.message.reply_text("Анкета пропущена. Продолжаем поиск...")
    return await search_profile(update, context)

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Shows settings options."""
    keyboard = [
        [KeyboardButton("Редактировать профиль")],
        [KeyboardButton("Мой профиль")],
        [KeyboardButton("Очистить историю")],
        [KeyboardButton("⬅️ Меню")],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Настройки:", reply_markup=reply_markup)
    return SETTINGS

async def edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Allows user to choose what to edit."""
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
    keyboard = [["Мужской"], ["Женский"], ["Другое"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("Укажите новый пол:", reply_markup=reply_markup)
    return EDIT_GENDER

@auto_save
async def save_edit_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id]["gender"] = update.message.text
    await update.message.reply_text("Пол обновлен.")
    return await edit_profile(update, context)

@auto_save
async def edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Укажите новое имя:")
    return EDIT_NAME

@auto_save
async def save_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id]["name"] = update.message.text
    await update.message.reply_text("Имя обновлено.")
    return await edit_profile(update, context)

@auto_save
async def edit_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Укажите новый возраст (от 16 до 25):")
    return EDIT_AGE

@auto_save
async def save_edit_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    try:
        age = int(update.message.text)
        if age < 16 or age > 25:
            await update.message.reply_text("Пожалуйста, укажите реальный возраст (16-25):")
            return EDIT_AGE
        user_profiles[user_id]["age"] = age
        await update.message.reply_text("Возраст обновлен.")
        return await edit_profile(update, context)
    except ValueError:
        await update.message.reply_text("Пожалуйста, укажите возраст цифрами.")
        return EDIT_AGE

@auto_save
async def edit_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Укажите новый курс (от 1 до 5):")
    return EDIT_CITY

@auto_save
async def save_edit_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    try:
        course = int(update.message.text)
        if course < 1 or course > 5:
            await update.message.reply_text("Пожалуйста, укажите реальный курс (1-5):")
            return EDIT_CITY
        user_profiles[user_id]["city"] = course
        await update.message.reply_text("Курс обновлен.")
        return await edit_profile(update, context)
    except ValueError:
        await update.message.reply_text("Пожалуйста, укажите курс цифрами (1-5).")
        return EDIT_CITY

@auto_save
async def edit_bio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Напишите новое описание о себе:")
    return EDIT_BIO

@auto_save
async def save_edit_bio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id]["bio"] = update.message.text
    await update.message.reply_text("Описание обновлено.")
    return await edit_profile(update, context)

@auto_save
async def edit_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Отправьте новую фотографию:")
    return EDIT_PHOTO

@auto_save
async def save_edit_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        user_profiles[user_id]["photo"] = photo_file_id
        await update.message.reply_text("Фотография обновлена.")
        return await edit_profile(update, context)
    else:
        await update.message.reply_text("Пожалуйста, отправьте фотографию.")
        return EDIT_PHOTO

async def show_my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
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

async def done_editing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Returns to settings menu after editing."""
    await update.message.reply_text("Изменения сохранены.", reply_markup=ReplyKeyboardRemove())
    return await settings(update, context)

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Returns to the main menu."""
    keyboard = [
        [KeyboardButton("Поиск")],
        [KeyboardButton("Настройки")],
    ]
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

# --- CallbackQueryHandler for InlineKeyboardButtons (Like Back / Dislike Back) ---
@auto_save
async def handle_match_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    liked_id = query.from_user.id
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

    keyboard = [
        [KeyboardButton("Поиск")],
        [KeyboardButton("Настройки")],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    try:
        await context.bot.send_message(
            chat_id=liked_id,
            text="Что дальше?",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error sending menu message: {e}")

def main() -> None:
    """Run the bot."""
    # Загружаем данные при старте
    load_data()
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
                MessageHandler(filters.Regex("^Поиск$"), search),
                MessageHandler(filters.Regex("^Настройки$"), settings),
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
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL, back_to_menu)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(handle_match_response))
    application.add_handler(CommandHandler("clear", clear_history_handler))
    application.add_handler(CommandHandler("reset", reset_all_handler))
    application.add_handler(CommandHandler("stats", stats_handler))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
