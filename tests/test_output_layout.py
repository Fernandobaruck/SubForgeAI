import hashlib,json,tempfile,unittest
from pathlib import Path
from studio_ui.output_layout import compact_result,sidecar_path,is_internal
from speech_context import write_context,read_context

class OutputLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def test_single_ass_preserves_intermediate_and_reports(self):
        source=self.root/'episode.PTBR.srt';source.write_text('original text',encoding='utf-8')
        final=self.root/'episode.PTBR.visual.ass';final.write_text('styled text',encoding='utf-8')
        write_context(final,source,{},source_kind='subtitle')
        side=sidecar_path(final,'.source.json');data=json.loads(side.read_text(encoding='utf-8'));data['visual_source_path']=str(source.resolve());side.write_text(json.dumps(data),encoding='utf-8')
        Path(str(source)+'.quality.json').write_text(json.dumps({'findings':[{'block':1,'flags':['reading_speed']}]}),encoding='utf-8')
        self.assertEqual(compact_result(final,source),str(final.resolve()))
        visible=[p for p in self.root.iterdir() if p.is_file()]
        self.assertEqual(visible,[final])
        archived=self.root/'.subforge'/source.name
        self.assertEqual(archived.read_text(),'original text')
        self.assertEqual(read_context(final)['visual_source_path'],str(archived))
        self.assertEqual(read_context(final)['source_file'],str(archived))
        self.assertTrue(sidecar_path(final,'.quality.json').is_file())
        self.assertTrue(is_internal(archived))
        self.assertEqual(compact_result(final),str(final.resolve()))
    def test_srt_only_moves_json_not_subtitle(self):
        final=self.root/'a.srt';final.write_text('text');write_context(final,final,{})
        compact_result(final)
        self.assertTrue(final.is_file());self.assertTrue(read_context(final))
        self.assertFalse(Path(str(final)+'.source.json').exists())
    def test_different_archived_version_is_preserved(self):
        final=self.root/'a.ass';final.write_text('ass')
        source=self.root/'a.srt';source.write_text('one');compact_result(final,source)
        source.write_text('two');compact_result(final,source)
        self.assertEqual(sorted(p.read_text() for p in (self.root/'.subforge').glob('*.srt')),['one','two'])
    def test_new_run_does_not_overwrite_archived_provenance(self):
        source=self.root/'a.srt';source.write_text('one');write_context(source,source,{'A':'A'})
        final=self.root/'a.ass';final.write_text('ass');compact_result(final,source)
        archived=self.root/'.subforge'/source.name;before=sidecar_path(archived,'.source.json').read_bytes()
        source.write_text('two');write_context(source,source,{'B':'B'})
        self.assertEqual(sidecar_path(archived,'.source.json').read_bytes(),before)
        self.assertEqual(read_context(source)['confirmed_terms'],{'B':'B'})
    def test_legacy_sidecar_remains_readable(self):
        final=self.root/'a.srt';final.write_text('text');write_context(final,final,{})
        self.assertTrue(read_context(final));self.assertTrue(Path(str(final)+'.source.json').is_file())
    def test_invalid_metadata_does_not_move_any_subtitle(self):
        source=self.root/'a.srt';source.write_text('source')
        final=self.root/'a.ass';final.write_text('ass')
        Path(str(final)+'.source.json').write_text('{broken')
        with self.assertRaises(ValueError):compact_result(final,source)
        self.assertEqual(source.read_text(),'source');self.assertEqual(final.read_text(),'ass')
    def test_review_loads_archived_quality_report(self):
        from review_workspace import SubtitleDocument
        final=self.root/'a.srt';final.write_text('1\n00:00:01,000 --> 00:00:03,000\nFala.\n',encoding='utf-8')
        Path(str(final)+'.quality.json').write_text(json.dumps({'findings':[{'block':1,'flags':['reading_speed'],'source':'Line.'}]}))
        compact_result(final);doc=SubtitleDocument(final)
        self.assertIn('reading_speed',doc.reported[0]);self.assertEqual(doc.original_texts[0],'Line.')

if __name__=='__main__':unittest.main()
