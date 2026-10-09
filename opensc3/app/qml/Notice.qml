import QtQuick

// Message card laid over the panel when the window cannot show live SC3 state.
Item {
    id: notice
    required property Tokens theme
    property string title: ""
    property string text: ""
    property string iconPath: Icons.usbPlug
    property color tone: theme.warn
    readonly property real ts: theme.uiTextSize

    implicitWidth: 460
    implicitHeight: box.height

    Shadow {
        anchors.fill: box
        theme: notice.theme
        radius: box.radius
        offsetY: 12
        blur: 36
        color: "#b0000000"
    }
    Rectangle {
        id: box
        width: parent.width
        height: content.implicitHeight + 44
        radius: notice.theme.uiRadius + 4
        color: notice.theme.menuBg
        border.width: 1
        border.color: notice.theme.menuBorder

        Rectangle {   // tone stripe on the left
            x: 1
            y: box.radius
            width: 3
            height: box.height - 2 * box.radius
            color: notice.tone
        }

        Row {
            id: content
            x: 26
            y: 22
            spacing: 18
            Rectangle {
                width: 44
                height: 44
                radius: 22
                color: Qt.alpha(notice.tone, 0.14)
                Glyph {
                    anchors.centerIn: parent
                    size: 24
                    stroke: 1.8
                    color: notice.tone
                    strokePath: notice.iconPath
                }
            }
            Column {
                spacing: 7
                width: notice.width - 26 - 44 - 18 - 26
                Text {
                    width: parent.width
                    text: notice.title
                    wrapMode: Text.WordWrap
                    color: notice.theme.menuText
                    font.family: notice.theme.fontUi
                    font.pixelSize: notice.ts + 4
                    font.bold: true
                }
                Text {
                    width: parent.width
                    text: notice.text
                    wrapMode: Text.WordWrap
                    lineHeight: 1.15
                    color: notice.theme.menuDim
                    font.family: notice.theme.fontUi
                    font.pixelSize: notice.ts
                }
            }
        }
    }
}
