import telebot
import os
import time

# Kita ambil token dari Environment Variable nanti di Render
TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = 5845570657 

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "Halo! Bot ini sudah hidup di Render dan anti-blokir.")

@bot.message_handler(commands=['admin'])
def admin(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "✅ Akses Admin Diterima! Selamat datang kembali, Bos.")
    else:
        bot.reply_to(message, f"❌ Akses Ditolak. ID: {message.chat.id}")

if __name__ == "__main__":
    print("Bot sedang berjalan...")
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)