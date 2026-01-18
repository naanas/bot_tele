from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from pyrogram import Client, filters, enums
from dotenv import load_dotenv
import asyncio
import threading
import json
import time
import os
from datetime import datetime, timedelta

load_dotenv()

# --- CONFIG ---
API_ID = os.environ.get("API_ID", "2040") 
API_HASH = os.environ.get("API_HASH", "b18441a1bb60760f5")
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///userbot.db").replace("postgres://", "postgresql://")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secret")
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(50))
    session_string = db.Column(db.Text)
    role = db.Column(db.String(10), default='user')
    authorized_admins = db.Column(db.Text, default='[]')
    active_until = db.Column(db.DateTime)
    promo = db.relationship('PromoConfig', backref='user', uselist=False, cascade="all, delete-orphan")

class PromoConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=False)
    delay = db.Column(db.Integer, default=240)
    last_run = db.Column(db.Float, default=0.0)
    msg_type = db.Column(db.String(20), default='text') 
    message_text = db.Column(db.Text, default="Halo!")
    saved_message_id = db.Column(db.Integer) 
    forward_link = db.Column(db.Text)
    target_mode = db.Column(db.String(20), default='list')
    target_list = db.Column(db.Text, default='[]')
    batch_offset = db.Column(db.Integer, default=0)
    watermark = db.Column(db.Text)
    permit_mode = db.Column(db.Boolean, default=False)
    permit_text = db.Column(db.Text, default="PM Protected.")
    timer_mode = db.Column(db.String(10), default='none')
    timer_data = db.Column(db.Text)

# --- USERBOT MANAGER (ASYNC) ---
clients = {} # {user_id: Client}

async def start_client(user):
    if not user.session_string: return
    try:
        app_client = Client(
            f"user_{user.id}",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=user.session_string,
            in_memory=True
        )
        
        # --- COMMANDS ---
        @app_client.on_message(filters.me & filters.command("on", prefixes="."))
        async def cmd_on(c, m):
            with app.app_context():
                # Re-fetch within context
                u = User.query.get(user.id)
                if u and u.promo:
                     u.promo.is_active = True
                     db.session.commit()
            await m.edit("✅ **Broadcast Aktif**")

        @app_client.on_message(filters.me & filters.command("off", prefixes="."))
        async def cmd_off(c, m):
            with app.app_context():
                u = User.query.get(user.id)
                if u and u.promo:
                    u.promo.is_active = False
                    db.session.commit()
            await m.edit("🔴 **Broadcast Nonaktif**")

        @app_client.on_message(filters.me & filters.command("jeda", prefixes="."))
        async def cmd_jeda(c, m):
            try:
                val = int(m.command[1])
                with app.app_context():
                    u = User.query.get(user.id)
                    if u and u.promo:
                        u.promo.delay = val
                        db.session.commit()
                await m.edit(f"⏱ **Jeda diatur:** {val} detik")
            except: await m.edit("❌ Format: `.jeda 240`")
            
        @app_client.on_message(filters.me & filters.command("basic", prefixes="."))
        async def cmd_basic(c, m):
            if not m.reply_to_message:
                return await m.edit("❌ Reply pesan yang mau disimpan.")
            
            # Forward to Self
            fwd = await m.reply_to_message.forward("me")
            
            with app.app_context():
                u = User.query.get(user.id)
                if u and u.promo:
                    u.promo.msg_type = 'basic'
                    u.promo.saved_message_id = fwd.id
                    db.session.commit()
            await m.edit("✅ **Pesan Basic Disimpan!**")

        @app_client.on_message(filters.me & filters.command("watermark", prefixes="."))
        async def cmd_wm(c, m):
            text = " ".join(m.command[1:]) if len(m.command) > 1 else ""
            if not text: return await m.edit("❌ Format: `.watermark teks` / `.watermark off`")
            
            val = None if text.lower() == 'off' else text
            with app.app_context():
                u = User.query.get(user.id)
                if u and u.promo:
                    u.promo.watermark = val
                    db.session.commit()
            status = "Dihapus" if not val else val
            await m.edit(f"🎨 **Watermark:** {status}")

        @app_client.on_message(filters.me & filters.command("cekgrup", prefixes="."))
        async def cmd_cekgrup(c, m):
            await m.edit("🔄 **Scanning Groups...**")
            msg_text = "📂 **DAFTAR GRUP:**\n\n"
            i = 1
            async for dialog in c.get_dialogs():
                if dialog.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
                    msg_text += f"{i}. {dialog.chat.title} (`{dialog.chat.id}`)\n"
                    i += 1
            
            if len(msg_text) > 4000: msg_text = msg_text[:4000] + "\n...(terpotong)"
            await m.reply(msg_text)

        @app_client.on_message(filters.me & filters.command("setgrup", prefixes="."))
        async def cmd_setgrup(c, m):
            if len(m.command) < 2: return await m.edit("❌ Format: `.setgrup ID1,ID2` atau `.setgrup all`")
            args = m.command[1]
            
            final_list = []
            if args == 'all':
                async for dialog in c.get_dialogs():
                    if dialog.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
                        final_list.append(dialog.chat.id)
            else:
                try:
                    final_list = [int(x) for x in args.split(',')]
                except: return await m.edit("❌ ID harus angka, pisahkan koma.")
            
            with app.app_context():
                u = User.query.get(user.id)
                if u and u.promo:
                    u.promo.target_list = json.dumps(final_list)
                    u.promo.target_mode = 'list'
                    db.session.commit()
            await m.edit(f"✅ **{len(final_list)} Grup Disimpan!**")

        await app_client.start()
        clients[user.id] = app_client
        print(f"User {user.username} (ID: {user.id}) Started!")
        
    except Exception as e:
        print(f"Failed to start {user.username}: {e}")

