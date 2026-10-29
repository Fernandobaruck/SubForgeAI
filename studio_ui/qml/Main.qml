import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: window
    width: 1280; height: 840; minimumWidth: 1060; minimumHeight: 700
    visible: true; title: "SubForgeAI Studio"
    color: Theme.bg; font.family: Theme.font
    property int page: 0
    property bool showConsole: false
    property bool allowClose: false
    property string operationCode: "auto"
    palette.window: Theme.bg; palette.windowText: Theme.text
    palette.base: Theme.card; palette.text: Theme.text
    palette.button: Theme.elevated; palette.buttonText: Theme.text
    palette.highlight: Theme.accent; palette.highlightedText: Theme.accentText
    palette.placeholderText: Theme.muted
    readonly property var pages: [Tr.tr("Início"), Tr.tr("Episódios"), Tr.tr("Tradução"), Tr.tr("Resultados"), Tr.tr("Configurações"), Tr.tr("Diagnóstico"), Tr.tr("Revisão"), Tr.tr("Animes"), Tr.tr("Atualizações")]
    readonly property var subtitles: [Tr.tr("Seu estúdio de legendas"), Tr.tr("Uma temporada, uma fila"), Tr.tr("Contexto e consistência"), Tr.tr("Legendas prontas para revisar"), Tr.tr("Seu fluxo, do seu jeito"), Tr.tr("Acompanhe o processamento"), Tr.tr("Conferir, corrigir e recuperar versões"), Tr.tr("Vocabulário compartilhado entre temporadas"), Tr.tr("Versões oficiais e recuperação do aplicativo")]
    onClosing: function(close) {
        if ((Backend.busy || Backend.review.dirty) && !allowClose) { close.accepted = false; closeDialog.open() }
    }
    Connections {
        target: Backend
        function onMessage(text) { toastText.text = text; toast.open(); toastTimer.restart() }
        function onPreferencesChanged() { toast.close() }
        function onCloseReady() { window.allowClose = true; window.close() }
    }
    Connections {
        target: Backend.review
        function onSourceReady() { sourceDialog.open() }
        function onOpened() { window.page = 6 }
    }
    SourceDialog { id: sourceDialog }
    SetupDialog { id: setupDialog; objectName: "setupDialog" }
    DropArea {
        anchors.fill: parent
        onDropped: function(drop) { if (drop.hasUrls) Backend.addFiles(drop.urls.map(function(u) { return u.toString() })) }
    }
    Rectangle {
        id: sidebar; width: 208
        anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom
        color: Theme.rail
        Rectangle { anchors.right: parent.right; height: parent.height; width: 1; color: Theme.line; opacity: 0.6 }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 18; spacing: 5
            Item { Layout.fillWidth: true; Layout.preferredHeight: 111
                Column {
                    anchors.left: parent.left; anchors.leftMargin: 8; anchors.verticalCenter: parent.verticalCenter; spacing: 7
                    Text { text: "SUBFORGE"; color: Theme.text; font.family: Theme.display; font.pixelSize: 25; font.weight: Font.Bold; font.letterSpacing: 1.4 }
                    Row { spacing: 8
                        Rectangle { width: 20; height: 2; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: "AI FANSUB STUDIO"; color: Theme.accent; font.pixelSize: 9; font.letterSpacing: 2 }
                    }
                }
            }
            Repeater {
                model: window.pages
                delegate: Rectangle {
                    required property int index
                    required property string modelData
                    Layout.fillWidth: true; Layout.preferredHeight: 46; radius: 8
                    color: window.page === index ? Theme.elevated : navHover.containsMouse ? Theme.navHover : "transparent"
                    Rectangle { visible: window.page === index; width: 3; height: 19; radius: 1; color: Theme.accent; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter }
                    Row { anchors.verticalCenter: parent.verticalCenter; x: 16; spacing: 15
                        Text { text: "0" + (index+1); color: window.page === index ? Theme.accent : Theme.navIndex; font.pixelSize: 11; font.family: Theme.display }
                        Text { text: modelData; color: window.page === index ? Theme.text : Theme.muted; font.pixelSize: 13; font.weight: window.page === index ? Font.DemiBold : Font.Normal }
                    }
                    MouseArea { id: navHover; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: window.page = index }
                    Accessible.role: Accessible.Button; Accessible.name: modelData
                    Accessible.onPressAction: window.page = index
                    Behavior on color { ColorAnimation { duration: 120 } }
                }
            }
            Item { Layout.fillHeight: true }
            Rectangle {
                Layout.fillWidth: true; height: 76; radius: 9; color: Theme.card; border.color: Theme.line
                Column { anchors.fill: parent; anchors.margins: 12; spacing: 7
                    Text { text: Tr.tr("TRADUÇÃO LOCAL"); color: Theme.green; font.pixelSize: 9; font.letterSpacing: 1.3 }
                    Text { text: "TranslateGemma 12B"; color: Theme.text; font.pixelSize: 12 }
                    Text { text: Tr.tr("Seus arquivos no seu computador"); color: Theme.muted; font.pixelSize: 9 }
                }
            }
            Text { text: "STUDIO  /  Qt Quick"; color: Theme.caption; font.pixelSize: 10; Layout.topMargin: 14; Layout.leftMargin: 7 }
        }
    }
    ColumnLayout {
        anchors.left: sidebar.right; anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom
        anchors.leftMargin: 30; anchors.rightMargin: 30; anchors.topMargin: 24; anchors.bottomMargin: 15
        spacing: 17
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout { Layout.fillWidth: true; spacing: 4
                Text { Layout.fillWidth: true; text: window.pages[window.page].toUpperCase(); color: Theme.text; font.family: Theme.display; font.pixelSize: 28; font.weight: Font.DemiBold; font.letterSpacing: 1.2 }
                Text { Layout.fillWidth: true; text: window.subtitles[window.page]; color: Theme.muted; font.pixelSize: 12; elide: Text.ElideRight }
            }
            ToolButton { objectName: "quickThemeToggle"; text: Theme.dark ? "☀" : "☾"; implicitWidth: 42; implicitHeight: 42
                contentItem: Canvas {
                    id: themeGlyph
                    implicitWidth: 20; implicitHeight: 20
                    onPaint: {
                        let ctx = getContext("2d")
                        ctx.reset(); ctx.clearRect(0,0,width,height)
                        let x=width/2, y=height/2
                        ctx.strokeStyle=Theme.accent; ctx.fillStyle=Theme.accent; ctx.lineWidth=1.6
                        if (Theme.dark) {
                            ctx.beginPath(); ctx.arc(x,y,4,0,Math.PI*2); ctx.stroke()
                            for (let i=0;i<8;i++) {
                                let angle=i*Math.PI/4
                                ctx.beginPath(); ctx.moveTo(x+Math.cos(angle)*6,y+Math.sin(angle)*6)
                                ctx.lineTo(x+Math.cos(angle)*9,y+Math.sin(angle)*9); ctx.stroke()
                            }
                        } else {
                            ctx.beginPath(); ctx.arc(x,y,8,0,Math.PI*2); ctx.fill()
                            ctx.globalCompositeOperation="destination-out"
                            ctx.beginPath(); ctx.arc(x+4,y-3,7,0,Math.PI*2); ctx.fill()
                            ctx.globalCompositeOperation="source-over"
                        }
                    }
                    Connections { target: Theme; function onDarkChanged() { themeGlyph.requestPaint() } }
                }
                background: Rectangle { radius: 8; color: Theme.elevated; border.color: Theme.line }
                Accessible.name: Tr.tr("Alternar tema"); ToolTip.visible: hovered; ToolTip.text: Theme.dark ? Tr.tr("Tema claro") : Tr.tr("Tema escuro")
                onClicked: Backend.updateSetting("ui_theme", Theme.dark ? "light" : "dark")
            }
            ActionButton { text: Tr.tr("Abrir resultados ↗"); onClicked: Backend.openOutputs() }
        }
        Loader {
            id: content
            Layout.fillWidth: true; Layout.fillHeight: true
            sourceComponent: window.page === 0 ? homePage : window.page === 1 ? episodesPage : window.page === 2 ? translationPage : window.page === 3 ? resultsPage : window.page === 4 ? settingsPage : window.page === 5 ? diagnosticsPage : window.page === 6 ? reviewPage : window.page === 7 ? glossaryPage : updatesPage
            onLoaded: { item.opacity = 0; appear.restart() }
            NumberAnimation { id: appear; target: content.item; property: "opacity"; to: 1; duration: 160 }
        }
        Rectangle {
            Layout.fillWidth: true; Layout.preferredHeight: window.showConsole ? 205 : 0
            visible: window.showConsole; radius: 10; color: Theme.consoleBg; border.color: Theme.line
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 12; spacing: 6
                RowLayout { Layout.fillWidth: true
                    Text { text: Tr.tr("REGISTRO DA EXECUÇÃO"); color: Theme.muted; font.pixelSize: 10; font.letterSpacing: 1; Layout.fillWidth: true }
                    CheckBox { id: followLogs; text: Tr.tr("Acompanhar"); checked: true; palette.windowText: Theme.muted; font.pixelSize: 11 }
                    ActionButton { text: Tr.tr("Abrir log"); implicitHeight: 28; onClicked: Backend.openPath(Backend.logPath) }
                }
                ScrollView {
                    id: consoleScroll; Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                    TextArea {
                        text: Backend.console; readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText
                        wrapMode: TextEdit.WrapAnywhere; color: Theme.consoleText; font.family: "Consolas"; font.pixelSize: 11
                        background: null
                        onTextChanged: if (followLogs.checked) cursorPosition = length
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 9
            Rectangle { width: 6; height: 6; radius: 3; color: Backend.busy ? Theme.accent : Theme.green }
            Text { text: Backend.status; color: Theme.muted; font.pixelSize: 11; elide: Text.ElideMiddle; Layout.fillWidth: true }
            ActionButton { text: window.showConsole ? Tr.tr("Ocultar registro") : Tr.tr("Ver registro"); implicitHeight: 30; onClicked: window.showConsole = !window.showConsole }
            ActionButton { text: Tr.tr("Interromper"); danger: true; implicitHeight: 30; enabled: Backend.busy; onClicked: Backend.stop() }
        }
    }
    Component {
        id: homePage
        ScrollView {
            clip: true; contentWidth: availableWidth
            ColumnLayout {
                width: parent.width; spacing: 18
                Rectangle {
                    Layout.fillWidth: true; Layout.preferredHeight: 216; radius: 13; clip: true
                    gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: Theme.heroStart } GradientStop { position: 1; color: Theme.heroEnd } }
                    border.color: Theme.heroBorder
                    Text { anchors.right: parent.right; anchors.rightMargin: 25; anchors.verticalCenter: parent.verticalCenter; text: "字幕"; color: Theme.heroGlyph; font.pixelSize: 150; font.bold: true; rotation: -8 }
                    Rectangle { x: parent.width*0.66; y: -40; width: 1; height: 310; rotation: 28; color: Theme.heroLine; opacity: 0.5 }
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 26; spacing: 9
                        Text { text: Tr.tr("DO PRIMEIRO DIÁLOGO AO ÚLTIMO EPISÓDIO"); color: Theme.accent; font.pixelSize: 10; font.letterSpacing: 1.6 }
                        Text { text: Tr.tr("DÊ VOZ À SUA\nPRÓXIMA TEMPORADA."); color: Theme.text; font.family: Theme.display; font.pixelSize: 32; font.weight: Font.Bold; font.letterSpacing: 0.5; lineHeight: 0.98 }
                        Text { text: Tr.tr("Transcreva, traduza e acompanhe cada episódio em um só lugar."); color: Theme.heroText; font.pixelSize: 12 }
                        Item { Layout.fillHeight: true }
                        RowLayout { spacing: 10
                            ActionButton { text: Tr.tr("+  Adicionar arquivos"); primary: true; onClicked: Backend.chooseFiles() }
                            ActionButton { text: Tr.tr("Ver a fila →"); onClicked: window.page = 1 }
                        }
                    }
                }
                Rectangle {
                    Layout.fillWidth: true; implicitHeight: setupCard.implicitHeight + 28; radius: 10; color: Theme.card; border.color: Theme.line
                    ColumnLayout { id: setupCard; anchors.fill: parent; anchors.margins: 14; spacing: 8
                        Text { text: Tr.tr("PRIMEIROS PASSOS"); color: Theme.accent; font.pixelSize: 11 }
                        Text { text: Tr.tr("Prepare os modelos, adicione os arquivos e inicie pela fila. Os resultados ficam disponíveis para revisão."); color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        ActionButton { text: Tr.tr("Preparar para começar"); onClicked: setupDialog.open() }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true; spacing: 12
                    Repeater {
                        model: [{title:Tr.tr("NA FILA"), value:Backend.pendingCount.toString(), detail:Tr.tr("aguardando processamento")}, {title:Tr.tr("CONCLUÍDOS"), value:Backend.completed.toString(), detail:Tr.tr("resultados preservados")}, {title:Tr.tr("PRECISAM DE ATENÇÃO"), value:Backend.failed.toString(), detail:Tr.tr("retome pelo mesmo checkpoint")}]
                        delegate: Rectangle {
                            required property var modelData
                            Layout.fillWidth: true; height: 100; radius: 10; color: Theme.card; border.color: Theme.line
                            Column { anchors.fill: parent; anchors.margins: 16; spacing: 5
                                Text { text: modelData.title; color: Theme.muted; font.pixelSize: 9; font.letterSpacing: 1 }
                                Text { text: modelData.value; color: Theme.text; font.family: Theme.display; font.pixelSize: 27 }
                                Text { text: modelData.detail; color: Theme.muted; font.pixelSize: 10 }
                            }
                        }
                    }
                }
                Text { Layout.fillWidth: true; text: Backend.hardware; color: Theme.muted; font.pixelSize: 11; elide: Text.ElideRight }
                EpisodeQueue { Layout.fillWidth: true }
                Item { height: 5 }
            }
        }
    }
    Component {
        id: episodesPage
        ColumnLayout {
            spacing: 18
            Rectangle {
                Layout.fillWidth: true; implicitHeight: 96; radius: 11; color: Theme.card; border.color: Theme.line
                RowLayout {
                    anchors.fill: parent; anchors.margins: 18; spacing: 10
                    ColumnLayout { Layout.fillWidth: true; spacing: 5
                        Text { text: Tr.tr("SEU FLUXO DE TRABALHO"); color: Theme.accent; font.pixelSize: 10; font.letterSpacing: 1.1 }
                        Text { text: Tr.tr("Legendas prontas entram direto na tradução."); color: Theme.muted; font.pixelSize: 12 }
                    }
                    SelectField { id: operation; objectName: "operationSelector"; property var codes: ["auto","transcribe","translate","extract"]; selectedIndex: codes.indexOf(window.operationCode); onActivated: window.operationCode = codes[currentIndex]; model: [Tr.tr("Automático"), Tr.tr("Só transcrever"), Tr.tr("Só traduzir"), Tr.tr("Extrair legendas")]; enabled: !Backend.busy; implicitWidth: 160 }
                    ActionButton { text: Tr.tr("+ Arquivos"); onClicked: Backend.chooseFiles() }
                    ActionButton { text: Tr.tr("Iniciar fila →"); primary: true; enabled: !Backend.busy && Backend.items.length > Backend.completed; onClicked: Backend.start(window.operationCode) }
                }
            }
            EpisodeQueue { Layout.fillWidth: true; Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true
                Text { text: Tr.tr("Tempos, nomes e checkpoints continuam sob os cuidados do processamento existente."); color: Theme.muted; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                ActionButton { text: Tr.tr("Retomar falhas"); enabled: !Backend.busy; onClicked: Backend.retryFailed() }
            }
        }
    }
    Component {
        id: translationPage
        ScrollView {
            clip: true; contentWidth: availableWidth
            ColumnLayout {
                width: parent.width; spacing: 18
                Rectangle {
                    Layout.fillWidth: true; height: 140; color: Theme.card; radius: 12; border.color: Theme.line
                    Column { anchors.fill: parent; anchors.margins: 24; spacing: 9
                        Text { text: Tr.tr("TRADUÇÃO COM CONTEXTO"); color: Theme.accent; font.pixelSize: 10; font.letterSpacing: 1.4 }
                        Text { text: "TranslateGemma 12B"; color: Theme.text; font.family: Theme.display; font.pixelSize: 27 }
                        Text { text: Tr.tr("Português do Brasil · modelo local quantizado · glossário e memória por série"); color: Theme.muted; font.pixelSize: 12 }
                        Text { text: Tr.tr("Arquivos de vídeo precisam de extração ou transcrição antes da tradução."); color: Theme.muted; font.pixelSize: 11 }
                    }
                }
                SettingRow {
                    Layout.fillWidth: true; title: Tr.tr("Validação da tradução"); description: Tr.tr("Verifica a estrutura e registra trechos que precisam de revisão.")
                    SelectField { model: [Tr.tr("Automática"), Tr.tr("Desativada")]; selectedIndex: Backend.settings.review_mode === "disabled" ? 1 : 0; enabled: !Backend.busy; onActivated: Backend.updateSetting("review_mode", currentIndex ? "disabled" : "auto") }
                }
                SettingRow {
                    Layout.fillWidth: true; title: Tr.tr("Pasta das traduções"); description: Backend.settings.ollama_out_dir
                    ActionButton { text: Tr.tr("Escolher pasta"); enabled: !Backend.busy; onClicked: Backend.chooseDirectory("ollama_out_dir") }
                }
                SettingRow {
                    Layout.fillWidth: true; title: Tr.tr("Terminologia e nomes"); description: Tr.tr("As preferências confirmadas de cada série são reutilizadas entre episódios.")
                }
                Rectangle {
                    Layout.fillWidth: true; height: 90; radius: 10; color: Theme.successBg; border.color: Theme.successBorder
                    Text { anchors.fill: parent; anchors.margins: 19; text: Tr.tr("Retomada automática\nSe uma tradução falhar, adicione o mesmo arquivo ou retome a falha na fila. Os blocos já concluídos são recuperados pelo tradutor."); color: Theme.successText; font.pixelSize: 13; wrapMode: Text.WordWrap; verticalAlignment: Text.AlignVCenter }
                }
                ActionButton { text: Tr.tr("Ir para episódios →"); primary: true; onClicked: window.page = 1 }
                Item { Layout.fillHeight: true }
            }
        }
    }
    Component {
        id: settingsPage
        ScrollView {
            clip: true; contentWidth: availableWidth
            ColumnLayout {
                width: parent.width; spacing: 8
                Text { text: Tr.tr("APARÊNCIA E IDIOMA"); color: Theme.accent; font.pixelSize: 11; font.letterSpacing: 1.5; Layout.bottomMargin: 8 }
                SettingRow { Layout.fillWidth: true; title: Tr.tr("Idioma da interface"); description: Tr.tr("A troca é imediata e fica salva para a próxima abertura.")
                    SelectField { objectName: "interfaceLanguage"; property var codes: ["pt-BR","en","es"]; model: ["Português (Brasil)", "English", "Español"]; selectedIndex: Math.max(0,codes.indexOf(Backend.uiLanguage)); onActivated: Backend.updateSetting("ui_language", codes[currentIndex]); Accessible.name: Tr.tr("Idioma da interface") }
                }
                SettingRow { Layout.fillWidth: true; title: Tr.tr("Tema"); description: Tr.tr("O escuro mantém o visual original do Studio.")
                    SelectField { objectName: "interfaceTheme"; property var codes: ["dark","light"]; model: [Tr.tr("Escuro (padrão)"),Tr.tr("Claro")]; selectedIndex: Math.max(0,codes.indexOf(Backend.uiTheme)); onActivated: Backend.updateSetting("ui_theme", codes[currentIndex]); Accessible.name: Tr.tr("Tema") }
                }
                Text { Layout.fillWidth: true; text: Tr.tr("Idioma e tema podem ser alterados durante o processamento."); color: Theme.muted; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.bottomMargin: 18 }
                Text { text: Tr.tr("TRANSCRIÇÃO"); color: Theme.accent; font.pixelSize: 11; font.letterSpacing: 1.5; Layout.bottomMargin: 8 }
                SettingRow { Layout.fillWidth: true; title: Tr.tr("Modelo Whisper"); description: Tr.tr("Large v3 prioriza qualidade; Turbo prioriza velocidade.")
                    SelectField { model: ["Large v3", "Large v3 Turbo"]; selectedIndex: Backend.settings.whisper_model === "large-v3" ? 0 : 1; enabled: !Backend.busy; onActivated: Backend.updateSetting("whisper_model", currentIndex ? "large-v3-turbo" : "large-v3") }
                }
                SettingRow { Layout.fillWidth: true; title: Tr.tr("Idioma do áudio"); description: Tr.tr("Para animes em japonês, informar o idioma evita uma detecção incorreta.")
                    SelectField { property var codes: ["auto","ja","en","pt","es","fr","de","it","ko","zh"]; model: [Tr.tr("Detectar automaticamente"), Tr.tr("Japonês"), Tr.tr("Inglês"), Tr.tr("Português"), Tr.tr("Espanhol"), Tr.tr("Francês"), Tr.tr("Alemão"), Tr.tr("Italiano"), Tr.tr("Coreano"), Tr.tr("Chinês")]; selectedIndex: Math.max(0, codes.indexOf(Backend.settings.whisper_language)); enabled: !Backend.busy; onActivated: Backend.updateSetting("whisper_language", codes[currentIndex]) }
                }
                SettingRow { Layout.fillWidth: true; title: Tr.tr("Dispositivo"); description: Tr.tr("CUDA utiliza sua GPU NVIDIA.")
                    SelectField { property var codes: ["cuda","cpu","auto"]; model: [Tr.tr("GPU NVIDIA · CUDA"), Tr.tr("Processador · CPU"), Tr.tr("Automático")]; selectedIndex: Math.max(0, codes.indexOf(Backend.settings.whisper_device)); enabled: !Backend.busy; onActivated: Backend.updateSetting("whisper_device", codes[currentIndex]) }
                }
                SettingRow { Layout.fillWidth: true; title: Tr.tr("Faixa do áudio"); description: Tr.tr("auto prioriza japonês em animes. Um idioma explícito seleciona a faixa correspondente. Ou informe o índice global da stream.")
                    TextField { text: Backend.settings.whisper_audio_stream; enabled: !Backend.busy; implicitWidth: 235; color: Theme.text; font.pixelSize: 13; padding: 12
                        background: Rectangle { color: Theme.elevated; radius: 7; border.color: Theme.line }
                        onEditingFinished: Backend.updateSetting("whisper_audio_stream", text)
                    }
                }
                SettingRow { Layout.fillWidth: true; title: Tr.tr("Separação de voz"); description: Tr.tr("O modo automático usa Demucs com Large v3 e dispensa a etapa com Turbo.")
                    SelectField { property var codes: ["auto","enabled","disabled"]; model: [Tr.tr("Automática"), Tr.tr("Ativada"), Tr.tr("Desativada")]; selectedIndex: Math.max(0, codes.indexOf(Backend.settings.whisper_demucs_mode)); enabled: !Backend.busy; onActivated: Backend.updateSetting("whisper_demucs_mode", codes[currentIndex]) }
                }
                ActionButton {objectName:"openMaintenance";text:Tr.tr("Recursos, modelos, limpeza e conclusão");onClicked:maintenanceDialog.open();Layout.topMargin:18}
                Text { text: Tr.tr("FLUXO AUTOMÁTICO"); color: Theme.accent; font.pixelSize: 11; font.letterSpacing: 1.5; Layout.topMargin: 25 }
                SettingRow { Layout.fillWidth: true; title: Tr.tr("Extrair legendas existentes"); description: Tr.tr("Salva também as faixas de legenda embutidas antes de transcrever o áudio.")
                    ToggleSwitch { checked: Backend.settings.auto_extract_subs; enabled: !Backend.busy; onToggled: Backend.updateSetting("auto_extract_subs", checked); Accessible.name: Tr.tr("Extrair legendas no automático") }
                }
                SettingRow { Layout.fillWidth: true; title: Tr.tr("Incorporar a tradução ao vídeo"); description: Tr.tr("Cria um MKV com legenda selecionável, preservando o vídeo original.")
                    ToggleSwitch { checked: Backend.settings.embed_enabled; enabled: !Backend.busy; onToggled: Backend.updateSetting("embed_enabled", checked); Accessible.name: Tr.tr("Incorporar tradução") }
                }
                SettingRow { Layout.fillWidth: true; title: Tr.tr("Formato de extração"); description: Tr.tr("Manter original evita converter faixas desnecessariamente.")
                    SelectField { property var codes: ["copy","srt","ass","vtt"]; model: [Tr.tr("Manter original"), "SRT", "ASS", "VTT"]; selectedIndex: Math.max(0, codes.indexOf(Backend.settings.extract_to)); enabled: !Backend.busy; onActivated: Backend.updateSetting("extract_to", codes[currentIndex]) }
                }
                SettingRow { Layout.fillWidth: true; title: Tr.tr("Faixas para extrair"); description: Tr.tr("Use all para todas ou índices separados por vírgula, como 2,3.")
                    TextField { text: Backend.settings.extract_stream; enabled: !Backend.busy; implicitWidth: 235; color: Theme.text; font.pixelSize: 13; padding: 12; background: Rectangle { color: Theme.elevated; radius: 7; border.color: Theme.line } onEditingFinished: Backend.updateSetting("extract_stream", text) }
                }
                Text { text: Tr.tr("PASTAS DE SAÍDA"); color: Theme.accent; font.pixelSize: 11; font.letterSpacing: 1.5; Layout.topMargin: 25 }
                Repeater {
                    model: [{key:"whisper_out_dir",label:Tr.tr("Transcrições")},{key:"ollama_out_dir",label:Tr.tr("Traduções")},{key:"subs_out_dir",label:Tr.tr("Legendas extraídas")},{key:"embed_output_dir",label:Tr.tr("Vídeos com legenda")}]
                    delegate: SettingRow {
                        required property var modelData
                        Layout.fillWidth: true; title: modelData.label; description: Backend.settings[modelData.key]
                        ActionButton { text: Tr.tr("Escolher pasta"); enabled: !Backend.busy; onClicked: Backend.chooseDirectory(modelData.key) }
                    }
                }
                Text { text: Tr.tr("As alterações são salvas automaticamente e ficam bloqueadas durante uma execução."); color: Theme.muted; font.pixelSize: 11; Layout.topMargin: 15; Layout.bottomMargin: 20 }
            }
        }
    }
    Component {
        id: resultsPage
        ColumnLayout {
            spacing: 14
            RowLayout { Layout.fillWidth: true
                TextField { id: search; Layout.fillWidth: true; placeholderText: Tr.tr("Buscar por episódio ou nome do arquivo…"); color: Theme.text; placeholderTextColor: Theme.muted; padding: 13; background: Rectangle { color: Theme.card; radius: 8; border.color: Theme.line } }
                ActionButton { text: Tr.tr("Atualizar"); onClicked: Backend.refreshResults() }
            }
            SplitView {
                Layout.fillWidth: true; Layout.fillHeight: true
                handle: Rectangle { implicitWidth: 10; color: Theme.bg }
                Rectangle {
                    SplitView.preferredWidth: 350; SplitView.minimumWidth: 240; color: Theme.card; radius: 10; border.color: Theme.line
                    ListView {
                        id: resultList; anchors.fill: parent; anchors.margins: 8; spacing: 5; clip: true
                        model: Backend.results.filter(function(row) { return row.name.toLowerCase().indexOf(search.text.toLowerCase()) >= 0 })
                        ScrollBar.vertical: ScrollBar {}
                        Text { anchors.centerIn: parent; visible: resultList.count === 0; text: Tr.tr("Nenhum resultado encontrado"); color: Theme.muted; font.pixelSize: 12 }
                        delegate: Rectangle {
                            required property var modelData
                            width: ListView.view.width-10; height: 81; radius: 7
                            color: resultHover.containsMouse ? Theme.elevated : Theme.resultBg
                            Column { anchors.fill: parent; anchors.margins: 11; spacing: 6
                                Text { width: parent.width; text: modelData.name; color: Theme.text; font.pixelSize: 12; elide: Text.ElideMiddle }
                                Text { text: modelData.format + "   /   " + modelData.size; color: Theme.accent; font.pixelSize: 10 }
                                Text { width: parent.width; text: modelData.folder; color: Theme.muted; font.pixelSize: 10; elide: Text.ElideLeft }
                            }
                            MouseArea { id: resultHover; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Backend.inspectResult(modelData.path) }
                        }
                    }
                }
                Rectangle {
                    SplitView.fillWidth: true; SplitView.minimumWidth: 300; color: Theme.card; radius: 10; border.color: Theme.line
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 15; spacing: 14
                        Text { Layout.fillWidth: true; text: Backend.previewTitle; color: Theme.text; font.pixelSize: 12; wrapMode: Text.WrapAnywhere }
                        RowLayout {
                            ActionButton { text: Tr.tr("Revisar"); primary: true; implicitHeight: 32; enabled: /\.(srt|ass|vtt|review_required\.json)$/i.test(Backend.previewPath) && !Backend.busy; onClicked: Backend.review.openDocument(Backend.previewPath) }
                            ActionButton { text: Tr.tr("Abrir arquivo ↗"); implicitHeight: 32; enabled: Backend.previewPath.length > 0; onClicked: Backend.openPath(Backend.previewPath) }
                            ActionButton { text: Tr.tr("Abrir pasta"); implicitHeight: 32; enabled: Backend.previewPath.length > 0; onClicked: Backend.openPath(Backend.previewFolder) }
                        }
                        Text { text: Tr.tr("PRÉVIA · SOMENTE LEITURA"); color: Theme.accent; font.pixelSize: 9; font.letterSpacing: 1.1 }
                        ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                            TextArea { text: Backend.preview; readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText; wrapMode: TextEdit.WrapAnywhere; color: Theme.previewText; font.family: "Consolas"; font.pixelSize: 12; background: null }
                        }
                    }
                }
            }
        }
    }
    Component {
        id: diagnosticsPage
        ColumnLayout {
            spacing: 18
            Text { Layout.fillWidth: true; text: Backend.hardware; color: Theme.text; font.pixelSize: 14; wrapMode: Text.WordWrap }
            Repeater {
                model: [{key:"cpu_pct",label:Tr.tr("PROCESSADOR")},{key:"ram_pct",label:Tr.tr("MEMÓRIA RAM")},{key:"gpu_pct",label:"GPU"},{key:"vram_pct",label:Tr.tr("MEMÓRIA DE VÍDEO")}]
                delegate: Rectangle {
                    required property var modelData
                    property var reading: Backend.metrics[modelData.key]
                    Layout.fillWidth: true; height: 78; radius: 10; color: Theme.card; border.color: Theme.line
                    ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 11
                        RowLayout { Layout.fillWidth: true
                            Text { text: modelData.label; color: Theme.muted; font.pixelSize: 10; font.letterSpacing: 1; Layout.fillWidth: true }
                            Text { text: reading === undefined || reading === null ? "—" : Math.round(reading)+"%"; color: Theme.text; font.family: Theme.display; font.pixelSize: 20 }
                        }
                        Rectangle { Layout.fillWidth: true; height: 4; radius: 2; color: Theme.line
                            Rectangle { height: 4; radius: 2; width: parent.width * Math.max(0, Math.min(100, reading || 0))/100; color: Theme.green; Behavior on width { NumberAnimation { duration: 200 } } }
                        }
                    }
                }
            }
            ActionButton {text:Tr.tr("Gerenciar recursos e modelos");onClicked:{maintenanceDialog.section=1;maintenanceDialog.open();Backend.maintenance.refreshModels()}}
            Text { text: Tr.tr("Os registros detalhados ficam disponíveis durante e após a execução."); color: Theme.muted; font.pixelSize: 12 }
            RowLayout {
                ActionButton { text: Tr.tr("Ver registro"); onClicked: window.showConsole = true }
                ActionButton { text: Tr.tr("Abrir log da sessão"); onClicked: Backend.openPath(Backend.logPath) }
            }
            Item { Layout.fillHeight: true }
        }
    }
    MaintenanceDialog {id:maintenanceDialog}
    Popup {
        anchors.centerIn:Overlay.overlay;width:Math.min(620,window.width-40);padding:20;modal:false;closePolicy:Popup.NoAutoClose
        visible:Backend.maintenance.countdown>0
        background:Rectangle {color:Theme.card;radius:10;border.color:Theme.accent}
        contentItem:ColumnLayout {
            Text {text:Tr.format("Suspensão em {seconds} segundos",{seconds:Backend.maintenance.countdown});color:Theme.text;font.pixelSize:18;Layout.fillWidth:true;wrapMode:Text.Wrap}
            ActionButton {objectName:"cancelScheduledSleep";text:Tr.tr("Cancelar suspensão");primary:true;onClicked:Backend.maintenance.cancelCompletion()}
        }
    }
    Component { id: reviewPage; ReviewPage {} }
    Component { id: glossaryPage; GlossaryPage {} }
    Component { id: updatesPage; UpdatesPage {} }
    Popup {
        id: toast; anchors.centerIn: Overlay.overlay; width: Math.min(window.width-80, 620); padding: 20; modal: false
        background: Rectangle { radius: 10; color: Theme.toastBg; border.color: Theme.toastBorder }
        contentItem: Text { id: toastText; color: Theme.text; font.pixelSize: 13; wrapMode: Text.WordWrap }
    }
    Timer { id: toastTimer; interval: 6000; onTriggered: toast.close() }
    Dialog {
        id: closeDialog; anchors.centerIn: Overlay.overlay; modal: true; width: 420; padding: 24
        background: Rectangle { color: Theme.card; radius: 12; border.color: Theme.line }
        contentItem: ColumnLayout { spacing: 18
            Text { text: Backend.review.dirty ? Tr.tr("Revisão não salva") : Tr.tr("Há uma tarefa em andamento"); color: Theme.text; font.pixelSize: 17; font.bold: true }
            Text { Layout.fillWidth: true; text: Backend.review.dirty ? Tr.tr("As alterações serão salvas em cópia antes de fechar.") : Tr.tr("O Studio pode interromper o processamento e fechar. Resultados e checkpoints concluídos serão preservados."); color: Theme.muted; font.pixelSize: 13; wrapMode: Text.WordWrap }
            RowLayout {
                ActionButton { text: Tr.tr("Continuar trabalhando"); onClicked: closeDialog.close() }
                ActionButton { text: Backend.review.dirty ? Tr.tr("Salvar e fechar") : Tr.tr("Interromper e fechar"); danger: true; onClicked: { closeDialog.close(); Backend.requestClose() } }
            }
        }
    }
}
