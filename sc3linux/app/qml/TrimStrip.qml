import QtQuick

// Thin strip under the body, outside it (owner's choice after v1): the software trims
// for MIC and LINE IN sit right under their channel columns, so the body itself stays
// exactly like a real SC3. HEADPHONE and LINE OUT columns say they live on the body.
// Positions follow the panel's channel columns: `panelX` is the strip's x inside the
// panel's coordinate system (the strip is usually inset from the body's edges).
Rectangle {
    id: strip
    required property Tokens theme
    required property QtObject sc3     // Backend (app) or DemoState (mock-ups): same shape
    required property real panelW
    property real panelX: 0
    property var keyX: [0.291, 0.430, 0.570, 0.709]

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

    // Left end, under the ELECTRIC column: what these knobs are (and, before the write path
    // exists, that they are not there yet - DECISIONS.md, 4).
    readonly property bool trimsKnown: known("trimMic") && known("trimLineIn")
    Caption {
        x: strip.cx(0.062)
        text: "Поправка к ползункам"
        anchors.verticalCenterOffset: strip.trimsKnown ? 0 : -7
    }
    Caption {
        visible: !strip.trimsKnown
        x: strip.cx(0.062)
        text: "появится с записью в SC3"
        color: Qt.darker(strip.theme.stripText, 1.35)
        font.pixelSize: strip.theme.uiTextSize - 2
        anchors.verticalCenterOffset: 8
    }

    // Trims under MIC and LINE IN. Without a write path to the SC3 (DECISIONS.md, 4) the app
    // has no trim yet: the knob stays empty and says when it comes.
    Repeater {
        model: [[0, strip.sc3.trimMic, "trimMic"], [1, strip.sc3.trimLineIn, "trimLineIn"]]
        delegate: Item {
            id: cell
            required property var modelData
            readonly property bool known: strip.known(modelData[2])
            readonly property real column: strip.cx(strip.keyX[modelData[0]])
            x: column - width / 2
            width: trim.width
            height: strip.height
            TrimKnob {
                id: trim
                theme: strip.theme
                anchors.verticalCenter: parent.verticalCenter
                opacity: strip.frozen || strip.offline ? 0.45 : 1
                knobSize: 24
                textSize: 13
                db: cell.modelData[1]
                known: cell.known
            }
            LockBadge {
                visible: strip.frozen
                theme: strip.theme
                size: 18
                x: cell.column - 52 - cell.x
                anchors.verticalCenter: parent.verticalCenter
            }
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
}
