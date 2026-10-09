import QtQuick

// Fader cap seen from above: a tall saddle grip with ribs on both slopes and the
// red-orange index stripe across the middle.
Item {
    id: cap
    required property Tokens theme
    readonly property real radius: width * 0.42

    Shadow {
        anchors.fill: body
        theme: cap.theme
        radius: cap.radius
        offsetY: cap.theme.capShadowOffset
        blur: cap.theme.capShadowBlur
        color: Qt.rgba(0, 0, 0, cap.theme.capShadowOpacity)
    }

    Rectangle {
        id: body
        anchors.fill: parent
        radius: cap.radius
        gradient: Gradient {
            GradientStop { position: 0.00; color: cap.theme.capTop }
            GradientStop { position: 0.42; color: cap.theme.capMid }
            GradientStop { position: 0.50; color: Qt.lighter(cap.theme.capMid, 1.12) }
            GradientStop { position: 0.58; color: cap.theme.capMid }
            GradientStop { position: 1.00; color: cap.theme.capBottom }
        }
        border.width: 1
        border.color: cap.theme.capEdge
    }
    // The grip is rounded across its width: flanks fall into shadow.
    Rectangle {
        anchors.fill: body
        anchors.margins: 1
        radius: cap.radius
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.00; color: "#66000000" }
            GradientStop { position: 0.22; color: "#00000000" }
            GradientStop { position: 0.78; color: "#00000000" }
            GradientStop { position: 1.00; color: "#80000000" }
        }
    }

    // Ribs: groove + lit lip, four on each slope.
    Repeater {
        model: [0.10, 0.17, 0.24, 0.31, 0.69, 0.76, 0.83, 0.90]
        delegate: Item {
            required property real modelData
            x: cap.width * 0.17
            y: cap.height * modelData
            width: cap.width * 0.66
            height: 3
            Rectangle { width: parent.width; height: 1.5; radius: 0.75; color: "#b0000000" }
            Rectangle { y: 1.5; width: parent.width; height: 1; radius: 0.5; color: Qt.rgba(1, 1, 1, cap.theme.capRibLight) }
        }
    }

    // Index stripe: runs over the top and down the sides.
    Rectangle {
        x: 1
        width: cap.width - 2
        y: cap.height / 2 - height / 2
        height: Math.max(2.5, cap.height * 0.02)
        color: cap.theme.capStripe
    }
    Rectangle {
        x: cap.width * 0.2
        width: cap.width * 0.6
        y: cap.height / 2 - 1.5
        height: 1
        color: "#40ffffff"
    }

    // Top edge catches the light.
    Rectangle {
        x: cap.radius * 0.8
        y: 1
        width: cap.width - 1.6 * cap.radius
        height: 1
        color: "#28ffffff"
    }
}
