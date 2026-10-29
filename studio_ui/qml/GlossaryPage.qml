import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
ColumnLayout {
    property var review: Backend.review
    spacing: 12
    SeasonDialog { id: seasonDialog }
    OnlineGlossaryDialog { id: onlineDialog }
    ActionButton { objectName: "openOnlineGlossary"; text: Tr.tr("Glossário online e sugestões de IA"); enabled: !Backend.busy; onClicked: onlineDialog.open() }
    ActionButton { objectName: "seasonOpenAnime"; text: Tr.tr("Temporada e guia de estilo"); enabled: !Backend.busy; onClicked: {seasonDialog.section=3;seasonDialog.open()} }
    RowLayout {
        Layout.fillWidth: true
        SelectField { id: project; property var projects: [{id:"",name:Tr.tr("Escolha um anime")}].concat(review.projects); model: projects.map(p=>p.name); selectedIndex: Math.max(0,projects.findIndex(p=>p.id===review.selectedProject)); onActivated: review.setProject(projects[currentIndex].id); enabled: !Backend.busy; Layout.preferredWidth: 260 }
        TextField { id: newName; Layout.fillWidth: true; placeholderText: Tr.tr("Nome do novo anime"); enabled: !Backend.busy; color: Theme.text; padding: 12; background: Rectangle {radius:7;color:Theme.elevated;border.color:Theme.line} }
        ActionButton { text: Tr.tr("Criar anime"); enabled: newName.text.trim().length>0 && !Backend.busy; onClicked: {review.createProject(newName.text);newName.clear()} }
    }
    Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: Tr.tr("Termos confirmados são exigidos na tradução. Sugestões ficam separadas até sua aprovação."); color: Theme.muted; font.pixelSize: 12; wrapMode: Text.WordWrap }
    RowLayout {
        Layout.fillWidth: true
        TextField { id: original; Layout.fillWidth: true; placeholderText: Tr.tr("Termo original"); enabled: !Backend.busy; color: Theme.text; padding: 12; background: Rectangle {radius:7;color:Theme.elevated;border.color:Theme.line} }
        TextField { id: target; Layout.fillWidth: true; placeholderText: Tr.tr("Tradução ou grafia aprovada"); enabled: !Backend.busy; color: Theme.text; padding: 12; background: Rectangle {radius:7;color:Theme.elevated;border.color:Theme.line} }
        CheckBox { id: confirmed; text: Tr.tr("Confirmado"); palette.windowText: Theme.text; enabled: !Backend.busy }
        ActionButton { text: Tr.tr("Salvar termo"); primary: true; enabled: review.selectedProject.length>0 && !Backend.busy; onClicked: {review.saveTerm(original.text,target.text,confirmed.checked)} }
    }
    Rectangle {
        Layout.fillWidth: true; Layout.fillHeight: true; radius: 8; color: Theme.card; border.color: Theme.line
        ListView {
            anchors.fill: parent; anchors.margins: 10; spacing: 6; clip: true; model: review.terms; ScrollBar.vertical: ScrollBar {}
            delegate: Rectangle {
                required property var modelData
                width: ListView.view.width-8; height: 64; radius: 7; color: Theme.queueBg
                RowLayout {
                    anchors.fill: parent; anchors.margins: 10; spacing: 9
                    ColumnLayout { Layout.fillWidth: true
                        Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: modelData.source + " → " + modelData.target; color: Theme.text; elide: Text.ElideRight }
                        Text { textFormat: Text.PlainText; text: modelData.confirmed ? Tr.tr("Confirmado") : Tr.tr("Sugerido"); color: modelData.confirmed ? Theme.green : Theme.accent; font.pixelSize: 11 }
                    }
                    ActionButton { text: Tr.tr("Editar"); implicitHeight: 32; enabled: !Backend.busy; onClicked: {original.text=modelData.source;target.text=modelData.target;confirmed.checked=modelData.confirmed} }
                    ActionButton { text: Tr.tr("Remover"); danger: true; implicitHeight: 32; enabled: !Backend.busy; onClicked: review.removeTerm(modelData.source) }
                }
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Text { textFormat: Text.PlainText; text: Tr.tr("TEMPORADAS VINCULADAS"); color: Theme.accent; font.pixelSize: 11; Layout.fillWidth: true }
        ActionButton { text: Tr.tr("Vincular pasta"); enabled: review.selectedProject.length>0 && !Backend.busy; onClicked: review.bindSeason() }
    }
    ListView {
        Layout.fillWidth: true; Layout.preferredHeight: 95; clip: true; model: review.folders; spacing: 4; ScrollBar.vertical: ScrollBar {}
        delegate: RowLayout {
            required property var modelData
            width: ListView.view.width
            Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: modelData.path; color: Theme.muted; font.pixelSize: 11; elide: Text.ElideMiddle }
            ActionButton { text: Tr.tr("Desvincular"); implicitHeight: 30; enabled: !Backend.busy; onClicked: review.unbindSeason(modelData.key) }
        }
    }
}
