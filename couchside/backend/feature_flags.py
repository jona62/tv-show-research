"""Static, server-owned experimental eligibility; browser identity is never input."""
import json
import logging
import os
from pathlib import Path
import re

CONFIG = Path(__file__).with_name('feature-flags.json')
FEATURES = ('watch_tracking',)
ACCOUNT_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')
EMAIL = re.compile(r'[^\s@]{1,254}@[^\s@]{1,254}')
MAX_CONFIG_BYTES = 65536


def unique_object(pairs):
    """Reject duplicate JSON keys instead of accepting an ambiguous policy."""
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate feature flag key.')
        value[key] = item
    return value


class FeatureFlags:
    """Read once at process startup. Config changes require a server restart."""

    def __init__(self, path=None, *, local_development=False):
        # This is a trusted server-startup option, never a request/header value.
        # AccountRoutes permits non-HTTPS accounts only for loopback host + peer.
        self.local_development = local_development is True
        self.enabled, self.user_ids, self.emails, self.features = False, frozenset(), frozenset(), {}
        selected = Path(path if path is not None else os.environ.get('COUCHSIDE_FEATURE_FLAGS') or CONFIG)
        try:
            with selected.open('rb') as source:
                raw = source.read(MAX_CONFIG_BYTES + 1)
            if len(raw) > MAX_CONFIG_BYTES:
                raise ValueError('Feature flags are too large.')
            value = json.loads(raw, object_pairs_hook=unique_object,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            required = {'version', 'enabled', 'user_ids', 'emails', 'features'}
            if not isinstance(value, dict) or set(value) != required or type(value['version']) is not int or value['version'] != 1:
                raise ValueError('Invalid feature flag version or fields.')
            if type(value['enabled']) is not bool:
                raise ValueError('Invalid global feature switch.')
            ids, emails, flags = value['user_ids'], value['emails'], value['features']
            if not isinstance(ids, list) or len(ids) > 1000 or any(not isinstance(v, str) or not ACCOUNT_ID.fullmatch(v) for v in ids):
                raise ValueError('Invalid account allowlist.')
            if not isinstance(emails, list) or len(emails) > 1000 or any(not isinstance(v, str) or len(v) > 254 or not EMAIL.fullmatch(v) for v in emails):
                raise ValueError('Invalid email allowlist.')
            if not isinstance(flags, dict) or set(flags) - set(FEATURES) or any(type(v) is not bool for v in flags.values()):
                raise ValueError('Invalid feature switches.')
            self.enabled = value['enabled']
            self.user_ids, self.emails = frozenset(ids), frozenset(v.casefold() for v in emails)
            self.features = dict(flags)
        except (OSError, ValueError, TypeError, RecursionError):
            logging.warning('Experimental feature config is unavailable or invalid; all features disabled.')

    def eligible(self, user):
        """The caller supplies only identity obtained from a validated session."""
        if not isinstance(user, dict):
            return False
        account_id, email = user.get('id'), user.get('email')
        if not isinstance(account_id, str) or not ACCOUNT_ID.fullmatch(account_id):
            return False
        if self.local_development:
            return True
        if not self.enabled:
            return False
        return account_id in self.user_ids or isinstance(email, str) and email.casefold() in self.emails

    def enabled_for(self, user, feature='watch_tracking'):
        if feature not in FEATURES:
            return False
        return self.eligible(user) and (self.local_development or self.features.get(feature) is True)

    def envelope(self, user=None):
        account_id = user.get('id') if isinstance(user, dict) else None
        if not isinstance(account_id, str) or not ACCOUNT_ID.fullmatch(account_id):
            account_id = None
        value = {'user_id': account_id, 'experimental_allowed': self.eligible(user),
                 'features': {feature: self.enabled_for(user, feature) for feature in FEATURES}}
        if self.local_development:
            value['local_development'] = True
        return value
