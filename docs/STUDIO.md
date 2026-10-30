# SubForgeAI Studio

Execute `SubForgeAI Studio.exe` na raiz. A interface usa Qt Quick/QML. A interface clássica e suas bibliotecas foram removidas da instalação ativa.

## Primeiro uso

Novos usuários: consulte [o guia de instalação e primeiros passos](PRIMEIROS-PASSOS.md). Na tela Início, o botão **Preparar para começar** verifica os componentes e permite baixar TranslateGemma, Whisper Turbo ou Large v3, com progresso e interrupção. Baixe apenas os modelos necessários.

## Telas

- **Início:** resumo da fila, acesso aos arquivos e identificação do hardware.
- **Episódios:** adicionar arquivos ou arrastá-los, escolher a operação e acompanhar o estado individual.
- **Tradução:** TranslateGemma 12B, validação e pasta das traduções.
- **Resultados:** localizar legendas e vídeos, visualizar texto e abrir o arquivo ou a pasta. A prévia não edita a legenda.
- **Configurações:** escolher Large v3/Turbo, idioma, dispositivo, Demucs, extração, incorporação e pastas.
- **Diagnóstico:** CPU, RAM, GPU, VRAM e acesso aos registros.
- **Revisão:** validação, edição lado a lado, retradução de blocos, prévia do vídeo e histórico.
- **Animes:** glossário e correções aprovadas por projeto, compartilhados entre temporadas vinculadas.
- **Atualizações:** consulta ao canal oficial, download assinado, instalação com reinício e restauração da versão anterior do aplicativo.

O registro detalhado pode ser aberto pelo rodapé em qualquer tela. Os logs de sessão ficam em `logs/studio/`.

## Aparência e idioma

Em **Configurações → Aparência e idioma**, escolha **Português (Brasil)**, **English** ou **Español**. Menus, botões, estados da fila, mensagens, prévias informativas e diálogos de arquivos acompanham a escolha imediatamente. As preferências ficam salvas em `config.json` como `ui_language` e `ui_theme` e são recuperadas na próxima abertura.

O tema **Escuro (padrão)** conserva a paleta violeta original. O tema **Claro** usa fundos claros e cores de texto, bordas e controles ajustadas para contraste. O botão de sol/lua no cabeçalho permite alternar rapidamente. Idioma e tema podem ser alterados enquanto há processamento; as configurações desse processamento continuam protegidas durante a execução.

O idioma da interface controla a apresentação do Studio. A transcrição segue **Idioma do áudio**, e o TranslateGemma continua gerando português do Brasil. Textos das legendas, nomes de arquivo, caminhos e registros técnicos são preservados no idioma original.

A validação percorre as nove páginas nos três idiomas e nos dois temas, verifica os seletores, os diálogos de arquivos e a preservação da fila. A ferramenta `tools/check_ui_preferences.py` gera capturas e um relatório em `reviews/ui_preferences/`.

## Atualizações pelo launcher

O canal oficial é `https://github.com/Fernandobaruck/SubForgeAI`. A versão inicial desta integração é `1.0.0`. Na aba **Atualizações**, use **Verificar atualizações**. Se o repositório ainda não tiver releases, isso aparece como um estado normal; criar o repositório não publica uma versão automaticamente.

**Verificar ao abrir o launcher** é opcional e começa desativado. A consulta usa a API pública do GitHub, sem token; envia o pedido HTTP e um identificador com a versão do aplicativo. Não envia configurações, legendas ou glossários. Falhas de rede e limites da API não impedem usar o restante do Studio.

Quando houver uma versão estável maior que a instalada, **Baixar atualização** baixa o pacote, verifica a assinatura RSA/SHA-256 do manifesto, o hash do ZIP e de cada arquivo e prepara a instalação em `.updates/jobs/`. Downloads não são instalados automaticamente. Um pacote preparado pode ser encontrado novamente após reabrir o aplicativo; seus arquivos são revalidados antes de aplicar.

**Instalar e reiniciar** pede confirmação, salva uma revisão modificada, fecha o Studio e inicia um instalador independente. Feche outras instâncias. O instalador espera os processos desta instância saírem, obtém acesso exclusivo à instalação, guarda os arquivos antigos e substitui somente arquivos permitidos do aplicativo. O runtime Python/Qt em `runtime/`, modelos, configurações, glossários, resultados, histórico e backups pessoais não fazem parte do pacote. O inicializador `.exe` e seus recursos `_studio_boot/` podem acompanhar uma atualização do aplicativo.

A nova versão passa por um teste de inicialização com interface fora da tela, conferindo a versão carregada e erros de QML. Se a validação falhar, os arquivos anteriores são recuperados. Uma instalação interrompida durante a substituição também é recuperada na próxima abertura. Caches Python dos módulos substituídos podem ser removidos para impedir leitura de código antigo; dados do usuário permanecem preservados.

**Restaurar versão anterior** usa o último backup de atualização concluída, fecha e reabre o aplicativo. Arquivos modificados manualmente depois da atualização fazem a restauração parar para evitar sobrescrever essas alterações. Os backups e registros ficam em `.updates/jobs/<id>/`; o resumo da última operação fica em `.updates/last_result.json`. A limpeza assistida não remove essas cópias.

