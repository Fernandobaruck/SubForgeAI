import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
Dialog {
    id: dialog; objectName: "maintenanceDialog"
    property var maintenance: Backend.maintenance
    property int section: 0
    onOpened:maintenance.setPanelOpen(true)
    onClosed:maintenance.setPanelOpen(false)
    anchors.centerIn: Overlay.overlay; modal: true; padding: 18
    width: Math.min(1040,Overlay.overlay.width-32); height: Math.min(740,Overlay.overlay.height-32)
    background: Rectangle {color:Theme.bg;radius:12;border.color:Theme.line}
    contentItem: ColumnLayout {
        spacing: 12
        RowLayout {
            Layout.fillWidth:true
            Text {text:Tr.tr("Gerenciamento do Studio");color:Theme.text;font.pixelSize:20;Layout.fillWidth:true}
            ActionButton {text:Tr.tr("Fechar");onClicked:dialog.close()}
        }
        Flow {
            Layout.fillWidth:true;spacing:6
            ActionButton {text:Tr.tr("Recursos");primary:dialog.section===0;onClicked:dialog.section=0}
            ActionButton {text:Tr.tr("Modelos locais");primary:dialog.section===1;onClicked:{dialog.section=1;maintenance.refreshModels()}}
            ActionButton {text:Tr.tr("Limpeza assistida");primary:dialog.section===2;onClicked:dialog.section=2}
            ActionButton {text:Tr.tr("Ao concluir a fila");primary:dialog.section===3;onClicked:dialog.section=3}
        }
        Text {textFormat:Text.PlainText;text:maintenance.result;visible:text.length>0;color:Theme.accent;Layout.fillWidth:true;wrapMode:Text.Wrap;maximumLineCount:3;elide:Text.ElideRight}
        StackLayout {
            Layout.fillWidth:true;Layout.fillHeight:true;currentIndex:dialog.section
            ColumnLayout {
                Text {text:Tr.tr("Os controles valem para novos trabalhos. Modelos, precisão e contexto permanecem iguais; reduzir recursos pode aumentar o tempo de processamento.");Layout.fillWidth:true;wrapMode:Text.Wrap;color:Theme.muted}
                SettingRow {Layout.fillWidth:true;title:Tr.tr("Threads da CPU");description:Tr.tr("0 usa a escolha automática. O limite é aplicado aos trabalhadores de transcrição, bibliotecas numéricas e pedidos ao Ollama.")
                    TextField {id:threads;objectName:"resourceThreads";text:String(Backend.settings.resource_cpu_threads);validator:IntValidator {bottom:0;top:maintenance.maxCpuThreads} enabled:!Backend.busy;color:Theme.text;padding:12;implicitWidth:150;background:Rectangle {color:Theme.card;border.color:Theme.line}}
                }
                Text {text:Tr.tr("GPU obrigatória: todas as camadas da tradução devem caber na GPU. Se faltar VRAM, escolha um modelo menor; inferência em CPU ou dividida com CPU será bloqueada.");Layout.fillWidth:true;wrapMode:Text.Wrap;color:Theme.accent}
                CheckBox {id:background;objectName:"resourceBackground";text:Tr.tr("Executar trabalhadores com prioridade reduzida no Windows");checked:Backend.settings.resource_background;enabled:!Backend.busy;palette.windowText:Theme.text}
                ActionButton {objectName:"applyResources";text:Tr.tr("Aplicar controles");primary:true;enabled:!Backend.busy && threads.acceptableInput
                    onClicked:{var cpu=Number(threads.text);var bg=background.checked;Backend.updateSetting("resource_cpu_threads",cpu);Backend.updateSetting("resource_background",bg)}
                }
                Text {text:Tr.tr("O motor CUDA/Vulkan do Whisper pode ser escolhido em Configurações. A CPU continua responsável pela interface e preparação dos arquivos.");color:Theme.muted;Layout.fillWidth:true;wrapMode:Text.Wrap}
                Item {Layout.fillHeight:true}
            }
            ColumnLayout {
                RowLayout {
                    ActionButton {objectName:"refreshLocalModels";text:Tr.tr("Atualizar inventário");enabled:!Backend.busy;onClicked:maintenance.refreshModels()}
                    Text {text:Tr.tr("Consulta local; nenhum download é necessário para listar.");color:Theme.muted;Layout.fillWidth:true;wrapMode:Text.Wrap;font.pixelSize:11}
                }
                Text {text:Tr.tr("Tamanhos são lógicos por modelo; arquivos compartilhados podem ser contados em mais de um. Presença local não garante compatibilidade com o hardware.");color:Theme.muted;Layout.fillWidth:true;wrapMode:Text.Wrap;font.pixelSize:11}
                ListView {
                    Layout.fillWidth:true;Layout.fillHeight:true;clip:true;model:maintenance.models;spacing:8;ScrollBar.vertical:ScrollBar {}
                    delegate:Rectangle {
                        required property var modelData
                        width:ListView.view.width-8;height:126;radius:8;color:Theme.card
                        RowLayout {anchors.fill:parent;anchors.margins:10
                            ColumnLayout {Layout.fillWidth:true
                                Text {textFormat:Text.PlainText;text:modelData.name;color:Theme.text;Layout.fillWidth:true;elide:Text.ElideMiddle}
                                Text {textFormat:Text.PlainText;text:modelData.type+" · "+(modelData.bytes/1073741824).toFixed(2)+" GB · "+modelData.statusLabel;color:modelData.offline ? Theme.green : Theme.accent;font.pixelSize:11;Layout.fillWidth:true;elide:Text.ElideRight}
                                Text {textFormat:Text.PlainText;text:modelData.path;color:Theme.muted;font.pixelSize:11;Layout.fillWidth:true;elide:Text.ElideMiddle}
                            }
                            ColumnLayout {
                                ActionButton {text:Tr.tr("Abrir pasta");implicitHeight:32;onClicked:maintenance.openModel(modelData.index)}
                                ActionButton {text:Tr.tr("Verificar SHA-256");implicitHeight:32;enabled:!Backend.busy && modelData.offline;onClicked:maintenance.verifyModel(modelData.index)}
                            }
                        }
                    }
                }
                Text {text:Tr.tr("A verificação pode ler vários GB. Arquivos sem hash publicado são informados separadamente; a leitura pode ser interrompida pelo botão Interromper.");color:Theme.muted;Layout.fillWidth:true;wrapMode:Text.Wrap;font.pixelSize:11}
            }
            ColumnLayout {
                Text {text:Tr.tr("A prévia inclui somente arquivos de prévias regeneráveis, logs antigos de sessões e cache Python do código. Modelos, resultados, histórico, backups e checkpoints de retomada permanecem preservados.");color:Theme.muted;Layout.fillWidth:true;wrapMode:Text.Wrap}
                RowLayout {
                    Text {text:Tr.tr("Idade mínima em dias (0 = todos)");color:Theme.text}
                    TextField {id:days;objectName:"cleanupDays";text:"7";validator:IntValidator {bottom:0;top:3650} enabled:!Backend.busy;color:Theme.text;padding:10;Layout.preferredWidth:80;background:Rectangle {color:Theme.card;border.color:Theme.line}}
                    ActionButton {objectName:"scanTemporaryFiles";text:Tr.tr("Gerar prévia");enabled:!Backend.busy && days.acceptableInput;onClicked:maintenance.scanCleanup(Number(days.text))}
                    ActionButton {text:Tr.tr("Selecionar todos");enabled:!Backend.busy;onClicked:maintenance.selectAll(true)}
                    ActionButton {text:Tr.tr("Desmarcar");enabled:!Backend.busy;onClicked:maintenance.selectAll(false)}
                }
                Text {text:Tr.format("{count} arquivos · {size} MB lógicos selecionados",{count:maintenance.selectedCount,size:(maintenance.selectedBytes/1048576).toFixed(1)});color:Theme.accent}
                ListView {
                    Layout.fillWidth:true;Layout.fillHeight:true;clip:true;model:maintenance.cleanup;spacing:5;ScrollBar.vertical:ScrollBar {}
                    delegate:Rectangle {
                        required property var modelData
                        width:ListView.view.width-8;height:68;color:Theme.card;radius:6
                        RowLayout {anchors.fill:parent;anchors.margins:8
                            CheckBox {checked:modelData.checked;enabled:!Backend.busy;onToggled:maintenance.selectCleanup(modelData.id,checked)}
                            ColumnLayout {Layout.fillWidth:true
                                Text {textFormat:Text.PlainText;text:modelData.relative;color:Theme.text;Layout.fillWidth:true;elide:Text.ElideMiddle;font.pixelSize:12}
                                Text {textFormat:Text.PlainText;text:modelData.categoryLabel+" · "+(modelData.bytes/1048576).toFixed(2)+" MB";color:Theme.muted;font.pixelSize:11}
                            }
                        }
                    }
                }
                ActionButton {objectName:"requestCleanup";text:Tr.tr("Excluir selecionados…");danger:true;enabled:!Backend.busy && maintenance.selectedCount>0;onClicked:confirmCleanup.open()}
            }
            ColumnLayout {
                Text {text:Tr.tr("A ação ocorre após o último lote, incluindo episódios adicionados durante a execução. Erros, interrupções ou itens pendentes impedem abrir resultados ou suspender.");color:Theme.muted;Layout.fillWidth:true;wrapMode:Text.Wrap}
                SelectField {objectName:"completionAction";property var codes:["none","notify","open","sleep"];model:[Tr.tr("Somente atualizar o estado"),Tr.tr("Notificar conclusão"),Tr.tr("Abrir pasta do último resultado"),Tr.tr("Suspender após contagem regressiva")];selectedIndex:Math.max(0,codes.indexOf(Backend.settings.completion_action));implicitWidth:380;enabled:!Backend.busy;onActivated:Backend.updateSetting("completion_action",codes[currentIndex])}
                Text {text:Tr.tr("A suspensão exige armar cada nova fila. Após concluir com sucesso, haverá 60 segundos para cancelar. Uma revisão editada ou novo trabalho cancela a suspensão.");color:Theme.muted;Layout.fillWidth:true;wrapMode:Text.Wrap}
                ActionButton {objectName:"armSleep";text:Tr.tr("Armar suspensão para a próxima fila");enabled:!Backend.busy && Backend.settings.completion_action==="sleep" && !maintenance.sleepArmed;onClicked:maintenance.armSleep()}
                Text {text:maintenance.sleepArmed ? Tr.tr("Suspensão armada para uma única fila.") : Tr.tr("Suspensão não armada.");color:maintenance.sleepArmed ? Theme.accent : Theme.muted}
                ActionButton {text:Tr.tr("Cancelar ação final / desarmar");onClicked:maintenance.cancelCompletion()}
                Text {text:Tr.tr("A notificação usa a área de notificações quando disponível, além do aviso no Studio. A suspensão depende da permissão e dos recursos do Windows.");color:Theme.muted;Layout.fillWidth:true;wrapMode:Text.Wrap}
                Item {Layout.fillHeight:true}
            }
        }
    }
    Dialog {
        id:confirmCleanup;objectName:"cleanupConfirmation";anchors.centerIn:Overlay.overlay;modal:true;padding:20;width:Math.min(540,dialog.width-40)
        background:Rectangle {color:Theme.card;radius:10;border.color:Theme.line}
        contentItem:ColumnLayout {
            Text {text:Tr.tr("Excluir definitivamente os temporários selecionados?");color:Theme.text;Layout.fillWidth:true;wrapMode:Text.Wrap;font.pixelSize:17}
            Text {text:Tr.format("São {count} arquivos. A exclusão não usa a lixeira. Arquivos alterados após a prévia serão ignorados com aviso.",{count:maintenance.selectedCount});color:Theme.muted;Layout.fillWidth:true;wrapMode:Text.Wrap}
            RowLayout {
                ActionButton {text:Tr.tr("Cancelar");onClicked:confirmCleanup.close()}
                ActionButton {objectName:"confirmDeleteTemporary";text:Tr.tr("Confirmar exclusão");danger:true;enabled:!Backend.busy;onClicked:{confirmCleanup.close();maintenance.deleteSelected()}}
            }
        }
    }
}

