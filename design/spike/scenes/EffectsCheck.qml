import QtQuick
import QtQuick.Shapes
import QtQuick.Effects
import "../qml"

// Backend check: one tile per rendering feature the skeuomorphic UI relies on.
// A blank tile means the current scene graph backend cannot draw that feature
// (e.g. every MultiEffect / RectangularShadow tile under the software backend).
Rectangle {
    id: scene
    width: 800
    height: 360
    color: Theme.desk

    component Tile: Item {
        default property alias body: holder.data
        property string caption
        width: 150
        height: 160
        Rectangle { anchors.fill: parent; radius: 10; color: "#1d1e21"; border.color: "#000000" }
        Item { id: holder; x: 25; y: 18; width: 100; height: 100 }
        Text {
            text: parent.caption
            x: 8; y: parent.height - 30
            width: parent.width - 16
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            color: Theme.ink
            font.family: Theme.font
            font.pixelSize: 10
        }
    }

    Grid {
        x: 15
        y: 15
        columns: 5
        spacing: 7

        Tile {
            caption: "Rectangle gradient"
            Rectangle {
                anchors.fill: parent
                radius: 12
                gradient: Gradient {
                    GradientStop { position: 0; color: "#6b6e75" }
                    GradientStop { position: 1; color: "#1e1f22" }
                }
            }
        }
        Tile {
            caption: "Shapes linear (CurveRenderer)"
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: "#000000"
                    fillGradient: LinearGradient {
                        x1: 0; y1: 0; x2: 100; y2: 100
                        GradientStop { position: 0; color: "#4cc2ff" }
                        GradientStop { position: 1; color: "#ff4fd2" }
                    }
                    PathRectangle { x: 0.5; y: 0.5; width: 99; height: 99; radius: 14 }
                }
            }
        }
        Tile {
            caption: "Shapes radial"
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: "transparent"
                    fillGradient: RadialGradient {
                        centerX: 50; centerY: 50; focalX: 50; focalY: 50; centerRadius: 50
                        GradientStop { position: 0; color: "#ffffffff" }
                        GradientStop { position: 1; color: "#00ffffff" }
                    }
                    PathAngleArc { centerX: 50; centerY: 50; radiusX: 50; radiusY: 50; sweepAngle: 360 }
                }
            }
        }
        Tile {
            caption: "Shapes conical"
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: "#000000"
                    fillGradient: ConicalGradient {
                        centerX: 50; centerY: 50; angle: 30
                        GradientStop { position: 0.00; color: "#2b2d31" }
                        GradientStop { position: 0.25; color: "#6a6d74" }
                        GradientStop { position: 0.50; color: "#2b2d31" }
                        GradientStop { position: 0.75; color: "#6a6d74" }
                        GradientStop { position: 1.00; color: "#2b2d31" }
                    }
                    PathAngleArc { centerX: 50; centerY: 50; radiusX: 48; radiusY: 48; sweepAngle: 360 }
                }
            }
        }
        Tile {
            caption: "Text: Inter, Кириллица 0–9"
            Column {
                anchors.centerIn: parent
                Text { text: "MUTE"; color: Theme.ink; font.family: Theme.font; font.pixelSize: 9; font.letterSpacing: 1.4; font.weight: Font.DemiBold }
                Text { text: "Микрофон"; color: Theme.ink; font.family: Theme.font; font.pixelSize: 14 }
                Text { text: "−12 dB"; color: Theme.ink; font.family: Theme.font; font.pixelSize: 22; font.weight: Font.Bold }
            }
        }
        Tile {
            caption: "MultiEffect shadow"
            Rectangle {
                anchors.fill: parent
                anchors.margins: 12
                radius: 10
                color: "#3b3d42"
                layer.enabled: true
                layer.effect: MultiEffect {
                    shadowEnabled: true; shadowColor: "#000000"; shadowOpacity: 0.9
                    shadowBlur: 0.8; shadowVerticalOffset: 10
                }
            }
        }
        Tile {
            caption: "MultiEffect glow (shadow at 0,0)"
            Rectangle {
                anchors.centerIn: parent
                width: 30; height: 30; radius: 15
                color: "#ffffff"
                layer.enabled: true
                layer.effect: MultiEffect {
                    shadowEnabled: true; shadowColor: "#ffffff"; shadowOpacity: 1
                    shadowBlur: 1; blurMax: 48; shadowHorizontalOffset: 0; shadowVerticalOffset: 0
                }
            }
        }
        Tile {
            caption: "MultiEffect blur"
            Rectangle {
                anchors.fill: parent
                anchors.margins: 20
                radius: 8
                color: "#4cc2ff"
                layer.enabled: true
                layer.effect: MultiEffect { blurEnabled: true; blur: 1; blurMax: 32 }
            }
        }
        Tile {
            caption: "RectangularShadow (6.9+)"
            RectangularShadow {
                anchors.fill: inset
                offset.y: 8
                blur: 18
                radius: inset.radius
                color: "#000000"
            }
            Rectangle { id: inset; anchors.fill: parent; anchors.margins: 14; radius: 10; color: "#3b3d42" }
        }
        Tile {
            caption: "Canvas grain + chassis"
            Chassis { anchors.fill: parent; radius: 12 }
        }
    }
}
