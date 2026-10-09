import QtQuick
import QtQuick.Effects

// Bottom-row key (MUTE x3, MIC MONITOR): the whole translucent cap glows.
// Idle = dim neutral cap; lit = white cap with darker legend of the same hue.
Item {
    id: key
    required property Tokens theme
    property string text: "MUTE"
    property bool lit: false
    property bool unknown: false      // state not known: never lit, legend dimmed
    property bool guess: false        // lit by a guess (poll saw the volume drop to 0), not read: small «≈»
    property bool pressed: false      // pointer held on it: the cap sinks a little (brief #9)
    property real textSize: 14

    readonly property real radius: width * 0.12

    Rectangle {
        visible: key.lit && key.theme.effects
        anchors.fill: parent
        anchors.margins: -4
        radius: key.radius + 4
        color: key.theme.lightOn
        opacity: key.theme.lightHalo
        layer.enabled: true
        layer.effect: MultiEffect {
            blurEnabled: true
            blur: 1.0
            blurMax: 40
        }
    }

    Rectangle {   // flat stand-in for the halo
        visible: key.lit && !key.theme.effects
        anchors.fill: parent
        anchors.margins: -4
        radius: key.radius + 4
        color: "transparent"
        border.width: 3
        border.color: Qt.alpha(key.theme.lightOn, 0.3)
    }

    Shadow {
        visible: !key.lit
        anchors.fill: cap
        theme: key.theme
        radius: key.radius
        offsetY: 3 + 4 * key.theme.keyShadow
        blur: 6 + 10 * key.theme.keyShadow
        color: Qt.rgba(0, 0, 0, 0.35 + 0.4 * key.theme.keyShadow)
    }

    scale: pressed ? 0.965 : 1
    Behavior on scale {
        enabled: key.theme.animations
        NumberAnimation { duration: 90; easing.type: Easing.OutQuad }
    }

    Rectangle {
        id: cap
        anchors.fill: parent
        radius: key.radius
        gradient: Gradient {
            GradientStop { position: 0.0; color: key.lit ? "#ffffff" : key.theme.keyIdleTop }
            GradientStop { position: 1.0; color: key.lit ? Qt.darker(key.theme.lightOn, 1.08) : key.theme.keyIdleBottom }
        }
        border.width: 1
        border.color: key.lit ? "#ffffff" : key.theme.keyIdleBorder
        layer.enabled: key.lit && key.theme.effects
        layer.effect: MultiEffect {
            shadowEnabled: true
            shadowColor: key.theme.lightOn
            shadowOpacity: key.theme.lightGlow
            shadowBlur: 0.75
            blurMax: 24
            shadowHorizontalOffset: 0
            shadowVerticalOffset: 0
        }
    }
    // Soft-touch rubber: faint top lip.
    Rectangle {
        x: key.radius
        y: 1
        width: key.width - 2 * key.radius
        height: 1
        color: key.lit ? "#ffffff" : "#26ffffff"
    }

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: key.height * 0.07
        text: key.text
        color: key.lit ? key.theme.keyTextLit : key.theme.keyTextIdle
        opacity: key.unknown ? 0.55 : 1
        font.family: key.theme.fontPrint
        font.pixelSize: key.textSize
        horizontalAlignment: Text.AlignHCenter
        lineHeight: 0.9
    }

    Text {   // «по догадке»: the SC3 does not report MUTE, the poll guessed it from the volume
        visible: key.guess
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.rightMargin: key.width * 0.08
        anchors.topMargin: key.height * 0.04
        text: "≈"
        color: key.lit ? key.theme.keyTextLit : key.theme.keyTextIdle
        font.family: key.theme.fontPrint
        font.pixelSize: Math.max(9, key.textSize * 0.85)
    }
}
