BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE SEQUENCE IF NOT EXISTS company_ref_seq START 1;

CREATE TABLE alerts (
    id BIGSERIAL NOT NULL, 
    alert_type VARCHAR(40) NOT NULL, 
    severity VARCHAR(10) NOT NULL, 
    entity_type VARCHAR(40), 
    entity_id VARCHAR(64), 
    message TEXT NOT NULL, 
    payload JSONB NOT NULL, 
    is_read BOOLEAN NOT NULL, 
    delivered_webhook BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_alerts_unread ON alerts (is_read, created_at);

CREATE TABLE api_usage (
    id BIGSERIAL NOT NULL, 
    provider VARCHAR(40) NOT NULL, 
    operation VARCHAR(60) NOT NULL, 
    units INTEGER NOT NULL, 
    input_tokens INTEGER, 
    output_tokens INTEGER, 
    estimated_cost_usd NUMERIC(12, 6) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_api_usage_provider_created ON api_usage (provider, created_at);

CREATE TABLE app_settings (
    key VARCHAR(80) NOT NULL, 
    value JSONB NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (key)
);

CREATE TABLE countries (
    code VARCHAR(2) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    region VARCHAR(60), 
    is_active BOOLEAN NOT NULL, 
    priority INTEGER NOT NULL, 
    m49_code INTEGER, 
    phone_prefix VARCHAR(6), 
    aliases TEXT[] NOT NULL, 
    search_terms JSONB NOT NULL, 
    notes TEXT, 
    PRIMARY KEY (code)
);

CREATE TABLE materials (
    id SERIAL NOT NULL, 
    code VARCHAR(20) NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    family VARCHAR(60) NOT NULL, 
    hs_codes TEXT[] NOT NULL, 
    synonyms TEXT[] NOT NULL, 
    is_target BOOLEAN NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    notes TEXT, 
    PRIMARY KEY (id), 
    UNIQUE (code)
);

CREATE TABLE sources (
    id SERIAL NOT NULL, 
    key VARCHAR(60) NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    source_type VARCHAR(30) NOT NULL, 
    access_method VARCHAR(30) NOT NULL, 
    base_url VARCHAR(500), 
    status VARCHAR(30) NOT NULL, 
    enabled BOOLEAN NOT NULL, 
    requires_credentials BOOLEAN NOT NULL, 
    credential_env_vars TEXT[] NOT NULL, 
    terms_notes TEXT, 
    pricing_notes TEXT, 
    config JSONB NOT NULL, 
    refresh_interval_days INTEGER, 
    last_run_at TIMESTAMP WITH TIME ZONE, 
    last_success_at TIMESTAMP WITH TIME ZONE, 
    last_error TEXT, 
    total_records INTEGER NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_sources_access CHECK (access_method IN ('api', 'export_import', 'scrape', 'manual')), 
    CONSTRAINT ck_sources_type CHECK (source_type IN ('trade_database', 'directory', 'website', 'search_api', 'government', 'enrichment', 'manual_import', 'ai')), 
    CONSTRAINT ck_sources_status CHECK (status IN ('active', 'awaiting_credentials', 'requires_terms_review', 'disabled', 'error', 'manual_only')), 
    UNIQUE (key)
);

CREATE TABLE suppression_list (
    id BIGSERIAL NOT NULL, 
    value_hash VARCHAR(64) NOT NULL, 
    value_type VARCHAR(10) NOT NULL, 
    reason VARCHAR(30) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (value_hash)
);

CREATE TABLE users (
    id UUID NOT NULL, 
    email VARCHAR(255) NOT NULL, 
    full_name VARCHAR(200), 
    password_hash VARCHAR(255), 
    auth_provider VARCHAR(30) NOT NULL, 
    external_auth_id VARCHAR(255), 
    role VARCHAR(20) NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    last_login_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_users_role CHECK (role IN ('admin', 'analyst', 'viewer')), 
    UNIQUE (email), 
    UNIQUE (external_auth_id)
);

CREATE TABLE companies (
    id UUID NOT NULL, 
    public_ref VARCHAR(20) DEFAULT 'CMP-' || lpad(nextval('company_ref_seq')::text, 7, '0') NOT NULL, 
    name VARCHAR(300) NOT NULL, 
    normalized_name VARCHAR(300) NOT NULL, 
    country_code VARCHAR(2), 
    state VARCHAR(120), 
    city VARCHAR(120), 
    address TEXT, 
    postal_code VARCHAR(30), 
    website VARCHAR(500), 
    domain VARCHAR(255), 
    email VARCHAR(255), 
    phone VARCHAR(60), 
    phone_normalized VARCHAR(30), 
    linkedin_url VARCHAR(500), 
    description TEXT, 
    registration_number VARCHAR(100), 
    registration_authority VARCHAR(150), 
    status VARCHAR(20) NOT NULL, 
    merged_into_id UUID, 
    primary_source_id INTEGER, 
    lead_score INTEGER, 
    lead_tier VARCHAR(30), 
    lead_score_breakdown JSONB NOT NULL, 
    lead_score_updated_at TIMESTAMP WITH TIME ZONE, 
    website_last_crawled_at TIMESTAMP WITH TIME ZONE, 
    first_discovered_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    last_seen_at TIMESTAMP WITH TIME ZONE, 
    last_verified_at TIMESTAMP WITH TIME ZONE, 
    is_demo BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_companies_status CHECK (status IN ('active', 'merged', 'opted_out', 'archived')), 
    CONSTRAINT ck_companies_score CHECK (lead_score IS NULL OR (lead_score BETWEEN 0 AND 100)), 
    FOREIGN KEY(country_code) REFERENCES countries (code), 
    FOREIGN KEY(merged_into_id) REFERENCES companies (id) ON DELETE SET NULL, 
    FOREIGN KEY(primary_source_id) REFERENCES sources (id) ON DELETE SET NULL, 
    UNIQUE (public_ref)
);

CREATE INDEX ix_companies_country_status ON companies (country_code, status);

CREATE INDEX ix_companies_domain ON companies (domain);

CREATE INDEX ix_companies_lead_score ON companies (lead_score);

CREATE INDEX ix_companies_name_trgm ON companies USING gin (normalized_name gin_trgm_ops);

CREATE INDEX ix_companies_phone ON companies (phone_normalized);

CREATE INDEX ix_companies_reg ON companies (country_code, registration_number);

CREATE TABLE scrape_jobs (
    id BIGSERIAL NOT NULL, 
    source_id INTEGER NOT NULL, 
    job_type VARCHAR(50) NOT NULL, 
    params JSONB NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    priority INTEGER NOT NULL, 
    scheduled_for TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    started_at TIMESTAMP WITH TIME ZONE, 
    finished_at TIMESTAMP WITH TIME ZONE, 
    attempts INTEGER NOT NULL, 
    max_attempts INTEGER NOT NULL, 
    records_found INTEGER NOT NULL, 
    records_created INTEGER NOT NULL, 
    records_updated INTEGER NOT NULL, 
    records_failed INTEGER NOT NULL, 
    error_message TEXT, 
    log JSONB NOT NULL, 
    created_by UUID, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_jobs_status CHECK (status IN ('queued', 'running', 'succeeded', 'partial', 'failed', 'cancelled')), 
    FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL, 
    FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE CASCADE
);

CREATE INDEX ix_jobs_status_scheduled ON scrape_jobs (status, scheduled_for);

CREATE INDEX ix_scrape_jobs_source_id ON scrape_jobs (source_id);

CREATE TABLE trade_statistics (
    id BIGSERIAL NOT NULL, 
    source_id INTEGER NOT NULL, 
    reporter_country VARCHAR(3) NOT NULL, 
    partner_country VARCHAR(3) NOT NULL, 
    partner_name VARCHAR(120), 
    flow VARCHAR(10) NOT NULL, 
    hs_code VARCHAR(12) NOT NULL, 
    hs_description TEXT, 
    period VARCHAR(7) NOT NULL, 
    value_usd NUMERIC(20, 2), 
    net_weight_kg NUMERIC(20, 2), 
    quantity NUMERIC(20, 2), 
    quantity_unit VARCHAR(20), 
    source_url TEXT, 
    collected_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_tradestat_flow CHECK (flow IN ('import', 'export')), 
    FOREIGN KEY(source_id) REFERENCES sources (id), 
    CONSTRAINT uq_tradestat UNIQUE (source_id, reporter_country, partner_country, flow, hs_code, period)
);

CREATE TABLE user_activity (
    id BIGSERIAL NOT NULL, 
    user_id UUID, 
    action VARCHAR(80) NOT NULL, 
    entity_type VARCHAR(50), 
    entity_id VARCHAR(64), 
    details JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_user_activity_user_created ON user_activity (user_id, created_at);

CREATE TABLE company_aliases (
    id BIGSERIAL NOT NULL, 
    company_id UUID NOT NULL, 
    alias VARCHAR(300) NOT NULL, 
    normalized_alias VARCHAR(300) NOT NULL, 
    alias_type VARCHAR(30) NOT NULL, 
    source_id INTEGER, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE, 
    FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL, 
    CONSTRAINT uq_alias_company_norm UNIQUE (company_id, normalized_alias)
);

CREATE INDEX ix_alias_norm ON company_aliases (normalized_alias);

CREATE TABLE company_locations (
    id BIGSERIAL NOT NULL, 
    company_id UUID NOT NULL, 
    location_type VARCHAR(20) NOT NULL, 
    address TEXT, 
    city VARCHAR(120), 
    state VARCHAR(120), 
    postal_code VARCHAR(30), 
    country_code VARCHAR(2), 
    phone VARCHAR(60), 
    is_primary BOOLEAN NOT NULL, 
    source_id INTEGER, 
    source_url TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_loc_type CHECK (location_type IN ('headquarters', 'plant', 'warehouse', 'office', 'sales', 'other')), 
    FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE, 
    FOREIGN KEY(country_code) REFERENCES countries (code), 
    FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL
);

CREATE INDEX ix_company_locations_company_id ON company_locations (company_id);

CREATE TABLE company_notes (
    id BIGSERIAL NOT NULL, 
    company_id UUID NOT NULL, 
    user_id UUID, 
    body TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE, 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_company_notes_company_id ON company_notes (company_id);

CREATE TABLE contacts (
    id UUID NOT NULL, 
    company_id UUID NOT NULL, 
    contact_type VARCHAR(20) NOT NULL, 
    full_name VARCHAR(200), 
    job_title VARCHAR(200), 
    department VARCHAR(100), 
    decision_role VARCHAR(30) NOT NULL, 
    email VARCHAR(255), 
    email_normalized VARCHAR(255), 
    phone VARCHAR(60), 
    phone_normalized VARCHAR(30), 
    linkedin_url VARCHAR(500), 
    country_code VARCHAR(2), 
    source_id INTEGER, 
    source_url TEXT, 
    evidence_text TEXT, 
    verification_status VARCHAR(30) NOT NULL, 
    last_verified_at TIMESTAMP WITH TIME ZONE, 
    is_opted_out BOOLEAN NOT NULL, 
    is_demo BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_contact_type CHECK (contact_type IN ('general', 'individual')), 
    CONSTRAINT ck_contact_role CHECK (decision_role IN ('confirmed_decision_maker', 'likely_decision_maker', 'unknown_authority')), 
    CONSTRAINT ck_contact_verif CHECK (verification_status IN ('discovered', 'syntax_checked', 'domain_checked', 'email_verified', 'phone_checked', 'manually_verified', 'invalid', 'outdated')), 
    CONSTRAINT ck_contact_has_channel CHECK (email IS NOT NULL OR phone IS NOT NULL OR linkedin_url IS NOT NULL), 
    FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE, 
    FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL
);

CREATE INDEX ix_contacts_company_id ON contacts (company_id);

CREATE INDEX ix_contacts_email ON contacts (email_normalized);

CREATE UNIQUE INDEX uq_contact_company_email ON contacts (company_id, email_normalized) WHERE email_normalized IS NOT NULL;

CREATE TABLE duplicate_candidates (
    id BIGSERIAL NOT NULL, 
    company_a_id UUID NOT NULL, 
    company_b_id UUID NOT NULL, 
    score FLOAT NOT NULL, 
    reasons JSONB NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    resolved_by UUID, 
    resolved_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_dup_status CHECK (status IN ('pending', 'merged', 'rejected')), 
    CONSTRAINT ck_dup_order CHECK (company_a_id < company_b_id), 
    FOREIGN KEY(company_a_id) REFERENCES companies (id) ON DELETE CASCADE, 
    FOREIGN KEY(company_b_id) REFERENCES companies (id) ON DELETE CASCADE, 
    FOREIGN KEY(resolved_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT uq_dup_pair UNIQUE (company_a_id, company_b_id)
);

CREATE TABLE leads (
    id UUID NOT NULL, 
    company_id UUID NOT NULL, 
    owner_user_id UUID NOT NULL, 
    lead_type VARCHAR(30) NOT NULL, 
    stage VARCHAR(30) NOT NULL, 
    priority VARCHAR(10) NOT NULL, 
    interested_materials TEXT[] NOT NULL, 
    communication_status VARCHAR(100), 
    notes TEXT, 
    last_contacted_at TIMESTAMP WITH TIME ZONE, 
    next_follow_up_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_lead_type CHECK (lead_type IN ('potential_buyer', 'potential_supplier', 'both', 'unknown')), 
    CONSTRAINT ck_lead_priority CHECK (priority IN ('high', 'medium', 'low')), 
    CONSTRAINT ck_lead_stage CHECK (stage IN ('new', 'researching', 'contacted', 'interested', 'negotiation', 'converted', 'not_interested')), 
    FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE, 
    FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_lead_company_owner UNIQUE (company_id, owner_user_id)
);

CREATE INDEX ix_leads_followup ON leads (next_follow_up_at);

CREATE INDEX ix_leads_stage ON leads (stage);

CREATE TABLE raw_records (
    id BIGSERIAL NOT NULL, 
    source_id INTEGER NOT NULL, 
    scrape_job_id BIGINT, 
    record_type VARCHAR(40) NOT NULL, 
    source_url TEXT, 
    external_id VARCHAR(255), 
    content_hash VARCHAR(64) NOT NULL, 
    payload JSONB NOT NULL, 
    raw_text TEXT, 
    collected_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    processing_status VARCHAR(20) NOT NULL, 
    processing_error TEXT, 
    processed_at TIMESTAMP WITH TIME ZONE, 
    is_demo BOOLEAN NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_raw_status CHECK (processing_status IN ('pending', 'processed', 'failed', 'skipped')), 
    FOREIGN KEY(scrape_job_id) REFERENCES scrape_jobs (id) ON DELETE SET NULL, 
    FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE CASCADE, 
    CONSTRAINT uq_raw_source_hash UNIQUE (source_id, content_hash)
);

CREATE INDEX ix_raw_status ON raw_records (processing_status);

CREATE TABLE company_classifications (
    id BIGSERIAL NOT NULL, 
    company_id UUID NOT NULL, 
    category VARCHAR(30) NOT NULL, 
    method VARCHAR(20) NOT NULL, 
    confidence FLOAT NOT NULL, 
    evidence_text TEXT, 
    evidence_url TEXT, 
    raw_record_id BIGINT, 
    review_status VARCHAR(20) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_class_category CHECK (category IN ('manufacturer', 'producer', 'trader', 'distributor', 'importer', 'exporter', 'recycler', 'processor', 'converter', 'scrap_aggregator')), 
    CONSTRAINT ck_class_method CHECK (method IN ('rule', 'ai', 'manual', 'trade_data', 'import')), 
    CONSTRAINT ck_class_review CHECK (review_status IN ('auto', 'needs_review', 'confirmed', 'rejected')), 
    FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE, 
    FOREIGN KEY(raw_record_id) REFERENCES raw_records (id) ON DELETE SET NULL, 
    CONSTRAINT uq_classification_company_cat UNIQUE (company_id, category)
);

CREATE INDEX ix_class_category ON company_classifications (category);

CREATE TABLE company_materials (
    id BIGSERIAL NOT NULL, 
    company_id UUID NOT NULL, 
    material_id INTEGER NOT NULL, 
    grade_category VARCHAR(30) NOT NULL, 
    application VARCHAR(30) NOT NULL, 
    relationship_type VARCHAR(30) NOT NULL, 
    form VARCHAR(20), 
    available_quantity NUMERIC(18, 3), 
    required_quantity NUMERIC(18, 3), 
    quantity_unit VARCHAR(20), 
    quantity_period VARCHAR(20), 
    method VARCHAR(20) NOT NULL, 
    confidence FLOAT NOT NULL, 
    evidence_text TEXT, 
    evidence_url TEXT, 
    raw_record_id BIGINT, 
    source_id INTEGER, 
    review_status VARCHAR(20) NOT NULL, 
    reviewed_by UUID, 
    reviewed_at TIMESTAMP WITH TIME ZONE, 
    is_current BOOLEAN NOT NULL, 
    first_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_cm_form CHECK ((form IS NULL OR form IN ('pellets', 'granules', 'flakes', 'bales', 'regrind', 'lumps', 'powder', 'rolls', 'film_scrap', 'other'))), 
    CONSTRAINT ck_cm_app CHECK (application IN ('film', 'extrusion', 'blow_moulding', 'injection_moulding', 'rotomoulding', 'pipe', 'raffia_tape', 'wire_cable', 'coating', 'other', 'unknown')), 
    CONSTRAINT ck_cm_grade CHECK (grade_category IN ('virgin_prime', 'near_prime', 'off_grade', 'off_spec', 'non_prime_unspecified', 'recycled', 'reprocessed', 'pcr', 'pir', 'scrap', 'unknown')), 
    CONSTRAINT ck_cm_method CHECK (method IN ('rule', 'ai', 'manual', 'trade_data', 'import')), 
    CONSTRAINT ck_cm_rel CHECK (relationship_type IN ('buyer', 'seller', 'both', 'manufacturer', 'historical_buyer', 'historical_seller', 'unknown')), 
    CONSTRAINT ck_cm_review CHECK (review_status IN ('auto', 'needs_review', 'confirmed', 'rejected')), 
    CONSTRAINT ck_cm_conf CHECK (confidence BETWEEN 0 AND 1), 
    FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE, 
    FOREIGN KEY(material_id) REFERENCES materials (id), 
    FOREIGN KEY(raw_record_id) REFERENCES raw_records (id) ON DELETE SET NULL, 
    FOREIGN KEY(reviewed_by) REFERENCES users (id) ON DELETE SET NULL, 
    FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL
);

CREATE INDEX ix_cm_filter ON company_materials (material_id, grade_category, application, relationship_type);

CREATE INDEX ix_company_materials_company_id ON company_materials (company_id);

CREATE UNIQUE INDEX uq_cm_current ON company_materials (company_id, material_id, grade_category, application, relationship_type) WHERE is_current;

CREATE TABLE company_source_records (
    id BIGSERIAL NOT NULL, 
    company_id UUID NOT NULL, 
    source_id INTEGER NOT NULL, 
    raw_record_id BIGINT, 
    source_url TEXT, 
    external_id VARCHAR(255), 
    extracted_data JSONB NOT NULL, 
    match_method VARCHAR(40) NOT NULL, 
    match_score FLOAT, 
    collected_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE, 
    FOREIGN KEY(raw_record_id) REFERENCES raw_records (id) ON DELETE SET NULL, 
    FOREIGN KEY(source_id) REFERENCES sources (id), 
    CONSTRAINT uq_csr UNIQUE (company_id, source_id, raw_record_id)
);

CREATE INDEX ix_company_source_records_company_id ON company_source_records (company_id);

CREATE INDEX ix_csr_source ON company_source_records (source_id);

CREATE TABLE contact_verification (
    id BIGSERIAL NOT NULL, 
    contact_id UUID NOT NULL, 
    check_type VARCHAR(30) NOT NULL, 
    result VARCHAR(10) NOT NULL, 
    status_after VARCHAR(30) NOT NULL, 
    provider VARCHAR(60), 
    details JSONB NOT NULL, 
    checked_by UUID, 
    checked_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_cv_type CHECK (check_type IN ('syntax', 'domain_mx', 'provider_email', 'phone_format', 'manual')), 
    CONSTRAINT ck_cv_result CHECK (result IN ('pass', 'fail', 'unknown')), 
    FOREIGN KEY(checked_by) REFERENCES users (id) ON DELETE SET NULL, 
    FOREIGN KEY(contact_id) REFERENCES contacts (id) ON DELETE CASCADE
);

CREATE INDEX ix_contact_verification_contact_id ON contact_verification (contact_id);

CREATE TABLE lead_activities (
    id BIGSERIAL NOT NULL, 
    lead_id UUID NOT NULL, 
    user_id UUID, 
    activity_type VARCHAR(30) NOT NULL, 
    summary TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(lead_id) REFERENCES leads (id) ON DELETE CASCADE, 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_lead_activities_lead_id ON lead_activities (lead_id);

CREATE TABLE price_observations (
    id BIGSERIAL NOT NULL, 
    company_id UUID, 
    material_id INTEGER NOT NULL, 
    grade_category VARCHAR(30), 
    price NUMERIC(14, 4) NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    unit VARCHAR(20) NOT NULL, 
    incoterm VARCHAR(10), 
    location VARCHAR(120), 
    observed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    evidence_text TEXT NOT NULL, 
    source_url TEXT, 
    source_id INTEGER, 
    raw_record_id BIGINT, 
    is_demo BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_price_positive CHECK (price > 0), 
    FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE, 
    FOREIGN KEY(material_id) REFERENCES materials (id), 
    FOREIGN KEY(raw_record_id) REFERENCES raw_records (id) ON DELETE SET NULL, 
    FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL
);

CREATE INDEX ix_price_material_date ON price_observations (material_id, observed_at);

CREATE INDEX ix_price_observations_company_id ON price_observations (company_id);

CREATE TABLE privacy_requests (
    id BIGSERIAL NOT NULL, 
    request_type VARCHAR(20) NOT NULL, 
    requester_email VARCHAR(255) NOT NULL, 
    contact_id UUID, 
    details TEXT, 
    status VARCHAR(20) NOT NULL, 
    resolution_notes TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    resolved_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_pr_type CHECK (request_type IN ('opt_out', 'correction', 'deletion')), 
    CONSTRAINT ck_pr_status CHECK (status IN ('received', 'in_progress', 'completed', 'rejected')), 
    FOREIGN KEY(contact_id) REFERENCES contacts (id) ON DELETE SET NULL
);

CREATE TABLE shipments (
    id BIGSERIAL NOT NULL, 
    source_id INTEGER NOT NULL, 
    external_id VARCHAR(255) NOT NULL, 
    shipment_date DATE, 
    importer_company_id UUID, 
    exporter_company_id UUID, 
    importer_name_raw VARCHAR(300), 
    exporter_name_raw VARCHAR(300), 
    importer_country VARCHAR(2), 
    exporter_country VARCHAR(2), 
    origin_country VARCHAR(2), 
    destination_country VARCHAR(2), 
    port_of_loading VARCHAR(150), 
    port_of_discharge VARCHAR(150), 
    hs_code VARCHAR(12), 
    product_description TEXT, 
    material_id INTEGER, 
    material_inference VARCHAR(30), 
    grade_category VARCHAR(30), 
    quantity NUMERIC(18, 3), 
    quantity_unit VARCHAR(20), 
    weight_kg NUMERIC(18, 3), 
    value NUMERIC(18, 2), 
    currency VARCHAR(3), 
    bill_of_lading VARCHAR(100), 
    source_url TEXT, 
    raw_record_id BIGINT, 
    collected_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    is_demo BOOLEAN NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(exporter_company_id) REFERENCES companies (id) ON DELETE SET NULL, 
    FOREIGN KEY(importer_company_id) REFERENCES companies (id) ON DELETE SET NULL, 
    FOREIGN KEY(material_id) REFERENCES materials (id), 
    FOREIGN KEY(raw_record_id) REFERENCES raw_records (id) ON DELETE SET NULL, 
    FOREIGN KEY(source_id) REFERENCES sources (id), 
    CONSTRAINT uq_shipment_source_ext UNIQUE (source_id, external_id)
);

CREATE INDEX ix_ship_date ON shipments (shipment_date);

CREATE INDEX ix_ship_exporter ON shipments (exporter_company_id);

CREATE INDEX ix_ship_hs ON shipments (hs_code);

CREATE INDEX ix_ship_importer ON shipments (importer_company_id);

CREATE TABLE classification_reviews (
    id BIGSERIAL NOT NULL, 
    company_material_id BIGINT NOT NULL, 
    reviewer_id UUID, 
    polymer_correct BOOLEAN NOT NULL, 
    grade_correct BOOLEAN, 
    relationship_correct BOOLEAN, 
    comment TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(company_material_id) REFERENCES company_materials (id) ON DELETE CASCADE, 
    FOREIGN KEY(reviewer_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_classification_reviews_company_material_id ON classification_reviews (company_material_id);

CREATE TABLE material_specifications (
    id BIGSERIAL NOT NULL, 
    company_material_id BIGINT NOT NULL, 
    grade_number VARCHAR(60), 
    brand VARCHAR(120), 
    manufacturer_name VARCHAR(200), 
    mfi FLOAT, 
    mfi_conditions VARCHAR(60), 
    density FLOAT, 
    colour VARCHAR(60), 
    form VARCHAR(20), 
    origin_country VARCHAR(2), 
    packaging VARCHAR(120), 
    evidence_text TEXT NOT NULL, 
    evidence_url TEXT, 
    method VARCHAR(20) NOT NULL, 
    raw_record_id BIGINT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_spec_density CHECK (density IS NULL OR (density > 0.85 AND density < 1.0)), 
    CONSTRAINT ck_spec_mfi CHECK (mfi IS NULL OR (mfi >= 0 AND mfi < 200)), 
    FOREIGN KEY(company_material_id) REFERENCES company_materials (id) ON DELETE CASCADE, 
    FOREIGN KEY(raw_record_id) REFERENCES raw_records (id) ON DELETE SET NULL
);

CREATE INDEX ix_material_specifications_company_material_id ON material_specifications (company_material_id);

INSERT INTO alembic_version (version_num) VALUES ('0001') RETURNING alembic_version.version_num;

-- Running upgrade 0001 -> 0002

ALTER TABLE sources DROP CONSTRAINT ck_sources_type;

ALTER TABLE sources ADD CONSTRAINT ck_sources_type CHECK (source_type IN ('trade_database', 'directory', 'website', 'search_api', 'government', 'enrichment', 'manual_import', 'ai', 'market_data'));

CREATE TABLE fx_rates (
    id BIGSERIAL NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    rate_date DATE NOT NULL, 
    per_usd NUMERIC(18, 8) NOT NULL, 
    source VARCHAR(40) NOT NULL, 
    collected_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_fx_positive CHECK (per_usd > 0), 
    CONSTRAINT uq_fx_currency_date UNIQUE (currency, rate_date)
);

CREATE TABLE price_series (
    id SERIAL NOT NULL, 
    key VARCHAR(80) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    material_id INTEGER, 
    grade VARCHAR(120), 
    country_code VARCHAR(2), 
    location VARCHAR(120), 
    price_type VARCHAR(20) NOT NULL, 
    currency VARCHAR(3), 
    unit VARCHAR(10) NOT NULL, 
    incoterm VARCHAR(20), 
    frequency VARCHAR(10) NOT NULL, 
    source_id INTEGER, 
    external_code VARCHAR(120), 
    config JSONB NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    notes TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_pseries_freq CHECK (frequency IN ('intraday', 'daily', 'weekly', 'monthly')), 
    CONSTRAINT ck_pseries_type CHECK (price_type IN ('futures', 'spot', 'contract', 'producer_list', 'assessment', 'index', 'feedstock')), 
    CONSTRAINT ck_pseries_unit CHECK (unit IN ('t', 'kg', 'lb', 'index', 'bbl', 'mmbtu')), 
    FOREIGN KEY(material_id) REFERENCES materials (id), 
    FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL, 
    UNIQUE (key)
);

CREATE INDEX ix_pseries_material_country ON price_series (material_id, country_code);

CREATE TABLE price_alert_rules (
    id SERIAL NOT NULL, 
    series_id INTEGER NOT NULL, 
    condition VARCHAR(20) NOT NULL, 
    threshold NUMERIC(18, 4) NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    last_triggered_at TIMESTAMP WITH TIME ZONE, 
    created_by UUID, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_palert_cond CHECK (condition IN ('above', 'below', 'change_pct')), 
    FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL, 
    FOREIGN KEY(series_id) REFERENCES price_series (id) ON DELETE CASCADE
);

CREATE INDEX ix_price_alert_rules_series_id ON price_alert_rules (series_id);

CREATE TABLE price_points (
    id BIGSERIAL NOT NULL, 
    series_id INTEGER NOT NULL, 
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    price NUMERIC(18, 4) NOT NULL, 
    price_low NUMERIC(18, 4), 
    price_high NUMERIC(18, 4), 
    volume NUMERIC(20, 2), 
    open_interest NUMERIC(20, 2), 
    contract VARCHAR(40), 
    is_provisional BOOLEAN NOT NULL, 
    origin VARCHAR(20) NOT NULL, 
    source_url TEXT, 
    note TEXT, 
    raw_record_id BIGINT, 
    created_by UUID, 
    collected_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_ppoint_positive CHECK (price > 0), 
    FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL, 
    FOREIGN KEY(raw_record_id) REFERENCES raw_records (id) ON DELETE SET NULL, 
    FOREIGN KEY(series_id) REFERENCES price_series (id) ON DELETE CASCADE, 
    CONSTRAINT uq_price_point UNIQUE (series_id, observed_at)
);

UPDATE alembic_version SET version_num='0002' WHERE alembic_version.version_num = '0001';

COMMIT;

