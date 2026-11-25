from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    site_domain: str = "localhost"
    database_url: str = "postgresql+asyncpg://berezhno:berezhno@localhost:5432/berezhno"

    # Ключ для подписи кук и кодов входа. Скрипты установки и обновления создают его сами.
    secret_key: str = ""
    # Куки только по https. В тестах на http выключается.
    cookie_secure: bool = True

    # Почта: postbox — отправка через Yandex Cloud Postbox, log — только запись в журнал (разработка и тесты).
    mail_mode: str = "postbox"
    mail_from_name: str = "Бережно"
    mail_from_address: str = "privet@steady-me.ru"

    yandex_folder_id: str = ""
    yandex_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
