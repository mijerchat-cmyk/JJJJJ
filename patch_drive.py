# Запуск (в папке проекта):  python patch_drive.py
# Долгий доступ к Google Drive без хранения на сервере + привязка Drive к аккаунту + показ почты.
# Меняет main.py и frontend/index.html, создаёт app/drive_auth.py. Всё или ничего: если хоть одно место
# не найдено, файлы НЕ меняются, а скрипт пишет, какого места не хватило. Копии: *.bak
import shutil, sys

DRIVE_AUTH = '"""Долгий доступ к Google Drive (refresh token) без хранения чего-либо на сервере.\n\nСервер только обменивает одноразовый код (или ключ продления) в Google и сразу\nвозвращает ответ приложению. Ключ продления нигде не сохраняется и не пишется в логи.\nНужны переменные: GOOGLE_CLIENT_ID (уже есть) и GOOGLE_CLIENT_SECRET (новая).\n"""\nimport base64\nimport json\nimport os\nimport urllib.error\nimport urllib.parse\nimport urllib.request\n\nfrom app.database import get_connection\n\nTOKEN_URL = "https://oauth2.googleapis.com/token"\nDRIVE_SCOPE = "https://www.googleapis.com/auth/drive.appdata"\n\n\ndef client_id():\n    return os.environ.get("GOOGLE_CLIENT_ID", "").strip()\n\n\ndef client_secret():\n    return os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()\n\n\ndef configured():\n    return bool(client_id() and client_secret())\n\n\ndef _post(form):\n    """Возвращает (json, http_status); (None, 0) если Google недоступен."""\n    data = urllib.parse.urlencode(form).encode("utf-8")\n    req = urllib.request.Request(TOKEN_URL, data=data, method="POST",\n                                 headers={"Content-Type": "application/x-www-form-urlencoded"})\n    try:\n        with urllib.request.urlopen(req, timeout=10) as resp:\n            return json.loads(resp.read().decode("utf-8")), resp.status\n    except urllib.error.HTTPError as exc:\n        try:\n            body = json.loads(exc.read().decode("utf-8"))\n        except Exception:  # noqa: BLE001\n            body = {}\n        return body, exc.code\n    except Exception:  # noqa: BLE001\n        return None, 0\n\n\ndef _claims(id_token):\n    try:\n        part = id_token.split(".")[1]\n        part += "=" * (-len(part) % 4)\n        return json.loads(base64.urlsafe_b64decode(part.encode("ascii")).decode("utf-8"))\n    except Exception:  # noqa: BLE001\n        return {}\n\n\ndef _mask(email):\n    if not email or "@" not in email:\n        return ""\n    name, domain = email.split("@", 1)\n    return name[:2] + "***@" + domain\n\n\ndef _binding_error(user_id, sub, email):\n    """Drive должен принадлежать тому же Google-аккаунту, что и аккаунт приложения."""\n    with get_connection() as conn:\n        row = conn.execute("SELECT google_sub, email FROM users WHERE id = ?", (user_id,)).fetchone()\n    if not row:\n        return "Пользователь не найден"\n    gsub = row["google_sub"]\n    uemail = (row["email"] or "").strip().lower()\n    email = (email or "").strip().lower()\n    if gsub:\n        ok = gsub == sub\n    elif uemail and uemail == email:\n        ok = True\n    elif uemail.endswith(("@gmail.com", "@googlemail.com")):\n        ok = False\n    else:\n        ok = True   # аккаунт создан по почте не из Google — такой не проверить, приложение запомнит первый выбор\n    if ok:\n        return None\n    hint = _mask(uemail)\n    return "Подключите тот же Google-аккаунт" + (": " + hint if hint else ", которым вы входили")\n\n\ndef exchange_code(user_id, code):\n    """Возвращает (результат, ошибка, http_status)."""\n    code = str(code or "").strip()\n    if not code or len(code) > 2048:\n        return None, "Пустой код", 400\n    data, status = _post({\n        "code": code, "client_id": client_id(), "client_secret": client_secret(),\n        "redirect_uri": "postmessage", "grant_type": "authorization_code",\n    })\n    if data is None:\n        return None, "Не удалось связаться с Google, попробуйте ещё раз", 502\n    if status != 200 or not data.get("access_token"):\n        return None, "Google отклонил код. Попробуйте подключить Drive ещё раз", 400\n    if DRIVE_SCOPE not in str(data.get("scope", "")):\n        return None, "Не выдан доступ к Drive. В окне Google отметьте разрешение на данные приложения", 400\n    claims = _claims(data.get("id_token", ""))\n    sub, email = claims.get("sub"), claims.get("email", "")\n    if not sub:\n        return None, "Google не вернул данные аккаунта", 400\n    problem = _binding_error(user_id, sub, email)\n    if problem:\n        return {"error": problem, "code": "wrong-account"}, None, 403\n    result = {"access_token": data["access_token"], "expires_in": data.get("expires_in", 3600),\n              "email": email, "sub": sub}\n    if data.get("refresh_token"):\n        result["refresh_token"] = data["refresh_token"]\n    return result, None, 200\n\n\ndef refresh(refresh_token):\n    refresh_token = str(refresh_token or "").strip()\n    if not refresh_token or len(refresh_token) > 2048:\n        return None, "Пустой ключ", 400\n    data, status = _post({\n        "refresh_token": refresh_token, "client_id": client_id(),\n        "client_secret": client_secret(), "grant_type": "refresh_token",\n    })\n    if data is None:\n        return None, "Не удалось связаться с Google", 502\n    if status != 200 or not data.get("access_token"):\n        return None, {"error": "revoked"}, 400     # доступ отозван или ключ недействителен\n    return {"access_token": data["access_token"], "expires_in": data.get("expires_in", 3600)}, None, 200\n'
JS_CONNECT = 'function driveEmailLine(){ const m = readMeta(); return m.email ? \'<p class="ob-lead">Google: \' + esc(m.email) + \'</p>\' : \'\'; }\n// Ключ продления лежит на устройстве, зашифрованный главным ключом копии. На сервере его нет.\nasync function saveRt(){ if(!state.mk || !drive.rt) return; try{ await kvPut(\'rt\', await seal(state.mk, enc.encode(drive.rt), \'rt\')); }catch{} }\nasync function loadRt(){ drive.rt = null; if(!state.mk) return; try{ const env = await kvGet(\'rt\'); if(env) drive.rt = dec.decode(await open(state.mk, env, \'rt\')); }catch{} }\nasync function dropRt(){ drive.rt = null; try{ await idb(\'kv\', \'readwrite\', st => { st.delete(\'rt\'); }); }catch{} }\nfunction refreshByRt(){\n  if(drive.refreshing) return drive.refreshing;\n  drive.refreshing = (async () => {\n    const res = await origFetch(API_BASE + \'/api/drive/refresh\', {method: \'POST\', headers: deviceHeaders({\'Content-Type\': \'application/json\'}), body: JSON.stringify({refresh_token: drive.rt})});\n    if(res.status === 400) throw new Error(\'rt-revoked\');\n    if(!res.ok) throw new DriveError(\'auth\');\n    const d = await res.json();\n    drive.token = d.access_token; drive.exp = Date.now() + (Number(d.expires_in) || 3600) * 1000; storeToken();\n  })().finally(() => { drive.refreshing = null; });\n  return drive.refreshing;\n}\nasync function connectOffline(cfg){\n  const meta = readMeta();\n  const resp = await new Promise((resolve, reject) => {\n    const client = google.accounts.oauth2.initCodeClient({\n      client_id: cfg.google_client_id, scope: SCOPES, ux_mode: \'popup\', login_hint: meta.email || undefined,\n      callback: r => r && r.error ? reject(new Error(r.error)) : resolve(r),\n      error_callback: e => reject(new Error((e && e.type) || \'popup_closed\'))\n    });\n    client.requestCode();\n  });\n  if(!resp || !resp.code) throw new Error(\'popup_closed\');\n  if(resp.scope && !String(resp.scope).includes(\'drive.appdata\')) throw new Error(\'no-scope\');\n  let res;\n  try{ res = await origFetch(API_BASE + \'/api/drive/token\', {method: \'POST\', headers: deviceHeaders({\'Content-Type\': \'application/json\'}), body: JSON.stringify({code: resp.code})}); }\n  catch{ throw new Error(\'offline-unavailable\'); }\n  if([401, 404, 501].includes(res.status)) throw new Error(\'offline-unavailable\');\n  if(!res.ok){\n    let d = {}; try{ d = await res.json(); }catch{}\n    if(d.code === \'wrong-account\') throw new Error(\'wrong-account:\' + (d.error || \'\'));\n    throw new Error(d.error || \'drive-token\');\n  }\n  const d = await res.json();\n  if(meta.driveSub && d.sub && meta.driveSub !== d.sub) throw new Error(\'wrong-account:Подключите тот же Google-аккаунт\' + (meta.email ? \': \' + meta.email : \'\'));\n  drive.token = d.access_token; drive.exp = Date.now() + (Number(d.expires_in) || 3600) * 1000; storeToken();\n  if(d.refresh_token){ drive.rt = d.refresh_token; drive.noRt = false; await saveRt(); } else if(!drive.rt) drive.noRt = true;\n  const patch = {}; if(d.email) patch.email = d.email; if(d.sub) patch.driveSub = d.sub;\n  writeMeta(patch);\n  return drive.token;\n}\nasync function connectImplicit(cfg){\n  const resp = await new Promise((resolve, reject) => {\n    const client = google.accounts.oauth2.initTokenClient({\n      client_id: cfg.google_client_id, scope: SCOPES,\n      callback: r => r && r.error ? reject(new Error(r.error)) : resolve(r),\n      error_callback: e => reject(new Error((e && e.type) || \'popup_closed\'))\n    });\n    client.requestAccessToken({prompt: \'\'});\n  });\n  const granted = (typeof google.accounts.oauth2.hasGrantedAllScopes === \'function\')\n    ? google.accounts.oauth2.hasGrantedAllScopes(resp, DRIVE_SCOPE) : String(resp.scope || \'\').includes(\'drive.appdata\');\n  if(!granted) throw new Error(\'no-scope\');\n  drive.token = resp.access_token; drive.exp = Date.now() + (Number(resp.expires_in) || 3600) * 1000; storeToken();\n  try{ const ui2 = await (await fetch(\'https://www.googleapis.com/oauth2/v3/userinfo\', {headers:{Authorization:\'Bearer \' + drive.token}})).json(); if(ui2 && ui2.email) writeMeta({email: ui2.email}); }catch{}\n  return drive.token;\n}\nasync function connectDrive(interactive){\n  if(tokenValid()) return drive.token;\n  if(drive.rt){\n    try{ await refreshByRt(); return drive.token; }\n    catch(e){\n      if(String(e && e.message) === \'rt-revoked\') await dropRt();\n      if(!interactive) throw new DriveError(\'auth\');\n    }\n  }\n  if(!interactive) throw new DriveError(\'auth\');\n  const cfg = await prepareGoogle();\n  if(!cfg.google_client_id) throw new Error(\'no-google\');\n  if(cfg.drive_offline){\n    try{ return await connectOffline(cfg); }\n    catch(e){ if(String(e && e.message) !== \'offline-unavailable\') throw e; }\n  }\n  return connectImplicit(cfg);\n}\n'

