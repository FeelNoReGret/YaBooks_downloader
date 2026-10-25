"""Сессия: токен Яндекса хранится в зашифрованной HttpOnly-cookie.

Сервер сам токены не хранит (stateless) — токен лежит в cookie пользователя,
зашифрован ключом из WEB_SECRET_KEY (Fernet: шифрование + подпись) и приходит
с каждым запросом. Так токен владельца не зашит в приложение, каждый
пользователь работает под своим, а значение cookie нельзя прочитать/подделать.
"""
import base64
import hashlib
import os
import secrets
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

COOKIE_NAME = "yabooks_session"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 дней

# Секрет для шифрования cookie. В проде задаётся через WEB_SECRET_KEY; если не
# задан — случайный на процесс (сессии сбрасываются при рестарте: ок для
# разработки, в проде переменную надо задать явно).
_SECRET = os.environ.get("WEB_SECRET_KEY") or secrets.token_urlsafe(32)
# Ключ Fernet: 32 байта из секрета, base64 (как требует Fernet).
_fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(_SECRET.encode()).digest()))

# Secure-cookie (только по HTTPS). Выключается для локальной отладки по http:
# WEB_COOKIE_SECURE=0.
COOKIE_SECURE = os.environ.get("WEB_COOKIE_SECURE", "1") != "0"


def encode_token(token: str) -> str:
    return _fernet.encrypt(token.encode()).decode()


def decode_token(value: str) -> Optional[str]:
    try:
        token = _fernet.decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return None
    return token or None


def get_token(request) -> Optional[str]:
    """Токен из cookie запроса или None."""
    raw = request.cookies.get(COOKIE_NAME)
    return decode_token(raw) if raw else None
