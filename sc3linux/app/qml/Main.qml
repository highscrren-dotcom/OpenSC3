import QtQuick
import QtQuick.Window

// The app window. Its content (Sc3Window) is laid out at the design width and scaled to the
// window width, so the panel keeps its proportions at any size; when a drawer makes it taller
// than the window, it scrolls. main.py passes the backend in as `sc3`, shows the window and
// decides what closing does: hide to the tray (closeToTray) or quit.
Window {
    id: win
    required property QtObject sc3
    property bool closeToTray: false
    property alias section: content.section
    property alias animations: content.animations
    readonly property real designWidth: content.width
    readonly property real zoom: width / content.width
    readonly property real fullHeight: content.height * zoom

    title: "SC3"
    color: "#101010"
    minimumWidth: 600
    minimumHeight: 360
    // First size: the whole panel on screen, at most 1:1.
    readonly property real fitZoom: Math.min(1, (Screen.desktopAvailableHeight - 80) / content.height,
                                             Screen.desktopAvailableWidth * 0.92 / content.width)
    width: Math.round(content.width * Math.max(0.5, fitZoom))
    height: Math.round(content.height * Math.max(0.5, fitZoom))

    onClosing: close => {
        if (win.closeToTray) {
            close.accepted = false;
            win.hide();
        } else {
            Qt.quit();
        }
    }

    Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: win.fullHeight
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height + 1

        Sc3Window {
            id: content
            sc3: win.sc3
            transformOrigin: Item.TopLeft
            scale: win.zoom
        }
    }

    // A drawer coming out pulls the view along so it is seen whole; a closing one gives the room back.
    Connections {
        target: content
        function onHeightChanged() {
            const bottom = Math.max(0, flick.contentHeight - flick.height);
            flick.contentY = content.section !== "" ? bottom : Math.min(flick.contentY, bottom);
        }
    }

    Shortcut {
        sequence: "F5"
        onActivated: win.sc3.refresh()
    }
    Shortcut {
        sequence: "Esc"
        onActivated: {
            if (content.profileOpen)
                content.profileOpen = false;
            else
                content.section = "";
        }
    }
}
