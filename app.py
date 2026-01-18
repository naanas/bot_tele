import os
import time
import json
import asyncio
import threading
from datetime import datetime
from dotenv import load_dotenv

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait, PeerIdInvalid

# --- INITIALIZATION ---
load_dotenv()
app = Flask(__name__)

# Config
API_ID = os.environ.get("API_ID", "2040")
API_HASH = os.environ.get("API_HASH", "b18441a1bb60760f5")
# Handle Render/Supabase Postgres URL fix
db_url = os.environ.get("DATABASE_URL", "sqlite:///userbot.db")
if "postgres://" in db_url:
    db_url = db_url.replace("postgres://", "postgresql://")

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- DATABASE MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    # Password & role kept for legacy schema compatibility, though unused in No-CMS
    password = db.Column(db.String(50), default='123456')
    role = db.Column(db.String(10), default='user') 
    
    session_string = db.Column(db.Text)
    authorized_admins = db.Column(db.Text, default='[]') # JSON List of IDs
    active_until = db.Column(db.DateTime)
    
    promo = db.relationship('PromoConfig', backref='user', uselist=False, cascade="all, delete-orphan")

class PromoConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Broadcast Control
    is_active = db.Column(db.Boolean, default=False)
    delay = db.Column(db.Integer, default=240)
    last_run = db.Column(db.Float, default=0.0)
    
    # Content
    msg_type = db.Column(db.String(20), default='text') # 'text', 'basic'
    message_text = db.Column(db.Text, default="Halo! Selamat siang.")
    saved_message_id = db.Column(db.Integer) # ID from Saved Messages
    forward_link = db.Column(db.Text)
    watermark = db.Column(db.Text)
    
    # Targeting
    target_mode = db.Column(db.String(20), default='list') # 'list', 'all'
    target_list = db.Column(db.Text, default='[]') # JSON List of Chat IDs
    batch_offset = db.Column(db.Integer, default=0)
    
    # Features
    permit_mode = db.Column(db.Boolean, default=False)
    permit_text = db.Column(db.Text, default="[AUTO] Pesan anda terbaca tapi saya sedang sibuk.")
    timer_mode = db.Column(db.String(10), default='none')
    timer_data = db.Column(db.Text)

# --- USERBOT LOGIC ---
clients = {} # Cache active clients: {user_id: Client}

def get_db_safe():
    # Helper to get fresh DB session in threads
    with app.app_context():
        return db.session

