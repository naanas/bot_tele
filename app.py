import telebot
import os
import time
from flask import Flask
from threading import Thread

# Ambil token dari Environment Variable Render
TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = 5845570657 

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Penjaga agar Render tidak mematikan service
@app.route('/')
def home():
    return "Bot Online Gratis di Render!"

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "Halo! Bot ini hidup di Web Service Render (Gratis).")

@bot.message_handler(commands=['admin'])
def admin(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "✅ Akses Admin Diterima!")

def run_flask():
    # Render otomatis memberikan PORT, jika tidak ada pakai 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # Jalankan Flask di background
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    print("Bot sedang berjalan...")
    bot.infinity_polling()