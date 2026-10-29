from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from whisper_audio import choose_stream,local_faster_model
import whisper_script as W


def stream(index,lang,default=False,title='',comment=False):
    return dict(index=index,codec_type='audio',tags=dict(language=lang,title=title),
                disposition=dict(default=int(default),comment=int(comment)))


class WhisperAudioTests(unittest.TestCase):
    def test_anime_auto_uses_japanese_instead_of_default_english_dub(self):
        self.assertEqual(choose_stream([stream(1,'eng',True),stream(2,'jpn')])['index'],2)

    def test_explicit_english_is_respected(self):
        self.assertEqual(choose_stream([stream(1,'eng',True),stream(2,'jpn')],'en')['index'],1)

    def test_explicit_audio_stream_is_respected(self):
        self.assertEqual(choose_stream([stream(1,'eng',True),stream(2,'jpn')],selection='1')['index'],1)

    def test_mismatched_language_cannot_silently_transcribe_a_dub(self):
        with self.assertRaises(ValueError):choose_stream([stream(1,'eng',True)],'ja')
        with self.assertRaises(ValueError):choose_stream([stream(1,'eng',True)],'ja','1')

    def test_subtitle_index_cannot_be_selected_as_audio(self):
        with self.assertRaises(ValueError):choose_stream([stream(1,'eng'),dict(index=2,codec_type='subtitle')],selection='2')

    def test_commentary_is_not_preferred_over_original_audio(self):
        self.assertEqual(choose_stream([stream(1,'jpn',True,comment=True),stream(2,'jpn')])['index'],2)

    def test_japanese_commentary_does_not_override_normal_dialogue(self):
        self.assertEqual(choose_stream([stream(1,'jpn',True,comment=True),stream(2,'eng')])['index'],2)

    def test_unknown_metadata_uses_default_and_does_not_force_japanese(self):
        selected=choose_stream([stream(1,'und'),stream(2,'und',True)])
        self.assertEqual(selected['index'],2)

    def test_demucs_and_whisper_receive_same_explicit_audio_map(self):
        for function in (W.ffmpeg_extract_wav,W.ffmpeg_extract_hq_audio):
            with patch.object(W,'resolve_ffmpeg',return_value='ffmpeg.exe'),patch.object(W.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
                self.assertEqual(function(Path('input.mkv'),Path('output.wav'),2),0)
                command=run.call_args.args[0]
                self.assertEqual(command[command.index('-map')+1],'0:2')

    def test_complete_cached_snapshot_is_opened_directly(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as name:
            root=Path(name);store=root/'cache/hub/models--Systran--faster-whisper-large-v3'
            snapshot=store/'snapshots'/('a'*40);snapshot.mkdir(parents=True)
            (store/'refs').mkdir();(store/'refs/main').write_text('a'*40)
            for filename in ('model.bin','config.json','tokenizer.json'):(snapshot/filename).touch()
            self.assertEqual(local_faster_model('large-v3',root),str(snapshot.resolve()))
            (snapshot/'tokenizer.json').unlink()
            self.assertEqual(local_faster_model('large-v3',root),'large-v3')

    def test_empty_gap_needs_confidence_but_real_short_japanese_survives(self):
        weak=dict(text="We'll be right back.",avg_logprob=-1.7,avg_word_prob=.2,no_speech_prob=.8)
        self.assertFalse(W._accept_gap_candidate(weak))
        strong=dict(text='愛',avg_logprob=-.1,avg_word_prob=.9,no_speech_prob=.01)
        self.assertTrue(W._accept_gap_candidate(strong))

    def test_uncertain_japanese_is_flagged_without_being_deleted(self):
        segments=[dict(start=1,end=2,text='愛',avg_word_prob=.4,avg_logprob=-.1)]
        findings=W.transcription_findings(segments,'ja')
        self.assertEqual(findings[0]['flags'],['low_word_confidence'])
        self.assertEqual(segments[0]['text'],'愛')

    def test_latin_phrase_in_japanese_transcript_is_reviewed_not_rewritten(self):
        segments=[dict(start=1,end=2,text='on my left go',avg_word_prob=.48)]
        self.assertIn('unexpected_latin_phrase',W.transcription_findings(segments,'ja')[0]['flags'])
        self.assertNotIn('unexpected_latin_phrase',W.transcription_findings(segments,'en')[0]['flags'])

    def test_duration_limit_does_not_split_a_japanese_word(self):
        words=[dict(start=0,end=4.4,word='これは不'),dict(start=4.4,end=6,word='調です。')]
        blocks=W._split_by_words(words,max_dur=4.5,gap_split=.48)
        self.assertEqual(len(blocks),1)
        self.assertEqual(W._words_text(blocks[0]),'これは不調です。')

    def test_japanese_sentence_boundary_can_split_long_cue(self):
        words=[dict(start=0,end=4.4,word='終わりました。'),dict(start=4.4,end=6,word='次です。')]
        self.assertEqual(len(W._split_by_words(words,max_dur=4.5,gap_split=.48)),2)


if __name__=='__main__':unittest.main()
