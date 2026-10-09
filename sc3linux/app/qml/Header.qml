import QtQuick

// Narrow window header above the panel (Russian): connection, sound profile, microphone
// mute and on-air state. Deliberately quiet - the panel is the main thing.
Rectangle {
    id: header
    required property Tokens theme
    required property QtObject sc3     // Backend (app) or DemoState (mock-ups): same shape
    property bool profileOpen: false
    property int profileHover: -1      // mock-ups: profile row drawn as hovered
    signal profileClicked()
    signal refreshClicked()
    readonly property Item profileChip: chip          // the profile menu hangs under it
    readonly property real ts: theme.uiTextSize

    readonly property var linkWords: ({
        "connected": "подключён", "disconnected": "отключён", "no_access": "нет доступа",
        "foreign": "чужая прошивка", "error": "не отвечает"
    })
    // Second line of the connection block: where the data comes from and how old it is.
    readonly property string statusText: {
        const s = header.sc3;
        if (s.link === "disconnected") return "голоса в эфире нет";
        if (s.link === "no_access") return "нет прав на USB-узел · проверка: sc3 doctor";
        if (s.link === "foreign") return "сборка не V22 · SC3 не читаем";
        if (s.link === "error") return s.acpNote !== "" ? s.acpNote : "чтения ACP не проходят";
        const when = s.lastPoll !== "" ? "данные на " + s.lastPoll : "данных ещё нет";
        if (s.frozen) return "опрос SC3 на паузе · " + when;
        if (s.acpNote !== "") return when + " · " + s.acpNote;
        return "USB · прошивка " + (s.firmware !== "" ? s.firmware : "?") + " · "
             + (s.polling ? "в реальном времени" : when) + (s.audioPresent ? "" : " · нет в PipeWire");
    }

    implicitHeight: theme.headerHeight
    color: theme.headerBg

    component Ui: Text {
        color: header.theme.headerText
        font.family: header.theme.fontUi
        font.pixelSize: header.ts
        anchors.verticalCenter: parent ? parent.verticalCenter : undefined
    }
    component Dot: Rectangle {
        width: 8
        height: 8
        radius: 4
        anchors.verticalCenter: parent ? parent.verticalCenter : undefined
    }

    Rectangle {
        anchors.bottom: parent.bottom
        width: parent.width
        height: 1
        color: header.theme.headerBorder
    }

    // ---- left: device and connection
    Row {
        id: linkRow
        x: 24
        height: parent.height
        spacing: 9
        Dot { color: header.sc3.connected ? header.theme.statusOk : header.theme.warn }
        Ui {
            text: "SC3"
            font.pixelSize: header.ts + 1
            font.bold: true
            font.letterSpacing: 0.5
        }
        Ui { text: header.linkWords[header.sc3.link] || header.sc3.link }
        Ui {
            id: statusLine
            leftPadding: 10
            // Up to the profile block; the rest is elided (the full text is in the tray tooltip).
            width: Math.min(implicitWidth, profileRow.x - linkRow.x - x - refresh.width - 2 * linkRow.spacing - 16)
            elide: Text.ElideRight
            text: header.statusText
            color: header.sc3.connected ? header.theme.headerDim : header.theme.warn
            font.pixelSize: header.ts - 1
        }
        // «Обновить»: one set of ACP reads, if the guard allows (CLAUDE.md, rules 3 and 4).
        Item {
            id: refresh
            width: 22
            height: 22
            anchors.verticalCenter: parent.verticalCenter
            opacity: header.sc3.busy ? 0.35 : 1
            Glyph {
                anchors.centerIn: parent
                size: 16
                stroke: 2.1
                color: refreshArea.containsMouse ? header.theme.headerText : header.theme.headerDim
                strokePath: Icons.refresh
            }
            MouseArea {
                id: refreshArea
                anchors.fill: parent
                anchors.margins: -5
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: header.refreshClicked()
            }
        }
    }

    // ---- middle: sound profile
    Row {
        id: profileRow
        x: Math.round(parent.width * 0.42)
        height: parent.height
        spacing: 10
        Ui {
            text: "Профиль"
            color: header.theme.headerDim
        }
        Rectangle {
            id: chip
            anchors.verticalCenter: parent.verticalCenter
            width: chipRow.implicitWidth + 26
            height: header.height - 16
            radius: header.theme.uiRadius
            color: header.profileOpen ? Qt.lighter(header.theme.headerChip, 1.25) : header.theme.headerChip
            border.width: 1
            border.color: header.profileOpen ? header.theme.accent : header.theme.headerChipBorder
            ProfileMenu {
                visible: header.profileOpen
                theme: header.theme
                sc3: header.sc3
                forcedHover: header.profileHover
                y: chip.height + 6
            }
            Row {
                id: chipRow
                anchors.centerIn: parent
                height: parent.height
                spacing: 7
                Ui {
                    text: header.sc3.profile !== "" ? header.sc3.profile : "нет"
                    color: header.sc3.profile !== "" ? header.theme.headerText : header.theme.headerDim
                    font.bold: header.sc3.profile !== ""
                }
                Glyph {
                    anchors.verticalCenter: parent.verticalCenter
                    size: 14
                    stroke: 2.4
                    color: header.theme.headerDim
                    strokePath: header.profileOpen ? Icons.chevronUp : Icons.chevronDown
                }
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: header.profileClicked()
            }
        }
    }

    // ---- right: microphone mute and on-air
    Row {
        anchors.right: parent.right
        anchors.rightMargin: 24
        height: parent.height
        spacing: 22

        Row {
            visible: (header.sc3.muteMic && header.sc3.connected) || (header.sc3.pipewireMute && header.sc3.audioPresent)
            height: parent.height
            spacing: 7
            Item {
                width: 18
                height: 18
                anchors.verticalCenter: parent.verticalCenter
                Glyph { size: 18; stroke: 1.9; color: header.theme.headerText; strokePath: Icons.micStroke }
                Glyph { size: 18; stroke: 2.2; color: header.theme.warn; strokePath: Icons.slash }
            }
            Ui { text: header.sc3.pipewireMute ? "Микрофон заглушён (PipeWire)" : "Микрофон заглушён" }
        }

        // Off air: a quiet hollow dot. On air: a red pill with the running time.
        // Unknown (OBS runs but does not answer): a neutral pill - treated like on air.
        Row {
            visible: header.sc3.live === "off"
            height: parent.height
            spacing: 8
            Dot {
                color: "transparent"
                border.width: 1.5
                border.color: header.theme.headerDim
            }
            Ui { text: "Не в эфире"; color: header.theme.headerDim }
        }
        Rectangle {
            visible: header.sc3.live === "on"
            anchors.verticalCenter: parent.verticalCenter
            width: live.implicitWidth + 24
            height: header.height - 18
            radius: height / 2
            color: Qt.alpha(header.theme.onAir, 0.16)
            border.width: 1
            border.color: Qt.alpha(header.theme.onAir, 0.7)
            Row {
                id: live
                anchors.centerIn: parent
                height: parent.height
                spacing: 8
                Dot { color: header.theme.onAir }
                Ui { text: "В ЭФИРЕ"; font.bold: true; font.letterSpacing: 0.8 }
                Ui {
                    visible: header.sc3.onAirTime !== ""
                    text: header.sc3.onAirTime
                    color: header.theme.headerDim
                    font.features: { "tnum": 1 }
                }
            }
        }
        Rectangle {
            visible: header.sc3.live === "unknown"
            anchors.verticalCenter: parent.verticalCenter
            width: unknownLive.implicitWidth + 24
            height: header.height - 18
            radius: height / 2
            color: header.theme.headerChip
            border.width: 1
            border.color: header.theme.headerChipBorder
            Row {
                id: unknownLive
                anchors.centerIn: parent
                height: parent.height
                spacing: 8
                Dot {
                    color: "transparent"
                    border.width: 1.5
                    border.color: header.theme.onAir
                }
                Ui { text: "Эфир не определён" }
            }
        }
    }
}
