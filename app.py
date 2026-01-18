import telebot
from telebot import types
from flask import Flask, request
import os

# --- KONFIGURASI ---
TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = 5845570657
# Ganti dengan URL Render kamu (tambahkan https://)
# Contoh: https://bot-tele-u3f8.onrender.com
SERVER_URL = "https://bot-tele-u3f8.onrender.com"

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- LOGIKA BOT ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_katalog = types.InlineKeyboardButton("🛍️ Katalog Produk", callback_data='menu_katalog')
    btn_bayar = types.InlineKeyboardButton("💳 Cara Bayar", callback_data='menu_bayar')
    
    # Update WA Link dengan pesan otomatis
    wa_msg = "Halo Admin, saya mau pesan Jasa Bot Telegram."
    wa_url = f"https://wa.me/6282131077460?text={wa_msg.replace(' ', '%20')}"
    btn_admin = types.InlineKeyboardButton("📞 Chat Admin (WA)", url=wa_url)
    
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
        user_info = f"Nama: {call.from_user.first_name}\nID: {call.from_user.id}\nUsername: @{call.from_user.username}"
        bot.send_message(ADMIN_ID, f"🔔 **PESANAN BARU MASUK!**\n\nProduk: Jasa Bot Telegram\nPelanggan: \n{user_info}")
        
        bot.answer_callback_query(call.id, "Pesanan dikirim ke Admin!")
        bot.send_message(call.message.chat.id, "✅ **Pesanan Berhasil!**\nAdmin telah menerima notifikasi pesananmu dan akan segera menghubungimu.")

@bot.message_handler(commands=['admin'])
def check_admin(message):
    if message.chat.id == ADMIN_ID:
        webhook_info = bot.get_webhook_info()
        status = "Webhook Aktif" if webhook_info.url else "Polling Mode"
        bot.reply_to(message, f"✅ **Akses Admin Diterima!**\nStatus: {status}\nServer: Running")
    else:
        bot.reply_to(message, "❌ Akses Ditolak. Menu ini hanya untuk owner.")

# --- WEBHOOK ROUTE ---
# Telegram akan mengirim update ke sini
@app.route('/' + TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

@app.route("/")
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url=SERVER_URL + "/" + TOKEN)
    return "Bot dengan Webhook Siap!", 200

# --- EKSEKUSI ---
if __name__ == "__main__":
    # Jika dijalankan di Render (ada PORT env), pakai Webhook
    # Jika dijalankan local, pakai Polling biasa untuk testing
    
    if os.environ.get('PORT'):
        port = int(os.environ.get('PORT', 5000))
        # Webhook diset saat route '/' diakses pertama kali oleh Render health check atau kita panggil manual
        # Tapi lebih aman kita set langsung saat start jika memungkinkan, atau biarkan route '/' yang handle
        app.run(host="0.0.0.0", port=port)
    else:
        print("Bot berjalan di mode Local (Polling)...")
        bot.remove_webhook()
        bot.infinity_polling()