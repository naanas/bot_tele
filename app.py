import telebot
from telebot import types
from flask import Flask, request, render_template, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
import os
from threading import Thread

# --- KONFIGURASI ---
TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = 5845570657
# URL Render (untuk Webhook)
SERVER_URL = "https://bot-tele-u3f8.onrender.com"

# --- FLASK & DB SETUP ---
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'rahasia123') # Ganti di production!
# Gunakan SQLite file. Di Render Free Tier ini akan reset tiap deploy. 
# Untuk storage permanen, ganti string ini dengan URL PostgreSQL dari Render.
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///bot_content.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
bot = telebot.TeleBot(TOKEN)

# --- DATABASE MODELS ---
class BotConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    welcome_message = db.Column(db.Text, default="Halo! Selamat datang di Toko Digital Pro.")
    payment_info = db.Column(db.Text, default="BCA: 123456\nDana: 08123456")
    wa_number = db.Column(db.String(20), default="6282131077460")
    wa_template = db.Column(db.String(100), default="Halo Admin, saya mau pesan.")

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=True)

# Helper untuk mendapatkan config (Singleton pattern sederhana)
def get_config():
    config = BotConfig.query.first()
    if not config:
        config = BotConfig()
        db.session.add(config)
        db.session.commit()
    return config

# --- LOGIKA BOT (DYNAMIC CONTENT) ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    with app.app_context(): # Butuh context karena akses DB di thread berbeda
        config = get_config()
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_katalog = types.InlineKeyboardButton("🛍️ Katalog Produk", callback_data='menu_katalog')
        btn_bayar = types.InlineKeyboardButton("💳 Cara Bayar", callback_data='menu_bayar')
        
        # WA Link Dinamis
        wa_url = f"https://wa.me/{config.wa_number}?text={config.wa_template.replace(' ', '%20')}"
        btn_admin = types.InlineKeyboardButton("📞 Chat Admin (WA)", url=wa_url)
        
        markup.add(btn_katalog, btn_bayar, btn_admin)
        
        bot.send_message(
            message.chat.id, 
            f"Halo {message.from_user.first_name}!\n\n{config.welcome_message}",
            reply_markup=markup,
            parse_mode="Markdown"
        )

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    with app.app_context():
        config = get_config()
        
        if call.data == 'menu_katalog':
            products = Product.query.all()
            markup = types.InlineKeyboardMarkup()
            
            msg_text = "📜 **KATALOG PRODUK**\n\n"
            if not products:
                msg_text += "_Belum ada produk yang ditambahkan._"
            else:
                for p in products:
                    msg_text += f"🔹 **{p.name}**\n   Harga: {p.price}\n   Ket: {p.description}\n\n"
            
            btn_beli = types.InlineKeyboardButton("🛒 Pesan Sekarang (WA)", url=f"https://wa.me/{config.wa_number}?text=Halo%20Admin%20saya%20mau%20pesan%20produk")
            markup.add(btn_beli)
            
            bot.send_message(call.message.chat.id, msg_text, reply_markup=markup, parse_mode="Markdown")

        elif call.data == 'menu_bayar':
            bot.send_message(
                call.message.chat.id,
                f"🏦 **METODE PEMBAYARAN**\n\n{config.payment_info}\n\n_Segera konfirmasi setelah transfer!_"
            )

        elif call.data == 'order_bot':
            # Ini logika lama, mungkin tidak terpakai jika tombol order direct ke WA, tapi tetap disimpan
            bot.answer_callback_query(call.id, "Silakan chat admin via WA!")

# --- FLASK ROUTES (CMS) ---

@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        # Password hardcoded sederhana (Ganti dengan Env Var di production!)
        if password == os.environ.get('ADMIN_PASSWORD', 'admin123'):
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Wrong Password!")
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    config = get_config()
    products = Product.query.all()
    return render_template('dashboard.html', config=config, products=products)

@app.route('/update_config', methods=['POST'])
def update_config():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    config = get_config()
    config.welcome_message = request.form.get('welcome_message')
    config.payment_info = request.form.get('payment_info')
    config.wa_number = request.form.get('wa_number')
    config.wa_template = request.form.get('wa_template')
    
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/add_product', methods=['POST'])
def add_product():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    name = request.form.get('name')
    price = request.form.get('price')
    desc = request.form.get('description')
    
    new_product = Product(name=name, price=price, description=desc)
    db.session.add(new_product)
    db.session.commit()
    
    return redirect(url_for('dashboard'))

@app.route('/delete_product/<int:id>', methods=['POST'])
def delete_product(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    product = Product.query.get(id)
    if product:
        db.session.delete(product)
        db.session.commit()
    
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# --- WEBHOOK SETUP ---
@app.route('/' + TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

@app.route("/")
def index():
    # Setup Webhook otomatis saat halaman utama dibuka
    bot.remove_webhook()
    bot.set_webhook(url=SERVER_URL + "/" + TOKEN)
    return redirect(url_for('login')) # Redirect ke login page

# --- INIT DB ---
# Membuat tabel jika belum ada
with app.app_context():
    db.create_all()

# --- EKSEKUSI ---
if __name__ == "__main__":
    if os.environ.get('PORT'):
        port = int(os.environ.get('PORT', 5000))
        app.run(host="0.0.0.0", port=port)
    else:
        print("Bot berjalan di mode Local (Polling)...")
        bot.remove_webhook()
        bot.infinity_polling()