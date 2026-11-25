from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    site_domain: str = "localhost"
    database_url: str = "postgresql+asyncpg://berezhno:berezhno@localhost:5432/berezhno"

    yandex_folder_id: str = ""
    yandex_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
