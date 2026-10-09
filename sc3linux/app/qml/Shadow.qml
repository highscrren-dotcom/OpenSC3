import QtQuick
import QtQuick.Effects

// Drop shadow under a rounded rectangle; anchors.fill the caster and put it before it.
// GPU: RectangularShadow (soft). Software scene graph: RectangularShadow draws nothing
// there, so a flat dark plate slightly offset downwards stands in for it.
Item {
    id: shadow
    required property Tokens theme
    property real radius: 0
    property real blur: 12
    property real offsetY: 6
    property color color: "#80000000"

    RectangularShadow {
        visible: shadow.theme.effects
        anchors.fill: parent
        offset.y: shadow.offsetY
        blur: shadow.blur
        radius: shadow.radius
        color: shadow.color
    }
    Rectangle {
        visible: !shadow.theme.effects
        y: Math.min(shadow.offsetY * 0.5, 4)
        width: parent.width
        height: parent.height
        radius: shadow.radius
        color: Qt.alpha(shadow.color, shadow.color.a * 0.7)
    }
}
