from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import requests

from portfolio_sync.models import InboxRecord, NotionPage, PortfolioTarget

NOTION_BASE_URL = "https://api.notion.com/v1"
TEXT_BLOCK_TYPES = {
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "to_do",
    "toggle",
    "quote",
    "callout",
    "code",
}
TRANSIENT_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
MAX_REQUEST_ATTEMPTS = 4
REQUEST_BACKOFF_SECONDS = 1.5


def parse_notion_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def extract_plain_text(rich_text: list[dict] | None) -> str:
    if not rich_text:
        return ""
    return "".join(fragment.get("plain_text", "") for fragment in rich_text)


def normalize_title(value: str) -> str:
    return " ".join(value.casefold().split())


class NotionClient:
    def __init__(self, token: str, notion_version: str) -> None:
        self.token = token
        self.notion_version = notion_version
        self._database_schema_cache: dict[str, dict[str, dict]] = {}
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": notion_version,
                "Content-Type": "application/json",
            }
        )

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        url = f"{NOTION_BASE_URL}{path}"
        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            try:
                response = self.session.request(method, url, json=payload, timeout=60)
            except requests.RequestException as exc:
                if attempt == MAX_REQUEST_ATTEMPTS:
                    raise RuntimeError(
                        f"Notion API request failed after {MAX_REQUEST_ATTEMPTS} attempts for {path}: {exc}"
                    ) from exc
                time.sleep(REQUEST_BACKOFF_SECONDS * attempt)
                continue

            if response.status_code < 400:
                return response.json()

            if response.status_code in TRANSIENT_STATUS_CODES and attempt < MAX_REQUEST_ATTEMPTS:
                time.sleep(REQUEST_BACKOFF_SECONDS * attempt)
                continue

            raise RuntimeError(
                f"Notion API request failed ({response.status_code}) for {path}: {response.text}"
            )

        raise RuntimeError(f"Notion API request failed after {MAX_REQUEST_ATTEMPTS} attempts for {path}.")

    def search_pages(self) -> list[dict]:
        results: list[dict] = []
        cursor: str | None = None
        while True:
            payload: dict[str, Any] = {
                "filter": {"property": "object", "value": "page"},
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            }
            if cursor:
                payload["start_cursor"] = cursor
            response = self._request("POST", "/search", payload)
            results.extend(response.get("results", []))
            if not response.get("has_more"):
                return results
            cursor = response.get("next_cursor")

    def retrieve_page(self, page_id: str) -> dict:
        return self._request("GET", f"/pages/{page_id}")

    def retrieve_database(self, database_id: str) -> dict:
        return self._request("GET", f"/databases/{database_id}")

    def query_database(self, database_id: str, payload: dict | None = None) -> list[dict]:
        results: list[dict] = []
        cursor: str | None = None
        body = payload.copy() if payload else {}
        while True:
            request_payload = dict(body)
            if cursor:
                request_payload["start_cursor"] = cursor
            response = self._request("POST", f"/databases/{database_id}/query", request_payload)
            results.extend(response.get("results", []))
            if not response.get("has_more"):
                return results
            cursor = response.get("next_cursor")

    def list_block_children(self, block_id: str) -> list[dict]:
        results: list[dict] = []
        cursor: str | None = None
        while True:
            suffix = f"/blocks/{block_id}/children?page_size=100"
            if cursor:
                suffix += f"&start_cursor={cursor}"
            response = self._request("GET", suffix)
            results.extend(response.get("results", []))
            if not response.get("has_more"):
                return results
            cursor = response.get("next_cursor")

    def append_block_children(self, block_id: str, children: list[dict], after: str | None = None) -> dict:
        payload: dict[str, Any] = {"children": children}
        if after:
            payload["after"] = after
        return self._request("PATCH", f"/blocks/{block_id}/children", payload)

    def archive_block(self, block_id: str) -> dict:
        return self._request("PATCH", f"/blocks/{block_id}", {"archived": True})

    def update_page_properties(self, page_id: str, properties: dict) -> dict:
        return self._request("PATCH", f"/pages/{page_id}", {"properties": properties})

    def create_page(self, parent: dict, properties: dict, children: list[dict]) -> dict:
        payload: dict[str, Any] = {"parent": parent, "properties": properties}
        if children:
            payload["children"] = children
        return self._request("POST", "/pages", payload)

    def page_title(self, page: dict) -> str:
        properties = page.get("properties", {})
        for property_name, payload in properties.items():
            if payload.get("type") == "title":
                return extract_plain_text(payload.get("title"))
            if "title" in payload:
                return extract_plain_text(payload.get("title"))
            if payload.get("id") and property_name == "title":
                return extract_plain_text(payload.get("title"))
        return "Untitled"

    def database_schema(self, database_id: str) -> dict[str, dict]:
        if database_id not in self._database_schema_cache:
            self._database_schema_cache[database_id] = self.retrieve_database(database_id).get("properties", {})
        return self._database_schema_cache[database_id]

    def title_property_name(self, database_id: str) -> str:
        schema = self.database_schema(database_id)
        for property_name, payload in schema.items():
            if payload.get("type") == "title":
                return property_name
        raise RuntimeError(f"Database {database_id} does not have a title property.")

    def build_properties(self, database_id: str, values: dict[str, Any]) -> dict:
        schema = self.database_schema(database_id)
        properties: dict[str, Any] = {}
        for property_name, value in values.items():
            resolved_name = self._resolve_property_name(database_id, property_name)
            definition = schema.get(resolved_name)
            if not definition:
                raise RuntimeError(f"Database missing required property: {property_name}")
            property_type = definition["type"]
            properties[resolved_name] = self._serialize_property(property_type, value)
        return properties

    def _resolve_property_name(self, database_id: str, property_name: str) -> str:
        schema = self.database_schema(database_id)
        if property_name in schema:
            return property_name
        if property_name == "Title":
            return self.title_property_name(database_id)
        return property_name

    def _serialize_property(self, property_type: str, value: Any) -> dict:
        if property_type == "title":
            return {"title": self._rich_text(value)}
        if property_type == "rich_text":
            return {"rich_text": self._rich_text(value)}
        if property_type == "url":
            return {"url": value or None}
        if property_type == "number":
            return {"number": value}
        if property_type == "date":
            return {"date": {"start": value} if value else None}
        if property_type == "select":
            return {"select": {"name": value} if value else None}
        if property_type == "status":
            return {"status": {"name": value} if value else None}
        raise RuntimeError(f"Unsupported Notion property type: {property_type}")

    def _rich_text(self, value: str | None) -> list[dict]:
        if not value:
            return []
        chunks: list[dict] = []
        remaining = value
        while remaining:
            chunks.append({"type": "text", "text": {"content": remaining[:1800]}})
            remaining = remaining[1800:]
        return chunks

    def create_page_in_database(self, database_id: str, title: str, children: list[dict]) -> dict:
        title_property = self.title_property_name(database_id)
        properties = self.build_properties(database_id, {title_property: title})
        return self.create_page({"database_id": database_id}, properties, children)

    def create_page_under_parent(self, parent_page_id: str, title: str, children: list[dict]) -> dict:
        properties = {"title": self._serialize_property("title", title)}
        return self.create_page({"page_id": parent_page_id}, properties, children)

    def find_inbox_row(self, database_id: str, source_page_id: str) -> dict | None:
        results = self.query_database(
            database_id,
            {
                "filter": {
                    "property": "Source Page ID",
                    "rich_text": {"equals": source_page_id},
                }
            },
        )
        return results[0] if results else None

    def find_row_by_rich_text(self, database_id: str, property_name: str, value: str) -> dict | None:
        results = self.query_database(
            database_id,
            {
                "filter": {
                    "property": property_name,
                    "rich_text": {"equals": value},
                }
            },
        )
        return results[0] if results else None

    def approved_rows(self, database_id: str) -> list[dict]:
        schema = self.database_schema(database_id)
        approval_filter = self._status_filter(schema["Approval Status"]["type"], "Approval Status", "approved")
        apply_filter = self._status_filter(schema["Apply State"]["type"], "Apply State", "pending")
        return self.query_database(database_id, {"filter": {"and": [approval_filter, apply_filter]}})

    def approved_inbox_rows(self, database_id: str) -> list[dict]:
        schema = self.database_schema(database_id)
        approval_filter = self._status_filter(schema["Approval Status"]["type"], "Approval Status", "approved")
        return self.query_database(database_id, {"filter": approval_filter})

    def _status_filter(self, property_type: str, property_name: str, value: str) -> dict:
        if property_type == "status":
            return {"property": property_name, "status": {"equals": value}}
        if property_type == "select":
            return {"property": property_name, "select": {"equals": value}}
        raise RuntimeError(f"{property_name} must be a status or select property.")

    def parse_page_to_notion_page(self, page: dict, content: str) -> NotionPage:
        return NotionPage(
            page_id=page["id"],
            url=page["url"],
            title=self.page_title(page),
            created_time=parse_notion_datetime(page["created_time"]),
            last_edited_time=parse_notion_datetime(page["last_edited_time"]),
            created_by=page.get("created_by", {}).get("id", ""),
            last_edited_by=page.get("last_edited_by", {}).get("id", ""),
            content=content,
        )

    def page_content_as_text(self, page_id: str) -> str:
        lines: list[str] = []
        self._collect_block_text(page_id, lines)
        return "\n".join(line for line in lines if line.strip())

    def _collect_block_text(self, block_id: str, lines: list[str]) -> None:
        children = self.list_block_children(block_id)
        for block in children:
            text = self.block_plain_text(block)
            if text:
                lines.append(text)
            if block.get("has_children"):
                self._collect_block_text(block["id"], lines)

    def block_plain_text(self, block: dict) -> str:
        block_type = block.get("type")
        if block_type in TEXT_BLOCK_TYPES:
            payload = block.get(block_type, {})
            if block_type == "to_do":
                prefix = "[x] " if payload.get("checked") else "[ ] "
                return prefix + extract_plain_text(payload.get("rich_text"))
            if block_type == "code":
                return extract_plain_text(payload.get("rich_text"))
            return extract_plain_text(payload.get("rich_text"))
        if block_type == "child_page":
            return block.get("child_page", {}).get("title", "")
        return ""

    def inbox_record_from_page(self, row: dict) -> InboxRecord:
        properties = row["properties"]
        title_property_name = next(
            (property_name for property_name, payload in properties.items() if payload.get("type") == "title"),
            "Title",
        )
        return InboxRecord(
            page_id=row["id"],
            title=self._property_value(properties[title_property_name]),
            source_page_id=self._property_value(properties["Source Page ID"]),
            approval_status=self._property_value(properties["Approval Status"]),
            apply_state=self._property_value(properties["Apply State"]),
            recommendation_type=self._property_value(properties["Recommendation Type"]),
            target_page_id=self._property_value(properties["Target Page ID"]),
            target_page_url=self._property_value(properties["Target Page URL"]),
            managed_section_key=self._property_value(properties["Managed Section Key"]),
        )

    def _property_value(self, payload: dict) -> str:
        property_type = payload["type"]
        if property_type == "title":
            return extract_plain_text(payload.get("title"))
        if property_type == "rich_text":
            return extract_plain_text(payload.get("rich_text"))
        if property_type == "url":
            return payload.get("url") or ""
        if property_type == "number":
            value = payload.get("number")
            return "" if value is None else str(value)
        if property_type == "date":
            date_value = payload.get("date")
            return date_value.get("start", "") if date_value else ""
        if property_type == "select":
            select_value = payload.get("select")
            return select_value.get("name", "") if select_value else ""
        if property_type == "status":
            status_value = payload.get("status")
            return status_value.get("name", "") if status_value else ""
        return ""

    def portfolio_targets_from_database(self, database_id: str) -> list[PortfolioTarget]:
        targets: list[PortfolioTarget] = []
        for row in self.query_database(database_id):
            page_id = row["id"]
            keys = self.find_managed_section_keys(page_id)
            targets.append(
                PortfolioTarget(
                    page_id=page_id,
                    title=self.page_title(row),
                    url=row["url"],
                    managed_section_keys=keys,
                )
            )
        return targets

    def portfolio_target_from_page(self, page_id: str) -> PortfolioTarget:
        page = self.retrieve_page(page_id)
        return PortfolioTarget(
            page_id=page["id"],
            title=self.page_title(page),
            url=page["url"],
            managed_section_keys=self.find_managed_section_keys(page["id"]),
        )

    def portfolio_targets_from_page_ids(self, page_ids: list[str]) -> list[PortfolioTarget]:
        return [self.portfolio_target_from_page(page_id) for page_id in page_ids]

    def find_managed_section_keys(self, page_id: str) -> list[str]:
        children = self.list_block_children(page_id)
        keys: list[str] = []
        for block in children:
            text = self.block_plain_text(block)
            if text.startswith("portfolio_sync_managed_section:") and text.endswith(":start"):
                parts = text.split(":")
                if len(parts) == 3:
                    keys.append(parts[1])
        return keys
