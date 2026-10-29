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


Whisper Vulkan: [whisper.cpp](https://github.com/ggml-org/whisper.cpp), licença MIT em `licenses/whisper.cpp-LICENSE.txt`. O runtime Windows é a distribuição [nyancodex/whisper-server-vulkan-windows v0.1.0](https://github.com/nyancodex/whisper-server-vulkan-windows/releases/tag/v0.1.0), um build de terceiros; SHA256 fixado no código: `587d04a2805737436d134ab9e02c80437f41a7cb64018a7cd4d8f65a76a56af1`. O instalador de dependências verifica o arquivo antes de extrair apenas os componentes permitidos. Os modelos são baixados separadamente de `ggerganov/whisper.cpp` no Hugging Face, com revisão e SHA256 do fornecedor.
