import QtQuick

// Thin strip under the body, outside it (owner's choice after v1): the software trims
// for MIC and LINE IN sit right under their channel columns, so the body itself stays
// exactly like a real SC3. HEADPHONE and LINE OUT columns say they live on the body.
// Positions follow the panel's channel columns: `panelX` is the strip's x inside the
// panel's coordinate system (the strip is usually inset from the body's edges).
//
// MIC trim is written to the SC3 (mic.trim, node 0xAC: to the PC only, after the fader;
// docs/WRITE.md): turned off air, with the write fuse on (header gear), it asks the backend,
// which writes on the next poll slot and reads back. LINE IN stays off until its path to the
// PC (node 0xAE) is proven.
Rectangle {
    id: strip
    required property Tokens theme
    required property QtObject sc3     // Backend (app) or DemoState (mock-ups): same shape
    required property real panelW
    property real panelX: 0
    property var keyX: [0.291, 0.430, 0.570, 0.709]
    property string forcedTip: ""      // mock-ups and screenshots: tooltip without a press

    readonly property bool frozen: sc3.frozen          // on air (or unknown): nothing may change the SC3
    readonly property bool offline: !sc3.connected
    function cx(f) { return f * panelW - panelX; }
    function known(name) { return !(sc3.unknown && sc3.unknown[name] === true); }

    implicitHeight: 40
    radius: theme.uiRadius + 2
    color: theme.stripBg
    border.width: 1
    border.color: theme.stripEdge

    component Caption: Text {
        color: strip.theme.stripText
        font.family: strip.theme.fontUi
        font.pixelSize: strip.theme.uiTextSize - 1
        anchors.verticalCenter: parent ? parent.verticalCenter : undefined
    }

    // Left end, under the ELECTRIC column: what these knobs are and, while the fuse is off,
    // that turning them does nothing (DECISIONS.md, 4: writing is the owner's switch).
    readonly property string captionNote: strip.offline || strip.frozen || strip.sc3.writeEnabled
                                          ? "" : "запись в SC3 выключена"
    Caption {
        x: strip.cx(0.062)
        text: "Поправка к ползункам"
        anchors.verticalCenterOffset: strip.captionNote !== "" ? -7 : 0
    }
    Caption {
        visible: strip.captionNote !== ""
        x: strip.cx(0.062)
        text: strip.captionNote
        color: Qt.darker(strip.theme.stripText, 1.35)
        font.pixelSize: strip.theme.uiTextSize - 2
        anchors.verticalCenterOffset: 8
    }

    // MIC: the trim the app writes.
    Item {
        id: micCell
        readonly property real column: strip.cx(strip.keyX[0])
        x: column - width / 2
        width: micKnob.width
        height: strip.height
        TrimKnob {
            id: micKnob
            objectName: "trimMic"            // tests find it by name
            theme: strip.theme
            anchors.verticalCenter: parent.verticalCenter
            opacity: strip.frozen || strip.offline ? 0.45 : 1
            knobSize: 24
            textSize: 13
            db: strip.sc3.trimMic
            known: strip.known("trimMic")
            interactive: known && !strip.frozen && !strip.offline
            writable: strip.sc3.writeEnabled
            pending: strip.sc3.trimMicPending
            onChangeRequested: v => strip.sc3.setMicTrim(v)
            onRefused: strip.showTip("trim-off")
            onHoveredChanged: strip.hover(hovered, "trim-mic")
        }
        LockBadge {
            visible: strip.frozen
            theme: strip.theme
            size: 18
            x: -width - 8                 // left of the knob
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    // LINE IN: not yet - its path to the PC is a guess until a probe proves it.
    Item {
        id: lineCell
        readonly property real column: strip.cx(strip.keyX[1])
        x: column - width / 2
        width: lineKnob.width
        height: strip.height
        TrimKnob {
            id: lineKnob
            theme: strip.theme
            anchors.verticalCenter: parent.verticalCenter
            opacity: 0.45
            knobSize: 24
            textSize: 13
            known: false
            blank: "LINE IN — позже"
        }
        MouseArea {
            anchors.fill: lineKnob
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
            onContainsMouseChanged: strip.hover(containsMouse, "trim-linein")
        }
        LockBadge {
            visible: strip.frozen
            theme: strip.theme
            size: 18
            x: -width - 8                 // left of the knob
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    // HEADPHONE and LINE OUT: no software control, say so quietly.
    Repeater {
        model: strip.frozen ? [] : [2, 3]
        delegate: Row {
            required property int modelData
            x: strip.cx(strip.keyX[modelData]) - width / 2
            anchors.verticalCenter: parent.verticalCenter
            spacing: 5
            opacity: 0.8
            Glyph {
                anchors.verticalCenter: parent.verticalCenter
                size: 14
                stroke: 2.2
                color: strip.theme.stripText
                strokePath: Icons.lockStroke
                fillPath: Icons.lockFill
            }
            Caption { text: "на корпусе" }
        }
    }

    // On air: why everything is locked, under the HEADPHONE / LINE OUT columns.
    Caption {
        visible: strip.frozen
        x: strip.cx(0.515)
        text: strip.sc3.live === "on" ? "Идёт эфир — во время эфира изменения выключены"
                                      : "Эфир не определён — изменения выключены"
        color: strip.theme.headerText
    }

    // Tooltips above the strip (over the panel's bottom edge): hover, or a refused turn.
    property string hoverTip: ""
    property string pressTip: ""
    readonly property string tipId: forcedTip !== "" ? forcedTip : pressTip !== "" ? pressTip
                                  : micKnob.dragging ? "" : hoverTip
    function hover(on, id) {
        if (on)
            hoverTip = id;
        else if (hoverTip === id)
            hoverTip = "";
    }
    function showTip(id) {
        pressTip = id;
        pressTipTimer.restart();
    }
    Timer {
        id: pressTipTimer
        interval: 4000
        onTriggered: strip.pressTip = ""
    }
    function tipInfo(id) {
        switch (id) {
        case "trim-off": return { cell: micCell, lock: true, title: "Запись в SC3 выключена — включите в настройках",
                                  text: "шестерёнка в шапке → «Разрешить запись в SC3»" };
        case "trim-mic": return strip.sc3.writeEnabled && micKnob.interactive
                         ? { cell: micCell, lock: false, title: "Поправка MIC — в ПК, после ползунка",
                             text: "тяните вверх-вниз или крутите колёсиком, шаг 0,5 дБ\n"
                                   + "двойной щелчок — 0 дБ · в наушниках не слышно" } : null;
        case "trim-linein": return { cell: lineCell, lock: true, title: "Поправка LINE IN — позже",
                                     text: "путь LINE IN в ПК (узел 0xAE) ещё не проверен пробой" };
        }
        return null;
    }
    Tip {
        id: tip
        objectName: "trimTip"
        readonly property var info: strip.tipInfo(strip.tipId)
        readonly property Item cell: info ? info.cell : micCell
        visible: info !== null
        theme: strip.theme
        arrow: "down"
        lock: info ? info.lock : false
        title: info ? info.title : ""
        text: info ? info.text : ""
        x: cell.x + 12 - width / 2          // arrow at the knob's centre
        y: -height - 4
    }
}
