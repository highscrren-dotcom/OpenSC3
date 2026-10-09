import QtQuick
import QtQuick.Templates as T
import QtQuick.Effects

// Vertical channel fader built on T.Slider, so the real app gets mouse,
// wheel, keyboard and accessibility for free. Visuals: recessed slot,
// printed 0..10 scale, ribbed cap with a drop shadow and a white index line.
T.Slider {
    id: control
    orientation: Qt.Vertical
    property string label: ""

    implicitWidth: 96
    implicitHeight: 320
    topPadding: 20
    bottomPadding: 40  // the label lives below the travel

    readonly property real cx: width / 2

    background: Item {
        // Scale: ticks on both sides of the slot, numbers on the left.
        Repeater {
            model: 11
            delegate: Item {
                id: tick
                required property int index
                readonly property bool major: index % 2 === 0
                y: control.topPadding + control.availableHeight * index / 10
                width: control.width
                height: 1
                Rectangle {
                    x: control.cx - 11 - width
                    width: tick.major ? 9 : 5
                    height: 1
                    color: Theme.inkDim
                }
                Rectangle {
                    x: control.cx + 11
                    width: tick.major ? 9 : 5
                    height: 1
                    color: Theme.inkDim
                }
                Text {
                    visible: tick.major
                    text: 10 - tick.index
                    x: control.cx - 24 - width
                    y: -height / 2
                    color: Theme.inkDim
                    font.family: Theme.font
                    font.pixelSize: 9
                    font.weight: Font.Medium
                }
            }
        }

        // Slot: dark at the walls, pitch black in the middle (reads as depth).
        Rectangle {
            id: slot
            width: 6
            radius: 3
            x: control.cx - width / 2
            y: control.topPadding - 8
            height: control.availableHeight + 16
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "#151619" }
                GradientStop { position: 0.5; color: Theme.slot }
                GradientStop { position: 1.0; color: "#1b1c1f" }
            }
            border.color: "#000000"
        }
        // Light catching the lower lip of the slot.
        Rectangle {
            x: slot.x
            y: slot.y + slot.height
            width: slot.width
            height: 1
            color: "#16ffffff"
        }

        Print {
            text: control.label
            anchors.horizontalCenter: parent.horizontalCenter
            y: control.height - 18
        }
    }

    handle: Item {
        id: cap
        width: 46
        height: 30
        x: control.cx - width / 2
        y: control.topPadding + control.visualPosition * control.availableHeight - height / 2

        Rectangle {
            id: capBody
            anchors.fill: parent
            radius: 5
            gradient: Gradient {
                GradientStop { position: 0.00; color: "#686b72" }
                GradientStop { position: 0.10; color: "#4c4f55" }
                GradientStop { position: 0.50; color: "#36383d" }
                GradientStop { position: 0.90; color: "#25262a" }
                GradientStop { position: 1.00; color: "#18191b" }
            }
            border.color: "#000000"
            layer.enabled: true
            layer.effect: MultiEffect {
                shadowEnabled: true
                shadowColor: "#000000"
                shadowOpacity: 0.85
                shadowBlur: 0.6
                shadowVerticalOffset: 7
            }
        }

        // Grip ribs: dark groove + light lip, two above and two below the index.
        Repeater {
            model: [5, 9, 18, 22]
            delegate: Item {
                required property int modelData
                x: 5
                y: modelData
                width: cap.width - 10
                height: 2
                Rectangle { width: parent.width; height: 1; color: "#aa000000" }
                Rectangle { y: 1; width: parent.width; height: 1; color: "#18ffffff" }
            }
        }

        // Index line.
        Rectangle {
            x: 3
            width: cap.width - 6
            y: cap.height / 2 - 1
            height: 2
            radius: 1
            color: "#eceef2"
        }
    }
}
