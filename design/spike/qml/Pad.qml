import QtQuick
import QtQuick.Templates as T
import QtQuick.Shapes
import QtQuick.Effects

// Backlit silicone pad. Light enters from below: hot centre (radial gradient
// via QtQuick.Shapes), saturated edges, and a halo leaking around the pad
// (blurred copy via MultiEffect). checked == lit.
T.Button {
    id: control
    checkable: true
    property color lightColor: "#ffffff"
    property real radius: 11

    implicitWidth: 84
    implicitHeight: 84
    padding: 0

    background: Item {
        // Halo around the pad.
        Rectangle {
            anchors.fill: parent
            visible: control.checked
            radius: control.radius
            color: control.lightColor
            opacity: 0.6
            layer.enabled: true
            layer.effect: MultiEffect {
                blurEnabled: true
                blur: 1.0
                blurMax: 40
            }
        }

        // Dark well the pad sits in.
        Rectangle {
            anchors.fill: parent
            anchors.margins: -3
            radius: control.radius + 3
            color: "#0c0c0e"
            visible: !control.checked
        }

        // Pad body, off: dark translucent silicone.
        Shape {
            anchors.fill: parent
            visible: !control.checked
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: "#000000"
                strokeWidth: 1
                fillGradient: LinearGradient {
                    x1: 0; y1: 0; x2: 0; y2: control.height
                    GradientStop { position: 0.0; color: "#3a3c41" }
                    GradientStop { position: 1.0; color: "#2a2b2f" }
                }
                PathRectangle {
                    x: 0.5; y: 0.5
                    width: control.width - 1; height: control.height - 1
                    radius: control.radius
                }
            }
        }

        // Pad body, lit: radial falloff from a near-white core.
        Shape {
            anchors.fill: parent
            visible: control.checked
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: Qt.darker(control.lightColor, 1.8)
                strokeWidth: 1
                fillGradient: RadialGradient {
                    centerX: control.width / 2; centerY: control.height / 2
                    focalX: centerX; focalY: centerY
                    centerRadius: control.width * 0.72
                    GradientStop { position: 0.0; color: Qt.tint(control.lightColor, "#c0ffffff") }
                    GradientStop { position: 0.45; color: Qt.tint(control.lightColor, "#40ffffff") }
                    GradientStop { position: 1.0; color: Qt.darker(control.lightColor, 1.35) }
                }
                PathRectangle {
                    x: 0.5; y: 0.5
                    width: control.width - 1; height: control.height - 1
                    radius: control.radius
                }
            }
        }

        // Specular rim along the top edge (matte silicone, so very soft).
        Rectangle {
            x: control.radius
            y: 1
            width: control.width - 2 * control.radius
            height: 1
            color: control.checked ? "#66ffffff" : "#22ffffff"
        }
    }

    contentItem: Text {
        text: control.text
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        color: control.checked ? Qt.darker(control.lightColor, 2.6) : Theme.inkDim
        font.family: Theme.font
        font.pixelSize: 11
        font.weight: Font.Bold
        font.letterSpacing: 1.2
        font.capitalization: Font.AllUppercase
    }
}
