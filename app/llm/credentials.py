import json
import os
from pathlib import Path
from typing import Dict, Optional

# Prefer to store in data directory like bookkeeping does
CREDENTIALS_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "credentials.json"

def _load_credentials() -> Dict[str, str]:
    if CREDENTIALS_FILE.exists():
        try:
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_credentials(data: Dict[str, str]) -> None:
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def get_provider_api_key(provider_name: str) -> Optional[str]:
    """
    Get the API key for a provider.
    Checks memory/json first, falls back to os.environ.
    """
    # 1. Check local secure storage
    creds = _load_credentials()
    key = creds.get(provider_name.lower())
    if key:
        return key
    
    # 2. Check environment variables
    env_var_name = f"{provider_name.upper()}_API_KEY"
    return os.environ.get(env_var_name)

def set_provider_api_key(provider_name: str, key: str) -> None:
    """
    Store the API key for a provider in the local credentials file.
    This enables the Phase C.2 UI to securely save keys without rewriting .env.
    """
    creds = _load_credentials()
    creds[provider_name.lower()] = key.strip()
    _save_credentials(creds)
