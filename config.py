from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_key: str
    supabase_anon_key: str = ""
    secret_key: str = "change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    app_name: str = "Gym 25"
    debug: bool = True
    zkteco_use_mock: bool = True

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = "rfazal853.ml@gmail.com"
    smtp_password: str = "tndm yxbd twrf xzue"
    smtp_sender_email: str = "rfazal853.ml@gmail.com"
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()