def read(p):
    with open(p, 'rb') as f: return f.read().decode('utf-8')
def write(p, s, backup=True):
    if backup:
        try: shutil.copyfile(p, p + '.bak')
        except FileNotFoundError: pass
    with open(p, 'wb') as f: f.write(s.encode('utf-8'))

problems = []
def once(s, old, new, name):
    n = s.count(old)
    if n != 1:
        problems.append('%s: найдено %d раз (нужно 1)' % (name, n)); return s
    return s.replace(old, new, 1)

# ------------------------- main.py -------------------------
m = read('main.py'); nl = '\r\n' if '\r\n' in m else '\n'
m = once(m, 'from app import email_auth', 'from app import email_auth' + nl + 'from app import drive_auth', 'main: import')
m = once(m, '"relay_mode": relay_mod.enabled()})', '"relay_mode": relay_mod.enabled(), "drive_offline": drive_auth.configured()})', 'main: config')
BLOCK = """
        # Долгий доступ к Drive: обмен кода/ключа в Google. Сервер ничего не запоминает.
        if self.path in ("/api/drive/token", "/api/drive/refresh"):
            data = self.read_json_body() or {}
            if not drive_auth.configured():
                self.send_json(501, {"error": "Долгий доступ к Drive не настроен на сервере (GOOGLE_CLIENT_SECRET)"})
                return
            user_id, _device = self._device_auth()
            if not user_id:
                self.send_json(401, {"error": "Сеанс недействителен", "session_invalid": True})
                return
            if self.path == "/api/drive/token":
                result, error, status = drive_auth.exchange_code(user_id, data.get("code", ""))
            else:
                result, error, status = drive_auth.refresh(data.get("refresh_token", ""))
            if error:
                self.send_json(status, error if isinstance(error, dict) else {"error": error})
                return
            self.send_json(status, result)
            return
""".replace('\n', nl)
a = m.find('def _do_post_inner(self):')
if m.count('def _do_post_inner(self):') != 1: problems.append('main: _do_post_inner не найден')
else:
    e = m.find(nl, a) + len(nl)
    m = m[:e] + BLOCK + m[e:]