Este canal distribui atualizações de uma instalação portátil existente. Mudanças de dependências/runtime exigem um pacote separado compatível; modelos não são baixados novamente pelo atualizador. Para preparar/publicar versões, consulte `docs/RELEASES.md`.

## Fluxo de revisão e preparação de uma temporada

1. Em **Animes**, crie um projeto e vincule as pastas das temporadas. Cadastre termos como confirmados para usá-los na tradução; sugestões ainda não confirmadas não são impostas. Os dados ficam em `series_projects/`, separados por anime.
2. Em **Episódios → Fonte**, escolha a origem por arquivo: automática, Whisper, legenda embutida, legenda externa ou OCR. A lista mostra índices, idiomas e títulos das faixas. OCR aceita PGS/SUP; outros formatos bitmap precisam de conversão anterior. Escolher uma legenda explicitamente evita transcrever o áudio.
3. Use **Testar 60 s** antes da temporada. O início é informado em segundos; o teste cria um item separado e saídas em `outputs/studio/samples/`, sem executar os outros pendentes. Recortes de áudio/vídeo têm tempos relativos ao recorte; amostras de legendas conservam os tempos originais.
4. Em **Resultados → Revisar**, abra uma legenda ou um relatório `.review_required.json`. A tela sinaliza blocos vazios, tempos inválidos, sobreposições, ordem temporal, velocidade de leitura e alertas disponíveis de tradução/transcrição/OCR. Alertas exigem conferência: não comprovam erro semântico.
5. Confira origem e texto lado a lado. A associação à origem exige tempos correspondentes; use a opção de associar legenda quando necessário. É possível editar, aprovar e **Memorizar correção** no anime selecionado. Só correções aprovadas com origem verificada podem entrar nessa memória.
6. Selecione blocos e use **Retraduzir seleção**. Sem seleção, a ação usa o bloco atual. A proposta aparece para conferência e só substitui o rascunho ao clicar em **Aplicar sugestão**. Depois aprove e salve.

**Ver trecho** gera um pequeno vídeo H.264/AAC e abre o reprodutor padrão. A faixa de áudio auditada é preservada; sem essa informação, a seleção automática prioriza japonês. Associe o vídeo se a legenda não tiver uma origem de mídia conhecida.

**Salvar** ou **Ctrl+S** cria uma cópia em `outputs/studio/reviewed/`. O original permanece intacto. Rascunhos e versões ficam em `outputs/studio/history/`, incluindo uma referência da legenda de origem. No histórico, **Restaurar versão** cria uma nova versão recuperável. Se outro programa alterar um arquivo durante a revisão, o salvamento normal é bloqueado; **Salvar nova cópia** permite preservar o trabalho em uma cópia independente.

**Backup** inclui configurações, glossários, memórias, revisões e suas referências de origem. Não inclui modelos nem vídeos. **Restaurar backup** valida os caminhos e cria um backup de segurança antes de restaurar. Arquivos ficam em `backups/studio/`; conserve uma cópia em outro dispositivo para proteger contra perda do disco.

Relatórios de tradução bloqueada antigos podem não conter os blocos parciais recuperáveis. Os novos relatórios registram a identidade da origem e os blocos já validados; propostas rejeitadas continuam sinalizadas para revisão, sem publicação automática.

## Consistência da temporada — prioridade 2

Abra **Revisão → Temporada** ou **Animes → Temporada e guia de estilo**. O painel reúne:

- **Resumo:** blocos, pendências, falas rápidas, linhas longas, fonte, falhas e tempo registrado. **Pasta de legendas** analisa os SRT/ASS/VTT da pasta escolhida e suas subpastas. **Carregar anime** procura nas temporadas vinculadas, nas cópias revisadas e nas pastas configuradas de tradução/transcrição, filtrando pelo projeto. Arquivos antigos sem associação podem ser encontrados pela pasta e associados ao anime na Revisão. Falhas de leitura aparecem no painel.
- **Busca:** procura na origem associada e na tradução dos arquivos carregados. **Revisar** abre o bloco correspondente. Há limite explícito de 1000 resultados; refine a busca quando necessário.
- **Correções:** informe texto atual e corrigido, escolha diferenciação de maiúsculas e termo inteiro, e clique em **Gerar prévia**. Confira os contextos e marque apenas as ocorrências desejadas. **Aplicar selecionados** grava cópias revisadas com histórico; os originais permanecem intactos e só os blocos modificados perdem a aprovação. Tags e comandos de formatação não são substituídos. Alterações externas após a prévia exigem gerar uma nova prévia. Se algum arquivo falhar ao salvar, os demais resultados concluídos são mantidos e a falha é exibida; não se trata de uma transação única da temporada inteira.
- **Guia de estilo:** escolha o anime no seletor do painel e configure honoríficos, formalidade, intensidade dos palavrões, notas existentes, caracteres por linha e caracteres por segundo. O guia é salvo em `series_projects/<id>/style.json`, entra no prompt do TranslateGemma e participa da identidade dos checkpoints. Novas traduções e retraduções passam a usá-lo; traduções prontas não são alteradas automaticamente. Correções humanas memorizadas continuam tendo preferência. As opções orientam o modelo e precisam de conferência humana.
- **Sincronização:** aplica à legenda aberta a fórmula `novo tempo = tempo atual × fator + atraso`. Use fator `1` para atraso fixo; atraso positivo mostra a legenda mais tarde. O fator corrige desvio progressivo; por exemplo, `25 / 23,976 ≈ 1,04271` converte tempos de uma versão a 25 fps para outra a 23,976 fps. Confira o primeiro e último bloco na prévia, aplique ao rascunho e salve a cópia. O histórico recupera também os tempos anteriores. Tempos negativos, inválidos ou com duração zerada pelo arredondamento são recusados. O ajuste não detecta cortes diferentes entre edições do vídeo.

