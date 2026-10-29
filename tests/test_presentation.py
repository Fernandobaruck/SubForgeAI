"""Persistent display preferences and complete, data-safe UI localization."""
import json,re,tempfile,unittest
from pathlib import Path
from string import Formatter
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication
from studio_ui.backend import Backend
from studio_ui.presentation import Translations,COLORS,normalize_preferences,UI_DEFAULTS

ROOT=Path(__file__).resolve().parents[1]
class Runtime:
    def _stop_managed_ollama_server(self,**kwargs):pass
    def kill_all_active_procs(self):pass

class PresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tests');self.root=Path(self.temp.name)
        self.backend=Backend(self.root,Runtime(),monitor_enabled=False)
    def tearDown(self):
        self.backend.shutdown();self.app.processEvents();self.temp.cleanup()
    def test_original_theme_and_portuguese_are_defaults(self):
        self.assertEqual(self.backend.uiTheme,'dark');self.assertEqual(self.backend.uiLanguage,'pt-BR')
        self.assertEqual(self.backend.themePalette['bg'],'#101216');self.assertEqual(self.backend.themePalette['accent'],'#a78bfa')
    def test_invalid_saved_preferences_fall_back(self):
        self.assertEqual(normalize_preferences({'ui_language':[], 'ui_theme':'missing'}),UI_DEFAULTS)
    def test_preferences_persist_and_preserve_processing_and_custom_keys(self):
        data={'whisper_language':'ja','whisper_model':'large-v3','runtime_python':'portable.exe','custom':42}
        (self.root/'config.json').write_text(json.dumps(data),encoding='utf-8')
        self.backend.updateSetting('ui_language','en');self.backend.updateSetting('ui_theme','light')
        stored=json.loads((self.root/'config.json').read_text(encoding='utf-8'))
        self.assertEqual({key:stored[key] for key in data},data)
        self.assertEqual(stored['ui_language'],'en');self.assertEqual(stored['ui_theme'],'light')
        restored=self.backend._load_settings();self.assertEqual(restored['ui_language'],'en');self.assertEqual(restored['ui_theme'],'light')
    def test_display_can_change_while_busy_processing_settings_stay_locked(self):
        previous=self.backend.settings['whisper_model'];self.backend._busy=True
        self.backend.updateSetting('ui_language','es');self.backend.updateSetting('ui_theme','light')
        self.backend.updateSetting('whisper_model','large-v3')
        self.assertEqual(self.backend.uiLanguage,'es');self.assertEqual(self.backend.uiTheme,'light')
        self.assertEqual(self.backend.settings['whisper_model'],previous);self.backend._busy=False
    def test_invalid_preferences_are_rejected(self):
        self.backend.updateSetting('ui_language','de');self.backend.updateSetting('ui_theme','other')
        self.assertEqual(self.backend.uiLanguage,'pt-BR');self.assertEqual(self.backend.uiTheme,'dark')
    def test_save_failure_does_not_apply_visual_change(self):
        with patch('studio_ui.backend.atomic_write_text',side_effect=OSError('disk full')):
            self.backend.updateSetting('ui_theme','light')
        self.assertEqual(self.backend.uiTheme,'dark')
    def test_queue_codes_and_filename_survive_language_change(self):
        source=self.root/'Concluído · Início.srt';source.touch();self.backend.addFiles([str(source)])
        self.backend._items[0].update(state='Concluído',stage='Concluído');self.backend.changed.emit()
        self.backend.updateSetting('ui_language','en');row=self.backend.items[0]
        self.assertEqual(row['state'],'Concluído');self.assertEqual(row['stateLabel'],'Completed');self.assertEqual(row['name'],source.name)
        self.assertEqual(self.backend.completed,1)
    def test_dynamic_notifications_are_translated(self):
        self.backend.updateSetting('ui_language','es');messages=[];self.backend.message.connect(messages.append)
        self.backend.addFiles([str(self.root/'missing.srt')])
        self.assertEqual(messages[-1],'1 archivo(s) no disponible(s) o con formato no compatible.')
    def test_status_preview_suffix_and_error_details_are_localized(self):
        tr=Translations()
        self.assertEqual(tr.message('en','Transcrevendo áudio · episode.srt'),'Transcribing audio · episode.srt')
        self.assertEqual(tr.message('es','episode.srt · 3 bloco(s) sinalizado(s)'),'episode.srt · 3 bloque(s) señalado(s)')
        self.assertEqual(tr.message('en','Extraindo legendas falhou (código 4). Veja o diagnóstico.'),'Extracting subtitles failed (code 4). See diagnostics.')
        self.assertEqual(tr.message('en','C:/Videos/Concluído.srt'),'C:/Videos/Concluído.srt')
    def test_subtitle_document_and_raw_logs_are_never_translated(self):
        source=self.root/'episode.srt';text='1\n00:00:01,000 --> 00:00:02,000\nInício\n';source.write_text(text,encoding='utf-8')
        self.backend.inspectResult(str(source));self.backend._console='Início\n[INFO] arquivo original'
        self.backend.updateSetting('ui_language','en')
        self.assertEqual(self.backend.preview,text);self.assertEqual(self.backend.console,'Início\n[INFO] arquivo original')
    def test_video_placeholder_is_translated(self):
        source=self.root/'episode.mkv';source.touch();self.backend.inspectResult(str(source));self.backend.updateSetting('ui_language','en')
        self.assertIn('Video file.',self.backend.preview)
    def test_catalogs_cover_all_qml_labels_and_keep_placeholders(self):
        tr=Translations();self.assertEqual(set(tr.catalogs['en']),set(tr.catalogs['es']))
        fields=lambda text:{field for _,field,_,_ in Formatter().parse(text) if field}
        for catalog in tr.catalogs.values():
            for source,target in catalog.items():
                self.assertTrue(target.strip());self.assertEqual(fields(source),fields(target),source)
        for path in (ROOT/'studio_ui/qml').glob('*.qml'):
            for value in re.findall(r'Tr\.(?:tr|format)\(("(?:\\.|[^"\\])*")',path.read_text(encoding='utf-8')):
                self.assertIn(json.loads(value),tr.catalogs['en'],str(path))
    def test_pipeline_stages_and_errors_have_translations(self):
        tr=Translations()
        stages=['Preparando','Falhou','Transcrição pronta','Transcrevendo lote de episódios','Preparando tradutor','Extraindo legendas','Traduzindo para português','Incorporando legenda','Transcrevendo áudio']
        for language in ('en','es'):
            for stage in stages:self.assertIn(stage,tr.catalogs[language])
    def test_startup_errors_use_persisted_language_without_qt(self):
        from studio_bootstrap import startup_text
        for language,expected in [('en','Could not'),('es','No se pudo'),('pt-BR','Falha')]:
            (self.root/'config.json').write_text(json.dumps({'ui_language':language}),encoding='utf-8')
            self.assertTrue(startup_text(self.root,'qt_failed').startswith(expected))
        (self.root/'config.json').write_text('bad json',encoding='utf-8')
        self.assertTrue(startup_text(self.root,'qt_failed').startswith('Falha'))

    def test_palette_roles_and_reading_contrast(self):
        self.assertEqual(set(COLORS['dark']),set(COLORS['light']))
        def luminance(value):
            channels=[int(value[i:i+2],16)/255 for i in (1,3,5)]
            channels=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in channels]
            return sum(x*w for x,w in zip(channels,(.2126,.7152,.0722)))
        for colors in COLORS.values():
            for foreground,background in [('text','card'),('muted','card'),('accentText','accent'),('consoleText','consoleBg'),('successText','successBg')]:
                values=sorted((luminance(colors[foreground]),luminance(colors[background])))
                self.assertGreaterEqual((values[1]+.05)/(values[0]+.05),4.5,(foreground,background))
