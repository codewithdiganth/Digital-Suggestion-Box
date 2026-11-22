
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from config import Config

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()


def create_app():
    app = Flask(__name__, instance_relative_config=True)

    app.config.from_object(Config)
    if os.environ.get("APP_ENV", "development").lower() == "production":
        if not app.config.get("SECRET_KEY"):
            raise RuntimeError("SECRET_KEY is required when APP_ENV=production")

    os.makedirs(app.instance_path, exist_ok=True)
    app.config.setdefault(
        "UPLOAD_FOLDER",
        os.path.join(app.instance_path, "uploads")
    )
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)

    login_manager.init_app(app)
    login_manager.login_view = "login"
    login_manager.login_message = "Please log in to access this page."

    csrf.init_app(app)

    with app.app_context():
        from app import models

    from app import routes
    routes.register_routes(app)

    return app


@login_manager.user_loader
def load_user(user_id):
    from app.models import User

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None

    user = db.session.get(User, user_id)
    if user is None or not user.is_active:
        return None

    return user
