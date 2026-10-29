import QtQuick
import QtQuick.Layouts
SettingRow {
    title: Tr.tr("Visual padrão streaming")
    description: Backend.settings.subtitle_style === "reference"
        ? Tr.tr("Ativado: gera a legenda estilizada automaticamente ao concluir. O original também é mantido.")
        : Tr.tr("Ative para receber a legenda pronta com fonte branca em negrito e contorno preto.")
    ToggleSwitch {
        objectName: "automaticSubtitleStyle"
        checked: Backend.settings.subtitle_style === "reference"
        enabled: !Backend.busy
        onToggled: Backend.updateSetting("subtitle_style", checked ? "reference" : "original")
        Accessible.name: Tr.tr("Visual padrão streaming")
    }
}
