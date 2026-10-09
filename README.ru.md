# OpenSC3

[English](README.md) · Русский

**OpenSC3** — открытый пульт под Linux для USB-микшера **fifine AmpliGame SC3** (USB `3142:0c33`, чип MVsilicon
BP1048B2). Своей программы для SC3 у Fifine нет вообще; в Linux он работает как обычная USB-звуковая карта, а всё
остальное — mute, усиления, встроенный эквалайзер и эффекты голоса, тональность автотюна — живёт за вендорским
HID-интерфейсом, который ядро не подхватывает. Этот проект говорит с ним напрямую.

**Состояние: пре-альфа.** В основном чтение: командная строка проверяет установку, печатает понятную сводку и
снимает полный дамп блоков и узлов эффектов; окно (Qt) показывает состояние микшера, уровни и mute микрофона.
Запись в микшер (поправка микрофона, эквалайзер голоса, шумодав) — по белому списку и по умолчанию сухим
прогоном; `sc3 … --write` — экспериментально, см. [docs/WRITE.md](docs/WRITE.md). Планы — [docs/PLAN.md](docs/PLAN.md).

## Сначала безопасность

В протоколе есть команды, которые перепрошивают устройство или вешают его канал управления. Проект шлёт **только**
кадры-чтения из белого списка, перед первым сверяет дескриптор интерфейса и сборку прошивки, никогда не делает
Feature-запросов HID и не трогает конфигурацию USB; тест проверяет его собственный исходник на опасные вызовы.
Подробно — [docs/GOTCHAS.md](docs/GOTCHAS.md), [docs/RESEARCH.md](docs/RESEARCH.md). Поддерживается только прошивка **V22**.

## Быстрый старт

Нужно: Python ≥ 3.11, системная `libusb`, для окна — `pyside6`, для кнопок — `python-evdev`.

```sh
sudo install -m 644 udev/70-fifine-sc3.rules /etc/udev/rules.d/
sudo udevadm control --reload
sudo udevadm trigger --action=change --attr-match=idVendor=3142 --attr-match=idProduct=0c33
python3 -m opensc3 doctor      # проверка установки, устройству ничего не шлёт
python3 -m opensc3 status      # ~20 запросов чтения
python3 -m opensc3 dump -o dump.json
python3 -m opensc3.app         # окно и трей
```

После установки пакетом те же команды — `sc3 doctor|status|dump` и `opensc3` (окно).

Правило udev даёт доступ (`uaccess`) пользователю за компьютером и только к SC3 — без группы `input`.

## На чём стоит

[dank0i/sc3](https://github.com/dank0i/sc3) (протокол ACP, разбор прошивки),
[wopln/FIFINE-SC3-RGB-Plus](https://github.com/wopln/FIFINE-SC3-RGB-Plus) (опознание прошивки, протокол загрузчика),
[Austrum-lab/fifine-am8](https://github.com/Austrum-lab/fifine-am8) (тот же протокол на AM8 под Linux), открытый SDK
MVsilicon BP10 ([leadercxn/bp1048_sdk_v0.1.12](https://github.com/leadercxn/bp1048_sdk_v0.1.12)).

## Оговорка

OpenSC3 — неофициальный проект, не связан с FIFINE и MVsilicon и не одобрен ими. «FIFINE» и «AmpliGame» — товарные
знаки их владельцев; «SC3» лишь называет совместимую модель. Прошивок и данных производителя в репозитории нет.
Пользуетесь на свой риск.

Лицензия: [MIT](LICENSE).
