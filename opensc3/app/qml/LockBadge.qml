import QtQuick

// "Only on the body" mark: a small padlock on a dark badge.
Rectangle {
    id: badge
    required property Tokens theme
    property real size: 22
    width: size
    height: size
    radius: theme.uiRadius === 0 ? 0 : size / 2
    color: theme.lockBadge
    border.width: 1
    border.color: theme.lockBadgeEdge

    Glyph {
        anchors.centerIn: parent
        size: badge.size * 0.72
        stroke: 2.2
        color: badge.theme.lockColor
        strokePath: Icons.lockStroke
        fillPath: Icons.lockFill
    }
}