**Prévia de quebras de linha**, em Correções, usa somente a legenda aberta e o limite do seu anime (42 por padrão). O texto simples é distribuído em até duas linhas sem remover palavras. Tags, desenhos, músicas e falas marcadas como simultâneas são preservados para revisão manual. Falas que continuam rápidas são sinalizadas; o editor não apaga conteúdo nem estende tempos automaticamente para esconder o alerta.

Os resumos de processamento ficam em `outputs/studio/episode_reports/` e acompanham o backup. Tempos anteriores à atualização podem estar ausentes. O tempo individual mede a execução do episódio após a preparação em lote; o tempo de preparação do lote aparece separado e não deve ser somado uma vez por episódio. Recarregue a pasta/anime após processamento ou alterações feitas em outro programa para atualizar busca e resumos. A análise limita o escopo a 1500 legendas e a prévia a 5000 blocos modificados.

## Ferramentas de fansub — prioridade 3

Abra **Revisão → Fansub**. Na fila, **Organizar / estimar** abre o mesmo painel e continua disponível durante o processamento para consultar as estimativas; ações que modificam dados ficam bloqueadas enquanto há uma tarefa.

### Falas simultâneas, músicas e placas

O painel **Falas, músicas e placas** apresenta sugestões baseadas em marcadores musicais, comandos de posição e estilos ASS reconhecidos. Sugestões não são aplicadas automaticamente. Selecione os blocos, escolha **Diálogo**, **Música** ou **Placa**, e use **Marcar seleção / atual**. Sem seleção, a ação usa o bloco atual. **Confirmar sugestão** confirma somente a linha correspondente.

Marque **Fala simultânea confirmada** nos dois blocos que realmente se sobrepõem. Só então essa sobreposição deixa de ser sinalizada como suspeita. Os eventos, textos e tempos continuam separados; não há fusão automática de falas. A marcação não elimina alertas de tempo inválido ou legibilidade. Músicas e placas confirmadas, assim como eventos simultâneos confirmados, são preservados pela prévia de quebras de linha da temporada.

As marcações removem a aprovação dos blocos afetados e ficam nos rascunhos, cópias revisadas, histórico e backup. Use **Salvar cópia**. Alterações externas na cópia revisada invalidam as classificações anteriores até nova conferência.

### Exportação ASS e padrões salvos

Em **Exportação ASS**, configure família da fonte, tamanho, cor, contorno, sombra, margem, posição superior/inferior do diálogo e resolução de referência. **Exportar cópia ASS** grava um arquivo novo em `outputs/studio/exports/`; nomes repetidos recebem um sufixo, sem substituir exportações anteriores. Um `.export.json` registra origem, padrão e classificações.

Para origens **SRT/VTT**, a conversão mantém cada evento e suas quebras, conserva formatação simples suportada (itálico, negrito, sublinhado, tachado e cor hexadecimal) e cria estilos próprios para diálogos, músicas, placas e eventos simultâneos. No padrão genérico, músicas e placas ficam no alto; no Visual padrão streaming ficam embaixo, conforme a referência ASS fornecida. O renderizador organiza colisões entre diálogos simultâneos no mesmo plano, sem mudar os tempos. Tags incompatíveis, comandos ASS literais no texto e durações que zerariam ao arredondar para centésimos são recusados para conferência manual.

Para origens **ASS**, a exportação conserva os estilos, posições, desenhos, nomes de falantes e fontes declaradas no arquivo existente; os campos do novo padrão não substituem essa diagramação. Este painel não é um editor visual de placas nem cria karaokê com temporização por sílaba. As fontes precisam estar instaladas no computador; elas não são incorporadas ao novo arquivo automaticamente.

Com um vídeo associado, **Renderizar prévia no vídeo** gera uma imagem e um trecho H.264/AAC de até 15 segundos usando o bloco atual, a linha temporal original e a faixa de áudio da revisão. **Reproduzir prévia** abre esse trecho no reprodutor padrão. A prévia não altera o vídeo original. Em janelas menores, role o painel para ver a imagem inteira.

