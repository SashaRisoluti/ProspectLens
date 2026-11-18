"""Impostazioni lette solo da variabili d'ambiente."""

import os
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]  # radice del repo (o /app nel container)


@dataclass(frozen=True)
class Settings:
    database_url: str
    config_dir: Path
    cache_dir: Path
    app_mode: str


def get_settings() -> Settings:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL non impostata: copia .env.example in .env")
    return Settings(
        database_url=url,
        config_dir=Path(os.environ.get("CONFIG_DIR", _ROOT / "config")),
        cache_dir=Path(os.environ.get("CACHE_DIR", _ROOT / "data" / "cache")),
        app_mode=os.environ.get("APP_MODE", "dev"),
    )
