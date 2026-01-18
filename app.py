import telebot
import os
import time
from flask import Flask
from threading import Thread
from telebot import types

# --- KONFIGURASI ---
# Token diambil dari Environment Variable di Render
TOKEN = os.environ.get('BOT_TOKEN')
# ID Telegram kamu untuk menerima laporan order
ADMIN_ID = 5845570657 

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- WEB SERVER (Agar Render tidak mati/Error) ---
@app.route('/')
def home():
    return "Bot Toko Online is Running!"

def run_flask():
    # Render mewajibkan aplikasi berjalan di port yang mereka tentukan
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- LOGIKA BOT ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    # Membuat tombol menu utama
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_katalog = types.InlineKeyboardButton("🛍️ Katalog Produk", callback_data='menu_katalog')
    btn_bayar = types.InlineKeyboardButton("💳 Cara Bayar", callback_data='menu_bayar')
    btn_admin = types.InlineKeyboardButton("📞 Chat Admin (WA)", url="https://wa.me/6282131077460") # Ganti nomor WA kamu
    
    markup.add(btn_katalog, btn_bayar, btn_admin)
    
    bot.send_message(
        message.chat.id, 
        f"Halo {message.from_user.first_name}!\nSelamat datang di **Toko Digital Pro**.\n\nSilakan pilih menu di bawah ini:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    if call.data == 'menu_katalog':
        # Menampilkan katalog dengan tombol beli
        markup = types.InlineKeyboardMarkup()
        btn_beli = types.InlineKeyboardButton("🛒 Pesan Bot Telegram Sekarang", callback_data='order_bot')
        markup.add(btn_beli)
        
        bot.send_message(
            call.message.chat.id, 
            "📜 **KATALOG PRODUK**\n\n1. **Jasa Bot Telegram**\n   - 24 Jam Online\n   - Fitur Custom\n   - Harga: Rp500.000\n\nKlik tombol di bawah untuk memesan:",
            reply_markup=markup,
            parse_mode="Markdown"
        )

    elif call.data == 'menu_bayar':
        bot.send_message(
            call.message.chat.id,
            "🏦 **METODE PEMBAYARAN**\n\n- **BCA**: 123456789 (A/N Nama Anda)\n- **Dana/OVO**: 08123456789\n\nKirim bukti transfer ke admin setelah membayar."
        )

    elif call.data == 'order_bot':
        # NOTIFIKASI KE ADMIN
        user_info = f"Nama: {call.from_user.first_name}\nID: {call.from_user.id}\nUsername: @{call.from_user.username}"
        bot.send_message(ADMIN_ID, f"🔔 **PESANAN BARU MASUK!**\n\nProduk: Jasa Bot Telegram\nPelanggan: \n{user_info}")
        
        # KONFIRMASI KE USER
        bot.answer_callback_query(call.id, "Pesanan dikirim ke Admin!")
        bot.send_message(call.message.chat.id, "✅ **Pesanan Berhasil!**\nAdmin telah menerima notifikasi pesananmu dan akan segera menghubungimu.")

@bot.message_handler(commands=['admin'])
def check_admin(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "✅ **Akses Admin Diterima!**\nBos, semua sistem berjalan normal di Render.")
    else:
        bot.reply_to(message, "❌ Akses Ditolak. Menu ini hanya untuk owner.")

# --- EKSEKUSI ---
if __name__ == "__main__":
    # Jalankan Flask di thread berbeda agar tidak mengganggu polling bot
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    print("Bot sedang online di Render...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            print(f"Error Koneksi: {e}")
            time.sleep(5)