pragma Singleton
import QtQuick
QtObject {
    readonly property bool dark: Backend.uiTheme === "dark"
    readonly property var colors: Backend.themePalette
    readonly property color bg: colors.bg
    readonly property color rail: colors.rail
    readonly property color card: colors.card
    readonly property color elevated: colors.elevated
    readonly property color line: colors.line
    readonly property color text: colors.text
    readonly property color muted: colors.muted
    readonly property color accent: colors.accent
    readonly property color accentHover: colors.accentHover
    readonly property color accentText: colors.accentText
    readonly property color green: colors.green
    readonly property color red: colors.red
    readonly property color hover: colors.hover
    readonly property color navHover: colors.navHover
    readonly property color navIndex: colors.navIndex
    readonly property color caption: colors.caption
    readonly property color disabledText: colors.disabledText
    readonly property color disabledBg: colors.disabledBg
    readonly property color dangerBorder: colors.dangerBorder
    readonly property color optionHover: colors.optionHover
    readonly property color switchBorder: colors.switchBorder
    readonly property color switchThumb: colors.switchThumb
    readonly property color queueBg: colors.queueBg
    readonly property color resultBg: colors.resultBg
    readonly property color consoleBg: colors.consoleBg
    readonly property color consoleText: colors.consoleText
    readonly property color previewText: colors.previewText
    readonly property color heroStart: colors.heroStart
    readonly property color heroEnd: colors.heroEnd
    readonly property color heroBorder: colors.heroBorder
    readonly property color heroGlyph: colors.heroGlyph
    readonly property color heroLine: colors.heroLine
    readonly property color heroText: colors.heroText
    readonly property color successBg: colors.successBg
    readonly property color successBorder: colors.successBorder
    readonly property color successText: colors.successText
    readonly property color toastBg: colors.toastBg
    readonly property color toastBorder: colors.toastBorder
    readonly property string font: "Segoe UI"
    readonly property string display: "Bahnschrift"
}
