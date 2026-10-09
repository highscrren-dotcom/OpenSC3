# research/ — разовые скрипты разведки

Не часть пакета; ruff их не проверяет. Вызывать с `python3 -I -B`, пути — аргументами.

| Скрипт | Что делает | Нужно |
|---|---|---|
| `gate-stats.py запись.raw` | статистика сырой записи входа SC3 (S16_LE, 48 кГц, 2 кан.): нули, уровни, закрытия гейта | numpy |
| `gate-watch.py СЕКУНД` | то же потоком из `parec … --raw`, по минутам, без сохранения звука | numpy |
| `stand.py [--seconds 900] [--interval 0.5]` | стенд опроса этапа 2: только `0x07` по расписанию, xrun узлов SC3 (`pw-top`), журнал ядра, аварийная остановка → `dumps/stand-*.json`. На SC3 — только вне эфира, вместе с владельцем; `--fake [--fault …]` — без устройства | `pw-top`, `journalctl` |
| `decode-dump.py дамп.json` | расшифровка EQ/DRC/эффектов из дампа `sc3 dump` | — |
| `fw-analyze.py <dank0i-sc3> <.MVA> <дамп.json> <папка>` | расшифровка кода V22, сверка имён узлов с устройством, поиск USB-дескрипторов, список ресурсов | клон [dank0i/sc3](https://github.com/dank0i/sc3) (код прочитан 07.10, сеть не трогает) |
| `fw-presets.py plain.bin дамп.json` | поиск вшитых пресетов (цепочек ACP-кадров) в расшифрованном коде | вывод `fw-analyze.py` |

Запись входа для `gate-stats.py`:

```fish
timeout 60 parec -d alsa_input.usb-MV-SILICON_fifine_SC3_20190808-00.analog-stereo --format=s16le --rate=48000 --channels=2 --raw > /tmp/sc3.raw
```

Результаты разбора прошивки — только локально (`firmware/`, вне git; `DECISIONS.md`, решение 5).
