
from datetime import datetime, timedelta
from functools import wraps
import secrets
import os
import re
import uuid

from flask import (
    render_template, request, redirect, url_for,
    flash, session, abort, make_response, jsonify, send_from_directory,
    current_app
)
from flask_login import (
    login_user, logout_user, login_required, current_user
)
from werkzeug.security import (
    check_password_hash, generate_password_hash
)
from werkzeug.utils import secure_filename

from app import db, csrf
from app.models import Suggestion, User, ActivityLog


ALLOWED_PHOTO_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


def generate_tracking_id():
    while True:
        tracking_id = f"{secrets.randbelow(100_000_000):08d}"
        if Suggestion.query.filter_by(tracking_id=tracking_id).first() is None:
            return tracking_id


def normalize_tracking_id(tracking_id):
    tracking_id = tracking_id.strip()
    if re.fullmatch(r"\d{8}", tracking_id):
        return tracking_id
    try:
        return str(uuid.UUID(tracking_id))
    except (ValueError, AttributeError):
        return None


def save_suggestion_photo(upload):
    if not upload or not upload.filename:
        return None

    filename = secure_filename(upload.filename)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_PHOTO_EXTENSIONS:
        raise ValueError("Please upload a JPG, PNG, or WebP image.")

    stored_name = f"{secrets.token_hex(16)}.{extension}"
    upload.save(os.path.join(current_app.config["UPLOAD_FOLDER"], stored_name))
    return stored_name


def admin_required(view_function):
    @wraps(view_function)
    @login_required
    def wrapped_view(*args, **kwargs):
        if current_user.role != "admin":
            abort(403)
        return view_function(*args, **kwargs)
    return wrapped_view


def staff_required(view_function):
    @wraps(view_function)
    @login_required
    def wrapped_view(*args, **kwargs):
        if current_user.role not in ["admin", "staff"]:
            abort(403)
        return view_function(*args, **kwargs)
    return wrapped_view


