"""Small JSON cache for expensive local/Claude-derived outputs."""
import hashlib
import json
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).parent / "data" / "cache"


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_key(kind: str, payload: dict) -> str:
    return hashlib.sha256(f"{kind}:{stable_json(payload)}".encode("utf-8")).hexdigest()


def get(cache_dir: str | Path, kind: str, key: str) -> Any | None:
    path = Path(cache_dir) / kind / f"{key}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("value")


def set(cache_dir: str | Path, kind: str, key: str, value: Any) -> None:
    path = Path(cache_dir) / kind / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"value": value}, f, indent=2, ensure_ascii=True)
    tmp.replace(path)
