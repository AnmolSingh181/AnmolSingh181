"""FastAPI application. Interactive API docs at /docs (Swagger) and /redoc."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import admin, companies, contacts, leads, misc, prices, trade
from app.config import get_settings
from app.db import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()
app = FastAPI(
    title="Global Plastic Trading Intelligence API",
    version="0.1.0",
    description="B2B intelligence for LDPE / LLDPE / HDPE (virgin, near-prime, off-grade, recycled) and market price "
                "tracking for commodity polymers across India, China, the USA and other markets. "
                "All records are traceable to their source; nothing is fabricated.",
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

for r in (misc.router, admin.router, companies.router, contacts.router, trade.router, leads.router,
          prices.router):
    app.include_router(r)


@app.get("/health", tags=["meta"])
def health():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        ok = True
    except Exception:
        ok = False
    finally:
        db.close()
    return {"status": "ok" if ok else "degraded", "database": ok, "env": settings.app_env}
