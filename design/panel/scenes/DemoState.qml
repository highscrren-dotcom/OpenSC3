import QtQuick
import "demo-dsp.js" as DemoDsp

// Fixed demo data in the shape of the app's backend object (opensc3/app/backend.py, Backend;
// field meaning: opensc3/app/view.py): the mock-ups render the app's own QML
// (opensc3/app/qml) with this object in place of the live one. Tweaked per frame by Window.qml.
QtObject {
    // --- SC3 itself: ACP reads (in the app only at start, reconnect, window shown and «Обновить»)
    property string link: "connected"      // connected | disconnected | no_access | foreign | error
    readonly property bool connected: link === "connected"
    property string firmware: "V22"
    property real faderMic: 0.80           // 0 = bottom, 1 = top
    property real faderLineIn: 0.52
    property real faderHeadphone: 0.66
    property real faderLineOut: 0.40
    property bool muteMic: false           // hardware Mute of the SC3 (key lit white)
    property bool muteLineIn: false
    property bool muteLineOut: false
    property bool micMonitor: true
    property bool phantom: false           // 48V: body only
    property string electricKey: "C"       // as printed; "" = ELECTRIC off
    property string voice: "Male"          // as printed; "" = CHANGE VOICE off
    property string customLit: "A"         // CUSTOM pad that is lit (playing)
    property real trimMic: 2.5             // software trims under the MIC and LINE IN faders, dB
    property bool trimMicPending: false    // the MIC trim is still being written (asked, not read back)
    property real trimLineIn: 0.0          // LINE IN trim: not written yet (its path to the PC is unproven)
    property bool writeEnabled: true       // the write fuse in the header gear («Разрешить запись в SC3»)
    property var unknown: ({})             // field -> true when it is not known: drawn neutral, no guess
    property var guess: ({})               // key -> true when it is lit by the poll's guess (MUTE): «≈» on the cap
    property var dsp: DemoDsp.dsp          // drawer data (EQ, gate, voices...): synthetic, mock-ups only
    property string lastPoll: "21:04"      // time of the last ACP read
    property string acpNote: ""            // why the SC3 is not read right now
    property bool busy: false              // a read is running
    property bool polling: false           // live poll of the SC3 is running (DECISIONS.md, 9)

    // --- PipeWire: live levels, 0..1 of the 9-LED half, and the software mute
    property bool audioPresent: true
    property bool pipewireMute: false      // the SC3 input muted in PipeWire, key stays dark
    property real levelIn: 0.60            // to the PC: microphone
    property real levelOut: 0.44           // from the PC: headphones

    // --- OBS
    property bool onAir: false
    property string live: onAir ? "on" : "off"   // off | on | unknown
    readonly property bool frozen: live !== "off"
    property string onAirTime: "1:23:45"

    // --- sound profiles: the app's menu rows also carry action / enabled / active (Backend)
    property string profile: "Подкаст"
    property string profileHint: ""        // why the menu rows are disabled
    property string writeTitle: ""         // a profile being written: «Подкаст: 12 из 24» and «Стоп»
    property int writeDone: 0
    property int writeTotal: 0
    property var profiles: [
        { name: "Подкаст", note: "EQ голоса, гейт и компрессор" },
        { name: "Как с завода", note: "настройки SC3 из коробки" },
        { name: "Без обработки", note: "чистый сигнал микрофона" }
    ]

    function refresh() {}
    function toggleMicMute() {}
    function setMicTrim(db) { trimMic = db; }
    function setWriteEnabled(on) { writeEnabled = on; }
    function profileAction(action) {}
    function stopWrite() {}
}
