import os
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

from core.catalog import build_groups, merge_channel, order_by_date
from core.converter_bridge import ConvertResult, install_speed, use_fast_gpu
from core.errors import Cancelled, diagnose
from core.export import assign_numbers, search_texts, write_lists
from core.filters import matches
from core.fmt import fold
from core.links import classify
from core.models import Channel, Playlist, Settings, Video
from core.naming import safe_name, text_filename
from core.queue_runner import build_items, run
from core.selection import export_order, group_mark, set_group, summary, toggle_one
from core.subtitles import _pick_track, cues_to_body, find_snippet, parse_vtt


def video(video_id, title, duration=60, date="", kind="video"):
    return Video(id=video_id, title=title, duration_sec=duration, upload_date=date, kind=kind)


class LinkTests(unittest.TestCase):
    def test_channel_handle_and_tabs(self):
        link = classify("  https://www.youtube.com/@ekonomist_n/videos?si=abc  ")
        self.assertEqual(link.kind, "channel")
        self.assertEqual(link.handle, "ekonomist_n")
        self.assertNotIn("/videos", link.url)

    def test_video_strips_tracking(self):
        link = classify("https://youtu.be/abcdefghijk?t=12&si=zzz")
        self.assertEqual(link.kind, "video")
        self.assertEqual(link.video_id, "abcdefghijk")
        self.assertNotIn("si=", link.url)

    def test_playlist_and_junk(self):
        link = classify("https://www.youtube.com/playlist?list=PLabcdefghijklmnop")
        self.assertEqual(link.kind, "playlist")
        self.assertEqual(link.playlist_id, "PLabcdefghijklmnop")
        self.assertEqual(classify("https://example.com/watch?v=abcdefghijk").kind, "bad")
        self.assertIn("не похоже", classify("просто текст").message)


class NamingTests(unittest.TestCase):
    def test_forbidden_and_length(self):
        self.assertEqual(safe_name('a/b:c*?"'), "a b c")
        self.assertFalse(safe_name("конец... ").endswith("."))
        self.assertLessEqual(len(safe_name("я" * 200)), 120)
        self.assertEqual(safe_name("CON"), "_CON")
        self.assertEqual(safe_name("aux"), "_aux")
        self.assertTrue(text_filename(2, "Инфляция", "20230228", "number").startswith("002 - "))
        self.assertTrue(text_filename(2, "Инфляция", "20230228", "date").startswith("2023-02-28 - "))


class SelectionTests(unittest.TestCase):
    def test_dedup_and_partial(self):
        groups = [
            ("tab:videos", "Все видео", ["a", "b", "c"]),
            ("pl:1", "Основы", ["b", "c"]),
            ("loose", "Видео вне плейлистов", ["a"]),
        ]
        manual = set_group(set(), ["b", "c"], True)
        manual = toggle_one(manual, "a", True)
        self.assertEqual(group_mark(manual, ["b", "c"]), "on")
        self.assertEqual(group_mark(manual, ["a", "b", "c"]), "on")
        manual = toggle_one(manual, "c", False)
        self.assertEqual(group_mark(manual, ["b", "c"]), "partial")
        ordered = [video_id for video_id, _title in export_order(groups, manual)]
        self.assertEqual(ordered, ["b", "a"])
        info = summary(groups, manual, {"a": video("a", "A", 10), "b": video("b", "B", 20), "c": video("c", "C", 30)}, {"a"})
        self.assertEqual(info["count"], 2)
        self.assertEqual(info["ready"], 1)
        self.assertEqual(info["whole_playlists"], 0)


class FilterTests(unittest.TestCase):
    def test_yo_and_exclude_and_undated(self):
        item = video("a", "Ёлка и инфляция", 300, "20200101")
        item.description = "рост цен"
        self.assertTrue(matches(item, "елка", "", None, None, now=datetime(2026, 1, 1)))
        self.assertFalse(matches(item, "", "инфляция", None, None))
        undated = video("b", "Без даты", 10, "")
        self.assertTrue(matches(undated, "", "", None, 7, now=datetime(2026, 1, 1)))
        self.assertFalse(matches(item, "", "", None, 7, now=datetime(2026, 1, 1)))