def register_routes(app):

    def suggestion_payload(suggestion):
        return {
            "id": suggestion.id,
            "tracking_id": suggestion.tracking_id,
            "name": suggestion.name,
            "category": suggestion.category,
            "description": suggestion.description,
            "status": suggestion.status,
            "ward": suggestion.ward,
            "officer_remark": suggestion.officer_remark,
            "photo_url": (
                url_for("uploaded_photo", filename=suggestion.photo_filename)
                if suggestion.photo_filename else None
            ),
            "created_at": (
                suggestion.created_at.isoformat() if suggestion.created_at else None
            ),
        }

    @app.route("/uploads/<path:filename>")
    def uploaded_photo(filename):
        return send_from_directory(
            current_app.config["UPLOAD_FOLDER"],
            filename
        )

    # ---------------- HOME ----------------

    @app.route("/")
    def home():
        return render_template("index.html")

    # ---------------- SUBMIT SUGGESTION ----------------

    @app.route("/submit", methods=["GET", "POST"])
    def submit():
        if (
            current_user.is_authenticated
            and current_user.role in ["admin", "staff"]
        ):
            abort(403)

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            category = request.form.get("category", "").strip()
            ward = request.form.get("ward", "").strip()
            description = request.form.get("description", "").strip()

            if not name or not category or not description:
                flash("Please fill in all fields.", "error")
                return redirect(url_for("submit"))
            if len(name) > 100 or len(category) > 100 or len(ward) > 100:
                flash("One or more submitted fields are too long.", "error")
                return redirect(url_for("submit"))
            if len(description) > 5000:
                flash("Please keep the description under 5000 characters.", "error")
                return redirect(url_for("submit"))

            try:
                photo_filename = save_suggestion_photo(request.files.get("photo"))
            except ValueError as error:
                flash(str(error), "error")
                return redirect(url_for("submit"))

            suggestion = Suggestion(
                name=name,
                category=category,
                ward=ward or None,
                description=description,
                tracking_id=generate_tracking_id(),
                photo_filename=photo_filename
            )

            db.session.add(suggestion)
            db.session.commit()

            flash(
                f"Suggestion submitted successfully! Tracking ID: {suggestion.tracking_id}",
                "success"
            )

            return redirect(url_for("home"))

        return render_template("submit.html")

    # ---------------- JSON API ----------------

    @app.route("/api/suggestions", methods=["POST"])
    @csrf.exempt
    def api_create_suggestion():
        if (
            current_user.is_authenticated
            and current_user.role in ["admin", "staff"]
        ):
            return jsonify({
                "error": "Staff and administrator accounts cannot submit citizen suggestions"
            }), 403

        data = request.get_json(silent=True) or request.form
        name = str(data.get("name", "")).strip()
        category = str(data.get("category", "")).strip()
        ward = str(data.get("ward", "")).strip()
        description = str(data.get("description", "")).strip()

        if not name or not category or not description:
            return jsonify({
                "error": "name, category, and description are required"
            }), 400
        if len(name) > 100 or len(category) > 100 or len(ward) > 100:
            return jsonify({"error": "Submitted fields exceed the maximum length"}), 400

        try:
            photo_filename = save_suggestion_photo(request.files.get("photo"))
        except ValueError as error:
            return jsonify({"error": str(error)}), 400

        suggestion = Suggestion(
            name=name,
            category=category,
            ward=ward or None,
            description=description,
            tracking_id=generate_tracking_id(),
            photo_filename=photo_filename
        )
        db.session.add(suggestion)
        db.session.commit()

        return jsonify({
            "message": "Suggestion submitted successfully",
            "suggestion": suggestion_payload(suggestion),
        }), 201

    @app.route("/api/suggestions", methods=["GET"])
    @staff_required
    def api_list_suggestions():
        status = request.args.get("status", "").strip()
        category = request.args.get("category", "").strip()
        ward = request.args.get("ward", "").strip()
        query = Suggestion.query
        if status:
            query = query.filter(Suggestion.status == status)
        if category:
            query = query.filter(Suggestion.category == category)
        if ward:
            query = query.filter(Suggestion.ward == ward)

        suggestions = query.order_by(Suggestion.created_at.desc()).all()
        return jsonify({
            "count": len(suggestions),
            "suggestions": [suggestion_payload(item) for item in suggestions],
        })

    @app.route("/api/suggestions/<tracking_id>", methods=["GET"])
    def api_track_suggestion(tracking_id):
        normalized_id = normalize_tracking_id(tracking_id)
        if normalized_id is None:
            return jsonify({"error": "Enter a valid tracking ID"}), 400

        suggestion = Suggestion.query.filter_by(tracking_id=normalized_id).first()
        if suggestion is None:
            return jsonify({"error": "Suggestion not found"}), 404
        return jsonify({"suggestion": suggestion_payload(suggestion)})

    @app.route("/api/suggestions/<int:suggestion_id>", methods=["PATCH"])
    @csrf.exempt
    @staff_required
    def api_update_suggestion(suggestion_id):
        suggestion = db.session.get(Suggestion, suggestion_id)
        if suggestion is None:
            return jsonify({"error": "Suggestion not found"}), 404

        data = request.get_json(silent=True) or {}
        status = str(data.get("status", "")).strip()
        remark = data.get("officer_remark")
        allowed_statuses = ["Received", "In Progress", "Solved"]
        if status not in allowed_statuses:
            return jsonify({"error": "status must be Received, In Progress, or Solved"}), 400

        old_status = suggestion.status
        suggestion.status = status
        if remark is not None:
            suggestion.officer_remark = str(remark).strip()

        db.session.add(ActivityLog(
            user_id=current_user.id,
            action="Suggestion Updated",
            details=(
                f"Tracking ID: {suggestion.tracking_id}; "
                f"Status changed from {old_status} to {status}"
            )
        ))
        db.session.commit()
        return jsonify({"message": "Suggestion updated", "suggestion": suggestion_payload(suggestion)})

    @app.route("/api/suggestions/<tracking_id>", methods=["PATCH"])
    @csrf.exempt
    @staff_required
    def api_update_suggestion_by_tracking_id(tracking_id):
        normalized_id = normalize_tracking_id(tracking_id)
        if normalized_id is None:
            return jsonify({"error": "Enter a valid tracking ID"}), 400

        suggestion = Suggestion.query.filter_by(tracking_id=normalized_id).first()
        if suggestion is None:
            return jsonify({"error": "Suggestion not found"}), 404

        data = request.get_json(silent=True) or {}
        status = str(data.get("status", "")).strip()
        if status not in ["Received", "In Progress", "Solved"]:
            return jsonify({"error": "status must be Received, In Progress, or Solved"}), 400

        old_status = suggestion.status
        suggestion.status = status
        if data.get("officer_remark") is not None:
            suggestion.officer_remark = str(data["officer_remark"]).strip()

        db.session.add(ActivityLog(
            user_id=current_user.id,
            action="Suggestion Updated",
            details=(
                f"Tracking ID: {suggestion.tracking_id}; "
                f"Status changed from {old_status} to {status}"
            )
        ))
        db.session.commit()
        return jsonify({"message": "Suggestion updated", "suggestion": suggestion_payload(suggestion)})

    # ---------------- TRACK SUGGESTION ----------------

    @app.route("/track")
    def track_suggestion():
        tracking_id = request.args.get("tracking_id", "").strip()
        suggestion = None
        error = None

        if tracking_id:
            tracking_id = normalize_tracking_id(tracking_id)
            if tracking_id is None:
                error = "Enter a valid tracking ID."
            else:
                suggestion = Suggestion.query.filter_by(
                    tracking_id=tracking_id
                ).first()
                if suggestion is None:
                    error = "No suggestion was found with that tracking ID."

        return render_template(
            "track.html",
            tracking_id=tracking_id,
            suggestion=suggestion,
            error=error
        )

    # ---------------- LOGIN ----------------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("home"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            user = User.query.filter_by(username=username).first()

            if (
                user
                and user.is_active
                and user.locked_until
                and user.locked_until > datetime.utcnow()
            ):
                flash("Invalid username or password.", "error")
                return redirect(url_for("login"))

            if user and user.is_active and check_password_hash(
                user.password_hash, password
            ):
                user.failed_login_attempts = 0
                user.locked_until = None
                db.session.commit()

                login_user(user)
                session.permanent = True

                flash("Login successful.", "success")
                return redirect(url_for("home"))

            if user and user.is_active:
                user.failed_login_attempts += 1

                if user.failed_login_attempts >= 5:
                    user.locked_until = (
                        datetime.utcnow() + timedelta(minutes=15)
                    )
                    user.failed_login_attempts = 0

                db.session.commit()

            flash("Invalid username or password.", "error")

        return render_template("login.html")

    # ---------------- LOGOUT ----------------

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        flash("You have been logged out.", "success")
        return redirect(url_for("login"))

    # ---------------- CHANGE PASSWORD ----------------

    @app.route("/change-password", methods=["GET", "POST"])
    @login_required
    def change_password():
        if request.method == "POST":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not check_password_hash(
                current_user.password_hash, current_password
            ):
                flash("Current password is incorrect.", "error")

            elif len(new_password) < 8:
                flash(
                    "New password must contain at least 8 characters.",
                    "error"
                )

            elif new_password != confirm_password:
                flash("New passwords do not match.", "error")

            else:
                current_user.password_hash = generate_password_hash(
                    new_password
                )
                current_user.must_change_password = False
                db.session.commit()

                flash("Password changed successfully.", "success")
                return redirect(url_for("home"))

        return render_template("change_password.html")

    # Force users with temporary passwords to change them first.
    @app.before_request
    def require_password_change():
        if (
            current_user.is_authenticated
            and current_user.must_change_password
        ):
            allowed_endpoints = [
                "change_password",
                "logout",
                "static"
            ]

            if request.endpoint not in allowed_endpoints:
                return redirect(url_for("change_password"))

    # ---------------- STAFF DASHBOARD ----------------

    @app.route("/dashboard")
    @staff_required
    def dashboard():
        status_counts = dict(
            db.session.query(Suggestion.status, db.func.count(Suggestion.id))
            .group_by(Suggestion.status)
            .all()
        )
        statuses = ["Received", "In Progress", "Solved"]
        statuses.extend(
            status for status in status_counts if status not in statuses
        )
        status_counts = {
            status: status_counts.get(status, 0)
            for status in statuses
        }

        category_counts = (
            db.session.query(
                Suggestion.category,
                db.func.count(Suggestion.id)
            )
            .group_by(Suggestion.category)
            .order_by(Suggestion.category)
            .all()
        )

        return render_template(
            "dashboard.html",
            total_suggestions=sum(status_counts.values()),
            status_counts=status_counts,
            category_counts=category_counts
        )

    # ---------------- SUGGESTION MANAGEMENT ----------------

    @app.route("/admin/suggestions")
    @staff_required
    def manage_suggestions():
        search = request.args.get("search", "").strip()
        status = request.args.get("status", "").strip()
        category = request.args.get("category", "").strip()
        ward = request.args.get("ward", "").strip()

        query = Suggestion.query

        if search:
            search_term = f"%{search}%"

            query = query.filter(
                db.or_(
                    Suggestion.tracking_id.ilike(search_term),
                    Suggestion.name.ilike(search_term),
                    Suggestion.description.ilike(search_term)
                )
            )

        if status:
            query = query.filter(Suggestion.status == status)

        if category:
            query = query.filter(Suggestion.category == category)

        if ward:
            query = query.filter(Suggestion.ward == ward)

        suggestions = query.order_by(
            Suggestion.created_at.desc()
        ).all()

        categories = [
            item[0]
            for item in db.session.query(Suggestion.category)
            .distinct()
            .order_by(Suggestion.category)
            .all()
        ]

        wards = [
            item[0]
            for item in db.session.query(Suggestion.ward)
            .filter(Suggestion.ward.isnot(None))
            .filter(Suggestion.ward != "")
            .distinct()
            .order_by(Suggestion.ward)
            .all()
        ]

        return render_template(
            "suggestions.html",
            suggestions=suggestions,
            search=search,
            selected_status=status,
            selected_category=category,
            selected_ward=ward,
            categories=categories,
            wards=wards
        )

    # ---------------- SUGGESTION DETAILS ----------------

    @app.route("/admin/suggestions/<int:suggestion_id>")
    @staff_required
    def suggestion_detail(suggestion_id):
        suggestion = db.session.get(Suggestion, suggestion_id)

        if suggestion is None:
            abort(404)

        return render_template(
            "suggestion.html",
            suggestion=suggestion
        )

    # ---------------- UPDATE SUGGESTION ----------------

    @app.route(
        "/admin/suggestions/<int:suggestion_id>/update",
        methods=["POST"]
    )
    @staff_required
    def update_suggestion(suggestion_id):
        suggestion = db.session.get(Suggestion, suggestion_id)

        if suggestion is None:
            abort(404)

        new_status = request.form.get("status", "").strip()
        new_remark = request.form.get("officer_remark", "").strip()

        allowed_statuses = [
            "Received",
            "In Progress",
            "Solved"
        ]

        if new_status not in allowed_statuses:
            flash("Invalid suggestion status.", "error")
            return redirect(url_for(
                "suggestion_detail",
                suggestion_id=suggestion_id
            ))

        old_status = suggestion.status

        suggestion.status = new_status
        suggestion.officer_remark = new_remark

        log = ActivityLog(
            user_id=current_user.id,
            action="Suggestion Updated",
            details=(
                f"Tracking ID: {suggestion.tracking_id}; "
                f"Status changed from {old_status} to {new_status}"
            )
        )

        db.session.add(log)
        db.session.commit()

        flash("Suggestion updated successfully.", "success")

        return redirect(url_for(
            "suggestion_detail",
            suggestion_id=suggestion_id
        ))

    # ---------------- ACTIVITY LOG ----------------

    @app.route("/admin/activity")
    @admin_required
    def activity_log():
        activity_entries = (
            db.session.query(ActivityLog, User.username)
            .outerjoin(User, ActivityLog.user_id == User.id)
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
            .all()
        )

        return render_template(
            "activity_log.html",
            activity_entries=activity_entries
        )

    # ---------------- USER MANAGEMENT ----------------

    @app.route("/admin/users")
    @admin_required
    def manage_users():
        users = User.query.order_by(
            User.created_at.desc()
        ).all()

        return render_template(
            "manage_users.html",
            users=users
        )

    # ---------------- CREATE USER ----------------

    @app.route("/admin/users/create", methods=["GET", "POST"])
    @admin_required
    def create_user():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            role = request.form.get("role", "").strip()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not username or role not in ["admin", "staff"]:
                flash("Please enter valid user details.", "error")
                return redirect(url_for("create_user"))

            if User.query.filter_by(username=username).first():
                flash("Username already exists.", "error")
                return redirect(url_for("create_user"))

            if len(password) < 8:
                flash(
                    "Password must contain at least 8 characters.",
                    "error"
                )
                return redirect(url_for("create_user"))

            if password != confirm_password:
                flash("Passwords do not match.", "error")
                return redirect(url_for("create_user"))

            user = User(
                username=username,
                password_hash=generate_password_hash(password),
                role=role,
                is_active=True,
                must_change_password=True
            )

            db.session.add(user)
            db.session.flush()

            log = ActivityLog(
                user_id=current_user.id,
                action="User Created",
                details=f"Created {role} account: {username}"
            )

            db.session.add(log)
            db.session.commit()

            flash("User account created successfully.", "success")
            return redirect(url_for("manage_users"))

        return render_template("create_user.html")

    # ---------------- ACTIVATE / DEACTIVATE USER ----------------

    @app.route(
        "/admin/users/<int:user_id>/toggle",
        methods=["POST"]
    )
    @admin_required
    def toggle_user(user_id):
        user = db.session.get(User, user_id)

        if not user:
            abort(404)

        if user.id == current_user.id:
            flash(
                "You cannot deactivate your own account.",
                "error"
            )
            return redirect(url_for("manage_users"))

        if user.role == "admin" and user.is_active:
            active_admins = User.query.filter_by(
                role="admin",
                is_active=True
            ).count()

            if active_admins <= 1:
                flash(
                    "The last active administrator cannot be deactivated.",
                    "error"
                )
                return redirect(url_for("manage_users"))

        user.is_active = not user.is_active

        log = ActivityLog(
            user_id=current_user.id,
            action="User Status Changed",
            details=(
                f"{user.username} active status set to {user.is_active}"
            )
        )

        db.session.add(log)
        db.session.commit()

        flash("User status updated successfully.", "success")
        return redirect(url_for("manage_users"))

    # ---------------- RESET USER PASSWORD ----------------

    @app.route(
        "/admin/users/<int:user_id>/reset-password",
        methods=["POST"]
    )
    @admin_required
    def reset_user_password(user_id):
        user = db.session.get(User, user_id)

        if not user:
            abort(404)

        temporary_password = secrets.token_urlsafe(12)

        user.password_hash = generate_password_hash(
            temporary_password
        )
        user.must_change_password = True
        user.failed_login_attempts = 0
        user.locked_until = None

        log = ActivityLog(
            user_id=current_user.id,
            action="Password Reset",
            details=f"Password reset for user: {user.username}"
        )

        db.session.add(log)
        db.session.commit()

        response = make_response(render_template(
            "reset_password_result.html",
            username=user.username,
            temporary_password=temporary_password
        ))
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response

    # ---------------- SHOW TEMPORARY PASSWORD ----------------

    @app.route("/admin/users/reset-password-result")
    @admin_required
    def show_reset_password():
        flash(
            "Temporary passwords are displayed only once, immediately after a reset.",
            "error"
        )
        return redirect(url_for("manage_users"))
