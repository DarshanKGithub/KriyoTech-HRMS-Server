from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field,AliasChoices


class Settings(BaseSettings):
    app_name: str = 'HRMS API'
    secret_key: str = Field(min_length=32)
    algorithm: str = 'HS256'
    access_token_expire_minutes: int = 480
    database_url: str = 'sqlite:///./hrms.db'
    frontend_origins: str = 'http://localhost:3000,http://127.0.0.1:3000,https://avi-corex-hrms-ui.vercel.app/,https://hrms.greatertechhub.com'
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None
    stripe_secret_key: str | None = None
    stripe_publishable_key: str | None = None
    stripe_webhook_secret: str | None = None
    upload_root: str = 'uploads'
    public_app_url: str = 'http://localhost:3000'
    mail_transport: str = 'auto'
    smtp_server: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = Field(default=None,validation_alias=AliasChoices('SMTP_USERNAME','SENDER_EMAIL'))
    smtp_password: str | None = Field(default=None,validation_alias=AliasChoices('SMTP_PASSWORD','SENDER_PASSWORD'))
    smtp_from: str = Field(default='no-reply@kriyotechlabs.com',validation_alias=AliasChoices('SMTP_FROM','SENDER_EMAIL'))
    smtp_use_tls: bool = True
    smtp_allow_insecure_loopback: bool = False
    account_token_minutes: int = 30
    invitation_token_minutes: int = 1440
    login_attempt_limit: int = 5
    login_window_minutes: int = 15

    model_config = SettingsConfigDict(env_file=('.env', '.env.local'), extra='ignore',hide_input_in_errors=True)

    @property
    def sqlalchemy_database_url(self) -> str:
        """Return a SQLAlchemy URL compatible with installed Postgres driver."""
        raw = self.database_url.strip()
        if raw.startswith('postgresql+'):  # driver already specified
            return raw
        if raw.startswith('postgres://'):
            return raw.replace('postgres://', 'postgresql+psycopg://', 1)
        if raw.startswith('postgresql://'):
            return raw.replace('postgresql://', 'postgresql+psycopg://', 1)
        return raw

    @property
    def cors_origins(self) -> list[str]:
        return [origin.rstrip('/').strip() for origin in self.frontend_origins.split(',') if origin.strip()]


@lru_cache

def get_settings() -> Settings:
    return Settings()


settings = get_settings()
