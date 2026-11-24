# Digital Suggestion Box - Project Documentation

## 1. Problem statement

Local governance receives improvement ideas and public concerns through informal channels that are difficult to organize, track and review. The Digital Suggestion Box provides a structured public submission workflow, private tracking IDs, staff management and an AI-assisted guidance layer.

## 2. Objectives

- Allow citizens to submit, review and track suggestions.
- Prevent staff and administrators from submitting citizen suggestions.
- Give staff search, filtering, status and officer-remark tools.
- Provide explainable AI assistance without replacing official decisions.
- Preserve SQLite records and uploaded evidence.
- Provide logs, privacy controls and CSRF protection.

## 3. Workflow

1. A citizen opens the public submission page.
2. The citizen submits name, title, category, ward, description and optional photo.
3. Flask creates a unique eight-digit tracking ID.
4. Staff review the suggestion and update status or remarks.
5. Each status update creates an activity log and status-history record.
6. The citizen enters the tracking ID to view the current status.

## 4. AI architecture

Google Gemini is called only from `app/ai_service.py` on the Flask server.

AI capabilities include:

- Civic chat assistance.
- Suggestion title, description, category and missing-detail suggestions.
- Priority recommendations.
- Tracking-status explanations.
- Staff operational summaries.
- Similar-suggestion detection.
- Weekly report totals.

AI outputs are labelled advisory, and staff or citizens make final decisions.

## 5. Security design

- Werkzeug password hashing.
- Flask-Login session authentication.
- Staff and admin role decorators.
- CSRF protection on browser and staff mutation routes.
- Thirty-minute permanent-session lifetime.
- HTTP-only and SameSite session cookies.
- Account and IP/login throttling.
- 5 MB upload limit and image type/header validation.
- Server-side input length validation.
- Parameterized SQLAlchemy queries.
- Safe production-secret and error handling.

## 6. Testing

Run:

```bash
python -m unittest discover -s tests -v
```

Current automated coverage includes public pages, citizen submission, tracking, AI fallbacks and validation, role restrictions, direct staff POST rejection, dashboard totals, username/mobile login, temporary-password account creation and reset, mandatory password changes, status updates, activity logs, user deactivation, chat reset and status history.

## 7. ER diagram

```text
USER
-----
id PK
public_user_id UNIQUE
username
full_name
mobile_number UNIQUE
email UNIQUE (legacy; retained but unused)
password_hash
role
is_active
must_change_password
failed_login_attempts
locked_until
setup_token_nonce (legacy; retained but unused)
created_at

SUGGESTION
----------
id PK
tracking_id UNIQUE
name
title
category
description
status
ward
officer_remark
photo_filename
ai_priority
ai_priority_reason
ai_priority_provider
created_at

ACTIVITY_LOG
------------
id PK
user_id FK -> USER.id
action
details
created_at

STATUS_HISTORY
--------------
id PK
suggestion_id FK -> SUGGESTION.id
status
remark
changed_by FK -> USER.id
created_at
```

The legacy `email` and `setup_token_nonce` columns remain in SQLite to preserve existing records and avoid a destructive migration. They are no longer used by account creation, login, or password reset.

## 8. Presentation outline

1. Problem and objectives.
2. Existing project preserved and upgraded.
3. System architecture.
4. Citizen workflow.
5. Staff and administrator workflow.
6. AI integration and safety rules.
7. Database and migration design.
8. Security features.
9. Testing results.
10. Demo and future improvements.

## 9. Viva questions and answers

**Why Flask?** It is lightweight, Python-based and suitable for this SQLite-backed student application.

**How are users authenticated?** Flask-Login verifies server sessions; passwords are stored as hashed values.

**How does tracking work?** A secure random eight-digit tracking ID identifies a suggestion without exposing unrelated citizen data.

**How is AI kept secure?** The Gemini key remains in `.env`, and the provider is called through Flask server routes.

**Can AI change a suggestion?** No. AI draft content requires citizen approval; staff recommendations require human decisions.

**How are status updates recorded?** Each update creates a status-history row and an activity-log row.

**How is SQL injection prevented?** SQLAlchemy model queries and parameter binding are used instead of raw string SQL.
