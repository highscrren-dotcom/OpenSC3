import QtQuick

// MIC drawer: what the body has no controls for - voice EQ (node 0xA2, ten slots), gate
// (0x82), compressor, the trim to the PC (0xAC). Everything comes from sc3.dsp (shape:
// design/panel/scenes/demo-dsp.js; the app builds it from the nodes it read, view.drawer_dsp);
// a card whose key is missing shows «появится позже» (Card.ready). Display only.
Drawer {
    id: drawer
    required property QtObject sc3     // Backend (app) or DemoState (mock-ups): same shape
    title: "MIC"
    subtitle: "Обработка голоса"
    note: "Только просмотр · «Подкаст» — в меню профиля"
    bodyHeight: 300

    readonly property var dsp: sc3.dsp || ({})
    readonly property var eqData: dsp.eq && dsp.eq.slots ? dsp.eq : null
    readonly property var gateData: dsp.gate && dsp.gate.rows ? dsp.gate : null
    readonly property var compData: dsp.comp && dsp.comp.reduction ? dsp.comp : null
    readonly property var gainData: dsp.gain && dsp.gain.value !== undefined ? dsp.gain : null

    function dB(v) {
        const s = Math.abs(v).toFixed(1).replace(".", ",");
        return (v > 0.05 ? "+" : v < -0.05 ? "−" : "") + s + " дБ";
    }
    function fmtHz(f) {
        return f >= 1000 ? (f / 1000).toFixed(f % 1000 ? 1 : 0).replace(".", ",") + " кГц" : f + " Гц";
    }

    // ---- cards
    Row {
        id: cards
        height: drawer.bodyHeight
        spacing: 14
        readonly property real inner: drawer.innerWidth - 3 * spacing

        // Voice EQ ----------------------------------------------------------
        Card {
            id: eqCard
            theme: drawer.theme
            width: cards.inner * 0.47
            height: cards.height
            title: "Эквалайзер голоса"
            ready: drawer.eqData !== null
            badge: ready && drawer.eqData.on === false ? "выкл" : "вкл"
            badgeOn: badge === "вкл"

            Item {
                EqGraph {
                    id: eq
                    theme: drawer.theme
                    bands: drawer.eqData.bands
                    selected: drawer.eqData.selected ?? -1
                    width: parent.width
                    height: 136
                }
                // Ten slots of the node, as they are: on, type, frequency, gain, Q. Off and empty ones are dim.
                Grid {
                    id: slotGrid
                    y: 146
                    width: parent.width
                    columns: 5
                    columnSpacing: 6
                    rowSpacing: 6
                    readonly property real cw: (width - 4 * columnSpacing) / 5
                    Repeater {
                        model: drawer.eqData.slots
                        delegate: Rectangle {
                            id: chip
                            required property var modelData
                            readonly property var slot: modelData
                            width: slotGrid.cw
                            height: 48
                            radius: drawer.theme.uiRadius === 0 ? 0 : 5
                            color: slot.on ? Qt.alpha(drawer.theme.accent, 0.08) : "transparent"
                            border.width: 1
                            border.color: slot.on ? Qt.alpha(drawer.theme.accent, 0.55) : drawer.theme.drawerCardEdge
                            opacity: slot.on ? 1 : slot.empty ? 0.4 : 0.6
                            Column {
                                x: 7
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 0
                                Text {
                                    text: chip.slot.n + "  " + (chip.slot.empty ? "—" : chip.slot.freq)
                                    color: chip.slot.on ? drawer.theme.accent : drawer.theme.drawerText
                                    font.family: drawer.theme.fontValue
                                    font.pixelSize: drawer.ts - 1.5
                                    font.bold: true
                                }
                                Text {
                                    text: chip.slot.empty ? "пусто" : chip.slot.name + (chip.slot.on ? "" : " · выкл")
                                    color: drawer.theme.drawerDim
                                    font.family: drawer.theme.fontUi
                                    font.pixelSize: drawer.ts - 2
                                }
                                Text {
                                    visible: !chip.slot.empty
                                    text: (chip.slot.shaped ? chip.slot.gain.replace(" дБ", "") + " · " : "") + chip.slot.qText
                                    color: drawer.theme.drawerFaint
                                    font.family: drawer.theme.fontValue
                                    font.pixelSize: drawer.ts - 2.5
                                }
                            }
                        }
                    }
                }
            }
        }

        // Gate ----------------------------------------------------------------
        Card {
            id: gateCard
            theme: drawer.theme
            width: cards.inner * 0.19
            height: cards.height
            title: "Гейт"
            ready: drawer.gateData !== null
            badge: ready && drawer.gateData.on === false ? "выкл" : "вкл"
            badgeOn: badge === "вкл"

            Item {
                // Input level against the threshold
                Item {
                    width: parent.width
                    height: 40
                    Text {   // input level now (mock-ups), or just the scale with the threshold (app)
                        text: drawer.gateData.level ? "Вход" : "Порог на шкале −80…0 дБ"
                        color: drawer.theme.drawerDim
                        font.family: drawer.theme.fontUi
                        font.pixelSize: drawer.ts - (drawer.gateData.level ? 0.5 : 1.5)
                    }
                    Text {
                        visible: !!drawer.gateData.level
                        anchors.right: parent.right
                        text: drawer.gateData.level ? drawer.gateData.level.value : ""
                        color: drawer.theme.drawerText
                        font.family: drawer.theme.fontValue
                        font.pixelSize: drawer.ts
                        font.bold: true
                    }
                    Rectangle {
                        id: gateTrack
                        y: 22
                        width: parent.width
                        height: 8
                        radius: drawer.theme.uiRadius === 0 ? 0 : 2
                        color: drawer.theme.barTrack
                    }
                    Rectangle {
                        visible: !!drawer.gateData.level
                        y: gateTrack.y
                        width: gateTrack.width * (drawer.gateData.level ? drawer.gateData.level.fraction : 0)
                        height: gateTrack.height
                        radius: gateTrack.radius
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: Qt.alpha(drawer.theme.accent, 0.25) }
                            GradientStop { position: 1.0; color: drawer.theme.accent }
                        }
                    }
                    Rectangle {   // threshold
                        visible: drawer.gateData.threshold !== undefined
                        x: gateTrack.width * (drawer.gateData.threshold || 0) - 1
                        y: gateTrack.y - 3
                        width: 2
                        height: gateTrack.height + 6
                        color: drawer.theme.drawerText
                    }
                }
                Column {
                    y: 50
                    width: parent.width
                    spacing: 3
                    Repeater {
                        model: drawer.gateData.rows || []
                        delegate: ParamRow {
                            required property var modelData
                            theme: drawer.theme
                            width: parent.width
                            row: modelData
                        }
                    }
                }
            }
        }

        // Compressor ------------------------------------------------------------
        Card {
            id: compCard
            theme: drawer.theme
            width: cards.inner * 0.175
            height: cards.height
            title: "Компрессор"
            ready: drawer.compData !== null
            // Not on the way to the PC: the mic DRC sits in the headphone monitor only (SDK; docs/WRITE.md).
            pendingText: drawer.sc3.connected ? "нет на пути в ПК" : "появится позже"
            pendingNote: drawer.sc3.connected ? "по SDK компрессор микрофона стоит только в\u00a0мониторе наушников" : ""
            badge: ready && drawer.compData.on === false ? "выкл" : "вкл"
            badgeOn: badge === "вкл"

            Item {
                CompGraph {
                    id: compGraph
                    theme: drawer.theme
                    threshold: drawer.compData.threshold
                    ratio: drawer.compData.ratio
                    knee: drawer.compData.knee
                    input: drawer.compData.input
                    width: 84
                    height: 84
                }
                Column {
                    x: compGraph.width + 14
                    width: parent.width - x
                    spacing: 3
                    Text {
                        text: "Сжатие сейчас"
                        color: drawer.theme.drawerDim
                        font.family: drawer.theme.fontUi
                        font.pixelSize: drawer.ts - 1
                    }
                    Text {
                        text: drawer.compData.reduction.value
                        color: drawer.theme.accent
                        font.family: drawer.theme.fontValue
                        font.pixelSize: drawer.ts + 9
                        font.bold: true
                    }
                    // Gain reduction grows from the right
                    Item {
                        width: parent.width
                        height: 12
                        Rectangle {
                            y: 4
                            width: parent.width
                            height: 5
                            radius: drawer.theme.uiRadius === 0 ? 0 : 2
                            color: drawer.theme.barTrack
                        }
                        Rectangle {
                            x: parent.width * (1 - drawer.compData.reduction.fraction)
                            y: 4
                            width: parent.width * drawer.compData.reduction.fraction
                            height: 5
                            radius: drawer.theme.uiRadius === 0 ? 0 : 2
                            color: drawer.theme.accent
                        }
                    }
                }
                Grid {
                    y: compGraph.height + 10
                    width: parent.width
                    columns: 2
                    columnSpacing: 14
                    rowSpacing: 1
                    readonly property real cw: (width - columnSpacing) / 2
                    Repeater {
                        model: drawer.compData.rows || []
                        delegate: ParamRow {
                            required property var modelData
                            theme: drawer.theme
                            width: parent.cw
                            row: modelData
                        }
                    }
                }
            }
        }

        // Digital gain -------------------------------------------------------------
        Card {
            id: gainCard
            theme: drawer.theme
            width: cards.inner * 0.165
            height: cards.height
            title: "Поправка в ПК"
            ready: drawer.gainData !== null

            Item {
                Text {
                    text: drawer.gainData.value
                    color: drawer.theme.drawerText
                    font.family: drawer.theme.fontValue
                    font.pixelSize: drawer.ts + 13
                    font.bold: true
                }
                Text {
                    y: 38
                    width: parent.width
                    text: "после ползунка MIC, перед выходом в ПК"
                    wrapMode: Text.WordWrap
                    color: drawer.theme.drawerDim
                    font.family: drawer.theme.fontUi
                    font.pixelSize: drawer.ts - 1.5
                    lineHeight: 1.1
                }
                Column {
                    visible: drawer.gainData.peak !== undefined
                    y: 92
                    spacing: 1
                    Text {
                        text: "Пик на выходе"
                        color: drawer.theme.drawerDim
                        font.family: drawer.theme.fontUi
                        font.pixelSize: drawer.ts - 1
                    }
                    Text {
                        text: drawer.gainData.peak || ""
                        color: drawer.theme.drawerText
                        font.family: drawer.theme.fontValue
                        font.pixelSize: drawer.ts + 1
                        font.bold: true
                    }
                }
                // Bipolar around 0 dB
                Item {
                    id: gainBar
                    readonly property real f: drawer.gainData.fraction || 0
                    readonly property real c: drawer.gainData.centre || 0
                    y: parent.height - 34
                    width: parent.width
                    height: 40
                    Rectangle {
                        id: gainTrack
                        width: parent.width
                        height: 6
                        radius: drawer.theme.uiRadius === 0 ? 0 : 3
                        color: drawer.theme.barTrack
                    }
                    Rectangle {
                        x: gainTrack.width * Math.min(gainBar.c, gainBar.f)
                        width: gainTrack.width * Math.abs(gainBar.f - gainBar.c)
                        height: gainTrack.height
                        color: drawer.theme.accent
                    }
                    Rectangle {   // thumb
                        x: gainTrack.width * gainBar.f - width / 2
                        y: -5
                        width: 14
                        height: 14
                        radius: 7
                        color: drawer.theme.accentLight
                        border.width: 1
                        border.color: drawer.theme.accent
                    }
                    Repeater {
                        model: drawer.gainData.ticks || []
                        delegate: Text {
                            required property var modelData
                            x: Math.max(0, Math.min(gainTrack.width - implicitWidth, gainTrack.width * modelData.fraction - implicitWidth / 2))
                            y: 14
                            text: modelData.text
                            color: drawer.theme.drawerFaint
                            font.family: drawer.theme.fontValue
                            font.pixelSize: 11
                        }
                    }
                }
            }
        }
    }
}
