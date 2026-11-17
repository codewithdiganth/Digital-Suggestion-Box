
from app import db
from datetime import datetime
import uuid
from flask_login import UserMixin


class Suggestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    tracking_id = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4())
    )

    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)

    status = db.Column(
        db.String(30),
        default="Received",
        nullable=False
    )

    ward = db.Column(db.String(100), nullable=True)
    officer_remark = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(
        db.String(80),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(db.String(255), nullable=False)

    role = db.Column(db.String(20), nullable=False)

    is_active = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    must_change_password = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    failed_login_attempts = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    locked_until = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True
    )

    action = db.Column(db.String(100), nullable=False)

    details = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )
