import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
Dialog {
    id: dialog; objectName: "fansubDialog"
    property var fansub: Backend.review.fansub
    property var review: Backend.review
    property int section: 0
    property string project: review.selectedProject
    function settings() {
        return fansub.setPreset({font:fontInput.text,size:Number(sizeInput.text),color:colorInput.text,outline_color:outlineColor.text,outline:Number(outlineInput.text),shadow:Number(shadowInput.text),margin:Number(marginInput.text),alignment:alignment.currentIndex===1 ? 8 : 2,width:Number(widthInput.text),height:Number(heightInput.text),preserve_ass:true})
    }
    function fillPreset() {
        var p=fansub.preset
        fontInput.text=p.font;sizeInput.text=String(p.size);colorInput.text=p.color;outlineColor.text=p.outline_color
        outlineInput.text=String(p.outline);shadowInput.text=String(p.shadow);marginInput.text=String(p.margin)
        widthInput.text=String(p.width);heightInput.text=String(p.height);alignment.currentIndex=p.alignment===8 ? 1 : 0
    }
    onOpened: fillPreset()
    modal: true; anchors.centerIn: Overlay.overlay; width: Math.min(1080,Overlay.overlay.width-32); height: Math.min(780,Overlay.overlay.height-32); padding: 18
    background: Rectangle {color:Theme.bg;radius:12;border.color:Theme.line}
    contentItem: ColumnLayout {
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Text {text:Tr.tr("Ferramentas de fansub");font.pixelSize:20;color:Theme.text;Layout.fillWidth:true}
            ActionButton {text:Tr.tr("Fechar");onClicked:dialog.close()}
        }
        Flow {
            Layout.fillWidth:true;spacing:6
            ActionButton {text:Tr.tr("Falas, músicas e placas");primary:dialog.section===0;onClicked:dialog.section=0}
            ActionButton {text:Tr.tr("Exportação ASS");primary:dialog.section===1;onClicked:dialog.section=1}
            ActionButton {text:Tr.tr("Organizar temporada");primary:dialog.section===2;onClicked:dialog.section=2}
            ActionButton {text:Tr.tr("Estimativa e atalhos");primary:dialog.section===3;onClicked:dialog.section=3}
        }
        StackLayout {
            Layout.fillWidth:true;Layout.fillHeight:true;currentIndex:dialog.section
            ColumnLayout {
                Text {text:Tr.tr("Sugestões não alteram a legenda. Confirme o tipo de cada bloco. Uma sobreposição só deixa de ser suspeita quando os dois blocos são marcados como simultâneos.");Layout.fillWidth:true;wrapMode:Text.Wrap;color:Theme.muted}
                RowLayout {
                    SelectField {id:kind;model:[Tr.tr("Diálogo"),Tr.tr("Música"),Tr.tr("Placa")];Layout.preferredWidth:170}
                    CheckBox {id:simultaneous;text:Tr.tr("Fala simultânea confirmada");palette.windowText:Theme.text}
                    ActionButton {objectName:"fansubClassify";text:Tr.tr("Marcar seleção / atual");enabled:review.loaded && !Backend.busy;onClicked:fansub.classify(["dialogue","music","sign"][kind.currentIndex],simultaneous.checked)}
                }
                Text {text:Tr.format("{count} blocos selecionados. Sem seleção, usa o bloco atual.",{count:review.selectedCount});color:Theme.muted;font.pixelSize:11}
                ListView {
                    Layout.fillWidth:true;Layout.fillHeight:true;clip:true;spacing:6;model:fansub.cues;ScrollBar.vertical:ScrollBar {}
                    delegate: Rectangle {
                        required property var modelData
                        width:ListView.view.width-8;height:124;color:review.currentIndex===modelData.index ? Theme.optionHover : Theme.card;radius:8
                        RowLayout {anchors.fill:parent;anchors.margins:10
                            CheckBox {checked:modelData.checked;enabled:!Backend.busy;onToggled:review.toggle(modelData.index,checked)}
                            ColumnLayout {Layout.fillWidth:true
                                Text {textFormat:Text.PlainText;text:modelData.number+" · "+modelData.time+" · "+modelData.kindLabel+(modelData.simultaneous ? " · "+Tr.tr("Simultânea") : "");color:Theme.accent;Layout.fillWidth:true;elide:Text.ElideRight;font.pixelSize:11}
                                Text {textFormat:Text.PlainText;text:modelData.text;color:Theme.text;Layout.fillWidth:true;maximumLineCount:2;wrapMode:Text.Wrap;elide:Text.ElideRight}
                                Text {textFormat:Text.PlainText;text:modelData.reasonLabel+" · "+modelData.suggestionLabel;color:Theme.muted;font.pixelSize:11}
                            }
                            ColumnLayout {
                                ActionButton {text:Tr.tr("Selecionar bloco");implicitHeight:32;onClicked:review.select(modelData.index)}
                                ActionButton {text:Tr.tr("Confirmar sugestão");implicitHeight:32;enabled:!Backend.busy && modelData.reason.length>0;onClicked:fansub.acceptSuggestion(modelData.index)}
                            }
                        }
                    }
                }
                ActionButton {text:Tr.tr("Salvar cópia");enabled:review.loaded && !Backend.busy;onClicked:review.save()}
            }
            ScrollView {
                clip:true;contentWidth:availableWidth
                ColumnLayout {
                    width:parent.width;spacing:10
                    Text {text:Tr.tr("SRT/VTT recebem o padrão abaixo. ASS existente conserva estilos, posições, desenhos e fontes originais. Músicas e placas confirmadas usam estilos próprios; eventos simultâneos continuam separados.");Layout.fillWidth:true;wrapMode:Text.Wrap;color:Theme.muted}
                    RowLayout {
                        SelectField {id:projectSelect;property var projects:[{id:"",name:Tr.tr("Padrões globais")}].concat(review.projects);model:projects.map(p=>p.name);selectedIndex:Math.max(0,projects.findIndex(p=>p.id===review.selectedProject));onActivated:review.setProject(projects[currentIndex].id);enabled:!Backend.busy}
                        SelectField {id:profile;model:fansub.profiles.map(p=>p.name);Layout.fillWidth:true}
                        ActionButton {text:Tr.tr("Carregar padrão");enabled:profile.currentIndex>=0 && !Backend.busy;onClicked:{fansub.loadProfile(profile.currentText);dialog.fillPreset()}}
                        ActionButton {text:Tr.tr("Remover");enabled:profile.currentIndex>=0 && !Backend.busy;onClicked:fansub.removeProfile(profile.currentText)}
                    }
                    RowLayout {
                        TextField {id:profileName;objectName:"exportProfileName";placeholderText:Tr.tr("Nome do padrão");color:Theme.text;Layout.fillWidth:true;padding:10;background:Rectangle {color:Theme.card;border.color:Theme.line;radius:6}}
                        ActionButton {objectName:"exportSavePreset";text:Tr.tr("Salvar padrão");enabled:!Backend.busy;onClicked:{if(dialog.settings())fansub.saveProfile(profileName.text)}}
                    }
                    GridLayout {
                        columns:4;columnSpacing:12;rowSpacing:8;Layout.fillWidth:true
                        Text {text:Tr.tr("Família da fonte");color:Theme.text}
                        TextField {id:fontInput;objectName:"exportFont";color:Theme.text;padding:9;Layout.preferredWidth:200;background:Rectangle {color:Theme.card;border.color:Theme.line}}
                        Text {text:Tr.tr("Tamanho");color:Theme.text}
                        TextField {id:sizeInput;objectName:"exportSize";color:Theme.text;padding:9;Layout.preferredWidth:90;background:Rectangle {color:Theme.card;border.color:Theme.line}}
                        Text {text:Tr.tr("Cor #RRGGBB");color:Theme.text}
                        TextField {id:colorInput;color:Theme.text;padding:9;background:Rectangle {color:Theme.card;border.color:Theme.line}}
                        Text {text:Tr.tr("Cor do contorno");color:Theme.text}
                        TextField {id:outlineColor;color:Theme.text;padding:9;Layout.preferredWidth:120;background:Rectangle {color:Theme.card;border.color:Theme.line}}
                        Text {text:Tr.tr("Contorno");color:Theme.text}
                        TextField {id:outlineInput;color:Theme.text;padding:9;background:Rectangle {color:Theme.card;border.color:Theme.line}}
                        Text {text:Tr.tr("Sombra");color:Theme.text}
                        TextField {id:shadowInput;color:Theme.text;padding:9;Layout.preferredWidth:90;background:Rectangle {color:Theme.card;border.color:Theme.line}}
                        Text {text:Tr.tr("Margem");color:Theme.text}
                        TextField {id:marginInput;color:Theme.text;padding:9;background:Rectangle {color:Theme.card;border.color:Theme.line}}
                        Text {text:Tr.tr("Posição do diálogo");color:Theme.text}
                        SelectField {id:alignment;model:[Tr.tr("Inferior"),Tr.tr("Superior")];Layout.preferredWidth:160}
                        Text {text:Tr.tr("Resolução ASS");color:Theme.text}
                        TextField {id:widthInput;color:Theme.text;padding:9;background:Rectangle {color:Theme.card;border.color:Theme.line}}
                        Text {text:"×";color:Theme.text}
                        TextField {id:heightInput;color:Theme.text;padding:9;Layout.preferredWidth:90;background:Rectangle {color:Theme.card;border.color:Theme.line}}
                    }
                    Flow {
                        Layout.fillWidth:true;spacing:6
                        ActionButton {objectName:"fansubExport";text:Tr.tr("Exportar cópia ASS");primary:true;enabled:review.loaded && !Backend.busy;onClicked:{if(dialog.settings())fansub.exportAss()}}
                        ActionButton {objectName:"fansubRender";text:Tr.tr("Renderizar prévia no vídeo");enabled:review.loaded && review.videoPath.length>0 && !Backend.busy;onClicked:{if(dialog.settings())fansub.previewAss()}}
                        ActionButton {text:Tr.tr("Reproduzir prévia");enabled:fansub.previewVideo.length>0 && !Backend.busy;onClicked:fansub.playPreview()}
                    }
                    Text {text:Tr.tr("As fontes precisam existir no computador; uma fonte ausente pode ser substituída pelo renderizador. A prévia usa o bloco atual e a faixa de áudio da revisão.");Layout.fillWidth:true;wrapMode:Text.Wrap;color:Theme.muted;font.pixelSize:11}
                    Image {source:fansub.previewImage;cache:false;Layout.fillWidth:true;Layout.preferredHeight:180;fillMode:Image.PreserveAspectFit;visible:source.toString().length>0}
                }
            }
            ColumnLayout {
                Text {text:Tr.tr("Analisa nomes e ordena a fila sem mover ou renomear arquivos. Possíveis duplicados são candidatos pelo episódio e extensão, não uma prova de conteúdo idêntico.");Layout.fillWidth:true;wrapMode:Text.Wrap;color:Theme.muted}
                RowLayout {
                    Text {text:Tr.tr("Último episódio (0 = até o maior encontrado)");color:Theme.text}
                    TextField {id:lastEpisode;text:"0";color:Theme.text;padding:9;Layout.preferredWidth:70;validator:IntValidator {bottom:0;top:500} background:Rectangle {color:Theme.card;border.color:Theme.line}}
                    ActionButton {text:Tr.tr("Escolher pasta");enabled:!Backend.busy && lastEpisode.acceptableInput;onClicked:fansub.chooseSeason(Number(lastEpisode.text))}
                    ActionButton {objectName:"fansubSortQueue";text:Tr.tr("Ordenar pendentes");enabled:!Backend.busy;onClicked:fansub.sortQueue()}
                }
                Text {textFormat:Text.PlainText;text:Tr.tr("Possíveis ausentes")+": "+(fansub.organization.missing.map(v=>(v.season===null ? "" : "S"+v.season+"E")+v.episode).join(", ") || "—");color:Theme.accent;Layout.fillWidth:true;maximumLineCount:3;wrapMode:Text.Wrap;elide:Text.ElideRight}
                ListView {
                    Layout.fillWidth:true;Layout.fillHeight:true;clip:true;spacing:5;model:fansub.organization.rows;ScrollBar.vertical:ScrollBar {}
                    delegate: Rectangle {
                        required property var modelData
                        width:ListView.view.width-8;height:62;color:Theme.card;radius:6
                        ColumnLayout {anchors.fill:parent;anchors.margins:9
                            Text {textFormat:Text.PlainText;text:modelData.file;color:Theme.text;Layout.fillWidth:true;elide:Text.ElideMiddle}
                            Text {textFormat:Text.PlainText;text:modelData.duplicate ? Tr.tr("Possível duplicado / outra versão") : modelData.kind==="special" ? Tr.tr("Especial / abertura / encerramento") : modelData.kind==="range" ? Tr.tr("Faixa de episódios: conferir manualmente") : modelData.episode===null ? Tr.tr("Numeração não reconhecida") : Tr.format("Episódio {number}",{number:modelData.episode});color:Theme.muted;font.pixelSize:11}
                        }
                    }
                }
                ActionButton {text:Tr.tr("Adicionar todos na ordem exibida");enabled:!Backend.busy && fansub.organization.rows.length>0;onClicked:fansub.addOrganized()}
            }
            ScrollView {
                clip:true;contentWidth:availableWidth
                ColumnLayout {
                    width:parent.width;spacing:14
                    Text {text:Tr.tr("Estimativas usam pelo menos dois episódios concluídos com operação, formato, modelos e configurações compatíveis. O progresso entre etapas não é linear; trate os valores como aproximações.");color:Theme.muted;Layout.fillWidth:true;wrapMode:Text.Wrap}
                    Text {text:fansub.queueStats.pending===0 ? Tr.tr("Fila sem itens pendentes") : fansub.queueStats.seconds===null ? Tr.tr("Tempo restante: aguardando histórico compatível") : Tr.format("Tempo restante estimado: {minutes} min",{minutes:Math.max(1,Math.round(fansub.queueStats.seconds/60))});color:Theme.text;font.pixelSize:18}
                    Text {text:Tr.format("{count} itens sem histórico suficiente",{count:fansub.queueStats.unknown});color:Theme.muted}
                    Text {text:fansub.queueStats.episodesPerHour===null ? Tr.tr("Velocidade: indisponível") : Tr.format("Velocidade histórica: {rate} episódios/h",{rate:fansub.queueStats.episodesPerHour});color:Theme.text}
                    Text {text:fansub.queueStats.outputBytes===null ? Tr.tr("Espaço de saída: aguardando histórico compatível") : Tr.format("Saídas estimadas: {size} MB",{size:Math.ceil(fansub.queueStats.outputBytes/1048576)});color:Theme.text}
                    Text {text:Tr.tr("Espaço livre por destino (temporários e modelos não entram na estimativa)");color:Theme.muted;Layout.fillWidth:true;wrapMode:Text.Wrap}
                    Repeater {model:fansub.queueStats.disks
                        Text {required property var modelData;textFormat:Text.PlainText;text:modelData.path+" · "+(modelData.freeBytes/1073741824).toFixed(1)+" GB";color:Theme.text;Layout.fillWidth:true;elide:Text.ElideMiddle}
                    }
                    Text {text:Tr.tr("ATALHOS NA REVISÃO");color:Theme.accent;font.pixelSize:13}
                    Text {text:Tr.tr("Ctrl+S — salvar cópia\nAlt+↑ / Alt+↓ — bloco anterior / próximo\nCtrl+Enter — aprovar e avançar\nAlt+P — reproduzir trecho\nAlt+B — reproduzir começando cinco segundos antes");color:Theme.text;Layout.fillWidth:true;wrapMode:Text.Wrap}
                }
            }
        }
    }
}
