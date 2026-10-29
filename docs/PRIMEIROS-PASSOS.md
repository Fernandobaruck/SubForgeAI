# Começar a usar

## Instalar

1. Na página de [downloads](https://github.com/Fernandobaruck/SubForgeAI/releases/latest), baixe **SubForgeAI-Instalar-1.0.3.zip**.
2. Extraia o ZIP em uma pasta e dê dois cliques em **Instalar.cmd**. Não execute de dentro do ZIP e não é necessário executar como administrador.
3. Escolha onde guardar o aplicativo. Aguarde o download, a verificação e a extração. O Studio abre ao terminar.

O instalador baixa automaticamente as partes grandes da mesma release: você não precisa juntar arquivos nem instalar Python, Qt, Ollama ou FFmpeg à parte. A pasta de destino precisa ser nova; uma instalação existente não é substituída. Se a internet cair, abra o instalador novamente para aproveitar as partes já baixadas. Após instalar, os arquivos temporários grandes são removidos.

A instalação inicial exige internet e espaço no disco do perfil do Windows para preparar os downloads, além do espaço da pasta escolhida. O instalador verifica o espaço antes de começar. Os modelos não estão incluídos no aplicativo.

## Preparar os modelos

Na página **Início**, clique em **Preparar para começar**:

| O que deseja fazer | Modelo necessário | Download aproximado |
| --- | --- | --- |
| Traduzir uma legenda em inglês | TranslateGemma 12B | 8,1 GB |
| Transcrever áudio com maior velocidade | Whisper Large v3 Turbo | 1,6 GB |
| Transcrever com Large v3 | Whisper Large v3 | 3,1 GB |

Você pode instalar os dois Whisper e escolher qual usar nas Configurações. Só baixe os modelos que pretende usar. Os downloads são feitos dos fornecedores dos modelos e ficam dentro da pasta do projeto. Demucs, se ativado para separação de voz, pode precisar baixar seus pesos no primeiro processamento. Recursos opcionais, como OCR, também podem obter recursos próprios no primeiro uso.

O TranslateGemma está sujeito aos [termos do Gemma](https://ai.google.dev/gemma/terms). Confira os termos dos modelos antes do uso e da redistribuição.

## Fazer o primeiro teste

O caminho mais simples é começar com um arquivo de legenda em inglês:

1. Prepare o TranslateGemma.
2. Clique em **Adicionar arquivos** e selecione um `.srt`, `.ass` ou `.vtt`.
3. Em **Episódios**, escolha a operação de tradução e inicie a fila.
4. Confira a legenda em **Resultados** e use **Revisão** para corrigir os trechos sinalizados.

Para vídeos, o Studio pode aproveitar legendas disponíveis ou transcrever o áudio conforme a operação escolhida. Em **Configurações**, confira o idioma do áudio, Whisper e dispositivo. As traduções de legendas são geradas em português do Brasil; mudar o idioma da interface não muda o idioma de saída.

## Requisitos e limitações

- Windows x64. O pacote foi validado no ambiente Windows do projeto; outras configurações exigem teste.
- A referência de desenvolvimento é uma NVIDIA RTX 5070 com 12 GB de VRAM e 32 GB de RAM. Isso não estabelece um mínimo obrigatório para todas as operações.
- A IA exige GPU. Whisper utiliza CUDA em NVIDIA e pode utilizar Vulkan em AMD/Intel compatíveis. Prepare o modelo do motor correspondente. Falta de GPU/VRAM bloqueia inferência; não há execução alternativa em CPU. AMD e Intel ainda precisam de testes físicos.
- Depois de preparar os recursos necessários, o processamento dos arquivos é local. Consultar atualizações e baixar recursos exige internet.
- As saídas de IA precisam de revisão humana, especialmente nomes, contexto e falas difíceis.

## Problemas comuns

| Situação | O que verificar |
| --- | --- |
| Baixei o ZIP de atualização e não abre | Novos usuários precisam do ZIP **Instalar**, não de `SubForgeAI-update-*`. |
| Windows mostra editor desconhecido/SmartScreen | O executável não tem assinatura Authenticode. Confirme que o download veio deste repositório e confira os hashes fornecidos; não desative o antivírus. |
| Download interrompido | Execute o instalador novamente. Para modelos, repita o download no painel de preparação. |
| Modelo não encontrado | Abra **Preparar para começar**, confira o estado e baixe o modelo necessário. |
| Erro de CUDA ou falta de memória | Atualize o driver pelo fabricante, feche programas que ocupam VRAM ou escolha um TranslateGemma menor. Para AMD/Intel, prepare Whisper Vulkan e selecione Automático/Vulkan nas Configurações. |
| Ollama demorou ou tradução parou | Confira Diagnóstico e o log; tente retomar o mesmo trabalho para aproveitar o checkpoint. |
| Instalação incompleta | Extraia o instalador inteiro e instale em uma nova pasta. Não mova apenas o `.exe`. |

Para pedir ajuda, abra uma [issue](https://github.com/Fernandobaruck/SubForgeAI/issues) com versão, Windows, GPU/RAM, operação e mensagem do log. Remova caminhos pessoais e não envie vídeos ou legendas protegidas sem autorização.
