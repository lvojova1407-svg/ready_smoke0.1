import os
import sqlite3
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# ==================== НАСТРОЙКИ ====================
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')  # ИЗМЕНИЛ: был BOT_TOKEN

# Типы перерывов
BREAK_TYPES = {
    "lunch": {"name": "🍽 Обед", "duration": 45, "max_users": 5},
    "smoke": {"name": "🚬 Перекур", "duration": 10, "max_users": 3}
}

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect('queue.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  full_name TEXT,
                  registered_at TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS bookings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  break_type TEXT,
                  start_time TEXT,
                  end_time TEXT,
                  status TEXT DEFAULT 'active',
                  created_at TIMESTAMP)''')
    
    conn.commit()
    conn.close()
    print("✅ База данных готова")

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📋 Мои записи"), KeyboardButton("📊 Очередь")],
        [KeyboardButton("🍽 Записать на обед"), KeyboardButton("🚬 Записать на перекур")],
        [KeyboardButton("❌ Отменить запись"), KeyboardButton("📈 Статистика")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_cancel_keyboard():
    keyboard = [
        [KeyboardButton("Отменить обед"), KeyboardButton("Отменить перекур")],
        [KeyboardButton("Отменить всё"), KeyboardButton("🔙 Назад")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def register_user(user_id, username, full_name):
    conn = sqlite3.connect('queue.db')
    c = conn.cursor()
    c.execute('''INSERT OR IGNORE INTO users (user_id, username, full_name, registered_at)
                 VALUES (?, ?, ?, ?)''', 
              (user_id, username, full_name, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_bookings_count(break_type, start_time):
    conn = sqlite3.connect('queue.db')
    c = conn.cursor()
    c.execute('''SELECT COUNT(*) FROM bookings 
                 WHERE break_type = ? AND start_time = ? AND status = 'active' ''',
              (break_type, start_time))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_user_bookings(user_id):
    conn = sqlite3.connect('queue.db')
    c = conn.cursor()
    c.execute('''SELECT break_type, start_time, end_time FROM bookings 
                 WHERE user_id = ? AND status = 'active' 
                 ORDER BY start_time''', (user_id,))
    bookings = c.fetchall()
    conn.close()
    return bookings

def create_booking(user_id, break_key, start_time):
    """Создать запись на перерыв"""
    break_info = BREAK_TYPES[break_key]
    
    # Проверяем лимит
    current_count = get_bookings_count(break_info["name"], start_time)
    if current_count >= break_info["max_users"]:
        return False, f"❌ На {break_info['name']} {start_time} уже записалось {current_count}/{break_info['max_users']} человек"
    
    # Проверяем дубли
    conn = sqlite3.connect('queue.db')
    c = conn.cursor()
    c.execute('''SELECT start_time FROM bookings 
                 WHERE user_id = ? AND break_type = ? AND status = 'active' ''',
              (user_id, break_info["name"]))
    if c.fetchone():
        conn.close()
        return False, f"❌ У вас уже есть активный {break_info['name']}"
    
    # Создаем запись
    start_dt = datetime.strptime(start_time, "%H:%M")
    end_dt = start_dt + timedelta(minutes=break_info["duration"])
    end_time = end_dt.strftime("%H:%M")
    
    c.execute('''INSERT INTO bookings (user_id, break_type, start_time, end_time, created_at)
                 VALUES (?, ?, ?, ?, ?)''',
              (user_id, break_info["name"], start_time, end_time, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    return True, f"✅ Вы записались на {break_info['name']}\n⏰ Время: {start_time}-{end_time}"

# ==================== ОСНОВНЫЕ КОМАНДЫ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    register_user(user.id, user.username, user.full_name)
    
    await update.message.reply_text(
        f"👋 *Привет, {user.first_name}!*\n\n"
        "🤖 *Я бот для организации очереди на перерывы*\n\n"
        "📋 *Используйте кнопки ниже:*\n"
        "• 📋 Мои записи - ваши брони\n"
        "• 📊 Очередь - все записи\n"
        "• 🍽 Записать на обед - 45 мин, до 5 чел\n"
        "• 🚬 Записать на перекур - 10 мин, до 3 чел\n"
        "• ❌ Отменить запись - отменить бронь\n"
        "• 📈 Статистика - статистика\n\n"
        "⏰ *Работаю круглосуточно!*",
        reply_markup=get_main_keyboard(),
        parse_mode='Markdown'
    )

async def show_my_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Мои записи"""
    user = update.effective_user
    bookings = get_user_bookings(user.id)
    
    if not bookings:
        await update.message.reply_text("📭 *У вас нет активных записей*", parse_mode='Markdown')
        return
    
    text = "📋 *Ваши активные записи:*\n\n"
    for break_type, start_time, end_time in bookings:
        current_count = get_bookings_count(break_type, start_time)
        max_users = 5 if "Обед" in break_type else 3
        text += f"{break_type}\n⏰ {start_time}-{end_time}\n👥 {current_count}/{max_users} чел\n\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def show_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вся очередь"""
    conn = sqlite3.connect('queue.db')
    c = conn.cursor()
    c.execute('''SELECT b.break_type, b.start_time, b.end_time, u.full_name
                 FROM bookings b
                 JOIN users u ON b.user_id = u.user_id
                 WHERE b.status = 'active'
                 ORDER BY b.start_time, b.break_type''')
    bookings = c.fetchall()
    conn.close()
    
    if not bookings:
        await update.message.reply_text("📭 *Очередь пуста*", parse_mode='Markdown')
        return
    
    # Группируем
    lunch = []
    smoke = []
    
    for break_type, start, end, name in bookings:
        if "Обед" in break_type:
            lunch.append((start, end, name or "Аноним"))
        else:
            smoke.append((start, end, name or "Аноним"))
    
    text = "📊 *Текущая очередь:*\n\n"
    
    if lunch:
        text += "🍽 *Обеды:*\n"
        for start, end, name in lunch:
            count = get_bookings_count("🍽 Обед", start)
            text += f"⏰ {start}-{end} - {name} ({count}/5)\n"
        text += "\n"
    
    if smoke:
        text += "🚬 *Перекуры:*\n"
        for start, end, name in smoke:
            count = get_bookings_count("🚬 Перекур", start)
            text += f"⏰ {start}-{end} - {name} ({count}/3)\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def show_time_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, break_key: str):
    """Показать выбор времени для записи"""
    break_info = BREAK_TYPES[break_key]
    
    # Генерируем ближайшие слоты
    now = datetime.now()
    slots = []
    for i in range(8):  # 8 слотов по 30 минут
        slot_time = (now + timedelta(minutes=i*30)).replace(second=0, microsecond=0)
        slots.append(slot_time.strftime("%H:%M"))
    
    # Создаем кнопки
    keyboard = []
    for time in slots:
        count = get_bookings_count(break_info["name"], time)
        if count >= break_info["max_users"]:
            btn_text = f"🔴 {time}"
            callback_data = f"full_{break_key}_{time}"
        else:
            btn_text = f"🟢 {time}"
            callback_data = f"book_{break_key}_{time}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=callback_data)])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_main")])
    
    await update.message.reply_text(
        f"*{break_info['name']}*\nВыберите время:\n🟢 - свободно\n🔴 - занято",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий кнопок"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user = query.from_user
    
    if data.startswith("book_"):
        # Запись на время
        parts = data.split("_")
        break_key = parts[1]
        time = parts[2]
        
        success, message = create_booking(user.id, break_key, time)
        await query.edit_message_text(message)
        
    elif data.startswith("full_"):
        await query.answer("❌ Это время уже занято!", show_alert=True)
        
    elif data == "back_main":
        await query.edit_message_text("Главное меню:", reply_markup=get_main_keyboard())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    text = update.message.text
    
    if text == "📋 Мои записи":
        await show_my_bookings(update, context)
    elif text == "📊 Очередь":
        await show_queue(update, context)
    elif text == "🍽 Записать на обед":
        await show_time_selection(update, context, "lunch")
    elif text == "🚬 Записать на перекур":
        await show_time_selection(update, context, "smoke")
    elif text == "❌ Отменить запись":
        # Простая отмена
        user = update.effective_user
        conn = sqlite3.connect('queue.db')
        c = conn.cursor()
        c.execute('''UPDATE bookings SET status = 'cancelled' 
                     WHERE user_id = ? AND status = 'active' ''', (user.id,))
        count = c.rowcount
        conn.commit()
        conn.close()
        
        if count > 0:
            await update.message.reply_text(f"✅ Отменено {count} записей")
        else:
            await update.message.reply_text("❌ Нечего отменять")
    elif text == "📈 Статистика":
        conn = sqlite3.connect('queue.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM bookings WHERE status='active'")
        active = c.fetchone()[0]
        conn.close()
        
        await update.message.reply_text(
            f"📈 *Статистика:*\n👥 Пользователей: {users}\n📋 Активных записей: {active}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("Используйте кнопки 👇", reply_markup=get_main_keyboard())

# ==================== ЗАПУСК ====================
def main():
    """Запуск бота"""
    # Инициализация БД
    init_db()
    
    # Проверка токена
    if not TOKEN:
        print("❌ ОШИБКА: Токен не найден!")
        print("Добавьте TELEGRAM_BOT_TOKEN в переменные окружения")
        return
    
    # Создаем приложение
    app = Application.builder().token(TOKEN).build()
    
    # Регистрируем обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("=" * 50)
    print("🤖 БОТ ДЛЯ ЗАПИСИ НА ПЕРЕРЫВЫ")
    print("=" * 50)
    print(f"✅ Токен: {'Найден' if TOKEN else 'НЕ НАЙДЕН!'}")
    print(f"🍽 Обед: {BREAK_TYPES['lunch']['duration']} мин, до {BREAK_TYPES['lunch']['max_users']} чел")
    print(f"🚬 Перекур: {BREAK_TYPES['smoke']['duration']} мин, до {BREAK_TYPES['smoke']['max_users']} чел")
    print("=" * 50)
    
    # Запускаем
    app.run_polling()

if __name__ == '__main__':
    main()