# Запуск (в папке проекта):  python patch_sync.py
# Синхронизация устройств одного аккаунта через Drive. Нужен уже применённый patch_drive.py.
# Меняет main.py и frontend/index.html. Всё или ничего. Копии: *.bak
import shutil, sys

SYNC_BLOCK = "// ---------- синхронизация устройств одного аккаунта через Drive ----------\nasync function tombAdd(id){ const t = (await kvGet2('tomb')) || []; if(t.includes(id)) return; t.push(id); await kvSet2('tomb', t.slice(-3000)); }\nfunction pokeOthers(){ try{ origFetch(API_BASE + '/api/drive/poke', {method: 'POST', headers: deviceHeaders({'Content-Type': 'application/json'}), body: '{}'}).catch(() => {}); }catch{} }\nasync function refreshCounts(){\n  try{\n    const vis = (await rall('msgs')).filter(m => !m.hidden && m.type !== 'call');\n    writeMeta({chats: new Set(vis.map(m => m.chat_key)).size, msgs: vis.length});\n  }catch{}\n}\nasync function mergeRecs(list, ackIds, fromChatFile){\n  const tomb = new Set((await kvGet2('tomb')) || []);\n  const ops = []; let n = 0;\n  for(const raw of list){\n    if(!raw || !raw.id || tomb.has(raw.id)) continue;\n    let rec = raw;\n    if(fromChatFile){\n      if(!raw.created_at) continue;\n      rec = {...raw, hidden: false, reactions: raw.reactions || {}, upd: raw.upd || raw.created_at};\n    }\n    if(!rec.chat_key || !rec.kind) continue;\n    const ex = await rget('msgs', rec.id);\n    if(!ex){\n      ops.push(['msgs', 'put', rec]); n++; ackIds.push(rec.id);\n    }else if(!fromChatFile){\n      const out = ((rec.upd || '') > (ex.upd || '')) ? {...rec} : {...ex};\n      out.read_at = ex.read_at || rec.read_at || null;\n      out.played_at = ex.played_at || rec.played_at || null;\n      out.hidden = !!(ex.hidden || rec.hidden);\n      if(JSON.stringify(out) !== JSON.stringify(ex)){ ops.push(['msgs', 'put', out]); n++; }\n    }\n  }\n  for(let i = 0; i < ops.length; i += 100) await rbatch(ops.slice(i, i + 100));\n  return n;\n}\nasync function ackSynced(ids){\n  try{\n    for(let i = 0; i < ids.length; i += 400){\n      await relayPost('/api/relay/ack', {ids: ids.slice(i, i + 400), level: 2});\n    }\n  }catch{}\n}\nasync function relaySync(){\n  if(!RELAY.on || !RELAY.restoredAt) return;\n  if(RELAY.syncing){ RELAY.syncAgain = true; return; }\n  const meta = readMeta();\n  if(!(meta.enabled && state.mk)) return;\n  RELAY.syncing = true;\n  let changed = 0;\n  try{\n    await connectDrive(false);\n    const pre = prefix(), files = await driveList(), byName = new Map(files.map(f => [f.name, f.id]));\n    const known = new Set((await kvGet2('deltas')) || []);\n    const fresh = files.map(f => f.name).filter(n => n.startsWith(pre + 'd_') && !known.has(n)).sort();\n    const ackIds = [];\n    for(const n of fresh){\n      let d;\n      try{ d = await decryptJSON(state.mk, await driveRead(byName.get(n)), n); }\n      catch(e){ if(e instanceof DriveError) throw e; known.add(n); await kvSet2('deltas', [...known].sort()); continue; }\n      changed += await mergeRecs(d.msgs || [], ackIds, false);\n      for(const id of d.dels || []){\n        if(await rget('msgs', id)){ await rbatch([['msgs', 'delete', id]]); changed++; }\n        await tombAdd(id);\n      }\n      known.add(n); await kvSet2('deltas', [...known].sort());\n    }\n    // другое устройство могло «склеить» мелкие файлы в полную копию — забираем недостающее оттуда\n    const mname = pre + 'manifest.enc';\n    if(byName.has(mname)){\n      const manifest = await decryptJSON(state.mk, await driveRead(byName.get(mname)), mname);\n      const seen = await kvGet2('manifestSeen');\n      if((manifest.updated || '') !== (seen || '')){\n        let hashes = await kvGet2('chatHashes');\n        const baselineOnly = !hashes;       // первый запуск после обновления: просто запоминаем состояние\n        hashes = hashes || {};\n        for(const [key, info] of Object.entries(manifest.chats || {})){\n          if(hashes[key] === info.hash) continue;\n          if(!baselineOnly){\n            const id = byName.get(info.file);\n            if(id){\n              const data = await decryptJSON(state.mk, await driveRead(id), info.file);\n              const list = (data.messages || []).map(m => ({...m, kind: data.kind, chat_key: data.kind + ':' + data.id, space_id: data.kind === 'sp' ? (m.space_id || data.id) : m.space_id}));\n              changed += await mergeRecs(list, ackIds, true);\n            }\n          }\n          hashes[key] = info.hash;\n        }\n        await kvSet2('chatHashes', hashes); await kvSet2('manifestSeen', manifest.updated || '');\n      }\n    }\n    if(ackIds.length) await ackSynced(ackIds);\n    if(changed){ await refreshCounts(); notifyApp(); try{ dbg('синхронизация устройств: обновлено записей ' + changed); }catch{} }\n  }catch(e){\n    RELAY.error = String(e && e.message || e);\n    if(!(e instanceof DriveError)) try{ dbg('синхронизация устройств: ошибка ' + RELAY.error); }catch{}\n  }finally{\n    RELAY.syncing = false;\n    if(RELAY.syncAgain){ RELAY.syncAgain = false; setTimeout(relaySync, 500); }\n  }\n}\ndocument.addEventListener('visibilitychange', () => { if(!document.hidden) relaySync(); });\n\n"

