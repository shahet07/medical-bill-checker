"""Email + password accounts.

Passwords are hashed with Argon2id. Login checks take the same time whether
or not the email exists, failures lock the account for 15 minutes after 10
attempts, and error messages never say which of email or password was wrong.
"""

import re
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .store import Store, UserRow

MIN_PASSWORD = 10
MAX_PASSWORD = 128
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

_hasher = PasswordHasher()
# Verified against when the email does not exist, so timing doesn't reveal accounts.
_DUMMY_HASH = _hasher.hash("not-a-real-password-placeholder")


class AuthError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise AuthError("invalid_email", "Please enter a valid email address.")
    return email


def check_password_rules(password: str, email: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError("weak_password", "Use at least {} characters for your password.".format(MIN_PASSWORD))
    if len(password) > MAX_PASSWORD:
        raise AuthError("weak_password", "Use at most {} characters for your password.".format(MAX_PASSWORD))
    if password.strip().lower() == email.lower() or password.lower() in email.lower():
        raise AuthError("weak_password", "Your password should not contain your email address.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def register(store: Store, email: str, password: str, research_consent: bool) -> UserRow:
    from .store import EmailTaken

    email = normalize_email(email)
    check_password_rules(password, email)
    try:
        return store.create_user(email, hash_password(password), research_consent)
    except EmailTaken:
        raise AuthError("email_taken", "An account with this email already exists. Try logging in.")


def login(store: Store, email: str, password: str) -> UserRow:
    bad = AuthError("bad_login", "Email or password is incorrect.")
    try:
        email = normalize_email(email)
    except AuthError:
        verify_password(_DUMMY_HASH, password)
        raise bad
    user = store.get_user_by_email(email)
    if user is None:
        verify_password(_DUMMY_HASH, password)
        raise bad
    if store.is_locked(user):
        raise AuthError("locked", "Too many failed attempts. Please wait 15 minutes and try again.")
    if not verify_password(user.password_hash, password):
        store.record_login(user.user_id, success=False)
        raise bad
    store.record_login(user.user_id, success=True)
    if _hasher.check_needs_rehash(user.password_hash):
        store.set_password(user.user_id, hash_password(password))
    return user


def change_password(store: Store, user: UserRow, current: str, new: str, keep_session: Optional[str] = None) -> None:
    if not verify_password(user.password_hash, current):
        raise AuthError("bad_password", "Your current password is incorrect.")
    check_password_rules(new, user.email)
    store.set_password(user.user_id, hash_password(new))
    # Log out everywhere else.
    store.delete_sessions(user.user_id, keep_token=keep_session)