# ------------------------- index.html -------------------------
h = read('frontend/index.html')
h = once(h, "async function loadMk(){ try{ state.mk = (await kvGet('mk')) || null; }catch{ state.mk = null; } state.loaded = true; }",
 "async function loadMk(){ try{ state.mk = (await kvGet('mk')) || null; }catch{ state.mk = null; } state.loaded = true; await loadRt(); if(drive.rt && !tokenValid()){ try{ await Promise.race([connectDrive(false), new Promise(r => setTimeout(r, 4000))]); }catch{} } }", 'js: loadMk')
h = once(h, "async function saveMk(mkRaw){ state.mk = await importMk(mkRaw); try{ await kvPut('mk', state.mk); }catch{} }",
 "async function saveMk(mkRaw){ state.mk = await importMk(mkRaw); try{ await kvPut('mk', state.mk); }catch{} if(drive.rt) await saveRt(); }", 'js: saveMk')
h = once(h, "function wipeLocal(userId){", "function wipeLocal(userId){ try{ drive.rt = null; drive.token = null; drive.exp = 0; }catch{}", 'js: wipeLocal')
# замена всей connectDrive
a = h.find('async function connectDrive(interactive){'); b = h.find('async function driveFetch(url, opts){')
if h.count('async function connectDrive(interactive){') != 1 or h.count('async function driveFetch(url, opts){') != 1 or b < a:
    problems.append('js: connectDrive/driveFetch не найдены')
