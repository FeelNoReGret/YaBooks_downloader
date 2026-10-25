# src/config.py
"""Конфигурация и константы"""
import random
from pathlib import Path

BASE_URL = "https://api.bookmate.yandex.net/api/v5"

MYBOOKS_DIR = Path("MyBooks")
# Папка создаётся явно при старте приложения (см. YaBooks_downloader.py),
# а не здесь на уровне модуля — импорт config.py не должен иметь побочных
# эффектов на файловой системе.

MAX_CONCURRENT_DOWNLOADS = 3
MAX_AUDIO_DOWNLOADS = 6

# Число попыток скачивания одного ресурса (книги/аудиокниги/комикса)
# при пакетной или одиночной загрузке. Некоторые книги отдают ошибку
# "недоступна" нестабильно — при единичном скачивании по прямой ссылке
# они скачиваются нормально, поэтому имеет смысл повторить попытку
# несколько раз перед тем, как считать ресурс окончательно недоступным.
DOWNLOAD_RETRY_ATTEMPTS = 3
# Пауза между повторными попытками (в секундах)
DOWNLOAD_RETRY_DELAY = 2

TITLE_MAX_LENGTH = 60

UA = {
    1: "Samsung/Galaxy_A51 Android/12 Bookmate/6.66.0",
    2: "Huawei/P40_Lite Android/11 Bookmate/6.66.0",
    3: "OnePlus/Nord_N10 Android/10 Bookmate/6.66.0",
    4: "Google/Pixel_4a Android/9 Bookmate/6.66.0",
    5: "Oppo/Reno_4 Android/8 Bookmate/6.66.0",
    6: "Xiaomi/Redmi_Note_9 Android/10 Bookmate/6.66.0",
    7: "Motorola/Moto_G_Power Android/10 Bookmate/6.66.0",
    8: "Sony/Xperia_10 Android/10 Bookmate/6.66.0",
    9: "LG/Velvet Android/10 Bookmate/6.66.0",
    10: "Realme/6_Pro Android/10 Bookmate/6.66.0",
}

HEADERS = {
    "app-user-agent": UA[random.randint(1, 10)],
    "auth-token": "",
    "user-agent": "",
}

URLS = {
    "series_parts": f"{BASE_URL}/series/{{uuid}}/parts?per_page=500",
    "books_info": f"{BASE_URL}/books/{{uuid}}",
    "audiobooks_info": f"{BASE_URL}/audiobooks/{{uuid}}",
    "comicbooks_info": f"{BASE_URL}/comicbooks/{{uuid}}",
    "book_content": f"{BASE_URL}/books/{{uuid}}/content/v4",
    "audiobook_playlist": f"{BASE_URL}/audiobooks/{{uuid}}/playlists.json",
    "comicbook_meta": f"{BASE_URL}/comicbooks/{{uuid}}/metadata.json",
    "author_books": f"{BASE_URL}/authors/{{uuid}}/books?role=author&per_page=500",
    "author_audiobooks": f"{BASE_URL}/authors/{{uuid}}/audiobooks?role=author&per_page=500",
    "author_comicbooks": f"{BASE_URL}/authors/{{uuid}}/comicbooks?role=author&per_page=500",
}

GRAPHQL_URL = "https://api-gateway.bookmate.yandex.net/graphql"

# Строка GraphQL-запроса поиска. Шлюз принимает ТОЛЬКО whitelisted-запросы,
# поэтому текст менять нельзя — он должен точно совпадать с запросом клиента.
SEARCH_QUERY = """
query Search($query: SearchParamsInput!) {
    search(query: $query) {
        page {
            __typename
            ...searchSnippetAudioBookFragment
            ...searchSnippetTextBookFragment
            ...searchSnippetComicBookFragment
            ...searchSnippetTextSerialFragment
            ...bookshelfFragment
            ...personFragment
            ...publisherFragment
            ...seriesFragment
            ...topicFragment
            ...userFragment
        }
        cursor
        rankedFilter { filterType }
        misspell { correctedText correctionType }
    }
}
fragment coverFragment on Cover { url ratio backgroundColorHex }
fragment personFragment on Person { avatar { __typename ...coverFragment } name uuid worksCount roles }
fragment bookFragment on Book { annotation name cover { __typename ...coverFragment } uuid authors { __typename ...personFragment } ageRestriction editorAnnotation }
fragment publisherFragment on Publisher { avatar { __typename ...coverFragment } name uuid worksCount }
fragment publisherBookFragment on Book { publisher { __typename ...publisherFragment } }
fragment translatorsBookFragment on Book { translators { __typename ...personFragment } }
fragment topicsBookFragment on Book { topics { name totalBook uuid } }
fragment subscriptionLevelsFragment on Book { subscriptionLevels }
fragment snippetBookFragment on Book { __typename ...bookFragment ...publisherBookFragment ...translatorsBookFragment ...topicsBookFragment ...subscriptionLevelsFragment }
fragment bookTagFragment on Tag { name value }
fragment narratorsAudioBookFragment on AudioBook { narrators { __typename ...personFragment } }
fragment progressFragment on Progress { finished inLibrary progress isPublic }
fragment progressAudioBookFragment on AudioBook { progress { __typename ...progressFragment } }
fragment listenersCountAudioBookFragment on AudioBook { listenersCount }
fragment searchSnippetAudioBookFragment on AudioBook { __typename book { __typename ...snippetBookFragment tags { __typename ...bookTagFragment } } ...narratorsAudioBookFragment ...progressAudioBookFragment ...listenersCountAudioBookFragment }
fragment progressTextBookFragment on TextBook { progress { __typename ...progressFragment } }
fragment readersCountTextBookFragment on TextBook { readersCount }
fragment searchSnippetTextBookFragment on TextBook { __typename book { __typename ...snippetBookFragment tags { __typename ...bookTagFragment } } ...progressTextBookFragment ...readersCountTextBookFragment }
fragment progressComicBookFragment on ComicBook { progress { __typename ...progressFragment } }
fragment readersCountComicBookFragment on ComicBook { readersCount }
fragment searchSnippetComicBookFragment on ComicBook { __typename book { __typename ...snippetBookFragment tags { __typename ...bookTagFragment } } ...progressComicBookFragment ...readersCountComicBookFragment }
fragment textSerialFragment on TextSerial { book { __typename ...bookFragment } }
fragment episodesTextSerialFragment on TextSerial { episodes { total } }
fragment readersCountTextSerialFragment on TextSerial { readersCount }
fragment searchSnippetTextSerialFragment on TextSerial { __typename book { __typename ...snippetBookFragment tags { __typename ...bookTagFragment } } ...textSerialFragment ...episodesTextSerialFragment ...readersCountTextSerialFragment }
fragment userFragment on User { avatar { __typename ...coverFragment } name uuid followersCount login }
fragment bookshelfFragment on Bookshelf { cover { __typename ...coverFragment } name uuid user { __typename ...userFragment } posts { total } followersCount description }
fragment seriesFragment on Series { authors { __typename ...personFragment } cover { __typename ...coverFragment } name uuid items { followersCount total } }
fragment topicFragment on Topic { name slug totalBook uuid parent { name slug totalBook uuid } }
"""
