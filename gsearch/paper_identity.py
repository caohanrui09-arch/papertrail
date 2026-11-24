"""One arXiv paper identity across interaction IDs, versioned URLs and citations."""
import re
from urllib.parse import urlparse, unquote


PATTERN = re.compile(r"(?P<base>(?:\d{4}\.\d{4,5}|[a-z][a-z.\-]*/\d{7}))(?P<version>v[1-9]\d*)?", re.I)


def arxiv_identity(value: str) -> tuple[str, int | None]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected a nonempty arXiv identity")
    text = value.strip()
    if text.startswith(("https://", "http://")):
        parsed = urlparse(text)
        if parsed.hostname not in ("arxiv.org", "www.arxiv.org", "export.arxiv.org"):
            raise ValueError("Unrecognized arXiv source host")
        path = unquote(parsed.path)
        if not path.startswith(("/abs/", "/pdf/")):
            raise ValueError("Expected an arXiv abstract/PDF record URL")
        text = path[5:]
    elif text.lower().startswith("arxiv:"):
        text = text[6:].strip()
    if text.endswith(".pdf"):
        text = text[:-4]
    match = PATTERN.fullmatch(text)
    if not match:
        raise ValueError("Invalid arXiv ID")
    base = match["base"]
    if "." in base and "/" not in base and not 1 <= int(base[2:4]) <= 12:
        raise ValueError("Invalid arXiv submission month")
    return base.lower(), int(match["version"][1:]) if match["version"] else None


def canonical_id(value: str) -> str:
    return arxiv_identity(value)[0]
