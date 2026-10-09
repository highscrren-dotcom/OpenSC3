import QtQuick
import QtQuick.Shapes

// Software trim for a fader (brief #5): a small knob and its value in dB. The arc shows the
// offset from 0 dB at twelve o'clock (each side of the range fills its own 135 degrees);
// amber marks it as the app's control, not the body's.
// With `interactive` it can be turned: drag up (or right), the wheel or Up/Down - one 0.5 dB
// step at a time; a double click brings it back to 0 dB. The knob only asks
// (`changeRequested`): the value it shows is the backend's - the asked one while it is being
// written (`pending`), then what was read back from the SC3. Without `writable` a turn does
// nothing but `refused()` (the strip says why).
Item {
    id: trim
    required property Tokens theme
    property real db: 0
    property bool known: true         // false: no trim (yet) - empty knob and `blank`
    property string blank: "—"
    property real minDb: -20
    property real maxDb: 10
    property real step: 0.5
    property bool interactive: false  // takes the mouse and the keys at all
    property bool writable: false     // a turn asks for a new value; otherwise it is refused
    property bool pending: false      // the shown value is still being written to the SC3
    property real knobSize: 22
    property real textSize: 12.5
    property real dragPx: 8           // drag distance per step
    readonly property bool dragging: area.pressed && area.moved
    readonly property bool hovered: area.containsMouse
    signal changeRequested(real db)
    signal refused()

    function sweepOf(v) {
        return v >= 0 ? Math.min(1, v / maxDb) * 135 : -Math.min(1, v / minDb) * 135;
    }
    // The pointer glides to a new value (brief #9) - but follows the hand while dragging.
    property real sweep: sweepOf(known ? db : 0)
    Behavior on sweep {
        enabled: trim.theme.animations && !trim.dragging
        NumberAnimation { duration: 260; easing.type: Easing.OutCubic }
    }
    readonly property real r: knobSize / 2

    function format(v) {
        const s = Math.abs(v).toFixed(1).replace(".", ",");
        return (v > 0.05 ? "+" : v < -0.05 ? "−" : "±") + s + " дБ";
    }
    // Ask for `v` (snapped to the step, kept in range); the same value again is not asked.
    function ask(v) {
        if (!writable) {
            refused();
            return;
        }
        const next = Math.max(minDb, Math.min(maxDb, Math.round(v / step) * step));
        if (Math.abs(next - db) >= 0.01)
            changeRequested(next);
    }

    implicitWidth: knobSize + 7 + label.implicitWidth
    implicitHeight: knobSize
    activeFocusOnTab: interactive

    Keys.onPressed: event => {
        if (!trim.interactive)
            return;
        if (event.key === Qt.Key_Up || event.key === Qt.Key_Right)
            trim.ask(trim.db + trim.step);
        else if (event.key === Qt.Key_Down || event.key === Qt.Key_Left)
            trim.ask(trim.db - trim.step);
        else if (event.key === Qt.Key_Home || event.key === Qt.Key_0)
            trim.ask(0);
        else
            return;
        event.accepted = true;
    }

    FocusRing {
        visible: trim.activeFocus
        theme: trim.theme
        x: -trim.theme.focusGap
        y: -trim.theme.focusGap
        width: trim.knobSize + 2 * trim.theme.focusGap
        height: trim.knobSize + 2 * trim.theme.focusGap
        radius: trim.knobSize / 2
    }

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
            strokeColor: trim.interactive && trim.writable && trim.hovered ? trim.theme.accent : trim.theme.knobEdge
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
        text: trim.known ? trim.format(trim.db) : trim.blank
        color: trim.known ? trim.theme.trimValue : trim.theme.stripText
        opacity: trim.pending ? 0.55 : 1   // asked, not yet read back
        Behavior on opacity {
            enabled: trim.theme.animations
            NumberAnimation { duration: 160 }
        }
        font.family: trim.theme.fontValue
        font.pixelSize: trim.textSize
        font.bold: trim.known
        font.features: { "tnum": 1 }
    }

    // Turning: drag (up or right is more), wheel, double click - 0 dB.
    MouseArea {
        id: area
        property real startDb: 0
        property point start: Qt.point(0, 0)
        property bool moved: false
        anchors.fill: parent
        anchors.margins: -4
        enabled: trim.interactive
        hoverEnabled: true
        preventStealing: true
        cursorShape: trim.writable ? Qt.SizeVerCursor : Qt.ArrowCursor
        onPressed: mouse => {
            start = Qt.point(mouse.x, mouse.y);
            startDb = trim.db;
            moved = false;
            if (!trim.writable)
                trim.refused();
        }
        onPositionChanged: mouse => {
            if (!pressed || !trim.writable)
                return;
            const d = (start.y - mouse.y) + (mouse.x - start.x);
            if (Math.abs(d) >= 3)
                moved = true;
            if (moved)
                trim.ask(startDb + Math.round(d / trim.dragPx) * trim.step);
        }
        onDoubleClicked: trim.ask(0)
        onWheel: wheel => {
            const notches = Math.round(wheel.angleDelta.y / 120);
            if (notches !== 0)
                trim.ask(trim.db + notches * trim.step);
            wheel.accepted = true;
        }
    }
}
