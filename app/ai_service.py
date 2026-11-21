import json
import os
import time
import urllib.error
import urllib.request
from threading import Lock


FALLBACK_MESSAGE = (
    "AI service is temporarily unavailable. You can still submit a suggestion "
    "or track it with its 8-digit tracking ID. This is a general civic guide "
    "and not an official government response."
)

_request_counts = {}
_request_counts_lock = Lock()


def check_ai_rate_limit(client_key, limit=10, window_seconds=60):
    now = time.monotonic()
    with _request_counts_lock:
        timestamps = [
            timestamp
            for timestamp in _request_counts.get(client_key, [])
            if now - timestamp < window_seconds
        ]
        if len(timestamps) >= limit:
            _request_counts[client_key] = timestamps
            return False
        timestamps.append(now)
        _request_counts[client_key] = timestamps
        return True


def generate_chat_reply(message, history=None):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {
            "reply": FALLBACK_MESSAGE,
            "fallback": True,
            "provider": "offline fallback",
        }

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )

    contents = []
    for item in (history or [])[-10:]:
        role = "model" if item.get("role") == "assistant" else "user"
        text = str(item.get("text", "")).strip()
        if text:
            contents.append({
                "role": role,
                "parts": [{"text": text[:2000]}],
            })
    contents.append({
        "role": "user",
        "parts": [{"text": str(message).strip()[:1000]}],
    })

    payload = {
        "system_instruction": {
            "parts": [{
                "text": (
                    "You are a friendly AI civic-help assistant for a local "
                    "Digital Suggestion Box. Give simple, beginner-friendly "
                    "guidance about roads, drainage, water supply, streetlights, "
                    "garbage collection, sanitation and public safety. Explain "
                    "what information a citizen can include when reporting an "
                    "issue. Never claim to be a government employee or provide "
                    "official decisions. Clearly tell citizens to verify urgent "
                    "or emergency matters with their local authorities."
                )
            }]
        },
        "contents": contents,
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 500,
        },
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))

        candidates = data.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        reply = "".join(
            str(part.get("text", "")).strip()
            for part in parts
            if isinstance(part, dict)
        ).strip()

        if not reply:
            raise ValueError("Gemini returned an empty response")

        return {
            "reply": reply,
            "fallback": False,
            "provider": "Gemini",
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            json.JSONDecodeError, ValueError, KeyError):
        return {
            "reply": FALLBACK_MESSAGE,
            "fallback": True,
            "provider": "offline fallback",
        }


def generate_suggestion_draft(description):
    raw_description = str(description).strip()
    categories = [
        "Roads and Infrastructure",
        "Water Supply",
        "Drainage",
        "Electricity and Streetlights",
        "Garbage Collection",
        "Sanitation",
        "Public Safety",
        "Other",
    ]

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        lowered = raw_description.lower()
        if any(word in lowered for word in ["road", "pothole", "footpath", "bridge"]):
            category = "Roads and Infrastructure"
        elif any(word in lowered for word in ["water", "pipe", "tap"]):
            category = "Water Supply"
        elif any(word in lowered for word in ["drain", "sewage", "flood"]):
            category = "Drainage"
        elif any(word in lowered for word in ["streetlight", "electric", "lamp", "power"]):
            category = "Electricity and Streetlights"
        elif any(word in lowered for word in ["garbage", "trash", "waste", "bin"]):
            category = "Garbage Collection"
        elif any(word in lowered for word in ["sanitary", "toilet", "cleaning"]):
            category = "Sanitation"
        elif any(word in lowered for word in ["crime", "unsafe", "harassment", "accident"]):
            category = "Public Safety"
        else:
            category = "Other"

        title = raw_description[:150].replace("\n", " ").strip()
        if not title:
            title = "Community improvement request"
        return {
            "title": title,
            "category": category,
            "description": raw_description,
            "fallback": True,
            "provider": "offline fallback",
        }

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    payload = {
        "system_instruction": {
            "parts": [{
                "text": (
                    "Improve a citizen's local-governance suggestion. Correct "
                    "grammar and clarity without inventing facts, locations or "
                    "government actions. Return only valid JSON with exactly "
                    "these fields: title, category, description. title must be "
                    "under 150 characters. category must be exactly one of: "
                    + ", ".join(categories)
                    + ". description must be professional and under 5000 "
                    "characters. Prefix no JSON with markdown."
                )
            }]
        },
        "contents": [{
            "role": "user",
            "parts": [{"text": raw_description[:5000]}]
        }],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 700,
            "responseMimeType": "application/json",
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))

        candidates = data.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        text = "".join(
            str(part.get("text", "")).strip()
            for part in parts
            if isinstance(part, dict)
        ).strip()
        result = json.loads(text)

        title = str(result.get("title", "")).strip()[:150]
        category = str(result.get("category", "")).strip()
        description = str(result.get("description", "")).strip()[:5000]
        if not title or not description or category not in categories:
            raise ValueError("Invalid structured suggestion response")

        return {
            "title": title,
            "category": category,
            "description": description,
            "fallback": False,
            "provider": "Gemini",
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            json.JSONDecodeError, ValueError, KeyError):
        return {
            "title": raw_description[:150].replace("\n", " ").strip(),
            "category": "Other",
            "description": raw_description,
            "fallback": True,
            "provider": "offline fallback",
        }


