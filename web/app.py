"""FastAPI-приложение: поиск и скачивание книг с Яндекс.Книги через браузер.

Переиспользует существующий пайплайн (src.downloader + загрузчики форматов).
Токен у каждого пользователя свой (см. web.session). Файлы собираются во
временную папку запроса и отдаются браузером, на сервере не оседают.
"""
import asyncio
import os
import shutil
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from src.audiobooks import AudiobooksDownloader
from src.books import BooksDownloader
from src.comics import ComicsDownloader
from src.config import URLS
from src.downloader import YandexBooksDownloader
from src.utils import AuthError
from web.session import (
    COOKIE_MAX_AGE,
    COOKIE_NAME,
    COOKIE_SECURE,
    encode_token,
    get_token,
)

# --- Настройки (из переменных окружения) --------------------------------------
STATIC_DIR = Path(__file__).parent / "static"
BASE_TMP = Path(os.environ.get("WEB_TMP_DIR", "/tmp/yabooks_web"))
# Одновременных сборок файлов — ограничиваем, чтобы не плодить ffmpeg-процессы
# и держать RAM/диск в рамках.
MAX_WEB_DOWNLOADS = int(os.environ.get("WEB_MAX_DOWNLOADS", "2"))
# Срок жизни собранного, но не забранного файла до авто-очистки (сек).
DOWNLOAD_TTL = int(os.environ.get("WEB_DOWNLOAD_TTL", "1800"))

DOWNLOADABLE = ("book", "audiobook", "comicbook")

# Реестр собранных файлов, ждущих отдачи: id -> {path, dir, filename, created}.
# Маленький (строки путей), один воркер — обычного dict + lock достаточно.
_download_sema = asyncio.Semaphore(MAX_WEB_DOWNLOADS)
_prepared: dict = {}
_prepared_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    BASE_TMP.mkdir(parents=True, exist_ok=True)
    sweeper = asyncio.create_task(_sweep_stale())
    try:
        yield
    finally:
        sweeper.cancel()


app = FastAPI(title="YaBooks", lifespan=lifespan)


# --- Вспомогательное ----------------------------------------------------------
@asynccontextmanager
async def _downloader(token: str, base_dir: Path):
    """Загрузчик под токен конкретного пользователя (веб-режим)."""
    dl = YandexBooksDownloader()
    await dl.initialize(token)
    dl.allow_interactive_reauth = False  # 401 всплывает наверх → ре-логин
    dl.base_dir = base_dir
    try:
        yield dl
    finally:
        await dl.close()


def _require(request: Request) -> str:
    token = get_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Требуется вход")
    return token


def _map_http_error(e: httpx.HTTPStatusError) -> HTTPException:
    if e.response.status_code == 401:
        return HTTPException(status_code=401, detail="Токен недействителен")
    return HTTPException(status_code=502, detail="Яндекс.Книги недоступны")


async def _run_download(dl, resource: dict, metadata: dict, ctype: str) -> bool:
    """Сборка файла существующими загрузчиками (как в CLI _download_once)."""
    if ctype == "book":
        return await BooksDownloader(dl).download(resource, metadata)
    if ctype == "audiobook":
        return await AudiobooksDownloader(dl).download(resource, metadata)
    return await ComicsDownloader(dl).download(resource)


def _find_output(tmp: Path) -> Optional[Path]:
    """Единственный собранный файл во временной папке запроса."""
    for pattern in ("*.epub", "*.m4b", "*.cbz"):
        files = list(tmp.rglob(pattern))
        if files:
            return files[0]
    return None


def _cover_from_rest(resource: dict) -> Optional[str]:
    cover = resource.get("cover")
    if isinstance(cover, dict):
        return cover.get("large") or cover.get("medium") or cover.get("small")
    return None


async def _author_items(dl, uuid: str) -> list:
    """Книги/аудио/комиксы автора — как в CLI process_author, но для списка."""
    type_urls = {
        "book": URLS["author_books"].format(uuid=uuid),
        "audiobook": URLS["author_audiobooks"].format(uuid=uuid),
        "comicbook": URLS["author_comicbooks"].format(uuid=uuid),
    }
    items = []
    for ctype, url in type_urls.items():
        try:
            data = await dl.api_get(url)
        except AuthError:
            raise  # истёкший токен → наверх (ре-логин), а не «нет книг»
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise
            continue  # нет такого раздела у автора (404) — пропускаем
        except Exception:
            continue
        raw = data.get("books") or data.get("audiobooks") or data.get("comicbooks") or []
        for it in raw:
            res = it.get("book") or it.get("audiobook") or it.get("comicbook") or it
            items.append({
                "content_type": ctype,
                "uuid": res.get("uuid", ""),
                "title": res.get("title", "Неизвестно"),
                "authors": dl.extract_authors(res),
                "cover_url": _cover_from_rest(res),
            })
    return items


async def _sweep_stale():
    """Периодически чистит собранные, но не забранные файлы и осиротевшие папки."""
    while True:
        try:
            await asyncio.sleep(300)
            now = time.time()
            async with _prepared_lock:
                stale = [k for k, v in _prepared.items() if now - v["created"] > DOWNLOAD_TTL]
                dirs = [_prepared.pop(k)["dir"] for k in stale]
            # Удаляем вне блокировки и вне event loop (rmtree синхронный и может
            # долго удалять большие папки аудиокниг — иначе блокирует воркер).
            for d in dirs:
                await asyncio.to_thread(shutil.rmtree, d, ignore_errors=True)
            if BASE_TMP.exists():
                for d in list(BASE_TMP.iterdir()):
                    try:
                        if d.is_dir() and now - d.stat().st_mtime > DOWNLOAD_TTL:
                            await asyncio.to_thread(shutil.rmtree, d, ignore_errors=True)
                    except OSError:
                        pass
        except asyncio.CancelledError:
            raise
        except Exception:
            pass


