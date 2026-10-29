"""Regression checks for the seven issues in the 28/10 review."""
from pathlib import Path
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import ollama_script as O
import pipeline_io as IO
import whisper_script as W
import extract_subs as X
import embed_script as E
from glossary_support import Glossary






class SevenFixes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="seven-fixes-", dir=str(ROOT / "tests"))
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.log = io.StringIO()
        self.output = contextlib.redirect_stdout(self.log)
        self.output.__enter__(); self.addCleanup(self.output.__exit__, None, None, None)
        for name, value in (("TEMPO_ENTRE_REQS", 0), ("REVIEW_MODE", "disabled"), ("MODELO_OLLAMA", "legacy-test-model")):
            mocked = patch.object(O, name, value); mocked.start(); self.addCleanup(mocked.stop)

    def subtitle(self, name="input.srt", text="Hello there."):
        path = self.base / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("1\n00:00:00,000 --> 00:00:01,000\n" + text + "\n", encoding="utf-8")
        return path

    def test_export_collision_preserves_both_files(self):
        src = self.subtitle("source/episode.srt", "NEW")
        old = self.subtitle("destination/episode.srt", "REVIEWED")
        actual = IO.export_result(src, old)
        self.assertEqual(actual.name, "episode_2.srt")
        self.assertIn("REVIEWED", old.read_text(encoding='utf-8'))
        self.assertIn("NEW", actual.read_text(encoding='utf-8'))
        self.assertFalse(src.exists())

    def test_export_same_folder_is_noop_and_failure_preserves_source(self):
        src = self.subtitle()
        self.assertEqual(IO.export_result(src, src), src)
        with patch.object(IO.shutil, "copy2", side_effect=OSError("copy failed")):
            with self.assertRaises(OSError): IO.export_result(src, self.base / "out.srt")
        self.assertTrue(src.exists()); self.assertFalse((self.base / "out.srt").exists())

    def test_publish_refuses_destination_created_during_copy(self):
        src = self.subtitle("source.srt", "NEW")
        destination = self.base / "destination.srt"
        native_copy = IO.shutil.copy2
        def competing_copy(source, temporary):
            result = native_copy(source, temporary)
            destination.write_text("OTHER WRITER", encoding="utf-8")
            return result
        with patch.object(IO.shutil, "copy2", side_effect=competing_copy):
            with self.assertRaises(FileExistsError): IO.export_result(src, destination)
        self.assertTrue(src.exists())
        self.assertEqual(destination.read_text(encoding='utf-8'), "OTHER WRITER")


    def test_empty_duplicate_and_prompt_items_are_rejected(self):
        for reply, count in (("<<<1>>>Oi\n<<<2>>>", 2),
                             ("<<<1>>>Oi\n<<<1>>>Outro", 1),
                             ("<<<2>>>Oi", 1),
                             ("<<<1>>>SRC:\nCat\nPT:\nGato", 1)):
            with self.subTest(reply=reply): self.assertIsNone(O._parse_marked(reply, count))

    def test_retries_do_not_publish_original_for_missing_translation(self):
        src = self.subtitle(); out = self.base / "out"
        with patch.object(O, "_ollama_call", return_value="<<<1>>>"):
            with self.assertRaises(O.TranslationBatchError): O.translate_paths([src], out)
        self.assertFalse(list(out.glob("*.srt")))
        self.assertTrue((out / "_cache_traducao").exists())

    def test_bad_reply_can_recover_on_retry(self):
        with patch.object(O, "_ollama_call", side_effect=["<<<1>>>", "<<<1>>>Oi!"]) as call:
            self.assertEqual(O._translate_with_retries("model", ["Hello"]), ["Oi!"])
        self.assertEqual(call.call_count, 2)

    def test_refinement_uses_only_current_translation_format(self):
        item = json.dumps({"source": "<i>Cat</i>", "translation": "<i>Gato</i>"})
        with patch.object(O, "_ollama_call", return_value="<<<1>>>⟦TAG0⟧Gatinho⟦TAG1⟧"):
            self.assertEqual(O._llm_refine_call("m", [item], "Refine"), ["<i>Gatinho</i>"])
        with patch.object(O, "_ollama_call", return_value="<<<1>>>SRC:\nCat\nPT:\nGato"):
            with self.assertRaises(O.InvalidModelOutput): O._llm_refine_call("m", [item], "Refine")

    def test_format_tokens_roundtrip_and_bad_responses(self):
        text = "{\\i1}<i>First</i>\\NSecond\n[Música]{\\i0}"
        safe, mapping = O._protect_tags(text)
        self.assertEqual(O._restore_tags(safe, mapping), text)
        damaged = safe.replace("⟦TAG", "⟦ tag_")
        self.assertEqual(O._restore_tags(damaged, mapping), text)
        for bad in ("No tokens", safe + "⟦TAG0⟧", safe.replace("⟦TAG0⟧", "⟦TAG999⟧")):
            with self.subTest(bad=bad):
                with self.assertRaises(O.InvalidModelOutput): O._restore_tags(bad, mapping)

    def test_missing_or_invented_html_is_not_accepted(self):
        for source, reply in (("<i>Hello</i>", "<<<1>>>Oi"),
                              ("Hello", "<<<1>>><i>Oi</i>")):
            with patch.object(O, "_ollama_call", return_value=reply):
                with self.assertRaises(O.InvalidModelOutput): O._translate_batch("m", [source])

    def test_review_has_its_own_format_map(self):
        with patch.object(O, "REVIEW_MODE", "always"), patch.object(O, "_ollama_call", side_effect=[
                "<<<1>>>⟦TAG0⟧Oi⟦TAG1⟧", "<<<1>>>⟦TAG0⟧Olá⟦TAG1⟧"]):
            self.assertEqual(O._translate_batch("m", ["<i>こんにちは</i>"]), ["<i>Olá</i>"])

    def test_ass_preserves_fonts_comments_and_field_order(self):
        source = ("[Script Info]\r\nScriptType: v4.00+\r\n[Events]\r\n"
                  "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\r\n"
                  "Comment: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,keep\r\n"
                  "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Hello, world\r\n"
                  "[Fonts]\r\nfontname: font.ttf\r\nencoded-data\r\n")
        header, cues = O.parse_ass(source)
        self.assertEqual(O.build_ass(header, cues), source)
        result = O.build_ass(header, [(cues[0][0], "Oi, mundo")])
        self.assertEqual(result, source.replace("Hello, world", "Oi, mundo"))
        reordered = "[Events]\nFormat: Start, Text, End\nDialogue: 0:00:00.00,Hello, world,0:00:01.00\n"
        h, c = O.parse_ass(reordered)
        self.assertEqual(c[0][1], "Hello, world")
        self.assertEqual(O.build_ass(h, [(c[0][0], "Oi")]), reordered.replace("Hello, world", "Oi"))

    def test_vtt_preserves_ids_notes_style_and_settings(self):
        source = ("WEBVTT\n\nSTYLE\n::cue { color: red; }\n\n"
                  "cue-42\n00:00.000 --> 00:01.000 align:start\nHello\n\n"
                  "NOTE comment stays here\n\nNOTE1\n00:01.000 --> 00:02.000\nGoodbye\n")
        header, cues = O.parse_vtt(source)
        self.assertEqual(len(cues), 2)
        self.assertEqual(O.build_vtt(header, cues), source)
        result = O.build_vtt(header, [(cues[0][0], "Oi"), (cues[1][0], "Tchau")])
        self.assertEqual(result, source.replace("Hello", "Oi").replace("Goodbye", "Tchau"))

    def test_partial_extraction_preserves_files_and_returns_error(self):
        streams = [dict(index=1, codec_name="subrip", tags={}), dict(index=2, codec_name="subrip", tags={})]
        saved = self.subtitle("partial/first.srt")
        with patch.object(X, "_ffprobe_streams", return_value=streams), patch.object(X, "_run_to_output", side_effect=[
                (0, "", saved), (1, "simulated failure", self.base / "missing.srt")]):
            code = X._extract_from_video("ffmpeg", "ffprobe", self.base / "input.mkv", self.base / "extract", "srt", "all")
        self.assertEqual(code, 4); self.assertTrue(saved.exists())


    def test_japanese_short_speech_is_preserved(self):
        for text in ("愛", "あ", "え?", "王"):
            result = W.filter_segments({"segments": [dict(start=0, end=1, text=text,
                                       avg_logprob=-0.01, avg_word_prob=0.99)]})
            self.assertEqual(result[0]["text"], text)
        self.assertFalse(W.filter_segments({"segments": [dict(start=0, end=1, text="...")]}))

    def test_portuguese_does_not_trigger_english_repair(self):
        for pt in ("O livro do irmão do João.", "Do que você está falando?", "Não gosto do nome do rapaz."):
            self.assertFalse(O._has_english_residual(pt, pt))
            self.assertFalse(O._has_english_residual("The book is here.", pt))
            self.assertFalse(O._needs_review([pt, pt], [pt, pt]))
            with patch.object(O, "_retry_no_english_line") as retry:
                self.assertEqual(O._repair_english_residual_lines("m", [pt], [pt]), [pt])
                retry.assert_not_called()
        self.assertTrue(O._has_english_residual("猫", "The cat is here."))

    def test_glossary_is_selected_in_prompts_and_cache_identity(self):
        path = self.base / "glossary.json"
        path.write_text(json.dumps({"東条": "Tojo", "Unrelated": "Outro"}), encoding="utf-8")
        glossary = Glossary(path)
        with patch.object(O, "GLOSSARY", glossary), patch.object(O, "_ollama_call", return_value="<<<1>>>Tojo chegou.") as call:
            key1 = O._cache_context(self.base / "x.srt", "m", ["東条が来た"], "T1")
            self.assertEqual(O._translate_batch("m", ["東条が来た"]), ["Tojo chegou."])
            prompt = call.call_args.args[1][-1]["content"]
            self.assertIn('"東条" -> "Tojo"', prompt); self.assertNotIn('"Unrelated" ->', prompt)
            IO.atomic_write_text(path, json.dumps({"東条": "Toujou"}))
            key2 = O._cache_context(self.base / "x.srt", "m", ["東条が来た"], "T1")
            self.assertNotEqual(key1, key2)
        self.assertTrue(O.GLOSSARY.terms())

    def test_refinement_and_all_passes_use_glossary(self):
        path = self.base / "terms.json"; path.write_text('{"Cat": "Gato"}', encoding='utf-8')
        item = json.dumps({"source": "Cat", "translation": "Gato"})
        with patch.object(O, "GLOSSARY", Glossary(path)), patch.object(O, "_ollama_call", return_value="<<<1>>>Gato") as call:
            self.assertEqual(O._llm_refine_call("m", [item], "Refine"), ["Gato"])
            self.assertIn("GLOSSÁRIO DO PROJETO", call.call_args.args[1][-1]["content"])

    def test_full_multipass_preserves_tags_and_resumes(self):
        source = self.subtitle(text="<i>Hello</i>")
        cache, progress = {}, {}
        options = dict(file_path=source, src_texts=["<i>Hello</i>"], model="m",
                       cache=cache, progress=progress, save_cache_fn=lambda: None,
                       save_prog_fn=lambda: None, mode="enabled_plus")
        reply = "<<<1>>>⟦TAG0⟧Olá⟦TAG1⟧"
        with patch.object(O, "_ollama_call", return_value=reply) as call:
            self.assertEqual(O._multipass_pipeline(**options), ["<i>Olá</i>"])
            self.assertEqual(call.call_count, 5)
        with patch.object(O, "_ollama_call", side_effect=AssertionError("cached pass called model")):
            self.assertEqual(O._multipass_pipeline(**options), ["<i>Olá</i>"])

    def test_glossary_cli_missing_file_reports_error(self):
        src = self.subtitle()
        with patch.object(sys, "argv", ["ollama_script.py", str(src), "--glossary", str(self.base / "missing.json")]):
            self.assertEqual(O.main_cli(), 2)

    def test_real_ffmpeg_still_embeds_correct_track_and_extracts(self):
        ff = ROOT / "tools/ffmpeg/ffmpeg.exe"; probe = ff.with_name("ffprobe.exe")
        original = self.subtitle("original.srt"); translated = self.subtitle("translated.srt", "Legenda nova.")
        video = self.base / "video.mkv"
        result = subprocess.run([str(ff), "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=1:d=1",
            "-i", str(original), "-map", "0:v", "-map", "1:0", "-c:v", "mpeg4", "-c:s", "srt",
            "-metadata:s:s:0", "language=eng", "-t", "1", str(video)], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = E.mux_softsub(str(video), str(translated), str(self.base / "mux"), ffmpeg_path=str(ff))
        result = subprocess.run([str(probe), "-v", "error", "-select_streams", "s", "-show_entries",
            "stream=index:stream_tags=language", "-of", "json", output], capture_output=True, timeout=15)
        streams = json.loads(result.stdout)["streams"]
        self.assertEqual([s["tags"]["language"] for s in streams], ["eng", "por"])
        code = X._extract_from_video(str(ff), str(probe), Path(output), self.base / "extract", "srt", str(streams[1]["index"]))
        self.assertEqual(code, 0)
        self.assertIn("Legenda nova", next((self.base / "extract").rglob("*.srt")).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
