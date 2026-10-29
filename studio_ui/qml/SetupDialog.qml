import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
Dialog {
    id: dialog
    objectName: "modelSetupDialog"
    title: Tr.tr("Preparar para começar")
    modal: true; anchors.centerIn: parent
    width: Math.min(850, parent.width - 40)
    height: Math.min(850, parent.height - 40)
    standardButtons: Dialog.Close
    onOpened: Backend.setup.refresh()
    contentItem: ScrollView {
        objectName: "modelGuideScroll"
        clip: true; contentWidth: availableWidth
        ColumnLayout {
            width: parent.width; spacing: 14
            Text { text: Tr.tr("Escolha o TranslateGemma antes de baixar. O modelo ativo será usado na tradução, na revisão e no glossário com IA."); color: Theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Text { text: Tr.tr("Download é espaço em disco; VRAM é memória da placa. As faixas abaixo são estimativas para legendas com contexto curto, não medições. Contexto, lote, outros aplicativos e modelos carregados alteram o consumo. O projeto exige inferência na GPU: se não houver VRAM suficiente, libere memória ou escolha um modelo menor."); color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Text { text: Tr.tr("Componentes do aplicativo") + ": " + (Backend.setup.state.missing.length ? Backend.setup.state.missing.join(", ") : Tr.tr("Disponíveis")) + " · " + Tr.tr("Espaço livre") + ": " + Backend.setup.state.free_gb + " GiB"; textFormat: Text.PlainText; color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Text { text: (Backend.setup.hardware.nvidia || (Backend.setup.hardware.vulkan && !Backend.setup.hardware.shared)) ? Backend.setup.hardware.name + " · " + Backend.setup.hardware.vram + " GiB VRAM · " + Backend.setup.hardware.ram + " GiB RAM" : Tr.tr("A memória dedicada é detectada via CUDA/Vulkan quando disponível. GPUs integradas usam memória compartilhada; confira a capacidade livre no sistema."); color: Theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Repeater {
                model: Backend.setup.translationModels
                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true; implicitHeight: card.implicitHeight + 24
                    color: Theme.card; radius: 10
                    border.color: Backend.settings.ollama_model === modelData.code ? Theme.accent : Theme.line
                    ColumnLayout {
                        id: card; anchors.fill: parent; anchors.margins: 12; spacing: 7
                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: modelData.name + (Backend.settings.ollama_model === modelData.code ? " · " + Tr.tr("Ativo") : ""); color: Theme.text; font.bold: true; Layout.fillWidth: true }
                            ActionButton { text: Backend.settings.ollama_model === modelData.code ? Tr.tr("Selecionado") : Tr.tr("Usar este modelo"); enabled: !Backend.busy && Backend.settings.ollama_model !== modelData.code; onClicked: Backend.setup.selectTranslation(modelData.code) }
                            ActionButton { text: modelData.ready ? Tr.tr("Disponível") : Tr.tr("Baixar modelo"); enabled: !modelData.ready && !Backend.busy && !Backend.setup.state.missing.length; onClicked: Backend.setup.prepare(modelData.code) }
                        }
                        Text { text: Tr.tr("Download aproximado") + ": " + modelData.download_gb + " GB · " + Tr.tr("VRAM estimada") + ": " + modelData.vram + " · " + Tr.tr("VRAM recomendada") + ": " + modelData.recommended_gb + " GB"; color: Theme.accent; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Text { visible: Backend.setup.hardware.nvidia === true || (Backend.setup.hardware.vulkan === true && !Backend.setup.hardware.shared); text: Backend.setup.hardware.vram * 1.073741824 >= modelData.recommended_gb ? Tr.tr("Sua placa atende à capacidade de VRAM recomendada; o uso real depende da memória livre.") : Tr.tr("Sua placa tem menos VRAM que o recomendado; escolha um modelo menor ou libere memória. A IA em CPU será bloqueada."); color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Text { text: Tr.tr(modelData.description); color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Text { text: modelData.gpus; textFormat: Text.PlainText; color: Theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
            }
            Text { text: Tr.tr("As GPUs são exemplos por capacidade de memória, sem garantia de desempenho. NVIDIA usa CUDA; AMD e Intel usam Vulkan no servidor gerenciado. AMD e Intel ainda precisam de validação no SubForgeAI. A compatibilidade do Whisper é independente da tradução."); color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            RowLayout {
                ActionButton { text: Tr.tr("Modelos e downloads oficiais"); onClicked: Qt.openUrlExternally("https://ollama.com/library/translategemma") }
                ActionButton { text: Tr.tr("Compatibilidade das GPUs"); onClicked: Qt.openUrlExternally("https://docs.ollama.com/gpu") }
            }
            Text { text: Tr.tr("Whisper — escolha conforme a memória da GPU e a precisão desejada"); color: Theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Text { text: Tr.tr("VRAM estimada para transcrição individual em FP16, sem Demucs. CUDA e Vulkan podem consumir quantidades diferentes. Lotes, alinhamento, separação de voz e outros aplicativos precisam de memória adicional. Estes valores são orientações conservadoras, não mínimos garantidos. A memória necessária para TranslateGemma é independente."); color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Repeater {
                model: Backend.setup.whisperModels
                delegate: Rectangle {
                    required property var modelData
                    objectName: "whisperModel-"+modelData.code
                    Layout.fillWidth: true; implicitHeight: whisperCard.implicitHeight + 24
                    color: Theme.card; radius: 10
                    border.color: Backend.settings.whisper_model === modelData.code ? Theme.accent : Theme.line
                    ColumnLayout {
                        id: whisperCard; anchors.fill: parent; anchors.margins: 12; spacing: 7
                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: modelData.name + (Backend.settings.whisper_model === modelData.code ? " · " + Tr.tr("Ativo") : ""); color: Theme.text; font.bold: true; Layout.fillWidth: true }
                            ActionButton { text: Backend.settings.whisper_model === modelData.code ? Tr.tr("Selecionado") : Tr.tr("Usar este modelo"); enabled: !Backend.busy && Backend.settings.whisper_model !== modelData.code; onClicked: Backend.setup.selectWhisper(modelData.code) }
                        }
                        Text { text: Tr.tr("Download aproximado") + ": " + modelData.download_gb + " GB · " + Tr.tr("VRAM estimada") + ": " + modelData.vram + " · " + Tr.tr("VRAM recomendada") + ": " + modelData.recommended_gb + " GB"; color: Theme.accent; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Text { text: Tr.tr(modelData.description); color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Text { text: modelData.gpus; textFormat: Text.PlainText; color: Theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Text { visible: Backend.setup.hardware.nvidia === true || (Backend.setup.hardware.vulkan === true && !Backend.setup.hardware.shared); text: Backend.setup.hardware.vram * 1.073741824 >= modelData.recommended_gb ? Tr.tr("Sua placa atende à capacidade de VRAM recomendada; o uso real depende da memória livre.") : Tr.tr("Sua placa tem menos VRAM que o recomendado; escolha um modelo menor ou libere memória. A IA em CPU será bloqueada."); color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        RowLayout {
                            ActionButton { text: modelData.cuda_ready ? Tr.tr("CUDA disponível") : Tr.tr("Baixar CUDA · NVIDIA"); enabled: !modelData.cuda_ready && !Backend.busy && !Backend.setup.state.missing.length; onClicked: Backend.setup.prepare(modelData.code) }
                            ActionButton { text: modelData.vulkan_ready ? Tr.tr("Vulkan disponível") : Tr.tr("Baixar Vulkan · AMD/Intel"); enabled: !modelData.vulkan_ready && !Backend.busy && !Backend.setup.state.missing.length; onClicked: Backend.setup.prepare("vulkan-"+modelData.code) }
                        }
                    }
                }
            }
            ActionButton { text: Tr.tr("Referências de memória do Whisper"); onClicked: Qt.openUrlExternally("https://github.com/openai/whisper#available-models-and-languages") }
            Text { text: Tr.tr("Instale o Whisper CUDA para NVIDIA ou Vulkan para AMD/Intel. Automático escolhe o motor em Configurações. Os formatos de modelo são diferentes; não é necessário baixar ambos. Demucs exige CUDA; OCR e VAD neural em CPU estão bloqueados."); color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            ProgressBar { from: 0; to: 1; value: Backend.setup.progress; visible: Backend.busy || Backend.setup.progress > 0; indeterminate: Backend.busy && Backend.setup.progress === 0; Layout.fillWidth: true }
            Text { text: Backend.setup.status; color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Text { text: Tr.tr("Os downloads usam internet e ficam nesta pasta. Depois, os modelos instalados podem ser usados offline. Selecione e baixe apenas o modelo que pretende usar; os demais são opcionais."); color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            ActionButton { text: Tr.tr("Interromper"); enabled: Backend.busy; onClicked: Backend.stop() }
        }
    }
}