def generate_priority_recommendation(description):
    raw_description = str(description).strip()
    priorities = ["Low", "Medium", "High", "Urgent"]

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        lowered = raw_description.lower()
        if any(word in lowered for word in [
            "accident", "death", "fire", "electrocution", "collapse",
            "gas leak", "danger to life", "immediate danger"
        ]):
            priority = "Urgent"
            reason = "The description mentions an immediate safety risk."
        elif any(word in lowered for word in [
            "severe", "major", "blocked", "overflow", "exposed wire",
            "deep pothole", "contaminated"
        ]):
            priority = "High"
            reason = "The issue appears likely to cause significant disruption or risk."
        elif any(word in lowered for word in [
            "repair", "broken", "damaged", "not working", "pothole",
            "garbage", "leak", "streetlight"
        ]):
            priority = "Medium"
            reason = "The issue needs attention but does not clearly indicate an immediate emergency."
        else:
            priority = "Low"
            reason = "The issue appears to be a general improvement or minor concern."
        return {
            "priority": priority,
            "reason": reason,
            "fallback": True,
            "provider": "offline heuristic",
        }

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    payload = {
        "system_instruction": {
            "parts": [{
                "text": (
                    "Recommend a civic issue priority only as an assistance "
                    "label. Use exactly one value: Low, Medium, High or Urgent. "
                    "Urgent is only for immediate and severe safety risks. "
                    "Never state that emergency or government action has been "
                    "taken. Return only JSON with exactly priority and reason "
                    "fields. The reason must be one or two plain sentences."
                )
            }]
        },
        "contents": [{
            "role": "user",
            "parts": [{"text": raw_description[:5000]}]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 250,
            "responseMimeType": "application/json",
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        candidates = data.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        text = "".join(
            str(part.get("text", "")).strip()
            for part in parts
            if isinstance(part, dict)
        ).strip()
        result = json.loads(text)
        priority = str(result.get("priority", "")).strip()
        reason = str(result.get("reason", "")).strip()
        if priority not in priorities or not reason:
            raise ValueError("Invalid priority recommendation")
        return {
            "priority": priority,
            "reason": reason[:1000],
            "fallback": False,
            "provider": "Gemini",
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            json.JSONDecodeError, ValueError, KeyError):
        return {
            "priority": "Low",
            "reason": "AI priority is unavailable. Staff must assess the issue.",
            "fallback": True,
            "provider": "offline fallback",
        }


def explain_tracking_status(status, officer_remark=None):
    status = str(status).strip()
    remark = str(officer_remark or "").strip()

    fallback_explanation = {
        "Received": (
            "Your suggestion has been received and recorded. "
            "The local team has not yet started working on it."
        ),
        "In Progress": (
            "Your suggestion is being assessed or handled by the relevant team. "
            "This status does not guarantee a completion date."
        ),
        "Solved": (
            "The local team has marked the suggestion as solved. "
            "Review the officer remark for the reported update."
        ),
    }.get(status, "The suggestion status is not recognised.")

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {
            "explanation": fallback_explanation,
            "remark_explanation": (
                remark
                if remark
                else "No officer remark has been added yet."
            ),
            "fallback": True,
            "provider": "offline fallback",
        }

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    payload = {
        "system_instruction": {
            "parts": [{
                "text": (
                    "Explain one citizen suggestion status and officer remark in "
                    "simple, calm language. Use only the provided status and "
                    "remark. Do not invent information, promised dates, staff "
                    "actions or government decisions. Return only JSON with "
                    "explanation and remark_explanation fields."
                )
            }]
        },
        "contents": [{
            "role": "user",
            "parts": [{
                "text": json.dumps({
                    "status": status,
                    "officer_remark": remark,
                })
            }]
        }],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 300,
            "responseMimeType": "application/json",
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        candidates = data.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        text = "".join(
            str(part.get("text", "")).strip()
            for part in parts
            if isinstance(part, dict)
        ).strip()
        result = json.loads(text)
        explanation = str(result.get("explanation", "")).strip()
        remark_explanation = str(result.get("remark_explanation", "")).strip()
        if not explanation or not remark_explanation:
            raise ValueError("Invalid tracking explanation")
        return {
            "explanation": explanation[:1000],
            "remark_explanation": remark_explanation[:1000],
            "fallback": False,
            "provider": "Gemini",
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            json.JSONDecodeError, ValueError, KeyError):
        return {
            "explanation": fallback_explanation,
            "remark_explanation": (
                remark
                if remark
                else "No officer remark has been added yet."
            ),
            "fallback": True,
            "provider": "offline fallback",
        }
