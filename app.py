"""PICKDAY: owner-authorized Instagram comment importer + lottery UI.

Uses Instagram API with Instagram Login. No scraping of arbitrary posts.
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

BASE = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
except ImportError:
    pass

APP_ID = os.getenv("INSTAGRAM_APP_ID", "").strip()
APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET", "").strip()
REDIRECT_URI = os.getenv("INSTAGRAM_REDIRECT_URI", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SESSION_KEY = os.getenv("FLASK_SECRET_KEY", "")
DB_PATH = os.getenv("DATABASE_PATH", str(BASE / "pickday.sqlite3"))
GRAPH_VER = os.getenv("GRAPH_API_VERSION", "v25.0")
GRAPH_ROOT = f"https://graph.instagram.com/{GRAPH_VER}"
MAX_MEDIA_PAGES = 100  # 100 * 100 = at most 10,000 owned posts
MAX_COMMENT_PAGES = 500  # 500 * 100 = at most 50,000 top-level comments

if not re.fullmatch(r"v\d+\.0", GRAPH_VER):
    raise RuntimeError("GRAPH_API_VERSION must look like v25.0")
if not SESSION_KEY or len(SESSION_KEY) < 24 or SESSION_KEY.startswith("REPLACE_WITH"):
    raise RuntimeError("Set a random FLASK_SECRET_KEY (at least 24 characters) in .env")
if not ADMIN_PASSWORD or len(ADMIN_PASSWORD) < 12 or ADMIN_PASSWORD.startswith("CHANGE_THIS"):
    raise RuntimeError("Set a unique ADMIN_PASSWORD (at least 12 characters) in .env")
if not APP_ID or not APP_SECRET or not REDIRECT_URI:
    # The app can still start so the UI/demo is accessible before Meta setup.
    print("PICKDAY: Instagram keys are not configured yet; Meta connection will be unavailable.")

app = Flask(__name__)
app.secret_key = SESSION_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
    MAX_CONTENT_LENGTH=16 * 1024,
)

# Encrypted-at-rest tokens, derived from stable secrets. Keep these private and stable.
fernet_seed = (SESSION_KEY + "::" + (APP_SECRET or "not-yet-configured")).encode("utf-8")
cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(fernet_seed).digest()))
POST_RE = re.compile(r"^/(?:p|reel|tv)/([A-Za-z0-9_-]{5,30})/?$")


def db_connection():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def create_db():
    with db_connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            token_encrypted TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            connected_at INTEGER NOT NULL
        )""")


create_db()


def graph_error(payload):
    """Never return request URLs or tokens to the browser."""
    if isinstance(payload, dict):
        error = payload.get("error", {})
        if isinstance(error, dict):
            msg = str(error.get("message", ""))
            return msg[:260] if msg else "Meta API 오류가 발생했어요."
        if "error_message" in payload:
            return str(payload["error_message"])[:260]
    return "Meta API 요청에 실패했어요."


class ApiProblem(Exception):
    def __init__(self, msg, status=400):
        self.msg, self.status = msg, status
        super().__init__(msg)


def api_json(resp):
    try:
        data = resp.json()
    except ValueError:
        raise ApiProblem("Meta API가 JSON 응답을 반환하지 않았어요.", 502)
    if not resp.ok or data.get("error") or data.get("error_type"):
        raise ApiProblem(graph_error(data), 502)
    return data


def api_get(url, token, params=None):
    try:
        resp = requests.get(
            url,
            params=params or {},
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
            timeout=20,
        )
    except requests.RequestException:
        raise ApiProblem("Meta API에 연결하지 못했어요. 네트워크 상태를 확인해 주세요.", 502)
    return api_json(resp)


def read_account():
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM account WHERE id=1").fetchone()
    return dict(row) if row else None


def save_account(user_id, username, token, expires_in):
    expiry = int(time.time()) + int(expires_in or 5184000)
    encrypted = cipher.encrypt(token.encode()).decode()
    with db_connection() as conn:
        conn.execute("""INSERT INTO account(id,user_id,username,token_encrypted,expires_at,connected_at)
            VALUES(1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            user_id=excluded.user_id, username=excluded.username,
            token_encrypted=excluded.token_encrypted, expires_at=excluded.expires_at,
            connected_at=excluded.connected_at""",
            (str(user_id), str(username), encrypted, expiry, int(time.time())))


