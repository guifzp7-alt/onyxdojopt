from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen


ADMIN_USER = os.getenv("ONYX_ADMIN_USER", "onyxdojo2026")
ADMIN_PASSWORD = os.getenv("ONYX_ADMIN_PASSWORD", "admin200")
SESSION_SECRET = os.getenv("ONYX_SESSION_SECRET", "change-this-secret")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

ALLOWED_TYPES = {"Aluno", "Pai", "Mãe", "Responsável"}
ALLOWED_STATUS = {"Pendente", "Aprovado", "Rejeitado"}
RATE_LIMIT_WINDOW = 60 * 10
RATE_LIMIT_MAX = 3


def supabase_request(method: str, table: str, query: str = "", payload: Any | None = None) -> Any:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Supabase nao configurado.")

    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(f"{SUPABASE_URL}/rest/v1/{table}{query}", data=body, method=method)
    request.add_header("apikey", SUPABASE_SERVICE_ROLE_KEY)
    request.add_header("Authorization", f"Bearer {SUPABASE_SERVICE_ROLE_KEY}")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    request.add_header("Prefer", "return=representation")

    with urlopen(request, timeout=12) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else None


def clean_text(value: Any, max_length: int) -> str:
    text = str(value or "").strip()
    text = " ".join(text.split())
    return html.escape(text[:max_length], quote=True)


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length > 20_000:
        raise ValueError("Payload muito grande.")
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8") or "{}")


def public_feedback(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "user_type": row["user_type"],
        "team_time": row.get("team_time"),
        "rating": row["rating"],
        "comment": row["comment"],
        "submitted_at": row["submitted_at"],
    }


def admin_feedback(row: dict[str, Any]) -> dict[str, Any]:
    data = public_feedback(row)
    data["status"] = row["status"]
    data["publish_authorized"] = bool(row["publish_authorized"])
    return data


