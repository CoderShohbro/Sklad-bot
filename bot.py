import logging
import datetime
from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from sqlalchemy.orm import Session

from backend import config, database, models, report_generator

# Logging setup
logger = logging.getLogger(__name__)

# Router definition
router = Router()

# Global Bot Instance
bot = Bot(token=config.BOT_TOKEN)

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Skladchi/Admin uchun asosiy doimiy Reply menyu tugmalari"""
    builder = ReplyKeyboardBuilder()
    
    # 1. Web App tugmasi
    web_app = WebAppInfo(url=config.WEB_APP_URL)
    builder.row(KeyboardButton(text="🚀 OMBORGA KIRISH", web_app=web_app))
    
    # 2. Boshqa operativ tugmalar
    builder.row(
        KeyboardButton(text="📦 Joriy Qoldiq"),
        KeyboardButton(text="📊 Kunlik Hisobot")
    )
    builder.row(
        KeyboardButton(text="👥 Ustalar Ro'yxati")
    )
    
    return builder.as_markup(resize_keyboard=True)

@router.message(Command("start"))
async def start_handler(message: types.Message):
    """Start buyrug'i kelganda foydalanuvchini ro'yxatdan o'tkazish yoki kutib olish"""
    telegram_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name
    
    # DB session
    db: Session = next(database.get_db())
    try:
        # Check if user exists
        user = db.query(models.User).filter_by(telegram_id=telegram_id).first()
        if not user:
            # Create new user
            user = models.User(
                telegram_id=telegram_id,
                username=username,
                full_name=full_name,
                role="Admin" if db.query(models.User).count() == 0 else "Skladchi" # Birinchi kirgan foydalanuvchi Admin
            )
            db.add(user)
            db.commit()
            logger.info(f"Yangi foydalanuvchi qo'shildi: {full_name} ({telegram_id})")
        else:
            # Update user details if changed
            user.username = username
            user.full_name = full_name
            db.commit()
            
        role_uz = "Administrator" if user.role == "Admin" else "Skladchi"
        welcome_text = (
            f"👋 **Assalomu alaykum, {full_name}!**\n\n"
            f"🏗 **\"Baraka Sklad\"** tizimiga xush kelibsiz.\n"
            f"Sizning rolingiz: **{role_uz}**\n\n"
            f"Quyidagi tugmalar orqali omborni boshqarishingiz yoki hisobotlarni olishingiz mumkin 👇"
        )
        await message.answer(welcome_text, reply_markup=get_main_keyboard(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Start handlerda xatolik: {e}")
        await message.answer("Tizimga ulanishda xatolik yuz berdi. Iltimos keyinroq qayta urining.")
    finally:
        db.close()

@router.message(F.text == "📦 Joriy Qoldiq")
async def stock_pdf_handler(message: types.Message):
    """Skladdagi tovarlarni PDF formatida yuklab berish"""
    await message.answer("⏳ Joriy qoldiqlar hisoboti tayyorlanmoqda, iltimos kuting...")
    
    db: Session = next(database.get_db())
    try:
        filepath = f"data/reports/qoldiq_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        report_generator.generate_stock_pdf(db, filepath)
        
        # Send file to user
        file_input = types.FSInputFile(filepath)
        await message.answer_document(
            file_input, 
            caption=f"📦 **Baraka Sklad** joriy qoldiqlari\nSana: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}",
            parse_mode="Markdown"
        )
        
        # Clean up file after sending (optional, but let's keep it in folder as log)
    except Exception as e:
        logger.error(f"PDF hisobot yuborishda xatolik: {e}")
        await message.answer("❌ PDF hisobotini tayyorlashda xatolik yuz berdi.")
    finally:
        db.close()

@router.message(F.text == "📊 Kunlik Hisobot")
async def daily_report_handler(message: types.Message):
    """Bugungi jami kirim/chiqim amallarini matn shaklida ko'rsatish"""
    db: Session = next(database.get_db())
    try:
        today_start = datetime.datetime.combine(datetime.date.today(), datetime.time.min)
        today_end = datetime.datetime.combine(datetime.date.today(), datetime.time.max)
        
        # Transactions today
        txs = db.query(models.Transaction).filter(
            models.Transaction.created_at >= today_start,
            models.Transaction.created_at <= today_end
        ).all()
        
        kirim_total = 0.0
        chiqim_total = 0.0
        profit_total = 0.0
        kirim_cnt = 0
        chiqim_cnt = 0
        
        for t in txs:
            if t.type == "Kirim":
                kirim_total += t.quantity * t.cost_price
                kirim_cnt += 1
            elif t.type == "Chiqim":
                chiqim_total += t.quantity * t.selling_price
                # Profit = (selling_price - cost_price) * quantity
                profit_total += t.quantity * (t.selling_price - t.cost_price)
                chiqim_cnt += 1
                
        report_text = (
            f"📊 **Baraka Sklad — Kunlik Hisobot**\n"
            f"📅 Sana: **{datetime.date.today().strftime('%d.%m.%Y')}**\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"📥 **Jami Kirim:**\n"
            f"  • Amallar soni: {kirim_cnt} ta\n"
            f"  • Umumiy summa: `{kirim_total:,.0f} UZS`\n\n"
            f"📤 **Jami Chiqim:**\n"
            f"  • Amallar soni: {chiqim_cnt} ta\n"
            f"  • Umumiy summa: `{chiqim_total:,.0f} UZS`\n\n"
            f"📈 **Bugungi Sof Foyda:**\n"
            f"  • `{profit_total:,.0f} UZS`\n"
            f"*(tannarx va sotish farqidan)*\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⚡️ *Batafsil ma'lumot olish uchun Web App ilovasiga kiring.*"
        )
        
        await message.answer(report_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Kunlik hisobotda xatolik: {e}")
        await message.answer("❌ Kunlik hisobotni hisoblashda xatolik yuz berdi.")
    finally:
        db.close()

@router.message(F.text == "👥 Ustalar Ro'yxati")
async def customers_list_handler(message: types.Message):
    """Ustalar (Mijozlar) va ularning qarzdorlik balansi"""
    db: Session = next(database.get_db())
    try:
        customers = db.query(models.Customer).all()
        if not customers:
            await message.answer("📭 Ustalar ro'yxati hozircha bo'sh.")
            return
            
        text = "👥 **Ustalar va Qarzdorlik Balansi**\n"
        text += "*(Minus qiymat - ustaning sklad oldidagi qarzi)*\n"
        text += "━━━━━━━━━━━━━━━━━━━\n\n"
        
        for c in customers:
            if c.balance < 0:
                bal_str = f"🔴 `{c.balance:,.0f} UZS` (Qarzdor)"
            elif c.balance > 0:
                bal_str = f"🟢 `+{c.balance:,.0f} UZS` (Haqdor)"
            else:
                bal_str = "⚪️ `0 UZS`"
                
            phone_str = f" ({c.phone})" if c.phone else ""
            text += f"👤 **{c.name}**{phone_str}\n   💵 Balans: {bal_str}\n\n"
            
        text += "━━━━━━━━━━━━━━━━━━━\n"
        text += "📝 *Yangi usta qo'shish Web App interfeysidan amalga oshiriladi.*"
        await message.answer(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ustalar ro'yxatida xatolik: {e}")
        await message.answer("❌ Ustalar ro'yxatini yuklashda xatolik yuz berdi.")
    finally:
        db.close()

# Integration helper function
async def send_low_stock_warning(product_name: str, current_quantity: float, threshold: float, warehouse_name: str):
    """Tovar qoldig'i minimal chegaradan kamayib ketganda admin guruhiga avtomatik xabar yuboradi"""
    try:
        warning_msg = (
            f"⚠️ ⚠️ ⚠️ **DIQQAT! MAHSULOT KAM QOLDI!** ⚠️ ⚠️ ⚠️\n\n"
            f"📦 **Mahsulot nomi:** {product_name}\n"
            f"🏢 **Ombor nomi:** {warehouse_name}\n"
            f"🔴 **Joriy qoldiq:** `{current_quantity}` ta\n"
            f"⚠️ **Minimal chegara:** `{threshold}` ta\n\n"
            f"📢 *Iltimos, mahsulotni to'ldirish yoki sotuvni to'xtatish choralarini ko'ring.*"
        )
        # We send to the configured Admin Group ID
        await bot.send_message(chat_id=config.ADMIN_GROUP_ID, text=warning_msg, parse_mode="Markdown")
        logger.info(f"Kam qolgan tovar ogohlantirishi guruhga yuborildi: {product_name} ({current_quantity})")
    except Exception as e:
        logger.error(f"Ogohlantirish xabari yuborishda xatolik: {e}")

async def send_invoice_notification(telegram_id: int, customer_name: str, product_name: str, quantity: float, total_price: float, current_balance: float):
    """Mijoz nomiga chiqim rasmiylashtirilganda unga yoki skladchiga avtomatik chek/xabarnoma yuboradi"""
    try:
        invoice_msg = (
            f"📄 **BARAKA SKLAD — SOTUV CHEKI** 📄\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Xaridor (Usta):** {customer_name}\n"
            f"📦 **Mahsulot:** {product_name}\n"
            f"🔢 **Miqdori:** {quantity} ta\n"
            f"💵 **Jami narx:** `{total_price:,.0f} UZS`\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💳 **Ustaning joriy balansi:** `{current_balance:,.0f} UZS`\n"
            f"🕒 Vaqt: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"✅ *Xarid muvaffaqiyatli rasmiylashtirildi!*"
        )
        if telegram_id:
            await bot.send_message(chat_id=telegram_id, text=invoice_msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Chek xabarnomasini yuborishda xatolik: {e}")