def access_token():
    row = read_account()
    if not row:
        raise ApiProblem("먼저 인스타 계정을 연결해 주세요.", 400)
    try:
        token = cipher.decrypt(row["token_encrypted"].encode()).decode()
    except InvalidToken:
        raise ApiProblem("토큰 복호화에 실패했어요. 계정을 다시 연결해 주세요.", 400)
    # Refresh long-lived tokens only when needed. Instagram allows it after 24h.
    if row["expires_at"] < time.time() + 14 * 86400:
        try:
            response = requests.get(
                "https://graph.instagram.com/refresh_access_token",
                params={"grant_type": "ig_refresh_token", "access_token": token},
                timeout=20,
            )
            data = api_json(response)
            token = data["access_token"]
            save_account(row["user_id"], row["username"], token, data.get("expires_in", 5184000))
        except (ApiProblem, KeyError, requests.RequestException):
            if row["expires_at"] < time.time():
                raise ApiProblem("인스타 로그인 유효기간이 끝났어요. 다시 연결해 주세요.", 401)
    return token


def check_csrf():
    proposed = request.headers.get("X-CSRF-Token", "")
    existing = session.get("csrf", "")
    if not proposed or not existing or not hmac.compare_digest(proposed, existing):
        raise ApiProblem("보안 검증에 실패했어요. 페이지를 새로고침해 주세요.", 403)
    # Block cross-origin form POSTs, even when a browser is configured unusually.
    origin = request.headers.get("Origin")
    if origin and urlparse(origin).netloc.lower() != request.host.lower():
        raise ApiProblem("허용되지 않은 요청 출처입니다.", 403)


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if session.get("admin") is not True:
            if request.path.startswith("/api/"):
                raise ApiProblem("관리자 로그인 후 이용해 주세요.", 401)
            return redirect(url_for("index"))
        return fn(*args, **kwargs)
    return wrapped


@app.errorhandler(ApiProblem)
def handle_api_error(ex):
    return jsonify({"ok": False, "error": ex.msg}), ex.status


@app.after_request
def headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
def index():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return render_template("index.html")


@app.get("/api/status")
def status():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    authed = session.get("admin") is True
    row = read_account() if authed else None
    return jsonify({
        "ok": True,
        "authenticated": authed,
        "csrf": session["csrf"],
        "instagram_ready": all([APP_ID, APP_SECRET, REDIRECT_URI]),
        "connected": bool(row),
        "username": row["username"] if row else None,
        "expires_at": row["expires_at"] if row else None,
    })


@app.post("/api/login")
def login():
    check_csrf()
    value = (request.get_json(silent=True) or {}).get("password", "")
    if not isinstance(value, str) or not hmac.compare_digest(value, ADMIN_PASSWORD):
        raise ApiProblem("관리자 비밀번호가 일치하지 않아요.", 401)
    csrf = session.get("csrf")
    session.clear()
    session["admin"] = True
    session["csrf"] = csrf or secrets.token_urlsafe(32)
    return jsonify({"ok": True})


@app.post("/api/logout")
@admin_required
def logout():
    check_csrf()
    session.clear()
    return jsonify({"ok": True})


@app.get("/auth/connect")
@admin_required
def auth_connect():
    if not all([APP_ID, APP_SECRET, REDIRECT_URI]):
        raise ApiProblem(".env의 Instagram App ID, Secret, Redirect URI를 먼저 설정해 주세요.", 400)
    session["oauth_state"] = secrets.token_urlsafe(32)
    from urllib.parse import urlencode
    url = "https://www.instagram.com/oauth/authorize?" + urlencode({
        "client_id": APP_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "instagram_business_basic,instagram_business_manage_comments",
        "state": session["oauth_state"],
        "enable_fb_login": "0",
        "force_reauth": "0",
    })
    return redirect(url)


@app.get("/auth/callback")
@admin_required
def auth_callback():
    if request.args.get("error"):
        return redirect("/?ig_error=access_denied")
    supplied = request.args.get("state", "")
    expected = session.pop("oauth_state", "")
    if not supplied or not expected or not hmac.compare_digest(supplied, expected):
        return redirect("/?ig_error=invalid_state")
    code = request.args.get("code", "").replace("#_", "")
    if not code:
        return redirect("/?ig_error=no_code")
    try:
        response = requests.post("https://api.instagram.com/oauth/access_token", data={
            "client_id": APP_ID,
            "client_secret": APP_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code": code,
        }, timeout=20)
        short = api_json(response)["access_token"]
        long_data = api_json(requests.get("https://graph.instagram.com/access_token", params={
            "grant_type": "ig_exchange_token",
            "client_secret": APP_SECRET,
            "access_token": short,
        }, timeout=20))
        long_token = long_data["access_token"]
        profile = api_get(GRAPH_ROOT + "/me", long_token, {"fields": "id,username,account_type"})
        if not profile.get("id") or not profile.get("username"):
            raise ApiProblem("인스타 프로 계정을 확인하지 못했어요.", 400)
        save_account(profile["id"], profile["username"], long_token, long_data.get("expires_in", 5184000))
        return redirect("/?ig_connected=1")
    except (ApiProblem, requests.RequestException, KeyError, ValueError) as ex:
        app.logger.warning("Instagram OAuth failed: %s", type(ex).__name__)
        return redirect("/?ig_error=oauth_failed")