async def start_client(user_id, session_str):
    if not session_str: return
    
    c = Client(f"user_{user_id}", api_id=API_ID, api_hash=API_HASH, session_string=session_str, in_memory=True)
    
    # --- HANDLERS (PLUGIN) ---
    
    # 1. CONTROL (.on, .off, .jeda)
    @c.on_message(filters.me & filters.command("on", prefixes="."))
    async def h_on(client, m):
        with app.app_context():
            u = User.query.get(user_id)
            if u and u.promo:
                u.promo.is_active = True
                db.session.commit()
        await m.edit("✅ **Broadcast: ON**")

    @c.on_message(filters.me & filters.command("off", prefixes="."))
    async def h_off(client, m):
        with app.app_context():
            u = User.query.get(user_id)
            if u and u.promo:
                u.promo.is_active = False
                db.session.commit()
        await m.edit("🔴 **Broadcast: OFF**")

    @c.on_message(filters.me & filters.command("jeda", prefixes="."))
    async def h_jeda(client, m):
        try:
            val = int(m.command[1])
            with app.app_context():
                User.query.get(user_id).promo.delay = val
                db.session.commit()
            await m.edit(f"⏱ **Jeda:** {val} detik")
        except: await m.edit("❌ `.jeda <angka>`")

    # 2. CONTENT (.basic, .watermark, .cekpesan)
    @c.on_message(filters.me & filters.command("basic", prefixes="."))
    async def h_basic(client, m):
        if not m.reply_to_message: return await m.edit("❌ Reply pesan dulu.")
        fwd = await m.reply_to_message.forward("me")
        with app.app_context():
            u = User.query.get(user_id)
            u.promo.msg_type = 'basic'
            u.promo.saved_message_id = fwd.id
            db.session.commit()
        await m.edit("✅ **Pesan Disimpan (Basic)**")

    @c.on_message(filters.me & filters.command("watermark", prefixes="."))
    async def h_wm(client, m):
        txt = " ".join(m.command[1:])
        val = None if txt.lower() == 'off' else txt
        with app.app_context():
            User.query.get(user_id).promo.watermark = val
            db.session.commit()
        await m.edit(f"🎨 **Watermark:** {val if val else 'OFF'}")

    @c.on_message(filters.me & filters.command("cekpesan", prefixes="."))
    async def h_cek(client, m):
        with app.app_context():
            p = User.query.get(user_id).promo
            if p.msg_type == 'basic' and p.saved_message_id:
                try:
                    await client.copy_message(m.chat.id, "me", p.saved_message_id, caption="👁️ **Preview Pesan**")
                except: await m.edit("❌ Pesan tersimpan tidak ditemukan (mungkin terhapus).")
            else:
                await m.edit(f"📝 **Teks:**\n{p.message_text}")

    # 3. TARGET (.cekgrup, .setgrup, .joingrup)
    @c.on_message(filters.me & filters.command("cekgrup", prefixes="."))
    async def h_cekgrup(client, m):
        await m.edit("🔄 **Scanning...**")
        out = "📂 **DAFTAR GRUP**\n"
        n = 0
        async for d in client.get_dialogs():
            if d.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
                n += 1
                out += f"`{d.chat.id}` | {d.chat.title}\n"
        
        # Split logic if too long
        if len(out) > 4000:
             with open("grup.txt", "w", encoding="utf-8") as f: f.write(out)
             await m.reply_document("grup.txt", caption=f"Total: {n} Grup")
             os.remove("grup.txt")
        else:
             await m.reply(out)

    @c.on_message(filters.me & filters.command("setgrup", prefixes="."))
    async def h_setgrup(client, m):
        args = m.command[1] if len(m.command) > 1 else ""
        ids = []
        if args == 'all':
             async for d in client.get_dialogs():
                 if d.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
                     ids.append(d.chat.id)
        else:
             try: ids = [int(x) for x in args.split(',')]
             except: return await m.edit("❌ `.setgrup all` atau `.setgrup -123,-456`")
        
        with app.app_context():
            u = User.query.get(user_id)
            u.promo.target_list = json.dumps(ids)
            u.promo.target_mode = 'list'
            db.session.commit()
        await m.edit(f"✅ **Target Disimpan:** {len(ids)} Grup")

    @c.on_message(filters.me & filters.command("joingrup", prefixes="."))
    async def h_join(client, m):
        try:
            link = m.command[1]
            await client.join_chat(link)
            await m.edit(f"✅ Joined: {link}")
        except Exception as e: await m.edit(f"❌ Error: {e}")

    # 4. UTILS (.info, .admin, .permit)
    @c.on_message(filters.me & filters.command("info", prefixes="."))
    async def h_info(client, m):
        with app.app_context():
            p = User.query.get(user_id).promo
            targets = json.loads(p.target_list or "[]")
            status = "🟢 ON" if p.is_active else "🔴 OFF"
            wm = p.watermark or "OFF"
            pm = "ON" if p.permit_mode else "OFF"
            
            txt = f"🤖 **USERBOT INFO**\n"
            txt += f"Status: {status}\n"
            txt += f"Jeda: {p.delay}s\n"
            txt += f"Target: {len(targets)} Grup\n"
            txt += f"Watermark: {wm}\n"
            txt += f"Permit: {pm}\n"
            txt += f"Mode Pesan: {p.msg_type}"
            await m.edit(txt)

    @c.on_message(filters.me & filters.command("permit", prefixes="."))
    async def h_permit(client, m):
        arg = m.command[1] if len(m.command) > 1 else ""
        if arg.lower() in ['on', 'off']:
            val = (arg.lower() == 'on')
            with app.app_context():
                User.query.get(user_id).promo.permit_mode = val
                db.session.commit()
            await m.edit(f"🛡️ **Permit:** {arg.upper()}")
        else:
            await m.edit("❌ .permit on / .permit off")

    # 5. PERMIT AUTO-REPLY
    @c.on_message(filters.incoming & filters.private)
    async def h_pm_guard(client, m):
        # Ignore self & already blocked/handled logic (simplified)
        with app.app_context():
            u = User.query.get(user_id)
            if u and u.promo and u.promo.permit_mode:
                # Check execution rate so we don't spam per message
                # For basic implementation, we just reply once (Pyrogram doesn't have built-in state per chat in this basic mode, 
                # but we can rely on replying 'Please wait')
                # To prevent loop, check if we already replied? (Difficult without extra DB).
                # Simple Logic: Reply text.
                await m.reply(u.promo.permit_text)

    # 6. ADMIN CONTROL (.admin add/del)
    @c.on_message(filters.me & filters.command("admin", prefixes="."))
    async def h_admin(client, m):
        if len(m.command) < 2: return await m.edit("❌ `.admin add @user` / `.admin del @user` / `.admin list`")
        cmd = m.command[1].lower()
        
        with app.app_context():
            u = User.query.get(user_id)
            current_admins = json.loads(u.authorized_admins or "[]")
            
            if cmd == "list":
                await m.edit(f"👮 **Admins:**\n" + "\n".join(current_admins))
            
            elif cmd == "add" and len(m.command) > 2:
                new_admin = m.command[2]
                if new_admin not in current_admins:
                    current_admins.append(new_admin)
                    u.authorized_admins = json.dumps(current_admins)
                    db.session.commit()
                    await m.edit(f"✅ Ext. Admin Added: {new_admin}")
                else: await m.edit("⚠️ Already admin.")
            
            elif cmd == "del" and len(m.command) > 2:
                target = m.command[2]
                if target in current_admins:
                    current_admins.remove(target)
                    u.authorized_admins = json.dumps(current_admins)
                    db.session.commit()
                    await m.edit(f"🗑️ Ext. Admin Removed: {target}")
                else: await m.edit("⚠️ Not found.")

    # START
    try:
        await c.start()
        clients[user_id] = c
        print(f"[+] Client {user_id} Started")
    except Exception as e:
        print(f"[-] Client {user_id} Error: {e}")

