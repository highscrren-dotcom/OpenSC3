import QtQuick

// Design tokens of the window: variant A "Factory" chosen by the owner (BRIEF.md,
// "Выбор по макетам") - as close to a real black SC3 as possible; amber only for
// focus, trims, selection and graphs. Colours with alpha are #AARRGGBB; sizes are
// logical px at a 1120 px wide panel unless a name says "Frac".
QtObject {
    // GPU effects available? Set from GraphicsInfo by the window. When false
    // (Qt's software scene graph) every glow/shadow switches to its flat look,
    // because MultiEffect items vanish there and RectangularShadow draws nothing.
    property bool effects: true
    // Motion (brief #9: faders glide, keys press in, LEDs fade). Off for still mock-ups.
    property bool animations: true

    // --- type ---------------------------------------------------------------
    property string fontPrint: Fonts.sans     // silk-screen on the body (English, as printed)
    property string fontUi: Fonts.sans        // window chrome, drawers, tooltips (Russian)
    property string fontValue: Fonts.sans     // dB, %, ms readouts (tabular figures where it matters)
    property real uiTextSize: 13

    // --- brand accent (stream-style/brand/BRAND.md) -------------------------
    property color accent: "#FFB000"
    property color accentLight: "#FFD27A"
    property color accentDark: "#5C3D00"
    property color onAir: "#e5484d"           // universal "live" red, header and tray only
    property color warn: "#e5484d"

    // --- window ---------------------------------------------------------------
    property color windowTop: "#151515"
    property color windowBottom: "#101010"
    property real uiRadius: 6

    property real headerHeight: 46
    property color headerBg: "#191919"
    property color headerBorder: "#262626"
    property color headerText: "#dcdcdc"
    property color headerDim: "#8d8d8d"
    property color headerChip: "#232323"
    property color headerChipBorder: "#2f2f2f"
    property color statusOk: "#7cc47f"
    property color statusIdle: "#6a6a6a"

    // menus, popups, notices
    property color menuBg: "#232323"
    property color menuBorder: "#353535"
    property color menuHover: "#2f2f2f"
    property color menuText: "#e2e2e2"
    property color menuDim: "#8f8f8f"

    // --- body -----------------------------------------------------------------
    property color bodyTop: "#2d2d2d"
    property color bodyBottom: "#272727"
    property real grain: 1.0
    property color bodyRim: "#16ffffff"
    property color bodyRimTop: "#2cffffff"
    property real bodyShadowOpacity: 0.55
    property real bodyShadowBlur: 34
    property real bodyShadowOffset: 12

    // print
    property color ink: "#cfcfcf"
    property color logo: "#bdbdbd"
    property color tick: "#8e8e8e"
    property real tickWidth: 2

    // --- pads (8 big keys) ----------------------------------------------------
    property color padTop: "#161616"
    property color padTopEdge: "#1f1f1f"
    property real padGloss: 0.05
    property real padRimFrac: 0.055           // light-guide width, fraction of pad width
    property color padRimIdle: "#57595d"
    property color padTextIdle: "#a8aaad"

    // light ("function on" = white, per the manual)
    property color lightOn: "#f7f9fc"
    property color lightText: "#ffffff"
    property real lightGlow: 0.9
    property real lightHalo: 0.42

    // --- bottom row (MUTE x3, MIC MONITOR): the whole cap glows ----------------
    property color keyIdleTop: "#47494d"
    property color keyIdleBottom: "#3b3d41"
    property color keyIdleBorder: "#5c5e62"
    property color keyTextIdle: "#c3c5c9"
    property color keyTextLit: "#5a5e66"
    property real keyShadow: 0.45

    // --- faders ---------------------------------------------------------------
    property color slot: "#050505"
    property color slotWall: "#1b1b1b"
    property color capTop: "#3b3b3b"
    property color capMid: "#2c2c2c"
    property color capBottom: "#232323"
    property color capEdge: "#0c0c0c"
    property real capRibLight: 0.07
    property color capStripe: "#e8401c"
    property real capShadowOpacity: 0.65
    property real capShadowBlur: 12
    property real capShadowOffset: 7

    // --- level strip (9 + 9) --------------------------------------------------
    property color meterOff: "#56595d"
    property color meterOffEdge: "#2a2c2f"
    // Lit colours from the centre outwards (index 0 = next to the divider).
    property var meterColors: ["#5fd35a", "#5fd35a", "#5fd35a", "#5fd35a", "#5fd35a",
                               "#c8e04a", "#f2c53a", "#ff8a2a", "#ff3b3b"]
    property real meterGlow: 0.75
    property real meterHalo: 0.35

    // indicator dots (ELECTRIC keys, voices)
    property color dotOff: "#6c6e72"
    property color dotOn: "#ffffff"

    // --- software overlays ----------------------------------------------------
    property real lockedOpacity: 0.4
    property color lockColor: "#b9b9b9"
    property color lockBadge: "#1a1a1a"
    property color lockBadgeEdge: "#3a3a3a"

    property real focusGap: 5
    property real focusWidth: 2
    property real focusGlow: 0.55

    property color knobBody: "#1d1d1d"
    property color knobEdge: "#3c3c3c"
    property color knobTrack: "#3a3a3a"
    property color trimValue: "#FFB000"

    // trim strip under the body
    property color stripBg: "#181818"
    property color stripEdge: "#242424"
    property color stripText: "#8d8d8d"

    property color tipBg: "#262626"
    property color tipBorder: "#3a3a3a"
    property color tipText: "#e4e4e4"
    property color tipDim: "#9a9a9a"

    // --- drawers --------------------------------------------------------------
    property color drawerBg: "#1b1b1b"
    property color drawerBgBottom: "#171717"
    property color drawerEdge: "#2b2b2b"
    property color drawerCard: "#202020"
    property color drawerCardEdge: "#2b2b2b"
    property color drawerText: "#dadada"
    property color drawerDim: "#8b8b8b"
    property color drawerFaint: "#5e5e5e"
    property color graphBg: "#161616"
    property color graphGrid: "#262626"
    property color graphGridStrong: "#363636"
    property color graphCurve: "#FFB000"
    property color graphFill: "#1eFFB000"
    property color barTrack: "#2c2c2c"
    property color barFill: "#9a9a9a"         // neutral parameter bars; accent marks the edited one
    property real drawerShadowOpacity: 0.5
}
