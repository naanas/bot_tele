import telebot
from telebot import types
import json
from flask import Flask, request, render_template, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
import os
from dotenv import load_dotenv
load_dotenv() # Load local .env if exists

import time
from datetime import datetime, timedelta
from threading import Thread

# --- KONFIGURASI ---
TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = 5845570657 # ID Super Admin (Owner)
SERVER_URL = "https://bot-tele-u3f8.onrender.com"

# --- FLASK & DB SETUP ---
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'rahasia123')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///bot_content.db').replace("postgres://", "postgresql://")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
bot = telebot.TeleBot(TOKEN)

# --- DATABASE MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(50), nullable=False)
    telegram_id = db.Column(db.String(50), nullable=True) # Untuk akses bot
    role = db.Column(db.String(10), default='user') # 'owner' or 'user'
    active_until = db.Column(db.DateTime, nullable=True) # Masa aktif
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    # Relasi ke PromoConfig
    promo = db.relationship('PromoConfig', backref='user', uselist=False, cascade="all, delete-orphan")

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
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=False)
    message = db.Column(db.Text, default="Halo! Cek promo kami.")
    delay = db.Column(db.Integer, default=60)
    last_run = db.Column(db.Float, default=0.0)
    targets_filter = db.Column(db.String(20), default="all") # 'all', 'group', 'private', 'specific'
    specific_groups = db.Column(db.Text, default="[]") # JSON list of chat_ids
    batch_offset = db.Column(db.Integer, default=0) # Round Robin Paging

class PromoTarget(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.String(50), unique=True)
    type = db.Column(db.String(20)) # 'private' atau 'group'
    name = db.Column(db.String(100))

# --- HELPERS ---
def get_config():
    config = BotConfig.query.first()
    if not config:
        config = BotConfig()
        db.session.add(config)
        db.session.commit()
    return config

def init_owner():
    # Pastikan ada user Owner default
    owner = User.query.filter_by(role='owner').first()
    if not owner:
        owner = User(username='admin', password='admin123', role='owner', active_until=datetime.now() + timedelta(days=3650))
        db.session.add(owner)
        db.session.commit()
        # Create promo config for owner
        db.session.add(PromoConfig(user_id=owner.id))
        db.session.commit()

# --- BACKGROUND PROMO LOOP (SMART BATCHING | ROUND ROBIN) ---
def run_promo_loop():
    BATCH_SIZE = 20
    while True:
        try:
            with app.app_context():
                # Ambil semua user yang aktif dan masa aktif belum habis
                active_users = User.query.filter(User.active_until > datetime.now()).all()
                
                for user in active_users:
                    if user.promo and user.promo.is_active:
                        promo = user.promo
                        
                        # Cek Delay (Time-based regulation)
                        if (time.time() - promo.last_run) > promo.delay:
                            targets = []
                            query = PromoTarget.query
                            
                            # Apply Filters
                            if promo.targets_filter == 'group':
                                query = query.filter_by(type='group')
                            elif promo.targets_filter == 'private':
                                query = query.filter_by(type='private')
                            elif promo.targets_filter == 'specific':
                                try:
                                    selected_ids = json.loads(promo.specific_groups)
                                    selected_ids = [str(i) for i in selected_ids]
                                    query = query.filter(PromoTarget.chat_id.in_(selected_ids))
                                except: pass # If error, default to empty query or handle safely
                            
                            # Smart Paging (Offset & Limit)
                            # Get batch of targets based on saved offset
                            targets = query.offset(promo.batch_offset).limit(BATCH_SIZE).all()
                            
                            if not targets:
                                # Jika tidak ada target (sudah habis), reset ke 0 untuk loop berikutnya
                                promo.batch_offset = 0
                                db.session.commit()
                                continue

                            count = 0
                            for target in targets:
                                try:
                                    formatted_msg = promo.message.replace("{name}", target.name or "Kak")
                                    bot.send_message(target.chat_id, formatted_msg)
                                    count += 1
                                    time.sleep(0.05) # Fast local sleep, relying on global delay
                                except Exception as e:
                                    if "forbidden" in str(e).lower():
                                        db.session.delete(target)
                            
                            if count > 0:
                                # Update Offset & Timestamp
                                promo.batch_offset += count
                                promo.last_run = time.time()
                                db.session.commit()
                                print(f"User {user.username}: Sent Batch {count} msgs. (Offset: {promo.batch_offset})")
            
        except Exception as e:
            print(f"Error Promo Loop: {e}")
        
        time.sleep(5) # Global Loop Delay

