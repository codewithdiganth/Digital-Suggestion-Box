
from flask import render_template, request, redirect, url_for, flash
from app import db
from app.models import Suggestion


def register_routes(app):

    @app.route("/")
    def home():
        return render_template("index.html")

    @app.route("/submit", methods=["GET", "POST"])
    def submit():

        if request.method == "POST":

            name = request.form.get("name", "").strip()
            category = request.form.get("category", "").strip()
            description = request.form.get("description", "").strip()

            if not name or not category or not description:
                flash("Please fill in all fields.", "error")
                return redirect(url_for("submit"))

            suggestion = Suggestion(
                name=name,
                category=category,
                description=description
            )

            db.session.add(suggestion)
            db.session.commit()

            flash(
                f"Suggestion submitted successfully! Tracking ID: {suggestion.tracking_id}",
                "success"
            )

            return redirect(url_for("home"))

        return render_template("submit.html")
