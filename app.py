import telebot
from telebot import types
from flask import Flask, request, render_template, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
import os
import time
from threading import Thread

# --- KONFIGURASI ---
TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = 5845570657
SERVER_URL = "https://bot-tele-u3f8.onrender.com"

# --- FLASK & DB SETUP ---
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'rahasia123')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///bot_content.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
bot = telebot.TeleBot(TOKEN)

# --- DATABASE MODELS ---
class BotConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    welcome_message = db.Column(db.Text, default="Halo! Selamat datang di Toko Digital Pro.")
    payment_info = db.Column(db.Text, default="BCA: 123456\nDana: 08123456")
    admin_telegram_username = db.Column(db.String(50), default="yourFatherkeeper")

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=True)

class PromoConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_active = db.Column(db.Boolean, default=False)
    message = db.Column(db.Text, default="Halo! Jangan lupa cek katalog kami ya!")
    delay = db.Column(db.Integer, default=60) # Detik
    last_run = db.Column(db.Float, default=0.0)

class PromoTarget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.String(50), unique=True)
    type = db.Column(db.String(20)) # 'private' atau 'group'
    name = db.Column(db.String(100))

def get_config():
    config = BotConfig.query.first()
    if not config:
        config = BotConfig()
        db.session.add(config)
        db.session.commit()
    return config

def get_promo_config():
    config = PromoConfig.query.first()
    if not config:
        config = PromoConfig()
        db.session.add(config)
        db.session.commit()
    return config

# --- BACKGROUND PROMO LOOP ---
def run_promo_loop():
    while True:
        try:
            with app.app_context():
                promo = get_promo_config()
                if promo.is_active and (time.time() - promo.last_run) > promo.delay:
                    targets = PromoTarget.query.all()
                    count = 0
                    for target in targets:
                        try:
                            formatted_msg = promo.message.replace("{name}", target.name or "Kak")
                            bot.send_message(target.chat_id, formatted_msg)
                            count += 1
                        except Exception as e:
                            print(f"Gagal kirim ke {target.chat_id}: {e}")
                            # Hapus jika user block bot
                            if "forbidden" in str(e).lower():
                                db.session.delete(target)
                    
                    if count > 0:
                        promo.last_run = time.time()
                        db.session.commit()
                        print(f"Broadcast sukses ke {count} target.")
        except Exception as e:
            print(f"Error Promo Loop: {e}")
        
        time.sleep(10) # Cek setiap 10 detik

# --- LOGIKA BOT ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    # Simpan User ke Database Target
    with app.app_context():
        if not PromoTarget.query.filter_by(chat_id=str(message.chat.id)).first():
            new_target = PromoTarget(
                chat_id=str(message.chat.id),
                type=message.chat.type,
                name=message.from_user.first_name
            )
            db.session.add(new_target)
            db.session.commit()

        config = get_config()
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_katalog = types.InlineKeyboardButton("🛍️ Katalog Produk", callback_data='menu_katalog')
        btn_bayar = types.InlineKeyboardButton("💳 Cara Bayar", callback_data='menu_bayar')
        tele_url = f"https://t.me/{config.admin_telegram_username}"
        btn_admin = types.InlineKeyboardButton("📞 Chat Admin", url=tele_url)
        markup.add(btn_katalog, btn_bayar, btn_admin)
        
        bot.send_message(
            message.chat.id, 
            f"Halo {message.from_user.first_name}!\n\n{config.welcome_message}",
            reply_markup=markup,
            parse_mode="Markdown"
        )

