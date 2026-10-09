#!/usr/bin/env python3
"""Офлайн-разбор заводской прошивки SC3 V22 библиотекой dank0i/sc3 (decrypt/*, прочитана).

  python3 -I fw-analyze.py <путь к репо dank0i-sc3> <файл .MVA> <дамп sc3-probe .json> <папка для результатов>
Устройство не трогает. Пишет plain.bin (расшифрованный код) и resources.txt в папку результатов.
"""
import hashlib
import json
import pathlib
import sys

repo, mva_path, dump_path, out = map(pathlib.Path, sys.argv[1:5])
sys.path.insert(0, str(repo))
sys.path.insert(0, str(repo / "tools"))
from decrypt import container, image  # noqa: E402
import effect_table  # noqa: E402  (tools/effect_table.py — прочитан, только парсер)

mva = container.load(mva_path)
print(f"MVA: чип {mva.chip:#04x}, поколение {mva.generation:#04x}, записей {len(mva.records)}, "
      f"CRC16 {mva.stored_crc:#06x} {'совпадает' if mva.crc_ok else 'НЕ совпадает'}")
for r in mva.records:
    base = r.flash_base
    print(f"  тип {r.type} {r.type_name:<12} {len(r.payload):>9} байт" + (f", база {base:#010x}" if base is not None else ""))

table, exact = image.resolve_table(mva)
print(f"таблица меток: {table.name}, точное совпадение по SHA-256 кода: {exact}")
plain, stats = image.decrypt_code(mva.record(container.TYPE_CODE).payload, table)
print(f"расшифровано: {stats}")
out.mkdir(parents=True, exist_ok=True)
(out / "plain.bin").write_bytes(plain)
print(f"plain.bin: {len(plain)} байт, SHA-256 {hashlib.sha256(plain).hexdigest()[:16]}…")

# 1) Таблица имён узлов из образа против того, что сказало устройство (0x80)
names = effect_table.names_from_image(plain)
dev = json.load(open(dump_path))["nodes"]
same = sum(1 for i, n in enumerate(names) if dev[f"{0x81 + i:#04x}"]["name"] == n)
print(f"имена узлов: образ {len(names)}, совпало с устройством {same} из {len(names)}")
for i, n in enumerate(names):
    d = dev[f"{0x81 + i:#04x}"]["name"]
    if d != n:
        print(f"  {0x81 + i:#04x}: образ «{n}» / устройство «{d}»")

# 2) USB-дескрипторы и строки в образе
def find_all(b, pat):
    i, res = 0, []
    while (i := b.find(pat, i)) != -1:
        res.append(i)
        i += 1
    return res

pats = {
    "HID consumer (интерфейс 3)": bytes.fromhex("050c0901a101150025010" "9e909ea09b509b609e209b309cd09b7750195088142c0"),
    "HID vendor (интерфейс 4)": bytes.fromhex("0600ff0aaa55a10115"),
    "VID/PID 3142:0c33 (LE)": bytes.fromhex("4231330c"),
    "MV-SILICON (UTF-16LE)": "MV-SILICON".encode("utf-16le"),
    "fifine SC3 (UTF-16LE)": "fifine SC3".encode("utf-16le"),
    "20190808 (UTF-16LE)": "20190808".encode("utf-16le"),
    "MV-SILICON (ascii)": b"MV-SILICON",
    "fifine SC3 (ascii)": b"fifine SC3",
}
for label, pat in pats.items():
    hits = find_all(plain, pat)
    print(f"{label}: " + (", ".join(f"{h:#08x}" for h in hits[:6]) if hits else "нет"))

# 3) Ресурсы Const (голосовые подсказки, открытым текстом)
res = container.parse_mvub(mva.record(container.TYPE_CONST).body)
(out / "resources.txt").write_text("\n".join(f"{r.name:<10} {r.offset:#08x} {r.size}" for r in res))
print(f"ресурсов в Const: {len(res)}: " + ", ".join(r.name for r in res))
