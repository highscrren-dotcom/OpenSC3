import QtQuick

// Window settings, hanging under the header's gear. One switch so far: the write fuse
// (DECISIONS.md, 4: writing to the SC3 is the owner's call) - off by default, kept between
// runs (QSettings). Off: the MIC trim knob is shown but does not turn.
Item {
    id: menu
    required property Tokens theme
    required property QtObject sc3     // Backend (app) or DemoState (mock-ups): same shape
    property bool forcedHover: false   // mock-ups: row drawn as hovered
    readonly property bool on: sc3.writeEnabled
    readonly property real ts: theme.uiTextSize

    implicitWidth: 360
    implicitHeight: box.height

    Shadow {
        anchors.fill: box
        theme: menu.theme
        radius: box.radius
        offsetY: 10
        blur: 28
        color: "#a0000000"
    }

    Rectangle {
        id: box
        width: parent.width
        height: list.implicitHeight + 12
        radius: menu.theme.uiRadius + 2
        color: menu.theme.menuBg
        border.width: 1
        border.color: menu.theme.menuBorder

        Column {
            id: list
            x: 6
            y: 6
            width: parent.width - 12

            Rectangle {
                id: row
                objectName: "writeSwitch"     // tests click it by name
                width: list.width
                height: 62
                radius: menu.theme.uiRadius
                color: menu.forcedHover || rowArea.containsMouse ? menu.theme.menuHover : "transparent"
                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: menu.sc3.setWriteEnabled(!menu.on)
                }
                Column {
                    x: 12
                    width: parent.width - 12 - track.width - 24
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 3
                    Text {
                        text: "Разрешить запись в SC3"
                        color: menu.theme.menuText
                        font.family: menu.theme.fontUi
                        font.pixelSize: menu.ts + 1
                        font.bold: menu.on
                    }
                    Text {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: "ручка-поправка MIC под панелью — вне эфира,\nкаждое значение сверяется чтением назад"
                        color: menu.theme.menuDim
                        font.family: menu.theme.fontUi
                        font.pixelSize: menu.ts - 1
                    }
                }
                // Switch: amber track when on.
                Rectangle {
                    id: track
                    anchors.right: parent.right
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    width: 36
                    height: 20
                    radius: menu.theme.uiRadius === 0 ? 0 : height / 2
                    color: menu.on ? menu.theme.accent : menu.theme.knobTrack
                    Behavior on color {
                        enabled: menu.theme.animations
                        ColorAnimation { duration: 160 }
                    }
                    Rectangle {
                        width: 16
                        height: 16
                        radius: menu.theme.uiRadius === 0 ? 0 : 8
                        y: 2
                        x: menu.on ? track.width - width - 2 : 2
                        color: menu.on ? menu.theme.accentDark : menu.theme.menuText
                        Behavior on x {
                            enabled: menu.theme.animations
                            NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
                        }
                    }
                }
            }
        }
    }
}
