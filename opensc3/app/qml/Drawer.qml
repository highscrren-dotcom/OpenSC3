import QtQuick

// Drawer of one panel section (brief #4), sliding out from under the trim strip:
// its top `tuck` px stay hidden under the strip. Title row, then the content
// (default property) in a row of cards. Drawers only show what is read from the SC3;
// writing goes through the trim knob and the profile menu.
Item {
    id: drawer
    required property Tokens theme
    property string title: ""
    property string subtitle: ""
    property real notchX: 0            // centre of the owning section, drawer coordinates
    property real notchW: 140
    property real bodyHeight: 246
    property string note: "Только просмотр"
    default property alias content: body.data
    signal collapse()
    readonly property real tuck: 22
    readonly property real ts: theme.uiTextSize
    readonly property real innerWidth: width - 40

    implicitHeight: tuck + 50 + bodyHeight + 20

    Shadow {
        anchors.fill: bg
        theme: drawer.theme
        radius: bg.radius
        offsetY: 14
        blur: 40
        color: Qt.rgba(0, 0, 0, drawer.theme.drawerShadowOpacity)
    }
    Rectangle {
        id: bg
        anchors.fill: parent
        radius: drawer.theme.uiRadius + 4
        gradient: Gradient {
            GradientStop { position: 0.0; color: drawer.theme.drawerBg }
            GradientStop { position: 1.0; color: drawer.theme.drawerBgBottom }
        }
        border.width: 1
        border.color: drawer.theme.drawerEdge
    }
    // The strip above shades the top of the drawer.
    Rectangle {
        y: drawer.tuck
        width: parent.width
        height: 18
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#70000000" }
            GradientStop { position: 1.0; color: "#00000000" }
        }
    }
    // Which section owns the drawer: amber mark under its column.
    Rectangle {
        x: drawer.notchX - drawer.notchW / 2
        y: drawer.tuck
        width: drawer.notchW
        height: 2
        color: drawer.theme.accent
    }

    Row {
        x: 20
        y: drawer.tuck + 14
        spacing: 10
        Text {
            id: titleText
            text: drawer.title
            color: drawer.theme.drawerText
            font.family: drawer.theme.fontUi
            font.pixelSize: drawer.ts + 4
            font.bold: true
            font.letterSpacing: 1
        }
        Text {
            anchors.baseline: titleText.baseline
            text: drawer.subtitle
            color: drawer.theme.drawerDim
            font.family: drawer.theme.fontUi
            font.pixelSize: drawer.ts + 1
        }
    }
    Row {
        id: rightRow
        anchors.right: parent.right
        anchors.rightMargin: 20
        y: drawer.tuck + 15
        spacing: 18
        Text {
            text: drawer.note
            color: drawer.theme.drawerDim
            font.family: drawer.theme.fontUi
            font.pixelSize: drawer.ts - 0.5
        }
        Row {
            id: collapseRow
            spacing: 4
            Text {
                text: "Свернуть"
                color: drawer.theme.drawerText
                font.family: drawer.theme.fontUi
                font.pixelSize: drawer.ts - 0.5
            }
            Glyph {
                size: 15
                stroke: 2.4
                color: drawer.theme.drawerText
                strokePath: Icons.chevronUp
            }
        }
    }

    MouseArea {   // «Свернуть»
        x: rightRow.x + collapseRow.x - 6
        y: drawer.tuck + 8
        width: collapseRow.width + 12
        height: collapseRow.height + 14
        cursorShape: Qt.PointingHandCursor
        onClicked: drawer.collapse()
    }

    Item {
        id: body
        x: 20
        y: drawer.tuck + 50
        width: drawer.innerWidth
        height: drawer.bodyHeight
    }
}
