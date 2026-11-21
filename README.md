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

Without `GEMINI_API_KEY`, AI endpoints provide clearly labeled offline fallback responses.

## Database migrations

```bash
flask --app run.py db upgrade
flask --app run.py db current
flask --app run.py db heads
```

The migration head is `d3f91a6b20ce`.

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

Example public submission:

```bash
curl -X POST http://localhost:5000/api/suggestions \
  -H 'Content-Type: application/json' \
  -d '{"name":"Alex","title":"Repair damaged crossing","category":"Roads and Infrastructure","ward":"Ward 2","description":"Repair the damaged pedestrian crossing."}'
```
