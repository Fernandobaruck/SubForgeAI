import QtQuick
import QtQuick.Layouts
Item {
    id: row
    property string title
    property string description
    default property alias controls: target.data
    implicitHeight: Math.max(labels.implicitHeight, target.implicitHeight)+30
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line; opacity: 0.6 }
    RowLayout {
        anchors.fill: parent; spacing: 30
        ColumnLayout {
            id: labels
            Layout.fillWidth: true; spacing: 5
            Text { Layout.fillWidth: true; text: row.title; color: Theme.text; font.family: Theme.font; font.pixelSize: 14; font.weight: Font.DemiBold; wrapMode: Text.WordWrap }
            Text { Layout.fillWidth: true; text: row.description; color: Theme.muted; font.family: Theme.font; font.pixelSize: 12; wrapMode: Text.WordWrap; visible: text.length > 0 }
        }
        RowLayout { id: target; Layout.alignment: Qt.AlignVCenter; spacing: 8 }
    }
}
