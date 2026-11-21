import os
import re
import unittest
import io

os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app, db
from app.models import ActivityLog, Suggestion, User
from werkzeug.security import check_password_hash, generate_password_hash


class DigitalSuggestionBoxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
        )

    def setUp(self):
        with self.app.app_context():
            self.assertEqual(str(db.engine.url), "sqlite://")
            db.drop_all()
            db.create_all()

            self.admin = User(
                username="test-admin",
                password_hash=generate_password_hash("test-admin-password"),
                role="admin",
                is_active=True,
                must_change_password=False,
            )
            self.staff = User(
                username="test-staff",
                password_hash=generate_password_hash("test-staff-password"),
                role="staff",
                is_active=True,
                must_change_password=False,
            )
            self.suggestion = Suggestion(
                name="Test Citizen",
                category="Roads",
                description="Repair the community road.",
                status="Received",
                ward="Ward 1",
            )
            db.session.add_all([self.admin, self.staff, self.suggestion])
            db.session.commit()

            self.admin_id = self.admin.id
            self.staff_id = self.staff.id
            self.suggestion_id = self.suggestion.id
            self.tracking_id = self.suggestion.tracking_id

        self.client = self.app.test_client()

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def sign_in_as(self, user_id):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True

    def test_public_pages_submission_and_tracking(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/submit").status_code, 200)
        self.assertEqual(self.client.get("/track").status_code, 200)

        response = self.client.post(
            "/submit",
            data={
                "name": "Another Citizen",
                "category": "Water",
                "description": "Improve water supply.",
                "photo": (io.BytesIO(b"not-real-image-data"), "water.jpg"),
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Suggestion submitted successfully", response.data)

        with self.app.app_context():
            submitted = Suggestion.query.filter_by(
                name="Another Citizen"
            ).one()
            self.assertTrue(re.fullmatch(r"[0-9]{8}", submitted.tracking_id))

        tracked = self.client.get(
            "/track",
            query_string={"tracking_id": self.tracking_id.upper()},
        )
        self.assertEqual(tracked.status_code, 200)
        self.assertIn(self.tracking_id.encode(), tracked.data)
        self.assertIn(b"Roads", tracked.data)
        self.assertIn(b"Received", tracked.data)

        malformed = self.client.get(
            "/track",
            query_string={"tracking_id": "not-a-tracking-id"},
        )
        self.assertIn(b"Enter a valid tracking ID.", malformed.data)

    def test_role_permissions_and_dashboard(self):
        for path in ("/dashboard", "/admin/suggestions", "/admin/users", "/admin/activity"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/login", response.headers["Location"])

        self.sign_in_as(self.staff_id)
        self.assertEqual(self.client.get("/dashboard").status_code, 200)
        self.assertEqual(self.client.get("/admin/suggestions").status_code, 200)
        self.assertEqual(self.client.get("/admin/users").status_code, 403)
        self.assertEqual(self.client.get("/admin/activity").status_code, 403)
        self.assertEqual(self.client.get("/submit").status_code, 403)

        response = self.client.post(
            "/api/suggestions",
            json={
                "name": "Staff Member",
                "category": "Roads",
                "description": "This submission must be rejected.",
            },
        )
        self.assertEqual(response.status_code, 403)

        self.client.get("/logout")
        self.sign_in_as(self.admin_id)
        self.assertEqual(self.client.get("/admin/users").status_code, 200)
        self.assertEqual(self.client.get("/admin/activity").status_code, 200)

    def test_staff_and_admin_end_to_end_workflow(self):
        with self.app.app_context():
            staff = db.session.get(User, self.staff_id)
            staff.must_change_password = True
            db.session.commit()

        login = self.client.post(
            "/login",
            data={
                "username": "test-staff",
                "password": "test-staff-password",
            },
        )
        self.assertEqual(login.status_code, 302)
        self.assertEqual(login.headers["Location"], "/")

        forced_change = self.client.get("/dashboard")
        self.assertEqual(forced_change.status_code, 302)
        self.assertIn("/change-password", forced_change.headers["Location"])
        self.assertEqual(self.client.get("/change-password").status_code, 200)

        changed = self.client.post(
            "/change-password",
            data={
                "current_password": "test-staff-password",
                "new_password": "new-test-staff-password",
                "confirm_password": "new-test-staff-password",
            },
        )
        self.assertEqual(changed.status_code, 302)
        self.assertEqual(self.client.get("/dashboard").status_code, 200)
        self.assertEqual(self.client.get("/admin/suggestions").status_code, 200)

        updated = self.client.post(
            f"/admin/suggestions/{self.suggestion_id}/update",
            data={
                "status": "Solved",
                "officer_remark": "The repair is complete.",
            },
            follow_redirects=True,
        )
        self.assertEqual(updated.status_code, 200)
        self.assertIn(b"The repair is complete.", updated.data)

        tracked = self.client.get(
            "/track",
            query_string={"tracking_id": self.tracking_id},
        )
        self.assertEqual(tracked.status_code, 200)
        self.assertIn(b"Solved", tracked.data)
        self.assertIn(b"The repair is complete.", tracked.data)

        self.client.get("/logout")
        admin_login = self.client.post(
            "/login",
            data={
                "username": "test-admin",
                "password": "test-admin-password",
            },
        )
        self.assertEqual(admin_login.status_code, 302)
        self.assertEqual(self.client.get("/admin/users").status_code, 200)
        self.assertEqual(self.client.get("/admin/activity").status_code, 200)
        self.assertIn(
            b"Suggestion Updated",
            self.client.get("/admin/activity").data,
        )

    def test_suggestion_update_and_invalid_status(self):
        self.sign_in_as(self.staff_id)

        detail = self.client.get(
            f"/admin/suggestions/{self.suggestion_id}"
        )
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Update Status", detail.data)

        response = self.client.post(
            f"/admin/suggestions/{self.suggestion_id}/update",
            data={
                "status": "In Progress",
                "officer_remark": "The repair is being reviewed.",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Suggestion updated successfully.", response.data)

        with self.app.app_context():
            suggestion = db.session.get(Suggestion, self.suggestion_id)
            self.assertEqual(suggestion.status, "In Progress")
            self.assertEqual(
                suggestion.officer_remark,
                "The repair is being reviewed.",
            )
            self.assertEqual(
                ActivityLog.query.filter_by(
                    action="Suggestion Updated"
                ).count(),
                1,
            )

        invalid = self.client.post(
            f"/admin/suggestions/{self.suggestion_id}/update",
            data={
                "status": "Invalid",
                "officer_remark": "This must not be saved.",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Invalid suggestion status.", invalid.data)
        with self.app.app_context():
            suggestion = db.session.get(Suggestion, self.suggestion_id)
            self.assertEqual(suggestion.status, "In Progress")
            self.assertEqual(
                suggestion.officer_remark,
                "The repair is being reviewed.",
            )

    def test_dashboard_counts_statuses_and_categories(self):
        with self.app.app_context():
            db.session.add_all([
                Suggestion(
                    name="Citizen Two",
                    category="Water",
                    description="Water issue.",
                    status="Solved",
                ),
                Suggestion(
                    name="Citizen Three",
                    category="Roads",
                    description="Another road issue.",
                    status="In Progress",
                ),
            ])
            db.session.commit()

        self.sign_in_as(self.staff_id)
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Total suggestions: <strong>3</strong>", response.data)
        self.assertIn(b"Received", response.data)
        self.assertIn(b"In Progress", response.data)
        self.assertIn(b"Solved", response.data)
        self.assertIn(b"Roads", response.data)
        self.assertIn(b"Water", response.data)

    def test_deactivated_user_session_is_revoked(self):
        self.sign_in_as(self.staff_id)
        self.assertEqual(self.client.get("/admin/suggestions").status_code, 200)

        with self.app.app_context():
            staff = db.session.get(User, self.staff_id)
            staff.is_active = False
            db.session.commit()

        response = self.client.get("/admin/suggestions")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_admin_activity_log_shows_actor_and_details(self):
        with self.app.app_context():
            db.session.add(ActivityLog(
                user_id=self.admin_id,
                action="Test Action",
                details="Test activity details.",
            ))
            db.session.commit()

        self.sign_in_as(self.admin_id)
        response = self.client.get("/admin/activity")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"test-admin", response.data)
        self.assertIn(b"Test Action", response.data)
        self.assertIn(b"Test activity details.", response.data)

    def test_password_reset_does_not_store_password_in_session(self):
        self.sign_in_as(self.admin_id)
        response = self.client.post(
            f"/admin/users/{self.staff_id}/reset-password"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Pragma"], "no-cache")

        match = re.search(
            rb'<input\s+type="text"\s+value="([^"]+)"',
            response.data,
        )
        self.assertIsNotNone(match)
        temporary_password = match.group(1).decode()

        with self.app.app_context():
            staff = db.session.get(User, self.staff_id)
            self.assertTrue(
                check_password_hash(staff.password_hash, temporary_password)
            )
            self.assertTrue(staff.must_change_password)

        with self.client.session_transaction() as session:
            self.assertNotIn("reset_password_result", session)


if __name__ == "__main__":
    unittest.main()