# --- LOGIKA BOT ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    with app.app_context():
        # Save Target
        if not PromoTarget.query.filter_by(chat_id=str(message.chat.id)).first():
            db.session.add(PromoTarget(chat_id=str(message.chat.id), type=message.chat.type, name=message.from_user.first_name))
            db.session.commit()

        config = get_config()
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_katalog = types.InlineKeyboardButton("🛍️ Katalog Produk", callback_data='menu_katalog')
        btn_bayar = types.InlineKeyboardButton("💳 Cara Bayar", callback_data='menu_bayar')
        tele_url = f"https://t.me/{config.admin_telegram_username}"
        btn_admin = types.InlineKeyboardButton("📞 Chat Admin", url=tele_url)
        markup.add(btn_katalog, btn_bayar, btn_admin)
        
        bot.send_message(message.chat.id, f"Halo {message.from_user.first_name}!\n\n{config.welcome_message}", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['admin', 'menu'])
def admin_menu(message):
    chat_id = str(message.chat.id)
    with app.app_context():
        # 1. Cek apakah ini Super Admin (Hardcoded)
        is_hardcoded_admin = (chat_id == str(ADMIN_ID))
        
        user = User.query.filter_by(telegram_id=chat_id).first()
        
        # Auto-Link Owner ID if valid Admin but not linked
        if is_hardcoded_admin:
            owner_db = User.query.filter_by(role='owner').first()
            if owner_db:
                if owner_db.telegram_id != chat_id:
                    owner_db.telegram_id = chat_id
                    db.session.commit()
                user = owner_db # Set user context to owner
                
                # Ensure Promo Config Exists
                if not user.promo:
                    db.session.add(PromoConfig(user_id=user.id))
                    db.session.commit()

        # 2. Validasi Akses
        if user and user.active_until and user.active_until > datetime.now():
             target_promo = user.promo
             
             if target_promo:
                status_icon = "🟢 ON" if target_promo.is_active else "🔴 OFF"
                markup = types.InlineKeyboardMarkup(row_width=2)
                
                # Main Controls
                markup.add(types.InlineKeyboardButton(f"🚀 Mulai ({status_icon})", callback_data='toggle_promo'))
                markup.add(types.InlineKeyboardButton("📩 Set Pesan", callback_data='set_promo_msg'), 
                           types.InlineKeyboardButton(f"⏱ Jeda ({target_promo.delay}s)", callback_data='set_promo_delay'))
                
                # Target Controls
                filter_label = target_promo.targets_filter.upper()
                markup.add(types.InlineKeyboardButton(f"🎯 Target: {filter_label}", callback_data='toggle_filter'))
                if target_promo.targets_filter == 'specific':
                     markup.add(types.InlineKeyboardButton("⚙️ Pilih Group", callback_data='select_groups'))

                info_text = f"🤖 **BROADCAST PANEL**\nStatus: {status_icon}\nTarget: {filter_label}\n"
                info_text += f"👤 **Client: {user.username}**\n"
                info_text += f"📅 Expired: {user.active_until.strftime('%Y-%m-%d')}\n"
                
                # Tambahan Menu Owner
                if user.role == 'owner':
                    markup.add(types.InlineKeyboardButton("👥 Manage Users (SaaS)", callback_data='manage_users'))

                bot.reply_to(message, info_text, reply_markup=markup, parse_mode="Markdown")
             else:
                 bot.reply_to(message, "⚠️ Akun aktif tapi konfigurasi error. (Hubungi Dev)")
        else:
             # Akses Ditolak
             bot.reply_to(message, f"❌ **Akses Ditolak**\n\nID Kamu: `{chat_id}`\nAdmin ID Terdaftar: `{ADMIN_ID}`\n\nJika kamu Owner, pastikan `ADMIN_ID` di `app.py` sudah benar.", parse_mode="Markdown")