# --- Маршруты API -------------------------------------------------------------
@app.get("/api/me")
async def api_me(request: Request):
    return {"authed": get_token(request) is not None}


@app.post("/api/login")
async def api_login(payload: dict = Body(...)):
    token = (payload.get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Введите токен")
    # Проверяем токен дешёвым поисковым запросом: успех (вернул кортеж) — токен
    # рабочий; любое исключение — отклоняем (невалидный токен даёт 401).
    async with _downloader(token, BASE_TMP) as dl:
        try:
            await dl.search("тест")
        except AuthError:
            raise HTTPException(status_code=401, detail="Токен недействителен")
        except httpx.HTTPStatusError as e:
            raise _map_http_error(e)
        except httpx.RequestError:
            # Сетевой сбой — не выдаём за «неверный токен», просим повторить.
            raise HTTPException(status_code=503, detail="Яндекс.Книги недоступны, попробуйте позже")
        except Exception:
            raise HTTPException(status_code=401, detail="Не удалось проверить токен")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        COOKIE_NAME, encode_token(token),
        httponly=True, samesite="lax", secure=COOKIE_SECURE, max_age=COOKIE_MAX_AGE,
    )
    return resp


@app.post("/api/logout")
async def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME)
    return resp


@app.get("/api/search")
async def api_search(request: Request, q: str, cursor: str = ""):
    token = _require(request)
    q = q.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Пустой запрос")
    async with _downloader(token, BASE_TMP) as dl:
        try:
            results, next_cursor = await dl.search(q, cursor)
        except AuthError:
            raise HTTPException(status_code=401, detail="Токен недействителен")
        except httpx.HTTPStatusError as e:
            raise _map_http_error(e)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    sections: dict = {}
    for r in results:
        sections.setdefault(r["content_type"], []).append(r)
    return {"sections": sections, "cursor": next_cursor}


@app.get("/api/items")
async def api_items(request: Request, type: str, uuid: str):
    """Содержимое серии или автора (для перехода «внутрь»)."""
    token = _require(request)
    async with _downloader(token, BASE_TMP) as dl:
        try:
            if type == "series":
                books = await dl.get_series_books(uuid)
                items = [{
                    "content_type": b["resource_type"],
                    "uuid": b["uuid"],
                    "title": b["title"],
                    "authors": b["authors"],
                    "cover_url": b.get("cover_url"),
                    "series_position": b.get("series_position"),
                } for b in books]
            elif type == "authors":
                items = await _author_items(dl, uuid)
            else:
                raise HTTPException(status_code=400, detail="Неверный тип")
        except AuthError:
            raise HTTPException(status_code=401, detail="Токен недействителен")
        except httpx.HTTPStatusError as e:
            raise _map_http_error(e)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=502, detail="Не удалось получить список")
    return {"items": items}


@app.post("/api/download/prepare")
async def api_prepare(request: Request, payload: dict = Body(...)):
    """Собирает файл во временную папку, возвращает id для скачивания."""
    token = _require(request)
    ctype = payload.get("content_type")
    uuid = payload.get("uuid")
    bitrate = payload.get("bitrate", "max")
    if ctype not in DOWNLOADABLE or not uuid:
        raise HTTPException(status_code=400, detail="Неверный запрос")
    if ctype == "audiobook" and not shutil.which("ffmpeg"):
        raise HTTPException(status_code=503, detail="На сервере нет FFmpeg — аудиокниги недоступны")

    async with _download_sema:
        tmp = BASE_TMP / secrets.token_hex(8)
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            async with _downloader(token, tmp) as dl:
                dl.bitrate_mode = "min_bit_rate" if bitrate == "min" else "max_bit_rate"
                info, metadata = await dl.get_resource_info(uuid, ctype)
                if not dl.check_availability(info, ctype):
                    raise HTTPException(status_code=409, detail="Ресурс недоступен для скачивания")
                resource = {
                    "uuid": uuid,
                    "resource_type": ctype,
                    "title": metadata.get("title", ""),
                    "authors": metadata.get("authors", []),
                    "series_list": metadata.get("series_list", []),
                }
                ok = await _run_download(dl, resource, metadata, ctype)
            file = _find_output(tmp) if ok else None
            if not file:
                raise HTTPException(status_code=502, detail="Не удалось собрать файл")
            did = secrets.token_urlsafe(12)
            async with _prepared_lock:
                _prepared[did] = {"path": file, "dir": tmp, "filename": file.name, "created": time.time()}
            return {"id": did, "filename": file.name}
        except HTTPException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        except (AuthError, httpx.HTTPStatusError) as e:
            shutil.rmtree(tmp, ignore_errors=True)
            if isinstance(e, AuthError) or e.response.status_code == 401:
                raise HTTPException(status_code=401, detail="Токен недействителен")
            raise HTTPException(status_code=502, detail="Яндекс.Книги недоступны")
        except Exception as e:
            shutil.rmtree(tmp, ignore_errors=True)
            raise HTTPException(status_code=502, detail=f"Ошибка сборки: {e}")


@app.get("/api/download/file")
async def api_file(request: Request, id: str):
    _require(request)
    async with _prepared_lock:
        entry = _prepared.pop(id, None)
    if not entry or not Path(entry["path"]).exists():
        raise HTTPException(status_code=404, detail="Файл не найден или устарел")
    tmpdir = entry["dir"]
    return FileResponse(
        entry["path"],
        filename=entry["filename"],
        media_type="application/octet-stream",
        background=BackgroundTask(lambda: shutil.rmtree(tmpdir, ignore_errors=True)),
    )


# --- Статика ------------------------------------------------------------------
@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
