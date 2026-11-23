# Digital Suggestion Box

A modern Flask civic engagement platform for submitting, reviewing and tracking local-government suggestions.

## Features

- Public suggestion submission and private eight-digit tracking
- Citizen AI chatbot with session history
- AI-assisted title, category and description drafting
- AI priority recommendations
- AI-assisted explanation of status and officer remarks
- Staff suggestion search, filters and status updates
- Administrator account, password and activity management
- Ward, category, status and AI-priority dashboards
- CSRF protection, password hashing and role-based access
- Status history for citizen tracking
- Session chat history and new-conversation reset
- AI draft preview that requires explicit citizen approval
- Staff-only AI summaries, duplicate review and weekly reports
- Login throttling and 5 MB upload limits

## System architecture

```text
Browser
  -> Flask routes and templates
  -> Flask-Login / Flask-WTF / SQLAlchemy
  -> SQLite database
  -> Gemini API through secure server-side ai_service.py
```

Staff and citizen roles are enforced in Flask routes. Gemini API keys are read from `.env` and are never sent to browser JavaScript. AI responses are advisory and cannot update database records or citizen statuses automatically.

## Database design

- `User`: staff and administrator accounts, password hash, role and login lock fields.
- `Suggestion`: citizen details, tracking ID, category, status, ward, photo and AI priority.
- `ActivityLog`: administrative actions and status-change audit records.
- `StatusHistory`: ordered status and remark history for each suggestion.

The relationship is:

```text
User 1 ---- many ActivityLog
User 1 ---- many StatusHistory (optional changed_by)
Suggestion 1 ---- many StatusHistory
```

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app run.py db upgrade
python run.py
```

Open `http://127.0.0.1:5000`.

## Environment configuration

Copy the sample file:

```bash
cp .env.example .env
```

Configure:

- `SECRET_KEY`: a long random value
- `DATABASE_URL`: normally `sqlite:///suggestions.db`
- `APP_ENV`: `development` or `production`
- `SESSION_COOKIE_SECURE`: `true` behind HTTPS
- `GEMINI_API_KEY`: optional Google Gemini API key
- `GEMINI_MODEL`: normally `gemini-2.5-flash`

Never commit `.env` or expose API keys in browser JavaScript.

Without `GEMINI_API_KEY`, the chat still provides basic guidance for submitting
and tracking suggestions, and uses the database for a status lookup when the
citizen supplies an 8-digit tracking ID. Other AI answers require the server-side
Gemini key. Add it to `.env` and restart Flask; never put the key in browser code.
Current government schemes and policies are not verified by the assistant, so
citizens are directed to official local-government sources rather than given
guessed information.

## Database migrations

```bash
flask --app run.py db upgrade
flask --app run.py db current
flask --app run.py db heads
```

The migration head is `e6a1c9d2f804`.

## Tests

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

## Roles

- Citizens/public users can submit and track suggestions.
- Staff can view and update suggestions and view staff activity.
- Administrators can perform staff functions and manage users and account activity.
- Staff and administrators cannot submit citizen suggestions.

## JSON API

- `POST /api/suggestions` — public suggestion submission
- `GET /api/suggestions/<tracking_id>` — public tracking
- `GET /api/suggestions` — staff/admin suggestion list
- `PATCH /api/suggestions/<id>` — staff/admin status update
- `POST /api/ai/chat` — citizen chatbot
- `POST /api/ai/suggestion-draft` — citizen draft assistance
- `POST /api/ai/tracking/<tracking_id>` — citizen tracking explanation
- `POST /api/ai/chat/reset` — start a new citizen chat conversation

Example public submission:

```bash
curl -X POST http://localhost:5000/api/suggestions \
  -H 'Content-Type: application/json' \
  -d '{"name":"Alex","title":"Repair damaged crossing","category":"Roads and Infrastructure","ward":"Ward 2","description":"Repair the damaged pedestrian crossing."}'
```
