import hmac
import hashlib
import urllib.parse
import json
import logging
from fastapi import Header, HTTPException, status, Depends
from sqlalchemy.orm import Session
from backend import config, database, models

logger = logging.getLogger("security")

def verify_telegram_data(init_data: str) -> bool:
    """Telegram Web App initData tarkibidagi hashni bot token orqali tekshiradi"""
    if not init_data:
        return False
        
    try:
        # Parse query string parameters
        parsed = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
        params = dict(parsed)
        
        if "hash" not in params:
            return False
            
        received_hash = params.pop("hash")
        
        # Sort remaining parameters alphabetically
        sorted_params = sorted(params.items())
        
        # Join parameters with new line
        data_check_string = "\n".join([f"{k}={v}" for k, v in sorted_params])
        
        # Secret key calculation: HMAC_SHA256("WebApps", BOT_TOKEN)
        secret_key = hmac.new(
            key=b"WebApps",
            msg=config.BOT_TOKEN.encode(),
            digestmod=hashlib.sha256
        ).digest()
        
        # Calculated hash calculation: HMAC_SHA256(secret_key, data_check_string)
        calculated_hash = hmac.new(
            key=secret_key,
            msg=data_check_string.encode(),
            digestmod=hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(calculated_hash, received_hash)
        
    except Exception as e:
        logger.error(f"Telegram signature validation error: {e}")
        return False

# FastAPI Dependency
def verify_telegram_request(x_telegram_init_data: str = Header(None, alias="X-Telegram-Init-Data")):
    """FastAPI endpointlari uchun xavfsizlik filtri"""
    if not x_telegram_init_data:
        logger.warning("X-Telegram-Init-Data topilmadi. Test rejimi faollashgan.")
        return True
        
    if not verify_telegram_data(x_telegram_init_data):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Telegram orqali kelmagan so'rov (Signature xato)!"
        )
    return True

def get_telegram_user_id(init_data: str) -> int:
    """initData tarkibidan foydalanuvchining Telegram ID sini ajratadi"""
    try:
        parsed = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
        params = dict(parsed)
        user_str = params.get("user")
        if user_str:
            user_data = json.loads(user_str)
            return user_data.get("id")
    except Exception:
        pass
    return None

def get_current_user(
    x_telegram_init_data: str = Header(None, alias="X-Telegram-Init-Data"),
    db: Session = Depends(database.get_db)
) -> models.User:
    """Joriy so'rov yuborgan foydalanuvchini aniqlaydi va uning modelini qaytaradi"""
    if x_telegram_init_data:
        if verify_telegram_data(x_telegram_init_data):
            tg_id = get_telegram_user_id(x_telegram_init_data)
            if tg_id:
                user = db.query(models.User).filter_by(telegram_id=tg_id).first()
                if user:
                    return user
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Telegram signature validatsiyasi muvaffaqiyatsiz bo'ldi!"
            )
            
    # Local testlar uchun bazadagi birinchi Admin foydalanuvchini qaytaradi
    mock_user = db.query(models.User).filter_by(role="Admin").first()
    if not mock_user:
        # Admin bo'lmasa har qanday birinchi user
        mock_user = db.query(models.User).first()
        
    if not mock_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tizimda hech qanday foydalanuvchi topilmadi!"
        )
    return mock_user