Use **Salvar padrão** para reutilizar as configurações. O seletor permite padrões globais (`export_presets/global.json`) ou específicos do anime selecionado (`series_projects/<id>/export_presets.json`). Carregar e remover um padrão não apaga legendas exportadas. Padrões e exportações ASS acompanham o backup do Studio.

### Organização e estimativa da fila

**Organizar temporada** analisa os arquivos diretamente na pasta escolhida. Reconhece numeração como `S01E02`, `Episode 02` e `Anime - 02`, separa especiais/aberturas/encerramentos e apresenta possíveis ausentes por temporada. O último episódio informado permite procurar ausências também no final; com zero, a busca termina no maior episódio identificado. Numerações desconhecidas e faixas de episódios são mostradas para revisão manual.

Possíveis duplicados são arquivos com a mesma temporada, episódio e extensão. Eles podem ser versões diferentes: o painel não verifica igualdade do conteúdo. **Adicionar todos na ordem exibida** adiciona os arquivos à fila; **Ordenar pendentes** reorganiza apenas as entradas não concluídas e conserva as opções individuais. Nenhum arquivo é renomeado, movido ou apagado. A ordenação exige que o processamento esteja parado.

**Estimativa e atalhos** mostra tempo aproximado, velocidade histórica em episódios/hora, tamanho previsto das saídas e espaço livre nos destinos. São necessárias pelo menos duas execuções concluídas com operação, formato, modelos e configurações compatíveis. Os relatórios anteriores à prioridade 3 podem não conter esses dados. A parcela de preparação em lote é distribuída entre os itens para formar a amostra de duração efetiva.

Se parte da fila não tiver histórico, o tempo mostrado cobre apenas os itens estimáveis e a quantidade desconhecida aparece ao lado. Estimativas não são garantias: a duração e complexidade dos episódios e as etapas têm custos diferentes. O espaço previsto cobre saídas a partir do histórico, excluindo modelos e temporários; os destinos podem estar em discos diferentes. O painel é atualizado aproximadamente a cada cinco segundos e não executa um benchmark em segundo plano.

### Atalhos na Revisão

| Atalho | Ação |
|---|---|
| `Ctrl+S` | Salvar cópia revisada |
| `Alt+↑` / `Alt+↓` | Selecionar bloco anterior / próximo e acompanhá-lo na lista |
| `Ctrl+Enter` | Aprovar o bloco válido e avançar |
| `Alt+P` | Reproduzir o trecho correspondente |
| `Alt+B` | Reproduzir começando cinco segundos antes do bloco |

Os atalhos ficam ativos na página Revisão, sem processamento e com seus painéis fechados. Diálogos modais de arquivo também bloqueiam essas ações. A reprodução usa um trecho novo no reprodutor externo; não controla a posição de um player que já estava aberto.

## Gerenciamento e conveniência — prioridade 4

Em **Configurações**, abra **Recursos, modelos, limpeza e conclusão**. O mesmo painel pode ser aberto em **Diagnóstico → Gerenciar recursos e modelos**. Os controles são salvos em `config.json` e acompanham o backup; a configuração inicial mantém o comportamento anterior.

### Recursos

- **Threads da CPU:** `0` mantém a escolha automática; um número positivo, até o número de processadores lógicos disponível, limita o processamento auxiliar dos trabalhadores do Faster-Whisper, as bibliotecas numéricas e os pedidos ao Ollama. As variáveis são passadas aos subprocessos, sem mudar o ambiente global do Windows. Não é uma limitação percentual de uso da CPU e nem todos os codecs usam esses controles.
- **GPU obrigatória:** os pedidos de tradução exigem todas as camadas na GPU. O antigo controle de camadas foi removido para impedir inferência em CPU ou mista. Se faltar VRAM, libere memória ou escolha um modelo menor.
- **Prioridade reduzida:** trabalhadores novos usam prioridade abaixo do normal no Windows. O Studio também ajusta a prioridade de seu próprio servidor Ollama, quando existente; servidores externos não são alterados.

Use **Aplicar controles** antes de iniciar outro trabalho. Os modelos, quantização, precisão e tamanho de contexto continuam iguais. Reduzir recursos pode aumentar o tempo de processamento. Mudanças nessas opções também separam as amostras usadas na estimativa de duração da fila.

### Modelos locais

**Atualizar inventário** consulta manifests/blobs do Ollama, snapshots do Hugging Face, checkpoints locais e modelos ONNX do RapidOCR. A lista mostra nome, tamanho lógico, pasta e estado dos arquivos necessários; **Abrir pasta** facilita a inspeção. A consulta não depende de downloads e não remove modelos.

**Verificar SHA-256** compara arquivos que possuem um hash de referência publicado/disponível no armazenamento. A operação lê os arquivos e pode ser interrompida. Arquivos sem esse hash são contados separadamente; a ferramenta não declara integridade comprovada nesses casos. Tamanhos por modelo podem incluir arquivos compartilhados e não representam uma soma exata do espaço físico ocupado. Presença dos arquivos não garante suporte da GPU, compatibilidade de runtime ou qualidade da saída.

### Limpeza assistida

