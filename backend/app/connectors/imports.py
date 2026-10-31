"""CSV / Excel import of permitted exports (ImportYeti, Volza, Panjiva, TradeData.Pro, Kompass, trade-fair lists, CRM).

Columns are auto-mapped by header synonyms; an explicit mapping can be supplied. Each row is ingested in its own
savepoint so a bad row never aborts the file. Every row is stored as a raw record for traceability.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime

from app.connectors.base import BaseConnector, JobStats
from app.services.ingestion import (CompanyInput, ContactInput, MaterialInput, ShipmentInput, ingest_company,
                                    ingest_shipment, store_raw)
from app.services.classifier import find_polymers, _matches

SHIPMENT_FIELDS = {
    "external_id": ["id", "record id", "shipment id", "bol id", "transaction id"],
    "shipment_date": ["date", "shipment date", "arrival date", "bill of lading date", "bol date", "shipping date",
                      "export date", "import date", "sb date", "be date"],
    "importer_name": ["importer", "importer name", "consignee", "consignee name", "buyer", "buyer name"],
    "importer_address": ["importer address", "consignee address", "buyer address"],
    "importer_country": ["importer country", "consignee country", "buyer country", "destination country",
                         "country of destination", "import country"],
    "exporter_name": ["exporter", "exporter name", "shipper", "shipper name", "supplier", "supplier name", "seller"],
    "exporter_address": ["exporter address", "shipper address", "supplier address"],
    "exporter_country": ["exporter country", "shipper country", "supplier country", "origin country",
                         "country of origin", "export country"],
    "port_of_loading": ["port of loading", "loading port", "pol", "foreign port", "port of lading"],
    "port_of_discharge": ["port of discharge", "discharge port", "pod", "port of unlading", "us port", "indian port"],
    "hs_code": ["hs code", "hs", "hscode", "hs_code", "tariff code", "hts code", "hts", "ritc code"],
    "product_description": ["product description", "description", "goods description", "item description",
                            "product", "commodity", "product details"],
    "quantity": ["quantity", "qty", "std quantity"],
    "quantity_unit": ["unit", "quantity unit", "uqc", "unit of measure", "std unit"],
    "weight_kg": ["weight", "weight kg", "weight (kg)", "gross weight", "net weight", "weight in kg"],
    "value": ["value", "value usd", "total value", "fob value", "cif value", "value (usd)", "total value usd", "fob usd"],
    "currency": ["currency"],
    "bill_of_lading": ["bill of lading", "bol", "bl number", "bill of lading number"],
}
COMPANY_FIELDS = {
    "name": ["company", "company name", "name", "organisation", "organization", "business name", "firm"],
    "country": ["country"],
    "state": ["state", "province", "region"],
    "city": ["city", "town"],
    "address": ["address", "full address", "street address"],
    "postal_code": ["zip", "postal code", "postcode", "pin code"],
    "website": ["website", "web", "url", "site", "domain"],
    "email": ["email", "company email", "e-mail", "general email"],
    "phone": ["phone", "telephone", "tel", "company phone", "phone number"],
    "linkedin_url": ["linkedin", "linkedin url", "company linkedin"],
    "description": ["description", "about", "business description", "products", "products & services", "activities"],
    "registration_number": ["registration number", "registration no", "cr number", "cin", "gstin", "ein", "trade license",
                            "uscc", "tax id"],
    "company_types": ["company type", "business type", "type", "category", "activity"],
    "polymer": ["polymer", "material"],
    "grade_category": ["grade", "grade category", "quality"],
    "relationship": ["relationship", "buyer/seller", "role", "intent"],
    "application": ["application"],
    "contact_name": ["contact", "contact name", "contact person", "person"],
    "contact_title": ["designation", "title", "job title", "position"],
    "contact_email": ["contact email", "person email"],
    "contact_phone": ["contact phone", "mobile", "person phone"],
    "contact_linkedin": ["contact linkedin", "person linkedin"],
}
TYPE_WORDS = {"manufacturer": "manufacturer", "producer": "producer", "trader": "trader", "trading": "trader",
              "distributor": "distributor", "importer": "importer", "exporter": "exporter", "recycler": "recycler",
              "recycling": "recycler", "processor": "processor", "compounder": "processor", "converter": "converter",
              "scrap": "scrap_aggregator"}


def _key(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (h or "").lower()).strip()


def auto_map(headers: list[str], fields: dict[str, list[str]]) -> dict[str, str]:
    norm = {_key(h): h for h in headers}
    out = {}
    for field, syns in fields.items():
        for s in syns:
            if _key(s) in norm and norm[_key(s)] not in out.values():
                out[field] = norm[_key(s)]
                break
    return out


def read_table(content: bytes, filename: str) -> tuple[list[str], list[dict]]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return [], []
        headers = [str(h).strip() if h is not None else f"col{i}" for i, h in enumerate(rows[0])]
        return headers, [dict(zip(headers, r)) for r in rows[1:] if any(v not in (None, "") for v in r)]
    text = content.decode("utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t|") if text.strip() else csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = [r for r in reader if any((v or "").strip() for v in r.values() if isinstance(v, str))]
    return list(reader.fieldnames or []), rows


def parse_date(v) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y",
                "%b %d, %Y", "%Y-%m-%dT%H:%M:%S", "%d-%b-%y", "%m/%d/%y"):
        for candidate in (s, s[:19], s[:10]):
            try:
                return datetime.strptime(candidate.strip(), fmt).date()
            except ValueError:
                continue
    return None


def _num(v) -> float | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d.\-]", "", str(v).replace(",", ""))
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _s(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


class CsvImportConnector(BaseConnector):
    key = "csv_import"
    job_types = ("import_file",)

    def import_rows(self, kind: str, headers: list[str], rows: list[dict], mapping: dict | None = None,
                    origin_source=None, is_demo: bool = False) -> JobStats:
        """origin_source: attribute records to the provider the export came from (e.g. importyeti)."""
        src = origin_source or self.source
        fields = SHIPMENT_FIELDS if kind == "shipments" else COMPANY_FIELDS
        mp = {**auto_map(headers, fields), **(mapping or {})}
        self.log(f"column mapping: {mp}")
        if kind == "shipments" and not ({"importer_name", "exporter_name"} & mp.keys()):
            raise ValueError("Shipment file needs an importer/consignee or exporter/shipper column")
        if kind == "companies" and "name" not in mp:
            raise ValueError("Company file needs a company name column")
        for i, row in enumerate(rows):
            self.stats.found += 1
            g = lambda f: row.get(mp[f]) if f in mp else None  # noqa: E731
            sp = self.db.begin_nested()
            try:
                raw, new = store_raw(self.db, src, "shipment_row" if kind == "shipments" else "company_row",
                                     {k: (str(v) if v is not None else None) for k, v in row.items()},
                                     external_id=_s(g("external_id")) if kind == "shipments" else None, job=self.job,
                                     is_demo=is_demo)
                if not new and raw.processing_status == "processed":
                    sp.commit()
                    self.stats.updated += 1
                    continue
                if kind == "shipments":
                    self._shipment(src, raw, g, is_demo)
                else:
                    self._company(src, raw, g, is_demo)
                sp.commit()
            except Exception as exc:
                sp.rollback()
                self.stats.failed += 1
                self.log(f"row {i + 2}: {exc}", "warning")
            if i % 100 == 99:
                self.db.commit()
        if kind == "shipments" and self.stats.created:
            from app.services.alerts import create_alert

            create_alert(self.db, "new_shipment", f"{self.stats.created} new shipment record(s) imported from {src.name}",
                         entity_type="source", entity_id=src.key, payload={"created": self.stats.created})
        self.db.commit()
        return self.stats

    def _shipment(self, src, raw, g, is_demo):
        data = ShipmentInput(
            external_id=_s(g("external_id")) or _s(g("bill_of_lading")), shipment_date=parse_date(g("shipment_date")),
            importer_name=_s(g("importer_name")), importer_address=_s(g("importer_address")),
            importer_country=_s(g("importer_country")), exporter_name=_s(g("exporter_name")),
            exporter_address=_s(g("exporter_address")), exporter_country=_s(g("exporter_country")),
            port_of_loading=_s(g("port_of_loading")), port_of_discharge=_s(g("port_of_discharge")),
            hs_code=re.sub(r"\D", "", str(g("hs_code") or ""))[:12] or None,
            product_description=_s(g("product_description")), quantity=_num(g("quantity")),
            quantity_unit=_s(g("quantity_unit")), weight_kg=_num(g("weight_kg")), value=_num(g("value")),
            currency=_s(g("currency")) or ("USD" if g("value") else None), bill_of_lading=_s(g("bill_of_lading")),
            is_demo=is_demo)
        _, created = ingest_shipment(self.db, src, data, raw)
        self.stats.created += int(created)
        self.stats.updated += int(not created)

    def _company(self, src, raw, g, is_demo):
        evidence_parts = [str(v) for v in (g("description"), g("polymer"), g("grade_category"), g("company_types")) if v]
        evidence = " | ".join(evidence_parts)
        types = []
        for w in re.split(r"[,/;|]", str(g("company_types") or "")):
            t = TYPE_WORDS.get(w.strip().lower().rstrip("s")) or TYPE_WORDS.get(w.strip().lower())
            if t:
                types.append(t)
        materials = []
        poly_text = str(g("polymer") or "")
        if poly_text:
            polys = {p for p, _, _ in find_polymers(poly_text)}
            grade_text = str(g("grade_category") or "")
            grades = [k for k, _ in _matches("grades", grade_text)] or ["unknown"]
            apps = [k for k, _ in _matches("applications", str(g("application") or ""))] or ["unknown"]
            rel_raw = str(g("relationship") or "").lower()
            rel = "both" if "both" in rel_raw or ("buy" in rel_raw and "sell" in rel_raw) else \
                "buyer" if "buy" in rel_raw else "seller" if ("sell" in rel_raw or "suppl" in rel_raw) else \
                "manufacturer" if "manufact" in rel_raw else "unknown"
            for p in polys:
                for gr in grades:
                    for ap in apps:
                        materials.append(MaterialInput(polymer=p, grade_category=gr, application=ap, relationship=rel,
                                                       evidence=evidence or poly_text))
        contacts = []
        if g("contact_name") or g("contact_email") or g("contact_phone") or g("contact_linkedin"):
            contacts.append(ContactInput(contact_type="individual" if g("contact_name") else "general",
                                         full_name=_s(g("contact_name")), job_title=_s(g("contact_title")),
                                         email=_s(g("contact_email")), phone=_s(g("contact_phone")),
                                         linkedin_url=_s(g("contact_linkedin")), evidence=f"Imported row from {src.name}"))
        for f in ("email", "phone"):
            if g(f):
                contacts.append(ContactInput(contact_type="general", **{f: _s(g(f))},
                                             evidence=f"Imported row from {src.name}"))
        out = ingest_company(self.db, src, CompanyInput(
            name=_s(g("name")), country=_s(g("country")), state=_s(g("state")), city=_s(g("city")),
            address=_s(g("address")), postal_code=_s(g("postal_code")), website=_s(g("website")), email=_s(g("email")),
            phone=_s(g("phone")), linkedin_url=_s(g("linkedin_url")), description=_s(g("description")),
            registration_number=_s(g("registration_number")), company_types=types, company_type_evidence=evidence or None,
            classification_text=_s(g("description")), materials=materials, contacts=contacts, is_demo=is_demo),
            raw=raw, explicit_method="import")
        self.stats.created += int(out.created)
        self.stats.updated += int(not out.created)
