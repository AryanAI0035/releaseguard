import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./data/releaseguard.db")
    )
    demo_origin: str = field(
        default_factory=lambda: os.getenv("DEMO_ORIGIN", "http://127.0.0.1:8001")
    )
    artifact_dir: Path = field(default_factory=lambda: Path(os.getenv("ARTIFACT_DIR", "artifacts")))
    api_key: str = field(default_factory=lambda: os.getenv("API_KEY", ""))
    lease_seconds: int = 120
    max_attempts: int = 2
