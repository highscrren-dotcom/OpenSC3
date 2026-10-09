import QtQuick
import "../qml"

// All spike elements on a dark matte chassis, in both off and on states.
Rectangle {
    width: 980
    height: 480
    color: Theme.desk

    Chassis {
        x: 40
        y: 30
        width: 900
        height: 410

        Print { x: 24; y: 18; dim: true; text: "SC3 · UI spike" }

        // Faders
        Row {
            x: 18
            y: 44
            spacing: 4
            Fader { label: "Mic"; value: 0.86 }
            Fader { label: "Phones"; value: 0.62 }
            Fader { label: "Line out"; value: 0.38 }
        }

        Divider { x: 330; y: 40; height: 340 }

        // LED keys: lit, unlit and one held down
        Print { x: 356; y: 40; dim: true; text: "Mute" }
        Row {
            x: 356
            y: 58
            spacing: 16
            LedButton { text: "Mic"; checked: true }
            LedButton { text: "Phones" }
            LedButton { text: "Line" }
        }
        Print { x: 356; y: 124; dim: true; text: "Voice" }
        Row {
            x: 356
            y: 142
            spacing: 16
            LedButton { text: "Monitor"; checked: true }
            LedButton { text: "Electric" }
            LedButton { text: "Custom"; checked: true; down: true }
        }

        // Encoder with LED ring
        Knob {
            x: 356 + (272 - width) / 2
            y: 214
            value: 0.58
        }
        Print { x: 356; y: 360; width: 272; horizontalAlignment: Text.AlignHCenter; text: "Voice FX" }

        Divider { x: 652; y: 40; height: 340 }

        // Backlit pads
        Print { x: 676; y: 40; dim: true; text: "Pads" }
        Grid {
            x: 676
            y: 58
            columns: 2
            spacing: 16
            Pad { text: "1"; checked: true }
            Pad { text: "2" }
            Pad { text: "3" }
            Pad { text: "4"; checked: true; lightColor: "#4cc2ff" }
            Pad { text: "5"; checked: true; lightColor: "#ff4fd2" }
            Pad { text: "6" }
        }
    }
}
