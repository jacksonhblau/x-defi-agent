"""Centralized config loader. Reads .env at project root and config/*.json."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel


# Resolve project root by walking up until we find .env.example.
def _find_project_root(start: Path) -> Path:
    cur = start.resolve()
    for parent in [cur, *cur.parents]:
        if (parent / ".env.example").exists():
            return parent
    raise RuntimeError("Could not locate project root (no .env.example found)")


PROJECT_ROOT = _find_project_root(Path(__file__).parent)
# override=True makes .env the source of truth. Without this, stale shell exports
# (e.g. an old RWA_XYZ_API_KEY exported in a prior session) silently beat out .env.
load_dotenv(PROJECT_ROOT / ".env", override=True)


class Env(BaseModel):
    # X / Twitter
    x_api_key: str = ""
    x_api_secret: str = ""
    x_bearer_token: str = ""
    x_access_token: str = ""
    x_access_secret: str = ""
    x_handle: str = "jacksonblau"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-6"

    # Supabase / Postgres
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""
    database_url: str = ""

    # Alchemy
    alchemy_api_key: str = ""
    alchemy_eth_mainnet_rpc: str = ""
    alchemy_base_rpc: str = ""
    alchemy_arbitrum_rpc: str = ""

    # Telegram
    telegram_api_id: str = ""
    telegram_api_hash: str = ""
    telegram_phone: str = ""
    telegram_session_path: str = "./data/telegram.session"
    telegram_channels: str = "RWAxyzNewswire"

    # RWA.xyz
    rwa_xyz_api_key: str = ""
    rwa_xyz_base_url: str = "https://api.rwa.xyz"

    # Other
    defillama_api_key: str = ""
    vaultsfyi_api_key: str = ""
    bubblemaps_api_key: str = ""
    etherscan_api_key: str = ""

    # App config
    review_ui_password: str = ""
    review_ui_jwt_secret: str = ""

    log_level: str = "info"


def env() -> Env:
    """Build an Env model from os.environ."""
    return Env(
        x_api_key=os.getenv("X_API_KEY", ""),
        x_api_secret=os.getenv("X_API_SECRET", ""),
        x_bearer_token=os.getenv("X_BEARER_TOKEN", ""),
        x_access_token=os.getenv("X_ACCESS_TOKEN", ""),
        x_access_secret=os.getenv("X_ACCESS_SECRET", ""),
        x_handle=os.getenv("X_HANDLE", "jacksonblau"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-opus-4-6"),
        supabase_url=os.getenv("SUPABASE_URL", ""),
        supabase_anon_key=os.getenv("SUPABASE_ANON_KEY", ""),
        supabase_service_key=os.getenv("SUPABASE_SERVICE_KEY", ""),
        database_url=os.getenv("DATABASE_URL", ""),
        alchemy_api_key=os.getenv("ALCHEMY_API_KEY", ""),
        alchemy_eth_mainnet_rpc=os.getenv("ALCHEMY_ETH_MAINNET_RPC", ""),
        alchemy_base_rpc=os.getenv("ALCHEMY_BASE_RPC", ""),
        alchemy_arbitrum_rpc=os.getenv("ALCHEMY_ARBITRUM_RPC", ""),
        telegram_api_id=os.getenv("TELEGRAM_API_ID", ""),
        telegram_api_hash=os.getenv("TELEGRAM_API_HASH", ""),
        telegram_phone=os.getenv("TELEGRAM_PHONE", ""),
        telegram_session_path=os.getenv("TELEGRAM_SESSION_PATH", "./data/telegram.session"),
        telegram_channels=os.getenv("TELEGRAM_CHANNELS", "RWAxyzNewswire"),
        rwa_xyz_api_key=os.getenv("RWA_XYZ_API_KEY", ""),
        rwa_xyz_base_url=os.getenv("RWA_XYZ_BASE_URL", "https://api.rwa.xyz"),
        defillama_api_key=os.getenv("DEFILLAMA_API_KEY", ""),
        vaultsfyi_api_key=os.getenv("VAULTSFYI_API_KEY", ""),
        bubblemaps_api_key=os.getenv("BUBBLEMAPS_API_KEY", ""),
        etherscan_api_key=os.getenv("ETHERSCAN_API_KEY", ""),
        review_ui_password=os.getenv("REVIEW_UI_PASSWORD", ""),
        review_ui_jwt_secret=os.getenv("REVIEW_UI_JWT_SECRET", ""),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )


def load_json(rel_path: str) -> dict[str, Any]:
    """Load a JSON config file relative to project root."""
    path = PROJECT_ROOT / rel_path
    with path.open() as f:
        return json.load(f)


def thresholds() -> dict[str, Any]:
    return load_json("config/thresholds.json")


def watchlist() -> dict[str, Any]:
    return load_json("config/watchlist.json")


def prompt(name: str) -> str:
    """Load a prompt file from packages/prompts/."""
    path = PROJECT_ROOT / "packages" / "prompts" / f"{name}.md"
    return path.read_text()
