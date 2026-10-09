import QtQuick
import QtQuick.Effects

// LED window. Off: dark lens with a tiny specular line.
// On: hot core plus bloom (a zero-offset coloured shadow acts as glow).
// No shadowScale: MultiEffect's auto padding ignores it and the glow gets clipped square.
Item {
    id: root
    property bool on: false
    property color color: Theme.ledOn
    property real glow: 1.0
    implicitWidth: 20
    implicitHeight: 5

    // Halo: an enlarged, blurred copy behind the lens (light spilling onto the key).
    Rectangle {
        visible: root.on
        anchors.centerIn: lens
        width: lens.width + 14
        height: lens.height + 12
        radius: height / 2
        color: root.color
        opacity: 0.5 * root.glow
        layer.enabled: true
        layer.effect: MultiEffect {
            blurEnabled: true
            blur: 1.0
            blurMax: 24
        }
    }

    Rectangle {
        id: lens
        anchors.fill: parent
        radius: Math.min(width, height) / 2
        color: root.on ? root.color : Theme.ledOff
        border.width: 1
        border.color: root.on ? Qt.tint(root.color, "#80ffffff") : "#000000"
        layer.enabled: root.on
        layer.effect: MultiEffect {
            shadowEnabled: true
            shadowColor: root.color
            shadowOpacity: root.glow
            shadowBlur: 1.0
            blurMax: 28
            shadowHorizontalOffset: 0
            shadowVerticalOffset: 0
        }
    }

    Rectangle {
        visible: !root.on
        x: 2
        y: 1
        width: parent.width - 4
        height: 1
        radius: 0.5
        color: "#1cffffff"
    }
}
