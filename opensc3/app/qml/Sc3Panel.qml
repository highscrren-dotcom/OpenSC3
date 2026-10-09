import QtQuick

// fifine AmpliGame SC3, strictly from above. All positions are fractions of the
// body's width W and depth D from design/sc3-layout.md §2.3 (x to the right,
// y towards the user), so the panel scales with its width and keeps 164:113.
// Body print is English as on the serial unit; the fifine logo is replaced by "SC3".
Item {
    id: panel
    objectName: "sc3Panel"             // tests find it (and the faders below) by name
    required property Tokens theme
    required property QtObject sc3     // Backend (app) or DemoState (mock-ups): same shape

    property string section: ""          // drawer open for this section: amber frame around it
    property string forcedTip: ""        // mock-ups: tooltip without hover
    property string forcedFocus: ""      // mock-ups: keyboard focus without a keyboard
    property string hoverTip: ""
    property string pressTip: ""         // a fader cap was pressed or dragged: why it does not move
    readonly property string tipId: forcedTip !== "" ? forcedTip : pressTip !== "" ? pressTip : hoverTip
    readonly property string focusId: forcedFocus !== "" ? forcedFocus : muteHit.activeFocus ? "muteMic" : ""

    // A field the app does not know is drawn neutral: no light, no guessed cap position.
    function known(name) { return !(panel.sc3.unknown && panel.sc3.unknown[name] === true); }
    // Lit by the poll's guess, not read: the SC3 MUTE only zeroes the volume (RESEARCH.md §14).
    function guessed(name) { return !!(panel.sc3.guess && panel.sc3.guess[name] === true); }
    readonly property string micGuessNote: guessed("muteMic")
        ? "\n≈ MUTE на корпусе — по догадке: громкость резко упала до 0" : ""
    function hover(on, id) {
        if (on)
            hoverTip = id;
        else if (hoverTip === id)
            hoverTip = "";
    }

    signal sectionClicked(string name)
    signal micMuteClicked()

    implicitWidth: 1120
    implicitHeight: Math.round(width * 113 / 164)

    readonly property real w: width
    readonly property real d: height
    function fx(f) { return f * w; }
    function fy(f) { return f * d; }

    // Type sizes from the text frames on the drawing (frame ~ 1.15 x pixel size).
    readonly property real textLabel: d * 0.0195     // MIC, MUTE, notes, voices, ELECTRIC
    readonly property real textCustom: d * 0.0178
    readonly property real textLetter: d * 0.034
    readonly property real text48v: d * 0.0235
    readonly property real textKey: d * 0.0182

    // Columns and rows (§2.3)
    readonly property real padW: fx(0.131)
    readonly property real colL: 0.1275
    readonly property real colR: 0.8715
    readonly property var channelX: [0.294, 0.433, 0.571, 0.711]     // fader slots
    readonly property var keyX: [0.291, 0.430, 0.570, 0.709]         // bottom row
    readonly property var noteX: [0.0473, 0.0790, 0.1103, 0.1422, 0.1737, 0.2052]
    readonly property var voiceX: [0.8153, 0.8762, 0.9370]

    // Live level -> brightness of LED i (0 = next to the divider). Fractional edge
    // gives the meter a soft, "live" front instead of a hard step.
    function meterLevel(level, i) {
        return Math.max(0, Math.min(1, level * 9 - i));
    }

    // ---------------------------------------------------------------- body
    Chassis {
        anchors.fill: parent
        theme: panel.theme
        radius: panel.fx(0.038)
    }

    // Where the fifine logo is: a neutral mark.
    PrintText {
        theme: panel.theme
        cx: panel.fx(0.5)
        cy: panel.fy(0.067)
        size: panel.d * 0.033
        color: panel.theme.logo
        font.letterSpacing: size * 0.18
        text: "SC3"
    }

    // ---------------------------------------------------------------- level strip 9 + 9
    Glyph {
        x: panel.fx(0.222) - width / 2
        y: panel.fy(0.145) - height / 2
        size: panel.d * 0.047
        stroke: 1.7
        color: panel.theme.ink
        strokePath: Icons.micStroke
    }
    Glyph {
        x: panel.fx(0.780) - width / 2
        y: panel.fy(0.145) - height / 2
        size: panel.d * 0.045
        stroke: 1.9
        color: panel.theme.ink
        strokePath: Icons.phonesStroke
        fillPath: Icons.phonesFill
    }
    Rectangle {
        x: panel.fx(0.5) - width / 2
        y: panel.fy(0.145) - height / 2
        width: Math.max(2, panel.fx(0.0024))
        height: panel.fy(0.052)
        radius: width / 2
        color: panel.theme.ink
    }
    // Left half: to the PC (microphone), grows from the centre to the left.
    Repeater {
        model: 9
        delegate: Lamp {
            required property int index
            readonly property int fromCentre: 8 - index
            theme: panel.theme
            width: panel.fx(0.0132)
            height: panel.fy(0.036)
            x: panel.fx(0.2578 + index * 0.02724) - width / 2
            y: panel.fy(0.145) - height / 2
            level: panel.meterLevel(panel.sc3.levelIn, fromCentre)
            color: panel.theme.meterColors[fromCentre]
        }
    }
    // Right half: from the PC (headphones), grows from the centre to the right.
    Repeater {
        model: 9
        delegate: Lamp {
            required property int index
            theme: panel.theme
            width: panel.fx(0.0132)
            height: panel.fy(0.036)
            x: panel.fx(0.5243 + index * 0.02724) - width / 2
            y: panel.fy(0.145) - height / 2
            level: panel.meterLevel(panel.sc3.levelOut, index)
            color: panel.theme.meterColors[index]
        }
    }

    // ---------------------------------------------------------------- left column
    Pad {
        id: pad48v
        theme: panel.theme
        x: panel.fx(panel.colL) - width / 2
        y: panel.fy(0.2145) - height / 2
        width: panel.padW
        height: panel.fy(0.105)
        text: "48V"
        textSize: panel.text48v
        lit: panel.sc3.phantom
        locked: true
    }

    // ELECTRIC: 12 keys around the pad, chromatic circle clockwise.
    Repeater {
        model: [["A", 0, 0], ["Bb", 1, 0], ["B", 2, 0], ["C", 3, 0], ["Db", 4, 0], ["D", 5, 0],
                ["Ab", 0, 1], ["G", 1, 1], ["Gb", 2, 1], ["F", 3, 1], ["E", 4, 1], ["Eb", 5, 1]]
        delegate: Item {
            id: note
            required property var modelData
            readonly property string name: modelData[0]
            readonly property real nx: panel.noteX[modelData[1]]
            readonly property bool below: modelData[2] === 1
            Lamp {
                theme: panel.theme
                width: panel.fx(0.0095)
                height: width
                x: panel.fx(note.nx) - width / 2
                y: panel.fy(note.below ? 0.527 : 0.302) - height / 2
                level: panel.sc3.electricKey === note.name ? 1 : 0
                color: panel.theme.dotOn
                offColor: panel.theme.dotOff
                edgeColor: Qt.darker(panel.theme.dotOff, 1.6)
                glow: panel.theme.lightGlow
                halo: panel.theme.lightHalo
            }
            PrintText {
                theme: panel.theme
                cx: panel.fx(note.nx)
                cy: panel.fy(note.below ? 0.507 : 0.333)
                size: panel.textLabel
                text: note.name
            }
        }
    }

    Pad {
        id: padElectric
        theme: panel.theme
        x: panel.fx(panel.colL) - width / 2
        y: panel.fy(0.4145) - height / 2
        width: panel.padW
        height: panel.fy(0.131)
        text: "ELECTRIC"
        textSize: panel.textLabel
        lit: panel.sc3.electricKey !== ""
    }
    Pad {
        id: padA
        theme: panel.theme
        x: panel.fx(panel.colL) - width / 2
        y: panel.fy(0.626) - height / 2
        width: panel.padW
        height: panel.fy(0.130)
        text: "CUSTOM"
        letter: "A"
        textSize: panel.textCustom
        letterSize: panel.textLetter
        lit: panel.sc3.customLit === "A"
    }
    Pad {
        id: padC
        theme: panel.theme
        x: panel.fx(panel.colL) - width / 2
        y: panel.fy(0.8195) - height / 2
        width: panel.padW
        height: panel.fy(0.131)
        text: "CUSTOM"
        letter: "C"
        textSize: panel.textCustom
        letterSize: panel.textLetter
        lit: panel.sc3.customLit === "C"
    }

    // ---------------------------------------------------------------- right column
    Pad {
        id: padRgb
        theme: panel.theme
        x: panel.fx(panel.colR) - width / 2
        y: panel.fy(0.2145) - height / 2
        width: panel.padW
        height: panel.fy(0.105)
        sun: true
        letterSize: panel.textLetter
        locked: true
    }

    // CHANGE VOICE: six voices, label between dot and pad.
    Repeater {
        model: [["Male", 0, 0], ["Female", 1, 0], ["Robot", 2, 0],
                ["Monster", 0, 1], ["Baby", 1, 1], ["Elder", 2, 1]]
        delegate: Item {
            id: voice
            required property var modelData
            readonly property string name: modelData[0]
            readonly property real vx: panel.voiceX[modelData[1]]
            readonly property bool below: modelData[2] === 1
            Lamp {
                theme: panel.theme
                width: panel.fx(0.0095)
                height: width
                x: panel.fx(voice.vx) - width / 2
                y: panel.fy(voice.below ? 0.527 : 0.304) - height / 2
                level: panel.sc3.voice === voice.name ? 1 : 0
                color: panel.theme.dotOn
                offColor: panel.theme.dotOff
                edgeColor: Qt.darker(panel.theme.dotOff, 1.6)
                glow: panel.theme.lightGlow
                halo: panel.theme.lightHalo
            }
            PrintText {
                theme: panel.theme
                cx: panel.fx(voice.vx)
                cy: panel.fy(voice.below ? 0.505 : 0.333)
                size: panel.textLabel
                text: voice.name
            }
        }
    }

    Pad {
        id: padVoice
        theme: panel.theme
        x: panel.fx(panel.colR) - width / 2
        y: panel.fy(0.4145) - height / 2
        width: panel.padW
        height: panel.fy(0.131)
        text: "CHANGE\nVOICE"
        textSize: panel.textLabel
        lit: panel.sc3.voice !== ""
    }
    Pad {
        id: padB
        theme: panel.theme
        x: panel.fx(panel.colR) - width / 2
        y: panel.fy(0.626) - height / 2
        width: panel.padW
        height: panel.fy(0.130)
        text: "CUSTOM"
        letter: "B"
        textSize: panel.textCustom
        letterSize: panel.textLetter
        lit: panel.sc3.customLit === "B"
    }
    Pad {
        id: padD
        theme: panel.theme
        x: panel.fx(panel.colR) - width / 2
        y: panel.fy(0.8195) - height / 2
        width: panel.padW
        height: panel.fy(0.131)
        text: "CUSTOM"
        letter: "D"
        textSize: panel.textCustom
        letterSize: panel.textLetter
        lit: panel.sc3.customLit === "D"
    }

    // ---------------------------------------------------------------- faders
    // "+" above and "-" below the scales, between neighbouring channels.
    Repeater {
        model: [0.3635, 0.502, 0.641]
        delegate: Item {
            id: sign
            required property real modelData
            readonly property real s: panel.fx(0.015)
            readonly property real t: panel.theme.tickWidth
            Rectangle {   // plus, horizontal
                x: panel.fx(sign.modelData) - sign.s / 2
                y: panel.fy(0.2535) - sign.t / 2
                width: sign.s
                height: sign.t
                color: panel.theme.tick
            }
            Rectangle {   // plus, vertical
                x: panel.fx(sign.modelData) - sign.t / 2
                y: panel.fy(0.2535) - sign.s / 2
                width: sign.t
                height: sign.s
                color: panel.theme.tick
            }
            Rectangle {   // minus
                x: panel.fx(sign.modelData) - sign.s * 0.45
                y: panel.fy(0.7129) - sign.t / 2
                width: sign.s * 0.9
                height: sign.t
                color: panel.theme.tick
            }
        }
    }

    Fader {
        id: faderMic
        objectName: "faderMic"
        theme: panel.theme
        panelW: panel.w
        panelD: panel.d
        width: panel.fx(0.139)
        height: panel.d
        x: panel.fx(panel.channelX[0]) - width / 2
        value: panel.sc3.faderMic
        known: panel.known("faderMic")
    }
    Fader {
        id: faderLineIn
        objectName: "faderLineIn"
        theme: panel.theme
        panelW: panel.w
        panelD: panel.d
        width: panel.fx(0.139)
        height: panel.d
        x: panel.fx(panel.channelX[1]) - width / 2
        value: panel.sc3.faderLineIn
        known: panel.known("faderLineIn")
    }
    Fader {
        id: faderHeadphone
        objectName: "faderHeadphone"
        theme: panel.theme
        panelW: panel.w
        panelD: panel.d
        width: panel.fx(0.139)
        height: panel.d
        x: panel.fx(panel.channelX[2]) - width / 2
        value: panel.sc3.faderHeadphone
        known: panel.known("faderHeadphone")
        locked: true
    }
    Fader {
        id: faderLineOut
        objectName: "faderLineOut"
        theme: panel.theme
        panelW: panel.w
        panelD: panel.d
        width: panel.fx(0.139)
        height: panel.d
        x: panel.fx(panel.channelX[3]) - width / 2
        value: panel.sc3.faderLineOut
        known: panel.known("faderLineOut")
        locked: true
    }

    // ---------------------------------------------------------------- bottom row
    Repeater {
        model: ["MIC", "LINE IN", "HEADPHONE", "LINE OUT"]
        delegate: PrintText {
            required property string modelData
            required property int index
            theme: panel.theme
            cx: panel.fx(panel.keyX[index])
            cy: panel.fy(0.811)
            size: panel.textLabel
            text: modelData
        }
    }

    KeyCap {
        id: keyMuteMic
        theme: panel.theme
        x: panel.fx(panel.keyX[0]) - width / 2
        y: panel.fy(0.887) - height / 2
        width: panel.fx(0.105)
        height: panel.fy(0.111)
        textSize: panel.textLabel
        text: "MUTE"
        lit: panel.sc3.muteMic && panel.known("muteMic")
        unknown: !panel.known("muteMic")
        guess: panel.guessed("muteMic")
        pressed: muteHit.pressed
    }
    KeyCap {
        id: keyMuteLineIn
        theme: panel.theme
        x: panel.fx(panel.keyX[1]) - width / 2
        y: panel.fy(0.887) - height / 2
        width: panel.fx(0.104)
        height: panel.fy(0.111)
        textSize: panel.textLabel
        text: "MUTE"
        lit: panel.sc3.muteLineIn && panel.known("muteLineIn")
        unknown: !panel.known("muteLineIn")
        guess: panel.guessed("muteLineIn")
    }
    KeyCap {
        id: keyMonitor
        theme: panel.theme
        x: panel.fx(panel.keyX[2]) - width / 2
        y: panel.fy(0.887) - height / 2
        width: panel.fx(0.105)
        height: panel.fy(0.111)
        textSize: panel.textKey
        text: "MIC\nMONITOR"
        lit: panel.sc3.micMonitor && panel.known("micMonitor")
        unknown: !panel.known("micMonitor")
    }
    KeyCap {
        id: keyMuteLineOut
        theme: panel.theme
        x: panel.fx(panel.keyX[3]) - width / 2
        y: panel.fy(0.887) - height / 2
        width: panel.fx(0.104)
        height: panel.fy(0.111)
        textSize: panel.textLabel
        text: "MUTE"
        lit: panel.sc3.muteLineOut && panel.known("muteLineOut")
        unknown: !panel.known("muteLineOut")
    }

    // ---------------------------------------------------------------- app overlays
    // (The trims live on the strip under the body - TrimStrip.qml - so the body stays
    // exactly as printed.)

    // Body-only pads carry a lock badge on their corner (brief #6).
    component CornerLock: LockBadge {
        required property Item target
        property bool inside: false     // ELECTRIC / CHANGE VOICE: labels sit right above them
        theme: panel.theme
        size: panel.fx(0.021)
        x: inside ? target.x + target.width - width - 7 : target.x + target.width - width * 0.65
        y: inside ? target.y + 7 : target.y - height * 0.35
    }
    CornerLock { target: pad48v }
    CornerLock { target: padRgb }

    // On air (or unknown) nothing may change the SC3 (CLAUDE.md rule 3): every control the
    // app could otherwise toggle gets the same lock. MIC MUTE stays available: the app mutes
    // the SC3 input in PipeWire instead (docs/DECISIONS.md, 8).
    Repeater {
        model: panel.sc3.frozen ? [padElectric, padVoice, keyMuteLineIn, keyMonitor, keyMuteLineOut] : []
        delegate: CornerLock {
            required property Item modelData
            target: modelData
            inside: modelData === padElectric || modelData === padVoice
        }
    }

    // Selected section (its drawer is open).
    readonly property var sections: ({
        "mic": [panel.channelX[0] - 0.0595, 0.226, 0.119, 0.962 - 0.226],
        "electric": [0.026, 0.283, 0.201, 0.262],
        "voice": [0.786, 0.283, 0.180, 0.262]
    })
    FocusRing {
        readonly property var r: panel.sections[panel.section] || [0, 0, 0, 0]
        visible: panel.section !== ""
        theme: panel.theme
        strength: 0.75
        radius: panel.fx(0.012)
        x: panel.fx(r[0])
        y: panel.fy(r[1])
        width: panel.fx(r[2])
        height: panel.fy(r[3])
    }

    // Microphone muted in PipeWire, not on the body: the key stays dark (the SC3 does
    // not know), an amber mark on it says the app holds the mute.
    Rectangle {
        visible: panel.sc3.pipewireMute
        x: keyMuteMic.x + (keyMuteMic.width - width) / 2
        y: keyMuteMic.y + 8
        width: pwRow.implicitWidth + 14
        height: 20
        radius: 10
        color: panel.theme.accent
        Row {
            id: pwRow
            anchors.centerIn: parent
            spacing: 4
            Item {
                width: 14
                height: 14
                anchors.verticalCenter: parent.verticalCenter
                Glyph { size: 14; stroke: 2.4; color: "#141414"; strokePath: Icons.micStroke }
                Glyph { size: 14; stroke: 2.6; color: "#141414"; strokePath: Icons.slash }
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "PipeWire"
                color: "#141414"
                font.family: panel.theme.fontUi
                font.pixelSize: 12
                font.bold: true
            }
        }
    }

    // Keyboard focus.
    FocusRing {
        visible: panel.focusId === "muteMic"
        theme: panel.theme
        radius: keyMuteMic.radius
        anchors.fill: keyMuteMic
        anchors.margins: -panel.theme.focusGap
    }

    // ---------------------------------------------------------------- pointer
    // Click on a section opens its drawer (brief #4).
    Repeater {
        model: ["mic", "electric", "voice"]
        delegate: MouseArea {
            required property string modelData
            readonly property var r: panel.sections[modelData]
            x: panel.fx(r[0])
            y: panel.fy(r[1])
            width: panel.fx(r[2])
            height: panel.fy(r[3])
            cursorShape: Qt.PointingHandCursor
            onClicked: panel.sectionClicked(modelData)
        }
    }

    // Hover on a body-only or unknown control: what it is and why the app cannot touch it.
    Repeater {
        model: [
            { tip: "48v", item: pad48v }, { tip: "rgb", item: padRgb },
            { tip: "custom-A", item: padA }, { tip: "custom-B", item: padB },
            { tip: "custom-C", item: padC }, { tip: "custom-D", item: padD },
            { tip: "key-linein", item: keyMuteLineIn }, { tip: "key-monitor", item: keyMonitor },
            { tip: "key-lineout", item: keyMuteLineOut },
            { tip: "fader-mic", item: faderMic.capItem, fader: faderMic },
            { tip: "fader-linein", item: faderLineIn.capItem, fader: faderLineIn },
            { tip: "fader-hp", item: faderHeadphone.capItem, fader: faderHeadphone },
            { tip: "fader-lo", item: faderLineOut.capItem, fader: faderLineOut }
        ]
        delegate: MouseArea {
            required property var modelData
            readonly property real dx: modelData.fader ? modelData.fader.x : 0
            x: modelData.item.x + dx
            y: modelData.item.y
            width: modelData.item.width
            height: modelData.item.height
            hoverEnabled: true
            acceptedButtons: Qt.NoButton     // clicks go on to the section under it
            onContainsMouseChanged: panel.hover(containsMouse, modelData.tip)
        }
    }

    // Fader caps are a mirror of the real ones (no motor): pressing or dragging one does not move
    // it, it says where to move it. Above the section areas, so it does not toggle the MIC drawer.
    Timer {
        id: pressTipTimer
        interval: 4000
        onTriggered: panel.pressTip = ""
    }
    Repeater {
        model: [{ tip: "drag-mic", fader: faderMic }, { tip: "drag-linein", fader: faderLineIn },
                { tip: "drag-hp", fader: faderHeadphone }, { tip: "drag-lo", fader: faderLineOut }]
        delegate: MouseArea {
            required property var modelData
            readonly property Item cap: modelData.fader.capItem
            x: modelData.fader.x + cap.x - 4
            y: cap.y - 4
            width: cap.width + 8
            height: cap.height + 8
            preventStealing: true
            onPressed: {
                pressTipTimer.stop();
                panel.pressTip = modelData.tip;
            }
            onReleased: pressTipTimer.restart()
            onCanceled: pressTipTimer.restart()
        }
    }

    // MIC MUTE: the one control the app drives - through PipeWire (DECISIONS.md, 8).
    MouseArea {
        id: muteHit
        anchors.fill: keyMuteMic
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        activeFocusOnTab: true
        onClicked: panel.micMuteClicked()
        Keys.onSpacePressed: panel.micMuteClicked()
        onContainsMouseChanged: panel.hover(containsMouse, panel.sc3.frozen ? "mute-onair" : "mute-pw")
    }

    // What a tooltip says and where it points: side is where the tip sits relative to its target.
    function tipInfo(id) {
        const lockText = "только на корпусе";
        const readOnly = panel.sc3.frozen ? "идёт эфир — изменения выключены"
                                          : "только просмотр: запись в SC3 появится позже";
        const unknownText = panel.sc3.frozen ? "SC3 в эфире не читаем"
                                             : panel.sc3.connected ? "SC3 ещё не прочитан — «Обновить» в шапке"
                                                                   : "SC3 не на связи";
        function capRect(f) { return Qt.rect(f.x + f.capItem.x, f.capItem.y, f.capItem.width, f.capItem.height); }
        // HEADPHONE and LINE OUT sit right of centre: their tips open to the left, inside the window.
        function fader(f, name) {
            return { target: capRect(f), side: f.locked ? "left" : "right", title: name, lock: f.locked,
                     text: f.locked ? lockText + ": с ПК его не прочитать" : f.known ? "" : "положение неизвестно: " + unknownText };
        }
        function rectOf(item) { return Qt.rect(item.x, item.y, item.width, item.height); }
        const mirror = "Это зеркало ползунка на корпусе — двигайте его на SC3.";
        function drag(f, name, trim) {
            return { target: capRect(f), side: f.locked ? "left" : "right", title: name, lock: f.locked,
                     text: f.locked ? lockText + ": двигайте его на SC3,\nс ПК его не прочитать и не поменять"
                                    : mirror + "\n" + trim };
        }
        switch (id) {
        case "rgb": return { target: rectOf(padRgb), side: "left", title: "Подсветка RGB", text: lockText, lock: true };
        case "48v": return { target: rectOf(pad48v), side: "right", title: "Фантомное питание 48V", text: lockText, lock: true };
        case "custom":
        case "custom-B": return { target: rectOf(padB), side: "left", title: "CUSTOM B — звуковой пэд", lock: true,
                                  text: lockText + ": держите — запись до 15 с,\nнажмите — воспроизведение" };
        case "custom-D": return { target: rectOf(padD), side: "left", title: "CUSTOM D — звуковой пэд", lock: true,
                                  text: lockText + ": держите — запись до 15 с,\nнажмите — воспроизведение" };
        case "custom-A": return { target: rectOf(padA), side: "right", title: "CUSTOM A — звуковой пэд", lock: true,
                                  text: lockText + ": держите — запись до 15 с,\nнажмите — воспроизведение" };
        case "custom-C": return { target: rectOf(padC), side: "right", title: "CUSTOM C — звуковой пэд", lock: true,
                                  text: lockText + ": держите — запись до 15 с,\nнажмите — воспроизведение" };
        case "mute-onair": return { target: rectOf(keyMuteMic), side: "above", shift: 40, gap: 24, lock: false,
                                    title: "В эфире — заглушение через PipeWire",
                                    text: "как mute в KDE: клавиша на корпусе не загорится" + panel.micGuessNote };
        case "mute-pw": return { target: rectOf(keyMuteMic), side: "above", shift: 40, gap: 24, lock: false,
                                 title: "Заглушение через PipeWire",
                                 text: "как mute в KDE: клавиша на корпусе не загорится" + panel.micGuessNote };
        case "key-linein": return { target: rectOf(keyMuteLineIn), side: "above", gap: 24, lock: true,
                                    title: "MUTE LINE IN", text: readOnly + (panel.guessed("muteLineIn")
                                        ? "\n≈ по догадке: громкость резко упала до 0" : "") };
        case "key-monitor": return { target: rectOf(keyMonitor), side: "above", gap: 24, lock: true,
                                     title: "MIC MONITOR", text: readOnly };
        case "key-lineout": return { target: rectOf(keyMuteLineOut), side: "above", gap: 24, lock: true,
                                     title: "MUTE LINE OUT", text: readOnly };
        case "fader-mic": return panel.known("faderMic") ? null : fader(faderMic, "Ползунок MIC");
        case "fader-linein": return panel.known("faderLineIn") ? null : fader(faderLineIn, "Ползунок LINE IN");
        case "drag-mic": return drag(faderMic, "Ползунок MIC — зеркало", "Поправка в ПК — ручкой под панелью");
        case "drag-linein": return drag(faderLineIn, "Ползунок LINE IN — зеркало", "Поправка LINE IN появится позже");
        case "drag-hp": return drag(faderHeadphone, "Ползунок HEADPHONE");
        case "drag-lo": return drag(faderLineOut, "Ползунок LINE OUT");
        case "fader-hp": return fader(faderHeadphone, "Ползунок HEADPHONE");
        case "fader-lo": return fader(faderLineOut, "Ползунок LINE OUT");
        }
        return null;
    }

    Tip {
        id: tip
        readonly property var info: panel.tipInfo(panel.tipId)
        readonly property rect t: info ? info.target : Qt.rect(0, 0, 0, 0)
        readonly property string side: info ? info.side : "left"
        readonly property real shift: info && info.shift ? info.shift : 0
        visible: info !== null
        theme: panel.theme
        arrow: side === "left" ? "right" : side === "right" ? "left" : "down"
        arrowShift: -shift
        lock: info ? info.lock : false
        title: info ? info.title : ""
        text: info ? info.text : ""
        x: side === "left" ? t.x - width - 8 : side === "right" ? t.x + t.width + 8 : t.x + t.width / 2 - width / 2 + shift
        y: side === "above" ? t.y - height - (info && info.gap ? info.gap : 8) : t.y + t.height / 2 - height / 2
    }
}
