"""Direct Altegio REST client (no MCP / no AI tokens)."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from env_loader import get_env


class AltegioError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class AltegioClient:
    def __init__(
        self,
        partner_token: str | None = None,
        user_token: str | None = None,
        location_id: int | None = None,
        api_base: str | None = None,
    ) -> None:
        self.partner_token = partner_token or get_env("ALTEGIO_PARTNER_TOKEN")
        self.user_token = user_token or get_env("ALTEGIO_USER_TOKEN")
        self.location_id = int(location_id or get_env("ALTEGIO_LOCATION_ID", "764940"))
        self.api_base = (api_base or get_env("ALTEGIO_API_BASE", "https://api.alteg.io/api/v1")).rstrip("/")
        if not self.partner_token:
            raise AltegioError("ALTEGIO_PARTNER_TOKEN is missing in .env")

    def _headers(self, with_user: bool = True) -> dict[str, str]:
        auth = f"Bearer {self.partner_token}"
        if with_user:
            if not self.user_token:
                raise AltegioError(
                    "ALTEGIO_USER_TOKEN is missing. Run: python scripts/auth_user_token.py"
                )
            auth = f"{auth}, User {self.user_token}"
        partner_id = get_env("ALTEGIO_PARTNER_ID", "2956") or "2956"
        # Cloudflare bans the default Python-urllib User-Agent (Error 1010).
        return {
            "Accept": "application/vnd.api.v2+json",
            "Content-Type": "application/json",
            "Authorization": auth,
            "User-Agent": f"AltegioCohortAnalyzer/1.0 (+partner_id/{partner_id}; local-sync)",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        with_user: bool = True,
        retries: int = 3,
    ) -> Any:
        url = path if path.startswith("http") else f"{self.api_base}/{path.lstrip('/')}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(retries):
            req = urllib.request.Request(url, data=data, headers=self._headers(with_user), method=method)
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    raw = resp.read().decode("utf-8")
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                payload = exc.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(payload) if payload else None
                except json.JSONDecodeError:
                    parsed = payload
                if exc.code in {429, 500, 502, 503, 504} and attempt + 1 < retries:
                    time.sleep(1.5 * (attempt + 1))
                    last_error = AltegioError(f"HTTP {exc.code}: {parsed}", exc.code, parsed)
                    continue
                raise AltegioError(f"HTTP {exc.code}: {parsed}", exc.code, parsed) from exc
            except urllib.error.URLError as exc:
                last_error = AltegioError(f"Network error: {exc}")
                if attempt + 1 < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise last_error from exc
        raise last_error or AltegioError("Unknown Altegio request failure")

    def authorize_user(self, login: str, password: str) -> str:
        payload = self.request(
            "POST",
            "auth",
            body={"login": login, "password": password},
            with_user=False,
        )
        token = (payload.get("data") or {}).get("user_token")
        if not token:
            raise AltegioError(f"Auth response has no user_token: {payload}")
        self.user_token = token
        return token

    def company(self) -> dict[str, Any]:
        payload = self.request("GET", f"company/{self.location_id}")
        return payload.get("data") or payload

    def locations(self) -> list[dict[str, Any]]:
        """Locations visible to the authenticated Altegio user."""
        payload = self.request("GET", "locations")
        data = payload.get("data") or payload
        if isinstance(data, dict):
            data = data.get("items") or data.get("locations") or []
        return data if isinstance(data, list) else []

    def iter_clients(self, page_size: int = 200) -> list[dict[str, Any]]:
        clients: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self.request(
                "GET",
                f"clients/{self.location_id}",
                params={"page": page, "count": page_size},
            )
            chunk = payload.get("data") or []
            if not chunk:
                break
            clients.extend(chunk)
            meta = payload.get("meta") or {}
            total_pages = int(meta.get("total_count") or meta.get("page_count") or 0)
            if total_pages and page >= total_pages:
                break
            if len(chunk) < page_size:
                break
            page += 1
            if page > 200:
                break
        return clients

    def iter_records(self, start_date: str, end_date: str, page_size: int = 200) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self.request(
                "GET",
                f"records/{self.location_id}",
                params={
                    "start_date": start_date,
                    "end_date": end_date,
                    "page": page,
                    "count": page_size,
                    "include_consumption": 1,
                    "with_deleted": 0,
                },
            )
            chunk = payload.get("data") or []
            if not chunk:
                break
            records.extend(chunk)
            if len(chunk) < page_size:
                break
            page += 1
            if page > 500:
                break
        return records

    def staff(self) -> list[dict[str, Any]]:
        payload = self.request("GET", f"staff/{self.location_id}")
        return payload.get("data") or []

    def services(self) -> list[dict[str, Any]]:
        payload = self.request("GET", f"company/{self.location_id}/services")
        data = payload.get("data") or []
        # Some deployments nest services under categories.
        flat: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict) and item.get("id") and (
                item.get("price") is not None
                or item.get("cost") is not None
                or item.get("title")
                or item.get("name")
            ):
                flat.append(item)
            for svc in item.get("services") or []:
                if isinstance(svc, dict) and svc.get("id"):
                    flat.append(svc)
        return flat or data

    def create_client(self, *, name: str, phone: str, comment: str = "") -> dict[str, Any]:
        payload = self.request(
            "POST",
            f"clients/{self.location_id}",
            body={"name": name, "phone": phone, "comment": comment},
        )
        data = payload.get("data") or payload
        if isinstance(data, list):
            return data[0] if data else {}
        return data

    def create_appointment(
        self,
        *,
        staff_id: int,
        service_id: int,
        service_cost: float,
        client_name: str,
        client_phone: str,
        client_id: int | None,
        datetime_iso: str,
        seance_length: int = 3600,
        attendance: int = 1,
        comment: str = "",
    ) -> dict[str, Any]:
        client_body: dict[str, Any] = {"name": client_name, "phone": client_phone}
        if client_id:
            client_body["id"] = client_id
        body = {
            "staff_id": staff_id,
            "team_member_id": staff_id,
            "services": [
                {
                    "id": service_id,
                    "amount": 1,
                    "cost": service_cost,
                    "first_cost": service_cost,
                    "discount": 0,
                }
            ],
            "client": client_body,
            "datetime": datetime_iso,
            "seance_length": seance_length,
            "save_if_busy": True,
            "send_sms": False,
            "sms_remain_hours": 0,
            "email_remain_hours": 0,
            "attendance": attendance,
            "comment": comment,
        }
        payload = self.request("POST", f"records/{self.location_id}", body=body)
        data = payload.get("data") or payload
        if isinstance(data, list):
            return data[0] if data else {}
        return data

    def set_attendance(self, record_id: int, attendance: int = 1) -> dict[str, Any]:
        payload = self.request(
            "PUT",
            f"record/{self.location_id}/{record_id}",
            body={"attendance": attendance},
        )
        # Fallback dedicated attendance endpoint used by newer docs.
        if not payload:
            payload = self.request(
                "POST",
                f"locations/{self.location_id}/appointments/{record_id}/attendance",
                body={"attendance": attendance},
            )
        return payload.get("data") or payload

    def create_payment(self, record_id: int, amount: float, document_id: int | None = None) -> dict[str, Any]:
        """Best-effort payment. Some accounts require a cash account id."""
        body: dict[str, Any] = {
            "payment": [
                {
                    "amount": amount,
                    "account_id": int(get_env("ALTEGIO_ACCOUNT_ID", "0") or "0") or None,
                    "pay_type": "cash",
                }
            ]
        }
        body["payment"] = [p for p in body["payment"] if p.get("account_id")]
        if not body["payment"]:
            # Without a cash account, still try document-based settle if document_id known.
            if not document_id:
                return {}
        try:
            if document_id:
                return self.request(
                    "POST",
                    f"company/{self.location_id}/sale/{document_id}/payment",
                    body={"payment": [{"amount": amount}]},
                )
        except AltegioError:
            return {}
        return {}
