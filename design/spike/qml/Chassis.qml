import QtQuick
import QtQuick.Effects

// Dark matte body: drop shadow onto the desk, vertical light falloff,
// faint rim light and a procedural grain (powder-coat texture).
Item {
    id: root
    default property alias content: inner.data
    property real radius: 18
    property bool grain: true

    Rectangle {
        id: body
        anchors.fill: parent
        radius: root.radius
        gradient: Gradient {
            GradientStop { position: 0.0; color: Theme.bodyTop }
            GradientStop { position: 1.0; color: Theme.bodyBottom }
        }
        border.color: "#000000"
        border.width: 1
        layer.enabled: true
        layer.effect: MultiEffect {
            shadowEnabled: true
            shadowColor: "#000000"
            shadowOpacity: 0.8
            shadowBlur: 1.0
            shadowVerticalOffset: 14
        }
    }

    // Grain. A seeded LCG keeps renders reproducible; the tile is repeated
    // through a pattern so it also respects the canvas' HiDPI transform.
    Canvas {
        id: grainCanvas
        visible: root.grain
        anchors.fill: parent
        anchors.margins: 1
        onPaint: {
            const ctx = getContext("2d");
            const n = 96;
            const tile = ctx.createImageData(n, n);
            const d = tile.data;
            let s = 20261007;
            for (let i = 0; i < d.length; i += 4) {
                s = (s * 1103515245 + 12345) & 0x7fffffff;
                const v = (s >> 15) & 0xff;
                const light = v > 127;
                d[i] = d[i + 1] = d[i + 2] = light ? 255 : 0;
                d[i + 3] = Math.round(Math.abs(v - 127.5) / 127.5 * (light ? 10 : 22));
            }
            ctx.reset();
            ctx.fillStyle = ctx.createPattern(tile, "repeat");
            ctx.beginPath();
            ctx.roundedRect(0, 0, width, height, root.radius - 1, root.radius - 1);
            ctx.fill();
        }
    }

    // Rim light: all-round hairline plus a brighter top edge.
    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: root.radius - 1
        color: "transparent"
        border.color: Theme.rim
    }
    Rectangle {
        x: root.radius
        y: 1
        width: parent.width - 2 * root.radius
        height: 1
        color: Theme.rimTop
    }

    Item {
        id: inner
        anchors.fill: parent
    }
}
