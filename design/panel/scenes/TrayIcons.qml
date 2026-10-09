import QtQuick
import "../../../opensc3/app/qml"

// Contact sheet of the tray icons: four states (rows) at 22 and 32 px on a Breeze Dark and a
// Breeze panel strip, plus the 22 px icon blown up x3 with nearest-neighbour sampling so the
// pixel grid can be checked. Images are the PNGs from ../icons/export.py (opensc3/app/icons/png).
// Root is a plain Rectangle sized by itself, for the off-screen renderer.
Rectangle {
    id: sheet

    readonly property var iconStates: [
        { key: "connected", title: "Подключён", note: "SC3 на связи, MIC открыт" },
        { key: "muted", title: "MIC заглушён", note: "косая черта цвета NegativeText" },
        { key: "disconnected", title: "Отключён", note: "знак на 40 %, крестик в углу" },
        { key: "onair", title: "Идёт эфир", note: "красная точка, как REC" },
        { key: "onair-muted", title: "Эфир, MIC заглушён", note: "через PipeWire: черта + точка" }
    ]
    readonly property color inkDim: "#a1a9b1"
    readonly property color darkPanel: "#2a2e32"
    readonly property color lightPanel: "#eff0f1"

    readonly property int pad: 32
    readonly property int labelW: 280
    readonly property int cellW: 84
    readonly property int rowH: 76
    readonly property int headH: 92
    readonly property int zoom: 3
    readonly property int zoomCell: 22 * zoom + 6

    readonly property int darkX: pad + labelW
    readonly property int lightX: darkX + 2 * cellW + 20
    readonly property int zoomX: lightX + 2 * cellW + 36

    width: zoomX + 2 * zoomCell + 12 + pad
    height: headH + iconStates.length * rowH + 52
    color: "#141618"

    // Inline components cannot see the ids of this file: everything they need is set at the use site.
    component Label: Text {
        color: "#fcfcfc"
        font.family: Fonts.sans
        font.pixelSize: 13
    }

    Label {
        x: sheet.pad
        y: 24
        text: "Значки трея SC3"
        font.pixelSize: 20
        font.bold: true
    }
    Label {
        x: sheet.pad
        y: 54
        text: "символьные, в духе Breeze"
        color: sheet.inkDim
    }

    // Column heads.
    Label { x: sheet.darkX; y: 30; text: "Тёмная панель"; font.bold: true }
    Label { x: sheet.lightX; y: 30; text: "Светлая панель"; font.bold: true }
    Label { x: sheet.zoomX; y: 30; text: "22 px ×" + sheet.zoom + ", по пикселям"; font.bold: true }
    Repeater {
        model: [sheet.darkX, sheet.lightX]
        delegate: Item {
            id: head
            required property int modelData
            Label {
                x: head.modelData
                y: 56
                width: sheet.cellW
                horizontalAlignment: Text.AlignHCenter
                text: "22 px"
                color: sheet.inkDim
            }
            Label {
                x: head.modelData + sheet.cellW
                y: 56
                width: sheet.cellW
                horizontalAlignment: Text.AlignHCenter
                text: "32 px"
                color: sheet.inkDim
            }
        }
    }
    Label {
        x: sheet.zoomX
        y: 56
        width: sheet.zoomCell
        horizontalAlignment: Text.AlignHCenter
        text: "тёмная"
        color: sheet.inkDim
    }
    Label {
        x: sheet.zoomX + sheet.zoomCell + 12
        y: 56
        width: sheet.zoomCell
        horizontalAlignment: Text.AlignHCenter
        text: "светлая"
        color: sheet.inkDim
    }

    // Panel strips, one column per theme, under all rows.
    Repeater {
        model: [{ x: sheet.darkX, bg: sheet.darkPanel }, { x: sheet.lightX, bg: sheet.lightPanel }]
        delegate: Rectangle {
            required property var modelData
            x: modelData.x
            y: sheet.headH - 8
            width: 2 * sheet.cellW
            height: sheet.iconStates.length * sheet.rowH + 16
            radius: 6
            color: modelData.bg
        }
    }

    Repeater {
        model: sheet.iconStates
        delegate: Item {
            id: row
            required property var modelData
            required property int index
            readonly property string base: "../../../opensc3/app/icons/png/sc3-" + modelData.key
            y: sheet.headH + index * sheet.rowH
            width: sheet.width
            height: sheet.rowH

            Rectangle {  // rule between rows, label column only
                visible: row.index > 0
                x: sheet.pad
                width: sheet.labelW - 24
                height: 1
                color: "#2c3034"
            }
            Label {
                x: sheet.pad
                y: 18
                text: row.modelData.title
                font.pixelSize: 15
                font.bold: true
            }
            Label {
                x: sheet.pad
                y: 41
                text: row.modelData.note
                color: sheet.inkDim
                font.pixelSize: 12
            }

            // 1:1 icons on whole pixels.
            Image {
                x: sheet.darkX + (sheet.cellW - 22) / 2
                y: (sheet.rowH - 22) / 2
                source: row.base + "-22-dark.png"
            }
            Image {
                x: sheet.darkX + sheet.cellW + (sheet.cellW - 32) / 2
                y: (sheet.rowH - 32) / 2
                source: row.base + "-32-dark.png"
            }
            Image {
                x: sheet.lightX + (sheet.cellW - 22) / 2
                y: (sheet.rowH - 22) / 2
                source: row.base + "-22-light.png"
            }
            Image {
                x: sheet.lightX + sheet.cellW + (sheet.cellW - 32) / 2
                y: (sheet.rowH - 32) / 2
                source: row.base + "-32-light.png"
            }

            // The 22 px icon enlarged, nearest neighbour.
            Repeater {
                model: [{ theme: "dark", bg: sheet.darkPanel }, { theme: "light", bg: sheet.lightPanel }]
                delegate: Rectangle {
                    id: zoomed
                    required property var modelData
                    required property int index
                    x: sheet.zoomX + index * (sheet.zoomCell + 12)
                    y: (sheet.rowH - sheet.zoomCell) / 2
                    width: sheet.zoomCell
                    height: sheet.zoomCell
                    radius: 4
                    color: modelData.bg
                    Image {
                        x: 3
                        y: 3
                        width: 22 * sheet.zoom
                        height: 22 * sheet.zoom
                        smooth: false
                        mipmap: false
                        source: row.base + "-22-" + zoomed.modelData.theme + ".png"
                    }
                }
            }
        }
    }

    Label {
        x: sheet.pad
        y: sheet.height - 34
        width: sheet.width - 2 * sheet.pad
        elide: Text.ElideRight
        color: sheet.inkDim
        font.pixelSize: 12
        text: "Знак — SC3 сверху: корпус 164:113, четыре ползунка. Цвета — текст панели (#fcfcfc / #232629) "
            + "и NegativeText #da4453."
    }
}
