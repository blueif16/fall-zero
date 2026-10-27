"""Settings loaded from the environment and `.env`. Any key left blank is treated as "not configured"."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Meta Model API: Muse Spark, Muse Wonder, Muse Image, Muse Voice Transcribe, SAM 3.1
    model_api_key: str = ""
    meta_base_url: str = "https://api.meta.ai/v1"
    meta_text_model: str = "muse-spark-1.3"
    meta_agent_model: str = "muse-wonder-1.0"
    meta_image_model: str = "muse-image-1.0"
    meta_asr_model: str = "muse-voice-transcribe-1.0"
    meta_sam_model: str = "sam-3.1"

    # Baseten: Muse Spark Open (the hackathon build is -1026, not the docs' default)
    baseten_api_key: str = ""
    baseten_base_url: str = "https://inference.baseten.co/v1"
    baseten_model: str = "meta-models/muse-spark-open-1026"

    # Fireworks: Muse Spark Open on serverless
    fireworks_api_key: str = ""
    fireworks_base_url: str = "https://api.fireworks.ai/inference/v1"
    fireworks_model: str = "accounts/fireworks/models/muse-spark-open"

    # Modal: one proxy token (wk-<id>.ws-<secret>) covers the shared endpoint and our own Glimmer server
    modal_proxy_token: str = ""
    modal_spark_open_url: str = ""  # Shared Endpoint URL from the Modal dashboard
    modal_spark_open_model: str = ""  # model name shown next to that URL
    glimmer_url: str = ""  # printed by `modal deploy modal_apps/glimmer.py`
    glimmer_model: str = "muse-glimmer"


@lru_cache
def get_settings() -> Settings:
    return Settings()
