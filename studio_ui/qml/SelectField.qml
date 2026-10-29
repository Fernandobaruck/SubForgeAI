import QtQuick
import QtQuick.Controls.Basic
ComboBox {
    id: control
    // Keep the canonical selection when a translated model is rebuilt.
    property int selectedIndex: -1
    function refreshSelection() {
        if (selectedIndex >= 0) currentIndex = selectedIndex
    }
    onSelectedIndexChanged: refreshSelection()
    onModelChanged: Qt.callLater(refreshSelection)
    Component.onCompleted: refreshSelection()
    implicitHeight: 42
    implicitWidth: 235
    font.family: Theme.font; font.pixelSize: 13
    leftPadding: 13; rightPadding: 30
    contentItem: Text {
        textFormat: Text.PlainText
        text: control.displayText; color: control.enabled ? Theme.text : Theme.muted
        font: control.font; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
    }
    indicator: Item {
        x: control.width - 24; y: (control.height-height)/2
        width: 11; height: 9
        Rectangle { x: 0; y: 3; width: 6; height: 1.5; radius: 0.75; rotation: 45; color: Theme.muted }
        Rectangle { x: 4; y: 3; width: 6; height: 1.5; radius: 0.75; rotation: -45; color: Theme.muted }
    }
    background: Rectangle {
        radius: 7; color: Theme.elevated
        border.color: control.activeFocus ? Theme.accent : Theme.line
    }
    popup: Popup {
        onClosed: Qt.callLater(control.refreshSelection)
        y: control.height+5; width: control.width
        padding: 5
        implicitHeight: Math.min(contentItem.implicitHeight+10, 320)
        background: Rectangle { radius: 8; color: Theme.elevated; border.color: Theme.line }
        contentItem: ListView {
            clip: true; implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
    }
    delegate: ItemDelegate {
        required property int index
        required property var modelData
        width: control.width-10; height: 36
        contentItem: Text {
        textFormat: Text.PlainText
            text: modelData; font: control.font; color: Theme.text
            verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
        }
        background: Rectangle { radius: 5; color: parent.highlighted ? Theme.optionHover : "transparent" }
        highlighted: control.highlightedIndex === index
    }
}
