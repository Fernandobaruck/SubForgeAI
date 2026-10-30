# Publicação de atualizações do SubForgeAI Studio

Repositório: https://github.com/Fernandobaruck/SubForgeAI

O aplicativo consulta `https://api.github.com/repos/Fernandobaruck/SubForgeAI/releases/latest`. A release deve ser estável, publicada, com tag `vMAJOR.MINOR.PATCH` e os dois arquivos abaixo com seus nomes originais.

## Primeira release

O pacote inicial é preparado em `F:\SubForgeAI\dist\releases\v1.0.0\`:

- `SubForgeAI-update-1.0.0.zip`
- `SubForgeAI-update-1.0.0.manifest.json`
- `RELEASE-NOTES.md`, para copiar para a descrição da release.

Abra https://github.com/Fernandobaruck/SubForgeAI/releases/new e use:

1. Tag: **v1.0.0**, criando a tag na branch **main**.
2. Título: **SubForgeAI Studio v1.0.0**.
3. Descrição: conteúdo de `RELEASE-NOTES.md`.
4. Anexos: ZIP e manifesto JSON, sem renomear ou alterar seus conteúdos.
5. Publique como versão estável/latest, sem marcar como pré-release.

A criação do repositório não cria essa release. Enquanto ela não estiver publicada, o launcher informa que ainda não há versões disponíveis. Como esta instalação já é `1.0.0`, a primeira release estabelecerá a referência inicial; o botão de download será habilitado para uma versão maior, como `1.0.1`.

O ZIP é uma atualização de instalação existente; não contém o runtime Python/Qt nem os modelos. Ele inclui os scripts Python distribuídos com o aplicativo. Não envie a pasta inteira do projeto: configurações, glossários, legendas, caches, modelos, relatórios e chave privada não são anexos da release.

## Versões seguintes

Após concluir e validar uma alteração, execute na pasta do projeto:

```powershell
.\runtime\python\python.exe -B -X utf8 tools\prepare_release.py --version 1.0.1
```

O comando prepara os arquivos em `dist/releases/v1.0.1/`. Use uma versão numérica maior a cada publicação. O número é carimbado dentro do ZIP; a versão instalada muda quando o pacote é aplicado. Não edite o ZIP nem o manifesto depois de assinados. Para modificar um pacote, gere outra versão e publique seus dois anexos juntos.

Cada ZIP deste canal é limitado pelo atualizador a 300 MiB, com extração total também limitada a 300 MiB. O empacotador usa uma lista de arquivos permitidos. Runtime, modelos e dados pessoais ficam excluídos. Quando dependências mudarem, planeje um novo pacote de base e uma identificação de runtime compatível.

## Chave de publicação

A chave privada foi criada em `%LOCALAPPDATA%\SubForgeAI-release-signing\release-key.dpapi`, fora da pasta portátil, e protegida por DPAPI do usuário do Windows. A chave pública está fixada em `release_info.py` e é distribuída com o aplicativo. A verificação usa a criptografia nativa do Windows, sem instalar bibliotecas adicionais.

Essa é a assinatura dos pacotes verificada pelo launcher. Ela não é uma assinatura Authenticode do executável e não altera sua reputação no SmartScreen.

Não publique a pasta de assinatura nem envie o arquivo privado em chats. Guarde uma cópia segura dessa pasta e preserve o perfil Windows correspondente: a proteção DPAPI pode impedir abrir a chave em outra máquina/perfil. A perda da chave impede assinar novas versões aceitas pelos clientes atuais; nesse caso será necessária uma transição manual de confiança. Não gere/substitua a chave pública como parte de uma atualização comum.

O empacotador verifica que a assinatura produzida corresponde à chave pública oficial antes de finalizar o manifesto. Os testes usam chaves temporárias diferentes, sem escrever a chave privada oficial nos pacotes.

## Verificação e recuperação

```powershell
.\runtime\python\python.exe -B -X utf8 -m unittest discover -s tests -p 'test_*.py'
.\runtime\python\python.exe -B -X utf8 tests\check_package.py
.\runtime\python\python.exe -B -X utf8 tools\check_updater.py --online
.\runtime\python\python.exe -B -X utf8 tools\check_update_worker.py
```

Os testes de instalação usam cópias isoladas em `reviews/updater/`; não atualizam a instalação em uso. O teste do worker pode precisar criar um vínculo NTFS de execução para o runtime existente, que não é alvo de escrita da atualização. Os registros e resultados ficam em `reviews/updater/`.

Após publicar, use **Verificar atualizações** no aplicativo. O launcher recusa assinatura inválida, arquivos protegidos, ZIP adulterado e versões incompatíveis. Em falhas de instalação, consulte `.updates/last_result.json` e os registros do job antes de tentar novamente. Conserve os backups de atualização até confirmar que a nova versão atende ao seu uso.

## Publicação automatizada pelo mantenedor

Com uma sessão do GitHub autorizada no Git Credential Manager, após preparar e verificar o pacote assinado, execute `runtime/python/python.exe -B -X utf8 tools/publish_release.py --version 1.0.0`. A ferramenta valida a assinatura e o hash, cria uma release em rascunho, envia os dois arquivos e publica. Credenciais não são gravadas nem exibidas. Uma release já publicada não é substituída.

## Pacote inicial para novos usuários

A partir de 1.0.1, `tools/build_portable.py` cria a instalação inicial sem modelos ou dados pessoais. Ela inclui o runtime e as ferramentas necessárias. Bibliotecas estáticas de desenvolvimento (`*.lib`), atalhos e caches de bytecode não são necessários para executar e ficam fora do pacote. Os componentes operacionais da instalação existente são preservados.

Com o runtime preparado e a chave de publicação disponível no perfil do mantenedor:

```powershell
runtime/python/python.exe -B -X utf8 tools/prepare_release.py --version 1.0.1
runtime/python/python.exe -B -X utf8 tools/build_portable.py --version 1.0.5
runtime/python/python.exe -B -X utf8 tools/publish_release.py --version 1.0.5 --portable
```

Execute as verificações antes de publicar. O instalador gráfico `SubForgeAI-Instalar-visual-1.0.5.exe` é a única opção de instalação publicada. Ele inclui a interface e o motor de download em um único executável, sem precisar extrair ZIP ou abrir CMD. Ele verifica um manifesto RSA/SHA-256 próprio e baixa as partes assinadas de até 1 GiB, respeitando o limite por arquivo do GitHub. Os nomes, tamanhos e hashes das partes estão no manifesto. A junção, a verificação do ZIP e a extração são automáticas; o destino precisa ser uma pasta nova. Downloads parciais são mantidos para retomada e partes são removidas depois da instalação bem-sucedida.

A assinatura do manifesto protege o pacote. O executável e os scripts não possuem assinatura Authenticode e o Windows pode exibir editor desconhecido. Não instrua usuários a desativar o antivírus.

`tools/check_installer.py` valida uma instalação pequena assinada, proteção de pasta existente, rejeição de assinatura inválida, arquivo corrompido e caminhos fora da pasta. `tools/check_first_run_ui.py` valida o painel nos três idiomas e dois temas. O pacote completo também deve ser extraído e aberto em uma pasta limpa antes da publicação.
