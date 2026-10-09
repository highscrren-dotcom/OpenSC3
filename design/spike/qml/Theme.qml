pragma Singleton
import QtQuick

// Shared palette for the spike. Colours with alpha use #AARRGGBB.
QtObject {
    // Desk and chassis (dark matte, powder-coat feel)
    readonly property color desk: "#0e0f11"
    readonly property color bodyTop: "#2a2b2f"
    readonly property color bodyBottom: "#1c1d20"
    readonly property color rim: "#14ffffff"
    readonly property color rimTop: "#2affffff"

    // Silk-screen print on the chassis
    readonly property color ink: "#c9cbd1"
    readonly property color inkDim: "#80838b"
    readonly property string font: "Inter"

    // Controls
    readonly property color slot: "#060607"
    readonly property color keyTop: "#3b3d42"
    readonly property color keyBottom: "#2a2b2f"
    readonly property color ledOff: "#2c2d31"
    readonly property color ledOn: "#ffffff"
}
