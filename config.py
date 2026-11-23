
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

    MAIL_SERVER = os.environ.get("MAIL_SERVER", "").strip()
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USE_SSL = os.environ.get("MAIL_USE_SSL", "false").lower() == "true"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "").strip()
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "").strip()
    PUBLIC_BASE_URL = os.environ.get(
        "PUBLIC_BASE_URL",
        "http://127.0.0.1:5000" if APP_ENV != "production" else "",
    ).rstrip("/")
    ACCOUNT_SETUP_TOKEN_MAX_AGE = 24 * 60 * 60
