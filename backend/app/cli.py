"""Management commands.

  python -m app.cli seed-reference              # countries, materials, sources, default settings (idempotent)
  python -m app.cli create-admin EMAIL PASSWORD
  python -m app.cli seed-demo                   # ONLY when APP_ENV=demo - synthetic, clearly labelled records
  python -m app.cli run-jobs [N]                # process queued jobs once
  python -m app.cli enqueue SOURCE JOB_TYPE '{json params}'
  python -m app.cli crawl URL [COUNTRY]         # crawl one company website now
  python -m app.cli import-file PATH companies|shipments [ORIGIN_SOURCE_KEY]
  python -m app.cli rescore
  python -m app.cli evaluate                    # acceptance-criteria metrics from live data
"""
import json
import sys

from sqlalchemy import select

from app.data.reference import COUNTRIES, DEFAULT_SETTINGS, MATERIALS, SOURCES
from app.db import SessionLocal
from app.models import AppSetting, Country, Material, Source, User


def seed_reference(db):
    for code, name, region, active, prio, m49, prefix, aliases, terms in COUNTRIES:
        c = db.get(Country, code)
        if not c:
            db.add(Country(code=code, name=name, region=region, is_active=active, priority=prio, m49_code=m49,
                           phone_prefix=prefix, aliases=aliases, search_terms=terms))
        else:  # keep admin's is_active choice
            c.name, c.region, c.m49_code, c.phone_prefix, c.aliases, c.search_terms = name, region, m49, prefix, aliases, terms
    for m in MATERIALS:
        row = db.scalar(select(Material).where(Material.code == m["code"]))
        if not row:
            db.add(Material(**m))
        else:
            for k, v in m.items():
                setattr(row, k, v)
    for s in SOURCES:
        row = db.scalar(select(Source).where(Source.key == s["key"]))
        if not row:
            enabled = s["status"] == "active" and s["key"] not in ("demo",)
            db.add(Source(**s, enabled=enabled))
        else:  # refresh descriptive fields only; keep status/enabled/config set by admins
            for k in ("name", "source_type", "access_method", "base_url", "requires_credentials", "credential_env_vars",
                      "terms_notes", "pricing_notes", "refresh_interval_days"):
                setattr(row, k, s.get(k))
    for k, v in DEFAULT_SETTINGS.items():
        if not db.get(AppSetting, k):
            db.add(AppSetting(key=k, value=v))
    db.commit()
    print(f"Seeded {len(COUNTRIES)} countries, {len(MATERIALS)} materials, {len(SOURCES)} sources")


def create_admin(db, email, password):
    from app.auth import hash_password

    u = db.scalar(select(User).where(User.email == email.lower()))
    if u:
        u.password_hash, u.role, u.is_active = hash_password(password), "admin", True
    else:
        db.add(User(email=email.lower(), password_hash=hash_password(password), role="admin", full_name="Administrator"))
    db.commit()
    print(f"Admin ready: {email}")


def main(argv):
    if not argv:
        print(__doc__)
        return
    cmd, args = argv[0], argv[1:]
    db = SessionLocal()
    try:
        if cmd == "seed-reference":
            seed_reference(db)
        elif cmd == "create-admin":
            create_admin(db, args[0], args[1])
        elif cmd == "seed-demo":
            from app.demo_seed import seed_demo

            seed_demo(db)
        elif cmd == "run-jobs":
            from app.workers.runner import run_pending

            print(f"processed {run_pending(int(args[0]) if args else 10)} job(s)")
        elif cmd == "enqueue":
            from app.workers.runner import enqueue

            j = enqueue(db, args[0], args[1], json.loads(args[2]) if len(args) > 2 else {})
            db.commit()
            print(f"queued job #{j.id}")
        elif cmd == "crawl":
            from app.workers.runner import enqueue, execute

            j = enqueue(db, "company_website", "crawl_website", {"url": args[0], "country": args[1] if len(args) > 1 else None})
            db.commit()
            j = execute(db, j)
            print(j.status, j.error_message or "", json.dumps(j.log[-5:], indent=1))
        elif cmd == "import-file":
            from app.connectors.imports import CsvImportConnector, read_table

            path, kind = args[0], args[1]
            src = db.scalar(select(Source).where(Source.key == "csv_import"))
            origin = db.scalar(select(Source).where(Source.key == args[2])) if len(args) > 2 else None
            headers, rows = read_table(open(path, "rb").read(), path)
            stats = CsvImportConnector(db, src).import_rows(kind, headers, rows, origin_source=origin)
            print(f"found={stats.found} created={stats.created} updated={stats.updated} failed={stats.failed}")
        elif cmd == "rescore":
            from app.services.scoring import rescore_all

            print(f"rescored {rescore_all(db)}")
        elif cmd == "evaluate":
            from app.services.metrics import data_quality

            print(json.dumps(data_quality(db), indent=2, default=str))
        else:
            print(__doc__)
    finally:
        db.close()


if __name__ == "__main__":
    main(sys.argv[1:])
