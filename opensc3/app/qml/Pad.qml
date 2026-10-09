import QtQuick
import QtQuick.Effects

// Big backlit pad (48V, ELECTRIC, CUSTOM A-D, RGB, CHANGE VOICE), top view:
// glossy black top inside a translucent light-guide skirt that carries the light.
// Idle  = dim neutral skirt (the app cannot know the RGB mode colour).
// lit   = white, as the manual says for "function on".
// locked = dimmed (exists only on the body; the lock badge is drawn by the panel).
Item {
    id: pad
    required property Tokens theme
    property string text: ""          // "48V", "ELECTRIC", "CHANGE\nVOICE", or "CUSTOM" for letter pads
    property string letter: ""        // CUSTOM pads: big letter, "CUSTOM" goes to the top-left corner
    property bool sun: false          // RGB pad: sun glyph instead of text
    property bool lit: false
    property bool locked: false
    property real textSize: 15
    property real letterSize: 26

    readonly property real rimW: Math.max(3, width * theme.padRimFrac)
    readonly property real radius: width * 0.09
    readonly property color ink: lit ? theme.lightText : theme.padTextIdle

    opacity: locked ? theme.lockedOpacity : 1

    // Light leaking onto the body around the pad.
    Rectangle {
        visible: pad.lit && pad.theme.effects
        anchors.fill: parent
        anchors.margins: -3
        radius: pad.radius + 3
        color: pad.theme.lightOn
        opacity: pad.theme.lightHalo
        layer.enabled: true
        layer.effect: MultiEffect {
            blurEnabled: true
            blur: 1.0
            blurMax: 40
        }
    }

    // Flat stand-in for the halo when there are no GPU effects.
    Rectangle {
        visible: pad.lit && !pad.theme.effects
        anchors.fill: parent
        anchors.margins: -4
        radius: pad.radius + 4
        color: "transparent"
        border.width: 3
        border.color: Qt.alpha(pad.theme.lightOn, 0.3)
    }

    // Dark seam between body and pad.
    Rectangle {
        anchors.fill: parent
        anchors.margins: -2
        radius: pad.radius + 2
        color: "#99000000"
        visible: !pad.lit
    }

    // Light guide (skirt).
    Rectangle {
        id: skirt
        anchors.fill: parent
        radius: pad.radius
        color: pad.lit ? pad.theme.lightOn : pad.theme.padRimIdle
        border.width: 1
        border.color: pad.lit ? "#ffffff" : Qt.darker(pad.theme.padRimIdle, 1.6)
        layer.enabled: pad.lit && pad.theme.effects
        layer.effect: MultiEffect {
            shadowEnabled: true
            shadowColor: pad.theme.lightOn
            shadowOpacity: pad.theme.lightGlow
            shadowBlur: 0.7
            blurMax: 24
            shadowHorizontalOffset: 0
            shadowVerticalOffset: 0
        }
    }
    // Idle skirt is translucent plastic, not paint: lighter towards its outer edge.
    Rectangle {
        visible: !pad.lit
        anchors.fill: parent
        anchors.margins: 1
        radius: pad.radius - 1
        color: "transparent"
        border.width: Math.max(1, pad.rimW * 0.35)
        border.color: "#18ffffff"
    }

    // Glossy black top.
    Rectangle {
        id: top
        anchors.fill: parent
        anchors.margins: pad.rimW
        radius: Math.max(2, pad.radius - pad.rimW * 0.6)
        gradient: Gradient {
            GradientStop { position: 0.0; color: pad.theme.padTopEdge }
            GradientStop { position: 0.35; color: pad.theme.padTop }
            GradientStop { position: 1.0; color: pad.theme.padTop }
        }
        border.width: 1
        border.color: pad.lit ? "#90ffffff" : "#000000"
    }
    // Specular strip on the glossy top.
    Rectangle {
        x: top.x + top.radius
        y: top.y + 2
        width: top.width - 2 * top.radius
        height: top.height * 0.36
        radius: top.radius
        visible: pad.theme.padGloss > 0
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, pad.theme.padGloss) }
            GradientStop { position: 1.0; color: Qt.rgba(1, 1, 1, 0) }
        }
    }

    // Legend (the print on the top lets the light through).
    Item {
        id: legend
        anchors.fill: top
        layer.enabled: pad.lit && pad.theme.effects
        layer.effect: MultiEffect {
            shadowEnabled: true
            shadowColor: pad.theme.lightOn
            shadowOpacity: 0.55
            shadowBlur: 0.35
            blurMax: 12
            shadowHorizontalOffset: 0
            shadowVerticalOffset: 0
        }

        Text {
            visible: pad.letter === "" && !pad.sun
            anchors.centerIn: parent
            text: pad.text
            color: pad.ink
            font.family: pad.theme.fontPrint
            font.pixelSize: pad.textSize
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            lineHeight: 0.92
        }

        // CUSTOM pads: word in the corner, big letter centred slightly low.
        Text {
            visible: pad.letter !== ""
            x: pad.width * 0.1 - pad.rimW
            y: top.height * 0.07
            text: pad.text
            color: pad.ink
            font.family: pad.theme.fontPrint
            font.pixelSize: pad.textSize
            font.bold: true
        }
        Text {
            visible: pad.letter !== ""
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: top.height * 0.09
            text: pad.letter
            color: pad.ink
            font.family: pad.theme.fontPrint
            font.pixelSize: pad.letterSize
            font.bold: true
        }

        Glyph {
            visible: pad.sun
            anchors.centerIn: parent
            size: pad.letterSize * 1.25
            stroke: 1.7
            color: pad.ink
            strokePath: Icons.sunStroke
        }
    }
}