class CatalogTests(unittest.TestCase):
    def test_merge_marks_new_and_keeps_details(self):
        old = Channel(id="UC1", title="Канал", videos={
            "aaa": Video(id="aaa", title="Старое", details_loaded=True, description="текст", upload_date="20200101"),
        }, tabs={"videos": ["aaa"], "streams": [], "shorts": []})
        new = Channel(id="UC1", title="Канал", videos={
            "aaa": Video(id="aaa", title="Новое имя"),
            "bbb": Video(id="bbb", title="Свежее"),
        }, tabs={"videos": ["bbb", "aaa"], "streams": [], "shorts": []})
        fresh = merge_channel(old, new)
        self.assertEqual(fresh, ["bbb"])
        self.assertTrue(new.videos["bbb"].is_new)
        self.assertEqual(new.videos["aaa"].description, "текст")
        self.assertEqual(new.videos["aaa"].title, "Новое имя")
        self.assertEqual(order_by_date(new, ["bbb", "aaa"]), ["aaa", "bbb"])


class ExportTests(unittest.TestCase):
    def test_csv_bom_and_aligned_lines(self):
        channel = Channel(id="UC1", title="Канал", videos={
            "aaa": video("aaa", "Первое\nимя", 70, "20230214"),
            "bbb": video("bbb", "Второе", 80, "20230301"),
        })
        numbers = assign_numbers({"aaa": 4}, ["aaa", "bbb"])
        self.assertEqual(numbers["aaa"], 4)
        self.assertEqual(numbers["bbb"], 5)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_lists(folder, channel, [(channel.videos["aaa"], "Плейлист"), (channel.videos["bbb"], "Плейлист")], numbers, "number")
            links = (folder / "links.txt").read_text(encoding="utf-8").splitlines()
            titles = (folder / "titles.txt").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(links), len(titles))
            self.assertNotIn("\n", titles[0])
            raw = (folder / "список.csv").read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            text = raw.decode("utf-8-sig")
            self.assertIn(";", text)
            self.assertIn("Первое имя", text)


class SubtitleTests(unittest.TestCase):
    def test_vtt_and_snippet(self):
        cues = parse_vtt(
            "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nИнфляция это рост\n\n"
            "00:00:04.000 --> 00:00:08.000\nИнфляция это рост\n\n"
            "00:00:09.000 --> 00:00:12.000\nЦен растёт дальше\n"
        )
        self.assertEqual(len(cues), 2)
        body = cues_to_body(cues)
        self.assertIn("[0:01]", body)
        self.assertIn("рост цен", fold(find_snippet(cues, "рост цен")))


class QueueTests(unittest.TestCase):
    def test_skip_ready_continue_and_stop(self):
        channel = Channel(id="UC1", title="Канал", videos={
            "aaa": video("aaa", "Первое", 30),
            "bbb": video("bbb", "Второе", 30),
            "ccc": Video(id="ccc", title="Закрыто", availability="unavailable"),
        })
        settings = Settings(data_dir=".", converter={"path": "", "language": "Авто", "model": "Авто", "text_mode": "Оригинал", "max_accuracy": True}, pause_between_sec=0, file_header=True)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "Тексты").mkdir()
            items, _ratio = build_items(channel, ["aaa", "bbb", "ccc"], {"aaa": 1, "bbb": 2, "ccc": 3}, folder, "number")
            self.assertEqual([item.status for item in items], ["waiting", "waiting", "skipped"])
            calls = []

            def convert(url, _settings, progress, cancel, log=None):
                calls.append(url)
                progress(0.4, "распознавание")
                if log:
                    log("Модель: small")
                if "bbb" in url:
                    raise Cancelled()
                return ConvertResult("привет мир", "ru", "small", 30, "Первое", "конвертер (модель small, оригинал)")

            events = []
            run(channel, items, folder, settings, {}, events.append, threading.Event(), threading.Event(), convert)
            self.assertEqual(calls, ["https://www.youtube.com/watch?v=aaa", "https://www.youtube.com/watch?v=bbb"])
            self.assertTrue((folder / "Тексты" / "001 - Первое.txt").is_file())
            text = (folder / "Тексты" / "001 - Первое.txt").read_text(encoding="utf-8")
            self.assertIn("Название: Первое", text)
            self.assertIn("привет мир", text)
            self.assertEqual(items[1].status, "waiting")
            again, _ratio = build_items(channel, ["aaa", "bbb", "ccc"], {"aaa": 1, "bbb": 2, "ccc": 3}, folder, "number")
            self.assertEqual(again[0].status, "done")
            self.assertEqual(again[1].status, "waiting")
            found = search_texts(folder, channel, ["aaa"], {"aaa": 1}, "number", "привет")
            self.assertEqual(len(found), 1)


