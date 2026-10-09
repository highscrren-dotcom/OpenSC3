"""`sc3 install` / `sc3 uninstall` на временных $HOME, $XDG_DATA_HOME, $XDG_CONFIG_HOME: в настоящий ~/.local и
~/.config ничего не пишется. Правило udev подменено путями во временном каталоге, кэши — подделкой run."""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from opensc3 import cli
from opensc3 import install as I

PY = "/usr/bin/python3"
LAUNCHER = I.launcher
STATES = ("connected", "disconnected", "muted", "onair", "onair-muted")


class Install(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data, self.config = self.root / "data", self.root / "config"
        env = {"HOME": str(self.root / "home"), "XDG_DATA_HOME": str(self.data), "XDG_CONFIG_HOME": str(self.config)}
        for p in (mock.patch.dict(os.environ, env),
                  mock.patch.object(cli, "RULE", self.root / "etc" / "70-fifine-sc3.rules"),
                  mock.patch.object(cli, "SYSTEM_RULE", self.root / "usr" / "70-fifine-sc3.rules"),
                  # PATH и интерпретатор — подставные: `opensc3` в PATH есть или нет — решает self.which
                  mock.patch.object(I, "launcher", lambda which, python: LAUNCHER(lambda n: self.which(n), PY))):
            p.start()
            self.addCleanup(p.stop)
        self.which = lambda name: None
        self.desktop = self.data / "applications" / "opensc3.desktop"
        self.autostart = self.config / "autostart" / "opensc3.desktop"
        self.manifest = self.data / "opensc3" / "installed.json"

    def sc3(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def tree(self) -> dict[str, bytes]:
        return {str(p.relative_to(self.root)): p.read_bytes() for p in sorted(self.root.rglob("*")) if p.is_file()}

    def ours(self) -> set[str]:
        files = {"data/applications/opensc3.desktop", "data/icons/hicolor/scalable/apps/opensc3.svg",
                 "data/opensc3/installed.json"}
        files |= {f"data/icons/hicolor/{px}x{px}/status/opensc3-{s}.svg" for px in (22, 32) for s in STATES}
        return files

    def test_installs_desktop_icons_manifest(self):
        code, out, err = self.sc3("install")
        self.assertEqual(code, 0, err)
        self.assertEqual(set(self.tree()), self.ours())          # автозапуск — только по флагу
        text = self.desktop.read_text()
        self.assertIn(f"\nExec={PY} -m opensc3.app\nPath={I.ROOT}\n", text)
        self.assertIn("\nIcon=opensc3\n", text)
        tray = self.data / "icons/hicolor/22x22/status/opensc3-muted.svg"
        self.assertEqual(tray.read_bytes(), (I.TRAY_ICONS / "sc3-muted-22.svg").read_bytes())
        self.assertIn("ColorScheme-Text", tray.read_text())       # Plasma перекрашивает по стилю current-color-scheme
        m = json.loads(self.manifest.read_text())
        self.assertEqual(set(m["files"]), {str(self.root / f) for f in self.ours()} - {str(self.manifest)})
        self.assertIn(f"+ {self.desktop}", out)
        self.assertNotIn(".opensc3-tmp", "".join(self.tree()))

    def test_exec_uses_opensc3_from_path(self):
        self.which = lambda name: "/usr/bin/opensc3" if name == "opensc3" else None
        self.assertEqual(self.sc3("install")[0], 0)
        text = self.desktop.read_text()
        self.assertIn("\nExec=/usr/bin/opensc3\n", text)
        self.assertNotIn("\nPath=", text)

    def test_exec_quoting(self):
        self.assertEqual(I.exec_line(["/opt/my apps/opensc3", "--x=100%"]), '"/opt/my apps/opensc3" --x=100%%')
        self.assertEqual(I.exec_line(["/a$b"]), '"/a\\\\$b"')   # "/a\$b" по Exec, затем \ → \\ строки .desktop
        with self.assertRaises(I.InstallError):
            I.exec_line(["/a\nb"])

    def test_second_install_is_idempotent(self):
        self.assertEqual(self.sc3("install")[0], 0)
        before = self.tree()
        mtimes = {p: p.stat().st_mtime_ns for p in self.root.rglob("*") if p.is_file() and p != self.manifest}
        code, out, _ = self.sc3("install")
        self.assertEqual(code, 0)
        self.assertEqual(self.tree(), before)
        self.assertEqual({p: p.stat().st_mtime_ns for p in mtimes}, mtimes)   # своё не переписано
        self.assertNotIn("  + ", out)
        self.assertIn("(без изменений)", out)

    def test_own_unmodified_file_is_updated(self):
        self.sc3("install")
        self.which = lambda name: "/usr/bin/opensc3" if name == "opensc3" else None
        code, out, _ = self.sc3("install")
        self.assertEqual(code, 0)
        self.assertIn(f"~ {self.desktop}", out)
        self.assertIn("Exec=/usr/bin/opensc3\n", self.desktop.read_text())

    def test_autostart_only_by_flag_and_dropped_without_it(self):
        self.assertEqual(self.sc3("install", "--autostart")[0], 0)
        text = self.autostart.read_text()
        self.assertIn(f"\nExec={PY} -m opensc3.app --tray\n", text)
        self.assertNotIn("StartupNotify", text)
        code, out, _ = self.sc3("install")                       # без флага — набор как сейчас: автозапуска нет
        self.assertEqual(code, 0)
        self.assertFalse(self.autostart.exists())
        self.assertIn(f"- {self.autostart}", out)
        self.assertEqual(set(self.tree()), self.ours())

    def test_uninstall_removes_only_own(self):
        self.sc3("install", "--autostart")
        foreign = self.data / "icons/hicolor/22x22/status/other-app.svg"
        foreign.write_text("<svg/>")
        neighbour = self.data / "applications" / "other.desktop"
        neighbour.write_text("[Desktop Entry]\n")
        code, out, _ = self.sc3("uninstall")
        self.assertEqual(code, 0)
        self.assertEqual(set(self.tree()), {"data/icons/hicolor/22x22/status/other-app.svg",
                                            "data/applications/other.desktop"})
        self.assertFalse((self.data / "icons/hicolor/32x32").exists())     # пустые каталоги, что создали мы, — убраны
        self.assertFalse((self.data / "opensc3").exists())
        self.assertTrue(foreign.parent.is_dir())
        code, out, _ = self.sc3("uninstall")
        self.assertEqual(code, 0)
        self.assertIn("убирать нечего", out)

    def test_modified_after_install_is_kept(self):
        self.sc3("install")
        self.desktop.write_text(self.desktop.read_text() + "NoDisplay=true\n")
        code, out, _ = self.sc3("install")                      # переписать правку — нельзя
        self.assertEqual(code, 1)
        self.assertIn(f"✗ {self.desktop}", out)
        code, out, _ = self.sc3("uninstall")
        self.assertEqual(code, 0)
        self.assertIn(f"• {self.desktop} — изменён после установки: оставлен", out)
        self.assertEqual(set(self.tree()), {"data/applications/opensc3.desktop"})

    def test_foreign_file_without_manifest_untouched(self):
        self.desktop.parent.mkdir(parents=True)
        self.desktop.write_text("[Desktop Entry]\nName=чужой\n")
        before = self.tree()
        code, out, _ = self.sc3("install")
        self.assertEqual(code, 1)
        self.assertIn("чужой файл", out)
        self.assertEqual(self.tree(), before)                    # отказ целиком: ни значков, ни манифеста
        self.assertEqual(self.sc3("uninstall")[0], 0)
        self.assertEqual(self.tree(), before)

    def test_symlink_in_place_is_foreign(self):
        self.desktop.parent.mkdir(parents=True)
        self.desktop.symlink_to(self.root / "elsewhere.desktop")
        self.assertEqual(self.sc3("install")[0], 1)
        self.assertTrue(self.desktop.is_symlink())

    def test_dry_run_writes_nothing(self):
        code, out, _ = self.sc3("install", "--autostart", "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(self.tree(), {})
        self.assertFalse(self.data.exists() or self.config.exists())
        self.assertIn("сухой прогон", out)
        for f in (self.desktop, self.autostart, self.data / "icons/hicolor/32x32/status/opensc3-onair.svg"):
            self.assertIn(str(f), out)
        self.sc3("install")
        before = self.tree()
        code, out, _ = self.sc3("uninstall", "--dry-run")
        self.assertEqual((code, self.tree()), (0, before))
        self.assertIn(f"- {self.desktop}", out)

    def test_broken_manifest_refuses(self):
        self.sc3("install")
        self.manifest.write_text("{")
        before = self.tree()
        for argv in (["install"], ["uninstall"]):
            code, _, err = self.sc3(*argv)
            self.assertEqual(code, 1, argv)
            self.assertIn("манифест", err)
        self.assertEqual(self.tree(), before)

    def test_not_under_sudo(self):
        with mock.patch("os.geteuid", return_value=0):
            code, _, err = self.sc3("install")
        self.assertEqual((code, self.tree()), (1, {}))
        self.assertIn("не под sudo", err)

    def test_udev_rule_only_checked(self):
        _, out, _ = self.sc3("install", "--dry-run")
        self.assertIn("✗ правило udev не стоит", out)
        self.assertIn(f"sudo install -m 644 {cli.REPO_RULE} /etc/udev/rules.d/", out)
        self.assertIn("sudo udevadm control --reload", out)
        self.assertNotIn("<<", out)                              # fish: без heredoc
        self.assertFalse(cli.RULE.exists())
        cli.SYSTEM_RULE.parent.mkdir(parents=True)
        cli.SYSTEM_RULE.write_text("# пакет\n" + cli.REPO_RULE.read_text())
        _, out, _ = self.sc3("install", "--dry-run")
        self.assertIn(f"✓ правило udev {cli.SYSTEM_RULE}", out)
        self.assertNotIn("sudo", out)


class Caches(unittest.TestCase):
    def test_only_existing_user_caches_are_refreshed(self):
        with tempfile.TemporaryDirectory() as d:
            data, runs = Path(d), []

            def run(argv, **_kw):
                runs.append(argv)
                return mock.Mock(returncode=0)

            which = {"update-desktop-database": "/usr/bin/update-desktop-database",
                     "gtk-update-icon-cache": "/usr/bin/gtk-update-icon-cache"}.get
            I.refresh_caches(data, which=which, run=run, out=lambda s: None)
            self.assertEqual(runs, [])                           # кэшей нет — свои не заводим
            (data / "icons/hicolor").mkdir(parents=True)
            (data / "icons/hicolor/icon-theme.cache").write_bytes(b"")
            I.refresh_caches(data, which=which, run=run, out=lambda s: None)
            self.assertEqual(runs, [["/usr/bin/gtk-update-icon-cache", "-q", "-f", "-t", str(data / "icons/hicolor")]])
            runs.clear()
            I.refresh_caches(data, which=lambda name: None, run=run, out=lambda s: None)
            self.assertEqual(runs, [])                           # нет программы — нет и вызова


class TrayTheme(unittest.TestCase):
    """Трей берёт значок из темы, если `sc3 install` его туда положил, иначе — PNG из пакета (как раньше)."""

    @classmethod
    def setUpClass(cls):
        if importlib.util.find_spec("PySide6") is None:
            raise unittest.SkipTest("нет PySide6")
        if not Path("/usr/share/icons/hicolor/index.theme").exists():
            raise unittest.SkipTest("нет /usr/share/icons/hicolor/index.theme")
        from PySide6.QtWidgets import QApplication

        from opensc3.app.headless import prepare
        if QApplication.instance() is None:
            prepare(gpu=False)
            cls.app = QApplication([])

    def test_theme_icon_or_none(self):
        from PySide6.QtGui import QIcon

        from opensc3.app import tray
        paths, name = QIcon.themeSearchPaths(), QIcon.themeName()
        self.addCleanup(QIcon.setThemeName, name)
        self.addCleanup(QIcon.setThemeSearchPaths, paths)
        with tempfile.TemporaryDirectory() as d:
            env = {"HOME": d, "XDG_DATA_HOME": str(Path(d) / "data"), "XDG_CONFIG_HOME": str(Path(d) / "config")}
            I.install(I.plan(env=env, which=lambda n: None, python=PY), out=lambda s: None, which=lambda n: None)
            QIcon.setThemeSearchPaths([str(Path(d) / "data" / "icons"), "/usr/share/icons"])
            QIcon.setThemeName("hicolor")
            for state in STATES:
                icon = tray.theme_icon(state)
                self.assertIsNotNone(icon, state)
                self.assertEqual(icon.name(), f"opensc3-{state}")  # трей отдаёт Plasma имя, не картинку
            self.assertIsNone(tray.theme_icon("no-such-state"))
            QIcon.setThemeSearchPaths(["/nonexistent"])
            self.assertIsNone(tray.theme_icon("muted"))


if __name__ == "__main__":
    unittest.main()
