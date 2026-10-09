import QtQuick

// SC3 body seen strictly from above: matte "sand" plastic, a shadow onto the desk,
// a faint rim where the edge rounds over.
Item {
    id: chassis
    required property Tokens theme
    property real radius: 42

    Shadow {
        anchors.fill: body
        theme: chassis.theme
        radius: chassis.radius
        offsetY: chassis.theme.bodyShadowOffset
        blur: chassis.theme.bodyShadowBlur
        color: Qt.rgba(0, 0, 0, chassis.theme.bodyShadowOpacity)
    }

    Rectangle {
        id: body
        anchors.fill: parent
        radius: chassis.radius
        gradient: Gradient {
            GradientStop { position: 0.0; color: chassis.theme.bodyTop }
            GradientStop { position: 1.0; color: chassis.theme.bodyBottom }
        }
        border.color: "#000000"
        border.width: 1
    }

    // Grain: seeded LCG, so renders are reproducible; repeated as a pattern so the
    // canvas' HiDPI transform is respected.
    Canvas {
        anchors.fill: parent
        anchors.margins: 1
        visible: chassis.theme.grain > 0
        onPaint: {
            const ctx = getContext("2d");
            const n = 128;
            const tile = ctx.createImageData(n, n);
            const d = tile.data;
            const k = chassis.theme.grain;
            let s = 20261007;
            for (let i = 0; i < d.length; i += 4) {
                s = (s * 1103515245 + 12345) & 0x7fffffff;
                const v = (s >> 15) & 0xff;
                const light = v > 127;
                d[i] = d[i + 1] = d[i + 2] = light ? 255 : 0;
                d[i + 3] = Math.round(Math.abs(v - 127.5) / 127.5 * (light ? 9 : 20) * k);
            }
            ctx.reset();
            ctx.fillStyle = ctx.createPattern(tile, "repeat");
            ctx.beginPath();
            ctx.roundedRect(0, 0, width, height, chassis.radius - 1, chassis.radius - 1);
            ctx.fill();
        }
    }

    // Rim: the rounded-over edge catches light, brightest along the back edge.
    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: chassis.radius - 1
        color: "transparent"
        border.color: chassis.theme.bodyRim
        border.width: 1.5
    }
    Rectangle {
        x: chassis.radius
        y: 1.5
        width: chassis.width - 2 * chassis.radius
        height: 1
        color: chassis.theme.bodyRimTop
    }
    // Front edge falls away from the light.
    Rectangle {
        x: chassis.radius
        y: chassis.height - 3
        width: chassis.width - 2 * chassis.radius
        height: 2
        color: "#40000000"
    }
}
