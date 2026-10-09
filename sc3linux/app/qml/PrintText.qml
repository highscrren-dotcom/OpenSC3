import QtQuick

// Silk-screen legend on the body: English, exactly as printed on the serial unit.
// Positioned by its centre (cx, cy) in the parent's coordinates.
Text {
    required property Tokens theme
    property real cx: 0
    property real cy: 0
    property real size: 15
    property bool bold: false

    x: cx - implicitWidth / 2
    y: cy - implicitHeight / 2
    color: theme.ink
    font.family: theme.fontPrint
    font.pixelSize: size
    font.bold: bold
    horizontalAlignment: Text.AlignHCenter
    lineHeight: 0.95
}
