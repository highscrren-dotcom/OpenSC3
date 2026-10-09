pragma Singleton
import QtQuick

// Fonts shipped with the app (SIL OFL 1.1, licence next to the files in ../fonts).
// Components only ever use the family string below, never whatever fontconfig has.
//   sans - Arimo: metric clone of Arial, closest to the print on the SC3 body; also
//          carries Cyrillic for the Russian UI.
QtObject {
    readonly property FontLoader arimo: FontLoader { source: Qt.resolvedUrl("../fonts/Arimo-Regular.ttf") }
    readonly property FontLoader arimoBold: FontLoader { source: Qt.resolvedUrl("../fonts/Arimo-Bold.ttf") }

    readonly property string sans: arimo.font.family
}
