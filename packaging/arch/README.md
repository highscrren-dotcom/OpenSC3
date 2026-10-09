# Пакет Arch: `opensc3-git` (черновик)

В AUR пакета **пока нет**. `PKGBUILD` собирает OpenSC3 из git (ветка по умолчанию на GitHub) и ставит:

- пакет Python (`sc3`, `opensc3` в `/usr/bin`);
- правило udev `/usr/lib/udev/rules.d/70-fifine-sc3.rules` (pacman сам перечитает правила и пошлёт `change`
  устройствам; правило с тем же именем в `/etc/udev/rules.d/` перекрывает пакетное);
- ярлык `/usr/share/applications/opensc3.desktop`, значок приложения и значки трея в `hicolor`
  (то же, что `sc3 install` кладёт в `~/.local/share`);
- `LICENSE`.

## Собрать и поставить локально

Делает владелец сам (нужен sudo):

```fish
cd ~/dev/sc3-linux/packaging/arch
makepkg -si            # клонирует репозиторий с GitHub, собирает колесо, гоняет тесты, ставит пакет
```

`--nocheck` — без тестов. Пакет берёт код с GitHub, а не из рабочего каталога: незапушенные правки в него не попадут.
Клон и сборка (`OpenSC3/`, `src/`, `pkg/`, `*.pkg.tar.zst`) остаются здесь и в git не идут (`.gitignore`).

После установки пакета ярлык из `sc3 install` (если ставили) перекрывает системный — убрать его: `sc3 uninstall`.

## Поправить PKGBUILD

После правки обновить `.SRCINFO` (это не сборка):

```fish
makepkg --printsrcinfo > .SRCINFO
```
