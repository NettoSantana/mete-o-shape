import json, os, threading
from typing import Dict, Any

_DB_PATH = os.path.join(os.getcwd(), "db.json")
_lock = threading.Lock()

DEFAULT = {
    "users": {},
}

def _ensure_file():
    if not os.path.isfile(_DB_PATH):
        with open(_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT, f, ensure_ascii=False, indent=2)

def load_db() -> Dict[str, Any]:
    _ensure_file()
    with _lock:
        with open(_DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

def save_db(db: Dict[str, Any]) -> None:
    with _lock:
        with open(_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
