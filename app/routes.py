
from datetime import datetime, timedelta
from functools import wraps
import secrets
import os
import re
import time
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
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app import db, csrf
from app.account_service import create_public_user_id
from app.ai_service import (
    check_ai_rate_limit,
    generate_chat_reply,
    generate_suggestion_draft,
    generate_priority_recommendation,
    explain_tracking_status,
    find_similar_suggestions,
    generate_staff_summary,
)
from app.models import Suggestion, User, ActivityLog, StatusHistory


ALLOWED_PHOTO_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
login_attempts = {}
login_attempts_lock = __import__("threading").Lock()


def temporary_password_response(user, temporary_password, message):
    response = make_response(render_template(
        "temporary_password.html",
        user=user,
        temporary_password=temporary_password,
        message=message,
    ))
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


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

    header = upload.stream.read(12)
    upload.stream.seek(0)
    is_jpeg = header.startswith(b"\xff\xd8\xff")
    is_png = header.startswith(b"\x89PNG\r\n\x1a\n")
    is_webp = header.startswith(b"RIFF") and header[8:12] == b"WEBP"
    valid_type = (
        (extension in {"jpg", "jpeg"} and is_jpeg)
        or (extension == "png" and is_png)
        or (extension == "webp" and is_webp)
    )
    if not valid_type:
        raise ValueError("The uploaded file is not a valid JPG, PNG, or WebP image.")

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

    @app.errorhandler(404)
    def page_not_found(error):
        return render_template("index.html"), 404

    @app.errorhandler(413)
    def upload_too_large(error):
        if request.accept_mimetypes.best == "application/json":
            return jsonify({"error": "The uploaded file is too large."}), 413
        flash("The uploaded file is too large.", "error")
        return redirect(url_for("submit"))

    @app.errorhandler(500)
    def internal_server_error(error):
        db.session.rollback()
        if request.accept_mimetypes.best == "application/json":
            return jsonify({"error": "An unexpected error occurred."}), 500
        return make_response("An unexpected error occurred.", 500)

    def suggestion_payload(suggestion):
        return {
            "id": suggestion.id,
            "tracking_id": suggestion.tracking_id,
            "name": suggestion.name,
            "title": suggestion.title,
            "category": suggestion.category,
            "description": suggestion.description,
            "ai_priority": suggestion.ai_priority,
            "ai_priority_reason": suggestion.ai_priority_reason,
            "ai_priority_provider": suggestion.ai_priority_provider,
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
            title = request.form.get("title", "").strip()
            category = request.form.get("category", "").strip()
            ward = request.form.get("ward", "").strip()
            description = request.form.get("description", "").strip()

            if not name or not title or not category or not description:
                flash("Please fill in all fields.", "error")
                return redirect(url_for("submit"))
            if (
                len(name) > 100
                or len(title) > 150
                or len(category) > 100
                or len(ward) > 100
            ):
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

            priority = generate_priority_recommendation(description)
            suggestion = Suggestion(
                name=name,
                title=title,
                category=category,
                ward=ward or None,
                description=description,
                tracking_id=generate_tracking_id(),
                photo_filename=photo_filename,
                ai_priority=priority["priority"],
                ai_priority_reason=priority["reason"],
                ai_priority_provider=priority["provider"],
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
        title = str(data.get("title", "")).strip()
        category = str(data.get("category", "")).strip()
        ward = str(data.get("ward", "")).strip()
        description = str(data.get("description", "")).strip()

        if not name or not category or not description:
            return jsonify({
                "error": "name, category, and description are required"
            }), 400
        if len(title) > 150 or len(name) > 100 or len(category) > 100 or len(ward) > 100:
            return jsonify({"error": "Submitted fields exceed the maximum length"}), 400

        try:
            photo_filename = save_suggestion_photo(request.files.get("photo"))
        except ValueError as error:
            return jsonify({"error": str(error)}), 400

        priority = generate_priority_recommendation(description)
        suggestion = Suggestion(
            name=name,
            title=title or None,
            category=category,
            ward=ward or None,
            description=description,
            tracking_id=generate_tracking_id(),
            photo_filename=photo_filename,
            ai_priority=priority["priority"],
            ai_priority_reason=priority["reason"],
            ai_priority_provider=priority["provider"],
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

        db.session.add(StatusHistory(
            suggestion_id=suggestion.id,
            status=status,
            remark=suggestion.officer_remark,
            changed_by=current_user.id,
        ))
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
            status_history=(
                StatusHistory.query.filter_by(
                    suggestion_id=suggestion.id
                ).order_by(StatusHistory.created_at.asc()).all()
                if suggestion else []
            ),
            error=error
        )

    @app.route("/api/ai/tracking/<tracking_id>", methods=["POST"])
    def ai_tracking_explanation(tracking_id):
        normalized_id = normalize_tracking_id(tracking_id)
        if normalized_id is None:
            return jsonify({"error": "Enter a valid tracking ID"}), 400

        suggestion = Suggestion.query.filter_by(tracking_id=normalized_id).first()
        if suggestion is None:
            return jsonify({"error": "Suggestion not found"}), 404

        client_key = session.get("_ai_tracking_client")
        if not client_key:
            client_key = uuid.uuid4().hex
            session["_ai_tracking_client"] = client_key
        if not check_ai_rate_limit(
            f"tracking:{request.remote_addr}:{client_key}",
            limit=6,
        ):
            return jsonify({
                "error": "Too many tracking explanations. Please try again later."
            }), 429

        result = explain_tracking_status(
            suggestion.status,
            suggestion.officer_remark,
        )
        return jsonify(result)

    # ---------------- AI CHAT ASSISTANT ----------------

    @app.route("/api/ai/chat", methods=["POST"])
    def ai_chat():
        data = request.get_json(silent=True) or {}
        message = str(data.get("message", "")).strip()

        if not message:
            return jsonify({"error": "Please enter a message."}), 400
        if len(message) > 1000:
            return jsonify({
                "error": "Please keep your message under 1000 characters."
            }), 400

        client_key = session.get("_ai_chat_client")
        if not client_key:
            client_key = uuid.uuid4().hex
            session["_ai_chat_client"] = client_key
        client_key = f"{request.remote_addr}:{client_key}"
        if not check_ai_rate_limit(client_key):
            return jsonify({
                "error": "Too many AI requests. Please wait a minute and try again."
            }), 429

        history = session.get("ai_chat_history", [])
        tracking_match = re.search(r"(?<!\d)(\d{8})(?!\d)", message)
        tracking_question = re.search(
            r"\b(track(?:ing)?|status|progress|update)\b",
            message,
            re.IGNORECASE,
        )
        if tracking_match and tracking_question:
            suggestion = Suggestion.query.filter_by(
                tracking_id=tracking_match.group(1)
            ).first()
            if suggestion is None:
                result = {
                    "reply": (
                        "I couldn’t find a suggestion with that tracking ID. "
                        "Please check the 8 digits and try again."
                    ),
                    "fallback": True,
                    "provider": "application database",
                }
            else:
                result = {
                    "reply": (
                        f"The current status for tracking ID "
                        f"{suggestion.tracking_id} is {suggestion.status}. "
                        "For the latest update, open the Track page and enter "
                        "your ID."
                    ),
                    "fallback": True,
                    "provider": "application database",
                }
        else:
            result = generate_chat_reply(message, history)

        history.append({"role": "user", "text": message[:150]})
        history.append({"role": "assistant", "text": result["reply"][:150]})
        session["ai_chat_history"] = history[-4:]

        return jsonify({
            "reply": result["reply"],
            "fallback": result["fallback"],
            "provider": result["provider"],
        })

    @app.route("/api/ai/chat/reset", methods=["POST"])
    def ai_chat_reset():
        session.pop("ai_chat_history", None)
        session.pop("_ai_chat_client", None)
        return jsonify({"message": "A new conversation has started."}), 200

    @app.route("/api/ai/suggestion-draft", methods=["POST"])
    def ai_suggestion_draft():
        if (
            current_user.is_authenticated
            and current_user.role in ["admin", "staff"]
        ):
            return jsonify({
                "error": "AI drafting is available only for public citizens."
            }), 403

        data = request.get_json(silent=True) or {}
        description = str(data.get("description", "")).strip()
        if not description:
            return jsonify({"error": "Please describe the civic issue first."}), 400
        if len(description) > 5000:
            return jsonify({
                "error": "Please keep the description under 5000 characters."
            }), 400

        client_key = session.get("_ai_draft_client")
        if not client_key:
            client_key = uuid.uuid4().hex
            session["_ai_draft_client"] = client_key
        if not check_ai_rate_limit(f"draft:{request.remote_addr}:{client_key}", limit=6):
            return jsonify({
                "error": "Too many AI draft requests. Please wait and try again."
            }), 429

        result = generate_suggestion_draft(description)
        priority = generate_priority_recommendation(description)
        result.update({
            "priority": priority["priority"],
            "priority_reason": priority["reason"],
            "priority_provider": priority["provider"],
        })
        return jsonify(result)

    # ---------------- LOGIN ----------------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            if current_user.role in ["admin", "staff"]:
                return redirect(url_for("dashboard"))
            return redirect(url_for("home"))

        if request.method == "POST":
            identifier = request.form.get(
                "identifier",
                request.form.get("username", ""),
            ).strip()
            password = request.form.get("password", "")
            mobile_identifier = re.sub(r"[\s().-]", "", identifier)
            rate_limit_identifier = (
                mobile_identifier
                if re.fullmatch(r"\+?[1-9]\d{6,14}", mobile_identifier)
                else identifier.lower()
            )
            login_key = (
                f"login:{request.remote_addr}:{rate_limit_identifier}"
            )
            now = time.monotonic()
            with login_attempts_lock:
                timestamps = [
                    timestamp
                    for timestamp in login_attempts.get(login_key, [])
                    if now - timestamp < 900
                ]
                if len(timestamps) >= 5:
                    login_attempts[login_key] = timestamps
                    flash("Too many login attempts. Please try again later.", "error")
                    return redirect(url_for("login"))
                timestamps.append(now)
                login_attempts[login_key] = timestamps

            user = User.query.filter(
                or_(
                    User.username == identifier,
                    db.func.lower(User.public_user_id) == identifier.lower(),
                )
            ).first()
            if user is None:
                username_match = User.query.filter(
                    db.func.lower(User.username) == identifier.lower()
                ).first()
                user = username_match
            if user is None:
                if re.fullmatch(r"\+?[1-9]\d{6,14}", mobile_identifier):
                    user = User.query.filter_by(
                        mobile_number=mobile_identifier
                    ).first()

            if (
                user
                and user.is_active
                and user.locked_until
                and user.locked_until > datetime.utcnow()
            ):
                flash("Invalid User ID or password.", "error")
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
                if user.role in ["admin", "staff"]:
                    return redirect(url_for("dashboard"))
                return redirect(url_for("home"))

            if user and user.is_active:
                user.failed_login_attempts += 1

                if user.failed_login_attempts >= 5:
                    user.locked_until = (
                        datetime.utcnow() + timedelta(minutes=15)
                    )
                    user.failed_login_attempts = 0

                db.session.commit()

            flash("Invalid User ID or password.", "error")

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
                if current_user.role in ["admin", "staff"]:
                    return redirect(url_for("dashboard"))
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
        ward_counts = (
            db.session.query(
                Suggestion.ward,
                db.func.count(Suggestion.id)
            )
            .filter(Suggestion.ward.isnot(None))
            .filter(Suggestion.ward != "")
            .group_by(Suggestion.ward)
            .order_by(Suggestion.ward)
            .all()
        )
        priority_counts = dict(
            db.session.query(Suggestion.ai_priority, db.func.count(Suggestion.id))
            .filter(Suggestion.ai_priority.isnot(None))
            .group_by(Suggestion.ai_priority)
            .all()
        )
        high_priority_count = Suggestion.query.filter(
            Suggestion.ai_priority.in_(["High", "Urgent"])
        ).count()
        recent_activity = (
            db.session.query(ActivityLog, User.username)
            .outerjoin(User, ActivityLog.user_id == User.id)
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
            .limit(8)
            .all()
        )
        all_suggestions = Suggestion.query.all()
        week_start = datetime.utcnow() - timedelta(days=7)
        weekly_suggestions = Suggestion.query.filter(
            Suggestion.created_at >= week_start
        ).all()
        weekly_category_counts = dict(
            db.session.query(
                Suggestion.category,
                db.func.count(Suggestion.id),
            )
            .filter(Suggestion.created_at >= week_start)
            .group_by(Suggestion.category)
            .all()
        )
        weekly_report = {
            "received": len(weekly_suggestions),
            "pending": sum(
                1 for suggestion in all_suggestions
                if suggestion.status in ["Received", "In Progress"]
            ),
            "completed": sum(
                1 for suggestion in all_suggestions
                if suggestion.status == "Solved"
            ),
            "common_category": (
                max(weekly_category_counts, key=weekly_category_counts.get)
                if weekly_category_counts else "No submissions"
            ),
        }
        staff_summary = generate_staff_summary(
            all_suggestions,
            status_counts=status_counts,
            category_counts=dict(category_counts),
        )
        similar_suggestions = find_similar_suggestions(all_suggestions)

        return render_template(
            "dashboard.html",
            total_suggestions=sum(status_counts.values()),
            status_counts=status_counts,
            category_counts=category_counts,
            ward_counts=ward_counts,
            category_max=max([count for _, count in category_counts] or [0]),
            ward_max=max([count for _, count in ward_counts] or [0]),
            priority_counts={
                priority: priority_counts.get(priority, 0)
                for priority in ["Low", "Medium", "High", "Urgent"]
            },
            high_priority_count=high_priority_count,
            recent_activity=recent_activity,
            staff_summary=staff_summary,
            similar_suggestions=similar_suggestions,
            weekly_report=weekly_report,
        )

    # ---------------- SUGGESTION MANAGEMENT ----------------

    @app.route("/admin/suggestions")
    @staff_required
    def manage_suggestions():
        search = request.args.get("search", "").strip()
        status = request.args.get("status", "").strip()
        category = request.args.get("category", "").strip()
        ward = request.args.get("ward", "").strip()
        priority = request.args.get("priority", "").strip()

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
        if priority:
            query = query.filter(Suggestion.ai_priority == priority)

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
            selected_priority=priority,
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

        db.session.add(StatusHistory(
            suggestion_id=suggestion.id,
            status=new_status,
            remark=new_remark,
            changed_by=current_user.id,
        ))
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

    @app.route("/staff/activity")
    @staff_required
    def staff_activity_log():
        activity_entries = (
            db.session.query(ActivityLog, User.username)
            .outerjoin(User, ActivityLog.user_id == User.id)
            .filter(ActivityLog.action.in_(["Suggestion Updated"]))
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
            .all()
        )
        return render_template(
            "activity_log.html",
            activity_entries=activity_entries,
            staff_view=True
        )

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
        search = request.args.get("q", "").strip()[:100]
        query = User.query
        if search:
            pattern = f"%{search}%"
            query = query.filter(or_(
                User.full_name.ilike(pattern),
                User.mobile_number.ilike(pattern),
                User.public_user_id.ilike(pattern),
                User.username.ilike(pattern),
            ))
        users = query.order_by(
            User.created_at.desc()
        ).all()

        return render_template(
            "manage_users.html",
            users=users,
            search=search,
        )

    # ---------------- CREATE USER ----------------

    @app.route("/admin/users/create", methods=["GET", "POST"])
    @admin_required
    def create_user():
        form_data = {
            "full_name": "",
            "username": "",
            "mobile_number": "",
            "role": "citizen",
        }

        if request.method == "POST":
            form_data = {
                "full_name": request.form.get("full_name", "").strip(),
                "username": request.form.get("username", "").strip(),
                "mobile_number": request.form.get("mobile_number", ""),
                "role": request.form.get("role", "citizen").strip(),
            }
            full_name = form_data["full_name"]
            username = form_data["username"]
            mobile_number = re.sub(
                r"[\s().-]",
                "",
                form_data["mobile_number"],
            )
            role = form_data["role"]

            if not full_name or len(full_name) > 100:
                flash("Enter a name between 1 and 100 characters.", "error")
                return render_template(
                    "create_user.html",
                    form_data=form_data,
                )

            if role not in {"citizen", "staff"}:
                flash("Choose a valid user role.", "error")
                return render_template(
                    "create_user.html",
                    form_data=form_data,
                )

            if not re.fullmatch(
                r"\+?[1-9]\d{6,14}", mobile_number
            ):
                flash(
                    "Enter a valid mobile number with 7 to 15 digits, "
                    "including country code when applicable.",
                    "error",
                )
                return render_template(
                    "create_user.html",
                    form_data=form_data,
                )

            if role == "staff" and not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", username
            ):
                flash(
                    "Enter a username using 1 to 80 letters, numbers, dots, "
                    "underscores, or hyphens; it must start with a letter "
                    "or number.",
                    "error",
                )
                return render_template(
                    "create_user.html",
                    form_data=form_data,
                )

            if role == "staff" and User.query.filter(
                or_(
                    db.func.lower(User.username) == username.lower(),
                    db.func.lower(User.public_user_id) == username.lower(),
                    User.mobile_number == username,
                )
            ).first():
                flash("That username is already registered.", "error")
                return render_template(
                    "create_user.html",
                    form_data=form_data,
                )

            if User.query.filter_by(mobile_number=mobile_number).first():
                flash("An account with that mobile number already exists.", "error")
                return render_template(
                    "create_user.html",
                    form_data=form_data,
                )

            public_user_id = create_public_user_id() if role == "citizen" else None
            username = public_user_id or username.lower()
            temporary_password = secrets.token_urlsafe(18)
            user = User(
                public_user_id=public_user_id,
                username=username,
                full_name=full_name,
                mobile_number=mobile_number,
                password_hash=generate_password_hash(temporary_password),
                role=role,
                is_active=True,
                must_change_password=True,
            )

            try:
                db.session.add(user)
                db.session.flush()
                db.session.add(ActivityLog(
                    user_id=current_user.id,
                    action="User Created",
                    details=(
                        f"Created {role} account {username} for {full_name}"
                    ),
                ))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash(
                    "That username or mobile number is already registered.",
                    "error",
                )
                return render_template(
                    "create_user.html",
                    form_data=form_data,
                )

            return temporary_password_response(
                user,
                temporary_password,
                "Account created successfully. Share this temporary password "
                "with the user through a secure channel. It will not be shown again.",
            )

        return render_template(
            "create_user.html",
            form_data=form_data,
        )

    @app.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
    @admin_required
    def edit_user(user_id):
        user = db.session.get(User, user_id)
        if user is None:
            abort(404)

        if request.method == "POST":
            full_name = request.form.get("full_name", "").strip()
            username = request.form.get("username", "").strip()
            mobile_number = re.sub(
                r"[\s().-]",
                "",
                request.form.get("mobile_number", ""),
            )
            role = request.form.get("role", "").strip()
            allowed_roles = {"citizen", "staff", "admin"}

            if not full_name or len(full_name) > 100:
                flash("Enter a name between 1 and 100 characters.", "error")
                return redirect(url_for("edit_user", user_id=user.id))
            if not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", username
            ):
                flash("Enter a valid username.", "error")
                return redirect(url_for("edit_user", user_id=user.id))
            if not re.fullmatch(r"\+?[1-9]\d{6,14}", mobile_number):
                flash("Enter a valid mobile number.", "error")
                return redirect(url_for("edit_user", user_id=user.id))
            if role not in allowed_roles:
                flash("Choose a valid user role.", "error")
                return redirect(url_for("edit_user", user_id=user.id))
            if user.id == current_user.id and role != user.role:
                flash("You cannot change your own account role.", "error")
                return redirect(url_for("edit_user", user_id=user.id))
            if (
                user.role == "admin"
                and role != "admin"
                and user.is_active
                and User.query.filter_by(role="admin", is_active=True).count() <= 1
            ):
                flash("The last active administrator cannot be demoted.", "error")
                return redirect(url_for("edit_user", user_id=user.id))

            duplicate_contact = User.query.filter(
                User.id != user.id,
                or_(
                    db.func.lower(User.username) == username.lower(),
                    db.func.lower(User.public_user_id) == username.lower(),
                    User.mobile_number == mobile_number,
                ),
            ).first()
            if duplicate_contact:
                flash(
                    "That username or mobile number belongs to another account.",
                    "error",
                )
                return redirect(url_for("edit_user", user_id=user.id))

            old_role = user.role
            user.full_name = full_name
            user.username = username
            user.mobile_number = mobile_number
            user.role = role
            try:
                db.session.add(ActivityLog(
                    user_id=current_user.id,
                    action="User Updated",
                    details=(
                        f"Updated account {user.public_user_id or user.username}; "
                        f"role {old_role} -> {role}"
                    ),
                ))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("The mobile number is already registered.", "error")
                return redirect(url_for("edit_user", user_id=user.id))

            if old_role != role:
                current_app.logger.info(
                    "Administrator %s changed role for user %s from %s to %s",
                    current_user.id,
                    user.id,
                    old_role,
                    role,
                )
            flash("User details updated successfully.", "success")
            return redirect(url_for("manage_users"))

        return render_template("edit_user.html", user=user)

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

        if not user.is_active:
            flash("Reactivate this account before resetting its password.", "error")
            return redirect(url_for("manage_users"))

        temporary_password = secrets.token_urlsafe(18)
        user.password_hash = generate_password_hash(temporary_password)
        user.must_change_password = True
        user.setup_token_nonce = None
        user.failed_login_attempts = 0
        user.locked_until = None
        db.session.add(ActivityLog(
            user_id=current_user.id,
            action="Password Reset",
            details=(
                f"Temporary password generated for "
                f"{user.public_user_id or user.username}"
            ),
        ))
        db.session.commit()
        return temporary_password_response(
            user,
            temporary_password,
            "Password reset successfully. Share this temporary password with "
            "the user through a secure channel. It will not be shown again.",
        )
