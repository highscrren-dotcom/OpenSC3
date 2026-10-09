import QtQuick
import QtQuick.Shapes
import "../../../sc3linux/app/qml"

// The tray context menu over a Plasma 6 panel (Breeze Dark), right-click on the SC3 icon.
// It is the system QMenu, so it wears Breeze colours, not the brand amber: background #2a2e32,
// hover = Breeze blue #3daee9 at ~25 % with a frame. The other tray icons are neutral stand-ins
// (plain shapes, not Breeze icons). Our icon is the 22 px "connected" PNG from ../icons/export.py (sc3linux/app/icons/png);
// at 2x Qt picks its @2x file by itself. Root is a plain Rectangle for the off-screen renderer.
Rectangle {
    id: frame

    readonly property color ink: "#fcfcfc"
    readonly property color inkDim: Qt.rgba(252 / 255, 252 / 255, 252 / 255, 0.6)
    readonly property color line: Qt.rgba(252 / 255, 252 / 255, 252 / 255, 0.13)
    readonly property color accent: "#3daee9"
    readonly property color panelColor: "#2a2e32"
    readonly property int panelH: 44
    readonly property int cell: 32              // tray cell width
    readonly property int trayX: 228            // first tray cell
    readonly property int ourIndex: 2           // our icon is the third cell

    width: 520
    height: 420
    gradient: Gradient {  // stand-in wallpaper
        GradientStop { position: 0.0; color: "#22374a" }
        GradientStop { position: 1.0; color: "#121a22" }
    }

    // ---- inline parts (they cannot see this file's ids: all inputs are properties) ---------------

    component Label: Text {
        color: "#fcfcfc"
        font.family: Fonts.sans
        font.pixelSize: 13
        verticalAlignment: Text.AlignVCenter
    }

    // A neutral grey stand-in for somebody else's tray icon, drawn in a 22 px box.
    component StandIn: Item {
        property string kind: "ring"
        readonly property color grey: "#a6acb2"
        width: 22
        height: 22
        Rectangle {  // ring
            visible: parent.kind === "ring"
            x: 3; y: 3; width: 16; height: 16; radius: 8
            color: "transparent"; border.width: 2; border.color: parent.grey
        }
        Rectangle {  // rounded box with a bar
            visible: parent.kind === "box"
            x: 3; y: 4; width: 16; height: 14; radius: 3
            color: "transparent"; border.width: 2; border.color: parent.grey
            Rectangle { x: 4; y: 5; width: 8; height: 2; color: parent.border.color }
        }
        Repeater {  // three rising bars
            model: parent.kind === "bars" ? 3 : 0
            delegate: Rectangle {
                required property int index
                x: 4 + index * 5; y: 17 - (6 + index * 4); width: 3; height: 6 + index * 4; radius: 1
                color: "#a6acb2"
            }
        }
        Rectangle {  // diamond
            visible: parent.kind === "diamond"
            x: 5; y: 5; width: 12; height: 12; rotation: 45; radius: 2
            color: "transparent"; border.width: 2; border.color: parent.grey
        }
    }

    component Separator: Item {
        height: 9
        Rectangle { x: 8; y: 4; width: parent.width - 16; height: 1; color: Qt.rgba(1, 1, 1, 0.13) }
    }

    // One menu row: optional radio/check indicator, label, optional shortcut, optional hover.
    component MenuRow: Item {
        property string label
        property string indicator: ""   // "", "radio", "check"
        property bool checked: false
        property bool hovered: false
        property string shortcut: ""
        height: 30

        Rectangle {  // hover: Breeze blue, translucent, with a frame
            visible: parent.hovered
            x: 4; y: 1; width: parent.width - 8; height: parent.height - 2; radius: 3
            color: Qt.rgba(61 / 255, 174 / 255, 233 / 255, 0.25)
            border.width: 1
            border.color: "#3daee9"
        }
        Rectangle {  // radio
            visible: parent.indicator === "radio"
            x: 12; y: 7; width: 16; height: 16; radius: 8
            color: "transparent"
            border.width: 1
            border.color: parent.checked ? "#3daee9" : Qt.rgba(252 / 255, 252 / 255, 252 / 255, 0.45)
            Rectangle {
                visible: parent.parent.checked
                x: 4; y: 4; width: 8; height: 8; radius: 4
                color: "#3daee9"
            }
        }
        Rectangle {  // check box (unchecked in this frame)
            visible: parent.indicator === "check"
            x: 12; y: 7; width: 16; height: 16; radius: 3
            color: "transparent"
            border.width: 1
            border.color: Qt.rgba(252 / 255, 252 / 255, 252 / 255, 0.45)
        }
        Label {
            x: 40; y: 0; height: parent.height
            text: parent.label
        }
        Label {
            visible: parent.shortcut !== ""
            x: parent.width - 14 - width; y: 0; height: parent.height
            text: parent.shortcut
            color: Qt.rgba(252 / 255, 252 / 255, 252 / 255, 0.6)
        }
    }

    // ---- panel ---------------------------------------------------------------------------------------

    Rectangle {
        id: panel
        y: frame.height - frame.panelH
        width: frame.width
        height: frame.panelH
        color: frame.panelColor
        Rectangle { width: parent.width; height: 1; color: Qt.rgba(1, 1, 1, 0.08) }  // top edge

        // Pressed look behind our icon.
        Rectangle {
            x: frame.trayX + frame.ourIndex * frame.cell
            y: 4
            width: frame.cell
            height: frame.panelH - 8
            radius: 4
            color: Qt.rgba(61 / 255, 174 / 255, 233 / 255, 0.25)
            border.width: 1
            border.color: Qt.rgba(61 / 255, 174 / 255, 233 / 255, 0.8)
        }

        Repeater {
            model: ["ring", "box", "sc3", "bars", "diamond"]
            delegate: Item {
                id: slot
                required property string modelData
                required property int index
                x: frame.trayX + index * frame.cell + (frame.cell - 22) / 2
                y: (frame.panelH - 22) / 2
                width: 22
                height: 22
                StandIn { visible: slot.modelData !== "sc3"; kind: slot.modelData }
                Image {
                    visible: slot.modelData === "sc3"
                    width: 22
                    height: 22
                    source: "../../../sc3linux/app/icons/png/sc3-connected-22-dark.png"
                }
            }
        }

        // "Show hidden icons" chevron.
        Shape {
            x: frame.trayX + 5 * frame.cell + (frame.cell - 22) / 2
            y: (frame.panelH - 22) / 2
            width: 22
            height: 22
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: "#a6acb2"
                strokeWidth: 1.5
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                joinStyle: ShapePath.RoundJoin
                startX: 6; startY: 13.5
                PathLine { x: 11; y: 8.5 }
                PathLine { x: 16; y: 13.5 }
            }
        }

        // Digital clock, time over date.
        Label {
            x: frame.width - 84
            y: 5
            width: 76
            height: 18
            horizontalAlignment: Text.AlignHCenter
            text: "21:47"
            font.pixelSize: 14
        }
        Label {
            x: frame.width - 84
            y: 23
            width: 76
            height: 16
            horizontalAlignment: Text.AlignHCenter
            text: "07.10.2026"
            font.pixelSize: 11
            color: frame.inkDim
        }
    }

    // ---- context menu ----------------------------------------------------------------------------------

    Item {
        id: menu
        x: 164
        width: 272
        height: items.height + 8
        y: panel.y - 6 - height

        // Soft shadow from stacked translucent frames (no effects).
        Repeater {
            model: 6
            delegate: Rectangle {
                required property int index
                x: -index - 1
                y: -index + 1
                width: menu.width + 2 * (index + 1)
                height: menu.height + 2 * (index + 1)
                radius: 6 + index
                color: Qt.rgba(0, 0, 0, 0.07)
            }
        }
        Rectangle {
            anchors.fill: parent
            radius: 5
            color: frame.panelColor
            border.width: 1
            border.color: "#4b5055"
        }

        Column {
            id: items
            x: 1
            y: 4
            width: menu.width - 2

            Item {  // section "Профиль": dim title followed by a rule
                width: parent.width
                height: 28
                Label {
                    id: sectionTitle
                    x: 12; y: 0; height: parent.height
                    text: "Профиль"
                    font.pixelSize: 12
                    font.bold: true
                    color: frame.inkDim
                }
                Rectangle {
                    x: sectionTitle.x + sectionTitle.implicitWidth + 8
                    y: Math.round(parent.height / 2)
                    width: parent.width - x - 12
                    height: 1
                    color: frame.line
                }
            }
            MenuRow { width: parent.width; indicator: "radio"; checked: true; label: "Подкаст" }
            MenuRow { width: parent.width; indicator: "radio"; label: "Как с завода" }
            MenuRow { width: parent.width; indicator: "radio"; label: "Без обработки" }
            Separator { width: parent.width }
            MenuRow { width: parent.width; indicator: "check"; label: "Заглушить микрофон" }
            Separator { width: parent.width }
            MenuRow { id: openRow; width: parent.width; label: "Открыть окно SC3"; hovered: true }
            MenuRow { width: parent.width; label: "Выход" }
        }
    }

    // Mouse pointer resting on "Открыть окно SC3".
    Shape {
        x: menu.x + items.x + 168
        y: menu.y + items.y + openRow.y + 12
        width: 14
        height: 22
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            fillColor: "#fcfcfc"
            strokeColor: "#141618"
            strokeWidth: 1
            joinStyle: ShapePath.MiterJoin
            startX: 0.5; startY: 0.5
            PathLine { x: 0.5; y: 16.5 }
            PathLine { x: 4.5; y: 12.8 }
            PathLine { x: 7.3; y: 19 }
            PathLine { x: 9.8; y: 17.9 }
            PathLine { x: 7.1; y: 11.9 }
            PathLine { x: 12.2; y: 11.9 }
            PathLine { x: 0.5; y: 0.5 }
        }
    }
}
