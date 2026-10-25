# CLAUDE.md — карта проекта YaBooks_downloader

Загрузчик книг/аудиокниг/комиксов с Яндекс.Книги (Bookmate). Python, async
(`httpx`/`asyncio`). Два интерфейса: **CLI** (вывод через `rich`) и **веб**
(FastAPI, пакет `web/`). Весь UI и строки — на русском.

## Запуск и окружение

- Установка: `uv venv` → `uv pip install -r requirements.txt` (или `.venv/bin/pip install -r requirements.txt`).
- Интерпретатор для команд: `.venv/bin/python`.
- Запуск: `python YaBooks_downloader.py [--max_bitrate|--min_bitrate] [URL|UUID]`.
  - Без аргументов — интерактивный режим (цикл: поиск по названию/автору ИЛИ ссылка/UUID; пустой ввод — выход).
  - С аргументом — одноразовая обработка и выход (контракт для скриптов).
- Аудиокнигам нужен **FFmpeg** (`ffmpeg`+`ffprobe`) в PATH.
- **Веб:** `.venv/bin/pip install -r requirements-web.txt`, запуск `uvicorn web.app:app`
  (локально: `WEB_COOKIE_SECURE=0` для http). Деплой — `Dockerfile`/`docker-compose.yml`
  (ffmpeg в образе). Переменные: `WEB_SECRET_KEY`, `WEB_COOKIE_SECURE`, `WEB_MAX_DOWNLOADS`, `PORT`.
- Проверка синтаксиса: `.venv/bin/python -m py_compile <файлы>`. **Тестов в репозитории нет** — проверяю скриптами против живого API (нужен валидный токен в `.env`).

## Структура

| Файл | Назначение |
|---|---|
| `YaBooks_downloader.py` | Точка входа. Класс `YaBooksApp`: интерактивный цикл `run()` → `handle_input()` → `_dispatch()` → `process_*`. FFmpeg-проверка, выбор битрейта, поиск. |
| `src/config.py` | Константы: `BASE_URL` (REST v5), `URLS`, `HEADERS`, `GRAPHQL_URL`, `SEARCH_QUERY`, лимиты параллелизма, UA, `MYBOOKS_DIR`. |
| `src/auth.py` | Токен в `.env` (`YANDEX_BOOKS_TOKEN`): `read_token/save_token/clear_token`, авто-миграция `token.txt`→`.env`, `get_auth_token`, OAuth-webview (`pywebview`). |
| `src/downloader.py` | `YandexBooksDownloader` — общий httpx-клиент (HTTP/2, `verify=False`), `api_get` (GET + ре-авторизация на 401 + 429), `search` (GraphQL), скачивание файлов, метаданные, серии. |
| `src/books.py` | `BooksDownloader.download` — сборка EPUB (`ebooklib`). |
| `src/audiobooks.py` | `AudiobooksDownloader` — склейка в M4B через FFmpeg, главы, `ask_bitrate` (бросает `SystemExitException` при выходе). |
| `src/comics.py` | `ComicsDownloader` — комиксы. |
| `src/utils.py` | `SystemExitException`, `AuthError` (токен истёк/невалиден → в вебе ре-логин), `sanitize_filename`, `format_series_position`. |
| `web/app.py` | FastAPI: `/api/login`, `/api/search`, `/api/items` (серия/автор), `/api/download/prepare`+`/file` (двухфазно), статика. Семафор `MAX_WEB_DOWNLOADS`, реестр собранных файлов, фоновая очистка temp. |
| `web/session.py` | Токен в подписанной HttpOnly-cookie (`itsdangerous`); сервер токены не хранит. |
| `web/static/` | SPA: `index.html` (вход + поиск + секции-грид), `app.js`, `style.css`. |

## Ключевые потоки

- **Ввод → загрузка (CLI).** `handle_input(value)`: `parse_input_url` распознаёт ссылку/UUID; иначе (или если UUID не разрешился) → `search_and_select`. Единственная точка маршрутизации — `_dispatch(content_type, uuid)` → `process_single_resource` / `process_series` / `process_author`.
- **Поиск.** `downloader.search(query, cursor)` → `(нормализованные результаты, cursor|None)`. Результат: `{content_type, uuid, title, authors:[str], cover_url}`. CLI: `search_and_select` (таблица, мультивыбор, `+`/`0`). Веб: `/api/search` группирует по `content_type` в секции.
- **Веб: мультиюзер и скачивание.** На запрос создаётся свой `YandexBooksDownloader` с токеном из cookie (`allow_interactive_reauth=False`, `base_dir`=temp — токены и файлы изолированы). `prepare` собирает файл теми же загрузчиками во временную папку → отдаётся браузером (`/file`, стрим) и удаляется. На сервере файлы не оседают.

## Семантика данных

- `content_type`: `"book"`, `"audiobook"`, `"comicbook"`, `"series"`, `"authors"` — единые значения на всех путях.
- Фильтр типов поиска — одна точка: `SEARCH_TYPENAME_TO_TYPE` в `src/downloader.py` (GraphQL `__typename` → `content_type`). Неподдерживаемое (Bookshelf/Publisher/Topic/User/TextSerial) отсеивается там же.
- Пути сохранения: `MyBooks/<Автор>/<Серия>/<позиция - название>`; имя автора нормализуется в «Фамилия Имя».

## Внешние API (неофициальные, важные нюансы)

- **REST**: `https://api.bookmate.yandex.net/api/v5` — инфо о книгах/аудио/комиксах/сериях/авторах, контент. Поиска в REST НЕТ.
- **Поиск = GraphQL**: `POST https://api-gateway.bookmate.yandex.net/graphql`, операция `Search`. Шлюз принимает **только whitelisted-запросы** — `SEARCH_QUERY` в `config.py` менять нельзя (должен быть байт-в-байт как у официального клиента, иначе `"Whitelist: query not found"`). Запрос ходит через тот же `self.client` (заголовок `auth-token`).
- В GraphQL у книг поле называется **`name`** (не `title`); у `TextBook/AudioBook/ComicBook` данные вложены в `node["book"]`, у `Series`/`Person` — на верхнем уровне узла.
- Связь форматов (не используется в UI, но есть): REST-инфо книги отдаёт `linked_audiobook_uuids` / `linked_book_uuids` (+ `variants_count`).
- Авторизация: заголовок `auth-token`. Токен берётся из `.env`/переменной окружения `YANDEX_BOOKS_TOKEN`. На 401 — `clear_token()` + повторная авторизация через webview.

## Соглашения

- **DRY/KISS строго.** Одна точка истины для логики (маршрутизация — `_dispatch`; фильтр типов — `SEARCH_TYPENAME_TO_TYPE`; эндпоинты/запросы — `config.py`). Без спекулятивных абстракций.
- Повторные попытки — `tenacity` (`@retry`), уже импортирован в `downloader.py`.
- Пользовательские строки и комментарии — на русском, вывод — `rich`.
- Git: ветки/коммиты делает пользователь; в конце показывать `git diff --stat`.
- При изменениях обновлять `README.md` (пользовательская дока) и `requirements.txt` (при новых зависимостях).

## Секреты

`.env` и `token.txt` — в `.gitignore`, не коммитить. Реальный токен в запросы к API слать можно (это и есть назначение), но не в сторонние сервисы.
