# Запуск (в папке проекта):  python patch_install.py
# Правит frontend/index.html и app/web_assets.py. Делает копии *.bak. Если что-то не найдено — ничего не ломает.
import io, sys, shutil

def read(p):
    with open(p, 'rb') as f: return f.read().decode('utf-8')
def write(p, s):
    shutil.copyfile(p, p + '.bak')
    with open(p, 'wb') as f: f.write(s.encode('utf-8'))

# ---------- 1. web_assets.py: надёжный manifest ----------
NEW_MANIFEST = '''def manifest():
    icons = []
    for size in (192, 512):
        for purpose in ("any", "maskable"):
            icons.append({"src": f"/icon-{size}.png", "sizes": f"{size}x{size}", "type": "image/png", "purpose": purpose})
    return json.dumps({
        "id": "/", "name": APP_NAME, "short_name": "Mijer", "start_url": "/", "scope": "/",
        "display": "standalone", "background_color": BG, "theme_color": THEME, "lang": "ru",
        "description": "Мессенджер: чаты, группы, голосовые и видеозвонки",
        "icons": icons,
    }, ensure_ascii=False)


'''
p = 'app/web_assets.py'
s = read(p)
a = s.find('def manifest():'); b = s.find('SERVICE_WORKER = """')
if a < 0 or b < 0 or b < a:
    print('web_assets.py: не нашёл manifest(), пропускаю'); sys.exit(1)
nl = '\r\n' if '\r\n' in s else '\n'
s2 = s[:a] + NEW_MANIFEST.replace('\n', nl) + s[b:]
write(p, s2); print('web_assets.py: готово')

# ---------- 2. index.html: кнопка установки для любых телефонов ----------
NEW_JS = '''let installPrompt = null;
const installBtn = document.getElementById('install-app-btn');
const installHint = document.getElementById('install-hint');
const isStandalone = () => window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
function installSteps(){
  const ua = navigator.userAgent;
  if(/iPhone|iPad|iPod/.test(ua)) return 'iPhone: откройте сайт в Safari → «Поделиться» → «На экран "Домой"».';
  if(/SamsungBrowser/.test(ua)) return 'Samsung Internet: меню ≡ → «Добавить страницу на» → «Главный экран».';
  if(/Firefox|FxiOS/.test(ua)) return 'Firefox: меню ⋮ → «Установить» (или «Добавить на главный экран»).';
  if(/OPR|Opera/.test(ua)) return 'Opera: меню ⋮ → «Главный экран» (или «Добавить на главный экран»).';
  return 'Откройте меню браузера (⋮) → «Установить приложение» или «Добавить на главный экран». Если такого пункта нет — откройте этот сайт в Google Chrome.';
}
function updateInstallUi(){
  if(isStandalone()){ installBtn.hidden = true; installHint.textContent = 'Приложение уже установлено на это устройство ✓'; return; }
  installBtn.hidden = false;
  installHint.textContent = installPrompt ? 'Нажмите кнопку — приложение установится на телефон.' : installSteps();
}
window.addEventListener('beforeinstallprompt', e => { e.preventDefault(); installPrompt = e; updateInstallUi(); });
window.addEventListener('appinstalled', () => { installPrompt = null; updateInstallUi(); });
installBtn.addEventListener('click', async () => {
  if(installPrompt){
    installPrompt.prompt();
    await installPrompt.userChoice.catch(() => {});
    installPrompt = null; updateInstallUi();
  }else{
    installHint.textContent = installSteps();
    installHint.style.fontWeight = '600';
  }
});
updateInstallUi();
if('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
'''
p = 'frontend/index.html'
s = read(p)
a = s.find('let installPrompt = null;')
m = "navigator.serviceWorker.register('/sw.js').catch(() => {});"
e = s.find(m, a)
e2 = s.find('})();', e) if e >= 0 else -1
if a < 0 or e < 0 or e2 < 0:
    print('index.html: не нашёл блок установки, пропускаю'); sys.exit(1)
nl = '\r\n' if '\r\n' in s else '\n'
s2 = s[:a] + NEW_JS.replace('\n', nl) + s[e2 + len('})();'):]
old_btn = 'id="install-app-btn" type="button" hidden'
if old_btn in s2: s2 = s2.replace(old_btn, 'id="install-app-btn" type="button"', 1)
write(p, s2); print('index.html: готово')
print('Теперь: git add . ; git commit -m "install button for all phones" ; git push')