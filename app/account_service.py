import secrets

from app.models import User


def create_public_user_id():
    while True:
        user_id = f"USR-{secrets.token_hex(5).upper()}"
        if not User.query.filter(
            (User.public_user_id == user_id) | (User.username == user_id)
        ).first():
            return user_id
