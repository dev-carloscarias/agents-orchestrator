# ingestors/notion.py

import re
import httpx

from ingestors.base import IngestorBase

BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionError(Exception):
    pass


def parse_page_id(url_or_id: str) -> str:
    """
    Acepta:
      - ID limpio:     "abc123def456abc123def456abc123de"  (32 hex)
      - ID con guiones:"abc123de-f456-abc1-23de-f456abc123de"
      - URL de Notion: "https://notion.so/workspace/Title-abc123def456abc123def456abc1234d"
    Devuelve siempre el ID de 32 chars hex sin guiones.
    Lanza ValueError si no puede extraer un ID válido.
    """
    s = url_or_id.strip()
    path = s.split("?", 1)[0].split("#", 1)[0]
    segment = path.rstrip("/").rsplit("/", 1)[-1] if "/" in path else path

    for part in reversed(segment.split("-")):
        p = part.lower()
        if re.fullmatch(r"[0-9a-f]{32}", p):
            return p

    compact = segment.replace("-", "").lower()
    if re.fullmatch(r"[0-9a-f]{32}", compact):
        return compact

    m = re.search(r"([0-9a-f]{32})\Z", compact)
    if m:
        return m.group(1)

    found = re.findall(r"[0-9a-f]{32}", compact)
    if found:
        return found[-1]

    raise ValueError(
        f"No se pudo extraer un Notion page ID válido de: {url_or_id!r}\n"
        "Asegúrate de pegar la URL completa de Notion o el ID de 32 caracteres."
    )


class NotionClient:
    def __init__(self, token: str):
        self._headers = {
            "Authorization":  f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type":   "application/json",
        }

    def get_page(self, page_id: str) -> dict:
        """Retorna metadata de la página: id, url, título."""
        url = f"{BASE_URL}/pages/{page_id}"
        with httpx.Client() as client:
            resp = client.get(url, headers=self._headers, timeout=15)
        if resp.status_code != 200:
            raise NotionError(
                f"Error al obtener página {page_id}: "
                f"HTTP {resp.status_code} — {resp.text[:300]}"
            )
        data = resp.json()
        # Extraer título de las properties
        title = ""
        props = data.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                rich = prop.get("title", [])
                title = "".join(r.get("plain_text", "") for r in rich)
                break
        return {
            "id":    data["id"].replace("-", ""),
            "url":   data["url"],
            "title": title,
        }

    def get_blocks(self, page_id: str) -> list[dict]:
        """Descarga todos los bloques de la página, manejando paginación."""
        blocks   = []
        url      = f"{BASE_URL}/blocks/{page_id}/children"
        params   = {"page_size": 100}
        with httpx.Client() as client:
            while True:
                resp = client.get(url, headers=self._headers, params=params, timeout=15)
                if resp.status_code != 200:
                    raise NotionError(f"Error obteniendo bloques: HTTP {resp.status_code}")
                data = resp.json()
                blocks.extend(data.get("results", []))
                if not data.get("has_more"):
                    break
                params["start_cursor"] = data["next_cursor"]
        return blocks

    def extract_text(self, blocks: list[dict]) -> str:
        """
        Convierte lista de bloques Notion a texto plano.
        Tipos soportados:
          paragraph, heading_1/2/3, bulleted_list_item, numbered_list_item,
          code, to_do, quote, divider, callout
        Tipos ignorados: image, video, file, embed, bookmark, etc.
        """
        lines   = []
        counters: dict[str, int] = {}

        for block in blocks:
            btype = block.get("type", "")
            data  = block.get(btype, {})

            if btype in ("paragraph", "heading_1", "heading_2", "heading_3"):
                text = self._rich_text(data.get("rich_text", []))
                if btype == "heading_1":
                    lines.append(f"# {text}")
                elif btype == "heading_2":
                    lines.append(f"## {text}")
                elif btype == "heading_3":
                    lines.append(f"### {text}")
                else:
                    lines.append(text)

            elif btype == "bulleted_list_item":
                text = self._rich_text(data.get("rich_text", []))
                lines.append(f"- {text}")

            elif btype == "numbered_list_item":
                n = counters.get("numbered", 0) + 1
                counters["numbered"] = n
                text = self._rich_text(data.get("rich_text", []))
                lines.append(f"{n}. {text}")

            elif btype == "to_do":
                checked = data.get("checked", False)
                text = self._rich_text(data.get("rich_text", []))
                prefix = "- [x]" if checked else "- [ ]"
                lines.append(f"{prefix} {text}")

            elif btype == "code":
                lang = data.get("language", "")
                text = self._rich_text(data.get("rich_text", []))
                lines.append(f"```{lang}\n{text}\n```")

            elif btype == "quote":
                text = self._rich_text(data.get("rich_text", []))
                lines.append(f"> {text}")

            elif btype == "callout":
                icon = data.get("icon", {}).get("emoji", "📌")
                text = self._rich_text(data.get("rich_text", []))
                lines.append(f"{icon} {text}")

            elif btype == "divider":
                lines.append("---")

            else:
                # Ignorar tipos no soportados sin error
                pass

            # Reset contador numbered si el bloque no es numbered_list_item
            if btype != "numbered_list_item":
                counters["numbered"] = 0

        return "\n".join(lines)

    @staticmethod
    def _rich_text(rich_text: list[dict]) -> str:
        return "".join(rt.get("plain_text", "") for rt in rich_text)


class NotionIngestor(IngestorBase):
    """Envuelve NotionClient y expone un dict listo para Normalizer.convert."""

    def __init__(self, token: str):
        self._client = NotionClient(token)

    def ingest(self, source: str) -> dict:
        page_id = parse_page_id(source)
        page = self._client.get_page(page_id)
        blocks = self._client.get_blocks(page_id)
        raw_text = self._client.extract_text(blocks)
        return {
            "page_id": page_id,
            "page_url": page["url"],
            "title": page["title"],
            "raw_text": raw_text,
        }
