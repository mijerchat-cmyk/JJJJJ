"""Долгий доступ к Google Drive (refresh token) без хранения чего-либо на сервере.

Сервер только обменивает одноразовый код (или ключ продления) в Google и сразу
возвращает ответ приложению. Ключ продления нигде не сохраняется и не пишется в логи.
Нужны переменные: GOOGLE_CLIENT_ID (уже есть) и GOOGLE_CLIENT_SECRET (новая).
"""
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from app.database import get_connection

TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.appdata"


def client_id():
    return os.environ.get("GOOGLE_CLIENT_ID", "").strip()


def client_secret():
    return os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()


def configured():
    return bool(client_id() and client_secret())


def _post(form):
    """Возвращает (json, http_status); (None, 0) если Google недоступен."""
    data = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            body = {}
        print("[drive] Google ответил", exc.code, body.get("error"), body.get("error_description"), flush=True)
        return body, exc.code
    except Exception as exc:  # noqa: BLE001
        print("[drive] нет связи с Google:", type(exc).__name__, flush=True)
        return None, 0


def _claims(id_token):
    try:
        part = id_token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part.encode("ascii")).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _mask(email):
    if not email or "@" not in email:
        return ""
    name, domain = email.split("@", 1)
    return name[:2] + "***@" + domain


def _binding_error(user_id, sub, email):
    """Drive должен принадлежать тому же Google-аккаунту, что и аккаунт приложения."""
    with get_connection() as conn:
        row = conn.execute("SELECT google_sub, email FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        return "Пользователь не найден"
    gsub = row["google_sub"]
    uemail = (row["email"] or "").strip().lower()
    email = (email or "").strip().lower()
    if gsub:
        ok = gsub == sub
    elif uemail and uemail == email:
        ok = True
    elif uemail.endswith(("@gmail.com", "@googlemail.com")):
        ok = False
    else:
        ok = True   # аккаунт создан по почте не из Google — такой не проверить, приложение запомнит первый выбор
    if ok:
        return None
    hint = _mask(uemail)
    return "Подключите тот же Google-аккаунт" + (": " + hint if hint else ", которым вы входили")


def exchange_code(user_id, code):
    """Возвращает (результат, ошибка, http_status)."""
    code = str(code or "").strip()
    if not code or len(code) > 2048:
        return None, "Пустой код", 400
    data, status = _post({
        "code": code, "client_id": client_id(), "client_secret": client_secret(),
        "redirect_uri": "postmessage", "grant_type": "authorization_code",
    })
    if data is None:
        return None, "Не удалось связаться с Google, попробуйте ещё раз", 502
    if status != 200 or not data.get("access_token"):
        return None, "Google отклонил код. Попробуйте подключить Drive ещё раз", 400
    if DRIVE_SCOPE not in str(data.get("scope", "")):
        return None, "Не выдан доступ к Drive. В окне Google отметьте разрешение на данные приложения", 400
    claims = _claims(data.get("id_token", ""))
    sub, email = claims.get("sub"), claims.get("email", "")
    if not sub:
        return None, "Google не вернул данные аккаунта", 400
    print("[drive] код принят; ключ продления:", "ЕСТЬ" if data.get("refresh_token") else "НЕТ", flush=True)
    problem = _binding_error(user_id, sub, email)
    if problem:
        print("[drive] другой Google-аккаунт, отказ", flush=True)
        return {"error": problem, "code": "wrong-account"}, None, 403
    result = {"access_token": data["access_token"], "expires_in": data.get("expires_in", 3600),
              "email": email, "sub": sub}
    if data.get("refresh_token"):
        result["refresh_token"] = data["refresh_token"]
    return result, None, 200


def refresh(refresh_token):
    refresh_token = str(refresh_token or "").strip()
    if not refresh_token or len(refresh_token) > 2048:
        return None, "Пустой ключ", 400
    data, status = _post({
        "refresh_token": refresh_token, "client_id": client_id(),
        "client_secret": client_secret(), "grant_type": "refresh_token",
    })
    if data is None:
        return None, "Не удалось связаться с Google", 502
    if status != 200 or not data.get("access_token"):
        return None, {"error": "revoked"}, 400     # доступ отозван или ключ недействителен
    return {"access_token": data["access_token"], "expires_in": data.get("expires_in", 3600)}, None, 200
