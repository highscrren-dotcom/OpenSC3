#!/usr/bin/env python3
"""Render the SC3 window mock-ups (design/panel) to PNG without any window on the desktop.

One command, from anywhere:

    python3 design/panel/render.py

renders every frame in JOBS into design/renders/v2/, the GPU-less fallback check into
design/renders/v2/software/, exports the tray icons (design/panel/icons/export.py) and
builds the comparison sheets (ImageMagick montage). `render.py drawer-voice tray-menu`
renders only the named jobs; --list shows them.

The pipeline is the one proven in design/spike/render.py: QQuickRenderControl drives a
QQuickWindow that is never shown and renders into our own OpenGL FBO; the "software"
backend grabs a hidden QQuickView instead (QPainter only: no MultiEffect, no
RectangularShadow - the scenes switch to their flat look there). Every job runs in its
own child process: QT_SCALE_FACTOR and the backend must be fixed before QGuiApplication
exists, and creating this scene a third time in one QQmlEngine makes creation ~1000x
slower (perf: the V4 garbage collector, IdentifierTable::sweep / MarkStack::drain).
Pitfalls from the spike still apply: QT_QUICK_BACKEND=rhi on the offscreen platform,
gray text antialiasing, explicit font families (bundled in design/panel/fonts).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENES = HERE / "scenes"
FONTS = HERE.parents[1] / "sc3linux" / "app" / "fonts"  # shipped with the app
DEFAULT_OUT = HERE.parent / "renders" / "v2"

# name -> scene stem, initial properties, scale factors, backend ("gpu" | "software").
# Output: <out>/<name>@<scale>x.png
JOBS: dict[str, tuple[str, dict, tuple[float, ...], str]] = {
    "panel": ("Window", {"frame": "panel"}, (1.0, 2.0), "gpu"),
    "tip-custom": ("Window", {"frame": "tip-custom"}, (1.0,), "gpu"),
    "drawer-mic": ("Window", {"frame": "drawer-mic"}, (1.0,), "gpu"),
    "drawer-voice": ("Window", {"frame": "drawer-voice"}, (1.0,), "gpu"),
    "drawer-electric": ("Window", {"frame": "drawer-electric"}, (1.0,), "gpu"),
    "state-disconnected": ("Window", {"frame": "disconnected"}, (1.0,), "gpu"),
    "state-onair": ("Window", {"frame": "onair"}, (1.0,), "gpu"),
    "state-onair-muted": ("Window", {"frame": "onair-muted"}, (1.0,), "gpu"),
    "state-muted": ("Window", {"frame": "muted"}, (1.0,), "gpu"),
    "profiles": ("Window", {"frame": "profiles"}, (1.0,), "gpu"),
    "tray-menu": ("TrayMenu", {}, (1.0, 2.0), "gpu"),
    "tray-icons": ("TrayIcons", {}, (1.0,), "gpu"),
    "software/panel": ("Window", {"frame": "panel", "software": True}, (1.0,), "software"),
}
# sheet file -> (job names at 1x, tile, captions)
SHEETS: dict[str, tuple[list[str], str, list[str]]] = {
    "compare-states.png": (["panel", "state-muted", "state-disconnected",
                            "state-onair", "state-onair-muted", "profiles"], "3x2",
                           ["Обычный вид", "MIC заглушён (SC3)", "SC3 отключён",
                            "Идёт эфир", "Эфир, MIC заглушён (PipeWire)", "Профили"]),
    "compare-drawers.png": (["drawer-mic", "drawer-voice", "drawer-electric"], "3x1",
                            ["Ящик MIC", "Ящик CHANGE VOICE", "Ящик ELECTRIC"]),
}

BACKENDS: dict[str, dict[str, str]] = {
    "offscreen-gl": {"QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "rhi", "QSG_RHI_BACKEND": "opengl"},
    "wayland-gl": {"QT_QPA_PLATFORM": "wayland", "QT_QUICK_BACKEND": "rhi", "QSG_RHI_BACKEND": "opengl"},
    "software": {"QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
}
COMMON_ENV = {"QT_FORCE_STDERR_LOGGING": "1", "QSG_DISTANCEFIELD_ANTIALIASING": "gray"}
SCRUB_ENV = ("QT_QUICK_BACKEND", "QSG_RHI_BACKEND", "QT_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS",
             "QT_QPA_PLATFORM", "QMLSCENE_DEVICE")
FRAME_PASSES = 3  # Canvas paints during polish and uploads on sync: give it a couple of frames


def pick_gpu_backend(name: str) -> str:
    if name != "auto":
        return name
    if os.environ.get("DISPLAY"):
        return "offscreen-gl"
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland-gl"
    sys.exit("render: neither DISPLAY nor WAYLAND_DISPLAY is set; no GPU path for Qt Quick.")


def montage(out: Path, sheet: str, names: list[str], tile: str, captions: list[str]) -> None:
    magick = shutil.which("magick")
    if not magick:
        print("render: ImageMagick not found, skipping the sheets. Install with:\n"
              "  sudo pacman -S imagemagick", file=sys.stderr)
        return
    cmd = [magick, "montage", "-font", str(FONTS / "Arimo-Bold.ttf"), "-pointsize", "26",
           "-fill", "#e8e8e8", "-background", "#0a0a0a", "-depth", "8", "-geometry", "+28+20", "-tile", tile]
    for name, caption in zip(names, captions, strict=True):
        cmd += ["-label", caption, str(out / f"{name}@1x.png")]
    cmd.append(str(out / sheet))
    subprocess.run(cmd, check=True)
    print(f"ok   {out / sheet}")


def parent_main(args: argparse.Namespace) -> int:
    names = args.jobs or list(JOBS)
    unknown = [n for n in names if n not in JOBS]
    if unknown:
        sys.exit(f"render: unknown job(s) {unknown}; have {list(JOBS)}")
    forced_software = args.backend == "software"
    gpu = "software" if forced_software else pick_gpu_backend(args.backend)

    status = 0
    # Tray icon PNGs first: the tray-icons sheet shows them.
    exporter = HERE / "icons" / "export.py"
    wants_icons = not forced_software and any(n.startswith("tray") for n in names) and exporter.exists()
    if wants_icons and subprocess.run([sys.executable, "-B", str(exporter)], check=False).returncode:
        status = 1
    for name in names:
        scene, props, scales, kind = JOBS[name]
        backend = "software" if kind == "software" else gpu
        stem = name
        if backend == "software":
            props = {**props, "software": True}
            if not name.startswith("software/"):
                stem = f"software/{name}"
        for scale in scales:
            out = args.out / f"{stem}@{scale:g}x.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            env = {k: v for k, v in os.environ.items() if k not in SCRUB_ENV}
            env.update(COMMON_ENV)
            env.update(BACKENDS[backend])
            env["QT_SCALE_FACTOR"] = f"{scale:g}"
            job = {"scene": str(SCENES / f"{scene}.qml"), "props": props, "out": str(out)}
            cmd = [sys.executable, "-B", str(Path(__file__).resolve()), "--child", "--backend", backend,
                   "--scale", f"{scale:g}", "--job", json.dumps(job)]
            if subprocess.run(cmd, env=env, check=False).returncode != 0:
                print(f"render: {name} {backend} @{scale:g}x failed", file=sys.stderr)
                status = 1

    if not args.jobs and not forced_software and status == 0 and not args.no_sheet:
        for sheet, (sheet_jobs, tile, captions) in SHEETS.items():
            montage(args.out, sheet, sheet_jobs, tile, captions)
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

    job = json.loads(args.job)
    software = args.backend == "software"
    qml_problems: list[str] = []

    def on_message(mode, ctx, msg):
        level = {QtMsgType.QtDebugMsg: "debug", QtMsgType.QtInfoMsg: "info", QtMsgType.QtWarningMsg: "warning",
                 QtMsgType.QtCriticalMsg: "critical", QtMsgType.QtFatalMsg: "fatal"}.get(mode, "?")
        if mode != QtMsgType.QtDebugMsg:
            print(f"  qt {level}: {msg}", file=sys.stderr)
        from_qml = (ctx.file or "").endswith(".qml") or ".qml:" in msg or (ctx.category or "") in ("qml", "js")
        if from_qml and mode not in (QtMsgType.QtDebugMsg, QtMsgType.QtInfoMsg):
            qml_problems.append(msg)

    qInstallMessageHandler(on_message)
    if not software:
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    app = QGuiApplication([sys.argv[0]])
    url = QUrl.fromLocalFile(job["scene"])

    def render_software():
        view = QQuickView()
        view.setResizeMode(QQuickView.ResizeMode.SizeViewToRootObject)
        view.setInitialProperties(job["props"])
        view.setSource(url)
        if view.status() != QQuickView.Status.Ready:
            for err in view.errors():
                print(f"  {err.toString()}", file=sys.stderr)
            return None, "none", 0.0, "scene did not load"
        view.resize(int(view.rootObject().width()), int(view.rootObject().height()))
        view.create()
        for _ in range(FRAME_PASSES):
            app.processEvents()
        img = view.grabWindow()
        return img, view.rendererInterface().graphicsApi().name, view.devicePixelRatio(), None

    def render_gl():
        fmt = QSurfaceFormat()
        fmt.setDepthBufferSize(24)
        fmt.setStencilBufferSize(8)
        fmt.setAlphaBufferSize(8)
        gl = QOpenGLContext()
        gl.setFormat(fmt)
        if not gl.create():
            return None, "none", 0.0, f"no OpenGL context on platform '{app.platformName()}'"
        surface = QOffscreenSurface()
        surface.setFormat(gl.format())
        surface.create()
        if not gl.makeCurrent(surface):
            return None, "none", 0.0, "cannot make the OpenGL context current"
        engine = QQmlEngine()
        component = QQmlComponent(engine, url)
        root = component.createWithInitialProperties(job["props"])
        if root is None or not isinstance(root, QQuickItem):
            for err in component.errors():
                print(f"  {err.toString()}", file=sys.stderr)
            return None, "none", 0.0, "scene did not load (root must be an Item)"
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
        fbo_format = QOpenGLFramebufferObjectFormat()
        fbo_format.setAttachment(QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
        fbo = QOpenGLFramebufferObject(size, fbo_format)
        target = QQuickRenderTarget.fromOpenGLTexture(fbo.texture(), size)
        target.setDevicePixelRatio(args.scale)
        window.setRenderTarget(target)
        for _ in range(FRAME_PASSES):
            control.polishItems()
            control.beginFrame()
            control.sync()
            control.render()
            control.endFrame()
            app.processEvents()
        gl.makeCurrent(surface)
        return fbo.toImage(), window.rendererInterface().graphicsApi().name, window.effectiveDevicePixelRatio(), None

    timer = QElapsedTimer()
    timer.start()
    img, api, dpr, error = render_software() if software else render_gl()
    problems = [error] if error else []
    if not error:
        expected = "Software" if software else "OpenGL"
        if api != expected:
            problems.append(f"scene graph used {api}, expected {expected}")
        if abs(dpr - args.scale) > 1e-3:
            problems.append(f"device pixel ratio {dpr:g} != {args.scale:g}")
        if img.isNull():
            problems.append("empty image")
        problems += [f"QML: {m}" for m in qml_problems]
    out = Path(job["out"])
    if img is not None and not img.isNull():
        dots_per_meter = round(96 * args.scale / 0.0254)
        img.setDotsPerMeterX(dots_per_meter)
        img.setDotsPerMeterY(dots_per_meter)
        img.save(str(out))
        print(f"{'FAIL' if problems else 'ok':4} {out}  {img.width()}x{img.height()}  {timer.elapsed()} ms")
    for p in problems:
        print(f"FAIL {out.name}: {p}", file=sys.stderr)
    # Leave without tearing the scene graph down: the process ends right here anyway.
    sys.stdout.flush()
    os._exit(1 if problems else 0)


def main() -> int:
    ap = argparse.ArgumentParser(description="Render the SC3 window mock-ups to PNG off-screen.")
    ap.add_argument("jobs", nargs="*", help="job names (default: all; see --list)")
    ap.add_argument("--list", action="store_true", help="list the jobs and exit")
    ap.add_argument("-b", "--backend", default="auto", choices=["auto", *BACKENDS],
                    help="backend for the normal jobs; 'software' renders them all without GPU effects "
                         "into <out>/software/ (jobs named software/... always use it)")
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT, help=f"output dir (default {DEFAULT_OUT})")
    ap.add_argument("--no-sheet", action="store_true", help="skip the comparison sheets")
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--scale", type=float, default=1.0, help=argparse.SUPPRESS)
    ap.add_argument("--job", default="{}", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.list:
        for name, (scene, props, scales, kind) in JOBS.items():
            print(f"{name:20} {scene}.qml {props or ''} @{','.join(f'{s:g}x' for s in scales)} {kind}")
        return 0
    args.out = args.out.resolve()
    if args.child:
        return child_main(args)
    started = time.monotonic()
    rc = parent_main(args)
    print(f"render: done in {time.monotonic() - started:.1f} s", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