# ... (get_current_promo_from_context, add_user_bot, cek_id... stay same) ...
# We need to insert the NEW handle_query logic (Target Management) BEFORE existing 'manage_users'

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    with app.app_context():
        config = get_config()
        
        # --- TARGET MANAGEMENT ---
        if call.data == 'toggle_filter':
            promo = get_current_promo_from_context(call.message.chat.id)
            if promo:
                modes = ['all', 'group', 'private', 'specific']
                current_idx = modes.index(promo.targets_filter)
                next_mode = modes[(current_idx + 1) % len(modes)]
                promo.targets_filter = next_mode
                db.session.commit()
                # Refresh Menu (Resend admin menu logic)
                bot.send_message(call.message.chat.id, f"✅ Mode Target: **{next_mode.upper()}**\nKetik `/menu` untuk refresh.", parse_mode="Markdown")
                return

        elif call.data == 'select_groups':
            promo = get_current_promo_from_context(call.message.chat.id)
            if not promo: return
            
            groups = PromoTarget.query.filter_by(type='group').all()
            if not groups: 
                bot.answer_callback_query(call.id, "Belum ada Grup terdata.")
                return

            markup = types.InlineKeyboardMarkup(row_width=1)
            selected = []
            try: selected = json.loads(promo.specific_groups)
            except: selected = []

            for g in groups:
                icon = "✅" if str(g.chat_id) in selected else "❌"
                markup.add(types.InlineKeyboardButton(f"{icon} {g.name}", callback_data=f"tgt_{g.chat_id}"))
            
            markup.add(types.InlineKeyboardButton("✅ Selesai", callback_data='back_to_menu'))
            bot.send_message(call.message.chat.id, "🎯 **PILIH GROUP TARGET**:\nKlik untuk toggle.", reply_markup=markup, parse_mode="Markdown")
            return

        elif call.data.startswith('tgt_'):
            promo = get_current_promo_from_context(call.message.chat.id)
            if promo:
                chat_id = call.data.split('_')[1]
                selected = []
                try: selected = json.loads(promo.specific_groups)
                except: selected = []
                
                # Toggle
                if chat_id in selected: selected.remove(chat_id)
                else: selected.append(chat_id)
                
                promo.specific_groups = json.dumps(selected)
                db.session.commit()
                
                # Refresh List UI
                groups = PromoTarget.query.filter_by(type='group').all()
                markup = types.InlineKeyboardMarkup(row_width=1)
                for g in groups:
                    icon = "✅" if str(g.chat_id) in selected else "❌"
                    markup.add(types.InlineKeyboardButton(f"{icon} {g.name}", callback_data=f"tgt_{g.chat_id}"))
                markup.add(types.InlineKeyboardButton("✅ Selesai", callback_data='back_to_menu'))
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
            return

        # --- SAAS MANAGEMENT ---
        if call.data == 'manage_users':
            # Cek Auth Owner
            is_owner = str(call.message.chat.id) == str(ADMIN_ID)
            if not is_owner:
                u = User.query.filter_by(telegram_id=str(call.message.chat.id)).first()
                if u and u.role == 'owner': is_owner = True
            
            if not is_owner:
                return bot.answer_callback_query(call.id, "Access Denied")

            users = User.query.filter(User.role != 'owner').all()
            msg = "👥 **DAFTAR KLIEN BROADCAST**\n\n"
            markup = types.InlineKeyboardMarkup(row_width=2)
            
            if not users:
                msg += "_Belum ada klien._\n"
            else:
                for u in users:
                    status = "🟢" if u.active_until > datetime.now() else "🔴"
                    msg += f"{status} **{u.username}** (Exp: {u.active_until.strftime('%d-%m-%Y')})\n"
                    # Add delete button per user
                    markup.add(types.InlineKeyboardButton(f"🗑️ Hapus {u.username}", callback_data=f"del_u_{u.id}"))
            
            msg += "\n➕ **Tambah Klien:**\n`/add_user <Nama> <ID> <Hari>`"
            
            # Back button
            markup.add(types.InlineKeyboardButton("🔙 Kembali", callback_data='back_to_menu'))
            bot.send_message(call.message.chat.id, msg, reply_markup=markup, parse_mode="Markdown")
            return

        elif call.data.startswith('del_u_'):
            user_id = int(call.data.split('_')[2])
            u = User.query.get(user_id)
            if u:
                name = u.username
                db.session.delete(u)
                db.session.commit()
                bot.answer_callback_query(call.id, f"Client {name} dihapus.")
                bot.send_message(call.message.chat.id, f"✅ Client **{name}** telah dihapus.", parse_mode="Markdown")
            else:
                bot.answer_callback_query(call.id, "User tidak ditemukan.")
            return

        elif call.data == 'back_to_menu':
            bot.delete_message(call.message.chat.id, call.message.message_id)
            return

        # --- PROMO LOGIC ---
        if call.data in ['toggle_promo', 'set_promo_msg', 'set_promo_delay']:
            promo = get_current_promo_from_context(call.message.chat.id)
            if not promo:
                bot.answer_callback_query(call.id, "Akses ditolak.")
                return

            if call.data == 'toggle_promo':
                promo.is_active = not promo.is_active
                db.session.commit()
                status = "DIAKTIFKAN" if promo.is_active else "DIMATIKAN"
                bot.answer_callback_query(call.id, f"Promo {status}")
                bot.send_message(call.message.chat.id, f"✅ Promosi berhasil {status}")

            elif call.data == 'set_promo_msg':
                msg = bot.send_message(call.message.chat.id, "Kirim pesan promosi baru:")
                bot.register_next_step_handler(msg, save_promo_msg_bot)

            elif call.data == 'set_promo_delay':
                msg = bot.send_message(call.message.chat.id, "Masukkan durasi jeda (detik):")
                bot.register_next_step_handler(msg, save_promo_delay_bot)

        # Menu Public
        elif call.data == 'menu_katalog':
            products = Product.query.all()
            markup = types.InlineKeyboardMarkup()
            msg_text = "📜 **KATALOG**\n\n" + ("\n".join([f"🔹 {p.name} - {p.price}" for p in products]) if products else "Kosong")
            markup.add(types.InlineKeyboardButton("Admin", url=f"https://t.me/{config.admin_telegram_username}"))
            bot.send_message(call.message.chat.id, msg_text, reply_markup=markup)
        
        elif call.data == 'menu_bayar':
            bot.send_message(call.message.chat.id, config.payment_info)

