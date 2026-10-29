import QtQuick
import QtQuick.Controls.Basic
Switch {
    id: control
    implicitWidth: 52; implicitHeight: 34
    indicator: Rectangle {
        x: (control.width-width)/2; y: (control.height-height)/2
        width: 44; height: 24; radius: 12
        color: control.checked ? Theme.accent : Theme.elevated
        border.color: control.checked ? Theme.accent : Theme.switchBorder
        Rectangle {
            x: control.checked ? 23 : 3; y: 3; width: 18; height: 18; radius: 9
            color: control.checked ? Theme.accentText : Theme.switchThumb
            Behavior on x { NumberAnimation { duration: 120 } }
        }
    }
}