async def broadcast_loop():
    while True:
        try:
            with app.app_context():
                # Only fetch active users
                active_users = User.query.filter(User.session_string != None).all()
                for user in active_users:
                    if user.id in clients and user.promo and user.promo.is_active:
                        
                        client = clients[user.id]
                        promo = user.promo
                        
                        if (time.time() - promo.last_run) > promo.delay:
                            # 1. Get Targets
                            targets = []
                            try: targets = json.loads(promo.target_list)
                            except: targets = []
                            
                            if not targets: continue
                            
                            # 2. Round Robin
                            if promo.batch_offset >= len(targets): promo.batch_offset = 0
                            target_id = targets[promo.batch_offset]
                            
                            # 3. Send
                            try:
                                if promo.msg_type == 'basic' and promo.saved_message_id:
                                    msg = await client.get_messages("me", promo.saved_message_id)
                                    if msg:
                                        caption = msg.caption or msg.text or ""
                                        if promo.watermark: caption += f"\n\n{promo.watermark}"
                                        
                                        # Copy message (supports text & media)
                                        await msg.copy(target_id, caption=caption)
                                        print(f"User {user.username} -> {target_id} OK")
                                else:
                                    # Fallback Text
                                    txt = promo.message_text
                                    if promo.watermark: txt += f"\n\n{promo.watermark}"
                                    await client.send_message(target_id, txt)
                            except Exception as e:
                                print(f"Fail {user.username} -> {target_id}: {e}")
                            
                            # 4. Update State
                            promo.batch_offset += 1
                            promo.last_run = time.time()
                            db.session.commit()

        except Exception as e:
            print(f"Broadcast Loop Error: {e}")
            
        await asyncio.sleep(5)

def run_async_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Init Clients for existing users
    with app.app_context():
        # Ensure tables
        db.create_all()
        
        users = User.query.filter(User.session_string != None).all()
        for u in users:
            loop.create_task(start_client(u))
    
    loop.run_until_complete(broadcast_loop())

# --- FLASK ROUTES ---
@app.route('/')
def index():
    return "Userbot SaaS System Active. <br> Run /gen_session.py locally to get string."

@app.route('/admin/login')
def admin_login():
    return "Dashboard Not Yet Implemented for Userbot Mode. Use Telegram Commands."

# Silence old webhook errors
@app.route('/<path:path>', methods=['GET', 'POST', 'HEAD'])
def catch_all(path):
    return "OK"

if __name__ == "__main__":
    # Start Userbot Loop in Background
    t = threading.Thread(target=run_async_loop)
    t.daemon = True
    t.start()
    
    # Start Flask
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)