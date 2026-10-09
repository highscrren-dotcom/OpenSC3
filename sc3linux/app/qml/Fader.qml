import QtQuick

// One channel fader in panel coordinates: the item is one channel pitch wide,
// spans the panel's full depth, and is centred on the slot axis. The cap is a
// mirror of the real one (display only, no motor). Scale per design/sc3-layout.md §2.4.
Item {
    id: fader
    required property Tokens theme
    required property real panelW
    required property real panelD
    property real value: 0.5          // 0 = bottom, 1 = top
    property bool locked: false       // HEADPHONE, LINE OUT: body only
    property bool known: true         // false: position unknown - a faint cap mid-travel with "?", no guess
    readonly property Item capItem: cap

    // The mirror glides to a new reading (brief #9); unknown parks it in the middle.
    readonly property real shown: known ? value : 0.5
    property real eased: shown
    Behavior on eased {
        enabled: fader.theme.animations
        NumberAnimation { duration: 420; easing.type: Easing.InOutCubic }
    }

    readonly property real cx: width / 2
    readonly property real travelTop: 0.2535 * panelD
    readonly property real travelBottom: 0.7129 * panelD
    readonly property real step: 0.0255 * panelD
    readonly property real capW: 0.066 * panelW
    readonly property real capH: 0.19 * panelD
    readonly property real capCenterY: travelBottom - eased * (travelBottom - travelTop)

    // Printed scale: 19 ticks per side, long ones at top / middle / bottom sit
    // closer to the slot.
    Item {
        anchors.fill: parent
        opacity: fader.locked ? 0.55 : 1
        Repeater {
            model: 19
            delegate: Item {
                id: tick
                required property int index
                readonly property bool major: index === 0 || index === 9 || index === 18
                readonly property real inner: (major ? 0.018 : 0.024) * fader.panelW
                readonly property real outer: (major ? 0.056 : 0.050) * fader.panelW
                y: fader.travelTop + index * fader.step - fader.theme.tickWidth / 2
                width: fader.width
                height: fader.theme.tickWidth
                Rectangle {
                    x: fader.cx - tick.outer
                    width: tick.outer - tick.inner
                    height: parent.height
                    color: fader.theme.tick
                }
                Rectangle {
                    x: fader.cx + tick.inner
                    width: tick.outer - tick.inner
                    height: parent.height
                    color: fader.theme.tick
                }
            }
        }
    }

    // Slot: dark at the walls, black in the middle; a lit lower lip reads as depth.
    Rectangle {
        id: slot
        readonly property real w: Math.max(5, 0.0085 * fader.panelW)
        x: fader.cx - w / 2
        y: 0.249 * fader.panelD
        width: w
        height: (0.718 - 0.249) * fader.panelD
        radius: w / 2
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: fader.theme.slotWall }
            GradientStop { position: 0.45; color: fader.theme.slot }
            GradientStop { position: 1.0; color: fader.theme.slot }
        }
        border.color: "#000000"
    }
    Rectangle {
        x: slot.x + 1
        y: slot.y + slot.height - 1
        width: slot.width - 2
        height: 1
        color: "#20ffffff"
    }

    FaderCap {
        id: cap
        theme: fader.theme
        width: fader.capW
        height: fader.capH
        x: fader.cx - width / 2
        y: fader.capCenterY - height / 2
        opacity: fader.known ? 1 : 0.28
        Behavior on opacity {
            enabled: fader.theme.animations
            NumberAnimation { duration: 250 }
        }
    }
    // Unknown position: a question mark on the faint cap instead of a guess.
    Rectangle {
        visible: !fader.known && !fader.locked
        x: fader.cx - width / 2
        y: fader.capCenterY - height / 2
        width: 0.024 * fader.panelW
        height: width
        radius: width / 2
        color: fader.theme.lockBadge
        border.width: 1
        border.color: fader.theme.lockBadgeEdge
        Glyph {
            anchors.centerIn: parent
            size: parent.width * 0.78
            stroke: 2.2
            color: fader.theme.lockColor
            strokePath: Icons.question
        }
    }
    // Body-only fader: fog the cap with body colour instead of making it see-through,
    // so the slot does not show through a "ghost" cap.
    Rectangle {
        visible: fader.locked && fader.known
        x: cap.x
        y: cap.y
        width: cap.width
        height: cap.height
        radius: cap.radius
        color: Qt.alpha(fader.theme.bodyBottom, 1 - fader.theme.lockedOpacity)
    }

    // Body-only fader: the mirrored cap carries the lock.
    LockBadge {
        visible: fader.locked
        theme: fader.theme
        size: 0.021 * fader.panelW
        x: fader.cx - width / 2
        y: cap.y + cap.height * 0.31 - height / 2
    }
}
