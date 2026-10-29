# SubForgeAI Studio

Aplicativo para Windows voltado à criação e revisão de legendas de anime, com processamento local.

## Recursos

- Extração de legendas, transcrição com Whisper large-v3 e large-v3-turbo e tradução com TranslateGemma pelo Ollama.
- Fila de episódios, retomada de tradução, glossários e memória por série.
- Revisão lado a lado, editor de legendas, sincronização, controle de legibilidade e exportação ASS.
- Interface Qt Quick/QML em português, inglês e espanhol, com temas escuro e claro.
- Atualizações assinadas, backup e recuperação da versão anterior.

## Código e aplicativo portátil

Este repositório contém o código-fonte, a interface, os testes e as ferramentas de desenvolvimento. O download do código do GitHub não é uma instalação portátil completa: runtime Python/Qt, Ollama, FFmpeg e modelos precisam ser preparados separadamente.

Em uma instalação portátil existente, abra **SubForgeAI Studio.exe** e mantenha `_studio_boot/`, `runtime/` e os demais componentes operacionais junto ao aplicativo. O código também pode ser iniciado pelo Python do runtime:

```powershell
.\runtime\python\python.exe -B -X utf8 studio_launcher.py
```

O ambiente atual utiliza Windows x64, Python 3.11 e Qt 6. As dependências da interface estão em [studio_ui/requirements.txt](studio_ui/requirements.txt); OCR possui dependências adicionais em [tools/requirements-ocr.txt](tools/requirements-ocr.txt). A transcrição requer faster-whisper/CTranslate2; recursos de separação de áudio requerem PyTorch/Demucs e versões de aceleração compatíveis com o hardware. Esses arquivos de requisitos não representam sozinhos todo o runtime portátil.

## Desenvolvimento e testes

Os módulos Python da raiz implementam o processamento; `studio_ui/` contém a interface; `tests/` reúne os testes; `tools/` reúne ferramentas de compilação e validação. Com o runtime preparado, execute:

```powershell
.\runtime\python\python.exe -B -X utf8 -m unittest discover -s tests -p 'test_*.py'
.\runtime\python\python.exe -B -X utf8 tests/check_package.py
```

A verificação do pacote exige o executável e os componentes portáteis. Ferramentas de integração podem exigir modelos instalados ou arquivos de mídia locais. `tools/build_studio.py` compila o inicializador com PyInstaller; feche o Studio antes de recompilar.

## Atualizações

O canal oficial é [Releases](https://github.com/Fernandobaruck/SubForgeAI/releases). Pacotes `SubForgeAI-update-*.zip` são atualizações de uma instalação existente e não incluem modelos ou runtime. Consulte [o guia de publicação](docs/RELEASES.md) e [o guia do Studio](docs/STUDIO.md).

Configurações, glossários pessoais, histórico, saídas, caches, modelos e chaves privadas ficam fora do controle de versão. A chave pública no código permite verificar os pacotes oficiais; ela não permite assinar novas versões.

## Licenciamento

Nenhuma licença de uso ou redistribuição do código foi definida pelo titular até o momento. Dependências e modelos mantêm suas próprias licenças; consulte os respectivos fornecedores antes de redistribuí-los.
