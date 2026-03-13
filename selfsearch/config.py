"""Shared configuration for selfsearch module."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
_dotenv_path = Path(__file__).parent / ".env"
load_dotenv(_dotenv_path)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

if not OPENROUTER_API_KEY:
    raise RuntimeError(
        "OPENROUTER_API_KEY not found. Please copy .env.example to .env and set your API key."
    )