# --- BROADCAST LOOP ---
async def broadcast_loop():
    print("🚀 Broadcast Loop Started")
    while True:
        try:
            with app.app_context():
                # DB Access must be brief
                users = User.query.filter(User.session_string != None).all()
                
                for u in users:
                    if u.id not in clients: continue # Skip if not running
                    
                    p = u.promo
                    if not p or not p.is_active: continue
                    
                    if (time.time() - p.last_run) > p.delay:
                        client = clients[u.id]
                        targets = json.loads(p.target_list or "[]")
                        
                        if not targets: continue
                        
                        # Round Robin
                        idx = p.batch_offset
                        if idx >= len(targets): idx = 0
                        dest_id = targets[idx]
                        
                        # Send
                        try:
                            if p.msg_type == 'basic' and p.saved_message_id:
                                msg = await client.get_messages("me", p.saved_message_id)
                                cap = msg.caption or ""
                                if p.watermark: cap += f"\n\n{p.watermark}"
                                await msg.copy(dest_id, caption=cap)
                            else:
                                txt = p.message_text
                                if p.watermark: txt += f"\n\n{p.watermark}"
                                await client.send_message(dest_id, txt)
                                
                            print(f"✅ {u.username} -> {dest_id}")
                        except FloodWait as fw:
                             print(f"⏳ FloodWait {u.username}: {fw.value}")
                             # Do NOT update last_run, try again later? Or just skip
                        except Exception as e:
                             print(f"❌ {u.username} -> {dest_id}: {e}")
                        
                        # Update State
                        p.batch_offset = idx + 1
                        p.last_run = time.time()
                        db.session.commit()
                        
        except Exception as e:
            print(f"Loop Error: {e}")
        
        await asyncio.sleep(5)

# --- RUNNER ---
def run_background():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    with app.app_context():
        # Ensure DB Tables
        db.create_all()
        # Ensure Admin exists
        if not User.query.filter_by(username='yourFatherkeeper').first():
            print("creating owner: yourFatherkeeper")
            u = User(username='yourFatherkeeper', role='owner')
            db.session.add(u)
            db.session.commit()
            db.session.add(PromoConfig(user_id=u.id))
            db.session.commit()

        # Load Sessions
        users = User.query.filter(User.session_string != None).all()
        tasks = [start_client(u.id, u.session_string) for u in users]
        if tasks:
            loop.run_until_complete(asyncio.gather(*tasks))
            # If clients started, run infinite loop
            loop.run_until_complete(broadcast_loop())
        else:
             print("⚠️ No Active Sessions found in DB. Run gen_session.py!")
             loop.run_forever()

@app.route('/')
def home():
    return "Userbot Alive. (100% Python/Pyrogram)", 200

if __name__ == "__main__":
    # Start Asyncio in Thread
    t = threading.Thread(target=run_background, daemon=True)
    t.start()
    
    # Start Web (Health Check)
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))