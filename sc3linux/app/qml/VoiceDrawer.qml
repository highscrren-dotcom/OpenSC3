import QtQuick

// CHANGE VOICE drawer: the six factory voices of the SC3, the user's own voices,
// and where each sits by pitch and formant. Which voice is on comes from sc3.voice;
// everything else from sc3.dsp.voices (shape: design/panel/scenes/demo-dsp.js) - a card
// without it shows «появится позже» (Card.ready).
Drawer {
    id: drawer
    required property QtObject sc3     // Backend (app) or DemoState (mock-ups): same shape
    title: "CHANGE VOICE"
    subtitle: "Голоса"

    // As printed on the body, in the order of the voice pad.
    readonly property var factory: [
        { key: "Male", name: "Мужской" },
        { key: "Female", name: "Женский" },
        { key: "Robot", name: "Робот" },
        { key: "Monster", name: "Монстр" },
        { key: "Baby", name: "Ребёнок" },
        { key: "Elder", name: "Пожилой" }
    ]

    readonly property var dsp: sc3.dsp || ({})
    readonly property var voiceData: dsp.voices && dsp.voices.factory ? dsp.voices.factory : null
    readonly property var own: dsp.voices && dsp.voices.own ? dsp.voices.own : null
    readonly property bool voiceKnown: !(sc3.unknown && sc3.unknown.voice === true)
    readonly property string voiceKey: voiceKnown ? sc3.voice : ""
    readonly property var current: factory.find(v => v.key === voiceKey) ?? null
    readonly property var currentData: current ? dataOf(current.key) : null

    // Pitch / formant of a factory voice, or null when the app does not know them.
    function dataOf(key) {
        const d = voiceData ? voiceData[key] : undefined;
        return d && d.pitch !== undefined && d.formant !== undefined ? d : null;
    }
    // Voices with known pitch / formant, factory first: points of the map.
    readonly property var mapPoints: {
        const pts = [];
        for (const v of factory) {
            const d = dataOf(v.key);
            if (d)
                pts.push({ key: v.key, name: v.name, pitch: d.pitch, formant: d.formant });
        }
        for (const o of own || [])
            pts.push({ key: "", name: o.name, pitch: o.pitch, formant: o.formant });
        return pts;
    }

    function st(v) {
        const s = Math.abs(v).toFixed(v % 1 ? 1 : 0).replace(".", ",");
        return (v > 0 ? "+" : v < 0 ? "−" : "±") + s + " пт";
    }

    component Label: Text {
        color: drawer.theme.drawerDim
        font.family: drawer.theme.fontUi
        font.pixelSize: drawer.ts - 1
    }

    Row {
        id: cards
        height: drawer.bodyHeight
        spacing: 14
        readonly property real inner: drawer.innerWidth - 3 * spacing

        // Factory voices ----------------------------------------------------------
        Card {
            id: factoryCard
            theme: drawer.theme
            width: cards.inner * 0.33
            height: cards.height
            title: "Голоса SC3"
            badge: "заводские"
            badgeOn: false

            Item {
                Grid {
                    columns: 3
                    columnSpacing: 8
                    rowSpacing: 8
                    readonly property real cw: (factoryCard.width - 28 - 2 * columnSpacing) / 3
                    Repeater {
                        model: drawer.factory
                        delegate: Rectangle {
                            id: tile
                            required property var modelData
                            readonly property bool on: modelData.key === drawer.voiceKey
                            readonly property var info: drawer.dataOf(modelData.key)
                            width: parent.cw
                            height: 88
                            radius: drawer.theme.uiRadius
                            color: on ? Qt.alpha(drawer.theme.accent, 0.10) : drawer.theme.graphBg
                            border.width: on ? 1.5 : 1
                            border.color: on ? drawer.theme.accent : drawer.theme.drawerCardEdge
                            Column {
                                x: 10
                                y: 9
                                spacing: 3
                                Text {
                                    text: tile.modelData.name
                                    color: drawer.theme.drawerText
                                    font.family: drawer.theme.fontUi
                                    font.pixelSize: drawer.ts
                                    font.bold: true
                                }
                                Text {   // as printed on the body
                                    text: tile.modelData.key
                                    color: drawer.theme.drawerDim
                                    font.family: drawer.theme.fontPrint
                                    font.pixelSize: drawer.ts - 2
                                }
                                Item { width: 1; height: 4 }
                                Text {
                                    visible: tile.info !== null
                                    text: tile.info ? "высота " + drawer.st(tile.info.pitch) : ""
                                    color: drawer.theme.drawerDim
                                    font.family: drawer.theme.fontUi
                                    font.pixelSize: drawer.ts - 2
                                }
                                Text {
                                    visible: tile.info !== null
                                    text: tile.info ? tile.info.extra || "форм. " + drawer.st(tile.info.formant) : ""
                                    color: drawer.theme.drawerDim
                                    font.family: drawer.theme.fontUi
                                    font.pixelSize: drawer.ts - 2
                                }
                            }
                            Rectangle {   // "on" lamp, white like the body's dot
                                visible: tile.on
                                x: tile.width - 18
                                y: 11
                                width: 8
                                height: 8
                                radius: 4
                                color: drawer.theme.dotOn
                            }
                        }
                    }
                }
            }
        }

        // Own voices ------------------------------------------------------------------
        Card {
            id: ownCard
            theme: drawer.theme
            width: cards.inner * 0.2
            height: cards.height
            title: "Свои голоса"
            ready: drawer.own !== null

            Item {
                Column {
                    width: parent.width
                    spacing: 6
                    Repeater {
                        model: drawer.own
                        delegate: Rectangle {
                            id: row
                            required property var modelData
                            width: parent.width
                            height: 44
                            radius: drawer.theme.uiRadius
                            color: drawer.theme.graphBg
                            border.width: 1
                            border.color: drawer.theme.drawerCardEdge
                            Column {
                                x: 10
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 3
                                Text {
                                    text: row.modelData.name
                                    color: drawer.theme.drawerText
                                    font.family: drawer.theme.fontUi
                                    font.pixelSize: drawer.ts
                                    font.bold: true
                                }
                                Text {
                                    text: drawer.st(row.modelData.pitch) + " · " + (row.modelData.extra || "форманта " + drawer.st(row.modelData.formant))
                                    color: drawer.theme.drawerDim
                                    font.family: drawer.theme.fontUi
                                    font.pixelSize: drawer.ts - 2
                                }
                            }
                        }
                    }
                    Rectangle {
                        width: parent.width
                        height: 40
                        radius: drawer.theme.uiRadius
                        color: "transparent"
                        border.width: 1
                        border.color: drawer.theme.drawerCardEdge
                        Row {
                            anchors.centerIn: parent
                            spacing: 6
                            Glyph { size: 14; stroke: 2.4; color: drawer.theme.drawerText; strokePath: Icons.plus; anchors.verticalCenter: parent.verticalCenter }
                            Text {
                                text: "Новый голос…"
                                color: drawer.theme.drawerText
                                font.family: drawer.theme.fontUi
                                font.pixelSize: drawer.ts - 0.5
                            }
                        }
                    }
                    Label {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: "Живут в профиле приложения; на корпусе их нет."
                        font.pixelSize: drawer.ts - 2
                    }
                }
            }
        }

        // Pitch x formant map ---------------------------------------------------------
        Card {
            id: mapCard
            theme: drawer.theme
            width: cards.inner * 0.24
            height: cards.height
            title: "Высота и форманта"
            ready: drawer.voiceData !== null

            Item {
                Item {
                    id: map
                    readonly property real padL: 22
                    readonly property real padB: 16
                    width: parent.width
                    height: parent.height - 2
                    readonly property real pw: width - padL
                    readonly property real ph: height - padB
                    function px(p) { return padL + pw * (p + 12) / 24; }
                    function py(f) { return ph * (1 - (f + 8) / 16); }

                    Rectangle {
                        x: map.padL
                        width: map.pw
                        height: map.ph
                        radius: 3
                        color: drawer.theme.graphBg
                        border.width: 1
                        border.color: drawer.theme.graphGrid
                    }
                    Rectangle { x: map.px(0); width: 1; height: map.ph; color: drawer.theme.graphGridStrong }
                    Rectangle { x: map.padL; y: map.py(0); width: map.pw; height: 1; color: drawer.theme.graphGridStrong }
                    Label { x: map.padL; y: map.ph + 2; text: "ниже"; font.pixelSize: 11 }
                    Label { x: map.width - implicitWidth; y: map.ph + 2; text: "выше  →  высота"; font.pixelSize: 11 }
                    Label {
                        x: -map.ph / 2 + 4
                        y: map.ph / 2 - 6
                        rotation: -90
                        width: map.ph
                        horizontalAlignment: Text.AlignHCenter
                        text: "форманта"
                        font.pixelSize: 11
                    }

                    Repeater {
                        model: drawer.mapPoints
                        delegate: Item {
                            id: pt
                            required property var modelData
                            readonly property bool on: modelData.key !== "" && modelData.key === drawer.voiceKey
                            readonly property bool mine: modelData.key === ""
                            x: map.px(modelData.pitch)
                            y: map.py(modelData.formant)
                            Rectangle {
                                x: -width / 2
                                y: -height / 2
                                width: pt.on ? 12 : 8
                                height: width
                                radius: width / 2
                                color: pt.on ? drawer.theme.accent : pt.mine ? "transparent" : drawer.theme.drawerDim
                                border.width: pt.mine ? 1.5 : 0
                                border.color: drawer.theme.drawerText
                            }
                            Text {   // near the right edge the name goes to the left of the dot
                                x: pt.modelData.pitch > 6 ? -implicitWidth - 9 : 9
                                y: -implicitHeight / 2
                                text: pt.modelData.name
                                color: pt.on ? drawer.theme.accent : drawer.theme.drawerDim
                                font.family: drawer.theme.fontUi
                                font.pixelSize: 11
                                font.bold: pt.on
                            }
                        }
                    }
                }
            }
        }

        // Selected voice ---------------------------------------------------------------
        Card {
            id: paramCard
            theme: drawer.theme
            width: cards.inner * 0.23
            height: cards.height
            title: drawer.current ? drawer.current.name + " · " + drawer.current.key : "Выбранный голос"
            badge: "включён"
            ready: drawer.currentData !== null
            pendingText: drawer.current ? "появится позже"
                       : drawer.voiceKnown ? "голос выключен" : "голос неизвестен"

            Item {
                Column {
                    width: parent.width
                    spacing: 3
                    ParamRow { theme: drawer.theme; width: parent.width; label: "Высота тона"; value: drawer.st(drawer.currentData.pitch); fraction: (drawer.currentData.pitch + 12) / 24; centre: 0.5 }
                    ParamRow { theme: drawer.theme; width: parent.width; label: "Форманта"; value: drawer.st(drawer.currentData.formant); fraction: (drawer.currentData.formant + 12) / 24; centre: 0.5 }
                    Repeater {
                        model: drawer.currentData.rows || []
                        delegate: ParamRow {
                            required property var modelData
                            theme: drawer.theme
                            width: parent.width
                            row: modelData
                        }
                    }
                }
                Rectangle {
                    y: parent.height - height
                    width: parent.width
                    height: 32
                    radius: drawer.theme.uiRadius
                    color: "transparent"
                    border.width: 1
                    border.color: drawer.theme.drawerCardEdge
                    Row {
                        anchors.centerIn: parent
                        spacing: 6
                        Glyph { size: 14; stroke: 2; color: drawer.theme.drawerText; strokePath: Icons.pencil; anchors.verticalCenter: parent.verticalCenter }
                        Text {
                            text: "Копия для правки"
                            color: drawer.theme.drawerText
                            font.family: drawer.theme.fontUi
                            font.pixelSize: drawer.ts - 0.5
                        }
                    }
                }
            }
        }
    }
}
