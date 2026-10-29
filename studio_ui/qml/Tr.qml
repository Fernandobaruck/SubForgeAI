pragma Singleton
import QtQuick
QtObject {
    readonly property string language: Backend.uiLanguage
    function tr(source) {
        let currentLanguage = language
        return Backend.translate(source)
    }
    function format(source, values) {
        let currentLanguage = language
        return Backend.formatText(source, values)
    }
}
