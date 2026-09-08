from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Secure environment-level application settings.

    Business mappings, schemas, formulas, and table definitions do not
    belong here. They are loaded from YAML by ConfigManager.
    """

    app_env: str = Field(
        default="local",
        description="Application execution environment.",
    )

    postgres_host: str = Field(
        description="PostgreSQL server hostname.",
    )

    postgres_port: int = Field(
        default=5432,
        description="PostgreSQL server port.",
    )

    postgres_database: str = Field(
        description="PostgreSQL database name.",
    )

    postgres_username: str = Field(
        description="PostgreSQL username.",
    )

    postgres_password: str = Field(
        description="PostgreSQL password.",
    )

    postgres_pool_size: int = Field(
        default=5,
        ge=1,
        description="Number of persistent database connections.",
    )

    postgres_max_overflow: int = Field(
        default=10,
        ge=0,
        description="Additional temporary database connections.",
    )

    postgres_pool_timeout_seconds: int = Field(
        default=30,
        ge=1,
        description="Maximum wait time for an available connection.",
    )

    postgres_pool_recycle_seconds: int = Field(
        default=1800,
        ge=60,
        description="Maximum age of pooled database connections.",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def postgres_url(self) -> str:
        """
        Build the SQLAlchemy PostgreSQL connection URL.

        Credentials are URL-encoded so special characters in the username
        or password do not break the connection string.
        """

        username = quote_plus(self.postgres_username)
        password = quote_plus(self.postgres_password)

        return (
            "postgresql+psycopg://"
            f"{username}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/{self.postgres_database}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return one cached Settings object for the application process.
    """

    return Settings()