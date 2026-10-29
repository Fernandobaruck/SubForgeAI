import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
ColumnLayout {
    id: page
    property var review: Backend.review
    property bool shortcutsReady: review.loaded && !Backend.busy && !fansubDialog.visible && !seasonDialog.visible && !historyDialog.visible && !Backend.maintenance.panelOpen
    property int lastShownIndex: -1
    Connections {
        target: review
        function onChanged() {
            if (review.loaded && page.lastShownIndex!==review.currentIndex) {
                page.lastShownIndex=review.currentIndex
                reviewList.positionViewAtIndex(review.currentIndex,ListView.Contain)
            }
        }
    }
    spacing: 10
    RowLayout {
        Layout.fillWidth: true; spacing: 6
        ActionButton { text: Tr.tr("Abrir legenda"); enabled: !Backend.busy; onClicked: review.chooseDocument() }
        ActionButton { objectName: "reviewSave"; text: Tr.tr("Salvar cópia"); primary: true; enabled: review.loaded && !Backend.busy; onClicked: review.save() }
        ActionButton { text: Tr.tr("Histórico"); enabled: review.loaded && !Backend.busy; onClicked: historyDialog.open() }
        Item { Layout.fillWidth: true }
        ActionButton { text: Tr.tr("Criar backup"); enabled: !Backend.busy; onClicked: review.createBackup() }
        ActionButton { text: Tr.tr("Restaurar backup"); enabled: !Backend.busy; onClicked: review.chooseRestoreBackup() }
    }
    RowLayout {
        Layout.fillWidth: true; spacing: 10
        ActionButton { objectName: "openSubtitleStyle"; text: Tr.tr("Estilo da legenda"); enabled: !Backend.busy; onClicked: {fansubDialog.section=1;fansubDialog.open()} }
        Text { text: Tr.tr("Fonte, contorno e exportação ASS"); color: Theme.muted; font.pixelSize: 11; Layout.fillWidth: true; elide: Text.ElideRight }
    }
    Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: review.loaded ? review.title + (review.dirty ? " *" : "") : Tr.tr("Abra uma legenda ou use Revisar na tela Resultados."); color: Theme.text; font.pixelSize: 13; elide: Text.ElideMiddle }
    RowLayout {
        Layout.fillWidth: true; visible: review.loaded
        Text { textFormat: Text.PlainText; text: Tr.tr("Anime da revisão"); color: Theme.muted; font.pixelSize: 12 }
        SelectField { property var projects: [{id:"",name:Tr.tr("Sem anime")}].concat(review.projects); model: projects.map(p=>p.name); selectedIndex: Math.max(0,projects.findIndex(p=>p.id===review.reviewProject)); enabled: !Backend.busy; implicitWidth: 230; onActivated: review.setReviewProject(projects[currentIndex].id) }
        Text { textFormat: Text.PlainText; text: review.summary; color: Theme.muted; font.pixelSize: 11; Layout.fillWidth: true; elide: Text.ElideRight }
    }
    RowLayout {
        Layout.fillWidth: true; visible: review.loaded
        ActionButton { text: Tr.tr("Associar original"); enabled: !Backend.busy; onClicked: review.chooseSource() }
        ActionButton { text: Tr.tr("Associar vídeo"); enabled: !Backend.busy; onClicked: review.chooseVideo() }
        ActionButton { text: Tr.tr("Ver trecho"); enabled: review.videoPath.length>0 && !Backend.busy; onClicked: review.playCurrent() }
        CheckBox { id: onlyIssues; text: Tr.tr("Só pendências"); palette.windowText: Theme.text }
        ActionButton { objectName: "seasonOpenReview"; text: Tr.tr("Temporada"); enabled: !Backend.busy; onClicked: {seasonDialog.section=0;seasonDialog.open()} }
        ActionButton {objectName:"fansubOpenReview";text:Tr.tr("Fansub");onClicked:fansubDialog.open()}
        Item { Layout.fillWidth: true }
    }
    FansubDialog {id:fansubDialog}
    SeasonDialog { id: seasonDialog }
    SplitView {
        Layout.fillWidth: true; Layout.fillHeight: true
        handle: Rectangle { implicitWidth: 8; color: Theme.bg }
        Rectangle {
            SplitView.preferredWidth: 285; SplitView.minimumWidth: 215; radius: 8; color: Theme.card; border.color: Theme.line
            ListView {
                id: reviewList; objectName: "reviewCueList"; anchors.fill: parent; anchors.margins: 6; spacing: 4; clip: true; model: review.model
                ScrollBar.vertical: ScrollBar {}
                delegate: Rectangle {
                    required property var modelData
                    property bool shown: !onlyIssues.checked || (modelData.flags.length>0 && !modelData.approved)
                    width: ListView.view.width-8; height: shown ? 92 : 0; visible: shown; radius: 6
                    color: review.currentIndex===modelData.index ? Theme.optionHover : Theme.queueBg
                    RowLayout {
                        anchors.fill: parent; anchors.margins: 8; spacing: 3
                        CheckBox { checked: modelData.checked; onToggled: review.toggle(modelData.index,checked); Accessible.name: Tr.format("Selecionar bloco {number}",{number:modelData.number}) }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 4
                            Text { textFormat: Text.PlainText; text: modelData.number + "  ·  " + modelData.time; color: Theme.muted; font.pixelSize: 10; Layout.fillWidth: true; elide: Text.ElideRight }
                            Text { textFormat: Text.PlainText; text: modelData.text; color: Theme.text; font.pixelSize: 11; Layout.fillWidth: true; maximumLineCount: 2; wrapMode: Text.Wrap; elide: Text.ElideRight }
                            Text { textFormat: Text.PlainText; text: modelData.approved ? Tr.tr("Aprovado") : modelData.flagText || Tr.tr("Sem alerta automático"); color: modelData.approved ? Theme.green : Theme.accent; font.pixelSize: 10; Layout.fillWidth: true; elide: Text.ElideRight }
                            MouseArea { anchors.fill: parent; onClicked: review.select(modelData.index); cursorShape: Qt.PointingHandCursor }
                        }
                    }
                }
            }
            Text { textFormat: Text.PlainText; anchors.centerIn: parent; visible: !review.loaded; text: Tr.tr("Nenhuma revisão aberta"); color: Theme.muted }
        }
        ScrollView {
            SplitView.fillWidth: true; SplitView.minimumWidth: 330; clip: true; contentWidth: availableWidth
            ColumnLayout {
                width: parent.width; spacing: 9
                Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: review.loaded ? Tr.format("Bloco {number}",{number:review.current.number}) + " · " + review.current.time : ""; color: Theme.accent; font.pixelSize: 12 }
                Text { textFormat: Text.PlainText; text: Tr.tr("ORIGINAL"); color: Theme.muted; font.pixelSize: 10; font.letterSpacing: 1 }
                Rectangle { Layout.fillWidth: true; height: 140; radius: 8; color: Theme.card; border.color: Theme.line
                    ScrollView { anchors.fill: parent; anchors.margins: 10; clip: true
                        TextArea { objectName: "reviewSourceText"; text: review.current.source; readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText; wrapMode: TextEdit.Wrap; color: Theme.text; font.pixelSize: 13; background: null }
                    }
                }
                Text { textFormat: Text.PlainText; Layout.fillWidth: true; visible: review.loaded && !review.current.sourceVerified; text: Tr.tr("Origem não verificada: associe a legenda original para retraduzir."); color: Theme.accent; font.pixelSize: 11; wrapMode: Text.WordWrap }
                Text { textFormat: Text.PlainText; text: Tr.tr("TEXTO EM REVISÃO"); color: Theme.muted; font.pixelSize: 10; font.letterSpacing: 1 }
                Rectangle { Layout.fillWidth: true; height: 165; radius: 8; color: Theme.card; border.color: edit.activeFocus ? Theme.accent : Theme.line
                    ScrollView { anchors.fill: parent; anchors.margins: 10; clip: true
                        TextArea { id: edit; objectName: "reviewTargetText"; text: review.current.text; enabled: review.loaded && !Backend.busy; selectByMouse: true; textFormat: TextEdit.PlainText; wrapMode: TextEdit.Wrap; color: Theme.text; font.pixelSize: 14; background: null
                            onTextChanged: if (activeFocus) review.editCurrent(text)
                        }
                    }
                }
                Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: review.current.flagText; color: Theme.accent; font.pixelSize: 11; wrapMode: Text.WordWrap }
                Flow {
                    Layout.fillWidth: true; spacing: 6
                    ActionButton { objectName: "reviewApprove"; text: Tr.tr("Aprovar bloco"); enabled: review.loaded && !Backend.busy; onClicked: review.approve() }
                    ActionButton { objectName: "reviewRetranslate"; text: Tr.tr("Retraduzir seleção"); enabled: review.loaded && !Backend.busy; onClicked: review.retranslateSelected() }
                    ActionButton { objectName: "reviewRemember"; text: Tr.tr("Memorizar correção"); enabled: review.current.approved && review.current.sourceVerified && review.reviewProject.length>0 && !Backend.busy; onClicked: review.rememberCurrent() }
                }
                Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: Tr.format("{count} blocos selecionados. Sem seleção, usa o bloco atual.",{count:review.selectedCount}); color: Theme.muted; font.pixelSize: 11; wrapMode: Text.WordWrap; visible: review.loaded }
                Rectangle {
                    Layout.fillWidth: true; implicitHeight: proposalColumn.implicitHeight+24; visible: review.current.proposal.length>0; radius: 8; color: Theme.successBg; border.color: Theme.successBorder
                    ColumnLayout { id: proposalColumn; anchors.fill: parent; anchors.margins: 12; spacing: 9
                        Text { textFormat: Text.PlainText; text: Tr.tr("SUGESTÃO PARA CONFERIR"); color: Theme.successText; font.pixelSize: 10 }
                        Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: review.current.proposal; color: Theme.text; font.pixelSize: 13; wrapMode: Text.Wrap }
                        ActionButton { text: Tr.tr("Aplicar sugestão"); enabled: !Backend.busy; onClicked: review.applyProposal() }
                    }
                }
                Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: Tr.tr("O salvamento cria uma cópia revisada e versões recuperáveis. O arquivo original é preservado."); color: Theme.muted; font.pixelSize: 11; wrapMode: Text.WordWrap }
            }
        }
    }
    Shortcut {context:Qt.ApplicationShortcut;sequence:"Alt+Up";enabled:page.shortcutsReady;onActivated:review.shortcut("previous")}
    Shortcut {context:Qt.ApplicationShortcut;sequence:"Alt+Down";enabled:page.shortcutsReady;onActivated:review.shortcut("next")}
    Shortcut {context:Qt.ApplicationShortcut;sequence:"Ctrl+Return";enabled:page.shortcutsReady;onActivated:review.shortcut("approve")}
    Shortcut {context:Qt.ApplicationShortcut;sequence:"Alt+P";enabled:page.shortcutsReady;onActivated:review.shortcut("play")}
    Shortcut {context:Qt.ApplicationShortcut;sequence:"Alt+B";enabled:page.shortcutsReady;onActivated:review.shortcut("back")}
    Shortcut { context:Qt.ApplicationShortcut;sequence: "Ctrl+S"; enabled: page.shortcutsReady; onActivated: review.shortcut("save") }
    Dialog {
        id: historyDialog; anchors.centerIn: Overlay.overlay; width: 560; height: 400; modal: true; padding: 20
        background: Rectangle { color: Theme.card; radius: 10; border.color: Theme.line }
        contentItem: ColumnLayout {
            Text { textFormat: Text.PlainText; text: Tr.tr("Histórico da revisão"); color: Theme.text; font.pixelSize: 18 }
            ListView {
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true; model: review.versions; spacing: 8
                delegate: RowLayout {
                    required property var modelData
                    width: ListView.view.width
                    Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: modelData.date + " · " + modelData.reasonLabel; color: Theme.text; elide: Text.ElideRight }
                    ActionButton { text: Tr.tr("Restaurar versão"); implicitHeight: 32; onClicked: {review.restoreVersion(modelData.id);historyDialog.close()} }
                }
            }
            Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: Tr.tr("Se o arquivo mudou em outro programa, salve uma nova cópia independente."); color: Theme.muted; font.pixelSize: 11; wrapMode: Text.WordWrap }
            RowLayout {
                ActionButton { text: Tr.tr("Salvar nova cópia"); onClicked: {if(review.saveIndependent())historyDialog.close()} }
                ActionButton { text: Tr.tr("Fechar"); onClicked: historyDialog.close() }
            }
        }
    }
}
