import QtQuick
import QtQuick.Effects

// LED window: level-strip pill or indicator dot. `level` 0..1 is how lit it is
// (partial values for the soft edge of a live meter). Lit = colour core, a tight
// zero-offset glow and a blurred halo; unlit = matte diffuser with a tiny highlight.
Item {
    id: lamp
    required property Tokens theme
    property real level: 0
    property color color: "#ffffff"
    property color offColor: theme.meterOff
    property color edgeColor: theme.meterOffEdge
    property real glow: theme.meterGlow
    property real halo: theme.meterHalo
    property real haloSpread: 1.0
    readonly property bool lit: level > 0.01

    // LEDs fade softly instead of snapping (brief #9).
    Behavior on level {
        enabled: lamp.theme.animations
        NumberAnimation { duration: 120; easing.type: Easing.OutQuad }
    }

    Rectangle {
        visible: lamp.lit && lamp.theme.effects
        anchors.centerIn: lens
        width: lens.width + 16 * lamp.haloSpread
        height: lens.height + 14 * lamp.haloSpread
        radius: Math.min(width, height) / 2
        color: lamp.color
        opacity: lamp.halo * lamp.level
        layer.enabled: true
        layer.effect: MultiEffect {
            blurEnabled: true
            blur: 1.0
            blurMax: 32
        }
    }

    Rectangle {
        id: lens
        anchors.fill: parent
        radius: Math.min(width, height) / 2
        color: lamp.lit ? Qt.tint(lamp.offColor, Qt.alpha(lamp.color, 0.25 + 0.75 * lamp.level)) : lamp.offColor
        border.width: 1
        border.color: lamp.lit ? Qt.tint(lamp.color, "#55ffffff") : lamp.edgeColor
        layer.enabled: lamp.level > 0.5 && lamp.theme.effects
        layer.effect: MultiEffect {
            shadowEnabled: true
            shadowColor: lamp.color
            shadowOpacity: lamp.glow
            shadowBlur: 0.8
            blurMax: 20
            shadowHorizontalOffset: 0
            shadowVerticalOffset: 0
        }
    }

    // Flat stand-in for the glow: a soft ring of the LED colour.
    Rectangle {
        visible: lamp.level > 0.5 && !lamp.theme.effects
        anchors.centerIn: lens
        width: lens.width + 6
        height: lens.height + 6
        radius: Math.min(width, height) / 2
        color: "transparent"
        border.width: 2
        border.color: Qt.alpha(lamp.color, 0.35 * lamp.level)
    }

    // Hot core: a lit LED is whiter in the middle.
    Rectangle {
        visible: lamp.level > 0.5
        anchors.centerIn: lens
        width: lens.width * 0.5
        height: lens.height * 0.6
        radius: Math.min(width, height) / 2
        color: Qt.tint(lamp.color, "#70ffffff")
        opacity: 0.8 * lamp.level
    }

    // Unlit diffuser catches a little light on its upper edge.
    Rectangle {
        visible: !lamp.lit
        x: lens.width * 0.25
        y: 1.5
        width: lens.width * 0.5
        height: 1
        radius: 0.5
        color: "#22ffffff"
    }
}
