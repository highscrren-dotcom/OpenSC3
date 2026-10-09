import QtQuick
import QtQuick.Shapes

// Software trim for a fader (brief #5): a small knob and its value in dB. The arc
// shows the offset from 0 dB at twelve o'clock; amber marks it as the app's control,
// not the body's.
Item {
    id: trim
    required property Tokens theme
    property real db: 0
    property bool known: true         // false: no trim yet - empty knob and a dash
    property real range: 12
    property real knobSize: 22
    property real textSize: 12.5

    readonly property real sweep: Math.max(-1, Math.min(1, db / range)) * 135
    readonly property real r: knobSize / 2

    function format(v) {
        const s = Math.abs(v).toFixed(1).replace(".", ",");
        return (v > 0.05 ? "+" : v < -0.05 ? "−" : "±") + s + " дБ";
    }

    implicitWidth: knobSize + 7 + label.implicitWidth
    implicitHeight: knobSize

    Shape {
        width: trim.knobSize
        height: trim.knobSize
        preferredRendererType: Shape.CurveRenderer
        // Track
        ShapePath {
            strokeColor: trim.theme.knobTrack
            strokeWidth: 2
            fillColor: "transparent"
            capStyle: ShapePath.FlatCap
            PathAngleArc {
                centerX: trim.r; centerY: trim.r
                radiusX: trim.r - 1.5; radiusY: trim.r - 1.5
                startAngle: -225; sweepAngle: 270
            }
        }
        // Offset from 0 dB
        ShapePath {
            strokeColor: trim.known && Math.abs(trim.sweep) > 0.5 ? trim.theme.accent : "transparent"
            strokeWidth: 2
            fillColor: "transparent"
            capStyle: ShapePath.FlatCap
            PathAngleArc {
                centerX: trim.r; centerY: trim.r
                radiusX: trim.r - 1.5; radiusY: trim.r - 1.5
                startAngle: -90; sweepAngle: trim.sweep
            }
        }
        // Body
        ShapePath {
            strokeColor: trim.theme.knobEdge
            strokeWidth: 1
            fillGradient: flat
            PathAngleArc {
                centerX: trim.r; centerY: trim.r
                radiusX: trim.r - 4.5; radiusY: trim.r - 4.5
                startAngle: 0; sweepAngle: 360
            }
        }
        LinearGradient {
            id: flat
            x1: 0; y1: 0; x2: 0; y2: trim.knobSize
            GradientStop { position: 0.0; color: Qt.lighter(trim.theme.knobBody, 1.5) }
            GradientStop { position: 1.0; color: trim.theme.knobBody }
        }
    }
    // Pointer
    Item {
        width: trim.knobSize
        height: trim.knobSize
        rotation: trim.sweep
        visible: trim.known
        Rectangle {
            x: trim.r - 1
            y: 5.5
            width: 2
            height: trim.r - 6
            radius: trim.theme.uiRadius === 0 ? 0 : 1
            color: trim.theme.accent
        }
    }

    Text {
        id: label
        x: trim.knobSize + 7
        anchors.verticalCenter: parent.verticalCenter
        text: trim.known ? trim.format(trim.db) : "—"
        color: trim.known ? trim.theme.trimValue : trim.theme.stripText
        font.family: trim.theme.fontValue
        font.pixelSize: trim.textSize
        font.bold: trim.known
        font.features: { "tnum": 1 }
    }
}
