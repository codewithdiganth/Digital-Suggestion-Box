import secrets
import smtplib
from email.message import EmailMessage
from urllib.parse import urljoin, urlsplit

from flask import current_app, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import db
from app.models import User


def validate_email_configuration():
    base_url = current_app.config["PUBLIC_BASE_URL"]
    parsed_base_url = urlsplit(base_url)
    if (
        not current_app.config["MAIL_SERVER"]
        or not current_app.config["MAIL_DEFAULT_SENDER"]
        or not base_url
        or parsed_base_url.scheme not in {"http", "https"}
        or not parsed_base_url.netloc
        or parsed_base_url.username
        or parsed_base_url.password
        or (
            current_app.config["APP_ENV"] == "production"
            and parsed_base_url.scheme != "https"
        )
        or (
            current_app.config["MAIL_USE_TLS"]
            and current_app.config["MAIL_USE_SSL"]
        )
        or not (
            current_app.config["MAIL_USE_TLS"]
            or current_app.config["MAIL_USE_SSL"]
        )
    ):
        raise RuntimeError(
            "Email is not configured. Set MAIL_SERVER, MAIL_DEFAULT_SENDER, "
            "PUBLIC_BASE_URL, and one secure SMTP transport (TLS or SSL) "
            "before creating or resetting accounts."
        )


def create_public_user_id():
    while True:
        user_id = f"USR-{secrets.token_hex(5).upper()}"
        if not User.query.filter(
            (User.public_user_id == user_id) | (User.username == user_id)
        ).first():
            return user_id


def issue_setup_token(user):
    nonce = secrets.token_urlsafe(32)
    user.setup_token_nonce = nonce
    serializer = URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"],
        salt="account-password-setup",
    )
    return serializer.dumps({"user_id": user.id, "nonce": nonce})


def get_user_for_setup_token(token):
    serializer = URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"],
        salt="account-password-setup",
    )
    try:
        payload = serializer.loads(
            token,
            max_age=current_app.config["ACCOUNT_SETUP_TOKEN_MAX_AGE"],
        )
    except (BadSignature, SignatureExpired):
        return None

    if not isinstance(payload, dict):
        return None
    user = db.session.get(User, payload.get("user_id"))
    nonce = payload.get("nonce")
    if (
        user is None
        or not user.is_active
        or not isinstance(nonce, str)
        or not user.setup_token_nonce
        or not secrets.compare_digest(user.setup_token_nonce, nonce)
    ):
        return None
    return user


def send_account_setup_email(user, token):
    validate_email_configuration()
    server = current_app.config["MAIL_SERVER"]
    sender = current_app.config["MAIL_DEFAULT_SENDER"]
    base_url = current_app.config["PUBLIC_BASE_URL"]

    setup_path = url_for("setup_account_password", token=token)
    setup_url = urljoin(f"{base_url}/", setup_path.lstrip("/"))
    message = EmailMessage()
    message["Subject"] = "Set up your Digital Suggestion Box account"
    message["From"] = sender
    message["To"] = user.email
    message.set_content(
        f"Hello {user.full_name},\n\n"
        "Your Digital Suggestion Box account has been created.\n"
        f"Your User ID is: {user.public_user_id}\n\n"
        "Set your password using this one-time link:\n"
        f"{setup_url}\n\n"
        "The link expires in 24 hours. If it expires, contact the "
        "administrator to request a new setup link. Never share this link.\n"
    )

    port = current_app.config["MAIL_PORT"]
    username = current_app.config["MAIL_USERNAME"]
    password = current_app.config["MAIL_PASSWORD"]
    if current_app.config["MAIL_USE_SSL"]:
        smtp_client = smtplib.SMTP_SSL(server, port, timeout=20)
    else:
        smtp_client = smtplib.SMTP(server, port, timeout=20)

    with smtp_client as smtp:
        if current_app.config["MAIL_USE_TLS"] and not current_app.config["MAIL_USE_SSL"]:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(message)
