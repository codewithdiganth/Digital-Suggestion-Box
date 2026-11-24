
import os
import secrets
from datetime import timedelta
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

load_dotenv(os.path.join(BASE_DIR, ".env"))

APP_ENV = os.environ.get("APP_ENV", "development").lower()


class Config:
    APP_ENV = APP_ENV

    SECRET_KEY = os.environ.get("SECRET_KEY") or (
        secrets.token_hex(32) if APP_ENV != "production" else None
    )

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(BASE_DIR, "instance", "suggestions.db")
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Session security
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get(
        "SESSION_COOKIE_SECURE",
        "True" if APP_ENV == "production" else "False"
    ).lower() == "true"

    # Remember-login protection
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
