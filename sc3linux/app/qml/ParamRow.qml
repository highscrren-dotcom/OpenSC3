import QtQuick

// One parameter in a drawer: name, value, and a thin bar showing where the value
// sits in its range. `centre` > 0 makes the bar bipolar around that fraction.
// `row` fills it from one row of drawer data: { label, value, fraction, centre? }
// (sc3.dsp, see design/panel/scenes/demo-dsp.js); explicit properties win over it.
Item {
    id: param
    required property Tokens theme
    property var row: null
    property string label: row ? row.label || "" : ""
    property string value: row ? row.value || "" : ""
    property real fraction: row ? row.fraction || 0 : 0.5
    property real centre: row ? row.centre || 0 : 0
    property bool active: false        // the parameter being edited: accent bar

    implicitHeight: 31
    readonly property real lo: Math.min(centre, fraction)
    readonly property real hi: Math.max(centre, fraction)

    Text {
        text: param.label
        color: param.theme.drawerDim
        font.family: param.theme.fontUi
        font.pixelSize: param.theme.uiTextSize - 0.5
    }
    Text {
        anchors.right: parent.right
        text: param.value
        color: param.active ? param.theme.accent : param.theme.drawerText
        font.family: param.theme.fontValue
        font.pixelSize: param.theme.uiTextSize
        font.bold: true
        font.features: { "tnum": 1 }
    }
    Rectangle {
        id: track
        y: 21
        width: parent.width
        height: 3
        radius: param.theme.uiRadius === 0 ? 0 : 1.5
        color: param.theme.barTrack
    }
    Rectangle {
        x: track.width * param.lo
        y: track.y
        width: Math.max(2, track.width * (param.hi - param.lo))
        height: track.height
        radius: track.radius
        color: param.active ? param.theme.accent : param.theme.barFill
    }
    Rectangle {   // zero mark of a bipolar bar
        visible: param.centre > 0
        x: track.width * param.centre - 0.5
        y: track.y - 2
        width: 1
        height: track.height + 4
        color: param.theme.drawerDim
    }
}
