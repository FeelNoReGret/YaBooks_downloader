"""Утилиты"""
import re
from pathlib import Path

class SystemExitException(Exception):
    """Исключение для выхода из программы"""
    pass


class AuthError(Exception):
    """Токен недействителен/истёк (GraphQL-ошибка TOKEN_EXPIRED или REST 401).

    Подкласс Exception — в CLI обрабатывается как обычная ошибка (печатается
    текст), в вебе отличается от прочих и приводит к ре-логину.
    """
    pass


def sanitize_filename(name: str) -> str:
    """Очистка имени файла от недопустимых символов с безопасной заменой"""
    if not name:
        return "Unknown"
    replacements = {
        '\\': '-',
        '/': '-',
        ':': ';',
        '*': 'x',
        '?': '!',
        '"': "'",
        '<': '(',
        '>': ')',
        '|': '-',
    }
    for forbidden, replacement in replacements.items():
        name = name.replace(forbidden, replacement)
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


def format_series_position(position) -> str:
    """Форматирует позицию книги в серии с ведущими нулями.

    Используется во всех загрузчиках (книги/аудиокниги/комиксы) вместо
    того, чтобы каждый дублировал одну и ту же логику самостоятельно.
    """
    try:
        pos_num = int(float(position))
    except (ValueError, TypeError):
        return str(position)
    return f"{pos_num:03d}" if pos_num >= 100 else f"{pos_num:02d}"
