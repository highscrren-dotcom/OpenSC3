import QtQuick
import QtQuick.Shapes

// Voice EQ: magnitude response of the band chain (RBJ biquads at the SC3's
// 44.1 kHz), log frequency axis 20 Hz - 20 kHz, +-15 dB. Bands come from sc3.dsp.eq:
// the enabled filters of node 0xA2 (kinds as in layouts.EQ_TYPES, view.EQ_KIND).
Item {
    id: eq
    required property Tokens theme
    required property var bands        // [{ kind: "pk" | "ls" | "hs" | "lp" | "hp" | "bp" | "notch", f: Hz, q, g: dB }]
    property int selected: -1          // band being edited: filled handle
    property real fs: 44100
    property real range: 15

    readonly property real padL: 30
    readonly property real padB: 18
    readonly property real plotW: width - padL
    readonly property real plotH: height - padB

    function xOf(f) { return padL + plotW * Math.log(f / 20) / Math.log(1000); }
    function yOf(db) { return plotH * (0.5 - db / (2 * range)); }

    // |H(e^jw)| in dB of one RBJ cookbook biquad.
    function bandDb(b, f) {
        const w0 = 2 * Math.PI * b.f / fs;
        const cw = Math.cos(w0), sw = Math.sin(w0);
        const alpha = sw / (2 * b.q);
        const A = Math.pow(10, b.g / 40);
        let b0, b1, b2, a0, a1, a2;
        if (b.kind === "pk") {
            b0 = 1 + alpha * A; b1 = -2 * cw; b2 = 1 - alpha * A;
            a0 = 1 + alpha / A; a1 = -2 * cw; a2 = 1 - alpha / A;
        } else if (b.kind === "ls") {
            const s = 2 * Math.sqrt(A) * alpha;
            b0 = A * ((A + 1) - (A - 1) * cw + s); b1 = 2 * A * ((A - 1) - (A + 1) * cw);
            b2 = A * ((A + 1) - (A - 1) * cw - s);
            a0 = (A + 1) + (A - 1) * cw + s; a1 = -2 * ((A - 1) + (A + 1) * cw);
            a2 = (A + 1) + (A - 1) * cw - s;
        } else if (b.kind === "hs") {
            const s = 2 * Math.sqrt(A) * alpha;
            b0 = A * ((A + 1) + (A - 1) * cw + s); b1 = -2 * A * ((A - 1) + (A + 1) * cw);
            b2 = A * ((A + 1) + (A - 1) * cw - s);
            a0 = (A + 1) - (A - 1) * cw + s; a1 = 2 * ((A - 1) - (A + 1) * cw);
            a2 = (A + 1) - (A - 1) * cw - s;
        } else {
            a0 = 1 + alpha; a1 = -2 * cw; a2 = 1 - alpha;
            if (b.kind === "lp") {
                b0 = (1 - cw) / 2; b1 = 1 - cw; b2 = b0;
            } else if (b.kind === "bp") {   // 0 dB at the centre
                b0 = alpha; b1 = 0; b2 = -alpha;
            } else if (b.kind === "notch") {
                b0 = 1; b1 = -2 * cw; b2 = 1;
            } else {  // hp
                b0 = (1 + cw) / 2; b1 = -(1 + cw); b2 = b0;
            }
        }
        const w = 2 * Math.PI * f / fs;
        const c1 = Math.cos(w), s1 = Math.sin(w), c2 = Math.cos(2 * w), s2 = Math.sin(2 * w);
        const nr = b0 + b1 * c1 + b2 * c2, ni = -(b1 * s1 + b2 * s2);
        const dr = a0 + a1 * c1 + a2 * c2, di = -(a1 * s1 + a2 * s2);
        return 10 * Math.log10((nr * nr + ni * ni) / (dr * dr + di * di));
    }
    function totalDb(f) {
        let sum = 0;
        for (const b of bands) sum += bandDb(b, f);
        return sum;
    }

    readonly property var curve: {
        const pts = [];
        const n = 220;
        for (let i = 0; i <= n; ++i) {
            const f = 20 * Math.pow(1000, i / n);
            const db = Math.max(-range - 3, totalDb(f));
            pts.push(Qt.point(xOf(f), yOf(db)));
        }
        return pts;
    }
    readonly property var area: {
        const pts = curve.slice();
        pts.push(Qt.point(xOf(20000), yOf(0)));
        pts.push(Qt.point(xOf(20), yOf(0)));
        return pts;
    }

    // Plot background
    Rectangle {
        x: eq.padL
        width: eq.plotW
        height: eq.plotH
        color: eq.theme.graphBg
        radius: eq.theme.uiRadius === 0 ? 0 : 3
        border.width: 1
        border.color: eq.theme.graphGrid
    }

    // Grid: decades and halves, dB lines
    Repeater {
        model: [50, 100, 200, 500, 1000, 2000, 5000, 10000]
        delegate: Item {
            required property int modelData
            Rectangle {
                x: eq.xOf(parent.modelData)
                width: 1
                height: eq.plotH
                color: parent.modelData === 100 || parent.modelData === 1000 || parent.modelData === 10000
                       ? eq.theme.graphGridStrong : eq.theme.graphGrid
            }
            Text {
                x: eq.xOf(parent.modelData) - implicitWidth / 2
                y: eq.plotH + 3
                text: parent.modelData >= 1000 ? (parent.modelData / 1000) + "к" : parent.modelData
                color: eq.theme.drawerFaint
                font.family: eq.theme.fontValue
                font.pixelSize: 11
            }
        }
    }
    Repeater {
        model: [12, 6, 0, -6, -12]
        delegate: Item {
            required property int modelData
            Rectangle {
                x: eq.padL
                y: eq.yOf(parent.modelData)
                width: eq.plotW
                height: 1
                color: parent.modelData === 0 ? eq.theme.graphGridStrong : eq.theme.graphGrid
            }
            Text {
                x: eq.padL - implicitWidth - 6
                y: eq.yOf(parent.modelData) - implicitHeight / 2
                text: parent.modelData > 0 ? "+" + parent.modelData : parent.modelData < 0 ? "−" + (-parent.modelData) : "0"
                color: eq.theme.drawerFaint
                font.family: eq.theme.fontValue
                font.pixelSize: 11
            }
        }
    }

    // Response
    Item {
        x: eq.padL
        width: eq.plotW
        height: eq.plotH
        clip: true
        Shape {
            x: -eq.padL
            width: eq.width
            height: eq.plotH
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: "transparent"
                fillColor: eq.theme.graphFill
                PathPolyline { path: eq.area }
            }
        }
        Shape {
            x: -eq.padL
            width: eq.width
            height: eq.plotH
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: eq.theme.graphCurve
                strokeWidth: 2
                fillColor: "transparent"
                joinStyle: ShapePath.RoundJoin
                PathPolyline { path: eq.curve }
            }
        }
    }

    // Band handles on the curve; the selected one is filled amber.
    Repeater {
        model: eq.bands.length
        delegate: Rectangle {
            id: handle
            required property int index
            readonly property var band: eq.bands[index]
            readonly property bool sel: index === eq.selected
            width: sel ? 18 : 15
            height: width
            radius: width / 2
            x: eq.xOf(band.f) - width / 2
            y: eq.yOf(Math.max(-eq.range, Math.min(eq.range, eq.totalDb(band.f)))) - height / 2
            color: sel ? eq.theme.accent : eq.theme.graphBg
            border.width: 1.5
            border.color: sel ? eq.theme.accentLight : eq.theme.accent
            Text {
                anchors.centerIn: parent
                text: handle.band.n !== undefined ? handle.band.n : handle.index + 1
                color: handle.sel ? "#0B0906" : eq.theme.accent
                font.family: eq.theme.fontValue
                font.pixelSize: 10
                font.bold: true
            }
        }
    }
}
