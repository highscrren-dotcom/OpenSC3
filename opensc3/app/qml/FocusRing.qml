import QtQuick
import QtQuick.Effects

// Keyboard focus / selection in brand amber. Drawn outside the element with a gap
// so it never reads as the element's own light; follows the element's rounding.
// Usage: anchors.fill: target; anchors.margins: -theme.focusGap
Item {
    id: ring
    required property Tokens theme
    property real radius: 8            // the target's corner radius
    property real strength: 1.0        // 1 = focus, lower = passive selection

    layer.enabled: ring.theme.effects
    layer.effect: MultiEffect {
        shadowEnabled: true
        shadowColor: ring.theme.accent
        shadowOpacity: ring.theme.focusGlow * ring.strength
        shadowBlur: 0.5
        blurMax: 16
        shadowHorizontalOffset: 0
        shadowVerticalOffset: 0
    }

    Rectangle {
        anchors.fill: parent
        radius: ring.radius + ring.theme.focusGap
        color: "transparent"
        border.width: ring.theme.focusWidth
        border.color: Qt.alpha(ring.theme.accent, 0.35 + 0.65 * ring.strength)
    }
}
