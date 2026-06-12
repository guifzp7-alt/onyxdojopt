from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SITE_DIR = ROOT.parent
FRONTEND_DIR = ROOT / "frontend"
ASSETS_DIR = ROOT.parent / "assets"
DB_PATH = ROOT / "database" / "feedbacks.sqlite3"

ADMIN_USER = os.getenv("ONYX_ADMIN_USER", "onyxdojo2026")
ADMIN_PASSWORD = os.getenv("ONYX_ADMIN_PASSWORD", "admin200")
SESSION_SECRET = os.getenv("ONYX_SESSION_SECRET", "dev-secret-change-me")
ALLOWED_TYPES = {"Aluno", "Pai", "Mãe", "Responsável"}
ALLOWED_STATUS = {"Pendente", "Aprovado", "Rejeitado"}
RATE_LIMIT_WINDOW = 60 * 10
RATE_LIMIT_MAX = 3
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    if USE_SUPABASE:
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                user_type TEXT NOT NULL,
                team_time TEXT,
                rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
                comment TEXT NOT NULL,
                publish_authorized INTEGER NOT NULL DEFAULT 0,
                submitted_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pendente'
                    CHECK (status IN ('Pendente', 'Aprovado', 'Rejeitado'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS submission_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_hash TEXT NOT NULL,
                submitted_at INTEGER NOT NULL
            )
            """
        )


def json_response(handler: SimpleHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length > 20_000:
        raise ValueError("Payload muito grande.")
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8") or "{}")


def clean_text(value: Any, max_length: int) -> str:
    text = str(value or "").strip()
    text = " ".join(text.split())
    return html.escape(text[:max_length], quote=True)


def public_feedback(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "user_type": row["user_type"],
        "team_time": row["team_time"],
        "rating": row["rating"],
        "comment": row["comment"],
        "submitted_at": row["submitted_at"],
    }


def admin_feedback(row: sqlite3.Row) -> dict[str, Any]:
    data = public_feedback(row)
    data["status"] = row["status"]
    data["publish_authorized"] = bool(row["publish_authorized"])
    return data


def supabase_request(method: str, table: str, query: str = "", payload: Any | None = None) -> Any:
    url = f"{SUPABASE_URL}/rest/v1/{table}{query}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, method=method)
    request.add_header("apikey", SUPABASE_SERVICE_ROLE_KEY)
    request.add_header("Authorization", f"Bearer {SUPABASE_SERVICE_ROLE_KEY}")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    request.add_header("Prefer", "return=representation")

    with urlopen(request, timeout=12) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else None


def list_feedbacks(status: str = "Todos", public_only: bool = False) -> list[dict[str, Any]]:
    if USE_SUPABASE:
        filters = ["order=submitted_at.desc"]
        if public_only:
            filters.extend(["status=eq.Aprovado", "publish_authorized=eq.true"])
        elif status in ALLOWED_STATUS:
            filters.append(f"status=eq.{quote(status)}")
        rows = supabase_request("GET", "feedbacks", "?" + "&".join(filters)) or []
        return [dict(row) for row in rows]

    params: tuple[Any, ...] = ()
    sql = "SELECT * FROM feedbacks"
    if public_only:
        sql += " WHERE status = 'Aprovado' AND publish_authorized = 1"
    elif status in ALLOWED_STATUS:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY submitted_at DESC"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def create_feedback_record(payload: dict[str, Any]) -> None:
    if USE_SUPABASE:
        supabase_request("POST", "feedbacks", payload=payload)
        return

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO feedbacks
            (name, user_type, team_time, rating, comment, publish_authorized, submitted_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["name"],
                payload["user_type"],
                payload["team_time"],
                payload["rating"],
                payload["comment"],
                1 if payload["publish_authorized"] else 0,
                payload["submitted_at"],
                payload["status"],
            ),
        )


def update_feedback_record(feedback_id: int, payload: dict[str, Any]) -> bool:
    if USE_SUPABASE:
        rows = supabase_request("PATCH", "feedbacks", f"?id=eq.{feedback_id}", payload=payload) or []
        return bool(rows)

    fields = []
    values = []
    for key, value in payload.items():
        fields.append(f"{key} = ?")
        if key == "publish_authorized":
            values.append(1 if value else 0)
        else:
            values.append(value)
    values.append(feedback_id)
    with connect() as conn:
        cursor = conn.execute(f"UPDATE feedbacks SET {', '.join(fields)} WHERE id = ?", tuple(values))
        return cursor.rowcount > 0


def delete_feedback_record(feedback_id: int) -> bool:
    if USE_SUPABASE:
        rows = supabase_request("DELETE", "feedbacks", f"?id=eq.{feedback_id}") or []
        return bool(rows)

    with connect() as conn:
        cursor = conn.execute("DELETE FROM feedbacks WHERE id = ?", (feedback_id,))
        return cursor.rowcount > 0


def sign_session(value: str) -> str:
    signature = hmac.new(SESSION_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{signature}"


def verify_session(token: str) -> bool:
    try:
        value, signature = token.rsplit(".", 1)
    except ValueError:
        return False
    expected = hmac.new(SESSION_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        username, issued_at = value.split(":", 1)
        return username == ADMIN_USER and time.time() - int(issued_at) < 60 * 60 * 8
    except ValueError:
        return False


def get_session_token(handler: SimpleHTTPRequestHandler) -> str:
    cookie = SimpleCookie(handler.headers.get("Cookie", ""))
    morsel = cookie.get("onyx_session")
    return morsel.value if morsel else ""


def require_auth(handler: SimpleHTTPRequestHandler) -> bool:
    if verify_session(get_session_token(handler)):
        return True
    json_response(handler, HTTPStatus.UNAUTHORIZED, {"error": "Login necessario."})
    return False


def ip_hash(handler: SimpleHTTPRequestHandler) -> str:
    forwarded = handler.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",")[0].strip() or handler.client_address[0]
    return hashlib.sha256(f"{ip}:{SESSION_SECRET}".encode()).hexdigest()


def rate_limited(handler: SimpleHTTPRequestHandler) -> bool:
    now = int(time.time())
    limit_after = now - RATE_LIMIT_WINDOW
    hashed_ip = ip_hash(handler)

    if USE_SUPABASE:
        supabase_request("DELETE", "submission_log", f"?submitted_at=lt.{limit_after}")
        rows = supabase_request(
            "GET",
            "submission_log",
            f"?ip_hash=eq.{hashed_ip}&submitted_at=gte.{limit_after}&select=id",
        ) or []
        if len(rows) >= RATE_LIMIT_MAX:
            return True
        supabase_request("POST", "submission_log", payload={"ip_hash": hashed_ip, "submitted_at": now})
        return False

    with connect() as conn:
        conn.execute("DELETE FROM submission_log WHERE submitted_at < ?", (limit_after,))
        count = conn.execute(
            "SELECT COUNT(*) FROM submission_log WHERE ip_hash = ? AND submitted_at >= ?",
            (hashed_ip, limit_after),
        ).fetchone()[0]
        if count >= RATE_LIMIT_MAX:
            return True
        conn.execute(
            "INSERT INTO submission_log (ip_hash, submitted_at) VALUES (?, ?)",
            (hashed_ip, now),
        )
    return False


class OnyxFeedbackHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        parsed_path = urlparse(path).path
        if parsed_path.startswith("/assets/"):
            return str(ASSETS_DIR / parsed_path.removeprefix("/assets/"))
        if parsed_path.startswith("/feedback-portal/"):
            return str(PUBLIC_SITE_DIR / parsed_path.removeprefix("/"))
        if parsed_path == "/site-publico" or parsed_path == "/site-publico/":
            return str(PUBLIC_SITE_DIR / "index.html")
        if parsed_path.startswith("/site-publico/"):
            return str(PUBLIC_SITE_DIR / parsed_path.removeprefix("/site-publico/"))
        requested = parsed_path.lstrip("/") or "index.html"
        return str(FRONTEND_DIR / requested)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/site-publico":
            self.send_response(HTTPStatus.MOVED_PERMANENTLY)
            self.send_header("Location", "/site-publico/")
            self.end_headers()
            return
        if path == "/api/public/feedbacks":
            return self.list_public_feedbacks()
        if path == "/api/admin/feedbacks":
            return self.list_admin_feedbacks()
        return super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        routes = {
            "/api/feedbacks": self.create_feedback,
            "/api/admin/login": self.login,
            "/api/admin/logout": self.logout,
        }
        action = routes.get(path)
        if action:
            return action()
        json_response(self, HTTPStatus.NOT_FOUND, {"error": "Rota nao encontrada."})

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/admin/feedbacks/"):
            return self.update_feedback(path)
        json_response(self, HTTPStatus.NOT_FOUND, {"error": "Rota nao encontrada."})

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/admin/feedbacks/"):
            return self.delete_feedback(path)
        json_response(self, HTTPStatus.NOT_FOUND, {"error": "Rota nao encontrada."})

    def create_feedback(self) -> None:
        try:
            data = read_json(self)
            honeypot = str(data.get("website", "")).strip()
            if honeypot:
                return json_response(self, HTTPStatus.OK, {"message": "Feedback recebido."})
            if rate_limited(self):
                return json_response(self, HTTPStatus.TOO_MANY_REQUESTS, {"error": "Muitos envios. Tente novamente mais tarde."})

            name = clean_text(data.get("name"), 120)
            user_type = clean_text(data.get("user_type"), 30)
            team_time = clean_text(data.get("team_time"), 80)
            comment = clean_text(data.get("comment"), 1200)
            rating = int(data.get("rating", 0))
            publish_authorized = bool(data.get("publish_authorized"))

            if len(name) < 3:
                raise ValueError("Informe o nome completo.")
            if user_type not in ALLOWED_TYPES:
                raise ValueError("Selecione um tipo de usuario valido.")
            if rating < 1 or rating > 5:
                raise ValueError("Selecione uma nota de 1 a 5 estrelas.")
            if len(comment) < 10:
                raise ValueError("Escreva um comentario com pelo menos 10 caracteres.")

            create_feedback_record(
                {
                    "name": name,
                    "user_type": user_type,
                    "team_time": team_time,
                    "rating": rating,
                    "comment": comment,
                    "publish_authorized": publish_authorized,
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "status": "Pendente",
                }
            )
            json_response(
                self,
                HTTPStatus.CREATED,
                {"message": "Obrigado pelo seu feedback! Sua avaliação foi recebida e será analisada antes da publicação."},
            )
        except (ValueError, json.JSONDecodeError) as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def list_public_feedbacks(self) -> None:
        rows = list_feedbacks(public_only=True)
        ratings = [row["rating"] for row in rows]
        average = round(sum(ratings) / len(ratings), 1) if ratings else 0
        json_response(
            self,
            HTTPStatus.OK,
            {
                "average": average,
                "total": len(rows),
                "feedbacks": [public_feedback(row) for row in rows],
            },
        )

    def list_admin_feedbacks(self) -> None:
        if not require_auth(self):
            return
        query = parse_qs(urlparse(self.path).query)
        status = query.get("status", ["Todos"])[0]
        rows = list_feedbacks(status=status)
        json_response(self, HTTPStatus.OK, {"feedbacks": [admin_feedback(row) for row in rows]})

    def login(self) -> None:
        try:
            data = read_json(self)
            username = str(data.get("username", ""))
            password = str(data.get("password", ""))
            valid_user = hmac.compare_digest(username, ADMIN_USER)
            valid_password = hmac.compare_digest(password, ADMIN_PASSWORD)
            if not (valid_user and valid_password):
                return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Usuario ou senha invalidos."})
            session = sign_session(f"{ADMIN_USER}:{int(time.time())}")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie", f"onyx_session={session}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800")
            self.end_headers()
            self.wfile.write(json.dumps({"message": "Login realizado."}).encode("utf-8"))
        except json.JSONDecodeError:
            json_response(self, HTTPStatus.BAD_REQUEST, {"error": "JSON invalido."})

    def logout(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", "onyx_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
        self.end_headers()
        self.wfile.write(json.dumps({"message": "Logout realizado."}).encode("utf-8"))

    def update_feedback(self, path: str) -> None:
        if not require_auth(self):
            return
        try:
            feedback_id = int(path.rstrip("/").split("/")[-1])
            data = read_json(self)
            update_data: dict[str, Any] = {}

            if "name" in data:
                update_data["name"] = clean_text(data["name"], 120)
            if "user_type" in data:
                user_type = clean_text(data["user_type"], 30)
                if user_type not in ALLOWED_TYPES:
                    raise ValueError("Tipo de usuario invalido.")
                update_data["user_type"] = user_type
            if "team_time" in data:
                update_data["team_time"] = clean_text(data["team_time"], 80)
            if "rating" in data:
                rating = int(data["rating"])
                if rating < 1 or rating > 5:
                    raise ValueError("Nota invalida.")
                update_data["rating"] = rating
            if "comment" in data:
                update_data["comment"] = clean_text(data["comment"], 1200)
            if "publish_authorized" in data:
                update_data["publish_authorized"] = bool(data["publish_authorized"])
            if "status" in data:
                status = clean_text(data["status"], 20)
                if status not in ALLOWED_STATUS:
                    raise ValueError("Status invalido.")
                update_data["status"] = status

            if not update_data:
                raise ValueError("Nenhum campo para atualizar.")

            if not update_feedback_record(feedback_id, update_data):
                return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Feedback nao encontrado."})
            json_response(self, HTTPStatus.OK, {"message": "Feedback atualizado."})
        except (ValueError, json.JSONDecodeError) as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def delete_feedback(self, path: str) -> None:
        if not require_auth(self):
            return
        try:
            feedback_id = int(path.rstrip("/").split("/")[-1])
        except ValueError:
            return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "ID invalido."})
        if not delete_feedback_record(feedback_id):
            return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Feedback nao encontrado."})
        json_response(self, HTTPStatus.OK, {"message": "Feedback excluido."})


def main() -> None:
    init_db()
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "localhost")
    server = ThreadingHTTPServer((host, port), OnyxFeedbackHandler)
    print(f"Portal de Feedback ONYX DOJO em http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
