# Запуск (в папке проекта):  python patch_relay.py
# Новое правило удаления на сервере: сообщение удаляется, когда у КАЖДОГО человека хотя бы ОДНО устройство
# записало его в Drive. Остальные устройства получают его из Drive сами (нужен patch_sync.py).
# Переменная Railway RELAY_WAIT_ALL_DEVICES=on возвращает старое правило. Всё или ничего. Копия: relay.py.bak
import shutil, sys

HELPER = '''

def _acked_enough(targets, acks):
    """Можно ли удалять с сервера. По умолчанию: у каждого человека хотя бы одно устройство
    записало данные в Drive (уровень 2). RELAY_WAIT_ALL_DEVICES=on — ждать ВСЕ устройства (как раньше)."""
    if os.environ.get("RELAY_WAIT_ALL_DEVICES", "").strip().lower() in ("on", "1", "true", "yes"):
        return all(acks.get(d["id"], 0) >= 2 for d in targets)
    by_user = {}
    for d in targets:
        by_user.setdefault(d["user_id"], []).append(d["id"])
    return all(any(acks.get(device_id, 0) >= 2 for device_id in ids) for ids in by_user.values())
'''

def read(p):
    with open(p, 'rb') as f: return f.read().decode('utf-8')

p = 'app/relay.py'
s = read(p); nl = '\r\n' if '\r\n' in s else '\n'
problems = []
def once(s, old, new, name):
    n = s.count(old)
    if n != 1:
        problems.append('%s: найдено %d раз (нужно 1)' % (name, n)); return s
    return s.replace(old, new, 1)

if '_acked_enough' in s:
    problems.append('relay.py: патч уже применён')
else:
    anchor = 'return {r["device_id"]: r["level"] for r in conn.execute("SELECT device_id, level FROM relay_acks WHERE item_id = ?", (item_id,)).fetchall()}'
    s = once(s, anchor, anchor + HELPER.replace('\n', nl), 'relay: _acks_for')
    s = once(s, 'if all(acks.get(d["id"], 0) >= 2 for d in targets):', 'if _acked_enough(targets, acks):', 'relay: удаление сообщений')
    s = once(s, 'if all(acks.get(d["id"], 0) >= 2 for d in devices):', 'if _acked_enough(devices, acks):', 'relay: удаление событий')
if 'import os' not in s: problems.append('relay.py: нет import os')
if problems:
    print('НИЧЕГО НЕ ИЗМЕНЕНО. Проблемы:'); [print(' -', x) for x in problems]; sys.exit(1)
shutil.copyfile(p, p + '.bak')
with open(p, 'wb') as f: f.write(s.encode('utf-8'))
print('Готово. Теперь: git add . ; git commit -m "relay: one device per person" ; git push')