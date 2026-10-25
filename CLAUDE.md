# CLAUDE.md — карта проекта YaBooks_downloader

Загрузчик книг/аудиокниг/комиксов с Яндекс.Книги (Bookmate). CLI на Python,
async (`httpx`/`asyncio`), вывод через `rich`. Весь UI и строки — на русском.

## Запуск и окружение

- Установка: `uv venv` → `uv pip install -r requirements.txt` (или `.venv/bin/pip install -r requirements.txt`).
- Интерпретатор для команд: `.venv/bin/python`.
- Запуск: `python YaBooks_downloader.py [--max_bitrate|--min_bitrate] [URL|UUID]`.
  - Без аргументов — интерактивный режим (цикл: поиск по названию/автору ИЛИ ссылка/UUID; пустой ввод — выход).
  - С аргументом — одноразовая обработка и выход (контракт для скриптов).
- Аудиокнигам нужен **FFmpeg** (`ffmpeg`+`ffprobe`) в PATH.
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
| `src/utils.py` | `SystemExitException`, `sanitize_filename`, `format_series_position`. |

## Ключевые потоки

- **Ввод → загрузка.** `handle_input(value)`: `parse_input_url` распознаёт ссылку/UUID; иначе (или если UUID не разрешился) → `search_and_select`. Единственная точка маршрутизации — `_dispatch(content_type, uuid)` → `process_single_resource` / `process_series` / `process_author`.
- **Поиск.** `downloader.search(query, cursor)` → `(нормализованные результаты, cursor|None)`. Результат: `{content_type, uuid, title, authors:[str]}`. `search_and_select` показывает таблицу, принимает номера через пробел (мультивыбор), `+` (ещё по cursor), `0`/пусто (назад). Загрузка не закрывает список/программу.

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
