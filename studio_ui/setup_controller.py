"""First-use preparation integrated with the existing cancellable job queue."""
from PySide6.QtCore import QObject, Property, Signal, Slot
from .setup_support import inspect, download


class SetupController(QObject):
    changed = Signal()
    _progress = Signal(str, float)

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self._state = inspect(owner.root)
        self._status = 'Escolha os modelos que deseja preparar.'
        self._value = 0
        self._active = False
        self._progress.connect(self._receive)
        owner.review.changed.connect(self._job_changed)
        owner.preferencesChanged.connect(self.changed.emit)

    @Property('QVariantMap', notify=changed)
    def state(self): return self._state

    @Property(str, notify=changed)
    def status(self): return self.owner.translate(self._status)

    @Property(float, notify=changed)
    def progress(self): return self._value

    @Slot(str, float)
    def _receive(self, status, value):
        self._status = status; self._value = value; self.changed.emit()

    @Slot()
    def refresh(self):
        self._state = inspect(self.owner.root); self.changed.emit()

    def _job_changed(self):
        if self._active and not self.owner.review.busy:
            self._active = False
            self._state = inspect(self.owner.root)
            self._status = 'Preparação encerrada. Confira o estado dos modelos e as mensagens do registro.'
            self.changed.emit()

    @Slot(str)
    def prepare(self, model):
        if self.owner.busy: return
        self.refresh()
        if self._state['missing']:
            self.owner._notify('A instalação está incompleta. Instale o pacote inicial novamente em uma nova pasta.')
            return
        def done(state):
            self._active = False
            self._state = state; self._receive('Modelo disponível', 1)
        self._value = 0
        self._active = True
        if not self.owner.review._submit('Preparando modelo',
            lambda: download(self.owner.root, model, self._progress.emit, self.owner.review._cancel), done, True):
            self._active = False
