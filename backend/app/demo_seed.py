"""Synthetic DEMO data - for APP_ENV=demo only.

Every record is fictional, flagged is_demo=true, prefixed "[DEMO]", uses reserved *.example domains and 555 phone
numbers. Records are pushed through the real pipeline (classifier, dedupe, scoring) so the UI can be evaluated,
but they are hidden from every non-demo environment and must never be used as business intelligence.
"""
import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.models import Source
from app.services.ingestion import CompanyInput, ContactInput, ShipmentInput, ingest_company, ingest_shipment

COUNTRIES = {"US": ("Houston", "1"), "CN": ("Ningbo", "86"), "VN": ("Ho Chi Minh City", "84"), "AE": ("Dubai", "971"),
             "SA": ("Jubail", "966"), "IN": ("Mumbai", "91")}
PROFILES = [
    ("Polymers Trading", "trader", "We are a plastic raw material trader. We supply virgin LLDPE film grade (MFI 1.0 g/10 min, "
     "density 0.918 g/cm3) and off-grade LDPE film grade. 200 MT available per month."),
    ("Recycling Industries", "recycler", "Recycling company. We buy LDPE film scrap and HDPE regrind. We supply reprocessed "
     "LDPE granules for extrusion grade applications."),
    ("Resin Distribution", "distributor", "Authorized distributor of HDPE blow moulding grade and LLDPE film grade resins. "
     "We offer near-prime HDPE and wide-spec LLDPE."),
    ("Film Converters", "converter", "Manufacturer of plastic bags and shrink films. We buy LDPE film grade and LLDPE film "
     "grade, requirement 150 MT per month. We are importers of polyethylene."),
    ("Petrochemicals", "manufacturer", "Petrochemical company and polyethylene producer. We produce LLDPE and HDPE for film "
     "and blow moulding applications. We export to Asia."),
    ("Impex", "trader", "General trading company, importer and exporter of off-spec LDPE, non-prime HDPE and PCR post-consumer "
     "LDPE pellets. We buy and sell polymers."),
]
FIRST = ["Asha", "Liang", "Minh", "Fatima", "Khalid", "Ravi", "Emily", "Omar", "Mei", "Arjun"]
LAST = ["Demo", "Sample", "Testwell", "Placeholder", "Mockford"]
TITLES = ["Procurement Manager", "Purchasing Manager", "Sales Manager", "Export Manager", "Managing Director",
          "Business Development Manager", "Accountant"]


def seed_demo(db, n_per_country: int = 6, seed: int = 42):
    if get_settings().app_env != "demo":
        raise SystemExit("Refusing to seed demo data: set APP_ENV=demo (and use a separate demo database).")
    rnd = random.Random(seed)
    src = db.scalar(select(Source).where(Source.key == "demo"))
    made = []
    for ci, (cc, (city, prefix)) in enumerate(COUNTRIES.items()):
        for i in range(n_per_country):
            label, ctype, text = PROFILES[(i + ci) % len(PROFILES)]
            name = f"[DEMO] {city.split()[0]} {label} {i + 1}"
            dom = f"demo-{cc.lower()}-{i + 1}-{label.split()[0].lower()}.example"
            contacts = [ContactInput(email=f"info@{dom}", evidence="synthetic demo record"),
                        ContactInput(phone=f"+{prefix} 555 01{rnd.randint(10, 99)}", evidence="synthetic demo record")]
            if rnd.random() < 0.7:
                title = rnd.choice(TITLES)
                fn, ln = rnd.choice(FIRST), rnd.choice(LAST)
                contacts.append(ContactInput(full_name=f"{fn} {ln}", job_title=title, email=f"{fn.lower()}@{dom}",
                                             evidence="synthetic demo record"))
            out = ingest_company(db, src, CompanyInput(
                name=name, country=cc, city=city, website=f"https://{dom}",
                description=f"Synthetic demo company. {text}", classification_text=text, company_types=[ctype],
                contacts=contacts, source_url=f"https://{dom}/", is_demo=True,
                collected_at=datetime.now(timezone.utc) - timedelta(days=rnd.randint(0, 200))), use_ai=False)
            made.append((out.company_id, name, cc))
    # synthetic shipments between demo companies
    descs = [("390110", "LDPE FILM GRADE OFF GRADE"), ("390140", "LLDPE FILM GRADE PRIME"), ("390120", "HDPE BLOW MOULDING"),
             ("391510", "PE FILM SCRAP BALES")]
    for k in range(60):
        imp, exp = rnd.sample(made, 2)
        if imp[2] == exp[2]:
            continue
        hs, desc = rnd.choice(descs)
        ingest_shipment(db, src, ShipmentInput(
            external_id=f"DEMO-{k:04d}", shipment_date=date.today() - timedelta(days=rnd.randint(5, 600)),
            importer_name=imp[1], importer_country=imp[2], exporter_name=exp[1], exporter_country=exp[2], hs_code=hs,
            product_description=f"[DEMO] {desc}", weight_kg=rnd.choice([24750, 25000, 49500, 99000]),
            value=rnd.randint(20, 120) * 1000, currency="USD", is_demo=True))
    db.commit()
    print(f"Seeded {len(made)} DEMO companies and synthetic shipments (is_demo=true)")
