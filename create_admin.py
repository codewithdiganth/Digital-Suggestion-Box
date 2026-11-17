from getpass import getpass
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import User

app = create_app()

with app.app_context():

    print("=== First Admin Account Setup ===")

    username = input("Enter admin username: ").strip()

    if not username:
        print("Username cannot be empty.")
        raise SystemExit

    existing_user = User.query.filter_by(username=username).first()

    if existing_user:
        print("This username already exists.")
        raise SystemExit

    password = getpass("Enter temporary password: ")
    confirm_password = getpass("Confirm temporary password: ")

    if len(password) < 8:
        print("Password must contain at least 8 characters.")
        raise SystemExit

    if password != confirm_password:
        print("Passwords do not match.")
        raise SystemExit

    admin = User(
        username=username,
        password_hash=generate_password_hash(password),
        role="admin",
        is_active=True,
        must_change_password=True
    )

    db.session.add(admin)
    db.session.commit()

    print("Administrator account created successfully!")
    print("You must change the temporary password after your first login.")