def save_promo_msg_bot(message):
    with app.app_context():
        promo = get_current_promo_from_context(message.chat.id)
        if promo:
            promo.message = message.text
            db.session.commit()
            bot.reply_to(message, "✅ Pesan tersimpan.")

def save_promo_delay_bot(message):
    try:
        val = int(message.text)
        with app.app_context():
            promo = get_current_promo_from_context(message.chat.id)
            if promo:
                promo.delay = val
                db.session.commit()
                bot.reply_to(message, "✅ Jeda tersimpan.")
    except: pass

# --- FLASK ROUTES (CMS) ---
@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        # STRICT OWNER ONLY
        if user and user.password == password and user.role == 'owner':
            session['user_id'] = user.id
            session['role'] = user.role
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Login Gagal / Hanya Owner yang bisa akses CMS!")
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    config = get_config()
    products = Product.query.all()
    
    # Data for Owner
    all_users = []
    if user.role == 'owner':
        all_users = User.query.all()
        
    return render_template('dashboard.html', user=user, config=config, products=products, all_users=all_users, targets_count=PromoTarget.query.count(), now=datetime.now())

# Routes Management User (Owner Only)
@app.route('/user/add', methods=['POST'])
def add_user():
    if session.get('role') != 'owner': return "Access Denied"
    
    username = request.form.get('username') # Name Label
    tele_id = request.form.get('telegram_id')
    days = int(request.form.get('days', 30))
    
    # Cek Duplicate
    if User.query.filter((User.username == username) | (User.telegram_id == tele_id)).first():
         flash('Username/ID sudah ada!') # Flash need secret key
         return redirect(url_for('dashboard'))
         
    new_user = User(
        username=username, 
        password="client_no_login", # Dummy
        telegram_id=tele_id, 
        role='user',
        active_until=datetime.now() + timedelta(days=days)
    )
    db.session.add(new_user)
    db.session.commit()
    # Create Promo Config for new user
    db.session.add(PromoConfig(user_id=new_user.id))
    db.session.commit()
    
    return redirect(url_for('dashboard'))

@app.route('/user/delete/<int:id>')
def delete_user(id):
    if session.get('role') != 'owner': return "Access Denied"
    u = User.query.get(id)
    if u and u.role != 'owner':
        db.session.delete(u)
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/update_promo', methods=['POST'])
def update_promo():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    
    user.promo.message = request.form.get('message')
    user.promo.delay = int(request.form.get('delay'))
    user.promo.is_active = 'is_active' in request.form
    user.promo.targets_filter = request.form.get('targets_filter', 'all')
    db.session.commit()
    return redirect(url_for('dashboard'))

# ... (Product & Config routes similar as before, check role if needed) ...
# For brevity, keeping basic Update Config routes:
@app.route('/update_config', methods=['POST'])
def update_config():
    if session.get('role') != 'owner': return "Access Denied" # Only owner changes global config
    config = get_config()
    config.welcome_message = request.form.get('welcome_message')
    config.payment_info = request.form.get('payment_info')
    config.admin_telegram_username = request.form.get('admin_telegram_username').replace('@', '')
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/add_product', methods=['POST'])
def add_product():
    if session.get('role') != 'owner': return "Access Denied"
    db.session.add(Product(name=request.form.get('name'), price=request.form.get('price'), description=request.form.get('description')))
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/delete_product/<int:id>', methods=['POST'])
def delete_product(id):
    if session.get('role') != 'owner': return "Access Denied"
    product = Product.query.get(id)
    db.session.delete(product)
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/' + TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

@app.route("/")
def index():
    return redirect(url_for('login'))

with app.app_context():
    db.create_all()
    init_owner() # Create default admin if not exists

if __name__ == "__main__":
    t_promo = Thread(target=run_promo_loop)
    t_promo.daemon = True
    t_promo.start()
    
    if os.environ.get('PORT'):
        app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
    else:
        bot.remove_webhook()
        bot.infinity_polling()