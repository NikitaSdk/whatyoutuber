"""Вход в YouTube через браузер или cookies.txt. Пароль приложение не видит."""

import os

_LOGIN_NAMES = {
    "LOGIN_INFO", "SID", "SSID", "HSID", "SAPISID", "APISID",
    "__SECURE-1PSID", "__SECURE-3PSID", "SIDCC", "__SECURE-1PSIDCC",
}


def _jar(auth: dict):
    from yt_dlp.cookies import extract_cookies_from_browser, YoutubeDLCookieJar

    mode = (auth or {}).get("mode")
    if mode == "browser":
        return extract_cookies_from_browser(auth.get("browser") or "firefox")
    if mode == "file":
        path = auth.get("cookie_file") or ""
        jar = YoutubeDLCookieJar(path)
        if path and os.path.isfile(path):
            jar.load(ignore_discard=True, ignore_expires=True)
        return jar
    return None


def _logged_in(jar) -> bool:
    if jar is None:
        return False
    for cookie in jar:
        domain = (cookie.domain or "").lower()
        if "youtube.com" not in domain and "google.com" not in domain:
            continue
        if (cookie.name or "").upper() in _LOGIN_NAMES and cookie.value:
            return True
    return False


def check_login(auth: dict) -> tuple[bool, str]:
    mode = (auth or {}).get("mode") or "none"
    browser = auth.get("browser") or "firefox"
    if mode == "none":
        return True, "Без входа. Обычные видео доступны, видео 18+ — нет."
    try:
        jar = _jar(auth)
    except Exception as exc:
        text = str(exc).lower()
        if browser in {"chrome", "edge", "brave", "opera"} and any(word in text for word in ("decrypt", "cookie", "key", "app-bound")):
            return False, "Вход из этого браузера в Windows часто не читается. Выберите Firefox или файл cookies.txt."
        return False, f"Не удалось прочитать вход: {exc}"
    if not _logged_in(jar):
        if mode == "file":
            return False, "В файле cookies.txt нет входа в YouTube. Сохраните его заново."
        return False, f"В {browser} не найден вход в YouTube. Откройте youtube.com в этом браузере и войдите."
    if browser in {"chrome", "edge", "brave", "opera"}:
        return True, f"Куки {browser} прочитались. Если видео 18+ всё равно не откроются, перейдите на Firefox или cookies.txt."
    if mode == "file":
        return True, "Файл cookies.txt подходит. Когда проверка покраснеет, сохраните файл заново."
    return True, f"Вход из {browser} работает. Видео 18+ будут доступны."


def describe_auth(auth: dict) -> str:
    auth = auth or {}
    mode = auth.get("mode") or "none"
    if mode == "none":
        return "без входа"
    if auth.get("last_ok") is False:
        return "вход не работает"
    if mode == "file":
        return "через cookies.txt"
    browser = (auth.get("browser") or "firefox").capitalize()
    return f"через вход {browser}"


def pill(auth: dict) -> tuple[str, str]:
    """Текст плашки и цвет: green, gray, red."""
    auth = auth or {}
    mode = auth.get("mode") or "none"
    if mode == "none":
        return "Без входа", "gray"
    browser = (auth.get("browser") or "firefox").capitalize() if mode == "browser" else "cookies.txt"
    if auth.get("last_ok") is False:
        return "Вход не работает", "red"
    if auth.get("last_ok") is True:
        if mode == "file":
            return "Вход: cookies.txt · видео 18+ доступны", "green"
        return f"Вход: {browser} · видео 18+ доступны", "green"
    if mode == "file":
        return "Вход: cookies.txt · не проверен", "gray"
    return f"Вход: {browser} · не проверен", "gray"
