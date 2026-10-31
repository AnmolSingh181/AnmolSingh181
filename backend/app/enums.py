"""Controlled vocabularies. Stored as text + CHECK constraints so new values only need a migration
that widens the constraint (no Postgres ENUM type juggling)."""

COMPANY_TYPES = [
    "manufacturer",      # resin producer (polymerisation) - NOT finished-product makers
    "producer",
    "trader",
    "distributor",
    "importer",
    "exporter",
    "recycler",
    "processor",         # compounder / reprocessor
    "converter",         # makes films, bags, pipes, bottles etc. from resin
    "scrap_aggregator",
]

GRADE_CATEGORIES = [
    "virgin_prime",
    "near_prime",
    "off_grade",
    "off_spec",
    "non_prime_unspecified",  # "non-prime": near-prime OR off-grade - needs context/review
    "recycled",
    "reprocessed",
    "pcr",
    "pir",
    "scrap",
    "unknown",
]

APPLICATIONS = [
    "film",
    "extrusion",
    "blow_moulding",
    "injection_moulding",
    "rotomoulding",
    "pipe",
    "raffia_tape",
    "wire_cable",
    "coating",
    "other",
    "unknown",
]

RELATIONSHIPS = [
    "buyer",
    "seller",
    "both",
    "manufacturer",
    "historical_buyer",
    "historical_seller",
    "unknown",
]

MATERIAL_FORMS = ["pellets", "granules", "flakes", "bales", "regrind", "lumps", "powder", "rolls", "film_scrap", "other"]

CLASSIFICATION_METHODS = ["rule", "ai", "manual", "trade_data", "import"]
REVIEW_STATUSES = ["auto", "needs_review", "confirmed", "rejected"]

CONTACT_TYPES = ["general", "individual"]
DECISION_ROLES = ["confirmed_decision_maker", "likely_decision_maker", "unknown_authority"]
CONTACT_VERIFICATION_STATUSES = [
    "discovered",
    "syntax_checked",
    "domain_checked",
    "email_verified",      # only via an authorised verification provider
    "phone_checked",
    "manually_verified",
    "invalid",
    "outdated",
]
VERIFICATION_CHECK_TYPES = ["syntax", "domain_mx", "provider_email", "phone_format", "manual"]
VERIFICATION_RESULTS = ["pass", "fail", "unknown"]

COMPANY_STATUSES = ["active", "merged", "opted_out", "archived"]

SOURCE_TYPES = ["trade_database", "directory", "website", "search_api", "government", "enrichment", "manual_import", "ai"]
ACCESS_METHODS = ["api", "export_import", "scrape", "manual"]
SOURCE_STATUSES = ["active", "awaiting_credentials", "requires_terms_review", "disabled", "error", "manual_only"]

JOB_STATUSES = ["queued", "running", "succeeded", "partial", "failed", "cancelled"]
RAW_STATUSES = ["pending", "processed", "failed", "skipped"]

LEAD_STAGES = ["new", "researching", "contacted", "interested", "negotiation", "converted", "not_interested"]
LEAD_TYPES = ["potential_buyer", "potential_supplier", "both", "unknown"]
LEAD_PRIORITIES = ["high", "medium", "low"]

DUPLICATE_STATUSES = ["pending", "merged", "rejected"]
PRIVACY_REQUEST_TYPES = ["opt_out", "correction", "deletion"]
PRIVACY_REQUEST_STATUSES = ["received", "in_progress", "completed", "rejected"]
USER_ROLES = ["admin", "analyst", "viewer"]
TRADE_FLOWS = ["import", "export"]

LOCATION_TYPES = ["headquarters", "plant", "warehouse", "office", "sales", "other"]

TARGET_POLYMERS = ["LDPE", "LLDPE", "HDPE"]


def check_in(column: str, values: list[str], nullable: bool = False) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    expr = f"{column} IN ({quoted})"
    return f"({column} IS NULL OR {expr})" if nullable else expr
