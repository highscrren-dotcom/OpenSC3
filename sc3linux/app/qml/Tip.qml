import QtQuick

// Tooltip (Russian). Points at its element with a small arrow on `arrow` side.
Item {
    id: tip
    required property Tokens theme
    property string title: ""
    property string text: ""
    property bool lock: true
    property string arrow: "right"     // "right" | "left" | "down"
    readonly property bool down: arrow === "down"
    property real arrowShift: 0        // "down": arrow offset from the box centre

    implicitWidth: box.width + (down ? 0 : 7)
    implicitHeight: box.height + (down ? 7 : 0)

    Shadow {
        anchors.fill: box
        theme: tip.theme
        radius: box.radius
        offsetY: 6
        blur: 18
        color: "#90000000"
    }

    Rectangle {
        id: box
        x: tip.arrow === "left" ? 7 : 0
        width: row.implicitWidth + 24
        height: row.implicitHeight + 16
        radius: tip.theme.uiRadius
        color: tip.theme.tipBg
        border.width: 1
        border.color: tip.theme.tipBorder

        Row {
            id: row
            anchors.centerIn: parent
            spacing: 9
            Glyph {
                visible: tip.lock
                anchors.verticalCenter: parent.verticalCenter
                size: 16
                stroke: 2.2
                color: tip.theme.tipText
                strokePath: Icons.lockStroke
                fillPath: Icons.lockFill
            }
            Column {
                spacing: 2
                Text {
                    text: tip.title
                    color: tip.theme.tipText
                    font.family: tip.theme.fontUi
                    font.pixelSize: tip.theme.uiTextSize
                    font.bold: true
                }
                Text {
                    text: tip.text
                    color: tip.theme.tipDim
                    font.family: tip.theme.fontUi
                    font.pixelSize: tip.theme.uiTextSize - 1
                }
            }
        }
    }

    // Arrow: a rotated square on the box edge; a patch hides the border where they meet.
    Rectangle {
        width: 10
        height: 10
        rotation: 45
        x: tip.down ? box.width / 2 - 5 + tip.arrowShift : tip.arrow === "right" ? box.x + box.width - 6 : 1
        y: tip.down ? box.height - 6 : box.height / 2 - 5
        color: tip.theme.tipBg
        border.width: 1
        border.color: tip.theme.tipBorder
    }

    Rectangle {
        x: tip.down ? box.width / 2 - 8 + tip.arrowShift : tip.arrow === "right" ? box.x + box.width - 9 : box.x + 0.5
        y: tip.down ? box.height - 9 : box.height / 2 - 8
        width: tip.down ? 16 : 8.5
        height: tip.down ? 8.5 : 16
        color: tip.theme.tipBg
    }
}
