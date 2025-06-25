import telebot
from telebot import types
import json
import os
from flask import Flask, render_template, request, redirect, url_for
from flask_httpauth import HTTPBasicAuth
from flask_wtf import FlaskForm
from wtforms import HiddenField, SubmitField, IntegerField
from wtforms.validators import NumberRange
from flask_wtf.csrf import CSRFProtect
import threading
from threading import Lock
import logging
from config import TOKEN, ADMIN_USERNAME, ADMIN_PASSWORD, SECRET_KEY
from faker import Faker
import random
import time
import unicodedata
import sys

# Инициализация бота
DATA_FILE = 'users.json'
bot = telebot.TeleBot(TOKEN)

logging.basicConfig(filename='logs.log', level=logging.INFO, format='%(asctime)s - %(message)s')

users_lock = Lock()
users_cache = None
fake = Faker('ru_RU')

def load_users():
    global users_cache
    with users_lock:
        if users_cache is None:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    users_cache = json.load(f)
            else:
                users_cache = {}
        return users_cache

def save_users(users_data):
    global users_cache
    with users_lock:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(users_data, f, ensure_ascii=False, indent=2)
        users_cache = users_data

user_template = {
    "name": "",
    "age": 0,
    "gender": "",
    "bio": "",
    "photo_id": "",
    "likes": [],
    "dislikes": [],
    "state": "MENU",
    "preferred_gender": "",
    "preferred_age_min": 18,
    "preferred_age_max": 100,
    "is_blocked": False,
    "is_virtual": False,
    "op_status": False,
    "username": ""
}

users = load_users()

def cancel_button():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("❌ Отмена")
    return markup

@bot.message_handler(commands=['start'])
def start(message):
    user_id = str(message.from_user.id)
    
    if user_id not in users:
        users[user_id] = user_template.copy()
        users[user_id]['state'] = 'REG_NAME'
        save_users(users)
        bot.send_message(message.chat.id, "👋 Добро пожаловать в бота для знакомств! Давай создадим твой профиль.\n\n✏️ Введи свое имя:")
        users[user_id]['username'] = message.from_user.username
    else:
        users[user_id]['state'] = 'MENU'
        save_users(users)
        show_main_menu(message.chat.id)
        if users[user_id]["name"] == "":
            bot.send_message(message.chat.id, "⚠️ Ваш аккаунт не зарегистрирован!")
            users_data = load_users()
            del users_data[user_id]
            start(message)

@bot.message_handler(func=lambda m: m.text == "❌ Отмена")
def cancel_registration(message):
    user_id = str(message.from_user.id)
    if user_id in users and users[user_id]['state'].startswith('REG_'):
        users[user_id]['state'] = 'MENU'
        save_users(users)
        bot.send_message(message.chat.id, "❌ Регистрация отменена.", reply_markup=types.ReplyKeyboardRemove())
        show_main_menu(message.chat.id)

@bot.message_handler(func=lambda m: unicodedata.normalize('NFKC', m.text.strip()) in ["🔍 Искать анкеты", "👤 Мой профиль", "⚙️ Редактировать профиль", "🆘 Поддержка", "admin563"])
def handle_menu(message):
    user_id = str(message.from_user.id)
    normalized_text = message.text
    logging.info(f"Menu button pressed by {user_id}: {normalized_text}. He`s id: @{message.from_user.username}")
    try:
        if user_id not in users:
            bot.send_message(message.chat.id, "⚠️ Пожалуйста, зарегистрируйтесь с помощью /start")
            return

        if users[user_id].get('is_blocked', False):
            bot.send_message(message.chat.id, "🚫 Ваш аккаунт заблокирован.")
            return

        if normalized_text == "🔍 Искать анкеты":
            candidates = find_profiles(user_id)
            if candidates:
                users[user_id]['current_candidate'] = candidates[0]
                save_users(users)
                show_profile(message.chat.id, candidates[0])
            else:
                bot.send_message(message.chat.id, "😔 Анкет пока нет. Попробуй позже или добавь виртуальных пользователей в админ-панели!")
        elif normalized_text == "👤 Мой профиль":
            show_own_profile(message)
        elif normalized_text == "⚙️ Редактировать профиль":
            edit_profile(message)
        elif normalized_text == "🆘 Поддержка":
            bot.send_message(message.chat.id, "📨 Username поддержки: @hello_im_roman")
        elif normalized_text == "admin563":
            if users[user_id]["op_status"] == "true":
                bot.send_message(message.chat.id, "🔐 Hello, dev! Admin panel is available on http://147.45.104.113:3000/. Login: admin, pass = roman")
            else:
                bot.send_message(message.chat.id, "⚠️ Hey! You dont have permissions to this command! If you dev: @hello_im_roman.")
    except Exception as e:
        logging.error(f"Error in handle_menu for user {user_id}: {e}")
        bot.send_message(message.chat.id, "❌ Произошла ошибка. Попробуйте снова.")