Escolha uma idade mínima em dias e clique em **Gerar prévia**. O padrão é sete dias; `0` inclui todos os arquivos elegíveis. Nada começa selecionado. As categorias permitidas são:

- Arquivos de prévias em `outputs/studio/previews/` que podem ser gerados novamente.
- Logs de sessões antigas em `logs/studio/`, com nomes de sessão reconhecidos; logs de inicialização/servidor e o log atual ficam preservados.
- Arquivos `.pyc` em caches `__pycache__` do código do projeto, da interface, ferramentas e testes.

A limpeza não alcança modelos, traduções, transcrições, amostras de teste, exportações, glossários, histórico, backups nem checkpoints de retomada. Referências ativas da revisão/prévia são protegidas. Links e junctions são recusados. A prévia informa os caminhos e o tamanho lógico selecionado, que pode diferir do espaço físico liberado em arquivos comprimidos ou compartilhados.

**Excluir selecionados…** abre uma confirmação: a exclusão é definitiva, sem lixeira. Imediatamente antes de cada exclusão o Studio revalida localização, categoria, tamanho, data e identidade do arquivo. Arquivos que mudaram desde a prévia são ignorados com aviso; falhas individuais são informadas. A ferramenta exclui apenas os arquivos selecionados e não faz exclusão recursiva de pastas. Durante a implementação, nenhuma limpeza foi executada nos arquivos reais do usuário.

### Ações ao concluir

Escolha entre atualizar somente o estado, notificar, abrir a pasta do último resultado ou suspender após contagem regressiva. A ação escolhida é capturada quando a fila começa. Episódios adicionados durante a execução entram no mesmo ciclo; a ação final só ocorre após o último lote.

A notificação usa o aviso do Studio, um sinal sonoro e a área de notificações do Windows quando disponível. Abrir resultados e suspender exigem uma fila integralmente concluída; interrupções, erros, itens pendentes ou fechamento cancelam essas ações.

Para suspender, escolha a opção e clique em **Armar suspensão para a próxima fila**. Essa autorização é temporária e vale uma única execução; ela não é restaurada ao reabrir o programa. Ao terminar com sucesso, o Studio mostra uma contagem de 60 segundos com **Cancelar suspensão**. Novo trabalho, adição de arquivos, revisão modificada, fechamento ou cancelamento impedem a suspensão. Diálogos nativos abertos no momento da ação também a cancelam. A operação usa a suspensão normal do Windows, sem forçar o encerramento de aplicativos; depende das permissões e estados de energia disponíveis.

Os testes verificaram a programação, o cancelamento e a chamada de energia por simulação. O computador não foi suspenso durante a validação.

## Faixa de áudio da transcrição

Em **Configurações → Faixa do áudio**, `auto` prioriza uma faixa japonesa identificada nos metadados, evitando comentários do diretor. Se não houver japonês, respeita as indicações de faixa original/padrão. Informar explicitamente o idioma seleciona uma faixa correspondente; informar um índice global de stream escolhe essa faixa diretamente. Se os metadados forem incompatíveis com o idioma solicitado, o aplicativo pede correção em vez de forçar o idioma em outra dublagem. Metadados ausentes ainda exigem detecção ou seleção manual.

Whisper e Demucs recebem a mesma faixa. O console informa índice, idioma, modelo e se a separação está habilitada. Uma vez detectado o idioma, ele permanece fixo nos reprocessamentos de trechos curtos. Cada SRT do Faster-Whisper acompanha um `.transcription.json` com metadados, segmentos e alertas para revisão. Alertas não removem automaticamente falas legítimas.

Os modelos completos já presentes em `cache/hub/` são abertos diretamente por seu snapshot, sem atualizar o arquivo `refs/main`. Os trechos vazios reprocessados usam VAD e exigem confiança mínima antes de inserir falas novas.

## Contexto, reavaliação e fidelidade

Cada transcrição acompanha um `.source.json`, vinculado ao SHA-256 do SRT, com a origem, identidade da série e cópia dos termos confirmados. Assim o tradutor encontra o mesmo contexto mesmo fora da pasta do vídeo e quando a origem não está disponível. Se o SRT for alterado, o vínculo deixa de ser usado até ser regenerado; glossários locais explícitos continuam disponíveis.

Pronúncias/grafias podem ser fornecidas em `whisper_glossary.json` na pasta dos vídeos ou em `<arquivo>.whisper_glossary.json`: um objeto JSON que associa a grafia no idioma original à tradução confirmada. Por exemplo, `{"ミラ":"Mira", "月の塔":"Torre da Lua"}`. O registro portátil equivalente fica em `series_speech/<identidade-da-pasta>.json`. Esses dados são específicos da série; não são substituições globais no código.

O Whisper recebe grafias confirmadas como dicas, não como falas a inserir. Reavaliações com significados muito diferentes, perda de conteúdo ou confiança insuficiente preservam a hipótese anterior e ficam na auditoria. Descontinuidades nas palavras são verificadas em pequenos recortes do áudio original. O realinhamento aceito preserva palavras fora do recorte; nunca aproxima duas falas separadas por longo silêncio apenas mudando o tempo do SRT.

