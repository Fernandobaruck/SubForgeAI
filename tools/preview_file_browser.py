"""Isolated native Windows picker preview; never modifies the user's queue."""
from pathlib import Path
import sys,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QPushButton,QLabel
from studio_ui.backend import Backend
class Runtime:
    def _stop_managed_ollama_server(self,**kwargs):pass
    def kill_all_active_procs(self):pass
app=QApplication([])
with tempfile.TemporaryDirectory(dir=ROOT/'reviews') as folder:
    root=Path(folder);media=ROOT/'reviews/file-browser/fixtures';media.mkdir(parents=True,exist_ok=True)
    for name in ('Episodio 01 - Legenda para conferir nomes completos.srt','Episodio 02 - Legenda para seleção de vários arquivos.srt'):
        (media/name).write_text('1\n00:00:01,000 --> 00:00:03,000\nTeste.\n',encoding='utf-8')
    backend=Backend(root,Runtime(),monitor_enabled=False);backend.fileLocations.remember('input',media,folder=True)
    window=QWidget();window.setWindowTitle('SubForgeAI - Conferência do explorador');window.resize(640,230)
    layout=QVBoxLayout(window);layout.addWidget(QLabel('Teste isolado do seletor nativo; a fila real permanece intacta.'))
    button=QPushButton('Abrir explorador');button.clicked.connect(backend.chooseFiles);layout.addWidget(button)
    close=QPushButton('Fechar teste');close.clicked.connect(window.close);layout.addWidget(close)
    window.show();app.exec();backend.shutdown()