@bot.message_handler(content_types=['text'])
def handle_text(message):
    user_id = str(message.from_user.id)
    normalized_text = unicodedata.normalize('NFKC', message.text.strip())
    logging.info(f"Received text from {user_id}: {normalized_text}")
    user = users.get(user_id)
    if not user:
        return start(message)
    if user.get('is_blocked', False):
        bot.send_message(message.chat.id, "🚫 Ваш аккаунт заблокирован.")
        return

    state = user['state']

    try:
        if state == 'REG_NAME':
            users[user_id]['name'] = normalized_text
            users[user_id]['state'] = 'REG_AGE'
            save_users(users)
            bot.send_message(message.chat.id, "📅 Сколько тебе лет?")

        elif state == 'REG_AGE':
            if normalized_text.isdigit():
                age = int(normalized_text)
                if age > 50 or age < 14:
                    bot.send_message(message.chat.id, "⚠️ Ваш возраст должен быть от 14 до 50 лет!")
                    return
                users[user_id]['age'] = age
                users[user_id]['state'] = 'REG_BIO'
                save_users(users)
                bot.send_message(message.chat.id, "📝 Расскажи о себе:")
            else:
                bot.send_message(message.chat.id, "⚠️ Пожалуйста, введите число!")

        elif state == 'REG_BIO':
            users[user_id]['bio'] = normalized_text
            users[user_id]['state'] = "REG_PREF_GENDER"
            save_users(users)
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("👨 Мужской", "👩 Женский")
            bot.send_message(message.chat.id, "🔍 Какой пол ты ищешь?", reply_markup=markup)

        elif state == 'REG_PREF_GENDER':
            if normalized_text in ["👨 Мужской", "👩 Женский"]:
                users[user_id]['preferred_gender'] = "М" if "Мужской" in normalized_text else "Ж"
                users[user_id]['state'] = 'REG_PREF_AGE'
                save_users(users)
                bot.send_message(message.chat.id, "📅 Введи диапазон возраста (например, 18-30):")
            else:
                bot.send_message(message.chat.id, "⚠️ Пожалуйста, выберите вариант из клавиатуры")

        elif state == 'REG_PREF_AGE':
            if '-' in normalized_text:
                try:
                    age_min, age_max = map(int, normalized_text.split('-'))
                    if age_min >= age_max or age_min < 14 or age_max > 50:
                        raise ValueError
                    users[user_id]['preferred_age_min'] = age_min
                    users[user_id]['preferred_age_max'] = age_max
                    users[user_id]['state'] = 'REG_PHOTO'
                    save_users(users)
                    bot.send_message(message.chat.id, "📸 Пришли свое фото. Если не хочешь - напиши '❌ Отмена'!",
                                   reply_markup=cancel_button())
                except Exception as e:
                    logging.error(f"Invalid age range: {e}")
                    bot.send_message(message.chat.id, "⚠️ Неправильный формат. Пример: 18-30\nДиапазон должен быть от 14 до 50 лет!")
            else:
                bot.send_message(message.chat.id, "⚠️ Используйте формат 'мин-макс', например: 20-35")

        elif state == 'REG_PHOTO' and normalized_text == "❌ Отмена":
            users[user_id]['state'] = 'MENU'
            save_users(users)
            bot.send_message(message.chat.id, "🖼️ Фото не добавлено. Регистрация завершена!",
                           reply_markup=types.ReplyKeyboardRemove())
            show_main_menu(message.chat.id)

    except Exception as e:
        logging.error(f"Error in handle_text for user {user_id}: {e}")
        bot.send_message(message.chat.id, "❌ Произошла ошибка. Попробуйте снова.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    user_id = str(message.from_user.id)
    user = users.get(user_id)
    if user and user['state'] == 'REG_PHOTO':
        users[user_id]['photo_id'] = message.photo[-1].file_id
        users[user_id]['state'] = 'MENU'
        save_users(users)
        bot.send_message(message.chat.id, "🎉 Регистрация завершена!", reply_markup=types.ReplyKeyboardRemove())
        show_main_menu(message.chat.id)

def show_main_menu(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🔍 Искать анкеты", "👤 Мой профиль")
    markup.row("⚙️ Редактировать профиль", "🆘 Поддержка")
    bot.send_message(chat_id, "📱 Главное меню:", reply_markup=markup)

def find_profiles(user_id, users_data=None):
    if users_data is None:
        users_data = load_users()
    
    current_user = users_data[user_id]
    candidates = []
    
    for uid, profile in users_data.items():
        # Пропускаем неактуальные профили
        if (uid == user_id or
            not profile.get('photo_id') or
            profile.get('is_blocked', False) or
            uid in current_user['likes'] or
            uid in current_user['dislikes']):
            continue
            
        # Фильтр по предпочтениям
        gender_ok = (not current_user['preferred_gender'] or 
                     profile['gender'] == current_user['preferred_gender'])
        age_ok = (current_user['preferred_age_min'] <= profile['age'] <= current_user['preferred_age_max'])
        
        if gender_ok and age_ok:
            candidates.append(uid)
    
    # Перемешиваем для случайного порядка
    random.shuffle(candidates)
    return candidates

def show_profile(chat_id, profile_id, users_data=None):
    if users_data is None:
        users_data = load_users()
    
    profile = users_data[profile_id]
    # Форматирование информации о username
    username_info = f"\n💬 Напиши: @{profile['username']}" if profile.get('username') else ""
    
    caption = (f"👤 {profile['name']}, {profile['age']}\n"
               f"📝 {profile['bio']}"
               f"{username_info}")
    
    try:
        bot.send_photo(
            chat_id,
            profile['photo_id'],
            caption=caption,
            reply_markup=generate_action_buttons()
        )
    except Exception as e:
        logging.error(f"Ошибка показа профиля {profile_id}: {e}")
        bot.send_message(chat_id, f"❌ Ошибка при загрузке анкеты: {profile['name']}")

def generate_action_buttons():
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("❤️ Лайк", callback_data="like"),
        types.InlineKeyboardButton("👎 Дизлайк", callback_data="dislike")
    )
    return markup

@bot.message_handler(commands=['profile'])
def show_own_profile(message):
    user_id = str(message.from_user.id)
    if user_id in users and users[user_id]['state'] == 'MENU':
        if users[user_id].get('is_blocked', False):
            bot.send_message(message.chat.id, "🚫 Ваш аккаунт заблокирован.")
            return
        profile = users[user_id]
        caption = f"📌 Твой профиль:\n\n👤 Имя: {profile['name']}\n📅 Возраст: {profile['age']}\n🔍 Пол: {profile['gender']}\n📝 О себе: {profile['bio']}\n💬 Username: @{profile['username']}"
        if profile['photo_id']:
            bot.send_photo(message.chat.id, profile['photo_id'], caption=caption)
        else:
            bot.send_message(message.chat.id, caption)
    else:
        bot.send_message(message.chat.id, "⚠️ Сначала заверши регистрацию с помощью /start")

@bot.message_handler(commands=['edit_profile'])
def edit_profile(message):
    user_id = str(message.from_user.id)
    if user_id in users:
        if users[user_id].get('is_blocked', False):
            bot.send_message(message.chat.id, "🚫 Ваш аккаунт заблокирован.")
            return
        users[user_id]['state'] = 'REG_NAME'
        save_users(users)
        bot.send_message(message.chat.id, "✏️ Давай отредактируем твой профиль. Введи новое имя:", reply_markup=cancel_button())
    else:
        bot.send_message(message.chat.id, "⚠️ Сначала зарегистрируйся с помощью /start")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    users_data = load_users()  # Загружаем актуальные данные
    user_id = str(call.from_user.id)
    
    if user_id not in users_data:
        bot.answer_callback_query(call.id, "❌ Ваш аккаунт не найден. Зарегистрируйтесь снова.")
        return

    current_user = users_data[user_id]
    if current_user.get('is_blocked', False):
        bot.answer_callback_query(call.id, "🚫 Ваш аккаунт заблокирован.", show_alert=True)
        return

    # Проверяем наличие текущего кандидата
    if 'current_candidate' not in current_user:
        bot.answer_callback_query(call.id, "❌ Ошибка: кандидат не найден.")
        return

    candidate_id = current_user['current_candidate']
    
    # Проверяем существование кандидата
    if candidate_id not in users_data:
        bot.answer_callback_query(call.id, "❌ Ошибка: кандидат не существует.")
        return

    try:
        # Удаляем сообщение с анкетой
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception as e:
        logging.error(f"Ошибка при удалении сообщения: {e}")

    # Обработка лайка
    if call.data == "like":
        # Проверка на повторный лайк
        if candidate_id in current_user['likes']:
            bot.answer_callback_query(call.id, "❌ Вы уже лайкали этот профиль.")
        else:
            # Добавляем лайк
            current_user['likes'].append(candidate_id)
            save_users(users_data)  # Сохраняем изменения
            
            # Проверяем взаимность
            if user_id in users_data[candidate_id].get('likes', []):
                # Формируем сообщение о мэтче
                match_message = f"💞 Мэтч! Вы понравились {users_data[candidate_id]['name']}."
                if users_data[candidate_id].get('username'):
                    match_message += f"\n💬 Напиши: @{users_data[candidate_id]['username']}"
                
                # Отправляем уведомление текущему пользователю
                bot.send_message(user_id, match_message)
                
                # Отправляем уведомление кандидату (если не виртуальный и не заблокирован)
                if (not users_data[candidate_id].get('is_virtual', False) and 
                    not users_data[candidate_id].get('is_blocked', False)):
                    try:
                        candidate_match_msg = f"💞 Мэтч! Вы понравились {users_data[user_id]['name']}."
                        if users_data[user_id].get('username'):
                            candidate_match_msg += f"\n💬 Напиши: @{users_data[user_id]['username']}"
                        bot.send_message(candidate_id, candidate_match_msg)
                    except Exception as e:
                        logging.error(f"Ошибка отправки мэтча кандидату: {e}")
                
                bot.answer_callback_query(call.id, "💞 Мэтч! Вы понравились друг другу!")
            else:
                bot.answer_callback_query(call.id, "❤️ Твой лайк отправлен!")

    # Обработка дизлайка
    elif call.data == "dislike":
        # Проверка на повторный дизлайк
        if candidate_id in current_user['dislikes']:
            bot.answer_callback_query(call.id, "❌ Вы уже дизлайкали этот профиль.")
        else:
            current_user['dislikes'].append(candidate_id)
            save_users(users_data)
            bot.answer_callback_query(call.id, "👎 Дизлайк")

    # Ищем следующего кандидата
    candidates = find_profiles(user_id, users_data)
    if candidates:
        users_data[user_id]['current_candidate'] = candidates[0]
        save_users(users_data)
        show_profile(call.message.chat.id, candidates[0], users_data)
    else:
        bot.send_message(call.message.chat.id, "😔 Анкеты закончились. Попробуйте позже!")

# Flask admin panel setup
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
auth = HTTPBasicAuth()
csrf = CSRFProtect(app)

# Формы для CSRF-защиты
class DeleteUserForm(FlaskForm):
    user_id = HiddenField()
    submit = SubmitField('🗑️ Удалить')

class AddOp(FlaskForm):
    user_id = HiddenField()
    submit = SubmitField("👑 Выдать права администратора")

class ToggleBlockForm(FlaskForm):
    user_id = HiddenField()
    submit = SubmitField('🚫 Заблокировать')

class TestUsersForm(FlaskForm):
    count = IntegerField('Количество пользователей', validators=[NumberRange(min=1, max=100)])
    submit = SubmitField('🛠️ Создать')

@auth.verify_password
def verify_password(username, password):
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD

@app.route('/')
@auth.login_required
def admin_dashboard():
    users_data = load_users()
    stats = {
        'total_users': len(users_data),
        'profiles_with_photo': sum(1 for u in users_data.values() if u['photo_id']),
        'active_profiles': sum(1 for u in users_data.values() if u['state'] == 'MENU'),
    }
    delete_form = DeleteUserForm()
    block_form = ToggleBlockForm()
    return render_template(
        'admin.html',
        users=users_data,
        stats=stats,
        current_user=auth.current_user(),
        delete_form=delete_form,
        block_form=block_form,
    )

@app.route('/user/<user_id>')
@auth.login_required
def view_user(user_id):
    users_data = load_users()
    user = users_data.get(user_id)
    if not user:
        return "❌ Пользователь не найден", 404
    return render_template('user.html', user=user, user_id=user_id)

@app.route('/delete_user', methods=['POST'])
@auth.login_required
def delete_user():
    form = DeleteUserForm()
    if form.validate_on_submit():
        user_id = form.user_id.data
        users_data = load_users()
        if user_id in users_data:
            logging.info(f"User {user_id} deleted by admin {auth.current_user()}")
            del users_data[user_id]
            bot.send_message(user_id, "❌ Ваш аккаунт удалён!")
            save_users(users_data)
    return redirect(url_for('admin_dashboard'))

@app.route('/toggle_block_user', methods=['POST'])
@auth.login_required
def toggle_block_user():
    form = ToggleBlockForm()
    if form.validate_on_submit():
        user_id = form.user_id.data
        users_data = load_users()
        if user_id in users_data:
            users_data[user_id]['is_blocked'] = not users_data[user_id].get('is_blocked', False)
            logging.info(f"User {user_id} {'blocked' if users_data[user_id]['is_blocked'] else 'unblocked'} by admin {auth.current_user()}")
            save_users(users_data)
            try:
                bot.send_message(user_id, "🚫 Ваш аккаунт был заблокирован." if users_data[user_id]['is_blocked'] else "✅ Ваш аккаунт разблокирован.")
            except:
                pass
    return redirect(url_for('admin_dashboard'))

@app.route('/test', methods=['GET', 'POST'])
@auth.login_required
def test_users():
    form = TestUsersForm()
    if form.validate_on_submit():
        count = form.count.data
        users_data = load_users()
        for _ in range(count):
            user_id = str(random.randint(1000000000, 9999999999))
            while user_id in users_data:
                user_id = str(random.randint(1000000000, 9999999999))
            users_data[user_id] = user_template.copy()
            users_data[user_id].update({
                'name': fake.first_name(),
                'age': random.randint(18, 50),
                'gender': random.choice(['М', 'Ж']),
                'bio': fake.sentence(nb_words=10),
                'photo_id': f"virtual_photo_{user_id}",
                'state': 'MENU',
                'preferred_gender': random.choice(['М', 'Ж', '']),
                'preferred_age_min': random.randint(18, 30),
                'preferred_age_max': random.randint(31, 50),
                'is_virtual': True
            })
            logging.info(f"Virtual user {user_id} created by admin {auth.current_user()}")
        save_users(users_data)
        return redirect(url_for('admin_dashboard'))
    return render_template('test.html', form=form)

def run_admin_panel():
    app.run(port=3000, host='127.0.0.1', debug=False, use_reloader=False)

if __name__ == '__main__':
    threading.Thread(target=run_admin_panel, daemon=True).start()
    print("🔐 Админ-панель запущена на http://localhost:3000")
    print(f"👤 Логин: {ADMIN_USERNAME}, 🔑 Пароль: {ADMIN_PASSWORD}")

    while True:
        try:
            print("🤖 Запускаем бота...")
            bot.infinity_polling()
            print("✅ Бот работает!")
            off = input()
            if off == "stop":
                sys.exit(0)
            else:
                print("⚠️ Введите правильную команду!")
        except Exception as e:
            logging.error(f"Polling error: {e}")
            time.sleep(5)  # Перезапуск через 5 секунд
