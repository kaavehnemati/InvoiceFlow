from typing import Literal

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Everything this application can be configured with.

    Values are resolved in this order, first match wins:

        1. an environment variable
        2. a key in the .env file, if one exists
        3. the default declared below

    The defaults are development values, not secrets, and a real deployment is
    expected to override them. Nothing here should ever hold a production
    credential -- .env is gitignored precisely so it can, locally, without
    being committed.

    The types are not decoration. A malformed URL or a misspelled log level
    fails here, at import time, with a message naming the field -- rather than
    surfacing later as a connection error or a silently ignored setting.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Ignore unrelated environment variables rather than failing on them;
        # the process environment contains plenty that is none of our business.
        extra="ignore",
    )

    database_url: PostgresDsn = (
        "postgresql+psycopg://invoiceflow:invoiceflow@localhost:5432/invoiceflow"
    )

    # Declared because a deployment needs to set them, but nothing reads them
    # yet: Phase 13 introduces logging and consumes log_level, and app_env is
    # for the environment-dependent behavior that later phases add.
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"


# One instance, imported wherever configuration is needed. Building it here
# means an invalid configuration stops the process at startup instead of at the
# first request that happens to touch the bad value.
settings = Settings()
