"""
Конфiгурацiя застосунку PharmaRef.
"""

import os
from pathlib import Path


class Config:
    """Базова конфiгурацiя."""

    BASE_DIR = Path(__file__).parent.absolute()
    DATA_DIR = BASE_DIR / "data"

    # База даних
    DATABASE_PATH = BASE_DIR / "pharmaref.db"

    # DRLZ джерело даних
    DRLZ_CSV_URL = "http://www.drlz.com.ua/ibp/zvity.nsf/all/zvit/$file/reestr.csv"
    DRLZ_ENCODING = "windows-1251"
    DRLZ_DELIMITER = ";"

    # OpenFDA API
    FDA_API_BASE = "https://api.fda.gov/drug/label.json"
    FDA_CACHE_TTL = 86400  # 24 години в секундах
    FDA_RATE_LIMIT = 240  # запитiв на хвилину без API ключа

    # Пошук
    MIN_SEARCH_LENGTH = 3  # мiнiмальна довжина запиту для live-пошуку

    # AI провайдери (Groq -> OpenRouter -> Gemini fallback)
    # Groq: безкоштовний, швидкий (llama-3.1-8b: 14,400 req/day)
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

    # OpenRouter: 29 безкоштовних моделей (50 req/day, 20 RPM)
    OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

    # Google Gemini (fallback)
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

    AI_ENABLED = True  # Увiмкнути AI-аналiз

    # Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    DEBUG = os.environ.get("FLASK_DEBUG", "False").lower() in ("true", "1", "yes")


class DevelopmentConfig(Config):
    """Конфiгурацiя для розробки."""
    DEBUG = True


class ProductionConfig(Config):
    """Конфiгурацiя для продакшену."""
    DEBUG = False


def get_config():
    """Повертає конфiгурацiю залежно вiд середовища."""
    env = os.environ.get("FLASK_ENV", "development")
    if env == "production":
        return ProductionConfig()
    return DevelopmentConfig()
