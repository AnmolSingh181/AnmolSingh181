"""DB-backed configurable settings (lead scoring weights, refresh schedule) with code defaults."""
import copy

from sqlalchemy.orm import Session

from app.data.reference import DEFAULT_SETTINGS
from app.models import AppSetting


def get_setting(db: Session, key: str) -> dict:
    row = db.get(AppSetting, key)
    base = copy.deepcopy(DEFAULT_SETTINGS.get(key, {}))
    if row:
        base.update(row.value)
    return base


def set_setting(db: Session, key: str, value: dict) -> dict:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.flush()
    return get_setting(db, key)
