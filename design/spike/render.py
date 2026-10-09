#!/usr/bin/env python3
"""Render the spike's QML scenes to PNG without any window on the desktop.

One command, from anywhere:

    python3 design/spike/render.py

renders every scene in design/spike/scenes/ at 1x and 2x into
design/renders/spike/<Scene>@<N>x.png. See --help for scenes, scales, backend, output dir.

How: QQuickRenderControl drives a QQuickWindow that is never shown (no platform
window is created at all) and renders into our own OpenGL framebuffer object,
whose size and device pixel ratio we set explicitly. Each scale runs in its own
child process because the backend and QT_SCALE_FACTOR must be fixed before
QGuiApplication exists.

Backends ("auto" = offscreen-gl if DISPLAY is set, else wayland-gl):
  offscreen-gl  QT_QPA_PLATFORM=offscreen. The GL context comes from GLX, so an X server
                is required (XWayland on Plasma). Nothing ever touches the compositor.
  wayland-gl    QT_QPA_PLATFORM=wayland, GL over EGL; only needs WAYLAND_DISPLAY.
                Still no window: the render control never creates one.
  software      QPainter only, via a hidden QQuickView. An item with layer.effect: MultiEffect
                vanishes completely (source included), RectangularShadow draws nothing;
                Shapes gradients, Canvas and text survive. Kept to demonstrate exactly that.

Pitfalls found while building this (Qt 6.11.2 / PySide6 6.11.2, Mesa radeonsi):
  * On the offscreen platform Qt Quick silently picks the software scene graph unless
    QT_QUICK_BACKEND=rhi is set (QQuickWindow.setGraphicsApi alone is not enough).
  * offscreen + show() + QT_SCALE_FACTOR=2: the GLX surface keeps the logical size,
    only a quarter of the frame is drawn, the rest is transparent. Hence render control.
  * QQuickWindow.grabWindow() on a hidden (create()d, never shown) window works on the
    wayland platform with GL and Vulkan, but Canvas never paints there and QtQuick.Shapes
    vanish on a second grab of the same window.
  * Vulkan is impossible on the offscreen platform (no platform Vulkan instance);
    PySide6 does not wrap QVulkanInstance either. The GL path crashes without DISPLAY;
    minimalegl cannot do surfaceless EGL.
  * Qt sends its log to journald when stderr is not a TTY -> QT_FORCE_STDERR_LOGGING=1.
  * LCD subpixel text antialiasing bakes colour fringes into PNGs ->
    QSG_DISTANCEFIELD_ANTIALIASING=gray.
  * Default font differs per platform (offscreen: fontconfig sans-serif, here "PT Sans
    Expert"; wayland: Plasma's Noto Sans), so scenes must set font.family explicitly.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENES = HERE / "scenes"
DEFAULT_OUT = HERE.parent / "renders" / "spike"

BACKENDS: dict[str, dict[str, str]] = {
    "offscreen-gl": {"QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "rhi", "QSG_RHI_BACKEND": "opengl"},
    "wayland-gl": {"QT_QPA_PLATFORM": "wayland", "QT_QUICK_BACKEND": "rhi", "QSG_RHI_BACKEND": "opengl"},
    "software": {"QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
}
COMMON_ENV = {
    "QT_FORCE_STDERR_LOGGING": "1",
    "QSG_DISTANCEFIELD_ANTIALIASING": "gray",
}
# Env vars that would silently override our choice of backend or scale.
SCRUB_ENV = ("QT_QUICK_BACKEND", "QSG_RHI_BACKEND", "QT_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS",
             "QT_QPA_PLATFORM", "QMLSCENE_DEVICE")
FRAMES = 3  # Canvas paints during polish and uploads on sync: give it a couple of frames


def pick_backend(name: str) -> str:
    if name != "auto":
        return name
    if os.environ.get("DISPLAY"):
        return "offscreen-gl"
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland-gl"
    sys.exit("render: neither DISPLAY nor WAYLAND_DISPLAY is set; no GPU path for Qt Quick. "
             "Use --backend software (effects will be missing) or run inside a desktop session.")


def scale_tag(scale: float) -> str:
    return f"{scale:g}x"


def parent_main(args: argparse.Namespace) -> int:
    known = sorted(p.stem for p in SCENES.glob("*.qml"))
    scenes = args.scenes or known
    missing = [s for s in scenes if s not in known]
    if missing:
        sys.exit(f"render: unknown scene(s): {', '.join(missing)}; have: {', '.join(known)}")
    backend = pick_backend(args.backend)
    scales = [float(s) for s in args.scales.split(",") if s.strip()]
    args.out.mkdir(parents=True, exist_ok=True)

    status = 0
    for scale in scales:
        env = {k: v for k, v in os.environ.items() if k not in SCRUB_ENV}
        env.update(COMMON_ENV)
        env.update(BACKENDS[backend])
        env["QT_SCALE_FACTOR"] = f"{scale:g}"
        cmd = [sys.executable, "-B", str(Path(__file__).resolve()), "--child", "--backend", backend,
               "--scale", f"{scale:g}", "--out", str(args.out), *scenes]
        rc = subprocess.run(cmd, env=env, check=False).returncode
        if rc != 0:
            print(f"render: {backend} @{scale_tag(scale)} failed (exit {rc})", file=sys.stderr)
            status = 1
    return status


def child_main(args: argparse.Namespace) -> int:
    from PySide6.QtCore import QElapsedTimer, QSize, QSizeF, QtMsgType, QUrl, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat
    from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import (
        QQuickGraphicsDevice,
        QQuickItem,
        QQuickRenderControl,
        QQuickRenderTarget,
        QQuickView,
        QQuickWindow,
        QSGRendererInterface,
    )

    qml_problems: list[str] = []

    def on_message(mode, ctx, msg):  # Qt message handler
        level = {QtMsgType.QtDebugMsg: "debug", QtMsgType.QtInfoMsg: "info", QtMsgType.QtWarningMsg: "warning",
                 QtMsgType.QtCriticalMsg: "critical", QtMsgType.QtFatalMsg: "fatal"}.get(mode, "?")
        print(f"  qt {level}: {msg}", file=sys.stderr)
        from_qml = (ctx.file or "").endswith(".qml") or ".qml:" in msg or (ctx.category or "") in ("qml", "js")
        if from_qml and mode not in (QtMsgType.QtDebugMsg, QtMsgType.QtInfoMsg):
            qml_problems.append(msg)

    def render_software(url: QUrl) -> tuple:
        """Hidden QQuickView grabbed once; the software renderer needs no GPU objects."""
        view = QQuickView()
        view.setResizeMode(QQuickView.ResizeMode.SizeViewToRootObject)
        view.setSource(url)
        if view.status() != QQuickView.Status.Ready:
            return None, "none", 0.0, "QML did not load"
        view.resize(int(view.rootObject().width()), int(view.rootObject().height()))
        view.create()
        img = view.grabWindow()
        result = img, view.rendererInterface().graphicsApi().name, view.devicePixelRatio(), None
        view.destroy()
        view.deleteLater()
        return result

    def render_gl(url: QUrl) -> tuple:
        """QQuickRenderControl into our own FBO: no window, explicit size and DPR."""
        component = QQmlComponent(engine, url)
        root = component.create()
        if root is None or not isinstance(root, QQuickItem):
            for err in component.errors():
                print(f"  {err.toString()}", file=sys.stderr)
            return None, "none", 0.0, "root must be an Item (not a Window) and must load"
        w, h = int(root.width()), int(root.height())
        control = QQuickRenderControl()
        window = QQuickWindow(control)  # never shown; no platform window is created
        window.setGraphicsDevice(QQuickGraphicsDevice.fromOpenGLContext(gl))
        root.setParentItem(window.contentItem())
        window.contentItem().setSize(QSizeF(w, h))
        window.setGeometry(0, 0, w, h)
        if not control.initialize():
            return None, "none", 0.0, "QQuickRenderControl.initialize() failed"
        size = QSize(round(w * args.scale), round(h * args.scale))
        fbo = QOpenGLFramebufferObject(size, fbo_format)
        target = QQuickRenderTarget.fromOpenGLTexture(fbo.texture(), size)
        target.setDevicePixelRatio(args.scale)
        window.setRenderTarget(target)
        for _ in range(FRAMES):
            control.polishItems()
            control.beginFrame()
            control.sync()
            control.render()
            control.endFrame()
            app.processEvents()
        gl.makeCurrent(surface)
        img = fbo.toImage()
        result = img, window.rendererInterface().graphicsApi().name, window.effectiveDevicePixelRatio(), None
        # Tear down in dependency order while the context is current.
        root.setParentItem(None)
        root.deleteLater()
        control.invalidate()
        window.deleteLater()
        control.deleteLater()
        app.processEvents()
        gl.makeCurrent(surface)
        del fbo
        return result

    qInstallMessageHandler(on_message)
    software = args.backend == "software"
    if not software:
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    app = QGuiApplication([sys.argv[0]])
    expected_api = "Software" if software else "OpenGL"
    tag = scale_tag(args.scale)

    if not software:
        fmt = QSurfaceFormat()
        fmt.setDepthBufferSize(24)
        fmt.setStencilBufferSize(8)
        fmt.setAlphaBufferSize(8)
        gl = QOpenGLContext()
        gl.setFormat(fmt)
        if not gl.create():
            print(f"FAIL no OpenGL context on platform '{app.platformName()}'", file=sys.stderr)
            return 1
        surface = QOffscreenSurface()
        surface.setFormat(gl.format())
        surface.create()
        if not gl.makeCurrent(surface):
            print("FAIL cannot make the OpenGL context current", file=sys.stderr)
            return 1
        engine = QQmlEngine()
        fbo_format = QOpenGLFramebufferObjectFormat()
        fbo_format.setAttachment(QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)

    failed = False
    for name in args.scenes:
        qml_problems.clear()
        timer = QElapsedTimer()
        timer.start()
        url = QUrl.fromLocalFile(str(SCENES / f"{name}.qml"))
        img, api, dpr, error = render_software(url) if software else render_gl(url)

        problems = [error] if error else []
        if not error:
            if api != expected_api:
                problems.append(f"scene graph used {api}, expected {expected_api} (effects would be missing)")
            if abs(dpr - args.scale) > 1e-3:
                problems.append(f"device pixel ratio {dpr:g} != {args.scale:g} (desktop scaling leaked in; "
                                "try --backend offscreen-gl)")
            if img.isNull():
                problems.append("empty image")
            if not software:  # under software, effect warnings are the expected outcome
                problems += [f"QML: {m}" for m in qml_problems]

        out = args.out / f"{name}@{tag}.png"
        if img is not None and not img.isNull():
            dots_per_meter = round(96 * args.scale / 0.0254)
            img.setDotsPerMeterX(dots_per_meter)
            img.setDotsPerMeterY(dots_per_meter)
            img.save(str(out))
            print(f"{'FAIL' if problems else 'ok':4} {out}  {img.width()}x{img.height()}  "
                  f"{args.backend}/{api}  {timer.elapsed()} ms")
        for p in problems:
            print(f"FAIL {name}@{tag}: {p}", file=sys.stderr)
        failed |= bool(problems)

    if not software:
        gl.doneCurrent()
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Render spike QML scenes to PNG off-screen.")
    ap.add_argument("scenes", nargs="*", help="scene names (file stems in design/spike/scenes); default: all")
    ap.add_argument("-s", "--scales", default="1,2", help="comma-separated scale factors (default 1,2)")
    ap.add_argument("-b", "--backend", default="auto", choices=["auto", *BACKENDS])
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT, help=f"output dir (default {DEFAULT_OUT})")
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--scale", type=float, default=1.0, help=argparse.SUPPRESS)
    args = ap.parse_args()
    args.out = args.out.resolve()
    if args.child:
        return child_main(args)
    started = time.monotonic()
    rc = parent_main(args)
    print(f"render: done in {time.monotonic() - started:.1f} s", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
