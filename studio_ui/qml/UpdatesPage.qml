import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
ScrollView {
    id:page;clip:true;contentWidth:availableWidth
    property var updater:Backend.updater
    ColumnLayout {
        width:parent.width;spacing:20
        Text {text:Tr.tr("O Studio consulta o repositório oficial quando você pede, ou ao abrir se ativar a opção abaixo. Pacotes são verificados por assinatura e instalados nesta mesma pasta.");color:Theme.muted;Layout.fillWidth:true;wrapMode:Text.Wrap}
        Rectangle {
            Layout.fillWidth:true;implicitHeight:card.implicitHeight+36;radius:12;color:Theme.card;border.color:Theme.line
            ColumnLayout {id:card;anchors.fill:parent;anchors.margins:18;spacing:14
                RowLayout {
                    Layout.fillWidth:true
                    ColumnLayout {Layout.fillWidth:true;Layout.preferredWidth:Math.max(180,(card.width-20)/2)
                        Text {text:Tr.tr("VERSÃO INSTALADA");color:Theme.muted;font.pixelSize:11}
                        Text {text:"v"+updater.installed;color:Theme.text;font.pixelSize:26;font.family:Theme.display}
                    }
                    ColumnLayout {Layout.fillWidth:true;Layout.preferredWidth:Math.max(180,(card.width-20)/2)
                        Text {text:Tr.tr("ÚLTIMA RELEASE");color:Theme.muted;font.pixelSize:11}
                        Text {text:updater.latest;color:Theme.accent;font.pixelSize:26;font.family:Theme.display}
                    }
                }
                Text {textFormat:Text.PlainText;text:updater.status;color:Theme.text;Layout.fillWidth:true;wrapMode:Text.Wrap}
                ProgressBar {value:updater.progress;from:0;to:1;visible:Backend.busy && updater.progress>0;Layout.fillWidth:true}
                Flow {
                    Layout.fillWidth:true;spacing:8
                    ActionButton {objectName:"checkUpdates";text:Tr.tr("Verificar atualizações");primary:true;enabled:!Backend.busy;onClicked:updater.check()}
                    ActionButton {objectName:"downloadUpdate";text:Tr.tr("Baixar atualização");enabled:!Backend.busy && updater.canDownload;onClicked:updater.download()}
                    ActionButton {objectName:"installUpdate";text:Tr.tr("Instalar e reiniciar");enabled:!Backend.busy && updater.ready;onClicked:{confirm.restoreMode=false;confirm.open()}}
                    ActionButton {text:Tr.tr("Página da release");onClicked:updater.openRelease()}
                }
                Text {text:Tr.tr("Modelos, runtime, configurações, glossários e resultados são preservados. Os arquivos substituídos ficam em um backup local para recuperação.");color:Theme.muted;font.pixelSize:11;Layout.fillWidth:true;wrapMode:Text.Wrap}
            }
        }
        CheckBox {objectName:"checkUpdatesAtStartup";text:Tr.tr("Verificar ao abrir o launcher");checked:Backend.settings.update_check_startup;enabled:!Backend.busy;palette.windowText:Theme.text;onToggled:Backend.updateSetting("update_check_startup",checked)}
        Text {text:Tr.tr("Desativado por padrão. A consulta envia ao GitHub o pedido de release e a versão do Studio no identificador do aplicativo; não envia legendas nem configurações.");color:Theme.muted;Layout.fillWidth:true;wrapMode:Text.Wrap;font.pixelSize:11}
        ActionButton {objectName:"restorePreviousApp";text:Tr.tr("Restaurar versão anterior");enabled:!Backend.busy && updater.canRollback;onClicked:{confirm.restoreMode=true;confirm.open()}}
        Text {text:Tr.tr("NOTAS DA RELEASE");color:Theme.accent;font.pixelSize:14;font.family:Theme.display}
        TextArea {text:updater.notes || Tr.tr("As notas aparecerão após verificar uma release publicada.");readOnly:true;selectByMouse:true;textFormat:TextEdit.PlainText;wrapMode:TextEdit.Wrap;color:Theme.text;Layout.fillWidth:true;background:Rectangle {color:Theme.card;radius:8} padding:16}
        Text {textFormat:Text.PlainText;text:updater.repository;color:Theme.muted;font.pixelSize:11;Layout.fillWidth:true;elide:Text.ElideMiddle}
    }
    Dialog {
        id:confirm;objectName:"updateInstallConfirmation";property bool restoreMode:false;anchors.centerIn:Overlay.overlay;modal:true;width:520;padding:20
        background:Rectangle {color:Theme.card;radius:10;border.color:Theme.line}
        contentItem:ColumnLayout {
            Text {text:confirm.restoreMode ? Tr.tr("Restaurar a versão anterior do aplicativo?") : Tr.tr("Instalar a atualização agora?");color:Theme.text;font.pixelSize:18;Layout.fillWidth:true;wrapMode:Text.Wrap}
            Text {text:Tr.tr("O Studio será fechado e reaberto. Uma revisão modificada será salva antes de continuar. Feche outras instâncias do aplicativo. Seus modelos e dados permanecem nas pastas atuais.");color:Theme.muted;Layout.fillWidth:true;wrapMode:Text.Wrap}
            RowLayout {
                ActionButton {text:Tr.tr("Cancelar");onClicked:confirm.close()}
                ActionButton {objectName:"confirmAppUpdate";text:Tr.tr("Confirmar e reiniciar");primary:true;enabled:!Backend.busy;onClicked:{confirm.close();if(confirm.restoreMode)updater.restore();else updater.install()}}
            }
        }
    }
}