def read(p):
    with open(p, 'rb') as f: return f.read().decode('utf-8')
def write(p, s):
    shutil.copyfile(p, p + '.bak')
    with open(p, 'wb') as f: f.write(s.encode('utf-8'))

problems = []
def once(s, old, new, name):
    n = s.count(old)
    if n != 1:
        problems.append('%s: найдено %d раз (нужно 1)' % (name, n)); return s
    return s.replace(old, new, 1)

# ---------------- main.py: сигнал «загляни в Drive» ----------------
m = read('main.py'); nl = '\r\n' if '\r\n' in m else '\n'
POKE = """
        # Устройство записало новое в Drive — даём знать остальным устройствам этого аккаунта.
        if self.path == "/api/drive/poke":
            user_id, _device = self._device_auth()
            if not user_id:
                self.send_json(401, {"error": "Сеанс недействителен", "session_invalid": True})
                return
            calls.push(user_id, {"type": "sync", "scope": "drive"})
            self.send_json(200, {"ok": True})
            return
""".replace('\n', nl)
if m.count('def _do_post_inner(self):') != 1: problems.append('main: _do_post_inner не найден')
elif '/api/drive/poke' in m: problems.append('main: блок poke уже есть')
else:
    a = m.find('def _do_post_inner(self):'); e = m.find(nl, a) + len(nl)
    m = m[:e] + POKE + m[e:]

# ---------------- index.html ----------------
h = read('frontend/index.html'); hnl = '\r\n' if '\r\n' in h else '\n'
if 'async function relaySync(' in h: problems.append('index: синхронизация уже добавлена')
h = once(h, '// ---------- запуск / остановка ----------', SYNC_BLOCK.replace('\n', hnl) + '// ---------- запуск / остановка ----------', 'js: блок синхронизации')
h = once(h, "async function removeRec(id){ await rbatch([['msgs', 'delete', id], ['dirty', 'put', {id, t: 'del', at: Date.now()}]]); RELAY.dirtyCount++; }",
 "async function removeRec(id){ await rbatch([['msgs', 'delete', id], ['dirty', 'put', {id, t: 'del', at: Date.now()}]]); RELAY.dirtyCount++; try{ await tombAdd(id); }catch{} }", 'js: removeRec')
h = once(h, "writeMeta({last: nowIso()});", "writeMeta({last: nowIso()}); await refreshCounts(); if(dirty.length) pokeOthers();", 'js: relayFlush')
h = once(h, "if(!RELAY.pollTimer) RELAY.pollTimer = setInterval(() => relayPull(), POLL_MS);",
 "if(!RELAY.pollTimer) RELAY.pollTimer = setInterval(() => relayPull(), POLL_MS); if(!RELAY.syncTimer) RELAY.syncTimer = setInterval(() => relaySync(), 90000); relaySync();", 'js: relayInit')
h = once(h, "if(RELAY.on && msg && msg.scope === 'msg'){ relayPull(); return; }",
 "if(msg && msg.scope === 'drive'){ if(RELAY.on) relaySync(); return; } if(RELAY.on && msg && msg.scope === 'msg'){ relayPull(); return; }", 'js: onServerSync')
h = once(h, "writeMeta({last: now, chats: items.length, msgs: total});",
 "writeMeta({last: now, chats: items.length, msgs: total}); if(RELAY.on){ try{ const hh = (await kvGet2('chatHashes')) || {}; for(const it of items){ const k = it.kind + ':' + it.id; if(manifest.chats[k]) hh[k] = manifest.chats[k].hash; } await kvSet2('chatHashes', hh); }catch{} }", 'js: runBackup')
h = once(h, "for(const info of Object.values(manifest.chats || {})){",
 "{ const hh0 = {}; for(const [k0, i0] of Object.entries(manifest.chats || {})) hh0[k0] = i0.hash; await kvSet2('chatHashes', hh0); await kvSet2('manifestSeen', manifest.updated || ''); } for(const info of Object.values(manifest.chats || {})){", 'js: relayRestore')

if problems:
    print('НИЧЕГО НЕ ИЗМЕНЕНО. Проблемы:'); [print(' -', x) for x in problems]; sys.exit(1)
write('main.py', m); write('frontend/index.html', h)
print('Готово. Теперь: git add . ; git commit -m "device sync" ; git push')