# Digital Suggestion Box

A Flask civic engagement platform for submitting, reviewing, and tracking community suggestions.

## Features

- Public suggestion submission with ward and category support
- Private UUID tracking for public status updates
- Staff dashboard and suggestion workflow
- Admin account, password, and activity management
- CSRF protection and role-based access control
- JSON API for integrations

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Configure `SECRET_KEY`, `DATABASE_URL`, and `SESSION_COOKIE_SECURE` through the environment or `.env`.

## JSON API

- `POST /api/suggestions` - submit a suggestion
- `GET /api/suggestions/<tracking_id>` - track a suggestion publicly
- `GET /api/suggestions` - list suggestions (staff/admin login required)
- `PATCH /api/suggestions/<id>` - update status and officer remark (staff/admin login required)

Example submission:

```bash
curl -X POST http://localhost:5000/api/suggestions \
  -H 'Content-Type: application/json' \
  -d '{"name":"Alex","category":"Roads","ward":"Ward 2","description":"Repair the damaged crossing"}'
```
