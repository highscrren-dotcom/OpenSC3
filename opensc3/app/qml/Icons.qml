pragma Singleton
import QtQuick

// SVG path data (24x24 box) for the Glyph component. Drawn for this project.
QtObject {
    // Microphone printed left of the level strip: capsule, cradle, stem, foot.
    readonly property string micStroke: "M9 5.5a3 3 0 0 1 6 0v6a3 3 0 0 1 -6 0z M5.5 11a6.5 6.5 0 0 0 13 0 M12 17.5v3.5 M8.5 21h7"
    readonly property string slash: "M4 4l16 16"
    // Headphones printed right of the level strip.
    readonly property string phonesStroke: "M4 17v-4.5a8 8 0 0 1 16 0v4.5"
    readonly property string phonesFill: "M3 14.2h3.6v7h-2.1a1.5 1.5 0 0 1 -1.5 -1.5z M21 14.2h-3.6v7h2.1a1.5 1.5 0 0 0 1.5 -1.5z"
    // Sun on the RGB pad: ring and eight short rays.
    readonly property string sunStroke: "M15.4 12a3.4 3.4 0 1 1 -6.8 0a3.4 3.4 0 1 1 6.8 0 "
        + "M18.4 12h2.2 M16.5 16.5l1.6 1.6 M12 18.4v2.2 M7.5 16.5l-1.6 1.6 "
        + "M5.6 12h-2.2 M7.5 7.5l-1.6 -1.6 M12 5.6v-2.2 M16.5 7.5l1.6 -1.6"
    // Padlock for controls that the app may not change.
    readonly property string lockStroke: "M8.2 10.5v-2.6a3.8 3.8 0 0 1 7.6 0v2.6"
    readonly property string lockFill: "M6.5 10.5h11a1 1 0 0 1 1 1v8a1 1 0 0 1 -1 1h-11a1 1 0 0 1 -1 -1v-8a1 1 0 0 1 1 -1z"
    // UI
    readonly property string chevronDown: "M7 10l5 5 5-5"
    readonly property string chevronUp: "M7 14l5-5 5 5"
    readonly property string check: "M5 12.5l4.5 4.5 9.5-10"
    readonly property string plus: "M12 5v14 M5 12h14"
    readonly property string usbPlug: "M9 3h6v6h-6z M7 9h10v5a5 5 0 0 1 -10 0z M12 19v3"
    readonly property string onAir: "M8.5 8.5a5 5 0 0 0 0 7 M15.5 8.5a5 5 0 0 1 0 7 M5.6 5.6a9 9 0 0 0 0 12.8 M18.4 5.6a9 9 0 0 1 0 12.8"
    readonly property string dot: "M14 12a2 2 0 1 1 -4 0a2 2 0 1 1 4 0z"
    readonly property string pencil: "M5 19l1-4 10-10 3 3-10 10z M14 7l3 3"
    // «Обновить»: a 315-degree clockwise arc with its arrowhead at the upper right.
    readonly property string refresh: "M19.5 12a7.5 7.5 0 1 1 -2.2 -5.3 M19.6 3.6v3.6h-3.6"
    readonly property string question: "M9.2 9.2a2.9 2.9 0 1 1 4.1 2.6c-.8 .4 -1.3 1 -1.3 1.9v.8 M12 17.6v.1"
}