A tradução isola falas curtas ou incertas do diálogo vizinho, recebe grafias da série como referência e verifica expansão indevida também em japonês. Resultados críticos não são publicados após esgotar tentativas: é criado um `.review_required.json` e o checkpoint dos blocos validados permanece. Trechos já salvos no cache também passam pela nova validação. Alertas `source_fragment` e `asr_disagreement` indicam revisão da origem. Essas verificações não comprovam fidelidade semântica completa nem substituem conferência humana.

## Operações

- **Automático:** vídeo/áudio passa por transcrição e tradução; legendas SRT, ASS ou VTT entram direto na tradução. A extração opcional salva também as faixas existentes, mas não substitui a transcrição do áudio.
- **Só transcrever:** gera legenda a partir de vídeo ou áudio.
- **Só traduzir:** recebe SRT, ASS ou VTT. Para vídeos, use extração ou transcrição antes.
- **Extrair legendas:** extrai faixas de vídeo ou converte legendas para o formato escolhido, na pasta configurada.

Com vários vídeos e extração adicional desativada, a transcrição usa um único trabalhador em lote para manter o Whisper carregado. A tradução permanece no servidor Ollama entre episódios. A configuração com extração adicional segue o fluxo individual.

A fila persiste em `outputs/studio/queue.json`. Episódios concluídos não são repetidos ao iniciar os pendentes. **Retomar falhas** repete a operação original dos episódios com erro ou interrompidos; checkpoints da tradução continuam sendo administrados pelo tradutor existente. **Limpar concluídos** retira itens da fila e não apaga os arquivos produzidos.

Não há limite fixo de dois episódios: uma temporada inteira pode ser adicionada de uma vez, mantendo os concluídos na lista. Novos arquivos podem ser adicionados durante a execução; eles entram no próximo lote automaticamente, com a operação e as configurações da execução em andamento. A interrupção ou o fechamento impede essa continuação automática e mantém os novos episódios aguardando.

**Reenfileirar** adiciona uma nova entrada para um arquivo concluído, preservando a anterior e seus resultados. Duplicatas já pendentes são ignoradas com aviso. As atualizações de progresso são incrementais, preservando a rolagem, e a barra de rolagem fica visível quando há mais itens do que espaço. Entradas adicionadas para o próximo lote podem ser removidas enquanto o lote atual trabalha; entradas desse lote ficam protegidas.

As preferências usam o mesmo `config.json`, preservando chaves desconhecidas. Elas são bloqueadas durante uma execução. O fechamento durante uma tarefa permite interromper e aguarda seu encerramento. Somente processos iniciados pelo Studio são encerrados por seu controle de processos; um servidor Ollama reutilizado não é finalizado pelo Studio.

## Estrutura técnica

`studio_ui/pipeline.py` coordena os trabalhos sem depender do loop de eventos de uma interface. `backend.py` expõe os dados ao QML e consome eventos na thread da interface. `process_runtime.py` contém os auxiliares de ambiente, captura de processos e localização de recursos, sem dependência de Tkinter. `runtime.py` adapta esses auxiliares ao servidor Ollama portátil. `review_workspace.py` administra cópias, versões e backups; `series_registry.py` separa termos e memórias por anime. Whisper e tradução recebem o contexto do projeto selecionado.

O adaptador do Ollama usa explicitamente `.ollama_home/` como perfil de seu servidor portátil, grava o log do servidor e detecta encerramento prematuro. Isso evita depender da permissão do perfil do Windows.

O novo executável é um inicializador pequeno: usa o Python já fornecido em `runtime/python/`, onde as dependências Qt estão instaladas. Não duplica os modelos nem inclui outra cópia de todo o runtime. Portanto, ele não deve ser distribuído sozinho.

O inicializador é distribuído em modo pasta, com seus recursos em `_studio_boot/`. Essa pasta deve acompanhar o executável; a abertura não exige extrair o programa em uma pasta temporária do Windows.

Dependências da interface: `studio_ui/requirements.txt`. As licenças dos pacotes Qt/PySide6 e suas dependências acompanham a instalação em `runtime/python/Lib/site-packages/`; devem ser mantidas ao distribuir o projeto.

## Validação e build

```powershell
.\runtime\python\python.exe -X utf8 -B -m unittest discover -s tests -p 'test_*.py'
.\runtime\python\python.exe -X utf8 -B studio_launcher.py --smoke-test
.\runtime\python\python.exe -X utf8 -B tests/check_package.py
.\runtime\python\python.exe -X utf8 -B tools/check_studio.py --translate
```

O último comando usa entradas descartáveis: conversão real por FFmpeg, tradução curta no TranslateGemma local e cancelamento de um subprocesso. Ele não reprocessa a temporada. Relatórios ficam em `docs/validation/studio_*`.

Para recompilar o inicializador, com PyInstaller 6.22.0 no runtime:

```powershell
.\runtime\python\python.exe -X utf8 -B tools/build_studio.py
```

Feche o Studio antes de substituir seu executável. Alterações Python/QML são carregadas na próxima abertura. A qualidade de uma temporada inteira continua exigindo revisão de suas legendas; o teste curto de integração não substitui essa revisão.

