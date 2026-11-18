
import os
import threading
from flask import Flask
from bale import Bot, Message

app = Flask(__name__)

TOKEN = os.getenv("BALE_TOKEN")

bot = Bot(token=TOKEN)

@bot.event
async def on_before_ready():
    await bot.delete_webhook()

@bot.event
async def on_ready():
    print("HOOSH WEB YAR IS ONLINE!")

@bot.event
async def on_message(message: Message):
    text = (message.content or "").strip()

    if text == "/start":
        await message.reply(
            "سلام 👋\n"
            "خیلی به هوش وب یار خوش اومدید! 🌹\n\n"
            "اتصال ربات با موفقیت برقرار شد 💙"
        )

@app.route("/")
def home():
    return "HOOSH WEB YAR - ONLINE"

@app.route("/health")
def health():
    return {"status": "online"}

def start_bot():
    if TOKEN:
        bot.run()
    else:
        print("ERROR: BALE_TOKEN NOT FOUND")

if TOKEN:
    threading.Thread(
        target=start_bot,
        daemon=True
    ).start()

