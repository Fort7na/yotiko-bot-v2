import html
import os
import secrets
import sqlite3
import hmac
from pathlib import Path
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

CLIENT_ID = os.getenv("DASHBOARD_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("DASHBOARD_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv(
    "DASHBOARD_REDIRECT_URI",
    "http://127.0.0.1:8000/auth/callback",
)
SESSION_SECRET = os.getenv("DASHBOARD_SESSION_SECRET", "")
ALLOWED_USER_IDS = {
    item.strip()
    for item in os.getenv("DASHBOARD_ALLOWED_USER_IDS", "").split(",")
    if item.strip()
}
DB_PATH = BASE_DIR / "yotiko.sqlite3"

if not CLIENT_ID or not CLIENT_SECRET or not SESSION_SECRET:
    raise RuntimeError(
        "В .env не заполнены Client ID, Client Secret или Session Secret."
    )

app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="yotiko_dashboard_session",
    max_age=8 * 60 * 60,
    same_site="lax",
    https_only=False,  # Для локальной проверки; на хостинге включим HTTPS.
)


def page(title: str, content: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{ margin:0; background:#17181d; color:#f2f2f4;
           font:16px Arial,sans-serif; }}
    main {{ max-width:900px; margin:48px auto; padding:24px; }}
    .card {{ background:#24252c; border:1px solid #383943;
             border-radius:16px; padding:24px; margin:16px 0; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
             gap:14px; }}
    .number {{ font-size:30px; font-weight:bold; margin-top:12px; }}
    a.button {{ display:inline-block; background:#5865f2; color:white;
                padding:12px 18px; border-radius:9px; text-decoration:none; }}
    .muted {{ color:#b7b8c2; }}
  </style>
</head>
<body><main>{content}</main></body>
</html>"""
    )


def get_counts() -> tuple[int, int, int]:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Не найдена база данных: {DB_PATH.name}"
        )

    uri = DB_PATH.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

        invites = 0
        successful = 0
        unsuccessful = 0

        if "invite_attributions" in tables:
            invites = connection.execute(
                "SELECT COUNT(*) FROM invite_attributions"
            ).fetchone()[0]

        if "verification_actions" in tables:
            successful = connection.execute(
                "SELECT COUNT(*) FROM verification_actions "
                "WHERE outcome = 'успешно'"
            ).fetchone()[0]
            unsuccessful = connection.execute(
                "SELECT COUNT(*) FROM verification_actions "
                "WHERE outcome IN ('не прошёл верификацию', 'невериф')"
            ).fetchone()[0]

    return invites, successful, unsuccessful


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    if request.session.get("user_id") in ALLOWED_USER_IDS:
        return RedirectResponse("/dashboard", status_code=303)

    return page(
        "Панель Yotiko",
        """
        <section class="card">
          <h1>Панель управления Yotiko</h1>
          <p class="muted">Войди через Discord, чтобы открыть панель.</p>
          <a class="button" href="/login">Войти через Discord</a>
        </section>
        """,
    )


@app.get("/login")
async def login(request: Request):
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state

    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "identify",
        "state": state,
    }
    return RedirectResponse(
        "https://discord.com/oauth2/authorize?" + urlencode(params),
        status_code=302,
    )


@app.get("/auth/callback", response_class=HTMLResponse)
async def auth_callback(request: Request, code: str = "", state: str = ""):
    expected_state = request.session.pop("oauth_state", "")

    if not code or not expected_state or not hmac.compare_digest(
        state, expected_state
    ):
        return page("Ошибка входа", "<h1>Не удалось подтвердить вход.</h1>")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            token_response = await client.post(
                "https://discord.com/api/v10/oauth2/token",
                data={
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token_response.raise_for_status()
            access_token = token_response.json()["access_token"]

            user_response = await client.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user_response.raise_for_status()
            user = user_response.json()

    except (httpx.HTTPError, KeyError, ValueError):
        return page(
            "Ошибка входа",
            "<h1>Discord не завершил вход. Проверь настройки OAuth2 и попробуй ещё раз.</h1>",
        )

    user_id = str(user.get("id", ""))

    if user_id not in ALLOWED_USER_IDS:
        request.session.clear()
        return page(
            "Нет доступа",
            "<h1>У этого Discord-аккаунта нет доступа к панели.</h1>",
        )

    request.session.clear()
    request.session["user_id"] = user_id
    request.session["username"] = user.get("global_name") or user.get("username", "Администратор")

    return RedirectResponse("/dashboard", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if request.session.get("user_id") not in ALLOWED_USER_IDS:
        return RedirectResponse("/", status_code=303)

    username = html.escape(request.session.get("username", "Администратор"))

    try:
        invites, successful, unsuccessful = get_counts()
    except (FileNotFoundError, sqlite3.Error) as error:
        return page(
            "Панель Yotiko",
            f"""
            <section class="card">
              <h1>Здравствуйте, {username}</h1>
              <p>Не удалось прочитать базу: {html.escape(str(error))}</p>
              <a href="/logout">Выйти</a>
            </section>
            """,
        )

    return page(
        "Панель Yotiko",
        f"""
        <section class="card">
          <h1>Панель Yotiko</h1>
          <p class="muted">Вы вошли как {username}. Доступ только для разрешённых аккаунтов.</p>
          <a href="/logout">Выйти</a>
        </section>
        <section class="grid">
          <div class="card"><div>Пришло по личным ссылкам</div>
            <div class="number">{invites}</div></div>
          <div class="card"><div>Успешные верификации</div>
            <div class="number">{successful}</div></div>
          <div class="card"><div>Не прошли верификацию</div>
            <div class="number">{unsuccessful}</div></div>
        </section>
        <section class="card">
          <h2>Настройки</h2>
          <p class="muted">Пока панель показывает сводку. Раздел изменения настроек добавим отдельно после проверки входа.</p>
        </section>
        """,
    )


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
