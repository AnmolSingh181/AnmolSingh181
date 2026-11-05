"""Normalised relational schema for the Global Plastic Trading Intelligence Platform.

Design notes
- UUID primary keys for business entities (safe to expose, easy to merge across environments).
- Controlled vocabularies are text columns guarded by CHECK constraints (see app/enums.py).
- Nothing is overwritten destructively: company_materials rows are closed (is_current=false) rather
  than deleted, raw_records keep the original payload, company_source_records keep every sighting.
- is_demo marks clearly separated demo/test records. They are hidden unless APP_ENV=demo.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app import enums as E
from app.db import Base


def _uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# ---------------------------------------------------------------- reference data
class Country(Base):
    __tablename__ = "countries"
    code: Mapped[str] = mapped_column(String(2), primary_key=True)  # ISO 3166-1 alpha-2
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    region: Mapped[str | None] = mapped_column(String(60))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    m49_code: Mapped[int | None] = mapped_column(Integer)  # UN Comtrade reporter code
    phone_prefix: Mapped[str | None] = mapped_column(String(6))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    search_terms: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)  # local-language keywords
    notes: Mapped[str | None] = mapped_column(Text)


class Material(Base):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # LDPE, LLDPE, HDPE ...
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    family: Mapped[str] = mapped_column(String(60), nullable=False, default="polyethylene")
    hs_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    synonyms: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    is_target: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------- users
class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(E.check_in("role", E.USER_ROLES), name="ck_users_role"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    auth_provider: Mapped[str] = mapped_column(String(30), default="local", nullable=False)
    external_auth_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    role: Mapped[str] = mapped_column(String(20), default="analyst", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class UserActivity(Base):
    __tablename__ = "user_activity"
    __table_args__ = (Index("ix_user_activity_user_created", "user_id", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = _created()


# ---------------------------------------------------------------- sources & jobs
class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(E.check_in("source_type", E.SOURCE_TYPES), name="ck_sources_type"),
        CheckConstraint(E.check_in("access_method", E.ACCESS_METHODS), name="ck_sources_access"),
        CheckConstraint(E.check_in("status", E.SOURCE_STATUSES), name="ck_sources_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    access_method: Mapped[str] = mapped_column(String(30), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="disabled")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_credentials: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    credential_env_vars: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    terms_notes: Mapped[str | None] = mapped_column(Text)
    pricing_notes: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    refresh_interval_days: Mapped[int | None] = mapped_column(Integer)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    total_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"
    __table_args__ = (
        CheckConstraint(E.check_in("status", E.JOB_STATUSES), name="ck_jobs_status"),
        Index("ix_jobs_status_scheduled", "status", "scheduled_for"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    records_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    log: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()

    source: Mapped[Source] = relationship()


class RawRecord(Base):
    """Untouched copy of everything collected (HTML text, API JSON, CSV row) for traceability/reprocessing."""

    __tablename__ = "raw_records"
    __table_args__ = (
        UniqueConstraint("source_id", "content_hash", name="uq_raw_source_hash"),
        CheckConstraint(E.check_in("processing_status", E.RAW_STATUSES), name="ck_raw_status"),
        Index("ix_raw_status", "processing_status"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    scrape_job_id: Mapped[int | None] = mapped_column(ForeignKey("scrape_jobs.id", ondelete="SET NULL"))
    record_type: Mapped[str] = mapped_column(String(40), nullable=False)  # web_page, website_bundle, shipment, company_row ...
    source_url: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    processing_error: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


# ---------------------------------------------------------------- companies
class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint(E.check_in("status", E.COMPANY_STATUSES), name="ck_companies_status"),
        CheckConstraint("lead_score IS NULL OR (lead_score BETWEEN 0 AND 100)", name="ck_companies_score"),
        Index("ix_companies_country_status", "country_code", "status"),
        Index("ix_companies_domain", "domain"),
        Index("ix_companies_phone", "phone_normalized"),
        Index("ix_companies_reg", "country_code", "registration_number"),
        Index("ix_companies_name_trgm", "normalized_name", postgresql_using="gin",
              postgresql_ops={"normalized_name": "gin_trgm_ops"}),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    public_ref: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False,
        server_default=text("'CMP-' || lpad(nextval('company_ref_seq')::text, 7, '0')"),
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False)
    country_code: Mapped[str | None] = mapped_column(ForeignKey("countries.code"))
    state: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(Text)
    postal_code: Mapped[str | None] = mapped_column(String(30))
    website: Mapped[str | None] = mapped_column(String(500))
    domain: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(60))
    phone_normalized: Mapped[str | None] = mapped_column(String(30))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    registration_number: Mapped[str | None] = mapped_column(String(100))
    registration_authority: Mapped[str | None] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    primary_source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    lead_score: Mapped[int | None] = mapped_column(Integer, index=True)
    lead_tier: Mapped[str | None] = mapped_column(String(30))
    lead_score_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    lead_score_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    website_last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    aliases: Mapped[list["CompanyAlias"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    locations: Mapped[list["CompanyLocation"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    classifications: Mapped[list["CompanyClassification"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    materials: Mapped[list["CompanyMaterial"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    contacts: Mapped[list["Contact"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    source_records: Mapped[list["CompanySourceRecord"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    notes: Mapped[list["CompanyNote"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class CompanyAlias(Base):
    __tablename__ = "company_aliases"
    __table_args__ = (
        UniqueConstraint("company_id", "normalized_alias", name="uq_alias_company_norm"),
        Index("ix_alias_norm", "normalized_alias"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    alias: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(300), nullable=False)
    alias_type: Mapped[str] = mapped_column(String(30), default="source_variant", nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()
    company: Mapped[Company] = relationship(back_populates="aliases")


class CompanyLocation(Base):
    __tablename__ = "company_locations"
    __table_args__ = (CheckConstraint(E.check_in("location_type", E.LOCATION_TYPES), name="ck_loc_type"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    location_type: Mapped[str] = mapped_column(String(20), default="other", nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(120))
    postal_code: Mapped[str | None] = mapped_column(String(30))
    country_code: Mapped[str | None] = mapped_column(ForeignKey("countries.code"))
    phone: Mapped[str | None] = mapped_column(String(60))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    source_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    company: Mapped[Company] = relationship(back_populates="locations")


class CompanyClassification(Base):
    """Business-type classification with evidence (a company can hold several)."""

    __tablename__ = "company_classifications"
    __table_args__ = (
        UniqueConstraint("company_id", "category", name="uq_classification_company_cat"),
        CheckConstraint(E.check_in("category", E.COMPANY_TYPES), name="ck_class_category"),
        CheckConstraint(E.check_in("method", E.CLASSIFICATION_METHODS), name="ck_class_method"),
        CheckConstraint(E.check_in("review_status", E.REVIEW_STATUSES), name="ck_class_review"),
        Index("ix_class_category", "category"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    evidence_url: Mapped[str | None] = mapped_column(Text)
    raw_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_records.id", ondelete="SET NULL"))
    review_status: Mapped[str] = mapped_column(String(20), default="auto", nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    company: Mapped[Company] = relationship(back_populates="classifications")


class CompanyMaterial(Base):
    """Which company deals in which material, how (buyer/seller) and on what evidence."""

    __tablename__ = "company_materials"
    __table_args__ = (
        CheckConstraint(E.check_in("grade_category", E.GRADE_CATEGORIES), name="ck_cm_grade"),
        CheckConstraint(E.check_in("application", E.APPLICATIONS), name="ck_cm_app"),
        CheckConstraint(E.check_in("relationship_type", E.RELATIONSHIPS), name="ck_cm_rel"),
        CheckConstraint(E.check_in("form", E.MATERIAL_FORMS, nullable=True), name="ck_cm_form"),
        CheckConstraint(E.check_in("method", E.CLASSIFICATION_METHODS), name="ck_cm_method"),
        CheckConstraint(E.check_in("review_status", E.REVIEW_STATUSES), name="ck_cm_review"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_cm_conf"),
        Index("uq_cm_current", "company_id", "material_id", "grade_category", "application", "relationship_type",
              unique=True, postgresql_where=text("is_current")),
        Index("ix_cm_filter", "material_id", "grade_category", "application", "relationship_type"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), nullable=False)
    grade_category: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False)
    application: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False)
    form: Mapped[str | None] = mapped_column(String(20))
    available_quantity: Mapped[float | None] = mapped_column(Numeric(18, 3))
    required_quantity: Mapped[float | None] = mapped_column(Numeric(18, 3))
    quantity_unit: Mapped[str | None] = mapped_column(String(20))
    quantity_period: Mapped[str | None] = mapped_column(String(20))  # e.g. per month
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    evidence_url: Mapped[str | None] = mapped_column(Text)
    raw_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_records.id", ondelete="SET NULL"))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    review_status: Mapped[str] = mapped_column(String(20), default="auto", nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    company: Mapped[Company] = relationship(back_populates="materials")
    material: Mapped[Material] = relationship()
    specifications: Mapped[list["MaterialSpecification"]] = relationship(back_populates="company_material", cascade="all, delete-orphan")


class MaterialSpecification(Base):
    """Technical specs. Every value must be quoted verbatim in evidence_text (never inferred)."""

    __tablename__ = "material_specifications"
    __table_args__ = (
        CheckConstraint("density IS NULL OR (density > 0.85 AND density < 1.0)", name="ck_spec_density"),
        CheckConstraint("mfi IS NULL OR (mfi >= 0 AND mfi < 200)", name="ck_spec_mfi"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_material_id: Mapped[int] = mapped_column(ForeignKey("company_materials.id", ondelete="CASCADE"), nullable=False, index=True)
    grade_number: Mapped[str | None] = mapped_column(String(60))
    brand: Mapped[str | None] = mapped_column(String(120))
    manufacturer_name: Mapped[str | None] = mapped_column(String(200))
    mfi: Mapped[float | None] = mapped_column(Float)
    mfi_conditions: Mapped[str | None] = mapped_column(String(60))  # e.g. 190C/2.16kg
    density: Mapped[float | None] = mapped_column(Float)  # g/cm3
    colour: Mapped[str | None] = mapped_column(String(60))
    form: Mapped[str | None] = mapped_column(String(20))
    origin_country: Mapped[str | None] = mapped_column(String(2))
    packaging: Mapped[str | None] = mapped_column(String(120))
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_url: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(20), default="rule", nullable=False)
    raw_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_records.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()
    company_material: Mapped[CompanyMaterial] = relationship(back_populates="specifications")


class PriceObservation(Base):
    __tablename__ = "price_observations"
    __table_args__ = (
        CheckConstraint("price > 0", name="ck_price_positive"),
        Index("ix_price_material_date", "material_id", "observed_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), nullable=False)
    grade_category: Mapped[str | None] = mapped_column(String(30))
    price: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    incoterm: Mapped[str | None] = mapped_column(String(10))
    location: Mapped[str | None] = mapped_column(String(120))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    raw_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_records.id", ondelete="SET NULL"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = _created()


# ---------------------------------------------------------------- trade
class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_shipment_source_ext"),
        Index("ix_ship_date", "shipment_date"),
        Index("ix_ship_hs", "hs_code"),
        Index("ix_ship_importer", "importer_company_id"),
        Index("ix_ship_exporter", "exporter_company_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)  # provider id or content hash
    shipment_date: Mapped[date | None] = mapped_column(Date)
    importer_company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    exporter_company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    importer_name_raw: Mapped[str | None] = mapped_column(String(300))
    exporter_name_raw: Mapped[str | None] = mapped_column(String(300))
    importer_country: Mapped[str | None] = mapped_column(String(2))
    exporter_country: Mapped[str | None] = mapped_column(String(2))
    origin_country: Mapped[str | None] = mapped_column(String(2))
    destination_country: Mapped[str | None] = mapped_column(String(2))
    port_of_loading: Mapped[str | None] = mapped_column(String(150))
    port_of_discharge: Mapped[str | None] = mapped_column(String(150))
    hs_code: Mapped[str | None] = mapped_column(String(12))
    product_description: Mapped[str | None] = mapped_column(Text)
    material_id: Mapped[int | None] = mapped_column(ForeignKey("materials.id"))
    material_inference: Mapped[str | None] = mapped_column(String(30))  # description | hs_code | ambiguous_hs
    grade_category: Mapped[str | None] = mapped_column(String(30))
    quantity: Mapped[float | None] = mapped_column(Numeric(18, 3))
    quantity_unit: Mapped[str | None] = mapped_column(String(20))
    weight_kg: Mapped[float | None] = mapped_column(Numeric(18, 3))
    value: Mapped[float | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    bill_of_lading: Mapped[str | None] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(Text)
    raw_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_records.id", ondelete="SET NULL"))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    material: Mapped[Material | None] = relationship()
    source: Mapped[Source] = relationship()


class TradeStatistic(Base):
    """Country-level aggregate flows (UN Comtrade, US Census). Not company-level."""

    __tablename__ = "trade_statistics"
    __table_args__ = (
        UniqueConstraint("source_id", "reporter_country", "partner_country", "flow", "hs_code", "period",
                         name="uq_tradestat"),
        CheckConstraint(E.check_in("flow", E.TRADE_FLOWS), name="ck_tradestat_flow"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    reporter_country: Mapped[str] = mapped_column(String(3), nullable=False)
    partner_country: Mapped[str] = mapped_column(String(3), nullable=False)  # 'W' = world
    partner_name: Mapped[str | None] = mapped_column(String(120))
    flow: Mapped[str] = mapped_column(String(10), nullable=False)
    hs_code: Mapped[str] = mapped_column(String(12), nullable=False)
    hs_description: Mapped[str | None] = mapped_column(Text)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY or YYYY-MM
    value_usd: Mapped[float | None] = mapped_column(Numeric(20, 2))
    net_weight_kg: Mapped[float | None] = mapped_column(Numeric(20, 2))
    quantity: Mapped[float | None] = mapped_column(Numeric(20, 2))
    quantity_unit: Mapped[str | None] = mapped_column(String(20))
    source_url: Mapped[str | None] = mapped_column(Text)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CompanySourceRecord(Base):
    """Every sighting of a company in a source, with what was extracted and how it was matched."""

    __tablename__ = "company_source_records"
    __table_args__ = (
        UniqueConstraint("company_id", "source_id", "raw_record_id", name="uq_csr"),
        Index("ix_csr_source", "source_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    raw_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_records.id", ondelete="SET NULL"))
    source_url: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(255))
    extracted_data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    match_method: Mapped[str] = mapped_column(String(40), nullable=False)  # new, domain, registration, phone+name ...
    match_score: Mapped[float | None] = mapped_column(Float)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created()

    company: Mapped[Company] = relationship(back_populates="source_records")
    source: Mapped[Source] = relationship()


class DuplicateCandidate(Base):
    __tablename__ = "duplicate_candidates"
    __table_args__ = (
        UniqueConstraint("company_a_id", "company_b_id", name="uq_dup_pair"),
        CheckConstraint("company_a_id < company_b_id", name="ck_dup_order"),
        CheckConstraint(E.check_in("status", E.DUPLICATE_STATUSES), name="ck_dup_status"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_a_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    company_b_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    reasons: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


# ---------------------------------------------------------------- contacts
class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        CheckConstraint(E.check_in("contact_type", E.CONTACT_TYPES), name="ck_contact_type"),
        CheckConstraint(E.check_in("decision_role", E.DECISION_ROLES), name="ck_contact_role"),
        CheckConstraint(E.check_in("verification_status", E.CONTACT_VERIFICATION_STATUSES), name="ck_contact_verif"),
        CheckConstraint("email IS NOT NULL OR phone IS NOT NULL OR linkedin_url IS NOT NULL", name="ck_contact_has_channel"),
        Index("ix_contacts_email", "email_normalized"),
        Index("uq_contact_company_email", "company_id", "email_normalized", unique=True,
              postgresql_where=text("email_normalized IS NOT NULL")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_type: Mapped[str] = mapped_column(String(20), default="general", nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200))
    job_title: Mapped[str | None] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(100))
    decision_role: Mapped[str] = mapped_column(String(30), default="unknown_authority", nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    email_normalized: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(60))
    phone_normalized: Mapped[str | None] = mapped_column(String(30))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    country_code: Mapped[str | None] = mapped_column(String(2))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    source_url: Mapped[str | None] = mapped_column(Text)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(30), default="discovered", nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_opted_out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    company: Mapped[Company] = relationship(back_populates="contacts")
    verifications: Mapped[list["ContactVerification"]] = relationship(back_populates="contact", cascade="all, delete-orphan",
                                                                     order_by="ContactVerification.checked_at")


class ContactVerification(Base):
    __tablename__ = "contact_verification"
    __table_args__ = (
        CheckConstraint(E.check_in("check_type", E.VERIFICATION_CHECK_TYPES), name="ck_cv_type"),
        CheckConstraint(E.check_in("result", E.VERIFICATION_RESULTS), name="ck_cv_result"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    check_type: Mapped[str] = mapped_column(String(30), nullable=False)
    result: Mapped[str] = mapped_column(String(10), nullable=False)
    status_after: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(60))
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    checked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    contact: Mapped[Contact] = relationship(back_populates="verifications")


class SuppressionEntry(Base):
    """Opted-out / deleted personal data. Ingestion refuses to re-create these contacts."""

    __tablename__ = "suppression_list"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    value_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # sha256 of normalised email/phone
    value_type: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = _created()


class PrivacyRequest(Base):
    __tablename__ = "privacy_requests"
    __table_args__ = (
        CheckConstraint(E.check_in("request_type", E.PRIVACY_REQUEST_TYPES), name="ck_pr_type"),
        CheckConstraint(E.check_in("status", E.PRIVACY_REQUEST_STATUSES), name="ck_pr_status"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_type: Mapped[str] = mapped_column(String(20), nullable=False)
    requester_email: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    details: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="received", nullable=False)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- CRM
class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("company_id", "owner_user_id", name="uq_lead_company_owner"),
        CheckConstraint(E.check_in("stage", E.LEAD_STAGES), name="ck_lead_stage"),
        CheckConstraint(E.check_in("lead_type", E.LEAD_TYPES), name="ck_lead_type"),
        CheckConstraint(E.check_in("priority", E.LEAD_PRIORITIES), name="ck_lead_priority"),
        Index("ix_leads_stage", "stage"),
        Index("ix_leads_followup", "next_follow_up_at"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    lead_type: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False)
    stage: Mapped[str] = mapped_column(String(30), default="new", nullable=False)
    priority: Mapped[str] = mapped_column(String(10), default="medium", nullable=False)
    interested_materials: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    communication_status: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    company: Mapped[Company] = relationship()
    activities: Mapped[list["LeadActivity"]] = relationship(back_populates="lead", cascade="all, delete-orphan",
                                                           order_by="LeadActivity.created_at.desc()")


class LeadActivity(Base):
    __tablename__ = "lead_activities"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    activity_type: Mapped[str] = mapped_column(String(30), nullable=False)  # note, call, email, meeting, stage_change
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()
    lead: Mapped[Lead] = relationship(back_populates="activities")


class CompanyNote(Base):
    __tablename__ = "company_notes"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()
    company: Mapped[Company] = relationship(back_populates="notes")


# ---------------------------------------------------------------- ops
class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_unread", "is_read", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alert_type: Mapped[str] = mapped_column(String(40), nullable=False)  # new_company, material_change, new_shipment, job_failed
    severity: Mapped[str] = mapped_column(String(10), default="info", nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    delivered_webhook: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = _created()


class ApiUsage(Base):
    __tablename__ = "api_usage"
    __table_args__ = (Index("ix_api_usage_provider_created", "provider", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    operation: Mapped[str] = mapped_column(String(60), nullable=False)
    units: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # requests or tokens
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0, nullable=False)
    created_at: Mapped[datetime] = _created()


class ClassificationReview(Base):
    """Manual QA sample used to measure classification accuracy (acceptance criterion: >=80%)."""

    __tablename__ = "classification_reviews"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_material_id: Mapped[int] = mapped_column(ForeignKey("company_materials.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    polymer_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    grade_correct: Mapped[bool | None] = mapped_column(Boolean)
    relationship_correct: Mapped[bool | None] = mapped_column(Boolean)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = _updated()


# ---------------------------------------------------------------- market prices
class PriceSeries(Base):
    """A market price benchmark tracked over time: one material, one market (country/location), one price basis.

    Examples: 'DCE LLDPE futures, main contract (CNY/t)', 'US PPI plastic resins (index)',
    'India LLDPE film, producer list price ex-Mumbai (INR/kg)'. Points live in price_points.
    """

    __tablename__ = "price_series"
    __table_args__ = (
        CheckConstraint(E.check_in("price_type", E.PRICE_TYPES), name="ck_pseries_type"),
        CheckConstraint(E.check_in("frequency", E.PRICE_FREQUENCIES), name="ck_pseries_freq"),
        CheckConstraint(E.check_in("unit", E.PRICE_UNITS), name="ck_pseries_unit"),
        Index("ix_pseries_material_country", "material_id", "country_code"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    material_id: Mapped[int | None] = mapped_column(ForeignKey("materials.id"))  # null = multi-polymer index/feedstock
    grade: Mapped[str | None] = mapped_column(String(120))            # e.g. "film C4", "raffia", "injection"
    country_code: Mapped[str | None] = mapped_column(String(2))       # market the price applies to
    location: Mapped[str | None] = mapped_column(String(120))         # e.g. "Dalian", "US Gulf", "ex-Mumbai"
    price_type: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3))           # null for indices
    unit: Mapped[str] = mapped_column(String(10), nullable=False)
    incoterm: Mapped[str | None] = mapped_column(String(20))
    frequency: Mapped[str] = mapped_column(String(10), nullable=False, default="daily")
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    external_code: Mapped[str | None] = mapped_column(String(120))     # FRED id, DCE variety, provider symbol
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    material: Mapped[Material | None] = relationship()
    source: Mapped[Source | None] = relationship()


class PricePoint(Base):
    """One observation of a series. Never invented: each row carries where it came from."""

    __tablename__ = "price_points"
    __table_args__ = (
        UniqueConstraint("series_id", "observed_at", name="uq_price_point"),
        CheckConstraint("price > 0", name="ck_ppoint_positive"),
    )  # uq_price_point (series_id, observed_at) also serves history range scans
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("price_series.id", ondelete="CASCADE"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # price date/time
    price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    price_low: Mapped[float | None] = mapped_column(Numeric(18, 4))
    price_high: Mapped[float | None] = mapped_column(Numeric(18, 4))
    volume: Mapped[float | None] = mapped_column(Numeric(20, 2))
    open_interest: Mapped[float | None] = mapped_column(Numeric(20, 2))
    contract: Mapped[str | None] = mapped_column(String(40))          # futures contract used (e.g. l2601)
    is_provisional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="connector")  # connector|manual|import
    source_url: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    raw_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_records.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    collected_at: Mapped[datetime] = _created()

    series: Mapped[PriceSeries] = relationship()


class FxRate(Base):
    """Units of `currency` per 1 USD on `rate_date` (e.g. INR 84.1). Used to normalise prices across markets."""

    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("currency", "rate_date", name="uq_fx_currency_date"),
                      CheckConstraint("per_usd > 0", name="ck_fx_positive"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    per_usd: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)    # fred:DEXINUS | peg | manual
    collected_at: Mapped[datetime] = _created()


class PriceAlertRule(Base):
    """Raise an alert when a new point crosses a threshold or moves more than X% versus the previous point."""

    __tablename__ = "price_alert_rules"
    __table_args__ = (CheckConstraint(E.check_in("condition", E.PRICE_ALERT_CONDITIONS), name="ck_palert_cond"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("price_series.id", ondelete="CASCADE"), nullable=False, index=True)
    condition: Mapped[str] = mapped_column(String(20), nullable=False)
    threshold: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)  # price in series units, or % for change_pct
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()

    series: Mapped[PriceSeries] = relationship()
