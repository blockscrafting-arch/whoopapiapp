from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str
    DATABASE_URL_SYNC: str

    WHOOP_CLIENT_ID: str
    WHOOP_CLIENT_SECRET: str
    WHOOP_REDIRECT_URI: str

    WHOOP_AUTH_URL: str = "https://api.prod.whoop.com/oauth/oauth2/auth"
    WHOOP_TOKEN_URL: str = "https://api.prod.whoop.com/oauth/oauth2/token"
    WHOOP_API_BASE: str = "https://api.prod.whoop.com/developer"

    SESSION_SECRET_KEY: str
    TOKEN_ENCRYPTION_KEY: str

    DEBUG: bool = False
    CORS_ORIGINS: Optional[str] = None

    CACHE_TTL_SECONDS: int = 900
    CACHE_TTL_PROFILE_SECONDS: int = 3600

    @property
    def cors_origins_list(self) -> List[str]:
        if not self.CORS_ORIGINS or not self.CORS_ORIGINS.strip():
            return []
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
