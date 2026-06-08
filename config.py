import os

# Base Directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Bot Settings
BOT_TOKEN = os.getenv("BOT_TOKEN", "5984982200:AAG5YO57l-OUrGLjdPIULCNUegkjmLcD6sE")
# Web App URL
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://sklad-bot-nine.vercel.app/")
# Admin Group ID / User ID (to send critical low stock notifications)
ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID", "641993778")

# Database Settings
DB_DIR = os.path.join(BASE_DIR, "data")
if not os.path.exists(DB_DIR):
    os.makedirs(DB_DIR)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(DB_DIR, 'sklad.db')}")

# Server Settings
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", 8000))
DEBUG = True