class ReviewTests(unittest.TestCase):
    def test_diagnose_does_not_match_word_pieces(self):
        samples = [
            ("Unable to download API page: HTTP Error 503", "network"),
            ("ConnectionResetError(10054) message", "network"),
            ("Unable to download webpage: timed out", "network"),
            ("Requested format is not available", "outdated"),
            ("Video unavailable. This content isn't available, try again later", "ratelimit"),
            ("Sign in to confirm your age", "need_login"),
            ("Sign in to confirm you’re not a bot", "bot"),
            ("Private video", "unavailable"),
        ]
        for message, kind in samples:
            with self.subTest(message=message):
                self.assertEqual(diagnose(message)[0], kind)

    def test_download_wrapper_reports_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "a.m4a"
            audio.write_bytes(b"x" * 1000)

            class Fake:
                def ydl_common(self, **extra):
                    return {}

                def download_audio(self, url, folder, log):
                    return str(audio), "t", 10, "ru"

                def fmt_dur(self, seconds):
                    return f"{float(seconds):.0f}с"

            module = Fake()
            install_speed(module)
            logs = []
            self.assertEqual(module.download_audio("u", tmp, logs.append)[0], str(audio))
            self.assertTrue(any("Скачивание заняло" in line for line in logs))

    def test_auto_subs_prefer_original(self):
        picked = _pick_track({
            "language": "en",
            "automatic_captions": {
                "en-orig": [{"ext": "json3", "url": "http://orig"}],
                "ru": [{"ext": "vtt", "url": "http://ru"}],
            },
        })
        self.assertEqual(picked[0], "en")
        self.assertFalse(picked[2])

    def test_rename_keeps_ready_file(self):
        channel = Channel(id="UC1", title="Канал", videos={"aaa": video("aaa", "Новое имя", 30)})
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "Тексты").mkdir()
            (folder / "Тексты" / "001 - Старое имя.txt").write_text("Название: Старое имя\n\nтекст готов вполне\n", encoding="utf-8")
            items, _ratio = build_items(channel, ["aaa"], {"aaa": 1}, folder, "number")
            self.assertEqual(items[0].status, "done")
            self.assertEqual(items[0].out_file, str(Path("Тексты") / "001 - Старое имя.txt"))


