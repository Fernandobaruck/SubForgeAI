"""Optional real-provider checks using synthetic projects and local models only."""
from pathlib import Path
import argparse,json,sys,tempfile,threading,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--ai',action='store_true');parser.add_argument('--online',action='store_true');args=parser.parse_args()
    result={}
    with tempfile.TemporaryDirectory(dir=ROOT/'reviews/updater',prefix='glossary-runtime-') as name:
        root=Path(name)
        if args.online:
            from studio_ui.online_glossary import Store
            store=Store(root);cancel=threading.Event();entries,stamp,offline=store.refresh(cancel)
            assert not offline and entries
            rows,offline=store.load(entries[0],cancel);assert rows and not offline
            result.update(public_catalog=True,collection=entries[0]['id'],terms=len(rows))
        if args.ai:
            from PySide6.QtCore import QCoreApplication
            from studio_ui.backend import Backend
            from studio_ui.runtime import Runtime
            from studio_ui import process_runtime
            app=QCoreApplication.instance() or QCoreApplication([]);runtime=Runtime(process_runtime,ROOT)
            backend=Backend(root,runtime,monitor_enabled=False);messages=[];backend.message.connect(messages.append)
            try:
                backend.review.createProject('Teste sintético de glossário');backend.review.online.suggest('Tower of Fang','en')
                deadline=time.monotonic()+240
                while backend.review.busy and time.monotonic()<deadline:app.processEvents();time.sleep(.02)
                app.processEvents();assert not backend.review.busy,'AI request did not stop'
                value=backend.review.online.aiSuggestion;assert value,messages
                assert not backend.review.terms
                result.update(local_ai=True,suggestion=value,terms_saved_automatically=False)
            finally:
                if backend.busy:backend.stop()
                backend.timer.stop();backend.review.fansub.timer.stop();runtime._stop_managed_ollama_server()
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
