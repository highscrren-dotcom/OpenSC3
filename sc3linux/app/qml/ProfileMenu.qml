import QtQuick

// Drop-down list of sound profiles, hanging under the header's profile chip. The list is
// `sc3.profiles` ([{name, note}]); the app has none yet (they come with writing to the SC3).
Item {
    id: menu
    required property Tokens theme
    required property QtObject sc3     // Backend (app) or DemoState (mock-ups): same shape
    property int forcedHover: -1       // mock-ups: row drawn as hovered
    property int mouseHover: -1
    readonly property int hovered: forcedHover >= 0 ? forcedHover : mouseHover
    readonly property var profiles: sc3.profiles || []
    readonly property real ts: theme.uiTextSize

    implicitWidth: 300
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

            // No profiles yet: say so instead of an empty box.
            Item {
                visible: menu.profiles.length === 0
                width: list.width
                height: 50
                Column {
                    x: 12
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 3
                    Text {
                        text: "Профилей пока нет"
                        color: menu.theme.menuDim
                        font.family: menu.theme.fontUi
                        font.pixelSize: menu.ts + 1
                    }
                    Text {
                        text: "появятся вместе с записью в SC3"
                        color: menu.theme.menuDim
                        font.family: menu.theme.fontUi
                        font.pixelSize: menu.ts - 1
                    }
                }
            }
            Repeater {
                model: menu.profiles
                delegate: Rectangle {
                    id: item
                    required property var modelData
                    required property int index
                    readonly property bool active: modelData.name === menu.sc3.profile
                    width: list.width
                    height: 50
                    radius: menu.theme.uiRadius
                    color: index === menu.hovered ? menu.theme.menuHover : "transparent"
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        onContainsMouseChanged: menu.mouseHover = containsMouse ? item.index
                                                : menu.mouseHover === item.index ? -1 : menu.mouseHover
                    }
                    Glyph {
                        visible: item.active
                        x: 10
                        anchors.verticalCenter: parent.verticalCenter
                        size: 16
                        stroke: 2.4
                        color: menu.theme.accent
                        strokePath: Icons.check
                    }
                    Column {
                        x: 36
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 3
                        Text {
                            text: item.modelData.name
                            color: menu.theme.menuText
                            font.family: menu.theme.fontUi
                            font.pixelSize: menu.ts + 1
                            font.bold: item.active
                        }
                        Text {
                            text: item.modelData.note
                            color: menu.theme.menuDim
                            font.family: menu.theme.fontUi
                            font.pixelSize: menu.ts - 1
                        }
                    }
                }
            }
            Rectangle {   // separator
                visible: menu.profiles.length > 0
                width: list.width
                height: 13
                color: "transparent"
                Rectangle { y: 6; x: 8; width: parent.width - 16; height: 1; color: menu.theme.menuBorder }
            }
            Item {
                visible: menu.profiles.length > 0
                width: list.width
                height: 38
                Glyph {
                    x: 10
                    anchors.verticalCenter: parent.verticalCenter
                    size: 16
                    stroke: 2.2
                    color: menu.theme.menuText
                    strokePath: Icons.plus
                }
                Text {
                    x: 36
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Новый профиль…"
                    color: menu.theme.menuText
                    font.family: menu.theme.fontUi
                    font.pixelSize: menu.ts + 1
                }
            }
        }
    }
}