## Glossário online (1.0.2)

Em **Animes**, selecione o projeto e abra **Glossário online e sugestões de IA**. O painel tem Catálogo, Contribuir, IA local e Histórico. Consulte [o guia do catálogo](https://github.com/Fernandobaruck/SubForgeAI/blob/main/community/glossary/README.md). A consulta é manual; não há envio automático de termos ou arquivos. A importação cria sugestões e preserva os termos existentes, inclusive os confirmados. Só termos confirmados localmente passam a orientar novas traduções.

O catálogo inicial contém uma coleção opcional de honoríficos; coleções específicas de anime dependem de propostas revisadas. Sem conexão, coleções já baixadas continuam disponíveis pelo cache, com aviso. Na IA local, o TranslateGemma apenas propõe traduções, sem verificar o cânone do anime. A seção Contribuir mostra uma prévia antes de abrir um formulário público no GitHub. É necessário enviar o formulário manualmente e ter uma conta no GitHub para contribuir.

## Visual padrão streaming na exportação ASS

Em **Revisão → Fansub → Exportação ASS**, use **Visual padrão streaming** para carregar um estilo opcional calibrado com as referências: Trebuchet MS regular, tamanho ASS 26 em 640×480, branco, contorno preto 2,25, sombra 0,7, alinhamento inferior, margens laterais 24 e inferior 20. Músicas usam tamanho 24 em itálico, contorno 2 e margens 26/26/23; títulos usam tamanho 24 e contorno 2. Contorno e sombra aceitam frações. As músicas precisam estar classificadas ou conter marcadores reconhecíveis; o programa não presume que toda fala no início do episódio seja música. O renderizador escala o estilo proporcionalmente em outras resoluções. Não é um padrão oficial nem uma garantia de reprodução idêntica em todos os reprodutores.

O botão apenas preenche os controles. Use **Renderizar prévia no vídeo** para conferir e **Exportar cópia ASS** para gerar a saída; **Salvar padrão** guarda os ajustes nos padrões existentes. **Restaurar estilo padrão** recupera Arial 48 sem negrito. As configurações padrão e os arquivos originais não são alterados automaticamente.

O estilo é aplicado ao converter SRT/VTT em ASS. ASS existente conserva sua diagramação, inclusive placas e posições. As quebras de linha existentes são preservadas; o resultado depende também delas, da resolução e do reprodutor. A fonte precisa existir no computador; o Studio avisa quando ela não é encontrada. Arquivos de fonte do Windows não são incluídos no aplicativo.

## Uso simples do visual padrão streaming

Nas telas **Início**, **Episódios** e **Tradução**, ative **Visual padrão streaming** e use a fila normalmente. Ao concluir, o Studio cria também uma legenda `.visual.ass` ao lado do resultado original, com fonte branca regular, contorno preto e sombra discreta. Se a incorporação ao vídeo estiver ativada, a versão estilizada é a usada para incorporar. O estilo também é aplicado às saídas de transcrição e extração.

Para legendas já prontas, abra **Resultados** e use **Aplicar padrão streaming na pasta**, escolhendo a pasta das legendas da temporada. Para um único arquivo, selecione-o na lista e clique em **Aplicar padrão streaming**. Não há retradução. Textos e tempos são preservados; os arquivos existentes não são substituídos. Repetir a operação reutiliza uma cópia ainda válida.

Em ASS existente, somente falas comuns recebem os comandos de fonte e contorno; placas posicionadas, desenhos, músicas e efeitos identificados são preservados. A fonte Trebuchet MS deve existir no reprodutor. Os controles de fonte/tamanho da Revisão continuam disponíveis para ajustes avançados, mas não são necessários neste fluxo.


### Modelos e memória na preparação

Em **Preparar para começar**, escolha **Usar este modelo** e **Baixar modelo** para o TranslateGemma 4B, 12B ou 27B. Apenas o modelo escolhido precisa ser baixado. O 12B continua como padrão; a seleção é salva e vale também para retradução e sugestões do glossário.

| Modelo Q4_K_M | Download aproximado | VRAM estimada, contexto curto | Capacidade recomendada |
|---|---|---|---|
| 4B | 3,3 GB | 4–6 GB | 6 GB ou mais |
| 12B | 8,1 GB | 10–12 GB | 12 GB ou mais |
| 27B | 17 GB | 20–24 GB | 24 GB ou mais |

As faixas de VRAM são estimativas de planejamento, não benchmarks nem limites garantidos. Contexto, lote e memória ocupada por outros processos afetam o consumo. Inferência em CPU ou dividida com CPU é bloqueada: libere VRAM ou selecione um modelo menor. Os exemplos de NVIDIA, AMD e Intel na tela indicam capacidade; AMD/Intel ainda precisam de validação no projeto. A seleção de tradução não muda o suporte do Whisper. Fontes: [modelos oficiais](https://ollama.com/library/translategemma), [compatibilidade do Ollama](https://docs.ollama.com/gpu).


### GPU obrigatória e Vulkan

A IA exige GPU. No Whisper, **Automático** escolhe CUDA quando disponível e Vulkan nas outras máquinas; também é possível escolher CUDA ou Vulkan em Configurações. Prepare o modelo correspondente em **Preparar para começar**: os formatos CUDA e Vulkan são diferentes. Não há conversão ou download de modelo diferente silenciosamente. Os downloads Vulkan incluem um runtime portátil fixado por SHA256 e modelos oficiais de mesma variante.

O Ollama gerenciado habilita Vulkan e oculta CUDA/HIP/ROCm quando CUDA não está disponível. Antes de enviar texto de tradução ou glossário, uma carga sem prompt verifica que o modelo inteiro está residente na GPU usando `/api/ps`. Cargas CPU ou mistas são rejeitadas e descarregadas; pedidos de inferência exigem todas as camadas na GPU. Servidores externos também precisam passar pela verificação.

O Whisper Vulkan mantém um servidor local apenas em 127.0.0.1, verifica o backend carregado antes de enviar áudio e reutiliza o modelo no lote. Falhas CUDA não tentam CPU. Demucs exige CUDA nesta distribuição; quando explicitamente solicitado em Vulkan, a execução é bloqueada. No modo automático Vulkan, usa-se áudio original. OCR com motor CPU e Silero VAD via ONNX CPU estão desabilitados. Esta mudança no VAD pode alterar segmentação e exige revisão dos resultados; os filtros não neurais de qualidade e as novas tentativas CUDA continuam ativos.

Interface, FFmpeg, espectrogramas, leitura de arquivos e amostragem de tokens ainda usam CPU como trabalho auxiliar. GPU obrigatória significa inferência pesada dos modelos na GPU, não ausência de uso do processador. Vulkan depende de driver e recursos da placa; não é uma promessa de suporte a qualquer GPU. AMD e Intel precisam de testes físicos para confirmar compatibilidade.

O motor Vulkan aplica os filtros não neurais de texto, tempos e alucinações e registra auditoria de qualidade. Alinhamento por palavras e novas tentativas adaptativas do Faster-Whisper ainda não estão disponíveis nesse motor; a auditoria registra essas capacidades explicitamente.


### Escolha do Whisper por memória

Em **Preparar para começar**, há seis modelos multilíngues com **Usar este modelo**, download CUDA para NVIDIA e download Vulkan para placas compatíveis. A escolha também aparece em **Configurações → Modelo Whisper**.

| Modelo | Download aproximado | VRAM estimada (FP16, uma transcrição) | Capacidade recomendada |
|---|---|---|---|
| Tiny | 0,08 GB | 1–2 GB | 3 GB |
| Base | 0,15 GB | 1–2 GB | 3 GB |
| Small | 0,49 GB | 2–3 GB | 4 GB |
| Medium | 1,53 GB | 3–5 GB | 6 GB |
| Large v3 Turbo | 1,63 GB | 3–6 GB | 8 GB |
| Large v3 | 3,1 GB | 5–10 GB | 12 GB |

As faixas são estimativas conservadoras para os motores do projeto, não medições em todas as placas nem mínimos garantidos. O [Whisper original](https://github.com/openai/whisper#available-models-and-languages) e o [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper#benchmark) apresentam consumos diferentes; backend, driver, alinhamento, lote e separação de voz alteram a necessidade. A tela exibe exemplos de NVIDIA, AMD e Intel por capacidade; suporte real e velocidade precisam ser validados em cada placa. Essas recomendações não incluem Demucs nem a memória do TranslateGemma. Tiny/Base consomem menos memória, mas tendem a reconhecer pior falas difíceis de animes. Large v3 continua a opção mais completa; Turbo é uma opção de velocidade mesmo em PCs fortes.


### Seleção de arquivos e pastas

Os seletores usam a janela nativa do sistema. No Windows, ficam disponíveis busca, Acesso Rápido, discos e seleção múltipla. **Adicionar episódios ou legendas** lembra a última pasta escolhida; se ela não existir mais, usa uma origem válida da fila ou a pasta Vídeos do usuário. Os filtros separam vídeos, áudios, legendas e todos os arquivos, sem exibir a lista extensa de padrões no nome do filtro. A pasta é lembrada em `outputs/studio/file_browser.json`, um estado local excluído das distribuições. Cancelar a seleção mantém a fila. O visual e o idioma dos controles nativos seguem o Windows.


### Um arquivo final por tradução

A fila mostra e entrega a legenda final: `.visual.ass` com o Visual padrão streaming, ou `.srt` no modo original. Quando uma ASS é criada, o SRT gerado durante o processamento fica guardado em `.subforge`, junto dos relatórios JSON e da proveniência. Essa pasta é interna e oculta no Windows; não aparece na lista de Resultados. A revisão e os avisos continuam funcionando, e os leitores aceitam também os arquivos auxiliares antigos ao lado da legenda. As entradas fornecidas pelo usuário são preservadas. A incorporação opcional ainda entrega o vídeo correspondente. Exportações ASS manuais também guardam seu relatório internamente.
