from email_validator import EmailNotValidError, validate_email


def normalize_email(value):
    email = (value or "").strip()
    if not email or len(email) > 254:
        return None

    try:
        validated = validate_email(email, check_deliverability=False)
    except EmailNotValidError:
        return None

    return validated.normalized.lower()
