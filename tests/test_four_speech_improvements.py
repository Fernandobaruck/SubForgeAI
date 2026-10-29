from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import subtitle_quality as Q
import ollama_script as O
from speech_context import read_context,write_context,uncertain_cue
from speech_refinement import candidate_decision,timing_defects,replace_aligned_window


class FourSpeechImprovements(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tests');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_series_terms_follow_subtitle_outside_original_folder(self):
        origin=self.root/'series'/'video.mkv';origin.parent.mkdir();origin.touch()
        (origin.parent/'series_glossary.json').write_text(json.dumps({'Mira':'Mira','月の塔':'Torre da Lua'}),encoding='utf-8')
        original=Q.SeriesTerms(origin,[],self.root/'cache','ja')
        generated=self.root/'output.srt';generated.write_text('dialogue')
        write_context(generated,origin,original.explicit)
        inherited=Q.SeriesTerms(generated,[],self.root/'cache','ja')
        self.assertEqual(inherited.explicit,original.explicit)
        self.assertEqual(inherited.relevant('月の塔に行く'),{'月の塔':'Torre da Lua'})

    def test_edited_or_mismatched_subtitle_cannot_reuse_stale_context(self):
        source=self.root/'episode.srt';source.write_text('old')
        write_context(source,self.root/'movie.mkv',{'Mira':'Mira'})
        source.write_text('different episode')
        self.assertEqual(read_context(source),{})

    def test_context_snapshot_survives_missing_original_video(self):
        source=self.root/'episode.srt';source.write_text('text')
        write_context(source,self.root/'not-present/video.mkv',{'Mira':'Mira'})
        self.assertEqual(Q.SeriesTerms(source,[],self.root/'cache','ja').explicit,{'Mira':'Mira'})

    def test_confirmed_cue_memory_is_inherited_from_video_folder(self):
        origin=self.root/'series/video.mkv';origin.parent.mkdir();origin.touch()
        (origin.parent/'series_memory.json').write_text(json.dumps({'月の光':'Luz da lua.'}),encoding='utf-8')
        source=self.root/'generated.srt';source.write_text('月の光',encoding='utf-8')
        write_context(source,origin,{})
        self.assertEqual(Q.SeriesTerms(source,[],self.root/'cache','ja').memory_for('月の光'),'Luz da lua.')

    def test_different_meaning_is_not_selected_just_for_better_score(self):
        old=[dict(text='扉を開ける',confidence=.4)]
        new=[dict(text='彼女は魚を食べます',confidence=.99)]
        accepted,reason=candidate_decision(old,new,lambda s:s['confidence'])
        self.assertFalse(accepted);self.assertEqual(reason,'recognition_disagreement')

    def test_aligned_equivalent_candidate_can_correct_times(self):
        old=[dict(text='扉を開ける',confidence=-.4)]
        new=[dict(text='扉を開ける。',confidence=-.4,words=[])]
        accepted,reason=candidate_decision(old,new,lambda s:s['confidence'],alignment=True)
        self.assertTrue(accepted);self.assertEqual(reason,'local_alignment_confirmed')

    def test_replacing_window_keeps_dialogue_on_both_sides(self):
        words=[dict(start=i,end=i+1,word=t) for i,t in enumerate(['A','B','C','D'])]
        original=[dict(start=0,end=4,text='ABCD',words=words)]
        replacement=[dict(start=1,end=3,text='BC',words=words[1:3])]
        result=replace_aligned_window(original,1,3,replacement)
        self.assertEqual(''.join(s['text'] for s in result),'ABCD')
        self.assertEqual([s['start'] for s in result],[0,1,3])

    def test_discontinuous_words_trigger_bounded_audio_windows(self):
        words=[dict(start=79,end=80,word='我'),dict(start=212,end=214,word='は放つ')]
        windows=timing_defects([dict(words=words)])
        self.assertTrue(any(start<212<end for start,end in windows))
        self.assertTrue(all(end-start<12 for start,end in windows))

    def test_short_input_in_japanese_document_cannot_expand_into_song(self):
        self.assertIn('excessive_expansion',Q.quality_flags('I','Eu quero meu amor e proteger você com minhas próprias mãos.',1,{},'ja'))
        self.assertNotIn('excessive_expansion',Q.quality_flags('I','Eu',1,{},'ja'))

    def test_context_short_japanese_call_does_not_include_neighbour_dialogue(self):
        with patch.object(O,'ACTIVE_SOURCE_LANGUAGE','ja'),patch.object(O,'ACTIVE_SERIES_HINTS',{}),patch.object(O,'_ollama_call',return_value='O pingente do mestre.') as call:
            O._context_call('model','お師匠様のペンダント','NEIGHBOUR_BEFORE','NEIGHBOUR_AFTER',{})
            prompt=call.call_args.args[1][0]['content']
            self.assertNotIn('NEIGHBOUR_BEFORE',prompt)
            self.assertNotIn('NEIGHBOUR_AFTER',prompt)

    def test_latin_spelling_is_not_misclassified_as_japanese_entity_leak(self):
        self.assertEqual(Q.context_flags('ミラはどこ','Onde está Mira?',{'Mira':'Mira'}),[])

    def test_uncertainty_follows_matching_cue_only(self):
        context={'uncertain_ranges':[dict(start=210,end=216)]}
        self.assertTrue(uncertain_cue('00:03:32,000 --> 00:03:35,000',context))
        self.assertFalse(uncertain_cue('00:04:00,000 --> 00:04:02,000',context))

    def test_invalid_expansion_in_old_cache_is_retranslated(self):
        source=self.root/'input.srt';source.write_text('1\n00:00:01,000 --> 00:00:04,000\nI\n')
        write_context(source,self.root/'video.mkv',{})
        output=self.root/'out.srt';cache={};progress={}
        with patch.object(O,'ACTIVE_SOURCE_LANGUAGE','ja'):
            base=O._cache_context(source,'translategemma:12b',['I'],'.srt')
            cache[base+':'+('a'*40)+':0']='Eu quero meu amor e proteger você com minhas próprias mãos.'
            with patch.object(O,'_ollama_call',return_value='Eu') as call:
                O.translate_srt(source,output,'translategemma:12b',cache,progress)
        self.assertEqual(call.call_count,1)
        self.assertIn('\nEu\n',output.read_text())
        self.assertNotIn('proteger',output.read_text())
        report=json.loads(Path(str(output)+'.quality.json').read_text(encoding='utf-8'))
        self.assertIn('source_fragment',report['findings'][0]['flags'])

    def test_blocked_later_cue_preserves_validated_checkpoint(self):
        source=self.root/'input.srt';source.write_text('1\n00:00:01,000 --> 00:00:04,000\nHello.\n\n2\n00:00:05,000 --> 00:00:06,000\nI\n')
        cache,progress={},{};snapshots=[]
        bad='Eu quero meu amor e proteger você com minhas próprias mãos.'
        output=self.root/'out.srt'
        with patch.object(O,'ACTIVE_SOURCE_LANGUAGE','ja'),patch.object(O,'_ollama_call',side_effect=['Olá.']+[bad]*O.MAX_RETRIES):
            with self.assertRaises(O.InvalidModelOutput):
                O.translate_srt(source,output,'translategemma:12b',cache,progress,checkpoint=lambda:snapshots.append(dict(cache)))
        self.assertFalse(output.exists())
        self.assertTrue(any('Olá.' in values.values() for values in snapshots))
        self.assertFalse(any(bad in values.values() for values in snapshots))
        self.assertTrue(Path(str(output)+'.review_required.json').is_file())


if __name__=='__main__':unittest.main()
