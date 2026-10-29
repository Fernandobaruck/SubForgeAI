"""First-use preparation integrated with the existing cancellable job queue."""
from PySide6.QtCore import QObject, Property, Signal, Slot
from .setup_support import inspect, download, TRANSLATION_MODELS, WHISPER_GUIDE


class SetupController(QObject):
    changed = Signal()
    _progress = Signal(str, float)

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self._state = inspect(owner.root, owner.settings['ollama_model'])
        self._status = 'Escolha os modelos que deseja preparar.'
        self._value = 0
        self._active = False
        self._hardware = {}
        self._progress.connect(self._receive)
        owner.review.changed.connect(self._job_changed)
        owner.preferencesChanged.connect(self.changed.emit)

    @Property('QVariantMap', notify=changed)
    def state(self): return self._state

    @Property('QVariantMap', notify=changed)
    def hardware(self): return self._hardware

    @Property('QVariantList', notify=changed)
    def translationModels(self):
        return [dict(code=code, **info, ready=self._state['translations'].get(code, False))
                for code, info in TRANSLATION_MODELS.items()]

    @Property('QVariantList', notify=changed)
    def whisperModels(self):
        return [dict(code=code, **info, cuda_ready=self._state['whisper'][code],
                     vulkan_ready=self._state['whisper_vulkan'][code])
                for code, info in WHISPER_GUIDE.items()]

    @Slot(str)
    def selectWhisper(self, model):
        if model not in WHISPER_GUIDE or self.owner.busy: return
        self.owner.updateSetting('whisper_model',model)
        self.changed.emit()

    @Slot(str)
    def selectTranslation(self, model):
        if model not in TRANSLATION_MODELS or self.owner.busy: return
        self.owner.updateSetting('ollama_model', model)
        self.refresh()

    @Property(str, notify=changed)
    def status(self): return self.owner.translate(self._status)

    @Property(float, notify=changed)
    def progress(self): return self._value

    @Slot(str, float)
    def _receive(self, status, value):
        self._status = status; self._value = value; self.changed.emit()

    @Slot()
    def refresh(self):
        self._state = inspect(self.owner.root, self.owner.settings['ollama_model'])
        if not self._hardware:
            from profile_manager import detect_hw
            hw = detect_hw()
            self._hardware = dict(name=hw.gpu_name, vram=round(hw.vram_gb, 1), ram=round(hw.ram_gb, 1), nvidia=hw.has_nvidia)
            if not hw.has_nvidia:
                from .gpu_policy import vulkan_devices
                adapters=vulkan_devices()
                if adapters:
                    adapter=next((d for d in adapters if not d['shared']),adapters[0])
                    self._hardware.update(adapter)
                    self._hardware['vulkan']=True

        self.changed.emit()

    def _job_changed(self):
        if self._active and not self.owner.review.busy:
            self._active = False
            self._state = inspect(self.owner.root, self.owner.settings['ollama_model'])
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
            self._state = inspect(self.owner.root, self.owner.settings['ollama_model']); self._receive('Modelo disponível', 1)
        self._value = 0
        self._active = True
        if not self.owner.review._submit('Preparando modelo',
            lambda: download(self.owner.root, model, self._progress.emit, self.owner.review._cancel), done, True):
            self._active = False
