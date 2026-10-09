import QtQuick

// A block inside a drawer: title, optional state badge, content below.
// The content is one Item (the default property, a Component), sized to the card body: it
// is created only while `ready` is true, so its bindings never see data the app does not
// have. Until then a quiet plate stands in its place and the badge is hidden; the title
// stays. The content is created inside the change notification of what `ready` reads, so
// it should read that same property (or functions of it), not one derived from it in
// parallel: such a property may still hold its old value at that moment.
Rectangle {
    id: card
    required property Tokens theme
    property string title: ""
    property string badge: ""          // e.g. "вкл"
    property bool badgeOn: true
    property bool ready: true          // false: no data for this card yet
    property string pendingText: "появится позже"
    property string pendingNote: pendingText === "появится позже"
                                 ? "приложение пока не\u00a0читает эти настройки\u00a0SC3" : ""
    default property Component content // sized to the card body

    radius: theme.uiRadius
    color: theme.drawerCard
    border.width: 1
    border.color: theme.drawerCardEdge

    Text {
        id: heading
        x: 14
        y: 11
        text: card.title
        color: card.theme.drawerText
        font.family: card.theme.fontUi
        font.pixelSize: card.theme.uiTextSize + 0.5
        font.bold: true
        font.letterSpacing: 0.2
    }

    Rectangle {
        visible: card.ready && card.badge !== ""
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.verticalCenter: heading.verticalCenter
        width: badgeText.implicitWidth + 14
        height: badgeText.implicitHeight + 4
        radius: card.theme.uiRadius === 0 ? 0 : height / 2
        color: card.badgeOn ? Qt.alpha(card.theme.accent, 0.14) : "transparent"
        border.width: 1
        border.color: card.badgeOn ? Qt.alpha(card.theme.accent, 0.55) : card.theme.drawerCardEdge
        Text {
            id: badgeText
            anchors.centerIn: parent
            text: card.badge
            color: card.badgeOn ? card.theme.accent : card.theme.drawerDim
            font.family: card.theme.fontUi
            font.pixelSize: card.theme.uiTextSize - 1.5
        }
    }

    Loader {
        id: body
        x: 14
        y: 40
        width: card.width - 28
        height: card.height - 52
        active: card.ready
        sourceComponent: card.content
    }

    // No data yet: a quiet plate in the middle of the body, no made-up numbers.
    Item {
        visible: !card.ready
        x: body.x
        y: body.y
        width: body.width
        height: body.height
        Rectangle {
            id: plate
            anchors.horizontalCenter: parent.horizontalCenter
            y: Math.round(parent.height / 2 - height)
            width: pendingLabel.implicitWidth + 24
            height: pendingLabel.implicitHeight + 10
            radius: card.theme.uiRadius === 0 ? 0 : height / 2
            color: card.theme.graphBg
            border.width: 1
            border.color: card.theme.drawerCardEdge
            Text {
                id: pendingLabel
                anchors.centerIn: parent
                text: card.pendingText
                color: card.theme.drawerDim
                font.family: card.theme.fontUi
                font.pixelSize: card.theme.uiTextSize - 1
            }
        }
        Text {
            visible: card.pendingNote !== ""
            x: 6
            y: plate.y + plate.height + 9
            width: parent.width - 12
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: card.pendingNote
            color: card.theme.drawerFaint
            font.family: card.theme.fontUi
            font.pixelSize: card.theme.uiTextSize - 2
            lineHeight: 1.1
        }
    }
}
