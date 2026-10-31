"""Authentication. AUTH_MODE=local: users table + bcrypt + HS256 JWT issued by /auth/login.
AUTH_MODE=supabase: verify Supabase Auth JWTs (HS256 secret or JWKS) and map to a users row by email."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User, UserActivity

bearer = HTTPBearer(auto_error=False)
_jwks_client = None


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str | None) -> bool:
    return bool(hashed) and bcrypt.checkpw(pw.encode(), hashed.encode())


def issue_token(user: User) -> str:
    s = get_settings()
    payload = {"sub": str(user.id), "email": user.email, "role": user.role,
               "exp": datetime.now(timezone.utc) + timedelta(hours=s.jwt_expiry_hours)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def _decode(token: str) -> dict:
    s = get_settings()
    if s.auth_mode == "supabase":
        global _jwks_client
        if s.supabase_jwks_url:
            if _jwks_client is None:
                _jwks_client = jwt.PyJWKClient(s.supabase_jwks_url)
            key = _jwks_client.get_signing_key_from_jwt(token).key
            return jwt.decode(token, key, algorithms=["RS256", "ES256"], audience="authenticated")
        return jwt.decode(token, s.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
    return jwt.decode(token, s.jwt_secret, algorithms=["HS256"])


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        claims = _decode(creds.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}")
    s = get_settings()
    if s.auth_mode == "supabase":
        email = (claims.get("email") or "").lower()
        user = db.scalar(select(User).where(User.external_auth_id == claims["sub"])) or \
            db.scalar(select(User).where(User.email == email))
        if not user:  # first login of an invited Supabase user -> viewer until promoted by an admin
            user = User(email=email, external_auth_id=claims["sub"], auth_provider="supabase", role="viewer")
            db.add(user)
            db.commit()
    else:
        user = db.get(User, claims.get("sub"))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or not found")
    return user


def require_role(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role: {', '.join(roles)}")
        return user
    return dep


require_admin = require_role("admin")
require_editor = require_role("admin", "analyst")


def log_activity(db: Session, user: User | None, action: str, entity_type: str | None = None,
                 entity_id: str | None = None, details: dict | None = None):
    db.add(UserActivity(user_id=user.id if user else None, action=action, entity_type=entity_type,
                        entity_id=entity_id, details=details or {}))
