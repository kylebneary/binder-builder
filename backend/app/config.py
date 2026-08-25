"""Application settings. Loaded from environment / .env."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/binder_builder.db"
    pokemontcg_api_key: str | None = None
    pokemontcg_base_url: str = "https://api.pokemontcg.io/v2"
    tcgcsv_base_url: str = "https://tcgcsv.com"
    tcgcsv_pokemon_category_id: int = 3

    data_dir: Path = Path("./data")
    image_cache_dir: Path = Path("./data/images")

    sim_default_trials: int = 20_000
    sim_max_trials: int = 250_000

    log_level: str = "INFO"

    @property
    def pull_rates_dir(self) -> Path:
        return self.data_dir / "pull_rates"

    @property
    def templates_dir(self) -> Path:
        return self.data_dir / "binder_templates"


@lru_cache
def get_settings() -> Settings:
    return Settings()