@app.post("/api/disconnect")
@admin_required
def disconnect():
    check_csrf()
    with db_connection() as conn:
        conn.execute("DELETE FROM account WHERE id=1")
    return jsonify({"ok": True})


def shortcode_for_url(value):
    try:
        parsed = urlparse(str(value).strip())
        if parsed.scheme != "https" or parsed.netloc.lower() not in {"instagram.com", "www.instagram.com"}:
            return None
        match = POST_RE.fullmatch(parsed.path)
        return match.group(1) if match else None
    except ValueError:
        return None


def get_owned_post(shortcode, token):
    after = None
    for page in range(MAX_MEDIA_PAGES):
        params = {"fields": "id,permalink,timestamp,comments_count,media_type", "limit": 100}
        if after:
            params["after"] = after
        data = api_get(GRAPH_ROOT + "/me/media", token, params)
        for media in data.get("data", []):
            if shortcode_for_url(media.get("permalink", "")) == shortcode:
                return media
        nxt = (data.get("paging") or {}).get("cursors", {}).get("after")
        if not nxt or nxt == after:
            break
        after = nxt
    raise ApiProblem("연결한 계정이 직접 올린 게시물 중 해당 링크를 찾지 못했어요. 계정·링크를 확인해 주세요.", 404)


def list_comments(media_id, token):
    if not re.fullmatch(r"\d{5,30}", str(media_id)):
        raise ApiProblem("게시물 ID 형식이 올바르지 않아요.", 502)
    comments = []
    after = None
    seen = set()
    for _ in range(MAX_COMMENT_PAGES):
        params = {"fields": "id,text,username,timestamp", "limit": 100}
        if after:
            params["after"] = after
        data = api_get(GRAPH_ROOT + "/" + str(media_id) + "/comments", token, params)
        for item in data.get("data", []):
            if not isinstance(item, dict):
                continue
            comment_id = str(item.get("id", ""))
            if not comment_id or comment_id in seen:
                continue
            seen.add(comment_id)
            comments.append({
                "id": comment_id,
                "username": str(item.get("username", "")),
                "text": str(item.get("text", "")),
                "timestamp": str(item.get("timestamp", "")),
            })
        nxt = (data.get("paging") or {}).get("cursors", {}).get("after")
        if not nxt or nxt == after:
            return comments
        after = nxt
    raise ApiProblem("댓글이 50,000개를 넘어 전체 수집을 보장할 수 없어서 추첨을 중단했어요.", 422)


@app.post("/api/import")
@admin_required
def import_comments():
    check_csrf()
    payload = request.get_json(silent=True) or {}
    value = payload.get("url", "")
    shortcode = shortcode_for_url(value)
    if not shortcode:
        raise ApiProblem("https://www.instagram.com/p/... 또는 /reel/... 주소를 입력해 주세요.")
    token = access_token()
    media = get_owned_post(shortcode, token)
    comments = list_comments(media["id"], token)
    missing_username = sum(not re.fullmatch(r"[a-zA-Z0-9._]{1,30}", c["username"]) for c in comments)
    included = [c for c in comments if re.fullmatch(r"[a-zA-Z0-9._]{1,30}", c["username"])]
    unique = len({c["username"].lower() for c in included})
    snapshot_input = "\n".join(sorted(c["id"] + ":" + c["username"].lower() + ":" + c["text"] for c in comments))
    snapshot_hash = hashlib.sha256(snapshot_input.encode()).hexdigest()
    return jsonify({
        "ok": True,
        "post": {"id": media["id"], "permalink": media.get("permalink"), "timestamp": media.get("timestamp")},
        "comments": comments,
        "stats": {"total": len(comments), "accounts": unique, "missing_username": missing_username},
        "snapshot_sha256": snapshot_hash,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "scope": "게시물 최상위 댓글(대댓글 제외)",
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
