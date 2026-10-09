import QtQuick
import QtQuick.Shapes

// Compressor transfer curve, input vs output level, -60..0 dBFS, soft knee.
// Settings come from sc3.dsp.comp.
Item {
    id: comp
    required property Tokens theme
    required property real threshold    // dBFS
    required property real ratio        // n : 1
    required property real knee         // dB, 0 = hard knee
    required property real input        // current input level, dBFS, drawn as a dot
    readonly property real lo: -60

    function out(x) {
        const t = threshold, r = Math.max(1, ratio), k = Math.max(0, knee);
        if (k === 0) return x < t ? x : t + (x - t) / r;
        if (x < t - k / 2) return x;
        if (x > t + k / 2) return t + (x - t) / r;
        const d = x - t + k / 2;
        return x + (1 / r - 1) * d * d / (2 * k);
    }
    function px(db) { return width * (db - lo) / -lo; }
    function py(db) { return height * (1 - (db - lo) / -lo); }

    readonly property var curve: {
        const pts = [];
        for (let i = 0; i <= 120; ++i) {
            const x = lo + i * (-lo / 120);
            pts.push(Qt.point(px(x), py(out(x))));
        }
        return pts;
    }

    Rectangle {
        anchors.fill: parent
        color: comp.theme.graphBg
        radius: comp.theme.uiRadius === 0 ? 0 : 3
        border.width: 1
        border.color: comp.theme.graphGrid
    }
    Repeater {
        model: [-48, -36, -24, -12]
        delegate: Item {
            required property int modelData
            Rectangle { x: comp.px(parent.modelData); width: 1; height: comp.height; color: comp.theme.graphGrid }
            Rectangle { y: comp.py(parent.modelData); width: comp.width; height: 1; color: comp.theme.graphGrid }
        }
    }
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {   // 1:1 reference
            strokeColor: comp.theme.graphGridStrong
            strokeWidth: 1
            strokeStyle: ShapePath.DashLine
            dashPattern: [3, 3]
            fillColor: "transparent"
            startX: 0; startY: comp.height
            PathLine { x: comp.width; y: 0 }
        }
        ShapePath {
            strokeColor: comp.theme.graphCurve
            strokeWidth: 2
            fillColor: "transparent"
            PathPolyline { path: comp.curve }
        }
    }
    // Threshold
    Rectangle {
        x: comp.px(comp.threshold)
        y: comp.py(comp.out(comp.threshold)) + 4
        width: 1
        height: comp.height - y
        color: Qt.alpha(comp.theme.accent, 0.45)
    }
    // Where the voice is right now
    Rectangle {
        width: 9
        height: 9
        radius: comp.theme.uiRadius === 0 ? 0 : 4.5
        x: comp.px(comp.input) - 4.5
        y: comp.py(comp.out(comp.input)) - 4.5
        color: comp.theme.accentLight
        border.width: 1
        border.color: comp.theme.accent
    }
}
