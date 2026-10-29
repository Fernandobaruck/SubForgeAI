import QtQuick
import QtQuick.Controls.Basic
Button {
    id: control
    property bool primary: false
    property bool danger: false
    implicitHeight: 42
    implicitWidth: Math.max(110, contentItem.implicitWidth + 32)
    leftPadding: 16; rightPadding: 16
    hoverEnabled: true
    Accessible.name: text
    contentItem: Text {
        text: control.text
        font.family: Theme.font; font.pixelSize: 13; font.weight: Font.DemiBold
        color: !control.enabled ? Theme.disabledText : control.primary ? Theme.accentText : control.danger ? Theme.red : Theme.text
        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: 8
        color: !control.enabled ? Theme.disabledBg : control.primary ? (control.hovered ? Theme.accentHover : Theme.accent) : control.hovered ? Theme.hover : Theme.elevated
        border.width: control.primary ? 0 : 1
        border.color: control.activeFocus ? Theme.accent : control.danger ? Theme.dangerBorder : Theme.line
        Behavior on color { ColorAnimation { duration: 120 } }
    }
}
