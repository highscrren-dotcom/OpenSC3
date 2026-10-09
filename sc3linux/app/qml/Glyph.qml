import QtQuick
import QtQuick.Shapes

// Small vector icon drawn from SVG path data in a 24x24 box (no icon font needed).
// strokePath is outlined with `stroke` (in box units), fillPath is filled.
Item {
    id: glyph
    property string strokePath: ""
    property string fillPath: ""
    property color color: "#ffffff"
    property real size: 24
    property real stroke: 1.6

    implicitWidth: size
    implicitHeight: size

    Shape {
        width: 24
        height: 24
        scale: glyph.size / 24
        transformOrigin: Item.TopLeft
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: glyph.strokePath ? glyph.color : "transparent"
            strokeWidth: glyph.stroke
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: glyph.strokePath || "M0 0" }
        }
        ShapePath {
            strokeColor: "transparent"
            fillColor: glyph.fillPath ? glyph.color : "transparent"
            PathSvg { path: glyph.fillPath || "M0 0" }
        }
    }
}
