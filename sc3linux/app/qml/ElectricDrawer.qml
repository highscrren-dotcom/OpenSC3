import QtQuick
import QtQuick.Shapes

// ELECTRIC drawer: pitch correction ("autotune") - key out of the 12 printed around
// the pad, scale, retune speed, and what it does to a sung phrase. The key comes from
// sc3.electricKey; scale and speed from sc3.dsp.autotune (shape: design/panel/scenes/
// demo-dsp.js) - a card without it shows «появится позже» (Card.ready).
Drawer {
    id: drawer
    required property QtObject sc3     // Backend (app) or DemoState (mock-ups): same shape
    title: "ELECTRIC"
    subtitle: "Автотюн"

    // Chromatic circle, clockwise from the top; spelled as printed on the body.
    readonly property var notes: ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
    // Russian names for the line under the key: "до мажор"
    readonly property var noteNames: ["до", "ре-бемоль", "ре", "ми-бемоль", "ми", "фа",
                                      "соль-бемоль", "соль", "ля-бемоль", "ля", "си-бемоль", "си"]
    readonly property var scales: ({
        major: { steps: [0, 2, 4, 5, 7, 9, 11], name: "мажор", of: "мажора" },
        minor: { steps: [0, 2, 3, 5, 7, 8, 10], name: "минор", of: "минора" },
        chromatic: { steps: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], name: "все 12 нот", of: "" }
    })
    readonly property var scaleKeys: ["major", "minor", "chromatic"]

    readonly property var dsp: sc3.dsp || ({})
    readonly property var autotune: dsp.autotune && scales[dsp.autotune.scale] ? dsp.autotune : null
    readonly property bool keyKnown: !(sc3.unknown && sc3.unknown.electricKey === true)
    readonly property bool keyOff: keyKnown && sc3.electricKey === ""
    readonly property int keyIndex: keyKnown ? notes.indexOf(sc3.electricKey) : -1

    // Functions, not derived properties: card content is created inside the change
    // notification of `autotune` (Card.ready), before properties derived from it are updated.
    function scaleOf() { return autotune ? scales[autotune.scale] : null; }
    // The voice is pulled to note i (0 = C) - needs the key and the scale.
    function inScale(i) {
        const sc = scaleOf();
        return keyIndex >= 0 && sc !== null && sc.steps.indexOf((i - keyIndex + 12) % 12) >= 0;
    }
    // Under the key: "до мажор"
    function keyLine() {
        const sc = scaleOf();
        if (sc === null || keyIndex < 0)
            return "";
        return autotune.scale === "chromatic" ? sc.name : noteNames[keyIndex] + " " + sc.name;
    }
    // Under the keyboard of the scale card.
    function scaleLine() {
        const sc = scaleOf();
        if (keyIndex < 0)
            return keyOff ? "ELECTRIC выключен: голос идёт без коррекции." : "Тональность неизвестна.";
        if (sc === null)
            return "";
        return autotune.scale === "chromatic" ? "Голос подтягивается к ближайшей из 12 нот."
             : "Голос подтягивается к 7 нотам " + noteNames[keyIndex] + " " + sc.of + "; остальные 5 пропускаются.";
    }
    // Why a card that needs the key and the scale is empty.
    readonly property string keyPending: !autotune ? "появится позже"
                                       : keyOff ? "ELECTRIC выключен" : "тональность неизвестна"

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

        // Key -----------------------------------------------------------------------------
        Card {
            id: keyCard
            theme: drawer.theme
            width: cards.inner * 0.22
            height: cards.height
            title: "Тональность"
            badge: !drawer.keyKnown ? "" : drawer.keyOff ? "выкл" : "вкл"
            badgeOn: badge === "вкл"

            Item {
                Item {
                    id: wheel
                    readonly property real r: Math.min(width, height) / 2 - 14
                    readonly property bool scaleShown: drawer.autotune !== null && drawer.keyIndex >= 0
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: Math.min(parent.width, parent.height)
                    height: width
                    readonly property real cx: width / 2
                    readonly property real cy: height / 2

                    Rectangle {   // ring
                        x: wheel.cx - wheel.r
                        y: wheel.cy - wheel.r
                        width: 2 * wheel.r
                        height: width
                        radius: wheel.r
                        color: "transparent"
                        border.width: 1
                        border.color: drawer.theme.graphGridStrong
                    }
                    Repeater {
                        model: 12
                        delegate: Rectangle {
                            id: note
                            required property int index
                            readonly property real a: index / 12 * 2 * Math.PI
                            readonly property bool sel: index === drawer.keyIndex
                            readonly property bool inKey: drawer.inScale(index)
                            // without the scale every other note is drawn neutral
                            readonly property bool out: wheel.scaleShown && !inKey
                            width: sel ? 30 : 24
                            height: width
                            radius: width / 2
                            x: wheel.cx + Math.sin(a) * wheel.r - width / 2
                            y: wheel.cy - Math.cos(a) * wheel.r - height / 2
                            color: sel ? drawer.theme.accent : out ? drawer.theme.drawerCard : drawer.theme.graphBg
                            border.width: 1
                            border.color: sel ? drawer.theme.accentLight : inKey ? drawer.theme.drawerDim : drawer.theme.drawerCardEdge
                            Text {
                                anchors.centerIn: parent
                                text: drawer.notes[note.index]
                                color: note.sel ? "#141414" : note.inKey ? drawer.theme.drawerText
                                     : note.out ? drawer.theme.drawerFaint : drawer.theme.drawerDim
                                font.family: drawer.theme.fontPrint
                                font.pixelSize: 12
                                font.bold: note.sel
                            }
                        }
                    }
                    Column {
                        anchors.centerIn: parent
                        spacing: 0
                        Text {
                            readonly property bool off: drawer.keyIndex < 0
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: drawer.keyIndex >= 0 ? drawer.sc3.electricKey : drawer.keyOff ? "выкл" : "?"
                            color: off ? drawer.theme.drawerDim : drawer.theme.drawerText
                            font.family: drawer.keyOff ? drawer.theme.fontUi : drawer.theme.fontPrint
                            font.pixelSize: drawer.keyOff ? drawer.ts + 5 : 34
                            font.bold: !off
                        }
                        Label {
                            visible: text !== ""
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: drawer.keyLine()
                        }
                    }
                }
            }
        }

        // Scale ------------------------------------------------------------------------------
        Card {
            id: scaleCard
            theme: drawer.theme
            width: cards.inner * 0.21
            height: cards.height
            title: "Лад"
            ready: drawer.autotune !== null

            Item {
                Row {   // segmented choice
                    id: seg
                    readonly property int chosen: drawer.autotune ? drawer.scaleKeys.indexOf(drawer.autotune.scale) : -1
                    width: parent.width
                    height: 32
                    Repeater {
                        model: ["Мажор", "Минор", "Все 12"]
                        delegate: Rectangle {
                            required property string modelData
                            required property int index
                            readonly property bool on: index === seg.chosen
                            width: seg.width / 3
                            height: seg.height
                            color: on ? Qt.alpha(drawer.theme.accent, 0.14) : drawer.theme.graphBg
                            border.width: 1
                            border.color: on ? drawer.theme.accent : drawer.theme.drawerCardEdge
                            Text {
                                anchors.centerIn: parent
                                text: parent.modelData
                                color: parent.on ? drawer.theme.accent : drawer.theme.drawerText
                                font.family: drawer.theme.fontUi
                                font.pixelSize: drawer.ts - 0.5
                                font.bold: parent.on
                            }
                        }
                    }
                }

                // One octave from C: notes the voice will be pulled to.
                Item {
                    id: kb
                    y: 48
                    width: parent.width
                    height: 92
                    readonly property real ww: width / 7
                    readonly property var whites: [0, 2, 4, 5, 7, 9, 11]
                    readonly property var blacks: [[1, 1], [3, 2], [6, 4], [8, 5], [10, 6]]   // semitone, after white n
                    Repeater {
                        model: kb.whites
                        delegate: Rectangle {
                            required property int modelData
                            required property int index
                            readonly property bool on: drawer.inScale(modelData)
                            x: index * kb.ww
                            width: kb.ww - 2
                            height: kb.height
                            radius: 2
                            color: on ? "#e9e9e9" : "#7a7a7a"
                            border.width: 1
                            border.color: "#101010"
                            Rectangle {
                                visible: parent.on
                                anchors.horizontalCenter: parent.horizontalCenter
                                y: parent.height - 16
                                width: 8
                                height: 8
                                radius: 4
                                color: drawer.theme.accent
                            }
                        }
                    }
                    Repeater {
                        model: kb.blacks
                        delegate: Rectangle {
                            required property var modelData
                            readonly property bool on: drawer.inScale(modelData[0])
                            x: modelData[1] * kb.ww - width / 2 - 1
                            width: kb.ww * 0.6
                            height: kb.height * 0.6
                            radius: 2
                            color: on ? "#5a5a5a" : "#151515"
                            border.width: 1
                            border.color: "#000000"
                        }
                    }
                }
                Label {
                    y: 150
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: drawer.scaleLine()
                    font.pixelSize: drawer.ts - 2
                    lineHeight: 1.1
                }
            }
        }

        // Speed -------------------------------------------------------------------------------
        Card {
            id: speedCard
            theme: drawer.theme
            width: cards.inner * 0.2
            height: cards.height
            title: "Скорость коррекции"
            ready: drawer.autotune !== null && !!drawer.autotune.speed

            Item {
                Text {
                    text: drawer.autotune.speed.value
                    color: drawer.theme.drawerText
                    font.family: drawer.theme.fontUi
                    font.pixelSize: drawer.ts + 13
                    font.bold: true
                }
                Label {
                    y: 38
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: "Чем быстрее, тем заметнее «роботизированный» эффект."
                    font.pixelSize: drawer.ts - 2
                    lineHeight: 1.1
                }
                Item {   // slider: robot .. natural
                    y: 92
                    width: parent.width
                    height: 34
                    readonly property real f: drawer.autotune.speed.fraction || 0
                    Rectangle {
                        id: track
                        y: 6
                        width: parent.width
                        height: 6
                        radius: 3
                        color: drawer.theme.barTrack
                    }
                    Rectangle {
                        y: track.y
                        width: track.width * parent.f
                        height: track.height
                        radius: 3
                        color: drawer.theme.accent
                    }
                    Rectangle {
                        x: track.width * parent.f - 7
                        y: 2
                        width: 14
                        height: 14
                        radius: 7
                        color: drawer.theme.accentLight
                        border.width: 1
                        border.color: drawer.theme.accent
                    }
                    Label { y: 20; text: "робот"; font.pixelSize: 11 }
                    Label { y: 20; anchors.right: parent.right; text: "естественно"; font.pixelSize: 11 }
                }
                Column {
                    y: 136
                    width: parent.width
                    spacing: 3
                    Repeater {
                        model: drawer.autotune.rows || []
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

        // What it does --------------------------------------------------------------------------
        Card {
            id: curveCard
            theme: drawer.theme
            width: cards.inner * 0.37
            height: cards.height
            title: "Как это звучит"
            ready: drawer.autotune !== null && drawer.keyIndex >= 0
            pendingText: drawer.keyPending

            Item {
                Item {
                    id: plot
                    readonly property real padL: 26
                    readonly property real padB: 16
                    width: parent.width
                    height: parent.height - 2
                    readonly property real pw: width - padL
                    readonly property real ph: height - padB
                    readonly property int lo: -1      // semitones relative to C4, plot range
                    readonly property int hi: 9
                    function px(t) { return padL + pw * t / 2.0; }
                    function py(s) { return ph * (1 - (s - lo) / (hi - lo)); }

                    // An example sung phrase (semitones over C, 2 s) - an illustration, not
                    // SC3 data - and the same phrase pulled to the notes of the key and scale.
                    readonly property var sung: {
                        const seg = [[0.0, 0.3], [0.45, 4.25], [0.95, 6.7], [1.45, 4.2]];   // start s, sung note
                        const pts = [];
                        for (let i = 0; i <= 200; ++i) {
                            const t = i / 100;
                            let k = 0;
                            while (k < seg.length - 1 && t >= seg[k + 1][0]) ++k;
                            const prev = k > 0 ? seg[k - 1][1] : seg[0][1];
                            const u = Math.min(1, (t - seg[k][0]) / 0.12);          // 120 ms glide
                            const vib = 0.2 * Math.sin(t * 2 * Math.PI * 5.5) + 0.06 * Math.sin(t * 13.1);
                            pts.push({ t: t, s: prev + (seg[k][1] - prev) * u + vib });
                        }
                        return pts;
                    }
                    // Notes of the key and scale inside the plot: [semitone over C, name]
                    readonly property var lanes: {
                        const out = [];
                        for (let s = lo + 1; s <= hi; ++s)
                            if (drawer.inScale((s + 12) % 12))
                                out.push([s, drawer.notes[(s + 12) % 12]]);
                        return out;
                    }
                    function snap(s) {
                        let best = lanes.length ? lanes[0][0] : s;
                        for (const n of lanes) if (Math.abs(n[0] - s) < Math.abs(best - s)) best = n[0];
                        return best;
                    }
                    // Pull per 10 ms step: the speed is the time to cover ~80 % of the way to
                    // the note (0.45^2 of it is left after two steps at 20 ms).
                    readonly property real pull: drawer.autotune.speedMs > 0
                                                 ? 1 - Math.pow(0.45, 20 / drawer.autotune.speedMs) : 1
                    readonly property var sungPath: sung.map(p => Qt.point(px(p.t), py(p.s)))
                    readonly property var fixedPath: {
                        const pts = [];
                        let cur = sung[0].s;
                        for (const p of sung) {
                            cur += (snap(p.s) - cur) * pull;
                            pts.push(Qt.point(px(p.t), py(cur)));
                        }
                        return pts;
                    }

                    Rectangle {
                        x: plot.padL
                        width: plot.pw
                        height: plot.ph
                        radius: 3
                        color: drawer.theme.graphBg
                        border.width: 1
                        border.color: drawer.theme.graphGrid
                    }
                    Repeater {   // note lanes
                        model: plot.lanes
                        delegate: Item {
                            required property var modelData
                            Rectangle {
                                x: plot.padL
                                y: plot.py(parent.modelData[0])
                                width: plot.pw
                                height: 1
                                color: drawer.theme.graphGridStrong
                            }
                            Text {
                                x: plot.padL - implicitWidth - 6
                                y: plot.py(parent.modelData[0]) - implicitHeight / 2
                                text: parent.modelData[1]
                                color: drawer.theme.drawerFaint
                                font.family: drawer.theme.fontPrint
                                font.pixelSize: 11
                            }
                        }
                    }
                    Shape {
                        anchors.fill: parent
                        preferredRendererType: Shape.CurveRenderer
                        ShapePath {
                            strokeColor: drawer.theme.drawerDim
                            strokeWidth: 1.5
                            strokeStyle: ShapePath.DashLine
                            dashPattern: [2, 2]
                            fillColor: "transparent"
                            PathPolyline { path: plot.sungPath }
                        }
                        ShapePath {
                            strokeColor: drawer.theme.graphCurve
                            strokeWidth: 2.2
                            fillColor: "transparent"
                            joinStyle: ShapePath.RoundJoin
                            PathPolyline { path: plot.fixedPath }
                        }
                    }
                    Row {
                        x: plot.padL
                        y: plot.ph + 2
                        spacing: 14
                        Row {
                            spacing: 5
                            Rectangle { width: 14; height: 2; y: 6; color: drawer.theme.drawerDim }
                            Label { text: "как спето"; font.pixelSize: 11 }
                        }
                        Row {
                            spacing: 5
                            Rectangle { width: 14; height: 2; y: 6; color: drawer.theme.graphCurve }
                            Label { text: "после автотюна"; font.pixelSize: 11 }
                        }
                    }
                    Label {
                        anchors.right: parent.right
                        y: plot.ph + 2
                        text: "2 с"
                        font.pixelSize: 11
                    }
                }
            }
        }
    }
}
