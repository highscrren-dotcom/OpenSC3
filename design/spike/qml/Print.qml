import QtQuick

// Silk-screen legend printed on the chassis.
Text {
    property bool dim: false
    color: dim ? Theme.inkDim : Theme.ink
    font.family: Theme.font
    font.pixelSize: 10
    font.weight: Font.DemiBold
    font.letterSpacing: 1.4
    font.capitalization: Font.AllUppercase
}
