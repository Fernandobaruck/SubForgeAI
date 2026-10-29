import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
Rectangle {
    id: box
    color: Theme.card; radius: 12; border.color: Theme.line
    implicitHeight: Math.max(210, Math.min(470, 74 + Backend.items.length*85))
    FansubDialog {id:fansubDialog;section:2}
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 18; spacing: 14
        RowLayout {
            Layout.fillWidth: true
            Text { text: Tr.tr("FILA DE EPISÓDIOS"); color: Theme.text; font.family: Theme.display; font.pixelSize: 16; font.letterSpacing: 1.1; Layout.fillWidth: true }
            Text { text: Tr.format("{done} / {total} concluídos", {done: Backend.completed, total: Backend.items.length}); color: Theme.muted; font.pixelSize: 12 }
            ActionButton {objectName:"fansubOpenQueue";text:Tr.tr("Organizar / estimar");implicitHeight:32;onClicked:fansubDialog.open()}
            ActionButton { text: Tr.tr("Limpar concluídos"); enabled: Backend.completed > 0; implicitHeight: 32; onClicked: Backend.clearFinished() }
        }
        Text {
            Layout.fillWidth:true;color:Theme.muted;font.pixelSize:11;elide:Text.ElideRight
            objectName: "queueEstimate"
            property var stats:Backend.review.fansub.queueStats
            text:stats.pending===0 ? Tr.tr("Fila sem itens pendentes") : typeof stats.seconds !== "number" || !isFinite(stats.seconds) ? Tr.tr("Estimativa da fila: aguardando histórico compatível") : Tr.format("Estimativa: {minutes} min · {unknown} itens sem histórico",{minutes:Math.max(1,Math.round(stats.seconds/60)),unknown:stats.unknown})
        }
        Item {
            Layout.fillWidth: true; Layout.fillHeight: true
            Column {
                anchors.centerIn: parent; spacing: 8; visible: Backend.items.length === 0
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: Tr.tr("Sua próxima temporada começa aqui"); color: Theme.text; font.family: Theme.font; font.pixelSize: 16 }
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: Tr.tr("Adicione vídeos, áudios ou legendas. Você também pode arrastar arquivos."); color: Theme.muted; font.pixelSize: 12 }
            }
            ListView {
                id: episodeList
                objectName: "episodeQueueList"
                anchors.fill: parent; clip: true; spacing: 8; model: Backend.queueModel
                ScrollBar.vertical: ScrollBar { policy: episodeList.contentHeight > episodeList.height ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff; minimumSize: 0.08 }
                delegate: Rectangle {
                    required property var modelData
                    width: ListView.view.width-12; height: 78; radius: 8; color: Theme.queueBg
                    RowLayout {
                        anchors.fill: parent; anchors.margins: 12; spacing: 14
                        Rectangle {
                            width: 33; height: 33; radius: 8; color: Theme.elevated
                            Text { anchors.centerIn: parent; text: modelData.type === "Legenda" ? "CC" : "AV"; color: Theme.muted; font.pixelSize: 10; font.bold: true }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 5
                            Text { Layout.fillWidth: true; text: modelData.name; color: Theme.text; font.pixelSize: 13; elide: Text.ElideMiddle; ToolTip.visible: titleHover.containsMouse; ToolTip.text: modelData.path; MouseArea { id: titleHover; anchors.fill: parent; hoverEnabled: true } }
                            Text { Layout.fillWidth: true; text: modelData.errorLabel || modelData.stageLabel; color: modelData.state === "Erro" ? Theme.red : Theme.muted; font.pixelSize: 11; elide: Text.ElideRight; ToolTip.visible: stageHover.containsMouse; ToolTip.text: modelData.errorLabel || modelData.stageLabel; MouseArea { id: stageHover; anchors.fill: parent; hoverEnabled: true } }
                            Rectangle {
                                visible: modelData.state === "Executando"; Layout.fillWidth: true; height: 3; radius: 2; color: Theme.line
                                Rectangle { width: parent.width * modelData.progress; height: 3; radius: 2; color: Theme.accent; Behavior on width { NumberAnimation { duration: 180 } } }
                            }
                        }
                        Text { text: modelData.stateLabel; color: modelData.state === "Concluído" ? Theme.green : modelData.state === "Erro" ? Theme.red : modelData.state === "Executando" ? Theme.accent : Theme.muted; font.pixelSize: 12; Layout.preferredWidth: 100 }
                        ActionButton { text: Tr.tr("Fonte"); implicitWidth: 68; implicitHeight: 30; enabled: modelData.removable && !Backend.busy; onClicked: Backend.review.inspectInput(modelData.id) }
                        ActionButton { text: Tr.tr("Reenfileirar"); visible: modelData.state === "Concluído"; implicitWidth: 105; implicitHeight: 30; onClicked: Backend.requeueItem(modelData.id) }
                        ToolButton {
                            text: "×"; enabled: modelData.removable; implicitWidth: 28; implicitHeight: 30
                            contentItem: Text { text: parent.text; color: Theme.muted; font.pixelSize: 21; horizontalAlignment: Text.AlignHCenter }
                            Accessible.name: Tr.format("Remover {name}", {name: modelData.name})
                            onClicked: Backend.removeItem(modelData.id)
                        }
                    }
                }
            }
        }
        Text { Layout.fillWidth: true; text: Tr.format("{total} arquivo(s) · {pending} aguardando", {total: Backend.items.length, pending: Backend.pendingCount}) + (episodeList.contentHeight > episodeList.height ? " · " + Tr.tr("Role a lista para ver os demais") : ""); color: Theme.muted; font.pixelSize: 11 }
    }
}
