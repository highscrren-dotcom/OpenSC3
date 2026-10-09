import QtQuick

// Drop-down menu of sound profiles, hanging under the header's profile chip. The rows are
// `sc3.profiles` ([{name, note, action?, enabled?, active?}]). In the app each row is an
// action - «Подкаст — применить», «Вернуть как было», «Как с завода» (later) - behind the
// write fuse: a click asks `sc3.profileAction(action)`, a disabled row is dim and
// `sc3.profileHint` says why. Mock-up rows without `action` are plain profiles plus
// «Новый профиль…» (design/panel/scenes/DemoState.qml).
Item {
    id: menu
    signal picked()                    // a row was clicked: the window closes the menu
    required property Tokens theme
    required property QtObject sc3     // Backend (app) or DemoState (mock-ups): same shape
    property int forcedHover: -1       // mock-ups: row drawn as hovered
    property int mouseHover: -1
    readonly property int hovered: forcedHover >= 0 ? forcedHover : mouseHover
    readonly property var profiles: sc3.profiles || []
    readonly property bool mock: profiles.length > 0 && profiles[0].action === undefined
    readonly property string hint: sc3.profileHint || ""
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
                    readonly property bool active: modelData.active !== undefined ? modelData.active
                                                                                  : modelData.name === menu.sc3.profile
                    readonly property bool allowed: modelData.enabled !== false
                    objectName: "profileRow-" + (modelData.action || index)   // tests click it by name
                    width: list.width
                    height: 50
                    radius: menu.theme.uiRadius
                    opacity: allowed ? 1 : 0.45
                    color: allowed && index === menu.hovered ? menu.theme.menuHover : "transparent"
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: item.allowed && item.modelData.action ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onContainsMouseChanged: menu.mouseHover = containsMouse ? item.index
                                                : menu.mouseHover === item.index ? -1 : menu.mouseHover
                        onClicked: {
                            if (!item.modelData.action || !item.allowed)
                                return;
                            // Close first: the action republishes `profiles`, and the Repeater rebuilds this row.
                            const action = item.modelData.action;
                            menu.picked();
                            menu.sc3.profileAction(action);
                        }
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
                visible: menu.mock || menu.hint !== ""
                width: list.width
                height: 13
                color: "transparent"
                Rectangle { y: 6; x: 8; width: parent.width - 16; height: 1; color: menu.theme.menuBorder }
            }
            // Why the rows are disabled (the write fuse, on air, not connected).
            Item {
                visible: !menu.mock && menu.hint !== ""
                width: list.width
                height: 34
                Glyph {
                    x: 10
                    anchors.verticalCenter: parent.verticalCenter
                    size: 15
                    stroke: 2.2
                    color: menu.theme.menuDim
                    strokePath: Icons.lockStroke
                    fillPath: Icons.lockFill
                }
                Text {
                    x: 36
                    width: parent.width - 44
                    anchors.verticalCenter: parent.verticalCenter
                    text: menu.hint
                    elide: Text.ElideRight
                    color: menu.theme.menuDim
                    font.family: menu.theme.fontUi
                    font.pixelSize: menu.ts - 1
                }
            }
            Item {
                visible: menu.mock
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
