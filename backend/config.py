from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # GitLab
    GITLAB_TOKEN: str = ""
    GITLAB_URL: str = "https://gitlab.com"

    # Google Cloud / Gemini
    GOOGLE_PROJECT_ID: str = ""
    GOOGLE_LOCATION: str = "us-central1"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # MongoDB Atlas
    MONGODB_URI: str = ""
    MONGODB_DB_NAME: str = "necro_db"

    # Slack (optional — enables autonomous notifications)
    SLACK_BOT_TOKEN: str = ""
    SLACK_CHANNEL_ID: str = ""

    # App
    APP_PORT: int = 8080
    APP_URL: str = "https://necro-REPLACE.run.app"
    OUTPUT_DIR: str = "outputs"
    DEMO_MODE: bool = False

    # Autonomous monitoring
    MONITOR_INTERVAL_HOURS: int = 24

    # GitLab webhook secret (optional — validates incoming webhook payloads)
    NECRO_WEBHOOK_SECRET: str = ""


settings = Settings()
OUTPUT_PATH = Path(settings.OUTPUT_DIR) / "necro"
