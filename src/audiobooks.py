"""Загрузка аудиокниг"""
import asyncio
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple

import aiofiles
from rich.console import Console

from src.config import URLS
from src.downloader import YandexBooksDownloader
from src.utils import SystemExitException, format_series_position

console = Console()


class AudiobooksDownloader:
    """Загрузчик аудиокниг"""
    
    def __init__(self, downloader: YandexBooksDownloader):
        self.downloader = downloader

    def ask_bitrate(self) -> str:
        try:
            console.print("\n[bold]Выберите качество аудио:[/bold]")
            console.print("1. Максимальное (по умолчанию)")
            console.print("2. Минимальное (быстрее, меньше размер)")
            console.print("0. Выход")
            choice = console.input("[bold]Выберите качество [1/2/0/] (1): [/bold]").strip()
            if choice == "0":
                raise SystemExitException()
            elif choice == "2":
                return "min_bit_rate"
            return "max_bit_rate"
        except SystemExitException:
            raise
        except Exception:
            return "max_bit_rate"

    async def download(self, resource: dict, metadata: Optional[dict] = None, verbose: bool = False) -> bool:
        uuid = resource["uuid"]
        if not metadata:
            info, metadata = await self.downloader.get_resource_info(uuid, "audiobook")
            if info and not self.downloader.check_availability(info, "audiobook"):
                title = metadata.get('title', 'Неизвестно')
                if verbose:
                    console.print(f"[red]Пропуск (недоступна):[/red] {title}")
                else:
                    console.print(f"[red]   ✗   (недоступна)[/red]")
                return False
        
        if metadata.get("series_list"):
            series_uuid = metadata["series_list"][0].get("uuid")
            if series_uuid:
                try:
                    series_books = await self.downloader.get_series_books(series_uuid)
                    for series in metadata["series_list"]:
                        if series.get("uuid") == series_uuid:
                            series["total_parts"] = len(series_books)
                            for i, book in enumerate(series_books, start=1):
                                if book.get("uuid") == uuid:
                                    series["position_label"] = str(i)
                                    break
                except Exception:
                    pass
        
        playlist_url = URLS["audiobook_playlist"].format(uuid=uuid)
        try:
            playlist_data = await self.downloader.api_get(playlist_url)
        except Exception as e:
            console.print(f"\n[red]Ошибка получения плейлиста:[/red] {e}")
            return False
        
        tracks = playlist_data.get("tracks", [])
        if not tracks:
            console.print("\n[red]Треки не найдены[/red]")
            return False
        
        tracks.sort(key=lambda x: x.get("number", 0))
        
        chapters_info = []
        for track in tracks:
            offline = track.get("offline", {})
            bitrate_data = offline.get(self.downloader.bitrate_mode, {})
            url = bitrate_data.get("url")
            
            if not url:
                alt_mode = "min_bit_rate" if self.downloader.bitrate_mode == "max_bit_rate" else "max_bit_rate"
                bitrate_data = offline.get(alt_mode, {})
                url = bitrate_data.get("url")
            
            if url:
                url = url.replace(".m3u8", ".m4a")
                chapter_number = track.get("number", len(chapters_info) + 1)
                chapter_title = track.get("title", f"Глава {chapter_number:02d}")
                
                duration_info = track.get("duration", {})
                chapters_info.append({
                    "url": url,
                    "number": chapter_number,
                    "title": chapter_title,
                    "offset": duration_info.get("offset", 0),
                    "duration": duration_info.get("seconds", 0),
                })
        
        if not chapters_info:
            console.print("\n[red]Не найдены ссылки для скачивания аудио[/red]")
            return False
        
        title = resource.get("title", "Неизвестное название")
        authors = resource.get("authors", [])
        author = authors[0] if authors else "Неизвестный автор"
        
        series_name = None
        series_position = None
        
        if metadata.get("series_list") and isinstance(metadata["series_list"][0], dict):
            first_series = metadata["series_list"][0]
            series_name = first_series.get("title")
            position = first_series.get("position_label", "1")
            series_position = format_series_position(position)
        
        path = self.downloader.build_book_path(author, title, series_name, series_position)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        m4b_path = Path(str(path) + ".m4b")
        
        cover_url = metadata.get("cover_url")
        if not cover_url:
            cover_url = resource.get("cover", {}).get("large")
        
        cover_data = None
        if cover_url:
            try:
                cover_data = await self.downloader.download_file_content(cover_url)
            except Exception:
                pass
        
        temp_dir = path.parent / f"temp_{uuid}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        console.print(f"   [cyan]Скачивание глав ({len(chapters_info)} шт.)...[/cyan]")
        audio_files, successful_chapters = await self._download_chapters(chapters_info, temp_dir)
        
        if not audio_files:
            console.print("\n   [red]Не удалось скачать ни одной главы[/red]")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False
        
        console.print("   [cyan]Объединение глав в M4B...[/cyan]")
        success = await self.merge_chapters(audio_files, successful_chapters, m4b_path, cover_data, metadata)
        
        shutil.rmtree(temp_dir, ignore_errors=True)
        
        if success and m4b_path.exists():
            file_size = m4b_path.stat().st_size
            console.print(f"[green]Аудиокнига загружена   ✓   ({file_size / 1024 / 1024:.1f} МБ)[/green]")
            return True
        else:
            console.print("\n   [red]Не удалось создать M4B файл[/red]")
            return False

    async def _download_chapters(self, chapters_info: List[dict], temp_dir: Path) -> Tuple[List[Path], List[dict]]:
        """Параллельно скачивает главы (не более MAX_CONCURRENT_DOWNLOADS
        одновременно, см. self.downloader.download_semaphore).

        Возвращает списки только успешно скачанных файлов и
        соответствующих им глав — списки синхронны по индексам, порядок
        может не совпадать с порядком в chapters_info (т.к. загрузки
        завершаются в произвольном порядке), но это не важно: дальше
        файлы/главы всегда сопоставляются по номеру главы, а не по
        позиции в списке (см. merge_chapters).
        """
        total = len(chapters_info)
        done_count = 0

        async def _download_one(chapter: dict):
            nonlocal done_count
            async with self.downloader.download_semaphore:
                chapter_num = chapter["number"]
                chapter_file = temp_dir / f"Глава_{chapter_num:02d}.m4a"
                result = None
                try:
                    await self.downloader.download_file_sequential(chapter["url"], chapter_file)
                    if chapter_file.exists() and chapter_file.stat().st_size > 0:
                        result = (chapter_file, chapter)
                except Exception as e:
                    console.print(f"\n   [yellow]Ошибка скачивания {chapter['title']}:[/yellow] {e}")
                done_count += 1
                console.print(f"   [dim]Скачано глав: {done_count}/{total}[/dim]", end='\r')
                return result

        results = await asyncio.gather(*[_download_one(c) for c in chapters_info])
        console.print(" " * 40, end='\r')  # затираем строку прогресса

        audio_files = [r[0] for r in results if r]
        successful_chapters = [r[1] for r in results if r]
        return audio_files, successful_chapters

    @staticmethod
    def _chapter_number_from_filename(path: Path) -> int:
        """Извлекает номер главы из имени временного файла"""
        match = re.search(r'Глава_(\d+)\.m4a', path.name)
        return int(match.group(1)) if match else 0

    @staticmethod
    async def _get_audio_duration(path: Path) -> float:
        """Точная длительность аудиофайла (в секундах) через ffprobe.

        Используется вместо длительности из ответа API, чтобы разметка
        глав всегда соответствовала фактическому содержимому файла
        (без накопления ошибки округления/расхождений с API).
        """
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(path),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, _ = await process.communicate()
            return float(stdout.decode().strip())
        except Exception:
            return 0.0

    async def merge_chapters(
        self, 
        audio_files: List[Path], 
        chapters_info: List[dict],
        output_path: Path, 
        cover_data: Optional[bytes], 
        metadata: dict
    ) -> bool:
        """Объединение глав в M4B с метаданными.

        `chapters_info` должен содержать только те главы, файлы которых
        реально скачаны (см. вызов из `download()`), в противном случае
        разметка глав разойдётся с фактическим содержимым файла.
        """
        temp_dir = output_path.parent / "merge_temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        filelist_path = temp_dir / "chapters_list.txt"
        chapters_metadata_path = temp_dir / "chapters_metadata.txt"
        cover_path = temp_dir / "cover.jpg"
        temp_output = temp_dir / "output.m4b"
        
        try:
            if cover_data:
                async with aiofiles.open(cover_path, "wb") as f:
                    await f.write(cover_data)
            
            audio_files = sorted(audio_files, key=self._chapter_number_from_filename)

            # Сопоставляем скачанные файлы с их главами по номеру (а не по
            # позиции в списке) — так разметка не собьётся, если какая-то
            # глава не была скачана и выпала из списка.
            chapters_by_number = {c.get("number"): c for c in chapters_info}
            ordered_chapters = [
                chapters_by_number.get(self._chapter_number_from_filename(f), {})
                for f in audio_files
            ]
            
            async with aiofiles.open(filelist_path, 'w', encoding='utf-8') as f:
                for chapter_file in audio_files:
                    abs_path = str(chapter_file.absolute()).replace("'", "'\"'\"'")
                    await f.write(f"file '{abs_path}'\n")
            
            async with aiofiles.open(chapters_metadata_path, 'w', encoding='utf-8') as f:
                await f.write(";FFMETADATA1\n")
                
                if metadata:
                    if metadata.get("title"):
                        await f.write(f"title={self._escape(metadata['title'])}\n")

                    # Автор(ы) -> Artist, с дублированием в Author
                    authors = metadata.get("authors") or []
                    if authors:
                        authors_str = ", ".join(authors)
                        await f.write(f"artist={self._escape(authors_str)}\n")
                        await f.write(f"author={self._escape(authors_str)}\n")

                    # Чтец(ы) -> Composer, с дублированием в Album Artist
                    narrators = metadata.get("narrators") or []
                    if narrators:
                        narrators_str = ", ".join(narrators)
                        await f.write(f"composer={self._escape(narrators_str)}\n")
                        await f.write(f"album_artist={self._escape(narrators_str)}\n")
                    
                    if metadata.get("annotation"):
                        desc = metadata["annotation"].replace("\n", " ").replace("\r", " ")[:500]
                        await f.write(f"description={self._escape(desc)}\n")
                    
                    # Жанры (topics) -> Genre; служебные метки формата
                    # ("Виртуальный рассказчик", "Аудио") уже отфильтрованы
                    # в extract_metadata()
                    if metadata.get("genres"):
                        await f.write(f"genre={self._escape(', '.join(metadata['genres']))}\n")
                    
                    if metadata.get("language"):
                        await f.write(f"language={metadata['language']}\n")
                    
                    year = self._extract_year(metadata.get("publication_date"))
                    await f.write(f"date={year}\n")
                    
                    if metadata.get("owner_catalog_title"):
                        await f.write(f"copyright={self._escape(metadata['owner_catalog_title'])}\n")
                    
                    if metadata.get("age_restriction"):
                        await f.write(f"rating={metadata['age_restriction']}\n")
                    
                    if metadata.get("publishers"):
                        await f.write(f"publisher={self._escape(metadata['publishers'][0])}\n")
                    
                    if metadata.get("series_list"):
                        series = metadata["series_list"][0]
                        if series.get("title"):
                            await f.write(f"album={self._escape(series['title'])}\n")
                        if series.get("position_label"):
                            try:
                                track_num = int(float(series["position_label"]))
                                total = series.get("total_parts", 0)
                                if total > 0:
                                    await f.write(f"track={track_num}/{total}\n")
                                else:
                                    await f.write(f"track={track_num}\n")
                            except (ValueError, TypeError):
                                pass

                # Разметка глав: смещение считаем по фактической длительности
                # уже скачанных файлов (ffprobe), а не по данным из API —
                # это гарантирует правильный офсет от начала аудиокниги,
                # даже если какие-то главы не скачались или их
                # длительность в API отличается от реальной.
                # Все ffprobe-вызовы выполняются параллельно, а не по
                # очереди — на десятках глав это заметно быстрее.
                durations = await asyncio.gather(*[self._get_audio_duration(f) for f in audio_files])

                cumulative_offset = 0.0
                for chapter_file, chapter, duration in zip(audio_files, ordered_chapters, durations):
                    if duration <= 0:
                        # Фолбэк на данные API, если ffprobe не смог определить длительность
                        duration = float(chapter.get("duration", 0) or 0)

                    chapter_title = chapter.get("title") or f"Глава {chapter.get('number', '')}"
                    start_ms = int(round(cumulative_offset * 1000))
                    end_ms = int(round((cumulative_offset + duration) * 1000))

                    await f.write("\n[CHAPTER]\n")
                    await f.write("TIMEBASE=1/1000\n")
                    await f.write(f"START={start_ms}\n")
                    await f.write(f"END={end_ms}\n")
                    await f.write(f"title={self._escape(chapter_title)}\n")

                    cumulative_offset += duration
            
            cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                   '-i', str(filelist_path), '-i', str(chapters_metadata_path)]
            
            if cover_path.exists():
                cmd.extend(['-i', str(cover_path), '-c:v', 'copy', '-c:a', 'copy',
                           '-disposition:v:0', 'attached_pic', '-map_metadata', '1'])
            else:
                cmd.extend(['-c', 'copy', '-map_metadata', '1'])
            
            # Все теги (включая artist/author/composer/album_artist/genre и
            # главы) уже записаны в chapters_metadata_path и применяются
            # через -map_metadata 1 выше. Оставляем только URL источника,
            # который нигде больше не пишется.
            if metadata and metadata.get("source"):
                cmd.extend(['-metadata', f'URL={metadata["source"]}'])
            
            cmd.append(str(temp_output))
            
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await process.communicate()
            
            if process.returncode == 0 and temp_output.exists() and temp_output.stat().st_size > 0:
                if output_path.exists():
                    output_path.unlink()
                temp_output.rename(output_path)
                return True
            else:
                return False
                    
        except Exception as e:
            console.print(f"\n   [red]Ошибка при объединении:[/red] {e}")
            return False
        finally:
            for temp_file in [filelist_path, chapters_metadata_path, cover_path, temp_output]:
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except Exception:
                        pass
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass

    @staticmethod
    def _extract_year(pub_date) -> str:
        """Извлекает год публикации из publication_date.

        API может отдавать это поле по-разному: строкой ("2015-06-01"),
        числом-таймстампом (секунды или миллисекунды) или null — код
        должен корректно отработать в любом из случаев и не падать.
        """
        if pub_date:
            if isinstance(pub_date, str):
                candidate = pub_date.split("-")[0].strip()
                if candidate.isdigit():
                    return candidate
            elif isinstance(pub_date, (int, float)):
                try:
                    ts = pub_date / 1000 if pub_date > 1e12 else pub_date
                    return str(datetime.utcfromtimestamp(ts).year)
                except (ValueError, OSError, OverflowError):
                    pass
        return str(datetime.now().year)

    @staticmethod
    def _escape(value: str) -> str:
        """Экранирование специальных символов для FFMETADATA"""
        return str(value).replace('=', '\\=').replace(';', '\\;').replace('#', '\\#').replace('\\', '\\\\')
