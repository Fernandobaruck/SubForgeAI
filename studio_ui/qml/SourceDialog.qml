import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
Dialog {
    id: dialog
    objectName: "sourceSelectionDialog"
    property var review: Backend.review
    property string identifier: ""
    property string mode: "auto"
    property string audio: "auto"
    property string subtitle: ""
    property string projectId: ""
    property var streams: []
    property var audioOptions: [{code:"auto",label:Tr.tr("Automático")}].concat(streams.filter(s=>s.kind==="audio").map(s=>({code:s.index.toString(),label:s.index+" · "+s.language+" · "+s.codec+(s.title ? " · "+s.title : "")})))
    property var subtitleOptions: [{code:"",label:Tr.tr("Selecione uma faixa")}].concat(streams.filter(s=>s.kind==="subtitle").map(s=>({code:s.index.toString(),label:s.index+" · "+s.language+" · "+s.codec})))
    anchors.centerIn: Overlay.overlay; width: 650; modal: true; padding: 22
    background: Rectangle { color: Theme.card; radius: 10; border.color: Theme.line }
    onOpened: {
        let info=review.sourceInfo
        identifier=info.id;mode=info.options.source_mode;audio=info.options.audio_stream
        subtitle=info.options.subtitle_stream;projectId=info.options.series_project;streams=info.streams
        sampleStart.text=info.options.sample_start.toString()
    }
    function options() { return {source_mode:mode,audio_stream:audio,subtitle_stream:subtitle,source_subtitle:review.sourceInfo.options ? review.sourceInfo.options.source_subtitle : "",series_project:projectId,sample_start:parseInt(sampleStart.text)||0,sample_seconds:0} }
    contentItem: ColumnLayout {
        spacing: 13
        Text { textFormat: Text.PlainText; text: Tr.tr("Fonte do episódio"); color: Theme.text; font.pixelSize: 20 }
        Text { textFormat: Text.PlainText; Layout.fillWidth: true; text: review.sourceInfo.name || ""; color: Theme.muted; font.pixelSize: 11; elide: Text.ElideMiddle }
        SettingRow { Layout.fillWidth: true; title: Tr.tr("Usar como origem")
            SelectField { property var codes:["auto","whisper","embedded","external","ocr"]; model:[Tr.tr("Configuração atual"),Tr.tr("Whisper — áudio"),Tr.tr("Legenda do vídeo"),Tr.tr("Arquivo de legenda"),Tr.tr("OCR — imagem PGS")]; selectedIndex: Math.max(0,codes.indexOf(dialog.mode)); onActivated: dialog.mode=codes[currentIndex] }
        }
        SettingRow { Layout.fillWidth: true; title: Tr.tr("Faixa do áudio"); visible: dialog.mode==="whisper" || dialog.mode==="auto"
            SelectField { model: dialog.audioOptions.map(o=>o.label); selectedIndex: Math.max(0,dialog.audioOptions.findIndex(o=>o.code===dialog.audio)); onActivated: dialog.audio=dialog.audioOptions[currentIndex].code }
        }
        SettingRow { Layout.fillWidth: true; title: Tr.tr("Faixa de legenda"); visible: dialog.mode==="embedded" || dialog.mode==="ocr"
            SelectField { model: dialog.subtitleOptions.map(o=>o.label); selectedIndex: Math.max(0,dialog.subtitleOptions.findIndex(o=>o.code===dialog.subtitle)); onActivated: dialog.subtitle=dialog.subtitleOptions[currentIndex].code }
        }
        SettingRow { Layout.fillWidth: true; title: Tr.tr("Arquivo de legenda"); description: review.sourceInfo.options ? review.sourceInfo.options.source_subtitle : ""; visible: dialog.mode==="external"
            ActionButton { text: Tr.tr("Escolher arquivo"); onClicked: review.chooseInputSubtitle(dialog.identifier) }
        }
        SettingRow { Layout.fillWidth: true; title: Tr.tr("Anime")
            SelectField { property var projects:[{id:"",name:Tr.tr("Sem anime")}].concat(review.projects); model:projects.map(p=>p.name); selectedIndex:Math.max(0,projects.findIndex(p=>p.id===dialog.projectId)); onActivated:dialog.projectId=projects[currentIndex].id }
        }
        SettingRow { Layout.fillWidth: true; title: Tr.tr("Início do teste (segundos)"); description: Tr.tr("O teste processa até 60 segundos em uma pasta separada.")
            TextField { id:sampleStart; implicitWidth:235; text:"0"; validator:IntValidator {bottom:0;top:86400} color:Theme.text;padding:12;background:Rectangle {radius:7;color:Theme.elevated;border.color:Theme.line} }
        }
        RowLayout {
            ActionButton { text: Tr.tr("Testar 60 s"); enabled: !Backend.busy; onClicked: {if(review.saveInputOptions(dialog.identifier,dialog.options())) {dialog.close();Backend.sampleItem(dialog.identifier)}} }
            Item { Layout.fillWidth:true }
            ActionButton { text:Tr.tr("Cancelar"); onClicked:dialog.close() }
            ActionButton { objectName:"saveInputSource"; text:Tr.tr("Salvar origem"); primary:true; enabled:!Backend.busy; onClicked:{if(review.saveInputOptions(dialog.identifier,dialog.options()))dialog.close()} }
        }
    }
}
