import QtQuick

// Everything inside the app window: header, the SC3 panel, the trim strip under it and the
// section drawer that slides out from under the strip. One copy for the app (Main.qml, with
// the live backend) and the mock-ups (design/panel/scenes/Window.qml, with DemoState).
// Laid out at a fixed logical width; Main.qml scales it to the window.
Rectangle {
    id: win
    required property QtObject sc3     // Backend (app) or DemoState (mock-ups): same shape
    property bool software: false      // force the flat look (Qt's software scene graph)
    property bool animations: true     // off for still mock-ups
    property string section: ""        // "mic" | "voice" | "electric": drawer open
    property string forcedTip: ""      // mock-ups: tooltip shown without hover
    property string forcedFocus: ""    // mock-ups: element drawn with keyboard focus
    property bool profileOpen: false
    property bool settingsOpen: false    // the header gear's menu (write fuse)
    property int forcedProfileHover: -1  // mock-ups: profile menu row drawn as hovered

    // Section whose drawer is on screen: kept while the drawer slides back in.
    property string lastSection: ""
    onSectionChanged: if (section !== "") lastSection = section
    Component.onCompleted: if (section !== "") lastSection = section
    readonly property string shownSection: section !== "" ? section : drawerShown > 0 ? lastSection : ""

    // 0 = drawer hidden under the strip, 1 = fully out (brief #9: smooth, no sound).
    property real drawerShown: section !== "" ? 1 : 0
    Behavior on drawerShown {
        enabled: tokens.animations
        NumberAnimation { duration: 320; easing.type: Easing.OutCubic }
    }

    Tokens {
        id: tokens
        effects: !win.software && win.GraphicsInfo.api !== GraphicsInfo.Software
        animations: win.animations
    }

    readonly property real margin: 40
    readonly property real stripBottom: strip.y + strip.height
    readonly property real drawerBottom: drawerSlot.y + drawer.yOpen + (drawer.item ? drawer.item.height : 0)
    width: 1200
    height: stripBottom + 40 + (drawerBottom - stripBottom) * drawerShown

    gradient: Gradient {
        GradientStop { position: 0.0; color: tokens.windowTop }
        GradientStop { position: 1.0; color: tokens.windowBottom }
    }

    // Drawer first: it slides out from under the strip. The slot clips only what would show
    // above the strip; its sides and bottom leave room for the drawer's shadow.
    Item {
        id: drawerSlot
        readonly property real pad: 70                   // room for the shadow
        x: strip.x - pad
        y: strip.y + strip.height / 2
        width: strip.width + 2 * pad
        height: (drawer.item ? drawer.item.height : 0) + pad
        clip: win.drawerShown < 1
        visible: win.drawerShown > 0

        Loader {
            id: drawer
            x: drawerSlot.pad
            // Fully out, the top `tuck` px of the drawer stay under the strip (Drawer.qml).
            readonly property real yOpen: strip.height / 2 - 22
            y: yOpen - (item ? item.height : 0) * (1 - win.drawerShown)
            width: strip.width
            active: win.shownSection !== ""
            sourceComponent: win.shownSection === "mic" ? micDrawer
                           : win.shownSection === "voice" ? voiceDrawer : electricDrawer
        }
    }
    Component {
        id: micDrawer
        MicDrawer {
            theme: tokens
            sc3: win.sc3
            notchX: panel.fx(0.294) - 22
            notchW: panel.fx(0.119)
            onCollapse: win.section = ""
        }
    }
    Component {
        id: voiceDrawer
        VoiceDrawer {
            theme: tokens
            sc3: win.sc3
            notchX: panel.fx(0.8715) - 22
            notchW: panel.fx(0.17)
            onCollapse: win.section = ""
        }
    }
    Component {
        id: electricDrawer
        ElectricDrawer {
            theme: tokens
            sc3: win.sc3
            notchX: panel.fx(0.1275) - 22
            notchW: panel.fx(0.195)
            onCollapse: win.section = ""
        }
    }

    TrimStrip {
        id: strip
        z: 1   // its tooltips rise over the panel's bottom edge
        theme: tokens
        sc3: win.sc3
        forcedTip: win.forcedTip
        panelW: panel.width
        panelX: 22
        x: panel.x + 22
        width: panel.width - 44
        y: panel.y + panel.height + 12
    }

    Sc3Panel {
        id: panel
        theme: tokens
        sc3: win.sc3
        section: win.section
        forcedTip: win.forcedTip
        forcedFocus: win.forcedFocus
        x: win.margin
        y: header.height + 28
        width: win.width - 2 * win.margin
        opacity: win.sc3.connected ? 1 : 0.4
        onSectionClicked: name => win.section = win.section === name ? "" : name
        onMicMuteClicked: win.sc3.toggleMicMute()
    }

    // Why the panel cannot show live SC3 state (the panel is dimmed under it).
    readonly property var notices: ({
        "disconnected": {
            title: "SC3 отключён — голоса в эфире нет",
            text: "Микрофон подключён к SC3, поэтому без микшера звук голоса в ПК не идёт. "
                  + "Проверьте кабель USB-C — окно оживёт само, как только SC3 появится."
        },
        "no_access": {
            title: "Нет прав на USB-узел SC3",
            text: "SC3 на месте и звук идёт, но читать его состояние нельзя. Поставьте правило udev "
                  + "из папки udev/ (команда — в README), переподключите SC3 и проверьте: sc3 doctor."
        },
        "foreign": {
            title: "Чужая сборка прошивки SC3",
            text: "SC3 ответил сборкой не V22. Чтобы ничего не испортить, приложение его не читает: "
                  + "звук и уровни работают, панель — нет. Подробности: sc3 doctor."
        },
        "error": {
            title: "SC3 не отвечает на чтения",
            text: "Устройство на месте, но чтения ACP не проходят. Нажмите «Обновить» чуть позже "
                  + "или переподключите кабель."
        }
    })
    Notice {
        readonly property var info: win.notices[win.sc3.link]
        visible: info !== undefined
        theme: tokens
        width: 500
        x: panel.x + (panel.width - width) / 2
        y: panel.y + panel.height * 0.42 - height / 2
        title: info ? info.title : ""
        text: !info ? "" : win.sc3.link === "error" && win.sc3.acpNote !== ""
              ? info.text + "\nПричина: " + win.sc3.acpNote : info.text
    }

    Header {
        id: header
        z: 5   // the profile menu hangs over the panel
        theme: tokens
        sc3: win.sc3
        width: parent.width
        profileOpen: win.profileOpen
        profileHover: win.forcedProfileHover
        settingsOpen: win.settingsOpen
        onProfileClicked: {
            win.settingsOpen = false;
            win.profileOpen = !win.profileOpen;
        }
        onSettingsClicked: {
            win.profileOpen = false;
            win.settingsOpen = !win.settingsOpen;
        }
        onRefreshClicked: win.sc3.refresh()
    }

    // A click anywhere else closes the open menu.
    MouseArea {
        z: 4
        anchors.fill: parent
        visible: win.profileOpen || win.settingsOpen
        onClicked: {
            win.profileOpen = false;
            win.settingsOpen = false;
        }
    }
}
