# Componentes de terceiros

O pacote portátil inclui componentes de terceiros para executar o aplicativo. Seus avisos e licenças são mantidos junto aos arquivos distribuídos, incluindo os diretórios `*.dist-info` do Python e as licenças dos pacotes.

- [Python](https://www.python.org/psf/license/): runtime portátil.
- [Qt for Python / PySide6](https://doc.qt.io/qtforpython-6/licenses.html): interface. A distribuição usa bibliotecas dinâmicas; fontes e informações sobre licenciamento estão disponíveis no projeto Qt. Código-fonte da versão Qt/PySide utilizada: [Qt 6.10.2](https://download.qt.io/archive/qt/6.10/6.10.2/) e [PySide 6.10.2](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.2-src/).
- [Ollama](https://github.com/ollama/ollama): serviço local de modelos e seus backends; cada componente de aceleração mantém seus termos.
- [PyTorch](https://github.com/pytorch/pytorch), [CTranslate2](https://github.com/OpenNMT/CTranslate2), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Demucs](https://github.com/facebookresearch/demucs): processamento de áudio e inferência, com avisos incluídos nas respectivas distribuições.
- [FFmpeg](https://ffmpeg.org/legal.html): manipulação de mídia. Consulte a versão/configuração incluída e o arquivo de origem de distribuição junto à ferramenta.
- Bibliotecas NVIDIA/CUDA e outros backends são redistribuídos com os componentes que os fornecem e sujeitos aos termos de seus fornecedores.

Modelos de tradução, transcrição e separação não integram o download inicial. A preparação obtém os modelos diretamente de seus fornecedores; seus termos continuam aplicáveis. Consulte o guia de primeiros passos.

O repositório do SubForgeAI ainda não define uma licença geral para o código próprio. Isso não altera as licenças dos componentes de terceiros.
