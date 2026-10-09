import QtQuick
import QtQuick.Templates as T
import QtQuick.Shapes
import QtQuick.Effects

// Rotary encoder on T.Dial with an LED ring. Cap is anodised metal faked with
// a conical gradient (QtQuick.Shapes); skirt has a knurled edge; lit ring LEDs
// glow, unlit ones do not (they sit in a separate, effect-free layer).
T.Dial {
    id: control
    startAngle: -135
    endAngle: 135
    property int ledCount: 15
    property color ledColor: Theme.ledOn

    implicitWidth: 128
    implicitHeight: 128

    readonly property real cx: width / 2
    readonly property real cy: height / 2
    readonly property real ringRadius: Math.min(width, height) / 2 - 6
    readonly property real skirtRadius: ringRadius - 14
    readonly property real capRadius: skirtRadius - 8

    component RingDot: Rectangle {
        required property int index
        property real size: 5
        readonly property real a: (control.startAngle + (control.endAngle - control.startAngle) * index
                                   / (control.ledCount - 1)) * Math.PI / 180
        readonly property bool lit: index / (control.ledCount - 1) <= control.position + 1e-6
        width: size
        height: size
        radius: size / 2
        x: control.cx + Math.sin(a) * control.ringRadius - width / 2
        y: control.cy - Math.cos(a) * control.ringRadius - height / 2
    }

    background: Item {
        // Unlit ring LEDs: plain dark lenses.
        Repeater {
            model: control.ledCount
            delegate: RingDot {
                visible: !lit
                color: Theme.ledOff
                border.color: "#000000"
            }
        }
        // Halo behind lit ring LEDs: bigger dots, blurred as one layer.
        Item {
            anchors.fill: parent
            opacity: 0.55
            layer.enabled: true
            layer.effect: MultiEffect {
                blurEnabled: true
                blur: 1.0
                blurMax: 20
            }
            Repeater {
                model: control.ledCount
                delegate: RingDot {
                    visible: lit
                    size: 12
                    color: control.ledColor
                }
            }
        }
        // Lit ring LEDs with a tight glow.
        Item {
            anchors.fill: parent
            layer.enabled: true
            layer.effect: MultiEffect {
                shadowEnabled: true
                shadowColor: control.ledColor
                shadowOpacity: 1.0
                shadowBlur: 0.8
                blurMax: 16
                shadowHorizontalOffset: 0
                shadowVerticalOffset: 0
            }
            Repeater {
                model: control.ledCount
                delegate: RingDot {
                    visible: lit
                    color: control.ledColor
                }
            }
        }

        // Skirt with drop shadow.
        Rectangle {
            id: skirt
            width: control.skirtRadius * 2
            height: width
            radius: width / 2
            x: control.cx - width / 2
            y: control.cy - height / 2
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#3a3c41" }
                GradientStop { position: 1.0; color: "#1a1b1e" }
            }
            border.color: "#000000"
            layer.enabled: true
            layer.effect: MultiEffect {
                shadowEnabled: true
                shadowColor: "#000000"
                shadowOpacity: 0.85
                shadowBlur: 0.7
                shadowVerticalOffset: 6
            }
        }

        // Knurling: short radial grooves around the skirt edge.
        Repeater {
            model: 60
            delegate: Rectangle {
                required property int index
                antialiasing: true
                width: 1.2
                height: 6
                color: "#90000000"
                x: control.cx - width / 2
                y: control.cy - control.skirtRadius + 1
                transform: Rotation {
                    origin.x: 0.6
                    origin.y: control.skirtRadius - 1
                    angle: index * 6
                }
            }
        }

        // Cap: brushed/anodised look from a conical gradient.
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: "#000000"
                strokeWidth: 1
                fillGradient: ConicalGradient {
                    centerX: control.cx
                    centerY: control.cy
                    angle: 30
                    GradientStop { position: 0.00; color: "#2b2d31" }
                    GradientStop { position: 0.12; color: "#55585e" }
                    GradientStop { position: 0.25; color: "#2e3034" }
                    GradientStop { position: 0.40; color: "#46494f" }
                    GradientStop { position: 0.50; color: "#26282b" }
                    GradientStop { position: 0.62; color: "#505359" }
                    GradientStop { position: 0.75; color: "#2c2e32" }
                    GradientStop { position: 0.88; color: "#44474d" }
                    GradientStop { position: 1.00; color: "#2b2d31" }
                }
                PathAngleArc {
                    centerX: control.cx
                    centerY: control.cy
                    radiusX: control.capRadius
                    radiusY: control.capRadius
                    startAngle: 0
                    sweepAngle: 360
                }
            }
            // Soft top-left sheen.
            ShapePath {
                strokeColor: "transparent"
                strokeWidth: 0
                fillGradient: RadialGradient {
                    centerX: control.cx - control.capRadius * 0.35
                    centerY: control.cy - control.capRadius * 0.45
                    focalX: centerX
                    focalY: centerY
                    centerRadius: control.capRadius * 1.1
                    GradientStop { position: 0.0; color: "#26ffffff" }
                    GradientStop { position: 1.0; color: "#00ffffff" }
                }
                PathAngleArc {
                    centerX: control.cx
                    centerY: control.cy
                    radiusX: control.capRadius - 1
                    radiusY: control.capRadius - 1
                    startAngle: 0
                    sweepAngle: 360
                }
            }
        }

        // Pointer.
        Item {
            anchors.fill: parent
            rotation: control.angle
            Rectangle {
                width: 3
                height: control.capRadius * 0.55
                radius: 1.5
                x: control.cx - width / 2
                y: control.cy - control.capRadius + 4
                color: "#eceef2"
            }
        }
    }
}
