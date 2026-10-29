import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
Dialog {
    id: dialog; objectName: "onlineGlossaryDialog"
    modal: true; anchors.centerIn: Overlay.overlay
    width: Math.min(1040, Overlay.overlay.width-32); height: Math.min(760, Overlay.overlay.height-32)
    padding: 18
    property var online: Backend.review.online
    property int section: 0
    property string aiLanguageCode: "en"
    property string projectId: Backend.review.selectedProject
    onProjectIdChanged: { if (aiSource) aiSource.clear(); if (aiTarget) aiTarget.clear() }
    background: Rectangle { color: Theme.bg; radius: 12; border.color: Theme.line }
    contentItem: ColumnLayout {
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Text { text: Tr.tr("Glossário online"); color: Theme.text; font.pixelSize: 22; Layout.fillWidth: true }
            ActionButton { text: Tr.tr("Fechar"); onClicked: dialog.close() }
        }
        Text { text: Tr.tr("Anime selecionado")+": "+((Backend.review.projects.find(p=>p.id===dialog.projectId)||{}).name || Tr.tr("Escolha um anime")); textFormat: Text.PlainText; color: Theme.accent; elide: Text.ElideRight; Layout.fillWidth: true }
        Text { text: Tr.tr("Consultas são opcionais. Não há envio automático de arquivos ou glossários. Termos baixados exigem revisão e confirmação antes de entrar na tradução."); color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
        RowLayout {
            ActionButton { text: Tr.tr("Catálogo"); primary: dialog.section===0; onClicked: dialog.section=0 }
            ActionButton { text: Tr.tr("Contribuir"); primary: dialog.section===1; onClicked: dialog.section=1 }
            ActionButton { text: Tr.tr("IA local"); primary: dialog.section===2; onClicked: dialog.section=2 }
            ActionButton { text: Tr.tr("Histórico"); primary: dialog.section===3; onClicked: {dialog.section=3;online.localHistory()} }
        }
        Text { visible: !Backend.review.selectedProject.length; text: Tr.tr("Selecione ou crie um anime na aba Animes antes de importar ou sugerir termos."); color: Theme.accent; Layout.fillWidth: true; wrapMode: Text.Wrap }
        ColumnLayout {
            visible: dialog.section===0; Layout.fillWidth: true; Layout.fillHeight: true; spacing: 8
            RowLayout {
                TextField { objectName: "onlineGlossarySearch"; placeholderText: Tr.tr("Buscar anime ou coleção"); Layout.fillWidth: true; color: Theme.text; onTextChanged: online.search(text) }
                ActionButton { objectName: "onlineGlossaryRefresh"; text: Tr.tr("Atualizar catálogo"); enabled: !Backend.busy; onClicked: online.refresh() }
            }
            Text { text: online.status; textFormat: Text.PlainText; color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Text { visible: online.stamp.length>0; text: Tr.tr("Última consulta")+": "+online.stamp; color: Theme.muted; font.pixelSize: 10 }
            SplitView {
                Layout.fillWidth: true; Layout.fillHeight: true; orientation: Qt.Horizontal
                Rectangle {
                    SplitView.preferredWidth: 290; SplitView.minimumWidth: 220; color: Theme.card; radius: 8
                    ListView {
                        anchors.fill: parent; anchors.margins: 8; spacing: 8; clip: true; model: online.catalog; ScrollBar.vertical: ScrollBar {}
                        delegate: Rectangle {
                            required property var modelData
                            width: ListView.view.width; height: entry.implicitHeight+22; radius: 7; color: Theme.elevated
                            ColumnLayout { id: entry; anchors.fill: parent; anchors.margins: 11; spacing: 6
                                Text { text: modelData.title; textFormat: Text.PlainText; color: Theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                Text { text: modelData.description; textFormat: Text.PlainText; color: Theme.muted; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                Text { text: modelData.source_language+" → "+modelData.target_language+" · "+modelData.revision; color: Theme.accent; font.pixelSize: 10 }
                                ActionButton { text: Tr.tr("Conferir termos"); enabled: !Backend.busy && Backend.review.selectedProject.length>0; onClicked: online.load(modelData.id) }
                            }
                        }
                        Text { visible: !online.catalog.length; anchors.centerIn: parent; width: parent.width-16; text: Tr.tr("Atualize o catálogo para consultar as coleções disponíveis."); color: Theme.muted; wrapMode: Text.Wrap }
                    }
                }
                Rectangle {
                    SplitView.fillWidth: true; SplitView.minimumWidth: 350; color: Theme.card; radius: 8
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 10
                        Text { text: online.title || Tr.tr("Prévia dos termos"); textFormat: Text.PlainText; color: Theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        ListView {
                            Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 6; model: online.rows; ScrollBar.vertical: ScrollBar {}
                            delegate: RowLayout {
                                required property var modelData
                                width: ListView.view.width; spacing: 6
                                CheckBox { checked: modelData.checked; enabled: modelData.eligible && !Backend.busy; onToggled: online.select(modelData.index,checked) }
                                ColumnLayout { Layout.fillWidth: true; spacing: 3
                                    Text { text: modelData.source+" → "+modelData.target; textFormat: Text.PlainText; color: Theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    Text { text: modelData.label; textFormat: Text.PlainText; color: modelData.status==="conflict" ? Theme.accent : Theme.muted; font.pixelSize: 10; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    Text { visible: modelData.status==="conflict"; text: Tr.tr("Local")+": "+modelData.localTarget; textFormat: Text.PlainText; color: Theme.muted; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                }
                            }
                        }
                        Flow { Layout.fillWidth: true; spacing: 6
                            ActionButton { text: Tr.tr("Selecionar novos"); enabled: !Backend.busy; onClicked: online.selectNew() }
                            ActionButton { objectName: "onlineGlossaryImport"; text: Tr.tr("Importar sugestões")+" ("+online.selectedCount+")"; primary: true; enabled: !Backend.busy && online.selectedCount>0; onClicked: online.importSelected() }
                            ActionButton { text: Tr.tr("Versões online"); enabled: online.title.length>0; onClicked: online.remoteHistory() }
                        }
                    }
                }
            }
        }
        ColumnLayout {
            visible: dialog.section===1; Layout.fillWidth: true; Layout.fillHeight: true
            Text { text: Tr.tr("Marque somente os termos confirmados que deseja compartilhar. Confira a prévia abaixo. O navegador abrirá uma proposta pública; o envio depende da sua confirmação e conta no GitHub. Nada é publicado automaticamente."); color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            SelectField { model: [Tr.tr("Inglês"),Tr.tr("Japonês")]; selectedIndex: online.shareLanguage==="ja" ? 1 : 0; onActivated: online.setShareLanguage(currentIndex===0 ? "en" : "ja") }
            ListView { Layout.fillWidth: true; Layout.preferredHeight: 120; clip: true; model: online.shareRows; ScrollBar.vertical: ScrollBar {}
                delegate: RowLayout {
                    required property var modelData; width: ListView.view.width
                    CheckBox { checked: modelData.checked; onToggled: online.selectShare(modelData.source,checked) }
                    Text { text: modelData.source+" → "+modelData.target; textFormat: Text.PlainText; color: Theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                }
            }
            ScrollView { Layout.fillWidth: true; Layout.fillHeight: true
                TextArea { objectName: "onlineContributionPreview"; text: online.contribution; textFormat: TextEdit.PlainText; readOnly: true; selectByMouse: true; color: Theme.text; wrapMode: TextEdit.WrapAnywhere }
            }
            RowLayout {
                ActionButton { text: Tr.tr("Copiar proposta"); enabled: online.contribution.length>0; onClicked: online.copyContribution() }
                ActionButton { objectName: "onlineGlossaryContribute"; text: Tr.tr("Revisar proposta no GitHub"); enabled: online.contribution.length>0 && !Backend.busy; onClicked: online.contribute() }
            }
        }
        ColumnLayout {
            visible: dialog.section===2; Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
            Text { text: Tr.tr("A IA local sugere uma tradução, mas não verifica nomes oficiais ou o cânone do anime. Edite a proposta e salve como sugestão; confirme depois de revisar."); color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            SelectField { id: aiLanguage; model: [Tr.tr("Inglês"),Tr.tr("Japonês")]; selectedIndex: dialog.aiLanguageCode==="ja" ? 1 : 0; onActivated: dialog.aiLanguageCode=currentIndex===0 ? "en" : "ja"; enabled: !Backend.busy }
            TextField { id: aiSource; placeholderText: Tr.tr("Termo original"); Layout.fillWidth: true; color: Theme.text; maximumLength: 500; enabled: !Backend.busy }
            ActionButton { text: Tr.tr("Sugerir com TranslateGemma"); enabled: !Backend.busy && aiSource.text.trim().length>0 && Backend.review.selectedProject.length>0; onClicked: online.suggest(aiSource.text, dialog.aiLanguageCode) }
            TextField { id: aiTarget; placeholderText: Tr.tr("Tradução sugerida: confira e edite"); Layout.fillWidth: true; color: Theme.text; maximumLength: 500; enabled: !Backend.busy }
            Connections { target: online; function onSuggestionReady(value) { aiTarget.text=value } }
            ActionButton { text: Tr.tr("Salvar como sugestão local"); enabled: !Backend.busy && Backend.review.selectedProject.length>0 && aiSource.text.trim().length>0 && aiTarget.text.trim().length>0; onClicked: online.saveSuggestion(aiSource.text,aiTarget.text) }
            Item { Layout.fillHeight: true }
        }
        ColumnLayout {
            visible: dialog.section===3; Layout.fillWidth: true; Layout.fillHeight: true
            Text { text: Tr.tr("Últimas dez versões locais do glossário. Importações preservam os termos anteriores. Para resolver conflitos, edite o termo na aba Animes."); color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            ScrollView { Layout.fillWidth: true; Layout.fillHeight: true
                TextArea { text: online.historyText || Tr.tr("Nenhuma versão anterior disponível."); textFormat: TextEdit.PlainText; readOnly: true; selectByMouse: true; color: Theme.text; wrapMode: TextEdit.WrapAnywhere }
            }
        }
        RowLayout {
            visible: Backend.busy; Layout.fillWidth: true
            Text { text: Backend.review.job; color: Theme.muted; Layout.fillWidth: true }
            ActionButton { text: Tr.tr("Interromper"); onClicked: Backend.stop() }
        }
    }
}
