#!/usr/bin/env python3
"""Снимки самого приложения (opensc3/app) на подделке ядра — без экрана, без SC3, OBS и PipeWire.

    python3 design/panel/render_app.py [имя ...]

Каждый кадр — отдельный процесс `python3 -m opensc3.app --fake <сценарий> --screenshot <png>`: платформа
offscreen, окна и значка трея нет, D-Bus не трогается. В отличие от render.py (макеты: те же QML-компоненты с
DemoState), здесь работает настоящий бэкенд: потоки, гвард, баллистика уровней — только ядро поддельное.
Результат — design/renders/app/<имя>.png и лист compare-app.png (ImageMagick montage).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE.parent / "renders" / "app"
FONT = ROOT / "opensc3" / "app" / "fonts" / "Arimo-Bold.ttf"

# имя → (сценарий подделки, ящик, без GPU, подпись на листе)
JOBS: dict[str, tuple[str, str | None, bool, str]] = {
    "panel": ("normal", None, False, "Обычный вид"),
    "onair": ("onair", None, False, "Идёт эфир: данные заморожены"),
    "onair-muted": ("onair-muted", None, False, "Эфир, MIC заглушён (PipeWire)"),
    "muted": ("muted", None, False, "MIC заглушён (PipeWire)"),
    "disconnected": ("disconnected", None, False, "SC3 отключён"),
    "no-access": ("no-access", None, False, "Нет прав на USB"),
    "foreign": ("foreign", None, False, "Чужая сборка"),
    "unknown-live": ("unknown-live", None, False, "Эфир не определён"),
    "drawer-mic": ("normal", "mic", False, "Ящик MIC"),
    "drawer-voice": ("normal", "voice", False, "Ящик CHANGE VOICE"),
    "drawer-electric": ("normal", "electric", False, "Ящик ELECTRIC"),
    "software-panel": ("normal", None, True, "Без GPU"),
    "trim": ("write", None, False, "Ручка MIC: запись разрешена"),
    "trim-onair": ("write-onair", None, False, "Ручка MIC в эфире — под замком"),
    "trim-off": ("normal", None, False, "Запись выключена: подсказка"),
    "settings": ("normal", None, False, "Меню-шестерёнка: предохранитель"),
}
TIPS = {"trim-off": "trim-off", "settings": "settings"}  # кадр → `--tip` (подсказка или меню без мыши)
SHEET = ["panel", "onair", "onair-muted", "disconnected", "no-access", "unknown-live"]


def shoot(name: str, out: Path) -> bool:
    scenario, section, software, _ = JOBS[name]
    cmd = [sys.executable, "-B", "-m", "opensc3.app", "--fake", scenario, "--screenshot", str(out / f"{name}.png")]
    if section:
        cmd += ["--section", section]
    if software:
        cmd.append("--software")
    if name in TIPS:
        cmd += ["--tip", TIPS[name]]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60, check=False)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(f"render_app: {name} не снялся\n{r.stderr}")
    return r.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Снимки приложения на подделке ядра, без экрана.")
    ap.add_argument("jobs", nargs="*", help=f"кадры (по умолчанию все): {', '.join(JOBS)}")
    ap.add_argument("-o", "--out", type=Path, default=OUT, help=f"папка (по умолчанию {OUT})")
    args = ap.parse_args()
    names = args.jobs or list(JOBS)
    unknown = [n for n in names if n not in JOBS]
    if unknown:
        sys.exit(f"render_app: нет кадров {unknown}")
    args.out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        ok = all(pool.map(lambda n: shoot(n, args.out), names))
    if ok and not args.jobs and shutil.which("magick"):
        cmd = ["magick", "montage", "-font", str(FONT), "-pointsize", "26", "-fill", "#e8e8e8",
               "-background", "#0a0a0a", "-depth", "8", "-geometry", "+28+20", "-tile", "3x2"]
        for n in SHEET:
            cmd += ["-label", JOBS[n][3], str(args.out / f"{n}.png")]
        subprocess.run([*cmd, str(args.out / "compare-app.png")], check=True)
        print(f"ok   {args.out / 'compare-app.png'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