def sign_session(value: str) -> str:
    signature = hmac.new(SESSION_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{signature}"


def verify_session(token: str) -> bool:
    try:
        value, signature = token.rsplit(".", 1)
        username, issued_at = value.split(":", 1)
    except ValueError:
        return False

    expected = hmac.new(SESSION_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()
    return (
        hmac.compare_digest(signature, expected)
        and username == ADMIN_USER
        and time.time() - int(issued_at) < 60 * 60 * 8
    )


def ip_hash(handler: BaseHTTPRequestHandler) -> str:
    forwarded = handler.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",")[0].strip() or handler.client_address[0]
    return hashlib.sha256(f"{ip}:{SESSION_SECRET}".encode()).hexdigest()


def rate_limited(handler: BaseHTTPRequestHandler) -> bool:
    now = int(time.time())
    limit_after = now - RATE_LIMIT_WINDOW
    hashed_ip = ip_hash(handler)
    supabase_request("DELETE", "submission_log", f"?submitted_at=lt.{limit_after}")
    rows = supabase_request("GET", "submission_log", f"?ip_hash=eq.{hashed_ip}&submitted_at=gte.{limit_after}&select=id") or []
    if len(rows) >= RATE_LIMIT_MAX:
        return True
    supabase_request("POST", "submission_log", payload={"ip_hash": hashed_ip, "submitted_at": now})
    return False


class handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: Any, extra_headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/public/feedbacks":
            rows = self.list_feedbacks(public_only=True)
            ratings = [row["rating"] for row in rows]
            average = round(sum(ratings) / len(ratings), 1) if ratings else 0
            return self.send_json(HTTPStatus.OK, {"average": average, "total": len(rows), "feedbacks": [public_feedback(row) for row in rows]})
        if path == "/api/admin/feedbacks":
            if not self.require_auth():
                return
            query = parse_qs(urlparse(self.path).query)
            status = query.get("status", ["Todos"])[0]
            return self.send_json(HTTPStatus.OK, {"feedbacks": [admin_feedback(row) for row in self.list_feedbacks(status=status)]})
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "Rota nao encontrada."})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/feedbacks":
            return self.create_feedback()
        if path == "/api/admin/login":
            return self.login()
        if path == "/api/admin/logout":
            return self.send_json(HTTPStatus.OK, {"message": "Logout realizado."}, {"Set-Cookie": "onyx_session=; HttpOnly; SameSite=Strict; Secure; Path=/; Max-Age=0"})
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "Rota nao encontrada."})

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/admin/feedbacks/"):
            return self.update_feedback(path)
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "Rota nao encontrada."})

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/admin/feedbacks/"):
            return self.delete_feedback(path)
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "Rota nao encontrada."})

    def require_auth(self) -> bool:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("onyx_session")
        if morsel and verify_session(morsel.value):
            return True
        self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Login necessario."})
        return False

    def list_feedbacks(self, status: str = "Todos", public_only: bool = False) -> list[dict[str, Any]]:
        filters = ["order=submitted_at.desc"]
        if public_only:
            filters.extend(["status=eq.Aprovado", "publish_authorized=eq.true"])
        elif status in ALLOWED_STATUS:
            filters.append(f"status=eq.{quote(status)}")
        rows = supabase_request("GET", "feedbacks", "?" + "&".join(filters)) or []
        return [dict(row) for row in rows]

    def create_feedback(self) -> None:
        try:
            data = read_json(self)
            if str(data.get("website", "")).strip():
                return self.send_json(HTTPStatus.OK, {"message": "Feedback recebido."})
            if rate_limited(self):
                return self.send_json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "Muitos envios. Tente novamente mais tarde."})

            name = clean_text(data.get("name"), 120)
            user_type = clean_text(data.get("user_type"), 30)
            team_time = clean_text(data.get("team_time"), 80)
            comment = clean_text(data.get("comment"), 1200)
            rating = int(data.get("rating", 0))

            if len(name) < 3:
                raise ValueError("Informe o nome completo.")
            if user_type not in ALLOWED_TYPES:
                raise ValueError("Selecione um tipo de usuario valido.")
            if rating < 1 or rating > 5:
                raise ValueError("Selecione uma nota de 1 a 5 estrelas.")
            if len(comment) < 10:
                raise ValueError("Escreva um comentario com pelo menos 10 caracteres.")

            supabase_request("POST", "feedbacks", payload={
                "name": name,
                "user_type": user_type,
                "team_time": team_time,
                "rating": rating,
                "comment": comment,
                "publish_authorized": bool(data.get("publish_authorized")),
                "submitted_at": datetime.now(timezone.utc).isoformat(),
                "status": "Pendente",
            })
            self.send_json(HTTPStatus.CREATED, {"message": "Obrigado pelo seu feedback! Sua avaliação foi recebida e será analisada antes da publicação."})
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def login(self) -> None:
        try:
            data = read_json(self)
            valid_user = hmac.compare_digest(str(data.get("username", "")), ADMIN_USER)
            valid_password = hmac.compare_digest(str(data.get("password", "")), ADMIN_PASSWORD)
            if not (valid_user and valid_password):
                return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Usuario ou senha invalidos."})
            session = sign_session(f"{ADMIN_USER}:{int(time.time())}")
            self.send_json(HTTPStatus.OK, {"message": "Login realizado."}, {"Set-Cookie": f"onyx_session={session}; HttpOnly; SameSite=Strict; Secure; Path=/; Max-Age=28800"})
        except json.JSONDecodeError:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "JSON invalido."})

    def update_feedback(self, path: str) -> None:
        if not self.require_auth():
            return
        try:
            feedback_id = int(path.rstrip("/").split("/")[-1])
            data = read_json(self)
            payload: dict[str, Any] = {}
            if "name" in data:
                payload["name"] = clean_text(data["name"], 120)
            if "user_type" in data:
                user_type = clean_text(data["user_type"], 30)
                if user_type not in ALLOWED_TYPES:
                    raise ValueError("Tipo de usuario invalido.")
                payload["user_type"] = user_type
            if "team_time" in data:
                payload["team_time"] = clean_text(data["team_time"], 80)
            if "rating" in data:
                rating = int(data["rating"])
                if rating < 1 or rating > 5:
                    raise ValueError("Nota invalida.")
                payload["rating"] = rating
            if "comment" in data:
                payload["comment"] = clean_text(data["comment"], 1200)
            if "publish_authorized" in data:
                payload["publish_authorized"] = bool(data["publish_authorized"])
            if "status" in data:
                status = clean_text(data["status"], 20)
                if status not in ALLOWED_STATUS:
                    raise ValueError("Status invalido.")
                payload["status"] = status
            if not payload:
                raise ValueError("Nenhum campo para atualizar.")
            rows = supabase_request("PATCH", "feedbacks", f"?id=eq.{feedback_id}", payload=payload) or []
            if not rows:
                return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Feedback nao encontrado."})
            self.send_json(HTTPStatus.OK, {"message": "Feedback atualizado."})
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def delete_feedback(self, path: str) -> None:
        if not self.require_auth():
            return
        try:
            feedback_id = int(path.rstrip("/").split("/")[-1])
        except ValueError:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "ID invalido."})
        rows = supabase_request("DELETE", "feedbacks", f"?id=eq.{feedback_id}") or []
        if not rows:
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Feedback nao encontrado."})
        self.send_json(HTTPStatus.OK, {"message": "Feedback excluido."})
