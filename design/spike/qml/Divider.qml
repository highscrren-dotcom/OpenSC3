import QtQuick

// Engraved vertical groove: dark line with a light lip on its right side.
Item {
    implicitWidth: 2
    Rectangle { x: 0; width: 1; height: parent.height; color: "#cc000000" }
    Rectangle { x: 1; width: 1; height: parent.height; color: "#10ffffff" }
}
