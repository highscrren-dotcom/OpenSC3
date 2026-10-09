"""`sc3 install` / `sc3 uninstall`: ярлык, значки и автозапуск OpenSC3 для одного пользователя — без sudo.

Куда (XDG; $XDG_DATA_HOME — по умолчанию ~/.local/share, $XDG_CONFIG_HOME — ~/.config):

  applications/opensc3.desktop                            ярлык окна: data/opensc3.desktop, Exec — рабочий запуск
  icons/hicolor/scalable/apps/opensc3.svg                 значок приложения (data/opensc3.svg)
  icons/hicolor/{22x22,32x32}/status/opensc3-<сост.>.svg  значки трея (opensc3/app/icons/sc3-<сост.>-<px>.svg)
  $XDG_CONFIG_HOME/autostart/opensc3.desktop              только с --autostart: окно сразу в трей (--tray)

Значки трея — по соглашению Breeze: стиль current-color-scheme, классы ColorScheme-Text/NegativeText, без суффикса
-symbolic. Тема с FollowsColorScheme (Breeze) перекрашивает такие SVG под цвета панели, красное остаётся красным. Каждый
размер нарисован по своей пиксельной сетке (design/panel/icons/draw.py), поэтому — каталоги 22x22 и 32x32, а не
scalable: для других размеров тема берёт ближайший и рисует его вектором.

Что поставлено — манифест $XDG_DATA_HOME/opensc3/installed.json (путь → sha256 записанного). Чужое не трогаем: файл
с тем же именем, которого нет в манифесте или который изменён после установки, не перезаписывается и не удаляется.
Повторная установка приводит набор к нынешнему: своё неизменённое обновляет, лишнее из прошлого манифеста (например,
автозапуск, если теперь без --autostart) убирает. Кэши (mimeinfo.cache, icon-theme.cache) только обновляем, если они уже
есть: свой не заводим — устаревший кэш значков прячет от GTK чужие новые значки.

Правило udev сюда не входит (это /etc и sudo): `sc3 install` только проверяет его и печатает команды (cli.py).
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

APP_ID = "opensc3"
PKG = Path(__file__).resolve().parent
ROOT = PKG.parent                                  # каталог с исходниками (git): data/, udev/
DESKTOP = ROOT / "data" / f"{APP_ID}.desktop"
APP_ICON = ROOT / "data" / f"{APP_ID}.svg"
TRAY_ICONS = PKG / "app" / "icons"                 # sc3-<состояние>-<px>.svg
TRAY_SIZES = (22, 32)
HEADER = "# Поставил `sc3 install` (OpenSC3); убрать — `sc3 uninstall`. Изменённый здесь файл они не трогают."
# Desktop Entry Spec, «The Exec key»: аргумент с этими знаками — в двойных кавычках
EXEC_RESERVED = frozenset(" \t\"'\\><~|&;$*?#()`")
CACHES = (  # (подкаталог $XDG_DATA_HOME, файл кэша, программа, её ключи)
    ("applications", "mimeinfo.cache", "update-desktop-database", ("-q",)),
    ("icons/hicolor", "icon-theme.cache", "gtk-update-icon-cache", ("-q", "-f", "-t")),
)

Out = Callable[[str], None]


class InstallError(Exception):
    """Не из чего ставить, битый манифест, перевод строки в пути."""


@dataclass(frozen=True)
class Item:
    path: Path
    data: bytes
    what: str


@dataclass(frozen=True)
class Plan:
    items: tuple[Item, ...]
    manifest: Path
    roots: tuple[Path, ...]       # $XDG_DATA_HOME, $XDG_CONFIG_HOME: вне них ничего не пишем и не удаляем
    exec_line: str
    workdir: Path | None


def _xdg(env: Mapping[str, str], var: str, default: str) -> Path:
    value = env.get(var, "")
    if os.path.isabs(value):  # относительный путь спецификация велит не замечать
        return Path(value)
    return Path(env.get("HOME") or Path.home()) / default


def data_home(env: Mapping[str, str] = os.environ) -> Path:
    return _xdg(env, "XDG_DATA_HOME", ".local/share")


def config_home(env: Mapping[str, str] = os.environ) -> Path:
    return _xdg(env, "XDG_CONFIG_HOME", ".config")


def manifest_path(env: Mapping[str, str] = os.environ) -> Path:
    return data_home(env) / APP_ID / "installed.json"


def launcher(which: Callable[[str], str | None] = shutil.which,
             python: str = sys.executable) -> tuple[list[str], Path | None]:
    """Рабочий запуск окна и каталог для него: `opensc3` из PATH (пакет поставлен) — полным путём, чтобы не
    зависеть от PATH графического сеанса; иначе `python3 -m opensc3.app` из каталога с исходниками."""
    exe = which(APP_ID)
    if exe:
        return [os.path.abspath(exe)], None
    return [python or "python3", "-m", f"{APP_ID}.app"], ROOT


def _no_newline(s: str) -> str:
    if "\n" in s or "\r" in s:
        raise InstallError(f"перевод строки в пути — в .desktop его не записать: {s!r}")
    return s


def exec_line(argv: list[str]) -> str:
    """Значение Exec=: `%` удваивается, аргумент с пробелом или особым знаком — в "…" с `\\` перед " ` $ \\, затем
    экранирование строки .desktop (`\\` → `\\\\`)."""
    out = []
    for arg in argv:
        arg = _no_newline(arg).replace("%", "%%")
        if any(c in EXEC_RESERVED for c in arg):
            arg = '"' + "".join("\\" + c if c in '"`$\\' else c for c in arg) + '"'
        out.append(arg)
    return " ".join(out).replace("\\", "\\\\")


def desktop_entry(template: str, exec_value: str, workdir: Path | None, *, autostart: bool = False) -> str:
    """data/opensc3.desktop с рабочим Exec= (и Path=, если запуск из исходников). Автозапуск — с --tray и без
    StartupNotify: окна нет, курсор «занят» ждал бы его до тайм-аута."""
    out, seen = [HEADER], False
    for line in template.splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key == "Exec":
            seen = True
            out.append("Exec=" + exec_value + (" --tray" if autostart else ""))
            if workdir is not None:
                out.append("Path=" + _no_newline(str(workdir)).replace("\\", "\\\\"))
        elif key in ("Path", "TryExec") or (autostart and key in ("StartupNotify", "X-KDE-StartupNotify")):
            continue
        else:
            out.append(line)
    if not seen:
        raise InstallError(f"в {DESKTOP} нет строки Exec=")
    return "\n".join(out) + "\n"


def plan(*, autostart: bool = False, env: Mapping[str, str] = os.environ,
         which: Callable[[str], str | None] = shutil.which, python: str = sys.executable) -> Plan:
    """Что и куда ставить. Ничего не пишет."""
    for src in (DESKTOP, APP_ICON):
        if not src.is_file():
            raise InstallError(f"нет {src}: sc3 install ставит из каталога с исходниками (git clone); "
                               "пакет (packaging/arch) ставит ярлык и значки сам")
    data, config = data_home(env), config_home(env)
    argv, workdir = launcher(which, python)
    ex = exec_line(argv)
    template = DESKTOP.read_text(encoding="utf-8")
    items = [Item(data / "applications" / f"{APP_ID}.desktop",
                  desktop_entry(template, ex, workdir).encode("utf-8"), "ярлык окна"),
             Item(data / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg",
                  APP_ICON.read_bytes(), "значок приложения")]
    for px in TRAY_SIZES:
        sources = sorted(TRAY_ICONS.glob(f"sc3-*-{px}.svg"))
        if not sources:
            raise InstallError(f"нет значков трея sc3-*-{px}.svg в {TRAY_ICONS}")
        for src in sources:
            state = src.name[len("sc3-"):-len(f"-{px}.svg")]
            items.append(Item(data / "icons" / "hicolor" / f"{px}x{px}" / "status" / f"{APP_ID}-{state}.svg",
                              src.read_bytes(), f"значок трея «{state}», {px} px"))
    if autostart:
        items.append(Item(config / "autostart" / f"{APP_ID}.desktop",
                          desktop_entry(template, ex, workdir, autostart=True).encode("utf-8"), "автозапуск в трей"))
    return Plan(tuple(items), manifest_path(env), (data, config), ex, workdir)


# --- файлы ------------------------------------------------------------------------------------------------------------

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _state(p: Path) -> str | None:
    """None — файла нет; sha256 — обычный файл; "!" — ссылка, каталог и прочее (не наше, с хешем не совпадёт)."""
    if not os.path.lexists(p):
        return None
    if p.is_symlink() or not p.is_file():
        return "!"
    return _sha(p.read_bytes())


def _inside(p: Path, roots: tuple[Path, ...]) -> bool:
    return any(p.is_relative_to(r) for r in roots)


def read_manifest(path: Path) -> dict:
    """{"files": {путь: sha256}, "dirs": [созданные нами каталоги]}; нет файла — пустой."""
    if not path.exists():
        return {"files": {}, "dirs": []}
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
        files, dirs = m["files"], m.get("dirs", [])
        if not isinstance(files, dict) or not isinstance(dirs, list):
            raise TypeError("files — не словарь или dirs — не список")
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise InstallError(f"манифест {path} не читается ({e}) — ничего не трогаю, разберись руками") from None
    return {"files": {str(k): str(v) for k, v in files.items()}, "dirs": [str(d) for d in dirs]}


def _mkdirs(d: Path) -> set[str]:
    """Создать каталог; вернуть те, которых не было (их потом можно убрать, если опустеют)."""
    made, p = [], d
    while not p.exists():
        made.append(str(p))
        p = p.parent
    d.mkdir(parents=True, exist_ok=True)
    return set(made)


def _put(path: Path, data: bytes) -> set[str]:
    made = _mkdirs(path.parent)
    tmp = path.with_name(f".{path.name}.{APP_ID}-tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)  # атомарно: на месте либо старый файл, либо новый
    return made


def refresh_caches(data: Path, *, which: Callable[[str], str | None] = shutil.which,
                   run=subprocess.run, out: Out = print) -> None:
    """update-desktop-database / gtk-update-icon-cache — только для каталогов пользователя и только если кэш там уже
    есть (и есть сама программа). Plasma видит новые файлы и без них."""
    for sub, cache, tool, flags in CACHES:
        d = data / sub
        exe = which(tool)
        if exe is None or not (d / cache).is_file():
            continue
        try:
            ok = run([exe, *flags, str(d)], capture_output=True, timeout=60, check=False).returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        out(f"  {'✓' if ok else '✗'} {tool} {d}")


def install(p: Plan, *, dry_run: bool = False, out: Out = print, which: Callable[[str], str | None] = shutil.which,
            run=subprocess.run) -> int:
    """Поставить по плану. Чужой файл на месте — отказ целиком, до первой записи (код 1)."""
    old = read_manifest(p.manifest)
    owned = old["files"]
    rows, foreign = [], []
    for it in p.items:
        if not _inside(it.path, p.roots):
            raise InstallError(f"{it.path} вне {', '.join(map(str, p.roots))}")
        cur = _state(it.path)
        if cur is None:
            rows.append(("+", it))
        elif cur == _sha(it.data):
            rows.append(("=", it))
        elif owned.get(str(it.path)) == cur:
            rows.append(("~", it))
        else:
            foreign.append(it)
    if foreign:
        for it in foreign:
            out(f"✗ {it.path} — чужой файл (нет в манифесте или изменён после установки): не трогаю")
        out("ничего не поставлено: убери или переименуй эти файлы и повтори sc3 install")
        return 1
    want = {str(it.path) for it in p.items}
    stale = [(Path(s), h) for s, h in owned.items() if s not in want]

    out(("сухой прогон — ничего не пишу. " if dry_run else "") + f"запуск окна: Exec={p.exec_line}"
        + (f"  (Path={p.workdir})" if p.workdir else ""))
    notes = {"+": "", "~": " (обновлён)", "=": " (без изменений)"}
    for mark, it in rows:
        out(f"  {mark} {it.path} — {it.what}{notes[mark]}")
    drop = []
    for path, h in stale:
        st = _state(path)
        if st is None:
            continue
        if not _inside(path, p.roots):
            out(f"  • {path} — из прошлой установки, вне {', '.join(map(str, p.roots))}: не трогаю (и забываю)")
        elif st == h:
            out(f"  - {path} — был в прошлой установке, теперь не ставится")
            drop.append(path)
        else:
            out(f"  • {path} — был в прошлой установке, изменён после неё: оставлен (и забыт)")
    out(f"  манифест: {p.manifest}")
    if dry_run:
        return 0

    made = set(old["dirs"]) | _mkdirs(p.manifest.parent)
    for mark, it in rows:
        if mark != "=":
            made |= _put(it.path, it.data)
    for path in drop:
        path.unlink()
    manifest = {"app": APP_ID, "version": 1, "exec": p.exec_line,
                "files": {str(it.path): _sha(it.data) for it in p.items},
                "dirs": sorted(d for d in made if Path(d).is_dir())}
    _put(p.manifest, (json.dumps(manifest, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    if any(mark != "=" for mark, _ in rows) or drop:
        refresh_caches(p.roots[0], which=which, run=run, out=out)
    return 0


def uninstall(manifest: Path, *, env: Mapping[str, str] = os.environ, dry_run: bool = False, out: Out = print,
              which: Callable[[str], str | None] = shutil.which, run=subprocess.run) -> int:
    """Убрать ровно поставленное по манифесту и только неизменённое; созданные нами каталоги — если опустели."""
    if not manifest.exists():
        out(f"убирать нечего: нет манифеста {manifest} (sc3 install не запускался или всё уже убрано)")
        return 0
    m = read_manifest(manifest)
    roots = (data_home(env), config_home(env))
    out(("сухой прогон — ничего не удаляю. " if dry_run else "") + f"по манифесту {manifest}:")
    gone = []
    for s, h in m["files"].items():
        path, st = Path(s), _state(Path(s))
        if not _inside(path, roots):
            out(f"  • {path} — вне {', '.join(map(str, roots))}: не трогаю")
        elif st is None:
            out(f"  · {path} — уже нет")
        elif st == h:
            out(f"  - {path}")
            gone.append(path)
        else:
            out(f"  • {path} — изменён после установки: оставлен")
    if dry_run:
        return 0
    for path in gone:
        path.unlink()
    manifest.unlink()
    for d in sorted(m["dirs"], key=lambda x: len(Path(x).parts), reverse=True):
        if _inside(Path(d), roots):
            with contextlib.suppress(OSError):  # только пустой: rmdir не удаляет каталог с чужими файлами
                Path(d).rmdir()
    if gone:
        refresh_caches(roots[0], which=which, run=run, out=out)
    return 0
