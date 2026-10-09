import QtQuick
import "../../../sc3linux/app/qml"

// One frame of the app window for the mock-ups: the app's own window content
// (sc3linux/app/qml/Sc3Window.qml) with fixed demo data (DemoState.qml) instead of the
// live backend. Root is an Item so the off-screen renderer can size the frame itself.
// Initial properties from render.py:
//   frame: panel | tip-custom | drawer-mic | drawer-voice | drawer-electric |
//          disconnected | onair | onair-muted | muted | profiles
//   software: true when rendered by Qt's software scene graph (flat fallbacks)
Item {
    id: frameRoot
    property string frame: "panel"
    property bool software: false

    readonly property bool drawerOpen: frame.startsWith("drawer-")

    width: content.width
    height: content.height

    DemoState {
        id: demo
        link: frameRoot.frame === "disconnected" ? "disconnected" : "connected"
        onAir: frameRoot.frame === "onair" || frameRoot.frame === "onair-muted"
        muteMic: frameRoot.frame === "muted"
        pipewireMute: frameRoot.frame === "onair-muted"
        levelIn: muteMic || pipewireMute || !connected ? 0 : 0.6
        levelOut: connected ? 0.44 : 0
        micMonitor: connected
        electricKey: connected ? "C" : ""
        voice: connected ? "Male" : ""
        customLit: connected ? "A" : ""
    }

    Sc3Window {
        id: content
        sc3: demo
        software: frameRoot.software
        animations: false
        section: frameRoot.drawerOpen ? frameRoot.frame.slice(7) : ""
        forcedFocus: frameRoot.frame === "panel" || frameRoot.frame === "muted" ? "muteMic" : ""
        forcedTip: frameRoot.frame === "panel" ? "rgb" : frameRoot.frame === "tip-custom" ? "custom"
                 : frameRoot.frame === "onair" ? "mute-onair" : ""
        profileOpen: frameRoot.frame === "profiles"
        forcedProfileHover: profileOpen ? 1 : -1
    }
}