# --- VENOM STYLE MENU ---
@bot.message_handler(commands=['admin', 'menu'])
def admin_menu(message):
    if message.chat.id == ADMIN_ID:
        with app.app_context():
            promo = get_promo_config()
            status_icon = "🟢 ON" if promo.is_active else "🔴 OFF"
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            btn_start = types.InlineKeyboardButton(f"🚀 Mulai Promosi ({status_icon})", callback_data='toggle_promo')
            btn_msg = types.InlineKeyboardButton("📩 Set Pesan", callback_data='set_promo_msg')
            btn_delay = types.InlineKeyboardButton(f"⏱ Atur Jeda ({promo.delay}s)", callback_data='set_promo_delay')
            btn_list = types.InlineKeyboardButton("📂 List Target", callback_data='list_targets')
            markup.add(btn_start)
            markup.add(btn_msg, btn_delay, btn_list)
            
            bot.reply_to(message, "🤖 **PANEL PROMOSI**\n\nSilakan atur broadcast otomatis disini.", reply_markup=markup, parse_mode="Markdown")
    else:
        bot.reply_to(message, "❌ Akses Ditolak.")

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    with app.app_context():
        config = get_config()
        promo = get_promo_config()
        
        if call.data == 'toggle_promo':
            promo.is_active = not promo.is_active
            db.session.commit()
            status = "DIAKTIFKAN 🟢" if promo.is_active else "DIMATIKAN 🔴"
            bot.answer_callback_query(call.id, f"Promosi {status}")
            
            # Refresh Menu
            status_icon = "🟢 ON" if promo.is_active else "🔴 OFF"
            markup = types.InlineKeyboardMarkup(row_width=2)
            btn_start = types.InlineKeyboardButton(f"🚀 Mulai Promosi ({status_icon})", callback_data='toggle_promo')
            btn_msg = types.InlineKeyboardButton("📩 Set Pesan", callback_data='set_promo_msg')
            btn_delay = types.InlineKeyboardButton(f"⏱ Atur Jeda ({promo.delay}s)", callback_data='set_promo_delay')
            btn_list = types.InlineKeyboardButton("📂 List Target", callback_data='list_targets')
            markup.add(btn_start)
            markup.add(btn_msg, btn_delay, btn_list)
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)

        elif call.data == 'set_promo_msg':
            msg = bot.send_message(call.message.chat.id, "Silakan kirim pesan promosi baru (Text/Caption):")
            bot.register_next_step_handler(msg, save_promo_msg)

        elif call.data == 'set_promo_delay':
            msg = bot.send_message(call.message.chat.id, "Masukkan durasi jeda dalam detik (contoh: 60):")
            bot.register_next_step_handler(msg, save_promo_delay)
            
        elif call.data == 'list_targets':
            count = PromoTarget.query.count()
            bot.send_message(call.message.chat.id, f"📊 **Total Target:** {count} User/Grup")

        # --- MENU USER ---
        elif call.data == 'menu_katalog':
            products = Product.query.all()
            markup = types.InlineKeyboardMarkup()
            msg_text = "📜 **KATALOG PRODUK**\n\n"
            if not products:
                msg_text += "_Belum ada produk._"
            else:
                for p in products:
                    msg_text += f"🔹 **{p.name}**\n   Harga: {p.price}\n   Ket: {p.description}\n\n"
            btn_beli = types.InlineKeyboardButton("🛒 Pesan Sekarang", url=f"https://t.me/{config.admin_telegram_username}")
            markup.add(btn_beli)
            bot.send_message(call.message.chat.id, msg_text, reply_markup=markup, parse_mode="Markdown")

        elif call.data == 'menu_bayar':
            bot.send_message(call.message.chat.id, f"🏦 **METODE PEMBAYARAN**\n\n{config.payment_info}")

def save_promo_msg(message):
    with app.app_context():
        promo = get_promo_config()
        promo.message = message.text
        db.session.commit()
        bot.reply_to(message, "✅ Pesan promosi disimpan!")

def save_promo_delay(message):
    try:
        delay = int(message.text)
        with app.app_context():
            promo = get_promo_config()
            promo.delay = delay
            db.session.commit()
            bot.reply_to(message, f"✅ Jeda diatur ke {delay} detik.")
    except:
        bot.reply_to(message, "❌ Harap masukkan angka.")

# --- FLASK ROUTES (CMS) ---

@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == os.environ.get('ADMIN_PASSWORD', 'admin123'):
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Wrong Password!")
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    config = get_config()
    promo = get_promo_config()
    products = Product.query.all()
    targets_count = PromoTarget.query.count()
    return render_template('dashboard.html', config=config, products=products, promo=promo, targets_count=targets_count)

@app.route('/update_config', methods=['POST'])
def update_config():
    if not session.get('logged_in'): return redirect(url_for('login'))
    config = get_config()
    config.welcome_message = request.form.get('welcome_message')
    config.payment_info = request.form.get('payment_info')
    config.admin_telegram_username = request.form.get('admin_telegram_username').replace('@', '')
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/update_promo', methods=['POST'])
def update_promo():
    if not session.get('logged_in'): return redirect(url_for('login'))
    promo = get_promo_config()
    promo.message = request.form.get('message')
    promo.delay = int(request.form.get('delay'))
    promo.is_active = 'is_active' in request.form
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/add_product', methods=['POST'])
def add_product():
    if not session.get('logged_in'): return redirect(url_for('login'))
    db.session.add(Product(name=request.form.get('name'), price=request.form.get('price'), description=request.form.get('description')))
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/delete_product/<int:id>', methods=['POST'])
def delete_product(id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    product = Product.query.get(id)
    if product:
        db.session.delete(product)
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/' + TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

@app.route("/")
def index():
    bot.remove_webhook()
    bot.set_webhook(url=SERVER_URL + "/" + TOKEN)
    return redirect(url_for('login'))

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    # Jalankan Loop Promosi di Background Thread
    t_promo = Thread(target=run_promo_loop)
    t_promo.daemon = True
    t_promo.start()

    if os.environ.get('PORT'):
        app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
    else:
        print("Bot berjalan di mode Local...")
        bot.remove_webhook()
        bot.infinity_polling()