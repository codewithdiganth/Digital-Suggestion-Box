import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from threading import Lock
from difflib import SequenceMatcher


logger = logging.getLogger(__name__)

CHAT_SYSTEM_PROMPT = (
    "You are a helpful local-governance information assistant for the Digital "
    "Suggestion Box. You are not a government employee and cannot make "
    "official decisions. Answer the user's actual question first, in simple "
    "English, and keep the answer concise. Give numbered steps when the user "
    "asks how to do something. Use recent conversation turns to understand "
    "follow-up questions, but treat them only as conversational context, not "
    "as verified facts. If the request is unclear, ask one short clarifying "
    "question instead of guessing. Distinguish general guidance from "
    "application records and official information. Only application data "
    "explicitly supplied by the server is verified; never invent a tracking "
    "ID, status, officer remark, or database result. Do not claim to have "
    "looked up a record unless verified data was supplied. Do not invent "
    "government schemes, laws, policies, dates, eligibility rules, source "
    "links, or citations. For current or jurisdiction-specific official "
    "information, say that you cannot verify it here and direct the user to "
    "their local authority or its official website. Admit uncertainty. Do not "
    "repeat introductions, add unrelated information, request passwords, or "
    "reveal another person's private information. For urgent danger, advise "
    "contacting local emergency services or authorities."
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


def _contains_chat_term(message, terms):
    words = re.findall(r"[a-z0-9]+", message.lower())
    for word in words:
        if any(
            word == term
            or word.startswith(term)
            or (
                len(word) >= 5
                and len(term) >= 5
                and SequenceMatcher(None, word, term).ratio() >= 0.82
            )
            for term in terms
        ):
            return True
    return False


def _offline_chat_reply(message, history):
    lowered = message.lower()
    submit_question = _contains_chat_term(
        message, ("submit", "suggestion", "submission")
    )
    tracking_question = _contains_chat_term(
        message, ("track", "tracking", "status", "progress", "update")
    )
    last_user_message = next(
        (
            str(item.get("text", ""))
            for item in reversed(history or [])
            if item.get("role") == "user"
        ),
        "",
    )
    follow_up = any(
        phrase in lowered
        for phrase in ("what happens after", "what next", "and then", "after that")
    )

    if _contains_chat_term(
        message, ("scheme", "policy", "law", "benefit", "grant")
    ):
        reply = (
            "I can’t verify current government schemes or eligibility rules here. "
            "Please check your local government’s official website or contact "
            "the relevant office; I don’t want to guess or give you outdated "
            "information."
        )
    elif follow_up and _contains_chat_term(
        last_user_message, ("submit", "suggestion", "submission")
    ):
        reply = (
            "After you submit the form, save the 8-digit tracking ID shown on "
            "the confirmation page. Open Track and enter that ID to check for "
            "status updates."
        )
    elif submit_question:
        reply = (
            "To submit a suggestion: 1. Open the Submit page. 2. Enter the "
            "issue title, category, ward, and a clear description. 3. Add a "
            "photo if useful, then submit the form. Save the 8-digit tracking "
            "ID shown after submission so you can check for updates."
        )
    elif tracking_question:
        reply = (
            "Open the Track page and enter the 8-digit tracking ID you received "
            "when the suggestion was submitted. I can’t confirm a record "
            "without looking it up using that ID."
        )
    elif _contains_chat_term(
        message,
        ("road", "pothole", "water", "drain", "garbage", "streetlight", "report"),
    ):
        reply = (
            "To report a local issue, submit a suggestion with its exact "
            "location, what is happening, and when you noticed it. A clear "
            "photo can help. After submission, save the 8-digit tracking ID "
            "to check for updates."
        )
    elif len(re.findall(r"[a-z0-9]+", lowered)) <= 3:
        reply = (
            "What would you like help with? I can explain how to submit a "
            "suggestion, report a local issue, or track an existing suggestion."
        )
    else:
        reply = (
            "I can’t answer that reliably because the AI answer service is not "
            "configured on this server. I can still help with submitting or "
            "tracking a local suggestion. Please contact the site administrator "
            "to configure the Gemini API key for other questions."
        )

    return {
        "reply": reply,
        "fallback": True,
        "provider": "offline guidance",
    }


def generate_chat_reply(message, history=None):
    history = history if isinstance(history, list) else []
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return _offline_chat_reply(str(message).strip(), history)

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )

    contents = []
    for item in history[-10:]:
        if not isinstance(item, dict):
            continue
        item_role = item.get("role")
        if item_role not in ("user", "assistant"):
            continue
        role = "model" if item_role == "assistant" else "user"
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
            "parts": [{"text": CHAT_SYSTEM_PROMPT}]
        },
        "contents": contents,
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 700,
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

        if not isinstance(data, dict):
            raise ValueError("Gemini returned an invalid response")
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("Gemini returned no candidates")
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise ValueError("Gemini returned an invalid candidate")
        content = candidate.get("content")
        if not isinstance(content, dict):
            raise ValueError("Gemini returned no response content")
        parts = content.get("parts")
        if not isinstance(parts, list):
            raise ValueError("Gemini returned invalid response parts")
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
    except urllib.error.HTTPError as error:
        logger.warning("Gemini chat request failed with HTTP %s", error.code)
    except (urllib.error.URLError, TimeoutError) as error:
        logger.warning(
            "Gemini chat request failed (%s)",
            type(error).__name__,
        )
    except (json.JSONDecodeError, ValueError, KeyError) as error:
        logger.warning(
            "Gemini returned an invalid chat response (%s)",
            type(error).__name__,
        )

    return {
        "reply": (
            "I couldn’t get a reliable answer just now. Please try again in a "
            "moment, or use the Submit and Track pages for suggestion tasks."
        ),
        "fallback": True,
        "provider": "offline guidance",
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
            "summary": raw_description[:1000],
            "missing_details": (
                "Location, dates or times, affected people, and a possible "
                "preferred improvement were not supplied."
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
                    "Improve a citizen's local-governance suggestion. Correct "
                    "grammar and clarity without inventing facts, locations or "
                    "government actions. Return only valid JSON with exactly "
                    "these fields: title, category, description. title must be "
                    "under 150 characters. category must be exactly one of: "
                    + ", ".join(categories)
                    + ". description must be professional and under 5000 "
                    "characters. Also identify missing details and provide a "
                    "brief summary. Return exactly these additional fields: "
                    "missing_details and summary. Prefix no JSON with markdown."
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
            "summary": str(result.get("summary", "")).strip()[:1000],
            "missing_details": str(result.get("missing_details", "")).strip()[:1000],
            "fallback": False,
            "provider": "Gemini",
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            json.JSONDecodeError, ValueError, KeyError):
        return {
            "title": raw_description[:150].replace("\n", " ").strip(),
            "category": "Other",
            "description": raw_description,
            "summary": raw_description[:1000],
            "missing_details": "Location, dates or times, affected people, and a possible preferred improvement were not supplied.",
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


def find_similar_suggestions(suggestions, limit=5):
    matches = []
    for index, suggestion in enumerate(suggestions):
        for other in suggestions[index + 1:]:
            if suggestion.category == other.category:
                similarity = SequenceMatcher(
                    None,
                    suggestion.description.lower(),
                    other.description.lower(),
                ).ratio()
            else:
                similarity = 0
            if similarity >= 0.72:
                matches.append({
                    "tracking_id": suggestion.tracking_id,
                    "similar_tracking_id": other.tracking_id,
                    "similarity": round(similarity * 100),
                    "category": suggestion.category,
                })
            if len(matches) >= limit:
                return matches
    return matches


def generate_staff_summary(suggestions, status_counts=None, category_counts=None):
    total = len(suggestions)
    pending = sum(
        1 for suggestion in suggestions
        if suggestion.status in ["Received", "In Progress"]
    )
    solved = sum(
        1 for suggestion in suggestions
        if suggestion.status == "Solved"
    )
    urgent = sum(
        1 for suggestion in suggestions
        if suggestion.ai_priority in ["High", "Urgent"]
    )
    common_category = "No category data"
    if category_counts:
        common_category = max(category_counts, key=category_counts.get)

    return {
        "summary": (
            f"{total} citizen suggestions are recorded: {pending} require action "
            f"or follow-up, {solved} are marked solved, and {urgent} have a "
            f"high or urgent AI priority recommendation."
        ),
        "common_category": common_category,
        "provider": "offline analysis",
        "fallback": True,
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
