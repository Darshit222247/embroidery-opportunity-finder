"""
Load config from .env file in project root.
Call load_env() once at startup.
"""
import os

ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")


def load_env():
    if not os.path.exists(ENV_PATH):
        return
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())


def get_brave_key() -> str:
    return os.environ.get("BRAVE_API_KEY", "")


def has_brave_key() -> bool:
    return bool(get_brave_key())
