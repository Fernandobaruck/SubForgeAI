import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
Dialog {
    id: dialog
    title: Tr.tr("Preparar para começar")
    modal: true; anchors.centerIn: parent; width: Math.min(720, parent.width - 40)
    standardButtons: Dialog.Close
    onOpened: Backend.setup.refresh()
    contentItem: ColumnLayout {
        spacing: 14
        Text { text: Tr.tr("1. Prepare os modelos. 2. Adicione um episódio ou legenda. 3. Inicie pela fila e confira em Resultados."); color: Theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Text { text: Tr.tr("Os downloads usam internet e ficam nesta pasta. Depois, os modelos instalados podem ser usados offline. Tradução: cerca de 8,1 GB. Whisper Turbo: cerca de 1,6 GB; Large v3: cerca de 3,1 GB."); color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Text { text: Tr.tr("Componentes do aplicativo") + ": " + (Backend.setup.state.missing.length ? Backend.setup.state.missing.join(", ") : Tr.tr("Disponíveis")); textFormat: Text.PlainText; color: Backend.setup.state.missing.length ? Theme.accent : Theme.green; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Repeater {
            model: [{name:"TranslateGemma 12B", code:"translation", ready:Backend.setup.state.translation}, {name:"Whisper Large v3 Turbo", code:"large-v3-turbo", ready:Backend.setup.state.whisper["large-v3-turbo"]}, {name:"Whisper Large v3", code:"large-v3", ready:Backend.setup.state.whisper["large-v3"]}]
            delegate: RowLayout {
                required property var modelData
                Layout.fillWidth: true
                Text { text: modelData.name; color: Theme.text; Layout.fillWidth: true }
                ActionButton { text: modelData.ready ? Tr.tr("Disponível") : Tr.tr("Baixar modelo"); enabled: !modelData.ready && !Backend.busy && !Backend.setup.state.missing.length; onClicked: Backend.setup.prepare(modelData.code) }
            }
        }
        ProgressBar { from: 0; to: 1; value: Backend.setup.progress; visible: Backend.busy || Backend.setup.progress > 0; indeterminate: Backend.busy && Backend.setup.progress === 0; Layout.fillWidth: true }
        Text { text: Backend.setup.status; color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Text { text: Tr.tr("Você pode começar traduzindo uma legenda em inglês: basta o TranslateGemma. Para trabalhar com áudio, baixe também um Whisper. Revise as traduções antes de publicar."); color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
        ActionButton { text: Tr.tr("Interromper"); enabled: Backend.busy; onClicked: Backend.stop() }
    }
}