else:
    h = h[:a] + JS_CONNECT.replace('\n', nl) + h[b:]
h = once(h, "const t = T(), m = String(e && e.message || e);", "const t = T(), m = String(e && e.message || e); if(m.indexOf('wrong-account') === 0) return m.slice(14) || (t.err + m);", 'js: explain')
h = once(h, "(tokenValid() ? '' : '<p class=\"backup-err\">' + esc(t.expired) + '</p>')",
 "((tokenValid() || drive.rt) ? '' : '<p class=\"backup-err\">' + esc(t.expired) + '</p>') + ((drive.noRt && !drive.rt) ? '<p class=\"backup-err\">Google не выдал долгий доступ к Drive. Откройте myaccount.google.com/permissions \\u2192 Mijer Chat \\u2192 \\u00abУдалить доступ\\u00bb, затем подключите Drive снова.</p>' : '')", 'js: render expired')
h = once(h, "esc(tokenValid() ? t.backupNow : t.reconnectAgain)", "esc((tokenValid() || drive.rt) ? t.backupNow : t.reconnectAgain)", 'js: render button')
h = once(h, "if(!tokenValid()){ armSilentRefresh(); return; }", "if(!tokenValid()){ try{ await connectDrive(false); }catch{ armSilentRefresh(); return; } }", 'js: relayFlush')
h = once(h, "if(!meta.enabled || !state.mk || !tokenValid()) return;", "if(!meta.enabled || !state.mk) return;", 'js: scheduleAuto')
h = once(h, "!RELAY.restoredAt && tokenValid()", "!RELAY.restoredAt && (tokenValid() || drive.rt)", 'js: relayInit')
h = once(h, "+ esc(t.obCodeTitle) + '</h3><div class=\"ob-warn\">", "+ esc(t.obCodeTitle) + '</h3>' + driveEmailLine() + '<div class=\"ob-warn\">", 'js: onboarding email')
h = once(h, "displayEl.value = suggestedName || '';",
 "displayEl.value = suggestedName || ''; { let note = document.getElementById('reg-email-note'); if(!note){ note = document.createElement('p'); note.id = 'reg-email-note'; note.className = 'auth-subtitle'; authForm.insertBefore(note, authForm.querySelector('.field')); } note.textContent = (auth && auth.email) ? 'Аккаунт будет привязан к: ' + auth.email : ''; }", 'js: registration note')
h = once(h, "openRegistration({method:'google', credential: response.credential}, data.suggested_name);",
 "openRegistration({method:'google', credential: response.credential, email: data.email}, data.suggested_name);", 'js: google email')

if problems:
    print('НИЧЕГО НЕ ИЗМЕНЕНО. Не нашёл:'); [print(' -', x) for x in problems]; sys.exit(1)
write('app/drive_auth.py', DRIVE_AUTH, backup=False)
write('main.py', m); write('frontend/index.html', h)
print('Готово. Теперь: git add . ; git commit -m "drive long access" ; git push')
print('И добавь в Railway переменную GOOGLE_CLIENT_SECRET (см. инструкцию).')