class PlanTests(unittest.TestCase):
    def test_lemma_synonyms_windows_and_level(self):
        from core.indexer import to_windows
        from core.lemma import lemma, lemmatize, load_synonyms
        from core.search import Metrics, fts_query, level

        self.assertEqual(lemma("супер-эго"), "суперэго")
        self.assertEqual(lemma("Ид"), "ид")
        self.assertEqual(lemma("сверх-я"), "сверхя")
        self.assertIn("когнитивный", lemmatize("когнитивное искажение"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "синонимы.txt"
            path.write_text("эго, ~я, ego\nид, оно, id\n", encoding="utf-8")
            _groups, index, weak = load_synonyms(path)
            self.assertEqual(index[lemma("эго")], index["ego"])
            self.assertIn("я", weak)
            self.assertIn("оно", weak)
            self.assertNotIn("id", weak)
            query = fts_query("эго", *_unpack(path))
            self.assertIn("ego", query)
            self.assertNotIn('"я"', query)
        self.assertEqual(to_windows([{"start": 10, "text": "а"}, {"start": 70, "text": "б"}])[1][0], 60)
        self.assertEqual(level(Metrics(focus=16, mentions=2), 1), 5)
        self.assertEqual(level(Metrics(mentions=1, in_title=True), 2), 1)
        self.assertEqual(level(Metrics(mentions=4), 1), 3)

    def test_search_finds_synonym_in_memory_db(self):
        from core.index_db import IndexDB
        from core.search import search

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            synonyms = folder / "синонимы.txt"
            synonyms.write_text("когнитивное искажение, ошибка мышления\n", encoding="utf-8")
            db = IndexDB(folder / "index.sqlite")
            db.replace_video(
                "aaaaaaaaaaa", "ch", 600,
                [(0, "здесь когнитивное искажение и ещё раз", "speech")],
                ("Лекция", "описание", ""),
                "subs_manual", "ru",
            )
            found = search(folder / "index.sqlite", "ошибка мышления", synonyms)
            self.assertTrue(found)
            self.assertEqual(found[0].video_id, "aaaaaaaaaaa")
            self.assertGreaterEqual(found[0].level, 1)
            dated = folder / "Тексты"
            dated.mkdir()
            video_id = "bbbbbbbbbbb"
            (dated / "2023-02-28 - Старое имя.txt").write_text(
                f"Ссылка: https://www.youtube.com/watch?v={video_id}\n\nтекст\n", encoding="utf-8",
            )
            from core.export import text_path
            found_path = text_path(folder, 2, "Новое имя", "20230228", "date", video_id=video_id)
            self.assertEqual(found_path.name, "2023-02-28 - Старое имя.txt")

    def test_storyboard_plateau_merge_and_dark_board(self):
        from PIL import Image
        from core.ocr import prepare_image
        from core.storyboard import analyse
        from core.visual import merge_timeline

        same = [(second, 1) for second in range(0, 80, 10)]
        kind, _moments = analyse(same, plateau_sec=20)
        self.assertEqual(kind, "talking")
        slides = []
        for index, digest in enumerate((0, 0xFFFF, 0xFFFFFFFF, 0xFF00FF00, 0x00FF00FF)):
            slides.extend((index * 40 + offset, digest) for offset in range(0, 40, 10))
        kind, moments = analyse(slides, plateau_sec=20)
        self.assertEqual(kind, "slides")
        self.assertGreaterEqual(len(moments), 5)
        body = merge_timeline([(0, "речь")], [{"t": 12, "text": "Производная", "latex": ["x"]}])
        self.assertIn("[СЛАЙД", body)
        self.assertIn("LaTeX: x", body)
        dark = prepare_image(Image.new("L", (8, 8), 10))
        self.assertGreater(dark.getpixel((0, 0)), 200)


def _unpack(path):
    from core.lemma import load_synonyms
    groups, index, weak = load_synonyms(path)
    return groups, index, weak


class SpeedTests(unittest.TestCase):
    def test_small_card_uses_fast_mode(self):
        accurate, note = use_fast_gpu(True, 6141)
        self.assertFalse(accurate)
        self.assertIn("6 ГБ", note)
        self.assertTrue(use_fast_gpu(True, 12288)[0])
        self.assertFalse(use_fast_gpu(False, 12288)[0])
        self.assertTrue(use_fast_gpu(True, 0)[0])

    def test_long_video_stays_one_pass(self):
        class Module:
            ONE_SHOT_SEC = 20 * 60

            def normalize_lang(self, code):
                return "ru" if code == "ru" else None

            def lang_label(self, code):
                return code

            def resolve_language(self, model, path, duration, title, track_lang, user_lang, log):
                return "en"

        module = Module()
        install_speed(module)
        install_speed(module)
        self.assertGreaterEqual(module.ONE_SHOT_SEC, 3 * 60 * 60)
        notes = []
        self.assertEqual(
            module.resolve_language(None, "", 3600, "", "ru", None, notes.append),
            "ru",
        )
        self.assertEqual(len(notes), 1)


class WindowTests(unittest.TestCase):
    def test_window_builds_with_channel(self):
        os.environ["WY_TEST"] = "1"
        tmp = tempfile.mkdtemp()
        os.environ["WY_HOME"] = tmp
        home = Path(tmp)
        home.mkdir(exist_ok=True)
        from core.storage import save_settings
        settings = Settings(
            data_dir=str(home / "data"),
            converter={"path": str(Path(__file__).resolve().parents[1].parent / "MP4-TXT"), "language": "Авто", "model": "Авто", "text_mode": "Оригинал", "max_accuracy": True},
        )
        save_settings(settings)
        from ui.app import App
        app = App(settings)
        app.withdraw()
        channel = Channel(
            id="UC123",
            handle="ekonomist_n",
            title="Экономист N",
            url="https://www.youtube.com/@ekonomist_n",
            scanned_at=datetime.now().isoformat(timespec="minutes"),
            videos={
                "aaaaaaaaaaa": video("aaaaaaaaaaa", "Что такое ВВП и почему его все считают", 42 * 60 + 10, "20230214"),
                "bbbbbbbbbbb": video("bbbbbbbbbbb", "Инфляция простыми словами", 48 * 60 + 35, "20230228"),
            },
            playlists=[Playlist(id="PL1", title="Основы макроэкономики", video_ids=["aaaaaaaaaaa", "bbbbbbbbbbb"])],
            tabs={"videos": ["aaaaaaaaaaa", "bbbbbbbbbbb"], "streams": [], "shorts": []},
        )
        app.channel = channel
        app.manual = {"aaaaaaaaaaa", "bbbbbbbbbbb"}
        app.nav_key = "pl:PL1"
        app.channel_tab.reload(True)
        app.update_idletasks()
        self.assertIn("Экономист N", app.channel_tab.card_title.cget("text"))
        self.assertIn("Основы макроэкономики", app.channel_tab.view_title.cget("text"))
        self.assertEqual(len(app.channel_tab.table.tree.get_children()), 2)
        self.assertIn("Отмечено: 2 видео", app.channel_tab.total.cget("text"))
        app.destroy()


if __name__ == "__main__":
    unittest.main()
