import QtQuick
import QtQuick.Templates as T
import QtQuick.Effects

// Raised rubber key with an LED window above its legend.
// checked == LED lit; down == key pressed (shadow shrinks, key sinks).
T.Button {
    id: control
    checkable: true
    property color ledColor: Theme.ledOn

    implicitWidth: 80
    implicitHeight: 48
    padding: 0

    background: Item {
        Rectangle {
            id: key
            anchors.fill: parent
            anchors.topMargin: control.down ? 2 : 0
            radius: 8
            gradient: Gradient {
                GradientStop { position: 0.0; color: control.down ? "#2e3034" : Theme.keyTop }
                GradientStop { position: 1.0; color: control.down ? "#232427" : Theme.keyBottom }
            }
            border.color: "#000000"
            layer.enabled: true
            layer.effect: MultiEffect {
                shadowEnabled: true
                shadowColor: "#000000"
                shadowOpacity: 0.85
                shadowBlur: 0.45
                shadowVerticalOffset: control.down ? 1 : 4
            }
        }
        // Top highlight of the key cap.
        Rectangle {
            x: key.x + key.radius
            y: key.y + 1
            width: key.width - 2 * key.radius
            height: 1
            color: "#2cffffff"
        }
    }

    contentItem: Item {
        Led {
            on: control.checked
            color: control.ledColor
            anchors.horizontalCenter: parent.horizontalCenter
            y: (control.down ? 2 : 0) + 9
        }
        Text {
            text: control.text
            anchors.horizontalCenter: parent.horizontalCenter
            y: (control.down ? 2 : 0) + parent.height - height - 9
            color: Theme.ink
            font.family: Theme.font
            font.pixelSize: 9
            font.weight: Font.DemiBold
            font.letterSpacing: 1.2
            font.capitalization: Font.AllUppercase
        }
    }
}
