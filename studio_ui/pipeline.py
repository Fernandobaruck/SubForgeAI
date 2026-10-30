"""Sequential episode jobs, independent of Qt and Tk event loops.

The existing process/environment/Ollama helpers are reused without constructing
the classic GUI. Worker scripts retain their output reservations and checkpoints.
"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from source_selection import validate_options,context_copy,subtitle_sample

MEDIA = {'.mkv', '.mp4', '.avi', '.mov', '.webm', '.m4v', '.mpg', '.mpeg',
         '.ts', '.m2ts', '.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg'}
SUBTITLES = {'.srt', '.ass', '.vtt', '.ssa', '.sub', '.sup', '.idx', '.mks'}
TRANSLATABLE = {'.srt', '.ass', '.vtt'}
DEFAULTS = dict(whisper_model='large-v3-turbo', whisper_language='auto',
                whisper_device='auto', whisper_backend='faster', whisper_audio_stream='auto',
                whisper_demucs_mode='auto', ollama_model='translategemma:12b',
                resource_cpu_threads=0,resource_gpu_layers=-1,resource_background=False,completion_action='none',update_check_startup=False,
                review_mode='auto', subtitle_style='original', embed_enabled=False, auto_extract_subs=False,
                extract_to='copy', extract_stream='all',
                whisper_out_dir='outputs/whisper', ollama_out_dir='outputs/pt-br',
                subs_out_dir='outputs/subs_extradas', embed_output_dir='outputs/com_legenda')


def path_key(path):
    return os.path.normcase(str(Path(path).resolve()))


def resolve_dir(root, value):
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (Path(root) / path).resolve()


def validate_settings(values):
    result = {**DEFAULTS, **values}
    from whisper_audio import WHISPER_REPOSITORIES
    choices = {'whisper_model': tuple(WHISPER_REPOSITORIES),
               'whisper_device': ('cuda', 'vulkan', 'auto'),
               'whisper_demucs_mode': ('auto', 'enabled', 'disabled'),
               'review_mode': ('auto', 'disabled'),
               'subtitle_style': ('original','reference'),
               'extract_to': ('copy', 'srt', 'ass', 'vtt')}
    for key, allowed in choices.items():
        if result[key] not in allowed:
            result[key] = DEFAULTS[key]
    from maintenance_tools import resources
    result.update(resources(result))
    if result.get('completion_action') not in ('none','notify','open','sleep'):result['completion_action']='none'
    from .setup_support import TRANSLATION_MODELS
    if result['ollama_model'] not in tuple(TRANSLATION_MODELS):
        result['ollama_model'] = DEFAULTS['ollama_model']
    result['whisper_backend'] = 'auto'
    result['resource_gpu_layers'] = -1
    for key in ('embed_enabled', 'auto_extract_subs','update_check_startup'):
        result[key] = result[key] is True or str(result[key]).lower() in ('1', 'true')
    if not re.fullmatch(r'all|\d+(?:,\d+)*', str(result['extract_stream'])):
        result['extract_stream'] = 'all'
    if not re.fullmatch(r'auto|\d+',str(result['whisper_audio_stream'])):
        result['whisper_audio_stream'] = 'auto'
    for key in ('whisper_out_dir', 'ollama_out_dir', 'subs_out_dir', 'embed_output_dir'):
        if not str(result[key]).strip():
            result[key] = DEFAULTS[key]
    return result


class Pipeline:
    def __init__(self, runtime, root):
        self.runtime, self.root = runtime, Path(root)
        self.events = queue.Queue()
        self.logs = queue.Queue(maxsize=4000)
        self.cancelled = threading.Event()
        self.thread = None
        self.stopping = None

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def log(self, text):
        try:
            self.logs.put_nowait(str(text))
        except queue.Full:
            try:
                self.logs.get_nowait()
            except queue.Empty:
                pass
            try:
                self.logs.put_nowait(str(text))
            except queue.Full:
                pass

    def start(self, items, settings, operation):
        if self.busy or self.stopping and self.stopping.is_alive():
            return False
        self.cancelled.clear()
        snapshot = [dict(item) for item in items]
        settings = validate_settings(settings)
        if hasattr(self.runtime,'configure_resources'):self.runtime.configure_resources(settings)
        self.thread = threading.Thread(target=self._work, args=(snapshot, settings, operation),
                                       name='studio-pipeline', daemon=False)
        self.thread.start()
        return True

    def cancel(self):
        self.cancelled.set()
        if self.stopping and self.stopping.is_alive():
            return
        self.stopping = threading.Thread(target=self.runtime.kill_all_active_procs,
                                         name='studio-cancel', daemon=False)
        self.stopping.start()

    def _work(self, items, settings, operation):
        self._prepared = {}
        try:
            media = [i for i in items if Path(i['path']).suffix.lower() in MEDIA
                     and (i.get('operation', 'auto') if operation == 'resume' else operation) in ('auto', 'transcribe')]
            self._prepared={}
            groups={}
            for entry in media:
                options=entry.get('options') or {}
                if not isinstance(options,dict) or options.get('source_mode','auto') not in ('auto','whisper') or options.get('sample_seconds'):continue
                groups.setdefault((str(options.get('audio_stream',settings['whisper_audio_stream'])),options.get('series_project',''),options.get('audio_language',settings['whisper_language'])),[]).append(entry)
            preparation_started=time.monotonic()
            for (audio,project,language),group in groups.items():
                if len(group)>1 and not settings['auto_extract_subs']:
                    self._prepare_transcriptions(group,{**settings,'whisper_audio_stream':audio,'series_project':project,'whisper_language':language or settings['whisper_language']})
            preparation_seconds=round(time.monotonic()-preparation_started,3)
            for item in items:
                if self.cancelled.is_set():
                    break
                self.events.put(('item', item['id'], {'state': 'Executando', 'progress': 0,
                                                      'stage': 'Preparando', 'error': ''}))
                started=time.monotonic();results=[];failure='';state='Concluído'
                try:
                    effective_operation = item.get('operation', 'auto') if operation == 'resume' else operation
                    results = self._episode(item, settings, effective_operation)
                    if settings.get('subtitle_style')=='reference' and effective_operation in ('transcribe','extract'):
                        results=self._style_results(results)
                    from .output_layout import compact_result
                    for output in results:
                        if Path(output).is_file():compact_result(output)
                    if self.cancelled.is_set():
                        break
                    self.events.put(('item', item['id'], {'state': 'Concluído', 'progress': 1,
                                                          'stage': 'Concluído', 'results': results}))
                except Exception as exc:
                    failure=str(exc);state='Erro'
                    if not self.cancelled.is_set():
                        self.log(f'[ERRO] {item["name"]}: {exc}')
                        self.events.put(('item', item['id'], {'state': 'Erro', 'stage': 'Falhou',
                                                              'error': str(exc)}))
                finally:
                    from pipeline_io import atomic_write_text
                    options=item.get('options') or {}
                    if not isinstance(options,dict):options={}
                    mode=options.get('source_mode','auto')
                    if mode=='auto':mode='whisper' if Path(item['path']).suffix.lower() in MEDIA else 'external'
                    from series_registry import SeriesRegistry
                    project=options.get('series_project') or settings.get('series_project','')
                    if not project:
                        try:project=SeriesRegistry(self.root).resolve(item['path'])
                        except (OSError,ValueError):project=''
                    if (item.get('operation','auto') if operation=='resume' else operation)=='extract':mode='extract'
                    from fansub_tools import performance_key
                    op=item.get('operation','auto') if operation=='resume' else operation
                    try:output_bytes=sum(Path(p).stat().st_size for p in results if Path(p).is_file())
                    except OSError:output_bytes=None
                    report=dict(performance_key=performance_key(op,options,settings),effective_seconds=round(time.monotonic()-started+preparation_seconds/max(1,len(self._prepared)),3),output_bytes=output_bytes,audio_stream=options.get('audio_stream',settings['whisper_audio_stream']),subtitle_stream=options.get('subtitle_stream'),source_subtitle=options.get('source_subtitle'),sample_seconds=options.get('sample_seconds',0),input=item['path'],project=project,source_mode=mode,
                                operation=item.get('operation','auto') if operation=='resume' else operation,outputs=results,
                                elapsed_seconds=round(time.monotonic()-started,3),preparation_batch_seconds=preparation_seconds,
                                state='Interrompido' if self.cancelled.is_set() else state,error=failure,
                                model=settings['ollama_model'],whisper_model=settings['whisper_model'],finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
                    try:atomic_write_text(self.root/'outputs/studio/episode_reports'/(uuid.uuid4().hex+'.json'),json.dumps(report,ensure_ascii=False,indent=2))
                    except OSError as exc:self.log('[WARN] Não foi possível salvar o resumo: '+str(exc))
        finally:
            if self.cancelled.is_set():
                # Kill only children and the Ollama server owned by this process.
                self.runtime.kill_all_active_procs()
                self.runtime._stop_managed_ollama_server(log_fn=self.log)
                self.log('[WARN] Interrompido. Resultados e checkpoints foram preservados.')
            self.events.put(('finished', self.cancelled.is_set(), None))

    def _prepare_transcriptions(self, items, settings):
        """Keep Whisper loaded for the season instead of reloading it per file."""
        rt = self.runtime
        by_source = {path_key(i['path']): i for i in items}
        if not hasattr(self,'_prepared'):self._prepared={}
        self._prepared.update({key: None for key in by_source})
        stems = settings['whisper_demucs_mode']
        if stems == 'auto': stems = 'disabled'
        py = rt.runtime_python()
        override = settings.get('whisper_python')
        if override: py = str(resolve_dir(self.root, override))
        cmd = [py, str(rt.WHISPER_SCRIPT), *[i['path'] for i in items],
               '--outdir', str(resolve_dir(self.root, settings['whisper_out_dir'])),
               '--model', settings['whisper_model'], '--backend', 'auto',
               '--device', settings['whisper_device'], '--language', settings['whisper_language'],
               '--audio-stream', settings['whisper_audio_stream'],
               *(['--series-project',settings['series_project']] if settings.get('series_project') else []),
               *(['--stems'] if settings['whisper_demucs_mode']=='enabled' else ['--no-stems'] if settings['whisper_demucs_mode']=='disabled' else ['--no-stems'] if settings['whisper_model']=='large-v3-turbo' else ['--auto-stems'])]
        def line(text):
            self.log(text)
            if not text.startswith('[RESULT] '): return
            try:
                result = json.loads(text[9:])
                key = path_key(result['input'])
                if result.get('kind') == 'transcription' and key in by_source and Path(result['output']).is_file():
                    self._prepared[key] = result['output']
                    self.events.put(('item', by_source[key]['id'], dict(state='Aguardando', stage='Transcrição pronta', progress=0)))
            except (ValueError, KeyError, TypeError): pass
        try:
            rt._release_translation_memory(log_fn=self.log)
            if self.cancelled.is_set(): return
            for item in items:
                self.events.put(('item', item['id'], dict(state='Executando', stage='Transcrevendo lote de episódios', progress=0)))
            self.log(f'=== TRANSCRIÇÃO EM LOTE · {len(items)} episódios ===')
            rc = rt.run_capture(cmd, line, cwd=self.root, cancel_event=self.cancelled)
            if rc and not self.cancelled.is_set():
                self.log('[WARN] O lote de transcrição teve falhas. As saídas confirmadas serão aproveitadas.')
        except Exception as exc:
            self.log(f'[ERRO] Transcrição em lote: {exc}')

    def _episode(self, item, settings, operation):
        rt = self.runtime
        source = Path(item['path'])
        if not source.is_file():
            raise ValueError('O arquivo de entrada não está disponível.')
        original_source=source
        options=validate_options(item.get('options'))
        mode=options['source_mode']
        settings=dict(settings)
        if 'audio_stream' in (item.get('options') or {}):settings['whisper_audio_stream']=options['audio_stream']
        from series_registry import SeriesRegistry
        settings['series_project']=options['series_project'] or SeriesRegistry(self.root).resolve(original_source)
        if options['audio_language']:settings['whisper_language']=options['audio_language']
        if options['sample_seconds']:
            sample=self.root/'outputs/studio/samples'/item['id']
            for key,child in (('whisper_out_dir','whisper'),('ollama_out_dir','translated'),('subs_out_dir','subtitles')):settings[key]=str(sample/child)
            settings['embed_enabled']=False
        subtitle = source.suffix.lower() in SUBTITLES
        explicit=mode in ('embedded','external','ocr')
        if operation=='transcribe' and explicit:raise ValueError('Escolha Whisper para transcrever áudio.')
        if mode=='whisper' and subtitle:raise ValueError('Para transcrever, selecione vídeo ou áudio.')
        if operation == 'translate' and source.suffix.lower() not in TRANSLATABLE and not explicit:
            raise ValueError('Para traduzir, selecione SRT, ASS ou VTT; extraia a legenda do vídeo primeiro.')
        if operation == 'transcribe' and subtitle:
            raise ValueError('Para transcrever, selecione vídeo ou áudio.')
        if operation == 'auto' and subtitle and source.suffix.lower() not in TRANSLATABLE and not explicit:
            raise ValueError('Converta esta legenda para SRT, ASS ou VTT antes de traduzir.')
        py = rt.runtime_python()
        results = []
        confirmed = {}
        stage = ''
        last_progress = -1

        def line(text):
            nonlocal last_progress
            self.log(text)
            if text.startswith('[RESULT] '):
                try:
                    result = json.loads(text[9:])
                    confirmed[(result['kind'], path_key(result['input']))] = result['output']
                    output = str(Path(result['output']).resolve())
                    if Path(output).is_file() and output not in results:
                        results.append(output)
                except (ValueError, KeyError, TypeError):
                    self.log('[WARN] Marcador de resultado inválido; aguardando confirmação válida.')
            elif text.startswith('[OUTFILE]'):
                output = text[len('[OUTFILE]'):].strip()
                if Path(output).is_file() and output not in results:
                    results.append(output)
            match = re.search(r'(\d{1,3}(?:\.\d+)?)%', text)
            if match:
                progress = min(1, float(match[1]) / 100)
                if progress != last_progress:
                    last_progress = progress
                    self.events.put(('item', item['id'], {'progress': progress}))

        def run(cmd, label):
            nonlocal stage, last_progress
            if self.cancelled.is_set():
                raise RuntimeError('Cancelado')
            stage, last_progress = label, -1
            self.events.put(('item', item['id'], {'stage': label, 'progress': 0}))
            self.log(f'\n=== {source.name} · {label} ===')
            rc = rt.run_capture(cmd, line, cwd=self.root, cancel_event=self.cancelled)
            if self.cancelled.is_set():
                raise RuntimeError('Cancelado')
            if rc:
                raise RuntimeError(f'{label} falhou (código {rc}). Veja o diagnóstico.')

        def out(key):
            return str(resolve_dir(self.root, settings[key]))

        if options['sample_seconds'] and not subtitle and mode in ('auto','whisper'):
            clip=Path(settings['whisper_out_dir']).parent/(source.stem[:100]+'.sample'+source.suffix.lower());clip.parent.mkdir(parents=True,exist_ok=True)
            run([str(self.root/'tools/ffmpeg/ffmpeg.exe'),'-y','-v','error','-ss',str(options['sample_start']),'-i',str(source),'-t','60','-map','0','-c','copy','-avoid_negative_ts','make_zero',str(clip)],'Preparando teste curto')
            if not clip.is_file():raise RuntimeError('O recorte de teste não foi criado.')
            from pipeline_io import atomic_write_text
            atomic_write_text(Path(str(clip)+'.sample.json'),json.dumps({'source':str(source),'start':options['sample_start'],'duration':60}))
            from subtitle_quality import SeriesTerms
            from speech_context import write_context,load_speech_terms
            context=SeriesTerms(original_source,[],sample/'_series_context',settings['whisper_language'])
            write_context(clip,original_source,context.explicit,load_speech_terms(original_source,self.root),source_kind='media_sample',series_project=settings.get('series_project') or None)
            source=clip

        prepared_source=None
        if mode=='external':
            prepared_source=Path(options['source_subtitle'])
            if not prepared_source.is_file() or prepared_source.suffix.lower() not in TRANSLATABLE|{'.sup'}:raise ValueError('Selecione um arquivo de legenda válido.')
        elif mode in ('embedded','ocr'):
            if source.suffix.lower()=='.sup' and mode=='ocr':prepared_source=source
            else:
                if not options['subtitle_stream']:raise ValueError('Selecione uma faixa de legenda.')
                from source_selection import probe
                streams=probe(source,self.root)
                stream=next((entry for entry in streams if entry['kind']=='subtitle' and str(entry['index'])==options['subtitle_stream']),None)
                if stream is None:raise ValueError('A faixa de legenda selecionada não existe.')
                bitmap=stream['codec']=='hdmv_pgs_subtitle'
                if mode=='ocr' and not bitmap:raise ValueError('OCR de vídeo exige uma faixa PGS.')
                if mode=='embedded' and stream['codec'] in ('hdmv_pgs_subtitle','dvd_subtitle','dvb_subtitle'):raise ValueError('Esta faixa é uma imagem. Selecione OCR para PGS.')
                run([py,str(rt.EXTRACT_SCRIPT),str(source),'--outdir',out('subs_out_dir'),'--to','copy','--stream',options['subtitle_stream']],'Extraindo legendas')
                prepared_source=Path(confirmed.get(('extraction',path_key(source)),'__missing__'))
                if not prepared_source.is_file():raise RuntimeError('A extração não confirmou a legenda.')
        if prepared_source is not None:
            if prepared_source.suffix.lower()=='.sup':
                run([py,str(rt.EXTRACT_SCRIPT),str(prepared_source),'--outdir',out('subs_out_dir'),'--to','srt','--ocr'],'Lendo legenda por OCR')
                converted=confirmed.get(('extraction',path_key(prepared_source)))
                if not converted or not Path(converted).is_file():raise RuntimeError('O OCR não confirmou a legenda.')
                prepared_source=Path(converted)
            subtitle=True

        if operation == 'extract' or operation == 'auto' and settings['auto_extract_subs'] and not subtitle:
            run([py, str(rt.EXTRACT_SCRIPT), str(source), '--outdir', out('subs_out_dir'),
                 '--to', settings['extract_to'], '--stream', settings['extract_stream'],
                 *(['--ocr'] if source.suffix.lower() == '.sup' and settings['extract_to'] == 'srt' else [])], 'Extraindo legendas')
            if operation == 'extract':
                return results

        translation_source = prepared_source or source
        if operation in ('auto', 'transcribe') and not subtitle:
            prepared = getattr(self, '_prepared', {})
            if path_key(source) in prepared:
                output = prepared[path_key(source)]
                if not output or not Path(output).is_file():
                    raise RuntimeError('O Whisper não confirmou a transcrição deste episódio no lote.')
                translation_source = Path(output)
                results.append(str(translation_source))
            else:
                translation_source = self._transcribe_one(source, settings, py, run, confirmed)
            if operation == 'transcribe':
                return results

        if operation in ('auto','translate'):
            project=options['series_project']
            if not project:
                from series_registry import SeriesRegistry
                project=SeriesRegistry(self.root).resolve(original_source)
            if prepared_source is not None or project:
                translation_source=context_copy(translation_source,self.root/'outputs/studio/context_inputs',original_source,self.root,project)
            if options['sample_seconds'] and translation_source.suffix.lower() in TRANSLATABLE and (subtitle or mode in ('embedded','external','ocr')):
                translation_source=subtitle_sample(translation_source,Path(settings['ollama_out_dir']).parent/'source',options['sample_start'],60)

        if operation in ('auto', 'translate'):
            self.events.put(('item', item['id'], {'stage': 'Preparando tradutor', 'progress': 0}))
            if not rt._ensure_ollama_ready(log_fn=self.log, required_model=settings['ollama_model'],
                                            cancel_event=self.cancelled):
                raise RuntimeError('Não foi possível preparar o TranslateGemma no Ollama.')
            run([py, str(rt.OLLAMA_SCRIPT), str(translation_source), '--outdir', out('ollama_out_dir'),
                 '--model', settings['ollama_model'], '--review', settings['review_mode'], '--show-passes'],
                'Traduzindo para português')
            translated = confirmed.get(('translation', path_key(translation_source)))
            if not translated or not Path(translated).is_file():
                raise RuntimeError('O tradutor não confirmou a saída desta execução.')
            if settings.get('subtitle_style')=='reference':
                styled=self._style_results([translated])
                translated=styled[-1]
            from .output_layout import compact_result
            compact_result(translated)
            # Intermediate extraction/transcription/translation artifacts remain
            # recoverable internally; only the deliverable belongs in Results.
            results=[translated]
            if settings['embed_enabled'] and source.suffix.lower() in MEDIA and source.suffix.lower() not in {'.mp3','.wav','.flac','.m4a','.aac','.ogg'}:
                def embed_runner(cmd, **_kwargs):
                    run(cmd, 'Incorporando legenda')
                    return subprocess.CompletedProcess(cmd, 0, '', '')
                if rt.mux_softsub is None:
                    raise RuntimeError('Módulo de incorporação indisponível.')
                result = rt.mux_softsub(str(source), translated, out('embed_output_dir'),
                                        force_mkv=True, process_runner=embed_runner)
                results.append(result)
        return results

    def _style_results(self, paths):
        from fansub_tools import reference_copy
        from .output_layout import compact_result
        result=[]
        for path in paths:
            if Path(path).suffix.lower() not in TRANSLATABLE:
                result.append(path);continue
            if self.cancelled.is_set():raise RuntimeError('Cancelado')
            try:
                output=reference_copy(path,self.cancelled)
                output=compact_result(output,path if Path(output).resolve()!=Path(path).resolve() else None)
                if output not in result:result.append(output)
                self.log('[OK] Legenda com padrão streaming: '+output)
            except ValueError as exc:
                self.log('[WARN] '+str(exc))
                if path not in result:result.append(path)
        return result

    def _transcribe_one(self, source, settings, py, run, confirmed):
        rt = self.runtime
        rt._release_translation_memory(log_fn=self.log)
        if self.cancelled.is_set():
            raise RuntimeError('Cancelado')
        stems = settings['whisper_demucs_mode']
        if stems == 'auto':
            stems = 'disabled'
        override = settings.get('whisper_python')
        whisper_py = str(resolve_dir(self.root, override)) if override else py
        run([whisper_py, str(rt.WHISPER_SCRIPT), str(source), '--outdir', str(resolve_dir(self.root, settings['whisper_out_dir'])),
             '--model', settings['whisper_model'], '--backend', 'auto',
             '--device', settings['whisper_device'], '--language', settings['whisper_language'],
             '--audio-stream', settings['whisper_audio_stream'],
             *(['--series-project',settings['series_project']] if settings.get('series_project') else []),
             *(['--stems'] if settings['whisper_demucs_mode']=='enabled' else ['--no-stems'] if settings['whisper_demucs_mode']=='disabled' else ['--no-stems'] if settings['whisper_model']=='large-v3-turbo' else ['--auto-stems'])], 'Transcrevendo áudio')
        translated_input = confirmed.get(('transcription', path_key(source)))
        if not translated_input or not Path(translated_input).is_file():
            raise RuntimeError('O Whisper não confirmou a saída desta execução.')
        return Path(translated_input)
