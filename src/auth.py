"""Авторизация"""
import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import get_key, set_key, unset_key
from rich.console import Console

from src.config import HEADERS

console = Console()

# python-dotenv логирует WARNING «Key ... not found», когда токена в .env ещё
# нет — для нас это штатная ситуация (первый запуск, после clear_token), глушим.
logging.getLogger("dotenv.main").setLevel(logging.ERROR)

# Токен авторизации хранится в .env (одна точка истины). Старый token.txt
# автоматически переносится в .env при первом запуске (_migrate_legacy_token).
ENV_FILE = Path(".env")
TOKEN_KEY = "YANDEX_BOOKS_TOKEN"
LEGACY_TOKEN_FILE = Path("token.txt")


def read_token() -> Optional[str]:
    """Прочитать токен: сначала переменная окружения, затем .env."""
    env_value = os.environ.get(TOKEN_KEY)
    if env_value and env_value.strip():
        return env_value.strip()
    if ENV_FILE.exists():
        value = get_key(str(ENV_FILE), TOKEN_KEY)
        if value and value.strip():
            return value.strip()
    return None


def save_token(token: str) -> None:
    """Сохранить токен в .env (создав файл при необходимости)."""
    ENV_FILE.touch(exist_ok=True)
    set_key(str(ENV_FILE), TOKEN_KEY, token)


def clear_token() -> None:
    """Удалить токен из .env — например, при истечении, для переавторизации."""
    if ENV_FILE.exists() and get_key(str(ENV_FILE), TOKEN_KEY):
        unset_key(str(ENV_FILE), TOKEN_KEY)


def _migrate_legacy_token() -> None:
    """Перенести токен из старого token.txt в .env, если он там ещё лежит."""
    if LEGACY_TOKEN_FILE.exists() and not read_token():
        token = LEGACY_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            save_token(token)
            console.print("[green]Токен перенесён из token.txt в .env[/green]")
            LEGACY_TOKEN_FILE.unlink()


def get_auth_token() -> str:
    """Получение токена авторизации"""
    _migrate_legacy_token()

    token = read_token()
    if token:
        return token

    if HEADERS.get('auth-token'):
        return HEADERS['auth-token']

    console.print("[yellow]Токен не найден. Необходима авторизация...[/yellow]")
    auth_token = run_auth_webview()

    if auth_token:
        save_token(auth_token)
        console.print("[green]Токен сохранён в .env[/green]")
    else:
        console.print("[red]Не удалось получить токен автоматически[/red]")
        console.print("[yellow]Введите auth-token вручную:[/yellow]")
        auth_token = input("> ").strip()
        if auth_token:
            save_token(auth_token)

    return auth_token


def run_auth_webview() -> Optional[str]:
    """Запуск окна авторизации для получения токена"""
    try:
        import urllib.parse
        import webview

        def on_loaded(window):
            if "yx4483e97bab6e486a9822973109a14d05.oauth.yandex.ru" in urllib.parse.urlparse(window.get_current_url()).netloc:
                url = urllib.parse.urlparse(window.get_current_url())
                try:
                    window.auth_token = urllib.parse.parse_qs(url.fragment)['access_token'][0]
                    window.destroy()
                except:
                    pass

        window = webview.create_window(
            'Вход в аккаунт для получения токена',
            'https://oauth.yandex.ru/authorize?response_type=token&client_id=4483e97bab6e486a9822973109a14d05'
        )
        window.events.loaded += on_loaded
        window.auth_token = None
        webview.start()
        return window.auth_token
    except ImportError:
        console.print("[yellow]pywebview не установлен. Установите: pip install pywebview[/yellow]")
        return None
    except Exception as e:
        console.print(f"[red]Ошибка окна авторизации: {e}[/red]")
        return None