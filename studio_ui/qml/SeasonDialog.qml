import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
Dialog {
    id: dialog
    objectName: "seasonDialog"
    property var season: Backend.review.season
    property int section: 0
    property string styleProject: Backend.review.selectedProject
    function loadStyle() {
        var value=season.style
        honor.currentIndex=value.honorifics==="adapt" ? 1 : 0
        register.currentIndex=["source","formal","casual"].indexOf(value.register)
        profanity.currentIndex=value.profanity==="soften" ? 1 : 0
        notes.currentIndex=value.notes==="preserve" ? 1 : 0
        widthInput.text=String(value.line_width)
        cpsInput.text=String(value.max_cps)
    }
    onStyleProjectChanged: Qt.callLater(loadStyle)
    onOpened: loadStyle()
    modal: true; anchors.centerIn: Overlay.overlay
    width: Math.min(1040, Overlay.overlay.width-32); height: Math.min(760, Overlay.overlay.height-32); padding: 18
    background: Rectangle { color: Theme.bg; radius: 12; border.color: Theme.line }
    contentItem: ColumnLayout {
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Text { text: Tr.tr("Consistência da temporada"); color: Theme.text; font.pixelSize: 20; Layout.fillWidth: true }
            ActionButton { text: Tr.tr("Fechar"); onClicked: dialog.close() }
        }
        Flow {
            Layout.fillWidth: true; spacing: 6
            ActionButton { text: Tr.tr("Resumo"); primary: dialog.section===0; onClicked: dialog.section=0 }
            ActionButton { text: Tr.tr("Busca"); primary: dialog.section===1; onClicked: dialog.section=1 }
            ActionButton { text: Tr.tr("Correções"); primary: dialog.section===2; onClicked: dialog.section=2 }
            ActionButton { text: Tr.tr("Guia de estilo"); primary: dialog.section===3; onClicked: dialog.section=3 }
            ActionButton { text: Tr.tr("Sincronização"); primary: dialog.section===4; onClicked: dialog.section=4 }
        }
        RowLayout {
            Layout.fillWidth: true; visible: dialog.section<3
            ActionButton { objectName: "seasonChooseFolder"; text: Tr.tr("Pasta de legendas"); enabled: !Backend.busy; onClicked: season.chooseFolder() }
            ActionButton { text: Tr.tr("Carregar anime"); enabled: !Backend.busy && Backend.review.selectedProject.length>0; onClicked: season.loadProject() }
            Text { textFormat: Text.PlainText; text: season.folder; color: Theme.muted; Layout.fillWidth: true; elide: Text.ElideMiddle }
        }
        Text { textFormat: Text.PlainText; text: season.issues; visible: text.length>0; color: Theme.accent; Layout.fillWidth: true; maximumLineCount: 3; wrapMode: Text.Wrap; elide: Text.ElideRight }
        StackLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; currentIndex: dialog.section
            ColumnLayout {
                Text { text: Tr.tr("RESUMO DO EPISÓDIO ABERTO"); color: Theme.accent; font.pixelSize: 11 }
                Text { textFormat: Text.PlainText; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.text
                    text: Backend.review.loaded ? Tr.format("{total} blocos · {pending} pendentes · {fast} rápidos · {long} com linhas longas · máximo {cps} caracteres/s",{total:season.currentSummary.total,pending:season.currentSummary.pending,fast:season.currentSummary.fast,long:season.currentSummary.long,cps:season.currentSummary.maxCps}) : Tr.tr("Nenhuma revisão aberta")
                }
                Text { text: Tr.tr("EPISÓDIOS DA PASTA / ANIME"); color: Theme.accent; font.pixelSize: 11 }
                Text { text: Tr.tr("Tempos anteriores à atualização podem não estar disponíveis. A preparação em lote é registrada separadamente."); color: Theme.muted; Layout.fillWidth: true; wrapMode: Text.Wrap; font.pixelSize: 11 }
                ListView {
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 7; model: season.summaries; ScrollBar.vertical: ScrollBar {}
                    delegate: Rectangle {
                        required property var modelData
                        width: ListView.view.width-8; height: 116; color: Theme.card; radius: 7
                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 10; spacing: 3
                            Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: modelData.file; color: Theme.text; elide: Text.ElideMiddle }
                            Text { textFormat: Text.PlainText; Layout.fillWidth: true; color: Theme.muted; font.pixelSize: 11; elide: Text.ElideRight
                                text: Tr.format("{total} blocos · {pending} pendentes · fonte: {source} · tempo: {seconds}",{total:modelData.total,pending:modelData.pending,source:modelData.sourceLabel,seconds:modelData.seconds===undefined || modelData.seconds===null ? "—" : modelData.seconds+" s"})
                            }
                            Text { textFormat: Text.PlainText; Layout.fillWidth: true; color: Theme.muted; font.pixelSize: 11; elide: Text.ElideRight
                                text: Tr.format("{fast} rápidos · {long} com linhas longas · preparação do lote: {batch}",{fast:modelData.fast,long:modelData.long,batch:modelData.preparationSeconds===undefined || modelData.preparationSeconds===null ? "—" : modelData.preparationSeconds+" s"})
                            }
                            Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: modelData.error || (modelData.state ? Tr.tr(modelData.state) : Tr.tr("Sem falha registrada")); color: modelData.error ? Theme.accent : Theme.green; font.pixelSize: 11; elide: Text.ElideRight }
                        }
                    }
                }
            }
            ColumnLayout {
                RowLayout {
                    TextField { id: query; objectName: "seasonQuery"; Layout.fillWidth: true; placeholderText: Tr.tr("Buscar na origem e na tradução"); color: Theme.text; padding: 12; background: Rectangle {color:Theme.card;border.color:Theme.line;radius:7} onAccepted: season.search(text,searchCase.checked) }
                    CheckBox { id: searchCase; text: Tr.tr("Maiúsculas"); palette.windowText: Theme.text }
                    ActionButton { objectName: "seasonSearch"; text: Tr.tr("Buscar"); enabled: !Backend.busy; onClicked: season.search(query.text,searchCase.checked) }
                }
                Text { text: Tr.format("{count} resultados",{count:season.hits.length}); color: Theme.muted }
                ListView {
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 7; model: season.hits; ScrollBar.vertical: ScrollBar {}
                    delegate: Rectangle {
                        required property var modelData
                        width: ListView.view.width-8; height: 138; color: Theme.card; radius: 7
                        ColumnLayout { anchors.fill: parent; anchors.margins: 10
                            RowLayout {
                                Layout.fillWidth: true
                                Text { textFormat: Text.PlainText; text: modelData.file+" · "+modelData.number+" · "+modelData.time; color: Theme.accent; Layout.fillWidth: true; elide: Text.ElideMiddle; font.pixelSize: 11 }
                                ActionButton { text: Tr.tr("Revisar"); implicitHeight: 30; enabled: !Backend.busy; onClicked: {season.openHit(modelData.path,modelData.index);dialog.close()} }
                            }
                            Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: modelData.source || Tr.tr("Origem não associada"); color: Theme.muted; maximumLineCount: 2; wrapMode: Text.Wrap; elide: Text.ElideRight }
                            Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: modelData.text; color: Theme.text; maximumLineCount: 2; wrapMode: Text.Wrap; elide: Text.ElideRight }
                        }
                    }
                }
            }
            ColumnLayout {
                RowLayout {
                    Layout.fillWidth: true
                    TextField { id: oldTerm; objectName: "seasonOld"; Layout.fillWidth: true; placeholderText: Tr.tr("Texto atual"); color: Theme.text; padding: 12; background: Rectangle {color:Theme.card;border.color:Theme.line;radius:7} }
                    TextField { id: newTerm; objectName: "seasonNew"; Layout.fillWidth: true; placeholderText: Tr.tr("Texto corrigido"); color: Theme.text; padding: 12; background: Rectangle {color:Theme.card;border.color:Theme.line;radius:7} }
                    ActionButton { objectName: "seasonPreviewReplace"; text: Tr.tr("Gerar prévia"); enabled: !Backend.busy; onClicked: season.previewReplace(oldTerm.text,newTerm.text,replaceCase.checked,whole.checked) }
                }
                RowLayout {
                    CheckBox { id: replaceCase; text: Tr.tr("Maiúsculas"); checked: true; palette.windowText: Theme.text }
                    CheckBox { id: whole; text: Tr.tr("Termo inteiro"); checked: true; palette.windowText: Theme.text }
                    ActionButton { objectName: "seasonWrap"; text: Tr.tr("Prévia de quebras de linha"); enabled: Backend.review.loaded && !Backend.busy; onClicked: season.previewWrap() }
                }
                Text { text: Tr.tr("Quebras usam a legenda aberta. Propagação usa a pasta carregada. Confira cada contexto; blocos alterados perdem a aprovação."); Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: 11 }
                RowLayout {
                    ActionButton { text: Tr.tr("Selecionar todos"); enabled: !Backend.busy; onClicked: season.checkAll(true) }
                    ActionButton { text: Tr.tr("Desmarcar"); enabled: !Backend.busy; onClicked: season.checkAll(false) }
                    ActionButton { objectName: "seasonApply"; text: Tr.format("Aplicar {count} selecionados",{count:season.selectedCount}); primary: true; enabled: season.previewKind!=="sync" && season.selectedCount>0 && !Backend.busy; onClicked: season.apply() }
                }
                ListView {
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 7; model: season.previewKind==="sync" ? [] : season.preview; ScrollBar.vertical: ScrollBar {}
                    delegate: Rectangle {
                        required property var modelData; required property int index
                        width: ListView.view.width-8; height: 148; color: Theme.card; radius: 7
                        RowLayout { anchors.fill: parent; anchors.margins: 8
                            CheckBox { checked: modelData.checked; enabled: !Backend.busy; onToggled: season.check(index,checked) }
                            ColumnLayout {
                                Layout.fillWidth: true
                                Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: modelData.file+" · "+modelData.number; color: Theme.accent; elide: Text.ElideMiddle; font.pixelSize: 11 }
                                Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: modelData.before; color: Theme.muted; maximumLineCount: 3; wrapMode: Text.Wrap; elide: Text.ElideRight }
                                Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: modelData.after; color: Theme.text; maximumLineCount: 3; wrapMode: Text.Wrap; elide: Text.ElideRight }
                            }
                        }
                    }
                }
            }
            ScrollView {
                clip: true; contentWidth: availableWidth
                ColumnLayout {
                    width: parent.width; spacing: 12
                    Text { text: Tr.tr("Selecione o anime na aba Animes. O guia vale para novas traduções e retraduções; não modifica resultados existentes."); color: Theme.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    SelectField {
                        property var projects: [{id:"",name:Tr.tr("Escolha um anime")}].concat(Backend.review.projects)
                        model: projects.map(p=>p.name); selectedIndex: Math.max(0,projects.findIndex(p=>p.id===Backend.review.selectedProject)); enabled: !Backend.busy
                        onActivated: Backend.review.setProject(projects[currentIndex].id)
                    }
                    Text { text: Tr.tr("Honoríficos"); color: Theme.text }
                    SelectField { id: honor; model: [Tr.tr("Preservar existentes"),Tr.tr("Adaptar naturalmente")]; selectedIndex: season.style.honorifics==="adapt" ? 1 : 0 }
                    Text { text: Tr.tr("Formalidade"); color: Theme.text }
                    SelectField { id: register; model: [Tr.tr("Seguir personagem"),Tr.tr("Preferir formal"),Tr.tr("Preferir coloquial")]; selectedIndex: ["source","formal","casual"].indexOf(season.style.register) }
                    Text { text: Tr.tr("Palavrões"); color: Theme.text }
                    SelectField { id: profanity; model: [Tr.tr("Preservar intensidade"),Tr.tr("Suavizar")]; selectedIndex: season.style.profanity==="soften" ? 1 : 0 }
                    Text { text: Tr.tr("Notas do tradutor"); color: Theme.text }
                    SelectField { id: notes; model: [Tr.tr("Não acrescentar notas"),Tr.tr("Preservar notas existentes")]; selectedIndex: season.style.notes==="preserve" ? 1 : 0 }
                    RowLayout {
                        Text { text: Tr.tr("Caracteres por linha (24–60)"); color: Theme.text }
                        TextField { id: widthInput; objectName: "styleWidth"; text: String(season.style.line_width); validator: IntValidator {bottom:24;top:60}
                            color: Theme.text; background: Rectangle {color:Theme.card;border.color:Theme.line} padding: 10; Layout.preferredWidth: 70 }
                        Text { text: Tr.tr("Caracteres/s (10–30)"); color: Theme.text }
                        TextField { id: cpsInput; text: String(season.style.max_cps); validator: IntValidator {bottom:10;top:30}
                            color: Theme.text; background: Rectangle {color:Theme.card;border.color:Theme.line} padding: 10; Layout.preferredWidth: 70 }
                    }
                    ActionButton { objectName: "seasonSaveStyle"; text: Tr.tr("Salvar guia de estilo"); primary: true; enabled: Backend.review.selectedProject.length>0 && !Backend.busy && widthInput.acceptableInput && cpsInput.acceptableInput
                        onClicked: season.saveStyle({honorifics:["preserve","adapt"][honor.currentIndex],register:["source","formal","casual"][register.currentIndex],profanity:["source","soften"][profanity.currentIndex],notes:["none","preserve"][notes.currentIndex],line_width:Number(widthInput.text),max_cps:Number(cpsInput.text)})
                    }
                }
            }
            ColumnLayout {
                Text { text: Tr.tr("Ajuste aplicado à legenda aberta: novo tempo = tempo atual × fator + atraso. Atraso positivo exibe mais tarde. Ex.: 25 → 23,976 fps usa fator 1,04271."); color: Theme.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                RowLayout {
                    Text { text: Tr.tr("Atraso (segundos)"); color: Theme.text }
                    TextField { id: offset; objectName: "syncOffset"; text: "0"; color: Theme.text; padding: 10; Layout.preferredWidth: 110; background: Rectangle {color:Theme.card;border.color:Theme.line} }
                    Text { text: Tr.tr("Fator (0,5–2)"); color: Theme.text }
                    TextField { id: scale; objectName: "syncScale"; text: "1"; color: Theme.text; padding: 10; Layout.preferredWidth: 110; background: Rectangle {color:Theme.card;border.color:Theme.line} }
                    ActionButton { objectName: "seasonSyncPreview"; text: Tr.tr("Gerar prévia"); enabled: Backend.review.loaded && !Backend.busy; onClicked: season.previewSync(Number(offset.text.replace(",",".")),Number(scale.text.replace(",","."))) }
                }
                Text { text: Tr.tr("A prévia mostra o primeiro e o último bloco. Aplicar altera o rascunho inteiro; salve a cópia e use o histórico para recuperar os tempos anteriores."); color: Theme.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                ListView {
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true; model: season.previewKind==="sync" ? season.preview : []; spacing: 10
                    delegate: ColumnLayout {
                        required property var modelData; width: ListView.view.width
                        Text { textFormat: Text.PlainText; text: Tr.format("Bloco {number}",{number:modelData.number})+" · "+modelData.before; color: Theme.muted }
                        Text { textFormat: Text.PlainText; text: Tr.tr("Novo intervalo (s)")+": "+modelData.after; color: Theme.text }
                    }
                }
                ActionButton { objectName: "seasonSyncApply"; text: Tr.tr("Aplicar sincronização ao rascunho"); primary: true; enabled: season.previewKind==="sync" && season.preview.length>0 && !Backend.busy; onClicked: season.applySync() }
            }
        }
    }
}

