"""Untrusted account input becomes a small, predictable domain model here."""
import math

from email_validator import EmailNotValidError, validate_email
from email_validator.deliverability import validate_email_deliverability


MAX_RATED = 3000
MAX_SAVED = 200
MAX_ID = 2**53 - 1  # IDs must survive JavaScript's number representation.
WEIGHTS = (1, .7, .35, 0, -1)
REACH = (85, 60, 0)


class AccountError(Exception):
    """A safe error for the HTTP boundary; never contains account secrets."""

    def __init__(self, status, message, *, retry_after=None, data=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after
        self.data = data


def email_address(value):
    """Return the normalized address and its case-insensitive account key."""
    if not isinstance(value, str) or len(value) > 320:
        raise AccountError(400, 'Enter a valid email address.')
    try:
        info = validate_email(value.strip(), check_deliverability=False)
    except EmailNotValidError:
        raise AccountError(400, 'Enter a valid email address.') from None
    return info, info.normalized.casefold()


def email_domain(info):
    """Accept any mail-capable domain, but retry uncertain DNS results later."""
    try:
        result = validate_email_deliverability(info.ascii_domain, info.domain, timeout=3)
    except EmailNotValidError:
        raise AccountError(400, 'Use an email address with a domain that can receive email.') from None
    if result.get('unknown-deliverability') or not result.get('mx'):
        raise AccountError(503, 'We could not check that email domain. Please try again.', retry_after=30)


def password(value):
    if not isinstance(value, str) or not 15 <= len(value) <= 128:
        raise AccountError(400, 'Use a password between 15 and 128 characters.')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        raise AccountError(400, 'Use a password containing valid Unicode text.') from None
    # Leave spaces and Unicode intact. Passwords are never stripped or normalized.
    return value


def revision(value):
    if type(value) is not int or value < 0 or value > MAX_ID:
        raise AccountError(400, 'The list revision is invalid.')
    return value


def compact_state(value):
    """Validate stored preferences and discard client display metadata."""
    invalid = AccountError(400, 'The list contains invalid preferences.')
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 3:
        raise invalid
    settings = value.get('settings')
    if not isinstance(settings, dict) or type(settings.get('known_min')) is not int or settings['known_min'] not in REACH:
        raise invalid
    if type(value.get('onboarded')) is not bool:
        raise invalid

    def entries(name, limit, rated=False):
        raw = value.get(name)
        if not isinstance(raw, list) or len(raw) > limit:
            raise invalid
        seen, out = set(), []
        for item in raw:
            if not isinstance(item, dict):
                raise invalid
            show_id = item.get('id')
            if type(show_id) is not int or not 0 < show_id <= MAX_ID or show_id in seen:
                raise invalid
            seen.add(show_id)
            clean = {'id': show_id}
            if rated:
                weight = item.get('weight')
                if type(weight) not in (int, float) or weight not in WEIGHTS or not math.isfinite(weight):
                    raise invalid
                clean['weight'] = weight
            out.append(clean)
        return out

    return {
        'version': 3,
        'profile': entries('profile', MAX_RATED, rated=True),
        'saved': entries('saved', MAX_SAVED),
        'settings': {'known_min': settings['known_min']},
        'onboarded': value['onboarded'],
    }


def compact_removed(value, state):
    """Validate explicit cancellations that a full-state snapshot cannot express."""
    if value is None:
        return {'profile': [], 'saved': []}
    invalid = AccountError(400, 'The list contains invalid removals.')
    if not isinstance(value, dict) or set(value) != {'profile', 'saved'}:
        raise invalid
    clean = {}
    for kind, limit in (('profile', MAX_RATED), ('saved', MAX_SAVED)):
        raw = value[kind]
        if not isinstance(raw, list) or len(raw) > limit:
            raise invalid
        present, seen = {item['id'] for item in state[kind]}, set()
        for show_id in raw:
            if type(show_id) is not int or not 0 < show_id <= MAX_ID or show_id in seen or show_id in present:
                raise invalid
            seen.add(show_id)
        clean[kind] = list(raw)
    return clean
