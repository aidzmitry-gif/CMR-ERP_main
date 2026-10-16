CREATE SCHEMA IF NOT EXISTS accounting;

CREATE SCHEMA IF NOT EXISTS procurement;

CREATE SCHEMA IF NOT EXISTS wms;

CREATE SCHEMA IF NOT EXISTS sales;

CREATE SCHEMA IF NOT EXISTS logistics;

CREATE SCHEMA IF NOT EXISTS office;

CREATE TABLE accounting.organization (
	id SERIAL NOT NULL,
	name VARCHAR(200) NOT NULL,
	unp VARCHAR(9) NOT NULL,
	generation INTEGER NOT NULL,
	CONSTRAINT pk_organization PRIMARY KEY (id),
	CONSTRAINT uq_organization_unp UNIQUE (unp)
);

CREATE TABLE logistics.shipment_journal (
	id SERIAL NOT NULL,
	generation INTEGER NOT NULL,
	CONSTRAINT pk_shipment_journal PRIMARY KEY (id)
);

CREATE TABLE procurement.deal_procurement_allocation (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	demand_id INTEGER NOT NULL,
	order_id INTEGER NOT NULL,
	order_line_id INTEGER NOT NULL,
	sku_code VARCHAR(64) NOT NULL,
	qty NUMERIC(14, 2) NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	evidence VARCHAR(1000) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_deal_procurement_allocation PRIMARY KEY (id),
	CONSTRAINT deal_demand_allocation_request UNIQUE (organization_id, request_key),
	CONSTRAINT ck_deal_procurement_allocation_deal_allocation_positive_refs CHECK (organization_id > 0 AND demand_id > 0 AND order_id > 0 AND order_line_id > 0),
	CONSTRAINT ck_deal_procurement_allocation_deal_allocation_qty CHECK (qty > 0 AND qty < 1000000000000)
);

CREATE INDEX ix_procurement_deal_procurement_allocation_demand_id ON procurement.deal_procurement_allocation (demand_id);

CREATE INDEX ix_procurement_deal_procurement_allocation_order_id ON procurement.deal_procurement_allocation (order_id);

CREATE INDEX ix_procurement_deal_procurement_allocation_order_line_id ON procurement.deal_procurement_allocation (order_line_id);

CREATE INDEX ix_procurement_deal_procurement_allocation_organization_id ON procurement.deal_procurement_allocation (organization_id);

CREATE TABLE procurement.deal_procurement_demand (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	deal_id INTEGER NOT NULL,
	deal_item_id INTEGER NOT NULL,
	sku_id INTEGER NOT NULL,
	sku_code VARCHAR(64) NOT NULL,
	qty NUMERIC(14, 2) NOT NULL,
	document_id INTEGER,
	request_key VARCHAR(36) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	evidence VARCHAR(1000) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_deal_procurement_demand PRIMARY KEY (id),
	CONSTRAINT deal_demand_request UNIQUE (organization_id, request_key),
	CONSTRAINT ck_deal_procurement_demand_deal_demand_positive_refs CHECK (organization_id > 0 AND deal_id > 0 AND deal_item_id > 0),
	CONSTRAINT ck_deal_procurement_demand_deal_demand_qty CHECK (qty > 0 AND qty < 1000000000000)
);

CREATE INDEX ix_procurement_deal_procurement_demand_deal_id ON procurement.deal_procurement_demand (deal_id);

CREATE INDEX ix_procurement_deal_procurement_demand_deal_item_id ON procurement.deal_procurement_demand (deal_item_id);

CREATE INDEX ix_procurement_deal_procurement_demand_organization_id ON procurement.deal_procurement_demand (organization_id);

CREATE TABLE procurement.expected_conversion_request (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	event_identity VARCHAR(64) NOT NULL,
	reservation_identity VARCHAR(64),
	payload_hash VARCHAR(64) NOT NULL,
	payload JSON NOT NULL,
	reservation_ids JSON NOT NULL,
	completed BOOLEAN NOT NULL,
	CONSTRAINT pk_expected_conversion_request PRIMARY KEY (id),
	CONSTRAINT expected_conversion_request_event UNIQUE (organization_id, event_identity),
	CONSTRAINT expected_conversion_request_reservation UNIQUE (organization_id, reservation_identity)
);

CREATE INDEX ix_procurement_expected_conversion_request_organization_id ON procurement.expected_conversion_request (organization_id);

CREATE TABLE procurement.expected_reservation (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	order_id INTEGER NOT NULL,
	order_line_id INTEGER NOT NULL,
	deal_id INTEGER NOT NULL,
	demand_id INTEGER,
	document_id INTEGER,
	sku_code VARCHAR(64) NOT NULL,
	qty NUMERIC(14, 2) NOT NULL,
	request_key VARCHAR(128) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	evidence VARCHAR(1000) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_expected_reservation PRIMARY KEY (id),
	CONSTRAINT expected_reservation_request UNIQUE (organization_id, request_key),
	CONSTRAINT ck_expected_reservation_expected_reservation_qty CHECK (qty > 0 AND qty < 1000000000000)
);

CREATE INDEX ix_procurement_expected_reservation_deal_id ON procurement.expected_reservation (deal_id);

CREATE INDEX ix_procurement_expected_reservation_demand_id ON procurement.expected_reservation (demand_id);

CREATE INDEX ix_procurement_expected_reservation_order_id ON procurement.expected_reservation (order_id);

CREATE INDEX ix_procurement_expected_reservation_order_line_id ON procurement.expected_reservation (order_line_id);

CREATE INDEX ix_procurement_expected_reservation_organization_id ON procurement.expected_reservation (organization_id);

CREATE TABLE procurement.physical_receipt_acceptance (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	event_id INTEGER NOT NULL,
	receipt_id INTEGER NOT NULL,
	source_receipt_id INTEGER NOT NULL,
	source_version INTEGER NOT NULL,
	lines JSON NOT NULL,
	evidence VARCHAR(1000) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_physical_receipt_acceptance PRIMARY KEY (id),
	CONSTRAINT physical_receipt_acceptance_event UNIQUE (organization_id, event_id),
	CONSTRAINT physical_receipt_acceptance_receipt UNIQUE (organization_id, receipt_id),
	CONSTRAINT ck_physical_receipt_acceptance_physical_receipt_acceptance_refs CHECK (organization_id > 0 AND event_id > 0 AND receipt_id > 0)
);

CREATE INDEX ix_procurement_physical_receipt_acceptance_event_id ON procurement.physical_receipt_acceptance (event_id);

CREATE INDEX ix_procurement_physical_receipt_acceptance_organization_id ON procurement.physical_receipt_acceptance (organization_id);

CREATE INDEX ix_procurement_physical_receipt_acceptance_receipt_id ON procurement.physical_receipt_acceptance (receipt_id);

CREATE INDEX ix_procurement_physical_receipt_acceptance_source_receipt_id ON procurement.physical_receipt_acceptance (source_receipt_id);

CREATE TABLE procurement.purchase_ownership (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	kind VARCHAR(16) NOT NULL,
	source_id INTEGER NOT NULL,
	snapshot JSON NOT NULL,
	evidence VARCHAR(1000) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_purchase_ownership PRIMARY KEY (id),
	CONSTRAINT uq_purchase_ownership_kind UNIQUE (kind, source_id),
	CONSTRAINT ck_purchase_ownership_purchase_ownership_kind CHECK (kind IN ('request','order')),
	CONSTRAINT ck_purchase_ownership_purchase_ownership_positive_id CHECK (source_id > 0)
);

CREATE INDEX ix_procurement_purchase_ownership_organization_id ON procurement.purchase_ownership (organization_id);

CREATE TABLE procurement.receipt_document (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	source_key VARCHAR(160) NOT NULL,
	current_version INTEGER NOT NULL,
	status VARCHAR(24) NOT NULL,
	created_by VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_receipt_document PRIMARY KEY (id),
	CONSTRAINT uq_receipt_document_organization_id UNIQUE (organization_id, source_key)
);

CREATE INDEX ix_procurement_receipt_document_organization_id ON procurement.receipt_document (organization_id);

CREATE TABLE sales.price_quote_request (
	request_key VARCHAR(36) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	result JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_price_quote_request PRIMARY KEY (request_key)
);

CREATE TABLE wms.invoice_reservation (
	document_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	digest VARCHAR(64) NOT NULL,
	snapshot JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	CONSTRAINT pk_invoice_reservation PRIMARY KEY (document_id)
);

CREATE INDEX ix_wms_invoice_reservation_organization_id ON wms.invoice_reservation (organization_id);

CREATE TABLE wms.reservation_event_state (
	document_id INTEGER NOT NULL,
	state VARCHAR(16) NOT NULL,
	quantities JSON NOT NULL,
	reserved_items JSON,
	CONSTRAINT pk_reservation_event_state PRIMARY KEY (document_id)
);

CREATE TABLE wms.reservation_version (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	source VARCHAR(200) NOT NULL,
	version INTEGER NOT NULL,
	sku_code VARCHAR(64) NOT NULL,
	warehouse VARCHAR(128) NOT NULL,
	qty NUMERIC(14, 2) NOT NULL,
	evidence VARCHAR(1000) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_reservation_version PRIMARY KEY (id),
	CONSTRAINT wms_reservation_source_version UNIQUE (organization_id, source, version),
	CONSTRAINT ck_reservation_version_wms_reservation_valid CHECK (organization_id > 0 AND version > 0 AND qty >= 0 AND qty < 1000000000000)
);

CREATE TABLE accounting.access_grant (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	subject VARCHAR(200) NOT NULL,
	role VARCHAR(20) NOT NULL,
	CONSTRAINT pk_access_grant PRIMARY KEY (id),
	CONSTRAINT uq_access_grant_organization_id UNIQUE (organization_id, subject),
	CONSTRAINT fk_access_grant_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE TABLE accounting.account (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	code VARCHAR(32) NOT NULL,
	title VARCHAR(200) NOT NULL,
	category VARCHAR(20) NOT NULL,
	valid_from DATE NOT NULL,
	required_dimensions JSON NOT NULL,
	currency_tracking BOOLEAN NOT NULL,
	quantity_tracking BOOLEAN NOT NULL,
	cash BOOLEAN NOT NULL,
	normative_ref VARCHAR(200) NOT NULL,
	CONSTRAINT pk_account PRIMARY KEY (id),
	CONSTRAINT uq_account_organization_id UNIQUE (organization_id, code, valid_from),
	CONSTRAINT fk_account_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE TABLE accounting.audit (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	actor VARCHAR(200) NOT NULL,
	action VARCHAR(60) NOT NULL,
	detail JSON NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_audit PRIMARY KEY (id),
	CONSTRAINT fk_audit_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE TABLE accounting.expense_budget (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	year INTEGER NOT NULL,
	currency VARCHAR(3) NOT NULL,
	basis VARCHAR(10) NOT NULL,
	revision INTEGER NOT NULL,
	state VARCHAR(10) NOT NULL,
	catalog_revision INTEGER NOT NULL,
	actor VARCHAR(200) NOT NULL,
	evidence VARCHAR(1000) NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_expense_budget PRIMARY KEY (id),
	CONSTRAINT uq_expense_budget_org_version UNIQUE (organization_id, year, currency, basis, revision),
	CONSTRAINT uq_expense_budget_org_id UNIQUE (organization_id, id),
	CONSTRAINT ck_expense_budget_expense_budget_revision_year CHECK (revision > 0 AND year BETWEEN 2000 AND 2100),
	CONSTRAINT ck_expense_budget_expense_budget_draft_only CHECK (currency = 'BYN' AND basis IN ('cash','accrual') AND state = 'draft'),
	CONSTRAINT fk_expense_budget_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE TABLE accounting.expense_catalog (
	organization_id INTEGER NOT NULL,
	revision INTEGER NOT NULL,
	CONSTRAINT pk_expense_catalog PRIMARY KEY (organization_id),
	CONSTRAINT ck_expense_catalog_expense_catalog_revision CHECK (revision >= 0),
	CONSTRAINT fk_expense_catalog_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE TABLE accounting.expense_command_receipt (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	kind VARCHAR(20) NOT NULL,
	command_hash VARCHAR(64) NOT NULL,
	receipt JSON NOT NULL,
	CONSTRAINT pk_expense_command_receipt PRIMARY KEY (id),
	CONSTRAINT uq_expense_command_receipt_organization_id UNIQUE (organization_id, request_key),
	CONSTRAINT fk_expense_command_receipt_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE TABLE accounting.expense_group (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	code VARCHAR(64) NOT NULL,
	title VARCHAR(200) NOT NULL,
	active BOOLEAN NOT NULL,
	CONSTRAINT pk_expense_group PRIMARY KEY (id),
	CONSTRAINT uq_expense_group_org_code UNIQUE (organization_id, code),
	CONSTRAINT uq_expense_group_org_id UNIQUE (organization_id, id),
	CONSTRAINT fk_expense_group_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE TABLE accounting.financial_reopen_receipt (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	from_month VARCHAR(7) NOT NULL,
	command JSON NOT NULL,
	command_digest VARCHAR(64) NOT NULL,
	snapshot JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_financial_reopen_receipt PRIMARY KEY (id),
	CONSTRAINT uq_financial_reopen_receipt_organization_id UNIQUE (organization_id, request_key),
	CONSTRAINT fk_financial_reopen_receipt_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE INDEX ix_accounting_financial_reopen_receipt_organization_id ON accounting.financial_reopen_receipt (organization_id);

CREATE TABLE accounting.opening_import_receipt (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	batch VARCHAR(120) NOT NULL,
	protocol_version VARCHAR(40) NOT NULL,
	source_system VARCHAR(80) NOT NULL,
	source_digest VARCHAR(64) NOT NULL,
	cutover_date DATE NOT NULL,
	entry_count INTEGER NOT NULL,
	line_count INTEGER NOT NULL,
	debit_total NUMERIC(20, 2) NOT NULL,
	credit_total NUMERIC(20, 2) NOT NULL,
	command_digest VARCHAR(64) NOT NULL,
	evidence VARCHAR(2000) NOT NULL,
	entry_ids JSON NOT NULL,
	snapshot JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_opening_import_receipt PRIMARY KEY (id),
	CONSTRAINT uq_opening_import_request UNIQUE (organization_id, request_key),
	CONSTRAINT uq_opening_import_command UNIQUE (organization_id, command_digest),
	CONSTRAINT ck_opening_import_receipt_opening_import_entry_count_positive CHECK (entry_count > 0),
	CONSTRAINT ck_opening_import_receipt_opening_import_line_count_valid CHECK (line_count >= entry_count),
	CONSTRAINT ck_opening_import_receipt_opening_import_totals_nonnegative CHECK (debit_total >= 0 AND credit_total >= 0),
	CONSTRAINT fk_opening_import_receipt_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE INDEX ix_accounting_opening_import_receipt_organization_id ON accounting.opening_import_receipt (organization_id);

CREATE TABLE accounting.period (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	month VARCHAR(7) NOT NULL,
	closed BOOLEAN NOT NULL,
	generation INTEGER NOT NULL,
	closed_generation INTEGER,
	evidence JSON NOT NULL,
	CONSTRAINT pk_period PRIMARY KEY (id),
	CONSTRAINT uq_period_organization_id UNIQUE (organization_id, month),
	CONSTRAINT fk_period_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE TABLE accounting.policy (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	effective_from DATE NOT NULL,
	reference VARCHAR(200) NOT NULL,
	inventory_method VARCHAR(32) NOT NULL,
	allocation_basis VARCHAR(32) NOT NULL,
	depreciation_method VARCHAR(32) NOT NULL,
	normative_reference VARCHAR(200) NOT NULL,
	normative_verified BOOLEAN NOT NULL,
	financial_closing JSON,
	currency_revaluation JSON,
	late_cost_allocation JSON,
	production_costing JSON,
	approved_by VARCHAR(200) NOT NULL,
	CONSTRAINT pk_policy PRIMARY KEY (id),
	CONSTRAINT uq_policy_organization_id UNIQUE (organization_id, effective_from),
	CONSTRAINT fk_policy_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE TABLE accounting.production_overhead_correction_withdrawal (
	organization_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	month VARCHAR(7) NOT NULL,
	command JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	reason VARCHAR(1000) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_production_overhead_correction_withdrawal PRIMARY KEY (organization_id, request_key),
	CONSTRAINT fk_production_overhead_correction_withdrawal_organizati_3538 FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE TABLE accounting.production_overhead_withdrawal (
	organization_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	month VARCHAR(7) NOT NULL,
	command JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	reason VARCHAR(1000) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_production_overhead_withdrawal PRIMARY KEY (organization_id, request_key),
	CONSTRAINT fk_production_overhead_withdrawal_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE TABLE accounting.reconciliation_receipt (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	period_from DATE NOT NULL,
	period_to DATE NOT NULL,
	left_digest VARCHAR(64) NOT NULL,
	right_digest VARCHAR(64) NOT NULL,
	left_status VARCHAR(20) NOT NULL,
	right_status VARCHAR(20) NOT NULL,
	left_pending_documents INTEGER NOT NULL,
	right_pending_documents INTEGER NOT NULL,
	left_rows INTEGER NOT NULL,
	right_rows INTEGER NOT NULL,
	difference_count INTEGER NOT NULL,
	command_digest VARCHAR(64) NOT NULL,
	evidence VARCHAR(2000) NOT NULL,
	snapshot JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_reconciliation_receipt PRIMARY KEY (id),
	CONSTRAINT uq_reconciliation_request UNIQUE (organization_id, request_key),
	CONSTRAINT uq_reconciliation_command UNIQUE (organization_id, command_digest),
	CONSTRAINT uq_reconciliation_source_pair UNIQUE (organization_id, left_digest, right_digest),
	CONSTRAINT ck_reconciliation_receipt_reconciliation_no_differences CHECK (difference_count = 0),
	CONSTRAINT ck_reconciliation_receipt_reconciliation_no_pending_documents CHECK (left_pending_documents = 0 AND right_pending_documents = 0),
	CONSTRAINT ck_reconciliation_receipt_reconciliation_reports_closed CHECK (left_status = 'closed_periods' AND right_status = 'closed_periods'),
	CONSTRAINT ck_reconciliation_receipt_reconciliation_row_counts_valid CHECK (left_rows >= 0 AND right_rows >= 0),
	CONSTRAINT fk_reconciliation_receipt_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE INDEX ix_accounting_reconciliation_receipt_organization_id ON accounting.reconciliation_receipt (organization_id);

CREATE TABLE accounting.seller_profile (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	revision INTEGER NOT NULL,
	effective_from DATE NOT NULL,
	currency VARCHAR(3) NOT NULL,
	source_key VARCHAR(160) NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	digest VARCHAR(64) NOT NULL,
	snapshot JSON NOT NULL,
	evidence VARCHAR(2000) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_seller_profile PRIMARY KEY (id),
	CONSTRAINT uq_seller_profile_org_revision UNIQUE (organization_id, revision),
	CONSTRAINT uq_seller_profile_org_source_key UNIQUE (organization_id, source_key),
	CONSTRAINT ck_seller_profile_seller_profile_revision CHECK (revision > 0),
	CONSTRAINT fk_seller_profile_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE TABLE accounting.shipment_preparation_draft (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	source VARCHAR(160) NOT NULL,
	revision INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	command_digest VARCHAR(64) NOT NULL,
	payload JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_shipment_preparation_draft PRIMARY KEY (id),
	CONSTRAINT uq_shipment_draft_source_revision UNIQUE (organization_id, source, revision),
	CONSTRAINT uq_shipment_draft_request UNIQUE (organization_id, request_key),
	CONSTRAINT ck_shipment_preparation_draft_shipment_draft_positive_revision CHECK (revision > 0),
	CONSTRAINT fk_shipment_preparation_draft_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE TABLE accounting.source_binding (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	source_type VARCHAR(40) NOT NULL,
	source_id INTEGER NOT NULL,
	ownership VARCHAR(16) NOT NULL,
	evidence VARCHAR(1000) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_source_binding PRIMARY KEY (id),
	CONSTRAINT uq_source_binding_source_type UNIQUE (source_type, source_id),
	CONSTRAINT ck_source_binding_source_binding_positive_id CHECK (source_id > 0),
	CONSTRAINT ck_source_binding_source_binding_type CHECK (source_type IN ('wms_receipt', 'logistics_import', 'finance_bank_transaction')),
	CONSTRAINT ck_source_binding_source_binding_ownership CHECK (ownership IN ('own', 'customer')),
	CONSTRAINT fk_source_binding_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE INDEX ix_accounting_source_binding_organization_id ON accounting.source_binding (organization_id);

CREATE TABLE logistics.rfq_invoice_binding (
	rfq_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	deal_id INTEGER NOT NULL,
	document_id INTEGER NOT NULL,
	document_version INTEGER NOT NULL,
	content_sha256 VARCHAR(64) NOT NULL,
	source_key VARCHAR(200) NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_rfq_invoice_binding PRIMARY KEY (rfq_id),
	CONSTRAINT uq_rfq_invoice_binding_organization_id UNIQUE (organization_id, source_key),
	CONSTRAINT fk_rfq_invoice_binding_rfq_id_carrier_rfq FOREIGN KEY(rfq_id) REFERENCES logistics.carrier_rfq (id)
);

CREATE TABLE logistics.shipment_intake (
	id SERIAL NOT NULL,
	source_kind VARCHAR(40) NOT NULL,
	source_key VARCHAR(200) NOT NULL,
	source_revision VARCHAR(80) NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	snapshot JSON NOT NULL,
	state VARCHAR(20) NOT NULL,
	pending_reason VARCHAR(200) NOT NULL,
	shipment_id INTEGER,
	rfq_id INTEGER,
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_shipment_intake PRIMARY KEY (id),
	CONSTRAINT uq_shipment_intake_source_kind UNIQUE (source_kind, source_key, source_revision),
	CONSTRAINT fk_shipment_intake_shipment_id_shipment FOREIGN KEY(shipment_id) REFERENCES logistics.shipment (id),
	CONSTRAINT fk_shipment_intake_rfq_id_carrier_rfq FOREIGN KEY(rfq_id) REFERENCES logistics.carrier_rfq (id)
);

CREATE TABLE logistics.shipment_invoice_binding (
	shipment_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	deal_id INTEGER NOT NULL,
	document_id INTEGER NOT NULL,
	document_version INTEGER NOT NULL,
	content_sha256 VARCHAR(64) NOT NULL,
	source_key VARCHAR(200) NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_shipment_invoice_binding PRIMARY KEY (shipment_id),
	CONSTRAINT uq_shipment_invoice_binding_organization_id UNIQUE (organization_id, source_key),
	CONSTRAINT ck_shipment_invoice_binding_shipment_binding_positive CHECK (organization_id > 0 AND document_id > 0 AND document_version > 0),
	CONSTRAINT fk_shipment_invoice_binding_shipment_id_shipment FOREIGN KEY(shipment_id) REFERENCES logistics.shipment (id)
);

CREATE TABLE office.shipping_request (
	id VARCHAR(36) NOT NULL,
	office_doc_id INTEGER NOT NULL,
	request_key VARCHAR(64) NOT NULL,
	source_snapshot JSON NOT NULL,
	source_sha256 VARCHAR(64) NOT NULL,
	payload JSON NOT NULL,
	payload_sha256 VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_shipping_request PRIMARY KEY (id),
	CONSTRAINT uq_shipping_request_office_doc_id UNIQUE (office_doc_id),
	CONSTRAINT fk_shipping_request_office_doc_id_office_doc FOREIGN KEY(office_doc_id) REFERENCES office.office_doc (id),
	CONSTRAINT uq_shipping_request_request_key UNIQUE (request_key)
);

CREATE TABLE office.shipping_review_assignment (
	id SERIAL NOT NULL,
	office_doc_id INTEGER NOT NULL,
	revision INTEGER NOT NULL,
	subject VARCHAR(200) NOT NULL,
	evidence VARCHAR(1000) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_shipping_review_assignment PRIMARY KEY (id),
	CONSTRAINT uq_office_shipping_review_revision UNIQUE (office_doc_id, revision),
	CONSTRAINT fk_shipping_review_assignment_office_doc_id_office_doc FOREIGN KEY(office_doc_id) REFERENCES office.office_doc (id)
);

CREATE TABLE procurement.expected_reservation_event (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	reservation_id INTEGER NOT NULL,
	kind VARCHAR(16) NOT NULL,
	qty NUMERIC(14, 2) NOT NULL,
	request_key VARCHAR(128) NOT NULL,
	evidence VARCHAR(1000) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_expected_reservation_event PRIMARY KEY (id),
	CONSTRAINT expected_reservation_event_request UNIQUE (organization_id, request_key),
	CONSTRAINT ck_expected_reservation_event_expected_reservation_event_values CHECK (kind IN ('release', 'convert') AND qty > 0 AND qty < 1000000000000),
	CONSTRAINT fk_expected_reservation_event_reservation_id_expected_r_5175 FOREIGN KEY(reservation_id) REFERENCES procurement.expected_reservation (id)
);

CREATE INDEX ix_procurement_expected_reservation_event_organization_id ON procurement.expected_reservation_event (organization_id);

CREATE TABLE procurement.order_request_link (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	order_ownership_id INTEGER NOT NULL,
	request_ownership_id INTEGER NOT NULL,
	evidence VARCHAR(1000) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_order_request_link PRIMARY KEY (id),
	CONSTRAINT uq_order_request_link_order_ownership_id UNIQUE (order_ownership_id, request_ownership_id),
	CONSTRAINT fk_order_request_link_order_ownership_id_purchase_ownership FOREIGN KEY(order_ownership_id) REFERENCES procurement.purchase_ownership (id),
	CONSTRAINT fk_order_request_link_request_ownership_id_purchase_ownership FOREIGN KEY(request_ownership_id) REFERENCES procurement.purchase_ownership (id)
);

CREATE INDEX ix_procurement_order_request_link_organization_id ON procurement.order_request_link (organization_id);

CREATE TABLE procurement.purchase_order_edit_command (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	target_order_id INTEGER NOT NULL,
	action VARCHAR(16) NOT NULL,
	outcome VARCHAR(16) NOT NULL,
	ownership_id INTEGER,
	command JSON NOT NULL,
	command_hash VARCHAR(64) NOT NULL,
	result JSON NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_purchase_order_edit_command PRIMARY KEY (id),
	CONSTRAINT uq_purchase_order_edit_command_organization_id UNIQUE (organization_id, request_key),
	CONSTRAINT ck_purchase_order_edit_command_edit_positive_ids CHECK (organization_id > 0 AND target_order_id > 0),
	CONSTRAINT ck_purchase_order_edit_command_edit_action CHECK (action IN ('add_line','delete_line','header','status','plan')),
	CONSTRAINT ck_purchase_order_edit_command_edit_outcome CHECK ((outcome='applied' AND ownership_id IS NOT NULL) OR (outcome='rejected' AND ownership_id IS NULL)),
	CONSTRAINT fk_purchase_order_edit_command_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_purchase_order_edit_command_ownership_id_purchase_ownership FOREIGN KEY(ownership_id) REFERENCES procurement.purchase_ownership (id)
);

CREATE TABLE procurement.purchase_request_creation (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	request_id INTEGER NOT NULL,
	ownership_id INTEGER NOT NULL,
	command JSON NOT NULL,
	command_hash VARCHAR(64) NOT NULL,
	result JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_purchase_request_creation PRIMARY KEY (id),
	CONSTRAINT uq_purchase_request_creation_organization_id UNIQUE (organization_id, request_key),
	CONSTRAINT uq_purchase_request_creation_request_id UNIQUE (request_id),
	CONSTRAINT uq_purchase_request_creation_ownership_id UNIQUE (ownership_id),
	CONSTRAINT ck_purchase_request_creation_request_creation_positive_refs CHECK (organization_id > 0 AND request_id > 0 AND ownership_id > 0),
	CONSTRAINT ck_purchase_request_creation_request_creation_key_hash_length CHECK (length(request_key) = 36 AND length(command_hash) = 64),
	CONSTRAINT fk_purchase_request_creation_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_purchase_request_creation_request_id_purchase_request FOREIGN KEY(request_id) REFERENCES procurement.purchase_request (id),
	CONSTRAINT fk_purchase_request_creation_ownership_id_purchase_ownership FOREIGN KEY(ownership_id) REFERENCES procurement.purchase_ownership (id)
);

CREATE INDEX ix_procurement_purchase_request_creation_organization_id ON procurement.purchase_request_creation (organization_id);

CREATE TABLE procurement.receipt_posting (
	receipt_id INTEGER NOT NULL,
	version INTEGER NOT NULL,
	entry_id INTEGER NOT NULL,
	options JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_receipt_posting PRIMARY KEY (receipt_id),
	CONSTRAINT fk_receipt_posting_receipt_id_receipt_document FOREIGN KEY(receipt_id) REFERENCES procurement.receipt_document (id),
	CONSTRAINT uq_receipt_posting_entry_id UNIQUE (entry_id)
);

CREATE TABLE procurement.receipt_revision (
	id SERIAL NOT NULL,
	receipt_id INTEGER NOT NULL,
	version INTEGER NOT NULL,
	document JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_receipt_revision PRIMARY KEY (id),
	CONSTRAINT uq_receipt_revision_receipt_id UNIQUE (receipt_id, version),
	CONSTRAINT fk_receipt_revision_receipt_id_receipt_document FOREIGN KEY(receipt_id) REFERENCES procurement.receipt_document (id)
);

CREATE TABLE sales.deal_item_request (
	request_key VARCHAR(36) NOT NULL,
	deal_id INTEGER NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	result JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_deal_item_request PRIMARY KEY (request_key),
	CONSTRAINT fk_deal_item_request_deal_id_deal FOREIGN KEY(deal_id) REFERENCES sales.deal (id)
);

CREATE INDEX ix_sales_deal_item_request_deal_id ON sales.deal_item_request (deal_id);

CREATE TABLE sales.deal_loss_request (
	id VARCHAR(36) NOT NULL,
	organization_id INTEGER NOT NULL,
	deal_id INTEGER NOT NULL,
	command JSON NOT NULL,
	command_hash VARCHAR(64) NOT NULL,
	snapshot JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	state VARCHAR(16) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_deal_loss_request PRIMARY KEY (id),
	CONSTRAINT fk_deal_loss_request_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_deal_loss_request_deal_id_deal FOREIGN KEY(deal_id) REFERENCES sales.deal (id)
);

CREATE UNIQUE INDEX uq_deal_loss_pending ON sales.deal_loss_request (deal_id) WHERE state = 'pending';

CREATE TABLE sales.deal_ownership (
	deal_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	snapshot JSON NOT NULL,
	evidence VARCHAR(1000) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_deal_ownership PRIMARY KEY (deal_id),
	CONSTRAINT fk_deal_ownership_deal_id_deal FOREIGN KEY(deal_id) REFERENCES sales.deal (id)
);

CREATE INDEX ix_sales_deal_ownership_organization_id ON sales.deal_ownership (organization_id);

CREATE TABLE wms.invoice_reservation_release (
	id SERIAL NOT NULL,
	document_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	source_key VARCHAR(160) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	digest VARCHAR(64) NOT NULL,
	snapshot JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_invoice_reservation_release PRIMARY KEY (id),
	CONSTRAINT uq_invoice_reservation_release_organization_id UNIQUE (organization_id, source_key),
	CONSTRAINT ck_invoice_reservation_release_invoice_release_org CHECK (organization_id > 0),
	CONSTRAINT uq_invoice_reservation_release_document_id UNIQUE (document_id),
	CONSTRAINT fk_invoice_reservation_release_document_id_invoice_reservation FOREIGN KEY(document_id) REFERENCES wms.invoice_reservation (document_id)
);

CREATE TABLE wms.physical_shipment_act (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	document_id INTEGER NOT NULL,
	document_version INTEGER NOT NULL,
	content_sha256 VARCHAR(64) NOT NULL,
	reservation_digest VARCHAR(64) NOT NULL,
	source_key VARCHAR(36) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	operation_date DATE NOT NULL,
	actor VARCHAR(200) NOT NULL,
	snapshot JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	CONSTRAINT pk_physical_shipment_act PRIMARY KEY (id),
	CONSTRAINT physical_act_request UNIQUE (organization_id, source_key),
	CONSTRAINT fk_physical_shipment_act_document_id_invoice_reservation FOREIGN KEY(document_id) REFERENCES wms.invoice_reservation (document_id)
);

CREATE INDEX ix_wms_physical_shipment_act_document_id ON wms.physical_shipment_act (document_id);

CREATE TABLE wms.primary_receipt_binding (
	receipt_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	source_receipt_id INTEGER NOT NULL,
	source_version INTEGER NOT NULL,
	command JSON NOT NULL,
	source_snapshot JSON NOT NULL,
	line_bindings JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_primary_receipt_binding PRIMARY KEY (receipt_id),
	CONSTRAINT uq_primary_receipt_binding_organization_id UNIQUE (organization_id, request_key),
	CONSTRAINT fk_primary_receipt_binding_receipt_id_receipt FOREIGN KEY(receipt_id) REFERENCES wms.receipt (id)
);

CREATE INDEX ix_wms_primary_receipt_binding_organization_id ON wms.primary_receipt_binding (organization_id);

CREATE INDEX ix_wms_primary_receipt_binding_source_receipt_id ON wms.primary_receipt_binding (source_receipt_id);

CREATE TABLE accounting.entry (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	source VARCHAR(160) NOT NULL,
	source_version INTEGER NOT NULL,
	operation VARCHAR(60) NOT NULL,
	document_date DATE NOT NULL,
	operation_date DATE NOT NULL,
	posting_date DATE NOT NULL,
	policy_id INTEGER NOT NULL,
	rule_version VARCHAR(100) NOT NULL,
	explanation VARCHAR(1000) NOT NULL,
	opening BOOLEAN NOT NULL,
	correction_of INTEGER,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_entry PRIMARY KEY (id),
	CONSTRAINT uq_entry_organization_id UNIQUE (organization_id, source, source_version, operation),
	CONSTRAINT fk_entry_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_entry_policy_id_policy FOREIGN KEY(policy_id) REFERENCES accounting.policy (id),
	CONSTRAINT fk_entry_correction_of_entry FOREIGN KEY(correction_of) REFERENCES accounting.entry (id)
);

CREATE INDEX ix_accounting_entry_organization_id ON accounting.entry (organization_id);

CREATE INDEX ix_accounting_entry_posting_date ON accounting.entry (posting_date);

CREATE TABLE accounting.expense_article (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	group_id INTEGER NOT NULL,
	code VARCHAR(64) NOT NULL,
	title VARCHAR(200) NOT NULL,
	active BOOLEAN NOT NULL,
	CONSTRAINT pk_expense_article PRIMARY KEY (id),
	CONSTRAINT fk_expense_article_organization_id_expense_group FOREIGN KEY(organization_id, group_id) REFERENCES accounting.expense_group (organization_id, id),
	CONSTRAINT uq_expense_article_org_code UNIQUE (organization_id, code),
	CONSTRAINT uq_expense_article_org_id UNIQUE (organization_id, id),
	CONSTRAINT fk_expense_article_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE TABLE accounting.expense_budget_approval (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	budget_id INTEGER NOT NULL,
	budget_revision INTEGER NOT NULL,
	actor VARCHAR(200) NOT NULL,
	evidence VARCHAR(1000) NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	budget_snapshot JSON NOT NULL,
	approval_digest VARCHAR(64) NOT NULL,
	approved_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_expense_budget_approval PRIMARY KEY (id),
	CONSTRAINT fk_expense_budget_approval_organization_id_expense_budget FOREIGN KEY(organization_id, budget_id) REFERENCES accounting.expense_budget (organization_id, id),
	CONSTRAINT uq_expense_budget_approval_budget UNIQUE (organization_id, budget_id),
	CONSTRAINT uq_expense_budget_approval_org_id UNIQUE (organization_id, id),
	CONSTRAINT ck_expense_budget_approval_expense_budget_approval_revision CHECK (budget_revision > 0),
	CONSTRAINT fk_expense_budget_approval_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE TABLE logistics.shipping_execution (
	id VARCHAR(36) NOT NULL,
	organization_id INTEGER NOT NULL,
	document_id INTEGER NOT NULL,
	document_version INTEGER NOT NULL,
	content_sha256 VARCHAR(64) NOT NULL,
	intent JSON NOT NULL,
	intent_digest VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_shipping_execution PRIMARY KEY (id),
	CONSTRAINT shipping_execution_invoice_version UNIQUE (organization_id, document_id, document_version),
	CONSTRAINT ck_shipping_execution_shipping_execution_positive CHECK (organization_id > 0 AND document_id > 0 AND document_version > 0),
	CONSTRAINT fk_shipping_execution_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_shipping_execution_document_id_deal_document FOREIGN KEY(document_id) REFERENCES sales.deal_document (id)
);

CREATE TABLE office.office_invoice_association (
	id VARCHAR(36) NOT NULL,
	request_id VARCHAR(36) NOT NULL,
	office_doc_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	exact_invoice JSON NOT NULL,
	execution_id VARCHAR(36) NOT NULL,
	intent_digest VARCHAR(64) NOT NULL,
	assignment_revision INTEGER NOT NULL,
	request_key VARCHAR(64) NOT NULL,
	confirmation_sha256 VARCHAR(64) NOT NULL,
	evidence_refs JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_office_invoice_association PRIMARY KEY (id),
	CONSTRAINT uq_office_invoice_association_request_id UNIQUE (request_id),
	CONSTRAINT fk_office_invoice_association_request_id_shipping_request FOREIGN KEY(request_id) REFERENCES office.shipping_request (id),
	CONSTRAINT uq_office_invoice_association_office_doc_id UNIQUE (office_doc_id),
	CONSTRAINT fk_office_invoice_association_office_doc_id_office_doc FOREIGN KEY(office_doc_id) REFERENCES office.office_doc (id),
	CONSTRAINT uq_office_invoice_association_request_key UNIQUE (request_key)
);

CREATE INDEX ix_office_office_invoice_association_organization_id ON office.office_invoice_association (organization_id);

CREATE TABLE procurement.purchase_order_creation (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	outcome VARCHAR(16) NOT NULL,
	order_id INTEGER,
	ownership_id INTEGER,
	request_id INTEGER,
	request_ownership_id INTEGER,
	link_id INTEGER,
	command JSON NOT NULL,
	command_hash VARCHAR(64) NOT NULL,
	result JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_purchase_order_creation PRIMARY KEY (id),
	CONSTRAINT uq_purchase_order_creation_organization_id UNIQUE (organization_id, request_key),
	CONSTRAINT uq_purchase_order_creation_order_id UNIQUE (order_id),
	CONSTRAINT uq_purchase_order_creation_ownership_id UNIQUE (ownership_id),
	CONSTRAINT uq_purchase_order_creation_request_id UNIQUE (request_id),
	CONSTRAINT uq_purchase_order_creation_link_id UNIQUE (link_id),
	CONSTRAINT ck_purchase_order_creation_order_creation_positive_org CHECK (organization_id > 0),
	CONSTRAINT ck_purchase_order_creation_order_creation_outcome CHECK (outcome IN ('created','rejected')),
	CONSTRAINT ck_purchase_order_creation_order_creation_outcome_refs CHECK ((outcome='created' AND order_id IS NOT NULL AND ownership_id IS NOT NULL AND order_id > 0 AND ownership_id > 0) OR (outcome='rejected' AND order_id IS NULL AND ownership_id IS NULL AND request_id IS NULL AND request_ownership_id IS NULL AND link_id IS NULL)),
	CONSTRAINT ck_purchase_order_creation_order_creation_link_refs CHECK ((request_id IS NULL AND request_ownership_id IS NULL AND link_id IS NULL) OR (request_id IS NOT NULL AND request_ownership_id IS NOT NULL AND link_id IS NOT NULL AND request_id > 0 AND request_ownership_id > 0 AND link_id > 0)),
	CONSTRAINT fk_purchase_order_creation_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_purchase_order_creation_order_id_purchase_order FOREIGN KEY(order_id) REFERENCES procurement.purchase_order (id),
	CONSTRAINT fk_purchase_order_creation_ownership_id_purchase_ownership FOREIGN KEY(ownership_id) REFERENCES procurement.purchase_ownership (id),
	CONSTRAINT fk_purchase_order_creation_request_id_purchase_request FOREIGN KEY(request_id) REFERENCES procurement.purchase_request (id),
	CONSTRAINT fk_purchase_order_creation_request_ownership_id_purchas_ea3a FOREIGN KEY(request_ownership_id) REFERENCES procurement.purchase_ownership (id),
	CONSTRAINT fk_purchase_order_creation_link_id_order_request_link FOREIGN KEY(link_id) REFERENCES procurement.order_request_link (id)
);

CREATE INDEX ix_procurement_purchase_order_creation_organization_id ON procurement.purchase_order_creation (organization_id);

CREATE TABLE sales.deal_loss_resolution (
	id VARCHAR(36) NOT NULL,
	request_id VARCHAR(36) NOT NULL,
	action VARCHAR(16) NOT NULL,
	command JSON NOT NULL,
	command_hash VARCHAR(64) NOT NULL,
	snapshot JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_deal_loss_resolution PRIMARY KEY (id),
	CONSTRAINT uq_deal_loss_resolution_request_id UNIQUE (request_id),
	CONSTRAINT fk_deal_loss_resolution_request_id_deal_loss_request FOREIGN KEY(request_id) REFERENCES sales.deal_loss_request (id)
);

CREATE TABLE sales.invoice_money_reconciliation (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	document_id INTEGER NOT NULL,
	source_key VARCHAR(160) NOT NULL,
	basis_digest VARCHAR(64) NOT NULL,
	history_from DATE NOT NULL,
	history_through DATE NOT NULL,
	request JSON NOT NULL,
	facts JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_invoice_money_reconciliation PRIMARY KEY (id),
	CONSTRAINT uq_invoice_money_reconciliation_organization_id UNIQUE (organization_id, source_key),
	CONSTRAINT fk_invoice_money_reconciliation_document_id_deal_document FOREIGN KEY(document_id) REFERENCES sales.deal_document (id)
);

CREATE INDEX ix_sales_invoice_money_reconciliation_document_id ON sales.invoice_money_reconciliation (document_id);

CREATE INDEX ix_sales_invoice_money_reconciliation_organization_id ON sales.invoice_money_reconciliation (organization_id);

CREATE TABLE sales.invoice_notification (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	deal_id INTEGER NOT NULL,
	document_id INTEGER NOT NULL,
	document_version INTEGER NOT NULL,
	event_id INTEGER NOT NULL,
	event_type VARCHAR(64) NOT NULL,
	business_key VARCHAR(128) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	channel VARCHAR(16) DEFAULT 'email' NOT NULL,
	recipient VARCHAR(254),
	state VARCHAR(16) NOT NULL,
	reason VARCHAR(128),
	payload JSON NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_invoice_notification PRIMARY KEY (id),
	CONSTRAINT uq_invoice_notification_event UNIQUE (organization_id, event_id),
	CONSTRAINT uq_invoice_notification_business UNIQUE (organization_id, business_key),
	CONSTRAINT ck_invoice_notification_invoice_notification_org_positive CHECK (organization_id > 0),
	CONSTRAINT ck_invoice_notification_invoice_notification_deal_positive CHECK (deal_id > 0),
	CONSTRAINT ck_invoice_notification_invoice_notification_document_positive CHECK (document_id > 0),
	CONSTRAINT ck_invoice_notification_invoice_notification_version_positive CHECK (document_version > 0),
	CONSTRAINT ck_invoice_notification_invoice_notification_event_positive CHECK (event_id > 0),
	CONSTRAINT ck_invoice_notification_invoice_notification_channel_email CHECK (channel = 'email'),
	CONSTRAINT ck_invoice_notification_invoice_notification_state CHECK (state IN ('pending', 'blocked')),
	CONSTRAINT ck_invoice_notification_invoice_notification_block_reason CHECK (state = 'pending' OR reason IS NOT NULL),
	CONSTRAINT fk_invoice_notification_deal_id_deal FOREIGN KEY(deal_id) REFERENCES sales.deal (id),
	CONSTRAINT fk_invoice_notification_document_id_deal_document FOREIGN KEY(document_id) REFERENCES sales.deal_document (id)
);

CREATE INDEX ix_invoice_notification_document ON sales.invoice_notification (organization_id, document_id, created_at);

CREATE INDEX ix_sales_invoice_notification_deal_id ON sales.invoice_notification (deal_id);

CREATE INDEX ix_sales_invoice_notification_document_id ON sales.invoice_notification (document_id);

CREATE TABLE sales.invoice_settlement (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	document_id INTEGER NOT NULL,
	source_key VARCHAR(160) NOT NULL,
	bank_entry_id INTEGER NOT NULL,
	direction VARCHAR(10) NOT NULL,
	amount NUMERIC(20, 2) NOT NULL,
	refund_of INTEGER,
	evidence VARCHAR(1000) NOT NULL,
	snapshot JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_invoice_settlement PRIMARY KEY (id),
	CONSTRAINT uq_invoice_settlement_organization_id UNIQUE (organization_id, source_key),
	CONSTRAINT ck_invoice_settlement_invoice_settlement_positive CHECK (amount > 0),
	CONSTRAINT ck_invoice_settlement_invoice_settlement_direction CHECK ((direction = 'receipt' AND refund_of IS NULL) OR (direction = 'refund' AND refund_of IS NOT NULL)),
	CONSTRAINT fk_invoice_settlement_document_id_deal_document FOREIGN KEY(document_id) REFERENCES sales.deal_document (id),
	CONSTRAINT fk_invoice_settlement_refund_of_invoice_settlement FOREIGN KEY(refund_of) REFERENCES sales.invoice_settlement (id)
);

CREATE INDEX ix_sales_invoice_settlement_bank_entry_id ON sales.invoice_settlement (bank_entry_id);

CREATE INDEX ix_sales_invoice_settlement_document_id ON sales.invoice_settlement (document_id);

CREATE INDEX ix_sales_invoice_settlement_organization_id ON sales.invoice_settlement (organization_id);

CREATE TABLE sales.shipping_envelope (
	id VARCHAR(36) NOT NULL,
	order_document_id INTEGER NOT NULL,
	order_version INTEGER NOT NULL,
	source_sha256 VARCHAR(64) NOT NULL,
	request_key VARCHAR(64) NOT NULL,
	payload JSON NOT NULL,
	payload_sha256 VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_shipping_envelope PRIMARY KEY (id),
	CONSTRAINT uq_sales_shipping_envelope_source UNIQUE (order_document_id, order_version),
	CONSTRAINT fk_shipping_envelope_order_document_id_deal_document FOREIGN KEY(order_document_id) REFERENCES sales.deal_document (id),
	CONSTRAINT uq_shipping_envelope_request_key UNIQUE (request_key)
);

CREATE TABLE wms.invoice_reservation_release_line (
	id SERIAL NOT NULL,
	release_id INTEGER NOT NULL,
	before_id INTEGER NOT NULL,
	after_id INTEGER NOT NULL,
	source VARCHAR(200) NOT NULL,
	line_no INTEGER NOT NULL,
	released_qty NUMERIC(14, 2) NOT NULL,
	CONSTRAINT pk_invoice_reservation_release_line PRIMARY KEY (id),
	CONSTRAINT uq_invoice_reservation_release_line_release_id UNIQUE (release_id, source),
	CONSTRAINT ck_invoice_reservation_release_line_invoice_release_line_valid CHECK (line_no > 0 AND released_qty > 0 AND before_id <> after_id),
	CONSTRAINT fk_invoice_reservation_release_line_release_id_invoice__d993 FOREIGN KEY(release_id) REFERENCES wms.invoice_reservation_release (id),
	CONSTRAINT uq_invoice_reservation_release_line_before_id UNIQUE (before_id),
	CONSTRAINT fk_invoice_reservation_release_line_before_id_reservati_65a4 FOREIGN KEY(before_id) REFERENCES wms.reservation_version (id),
	CONSTRAINT uq_invoice_reservation_release_line_after_id UNIQUE (after_id),
	CONSTRAINT fk_invoice_reservation_release_line_after_id_reservatio_187f FOREIGN KEY(after_id) REFERENCES wms.reservation_version (id)
);

CREATE TABLE wms.physical_shipment_line (
	id SERIAL NOT NULL,
	act_id INTEGER NOT NULL,
	source VARCHAR(128) NOT NULL,
	line_no INTEGER NOT NULL,
	sku_code VARCHAR(64) NOT NULL,
	warehouse VARCHAR(128) NOT NULL,
	qty NUMERIC(14, 2) NOT NULL,
	before_id INTEGER NOT NULL,
	after_id INTEGER NOT NULL,
	movement_id INTEGER NOT NULL,
	CONSTRAINT pk_physical_shipment_line PRIMARY KEY (id),
	CONSTRAINT physical_line_source UNIQUE (act_id, source),
	CONSTRAINT physical_line_before UNIQUE (before_id),
	CONSTRAINT physical_line_after UNIQUE (after_id),
	CONSTRAINT physical_line_movement UNIQUE (movement_id),
	CONSTRAINT ck_physical_shipment_line_physical_line_quantity CHECK (qty > 0 AND qty < 1000000000000 AND line_no > 0),
	CONSTRAINT fk_physical_shipment_line_act_id_physical_shipment_act FOREIGN KEY(act_id) REFERENCES wms.physical_shipment_act (id),
	CONSTRAINT fk_physical_shipment_line_before_id_reservation_version FOREIGN KEY(before_id) REFERENCES wms.reservation_version (id),
	CONSTRAINT fk_physical_shipment_line_after_id_reservation_version FOREIGN KEY(after_id) REFERENCES wms.reservation_version (id),
	CONSTRAINT fk_physical_shipment_line_movement_id_stock_movement FOREIGN KEY(movement_id) REFERENCES wms.stock_movement (id)
);

CREATE TABLE wms.reservation_pick (
	task_id INTEGER NOT NULL,
	document_id INTEGER NOT NULL,
	CONSTRAINT pk_reservation_pick PRIMARY KEY (task_id),
	CONSTRAINT fk_reservation_pick_task_id_task FOREIGN KEY(task_id) REFERENCES wms.task (id),
	CONSTRAINT fk_reservation_pick_document_id_reservation_event_state FOREIGN KEY(document_id) REFERENCES wms.reservation_event_state (document_id)
);

CREATE INDEX ix_wms_reservation_pick_document_id ON wms.reservation_pick (document_id);

CREATE TABLE accounting.bank_import_receipt (
	entry_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	source_transaction_id INTEGER NOT NULL,
	source_ext_id VARCHAR(128) NOT NULL,
	source_digest VARCHAR(64) NOT NULL,
	source VARCHAR(160) NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	bank_account VARCHAR(32) NOT NULL,
	settlement_account VARCHAR(32) NOT NULL,
	amount NUMERIC(20, 2) NOT NULL,
	document_date DATE NOT NULL,
	operation_date DATE NOT NULL,
	posting_date DATE NOT NULL,
	command JSON NOT NULL,
	command_digest VARCHAR(64) NOT NULL,
	basis_digest VARCHAR(64) NOT NULL,
	snapshot JSON NOT NULL,
	posting JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_bank_import_receipt PRIMARY KEY (entry_id),
	CONSTRAINT uq_bank_import_source UNIQUE (organization_id, source_transaction_id),
	CONSTRAINT uq_bank_import_request UNIQUE (organization_id, request_key),
	CONSTRAINT uq_bank_import_entry UNIQUE (entry_id),
	CONSTRAINT ck_bank_import_receipt_bank_import_source_positive CHECK (source_transaction_id > 0),
	CONSTRAINT ck_bank_import_receipt_bank_import_amount_positive CHECK (amount > 0),
	CONSTRAINT fk_bank_import_receipt_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_bank_import_receipt_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE INDEX ix_accounting_bank_import_receipt_organization_id ON accounting.bank_import_receipt (organization_id);

CREATE INDEX ix_accounting_bank_import_receipt_posting_date ON accounting.bank_import_receipt (posting_date);

CREATE INDEX ix_accounting_bank_import_receipt_source_transaction_id ON accounting.bank_import_receipt (source_transaction_id);

CREATE TABLE accounting.expense_budget_line (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	budget_id INTEGER NOT NULL,
	article_id INTEGER NOT NULL,
	months JSON NOT NULL,
	article_snapshot JSON NOT NULL,
	CONSTRAINT pk_expense_budget_line PRIMARY KEY (id),
	CONSTRAINT fk_expense_budget_line_organization_id_expense_budget FOREIGN KEY(organization_id, budget_id) REFERENCES accounting.expense_budget (organization_id, id),
	CONSTRAINT fk_expense_budget_line_organization_id_expense_article FOREIGN KEY(organization_id, article_id) REFERENCES accounting.expense_article (organization_id, id),
	CONSTRAINT uq_expense_budget_line_budget_id UNIQUE (budget_id, article_id)
);

CREATE TABLE accounting.financial_close_receipt (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	month VARCHAR(7) NOT NULL,
	command JSON NOT NULL,
	command_digest VARCHAR(64) NOT NULL,
	snapshot JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	monthly_entry_id INTEGER,
	annual_entry_id INTEGER,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_financial_close_receipt PRIMARY KEY (id),
	CONSTRAINT uq_financial_close_receipt_organization_id UNIQUE (organization_id, request_key),
	CONSTRAINT uq_financial_close_receipt_monthly_entry_id UNIQUE (monthly_entry_id),
	CONSTRAINT uq_financial_close_receipt_annual_entry_id UNIQUE (annual_entry_id),
	CONSTRAINT fk_financial_close_receipt_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_financial_close_receipt_monthly_entry_id_entry FOREIGN KEY(monthly_entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_financial_close_receipt_annual_entry_id_entry FOREIGN KEY(annual_entry_id) REFERENCES accounting.entry (id)
);

CREATE INDEX ix_accounting_financial_close_receipt_month ON accounting.financial_close_receipt (month);

CREATE INDEX ix_accounting_financial_close_receipt_organization_id ON accounting.financial_close_receipt (organization_id);

CREATE TABLE accounting.fx_revaluation_receipt (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	month VARCHAR(7) NOT NULL,
	source_version INTEGER NOT NULL,
	command JSON NOT NULL,
	command_digest VARCHAR(64) NOT NULL,
	snapshot JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	entry_id INTEGER,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_fx_revaluation_receipt PRIMARY KEY (id),
	CONSTRAINT uq_fx_revaluation_request UNIQUE (organization_id, request_key),
	CONSTRAINT uq_fx_revaluation_source_version UNIQUE (organization_id, month, source_version),
	CONSTRAINT uq_fx_revaluation_entry UNIQUE (entry_id),
	CONSTRAINT ck_fx_revaluation_receipt_fx_revaluation_source_version_3ebb CHECK (source_version > 0),
	CONSTRAINT fk_fx_revaluation_receipt_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_fx_revaluation_receipt_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id)
);

CREATE INDEX ix_accounting_fx_revaluation_receipt_month ON accounting.fx_revaluation_receipt (month);

CREATE INDEX ix_accounting_fx_revaluation_receipt_organization_id ON accounting.fx_revaluation_receipt (organization_id);

CREATE TABLE accounting.inbox (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	event_key VARCHAR(160) NOT NULL,
	month VARCHAR(7) NOT NULL,
	payload JSON NOT NULL,
	error VARCHAR(1000),
	entry_id INTEGER,
	CONSTRAINT pk_inbox PRIMARY KEY (id),
	CONSTRAINT uq_inbox_organization_id UNIQUE (organization_id, event_key),
	CONSTRAINT fk_inbox_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_inbox_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id)
);

CREATE TABLE accounting.inventory_issue_receipt (
	entry_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	command JSON NOT NULL,
	cost JSON NOT NULL,
	posting JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_inventory_issue_receipt PRIMARY KEY (entry_id),
	CONSTRAINT fk_inventory_issue_receipt_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_inventory_issue_receipt_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE INDEX ix_accounting_inventory_issue_receipt_organization_id ON accounting.inventory_issue_receipt (organization_id);

CREATE TABLE accounting.inventory_sale_receipt (
	entry_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	command JSON NOT NULL,
	cost JSON NOT NULL,
	posting JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_inventory_sale_receipt PRIMARY KEY (entry_id),
	CONSTRAINT fk_inventory_sale_receipt_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_inventory_sale_receipt_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE INDEX ix_accounting_inventory_sale_receipt_organization_id ON accounting.inventory_sale_receipt (organization_id);

CREATE TABLE accounting.line (
	id SERIAL NOT NULL,
	entry_id INTEGER NOT NULL,
	account_id INTEGER NOT NULL,
	account_code VARCHAR(32) NOT NULL,
	account_title VARCHAR(200) NOT NULL,
	category VARCHAR(20) NOT NULL,
	cash BOOLEAN NOT NULL,
	side VARCHAR(6) NOT NULL,
	amount NUMERIC(20, 2) NOT NULL,
	dimensions JSON NOT NULL,
	currency VARCHAR(3) NOT NULL,
	original_amount NUMERIC(20, 2),
	rate NUMERIC(24, 6),
	rate_scale INTEGER,
	rate_date DATE,
	rate_source VARCHAR(200),
	quantity NUMERIC(24, 6),
	cash_activity VARCHAR(20),
	CONSTRAINT pk_line PRIMARY KEY (id),
	CONSTRAINT ck_line_amount_nonnegative CHECK (amount >= 0),
	CONSTRAINT ck_line_side_valid CHECK (side IN ('debit','credit')),
	CONSTRAINT fk_line_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_line_account_id_account FOREIGN KEY(account_id) REFERENCES accounting.account (id)
);

CREATE INDEX ix_accounting_line_entry_id ON accounting.line (entry_id);

CREATE TABLE accounting.payroll_accrual_receipt (
	entry_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	month VARCHAR(7) NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	source_document VARCHAR(160) NOT NULL,
	source_version INTEGER NOT NULL,
	source_digest VARCHAR(64) NOT NULL,
	command JSON NOT NULL,
	source JSON NOT NULL,
	posting JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_payroll_accrual_receipt PRIMARY KEY (entry_id),
	CONSTRAINT uq_payroll_accrual_request UNIQUE (organization_id, request_key),
	CONSTRAINT uq_payroll_accrual_source UNIQUE (organization_id, source_document, source_version),
	CONSTRAINT ck_payroll_accrual_receipt_payroll_accrual_source_versi_b784 CHECK (source_version > 0),
	CONSTRAINT fk_payroll_accrual_receipt_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_payroll_accrual_receipt_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE INDEX ix_accounting_payroll_accrual_receipt_month ON accounting.payroll_accrual_receipt (month);

CREATE INDEX ix_accounting_payroll_accrual_receipt_organization_id ON accounting.payroll_accrual_receipt (organization_id);

CREATE TABLE accounting.payroll_statutory_receipt (
	entry_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	month VARCHAR(7) NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	source_document VARCHAR(160) NOT NULL,
	source_version INTEGER NOT NULL,
	source_digest VARCHAR(64) NOT NULL,
	command JSON NOT NULL,
	source JSON NOT NULL,
	posting JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_payroll_statutory_receipt PRIMARY KEY (entry_id),
	CONSTRAINT uq_payroll_statutory_request UNIQUE (organization_id, request_key),
	CONSTRAINT uq_payroll_statutory_source UNIQUE (organization_id, source_document, source_version),
	CONSTRAINT ck_payroll_statutory_receipt_payroll_statutory_source_v_0d68 CHECK (source_version > 0),
	CONSTRAINT fk_payroll_statutory_receipt_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_payroll_statutory_receipt_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE INDEX ix_accounting_payroll_statutory_receipt_month ON accounting.payroll_statutory_receipt (month);

CREATE INDEX ix_accounting_payroll_statutory_receipt_organization_id ON accounting.payroll_statutory_receipt (organization_id);

CREATE TABLE accounting.production_labor_receipt (
	entry_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	month VARCHAR(7) NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	source_document VARCHAR(160) NOT NULL,
	source_version INTEGER NOT NULL,
	source_digest VARCHAR(64) NOT NULL,
	command JSON NOT NULL,
	source JSON NOT NULL,
	posting JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_production_labor_receipt PRIMARY KEY (entry_id),
	CONSTRAINT uq_production_labor_request UNIQUE (organization_id, request_key),
	CONSTRAINT uq_production_labor_source UNIQUE (organization_id, source_document, source_version),
	CONSTRAINT fk_production_labor_receipt_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_production_labor_receipt_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE INDEX ix_accounting_production_labor_receipt_month ON accounting.production_labor_receipt (month);

CREATE INDEX ix_accounting_production_labor_receipt_organization_id ON accounting.production_labor_receipt (organization_id);

CREATE TABLE accounting.production_output_transfer_receipt (
	entry_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	order_id INTEGER NOT NULL,
	month VARCHAR(7) NOT NULL,
	command JSON NOT NULL,
	basis JSON NOT NULL,
	posting JSON NOT NULL,
	basis_digest VARCHAR(64) NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_production_output_transfer_receipt PRIMARY KEY (entry_id),
	CONSTRAINT uq_production_output_transfer_order UNIQUE (organization_id, order_id),
	CONSTRAINT fk_production_output_transfer_receipt_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_production_output_transfer_receipt_organization_id_o_2f4e FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE INDEX ix_accounting_production_output_transfer_receipt_organi_69c2 ON accounting.production_output_transfer_receipt (organization_id);

CREATE TABLE accounting.production_overhead_receipt (
	entry_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	month VARCHAR(7) NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	command JSON NOT NULL,
	review JSON NOT NULL,
	posting JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_production_overhead_receipt PRIMARY KEY (entry_id),
	CONSTRAINT uq_production_overhead_month UNIQUE (organization_id, month),
	CONSTRAINT uq_production_overhead_request UNIQUE (organization_id, request_key),
	CONSTRAINT fk_production_overhead_receipt_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_production_overhead_receipt_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE TABLE accounting.repair_accounting_receipt (
	entry_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	service_request_id INTEGER NOT NULL,
	month VARCHAR(7) NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	source_version INTEGER NOT NULL,
	source_digest VARCHAR(64) NOT NULL,
	serial_number VARCHAR(160) NOT NULL,
	owner_type VARCHAR(16) NOT NULL,
	owner_reference VARCHAR(200) NOT NULL,
	coverage VARCHAR(16) NOT NULL,
	command JSON NOT NULL,
	source JSON NOT NULL,
	posting JSON NOT NULL,
	financial_result JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_repair_accounting_receipt PRIMARY KEY (entry_id),
	CONSTRAINT uq_repair_accounting_request UNIQUE (organization_id, request_key),
	CONSTRAINT uq_repair_accounting_source UNIQUE (organization_id, service_request_id, source_version),
	CONSTRAINT ck_repair_accounting_receipt_repair_accounting_coverage CHECK (coverage IN ('paid','warranty')),
	CONSTRAINT ck_repair_accounting_receipt_repair_accounting_owner_type CHECK (owner_type IN ('customer','organization')),
	CONSTRAINT fk_repair_accounting_receipt_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_repair_accounting_receipt_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE INDEX ix_accounting_repair_accounting_receipt_month ON accounting.repair_accounting_receipt (month);

CREATE INDEX ix_accounting_repair_accounting_receipt_organization_id ON accounting.repair_accounting_receipt (organization_id);

CREATE INDEX ix_accounting_repair_accounting_receipt_service_request_id ON accounting.repair_accounting_receipt (service_request_id);

CREATE TABLE accounting.settlement_offset_receipt (
	entry_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	bank_entry_id INTEGER NOT NULL,
	kind VARCHAR(32) NOT NULL,
	target_document VARCHAR(160) NOT NULL,
	source_account VARCHAR(32) NOT NULL,
	target_account VARCHAR(32) NOT NULL,
	amount NUMERIC(20, 2) NOT NULL,
	document_date DATE NOT NULL,
	operation_date DATE NOT NULL,
	posting_date DATE NOT NULL,
	command JSON NOT NULL,
	command_digest VARCHAR(64) NOT NULL,
	basis_digest VARCHAR(64) NOT NULL,
	source_snapshot JSON NOT NULL,
	target_snapshot JSON NOT NULL,
	snapshot JSON NOT NULL,
	posting JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_settlement_offset_receipt PRIMARY KEY (entry_id),
	CONSTRAINT uq_settlement_offset_request UNIQUE (organization_id, request_key),
	CONSTRAINT uq_settlement_offset_entry UNIQUE (entry_id),
	CONSTRAINT ck_settlement_offset_receipt_settlement_offset_amount_positive CHECK (amount > 0),
	CONSTRAINT ck_settlement_offset_receipt_settlement_offset_kind_valid CHECK (kind IN ('customer_advance','supplier_advance')),
	CONSTRAINT fk_settlement_offset_receipt_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_settlement_offset_receipt_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_settlement_offset_receipt_bank_entry_id_entry FOREIGN KEY(bank_entry_id) REFERENCES accounting.entry (id)
);

CREATE INDEX ix_accounting_settlement_offset_receipt_bank_entry_id ON accounting.settlement_offset_receipt (bank_entry_id);

CREATE INDEX ix_accounting_settlement_offset_receipt_organization_id ON accounting.settlement_offset_receipt (organization_id);

CREATE INDEX ix_accounting_settlement_offset_receipt_posting_date ON accounting.settlement_offset_receipt (posting_date);

CREATE TABLE accounting.shipment_accounting_receipt (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	source VARCHAR(160) NOT NULL,
	act_digest VARCHAR(64) NOT NULL,
	command JSON NOT NULL,
	basis_digest VARCHAR(64) NOT NULL,
	snapshot JSON NOT NULL,
	anchor_entry_id INTEGER NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_shipment_accounting_receipt PRIMARY KEY (id),
	CONSTRAINT uq_shipment_accounting_receipt_organization_id UNIQUE (organization_id, source),
	CONSTRAINT uq_shipment_accounting_receipt_anchor_entry_id UNIQUE (anchor_entry_id),
	CONSTRAINT fk_shipment_accounting_receipt_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_shipment_accounting_receipt_anchor_entry_id_entry FOREIGN KEY(anchor_entry_id) REFERENCES accounting.entry (id)
);

CREATE TABLE accounting.source_control (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	source VARCHAR(160) NOT NULL,
	version INTEGER NOT NULL,
	month VARCHAR(7) NOT NULL,
	entry_id INTEGER,
	CONSTRAINT pk_source_control PRIMARY KEY (id),
	CONSTRAINT uq_source_control_organization_id UNIQUE (organization_id, source),
	CONSTRAINT fk_source_control_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_source_control_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id)
);

CREATE INDEX ix_accounting_source_control_organization_id ON accounting.source_control (organization_id);

CREATE TABLE sales.invoice_fulfillment_review (
	id VARCHAR(36) NOT NULL,
	organization_id INTEGER NOT NULL,
	document_id INTEGER NOT NULL,
	money_reconciliation_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	request JSON NOT NULL,
	snapshot JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_invoice_fulfillment_review PRIMARY KEY (id),
	CONSTRAINT uq_invoice_fulfillment_review_organization_id UNIQUE (organization_id, request_key),
	CONSTRAINT fk_invoice_fulfillment_review_document_id_deal_document FOREIGN KEY(document_id) REFERENCES sales.deal_document (id),
	CONSTRAINT fk_invoice_fulfillment_review_money_reconciliation_id_i_5320 FOREIGN KEY(money_reconciliation_id) REFERENCES sales.invoice_money_reconciliation (id)
);

CREATE INDEX ix_sales_invoice_fulfillment_review_document_id ON sales.invoice_fulfillment_review (document_id);

CREATE INDEX ix_sales_invoice_fulfillment_review_organization_id ON sales.invoice_fulfillment_review (organization_id);

CREATE TABLE sales.order_invoice_association (
	id VARCHAR(36) NOT NULL,
	envelope_id VARCHAR(36) NOT NULL,
	organization_id INTEGER NOT NULL,
	deal_id INTEGER NOT NULL,
	exact_invoice JSON NOT NULL,
	execution_id VARCHAR(36) NOT NULL,
	intent_digest VARCHAR(64) NOT NULL,
	request_key VARCHAR(64) NOT NULL,
	confirmation_sha256 VARCHAR(64) NOT NULL,
	evidence_refs JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_order_invoice_association PRIMARY KEY (id),
	CONSTRAINT uq_order_invoice_association_envelope_id UNIQUE (envelope_id),
	CONSTRAINT fk_order_invoice_association_envelope_id_shipping_envelope FOREIGN KEY(envelope_id) REFERENCES sales.shipping_envelope (id),
	CONSTRAINT fk_order_invoice_association_deal_id_deal FOREIGN KEY(deal_id) REFERENCES sales.deal (id),
	CONSTRAINT uq_order_invoice_association_request_key UNIQUE (request_key)
);

CREATE INDEX ix_sales_order_invoice_association_organization_id ON sales.order_invoice_association (organization_id);

CREATE TABLE accounting.financial_reopen_item (
	id SERIAL NOT NULL,
	reopen_receipt_id INTEGER NOT NULL,
	close_receipt_id INTEGER NOT NULL,
	monthly_entry_id INTEGER,
	annual_entry_id INTEGER,
	CONSTRAINT pk_financial_reopen_item PRIMARY KEY (id),
	CONSTRAINT uq_financial_reopen_item_close_receipt_id UNIQUE (close_receipt_id),
	CONSTRAINT uq_financial_reopen_item_monthly_entry_id UNIQUE (monthly_entry_id),
	CONSTRAINT uq_financial_reopen_item_annual_entry_id UNIQUE (annual_entry_id),
	CONSTRAINT fk_financial_reopen_item_reopen_receipt_id_financial_re_579b FOREIGN KEY(reopen_receipt_id) REFERENCES accounting.financial_reopen_receipt (id),
	CONSTRAINT fk_financial_reopen_item_close_receipt_id_financial_clo_0742 FOREIGN KEY(close_receipt_id) REFERENCES accounting.financial_close_receipt (id),
	CONSTRAINT fk_financial_reopen_item_monthly_entry_id_entry FOREIGN KEY(monthly_entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_financial_reopen_item_annual_entry_id_entry FOREIGN KEY(annual_entry_id) REFERENCES accounting.entry (id)
);

CREATE TABLE accounting.fixed_asset_register_entry (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	asset_key VARCHAR(160) NOT NULL,
	source_entry_id INTEGER NOT NULL,
	source_line_id INTEGER NOT NULL,
	source_digest VARCHAR(64) NOT NULL,
	name VARCHAR(200) NOT NULL,
	inventory_number VARCHAR(100) NOT NULL,
	acquisition_date DATE NOT NULL,
	commissioning_date DATE NOT NULL,
	depreciation_start DATE NOT NULL,
	cost NUMERIC(20, 2) NOT NULL,
	residual_value NUMERIC(20, 2) NOT NULL,
	useful_life_months INTEGER NOT NULL,
	depreciation_method VARCHAR(32) NOT NULL,
	asset_account VARCHAR(32) NOT NULL,
	accumulated_account VARCHAR(32) NOT NULL,
	expense_account VARCHAR(32) NOT NULL,
	dimensions JSON NOT NULL,
	evidence VARCHAR(2000) NOT NULL,
	command JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_fixed_asset_register_entry PRIMARY KEY (id),
	CONSTRAINT uq_fixed_asset_register_request UNIQUE (organization_id, request_key),
	CONSTRAINT uq_fixed_asset_register_asset_key UNIQUE (organization_id, asset_key),
	CONSTRAINT uq_fixed_asset_register_source_line UNIQUE (organization_id, source_entry_id, source_line_id),
	CONSTRAINT ck_fixed_asset_register_entry_fixed_asset_register_cost_0040 CHECK (cost > 0),
	CONSTRAINT ck_fixed_asset_register_entry_fixed_asset_register_resi_2abc CHECK (residual_value >= 0 AND residual_value <= cost),
	CONSTRAINT ck_fixed_asset_register_entry_fixed_asset_register_life_3c8b CHECK (useful_life_months > 0),
	CONSTRAINT ck_fixed_asset_register_entry_fixed_asset_register_method CHECK (depreciation_method IN ('straight_line','declining_balance','production_units')),
	CONSTRAINT fk_fixed_asset_register_entry_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_fixed_asset_register_entry_source_entry_id_entry FOREIGN KEY(source_entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_fixed_asset_register_entry_source_line_id_line FOREIGN KEY(source_line_id) REFERENCES accounting.line (id)
);

CREATE INDEX ix_accounting_fixed_asset_register_entry_asset_key ON accounting.fixed_asset_register_entry (asset_key);

CREATE INDEX ix_accounting_fixed_asset_register_entry_organization_id ON accounting.fixed_asset_register_entry (organization_id);

CREATE INDEX ix_accounting_fixed_asset_register_entry_source_entry_id ON accounting.fixed_asset_register_entry (source_entry_id);

CREATE INDEX ix_accounting_fixed_asset_register_entry_source_line_id ON accounting.fixed_asset_register_entry (source_line_id);

CREATE TABLE accounting.foreign_trade_register_entry (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	entry_id INTEGER NOT NULL,
	line_id INTEGER NOT NULL,
	source VARCHAR(160) NOT NULL,
	source_version INTEGER NOT NULL,
	entry_digest VARCHAR(64) NOT NULL,
	posting_date DATE NOT NULL,
	tax_period VARCHAR(7) NOT NULL,
	trade_mode VARCHAR(32) NOT NULL,
	partner_country VARCHAR(64) NOT NULL,
	contract_reference VARCHAR(200) NOT NULL,
	invoice_reference VARCHAR(200) NOT NULL,
	customs_reference VARCHAR(200),
	eaeu_reference VARCHAR(200),
	incoterms VARCHAR(16),
	amount NUMERIC(20, 2) NOT NULL,
	currency VARCHAR(3) NOT NULL,
	original_amount NUMERIC(20, 2),
	rate NUMERIC(24, 6),
	rate_scale INTEGER,
	rate_date DATE,
	rate_source VARCHAR(200),
	customs_duty NUMERIC(20, 2) DEFAULT '0' NOT NULL,
	import_vat NUMERIC(20, 2) DEFAULT '0' NOT NULL,
	export_evidence VARCHAR(2000),
	evidence VARCHAR(2000) NOT NULL,
	command JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_foreign_trade_register_entry PRIMARY KEY (id),
	CONSTRAINT uq_foreign_trade_register_request UNIQUE (organization_id, request_key),
	CONSTRAINT uq_foreign_trade_register_line UNIQUE (organization_id, entry_id, line_id),
	CONSTRAINT ck_foreign_trade_register_entry_foreign_trade_register__56c3 CHECK (source_version > 0),
	CONSTRAINT ck_foreign_trade_register_entry_foreign_trade_register__681c CHECK (trade_mode IN ('eaeu_import','third_country_import','export')),
	CONSTRAINT ck_foreign_trade_register_entry_foreign_trade_register__9fdf CHECK (amount > 0),
	CONSTRAINT ck_foreign_trade_register_entry_foreign_trade_register__c415 CHECK (customs_duty >= 0 AND import_vat >= 0),
	CONSTRAINT fk_foreign_trade_register_entry_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_foreign_trade_register_entry_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_foreign_trade_register_entry_line_id_line FOREIGN KEY(line_id) REFERENCES accounting.line (id)
);

CREATE INDEX ix_accounting_foreign_trade_register_entry_entry_id ON accounting.foreign_trade_register_entry (entry_id);

CREATE INDEX ix_accounting_foreign_trade_register_entry_line_id ON accounting.foreign_trade_register_entry (line_id);

CREATE INDEX ix_accounting_foreign_trade_register_entry_organization_id ON accounting.foreign_trade_register_entry (organization_id);

CREATE INDEX ix_accounting_foreign_trade_register_entry_posting_date ON accounting.foreign_trade_register_entry (posting_date);

CREATE INDEX ix_accounting_foreign_trade_register_entry_tax_period ON accounting.foreign_trade_register_entry (tax_period);

CREATE INDEX ix_accounting_foreign_trade_register_entry_trade_mode ON accounting.foreign_trade_register_entry (trade_mode);

CREATE TABLE accounting.input_vat_register_entry (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	entry_id INTEGER NOT NULL,
	line_id INTEGER NOT NULL,
	source VARCHAR(160) NOT NULL,
	source_version INTEGER NOT NULL,
	entry_digest VARCHAR(64) NOT NULL,
	posting_date DATE NOT NULL,
	tax_period VARCHAR(7) NOT NULL,
	amount NUMERIC(20, 2) NOT NULL,
	currency VARCHAR(3) NOT NULL,
	side VARCHAR(6) NOT NULL,
	invoice_reference VARCHAR(200) NOT NULL,
	eschf_identifier VARCHAR(200),
	deduction_status VARCHAR(20) NOT NULL,
	eschf_status VARCHAR(20) NOT NULL,
	right_basis VARCHAR(2000) NOT NULL,
	evidence VARCHAR(2000) NOT NULL,
	command JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_input_vat_register_entry PRIMARY KEY (id),
	CONSTRAINT uq_input_vat_register_request UNIQUE (organization_id, request_key),
	CONSTRAINT uq_input_vat_register_line UNIQUE (organization_id, entry_id, line_id),
	CONSTRAINT ck_input_vat_register_entry_input_vat_register_source_v_8dd3 CHECK (source_version > 0),
	CONSTRAINT ck_input_vat_register_entry_input_vat_register_deduction_status CHECK (deduction_status IN ('not_assessed','pending','eligible','not_eligible')),
	CONSTRAINT ck_input_vat_register_entry_input_vat_register_eschf_status CHECK (eschf_status IN ('not_provided','provided','not_required','pending')),
	CONSTRAINT fk_input_vat_register_entry_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_input_vat_register_entry_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_input_vat_register_entry_line_id_line FOREIGN KEY(line_id) REFERENCES accounting.line (id)
);

CREATE INDEX ix_accounting_input_vat_register_entry_entry_id ON accounting.input_vat_register_entry (entry_id);

CREATE INDEX ix_accounting_input_vat_register_entry_line_id ON accounting.input_vat_register_entry (line_id);

CREATE INDEX ix_accounting_input_vat_register_entry_organization_id ON accounting.input_vat_register_entry (organization_id);

CREATE INDEX ix_accounting_input_vat_register_entry_posting_date ON accounting.input_vat_register_entry (posting_date);

CREATE INDEX ix_accounting_input_vat_register_entry_tax_period ON accounting.input_vat_register_entry (tax_period);

CREATE TABLE accounting.output_vat_register_entry (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	entry_id INTEGER NOT NULL,
	line_id INTEGER NOT NULL,
	source VARCHAR(160) NOT NULL,
	source_version INTEGER NOT NULL,
	entry_digest VARCHAR(64) NOT NULL,
	posting_date DATE NOT NULL,
	tax_period VARCHAR(7) NOT NULL,
	amount NUMERIC(20, 2) NOT NULL,
	currency VARCHAR(3) NOT NULL,
	side VARCHAR(6) NOT NULL,
	invoice_reference VARCHAR(200) NOT NULL,
	eschf_identifier VARCHAR(200),
	tax_treatment VARCHAR(20) NOT NULL,
	eschf_status VARCHAR(20) NOT NULL,
	treatment_basis VARCHAR(2000) NOT NULL,
	export_evidence VARCHAR(2000),
	evidence VARCHAR(2000) NOT NULL,
	command JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_output_vat_register_entry PRIMARY KEY (id),
	CONSTRAINT uq_output_vat_register_request UNIQUE (organization_id, request_key),
	CONSTRAINT uq_output_vat_register_line UNIQUE (organization_id, entry_id, line_id),
	CONSTRAINT ck_output_vat_register_entry_output_vat_register_source_5de3 CHECK (source_version > 0),
	CONSTRAINT ck_output_vat_register_entry_output_vat_register_tax_treatment CHECK (tax_treatment IN ('not_assessed','pending','standard','zero_export','exempt','not_subject')),
	CONSTRAINT ck_output_vat_register_entry_output_vat_register_eschf_status CHECK (eschf_status IN ('not_provided','provided','not_required','pending')),
	CONSTRAINT fk_output_vat_register_entry_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_output_vat_register_entry_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_output_vat_register_entry_line_id_line FOREIGN KEY(line_id) REFERENCES accounting.line (id)
);

CREATE INDEX ix_accounting_output_vat_register_entry_entry_id ON accounting.output_vat_register_entry (entry_id);

CREATE INDEX ix_accounting_output_vat_register_entry_line_id ON accounting.output_vat_register_entry (line_id);

CREATE INDEX ix_accounting_output_vat_register_entry_organization_id ON accounting.output_vat_register_entry (organization_id);

CREATE INDEX ix_accounting_output_vat_register_entry_posting_date ON accounting.output_vat_register_entry (posting_date);

CREATE INDEX ix_accounting_output_vat_register_entry_tax_period ON accounting.output_vat_register_entry (tax_period);

CREATE TABLE accounting.production_overhead_revision (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	original_entry_id INTEGER NOT NULL,
	sequence INTEGER NOT NULL,
	previous_id INTEGER,
	entry_id INTEGER,
	month VARCHAR(7) NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	command JSON NOT NULL,
	preview JSON NOT NULL,
	posting JSON,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_production_overhead_revision PRIMARY KEY (id),
	CONSTRAINT uq_overhead_revision_request UNIQUE (organization_id, request_key),
	CONSTRAINT uq_overhead_revision_sequence UNIQUE (original_entry_id, sequence),
	CONSTRAINT fk_production_overhead_revision_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_production_overhead_revision_original_entry_id_produ_2557 FOREIGN KEY(original_entry_id) REFERENCES accounting.production_overhead_receipt (entry_id),
	CONSTRAINT fk_production_overhead_revision_previous_id_production__e20a FOREIGN KEY(previous_id) REFERENCES accounting.production_overhead_revision (id),
	CONSTRAINT uq_production_overhead_revision_entry_id UNIQUE (entry_id),
	CONSTRAINT fk_production_overhead_revision_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id)
);

CREATE TABLE sales.invoice_cancellation_receipt (
	id VARCHAR(36) NOT NULL,
	organization_id INTEGER NOT NULL,
	document_id INTEGER NOT NULL,
	document_version INTEGER NOT NULL,
	content_sha256 VARCHAR(64) NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	request JSON NOT NULL,
	fulfillment_review_id VARCHAR(36) NOT NULL,
	release_id INTEGER NOT NULL,
	snapshot JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_invoice_cancellation_receipt PRIMARY KEY (id),
	CONSTRAINT uq_invoice_cancellation_receipt_organization_id UNIQUE (organization_id, request_key),
	CONSTRAINT uq_invoice_cancellation_receipt_document_id UNIQUE (document_id),
	CONSTRAINT fk_invoice_cancellation_receipt_document_id_deal_document FOREIGN KEY(document_id) REFERENCES sales.deal_document (id),
	CONSTRAINT fk_invoice_cancellation_receipt_fulfillment_review_id_i_5d32 FOREIGN KEY(fulfillment_review_id) REFERENCES sales.invoice_fulfillment_review (id),
	CONSTRAINT uq_invoice_cancellation_receipt_release_id UNIQUE (release_id),
	CONSTRAINT fk_invoice_cancellation_receipt_release_id_invoice_rese_41ec FOREIGN KEY(release_id) REFERENCES wms.invoice_reservation_release (id)
);

CREATE INDEX ix_sales_invoice_cancellation_receipt_organization_id ON sales.invoice_cancellation_receipt (organization_id);

CREATE TABLE accounting.fixed_asset_depreciation_receipt (
	entry_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	asset_id INTEGER NOT NULL,
	month VARCHAR(7) NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	command JSON NOT NULL,
	calculation JSON NOT NULL,
	posting JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_fixed_asset_depreciation_receipt PRIMARY KEY (entry_id),
	CONSTRAINT uq_fixed_asset_depreciation_request UNIQUE (organization_id, request_key),
	CONSTRAINT uq_fixed_asset_depreciation_asset_month UNIQUE (organization_id, asset_id, month),
	CONSTRAINT fk_fixed_asset_depreciation_receipt_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_fixed_asset_depreciation_receipt_organization_id_org_cdc6 FOREIGN KEY(organization_id) REFERENCES accounting.organization (id),
	CONSTRAINT fk_fixed_asset_depreciation_receipt_asset_id_fixed_asse_1bf5 FOREIGN KEY(asset_id) REFERENCES accounting.fixed_asset_register_entry (id)
);

CREATE INDEX ix_accounting_fixed_asset_depreciation_receipt_asset_id ON accounting.fixed_asset_depreciation_receipt (asset_id);

CREATE INDEX ix_accounting_fixed_asset_depreciation_receipt_month ON accounting.fixed_asset_depreciation_receipt (month);

CREATE INDEX ix_accounting_fixed_asset_depreciation_receipt_organization_id ON accounting.fixed_asset_depreciation_receipt (organization_id);

CREATE TABLE procurement.additional_expense_document (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	source_key VARCHAR(160) NOT NULL,
	created_by VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_additional_expense_document PRIMARY KEY (id),
	CONSTRAINT uq_additional_expense_document_organization_id UNIQUE (organization_id, source_key)
);

CREATE INDEX ix_procurement_additional_expense_document_organization_id ON procurement.additional_expense_document (organization_id);

CREATE TABLE procurement.additional_expense_revision (
	id SERIAL NOT NULL,
	expense_id INTEGER NOT NULL,
	version INTEGER NOT NULL,
	document JSON NOT NULL,
	receipt_sources JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_additional_expense_revision PRIMARY KEY (id),
	CONSTRAINT uq_additional_expense_revision_expense_id UNIQUE (expense_id, version),
	CONSTRAINT fk_additional_expense_revision_expense_id_additional_ex_a8dd FOREIGN KEY(expense_id) REFERENCES procurement.additional_expense_document (id)
);

CREATE TABLE accounting.late_cost_receipt (
	entry_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	expense_id INTEGER NOT NULL,
	source_version INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	command JSON NOT NULL,
	calculation JSON NOT NULL,
	posting JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_late_cost_receipt PRIMARY KEY (entry_id),
	CONSTRAINT uq_late_cost_source UNIQUE (organization_id, expense_id),
	CONSTRAINT uq_late_cost_request UNIQUE (organization_id, request_key),
	CONSTRAINT ck_late_cost_receipt_late_cost_positive_version CHECK (source_version > 0),
	CONSTRAINT fk_late_cost_receipt_entry_id_entry FOREIGN KEY(entry_id) REFERENCES accounting.entry (id),
	CONSTRAINT fk_late_cost_receipt_organization_id_organization FOREIGN KEY(organization_id) REFERENCES accounting.organization (id)
);

CREATE INDEX ix_accounting_late_cost_receipt_organization_id ON accounting.late_cost_receipt (organization_id);

CREATE TABLE production.order_ownership (
	order_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	snapshot JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	evidence VARCHAR(1000) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_order_ownership PRIMARY KEY (order_id),
	CONSTRAINT fk_order_ownership_order_id_production_order FOREIGN KEY(order_id) REFERENCES production.production_order (id)
);

CREATE INDEX ix_production_order_ownership_organization_id ON production.order_ownership (organization_id);

CREATE TABLE production.order_creation_receipt (
	order_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	request_id VARCHAR(36) NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	command JSON NOT NULL,
	result JSON NOT NULL,
	CONSTRAINT pk_order_creation_receipt PRIMARY KEY (order_id),
	CONSTRAINT uq_order_creation_receipt_organization_id UNIQUE (organization_id, request_id),
	CONSTRAINT fk_order_creation_receipt_order_id_order_ownership FOREIGN KEY(order_id) REFERENCES production.order_ownership (order_id)
);

CREATE TABLE production.output_document (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	order_id INTEGER NOT NULL,
	request_id VARCHAR(36) NOT NULL,
	command JSON NOT NULL,
	snapshot JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	registered_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_output_document PRIMARY KEY (id),
	CONSTRAINT uq_output_document_organization_id UNIQUE (organization_id, request_id),
	CONSTRAINT fk_output_document_order_id_order_ownership FOREIGN KEY(order_id) REFERENCES production.order_ownership (order_id)
);

CREATE TABLE production.output_confirmation (
	document_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	order_id INTEGER NOT NULL,
	event_id INTEGER NOT NULL,
	quantity NUMERIC(14, 2) NOT NULL,
	digest VARCHAR(64) NOT NULL,
	actor VARCHAR(200) NOT NULL,
	registered_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_output_confirmation PRIMARY KEY (document_id),
	CONSTRAINT fk_output_confirmation_document_id_output_document FOREIGN KEY(document_id) REFERENCES production.output_document (id),
	CONSTRAINT fk_output_confirmation_order_id_order_ownership FOREIGN KEY(order_id) REFERENCES production.order_ownership (order_id),
	CONSTRAINT uq_output_confirmation_event_id UNIQUE (event_id),
	CONSTRAINT fk_output_confirmation_event_id_outbox_event FOREIGN KEY(event_id) REFERENCES outbox_event (id)
);

CREATE INDEX ix_production_output_confirmation_order_id ON production.output_confirmation (order_id);

CREATE TABLE wms.production_arrival (
	receipt_id INTEGER NOT NULL,
	line_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	event_id INTEGER NOT NULL,
	movement_id INTEGER,
	accepted_quantity NUMERIC(14, 2) NOT NULL,
	rejected_quantity NUMERIC(14, 2) NOT NULL,
	CONSTRAINT pk_production_arrival PRIMARY KEY (receipt_id),
	CONSTRAINT fk_production_arrival_receipt_id_receipt FOREIGN KEY(receipt_id) REFERENCES wms.receipt (id),
	CONSTRAINT uq_production_arrival_line_id UNIQUE (line_id),
	CONSTRAINT fk_production_arrival_line_id_receipt_line FOREIGN KEY(line_id) REFERENCES wms.receipt_line (id),
	CONSTRAINT uq_production_arrival_event_id UNIQUE (event_id),
	CONSTRAINT fk_production_arrival_event_id_outbox_event FOREIGN KEY(event_id) REFERENCES outbox_event (id),
	CONSTRAINT uq_production_arrival_movement_id UNIQUE (movement_id),
	CONSTRAINT fk_production_arrival_movement_id_stock_movement FOREIGN KEY(movement_id) REFERENCES wms.stock_movement (id)
);

CREATE TABLE wms.production_material_issue (
	id SERIAL NOT NULL,
	organization_id INTEGER NOT NULL,
	order_id INTEGER NOT NULL,
	movement_id INTEGER NOT NULL,
	request_key VARCHAR(36) NOT NULL,
	operation_date DATE NOT NULL,
	snapshot JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_production_material_issue PRIMARY KEY (id),
	CONSTRAINT uq_production_material_issue_request UNIQUE (organization_id, request_key),
	CONSTRAINT uq_production_material_issue_movement UNIQUE (movement_id),
	CONSTRAINT fk_production_material_issue_order_id_order_ownership FOREIGN KEY(order_id) REFERENCES production.order_ownership (order_id),
	CONSTRAINT fk_production_material_issue_movement_id_stock_movement FOREIGN KEY(movement_id) REFERENCES wms.stock_movement (id)
);

CREATE INDEX ix_wms_production_material_issue_order_id ON wms.production_material_issue (order_id);

CREATE INDEX ix_wms_production_material_issue_organization_id ON wms.production_material_issue (organization_id);

CREATE TABLE production.order_completion (
	order_id INTEGER NOT NULL,
	organization_id INTEGER NOT NULL,
	command JSON NOT NULL,
	snapshot JSON NOT NULL,
	actor VARCHAR(200) NOT NULL,
	registered_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_order_completion PRIMARY KEY (order_id),
	CONSTRAINT fk_order_completion_order_id_order_ownership FOREIGN KEY(order_id) REFERENCES production.order_ownership (order_id)
);

-- Additional-expense primary history is append-only, including raw SQL writes.
CREATE OR REPLACE FUNCTION procurement.reject_additional_expense_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Additional expense source history is immutable';
END $$;
CREATE TRIGGER immutable_additional_expense_document
BEFORE UPDATE OR DELETE OR TRUNCATE ON procurement.additional_expense_document
FOR EACH STATEMENT EXECUTE FUNCTION procurement.reject_additional_expense_mutation();

CREATE OR REPLACE FUNCTION procurement.check_additional_expense(expense integer) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE h procurement.additional_expense_document%ROWTYPE;
        r procurement.additional_expense_revision%ROWTYPE;
        c accounting.source_control%ROWTYPE;
        n integer; latest integer;
BEGIN
  SELECT * INTO h FROM procurement.additional_expense_document WHERE id = expense;
  IF NOT FOUND THEN RAISE EXCEPTION 'Additional expense header is missing'; END IF;
  SELECT count(*), max(version) INTO n, latest FROM procurement.additional_expense_revision WHERE expense_id = expense;
  IF n = 0 OR latest <> n OR EXISTS (SELECT 1 FROM procurement.additional_expense_revision
      WHERE expense_id = expense AND version < 1) THEN
    RAISE EXCEPTION 'Additional expense revision chain is incomplete';
  END IF;
  SELECT * INTO r FROM procurement.additional_expense_revision WHERE expense_id = expense AND version = latest;
  SELECT * INTO c FROM accounting.source_control WHERE organization_id = h.organization_id
    AND source = 'procurement:additional-expense:' || expense;
  IF NOT FOUND OR c.version IS DISTINCT FROM latest OR c.month IS DISTINCT FROM left(r.document->>'operation_date', 7)
     OR (c.entry_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM accounting.late_cost_receipt l
       WHERE l.entry_id=c.entry_id AND l.organization_id=h.organization_id AND l.expense_id=expense
         AND l.source_version=latest)) THEN
    RAISE EXCEPTION 'Additional expense completeness registration is missing or inconsistent';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION procurement.check_additional_expense_trigger() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME = 'additional_expense_document' THEN
    PERFORM procurement.check_additional_expense(NEW.id);
  ELSIF TG_TABLE_NAME = 'additional_expense_revision' THEN
    PERFORM procurement.check_additional_expense(NEW.expense_id);
  ELSE
    IF NEW.source LIKE 'procurement:additional-expense:%' THEN
      PERFORM procurement.check_additional_expense(substring(NEW.source FROM 32)::integer);
    END IF;
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_additional_expense_header AFTER INSERT ON procurement.additional_expense_document
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION procurement.check_additional_expense_trigger();
CREATE CONSTRAINT TRIGGER complete_additional_expense_revision AFTER INSERT ON procurement.additional_expense_revision
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION procurement.check_additional_expense_trigger();
CREATE CONSTRAINT TRIGGER complete_additional_expense_control AFTER INSERT OR UPDATE ON accounting.source_control
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION procurement.check_additional_expense_trigger();

CREATE OR REPLACE FUNCTION procurement.guard_additional_expense_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE owner_id integer; latest integer; link jsonb; saved jsonb; expected jsonb;
        pos integer := 0; source_document jsonb; posting procurement.receipt_posting%ROWTYPE;
        seen jsonb := '[]'::jsonb;
BEGIN
  SELECT organization_id INTO owner_id FROM procurement.additional_expense_document WHERE id = NEW.expense_id;
  PERFORM 1 FROM accounting.organization WHERE id = owner_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Additional expense organization is missing'; END IF;
  SELECT coalesce(max(version), 0) INTO latest FROM procurement.additional_expense_revision WHERE expense_id = NEW.expense_id;
  IF NEW.version <> latest + 1 THEN RAISE EXCEPTION 'Additional expense must append the next version'; END IF;
  IF jsonb_typeof(NEW.document::jsonb->'receipt_lines') IS DISTINCT FROM 'array'
    OR jsonb_typeof(NEW.receipt_sources::jsonb) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Additional expense receipt links must be arrays';
  END IF;
  IF jsonb_array_length(NEW.document::jsonb->'receipt_lines') = 0
    OR jsonb_array_length(NEW.document::jsonb->'receipt_lines') <> jsonb_array_length(NEW.receipt_sources::jsonb) THEN
    RAISE EXCEPTION 'Additional expense receipt snapshots are incomplete';
  END IF;
  FOR link IN SELECT value FROM jsonb_array_elements(NEW.document::jsonb->'receipt_lines') LOOP
    IF link IS DISTINCT FROM jsonb_build_object('receipt_id', link->'receipt_id',
         'version', link->'version', 'line_number', link->'line_number')
      OR jsonb_typeof(link->'receipt_id') IS DISTINCT FROM 'number'
      OR jsonb_typeof(link->'version') IS DISTINCT FROM 'number'
      OR jsonb_typeof(link->'line_number') IS DISTINCT FROM 'number'
      OR link->>'receipt_id' !~ '^[1-9][0-9]*$' OR link->>'version' !~ '^[1-9][0-9]*$'
      OR link->>'line_number' !~ '^[1-9][0-9]*$' THEN
      RAISE EXCEPTION 'Additional expense receipt link must contain exact positive identifiers';
    END IF;
    IF seen @> jsonb_build_array(link) THEN RAISE EXCEPTION 'Additional expense receipt link is duplicated'; END IF;
    seen := seen || jsonb_build_array(link);
    SELECT p.* INTO posting FROM procurement.receipt_posting p JOIN procurement.receipt_document d ON d.id = p.receipt_id
      WHERE d.organization_id = owner_id AND p.receipt_id::text = link->>'receipt_id'
        AND p.version::text = link->>'version';
    IF NOT FOUND THEN RAISE EXCEPTION 'Additional expense receipt is not posted in this organization/version'; END IF;
    SELECT document::jsonb INTO source_document FROM procurement.receipt_revision
      WHERE receipt_id = posting.receipt_id AND version = posting.version;
    IF source_document IS NULL OR (link->>'line_number')::integer < 1
      OR (link->>'line_number')::integer > jsonb_array_length(source_document->'items') THEN
      RAISE EXCEPTION 'Additional expense receipt line is missing';
    END IF;
    expected := link || jsonb_build_object('entry_id', posting.entry_id, 'posting_digest', posting.digest,
      'document_date', source_document->'document_date', 'operation_date', source_document->'operation_date',
      'currency', source_document->'currency', 'warehouse', source_document->'warehouse',
      'item', source_document->'items'->((link->>'line_number')::integer - 1));
    saved := NEW.receipt_sources::jsonb->pos;
    IF saved IS DISTINCT FROM expected THEN RAISE EXCEPTION 'Additional expense receipt snapshot differs from source'; END IF;
    pos := pos + 1;
  END LOOP;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_additional_expense_revision BEFORE INSERT ON procurement.additional_expense_revision
FOR EACH ROW EXECUTE FUNCTION procurement.guard_additional_expense_revision();

CREATE OR REPLACE FUNCTION procurement.guard_additional_expense_control_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM procurement.additional_expense_document) THEN
    RAISE EXCEPTION 'Additional expense completeness records cannot be truncated';
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER preserve_additional_expense_completeness BEFORE TRUNCATE ON accounting.source_control
FOR EACH STATEMENT EXECUTE FUNCTION procurement.guard_additional_expense_control_truncate();
CREATE TRIGGER immutable_additional_expense_revision
BEFORE UPDATE OR DELETE OR TRUNCATE ON procurement.additional_expense_revision
FOR EACH STATEMENT EXECUTE FUNCTION procurement.reject_additional_expense_mutation();


ALTER TABLE production.order_ownership ADD CONSTRAINT fk_production_owner_organization
FOREIGN KEY (organization_id) REFERENCES accounting.organization(id);

CREATE OR REPLACE FUNCTION production.reject_order_ownership_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Production order ownership is immutable';
END $$;
CREATE TRIGGER immutable_production_order_ownership BEFORE UPDATE OR DELETE OR TRUNCATE
ON production.order_ownership FOR EACH STATEMENT EXECUTE FUNCTION production.reject_order_ownership_mutation();

CREATE OR REPLACE FUNCTION production.guard_order_ownership_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE o production.production_order%ROWTYPE;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Production ownership organization is missing'; END IF;
  SELECT * INTO o FROM production.production_order WHERE id=NEW.order_id FOR UPDATE;
  IF NOT FOUND OR jsonb_typeof(NEW.snapshot::jsonb) IS DISTINCT FROM 'object'
    OR (NEW.snapshot->>'order_id')::integer IS DISTINCT FROM o.id
    OR NEW.snapshot->>'number' IS DISTINCT FROM o.number
    OR NEW.snapshot->>'product' IS DISTINCT FROM o.product
    OR (NEW.snapshot->>'quantity')::integer IS DISTINCT FROM o.qty
    OR NEW.snapshot->>'stage' IS DISTINCT FROM o.stage
    OR (NEW.snapshot->>'created_at')::timestamp IS DISTINCT FROM o.created_at
    OR NEW.digest !~ '^[a-f0-9]{64}$'
    OR length(btrim(NEW.evidence))<10 OR length(btrim(NEW.actor))=0 THEN
    RAISE EXCEPTION 'Production ownership snapshot does not match the order';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_production_order_ownership BEFORE INSERT ON production.order_ownership
FOR EACH ROW EXECUTE FUNCTION production.guard_order_ownership_insert();


CREATE TRIGGER immutable_production_order_creation BEFORE UPDATE OR DELETE OR TRUNCATE
ON production.order_creation_receipt FOR EACH STATEMENT
EXECUTE FUNCTION production.reject_order_ownership_mutation();

CREATE OR REPLACE FUNCTION production.guard_order_creation_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE o production.production_order%ROWTYPE;
DECLARE own production.order_ownership%ROWTYPE;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Production creation organization is missing'; END IF;
  SELECT * INTO o FROM production.production_order WHERE id=NEW.order_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Production creation order is missing'; END IF;
  SELECT * INTO own FROM production.order_ownership WHERE order_id=NEW.order_id;
  IF NOT FOUND OR own.organization_id IS DISTINCT FROM NEW.organization_id
    OR own.actor IS DISTINCT FROM NEW.actor
    OR jsonb_typeof(NEW.command::jsonb) IS DISTINCT FROM 'object'
    OR NEW.command::jsonb IS DISTINCT FROM jsonb_build_object(
      'request_id', NEW.request_id, 'product', o.product, 'quantity', o.qty, 'evidence', own.evidence)
    OR NEW.result::jsonb IS DISTINCT FROM (to_jsonb(o) - ARRAY['created_at','completed_at'])
    OR o.stage IS DISTINCT FROM 'queue' OR o.made_qty<>0 OR o.qty<=0
    OR o.completed_at IS NOT NULL OR o.progress<>0
    OR NEW.request_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    OR NEW.digest !~ '^[a-f0-9]{64}$' THEN
    RAISE EXCEPTION 'Production creation receipt does not match its source';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_production_order_creation BEFORE INSERT ON production.order_creation_receipt
FOR EACH ROW EXECUTE FUNCTION production.guard_order_creation_insert();


-- Prepared source snapshots are append-only, including writes outside the ORM.
CREATE TRIGGER immutable_production_output_document BEFORE UPDATE OR DELETE OR TRUNCATE
ON production.output_document FOR EACH STATEMENT
EXECUTE FUNCTION production.reject_order_ownership_mutation();

CREATE OR REPLACE FUNCTION production.guard_output_document_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE o record;
DECLARE s record;
DECLARE p record;
DECLARE c jsonb := NEW.command::jsonb;
DECLARE snap jsonb := NEW.snapshot::jsonb;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Output organization is missing'; END IF;
  SELECT * INTO o FROM production.production_order WHERE id=NEW.order_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Output order is missing'; END IF;
  IF NOT EXISTS (SELECT 1 FROM production.order_ownership
      WHERE order_id=NEW.order_id AND organization_id=NEW.organization_id)
    OR o.completed_at IS NOT NULL OR o.stage='done' THEN
    RAISE EXCEPTION 'Output order is not available in this organization';
  END IF;
  SELECT * INTO s FROM public.sku WHERE code=c->>'sku_code' FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Output SKU is missing'; END IF;
  SELECT * INTO p FROM wms.location WHERE id=(c->>'location_id')::integer FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Output receiving place is missing'; END IF;
  IF NOT s.is_active OR NULLIF(btrim(s.unit),'') IS NULL OR NOT p.is_active
    OR p.warehouse IS DISTINCT FROM c->>'warehouse'
    OR c->'order_id' IS DISTINCT FROM to_jsonb(NEW.order_id)
    OR c->>'request_id' IS DISTINCT FROM NEW.request_id
    OR jsonb_typeof(c) IS DISTINCT FROM 'object'
    OR jsonb_typeof(c->'quantity') IS DISTINCT FROM 'string'
    OR coalesce(c->>'quantity','') !~ '^[0-9]{1,12}(\.[0-9]{1,2})?$'
    OR (c->>'quantity')::numeric<=0
    OR NULLIF(btrim(NEW.actor),'') IS NULL
    OR NEW.digest !~ '^[a-f0-9]{64}$'
    OR snap IS DISTINCT FROM jsonb_build_object(
      'organization_id', NEW.organization_id, 'principal', NEW.actor,
      'command', c, 'posted', false, 'confirmation_available', false,
      'order_snapshot', jsonb_build_object('order_id', o.id, 'number', o.number,
        'product', o.product, 'quantity', o.qty, 'stage', o.stage,
        'created_at', snap->'order_snapshot'->'created_at'),
      'sku_snapshot', jsonb_build_object('id',s.id,'code',s.code,'title',s.title,'unit',s.unit),
      'receiving_place', jsonb_build_object('location_id',p.id,'warehouse',p.warehouse,
        'code',p.code,'zone',p.zone,'title',p.title))
    OR (snap->'order_snapshot'->>'created_at')::timestamptz IS DISTINCT FROM o.created_at THEN
    RAISE EXCEPTION 'Output document does not match its source';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_production_output_document BEFORE INSERT ON production.output_document
FOR EACH ROW EXECUTE FUNCTION production.guard_output_document_insert();

CREATE TRIGGER immutable_production_output_confirmation BEFORE UPDATE OR DELETE OR TRUNCATE
ON production.output_confirmation FOR EACH STATEMENT
EXECUTE FUNCTION production.reject_order_ownership_mutation();

CREATE OR REPLACE FUNCTION production.guard_output_confirmation_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE d production.output_document%ROWTYPE;
DECLARE o production.production_order%ROWTYPE;
DECLARE total numeric;
DECLARE e record;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  SELECT * INTO o FROM production.production_order WHERE id=NEW.order_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Output order is missing'; END IF;
  SELECT * INTO d FROM production.output_document WHERE id=NEW.document_id;
  IF NOT FOUND OR d.organization_id IS DISTINCT FROM NEW.organization_id
    OR d.order_id IS DISTINCT FROM NEW.order_id OR d.digest IS DISTINCT FROM NEW.digest
    OR NEW.quantity IS DISTINCT FROM (d.command->>'quantity')::numeric
    OR NEW.quantity<=0 OR NEW.quantity::text IN ('NaN','Infinity','-Infinity')
    OR NULLIF(btrim(NEW.actor),'') IS NULL OR o.completed_at IS NOT NULL OR o.stage='done' THEN
    RAISE EXCEPTION 'Output confirmation does not match its document';
  END IF;
  SELECT coalesce(sum(quantity),0) INTO total FROM production.output_confirmation WHERE order_id=NEW.order_id;
  IF total+NEW.quantity>o.qty THEN RAISE EXCEPTION 'Confirmed output exceeds order quantity'; END IF;
  IF NOT EXISTS (SELECT 1 FROM accounting.source_control s
      WHERE s.organization_id=NEW.organization_id AND s.source='production:output:'||d.id
        AND s.version=1 AND s.month=substring(d.command->>'operation_date',1,7) AND s.entry_id IS NULL) THEN
    RAISE EXCEPTION 'Output confirmation requires its pending accounting source';
  END IF;
  SELECT * INTO e FROM public.outbox_event WHERE id=NEW.event_id;
  IF NOT FOUND OR e.event_type IS DISTINCT FROM 'production.output.confirmed' OR e.version<>1
    OR e.payload::jsonb IS DISTINCT FROM jsonb_build_object(
      'output_document_id',d.id,'output_digest',d.digest,'organization_id',d.organization_id,
      'sku_code',d.command->>'sku_code','qty',d.command->>'quantity','warehouse',d.command->>'warehouse',
      'location_id',d.command::jsonb->'location_id','lot',d.command->>'lot',
      'operation_date',d.command->>'operation_date','entity_ref','production_output:'||d.id) THEN
    RAISE EXCEPTION 'Output confirmation event differs from its document';
  END IF;
  IF EXISTS (SELECT 1 FROM production.output_confirmation c
    JOIN production.output_document previous ON previous.id=c.document_id
    WHERE c.order_id=NEW.order_id AND
      (previous.snapshot::jsonb->'sku_snapshot'->'code' IS DISTINCT FROM d.snapshot::jsonb->'sku_snapshot'->'code'
       OR previous.snapshot::jsonb->'sku_snapshot'->'unit' IS DISTINCT FROM d.snapshot::jsonb->'sku_snapshot'->'unit')) THEN
    RAISE EXCEPTION 'Partial output SKU or unit differs';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_production_output_confirmation BEFORE INSERT ON production.output_confirmation
FOR EACH ROW EXECUTE FUNCTION production.guard_output_confirmation_insert();

-- A confirmed physical source cannot be moved out of its accounting period.
CREATE OR REPLACE FUNCTION production.guard_output_source_control() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.source LIKE 'production:output:%' AND NOT EXISTS (
    SELECT 1 FROM production.output_document d
    WHERE NEW.source='production:output:'||d.id AND NEW.organization_id=d.organization_id
      AND NEW.version=1 AND NEW.month=substring(d.command->>'operation_date',1,7)) THEN
    RAISE EXCEPTION 'Production output accounting source differs from its document';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER valid_production_output_source BEFORE INSERT OR UPDATE ON accounting.source_control
FOR EACH ROW EXECUTE FUNCTION production.guard_output_source_control();

CREATE OR REPLACE FUNCTION production.guard_output_source_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM production.output_confirmation) THEN
    RAISE EXCEPTION 'Confirmed production output accounting sources cannot be truncated';
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER preserve_production_output_sources BEFORE TRUNCATE ON accounting.source_control
FOR EACH STATEMENT EXECUTE FUNCTION production.guard_output_source_truncate();


CREATE OR REPLACE FUNCTION logistics.reject_execution_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Shipping execution is immutable';
END;
$$;
CREATE TRIGGER immutable_shipping_execution
BEFORE UPDATE OR DELETE ON logistics.shipping_execution
FOR EACH ROW EXECUTE FUNCTION logistics.reject_execution_mutation();
CREATE TRIGGER no_truncate_shipping_execution
BEFORE TRUNCATE ON logistics.shipping_execution
FOR EACH STATEMENT EXECUTE FUNCTION logistics.reject_execution_mutation();


-- Bootstrap completeness from procurement sources already present before this registry.
-- Organization ownership was explicit on these sources; no default company is assigned.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM procurement.receipt_document d
    LEFT JOIN procurement.receipt_revision r ON r.receipt_id = d.id AND r.version = d.current_version
    LEFT JOIN procurement.receipt_posting p ON p.receipt_id = d.id
    LEFT JOIN accounting.entry e ON e.id = p.entry_id
    WHERE r.id IS NULL OR (p.receipt_id IS NOT NULL AND (
      e.id IS NULL OR e.organization_id <> d.organization_id
      OR e.source <> 'procurement:receipt:' || d.id::text
      OR e.source_version <> d.current_version OR p.version <> d.current_version
      OR e.operation <> 'inventory_purchase' OR e.digest <> p.digest
    ))
  ) THEN
    RAISE EXCEPTION 'Existing receipt history must be reconciled before completeness bootstrap';
  END IF;
END $$;

INSERT INTO accounting.source_control (organization_id, source, version, month, entry_id)
SELECT d.organization_id, 'procurement:receipt:' || d.id::text, d.current_version,
       CASE WHEN p.entry_id IS NOT NULL THEN to_char(e.posting_date, 'YYYY-MM')
            ELSE substring(r.document->>'operation_date', 1, 7) END,
       p.entry_id
FROM procurement.receipt_document d
JOIN procurement.receipt_revision r ON r.receipt_id = d.id AND r.version = d.current_version
LEFT JOIN procurement.receipt_posting p ON p.receipt_id = d.id
LEFT JOIN accounting.entry e ON e.id = p.entry_id AND e.organization_id = d.organization_id
WHERE NOT EXISTS (SELECT 1 FROM accounting.source_control c
  WHERE c.organization_id = d.organization_id AND c.source = 'procurement:receipt:' || d.id::text);

-- A previously closed book with pending sources must no longer appear final.
UPDATE accounting.period p SET generation = p.generation + 1, evidence = '{}'::json
WHERE EXISTS (SELECT 1 FROM accounting.source_control c
  WHERE c.organization_id = p.organization_id AND c.entry_id IS NULL AND c.month <= p.month);


-- CRM-ACC-001 migration body: install with the accounting schema, never on finance tables.
CREATE OR REPLACE FUNCTION accounting.reject_history_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Accounting history is immutable: %', TG_TABLE_NAME;
END $$;

CREATE TRIGGER immutable_shipment_preparation_draft BEFORE UPDATE OR DELETE ON accounting.shipment_preparation_draft
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_shipment_preparation_draft BEFORE TRUNCATE ON accounting.shipment_preparation_draft
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE TRIGGER immutable_entry BEFORE UPDATE OR DELETE ON accounting.entry
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER immutable_shipment_accounting_receipt BEFORE UPDATE OR DELETE ON accounting.shipment_accounting_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER immutable_line BEFORE UPDATE OR DELETE ON accounting.line
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER immutable_account BEFORE UPDATE OR DELETE ON accounting.account
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER immutable_policy BEFORE UPDATE OR DELETE ON accounting.policy
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER immutable_seller_profile BEFORE UPDATE OR DELETE ON accounting.seller_profile
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_seller_profile BEFORE TRUNCATE ON accounting.seller_profile
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER immutable_audit BEFORE UPDATE OR DELETE ON accounting.audit
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER immutable_source_binding BEFORE UPDATE OR DELETE ON accounting.source_binding
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();

-- A subtransaction xmin is not the root transaction identity. Record a SQL-only
-- birth proof so entry + lines may use real savepoints without permitting late appends.
CREATE TABLE accounting.entry_transaction (
  entry_id integer PRIMARY KEY REFERENCES accounting.entry(id),
  root_transaction bigint NOT NULL
);
CREATE OR REPLACE FUNCTION accounting.guard_entry_transaction() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF pg_trigger_depth() <> 2 OR NEW.root_transaction <> txid_current()
     OR NOT EXISTS (SELECT 1 FROM accounting.entry WHERE id=NEW.entry_id) THEN
    RAISE EXCEPTION 'Entry transaction proof must be generated by its insert trigger';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER generated_entry_transaction BEFORE INSERT ON accounting.entry_transaction
FOR EACH ROW EXECUTE FUNCTION accounting.guard_entry_transaction();
CREATE TRIGGER immutable_entry_transaction BEFORE UPDATE OR DELETE ON accounting.entry_transaction
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_entry_transaction BEFORE TRUNCATE ON accounting.entry_transaction
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE OR REPLACE FUNCTION accounting.record_entry_transaction() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO accounting.entry_transaction(entry_id,root_transaction) VALUES(NEW.id,txid_current());
  RETURN NULL;
END $$;
CREATE TRIGGER record_entry_transaction AFTER INSERT ON accounting.entry
FOR EACH ROW EXECUTE FUNCTION accounting.record_entry_transaction();
CREATE TRIGGER no_truncate_entry BEFORE TRUNCATE ON accounting.entry
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_line BEFORE TRUNCATE ON accounting.line
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_account BEFORE TRUNCATE ON accounting.account
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_policy BEFORE TRUNCATE ON accounting.policy
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_audit BEFORE TRUNCATE ON accounting.audit
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_source_binding BEFORE TRUNCATE ON accounting.source_binding
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE OR REPLACE FUNCTION accounting.guard_entry_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE policy_org integer;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
  SELECT organization_id INTO policy_org FROM accounting.policy WHERE id = NEW.policy_id;
  IF policy_org IS DISTINCT FROM NEW.organization_id THEN
    RAISE EXCEPTION 'Policy belongs to another organization';
  END IF;
  IF EXISTS (SELECT 1 FROM accounting.period WHERE organization_id = NEW.organization_id
             AND month >= to_char(NEW.posting_date, 'YYYY-MM') AND closed) THEN
    RAISE EXCEPTION 'Closed accounting period';
  END IF;
  IF NEW.correction_of IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM accounting.entry WHERE id = NEW.correction_of
      AND organization_id = NEW.organization_id AND posting_date <= NEW.posting_date
  ) THEN RAISE EXCEPTION 'Invalid correction reference'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_entry_insert BEFORE INSERT ON accounting.entry
FOR EACH ROW EXECUTE FUNCTION accounting.guard_entry_insert();

CREATE OR REPLACE FUNCTION accounting.guard_line_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry; a accounting.account; entry_xid bigint;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id = NEW.entry_id;
  -- The entry and its lines must be created in the same transaction.
  SELECT root_transaction INTO entry_xid FROM accounting.entry_transaction WHERE entry_id = NEW.entry_id;
  IF entry_xid IS DISTINCT FROM txid_current() THEN
    RAISE EXCEPTION 'Cannot append lines to a committed entry';
  END IF;
  SELECT * INTO a FROM accounting.account WHERE id = NEW.account_id;
  IF a.organization_id IS DISTINCT FROM e.organization_id OR a.valid_from > e.posting_date THEN
    RAISE EXCEPTION 'Account organization or effective date mismatch';
  END IF;
  IF NEW.category IS DISTINCT FROM a.category OR NEW.cash IS DISTINCT FROM a.cash
     OR NEW.account_code IS DISTINCT FROM a.code OR NEW.account_title IS DISTINCT FROM a.title THEN
    RAISE EXCEPTION 'Account snapshot mismatch';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_line_insert BEFORE INSERT ON accounting.line
FOR EACH ROW EXECUTE FUNCTION accounting.guard_line_insert();

CREATE OR REPLACE FUNCTION accounting.check_entry_balance() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE delta numeric; line_count integer;
BEGIN
  SELECT count(*), coalesce(sum(CASE WHEN category = 'off_balance' THEN 0
    WHEN side = 'debit' THEN amount ELSE -amount END), 0)
  INTO line_count, delta FROM accounting.line WHERE entry_id = NEW.id;
  IF line_count = 0 OR delta <> 0 THEN
    RAISE EXCEPTION 'Empty or unbalanced accounting entry %', NEW.id;
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER balanced_entry AFTER INSERT ON accounting.entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_entry_balance();

-- Completeness registry may advance only with a new source version or its matching entry.
CREATE OR REPLACE FUNCTION accounting.guard_source_control() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Source completeness records cannot be deleted';
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF NEW.version <> 1 OR NEW.entry_id IS NOT NULL THEN
      RAISE EXCEPTION 'Source completeness must start pending at version 1';
    END IF;
  ELSE
    -- A physical act is immutable; corrections must be separate operations.
    IF OLD.source LIKE 'wms:physical-shipment:%' AND
       (NEW.version IS DISTINCT FROM OLD.version OR NEW.month IS DISTINCT FROM OLD.month) THEN
      RAISE EXCEPTION 'Physical shipment source identity is immutable';
    END IF;
    IF NEW.organization_id IS DISTINCT FROM OLD.organization_id OR NEW.source IS DISTINCT FROM OLD.source
       OR OLD.entry_id IS NOT NULL THEN
      RAISE EXCEPTION 'Resolved source completeness is immutable';
    END IF;
    IF NEW.entry_id IS NULL THEN
      IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'Source completeness requires the next version';
      END IF;
    ELSIF NEW.version <> OLD.version OR NEW.month <> OLD.month THEN
      RAISE EXCEPTION 'Resolving a source cannot change its version or month';
    END IF;
  END IF;
  IF NEW.entry_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM accounting.entry e WHERE e.id = NEW.entry_id
      AND e.organization_id = NEW.organization_id AND e.source = NEW.source
      AND e.source_version = NEW.version AND to_char(e.posting_date, 'YYYY-MM') = NEW.month
  ) THEN
    RAISE EXCEPTION 'Source completeness requires its matching posted entry';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_source_control BEFORE INSERT OR UPDATE OR DELETE ON accounting.source_control
FOR EACH ROW EXECUTE FUNCTION accounting.guard_source_control();


-- Source document history, independent of the accounting ledger's tables.
CREATE OR REPLACE FUNCTION procurement.reject_receipt_revision_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Source revisions are immutable';
END $$;
CREATE TRIGGER immutable_receipt_revision BEFORE UPDATE OR DELETE ON procurement.receipt_revision
FOR EACH ROW EXECUTE FUNCTION procurement.reject_receipt_revision_mutation();
CREATE TRIGGER immutable_receipt_document_delete BEFORE DELETE ON procurement.receipt_document
FOR EACH ROW EXECUTE FUNCTION procurement.reject_receipt_revision_mutation();

CREATE OR REPLACE FUNCTION procurement.guard_receipt_document() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.current_version <> 1 OR NEW.status <> 'draft' THEN
      RAISE EXCEPTION 'New receipt must start as draft version 1';
    END IF;
  ELSE
    IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.source_key IS DISTINCT FROM OLD.source_key
       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR OLD.status <> 'draft' OR NEW.status <> 'draft'
       OR EXISTS (SELECT 1 FROM procurement.receipt_posting WHERE receipt_id = OLD.id)
       OR NEW.current_version <> OLD.current_version + 1 THEN
      RAISE EXCEPTION 'Receipt identity is immutable; only append the next draft version';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_receipt_document BEFORE INSERT OR UPDATE ON procurement.receipt_document
FOR EACH ROW EXECUTE FUNCTION procurement.guard_receipt_document();

CREATE OR REPLACE FUNCTION procurement.check_receipt_revision_chain() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE revision_count integer; last_version integer;
BEGIN
  SELECT count(*), max(version) INTO revision_count, last_version
    FROM procurement.receipt_revision WHERE receipt_id = NEW.id;
  IF revision_count <> NEW.current_version OR last_version IS DISTINCT FROM NEW.current_version THEN
    RAISE EXCEPTION 'Receipt revision chain is incomplete';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_receipt_revision AFTER INSERT OR UPDATE ON procurement.receipt_document
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION procurement.check_receipt_revision_chain();

CREATE OR REPLACE FUNCTION procurement.guard_receipt_revision_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE expected integer; owner_id integer;
BEGIN
  SELECT current_version, organization_id INTO expected, owner_id FROM procurement.receipt_document WHERE id = NEW.receipt_id FOR UPDATE;
  IF NEW.version IS DISTINCT FROM expected OR NEW.version < 1 THEN
    RAISE EXCEPTION 'Receipt revision does not match its document';
  END IF;
  IF EXISTS (SELECT 1 FROM json_array_elements(NEW.document->'items') item
    WHERE item->>'order_id' IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM procurement.purchase_ownership o WHERE o.organization_id = owner_id
        AND o.kind = 'order' AND o.source_id::text = item->>'order_id'
    )) THEN
    RAISE EXCEPTION 'Receipt orders must belong to its organization';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_receipt_revision_insert BEFORE INSERT ON procurement.receipt_revision
FOR EACH ROW EXECUTE FUNCTION procurement.guard_receipt_revision_insert();

CREATE TRIGGER immutable_receipt_posting BEFORE UPDATE OR DELETE ON procurement.receipt_posting
FOR EACH ROW EXECUTE FUNCTION procurement.reject_receipt_revision_mutation();

CREATE OR REPLACE FUNCTION procurement.guard_receipt_posting_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE expected integer;
BEGIN
  SELECT current_version INTO expected FROM procurement.receipt_document WHERE id = NEW.receipt_id FOR UPDATE;
  IF NEW.version IS DISTINCT FROM expected OR NEW.version < 1 THEN
    RAISE EXCEPTION 'Posting must reference the current source revision';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_receipt_posting_insert BEFORE INSERT ON procurement.receipt_posting
FOR EACH ROW EXECUTE FUNCTION procurement.guard_receipt_posting_insert();

-- Atomic creation command: immutable history remains valid after request changes.
CREATE TRIGGER immutable_purchase_request_creation
BEFORE UPDATE OR DELETE ON procurement.purchase_request_creation
FOR EACH ROW EXECUTE FUNCTION procurement.reject_receipt_revision_mutation();
CREATE TRIGGER immutable_purchase_request_creation_truncate
BEFORE TRUNCATE ON procurement.purchase_request_creation
FOR EACH STATEMENT EXECUTE FUNCTION procurement.reject_receipt_revision_mutation();

CREATE OR REPLACE FUNCTION procurement.guard_purchase_request_creation() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE c jsonb; d jsonb; o procurement.purchase_ownership%ROWTYPE;
        r procurement.purchase_request%ROWTYPE; canonical_command text; expected_snapshot jsonb;
        trim_chars CONSTANT text := U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000';
BEGIN
  c := NEW.command::jsonb;
  d := c->'document';
  IF jsonb_typeof(c) IS DISTINCT FROM 'object'
    OR jsonb_typeof(d) IS DISTINCT FROM 'object'
    OR c IS DISTINCT FROM jsonb_build_object('request_key', NEW.request_key,
         'document', d, 'ownership_evidence', c->'ownership_evidence')
    OR d IS DISTINCT FROM jsonb_build_object('supplier', d->'supplier', 'item', d->'item',
         'qty', d->'qty', 'amount', d->'amount', 'due_date', d->'due_date')
    OR NEW.request_key !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    OR NEW.command_hash !~ '^[0-9a-f]{64}$'
    OR jsonb_typeof(c->'ownership_evidence') IS DISTINCT FROM 'string'
    OR c->>'ownership_evidence' IS DISTINCT FROM btrim(c->>'ownership_evidence', trim_chars)
    OR length(btrim(c->>'ownership_evidence')) NOT BETWEEN 1 AND 1000
    OR jsonb_typeof(d->'supplier') IS DISTINCT FROM 'string'
    OR d->>'supplier' IS DISTINCT FROM btrim(d->>'supplier', trim_chars)
    OR length(btrim(d->>'supplier')) NOT BETWEEN 1 AND 255
    OR jsonb_typeof(d->'item') IS DISTINCT FROM 'string'
    OR d->>'item' IS DISTINCT FROM btrim(d->>'item', trim_chars)
    OR length(btrim(d->>'item')) NOT BETWEEN 1 AND 255
    OR jsonb_typeof(d->'qty') IS DISTINCT FROM 'number'
    OR (NEW.command->'document'->>'qty') !~ '^[1-9][0-9]*$'
    OR jsonb_typeof(d->'amount') IS DISTINCT FROM 'string'
    OR (d->>'amount') !~ '^(0|[1-9][0-9]{0,11})\.[0-9]{2}$'
    OR jsonb_typeof(d->'due_date') NOT IN ('string','null')
    OR (d->>'due_date' IS NOT NULL AND (d->>'due_date') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$') THEN
    RAISE EXCEPTION 'Invalid purchase request creation command';
  END IF;
  IF (d->>'qty')::numeric > 2147483647
    OR (d->>'due_date' IS NOT NULL AND (d->>'due_date')::date::text IS DISTINCT FROM d->>'due_date') THEN
    RAISE EXCEPTION 'Invalid purchase request creation quantities or date';
  END IF;
  canonical_command := '{"document":{"amount":' || (d->'amount')::text
    || ',"due_date":' || (d->'due_date')::text || ',"item":' || (d->'item')::text
    || ',"qty":' || (d->'qty')::text || ',"supplier":' || (d->'supplier')::text
    || '},"ownership_evidence":' || (c->'ownership_evidence')::text
    || ',"request_key":' || (c->'request_key')::text || '}';
  IF NEW.command_hash IS DISTINCT FROM encode(sha256(convert_to(canonical_command, 'UTF8')), 'hex') THEN
    RAISE EXCEPTION 'Purchase request creation command hash mismatch';
  END IF;
  SELECT * INTO o FROM procurement.purchase_ownership WHERE id=NEW.ownership_id;
  SELECT * INTO r FROM procurement.purchase_request WHERE id=NEW.request_id;
  expected_snapshot := jsonb_build_object('number', r.number, 'supplier', d->'supplier',
    'supplier_id', NULL, 'item', d->'item', 'quantity', d->>'qty',
    'planned_amount', d->'amount', 'due_date', d->'due_date');
  IF o.id IS NULL OR r.id IS NULL OR o.kind IS DISTINCT FROM 'request'
    OR o.source_id IS DISTINCT FROM NEW.request_id OR o.organization_id IS DISTINCT FROM NEW.organization_id
    OR o.actor IS DISTINCT FROM NEW.actor OR o.evidence IS DISTINCT FROM c->>'ownership_evidence'
    OR o.snapshot::jsonb IS DISTINCT FROM expected_snapshot
    OR NEW.result::jsonb IS DISTINCT FROM jsonb_build_object('organization_id', NEW.organization_id,
        'request_key', NEW.request_key, 'request_id', NEW.request_id, 'ownership_id', NEW.ownership_id,
        'number', r.number, 'stage', 'need')
    OR r.origin IS DISTINCT FROM ''
    OR r.stage IS DISTINCT FROM 'need' OR r.supplier IS DISTINCT FROM d->>'supplier'
    OR r.item IS DISTINCT FROM d->>'item' OR r.qty IS DISTINCT FROM (d->>'qty')::integer
    OR r.amount IS DISTINCT FROM (d->>'amount')::numeric
    OR r.due_date IS DISTINCT FROM d->>'due_date' OR r.supplier_id IS NOT NULL THEN
    RAISE EXCEPTION 'Purchase request creation ownership or initial result mismatch';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_purchase_request_creation BEFORE INSERT ON procurement.purchase_request_creation
FOR EACH ROW EXECUTE FUNCTION procurement.guard_purchase_request_creation();


-- Unallocated proposal: install with the expected-reservation tables.
CREATE OR REPLACE FUNCTION procurement.guard_expected_conversion_request() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP <> 'UPDATE' THEN
    RAISE EXCEPTION 'Expected conversion request history cannot be removed';
  END IF;
  IF (to_jsonb(NEW) - 'completed') IS DISTINCT FROM (to_jsonb(OLD) - 'completed')
     OR OLD.completed OR NOT NEW.completed THEN
    RAISE EXCEPTION 'Only pending to completed conversion request transition is allowed';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_expected_conversion_request
BEFORE UPDATE OR DELETE ON procurement.expected_conversion_request
FOR EACH ROW EXECUTE FUNCTION procurement.guard_expected_conversion_request();
CREATE TRIGGER no_truncate_expected_conversion_request
BEFORE TRUNCATE ON procurement.expected_conversion_request
FOR EACH STATEMENT EXECUTE FUNCTION procurement.guard_expected_conversion_request();

CREATE OR REPLACE FUNCTION procurement.guard_expected_reservation_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM procurement.purchase_ownership
                 WHERE organization_id=NEW.organization_id AND kind='order' AND source_id=NEW.order_id)
     OR NOT EXISTS (SELECT 1 FROM procurement.purchase_order_line
                    WHERE id=NEW.order_line_id AND order_id=NEW.order_id)
     OR NOT EXISTS (SELECT 1 FROM sales.deal_ownership
                    WHERE deal_id=NEW.deal_id AND organization_id=NEW.organization_id)
     OR (NEW.demand_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM procurement.deal_procurement_demand d
          JOIN procurement.purchase_order_line l ON l.id=NEW.order_line_id
          WHERE d.id=NEW.demand_id AND d.organization_id=NEW.organization_id
            AND d.deal_id=NEW.deal_id AND d.sku_code=l.sku_code
        ))
     OR (NEW.document_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM sales.deal_document WHERE id=NEW.document_id AND deal_id=NEW.deal_id
            AND kind='invoice')) THEN
    RAISE EXCEPTION 'Expected reservation source identity is not owned and exact';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_expected_reservation_identity
BEFORE INSERT ON procurement.expected_reservation
FOR EACH ROW EXECUTE FUNCTION procurement.guard_expected_reservation_identity();

CREATE OR REPLACE FUNCTION procurement.guard_expected_reservation_event() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM procurement.expected_reservation
                 WHERE id=NEW.reservation_id AND organization_id=NEW.organization_id) THEN
    RAISE EXCEPTION 'Expected reservation event parent differs from organization';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_expected_reservation_event
BEFORE INSERT ON procurement.expected_reservation_event
FOR EACH ROW EXECUTE FUNCTION procurement.guard_expected_reservation_event();

CREATE OR REPLACE FUNCTION procurement.reject_expected_reservation_history_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Expected reservation history is immutable';
END $$;
CREATE TRIGGER immutable_expected_reservation
BEFORE UPDATE OR DELETE ON procurement.expected_reservation
FOR EACH ROW EXECUTE FUNCTION procurement.reject_expected_reservation_history_mutation();
CREATE TRIGGER immutable_physical_receipt_acceptance
BEFORE UPDATE OR DELETE ON procurement.physical_receipt_acceptance
FOR EACH ROW EXECUTE FUNCTION procurement.reject_expected_reservation_history_mutation();
CREATE TRIGGER no_truncate_physical_receipt_acceptance
BEFORE TRUNCATE ON procurement.physical_receipt_acceptance
FOR EACH STATEMENT EXECUTE FUNCTION procurement.reject_expected_reservation_history_mutation();
CREATE TRIGGER immutable_expected_reservation_event
BEFORE UPDATE OR DELETE ON procurement.expected_reservation_event
FOR EACH ROW EXECUTE FUNCTION procurement.reject_expected_reservation_history_mutation();
CREATE TRIGGER no_truncate_expected_reservation
BEFORE TRUNCATE ON procurement.expected_reservation
FOR EACH STATEMENT EXECUTE FUNCTION procurement.reject_expected_reservation_history_mutation();
CREATE TRIGGER no_truncate_expected_reservation_event
BEFORE TRUNCATE ON procurement.expected_reservation_event
FOR EACH STATEMENT EXECUTE FUNCTION procurement.reject_expected_reservation_history_mutation();


-- Unallocated proposal: install with the deal-demand register.
CREATE OR REPLACE FUNCTION procurement.guard_deal_procurement_demand() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  item_qty numeric;
BEGIN
  IF NOT EXISTS (
       SELECT 1 FROM sales.deal_ownership
       WHERE deal_id = NEW.deal_id AND organization_id = NEW.organization_id
     )
     OR NOT EXISTS (
       SELECT 1 FROM sales.deal_item
       WHERE id = NEW.deal_item_id AND deal_id = NEW.deal_id AND sku_id = NEW.sku_id
     )
     OR NOT EXISTS (
       SELECT 1 FROM public.sku
       WHERE id = NEW.sku_id AND code = NEW.sku_code AND is_active
     )
     OR (NEW.document_id IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM sales.deal_document
       WHERE id = NEW.document_id AND deal_id = NEW.deal_id AND kind = 'invoice'
     )) THEN
    RAISE EXCEPTION 'Deal procurement demand source identity is not exact and owned';
  END IF;

  SELECT qty INTO item_qty
  FROM sales.deal_item
  WHERE id = NEW.deal_item_id AND deal_id = NEW.deal_id
  FOR UPDATE;
  IF item_qty IS NULL OR NEW.qty + COALESCE((
       SELECT sum(qty) FROM procurement.deal_procurement_demand
       WHERE organization_id = NEW.organization_id AND deal_item_id = NEW.deal_item_id
     ), 0) > item_qty THEN
    RAISE EXCEPTION 'Deal procurement demand exceeds the CRM item quantity';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_deal_procurement_demand
BEFORE INSERT ON procurement.deal_procurement_demand
FOR EACH ROW EXECUTE FUNCTION procurement.guard_deal_procurement_demand();

CREATE OR REPLACE FUNCTION procurement.guard_deal_procurement_allocation() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  demand_qty numeric;
  demand_sku text;
  order_status text;
  line_qty numeric;
  line_sku text;
BEGIN
  SELECT qty, sku_code INTO demand_qty, demand_sku
  FROM procurement.deal_procurement_demand
  WHERE id = NEW.demand_id AND organization_id = NEW.organization_id
  FOR UPDATE;
  SELECT po.status, pol.qty, pol.sku_code INTO STRICT order_status, line_qty, line_sku
  FROM procurement.purchase_order_line pol
  JOIN procurement.purchase_order po ON po.id = pol.order_id
  WHERE pol.id = NEW.order_line_id AND pol.order_id = NEW.order_id;
  IF NOT EXISTS (
       SELECT 1 FROM procurement.purchase_ownership
       WHERE organization_id = NEW.organization_id AND kind = 'order' AND source_id = NEW.order_id
     )
     OR demand_qty IS NULL
     OR line_sku IS NULL
     OR line_sku <> demand_sku
     OR order_status NOT IN ('ordered', 'shipped', 'customs') THEN
    RAISE EXCEPTION 'Deal demand allocation source identity is not exact and open';
  END IF;
  IF NEW.qty + GREATEST(COALESCE((
       SELECT sum(qty) FROM procurement.deal_procurement_allocation
       WHERE organization_id = NEW.organization_id AND demand_id = NEW.demand_id
     ), 0) - COALESCE((
       SELECT sum(e.qty)
       FROM procurement.expected_reservation r
       JOIN procurement.expected_reservation_event e ON e.reservation_id = r.id
       WHERE r.organization_id = NEW.organization_id AND r.demand_id = NEW.demand_id
         AND e.organization_id = NEW.organization_id AND e.kind = 'release'
     ), 0), 0) > demand_qty THEN
    RAISE EXCEPTION 'Demand allocation exceeds the client demand';
  END IF;
  IF NEW.qty + COALESCE((
       SELECT sum(r.qty - COALESCE((
         SELECT sum(e.qty) FROM procurement.expected_reservation_event e
         WHERE e.reservation_id = r.id AND e.organization_id = NEW.organization_id
           AND e.kind = 'release'
       ), 0))
       FROM procurement.expected_reservation r
       WHERE r.organization_id = NEW.organization_id AND r.order_line_id = NEW.order_line_id
     ), 0) + COALESCE((
       SELECT sum(a.qty) FROM procurement.deal_procurement_allocation a
       WHERE a.organization_id = NEW.organization_id AND a.order_line_id = NEW.order_line_id
         AND NOT EXISTS (
           SELECT 1 FROM procurement.expected_reservation r
           WHERE r.organization_id = NEW.organization_id AND r.demand_id = a.demand_id
             AND r.order_line_id = a.order_line_id
         )
     ), 0) > line_qty THEN
    RAISE EXCEPTION 'Demand allocation exceeds the supplier order line';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_deal_procurement_allocation
BEFORE INSERT ON procurement.deal_procurement_allocation
FOR EACH ROW EXECUTE FUNCTION procurement.guard_deal_procurement_allocation();

CREATE OR REPLACE FUNCTION procurement.reject_deal_procurement_history_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Deal procurement history is immutable';
END $$;
CREATE TRIGGER immutable_deal_procurement_demand
BEFORE UPDATE OR DELETE ON procurement.deal_procurement_demand
FOR EACH ROW EXECUTE FUNCTION procurement.reject_deal_procurement_history_mutation();
CREATE TRIGGER immutable_deal_procurement_allocation
BEFORE UPDATE OR DELETE ON procurement.deal_procurement_allocation
FOR EACH ROW EXECUTE FUNCTION procurement.reject_deal_procurement_history_mutation();
CREATE TRIGGER no_truncate_deal_procurement_demand
BEFORE TRUNCATE ON procurement.deal_procurement_demand
FOR EACH STATEMENT EXECUTE FUNCTION procurement.reject_deal_procurement_history_mutation();
CREATE TRIGGER no_truncate_deal_procurement_allocation
BEFORE TRUNCATE ON procurement.deal_procurement_allocation
FOR EACH STATEMENT EXECUTE FUNCTION procurement.reject_deal_procurement_history_mutation();

CREATE OR REPLACE FUNCTION procurement.guard_supplier_order_line_allocations() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE allocated numeric;
        expected_reserved numeric;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF EXISTS (SELECT 1 FROM procurement.deal_procurement_allocation
               WHERE order_line_id = OLD.id)
       OR EXISTS (SELECT 1 FROM procurement.expected_reservation
                  WHERE order_line_id = OLD.id) THEN
      RAISE EXCEPTION 'Supplier order line has client allocations or expected reservations';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW.id <> OLD.id OR NEW.order_id <> OLD.order_id OR NEW.sku_code <> OLD.sku_code THEN
    IF EXISTS (SELECT 1 FROM procurement.deal_procurement_allocation WHERE order_line_id = OLD.id)
       OR EXISTS (SELECT 1 FROM procurement.expected_reservation WHERE order_line_id = OLD.id) THEN
      RAISE EXCEPTION 'Supplier order line identity is immutable after client allocation';
    END IF;
  END IF;
  SELECT COALESCE(sum(r.qty - COALESCE((
    SELECT sum(e.qty) FROM procurement.expected_reservation_event e
    WHERE e.reservation_id = r.id AND e.kind = 'release'
  ), 0)), 0)
  INTO expected_reserved
  FROM procurement.expected_reservation r
  WHERE r.order_line_id = OLD.id;
  SELECT COALESCE(sum(a.qty), 0) INTO allocated
  FROM procurement.deal_procurement_allocation a
  WHERE a.order_line_id = OLD.id
    AND NOT EXISTS (
      SELECT 1 FROM procurement.expected_reservation r
      WHERE r.organization_id = a.organization_id AND r.demand_id = a.demand_id
        AND r.order_line_id = a.order_line_id
    );
  IF NEW.qty < allocated OR NEW.qty < expected_reserved THEN
    RAISE EXCEPTION 'Supplier order line quantity is below client allocation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_supplier_order_line_allocations
BEFORE UPDATE OR DELETE ON procurement.purchase_order_line
FOR EACH ROW EXECUTE FUNCTION procurement.guard_supplier_order_line_allocations();


CREATE TRIGGER immutable_purchase_ownership BEFORE UPDATE OR DELETE ON procurement.purchase_ownership
FOR EACH ROW EXECUTE FUNCTION procurement.reject_receipt_revision_mutation();
CREATE TRIGGER immutable_order_request_link BEFORE UPDATE OR DELETE ON procurement.order_request_link
FOR EACH ROW EXECUTE FUNCTION procurement.reject_receipt_revision_mutation();

CREATE OR REPLACE FUNCTION procurement.guard_order_request_link() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM procurement.purchase_ownership o
    WHERE o.id = NEW.order_ownership_id AND o.kind = 'order' AND o.organization_id = NEW.organization_id)
    OR NOT EXISTS (SELECT 1 FROM procurement.purchase_ownership r
    WHERE r.id = NEW.request_ownership_id AND r.kind = 'request' AND r.organization_id = NEW.organization_id) THEN
    RAISE EXCEPTION 'Order and request must belong to the same organization with the correct roles';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_order_request_link BEFORE INSERT ON procurement.order_request_link
FOR EACH ROW EXECUTE FUNCTION procurement.guard_order_request_link();


-- Additive proposal only. Legacy ownership remains NULL pending reconciliation.
ALTER TABLE wms.receipt ADD COLUMN organization_id INTEGER;
ALTER TABLE wms.receipt ADD COLUMN source_event_id INTEGER;
ALTER TABLE wms.receipt ADD CONSTRAINT receipt_source_event_id_key UNIQUE (source_event_id);
ALTER TABLE wms.stock_movement ADD COLUMN organization_id INTEGER;
ALTER TABLE wms.task ADD COLUMN organization_id INTEGER;
ALTER TABLE wms.receipt ADD CONSTRAINT wms_receipt_org_positive CHECK (organization_id > 0);
ALTER TABLE wms.stock_movement ADD CONSTRAINT wms_movement_org_positive CHECK (organization_id > 0);
ALTER TABLE wms.task ADD CONSTRAINT wms_task_org_positive CHECK (organization_id > 0);

-- Unallocated additive proposal: no migration revision and no ownership backfill.
ALTER TABLE wms.inventory_count ADD COLUMN organization_id INTEGER;
ALTER TABLE wms.cycle_count_plan ADD COLUMN organization_id INTEGER;
ALTER TABLE wms.inventory_count ADD CONSTRAINT wms_inventory_count_org_positive CHECK (organization_id > 0);
ALTER TABLE wms.cycle_count_plan ADD CONSTRAINT wms_cycle_count_plan_org_positive CHECK (organization_id > 0);
ALTER TABLE wms.inventory_count ADD COLUMN expected_source VARCHAR(32);
ALTER TABLE wms.inventory_count ADD COLUMN source_evidence VARCHAR(1000);
ALTER TABLE wms.inventory_count ADD COLUMN journal_confirmed_by VARCHAR(200);
ALTER TABLE wms.inventory_count ADD COLUMN journal_confirmed_at TIMESTAMP;
ALTER TABLE wms.cycle_count_plan ADD COLUMN expected_source VARCHAR(32);
ALTER TABLE wms.cycle_count_plan ADD COLUMN source_evidence VARCHAR(1000);
ALTER TABLE wms.cycle_count_plan ADD COLUMN journal_confirmed_by VARCHAR(200);
ALTER TABLE wms.cycle_count_plan ADD COLUMN journal_confirmed_at TIMESTAMP;
ALTER TABLE wms.inventory_count ADD COLUMN snapshot_version VARCHAR(64);
ALTER TABLE wms.inventory_count ADD COLUMN snapshot_cutoff INTEGER;
ALTER TABLE wms.inventory_count ADD COLUMN snapshot_at TIMESTAMP;


CREATE OR REPLACE FUNCTION wms.reject_reservation_change() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
    RAISE EXCEPTION 'Reservation versions are immutable';
END $$;
CREATE TRIGGER reservation_version_immutable BEFORE UPDATE OR DELETE ON wms.reservation_version
FOR EACH ROW EXECUTE FUNCTION wms.reject_reservation_change();
CREATE TRIGGER reservation_version_no_truncate BEFORE TRUNCATE ON wms.reservation_version
FOR EACH STATEMENT EXECUTE FUNCTION wms.reject_reservation_change();
CREATE TRIGGER invoice_reservation_immutable BEFORE UPDATE OR DELETE ON wms.invoice_reservation
FOR EACH ROW EXECUTE FUNCTION wms.reject_reservation_change();
CREATE TRIGGER invoice_reservation_no_truncate BEFORE TRUNCATE ON wms.invoice_reservation
FOR EACH STATEMENT EXECUTE FUNCTION wms.reject_reservation_change();


-- Additive proposal only. Apply after the two new release tables.
-- Preserve existing reservation_guards.sql. No migration ID is registered here.
CREATE TRIGGER invoice_release_immutable BEFORE UPDATE OR DELETE ON wms.invoice_reservation_release
FOR EACH ROW EXECUTE FUNCTION wms.reject_reservation_change();
CREATE TRIGGER invoice_release_no_truncate BEFORE TRUNCATE ON wms.invoice_reservation_release
FOR EACH STATEMENT EXECUTE FUNCTION wms.reject_reservation_change();
CREATE TRIGGER invoice_release_line_immutable BEFORE UPDATE OR DELETE ON wms.invoice_reservation_release_line
FOR EACH ROW EXECUTE FUNCTION wms.reject_reservation_change();
CREATE TRIGGER invoice_release_line_no_truncate BEFORE TRUNCATE ON wms.invoice_reservation_release_line
FOR EACH STATEMENT EXECUTE FUNCTION wms.reject_reservation_change();

CREATE FUNCTION wms.check_invoice_release_package() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE release_key integer; p wms.invoice_reservation_release%ROWTYPE; expected integer;
BEGIN
  IF TG_TABLE_NAME = 'invoice_reservation_release' THEN release_key := NEW.id;
  ELSE release_key := NEW.release_id; END IF;
  SELECT * INTO STRICT p FROM wms.invoice_reservation_release WHERE id=release_key;
  SELECT jsonb_array_length(r.snapshot::jsonb->'allocations') INTO expected
    FROM wms.invoice_reservation r WHERE r.document_id=p.document_id AND r.organization_id=p.organization_id
      AND r.digest=p.snapshot->>'reservation_digest';
  IF expected IS NULL OR expected < 1 OR expected <> (
    SELECT count(*) FROM wms.invoice_reservation_release_line WHERE release_id=p.id
  ) OR expected <> jsonb_array_length(p.snapshot::jsonb->'lines') THEN
    RAISE EXCEPTION 'Incomplete invoice release package';
  END IF;
  IF EXISTS (
    SELECT 1 FROM wms.invoice_reservation_release_line l
    JOIN wms.reservation_version b ON b.id=l.before_id
    JOIN wms.reservation_version a ON a.id=l.after_id
    WHERE l.release_id=p.id AND (
      b.organization_id<>p.organization_id OR a.organization_id<>p.organization_id
      OR b.source<>l.source OR a.source<>l.source OR b.sku_code<>a.sku_code
      OR b.warehouse<>a.warehouse OR b.version<>1 OR a.version<>2
      OR b.qty<=0 OR a.qty<>0 OR l.released_qty<>b.qty OR l.line_no<=0
      OR NOT EXISTS (
        SELECT 1 FROM wms.invoice_reservation original,
          LATERAL jsonb_array_elements(original.snapshot::jsonb->'allocations') allocation
        WHERE original.document_id=p.document_id AND original.organization_id=p.organization_id
          AND allocation->>'source'=l.source
          AND (allocation->>'line_no')::integer=l.line_no
          AND allocation->>'sku_code'=b.sku_code
          AND allocation->>'warehouse'=b.warehouse
          AND (allocation->>'qty')::numeric=b.qty
      )
      OR NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(p.snapshot::jsonb->'lines') e
        WHERE e->>'source'=l.source AND (e->>'line_no')::integer=l.line_no
          AND (e->>'before_id')::integer=b.id AND (e->>'after_id')::integer=a.id
          AND e->>'sku_code'=b.sku_code AND e->>'warehouse'=b.warehouse
          AND (e->>'released_qty')::numeric=b.qty
      )
    )
  ) THEN RAISE EXCEPTION 'Invalid invoice release links'; END IF;
  IF NOT EXISTS (SELECT 1 FROM wms.reservation_event_state WHERE document_id=p.document_id AND state='released')
     OR EXISTS (SELECT 1 FROM wms.task t JOIN wms.reservation_pick k ON k.task_id=t.id
                WHERE k.document_id=p.document_id AND
                  (t.organization_id IS DISTINCT FROM p.organization_id OR t.kind<>'pick'
                   OR t.status<>'canceled' OR t.done_at IS NOT NULL)) THEN
    RAISE EXCEPTION 'Invoice release requires terminal private picks';
  END IF;
  RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER complete_invoice_release AFTER INSERT ON wms.invoice_reservation_release
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION wms.check_invoice_release_package();
CREATE CONSTRAINT TRIGGER complete_invoice_release_line AFTER INSERT ON wms.invoice_reservation_release_line
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION wms.check_invoice_release_package();

-- Compatible bounded namespace protocol: current reserve v1 + no-shipment release v2.
-- Consumption/partial release is intentionally a future versioned protocol.
-- This guards package consistency; review authority still needs restricted DML/functions.
CREATE FUNCTION wms.check_invoice_reservation_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_id integer; allocation jsonb;
BEGIN
  IF NEW.source NOT LIKE 'invoice:%' THEN RETURN NEW; END IF;
  IF NEW.source !~ '^invoice:[0-9]+:[0-9]+:[0-9a-f]{32}$' THEN
    RAISE EXCEPTION 'Invalid invoice reservation namespace';
  END IF;
  owner_id := split_part(NEW.source, ':', 2)::integer;
  SELECT e INTO allocation FROM wms.invoice_reservation r,
    LATERAL jsonb_array_elements(r.snapshot::jsonb->'allocations') e
    WHERE r.document_id=owner_id AND r.organization_id=NEW.organization_id AND e->>'source'=NEW.source;
  IF allocation IS NULL OR allocation->>'sku_code'<>NEW.sku_code
      OR allocation->>'warehouse'<>NEW.warehouse
      OR (allocation->>'line_no')::integer<>split_part(NEW.source, ':', 3)::integer THEN
    RAISE EXCEPTION 'Invoice reservation identity mismatch';
  END IF;
  IF NEW.version=1 AND NEW.qty=(allocation->>'qty')::numeric AND NEW.qty>0 THEN RETURN NEW; END IF;
  IF NEW.version=2 AND NEW.qty=0 AND EXISTS (
    SELECT 1 FROM wms.invoice_reservation_release_line l
    JOIN wms.invoice_reservation_release p ON p.id=l.release_id
    WHERE l.after_id=NEW.id AND l.source=NEW.source
      AND p.organization_id=NEW.organization_id AND p.document_id=owner_id
  ) THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Invoice quantity change requires supported release evidence';
END $$;
CREATE CONSTRAINT TRIGGER invoice_reservation_insert_protocol AFTER INSERT ON wms.reservation_version
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION wms.check_invoice_reservation_insert();


CREATE OR REPLACE FUNCTION sales.reject_ownership_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Confirmed sales ownership is immutable';
END;
$$;
CREATE TRIGGER sales_ownership_immutable BEFORE UPDATE OR DELETE ON sales.deal_ownership
FOR EACH ROW EXECUTE FUNCTION sales.reject_ownership_change();
CREATE TRIGGER sales_ownership_no_truncate BEFORE TRUNCATE ON sales.deal_ownership
FOR EACH STATEMENT EXECUTE FUNCTION sales.reject_ownership_change();

-- Paid cancellation requires the durable, deferred-validated ERP package.
CREATE OR REPLACE FUNCTION sales.protect_invoice_money() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status = 'paid' OR EXISTS (
      SELECT 1 FROM sales.invoice_settlement WHERE document_id = OLD.id
    ) THEN
      RAISE EXCEPTION 'Invoice with recorded money cannot be deleted';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status = 'cancelled' AND EXISTS (SELECT 1 FROM sales.invoice_cancellation_receipt WHERE document_id=OLD.id)
     AND (NEW.status IS DISTINCT FROM OLD.status OR NEW.reserve_status IS DISTINCT FROM OLD.reserve_status) THEN
    RAISE EXCEPTION 'Confirmed invoice cancellation is terminal';
  END IF;
  IF NEW.status = 'cancelled' AND NEW.status IS DISTINCT FROM OLD.status
     AND EXISTS (SELECT 1 FROM sales.invoice_cancellation_receipt c WHERE c.document_id=NEW.id
       AND c.document_version=NEW.version AND c.content_sha256=NEW.content_sha256) THEN
    RETURN NEW; -- deferred package guard below must pass in the same transaction
  END IF;
  IF NEW.status = 'cancelled' AND NEW.status IS DISTINCT FROM OLD.status
     AND EXISTS (SELECT 1 FROM sales.invoice_issuance_receipt WHERE document_id=NEW.id) THEN
    RAISE EXCEPTION 'ERP invoice requires the atomic cancellation workflow';
  END IF;
  IF OLD.status = 'paid' AND NEW.status IS DISTINCT FROM 'paid' THEN
    RAISE EXCEPTION 'Paid invoice requires confirmed full refund reconciliation';
  END IF;
  IF NEW.status = 'cancelled' AND NEW.status IS DISTINCT FROM OLD.status AND EXISTS (
    SELECT 1 FROM sales.invoice_settlement WHERE document_id = OLD.id AND direction = 'receipt'
  ) THEN
    RAISE EXCEPTION 'Invoice receipt requires full refund reconciliation before cancellation';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER sales_invoice_money_guard BEFORE UPDATE OR DELETE ON sales.deal_document
FOR EACH ROW EXECUTE FUNCTION sales.protect_invoice_money();
CREATE TRIGGER sales_invoice_money_no_truncate BEFORE TRUNCATE ON sales.deal_document
FOR EACH STATEMENT EXECUTE FUNCTION sales.reject_ownership_change();
CREATE TRIGGER sales_settlement_immutable BEFORE UPDATE OR DELETE ON sales.invoice_settlement
FOR EACH ROW EXECUTE FUNCTION sales.reject_ownership_change();
CREATE TRIGGER sales_settlement_no_truncate BEFORE TRUNCATE ON sales.invoice_settlement
FOR EACH STATEMENT EXECUTE FUNCTION sales.reject_ownership_change();
CREATE TRIGGER sales_money_reconciliation_immutable BEFORE UPDATE OR DELETE ON sales.invoice_money_reconciliation
FOR EACH ROW EXECUTE FUNCTION sales.reject_ownership_change();
CREATE TRIGGER sales_money_reconciliation_no_truncate BEFORE TRUNCATE ON sales.invoice_money_reconciliation
FOR EACH STATEMENT EXECUTE FUNCTION sales.reject_ownership_change();

CREATE TRIGGER sales_item_request_immutable BEFORE UPDATE OR DELETE ON sales.deal_item_request
FOR EACH ROW EXECUTE FUNCTION sales.reject_ownership_change();
CREATE TRIGGER sales_item_request_no_truncate BEFORE TRUNCATE ON sales.deal_item_request
FOR EACH STATEMENT EXECUTE FUNCTION sales.reject_ownership_change();

CREATE TRIGGER sales_price_request_immutable BEFORE UPDATE OR DELETE ON sales.price_quote_request
FOR EACH ROW EXECUTE FUNCTION sales.reject_ownership_change();
CREATE TRIGGER sales_price_request_no_truncate BEFORE TRUNCATE ON sales.price_quote_request
FOR EACH STATEMENT EXECUTE FUNCTION sales.reject_ownership_change();

CREATE TRIGGER sales_fulfillment_review_immutable BEFORE UPDATE OR DELETE ON sales.invoice_fulfillment_review
FOR EACH ROW EXECUTE FUNCTION sales.reject_ownership_change();
CREATE TRIGGER sales_fulfillment_review_no_truncate BEFORE TRUNCATE ON sales.invoice_fulfillment_review
FOR EACH STATEMENT EXECUTE FUNCTION sales.reject_ownership_change();

CREATE TRIGGER sales_cancellation_receipt_immutable BEFORE UPDATE OR DELETE ON sales.invoice_cancellation_receipt
FOR EACH ROW EXECUTE FUNCTION sales.reject_ownership_change();
CREATE TRIGGER sales_cancellation_receipt_no_truncate BEFORE TRUNCATE ON sales.invoice_cancellation_receipt
FOR EACH STATEMENT EXECUTE FUNCTION sales.reject_ownership_change();

CREATE OR REPLACE FUNCTION sales.check_cancellation_package() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  c sales.invoice_cancellation_receipt%ROWTYPE;
  d sales.deal_document%ROWTYPE;
  r sales.invoice_fulfillment_review%ROWTYPE;
  m sales.invoice_money_reconciliation%ROWTYPE;
  w wms.invoice_reservation_release%ROWTYPE;
BEGIN
  SELECT * INTO c FROM sales.invoice_cancellation_receipt WHERE id=NEW.id;
  SELECT * INTO d FROM sales.deal_document WHERE id=c.document_id;
  SELECT * INTO r FROM sales.invoice_fulfillment_review WHERE id=c.fulfillment_review_id;
  SELECT * INTO m FROM sales.invoice_money_reconciliation WHERE id=r.money_reconciliation_id;
  SELECT * INTO w FROM wms.invoice_reservation_release WHERE id=c.release_id;
  IF jsonb_typeof(c.snapshot::jsonb) IS DISTINCT FROM 'object'
    OR jsonb_typeof(r.request::jsonb->'external_sources') IS DISTINCT FROM 'array'
    OR jsonb_typeof(c.snapshot::jsonb->'money'->'facts') IS DISTINCT FROM 'object'
    OR COALESCE(c.snapshot->'money'->>'state','') NOT IN ('no_receipts','fully_refunded')
    OR COALESCE(c.request->>'acknowledge_invoice_invalidation','') <> 'true'
    OR COALESCE(r.snapshot->>'basis_digest','') !~ '^[a-f0-9]{64}$'
    OR jsonb_typeof(r.snapshot::jsonb->'sections') IS DISTINCT FROM 'object'
    OR EXISTS (SELECT 1 FROM jsonb_each(r.snapshot::jsonb->'sections') section
      WHERE jsonb_typeof(section.value) IS DISTINCT FROM 'object'
        OR jsonb_typeof(section.value->'facts') IS DISTINCT FROM 'object'
        OR COALESCE(section.value->>'sha256','') !~ '^[a-f0-9]{64}$')
    OR COALESCE(c.snapshot->'withdrawal'->>'before_snapshot_sha256','') !~ '^[a-f0-9]{64}$'
    OR COALESCE(r.snapshot->'sections'->'logistics_shipment'->'facts'->>'sha256','') !~ '^[a-f0-9]{64}$'
    OR COALESCE(r.snapshot::jsonb->'sections' ?& ARRAY['wms_issue','wms_pick','logistics_shipment','accounting_issue','legacy_fulfillment'],false) IS NOT TRUE
    OR jsonb_typeof(m.facts::jsonb->'revalidated_banks') IS DISTINCT FROM 'array'
    OR jsonb_typeof(m.facts::jsonb->'settlements') IS DISTINCT FROM 'array'
    OR EXISTS (SELECT 1 FROM jsonb_array_elements(m.facts::jsonb->'revalidated_banks') b
      WHERE NOT EXISTS (SELECT 1 FROM accounting.entry e WHERE e.id=(b->>'entry_id')::integer
        AND e.organization_id=c.organization_id AND e.digest=b->>'digest'
        AND e.operation='bank_settlement' AND e.rule_version='bank-byn-v1'
        AND e.opening=false AND e.correction_of IS NULL)
      OR EXISTS (SELECT 1 FROM accounting.entry e WHERE e.correction_of=(b->>'entry_id')::integer))
    OR EXISTS (SELECT 1 FROM accounting.entry e JOIN accounting.line l ON l.entry_id=e.id
      WHERE e.organization_id=c.organization_id AND l.dimensions->>'settlement_document'='sales:document:'||d.id
        AND (e.operation='bank_settlement' OR EXISTS (SELECT 1 FROM accounting.line cash WHERE cash.entry_id=e.id AND cash.cash))
        AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(m.facts::jsonb->'revalidated_banks') b
           WHERE (b->>'entry_id')::integer=e.id AND b->>'digest'=e.digest))
    OR (SELECT count(*) FROM sales.invoice_settlement s WHERE s.document_id=d.id)
       IS DISTINCT FROM jsonb_array_length(m.facts::jsonb->'settlements')::bigint
    OR EXISTS (SELECT 1 FROM sales.invoice_settlement s WHERE s.document_id=d.id
      AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(m.facts::jsonb->'settlements') b
        WHERE (b->>'id')::integer=s.id AND (b->>'organization_id')::integer=s.organization_id
          AND (b->>'bank_entry_id')::integer=s.bank_entry_id AND b->>'direction'=s.direction
          AND (b->>'amount')::numeric=s.amount AND (b->>'refund_of')::integer IS NOT DISTINCT FROM s.refund_of
          AND b->'snapshot'=s.snapshot::jsonb))
    OR d.status IS DISTINCT FROM 'cancelled' OR d.reserve_status IS DISTINCT FROM 'released'
    OR c.document_version IS DISTINCT FROM d.version OR c.content_sha256 IS DISTINCT FROM d.content_sha256
    OR r.document_id IS DISTINCT FROM d.id OR r.organization_id IS DISTINCT FROM c.organization_id
    OR m.document_id IS DISTINCT FROM d.id OR m.organization_id IS DISTINCT FROM c.organization_id
    OR w.document_id IS DISTINCT FROM d.id OR w.organization_id IS DISTINCT FROM c.organization_id
    OR w.source_key IS DISTINCT FROM c.id
    OR c.snapshot->>'basis_digest' IS DISTINCT FROM r.snapshot->>'basis_digest'
    OR c.snapshot->>'review_digest' IS DISTINCT FROM r.digest
    OR c.snapshot->'money'->>'digest' IS DISTINCT FROM m.basis_digest
    OR (c.snapshot->'money'->'facts')::jsonb IS DISTINCT FROM (r.snapshot->'money'->'facts')::jsonb
    OR (c.snapshot->'money'->'facts')::jsonb IS DISTINCT FROM m.facts::jsonb
    OR c.snapshot->'release'->>'digest' IS DISTINCT FROM w.digest
    OR (w.snapshot->'fulfillment'->>'review_id') IS DISTINCT FROM r.id
    OR (r.request->>'all_fulfillment_sources_identified') IS DISTINCT FROM 'true'
    OR (m.request->>'all_money_sources_checked') IS DISTINCT FROM 'true'
    OR m.history_through < c.created_at::date
    OR m.history_from > d.issued_at::date
    OR jsonb_array_length(r.request::jsonb->'external_sources') < 1
    OR EXISTS (SELECT 1 FROM jsonb_array_elements(r.request::jsonb->'external_sources') e
        WHERE e->>'confirmed_no_fulfillment' IS DISTINCT FROM 'true'
          OR e->>'history_from' IS NULL OR e->>'history_through' IS NULL
          OR COALESCE(btrim(e->>'system'),'')='' OR COALESCE(btrim(e->>'reference'),'')=''
          OR (e->>'history_from')::date > d.issued_at::date
          OR (e->>'history_through')::date < c.created_at::date)
    OR jsonb_typeof(c.snapshot::jsonb->'withdrawal') IS DISTINCT FROM 'object'
    OR c.snapshot->'withdrawal'->'cancel_receipt_identity'->>'cancellation_receipt_id' IS DISTINCT FROM c.id
    OR c.snapshot->'withdrawal'->'cancel_receipt_identity'->>'cancellation_request_sha256' IS DISTINCT FROM c.request_hash
    OR c.snapshot->'withdrawal'->>'before_snapshot_sha256' IS DISTINCT FROM
       r.snapshot->'sections'->'logistics_shipment'->'facts'->>'sha256'
    OR EXISTS (SELECT 1 FROM logistics.shipment_invoice_binding b JOIN logistics.shipment s ON s.id=b.shipment_id
       WHERE b.organization_id=c.organization_id AND b.document_id=d.id AND s.status IS DISTINCT FROM 'withdrawn')
    OR EXISTS (SELECT 1 FROM logistics.rfq_invoice_binding b JOIN logistics.carrier_rfq q ON q.id=b.rfq_id
       WHERE b.organization_id=c.organization_id AND b.document_id=d.id AND q.status IS DISTINCT FROM 'withdrawn')
    OR EXISTS (SELECT 1 FROM jsonb_array_elements(r.snapshot::jsonb->'sections'->'logistics_shipment'->'facts'->'shipments') e
       WHERE NOT EXISTS (SELECT 1 FROM logistics.shipment s WHERE s.id=(e->'row'->>'id')::integer AND s.status='withdrawn'))
    OR EXISTS (SELECT 1 FROM jsonb_array_elements(r.snapshot::jsonb->'sections'->'logistics_shipment'->'facts'->'rfqs') e
       WHERE NOT EXISTS (SELECT 1 FROM logistics.carrier_rfq q WHERE q.id=(e->'row'->>'id')::integer AND q.status='withdrawn'))
    OR EXISTS (SELECT 1 FROM jsonb_array_elements(r.snapshot::jsonb->'sections'->'logistics_shipment'->'facts'->'intakes') e
       WHERE NOT EXISTS (SELECT 1 FROM logistics.shipment_intake i WHERE i.id=(e->'row'->>'id')::integer
         AND ((e->'row'->>'state'='resolved' AND i.state='resolved')
           OR (e->'row'->>'state'='pending' AND i.state='withdrawn' AND i.pending_reason='invoice_cancelled:'||c.id))))
    OR EXISTS (SELECT 1 FROM wms.physical_shipment_act WHERE document_id=d.id)
    OR NOT EXISTS (SELECT 1 FROM sales.deal_ownership WHERE deal_id=d.deal_id AND organization_id=c.organization_id)
    OR EXISTS (SELECT 1 FROM sales.invoice_settlement receipt WHERE receipt.document_id=d.id
      AND receipt.direction='receipt' AND receipt.amount IS DISTINCT FROM
      (SELECT COALESCE(SUM(refund.amount),0) FROM sales.invoice_settlement refund
       WHERE refund.refund_of=receipt.id AND refund.direction='refund'
         AND refund.document_id=d.id AND refund.organization_id=c.organization_id))
    OR NOT EXISTS (SELECT 1 FROM public.outbox_event e WHERE e.event_type='sales.invoice.cancelled'
      AND e.payload->>'cancellation_id'=c.id AND e.payload->>'cancellation_digest'=c.digest
      AND (e.payload->>'document_id')::integer=d.id)
  THEN RAISE EXCEPTION 'Incomplete or inconsistent invoice cancellation package';
  END IF;
  RETURN NEW;
END;
$$;
CREATE CONSTRAINT TRIGGER sales_cancellation_package AFTER INSERT ON sales.invoice_cancellation_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION sales.check_cancellation_package();


-- Unallocated additive guard. Install only with the invoice notification table.
CREATE OR REPLACE FUNCTION sales.protect_invoice_notification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Invoice notification receipts are immutable';
END;
$$;

CREATE TRIGGER invoice_notification_immutable
BEFORE UPDATE OR DELETE ON sales.invoice_notification
FOR EACH ROW EXECUTE FUNCTION sales.protect_invoice_notification();

CREATE TRIGGER invoice_notification_no_truncate
BEFORE TRUNCATE ON sales.invoice_notification
FOR EACH STATEMENT EXECUTE FUNCTION sales.protect_invoice_notification();


-- PROPOSAL ONLY. No Alembic revision allocated; do not auto-apply.
-- Prerequisites: accounting.organization, sales.deal_ownership and public.counterparty.
-- Register in an operator-allocated migration only after PostgreSQL verification.
CREATE TABLE sales.deal_client_binding (
    deal_id INTEGER PRIMARY KEY REFERENCES sales.deal_ownership(deal_id),
    organization_id INTEGER NOT NULL,
    counterparty_id INTEGER NOT NULL REFERENCES public.counterparty(id),
    snapshot JSON NOT NULL,
    evidence VARCHAR(1000) NOT NULL,
    actor VARCHAR(200) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT deal_client_binding_positive CHECK (organization_id > 0 AND counterparty_id > 0),
    CONSTRAINT deal_client_binding_evidence CHECK (length(btrim(evidence)) > 0 AND length(btrim(actor)) > 0)
);
CREATE INDEX ix_sales_deal_client_binding_organization_id ON sales.deal_client_binding(organization_id);
CREATE INDEX ix_sales_deal_client_binding_counterparty_id ON sales.deal_client_binding(counterparty_id);

CREATE FUNCTION sales.check_client_binding_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    book_id INTEGER;
    cp public.counterparty%ROWTYPE;
BEGIN
    -- Preserve org-first order even for direct SQL insertions.
    PERFORM id FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Client binding organization not found' USING ERRCODE = '23514';
    END IF;
    SELECT organization_id INTO book_id FROM sales.deal_ownership WHERE deal_id = NEW.deal_id;
    IF book_id IS DISTINCT FROM NEW.organization_id THEN
        RAISE EXCEPTION 'Client binding requires explicit deal ownership' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO cp FROM public.counterparty WHERE id = NEW.counterparty_id FOR UPDATE;
    IF NOT FOUND OR NOT cp.is_active OR cp.merged_into_id IS NOT NULL THEN
        RAISE EXCEPTION 'Client binding requires an active exact client' USING ERRCODE = '23514';
    END IF;
    IF (NEW.snapshot->>'organization_id')::INTEGER IS DISTINCT FROM NEW.organization_id
       OR (NEW.snapshot->'deal'->>'id')::INTEGER IS DISTINCT FROM NEW.deal_id
       OR (NEW.snapshot->'client'->>'id')::INTEGER IS DISTINCT FROM cp.id
       OR (NEW.snapshot->'client'->>'revision')::INTEGER IS DISTINCT FROM cp.revision
       OR (NEW.snapshot->'client'->>'name') IS DISTINCT FROM cp.name
       OR (NEW.snapshot->'client'->>'unp') IS DISTINCT FROM cp.unp
       OR (NEW.snapshot->'client'->>'is_active')::BOOLEAN IS DISTINCT FROM TRUE
       OR (NEW.snapshot->'client'->>'merged_into_id') IS NOT NULL THEN
        RAISE EXCEPTION 'Client binding snapshot differs from exact identity' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER sales_client_binding_insert BEFORE INSERT ON sales.deal_client_binding
FOR EACH ROW EXECUTE FUNCTION sales.check_client_binding_insert();

CREATE FUNCTION sales.reject_client_binding_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Confirmed client binding is immutable; use a separately approved correction protocol'
        USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER sales_client_binding_immutable BEFORE UPDATE OR DELETE ON sales.deal_client_binding
FOR EACH ROW EXECUTE FUNCTION sales.reject_client_binding_change();
CREATE TRIGGER sales_client_binding_no_truncate BEFORE TRUNCATE ON sales.deal_client_binding
FOR EACH STATEMENT EXECUTE FUNCTION sales.reject_client_binding_change();

-- MDM rename/merge updates Counterparty, never this binding. Reads use the
-- historical ID and snapshot; no alias following. No destructive downgrade.


-- Unallocated additive proposal ONLY. Primary integrates generator/migration.
-- Run only after existing Sales source and Accounting/WMS proposal prerequisites.
ALTER TABLE sales.deal_document ALTER COLUMN issued_by TYPE varchar(200);
ALTER TABLE public.audit_log ALTER COLUMN actor TYPE varchar(200);
CREATE TABLE sales.invoice_issuance_receipt (
    document_id integer PRIMARY KEY REFERENCES sales.deal_document(id),
    deal_id integer NOT NULL,
    organization_id integer NOT NULL,
    document_version integer NOT NULL,
    content_sha256 varchar(64) NOT NULL,
    snapshot_digest varchar(64) NOT NULL,
    reservation_digest varchar(64),
    request_key varchar(64) NOT NULL UNIQUE,
    request_hash varchar(64) NOT NULL,
    response json NOT NULL,
    actor varchar(200) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION sales.check_invoice_issuance_reserve_mode() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE d sales.deal_document%ROWTYPE; mode text;
BEGIN
    SELECT * INTO d FROM sales.deal_document WHERE id=NEW.document_id FOR UPDATE;
    mode := coalesce(d.snapshot_json->>'reserve_mode', 'stock');
    IF NOT FOUND OR mode NOT IN ('stock', 'on_order')
       OR (mode='stock' AND (NEW.reservation_digest IS NULL OR length(NEW.reservation_digest) <> 64))
       OR (mode='on_order' AND (NEW.reservation_digest IS NOT NULL
           OR d.reserve_status IS DISTINCT FROM 'unreserved' OR d.reserved_at IS NOT NULL)) THEN
        RAISE EXCEPTION 'Invoice issuance reservation mode mismatch';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER invoice_issuance_reserve_mode BEFORE INSERT ON sales.invoice_issuance_receipt
FOR EACH ROW EXECUTE FUNCTION sales.check_invoice_issuance_reserve_mode();

CREATE FUNCTION sales.protect_invoice_issuance_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Invoice issuance receipt is immutable';
END;
$$;
CREATE TRIGGER invoice_issuance_receipt_immutable
BEFORE UPDATE OR DELETE ON sales.invoice_issuance_receipt
FOR EACH ROW EXECUTE FUNCTION sales.protect_invoice_issuance_receipt();
CREATE TRIGGER invoice_issuance_receipt_no_truncate
BEFORE TRUNCATE ON sales.invoice_issuance_receipt
FOR EACH STATEMENT EXECUTE FUNCTION sales.protect_invoice_issuance_receipt();

CREATE TABLE sales.invoice_late_reservation_receipt (
    document_id integer PRIMARY KEY REFERENCES sales.deal_document(id),
    organization_id integer NOT NULL,
    document_version integer NOT NULL,
    content_sha256 varchar(64) NOT NULL,
    issuance_snapshot_digest varchar(64) NOT NULL,
    request_key varchar(64) NOT NULL UNIQUE,
    request_hash varchar(64) NOT NULL,
    reservation_digest varchar(64) NOT NULL,
    response json NOT NULL,
    actor varchar(200) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER late_reservation_receipt_immutable BEFORE UPDATE OR DELETE ON sales.invoice_late_reservation_receipt
FOR EACH ROW EXECUTE FUNCTION sales.protect_invoice_issuance_receipt();
CREATE TRIGGER late_reservation_receipt_no_truncate BEFORE TRUNCATE ON sales.invoice_late_reservation_receipt
FOR EACH STATEMENT EXECUTE FUNCTION sales.protect_invoice_issuance_receipt();

CREATE FUNCTION sales.check_late_reservation_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM id FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
    IF NOT EXISTS (
        SELECT 1 FROM sales.deal_document d
        JOIN sales.invoice_issuance_receipt i ON i.document_id=d.id
        JOIN wms.invoice_reservation w ON w.document_id=d.id
        WHERE d.id=NEW.document_id AND d.reserve_status='reserved'
          AND d.snapshot_json->>'reserve_mode'='on_order' AND i.reservation_digest IS NULL
          AND i.organization_id=NEW.organization_id AND w.organization_id=NEW.organization_id
          AND d.version=NEW.document_version AND i.document_version=NEW.document_version
          AND d.content_sha256=NEW.content_sha256 AND i.content_sha256=NEW.content_sha256
          AND i.snapshot_digest=NEW.issuance_snapshot_digest AND w.digest=NEW.reservation_digest
          AND (w.snapshot->>'version')::integer=NEW.document_version
          AND w.snapshot->>'content_sha256'=NEW.content_sha256
    ) THEN RAISE EXCEPTION 'Later reservation does not match the immutable invoice and warehouse'; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER check_late_reservation_receipt BEFORE INSERT ON sales.invoice_late_reservation_receipt
FOR EACH ROW EXECUTE FUNCTION sales.check_late_reservation_receipt();


-- UNALLOCATED IMMUTABILITY GUARDS. No runtime execution performed.

CREATE OR REPLACE FUNCTION sales.shipping_history_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Shipping history is immutable';
END;
$$;

CREATE OR REPLACE FUNCTION office.shipping_history_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Shipping history is immutable';
END;
$$;

CREATE TRIGGER shipping_history_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON sales.shipping_envelope
FOR EACH STATEMENT EXECUTE FUNCTION sales.shipping_history_immutable();

CREATE TRIGGER shipping_history_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON sales.order_invoice_association
FOR EACH STATEMENT EXECUTE FUNCTION sales.shipping_history_immutable();

CREATE TRIGGER shipping_history_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON office.shipping_request
FOR EACH STATEMENT EXECUTE FUNCTION office.shipping_history_immutable();

CREATE TRIGGER shipping_history_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON office.office_invoice_association
FOR EACH STATEMENT EXECUTE FUNCTION office.shipping_history_immutable();

CREATE TRIGGER shipping_history_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON office.shipping_review_assignment
FOR EACH STATEMENT EXECUTE FUNCTION office.shipping_history_immutable();


-- Unallocated additive packet. Run after ORM tables + existing release guards.
CREATE TRIGGER physical_act_immutable BEFORE UPDATE OR DELETE ON wms.physical_shipment_act
FOR EACH ROW EXECUTE FUNCTION wms.reject_reservation_change();
CREATE TRIGGER physical_act_no_truncate BEFORE TRUNCATE ON wms.physical_shipment_act
FOR EACH STATEMENT EXECUTE FUNCTION wms.reject_reservation_change();
CREATE TRIGGER physical_line_immutable BEFORE UPDATE OR DELETE ON wms.physical_shipment_line
FOR EACH ROW EXECUTE FUNCTION wms.reject_reservation_change();
CREATE TRIGGER physical_line_no_truncate BEFORE TRUNCATE ON wms.physical_shipment_line
FOR EACH STATEMENT EXECUTE FUNCTION wms.reject_reservation_change();

CREATE FUNCTION wms.protect_physical_movement() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='TRUNCATE' THEN
   IF EXISTS (SELECT 1 FROM wms.physical_shipment_line) THEN RAISE EXCEPTION 'Linked physical movement immutable'; END IF;
 ELSIF EXISTS (SELECT 1 FROM wms.physical_shipment_line WHERE movement_id=OLD.id) THEN
   RAISE EXCEPTION 'Linked physical movement immutable';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER physical_movement_immutable BEFORE UPDATE OR DELETE ON wms.stock_movement
FOR EACH ROW EXECUTE FUNCTION wms.protect_physical_movement();
CREATE TRIGGER physical_movement_no_truncate BEFORE TRUNCATE ON wms.stock_movement
FOR EACH STATEMENT EXECUTE FUNCTION wms.protect_physical_movement();

CREATE FUNCTION wms.check_physical_package() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE k integer; p wms.physical_shipment_act%ROWTYPE; r wms.invoice_reservation%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME='physical_shipment_act' THEN k:=NEW.id; ELSE k:=NEW.act_id; END IF;
 SELECT * INTO STRICT p FROM wms.physical_shipment_act WHERE id=k;
 SELECT * INTO STRICT r FROM wms.invoice_reservation WHERE document_id=p.document_id;
 IF p.organization_id<>r.organization_id OR p.reservation_digest<>r.digest
    OR p.document_version IS DISTINCT FROM (r.snapshot->>'version')::integer
    OR p.content_sha256 IS DISTINCT FROM r.snapshot->>'content_sha256'
    OR p.snapshot->>'kind' IS DISTINCT FROM 'internal_physical_shipment'
    OR (p.snapshot->>'document_id')::integer IS DISTINCT FROM p.document_id
    OR (p.snapshot->>'organization_id')::integer IS DISTINCT FROM p.organization_id
    OR p.snapshot->>'source_key' IS DISTINCT FROM p.source_key
    OR p.snapshot->>'request_hash' IS DISTINCT FROM p.request_hash
    OR p.snapshot->>'actor' IS DISTINCT FROM p.actor
    OR p.snapshot->>'operation_date' IS DISTINCT FROM p.operation_date::text
    OR jsonb_typeof(p.snapshot::jsonb->'lines') IS DISTINCT FROM 'array'
    OR jsonb_array_length(p.snapshot::jsonb->'lines')=0
    OR jsonb_array_length(p.snapshot::jsonb->'lines')<>(SELECT count(*) FROM wms.physical_shipment_line WHERE act_id=k)
    OR EXISTS (SELECT 1 FROM wms.invoice_reservation_release WHERE document_id=p.document_id)
 THEN RAISE EXCEPTION 'Invalid physical act identity/package'; END IF;
 IF EXISTS (
  SELECT 1 FROM wms.physical_shipment_line l
  JOIN wms.reservation_version b ON b.id=l.before_id
  JOIN wms.reservation_version a ON a.id=l.after_id
  JOIN wms.stock_movement m ON m.id=l.movement_id
  WHERE l.act_id=k AND (
   b.organization_id<>p.organization_id OR a.organization_id<>p.organization_id OR m.organization_id IS DISTINCT FROM p.organization_id
   OR b.source<>l.source OR a.source<>l.source OR b.sku_code<>l.sku_code OR a.sku_code<>l.sku_code OR m.sku_code<>l.sku_code
   OR b.warehouse<>l.warehouse OR a.warehouse<>l.warehouse OR m.warehouse<>l.warehouse
   OR a.version<>b.version+1 OR b.qty-l.qty<>a.qty OR a.qty<0
   OR m.kind<>'out' OR m.reason<>'shipment' OR m.qty<>l.qty OR m.doc_ref IS DISTINCT FROM 'physical-act:'||p.id::text
   OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(r.snapshot::jsonb->'allocations') e
       WHERE e->>'source'=l.source AND (e->>'line_no')::integer=l.line_no AND e->>'sku_code'=l.sku_code AND e->>'warehouse'=l.warehouse)
   OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(p.snapshot::jsonb->'lines') e
       WHERE e->>'source'=l.source AND (e->>'line_no')::integer=l.line_no
       AND (e->>'before_id')::integer=b.id AND (e->>'after_id')::integer=a.id
       AND (e->>'movement_id')::integer=m.id AND (e->>'qty')::numeric=l.qty
       AND e->>'sku_code'=l.sku_code AND e->>'warehouse'=l.warehouse)
  )
 ) THEN RAISE EXCEPTION 'Invalid physical consumption links'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER physical_package AFTER INSERT ON wms.physical_shipment_act
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION wms.check_physical_package();
CREATE CONSTRAINT TRIGGER physical_line_package AFTER INSERT ON wms.physical_shipment_line
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION wms.check_physical_package();

-- Extend the existing deferred namespace protocol, retaining no-shipment release.
CREATE OR REPLACE FUNCTION wms.check_invoice_reservation_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_id integer; allocation jsonb;
BEGIN
 IF NEW.source NOT LIKE 'invoice:%' THEN RETURN NEW; END IF;
 IF NEW.source !~ '^invoice:[0-9]+:[0-9]+:[0-9a-f]{32}$' THEN RAISE EXCEPTION 'Invalid invoice namespace'; END IF;
 owner_id:=split_part(NEW.source,':',2)::integer;
 SELECT e INTO allocation FROM wms.invoice_reservation r,
 LATERAL jsonb_array_elements(r.snapshot::jsonb->'allocations') e
 WHERE r.document_id=owner_id AND r.organization_id=NEW.organization_id AND e->>'source'=NEW.source;
 IF allocation IS NULL OR allocation->>'sku_code'<>NEW.sku_code OR allocation->>'warehouse'<>NEW.warehouse
 OR (allocation->>'line_no')::integer<>split_part(NEW.source,':',3)::integer THEN RAISE EXCEPTION 'Invalid invoice identity'; END IF;
 IF NEW.version=1 AND NEW.qty=(allocation->>'qty')::numeric AND NEW.qty>0 THEN RETURN NEW; END IF;
 IF EXISTS (SELECT 1 FROM wms.physical_shipment_line l JOIN wms.physical_shipment_act p ON p.id=l.act_id
  WHERE l.after_id=NEW.id AND l.source=NEW.source AND p.document_id=owner_id AND p.organization_id=NEW.organization_id)
 THEN RETURN NEW; END IF;
 IF NEW.version=2 AND NEW.qty=0 AND NOT EXISTS (SELECT 1 FROM wms.physical_shipment_act WHERE document_id=owner_id)
 AND EXISTS (SELECT 1 FROM wms.invoice_reservation_release_line l JOIN wms.invoice_reservation_release p ON p.id=l.release_id
  WHERE l.after_id=NEW.id AND l.source=NEW.source AND p.organization_id=NEW.organization_id AND p.document_id=owner_id)
 THEN RETURN NEW; END IF;
 RAISE EXCEPTION 'Invoice quantity change requires linked evidence';
END $$;

CREATE FUNCTION wms.no_release_after_physical() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF EXISTS (SELECT 1 FROM wms.physical_shipment_act WHERE document_id=NEW.document_id) THEN
  RAISE EXCEPTION 'Physical act excludes no-shipment release';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER no_release_after_physical BEFORE INSERT ON wms.invoice_reservation_release
FOR EACH ROW EXECUTE FUNCTION wms.no_release_after_physical();


-- ADDITIVE REVIEW ARTIFACT. No migration or installation is performed here.
-- Install after both DealLoss ORM tables and existing invoice cancellation,
-- issuance, reservation-release, logistics and accounting guards. PostgreSQL
-- concurrency/commit-time tests are a required integration gate.
-- DML privileges remain application-only: these guards prove package consistency,
-- not actor authentication. Canonical SHA-256 is verified by the application.

ALTER TABLE sales.deal_loss_resolution ADD COLUMN born_root_transaction bigint NOT NULL DEFAULT txid_current();
CREATE OR REPLACE FUNCTION sales.stamp_loss_resolution_root() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 NEW.born_root_transaction := txid_current();
 RETURN NEW;
END $$;
CREATE TRIGGER stamp_loss_resolution_root BEFORE INSERT ON sales.deal_loss_resolution
FOR EACH ROW EXECUTE FUNCTION sales.stamp_loss_resolution_root();

CREATE OR REPLACE FUNCTION sales.loss_composition(deal_key integer) RETURNS jsonb
LANGUAGE sql STABLE AS $$
 SELECT COALESCE(jsonb_agg(jsonb_build_object('id',id,'deal_id',deal_id,'kind',kind,
   'version',version,'content_sha256',content_sha256,'supersedes_id',supersedes_id,
   'superseded_by_id',superseded_by_id) ORDER BY id),'[]'::jsonb)
 FROM sales.deal_document WHERE deal_id=deal_key AND kind='invoice'
$$;

CREATE OR REPLACE FUNCTION sales.loss_kind(funnel_key text, stage_key text) RETURNS boolean
LANGUAGE sql STABLE AS $$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM sales.stage WHERE funnel=funnel_key AND is_active)
   THEN EXISTS(SELECT 1 FROM sales.stage WHERE funnel=funnel_key AND code=stage_key AND is_active AND kind='lost')
   ELSE (funnel_key,stage_key) IN (('new_clients','lost'),('repeat_clients','rp_lost'),('tenders','tn_lost')) END
$$;

CREATE OR REPLACE FUNCTION sales.guard_loss_request() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE d sales.deal%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Loss requests are durable'; END IF;
 IF TG_OP='UPDATE' THEN
   IF (to_jsonb(NEW)-'state') IS DISTINCT FROM (to_jsonb(OLD)-'state')
     OR OLD.state<>'pending' OR NEW.state NOT IN ('finalized','withdrawn')
     OR NOT EXISTS(SELECT 1 FROM sales.deal_loss_resolution r WHERE r.request_id=NEW.id AND r.action=NEW.state)
   THEN RAISE EXCEPTION 'Immutable command; resolution required'; END IF;
   RETURN NEW;
 END IF;
 PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
 SELECT * INTO STRICT d FROM sales.deal WHERE id=NEW.deal_id FOR UPDATE;
 PERFORM id FROM sales.deal_document WHERE deal_id=d.id AND kind='invoice' ORDER BY id FOR UPDATE;
 IF NEW.state IS DISTINCT FROM 'pending'
   OR NOT EXISTS(SELECT 1 FROM sales.deal_ownership WHERE deal_id=d.id AND organization_id=NEW.organization_id)
   OR NEW.command->>'request_key' IS DISTINCT FROM NEW.id
   OR (NEW.command->>'organization_id')::integer IS DISTINCT FROM NEW.organization_id
   OR COALESCE(btrim(NEW.command->>'reason_code'),'')=''
   OR NEW.snapshot->>'funnel' IS DISTINCT FROM d.funnel
   OR NEW.snapshot->>'stage' IS DISTINCT FROM d.stage
   OR NEW.snapshot::jsonb->'invoices' IS DISTINCT FROM sales.loss_composition(d.id)
   OR sales.loss_kind(d.funnel,d.stage)
   OR sales.loss_kind(d.funnel,NEW.snapshot->>'lost_stage') IS NOT TRUE
 THEN RAISE EXCEPTION 'Invalid loss request scope or composition'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER deal_loss_request_guard BEFORE INSERT OR UPDATE OR DELETE ON sales.deal_loss_request
FOR EACH ROW EXECUTE FUNCTION sales.guard_loss_request();
CREATE TRIGGER deal_loss_request_no_truncate BEFORE TRUNCATE ON sales.deal_loss_request
EXECUTE FUNCTION sales.reject_ownership_change();
CREATE TRIGGER deal_loss_resolution_immutable BEFORE UPDATE OR DELETE ON sales.deal_loss_resolution
FOR EACH ROW EXECUTE FUNCTION sales.reject_ownership_change();
CREATE TRIGGER deal_loss_resolution_no_truncate BEFORE TRUNCATE ON sales.deal_loss_resolution
EXECUTE FUNCTION sales.reject_ownership_change();

CREATE OR REPLACE FUNCTION sales.guard_loss_composition() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE old_deal integer; new_deal integer; old_kind text; new_kind text;
BEGIN
 IF TG_OP<>'INSERT' THEN old_deal:=OLD.deal_id; old_kind:=OLD.kind; END IF;
 IF TG_OP<>'DELETE' THEN new_deal:=NEW.deal_id; new_kind:=NEW.kind; END IF;
 IF TG_OP='UPDATE' AND ROW(OLD.id,OLD.deal_id,OLD.kind,OLD.version,OLD.content_sha256,OLD.supersedes_id,OLD.superseded_by_id)
   IS NOT DISTINCT FROM ROW(NEW.id,NEW.deal_id,NEW.kind,NEW.version,NEW.content_sha256,NEW.supersedes_id,NEW.superseded_by_id)
 THEN RETURN NEW; END IF;
 IF old_kind='invoice' OR new_kind='invoice' THEN
   -- Serialize phantom inserts/moves with request creation and finalization.
   PERFORM id FROM sales.deal WHERE id IN (old_deal,new_deal) ORDER BY id FOR UPDATE;
   IF EXISTS(SELECT 1 FROM sales.deal_loss_request WHERE deal_id IN (old_deal,new_deal) AND state='pending')
   THEN RAISE EXCEPTION 'Pending loss request freezes every invoice identity'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER deal_loss_invoice_composition BEFORE INSERT OR UPDATE OR DELETE ON sales.deal_document
FOR EACH ROW EXECUTE FUNCTION sales.guard_loss_composition();
CREATE TRIGGER deal_loss_invoice_no_truncate BEFORE TRUNCATE ON sales.deal_document
EXECUTE FUNCTION sales.reject_ownership_change();

CREATE OR REPLACE FUNCTION sales.guard_loss_stage() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND ROW(NEW.funnel,NEW.stage) IS NOT DISTINCT FROM ROW(OLD.funnel,OLD.stage)
 THEN RETURN NEW; END IF;
 -- Coordinate rare semantic edits with entering a populated stage, without
 -- serializing invoice/document operations that only lock the unchanged deal.
 PERFORM pg_advisory_xact_lock(1935764588, 1);
 IF EXISTS(SELECT 1 FROM sales.deal_loss_request WHERE deal_id=NEW.id AND state='pending')
 THEN RAISE EXCEPTION 'Pending loss request blocks stage/funnel transitions'; END IF;
 IF sales.loss_kind(NEW.funnel,NEW.stage) THEN
   IF TG_OP='INSERT' THEN RAISE EXCEPTION 'New deal cannot start lost'; END IF;
   IF NOT EXISTS(SELECT 1 FROM sales.deal_loss_request q JOIN sales.deal_loss_resolution r ON r.request_id=q.id
     WHERE q.deal_id=NEW.id AND q.state='finalized' AND r.action='finalized'
       AND r.born_root_transaction = txid_current()
       AND q.snapshot->>'funnel'=NEW.funnel AND q.snapshot->>'stage'=OLD.stage
       AND q.snapshot->>'lost_stage'=NEW.stage AND OLD.funnel=NEW.funnel)
   THEN RAISE EXCEPTION 'Lost stage requires exact durable resolution'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER deal_loss_stage_guard BEFORE INSERT OR UPDATE ON sales.deal
FOR EACH ROW EXECUTE FUNCTION sales.guard_loss_stage();

CREATE OR REPLACE FUNCTION sales.guard_loss_stage_definition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(1935764588, 1);
 IF TG_OP='UPDATE' AND ROW(OLD.funnel,OLD.code,OLD.kind,OLD.is_active)
    IS DISTINCT FROM ROW(NEW.funnel,NEW.code,NEW.kind,NEW.is_active)
    AND EXISTS(SELECT 1 FROM sales.deal WHERE funnel IN (OLD.funnel,NEW.funnel))
 THEN RAISE EXCEPTION 'Populated funnel semantics require explicit migration'; END IF;
 IF TG_OP='INSERT' AND NEW.is_active AND NEW.kind='lost'
    AND EXISTS(SELECT 1 FROM sales.deal WHERE funnel=NEW.funnel AND stage=NEW.code)
 THEN RAISE EXCEPTION 'Cannot reclassify populated stage as lost'; END IF;
 IF TG_OP='DELETE' THEN
   IF EXISTS(SELECT 1 FROM sales.deal WHERE funnel=OLD.funnel)
   THEN RAISE EXCEPTION 'Populated funnel semantics require explicit migration'; END IF;
   RETURN OLD;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER deal_loss_stage_definition BEFORE INSERT OR UPDATE OR DELETE ON sales.stage
FOR EACH ROW EXECUTE FUNCTION sales.guard_loss_stage_definition();

CREATE UNIQUE INDEX uq_loss_request_event ON public.outbox_event ((payload->>'request_id'))
WHERE event_type='sales.deal.loss_requested';
CREATE UNIQUE INDEX uq_loss_resolution_event ON public.outbox_event ((payload->>'resolution_id'))
WHERE event_type IN ('sales.deal.loss_finalized','sales.deal.loss_withdrawn');

-- Source-owned cancellation package predicate copied verbatim from accounting_ownership_guards.sql,
-- with an explicit receipt key and current reserve/pick checks added for later finalization.
CREATE OR REPLACE FUNCTION sales.check_loss_cancelled_invoice(cancellation_key text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
  c sales.invoice_cancellation_receipt%ROWTYPE;
  d sales.deal_document%ROWTYPE;
  r sales.invoice_fulfillment_review%ROWTYPE;
  m sales.invoice_money_reconciliation%ROWTYPE;
  w wms.invoice_reservation_release%ROWTYPE;
BEGIN
  SELECT * INTO c FROM sales.invoice_cancellation_receipt WHERE id=cancellation_key;
  SELECT * INTO d FROM sales.deal_document WHERE id=c.document_id;
  SELECT * INTO r FROM sales.invoice_fulfillment_review WHERE id=c.fulfillment_review_id;
  SELECT * INTO m FROM sales.invoice_money_reconciliation WHERE id=r.money_reconciliation_id;
  SELECT * INTO w FROM wms.invoice_reservation_release WHERE id=c.release_id;
  IF jsonb_typeof(c.snapshot::jsonb) IS DISTINCT FROM 'object'
    OR jsonb_typeof(r.request::jsonb->'external_sources') IS DISTINCT FROM 'array'
    OR jsonb_typeof(c.snapshot::jsonb->'money'->'facts') IS DISTINCT FROM 'object'
    OR COALESCE(c.snapshot->'money'->>'state','') NOT IN ('no_receipts','fully_refunded')
    OR COALESCE(c.request->>'acknowledge_invoice_invalidation','') <> 'true'
    OR COALESCE(r.snapshot->>'basis_digest','') !~ '^[a-f0-9]{64}$'
    OR jsonb_typeof(r.snapshot::jsonb->'sections') IS DISTINCT FROM 'object'
    OR EXISTS (SELECT 1 FROM jsonb_each(r.snapshot::jsonb->'sections') section
      WHERE jsonb_typeof(section.value) IS DISTINCT FROM 'object'
        OR jsonb_typeof(section.value->'facts') IS DISTINCT FROM 'object'
        OR COALESCE(section.value->>'sha256','') !~ '^[a-f0-9]{64}$')
    OR COALESCE(c.snapshot->'withdrawal'->>'before_snapshot_sha256','') !~ '^[a-f0-9]{64}$'
    OR COALESCE(r.snapshot->'sections'->'logistics_shipment'->'facts'->>'sha256','') !~ '^[a-f0-9]{64}$'
    OR COALESCE(r.snapshot::jsonb->'sections' ?& ARRAY['wms_issue','wms_pick','logistics_shipment','accounting_issue','legacy_fulfillment'],false) IS NOT TRUE
    OR jsonb_typeof(m.facts::jsonb->'revalidated_banks') IS DISTINCT FROM 'array'
    OR jsonb_typeof(m.facts::jsonb->'settlements') IS DISTINCT FROM 'array'
    OR EXISTS (SELECT 1 FROM jsonb_array_elements(m.facts::jsonb->'revalidated_banks') b
      WHERE NOT EXISTS (SELECT 1 FROM accounting.entry e WHERE e.id=(b->>'entry_id')::integer
        AND e.organization_id=c.organization_id AND e.digest=b->>'digest'
        AND e.operation='bank_settlement' AND e.rule_version='bank-byn-v1'
        AND e.opening=false AND e.correction_of IS NULL)
      OR EXISTS (SELECT 1 FROM accounting.entry e WHERE e.correction_of=(b->>'entry_id')::integer))
    OR EXISTS (SELECT 1 FROM accounting.entry e JOIN accounting.line l ON l.entry_id=e.id
      WHERE e.organization_id=c.organization_id AND l.dimensions->>'settlement_document'='sales:document:'||d.id
        AND (e.operation='bank_settlement' OR EXISTS (SELECT 1 FROM accounting.line cash WHERE cash.entry_id=e.id AND cash.cash))
        AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(m.facts::jsonb->'revalidated_banks') b
           WHERE (b->>'entry_id')::integer=e.id AND b->>'digest'=e.digest))
    OR (SELECT count(*) FROM sales.invoice_settlement s WHERE s.document_id=d.id)
       IS DISTINCT FROM jsonb_array_length(m.facts::jsonb->'settlements')::bigint
    OR EXISTS (SELECT 1 FROM sales.invoice_settlement s WHERE s.document_id=d.id
      AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(m.facts::jsonb->'settlements') b
        WHERE (b->>'id')::integer=s.id AND (b->>'organization_id')::integer=s.organization_id
          AND (b->>'bank_entry_id')::integer=s.bank_entry_id AND b->>'direction'=s.direction
          AND (b->>'amount')::numeric=s.amount AND (b->>'refund_of')::integer IS NOT DISTINCT FROM s.refund_of
          AND b->'snapshot'=s.snapshot::jsonb))
    OR d.status IS DISTINCT FROM 'cancelled' OR d.reserve_status IS DISTINCT FROM 'released'
    OR c.document_version IS DISTINCT FROM d.version OR c.content_sha256 IS DISTINCT FROM d.content_sha256
    OR r.document_id IS DISTINCT FROM d.id OR r.organization_id IS DISTINCT FROM c.organization_id
    OR m.document_id IS DISTINCT FROM d.id OR m.organization_id IS DISTINCT FROM c.organization_id
    OR w.document_id IS DISTINCT FROM d.id OR w.organization_id IS DISTINCT FROM c.organization_id
    OR w.source_key IS DISTINCT FROM c.id
    OR c.snapshot->>'basis_digest' IS DISTINCT FROM r.snapshot->>'basis_digest'
    OR c.snapshot->>'review_digest' IS DISTINCT FROM r.digest
    OR c.snapshot->'money'->>'digest' IS DISTINCT FROM m.basis_digest
    OR (c.snapshot->'money'->'facts')::jsonb IS DISTINCT FROM (r.snapshot->'money'->'facts')::jsonb
    OR (c.snapshot->'money'->'facts')::jsonb IS DISTINCT FROM m.facts::jsonb
    OR c.snapshot->'release'->>'digest' IS DISTINCT FROM w.digest
    OR (w.snapshot->'fulfillment'->>'review_id') IS DISTINCT FROM r.id
    OR (r.request->>'all_fulfillment_sources_identified') IS DISTINCT FROM 'true'
    OR (m.request->>'all_money_sources_checked') IS DISTINCT FROM 'true'
    OR m.history_through < c.created_at::date
    OR m.history_from > d.issued_at::date
    OR jsonb_array_length(r.request::jsonb->'external_sources') < 1
    OR EXISTS (SELECT 1 FROM jsonb_array_elements(r.request::jsonb->'external_sources') e
        WHERE e->>'confirmed_no_fulfillment' IS DISTINCT FROM 'true'
          OR e->>'history_from' IS NULL OR e->>'history_through' IS NULL
          OR COALESCE(btrim(e->>'system'),'')='' OR COALESCE(btrim(e->>'reference'),'')=''
          OR (e->>'history_from')::date > d.issued_at::date
          OR (e->>'history_through')::date < c.created_at::date)
    OR jsonb_typeof(c.snapshot::jsonb->'withdrawal') IS DISTINCT FROM 'object'
    OR c.snapshot->'withdrawal'->'cancel_receipt_identity'->>'cancellation_receipt_id' IS DISTINCT FROM c.id
    OR c.snapshot->'withdrawal'->'cancel_receipt_identity'->>'cancellation_request_sha256' IS DISTINCT FROM c.request_hash
    OR c.snapshot->'withdrawal'->>'before_snapshot_sha256' IS DISTINCT FROM
       r.snapshot->'sections'->'logistics_shipment'->'facts'->>'sha256'
    OR EXISTS (SELECT 1 FROM logistics.shipment_invoice_binding b JOIN logistics.shipment s ON s.id=b.shipment_id
       WHERE b.organization_id=c.organization_id AND b.document_id=d.id AND s.status IS DISTINCT FROM 'withdrawn')
    OR EXISTS (SELECT 1 FROM logistics.rfq_invoice_binding b JOIN logistics.carrier_rfq q ON q.id=b.rfq_id
       WHERE b.organization_id=c.organization_id AND b.document_id=d.id AND q.status IS DISTINCT FROM 'withdrawn')
    OR EXISTS (SELECT 1 FROM jsonb_array_elements(r.snapshot::jsonb->'sections'->'logistics_shipment'->'facts'->'shipments') e
       WHERE NOT EXISTS (SELECT 1 FROM logistics.shipment s WHERE s.id=(e->'row'->>'id')::integer AND s.status='withdrawn'))
    OR EXISTS (SELECT 1 FROM jsonb_array_elements(r.snapshot::jsonb->'sections'->'logistics_shipment'->'facts'->'rfqs') e
       WHERE NOT EXISTS (SELECT 1 FROM logistics.carrier_rfq q WHERE q.id=(e->'row'->>'id')::integer AND q.status='withdrawn'))
    OR EXISTS (SELECT 1 FROM jsonb_array_elements(r.snapshot::jsonb->'sections'->'logistics_shipment'->'facts'->'intakes') e
       WHERE NOT EXISTS (SELECT 1 FROM logistics.shipment_intake i WHERE i.id=(e->'row'->>'id')::integer
         AND ((e->'row'->>'state'='resolved' AND i.state='resolved')
           OR (e->'row'->>'state'='pending' AND i.state='withdrawn' AND i.pending_reason='invoice_cancelled:'||c.id))))
    OR EXISTS (SELECT 1 FROM wms.physical_shipment_act WHERE document_id=d.id)
    OR NOT EXISTS (SELECT 1 FROM sales.deal_ownership WHERE deal_id=d.deal_id AND organization_id=c.organization_id)
    OR EXISTS (SELECT 1 FROM sales.invoice_settlement receipt WHERE receipt.document_id=d.id
      AND receipt.direction='receipt' AND receipt.amount IS DISTINCT FROM
      (SELECT COALESCE(SUM(refund.amount),0) FROM sales.invoice_settlement refund
       WHERE refund.refund_of=receipt.id AND refund.direction='refund'
         AND refund.document_id=d.id AND refund.organization_id=c.organization_id))
    OR NOT EXISTS (SELECT 1 FROM public.outbox_event e WHERE e.event_type='sales.invoice.cancelled'
      AND e.payload->>'cancellation_id'=c.id AND e.payload->>'cancellation_digest'=c.digest
      AND (e.payload->>'document_id')::integer=d.id)
  THEN RAISE EXCEPTION 'Incomplete or inconsistent invoice cancellation package';
  END IF;
  IF EXISTS (SELECT 1 FROM wms.invoice_reservation_release_line l
    LEFT JOIN wms.reservation_version v ON v.id=l.after_id
    WHERE l.release_id=w.id AND (v.id IS NULL OR v.qty<>0 OR EXISTS(
      SELECT 1 FROM wms.reservation_version newer WHERE newer.organization_id=w.organization_id
      AND newer.source=l.source AND newer.version>v.version)))
    OR NOT EXISTS(SELECT 1 FROM wms.reservation_event_state WHERE document_id=d.id AND state='released')
    OR EXISTS(SELECT 1 FROM wms.task t JOIN wms.reservation_pick p ON p.task_id=t.id
      WHERE p.document_id=d.id AND (t.status<>'canceled' OR t.done_at IS NOT NULL))
  THEN RAISE EXCEPTION 'Loss requires current released reserve and canceled picks'; END IF;
  RETURN;
END;
$$;

-- The final package checker is DEFERRED because receipt insertion, request state,
-- deal history/stage and outbox are one transaction, in that order.
CREATE OR REPLACE FUNCTION sales.check_loss_package() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE q sales.deal_loss_request%ROWTYPE; r sales.deal_loss_resolution%ROWTYPE;
  d sales.deal%ROWTYPE; invoice jsonb; c sales.invoice_cancellation_receipt%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME='deal_loss_request' THEN SELECT * INTO STRICT q FROM sales.deal_loss_request WHERE id=NEW.id;
 ELSE SELECT * INTO STRICT q FROM sales.deal_loss_request WHERE id=NEW.request_id; END IF;
 SELECT * INTO STRICT d FROM sales.deal WHERE id=q.deal_id;
 IF NOT EXISTS(SELECT 1 FROM public.outbox_event e WHERE e.event_type='sales.deal.loss_requested'
   AND e.payload->>'request_id'=q.id AND e.payload->>'digest'=q.digest
   AND (e.payload->>'deal_id')::integer=q.deal_id AND (e.payload->>'organization_id')::integer=q.organization_id)
 THEN RAISE EXCEPTION 'Loss request requires unique outbox evidence'; END IF;
 IF q.state='pending' THEN
   IF EXISTS(SELECT 1 FROM sales.deal_loss_resolution WHERE request_id=q.id)
   THEN RAISE EXCEPTION 'Resolution requires terminal request projection'; END IF;
   RETURN NEW;
 END IF;
 SELECT * INTO STRICT r FROM sales.deal_loss_resolution WHERE request_id=q.id;
 IF r.action IS DISTINCT FROM q.state OR r.command->>'request_key' IS DISTINCT FROM r.id
   OR r.command->>'expected_request_digest' IS DISTINCT FROM q.digest
   OR r.snapshot->>'request_digest' IS DISTINCT FROM q.digest
   OR COALESCE(btrim(r.command->>'evidence'),'')=''
   OR r.snapshot::jsonb->'composition' IS DISTINCT FROM q.snapshot::jsonb->'invoices'
   OR q.snapshot::jsonb->'invoices' IS DISTINCT FROM sales.loss_composition(q.deal_id)
   OR NOT EXISTS(SELECT 1 FROM public.outbox_event e WHERE e.event_type='sales.deal.loss_'||r.action
     AND e.payload->>'resolution_id'=r.id AND e.payload->>'request_id'=q.id AND e.payload->>'digest'=r.digest)
 THEN RAISE EXCEPTION 'Incomplete loss resolution package'; END IF;
 IF r.action='withdrawn' THEN RETURN NEW; END IF;
 IF r.action<>'finalized' OR d.funnel IS DISTINCT FROM q.snapshot->>'funnel'
   OR d.stage IS DISTINCT FROM q.snapshot->>'lost_stage' OR NOT sales.loss_kind(d.funnel,d.stage)
   OR d.lost_reason_code IS DISTINCT FROM q.command->>'reason_code'
   OR d.lost_comment IS DISTINCT FROM q.command->>'comment' OR d.closed_date IS NULL
   OR jsonb_array_length(r.snapshot::jsonb->'invoices') IS DISTINCT FROM jsonb_array_length(q.snapshot::jsonb->'invoices')
 THEN RAISE EXCEPTION 'Loss finalization stage or invoice set mismatch'; END IF;
 FOR invoice IN SELECT * FROM jsonb_array_elements(q.snapshot::jsonb->'invoices') LOOP
   SELECT * INTO STRICT c FROM sales.invoice_cancellation_receipt WHERE document_id=(invoice->>'id')::integer;
   IF c.organization_id<>q.organization_id OR c.document_version IS DISTINCT FROM (invoice->>'version')::integer
     OR c.content_sha256 IS DISTINCT FROM invoice->>'content_sha256'
     OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(r.snapshot::jsonb->'invoices') e
       WHERE (e->>'document_id')::integer=c.document_id AND e->>'ready'='true'
         AND e->'blockers'='[]'::jsonb AND e->'cancellation_receipt'->>'cancellation_id'=c.id
         AND e->'cancellation_receipt'->>'digest'=c.digest)
   THEN RAISE EXCEPTION 'Loss finalization missing exact cancellation evidence'; END IF;
   PERFORM sales.check_loss_cancelled_invoice(c.id);
 END LOOP;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER deal_loss_request_package AFTER INSERT OR UPDATE ON sales.deal_loss_request
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION sales.check_loss_package();
CREATE CONSTRAINT TRIGGER deal_loss_resolution_package AFTER INSERT ON sales.deal_loss_resolution
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION sales.check_loss_package();


-- Pending integration with purchase_order_creation; do not install separately.
-- INSERT provenance is separate from xmin: an UPDATE also changes xmin, and
-- savepoints use subtransaction xids. Only the order's INSERT trigger records it.
CREATE TABLE procurement.order_insert_proof (
  order_id integer PRIMARY KEY,
  root_transaction bigint NOT NULL
);
CREATE INDEX ix_order_insert_proof_transaction ON procurement.order_insert_proof(root_transaction);
CREATE OR REPLACE FUNCTION procurement.guard_order_insert_proof() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF pg_trigger_depth() <> 2 OR NEW.root_transaction IS DISTINCT FROM txid_current()
    OR NOT EXISTS (SELECT 1 FROM procurement.purchase_order WHERE id=NEW.order_id) THEN
    RAISE EXCEPTION 'Order insertion proof must originate from the order INSERT trigger';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_order_insert_proof BEFORE INSERT ON procurement.order_insert_proof
FOR EACH ROW EXECUTE FUNCTION procurement.guard_order_insert_proof();
CREATE TRIGGER immutable_order_insert_proof BEFORE UPDATE OR DELETE ON procurement.order_insert_proof
FOR EACH ROW EXECUTE FUNCTION procurement.reject_receipt_revision_mutation();
CREATE TRIGGER immutable_order_insert_proof_truncate BEFORE TRUNCATE ON procurement.order_insert_proof
FOR EACH STATEMENT EXECUTE FUNCTION procurement.reject_receipt_revision_mutation();
CREATE OR REPLACE FUNCTION procurement.record_order_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO procurement.order_insert_proof(order_id,root_transaction) VALUES (NEW.id,txid_current());
  RETURN NEW;
END $$;
CREATE TRIGGER record_order_insert AFTER INSERT ON procurement.purchase_order
FOR EACH ROW EXECUTE FUNCTION procurement.record_order_insert();

CREATE OR REPLACE FUNCTION procurement.keep_order_line_parent() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.order_id IS DISTINCT FROM OLD.order_id THEN
    RAISE EXCEPTION 'Order line parent is immutable; create a new line in the target order';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER keep_order_line_parent BEFORE UPDATE OF order_id ON procurement.purchase_order_line
FOR EACH ROW EXECUTE FUNCTION procurement.keep_order_line_parent();

-- All object keys below are fixed ASCII; numbers are validated integer identifiers.
CREATE OR REPLACE FUNCTION procurement.order_command_json(value jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE result text;
BEGIN
  CASE jsonb_typeof(value)
    WHEN 'object' THEN
      SELECT '{' || coalesce(string_agg(to_jsonb(key)::text || ':' ||
        procurement.order_command_json(val), ',' ORDER BY key COLLATE "C"), '') || '}'
        INTO result FROM jsonb_each(value) AS pairs(key,val);
    WHEN 'array' THEN
      SELECT '[' || coalesce(string_agg(procurement.order_command_json(val), ',' ORDER BY ordinal), '') || ']'
        INTO result FROM jsonb_array_elements(value) WITH ORDINALITY AS items(val,ordinal);
    ELSE result := value::text;
  END CASE;
  RETURN result;
END $$;

CREATE OR REPLACE FUNCTION procurement.order_command_text(value jsonb, max_length integer) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT coalesce(jsonb_typeof(value) = 'string' AND length(value #>> '{}') BETWEEN 1 AND max_length
    AND (value #>> '{}') = btrim(value #>> '{}',
      U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'), false)
$$;

-- Immutable evidence of the actual pre-transition state, not a reconstruction
-- of an approval stage from a request which is already linked to an order.
CREATE TABLE procurement.order_request_transition_proof (
  request_id integer NOT NULL,
  root_transaction bigint NOT NULL,
  snapshot jsonb NOT NULL,
  PRIMARY KEY (request_id, root_transaction)
);
CREATE OR REPLACE FUNCTION procurement.guard_order_request_transition_proof() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF pg_trigger_depth() <> 2 OR NEW.root_transaction IS DISTINCT FROM txid_current()
    OR NOT EXISTS (SELECT 1 FROM procurement.purchase_request WHERE id=NEW.request_id AND stage='approval') THEN
    RAISE EXCEPTION 'Approval proof must originate from the request transition trigger';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_order_request_transition_proof BEFORE INSERT ON procurement.order_request_transition_proof
FOR EACH ROW EXECUTE FUNCTION procurement.guard_order_request_transition_proof();
CREATE TRIGGER immutable_order_request_transition_proof BEFORE UPDATE OR DELETE ON procurement.order_request_transition_proof
FOR EACH ROW EXECUTE FUNCTION procurement.reject_receipt_revision_mutation();
CREATE TRIGGER immutable_order_request_transition_proof_truncate BEFORE TRUNCATE ON procurement.order_request_transition_proof
FOR EACH STATEMENT EXECUTE FUNCTION procurement.reject_receipt_revision_mutation();
CREATE OR REPLACE FUNCTION procurement.record_order_request_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE owner_id integer;
BEGIN
  IF OLD.stage='approval' AND NEW.stage='po' THEN
    SELECT id INTO owner_id FROM procurement.purchase_ownership WHERE kind='request' AND source_id=OLD.id;
    IF owner_id IS NOT NULL THEN
      INSERT INTO procurement.order_request_transition_proof(request_id,root_transaction,snapshot)
      VALUES (OLD.id,txid_current(),jsonb_build_object('request_id',OLD.id,'ownership_id',owner_id,
        'number',OLD.number,'supplier',OLD.supplier,'supplier_id',OLD.supplier_id,'item',OLD.item,
        'qty',OLD.qty::text,'amount',OLD.amount::text,'due_date',OLD.due_date,'stage',OLD.stage));
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER record_order_request_transition BEFORE UPDATE OF stage ON procurement.purchase_request
FOR EACH ROW EXECUTE FUNCTION procurement.record_order_request_transition();

CREATE OR REPLACE FUNCTION procurement.guard_order_creation() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE c jsonb; d jsonb; b jsonb; item jsonb; actual_lines jsonb; expected jsonb;
        snapshot jsonb; proof_snapshot jsonb; position_count integer; index_number integer; id_key text; o procurement.purchase_order%ROWTYPE;
        owner_row procurement.purchase_ownership%ROWTYPE; request_owner procurement.purchase_ownership%ROWTYPE;
        request_row procurement.purchase_request%ROWTYPE; link_row procurement.order_request_link%ROWTYPE;
BEGIN
  PERFORM id FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  c := NEW.command::jsonb; d := c->'document'; b := c->'request_basis';
  IF jsonb_typeof(c) IS DISTINCT FROM 'object' OR jsonb_typeof(d) IS DISTINCT FROM 'object'
    OR c IS DISTINCT FROM jsonb_build_object('request_key',NEW.request_key,'document',d,
         'ownership_evidence',c->'ownership_evidence','request_basis',b)
    OR d IS DISTINCT FROM jsonb_build_object('supplier',d->'supplier','eta_date',d->'eta_date',
         'freight_byn',d->'freight_byn','lines',d->'lines')
    OR NEW.request_key !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    OR NEW.command_hash !~ '^[0-9a-f]{64}$'
    OR NEW.actor IS NULL OR length(NEW.actor) NOT BETWEEN 1 AND 200
    OR NOT procurement.order_command_text(c->'ownership_evidence',1000)
    OR NOT procurement.order_command_text(d->'supplier',255)
    OR jsonb_typeof(d->'lines') IS DISTINCT FROM 'array'
    OR jsonb_typeof(d->'freight_byn') IS DISTINCT FROM 'string'
    OR (d->>'freight_byn') !~ '^(0|[1-9][0-9]{0,11})\.[0-9]{2}$'
    OR jsonb_typeof(d->'eta_date') NOT IN ('null','string')
    OR (d->>'eta_date' IS NOT NULL AND (d->>'eta_date') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
    OR jsonb_typeof(b) NOT IN ('null','object') THEN
    RAISE EXCEPTION 'Invalid order creation command';
  END IF;
  IF jsonb_array_length(d->'lines') NOT BETWEEN 1 AND 200
    OR (d->>'eta_date' IS NOT NULL AND (d->>'eta_date')::date::text IS DISTINCT FROM d->>'eta_date') THEN
    RAISE EXCEPTION 'Invalid order creation line count or date';
  END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(d->'lines') LOOP
    IF item IS DISTINCT FROM jsonb_build_object('sku_code',item->'sku_code','qty',item->'qty',
        'goods_value_byn',item->'goods_value_byn','weight',item->'weight','volume',item->'volume')
      OR NOT procurement.order_command_text(item->'sku_code',64)
      OR jsonb_typeof(item->'qty') IS DISTINCT FROM 'string'
      OR (item->>'qty') !~ '^(0|[1-9][0-9]{0,11})\.[0-9]{2}$'
      OR jsonb_typeof(item->'goods_value_byn') IS DISTINCT FROM 'string'
      OR (item->>'goods_value_byn') !~ '^(0|[1-9][0-9]{0,11})\.[0-9]{2}$'
      OR jsonb_typeof(item->'weight') IS DISTINCT FROM 'string'
      OR (item->>'weight') !~ '^(0|[1-9][0-9]{0,10})\.[0-9]{3}$'
      OR jsonb_typeof(item->'volume') IS DISTINCT FROM 'string'
      OR (item->>'volume') !~ '^(0|[1-9][0-9]{0,9})\.[0-9]{4}$' THEN
      RAISE EXCEPTION 'Invalid order creation line';
    END IF;
    IF (item->>'qty')::numeric <= 0 THEN RAISE EXCEPTION 'Invalid order creation quantity'; END IF;
  END LOOP;
  SELECT count(DISTINCT value->>'sku_code') INTO position_count FROM jsonb_array_elements(d->'lines');
  IF position_count <> jsonb_array_length(d->'lines') THEN RAISE EXCEPTION 'Duplicate order creation SKU'; END IF;
  IF b <> 'null'::jsonb THEN
    IF b IS DISTINCT FROM jsonb_build_object('request_id',b->'request_id','expected_stage','approval',
         'expected_hash',b->'expected_hash','link_evidence',b->'link_evidence')
      OR jsonb_typeof(b->'request_id') IS DISTINCT FROM 'number'
      OR (NEW.command->'request_basis'->>'request_id') !~ '^[1-9][0-9]*$'
      OR jsonb_typeof(b->'expected_hash') IS DISTINCT FROM 'string'
      OR (b->>'expected_hash') !~ '^[0-9a-f]{64}$'
      OR NOT procurement.order_command_text(b->'link_evidence',1000) THEN
      RAISE EXCEPTION 'Invalid order creation request basis';
    END IF;
    IF (b->>'request_id')::numeric > 2147483647 THEN RAISE EXCEPTION 'Invalid order creation request identifier'; END IF;
  END IF;
  IF NEW.command_hash IS DISTINCT FROM encode(sha256(convert_to(procurement.order_command_json(c),'UTF8')),'hex') THEN
    RAISE EXCEPTION 'Order creation command hash mismatch';
  END IF;
  expected := jsonb_build_object('organization_id',NEW.organization_id,'request_key',NEW.request_key,
                                'principal',NEW.actor,'outcome',NEW.outcome);
  IF coalesce(NEW.result->>'organization_id','') !~ '^[1-9][0-9]*$' THEN
    RAISE EXCEPTION 'Invalid order creation result identifier';
  END IF;
  IF NEW.outcome = 'rejected' THEN
    -- Each HTTP command owns one root transaction; a rejection may not leave
    -- an order inserted earlier or later in that transaction (deferred recheck).
    IF NEW.order_id IS NOT NULL OR NEW.ownership_id IS NOT NULL OR NEW.request_id IS NOT NULL
      OR NEW.request_ownership_id IS NOT NULL OR NEW.link_id IS NOT NULL
      OR coalesce(NEW.result->>'code','') NOT IN
         ('request_basis_changed','request_basis_unavailable','request_already_linked','command_abandoned')
      OR (NEW.result->>'code' <> 'command_abandoned' AND b = 'null'::jsonb)
      OR EXISTS (SELECT 1 FROM procurement.order_insert_proof WHERE root_transaction=txid_current())
      OR NEW.result::jsonb IS DISTINCT FROM expected || jsonb_build_object('code',NEW.result->>'code','no_business_write',true) THEN
      RAISE EXCEPTION 'Invalid rejected order creation outcome';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.outcome IS DISTINCT FROM 'created' THEN RAISE EXCEPTION 'Invalid order creation outcome'; END IF;
  SELECT * INTO o FROM procurement.purchase_order WHERE id=NEW.order_id;
  SELECT * INTO owner_row FROM procurement.purchase_ownership WHERE id=NEW.ownership_id;
  IF o.id IS NULL OR owner_row.id IS NULL OR owner_row.kind IS DISTINCT FROM 'order'
    OR owner_row.source_id IS DISTINCT FROM o.id OR owner_row.organization_id IS DISTINCT FROM NEW.organization_id
    OR owner_row.actor IS DISTINCT FROM NEW.actor OR owner_row.evidence IS DISTINCT FROM c->>'ownership_evidence'
    OR o.status IS DISTINCT FROM 'draft' OR o.received_at IS NOT NULL OR o.supplier_id IS NOT NULL
    OR o.transport_method_code IS NOT NULL OR o.target_arrival_date IS NOT NULL
    OR o.supplier IS DISTINCT FROM d->>'supplier' OR o.freight_byn IS DISTINCT FROM (d->>'freight_byn')::numeric
    OR o.eta_date::text IS DISTINCT FROM d->>'eta_date'
    OR owner_row.snapshot::jsonb IS DISTINCT FROM jsonb_build_object('number',o.number,'supplier',o.supplier,
         'supplier_id',NULL,'status','draft','eta_date',d->'eta_date') THEN
    RAISE EXCEPTION 'Order creation initial ownership/header mismatch';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM procurement.order_insert_proof WHERE order_id=o.id AND root_transaction=txid_current()) THEN
    RAISE EXCEPTION 'Order creation package must originate in this transaction';
  END IF;
  SELECT jsonb_agg(jsonb_build_object('id',id,'sku_code',sku_code,'qty',qty::text,
    'goods_value_byn',goods_value_byn::text,'weight',weight::text,'volume',volume::text) ORDER BY id)
    INTO actual_lines FROM procurement.purchase_order_line WHERE order_id=o.id;
  IF (SELECT jsonb_agg(value - 'id' ORDER BY ordinal)
      FROM jsonb_array_elements(actual_lines) WITH ORDINALITY AS lines(value,ordinal)) IS DISTINCT FROM d->'lines' THEN
    RAISE EXCEPTION 'Order creation initial lines mismatch';
  END IF;
  snapshot := 'null'::jsonb;
  IF b = 'null'::jsonb THEN
    IF NEW.request_id IS NOT NULL OR NEW.request_ownership_id IS NOT NULL OR NEW.link_id IS NOT NULL THEN
      RAISE EXCEPTION 'Unexpected order creation request link';
    END IF;
  ELSE
    SELECT * INTO request_row FROM procurement.purchase_request WHERE id=NEW.request_id;
    SELECT * INTO request_owner FROM procurement.purchase_ownership WHERE id=NEW.request_ownership_id;
    SELECT * INTO link_row FROM procurement.order_request_link WHERE id=NEW.link_id;
    SELECT proof.snapshot INTO proof_snapshot FROM procurement.order_request_transition_proof proof
      WHERE proof.request_id=NEW.request_id AND proof.root_transaction=txid_current();
    snapshot := jsonb_build_object('request_id',request_row.id,'ownership_id',request_owner.id,
      'number',request_row.number,'supplier',request_row.supplier,'supplier_id',request_row.supplier_id,
      'item',request_row.item,'qty',request_row.qty::text,'amount',request_row.amount::text,
      'due_date',request_row.due_date,'stage','approval');
    IF request_row.id IS NULL OR request_owner.id IS NULL OR link_row.id IS NULL
      OR NEW.request_id IS DISTINCT FROM (b->>'request_id')::integer OR request_row.stage IS DISTINCT FROM 'po'
      OR request_owner.kind IS DISTINCT FROM 'request' OR request_owner.source_id IS DISTINCT FROM NEW.request_id
      OR request_owner.organization_id IS DISTINCT FROM NEW.organization_id
      OR link_row.organization_id IS DISTINCT FROM NEW.organization_id OR link_row.actor IS DISTINCT FROM NEW.actor
      OR link_row.order_ownership_id IS DISTINCT FROM NEW.ownership_id
      OR link_row.request_ownership_id IS DISTINCT FROM NEW.request_ownership_id
      OR link_row.evidence IS DISTINCT FROM b->>'link_evidence'
      OR (SELECT count(*) FROM procurement.order_request_link WHERE request_ownership_id=NEW.request_ownership_id) <> 1
      OR proof_snapshot IS DISTINCT FROM snapshot
      OR encode(sha256(convert_to(procurement.order_command_json(snapshot),'UTF8')),'hex') IS DISTINCT FROM b->>'expected_hash' THEN
      RAISE EXCEPTION 'Order creation approved request/link mismatch';
    END IF;
  END IF;
  expected := expected || jsonb_build_object('order_id',o.id,'ownership_id',NEW.ownership_id,'number',o.number,
    'status','draft','supplier',o.supplier,'eta_date',d->'eta_date','freight_byn',d->'freight_byn',
    'lines',actual_lines,'request_id',NEW.request_id,'request_ownership_id',NEW.request_ownership_id,
    'link_id',NEW.link_id,'request_snapshot',snapshot);
  IF NEW.result::jsonb IS DISTINCT FROM expected THEN RAISE EXCEPTION 'Order creation result mismatch'; END IF;
  FOREACH id_key IN ARRAY ARRAY['order_id','ownership_id','request_id','request_ownership_id','link_id'] LOOP
    IF NEW.result->>id_key IS NOT NULL AND (NEW.result->>id_key) !~ '^[1-9][0-9]*$' THEN
      RAISE EXCEPTION 'Invalid order creation result identifier';
    END IF;
  END LOOP;
  FOR index_number IN 0..jsonb_array_length(actual_lines)-1 LOOP
    IF coalesce(NEW.result->'lines'->index_number->>'id','') !~ '^[1-9][0-9]*$' THEN
      RAISE EXCEPTION 'Invalid order creation result line identifier';
    END IF;
  END LOOP;
  IF b <> 'null'::jsonb THEN
    FOREACH id_key IN ARRAY ARRAY['request_id','ownership_id','supplier_id'] LOOP
      IF NEW.result->'request_snapshot'->>id_key IS NOT NULL
        AND (NEW.result->'request_snapshot'->>id_key) !~ '^[1-9][0-9]*$' THEN
        RAISE EXCEPTION 'Invalid order creation snapshot identifier';
      END IF;
    END LOOP;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER guard_order_creation BEFORE INSERT ON procurement.purchase_order_creation
FOR EACH ROW EXECUTE FUNCTION procurement.guard_order_creation();
CREATE CONSTRAINT TRIGGER complete_order_creation AFTER INSERT ON procurement.purchase_order_creation
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION procurement.guard_order_creation();
CREATE TRIGGER immutable_order_creation BEFORE UPDATE OR DELETE ON procurement.purchase_order_creation
FOR EACH ROW EXECUTE FUNCTION procurement.reject_receipt_revision_mutation();
CREATE TRIGGER immutable_order_creation_truncate BEFORE TRUNCATE ON procurement.purchase_order_creation
FOR EACH STATEMENT EXECUTE FUNCTION procurement.reject_receipt_revision_mutation();


-- Financial close/reopen packages are single commands per organization/root transaction.
-- Calculation below uses ledger rows and immutable policy, never client-provided totals.
-- Envelope integrity is necessary but not sufficient: the independent package
-- and period-transition checks must also pass before public confirmation opens.
CREATE TRIGGER immutable_financial_close BEFORE UPDATE OR DELETE ON accounting.financial_close_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_financial_close BEFORE TRUNCATE ON accounting.financial_close_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER immutable_financial_reopen BEFORE UPDATE OR DELETE ON accounting.financial_reopen_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_financial_reopen BEFORE TRUNCATE ON accounting.financial_reopen_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER immutable_financial_reopen_item BEFORE UPDATE OR DELETE ON accounting.financial_reopen_item
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_financial_reopen_item BEFORE TRUNCATE ON accounting.financial_reopen_item
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE OR REPLACE FUNCTION accounting.financial_canonical(value jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE result text;
BEGIN
  IF jsonb_typeof(value)='object' THEN
    SELECT '{'||coalesce(string_agg(to_jsonb(key)::text||':'||accounting.financial_canonical(v),',' ORDER BY key COLLATE "C"),'')||'}'
      INTO result FROM jsonb_each(value) AS x(key,v);
  ELSIF jsonb_typeof(value)='array' THEN
    SELECT '['||coalesce(string_agg(accounting.financial_canonical(v),',' ORDER BY n),'')||']'
      INTO result FROM jsonb_array_elements(value) WITH ORDINALITY AS x(v,n);
  ELSE result:=value::text;
  END IF;
  RETURN result;
END $$;
CREATE OR REPLACE FUNCTION accounting.financial_sha(value jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT encode(sha256(convert_to(accounting.financial_canonical(value),'UTF8')),'hex')
$$;

CREATE TABLE accounting.financial_receipt_transaction (
  kind text NOT NULL CHECK (kind IN ('close','reopen')),
  receipt_id integer NOT NULL,
  root_transaction bigint NOT NULL,
  organization_id integer NOT NULL REFERENCES accounting.organization(id),
  PRIMARY KEY(kind,receipt_id),
  CONSTRAINT financial_receipt_one_command_per_root UNIQUE(organization_id,root_transaction)
);
CREATE OR REPLACE FUNCTION accounting.guard_financial_receipt_transaction() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF pg_trigger_depth()<>2 OR NEW.root_transaction<>txid_current()
     OR (NEW.kind='close' AND NOT EXISTS(SELECT 1 FROM accounting.financial_close_receipt WHERE id=NEW.receipt_id AND organization_id=NEW.organization_id))
     OR (NEW.kind='reopen' AND NOT EXISTS(SELECT 1 FROM accounting.financial_reopen_receipt WHERE id=NEW.receipt_id AND organization_id=NEW.organization_id)) THEN
    RAISE EXCEPTION 'Financial receipt proof must be generated by its insert trigger';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER generated_financial_receipt_transaction BEFORE INSERT ON accounting.financial_receipt_transaction
FOR EACH ROW EXECUTE FUNCTION accounting.guard_financial_receipt_transaction();
CREATE TRIGGER immutable_financial_receipt_transaction BEFORE UPDATE OR DELETE ON accounting.financial_receipt_transaction
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_financial_receipt_transaction BEFORE TRUNCATE ON accounting.financial_receipt_transaction
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE OR REPLACE FUNCTION accounting.record_financial_receipt_transaction() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO accounting.financial_receipt_transaction VALUES(
    CASE WHEN TG_TABLE_NAME='financial_close_receipt' THEN 'close' ELSE 'reopen' END,NEW.id,txid_current(),NEW.organization_id);
  RETURN NULL;
END $$;
CREATE TRIGGER record_financial_close_transaction AFTER INSERT ON accounting.financial_close_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.record_financial_receipt_transaction();
CREATE TRIGGER record_financial_reopen_transaction AFTER INSERT ON accounting.financial_reopen_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.record_financial_receipt_transaction();

CREATE OR REPLACE FUNCTION accounting.require_financial_entry_root(target_entry_id integer, org integer, actor_code text, op text)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  IF target_entry_id IS NOT NULL AND NOT EXISTS(
    SELECT 1 FROM accounting.entry e JOIN accounting.entry_transaction t ON t.entry_id=e.id
    WHERE e.id=target_entry_id AND e.organization_id=org AND e.actor=actor_code AND e.operation=op
      AND t.root_transaction=txid_current()) THEN
    RAISE EXCEPTION 'Financial entry must belong to the same organization and root transaction';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION accounting.guard_financial_reopen_item() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE receipt accounting.financial_reopen_receipt; original accounting.financial_close_receipt;
BEGIN
  SELECT * INTO receipt FROM accounting.financial_reopen_receipt WHERE id=NEW.reopen_receipt_id;
  SELECT * INTO original FROM accounting.financial_close_receipt WHERE id=NEW.close_receipt_id;
  IF receipt.id IS NULL OR original.id IS NULL OR receipt.organization_id<>original.organization_id
     OR original.month<receipt.from_month OR NOT EXISTS(
       SELECT 1 FROM accounting.financial_receipt_transaction WHERE kind='reopen'
       AND receipt_id=receipt.id AND root_transaction=txid_current()) THEN
    RAISE EXCEPTION 'Financial reopening item must belong to its original receipt transaction and organization';
  END IF;
  PERFORM accounting.require_financial_entry_root(NEW.monthly_entry_id,receipt.organization_id,receipt.actor,'period_reopen');
  PERFORM accounting.require_financial_entry_root(NEW.annual_entry_id,receipt.organization_id,receipt.actor,'period_reopen');
  RETURN NEW;
END $$;
CREATE TRIGGER valid_financial_reopen_item BEFORE INSERT ON accounting.financial_reopen_item
FOR EACH ROW EXECUTE FUNCTION accounting.guard_financial_reopen_item();

CREATE OR REPLACE FUNCTION accounting.guard_financial_envelope() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE kind text; month_code text; row_json jsonb;
BEGIN
  row_json:=to_jsonb(NEW);
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  IF EXISTS(SELECT 1 FROM accounting.financial_receipt_transaction t
    JOIN accounting.financial_close_receipt c ON t.kind='close' AND t.receipt_id=c.id
    WHERE t.root_transaction=txid_current() AND c.organization_id=NEW.organization_id)
    OR EXISTS(SELECT 1 FROM accounting.financial_receipt_transaction t
    JOIN accounting.financial_reopen_receipt r ON t.kind='reopen' AND t.receipt_id=r.id
    WHERE t.root_transaction=txid_current() AND r.organization_id=NEW.organization_id) THEN
    RAISE EXCEPTION 'Only one financial command per organization and root transaction is allowed';
  END IF;
  kind:=CASE WHEN TG_TABLE_NAME='financial_close_receipt' THEN 'close' ELSE 'reopen' END;
  month_code:=CASE WHEN kind='close' THEN row_json->>'month' ELSE row_json->>'from_month' END;
  IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
     OR month_code !~ '^[0-9]{4}-(0[1-9]|1[0-2])$'
     OR btrim(NEW.actor)='' OR jsonb_typeof(NEW.command::jsonb) IS DISTINCT FROM 'object'
     OR jsonb_typeof(NEW.snapshot::jsonb) IS DISTINCT FROM 'object'
     OR NEW.command::jsonb->>'request_key' IS DISTINCT FROM NEW.request_key
     OR NEW.command::jsonb->>(CASE WHEN kind='close' THEN 'month' ELSE 'from_month' END) IS DISTINCT FROM month_code
     OR NEW.command_digest IS DISTINCT FROM accounting.financial_sha(NEW.command::jsonb)
     OR NEW.digest IS DISTINCT FROM accounting.financial_sha(jsonb_build_object(
         'organization_id',NEW.organization_id,'request_key',NEW.request_key,'kind',kind,
         'command',NEW.command,'command_digest',NEW.command_digest,'snapshot',NEW.snapshot,'actor',NEW.actor)) THEN
    RAISE EXCEPTION 'Invalid financial receipt envelope';
  END IF;
  IF kind='close' THEN
    PERFORM accounting.require_financial_entry_root((row_json->>'monthly_entry_id')::integer,NEW.organization_id,NEW.actor,'period_close');
    PERFORM accounting.require_financial_entry_root((row_json->>'annual_entry_id')::integer,NEW.organization_id,NEW.actor,'period_close');
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER valid_financial_close_envelope BEFORE INSERT ON accounting.financial_close_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_financial_envelope();
CREATE TRIGGER valid_financial_reopen_envelope BEFORE INSERT ON accounting.financial_reopen_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_financial_envelope();

CREATE OR REPLACE FUNCTION accounting.financial_close_calculation(
  org integer, month_code text, excluded integer[], org_generation integer, period_generation integer
) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE first_day date; last_day date; initial accounting.policy; settings jsonb;
        policies jsonb; accounts jsonb; source_rows jsonb; codes text[]; monthly jsonb:='[]'; annual jsonb:='[]';
        b record; a jsonb; code text; amount text; source_side text; target_side text;
BEGIN
  IF month_code !~ '^[0-9]{4}-(0[1-9]|1[0-2])$' THEN RAISE EXCEPTION 'Invalid financial month'; END IF;
  first_day:=(month_code||'-01')::date;
  last_day:=(first_day+interval '1 month - 1 day')::date;
  SELECT * INTO initial FROM accounting.policy WHERE organization_id=org AND effective_from<=first_day
    ORDER BY effective_from DESC LIMIT 1;
  settings:=initial.financial_closing::jsonb;
  IF initial.id IS NULL OR settings IS NULL OR settings='null'::jsonb THEN
    RAISE EXCEPTION 'Financial closing policy must cover the whole month';
  END IF;
  IF EXISTS(SELECT 1 FROM accounting.policy WHERE organization_id=org AND effective_from<=last_day
     AND (effective_from>first_day OR id=initial.id)
     AND financial_closing::jsonb IS DISTINCT FROM settings) THEN
    RAISE EXCEPTION 'Changed financial closing policy';
  END IF;
  SELECT jsonb_agg(jsonb_build_object('id',id,'effective_from',effective_from::text,
    'normative_verified',normative_verified,'settings',financial_closing) ORDER BY effective_from DESC)
    INTO policies FROM accounting.policy WHERE organization_id=org AND effective_from<=last_day
      AND (effective_from>first_day OR id=initial.id);
  IF settings->>'opening_balance_treatment' NOT IN ('include','exclude')
     OR jsonb_typeof(settings->'monthly_accounts')<>'array'
     OR jsonb_array_length(settings->'monthly_accounts') NOT BETWEEN 1 AND 200
     OR (settings->>'year_end_month')::integer NOT BETWEEN 1 AND 12 THEN
    RAISE EXCEPTION 'Unsupported financial closing settings';
  END IF;
  SELECT array_agg(v) INTO codes FROM (
    SELECT jsonb_array_elements_text(settings->'monthly_accounts') v
    UNION ALL SELECT settings->>'result_account' UNION ALL SELECT settings->>'retained_earnings_account') x;
  IF cardinality(codes)<>(SELECT count(DISTINCT v) FROM unnest(codes) v)
     OR EXISTS(SELECT 1 FROM unnest(codes) v WHERE v IS NULL OR v !~ '^[0-9]+(\.[0-9]+)*$') THEN
    RAISE EXCEPTION 'Financial closing account roles must be distinct';
  END IF;
  SELECT jsonb_object_agg(x.code,to_jsonb(x)) INTO accounts FROM (
    SELECT DISTINCT ON (a.code) a.* FROM accounting.account a WHERE a.organization_id=org AND a.valid_from<=last_day
      AND a.code=ANY(codes) ORDER BY a.code,a.valid_from DESC,a.id DESC) x;
  FOREACH code IN ARRAY codes LOOP
    a:=accounts->code;
    IF a IS NULL OR (a->>'cash')::boolean OR (a->>'quantity_tracking')::boolean
       OR (a->>'currency_tracking')::boolean
       OR (code=settings->>'result_account' AND a->>'category'<>'income')
       OR (code=settings->>'retained_earnings_account' AND a->>'category'<>'equity')
       OR (settings->'monthly_accounts' ? code AND a->>'category' NOT IN ('income','expense')) THEN
      RAISE EXCEPTION 'Unsupported financial closing account %',code;
    END IF;
    IF code IN (settings->>'result_account',settings->>'retained_earnings_account') THEN
      IF ARRAY(SELECT jsonb_array_elements_text(a->'required_dimensions') ORDER BY 1)
         IS DISTINCT FROM ARRAY(SELECT jsonb_object_keys(settings->
             CASE WHEN code=settings->>'result_account' THEN 'result_dimensions' ELSE 'retained_dimensions' END) ORDER BY 1) THEN
        RAISE EXCEPTION 'Financial recipient analytics mismatch';
      END IF;
    END IF;
  END LOOP;
  IF EXISTS(SELECT 1 FROM accounting.financial_close_receipt c
      JOIN accounting.policy p ON p.id=(c.snapshot::jsonb->'preview'->>'policy_id')::integer
      WHERE c.organization_id=org AND c.month<month_code
      AND NOT EXISTS(SELECT 1 FROM accounting.financial_reopen_item r WHERE r.close_receipt_id=c.id)
      AND (p.financial_closing::jsonb-'reference') IS DISTINCT FROM (settings-'reference')) THEN
    RAISE EXCEPTION 'Financial policy transition requires reopening';
  END IF;
  IF EXISTS(SELECT 1 FROM accounting.entry e JOIN accounting.line l ON l.entry_id=e.id
      WHERE e.organization_id=org AND e.posting_date<=last_day AND l.account_code=ANY(codes)
      AND NOT(e.id=ANY(excluded)) AND NOT(e.opening AND settings->>'opening_balance_treatment'='exclude')
      AND (l.category IS DISTINCT FROM (accounts->l.account_code->>'category') OR l.cash
        OR l.currency<>'BYN' OR l.quantity IS NOT NULL OR NOT(l.dimensions::jsonb ?&
          ARRAY(SELECT jsonb_array_elements_text(accounts->l.account_code->'required_dimensions'))))) THEN
    RAISE EXCEPTION 'Historical closing analytics or account classification require reconciliation';
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('entry_id',e.id,'entry_digest',e.digest,'line_id',l.id,
      'account_id',l.account_id,'account_code',l.account_code,'category',l.category,'cash',l.cash,
      'side',l.side,'amount',l.amount::text,'dimensions',l.dimensions,'currency',l.currency,
      'quantity',l.quantity::text,'opening',e.opening,'posting_date',e.posting_date::text)
      ORDER BY e.id,l.id),'[]') INTO source_rows
    FROM accounting.entry e JOIN accounting.line l ON l.entry_id=e.id
    WHERE e.organization_id=org AND e.posting_date<=last_day AND l.account_code=ANY(codes)
      AND NOT(e.id=ANY(excluded));
  FOR b IN SELECT v->>'account_code' code,v->'dimensions' dims,
      sum((v->>'amount')::numeric*CASE WHEN v->>'side'='debit' THEN 1 ELSE -1 END) balance
      FROM jsonb_array_elements(source_rows) v
      WHERE settings->'monthly_accounts' ? (v->>'account_code')
        AND NOT((v->>'opening')::boolean AND settings->>'opening_balance_treatment'='exclude')
      GROUP BY v->>'account_code',v->'dimensions'
      ORDER BY (v->>'account_code') COLLATE "C",accounting.financial_canonical(v->'dimensions') COLLATE "C"
  LOOP
    IF b.balance=0 THEN CONTINUE; END IF;
    amount:=abs(b.balance)::numeric(20,2)::text;
    source_side:=CASE WHEN b.balance>0 THEN 'credit' ELSE 'debit' END;
    target_side:=CASE WHEN b.balance>0 THEN 'debit' ELSE 'credit' END;
    monthly:=monthly||jsonb_build_array(
      jsonb_build_object('account',b.code,'dimensions',b.dims,'side',source_side,'amount',amount),
      jsonb_build_object('account',settings->>'result_account','dimensions',settings->'result_dimensions','side',target_side,'amount',amount));
  END LOOP;
  IF extract(month FROM first_day)=(settings->>'year_end_month')::integer THEN
    FOR b IN SELECT dims,sum(balance) balance FROM (
        SELECT v->'dimensions' dims,(v->>'amount')::numeric*CASE WHEN v->>'side'='debit' THEN 1 ELSE -1 END balance
        FROM jsonb_array_elements(source_rows) v WHERE v->>'account_code'=settings->>'result_account'
          AND NOT((v->>'opening')::boolean AND settings->>'opening_balance_treatment'='exclude')
        UNION ALL SELECT v->'dimensions',(v->>'amount')::numeric*CASE WHEN v->>'side'='debit' THEN 1 ELSE -1 END
        FROM jsonb_array_elements(monthly) v WHERE v->>'account'=settings->>'result_account') x
      GROUP BY dims ORDER BY accounting.financial_canonical(dims) COLLATE "C"
    LOOP
      IF b.balance=0 THEN CONTINUE; END IF;
      amount:=abs(b.balance)::numeric(20,2)::text;
      annual:=annual||jsonb_build_array(
        jsonb_build_object('account',settings->>'result_account','dimensions',b.dims,
          'side',CASE WHEN b.balance>0 THEN 'credit' ELSE 'debit' END,'amount',amount),
        jsonb_build_object('account',settings->>'retained_earnings_account','dimensions',settings->'retained_dimensions',
          'side',CASE WHEN b.balance>0 THEN 'debit' ELSE 'credit' END,'amount',amount));
    END LOOP;
  END IF;
  SELECT jsonb_agg(jsonb_build_object('id',(v->>'id')::integer,'code',k,'category',v->>'category',
      'dimensions',v->'required_dimensions') ORDER BY k COLLATE "C") INTO accounts FROM jsonb_each(accounts) x(k,v);
  RETURN jsonb_build_object('organization_id',org,'month',month_code,'organization_generation',org_generation,
    'period_generation',period_generation,'policies',policies,'accounts',accounts,'source_lines',source_rows,
    'monthly_lines',monthly,'annual_lines',annual);
END $$;


-- Validate the complete close calculation at receipt insertion. Deferred period
-- transition and reopening-cascade certification are separate required guards.
CREATE OR REPLACE FUNCTION accounting.guard_financial_close_calculation() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE ids integer[]; transfer_count integer; org_generation integer; period_row accounting.period;
        basis jsonb; plan jsonb; phase text; planned jsonb; expected_body jsonb; actual_body jsonb;
        entry_row accounting.entry; target_id integer; last_day date;
BEGIN
  ids:=array_remove(ARRAY[NEW.monthly_entry_id,NEW.annual_entry_id],NULL);
  transfer_count:=cardinality(ids);
  SELECT generation INTO org_generation FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  SELECT * INTO period_row FROM accounting.period WHERE organization_id=NEW.organization_id AND month=NEW.month;
  IF period_row.id IS NULL OR NOT period_row.closed OR period_row.closed_generation IS DISTINCT FROM period_row.generation
     OR period_row.evidence::jsonb IS DISTINCT FROM NEW.command::jsonb->'evidence'
     OR NEW.command::jsonb->>'expected_generation' IS DISTINCT FROM (period_row.generation-transfer_count)::text
     OR NEW.snapshot::jsonb->>'closed_generation' IS DISTINCT FROM period_row.generation::text THEN
    RAISE EXCEPTION 'Financial closing period does not match the reviewed command';
  END IF;
  basis:=accounting.financial_close_calculation(NEW.organization_id,NEW.month,ids,
      org_generation-transfer_count,period_row.generation-transfer_count);
  plan:=NEW.snapshot::jsonb->'preview';
  IF plan->'basis' IS DISTINCT FROM basis OR plan->>'basis_digest' IS DISTINCT FROM accounting.financial_sha(basis)
     OR NEW.command::jsonb->>'expected_basis_digest' IS DISTINCT FROM accounting.financial_sha(basis)
     OR plan->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
     OR plan->>'month' IS DISTINCT FROM NEW.month
     OR plan->>'period_generation' IS DISTINCT FROM (period_row.generation-transfer_count)::text
     OR plan->>'policy_id' IS DISTINCT FROM basis->'policies'->0->>'id'
     OR EXISTS(SELECT 1 FROM jsonb_array_elements(basis->'policies') p WHERE p->>'normative_verified' IS DISTINCT FROM 'true') THEN
    RAISE EXCEPTION 'Financial closing basis differs from independent ledger calculation';
  END IF;
  last_day:=((NEW.month||'-01')::date+interval '1 month - 1 day')::date;
  FOREACH phase IN ARRAY ARRAY['monthly','annual'] LOOP
    target_id:=CASE WHEN phase='monthly' THEN NEW.monthly_entry_id ELSE NEW.annual_entry_id END;
    planned:=basis->(phase||'_lines');
    IF plan->(phase||'_lines') IS DISTINCT FROM planned
       OR NEW.snapshot::jsonb->(phase||'_entry_id') IS DISTINCT FROM coalesce(to_jsonb(target_id),'null'::jsonb)
       OR (jsonb_array_length(planned)>0) IS DISTINCT FROM (target_id IS NOT NULL) THEN
      RAISE EXCEPTION 'Financial closing transfer membership differs from calculation';
    END IF;
    IF target_id IS NULL THEN CONTINUE; END IF;
    IF EXISTS(SELECT 1 FROM accounting.line l WHERE l.entry_id=target_id AND NOT EXISTS(
      SELECT 1 FROM jsonb_array_elements(basis->'accounts') a
      WHERE a->>'code'=l.account_code AND (a->>'id')::integer=l.account_id)) THEN
      RAISE EXCEPTION 'Financial closing line must use the effective account version from its basis';
    END IF;
    SELECT * INTO entry_row FROM accounting.entry WHERE id=target_id;
    SELECT jsonb_agg(v||jsonb_build_object('currency','BYN','original_amount',NULL,'rate',NULL,
        'rate_scale',NULL,'rate_date',NULL,'rate_source',NULL,'quantity',NULL,'cash_activity',NULL) ORDER BY n)
      INTO planned FROM jsonb_array_elements(planned) WITH ORDINALITY x(v,n);
    expected_body:=jsonb_build_object('source','financial-close:'||NEW.request_key||':'||phase,'source_version',1,
        'operation','period_close','document_date',last_day,'operation_date',last_day,'posting_date',last_day,
        'policy_id',(plan->>'policy_id')::integer,'rule_version','financial-closing-v1:'||phase,
        'explanation','Financial closing '||NEW.month||': '||phase,'opening',false,'correction_of',NULL,'lines',planned);
    SELECT (to_jsonb(entry_row)-ARRAY['id','organization_id','digest','actor','created_at'])||jsonb_build_object('lines',
      jsonb_agg((to_jsonb(l)-ARRAY['id','entry_id','account_id','account_code','account_title','category','cash'])||
        jsonb_build_object('account',l.account_code,'amount',l.amount::text) ORDER BY l.id))
      INTO actual_body FROM accounting.line l WHERE l.entry_id=target_id;
    IF actual_body IS DISTINCT FROM expected_body OR entry_row.digest IS DISTINCT FROM accounting.financial_sha(expected_body) THEN
      RAISE EXCEPTION 'Financial closing posting differs from independent calculation';
    END IF;
  END LOOP;
  RETURN NEW;
END $$;
CREATE TRIGGER verify_financial_close_calculation BEFORE INSERT ON accounting.financial_close_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_financial_close_calculation();

CREATE OR REPLACE FUNCTION accounting.guard_finalized_close_lines() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS(SELECT 1 FROM accounting.financial_close_receipt
    WHERE monthly_entry_id=NEW.entry_id OR annual_entry_id=NEW.entry_id) THEN
    RAISE EXCEPTION 'Financial closing lines cannot be appended after receipt validation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER finalized_financial_close_lines BEFORE INSERT ON accounting.line
FOR EACH ROW EXECUTE FUNCTION accounting.guard_finalized_close_lines();


CREATE OR REPLACE FUNCTION accounting.financial_posting_body(target_entry_id integer) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT (to_jsonb(e)-ARRAY['id','organization_id','digest','actor','created_at'])||jsonb_build_object('lines',
    (SELECT jsonb_agg((to_jsonb(l)-ARRAY['id','entry_id','account_id','account_code','account_title','category','cash'])||
      jsonb_build_object('account',l.account_code,'amount',l.amount::text) ORDER BY l.id)
     FROM accounting.line l WHERE l.entry_id=e.id)) FROM accounting.entry e WHERE e.id=target_entry_id
$$;
CREATE OR REPLACE FUNCTION accounting.validate_financial_reversal_bodies(target_receipt_id integer) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE receipt accounting.financial_reopen_receipt; items jsonb; item accounting.financial_reopen_item; original accounting.financial_close_receipt;
        phase text; source_id integer; target_id integer; expected jsonb; reversed_lines jsonb;
BEGIN
  SELECT * INTO STRICT receipt FROM accounting.financial_reopen_receipt WHERE id=target_receipt_id;
  IF EXISTS(SELECT 1 FROM accounting.financial_close_receipt c
    WHERE c.organization_id=receipt.organization_id AND c.month>=receipt.from_month
      AND NOT EXISTS(SELECT 1 FROM accounting.financial_reopen_item i WHERE i.close_receipt_id=c.id)) THEN
    RAISE EXCEPTION 'Financial reopening must include every active close from the selected month';
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('close_receipt_id',i.close_receipt_id,
    'monthly_entry_id',i.monthly_entry_id,'annual_entry_id',i.annual_entry_id) ORDER BY i.close_receipt_id),'[]'::jsonb)
    INTO items FROM accounting.financial_reopen_item i WHERE i.reopen_receipt_id=receipt.id;
  IF items IS DISTINCT FROM receipt.snapshot::jsonb->'items' THEN
    RAISE EXCEPTION 'Financial reopening item list differs from its receipt';
  END IF;
  FOR item IN SELECT * FROM accounting.financial_reopen_item WHERE reopen_receipt_id=receipt.id LOOP
    SELECT * INTO original FROM accounting.financial_close_receipt WHERE id=item.close_receipt_id;
    FOREACH phase IN ARRAY ARRAY['monthly','annual'] LOOP
      source_id:=CASE WHEN phase='monthly' THEN original.monthly_entry_id ELSE original.annual_entry_id END;
      target_id:=CASE WHEN phase='monthly' THEN item.monthly_entry_id ELSE item.annual_entry_id END;
      IF (source_id IS NULL) IS DISTINCT FROM (target_id IS NULL) THEN
        RAISE EXCEPTION 'Financial reopening has an incomplete reversal';
      END IF;
      IF source_id IS NULL THEN CONTINUE; END IF;
      expected:=accounting.financial_posting_body(source_id);
      SELECT jsonb_agg(v||jsonb_build_object('side',CASE WHEN v->>'side'='debit' THEN 'credit' ELSE 'debit' END) ORDER BY n)
        INTO reversed_lines FROM jsonb_array_elements(expected->'lines') WITH ORDINALITY x(v,n);
      expected:=expected||jsonb_build_object('source','financial-reopen:'||receipt.request_key||':'||source_id::text,
        'operation','period_reopen','correction_of',source_id,'rule_version','financial-reopening-v1',
        'explanation',receipt.command::jsonb->>'reason','lines',reversed_lines);
      IF expected IS DISTINCT FROM accounting.financial_posting_body(target_id)
         OR NOT EXISTS(SELECT 1 FROM accounting.entry WHERE id=target_id AND digest=accounting.financial_sha(expected))
         OR EXISTS(SELECT 1 FROM
           (SELECT account_id,row_number() OVER (ORDER BY id) n FROM accounting.line WHERE entry_id=source_id) a
           FULL JOIN (SELECT account_id,row_number() OVER (ORDER BY id) n FROM accounting.line WHERE entry_id=target_id) b USING(n)
           WHERE a.account_id IS DISTINCT FROM b.account_id) THEN
        RAISE EXCEPTION 'Financial reopening must exactly reverse the original posting and account versions';
      END IF;
    END LOOP;
  END LOOP;
  RETURN;
END $$;
CREATE OR REPLACE FUNCTION accounting.guard_financial_reversal_bodies() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer;
BEGIN
  IF TG_TABLE_NAME='financial_reopen_receipt' THEN
    PERFORM accounting.validate_financial_reversal_bodies(NEW.id);
  ELSIF TG_TABLE_NAME='financial_reopen_item' THEN
    PERFORM accounting.validate_financial_reversal_bodies(NEW.reopen_receipt_id);
  ELSE
    FOR target IN SELECT DISTINCT reopen_receipt_id FROM accounting.financial_reopen_item
      WHERE monthly_entry_id=NEW.entry_id OR annual_entry_id=NEW.entry_id LOOP
      PERFORM accounting.validate_financial_reversal_bodies(target);
    END LOOP;
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER verify_financial_reversal_bodies AFTER INSERT ON accounting.financial_reopen_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.guard_financial_reversal_bodies();

CREATE CONSTRAINT TRIGGER verify_financial_reversal_item AFTER INSERT ON accounting.financial_reopen_item
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.guard_financial_reversal_bodies();
CREATE CONSTRAINT TRIGGER verify_financial_reversal_line AFTER INSERT ON accounting.line
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.guard_financial_reversal_bodies();


-- Unallocated proposal guard for the reviewed currency-revaluation package.
-- Production registration still requires the operator-assigned migration.
CREATE OR REPLACE FUNCTION accounting.reject_fx_revaluation_history_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'FX revaluation receipts are immutable';
END $$;

CREATE TRIGGER immutable_fx_revaluation_receipt
BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.fx_revaluation_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_fx_revaluation_history_mutation();

CREATE OR REPLACE FUNCTION accounting.guard_fx_revaluation_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; p accounting.period%ROWTYPE;
BEGIN
  IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
     OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
     OR NEW.command->>'policy_id' IS NULL
     OR NEW.command->>'expected_generation' IS NULL
     OR NEW.snapshot->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
     OR NEW.snapshot->>'month' IS DISTINCT FROM NEW.month
     OR NEW.snapshot->>'source_version' IS DISTINCT FROM NEW.source_version::text
     OR NEW.command_digest IS DISTINCT FROM accounting.financial_sha(NEW.command::jsonb)
     OR NEW.digest IS DISTINCT FROM accounting.financial_sha(jsonb_build_object(
          'organization_id',NEW.organization_id,'request_key',NEW.request_key,
          'kind','fx_revaluation','month',NEW.month,'source_version',NEW.source_version,'command',NEW.command,
          'command_digest',NEW.command_digest,'snapshot',NEW.snapshot,'entry_id',NEW.entry_id,
          'actor',NEW.actor)) THEN
    RAISE EXCEPTION 'FX revaluation receipt identity or digest is invalid';
  END IF;
  SELECT * INTO p FROM accounting.period WHERE organization_id=NEW.organization_id AND month=NEW.month;
  IF p.closed THEN RAISE EXCEPTION 'FX revaluation cannot be recorded in a closed period'; END IF;
  IF NEW.entry_id IS NULL THEN RETURN NEW; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  IF NOT FOUND OR e.organization_id IS DISTINCT FROM NEW.organization_id
     OR e.source IS DISTINCT FROM 'accounting:fx-revaluation:'||NEW.organization_id||':'||NEW.month
     OR e.source_version IS DISTINCT FROM NEW.source_version
     OR e.operation IS DISTINCT FROM 'fx_revaluation'
     OR e.actor IS DISTINCT FROM NEW.actor
     OR e.posting_date IS DISTINCT FROM (NEW.command->>'posting_date')::date
     OR e.policy_id IS DISTINCT FROM (NEW.command->>'policy_id')::integer
     OR NEW.snapshot->>'digest' IS DISTINCT FROM e.digest THEN
    RAISE EXCEPTION 'FX revaluation receipt does not match its ledger entry';
  END IF;
  RETURN NEW;
END $$;

CREATE CONSTRAINT TRIGGER guard_fx_revaluation_receipt
AFTER INSERT ON accounting.fx_revaluation_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.guard_fx_revaluation_receipt();


-- Opening-import evidence is immutable and must point to the exact opening entries.
CREATE OR REPLACE FUNCTION accounting.guard_opening_import_receipt_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE invalid_entries integer;
BEGIN
  IF NEW.cutover_date <> date_trunc('month', NEW.cutover_date)::date
     OR NEW.request_key !~ '^[0-9a-fA-F-]{36}$'
     OR NEW.source_digest !~ '^[0-9a-f]{64}$'
     OR NEW.command_digest !~ '^[0-9a-f]{64}$'
     OR NEW.digest !~ '^[0-9a-f]{64}$'
     OR NEW.entry_count <= 0
     OR NEW.line_count < NEW.entry_count
     OR NEW.debit_total < 0
     OR NEW.credit_total < 0
     OR NEW.debit_total <> NEW.credit_total
     OR jsonb_typeof(NEW.entry_ids::jsonb) <> 'array'
     OR jsonb_array_length(NEW.entry_ids::jsonb) <> NEW.entry_count
     OR jsonb_typeof(NEW.snapshot::jsonb) <> 'object'
     OR length(btrim(NEW.evidence)) < 10 THEN
    RAISE EXCEPTION 'Opening import receipt has invalid control metadata';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements(NEW.entry_ids::jsonb) item
    WHERE jsonb_typeof(item) <> 'number'
  ) THEN
    RAISE EXCEPTION 'Opening import receipt entry ids must be numeric';
  END IF;
  SELECT count(*) INTO invalid_entries
  FROM jsonb_array_elements_text(NEW.entry_ids::jsonb) ids(value)
  LEFT JOIN accounting.entry e ON e.id = ids.value::bigint
  WHERE e.id IS NULL
     OR e.organization_id <> NEW.organization_id
     OR NOT e.opening
     OR e.posting_date <> NEW.cutover_date;
  IF invalid_entries <> 0 THEN
    RAISE EXCEPTION 'Opening import receipt must reference same-organization opening entries';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION accounting.guard_opening_import_receipt_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Opening import receipts are immutable';
END;
$$;

DROP TRIGGER IF EXISTS opening_import_receipt_insert_guard ON accounting.opening_import_receipt;
CREATE CONSTRAINT TRIGGER opening_import_receipt_insert_guard
AFTER INSERT ON accounting.opening_import_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.guard_opening_import_receipt_insert();

DROP TRIGGER IF EXISTS opening_import_receipt_update_guard ON accounting.opening_import_receipt;
CREATE TRIGGER opening_import_receipt_update_guard
BEFORE UPDATE OR DELETE ON accounting.opening_import_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_opening_import_receipt_immutable();


-- An OSV reconciliation receipt is accountant evidence only.  It never
-- creates ledger movements and it is admitted only for two closed, complete,
-- numerically equal normalized reports.
CREATE OR REPLACE FUNCTION accounting.guard_reconciliation_receipt_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.request_key !~ '^[0-9a-fA-F-]{36}$'
     OR NEW.period_from > NEW.period_to
     OR NEW.left_digest !~ '^[0-9a-f]{64}$'
     OR NEW.right_digest !~ '^[0-9a-f]{64}$'
     OR NEW.command_digest !~ '^[0-9a-f]{64}$'
     OR NEW.digest !~ '^[0-9a-f]{64}$'
     OR NEW.left_status <> 'closed_periods'
     OR NEW.right_status <> 'closed_periods'
     OR NEW.left_pending_documents <> 0
     OR NEW.right_pending_documents <> 0
     OR NEW.left_rows < 0
     OR NEW.right_rows < 0
     OR NEW.difference_count <> 0
     OR jsonb_typeof(NEW.snapshot::jsonb) <> 'object'
     OR length(btrim(NEW.evidence)) < 10
     OR length(btrim(NEW.actor)) < 1 THEN
    RAISE EXCEPTION 'Reconciliation receipt is not an eligible closed OSV acceptance';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS reconciliation_receipt_insert_guard ON accounting.reconciliation_receipt;
CREATE CONSTRAINT TRIGGER reconciliation_receipt_insert_guard
AFTER INSERT ON accounting.reconciliation_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.guard_reconciliation_receipt_insert();

CREATE OR REPLACE FUNCTION accounting.guard_reconciliation_receipt_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Reconciliation receipts are immutable';
END;
$$;

DROP TRIGGER IF EXISTS reconciliation_receipt_update_guard ON accounting.reconciliation_receipt;
CREATE TRIGGER reconciliation_receipt_update_guard
BEFORE UPDATE OR DELETE ON accounting.reconciliation_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_reconciliation_receipt_immutable();

DROP TRIGGER IF EXISTS reconciliation_receipt_truncate_guard ON accounting.reconciliation_receipt;
CREATE TRIGGER reconciliation_receipt_truncate_guard
BEFORE TRUNCATE ON accounting.reconciliation_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.guard_reconciliation_receipt_immutable();


-- Draft-only expense history. Approval and command/effect provenance require
-- separate guards; immutability alone is not proof of an authorized operation.
CREATE TRIGGER immutable_expense_budget BEFORE UPDATE OR DELETE ON accounting.expense_budget
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_expense_budget BEFORE TRUNCATE ON accounting.expense_budget
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER immutable_expense_budget_line BEFORE UPDATE OR DELETE ON accounting.expense_budget_line
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_expense_budget_line BEFORE TRUNCATE ON accounting.expense_budget_line
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER immutable_expense_command_receipt BEFORE UPDATE OR DELETE ON accounting.expense_command_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_expense_command_receipt BEFORE TRUNCATE ON accounting.expense_command_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER immutable_expense_budget_approval BEFORE UPDATE OR DELETE ON accounting.expense_budget_approval
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_expense_budget_approval BEFORE TRUNCATE ON accounting.expense_budget_approval
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE OR REPLACE FUNCTION accounting.guard_expense_months() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE cell jsonb;
BEGIN
  IF jsonb_typeof(NEW.months::jsonb) IS DISTINCT FROM 'array' OR jsonb_array_length(NEW.months::jsonb)<>12 THEN
    RAISE EXCEPTION 'Expense budget requires twelve monthly cells';
  END IF;
  FOR cell IN SELECT value FROM jsonb_array_elements(NEW.months::jsonb) LOOP
    IF cell='null'::jsonb THEN CONTINUE; END IF;
    IF jsonb_typeof(cell) IS DISTINCT FROM 'string' OR (cell#>>'{}') !~ '^(0|[1-9][0-9]{0,15})\.[0-9]{2}$' THEN
      RAISE EXCEPTION 'Expense month must be null or an exact nonnegative decimal string';
    END IF;
  END LOOP;
  RETURN NEW;
END $$;
CREATE TRIGGER valid_expense_months BEFORE INSERT ON accounting.expense_budget_line
FOR EACH ROW EXECUTE FUNCTION accounting.guard_expense_months();

-- Match the ledger's root-transaction proof: xmin cannot identify a parent
-- inserted inside a savepoint. A committed version must never gain new lines.
CREATE TABLE accounting.expense_budget_transaction (
  budget_id integer PRIMARY KEY REFERENCES accounting.expense_budget(id),
  root_transaction bigint NOT NULL
);
CREATE OR REPLACE FUNCTION accounting.guard_expense_budget_transaction() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF pg_trigger_depth() <> 2 OR NEW.root_transaction <> txid_current()
     OR NOT EXISTS (SELECT 1 FROM accounting.expense_budget WHERE id=NEW.budget_id) THEN
    RAISE EXCEPTION 'Expense budget transaction proof must be generated by its insert trigger';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER generated_expense_budget_transaction BEFORE INSERT ON accounting.expense_budget_transaction
FOR EACH ROW EXECUTE FUNCTION accounting.guard_expense_budget_transaction();
CREATE TRIGGER immutable_expense_budget_transaction BEFORE UPDATE OR DELETE ON accounting.expense_budget_transaction
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_expense_budget_transaction BEFORE TRUNCATE ON accounting.expense_budget_transaction
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE OR REPLACE FUNCTION accounting.record_expense_budget_transaction() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO accounting.expense_budget_transaction(budget_id,root_transaction)
    VALUES(NEW.id,txid_current());
  RETURN NULL;
END $$;
CREATE TRIGGER record_expense_budget_transaction AFTER INSERT ON accounting.expense_budget
FOR EACH ROW EXECUTE FUNCTION accounting.record_expense_budget_transaction();
CREATE OR REPLACE FUNCTION accounting.guard_expense_budget_line_birth() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM accounting.expense_budget_transaction
                 WHERE budget_id=NEW.budget_id AND root_transaction=txid_current()) THEN
    RAISE EXCEPTION 'Cannot append to a committed expense budget version';
  END IF;
  IF EXISTS (SELECT 1 FROM accounting.expense_command_receipt
             WHERE organization_id=NEW.organization_id AND kind='budget'
               AND receipt::jsonb#>'{result,id}'=to_jsonb(NEW.budget_id)) THEN
    RAISE EXCEPTION 'Expense budget is sealed by its command receipt';
  END IF;
  RETURN NEW;
END $$;
-- Validate cells first, including on rejected late appends.
CREATE TRIGGER z_expense_budget_line_birth BEFORE INSERT ON accounting.expense_budget_line
FOR EACH ROW EXECUTE FUNCTION accounting.guard_expense_budget_line_birth();

CREATE UNIQUE INDEX expense_one_receipt_per_budget
ON accounting.expense_command_receipt (organization_id, (receipt::jsonb#>>'{result,id}'))
WHERE kind='budget';

CREATE UNIQUE INDEX expense_one_approval_per_budget
ON accounting.expense_budget_approval (organization_id, budget_id);

CREATE OR REPLACE FUNCTION accounting.expense_budget_payload(budget_key integer) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT (to_jsonb(b)-'organization_id'-'created_at') || jsonb_build_object('lines',
    COALESCE((SELECT jsonb_agg(jsonb_build_object('article_id',l.article_id,
      'months',l.months,'article_snapshot',l.article_snapshot) ORDER BY l.article_id)
      FROM accounting.expense_budget_line l WHERE l.budget_id=b.id),'[]'::jsonb))
  FROM accounting.expense_budget b WHERE b.id=budget_key
$$;

CREATE OR REPLACE FUNCTION accounting.guard_expense_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE r jsonb:=NEW.receipt::jsonb; b accounting.expense_budget; a accounting.expense_budget_approval;
        expected jsonb; lines jsonb;
BEGIN
  IF NEW.kind NOT IN ('catalog','budget','budget_approval') OR jsonb_typeof(r) IS DISTINCT FROM 'object'
     OR r->'organization_id' IS DISTINCT FROM to_jsonb(NEW.organization_id)
     OR r->>'principal' IS DISTINCT FROM NEW.actor
     OR r->>'kind' IS DISTINCT FROM NEW.kind
     OR r->>'request_key' IS DISTINCT FROM NEW.request_key
     OR r#>>'{command,request_key}' IS DISTINCT FROM NEW.request_key
     OR r->>'command_hash' IS DISTINCT FROM NEW.command_hash
     OR accounting.financial_sha(r->'command') IS DISTINCT FROM NEW.command_hash
     OR accounting.financial_sha(r->'result') IS DISTINCT FROM r->>'result_digest'
     OR accounting.financial_sha(r-'receipt_digest') IS DISTINCT FROM r->>'receipt_digest' THEN
    RAISE EXCEPTION 'Expense receipt integrity mismatch';
  END IF;
  IF NEW.kind='budget' THEN
    SELECT * INTO b FROM accounting.expense_budget
      WHERE organization_id=NEW.organization_id AND to_jsonb(id)=r#>'{result,id}';
    IF b.id IS NULL OR NOT EXISTS (SELECT 1 FROM accounting.expense_budget_transaction
        WHERE budget_id=b.id AND root_transaction=txid_current()) THEN
      RAISE EXCEPTION 'Expense receipt requires a budget born in this transaction';
    END IF;
    expected:=accounting.expense_budget_payload(b.id);
    SELECT COALESCE(jsonb_agg(jsonb_build_object('article_id',l.article_id,'months',l.months)
      ORDER BY l.article_id),'[]'::jsonb) INTO lines
      FROM accounting.expense_budget_line l WHERE l.budget_id=b.id;
    IF jsonb_array_length(lines) NOT BETWEEN 1 AND 300 THEN
      RAISE EXCEPTION 'Expense budget requires between 1 and 300 lines';
    END IF;
    IF r->'result' IS DISTINCT FROM expected OR NEW.actor IS DISTINCT FROM b.actor
       OR r#>'{command,lines}' IS DISTINCT FROM lines
       OR r#>'{command,year}' IS DISTINCT FROM to_jsonb(b.year)
       OR r#>'{command,currency}' IS DISTINCT FROM to_jsonb(b.currency)
       OR r#>'{command,basis}' IS DISTINCT FROM to_jsonb(b.basis)
       OR r#>'{command,evidence}' IS DISTINCT FROM to_jsonb(b.evidence)
       OR r#>'{command,expected_revision}' IS DISTINCT FROM to_jsonb(b.revision-1)
       OR r#>'{command,expected_catalog_revision}' IS DISTINCT FROM to_jsonb(b.catalog_revision) THEN
      RAISE EXCEPTION 'Expense receipt does not match stored budget and command';
    END IF;
  END IF;
  IF NEW.kind='budget_approval' THEN
    IF jsonb_typeof(r#>'{result,budget_id}') IS DISTINCT FROM 'number'
       OR jsonb_typeof(r#>'{result,budget_revision}') IS DISTINCT FROM 'number'
       OR jsonb_typeof(r#>'{result,budget}') IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'Expense approval receipt has an invalid result';
    END IF;
    SELECT * INTO a FROM accounting.expense_budget_approval
      WHERE organization_id=NEW.organization_id
        AND budget_id=(r#>>'{result,budget_id}')::integer;
    IF a.id IS NULL THEN
      RAISE EXCEPTION 'Expense approval receipt requires its approval row';
    END IF;
    expected:=accounting.expense_budget_payload(a.budget_id);
    IF r#>'{result,budget}' IS DISTINCT FROM expected
       OR r#>>'{result,budget_revision}' IS DISTINCT FROM a.budget_revision::text
       OR r#>>'{result,approved_by}' IS DISTINCT FROM a.actor
       OR r#>>'{result,evidence}' IS DISTINCT FROM a.evidence
       OR r#>>'{result,approved_at}' IS DISTINCT FROM to_char(a.approved_at, 'YYYY-MM-DD"T"HH24:MI:SS')
       OR r#>>'{result,approval_digest}' IS DISTINCT FROM a.approval_digest
       OR accounting.financial_sha(r->'result'-'approval_digest') IS DISTINCT FROM a.approval_digest
       OR NEW.actor IS DISTINCT FROM a.actor
       OR r#>>'{command,budget_id}' IS DISTINCT FROM a.budget_id::text
       OR r#>>'{command,expected_revision}' IS DISTINCT FROM a.budget_revision::text
       OR r#>>'{command,evidence}' IS DISTINCT FROM a.evidence
       OR a.request_key IS DISTINCT FROM NEW.request_key THEN
      RAISE EXCEPTION 'Expense approval receipt does not match stored approval';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER valid_expense_receipt BEFORE INSERT ON accounting.expense_command_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_expense_receipt();

CREATE OR REPLACE FUNCTION accounting.require_expense_budget_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM accounting.expense_command_receipt
      WHERE organization_id=NEW.organization_id AND kind='budget'
        AND receipt::jsonb#>'{result,id}'=to_jsonb(NEW.id)) THEN
    RAISE EXCEPTION 'Expense budget requires its command receipt';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER expense_budget_has_receipt AFTER INSERT ON accounting.expense_budget
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.require_expense_budget_receipt();

CREATE OR REPLACE FUNCTION accounting.require_expense_approval_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM accounting.expense_command_receipt
      WHERE organization_id=NEW.organization_id AND kind='budget_approval'
        AND request_key=NEW.request_key
        AND receipt::jsonb#>'{result,budget_id}'=to_jsonb(NEW.budget_id)) THEN
    RAISE EXCEPTION 'Expense budget approval requires its command receipt';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER expense_approval_has_receipt AFTER INSERT ON accounting.expense_budget_approval
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.require_expense_approval_receipt();


-- Receipt identity and line birth/deletion evidence. Header/status/plan effects
-- and complete command attribution require additional independent guards.
CREATE TABLE procurement.order_line_edit_proof (
  root_transaction bigint NOT NULL,
  line_id integer NOT NULL,
  order_id integer NOT NULL,
  action text NOT NULL CHECK(action IN ('add_line','delete_line')),
  snapshot jsonb NOT NULL,
  PRIMARY KEY(root_transaction,line_id,action)
);
CREATE OR REPLACE FUNCTION procurement.guard_line_edit_proof() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF pg_trigger_depth()<>2 OR NEW.root_transaction<>txid_current() THEN
    RAISE EXCEPTION 'Line edit proof must be generated by a line trigger';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER generated_line_edit_proof BEFORE INSERT ON procurement.order_line_edit_proof
FOR EACH ROW EXECUTE FUNCTION procurement.guard_line_edit_proof();
CREATE TRIGGER immutable_line_edit_proof BEFORE UPDATE OR DELETE ON procurement.order_line_edit_proof
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_line_edit_proof BEFORE TRUNCATE ON procurement.order_line_edit_proof
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE OR REPLACE FUNCTION procurement.record_line_edit() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE row_value procurement.purchase_order_line;
BEGIN
  IF TG_OP='INSERT' THEN row_value:=NEW; ELSE row_value:=OLD; END IF;
  INSERT INTO procurement.order_line_edit_proof(root_transaction,line_id,order_id,action,snapshot)
  VALUES(txid_current(),row_value.id,row_value.order_id,
    CASE WHEN TG_OP='INSERT' THEN 'add_line' ELSE 'delete_line' END,
    jsonb_build_object('id',row_value.id,'sku_code',row_value.sku_code,
      'qty',row_value.qty::text,'goods_value_byn',row_value.goods_value_byn::text,
      'weight',row_value.weight::text,'volume',row_value.volume::text));
  RETURN NULL;
END $$;
CREATE TRIGGER record_line_edit AFTER INSERT OR DELETE ON procurement.purchase_order_line
FOR EACH ROW EXECUTE FUNCTION procurement.record_line_edit();

CREATE UNIQUE INDEX one_edit_receipt_per_line_action ON procurement.purchase_order_edit_command
  (action,(result::jsonb#>>'{effect,line,id}'))
  WHERE outcome='applied' AND action IN ('add_line','delete_line');
CREATE TRIGGER immutable_order_edit_command BEFORE UPDATE OR DELETE
ON procurement.purchase_order_edit_command FOR EACH ROW
EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_order_edit_command BEFORE TRUNCATE
ON procurement.purchase_order_edit_command FOR EACH STATEMENT
EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE OR REPLACE FUNCTION procurement.guard_order_edit_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE c jsonb:=NEW.command::jsonb; r jsonb:=NEW.result::jsonb; common jsonb; actual_line jsonb;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
     OR length(btrim(NEW.actor))=0 OR jsonb_typeof(c) IS DISTINCT FROM 'object'
     OR jsonb_typeof(r) IS DISTINCT FROM 'object'
     OR c->'version' IS DISTINCT FROM '1'::jsonb
     OR c->>'request_key' IS DISTINCT FROM NEW.request_key
     OR c->'order_id' IS DISTINCT FROM to_jsonb(NEW.target_order_id)
     OR c->>'action' IS DISTINCT FROM NEW.action
     OR jsonb_typeof(c->'payload') IS DISTINCT FROM 'object'
     OR encode(sha256(convert_to(procurement.order_command_json(c),'UTF8')),'hex')
        IS DISTINCT FROM NEW.command_hash THEN
    RAISE EXCEPTION 'Order edit command identity mismatch';
  END IF;
  common:=jsonb_build_object('version',1,'organization_id',NEW.organization_id,
    'principal',NEW.actor,'request_key',NEW.request_key,'command_hash',NEW.command_hash,
    'order_id',NEW.target_order_id,'action',NEW.action,'outcome',NEW.outcome);
  IF NEW.outcome='rejected' THEN
    IF NEW.ownership_id IS NOT NULL OR r->>'code' NOT IN
      ('command_abandoned','source_unavailable','order_not_editable','line_unavailable',
       'transition_not_allowed','transport_method_unavailable')
       OR r->>'code' IS NULL
       OR r IS DISTINCT FROM common || jsonb_build_object('code',r->>'code','no_business_write',true) THEN
      RAISE EXCEPTION 'Order edit rejected receipt mismatch';
    END IF;
  ELSE
    IF NOT EXISTS (SELECT 1 FROM procurement.purchase_ownership
      WHERE id=NEW.ownership_id AND organization_id=NEW.organization_id
        AND kind='order' AND source_id=NEW.target_order_id)
       OR jsonb_typeof(r->'effect') IS DISTINCT FROM 'object'
       OR r IS DISTINCT FROM common || jsonb_build_object('ownership_id',NEW.ownership_id,'effect',r->'effect') THEN
      RAISE EXCEPTION 'Order edit applied receipt ownership mismatch';
    END IF;
    IF NEW.action IN ('add_line','delete_line') THEN
      SELECT snapshot INTO actual_line FROM procurement.order_line_edit_proof
        WHERE root_transaction=txid_current() AND order_id=NEW.target_order_id
          AND action=NEW.action AND to_jsonb(line_id)=r#>'{effect,line,id}';
      IF actual_line IS NULL OR r->'effect' IS DISTINCT FROM jsonb_build_object('line',actual_line)
         OR (NEW.action='add_line' AND c->'payload' IS DISTINCT FROM actual_line-'id')
         OR (NEW.action='delete_line' AND c->'payload' IS DISTINCT FROM
           jsonb_build_object('line_id',actual_line->'id')) THEN
        RAISE EXCEPTION 'Order edit receipt lacks matching line mutation proof';
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER valid_order_edit_receipt BEFORE INSERT ON procurement.purchase_order_edit_command
FOR EACH ROW EXECUTE FUNCTION procurement.guard_order_edit_receipt();


-- Semantic projection for comparing received JSON with stored ledger rows.
-- Preserve raw Inbox.payload for replay; never use an application supplied hash.
CREATE OR REPLACE FUNCTION accounting.posting_text(value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT btrim(value, E' \t\n\r\f' || chr(11)||chr(133)||chr(160)||chr(5760)||
    chr(8192)||chr(8193)||chr(8194)||chr(8195)||chr(8196)||chr(8197)||chr(8198)||chr(8199)||chr(8200)||
    chr(8201)||chr(8202)||chr(8232)||chr(8233)||chr(8239)||chr(8287)||chr(12288))
$$;
CREATE OR REPLACE FUNCTION accounting.posting_integer_value(value jsonb) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE result numeric; raw text;
BEGIN
  IF value='null'::jsonb THEN RETURN NULL; END IF;
  IF value='true'::jsonb THEN RETURN 1; END IF;
  IF value='false'::jsonb THEN RETURN 0; END IF;
  raw:=accounting.posting_text(value#>>'{}');
  IF jsonb_typeof(value)='string' AND raw !~ '^[+-]?[0-9](_?[0-9])*(\.0+)?$' THEN
    RAISE EXCEPTION 'Invalid inbox integer model value';
  END IF;
  result:=raw::numeric;
  IF result<>trunc(result) THEN RAISE EXCEPTION 'Invalid inbox integer model value'; END IF;
  RETURN result;
END $$;
CREATE OR REPLACE FUNCTION accounting.posting_date_value(value jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE raw text; seconds numeric; result date;
BEGIN
  IF value='null'::jsonb THEN RETURN NULL; END IF;
  IF jsonb_typeof(value) NOT IN ('string','number') THEN RAISE EXCEPTION 'Invalid inbox date value'; END IF;
  raw:=value#>>'{}';
  IF raw ~ '^[+-]?[0-9]+(\.[0-9]+)?$' THEN
    seconds:=raw::numeric;
    IF abs(seconds)>20000000000 THEN seconds:=seconds/1000; END IF;
    IF seconds>=0 THEN seconds:=round(seconds,6); END IF;
    IF mod(seconds,86400)<>0 THEN RAISE EXCEPTION 'Inbox date requires midnight'; END IF;
    result:=DATE '1970-01-01'+(seconds/86400)::integer;
  ELSIF raw ~ '^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])([Tt ]00[:]00([:]00([.,](0{1,6}|000000[0-9]+))?)?([Zz]|[+-]([01][0-9]|2[0-3])[:]?[0-5][0-9])?)?$' THEN
    result:=left(raw,10)::date;
  ELSE RAISE EXCEPTION 'Invalid inbox date value'; END IF;
  IF result<DATE '0001-01-01' OR result>DATE '9999-12-31' THEN RAISE EXCEPTION 'Inbox date out of range'; END IF;
  RETURN to_char(result,'YYYY-MM-DD');
END $$;
CREATE OR REPLACE FUNCTION accounting.posting_body_projection(body jsonb, normalize_input boolean DEFAULT true) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE result jsonb; row_value jsonb; projected jsonb; rows jsonb:='[]'; key text; dims jsonb;
BEGIN
  IF jsonb_typeof(body) IS DISTINCT FROM 'object' OR jsonb_typeof(body->'lines') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Invalid inbox posting body';
  END IF;
  result:=jsonb_build_object('opening',false,'correction_of',NULL)||body;
  IF normalize_input THEN
    FOREACH key IN ARRAY ARRAY['source','operation','rule_version','explanation'] LOOP
      result:=jsonb_set(result,ARRAY[key],COALESCE(to_jsonb(accounting.posting_text(result->>key)),'null'::jsonb));
    END LOOP;
  END IF;
  FOREACH key IN ARRAY ARRAY['source_version','policy_id','correction_of'] LOOP
    result:=jsonb_set(result,ARRAY[key],COALESCE(to_jsonb(accounting.posting_integer_value(result->key)),'null'::jsonb));
  END LOOP;
  FOREACH key IN ARRAY ARRAY['document_date','operation_date','posting_date'] LOOP
    result:=jsonb_set(result,ARRAY[key],COALESCE(to_jsonb(accounting.posting_date_value(result->key)),'null'::jsonb));
  END LOOP;
  result:=jsonb_set(result,'{opening}',CASE WHEN jsonb_typeof(result->'opening')='number'
    THEN to_jsonb((result->>'opening')::numeric=1)
    ELSE COALESCE(to_jsonb((result->>'opening')::boolean),'null'::jsonb) END);
  FOR row_value IN SELECT value FROM jsonb_array_elements(body->'lines') LOOP
    projected:=jsonb_build_object('dimensions','{}'::jsonb,'currency','BYN','original_amount',NULL,
      'rate',NULL,'rate_scale',NULL,'rate_date',NULL,'rate_source',NULL,'quantity',NULL,'cash_activity',NULL)||row_value;
    IF normalize_input THEN
      -- Literal fields side/cash_activity do not use Pydantic string stripping.
      FOREACH key IN ARRAY ARRAY['account','currency','rate_source'] LOOP
        projected:=jsonb_set(projected,ARRAY[key],COALESCE(to_jsonb(accounting.posting_text(projected->>key)),'null'::jsonb));
      END LOOP;
    END IF;
    FOREACH key IN ARRAY ARRAY['amount','original_amount','rate','quantity'] LOOP
      projected:=jsonb_set(projected,ARRAY[key],COALESCE(to_jsonb(
        CASE WHEN normalize_input THEN accounting.inbox_decimal_model((projected->key)::json)::numeric
             ELSE (projected->>key)::numeric END),'null'::jsonb));
    END LOOP;
    projected:=jsonb_set(projected,'{rate_scale}',COALESCE(to_jsonb(accounting.posting_integer_value(projected->'rate_scale')),'null'::jsonb));
    projected:=jsonb_set(projected,'{rate_date}',COALESCE(to_jsonb(accounting.posting_date_value(projected->'rate_date')),'null'::jsonb));
    IF normalize_input THEN
      SELECT COALESCE(jsonb_object_agg(accounting.posting_text(k),accounting.posting_text(v)),'{}'::jsonb)
        INTO dims FROM jsonb_each_text(projected->'dimensions') d(k,v);
      projected:=jsonb_set(projected,'{dimensions}',dims);
    END IF;
    rows:=rows||jsonb_build_array(projected);
  END LOOP;
  RETURN jsonb_set(result,'{lines}',rows);
END $$;

CREATE OR REPLACE FUNCTION accounting.guard_resolved_inbox_lines() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM accounting.inbox WHERE entry_id=NEW.entry_id) THEN
    RAISE EXCEPTION 'Resolved inbox posting body cannot receive additional lines';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER resolved_inbox_lines BEFORE INSERT ON accounting.line
FOR EACH ROW EXECUTE FUNCTION accounting.guard_resolved_inbox_lines();

-- JSONB numeric equality loses the int/float distinction used by schemas.exact.
-- Inspect raw JSON tokens before the effect projection converts them to numeric.
CREATE OR REPLACE FUNCTION accounting.validate_inbox_decimal_tokens(body json) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE line_value json; key text; token json;
BEGIN
  IF json_typeof(body->'lines') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Invalid inbox posting body lines';
  END IF;
  FOR line_value IN SELECT value FROM json_array_elements(body->'lines') LOOP
    FOREACH key IN ARRAY ARRAY['amount','original_amount','rate','quantity'] LOOP
      token:=line_value->key;
      IF key<>'amount' AND (token IS NULL OR json_typeof(token)='null') THEN CONTINUE; END IF;
      IF token IS NULL OR json_typeof(token) NOT IN ('string','number')
          OR (json_typeof(token)='number' AND token::text !~ '^-?[0-9]+$') THEN
        RAISE EXCEPTION 'Inbox posting body requires exact decimal strings or integers';
      END IF;
    END LOOP;
  END LOOP;
END $$;

-- Preserve Decimal's scale/exponent in the replay model; SQL numeric equality
-- is used separately for comparing the actual accounting effect.
CREATE OR REPLACE FUNCTION accounting.inbox_decimal_model(value json) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE raw text; pieces text[]; coefficient text; exponent_value integer; adjusted integer;
  point integer; sign_value text:=''; fraction text; result text;
BEGIN
  IF json_typeof(value)='null' THEN RETURN NULL; END IF;
  IF json_typeof(value) NOT IN ('string','number')
     OR (json_typeof(value)='number' AND value::text !~ '^-?[0-9]+$') THEN
    RAISE EXCEPTION 'Invalid inbox decimal model token';
  END IF;
  raw:=replace(accounting.posting_text(value#>>'{}'),'_','');
  pieces:=regexp_match(raw,'^([+-]?)([0-9]*)(\.([0-9]*))?([eE]([+-]?[0-9]+))?$');
  IF pieces IS NULL OR COALESCE(pieces[2],'')||COALESCE(pieces[4],'')='' THEN
    RAISE EXCEPTION 'Invalid inbox decimal model value';
  END IF;
  IF pieces[1]='-' THEN sign_value:='-'; END IF;
  fraction:=COALESCE(pieces[4],'');
  coefficient:=ltrim(pieces[2]||fraction,'0');
  IF coefficient='' THEN coefficient:='0'; END IF;
  exponent_value:=COALESCE(pieces[6],'0')::integer-length(fraction);
  adjusted:=exponent_value+length(coefficient)-1;
  IF exponent_value>0 OR adjusted< -6 THEN
    result:=left(coefficient,1);
    IF length(coefficient)>1 THEN result:=result||'.'||substring(coefficient FROM 2); END IF;
    result:=result||'E'||CASE WHEN adjusted>=0 THEN '+' ELSE '' END||adjusted::text;
  ELSIF exponent_value=0 THEN result:=coefficient;
  ELSE
    point:=length(coefficient)+exponent_value;
    IF point>0 THEN result:=left(coefficient,point)||'.'||substring(coefficient FROM point+1);
    ELSE result:='0.'||repeat('0',-point)||coefficient; END IF;
  END IF;
  RETURN sign_value||result;
END $$;

CREATE OR REPLACE FUNCTION accounting.inbox_replay_model(body json) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE result jsonb; line_value json; projected jsonb; lines jsonb:='[]'; key text; n integer:=0;
BEGIN
  PERFORM accounting.validate_inbox_shape(body);
  PERFORM accounting.validate_inbox_decimal_tokens(body);
  result:=accounting.posting_body_projection(body::jsonb);
  FOREACH key IN ARRAY ARRAY['source_version','policy_id','correction_of'] LOOP
    IF result->key<>'null'::jsonb THEN
      IF (result->>key)::numeric<>trunc((result->>key)::numeric) THEN
        RAISE EXCEPTION 'Invalid inbox integer model value';
      END IF;
      result:=jsonb_set(result,ARRAY[key],to_jsonb((result->>key)::numeric::bigint));
    END IF;
  END LOOP;
  FOR line_value IN SELECT value FROM json_array_elements(body->'lines') LOOP
    projected:=result->'lines'->n;
    FOREACH key IN ARRAY ARRAY['amount','original_amount','rate','quantity'] LOOP
      projected:=jsonb_set(projected,ARRAY[key],COALESCE(to_jsonb(accounting.inbox_decimal_model(line_value->key)),'null'::jsonb));
    END LOOP;
    IF projected->'rate_scale'<>'null'::jsonb THEN
      IF (projected->>'rate_scale')::numeric<>trunc((projected->>'rate_scale')::numeric) THEN
        RAISE EXCEPTION 'Invalid inbox rate scale model value';
      END IF;
      projected:=jsonb_set(projected,'{rate_scale}',to_jsonb((projected->>'rate_scale')::numeric::bigint));
    END IF;
    lines:=lines||jsonb_build_array(projected);
    n:=n+1;
  END LOOP;
  result:=jsonb_set(result,'{lines}',lines);
  PERFORM accounting.validate_inbox_model_bounds(result);
  RETURN result;
END $$;

CREATE OR REPLACE FUNCTION accounting.validate_inbox_shape(body json) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE b jsonb:=body::jsonb; line_value jsonb; key text; v jsonb; limit_value integer;
BEGIN
  IF jsonb_typeof(b) IS DISTINCT FROM 'object' OR jsonb_typeof(b->'lines') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Invalid inbox posting body structure';
  END IF;
  IF jsonb_array_length(b->'lines') NOT BETWEEN 1 AND 1000
     OR b-ARRAY['source','source_version','operation','document_date','operation_date','posting_date',
         'policy_id','rule_version','explanation','lines','opening','correction_of']<>'{}'::jsonb THEN
    RAISE EXCEPTION 'Invalid inbox posting body fields';
  END IF;
  FOREACH key IN ARRAY ARRAY['source','operation','rule_version','explanation'] LOOP
    limit_value:=CASE key WHEN 'source' THEN 160 WHEN 'operation' THEN 60 WHEN 'rule_version' THEN 100 ELSE 1000 END;
    IF jsonb_typeof(b->key) IS DISTINCT FROM 'string' OR length(accounting.posting_text(b->>key)) NOT BETWEEN 1 AND limit_value THEN
      RAISE EXCEPTION 'Invalid inbox posting body string field';
    END IF;
  END LOOP;
  IF b ? 'opening' THEN
    v:=b->'opening';
    IF NOT (jsonb_typeof(v)='boolean' OR (jsonb_typeof(v)='number' AND v IN ('0'::jsonb,'1'::jsonb))
       OR (jsonb_typeof(v)='string' AND lower(v#>>'{}') IN ('0','1','off','on','no','yes','f','t','false','true','n','y'))) THEN
      RAISE EXCEPTION 'Invalid inbox posting body boolean field';
    END IF;
  END IF;
  FOR line_value IN SELECT value FROM jsonb_array_elements(b->'lines') LOOP
    IF jsonb_typeof(line_value) IS DISTINCT FROM 'object' OR line_value-ARRAY['account','side','amount','dimensions','currency',
        'original_amount','rate','rate_scale','rate_date','rate_source','quantity','cash_activity']<>'{}'::jsonb THEN
      RAISE EXCEPTION 'Invalid inbox posting body line fields';
    END IF;
    IF jsonb_typeof(line_value->'account') IS DISTINCT FROM 'string'
       OR accounting.posting_text(line_value->>'account') !~ '^[0-9]+(\.[0-9]+)*$'
       OR length(accounting.posting_text(line_value->>'account')) NOT BETWEEN 1 AND 32
       OR COALESCE(line_value->>'side','') NOT IN ('debit','credit') THEN
      RAISE EXCEPTION 'Invalid inbox posting body account or side';
    END IF;
    IF line_value ? 'currency' AND (jsonb_typeof(line_value->'currency') IS DISTINCT FROM 'string'
       OR accounting.posting_text(line_value->>'currency') !~ '^[A-Z]{3}$') THEN
      RAISE EXCEPTION 'Invalid inbox posting body currency';
    END IF;
    IF line_value ? 'rate_source' AND line_value->'rate_source'<>'null'::jsonb AND
       (jsonb_typeof(line_value->'rate_source')<>'string' OR length(accounting.posting_text(line_value->>'rate_source'))>200) THEN
      RAISE EXCEPTION 'Invalid inbox posting body rate source';
    END IF;
    IF line_value ? 'dimensions' THEN
      IF jsonb_typeof(line_value->'dimensions') IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'Invalid inbox posting body dimensions';
      END IF;
      FOR key,v IN SELECT * FROM jsonb_each(line_value->'dimensions') LOOP
        IF jsonb_typeof(v) IS DISTINCT FROM 'string' OR accounting.posting_text(key)=''
           OR accounting.posting_text(translate(v#>>'{}',chr(28)||chr(29)||chr(30)||chr(31),'    '))=''
           OR length(accounting.posting_text(v#>>'{}')) NOT BETWEEN 1 AND 200 THEN
          RAISE EXCEPTION 'Invalid inbox posting body analytical value';
        END IF;
      END LOOP;
    END IF;
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION accounting.validate_inbox_model_bounds(body jsonb) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE key text; line_value jsonb; v numeric; digits integer; places integer; fraction text; whole text;
  cents_numerator numeric; scale_value numeric; converted_cents numeric;
BEGIN
  FOREACH key IN ARRAY ARRAY['source_version','policy_id','document_date','operation_date','posting_date'] LOOP
    IF body->key IS NULL OR body->key='null'::jsonb THEN RAISE EXCEPTION 'Missing inbox posting body required field'; END IF;
  END LOOP;
  IF (body->>'source_version')::numeric<1 OR (body->>'policy_id')::numeric<=0
     OR COALESCE((body->>'correction_of')::numeric,1)<=0 THEN
    RAISE EXCEPTION 'Invalid inbox posting body identifier';
  END IF;
  FOR line_value IN SELECT value FROM jsonb_array_elements(body->'lines') LOOP
    FOREACH key IN ARRAY ARRAY['amount','original_amount','rate','quantity'] LOOP
      IF key<>'amount' AND (line_value->key IS NULL OR line_value->key='null'::jsonb) THEN CONTINUE; END IF;
      v:=(line_value->>key)::numeric;
      IF v IS NULL OR v::text IN ('NaN','Infinity','-Infinity') OR v<0
         OR (key IN ('rate','quantity') AND v=0) THEN
        RAISE EXCEPTION 'Invalid inbox posting body numeric value';
      END IF;
      whole:=ltrim(split_part(v::text,'.',1),'-0');
      fraction:=rtrim(split_part(v::text,'.',2),'0');
      digits:=CASE WHEN key IN ('amount','original_amount') THEN 20 ELSE 24 END;
      places:=CASE WHEN key IN ('amount','original_amount') THEN 2 ELSE 6 END;
      IF length(whole)+length(fraction)>digits OR length(fraction)>places THEN
        RAISE EXCEPTION 'Invalid inbox posting body numeric precision';
      END IF;
    END LOOP;
    IF COALESCE((line_value->>'rate_scale')::numeric,1)<=0
       OR (line_value->>'rate_scale')::numeric>2147483647
       OR (line_value->'cash_activity'<>'null'::jsonb AND line_value->>'cash_activity' NOT IN ('operating','investing','financing','internal')) THEN
      RAISE EXCEPTION 'Invalid inbox posting body scale or cash activity';
    END IF;
    IF line_value->>'currency'='BYN' THEN
      FOREACH key IN ARRAY ARRAY['original_amount','rate','rate_scale','rate_date','rate_source'] LOOP
        IF line_value->key<>'null'::jsonb THEN RAISE EXCEPTION 'BYN inbox posting body cannot carry FX metadata'; END IF;
      END LOOP;
    ELSE
      FOREACH key IN ARRAY ARRAY['original_amount','rate','rate_scale','rate_date','rate_source'] LOOP
        IF line_value->key IS NULL OR line_value->key='null'::jsonb THEN RAISE EXCEPTION 'Incomplete inbox posting body FX metadata'; END IF;
      END LOOP;
      -- Compare cents using quotient/remainder: numeric division may round a
      -- large quotient before round(...,2), changing a below-half-cent amount.
      cents_numerator:=(line_value->>'original_amount')::numeric*(line_value->>'rate')::numeric*100;
      scale_value:=(line_value->>'rate_scale')::numeric;
      converted_cents:=div(cents_numerator,scale_value)+
        CASE WHEN mod(cents_numerator,scale_value)*2>=scale_value THEN 1 ELSE 0 END;
      IF line_value->>'rate_source'='' OR converted_cents<>(line_value->>'amount')::numeric*100 THEN
        RAISE EXCEPTION 'Inbox posting body FX conversion mismatch';
      END IF;
    END IF;
  END LOOP;
END $$;


-- Structural period integrity; transition provenance and exact generation
-- arithmetic are separate requirements before financial confirmation opens.
ALTER TABLE accounting.inbox ADD CONSTRAINT inbox_canonical_month
CHECK (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$' AND left(month,4)<>'0000');
ALTER TABLE accounting.source_control ADD CONSTRAINT source_control_canonical_month
CHECK (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$' AND left(month,4)<>'0000');
CREATE OR REPLACE FUNCTION accounting.guard_inbox_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='INSERT' THEN
    IF NEW.entry_id IS NOT NULL THEN
      RAISE EXCEPTION 'Inbox must start pending';
    END IF;
  ELSE
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.event_key IS DISTINCT FROM OLD.event_key OR NEW.month IS DISTINCT FROM OLD.month
       OR NEW.payload::text IS DISTINCT FROM OLD.payload::text THEN
      RAISE EXCEPTION 'Inbox source identity is immutable';
    END IF;
    IF OLD.entry_id IS NOT NULL AND (NEW.entry_id IS DISTINCT FROM OLD.entry_id OR NEW.error IS DISTINCT FROM OLD.error) THEN
      RAISE EXCEPTION 'Resolved inbox is immutable';
    END IF;
  END IF;
  IF NEW.entry_id IS NOT NULL AND (NEW.error IS NOT NULL OR NOT EXISTS (
      SELECT 1 FROM accounting.entry e WHERE e.id=NEW.entry_id AND e.organization_id=NEW.organization_id
        AND to_char(e.posting_date,'YYYY-MM')=NEW.month
        AND e.source=accounting.posting_text(NEW.payload->>'source')
        AND e.source_version=accounting.posting_integer_value(NEW.payload::jsonb->'source_version')
        AND e.operation=accounting.posting_text(NEW.payload->>'operation'))) THEN
    RAISE EXCEPTION 'Inbox resolution requires its matching source entry';
  END IF;
  IF NEW.entry_id IS NOT NULL THEN
    PERFORM accounting.validate_inbox_decimal_tokens(NEW.payload);
  END IF;
  IF NEW.entry_id IS NOT NULL AND accounting.posting_body_projection(NEW.payload::jsonb)
      IS DISTINCT FROM accounting.posting_body_projection(accounting.financial_posting_body(NEW.entry_id),false) THEN
    RAISE EXCEPTION 'Inbox posting body differs from the posted entry';
  END IF;
  IF NEW.entry_id IS NOT NULL AND (SELECT digest FROM accounting.entry WHERE id=NEW.entry_id)
      IS DISTINCT FROM accounting.financial_sha(accounting.inbox_replay_model(NEW.payload)) THEN
    RAISE EXCEPTION 'Inbox posting body replay digest differs from the posted entry';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER valid_inbox_identity BEFORE INSERT OR UPDATE ON accounting.inbox
FOR EACH ROW EXECUTE FUNCTION accounting.guard_inbox_identity();
CREATE TRIGGER no_delete_inbox BEFORE DELETE ON accounting.inbox
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_inbox BEFORE TRUNCATE ON accounting.inbox
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE OR REPLACE FUNCTION accounting.guard_period_structure() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE required_steps text[]:=ARRAY['documents','bank','settlements','stock','costing',
  'depreciation','fx','tax','financial_result','trial_balance'];
  first_day date; start_policy accounting.policy;
BEGIN
  IF NEW.month !~ '^[0-9]{4}-(0[1-9]|1[0-2])$' OR left(NEW.month,4)='0000'
     OR NEW.generation<0 OR (NEW.closed AND NEW.closed_generation IS DISTINCT FROM NEW.generation)
     OR (NOT NEW.closed AND NEW.closed_generation IS NOT NULL)
     OR jsonb_typeof(NEW.evidence::jsonb) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'Invalid accounting period structure';
  END IF;
  IF NEW.closed AND (
      NOT (NEW.evidence::jsonb ?& required_steps)
      OR NEW.evidence::jsonb-required_steps<>'{}'::jsonb
      OR EXISTS (SELECT 1 FROM jsonb_each(NEW.evidence::jsonb) AS item(key,value)
        WHERE jsonb_typeof(value)<>'string' OR length(value#>>'{}') NOT BETWEEN 1 AND 1000
          OR accounting.posting_text(translate(value#>>'{}',chr(28)||chr(29)||chr(30)||chr(31),'    '))='')
  ) THEN
    RAISE EXCEPTION 'Closing evidence requires every control step with a nonempty bounded string';
  END IF;
  IF NEW.closed AND EXISTS (SELECT 1 FROM accounting.period p
      WHERE p.organization_id=NEW.organization_id AND p.month<NEW.month AND NOT p.closed) THEN
    RAISE EXCEPTION 'Close earlier periods first';
  END IF;
  IF NEW.closed THEN
    first_day:=(NEW.month||'-01')::date;
    SELECT * INTO start_policy FROM accounting.policy
      WHERE organization_id=NEW.organization_id AND effective_from<=first_day
      ORDER BY effective_from DESC LIMIT 1;
    IF start_policy.id IS NULL OR NOT start_policy.normative_verified OR EXISTS (
        SELECT 1 FROM accounting.policy q WHERE q.organization_id=NEW.organization_id
          AND q.effective_from>first_day AND q.effective_from<first_day+INTERVAL '1 month'
          AND NOT q.normative_verified) THEN
      RAISE EXCEPTION 'Normative basis must be verified before final closing';
    END IF;
  END IF;
  IF TG_OP='INSERT' THEN
    IF NEW.closed OR NEW.generation<>0 OR NEW.closed_generation IS NOT NULL
       OR NEW.evidence::jsonb<>'{}'::jsonb THEN
      RAISE EXCEPTION 'Accounting period must start open with generation zero';
    END IF;
  ELSE
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.month IS DISTINCT FROM OLD.month THEN
      RAISE EXCEPTION 'Accounting period identity is immutable';
    END IF;
    IF NEW.generation<OLD.generation THEN
      RAISE EXCEPTION 'Accounting period generation cannot decrease';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER valid_period_structure BEFORE INSERT OR UPDATE ON accounting.period
FOR EACH ROW EXECUTE FUNCTION accounting.guard_period_structure();
CREATE TRIGGER no_delete_period BEFORE DELETE ON accounting.period
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_period BEFORE TRUNCATE ON accounting.period
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();

-- SQL-originated transition evidence. Validators must inspect the complete
-- chain, not infer transitions solely from the final closed flag.
CREATE TABLE accounting.period_change (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  root_transaction bigint NOT NULL,
  organization_id integer NOT NULL REFERENCES accounting.organization(id),
  period_id integer NOT NULL REFERENCES accounting.period(id),
  before_row jsonb,
  after_row jsonb NOT NULL
);
CREATE INDEX period_change_root_org ON accounting.period_change(root_transaction,organization_id,id);
CREATE OR REPLACE FUNCTION accounting.guard_period_change_origin() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF pg_trigger_depth()<>2 OR NEW.root_transaction<>txid_current()
     OR NOT EXISTS (SELECT 1 FROM accounting.period p
       WHERE p.id=NEW.period_id AND p.organization_id=NEW.organization_id
         AND to_jsonb(p)=NEW.after_row) THEN
    RAISE EXCEPTION 'Period change proof must originate from its period trigger';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER generated_period_change BEFORE INSERT ON accounting.period_change
FOR EACH ROW EXECUTE FUNCTION accounting.guard_period_change_origin();
CREATE TRIGGER immutable_period_change BEFORE UPDATE OR DELETE ON accounting.period_change
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_period_change BEFORE TRUNCATE ON accounting.period_change
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE OR REPLACE FUNCTION accounting.record_period_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='UPDATE' AND to_jsonb(OLD)=to_jsonb(NEW) THEN RETURN NULL; END IF;
  INSERT INTO accounting.period_change(root_transaction,organization_id,period_id,before_row,after_row)
  VALUES(txid_current(),NEW.organization_id,NEW.id,
    CASE WHEN TG_OP='INSERT' THEN NULL ELSE to_jsonb(OLD) END,to_jsonb(NEW));
  RETURN NULL;
END $$;
CREATE TRIGGER record_period_change AFTER INSERT OR UPDATE ON accounting.period
FOR EACH ROW EXECUTE FUNCTION accounting.record_period_change();

CREATE OR REPLACE FUNCTION accounting.validate_period_change_chain() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE previous jsonb; current_change record; final_row jsonb; flips integer:=0; seen boolean:=false;
BEGIN
  FOR current_change IN SELECT before_row,after_row FROM accounting.period_change
    WHERE root_transaction=NEW.root_transaction AND organization_id=NEW.organization_id
      AND period_id=NEW.period_id ORDER BY id LOOP
    IF seen AND current_change.before_row IS DISTINCT FROM previous THEN
      RAISE EXCEPTION 'Accounting period change chain is discontinuous';
    END IF;
    IF current_change.before_row IS NOT NULL AND
       current_change.before_row->'closed' IS DISTINCT FROM current_change.after_row->'closed' THEN
      flips:=flips+1;
    END IF;
    previous:=current_change.after_row;
    seen:=true;
  END LOOP;
  IF flips>1 THEN
    RAISE EXCEPTION 'Accounting period cannot change closed state twice in one transaction';
  END IF;
  SELECT to_jsonb(p) INTO final_row FROM accounting.period p WHERE p.id=NEW.period_id;
  IF final_row IS DISTINCT FROM previous THEN
    RAISE EXCEPTION 'Accounting period state differs from its change journal';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER valid_period_change_chain AFTER INSERT ON accounting.period_change
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.validate_period_change_chain();

CREATE TABLE accounting.period_root_basis (
  root_transaction bigint NOT NULL,
  organization_id integer NOT NULL REFERENCES accounting.organization(id),
  organization_generation bigint NOT NULL,
  periods_before jsonb NOT NULL,
  active_closes_before jsonb NOT NULL,
  PRIMARY KEY(root_transaction,organization_id)
);
CREATE OR REPLACE FUNCTION accounting.guard_period_basis_origin() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF pg_trigger_depth()<>2 OR NEW.root_transaction<>txid_current() THEN
    RAISE EXCEPTION 'Period basis must be captured by a guarded write';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER generated_period_basis BEFORE INSERT ON accounting.period_root_basis
FOR EACH ROW EXECUTE FUNCTION accounting.guard_period_basis_origin();
CREATE TRIGGER immutable_period_basis BEFORE UPDATE OR DELETE ON accounting.period_root_basis
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_period_basis BEFORE TRUNCATE ON accounting.period_root_basis
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE OR REPLACE FUNCTION accounting.capture_period_basis() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE org_key integer; org_generation bigint; periods jsonb; closes jsonb;
BEGIN
  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE EXCEPTION 'Accounting guarded writes require READ COMMITTED isolation';
  END IF;
  IF TG_TABLE_NAME='organization' THEN org_key:=NEW.id;
  ELSE org_key:=NEW.organization_id; END IF;
  SELECT generation INTO org_generation FROM accounting.organization WHERE id=org_key FOR UPDATE;
  IF TG_TABLE_NAME='period' AND TG_OP='INSERT' THEN
    IF EXISTS (SELECT 1 FROM accounting.period WHERE organization_id=org_key AND closed AND month>NEW.month) THEN
      RAISE EXCEPTION 'Cannot create an open period before a closed period';
    END IF;
  END IF;
  IF EXISTS (SELECT 1 FROM accounting.period_root_basis
      WHERE root_transaction=txid_current() AND organization_id=org_key) THEN RETURN NEW; END IF;
  -- Read after acquiring the organization lock, before the guarded row changes.
  SELECT COALESCE(jsonb_agg(to_jsonb(p) ORDER BY p.month),'[]'::jsonb) INTO periods
    FROM accounting.period p WHERE p.organization_id=org_key;
  SELECT COALESCE(jsonb_agg(jsonb_build_object('id',c.id,'month',c.month,
      'closed_generation',c.snapshot::jsonb->'closed_generation') ORDER BY c.month,c.id),'[]'::jsonb)
    INTO closes FROM accounting.financial_close_receipt c
    WHERE c.organization_id=org_key AND NOT EXISTS
      (SELECT 1 FROM accounting.financial_reopen_item i WHERE i.close_receipt_id=c.id);
  INSERT INTO accounting.period_root_basis VALUES(txid_current(),org_key,org_generation,periods,closes);
  RETURN NEW;
END $$;
-- Names ensure capture precedes other row-level validation/effects.
CREATE TRIGGER a_capture_period_basis BEFORE INSERT OR UPDATE ON accounting.period
FOR EACH ROW EXECUTE FUNCTION accounting.capture_period_basis();
CREATE TRIGGER a_capture_period_basis BEFORE UPDATE OF generation ON accounting.organization
FOR EACH ROW EXECUTE FUNCTION accounting.capture_period_basis();
CREATE TRIGGER a_capture_period_basis BEFORE INSERT ON accounting.entry
FOR EACH ROW EXECUTE FUNCTION accounting.capture_period_basis();
CREATE TRIGGER a_capture_period_basis BEFORE INSERT ON accounting.financial_close_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.capture_period_basis();
CREATE TRIGGER a_capture_period_basis BEFORE INSERT ON accounting.financial_reopen_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.capture_period_basis();
CREATE TRIGGER a_capture_period_basis BEFORE INSERT OR UPDATE ON accounting.source_control
FOR EACH ROW EXECUTE FUNCTION accounting.capture_period_basis();
CREATE TRIGGER a_capture_period_basis BEFORE INSERT OR UPDATE ON accounting.inbox
FOR EACH ROW EXECUTE FUNCTION accounting.capture_period_basis();

CREATE OR REPLACE FUNCTION accounting.validate_reopen_periods() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE org_key integer; r accounting.financial_reopen_receipt; b accounting.period_root_basis;
  original jsonb; current_period accounting.period; expected_before jsonb; expected_after jsonb;
  entry_count bigint; period_entries bigint; current_org_generation bigint;
  reopened_from text;
BEGIN
  IF TG_TABLE_NAME='organization' THEN org_key:=NEW.id;
  ELSE org_key:=NEW.organization_id; END IF;
  SELECT q.* INTO r FROM accounting.financial_reopen_receipt q
    JOIN accounting.financial_receipt_transaction t ON t.kind='reopen' AND t.receipt_id=q.id
    WHERE t.root_transaction=txid_current() AND q.organization_id=org_key;
  SELECT * INTO b FROM accounting.period_root_basis
    WHERE root_transaction=txid_current() AND organization_id=org_key;
  SELECT min(after_row->>'month') INTO reopened_from FROM accounting.period_change
    WHERE root_transaction=txid_current() AND organization_id=org_key
      AND before_row->'closed'='true'::jsonb AND after_row->'closed'='false'::jsonb;
  IF reopened_from IS NOT NULL THEN
    IF b.organization_id IS NULL THEN RAISE EXCEPTION 'Reopening requires its original period basis'; END IF;
    IF EXISTS (SELECT 1 FROM accounting.period WHERE organization_id=org_key AND month>=reopened_from
        AND (closed OR closed_generation IS NOT NULL OR evidence::jsonb<>'{}'::jsonb)) THEN
      RAISE EXCEPTION 'Reopening must clear every later period';
    END IF;
    IF r.id IS NULL AND (
        EXISTS (SELECT 1 FROM jsonb_array_elements(b.active_closes_before) c WHERE c->>'month'>=reopened_from)
        OR EXISTS (SELECT 1 FROM accounting.financial_close_receipt c
          WHERE c.organization_id=org_key AND c.month>=reopened_from
            AND NOT EXISTS (SELECT 1 FROM accounting.financial_reopen_item i WHERE i.close_receipt_id=c.id))) THEN
      RAISE EXCEPTION 'Financial reopening requires a dedicated current transaction receipt';
    END IF;
    IF r.id IS NULL AND EXISTS (SELECT 1 FROM accounting.period_change c
        WHERE c.root_transaction=txid_current() AND c.organization_id=org_key
          AND c.before_row->'closed'='true'::jsonb AND c.after_row->'closed'='false'::jsonb
          AND c.before_row->'generation' IS DISTINCT FROM c.after_row->'generation') THEN
      RAISE EXCEPTION 'Manual reopening cannot increase the period generation';
    END IF;
  END IF;
  IF r.id IS NULL THEN RETURN NULL; END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(b.active_closes_before) x
      WHERE x->>'month'>=r.from_month AND NOT EXISTS
        (SELECT 1 FROM accounting.financial_reopen_item i WHERE i.reopen_receipt_id=r.id
           AND to_jsonb(i.close_receipt_id)=x->'id')) THEN
    RAISE EXCEPTION 'Reopening must include every active close';
  END IF;
  IF b.organization_id IS NULL OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(b.periods_before) p
      WHERE p->>'month'=r.from_month AND p->'closed'='true'::jsonb) THEN
    RAISE EXCEPTION 'Reopening requires an initially closed period';
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(b.active_closes_before) c
      LEFT JOIN LATERAL (SELECT p FROM jsonb_array_elements(b.periods_before) p
        WHERE p->>'month'=c->>'month') x ON true
      WHERE c->>'month'>=r.from_month AND
        (x.p IS NULL OR x.p->'closed' IS DISTINCT FROM 'true'::jsonb
          OR c->'closed_generation' IS DISTINCT FROM x.p->'closed_generation')) THEN
    RAISE EXCEPTION 'Reopening close receipt generation is stale';
  END IF;
  IF EXISTS (SELECT 1 FROM accounting.entry e JOIN accounting.entry_transaction t ON t.entry_id=e.id
      WHERE t.root_transaction=txid_current() AND e.organization_id=org_key
        AND NOT EXISTS (SELECT 1 FROM accounting.financial_reopen_item i
          WHERE i.reopen_receipt_id=r.id AND e.id IN (i.monthly_entry_id,i.annual_entry_id))) THEN
    RAISE EXCEPTION 'Reopening transaction contains unrelated entries';
  END IF;
  SELECT count(*) INTO entry_count FROM accounting.entry e JOIN accounting.entry_transaction t ON t.entry_id=e.id
    WHERE t.root_transaction=txid_current() AND e.organization_id=org_key;
  SELECT generation INTO current_org_generation FROM accounting.organization WHERE id=org_key;
  IF current_org_generation<>b.organization_generation+1+entry_count THEN
    RAISE EXCEPTION 'Reopening organization generation mismatch';
  END IF;
  IF (SELECT count(*) FROM accounting.period WHERE organization_id=org_key)<>jsonb_array_length(b.periods_before) THEN
    RAISE EXCEPTION 'Reopening cannot change the set of periods';
  END IF;
  FOR original IN SELECT value FROM jsonb_array_elements(b.periods_before) LOOP
    SELECT * INTO current_period FROM accounting.period WHERE id=(original->>'id')::integer;
    IF original->>'month'<r.from_month THEN
      IF to_jsonb(current_period) IS DISTINCT FROM original THEN
        RAISE EXCEPTION 'Reopening changed an earlier period';
      END IF;
    ELSE
      SELECT count(*) INTO period_entries FROM accounting.entry e JOIN accounting.entry_transaction t ON t.entry_id=e.id
        WHERE t.root_transaction=txid_current() AND e.organization_id=org_key
          AND to_char(e.posting_date,'YYYY-MM')<=original->>'month';
      IF current_period.closed OR current_period.closed_generation IS NOT NULL
         OR current_period.evidence::jsonb<>'{}'::jsonb
         OR current_period.generation<>(original->>'generation')::bigint+1+period_entries THEN
        RAISE EXCEPTION 'Reopening dependent period generation or state mismatch';
      END IF;
    END IF;
  END LOOP;
  SELECT jsonb_agg(jsonb_build_object('month',p->'month','generation',p->'generation','closed',p->'closed') ORDER BY p->>'month')
    INTO expected_before FROM jsonb_array_elements(b.periods_before) p WHERE p->>'month'>=r.from_month;
  SELECT jsonb_agg(jsonb_build_object('month',p.month,'generation',p.generation,'closed',p.closed) ORDER BY p.month)
    INTO expected_after FROM accounting.period p WHERE p.organization_id=org_key AND p.month>=r.from_month;
  IF r.snapshot::jsonb->'periods_before' IS DISTINCT FROM expected_before
     OR r.snapshot::jsonb->'periods_after' IS DISTINCT FROM expected_after THEN
    RAISE EXCEPTION 'Reopening period snapshots mismatch';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER reopen_period_basis_check AFTER INSERT ON accounting.period_root_basis
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_reopen_periods();
CREATE CONSTRAINT TRIGGER reopen_period_change_check AFTER INSERT ON accounting.period_change
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_reopen_periods();
CREATE CONSTRAINT TRIGGER reopen_period_receipt_check AFTER INSERT ON accounting.financial_reopen_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_reopen_periods();
CREATE CONSTRAINT TRIGGER reopen_organization_check AFTER UPDATE ON accounting.organization
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_reopen_periods();
CREATE CONSTRAINT TRIGGER z_reopen_entry_check AFTER INSERT ON accounting.entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_reopen_periods();

CREATE OR REPLACE FUNCTION accounting.validate_close_periods() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE org_key integer; r accounting.financial_close_receipt; b accounting.period_root_basis;
  original jsonb; target_before jsonb; p accounting.period; k bigint; initial_generation bigint;
  new_target integer; final_org bigint;
BEGIN
  IF TG_TABLE_NAME='organization' THEN org_key:=NEW.id;
  ELSE org_key:=NEW.organization_id; END IF;
  -- Completeness applies to every open-to-closed transition, including the
  -- manual path without a financial transfer receipt. Only this root's
  -- transitions are checked: a later delivery remains a durable pending item.
  IF EXISTS (
    SELECT 1 FROM accounting.period_change c
    WHERE c.root_transaction=txid_current() AND c.organization_id=org_key
      AND c.before_row->'closed'='false'::jsonb AND c.after_row->'closed'='true'::jsonb
      AND (EXISTS (SELECT 1 FROM accounting.inbox i WHERE i.organization_id=org_key
                    AND i.month<=c.after_row->>'month' AND i.entry_id IS NULL)
           OR EXISTS (SELECT 1 FROM accounting.source_control s WHERE s.organization_id=org_key
                    AND s.month<=c.after_row->>'month' AND s.entry_id IS NULL))
  ) THEN
    RAISE EXCEPTION 'Unposted documents prevent closing';
  END IF;
  SELECT q.* INTO r FROM accounting.financial_close_receipt q
    JOIN accounting.financial_receipt_transaction t ON t.kind='close' AND t.receipt_id=q.id
    WHERE t.root_transaction=txid_current() AND q.organization_id=org_key;
  IF r.id IS NULL THEN RETURN NULL; END IF;
  SELECT * INTO b FROM accounting.period_root_basis
    WHERE root_transaction=txid_current() AND organization_id=org_key;
  SELECT value INTO target_before FROM jsonb_array_elements(b.periods_before) WHERE value->>'month'=r.month;
  IF b.organization_id IS NULL OR target_before->'closed'='true'::jsonb THEN
    RAISE EXCEPTION 'Closing requires an initially open period';
  END IF;
  initial_generation:=COALESCE((target_before->>'generation')::bigint,0);
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(b.active_closes_before) WHERE value->>'month'=r.month) THEN
    RAISE EXCEPTION 'Period already has an active close';
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(b.periods_before)
      WHERE value->>'month'<r.month AND value->'closed'='false'::jsonb) THEN
    RAISE EXCEPTION 'Close earlier periods first';
  END IF;
  IF EXISTS (SELECT 1 FROM accounting.inbox WHERE organization_id=org_key AND month<=r.month AND entry_id IS NULL)
     OR EXISTS (SELECT 1 FROM accounting.source_control WHERE organization_id=org_key AND month<=r.month AND entry_id IS NULL) THEN
    RAISE EXCEPTION 'Unposted documents prevent closing';
  END IF;
  new_target:=CASE WHEN target_before IS NULL THEN 1 ELSE 0 END;
  IF EXISTS (SELECT 1 FROM accounting.entry e JOIN accounting.entry_transaction t ON t.entry_id=e.id
      WHERE t.root_transaction=txid_current() AND e.organization_id=org_key
        AND e.id IS DISTINCT FROM r.monthly_entry_id AND e.id IS DISTINCT FROM r.annual_entry_id) THEN
    RAISE EXCEPTION 'Closing transaction contains unrelated entries';
  END IF;
  SELECT count(*) INTO k FROM accounting.entry e JOIN accounting.entry_transaction t ON t.entry_id=e.id
    WHERE t.root_transaction=txid_current() AND e.organization_id=org_key;
  SELECT generation INTO final_org FROM accounting.organization WHERE id=org_key;
  IF final_org<>b.organization_generation+k OR r.command::jsonb->'expected_generation' IS DISTINCT FROM to_jsonb(initial_generation) THEN
    RAISE EXCEPTION 'Closing initial or organization generation mismatch';
  END IF;
  IF (SELECT count(*) FROM accounting.period WHERE organization_id=org_key)<>jsonb_array_length(b.periods_before)+new_target THEN
    RAISE EXCEPTION 'Closing changed unrelated period set';
  END IF;
  SELECT * INTO p FROM accounting.period WHERE organization_id=org_key AND month=r.month;
  IF p.id IS NULL OR NOT p.closed OR p.generation<>initial_generation+k
     OR p.evidence::jsonb IS DISTINCT FROM r.command::jsonb->'evidence'
     OR r.snapshot::jsonb->'closed_generation' IS DISTINCT FROM to_jsonb(p.generation) THEN
    RAISE EXCEPTION 'Closing target generation or state mismatch';
  END IF;
  FOR original IN SELECT value FROM jsonb_array_elements(b.periods_before) WHERE value->>'month'<>r.month LOOP
    SELECT * INTO p FROM accounting.period WHERE id=(original->>'id')::integer;
    IF original->>'month'<r.month OR k=0 THEN
      IF to_jsonb(p) IS DISTINCT FROM original THEN RAISE EXCEPTION 'Closing changed an unrelated period'; END IF;
    ELSE
      IF to_jsonb(p.closed) IS DISTINCT FROM original->'closed'
         OR p.generation<>(original->>'generation')::bigint+k OR p.evidence::jsonb<>'{}'::jsonb THEN
        RAISE EXCEPTION 'Closing dependent period generation mismatch';
      END IF;
    END IF;
  END LOOP;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER close_period_basis_check AFTER INSERT ON accounting.period_root_basis
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_close_periods();
CREATE CONSTRAINT TRIGGER close_period_change_check AFTER INSERT ON accounting.period_change
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_close_periods();
-- In IMMEDIATE mode the root stamp must exist before this validator runs.
CREATE CONSTRAINT TRIGGER z_close_period_receipt_check AFTER INSERT ON accounting.financial_close_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_close_periods();
CREATE CONSTRAINT TRIGGER close_organization_check AFTER UPDATE ON accounting.organization
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_close_periods();
CREATE CONSTRAINT TRIGGER z_close_entry_check AFTER INSERT ON accounting.entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_close_periods();
CREATE CONSTRAINT TRIGGER close_source_control_check AFTER INSERT OR UPDATE ON accounting.source_control
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_close_periods();
CREATE CONSTRAINT TRIGGER close_inbox_check AFTER INSERT OR UPDATE ON accounting.inbox
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_close_periods();


CREATE OR REPLACE FUNCTION accounting.reject_inventory_issue_receipt_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Inventory issue receipt is immutable';
END $$;
CREATE TRIGGER immutable_inventory_issue_receipt BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.inventory_issue_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_inventory_issue_receipt_mutation();

CREATE OR REPLACE FUNCTION accounting.guard_inventory_issue_receipt_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id = NEW.entry_id;
  IF NOT FOUND OR e.organization_id IS DISTINCT FROM NEW.organization_id
    OR e.operation IS DISTINCT FROM 'inventory_issue' OR e.actor IS DISTINCT FROM NEW.actor
    OR e.digest IS DISTINCT FROM NEW.digest
    OR NEW.command->>'source' IS DISTINCT FROM e.source
    OR (NEW.command->>'source_version')::integer IS DISTINCT FROM e.source_version
    OR NEW.posting->>'source' IS DISTINCT FROM e.source
    OR NEW.posting->>'operation' IS DISTINCT FROM e.operation
    OR NEW.posting->>'rule_version' IS DISTINCT FROM e.rule_version
    OR NEW.cost->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
    OR NEW.cost->>'basis_digest' IS NULL THEN
    RAISE EXCEPTION 'Inventory issue receipt does not match its ledger entry';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_inventory_issue_receipt BEFORE INSERT ON accounting.inventory_issue_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_inventory_issue_receipt_insert();

CREATE OR REPLACE FUNCTION accounting.reject_inventory_sale_receipt_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Inventory sale receipt is immutable';
END $$;
CREATE TRIGGER immutable_inventory_sale_receipt BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.inventory_sale_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_inventory_sale_receipt_mutation();

CREATE OR REPLACE FUNCTION accounting.guard_inventory_sale_receipt_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id = NEW.entry_id;
  IF NOT FOUND OR e.organization_id IS DISTINCT FROM NEW.organization_id
    OR e.operation IS DISTINCT FROM 'inventory_sale' OR e.actor IS DISTINCT FROM NEW.actor
    OR e.rule_version NOT LIKE 'sale-v1:%' OR e.digest IS DISTINCT FROM NEW.digest
    OR NEW.command->>'source' IS DISTINCT FROM e.source
    OR (NEW.command->>'source_version')::integer IS DISTINCT FROM e.source_version
    OR NEW.posting->>'source' IS DISTINCT FROM e.source
    OR NEW.posting->>'operation' IS DISTINCT FROM e.operation
    OR NEW.posting->>'rule_version' IS DISTINCT FROM e.rule_version
    OR NEW.cost->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
    OR NEW.cost->>'basis_digest' IS NULL THEN
    RAISE EXCEPTION 'Inventory sale receipt does not match its ledger entry';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_inventory_sale_receipt BEFORE INSERT ON accounting.inventory_sale_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_inventory_sale_receipt_insert();

CREATE OR REPLACE FUNCTION accounting.check_inventory_sale_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer; e accounting.entry%ROWTYPE; r accounting.inventory_sale_receipt%ROWTYPE;
        l accounting.line%ROWTYPE; expected jsonb; pos integer:=0;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF e.operation IS DISTINCT FROM 'inventory_sale' OR e.rule_version NOT LIKE 'sale-v1:%' THEN RETURN NULL; END IF;
  SELECT * INTO r FROM accounting.inventory_sale_receipt WHERE entry_id=target;
  IF NOT FOUND THEN RAISE EXCEPTION 'Inventory sale requires its complete receipt'; END IF;
  IF r.posting->>'document_date' IS DISTINCT FROM e.document_date::text
    OR r.posting->>'operation_date' IS DISTINCT FROM e.operation_date::text
    OR r.posting->>'posting_date' IS DISTINCT FROM e.posting_date::text
    OR r.posting->>'policy_id' IS DISTINCT FROM e.policy_id::text
    OR r.posting->>'explanation' IS DISTINCT FROM e.explanation
    OR e.opening OR e.correction_of IS NOT NULL
    OR jsonb_typeof(r.posting::jsonb->'lines') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Inventory sale posting metadata differs from ledger';
  END IF;
  FOR l IN SELECT * FROM accounting.line WHERE entry_id=target ORDER BY id LOOP
    expected:=r.posting::jsonb->'lines'->pos;
    IF expected IS NULL OR expected->>'account' IS DISTINCT FROM l.account_code
      OR expected->>'side' IS DISTINCT FROM l.side
      OR (expected->>'amount')::numeric IS DISTINCT FROM l.amount
      OR (expected->>'quantity')::numeric IS DISTINCT FROM l.quantity
      OR expected->'dimensions' IS DISTINCT FROM l.dimensions::jsonb
      OR expected->>'currency' IS DISTINCT FROM 'BYN' OR l.currency<>'BYN'
      OR expected->>'original_amount' IS NOT NULL OR l.original_amount IS NOT NULL
      OR expected->>'rate' IS NOT NULL OR l.rate IS NOT NULL
      OR expected->>'rate_scale' IS NOT NULL OR l.rate_scale IS NOT NULL
      OR expected->>'rate_date' IS NOT NULL OR l.rate_date IS NOT NULL
      OR expected->>'rate_source' IS NOT NULL OR l.rate_source IS NOT NULL
      OR expected->>'cash_activity' IS NOT NULL OR l.cash_activity IS NOT NULL OR l.cash THEN
      RAISE EXCEPTION 'Inventory sale posting lines differ from ledger';
    END IF;
    pos:=pos+1;
  END LOOP;
  IF pos=0 OR pos<>jsonb_array_length(r.posting::jsonb->'lines') THEN
    RAISE EXCEPTION 'Inventory sale posting lines are incomplete';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_inventory_sale_entry AFTER INSERT ON accounting.entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_inventory_sale_complete();
CREATE CONSTRAINT TRIGGER complete_inventory_sale_line AFTER INSERT ON accounting.line
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_inventory_sale_complete();
CREATE CONSTRAINT TRIGGER complete_inventory_sale_receipt AFTER INSERT ON accounting.inventory_sale_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_inventory_sale_complete();


ALTER TABLE accounting.late_cost_receipt ADD CONSTRAINT fk_late_cost_primary
FOREIGN KEY (expense_id) REFERENCES procurement.additional_expense_document(id);

CREATE OR REPLACE FUNCTION accounting.reject_late_cost_receipt_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Late cost receipt is immutable';
END $$;
CREATE TRIGGER immutable_late_cost_receipt BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.late_cost_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_late_cost_receipt_mutation();

CREATE OR REPLACE FUNCTION accounting.guard_late_cost_receipt_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; original jsonb;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  IF NOT FOUND OR e.organization_id IS DISTINCT FROM NEW.organization_id
    OR e.operation IS DISTINCT FROM 'inventory_late_cost' OR e.actor IS DISTINCT FROM NEW.actor
    OR e.digest IS DISTINCT FROM NEW.digest OR e.rule_version NOT IN ('late-cost-byn-v1', 'late-cost-fx-v1')
    OR e.source IS DISTINCT FROM 'procurement:additional-expense:' || NEW.expense_id::text
    OR e.source_version IS DISTINCT FROM NEW.source_version
    OR NEW.posting->>'source' IS DISTINCT FROM e.source
    OR NEW.posting->>'source_version' IS DISTINCT FROM e.source_version::text
    OR NEW.posting->>'operation' IS DISTINCT FROM e.operation
    OR NEW.posting->>'rule_version' IS DISTINCT FROM e.rule_version
    OR NEW.calculation->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
    OR NEW.calculation->>'expense_id' IS DISTINCT FROM NEW.expense_id::text
    OR NEW.calculation->>'source_version' IS DISTINCT FROM NEW.source_version::text
    OR NEW.calculation::jsonb->'source_movements_verified' IS DISTINCT FROM 'true'::jsonb
    OR NEW.calculation::jsonb->'posted' IS DISTINCT FROM 'false'::jsonb
    OR coalesce(NEW.calculation->>'basis_digest', '') !~ '^[a-f0-9]{64}$' THEN
    RAISE EXCEPTION 'Late cost receipt does not match its ledger entry';
  END IF;
  SELECT r.document::jsonb INTO original FROM procurement.additional_expense_revision r
    JOIN procurement.additional_expense_document d ON d.id=r.expense_id
    WHERE r.expense_id=NEW.expense_id AND r.version=NEW.source_version AND d.organization_id=NEW.organization_id;
  IF NOT FOUND OR NEW.calculation::jsonb#>'{history,document}' IS DISTINCT FROM original THEN
    RAISE EXCEPTION 'Late cost receipt does not match its primary document';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_late_cost_receipt BEFORE INSERT ON accounting.late_cost_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_late_cost_receipt_insert();

CREATE OR REPLACE FUNCTION accounting.verify_late_cost_lines(target integer) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; r accounting.late_cost_receipt%ROWTYPE;
        l accounting.line%ROWTYPE; expected jsonb; pos integer:=0;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  SELECT * INTO r FROM accounting.late_cost_receipt WHERE entry_id=target;
  IF NOT FOUND THEN RAISE EXCEPTION 'Late cost line verification requires a receipt'; END IF;
  IF r.posting->>'document_date' IS DISTINCT FROM e.document_date::text
    OR r.posting->>'operation_date' IS DISTINCT FROM e.operation_date::text
    OR r.posting->>'posting_date' IS DISTINCT FROM e.posting_date::text
    OR r.posting->>'policy_id' IS DISTINCT FROM e.policy_id::text
    OR r.posting->>'explanation' IS DISTINCT FROM e.explanation
    OR e.opening OR e.correction_of IS NOT NULL
    OR jsonb_typeof(r.posting::jsonb->'lines') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Late cost posting metadata differs from ledger';
  END IF;
  FOR l IN SELECT * FROM accounting.line WHERE entry_id=target ORDER BY id LOOP
    expected:=r.posting::jsonb->'lines'->pos;
    IF expected IS NULL OR expected->>'account' IS DISTINCT FROM l.account_code
      OR expected->>'side' IS DISTINCT FROM l.side
      OR (expected->>'amount')::numeric IS DISTINCT FROM l.amount
      OR expected->'dimensions' IS DISTINCT FROM l.dimensions::jsonb
      OR expected->>'currency' IS DISTINCT FROM 'BYN' OR l.currency<>'BYN'
      OR expected->>'quantity' IS NOT NULL OR l.quantity IS NOT NULL
      OR expected->>'original_amount' IS NOT NULL OR l.original_amount IS NOT NULL
      OR expected->>'rate' IS NOT NULL OR l.rate IS NOT NULL
      OR expected->>'rate_scale' IS NOT NULL OR l.rate_scale IS NOT NULL
      OR expected->>'rate_date' IS NOT NULL OR l.rate_date IS NOT NULL
      OR expected->>'rate_source' IS NOT NULL OR l.rate_source IS NOT NULL
      OR expected->>'cash_activity' IS NOT NULL OR l.cash_activity IS NOT NULL OR l.cash THEN
      RAISE EXCEPTION 'Late cost posting lines differ from ledger';
    END IF;
    pos:=pos+1;
  END LOOP;
  IF pos=0 OR pos<>jsonb_array_length(r.posting::jsonb->'lines') THEN
    RAISE EXCEPTION 'Late cost posting lines are incomplete';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION accounting.check_late_cost_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer; e accounting.entry%ROWTYPE; r accounting.late_cost_receipt%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF e.operation IS DISTINCT FROM 'inventory_late_cost' THEN RETURN NULL; END IF;
  SELECT * INTO r FROM accounting.late_cost_receipt WHERE entry_id=target;
  IF NOT FOUND OR NOT EXISTS (SELECT 1 FROM accounting.source_control c
    WHERE c.organization_id=e.organization_id AND c.source=e.source AND c.version=e.source_version AND c.entry_id=e.id) THEN
    RAISE EXCEPTION 'Late cost entry requires its complete receipt and source control';
  END IF;
  PERFORM procurement.check_additional_expense(r.expense_id);
  PERFORM accounting.verify_late_cost_lines(target);
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_late_cost_entry AFTER INSERT ON accounting.entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_late_cost_complete();
CREATE CONSTRAINT TRIGGER complete_late_cost_line AFTER INSERT ON accounting.line
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_late_cost_complete();
CREATE CONSTRAINT TRIGGER complete_late_cost_receipt AFTER INSERT ON accounting.late_cost_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_late_cost_complete();

CREATE OR REPLACE FUNCTION accounting.reject_posted_late_cost_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM accounting.late_cost_receipt WHERE expense_id=NEW.expense_id) THEN
    RAISE EXCEPTION 'Posted late expense requires a separate correction workflow';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER preserve_posted_late_cost_source BEFORE INSERT ON procurement.additional_expense_revision
FOR EACH ROW EXECUTE FUNCTION accounting.reject_posted_late_cost_revision();


-- Independent physical, commercial and specific-lot cost checks for whole shipments.
CREATE TRIGGER no_truncate_shipment_receipt BEFORE TRUNCATE ON accounting.shipment_accounting_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE OR REPLACE FUNCTION accounting.shipment_account_contract(org integer, code_value text, day_value date,
    dims jsonb, category_value text, tracks_quantity boolean) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE acc accounting.account;
BEGIN
  SELECT * INTO acc FROM accounting.account WHERE organization_id=org AND code=code_value
    AND valid_from<=day_value ORDER BY valid_from DESC LIMIT 1;
  IF acc.id IS NULL OR acc.category IS DISTINCT FROM category_value OR acc.cash
     OR acc.quantity_tracking IS DISTINCT FROM tracks_quantity
     OR jsonb_typeof(dims) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'Shipment account role or dimensions are invalid';
  END IF;
  IF EXISTS(SELECT 1 FROM jsonb_each(dims) d WHERE jsonb_typeof(d.value) IS DISTINCT FROM 'string'
      OR nullif(btrim(d.key),'') IS NULL OR length(d.key)>100
      OR nullif(btrim(d.value#>>'{}'),'') IS NULL OR length(d.value#>>'{}')>200)
     OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(acc.required_dimensions::jsonb) required
       WHERE NOT(dims ? required)) THEN
    RAISE EXCEPTION 'Shipment account requires valid complete analytics';
  END IF;
  RETURN acc.id;
END $$;

CREATE OR REPLACE FUNCTION accounting.validate_shipment_costs(receipt_id integer) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE r accounting.shipment_accounting_receipt; bucket record; movement record; cost jsonb;
        qty numeric; amount numeric; issue_cost numeric; acquisition_amount numeric; acquisition_qty numeric;
        dims jsonb; expected jsonb:='[]'; policy accounting.policy; posting_day date;
        allocation jsonb; cumulative numeric; assigned numeric; target numeric; history jsonb;
        adjusted boolean; value_only boolean;
BEGIN
  SELECT * INTO STRICT r FROM accounting.shipment_accounting_receipt WHERE id=receipt_id;
  posting_day:=(r.command->>'posting_date')::date;
  IF r.command->>'recognition' IS DISTINCT FROM 'sale_on_shipment'
     OR r.command->>'cost_allocation' IS DISTINCT FROM 'cumulative_floor_last'
     OR r.command->>'vat_rounding' IS DISTINCT FROM 'commercial_line_half_up' THEN
    RAISE EXCEPTION 'Shipment calculation rule is unsupported';
  END IF;
  SELECT * INTO policy FROM accounting.policy WHERE organization_id=r.organization_id
    AND effective_from<=posting_day ORDER BY effective_from DESC LIMIT 1;
  IF policy.id IS NULL OR policy.id<>(r.command->>'policy_id')::integer OR policy.inventory_method<>'specific' THEN
    RAISE EXCEPTION 'Shipment requires its applicable specific-lot policy';
  END IF;
  IF jsonb_typeof(r.snapshot::jsonb->'costs') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Shipment lot cost evidence required';
  END IF;
  FOR allocation IN SELECT value FROM jsonb_array_elements(r.snapshot::jsonb->'mapping') LOOP
    IF (allocation->>'expense_account' ~ '^90[.]4([.]|$)') IS NOT TRUE THEN
      RAISE EXCEPTION 'Shipment allocation requires an expense account under 90.4';
    END IF;
    PERFORM accounting.shipment_account_contract(r.organization_id,allocation->>'expense_account',posting_day,
      allocation->'expense_dimensions','expense',false);
  END LOOP;
  IF EXISTS (
    (SELECT value-'cost_byn' FROM jsonb_array_elements(r.snapshot::jsonb->'mapping')
      EXCEPT ALL SELECT value FROM jsonb_array_elements(r.command::jsonb->'allocations'))
    UNION ALL
    (SELECT value FROM jsonb_array_elements(r.command::jsonb->'allocations')
      EXCEPT ALL SELECT value-'cost_byn' FROM jsonb_array_elements(r.snapshot::jsonb->'mapping'))
  ) THEN RAISE EXCEPTION 'Shipment mapping differs from approved allocation inputs'; END IF;
  IF (SELECT count(*) FROM jsonb_array_elements(r.snapshot::jsonb->'costs')) <>
     (SELECT count(*) FROM (SELECT DISTINCT m->>'account',m->>'lot',p.warehouse,p.sku_code
       FROM jsonb_array_elements(r.snapshot::jsonb->'mapping') m
       JOIN wms.physical_shipment_line p ON p.source=m->>'line_source'
       JOIN wms.physical_shipment_act a ON a.id=p.act_id
       WHERE a.organization_id=r.organization_id AND 'wms:physical-shipment:'||a.organization_id||':'||a.source_key=r.source) b) THEN
    RAISE EXCEPTION 'Shipment lot cost evidence must cover every bucket once';
  END IF;
  FOR bucket IN
    SELECT m->>'account' AS account,m->>'lot' AS lot,p.warehouse,p.sku_code,
      sum((m->>'quantity')::numeric) AS quantity,sum((m->>'cost_byn')::numeric) AS mapped_cost
    FROM jsonb_array_elements(r.snapshot::jsonb->'mapping') m
    JOIN wms.physical_shipment_line p ON p.source=m->>'line_source'
    JOIN wms.physical_shipment_act a ON a.id=p.act_id
    WHERE a.organization_id=r.organization_id AND 'wms:physical-shipment:'||a.organization_id||':'||a.source_key=r.source
    GROUP BY m->>'account',m->>'lot',p.warehouse,p.sku_code
  LOOP
    IF bucket.account !~ '^41([.]|$)' OR nullif(bucket.lot,'') IS NULL THEN
      RAISE EXCEPTION 'Shipment inventory bucket is invalid';
    END IF;
    SELECT value INTO STRICT cost FROM jsonb_array_elements(r.snapshot::jsonb->'costs')
      WHERE value->>'account'=bucket.account AND value->'dimensions'->>'lot'=bucket.lot
        AND value->'dimensions'->>'warehouse'=bucket.warehouse AND value->'dimensions'->>'sku'=bucket.sku_code;
    qty:=0; amount:=0; dims:=NULL; acquisition_amount:=NULL; acquisition_qty:=NULL; history:='[]'; adjusted:=false;
    FOR movement IN SELECT l.*,e.posting_date,e.source,e.source_version,e.operation FROM accounting.line l JOIN accounting.entry e ON e.id=l.entry_id
      WHERE e.organization_id=r.organization_id AND l.account_code=bucket.account
        AND NOT(e.source=r.source OR starts_with(e.source,r.source||':part:'))
      ORDER BY e.posting_date,e.id,l.id
    LOOP
      IF nullif(movement.dimensions->>'warehouse','') IS NULL OR nullif(movement.dimensions->>'sku','') IS NULL
         OR nullif(movement.dimensions->>'lot','') IS NULL THEN
        RAISE EXCEPTION 'Shipment inventory history lacks required dimensions';
      END IF;
      IF movement.dimensions->>'warehouse'<>bucket.warehouse OR movement.dimensions->>'sku'<>bucket.sku_code
         OR movement.dimensions->>'lot'<>bucket.lot THEN CONTINUE; END IF;
      value_only:=movement.quantity IS NULL;
      IF value_only THEN
        IF movement.operation<>'inventory_late_cost' OR movement.side<>'debit' OR movement.amount<=0 OR qty<=0
           OR NOT EXISTS(SELECT 1 FROM accounting.late_cost_receipt c WHERE c.entry_id=movement.entry_id
              AND c.organization_id=r.organization_id) THEN
          RAISE EXCEPTION 'Shipment value adjustment has no valid late-cost receipt';
        END IF;
        PERFORM accounting.verify_late_cost_lines(movement.entry_id);
      END IF;
      IF movement.posting_date>posting_day OR movement.category<>'asset' OR movement.cash
         OR movement.currency<>'BYN' THEN
        RAISE EXCEPTION 'Shipment inventory history requires chronological owned BYN quantities';
      END IF;
      IF dims IS NULL THEN dims:=movement.dimensions::jsonb;
      ELSIF dims<>movement.dimensions::jsonb THEN RAISE EXCEPTION 'Shipment inventory lot has mixed analytics'; END IF;
      IF value_only THEN adjusted:=true;
      ELSIF movement.side='debit' THEN
        IF adjusted THEN RAISE EXCEPTION 'Shipment acquisition after cost adjustment requires separate layers'; END IF;
        IF acquisition_qty IS NULL THEN acquisition_amount:=movement.amount; acquisition_qty:=movement.quantity;
        ELSIF acquisition_amount*movement.quantity<>movement.amount*acquisition_qty THEN
          RAISE EXCEPTION 'Shipment inventory lot has mixed acquisition prices';
        END IF;
      END IF;
      IF NOT value_only THEN qty:=qty+movement.quantity*CASE WHEN movement.side='debit' THEN 1 ELSE -1 END; END IF;
      amount:=amount+movement.amount*CASE WHEN movement.side='debit' THEN 1 ELSE -1 END;
      IF qty<0 OR amount<0 OR (qty=0 AND amount<>0) THEN
        RAISE EXCEPTION 'Shipment inventory history has an invalid balance';
      END IF;
      history:=history||jsonb_build_array(jsonb_build_object('entry_id',movement.entry_id,'line_id',movement.id,
        'source',movement.source,'source_version',movement.source_version,'side',movement.side,
        'quantity',movement.quantity::text,'amount_byn',movement.amount::text));
    END LOOP;
    IF qty<=0 OR bucket.quantity<=0 OR bucket.quantity>qty THEN RAISE EXCEPTION 'Shipment exceeds book quantity'; END IF;
    issue_cost:=CASE WHEN bucket.quantity=qty THEN amount ELSE round(amount*bucket.quantity/qty,2) END;
    IF issue_cost<=0 OR bucket.mapped_cost IS DISTINCT FROM issue_cost
       OR (cost->>'issue_cost_byn')::numeric IS DISTINCT FROM issue_cost
       OR (cost->>'issue_quantity')::numeric IS DISTINCT FROM bucket.quantity
       OR (cost->>'book_quantity')::numeric IS DISTINCT FROM qty
       OR (cost->>'book_value_byn')::numeric IS DISTINCT FROM amount
       OR (cost->>'remaining_quantity')::numeric IS DISTINCT FROM qty-bucket.quantity
       OR (cost->>'remaining_value_byn')::numeric IS DISTINCT FROM amount-issue_cost
       OR cost->'evidence' IS DISTINCT FROM history
       OR cost->'inventory_dimensions' IS DISTINCT FROM dims THEN
      RAISE EXCEPTION 'Shipment inventory cost differs from ledger history';
    END IF;
    cumulative:=0; assigned:=0;
    FOR allocation IN SELECT m FROM jsonb_array_elements(r.snapshot::jsonb->'mapping') m
      JOIN wms.physical_shipment_line p ON p.source=m->>'line_source'
      JOIN wms.physical_shipment_act a ON a.id=p.act_id
      WHERE a.organization_id=r.organization_id AND 'wms:physical-shipment:'||a.organization_id||':'||a.source_key=r.source
        AND m->>'account'=bucket.account AND m->>'lot'=bucket.lot
        AND p.warehouse=bucket.warehouse AND p.sku_code=bucket.sku_code
      ORDER BY accounting.financial_canonical(m-'cost_byn') COLLATE "C"
    LOOP
      cumulative:=cumulative+(allocation->>'quantity')::numeric;
      target:=floor(issue_cost*100*cumulative/bucket.quantity);
      IF (allocation->>'cost_byn')::numeric IS DISTINCT FROM (target-assigned)/100 THEN
        RAISE EXCEPTION 'Shipment cent allocation differs from deterministic lot distribution';
      END IF;
      assigned:=target;
    END LOOP;
    expected:=expected||jsonb_build_array(jsonb_build_object('account',bucket.account,'side','credit',
      'amount',issue_cost,'quantity',bucket.quantity,'dimensions',dims));
  END LOOP;
  SELECT expected||coalesce(jsonb_agg(jsonb_build_object('account',totals.account,'side','debit','amount',totals.amount,
      'quantity',NULL,'dimensions',totals.dimensions)),'[]'::jsonb) INTO expected
    FROM (SELECT m->>'expense_account' AS account,m->'expense_dimensions' AS dimensions,sum((m->>'cost_byn')::numeric) AS amount
      FROM jsonb_array_elements(r.snapshot::jsonb->'mapping') m GROUP BY m->>'expense_account',m->'expense_dimensions'
      HAVING sum((m->>'cost_byn')::numeric)<>0) totals;
  IF EXISTS (
    WITH wanted AS (SELECT v->>'account' AS account,v->>'side' AS side,(v->>'amount')::numeric AS amount,
      (v->>'quantity')::numeric AS quantity,v->'dimensions' AS dimensions FROM jsonb_array_elements(expected) v),
    actual AS (SELECT l.account_code AS account,l.side,sum(l.amount) AS amount,sum(l.quantity) AS quantity,l.dimensions::jsonb AS dimensions
      FROM accounting.line l JOIN accounting.entry e ON e.id=l.entry_id
      WHERE e.organization_id=r.organization_id AND (e.source=r.source OR starts_with(e.source,r.source||':part:'))
        AND l.account_code ~ '^(41|90[.]4)([.]|$)'
      GROUP BY l.account_code,l.side,l.dimensions::jsonb)
    (SELECT * FROM wanted EXCEPT ALL SELECT * FROM actual) UNION ALL
    (SELECT * FROM actual EXCEPT ALL SELECT * FROM wanted)
  ) THEN RAISE EXCEPTION 'Shipment inventory and expense ledger coverage differs'; END IF;
END $$;

CREATE OR REPLACE FUNCTION accounting.validate_shipment_receipt(receipt_id integer) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE r accounting.shipment_accounting_receipt; a wms.physical_shipment_act;
        page jsonb; n integer:=0; entry_row accounting.entry; expected_source text; basis jsonb;
        line_row accounting.line; category_value text; inventory_line boolean; effective_account integer;
BEGIN
  SELECT * INTO r FROM accounting.shipment_accounting_receipt WHERE id=receipt_id;
  IF r.id IS NULL THEN RAISE EXCEPTION 'Shipment receipt is required'; END IF;
  SELECT * INTO a FROM wms.physical_shipment_act WHERE organization_id=r.organization_id
    AND 'wms:physical-shipment:'||organization_id||':'||source_key=r.source;
  IF a.id IS NULL OR a.digest IS DISTINCT FROM r.act_digest
     OR r.snapshot::jsonb->'act' IS DISTINCT FROM jsonb_build_object(
       'act_id',a.id,'source_key',a.source_key,'request_hash',a.request_hash,'digest',a.digest,'snapshot',a.snapshot)
     OR r.command::jsonb->>'expected_act_digest' IS DISTINCT FROM a.digest THEN
    RAISE EXCEPTION 'Shipment receipt requires its exact physical act';
  END IF;
  basis:=jsonb_build_object('act_digest',r.act_digest,'inputs',r.command,
      'mapping',r.snapshot::jsonb->'mapping','costs',r.snapshot::jsonb->'costs',
      'commercial',r.snapshot::jsonb->'commercial');
  IF accounting.financial_sha(basis) IS DISTINCT FROM r.basis_digest
     OR jsonb_typeof(r.snapshot::jsonb->'pages') IS DISTINCT FROM 'array'
     OR jsonb_array_length(r.snapshot::jsonb->'pages')<1 THEN
    RAISE EXCEPTION 'Shipment receipt calculation envelope is invalid';
  END IF;
  FOR page IN SELECT value FROM jsonb_array_elements(r.snapshot::jsonb->'pages') LOOP
    n:=n+1;
    expected_source:=r.source||CASE WHEN n=1 THEN '' ELSE ':part:'||n END;
    SELECT * INTO entry_row FROM accounting.entry WHERE id=(page->>'entry_id')::integer;
    IF entry_row.id IS NULL OR entry_row.organization_id<>r.organization_id
       OR entry_row.source<>expected_source OR entry_row.source_version<>1
       OR entry_row.operation<>'inventory_sale' OR entry_row.actor<>r.actor
       OR entry_row.operation_date<>a.operation_date
       OR entry_row.document_date IS DISTINCT FROM (r.command->>'document_date')::date
       OR entry_row.posting_date IS DISTINCT FROM (r.command->>'posting_date')::date
       OR entry_row.policy_id IS DISTINCT FROM (r.command->>'policy_id')::integer
       OR entry_row.explanation IS DISTINCT FROM r.command->>'explanation'
       OR entry_row.opening IS DISTINCT FROM false OR entry_row.correction_of IS NOT NULL
       OR entry_row.rule_version<>'shipment-sale-v1:'||r.basis_digest
       OR entry_row.digest IS DISTINCT FROM page->>'digest'
       OR accounting.financial_sha(page->'posting') IS DISTINCT FROM entry_row.digest
       OR accounting.posting_body_projection(accounting.financial_posting_body(entry_row.id),false)
          IS DISTINCT FROM accounting.posting_body_projection(page->'posting',false)
       OR (n=1 AND entry_row.id<>r.anchor_entry_id) THEN
      RAISE EXCEPTION 'Shipment receipt does not match its complete ledger pages';
    END IF;
    FOR line_row IN SELECT * FROM accounting.line WHERE entry_id=entry_row.id LOOP
      inventory_line:=line_row.account_code ~ '^41([.]|$)';
      category_value:=CASE
        WHEN inventory_line OR line_row.account_code ~ '^62([.]|$)' THEN 'asset'
        WHEN line_row.account_code ~ '^90[.]4([.]|$)' THEN 'expense'
        WHEN line_row.account_code ~ '^90[.](1|2)([.]|$)' THEN 'income'
        WHEN line_row.account_code ~ '^68([.]|$)' THEN 'liability'
        ELSE NULL END;
      IF category_value IS NULL OR line_row.currency IS DISTINCT FROM 'BYN'
         OR line_row.original_amount IS NOT NULL OR line_row.rate IS NOT NULL
         OR line_row.rate_scale IS NOT NULL OR line_row.rate_date IS NOT NULL OR line_row.rate_source IS NOT NULL
         OR line_row.cash_activity IS NOT NULL
         OR (line_row.amount>0 AND line_row.amount<1000000000000000000) IS NOT TRUE
         OR (inventory_line AND (line_row.quantity>0 AND line_row.quantity<1000000000000000000) IS NOT TRUE)
         OR (NOT inventory_line AND line_row.quantity IS NOT NULL) THEN
        RAISE EXCEPTION 'Shipment ledger line has incompatible quantity, currency or cash metadata';
      END IF;
      effective_account:=accounting.shipment_account_contract(r.organization_id,line_row.account_code,
        entry_row.posting_date,line_row.dimensions::jsonb,category_value,inventory_line);
      IF effective_account IS DISTINCT FROM line_row.account_id THEN
        RAISE EXCEPTION 'Shipment ledger line requires the effective account version';
      END IF;
    END LOOP;
  END LOOP;
  IF (SELECT count(*) FROM accounting.entry WHERE organization_id=r.organization_id
      AND (source=r.source OR starts_with(source,r.source||':part:')))<>n THEN
    RAISE EXCEPTION 'Shipment receipt has extra ledger pages';
  END IF;
  IF jsonb_typeof(r.snapshot::jsonb->'mapping') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Shipment receipt requires physical quantity coverage';
  END IF;
  IF EXISTS (
    WITH mapped AS (
      SELECT value->>'line_source' AS source,sum((value->>'quantity')::numeric) AS qty
      FROM jsonb_array_elements(r.snapshot::jsonb->'mapping') GROUP BY value->>'line_source'
    ), physical AS (SELECT source,qty FROM wms.physical_shipment_line WHERE act_id=a.id)
    SELECT 1 FROM mapped FULL JOIN physical USING(source)
    WHERE mapped.qty IS DISTINCT FROM physical.qty
  ) OR EXISTS (
    SELECT 1 FROM jsonb_array_elements(r.snapshot::jsonb->'mapping') m
    WHERE (m->>'quantity')::numeric<=0 OR m->>'quantity' IS NULL
  ) THEN RAISE EXCEPTION 'Shipment receipt physical quantity coverage differs'; END IF;
  IF jsonb_typeof(r.command::jsonb->'commercial_lines') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Shipment commercial treatment is required';
  END IF;
  IF EXISTS (
    WITH commercial AS (SELECT (value->>'line_no')::integer AS line_no,count(*) AS n
      FROM jsonb_array_elements(r.command::jsonb->'commercial_lines') GROUP BY (value->>'line_no')::integer),
    physical AS (SELECT DISTINCT line_no FROM wms.physical_shipment_line WHERE act_id=a.id)
    SELECT 1 FROM commercial FULL JOIN physical USING(line_no)
      WHERE commercial.n IS DISTINCT FROM 1::bigint OR physical.line_no IS NULL
  ) THEN RAISE EXCEPTION 'Shipment commercial lines must cover the physical act exactly once'; END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(r.command::jsonb->'commercial_lines') c WHERE
      jsonb_typeof(c->'net_amount') IS DISTINCT FROM 'string'
      OR jsonb_typeof(c->'vat_rate') IS DISTINCT FROM 'string'
      OR ((c->>'net_amount')::numeric>0 AND (c->>'net_amount')::numeric<1000000000000000000) IS NOT TRUE
      OR ((c->>'vat_rate')::numeric BETWEEN 0 AND 100) IS NOT TRUE
      OR (c->>'buyer_account' ~ '^62([.]|$)') IS NOT TRUE OR (c->>'revenue_account' ~ '^90[.]1([.]|$)') IS NOT TRUE
      OR (c->>'vat_revenue_account' ~ '^90[.]2([.]|$)') IS NOT TRUE OR (c->>'vat_payable_account' ~ '^68([.]|$)') IS NOT TRUE
      OR c->'buyer_dimensions'->>'settlement_document' IS DISTINCT FROM 'sales:document:'||a.document_id
      OR nullif(btrim(c->>'vat_basis'),'') IS NULL) THEN
    RAISE EXCEPTION 'Shipment commercial treatment is invalid';
  END IF;
  IF EXISTS (
    WITH commercial AS (
      SELECT c, round((c->>'net_amount')::numeric*(c->>'vat_rate')::numeric/100,2) AS vat,
        jsonb_build_object('vat_rate',c->>'vat_rate','vat_basis',c->>'vat_basis') AS metadata
      FROM jsonb_array_elements(r.command::jsonb->'commercial_lines') c
    ), expected_lines AS (
      SELECT v.* FROM commercial CROSS JOIN LATERAL (VALUES
        (c->>'buyer_account','debit',(c->>'net_amount')::numeric+vat,c->'buyer_dimensions'),
        (c->>'revenue_account','credit',(c->>'net_amount')::numeric+vat,(c->'revenue_dimensions')||metadata),
        (c->>'vat_revenue_account','debit',vat,(c->'vat_dimensions')||metadata),
        (c->>'vat_payable_account','credit',vat,(c->'vat_dimensions')||metadata)
      ) v(account,side,amount,dimensions) WHERE amount<>0
    ), expected AS (
      SELECT account,side,sum(amount) AS amount,dimensions FROM expected_lines GROUP BY account,side,dimensions
    ), actual AS (
      SELECT l.account_code AS account,l.side,sum(l.amount) AS amount,l.dimensions::jsonb AS dimensions
      FROM accounting.line l JOIN accounting.entry e ON e.id=l.entry_id
      WHERE e.organization_id=r.organization_id AND (e.source=r.source OR starts_with(e.source,r.source||':part:'))
        AND l.account_code !~ '^(41|90[.]4)([.]|$)'
      GROUP BY l.account_code,l.side,l.dimensions::jsonb
    )
    (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)
    UNION ALL
    (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)
  ) THEN RAISE EXCEPTION 'Shipment revenue and VAT ledger coverage differs'; END IF;
  PERFORM accounting.validate_shipment_costs(r.id);
END $$;

CREATE OR REPLACE FUNCTION accounting.guard_shipment_receipt_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE page jsonb;
BEGIN
  FOR page IN SELECT value FROM jsonb_array_elements(NEW.snapshot::jsonb->'pages') LOOP
    PERFORM accounting.require_financial_entry_root((page->>'entry_id')::integer,NEW.organization_id,NEW.actor,'inventory_sale');
  END LOOP;
  PERFORM accounting.validate_shipment_receipt(NEW.id);
  RETURN NULL;
END $$;
CREATE TRIGGER validate_shipment_receipt_insert AFTER INSERT ON accounting.shipment_accounting_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_shipment_receipt_insert();
CREATE CONSTRAINT TRIGGER recheck_shipment_receipt_at_commit AFTER INSERT ON accounting.shipment_accounting_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.guard_shipment_receipt_insert();

-- Each later ledger insertion schedules a fresh check. An earlier SET CONSTRAINTS
-- cannot drain protection for changes that have not happened yet.
CREATE OR REPLACE FUNCTION accounting.recheck_shipment_after_ledger_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE receipt_id integer;
BEGIN
  FOR receipt_id IN
    SELECT r.id FROM accounting.shipment_accounting_receipt r
    JOIN accounting.entry_transaction t ON t.entry_id=r.anchor_entry_id
    JOIN accounting.entry e ON e.organization_id=r.organization_id
    WHERE e.id=NEW.entry_id AND t.root_transaction=txid_current()
      -- Own pages are verified by receipt insertion/commit; finalized guards
      -- forbid adding their lines after receipt creation. Recheck only external
      -- movements that can change the already calculated inventory basis.
      AND e.source<>r.source AND NOT starts_with(e.source,r.source||':part:')
  LOOP
    PERFORM accounting.validate_shipment_receipt(receipt_id);
  END LOOP;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER recheck_shipment_on_ledger_insert AFTER INSERT ON accounting.line
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.recheck_shipment_after_ledger_insert();

CREATE OR REPLACE FUNCTION accounting.guard_shipment_source_resolution() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE receipt_id integer;
BEGIN
  IF starts_with(NEW.source,'wms:physical-shipment:') AND NEW.entry_id IS NOT NULL THEN
    SELECT id INTO receipt_id FROM accounting.shipment_accounting_receipt
      WHERE organization_id=NEW.organization_id AND source=NEW.source AND anchor_entry_id=NEW.entry_id;
    PERFORM accounting.validate_shipment_receipt(receipt_id);
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER require_shipment_receipt BEFORE INSERT OR UPDATE ON accounting.source_control
FOR EACH ROW EXECUTE FUNCTION accounting.guard_shipment_source_resolution();

CREATE OR REPLACE FUNCTION accounting.guard_final_shipment_line() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS(SELECT 1 FROM accounting.entry e JOIN accounting.shipment_accounting_receipt r
      ON r.organization_id=e.organization_id AND (e.source=r.source OR starts_with(e.source,r.source||':part:'))
      WHERE e.id=NEW.entry_id) THEN
    RAISE EXCEPTION 'Shipment receipt ledger lines are finalized';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER finalized_shipment_line BEFORE INSERT ON accounting.line
FOR EACH ROW EXECUTE FUNCTION accounting.guard_final_shipment_line();

CREATE OR REPLACE FUNCTION accounting.guard_final_shipment_page() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS(SELECT 1 FROM accounting.shipment_accounting_receipt r WHERE r.organization_id=NEW.organization_id
      AND (NEW.source=r.source OR starts_with(NEW.source,r.source||':part:'))) THEN
    RAISE EXCEPTION 'Shipment receipt ledger pages are finalized';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER finalized_shipment_page BEFORE INSERT ON accounting.entry
FOR EACH ROW EXECUTE FUNCTION accounting.guard_final_shipment_page();


-- Independent storage checks for the internal primary receipt binding.
CREATE OR REPLACE FUNCTION wms.reject_primary_receipt_binding_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Primary receipt binding is immutable';
END $$;
CREATE TRIGGER immutable_primary_receipt_binding
BEFORE UPDATE OR DELETE ON wms.primary_receipt_binding
FOR EACH ROW EXECUTE FUNCTION wms.reject_primary_receipt_binding_mutation();
CREATE TRIGGER immutable_primary_receipt_binding_truncate
BEFORE TRUNCATE ON wms.primary_receipt_binding
FOR EACH STATEMENT EXECUTE FUNCTION wms.reject_primary_receipt_binding_mutation();

CREATE OR REPLACE FUNCTION wms.check_primary_receipt_binding() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  primary_doc procurement.receipt_document%ROWTYPE;
  physical wms.receipt%ROWTYPE;
  primary_body jsonb;
  saved jsonb;
  fact jsonb;
  choice jsonb;
  physical_line wms.receipt_line%ROWTYPE;
  position integer;
  qty numeric;
  total numeric;
  count_lines integer;
  projection jsonb;
  source_position integer;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Primary receipt organization does not exist'; END IF;
  SELECT * INTO primary_doc FROM procurement.receipt_document WHERE id = NEW.source_receipt_id FOR UPDATE;
  IF NOT FOUND OR primary_doc.organization_id IS DISTINCT FROM NEW.organization_id
     OR primary_doc.current_version IS DISTINCT FROM NEW.source_version THEN
    RAISE EXCEPTION 'Primary receipt source owner or version mismatch';
  END IF;
  SELECT document::jsonb INTO primary_body FROM procurement.receipt_revision
    WHERE receipt_id = NEW.source_receipt_id AND version = NEW.source_version;
  IF primary_body IS NULL OR NEW.source_snapshot::jsonb->'document' IS DISTINCT FROM primary_body
     OR NEW.source_snapshot->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
     OR NEW.source_snapshot->>'receipt_id' IS DISTINCT FROM NEW.source_receipt_id::text
     OR NEW.source_snapshot->>'version' IS DISTINCT FROM NEW.source_version::text
     OR NEW.command->>'expected_version' IS DISTINCT FROM NEW.source_version::text
     OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
     OR NULLIF(btrim(NEW.actor), '') IS NULL
     OR NULLIF(btrim(NEW.command->>'evidence'), '') IS NULL THEN
    RAISE EXCEPTION 'Primary receipt binding snapshot or command mismatch';
  END IF;
  -- Validate the complete projection, including lines not selected for this delivery.
  -- Otherwise a forged immutable snapshot can poison later partial receipts and QC.
  IF jsonb_typeof(NEW.source_snapshot::jsonb->'lines') IS DISTINCT FROM 'array'
     OR jsonb_array_length(NEW.source_snapshot::jsonb->'lines') IS DISTINCT FROM
        jsonb_array_length(primary_body->'items') THEN
    RAISE EXCEPTION 'Primary receipt source projection mismatch';
  END IF;
  FOR fact, source_position IN
    SELECT value, ordinality::integer FROM jsonb_array_elements(primary_body->'items') WITH ORDINALITY
  LOOP
    projection := NEW.source_snapshot::jsonb->'lines'->(source_position - 1);
    IF projection->'position' IS DISTINCT FROM to_jsonb(source_position)
       OR projection->>'source_line' IS DISTINCT FROM
          format('procurement:receipt:%s:%s:%s', NEW.source_receipt_id, NEW.source_version, source_position)
       OR projection->>'sku' IS DISTINCT FROM fact->>'sku'
       OR projection->>'lot' IS DISTINCT FROM fact->>'lot'
       OR projection->>'unit' IS DISTINCT FROM fact->>'unit'
       OR NULLIF(btrim(fact->>'unit'), '') IS NULL
       OR jsonb_typeof(projection->'quantity') IS DISTINCT FROM 'string'
       OR (projection->>'quantity')::numeric IS DISTINCT FROM (fact->>'quantity')::numeric
       OR (fact->>'quantity')::numeric <= 0
       OR (fact->>'quantity')::numeric >= 1000000000000
       OR (fact->>'quantity')::numeric <> round((fact->>'quantity')::numeric, 2) THEN
      RAISE EXCEPTION 'Primary receipt source projection mismatch';
    END IF;
  END LOOP;
  SELECT * INTO physical FROM wms.receipt WHERE id = NEW.receipt_id FOR UPDATE;
  IF NOT FOUND OR physical.organization_id IS DISTINCT FROM NEW.organization_id
     OR physical.warehouse IS DISTINCT FROM NEW.command->>'warehouse'
     OR physical.status <> 'pending_qc' OR physical.source <> 'procurement' THEN
    RAISE EXCEPTION 'Physical receipt owner or preparation state mismatch';
  END IF;
  IF EXISTS (SELECT 1 FROM wms.primary_receipt_binding b
    WHERE b.organization_id = NEW.organization_id AND b.source_receipt_id = NEW.source_receipt_id
      AND (b.source_version <> NEW.source_version OR b.source_snapshot::jsonb <> NEW.source_snapshot::jsonb)) THEN
    RAISE EXCEPTION 'Primary receipt revision requires reconciliation';
  END IF;
  IF jsonb_typeof(NEW.line_bindings::jsonb) IS DISTINCT FROM 'array'
     OR jsonb_typeof(NEW.command::jsonb->'lines') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Primary receipt binding lines required';
  END IF;
  count_lines := jsonb_array_length(NEW.line_bindings::jsonb);
  IF count_lines < 1 OR count_lines <> jsonb_array_length(NEW.command::jsonb->'lines')
     OR count_lines <> (SELECT count(*) FROM wms.receipt_line WHERE receipt_id = NEW.receipt_id)
     OR count_lines <> (SELECT count(DISTINCT item->>'position') FROM jsonb_array_elements(NEW.line_bindings::jsonb) item)
     OR count_lines <> (SELECT count(DISTINCT item->>'receipt_line_id') FROM jsonb_array_elements(NEW.line_bindings::jsonb) item) THEN
    RAISE EXCEPTION 'Primary receipt binding line set mismatch';
  END IF;
  FOR saved IN SELECT * FROM jsonb_array_elements(NEW.line_bindings::jsonb) LOOP
    position := (saved->>'position')::integer;
    qty := (saved->>'quantity')::numeric;
    fact := primary_body->'items'->(position - 1);
    SELECT item INTO choice FROM jsonb_array_elements(NEW.command::jsonb->'lines') item
      WHERE (item->>'position')::integer = position;
    IF fact IS NULL OR position < 1 OR choice IS NULL OR qty IS NULL OR qty <= 0 OR qty >= 1000000000000
       OR qty <> round(qty, 2) OR NULLIF(btrim(fact->>'unit'), '') IS NULL
       OR saved->>'unit' IS DISTINCT FROM fact->>'unit'
       OR saved->>'sku_code' IS DISTINCT FROM choice->>'sku_code'
       OR qty IS DISTINCT FROM (choice->>'quantity')::numeric
       OR saved->>'source_line' IS DISTINCT FROM
          format('procurement:receipt:%s:%s:%s', NEW.source_receipt_id, NEW.source_version, position) THEN
      RAISE EXCEPTION 'Primary receipt line facts mismatch';
    END IF;
    SELECT * INTO physical_line FROM wms.receipt_line WHERE id = (saved->>'receipt_line_id')::integer;
    IF NOT FOUND OR physical_line.receipt_id IS DISTINCT FROM NEW.receipt_id
       OR physical_line.sku_code IS DISTINCT FROM saved->>'sku_code'
       OR physical_line.expected_qty IS DISTINCT FROM qty
       OR physical_line.batch_ref IS DISTINCT FROM fact->>'lot'
       OR NOT EXISTS (SELECT 1 FROM public.sku s WHERE s.code = physical_line.sku_code AND s.unit = fact->>'unit') THEN
      RAISE EXCEPTION 'Physical receipt line differs from primary binding';
    END IF;
    SELECT coalesce(sum((item->>'quantity')::numeric), 0) INTO total
      FROM wms.primary_receipt_binding b CROSS JOIN LATERAL jsonb_array_elements(b.line_bindings::jsonb) item
      WHERE b.organization_id = NEW.organization_id AND b.source_receipt_id = NEW.source_receipt_id
        AND (item->>'position')::integer = position;
    IF total + qty > (fact->>'quantity')::numeric THEN
      RAISE EXCEPTION 'Physical receipts exceed primary line quantity';
    END IF;
  END LOOP;
  RETURN NEW;
END $$;
CREATE TRIGGER check_primary_receipt_binding BEFORE INSERT ON wms.primary_receipt_binding
FOR EACH ROW EXECUTE FUNCTION wms.check_primary_receipt_binding();

CREATE OR REPLACE FUNCTION wms.guard_bound_receipt_line() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_receipt integer; new_receipt integer; bound_receipt integer; current_status text;
BEGIN
  IF TG_OP <> 'INSERT' THEN old_receipt := OLD.receipt_id; END IF;
  IF TG_OP <> 'DELETE' THEN new_receipt := NEW.receipt_id; END IF;
  -- Match the application's organization-before-receipt lock order.
  PERFORM o.id FROM accounting.organization o
    WHERE o.id IN (SELECT organization_id FROM wms.receipt WHERE id IN (old_receipt, new_receipt))
    ORDER BY o.id FOR UPDATE;
  SELECT b.receipt_id INTO bound_receipt FROM wms.primary_receipt_binding b
    WHERE b.receipt_id IN (old_receipt, new_receipt) ORDER BY b.receipt_id LIMIT 1;
  IF bound_receipt IS NULL THEN
    IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
  END IF;
  SELECT status INTO current_status FROM wms.receipt WHERE id = bound_receipt FOR UPDATE;
  IF TG_OP <> 'UPDATE' THEN
    RAISE EXCEPTION 'Bound physical receipt line set is immutable';
  END IF;
  IF current_status <> 'pending_qc' THEN
    RAISE EXCEPTION 'Accepted physical receipt lines are immutable';
  END IF;
  IF (to_jsonb(NEW) - ARRAY['accepted_qty', 'rejected_qty', 'reject_reason', 'location_id'])
      IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['accepted_qty', 'rejected_qty', 'reject_reason', 'location_id']) THEN
    RAISE EXCEPTION 'Bound physical receipt line identity is immutable';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_bound_receipt_line BEFORE INSERT OR UPDATE OR DELETE ON wms.receipt_line
FOR EACH ROW EXECUTE FUNCTION wms.guard_bound_receipt_line();

CREATE OR REPLACE FUNCTION wms.guard_bound_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM id FROM accounting.organization WHERE id = OLD.organization_id FOR UPDATE;
  IF NOT EXISTS (SELECT 1 FROM wms.primary_receipt_binding WHERE receipt_id = OLD.id) THEN
    IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
  END IF;
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Bound physical receipt is immutable'; END IF;
  IF (to_jsonb(NEW) - ARRAY['status', 'decided_by', 'decided_at']) IS DISTINCT FROM
     (to_jsonb(OLD) - ARRAY['status', 'decided_by', 'decided_at']) THEN
    RAISE EXCEPTION 'Bound physical receipt identity is immutable';
  END IF;
  IF OLD.status <> 'pending_qc' AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
    RAISE EXCEPTION 'Accepted physical receipt is immutable';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_bound_receipt BEFORE UPDATE OR DELETE ON wms.receipt
FOR EACH ROW EXECUTE FUNCTION wms.guard_bound_receipt();

CREATE OR REPLACE FUNCTION wms.reject_bound_receipt_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM wms.primary_receipt_binding) THEN
    RAISE EXCEPTION 'Bound physical receipt history is immutable';
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER guard_bound_receipt_line_truncate BEFORE TRUNCATE ON wms.receipt_line
FOR EACH STATEMENT EXECUTE FUNCTION wms.reject_bound_receipt_truncate();

CREATE OR REPLACE FUNCTION wms.verify_primary_receipt_state(target_id integer) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE r wms.receipt%ROWTYPE; b wms.primary_receipt_binding%ROWTYPE;
BEGIN
  SELECT * INTO b FROM wms.primary_receipt_binding WHERE receipt_id = target_id;
  IF NOT FOUND THEN RETURN; END IF;
  PERFORM id FROM accounting.organization WHERE id = b.organization_id FOR UPDATE;
  SELECT * INTO r FROM wms.receipt WHERE id = target_id FOR UPDATE;
  IF r.status = 'pending_qc' THEN
    IF EXISTS (SELECT 1 FROM wms.stock_movement WHERE organization_id = r.organization_id
      AND doc_ref = r.number AND reason = 'receipt') THEN
      RAISE EXCEPTION 'Pending primary receipt cannot have physical arrival movements';
    END IF;
    RETURN;
  END IF;
  IF r.status <> 'accepted' THEN RAISE EXCEPTION 'Unsupported bound receipt status'; END IF;
  IF NOT EXISTS (SELECT 1 FROM procurement.receipt_document WHERE id = b.source_receipt_id
    AND organization_id = b.organization_id AND current_version = b.source_version) THEN
    RAISE EXCEPTION 'Primary receipt version changed before acceptance';
  END IF;
  IF EXISTS (SELECT 1 FROM wms.receipt_line WHERE receipt_id = target_id AND
    (accepted_qty IS NULL OR rejected_qty IS NULL OR accepted_qty < 0 OR rejected_qty < 0
     OR accepted_qty + rejected_qty <> expected_qty)) THEN
    RAISE EXCEPTION 'Primary receipt requires complete explicit QC';
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(b.line_bindings::jsonb) item
    WHERE NOT EXISTS (SELECT 1 FROM public.sku s WHERE s.code = item->>'sku_code' AND s.unit = item->>'unit')) THEN
    RAISE EXCEPTION 'Primary receipt warehouse unit changed';
  END IF;
  IF EXISTS (
    (SELECT sku_code, r.warehouse, accepted_qty, 'in'::text, location_id, batch_ref
       FROM wms.receipt_line WHERE receipt_id = target_id AND accepted_qty > 0
     EXCEPT ALL
     SELECT sku_code, warehouse, qty, kind::text, location_id, batch_ref
       FROM wms.stock_movement WHERE organization_id = r.organization_id AND doc_ref = r.number AND reason = 'receipt')
    UNION ALL
    (SELECT sku_code, warehouse, qty, kind::text, location_id, batch_ref
       FROM wms.stock_movement WHERE organization_id = r.organization_id AND doc_ref = r.number AND reason = 'receipt'
     EXCEPT ALL
     SELECT sku_code, r.warehouse, accepted_qty, 'in'::text, location_id, batch_ref
       FROM wms.receipt_line WHERE receipt_id = target_id AND accepted_qty > 0)
  ) THEN
    RAISE EXCEPTION 'Primary receipt arrival movements do not match accepted QC';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION wms.check_primary_receipt_state_trigger() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME = 'primary_receipt_binding' THEN
    PERFORM wms.verify_primary_receipt_state(NEW.receipt_id);
  ELSE
    PERFORM wms.verify_primary_receipt_state(NEW.id);
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_primary_receipt_state AFTER UPDATE ON wms.receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION wms.check_primary_receipt_state_trigger();
CREATE CONSTRAINT TRIGGER complete_primary_receipt_binding_state AFTER INSERT ON wms.primary_receipt_binding
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION wms.check_primary_receipt_state_trigger();

CREATE OR REPLACE FUNCTION wms.check_primary_receipt_movement_trigger() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target_id integer;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    FOR target_id IN SELECT r.id FROM wms.receipt r JOIN wms.primary_receipt_binding b ON b.receipt_id = r.id
      WHERE r.organization_id = OLD.organization_id AND r.number = OLD.doc_ref LOOP
      PERFORM wms.verify_primary_receipt_state(target_id);
    END LOOP;
  END IF;
  IF TG_OP <> 'DELETE' THEN
    FOR target_id IN SELECT r.id FROM wms.receipt r JOIN wms.primary_receipt_binding b ON b.receipt_id = r.id
      WHERE r.organization_id = NEW.organization_id AND r.number = NEW.doc_ref LOOP
      PERFORM wms.verify_primary_receipt_state(target_id);
    END LOOP;
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_primary_receipt_movements AFTER INSERT OR UPDATE OR DELETE ON wms.stock_movement
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION wms.check_primary_receipt_movement_trigger();
CREATE TRIGGER guard_bound_receipt_movement_truncate BEFORE TRUNCATE ON wms.stock_movement
FOR EACH STATEMENT EXECUTE FUNCTION wms.reject_bound_receipt_truncate();
CREATE TRIGGER guard_bound_receipt_truncate BEFORE TRUNCATE ON wms.receipt
FOR EACH STATEMENT EXECUTE FUNCTION wms.reject_bound_receipt_truncate();


-- Preserve receipt provenance independently of editable QC lines.
CREATE OR REPLACE FUNCTION wms.guard_production_receipt_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE d record;
DECLARE anchored boolean;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    SELECT EXISTS (SELECT 1 FROM production.output_confirmation WHERE event_id=OLD.source_event_id)
      INTO anchored;
    IF anchored THEN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Confirmed production receipt source is immutable'; END IF;
      IF ROW(NEW.id,NEW.source_event_id,NEW.source,NEW.entity_ref,NEW.organization_id,NEW.warehouse)
        IS DISTINCT FROM ROW(OLD.id,OLD.source_event_id,OLD.source,OLD.entity_ref,OLD.organization_id,OLD.warehouse)
        OR (coalesce(OLD.number,'')<>'' AND NEW.number IS DISTINCT FROM OLD.number)
        OR (OLD.status='accepted' AND NEW.status IS DISTINCT FROM OLD.status) THEN
        RAISE EXCEPTION 'Confirmed production receipt source is immutable';
      END IF;
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  END IF;
  SELECT doc.* INTO d FROM production.output_confirmation c
    JOIN production.output_document doc ON doc.id=c.document_id WHERE c.event_id=NEW.source_event_id;
  IF FOUND THEN
    IF NEW.organization_id IS DISTINCT FROM d.organization_id
      OR NEW.source IS DISTINCT FROM 'production'
      OR NEW.entity_ref IS DISTINCT FROM 'production_output:'||d.id
      OR NEW.warehouse IS DISTINCT FROM d.command->>'warehouse'
      OR (TG_OP='INSERT' AND NEW.status IS DISTINCT FROM 'pending_qc') THEN
      RAISE EXCEPTION 'Production receipt source differs from its confirmation';
    END IF;
  ELSIF NEW.entity_ref LIKE 'production_output:%'
    OR EXISTS (SELECT 1 FROM public.outbox_event WHERE id=NEW.source_event_id AND event_type='production.output.confirmed') THEN
    RAISE EXCEPTION 'Production receipt requires a confirmed output source';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_production_receipt_source BEFORE INSERT OR UPDATE OR DELETE ON wms.receipt
FOR EACH ROW EXECUTE FUNCTION wms.guard_production_receipt_source();

CREATE OR REPLACE FUNCTION wms.guard_production_receipt_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM wms.receipt r JOIN production.output_confirmation c ON c.event_id=r.source_event_id) THEN
    RAISE EXCEPTION 'Confirmed production receipt source is immutable';
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER guard_production_receipt_truncate BEFORE TRUNCATE ON wms.receipt
FOR EACH STATEMENT EXECUTE FUNCTION wms.guard_production_receipt_truncate();

CREATE OR REPLACE FUNCTION wms.guard_accepted_production_line() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_receipt integer;
DECLARE new_receipt integer;
DECLARE r record;
BEGIN
  IF TG_OP<>'INSERT' THEN old_receipt := OLD.receipt_id; END IF;
  IF TG_OP<>'DELETE' THEN new_receipt := NEW.receipt_id; END IF;
  -- Lock the header even while pending, then inspect its post-wait status.
  -- This serializes an external line edit with the receipt acceptance command.
  FOR r IN SELECT id,status,source_event_id FROM wms.receipt
    WHERE id IN (old_receipt,new_receipt) ORDER BY id FOR UPDATE LOOP
    IF r.status='accepted' AND EXISTS (SELECT 1 FROM production.output_confirmation c WHERE c.event_id=r.source_event_id) THEN
      RAISE EXCEPTION 'Accepted production receipt lines are immutable';
    END IF;
  END LOOP;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_accepted_production_line BEFORE INSERT OR UPDATE OR DELETE ON wms.receipt_line
FOR EACH ROW EXECUTE FUNCTION wms.guard_accepted_production_line();

CREATE OR REPLACE FUNCTION wms.guard_accepted_production_lines_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM wms.receipt r JOIN production.output_confirmation c ON c.event_id=r.source_event_id
    WHERE r.status='accepted') THEN
    RAISE EXCEPTION 'Accepted production receipt lines are immutable';
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER guard_accepted_production_lines_truncate BEFORE TRUNCATE ON wms.receipt_line
FOR EACH STATEMENT EXECUTE FUNCTION wms.guard_accepted_production_lines_truncate();


CREATE FUNCTION wms.reject_production_arrival_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Production arrival binding is immutable'; END $$;
CREATE TRIGGER immutable_production_arrival BEFORE UPDATE OR DELETE OR TRUNCATE ON wms.production_arrival
FOR EACH STATEMENT EXECUTE FUNCTION wms.reject_production_arrival_mutation();

CREATE FUNCTION wms.check_production_arrival_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r wms.receipt%ROWTYPE; l wms.receipt_line%ROWTYPE; m wms.stock_movement%ROWTYPE;
BEGIN
  SELECT * INTO r FROM wms.receipt WHERE id=NEW.receipt_id FOR UPDATE;
  IF NOT FOUND OR r.status<>'accepted' OR r.organization_id IS DISTINCT FROM NEW.organization_id
    OR r.source_event_id IS DISTINCT FROM NEW.event_id
    OR NOT EXISTS (SELECT 1 FROM production.output_confirmation WHERE event_id=NEW.event_id AND organization_id=NEW.organization_id) THEN
    RAISE EXCEPTION 'Production arrival receipt identity mismatch';
  END IF;
  SELECT * INTO l FROM wms.receipt_line WHERE id=NEW.line_id;
  IF NOT FOUND OR l.receipt_id IS DISTINCT FROM r.id
    OR (SELECT count(*) FROM wms.receipt_line WHERE receipt_id=r.id)<>1
    OR NEW.accepted_quantity IS DISTINCT FROM l.accepted_qty OR NEW.rejected_quantity IS DISTINCT FROM l.rejected_qty
    OR l.accepted_qty IS NULL OR l.rejected_qty IS NULL OR l.accepted_qty<0 OR l.rejected_qty<0
    OR l.accepted_qty+l.rejected_qty IS DISTINCT FROM l.expected_qty THEN
    RAISE EXCEPTION 'Production arrival QC mismatch';
  END IF;
  IF NEW.accepted_quantity=0 THEN
    IF NEW.movement_id IS NOT NULL THEN RAISE EXCEPTION 'Rejected output cannot have an arrival movement'; END IF;
  ELSE
    SELECT * INTO m FROM wms.stock_movement WHERE id=NEW.movement_id;
    IF NOT FOUND OR ROW(m.organization_id,m.doc_ref,m.reason,m.sku_code,m.warehouse,m.kind,m.qty,m.location_id,m.batch_ref)
      IS DISTINCT FROM ROW(r.organization_id,r.number,'receipt',l.sku_code,r.warehouse,'in',l.accepted_qty,l.location_id,l.batch_ref) THEN
      RAISE EXCEPTION 'Production arrival movement mismatch';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER check_production_arrival_insert BEFORE INSERT ON wms.production_arrival
FOR EACH ROW EXECUTE FUNCTION wms.check_production_arrival_insert();

CREATE FUNCTION wms.protect_production_arrival_movement() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='TRUNCATE' THEN
    IF EXISTS (SELECT 1 FROM wms.production_arrival WHERE movement_id IS NOT NULL) THEN
      RAISE EXCEPTION 'Production arrival movement is immutable'; END IF;
  ELSIF EXISTS (SELECT 1 FROM wms.production_arrival WHERE movement_id=OLD.id) THEN
    RAISE EXCEPTION 'Production arrival movement is immutable';
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER protect_production_arrival_movement BEFORE UPDATE OR DELETE ON wms.stock_movement
FOR EACH ROW EXECUTE FUNCTION wms.protect_production_arrival_movement();
CREATE TRIGGER protect_production_arrival_movement_truncate BEFORE TRUNCATE ON wms.stock_movement
FOR EACH STATEMENT EXECUTE FUNCTION wms.protect_production_arrival_movement();

CREATE FUNCTION wms.check_production_arrival_state(target_id integer) RETURNS void LANGUAGE plpgsql AS $$
DECLARE r wms.receipt%ROWTYPE; b wms.production_arrival%ROWTYPE;
BEGIN
  SELECT * INTO r FROM wms.receipt WHERE id=target_id;
  IF NOT FOUND OR NOT EXISTS (SELECT 1 FROM production.output_confirmation WHERE event_id=r.source_event_id) THEN RETURN; END IF;
  PERFORM 1 FROM accounting.organization WHERE id=r.organization_id FOR UPDATE;
  SELECT * INTO r FROM wms.receipt WHERE id=target_id FOR UPDATE;
  IF r.status='accepted' THEN
    SELECT * INTO b FROM wms.production_arrival WHERE receipt_id=r.id;
    IF NOT FOUND THEN RAISE EXCEPTION 'Accepted production receipt requires its arrival binding'; END IF;
    IF EXISTS (SELECT 1 FROM wms.stock_movement WHERE organization_id=r.organization_id
      AND doc_ref=r.number AND reason='receipt' AND id IS DISTINCT FROM b.movement_id) THEN
      RAISE EXCEPTION 'Production arrival has extra movements';
    END IF;
  ELSIF EXISTS (SELECT 1 FROM wms.stock_movement WHERE organization_id=r.organization_id AND doc_ref=r.number AND reason='receipt') THEN
    RAISE EXCEPTION 'Unaccepted production receipt cannot have arrival movements';
  END IF;
END $$;

CREATE FUNCTION wms.require_production_arrival() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM wms.check_production_arrival_state(NEW.id);
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER require_production_arrival AFTER INSERT OR UPDATE ON wms.receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION wms.require_production_arrival();

CREATE FUNCTION wms.check_production_movement_set() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r record;
BEGIN
  IF TG_OP<>'INSERT' THEN
    FOR r IN SELECT id FROM wms.receipt WHERE organization_id=OLD.organization_id AND number=OLD.doc_ref LOOP
      PERFORM wms.check_production_arrival_state(r.id);
    END LOOP;
  END IF;
  IF TG_OP<>'DELETE' THEN
    FOR r IN SELECT id FROM wms.receipt WHERE organization_id=NEW.organization_id AND number=NEW.doc_ref LOOP
      PERFORM wms.check_production_arrival_state(r.id);
    END LOOP;
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER check_production_movement_set AFTER INSERT OR UPDATE OR DELETE ON wms.stock_movement
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION wms.check_production_movement_set();


CREATE FUNCTION wms.reject_production_material_issue_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Production material issue binding is immutable';
END $$;
CREATE TRIGGER immutable_production_material_issue
BEFORE UPDATE OR DELETE OR TRUNCATE ON wms.production_material_issue
FOR EACH STATEMENT EXECUTE FUNCTION wms.reject_production_material_issue_mutation();

CREATE FUNCTION wms.check_production_material_issue_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE own production.order_ownership%ROWTYPE; m wms.stock_movement%ROWTYPE; cmd jsonb; snap jsonb;
BEGIN
  SELECT * INTO own FROM production.order_ownership
  WHERE order_id=NEW.order_id FOR UPDATE;
  IF NOT FOUND OR own.organization_id IS DISTINCT FROM NEW.organization_id THEN
    RAISE EXCEPTION 'Production material issue order ownership mismatch';
  END IF;
  IF NEW.request_key !~ '^[0-9a-fA-F-]{36}$' THEN
    RAISE EXCEPTION 'Production material issue request key is not a UUID';
  END IF;
  cmd := to_jsonb(NEW.snapshot)->'command';
  snap := to_jsonb(NEW.snapshot)->'order_snapshot';
  IF cmd IS NULL OR snap IS NULL
    OR cmd->>'request_id' IS DISTINCT FROM NEW.request_key
    OR cmd->>'order_id' IS DISTINCT FROM NEW.order_id::text
    OR cmd->>'expected_order_digest' IS DISTINCT FROM own.digest
    OR cmd->>'operation_date' IS DISTINCT FROM NEW.operation_date::text
    OR snap IS DISTINCT FROM to_jsonb(own.snapshot) THEN
    RAISE EXCEPTION 'Production material issue command snapshot mismatch';
  END IF;
  SELECT * INTO m FROM wms.stock_movement WHERE id=NEW.movement_id;
  IF NOT FOUND OR m.organization_id IS DISTINCT FROM NEW.organization_id
    OR ROW(m.sku_code,m.warehouse,m.kind,m.qty,m.reason,m.location_id,m.batch_ref,m.doc_ref,m.note)
      IS DISTINCT FROM ROW(cmd->>'sku_code',cmd->>'warehouse','out',(cmd->>'quantity')::numeric,
                           'production_issue',NULLIF(cmd->>'location_id','')::integer,cmd->>'lot',
                           'production_material:'||NEW.request_key,cmd->>'evidence') THEN
    RAISE EXCEPTION 'Production material issue movement mismatch';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER check_production_material_issue_insert
BEFORE INSERT ON wms.production_material_issue
FOR EACH ROW EXECUTE FUNCTION wms.check_production_material_issue_insert();

CREATE FUNCTION wms.protect_production_material_issue_movement() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='TRUNCATE' THEN
    IF EXISTS (SELECT 1 FROM wms.production_material_issue) THEN
      RAISE EXCEPTION 'Production material issue movement is immutable';
    END IF;
  ELSIF EXISTS (SELECT 1 FROM wms.production_material_issue WHERE movement_id=OLD.id) THEN
    RAISE EXCEPTION 'Production material issue movement is immutable';
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER protect_production_material_issue_movement
BEFORE UPDATE OR DELETE ON wms.stock_movement
FOR EACH ROW EXECUTE FUNCTION wms.protect_production_material_issue_movement();
CREATE TRIGGER protect_production_material_issue_movement_truncate
BEFORE TRUNCATE ON wms.stock_movement
FOR EACH STATEMENT EXECUTE FUNCTION wms.protect_production_material_issue_movement();

CREATE FUNCTION wms.check_production_material_issue_state(target_id integer) RETURNS void LANGUAGE plpgsql AS $$
DECLARE m wms.stock_movement%ROWTYPE;
BEGIN
  SELECT * INTO m FROM wms.stock_movement WHERE id=target_id;
  IF NOT FOUND OR m.reason <> 'production_issue' OR m.doc_ref NOT LIKE 'production_material:%' THEN RETURN; END IF;
  IF NOT EXISTS (SELECT 1 FROM wms.production_material_issue WHERE movement_id=m.id) THEN
    RAISE EXCEPTION 'Production material movement requires its immutable source binding';
  END IF;
END $$;

CREATE FUNCTION wms.require_production_material_issue_binding() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    IF OLD.reason='production_issue' AND OLD.doc_ref LIKE 'production_material:%'
      AND EXISTS (SELECT 1 FROM wms.production_material_issue WHERE movement_id=OLD.id) THEN
      RAISE EXCEPTION 'Production material movement is bound and cannot be deleted';
    END IF;
  ELSE
    PERFORM wms.check_production_material_issue_state(NEW.id);
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER require_production_material_issue_binding
AFTER INSERT OR UPDATE OR DELETE ON wms.stock_movement
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION wms.require_production_material_issue_binding();


CREATE FUNCTION accounting.guard_production_material_issue_receipt_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE issue_row wms.production_material_issue%ROWTYPE; m wms.stock_movement%ROWTYPE;
        e accounting.entry%ROWTYPE; p accounting.policy%ROWTYPE; source_request_key text;
        debit accounting.line%ROWTYPE; credit accounting.line%ROWTYPE;
BEGIN
  IF NEW.command::jsonb->>'source' NOT LIKE 'production:material:%' THEN RETURN NEW; END IF;
  source_request_key := split_part(NEW.command::jsonb->>'source', ':', 4);
  SELECT issue.* INTO issue_row FROM wms.production_material_issue AS issue
    WHERE issue.organization_id=NEW.organization_id AND issue.request_key=source_request_key FOR UPDATE;
  SELECT * INTO m FROM wms.stock_movement WHERE id=issue_row.movement_id;
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  SELECT * INTO p FROM accounting.policy WHERE id=e.policy_id;
  IF NOT FOUND OR issue_row.id IS NULL OR m.id IS NULL OR e.id IS NULL OR p.id IS NULL
    OR e.organization_id IS DISTINCT FROM NEW.organization_id
    OR e.operation IS DISTINCT FROM 'inventory_issue'
    OR e.source IS DISTINCT FROM NEW.command::jsonb->>'source'
    OR e.source_version IS DISTINCT FROM 1
    OR e.rule_version NOT LIKE 'inventory-issue-v2:%'
    OR e.operation_date IS DISTINCT FROM issue_row.operation_date
    OR NEW.command::jsonb->>'operation_date' IS DISTINCT FROM issue_row.operation_date::text
    OR NEW.command::jsonb->>'order_id' IS NOT NULL
    OR NEW.command::jsonb->>'warehouse' IS DISTINCT FROM m.warehouse
    OR NEW.command::jsonb->>'sku' IS DISTINCT FROM m.sku_code
    OR NEW.command::jsonb->>'lot' IS DISTINCT FROM m.batch_ref
    OR (NEW.command::jsonb->>'quantity')::numeric IS DISTINCT FROM m.qty
    OR m.kind IS DISTINCT FROM 'out' OR m.reason IS DISTINCT FROM 'production_issue'
    OR NEW.command::jsonb->>'expense_account' IS DISTINCT FROM p.production_costing::jsonb->>'wip_account'
    OR jsonb_typeof(NEW.command::jsonb->'expense_dimensions') IS DISTINCT FROM 'object'
    OR NOT (NEW.command::jsonb->'expense_dimensions' ? 'department')
    OR NOT (NEW.command::jsonb->'expense_dimensions' ? 'order') THEN
    RAISE EXCEPTION 'Production material issue receipt is not bound to its reviewed WMS source';
  END IF;
  SELECT * INTO debit FROM accounting.line WHERE entry_id=e.id AND side='debit';
  SELECT * INTO credit FROM accounting.line WHERE entry_id=e.id AND side='credit';
  IF debit.id IS NULL OR credit.id IS NULL
    OR (SELECT count(*) FROM accounting.line WHERE entry_id=e.id)<>2
    OR debit.account_code IS DISTINCT FROM NEW.command::jsonb->>'expense_account'
    OR debit.dimensions::jsonb IS DISTINCT FROM NEW.command::jsonb->'expense_dimensions'
    OR credit.account_code IS DISTINCT FROM NEW.command::jsonb->>'account'
    OR credit.quantity IS DISTINCT FROM (NEW.command::jsonb->>'quantity')::numeric
    OR credit.dimensions->>'warehouse' IS DISTINCT FROM m.warehouse
    OR credit.dimensions->>'sku' IS DISTINCT FROM m.sku_code
    OR credit.dimensions->>'lot' IS DISTINCT FROM m.batch_ref
    OR debit.amount IS DISTINCT FROM credit.amount
    OR NEW.cost::jsonb->>'issue_cost_byn' IS NULL
    OR (NEW.cost::jsonb->>'issue_cost_byn')::numeric IS DISTINCT FROM credit.amount
    OR NEW.cost::jsonb->'inventory_dimensions' IS DISTINCT FROM credit.dimensions::jsonb THEN
    RAISE EXCEPTION 'Production material issue ledger lines differ from its reviewed source';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_production_material_issue_receipt
BEFORE INSERT ON accounting.inventory_issue_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_production_material_issue_receipt_insert();

CREATE OR REPLACE FUNCTION accounting.check_production_material_issue_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer; e accounting.entry%ROWTYPE; r accounting.inventory_issue_receipt%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF e.operation IS DISTINCT FROM 'inventory_issue' OR e.source NOT LIKE 'production:material:%' THEN RETURN NULL; END IF;
  SELECT * INTO r FROM accounting.inventory_issue_receipt WHERE entry_id=target;
  IF NOT FOUND THEN RAISE EXCEPTION 'Production material issue requires its complete source receipt'; END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_production_material_issue_entry
AFTER INSERT ON accounting.entry DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_production_material_issue_complete();
CREATE CONSTRAINT TRIGGER complete_production_material_issue_receipt
AFTER INSERT ON accounting.inventory_issue_receipt DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_production_material_issue_complete();


-- Unallocated proposal guard: verified payroll imports are append-only and
-- cannot be admitted without their matching reviewed ledger package.
CREATE OR REPLACE FUNCTION accounting.guard_production_labor_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; debit_count integer; credit_count integer;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  IF NOT FOUND OR e.organization_id IS DISTINCT FROM NEW.organization_id
     OR e.operation IS DISTINCT FROM 'production_labor_import'
     OR e.source IS DISTINCT FROM 'production:labor:'||NEW.organization_id||':'||NEW.source_document
     OR e.source_version <> 1 OR to_char(e.posting_date,'YYYY-MM') IS DISTINCT FROM NEW.month
     OR e.digest IS DISTINCT FROM NEW.digest
     OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
     OR NEW.command->>'source_document' IS DISTINCT FROM NEW.source_document
     OR (NEW.command->>'source_version')::integer IS DISTINCT FROM NEW.source_version
     OR NEW.command->>'source_digest' IS DISTINCT FROM NEW.source_digest
     OR NEW.source->>'source_document' IS DISTINCT FROM NEW.source_document
     OR (NEW.source->>'source_version')::integer IS DISTINCT FROM NEW.source_version
     OR NEW.source->>'source_digest' IS DISTINCT FROM NEW.source_digest
     OR NEW.posting IS NULL THEN
    RAISE EXCEPTION 'Production labor receipt does not match its ledger entry';
  END IF;
  SELECT count(*) FILTER (WHERE side='debit'), count(*) FILTER (WHERE side='credit')
    INTO debit_count, credit_count FROM accounting.line WHERE entry_id=NEW.entry_id;
  IF debit_count < 1 OR credit_count < 1 OR debit_count <> credit_count THEN
    RAISE EXCEPTION 'Production labor import must contain paired debit and credit lines';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER guard_production_labor_receipt
BEFORE INSERT ON accounting.production_labor_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_production_labor_receipt();

CREATE TRIGGER immutable_production_labor_receipt
BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.production_labor_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE OR REPLACE FUNCTION accounting.check_production_labor_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer; e accounting.entry%ROWTYPE; r accounting.production_labor_receipt%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF e.operation IS DISTINCT FROM 'production_labor_import' THEN RETURN NULL; END IF;
  SELECT * INTO r FROM accounting.production_labor_receipt WHERE entry_id=target;
  IF NOT FOUND THEN RAISE EXCEPTION 'Production labor import requires its complete source receipt'; END IF;
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER complete_production_labor_entry
AFTER INSERT ON accounting.entry DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_production_labor_complete();
CREATE CONSTRAINT TRIGGER complete_production_labor_receipt
AFTER INSERT ON accounting.production_labor_receipt DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_production_labor_complete();


-- Unallocated proposal guard: an interim gross-payroll import is admitted
-- only together with its immutable, source-bound ledger package.
CREATE OR REPLACE FUNCTION accounting.guard_payroll_accrual_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; debit_count integer; credit_count integer;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  IF NOT FOUND OR e.organization_id IS DISTINCT FROM NEW.organization_id
     OR e.operation IS DISTINCT FROM 'payroll_accrual_import'
     OR e.source IS DISTINCT FROM 'payroll:accrual:'||NEW.organization_id||':'||NEW.source_document
     OR e.source_version IS DISTINCT FROM NEW.source_version
     OR to_char(e.posting_date,'YYYY-MM') IS DISTINCT FROM NEW.month
     OR e.digest IS DISTINCT FROM NEW.digest
     OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
     OR NEW.command->>'source_document' IS DISTINCT FROM NEW.source_document
     OR (NEW.command->>'source_version')::integer IS DISTINCT FROM NEW.source_version
     OR NEW.command->>'source_digest' IS DISTINCT FROM NEW.source_digest
     OR NEW.source->>'source_document' IS DISTINCT FROM NEW.source_document
     OR (NEW.source->>'source_version')::integer IS DISTINCT FROM NEW.source_version
     OR NEW.source->>'source_digest' IS DISTINCT FROM NEW.source_digest
     OR NEW.posting IS NULL THEN
    RAISE EXCEPTION 'Payroll accrual receipt does not match its ledger entry';
  END IF;
  SELECT count(*) FILTER (WHERE side='debit'), count(*) FILTER (WHERE side='credit')
    INTO debit_count, credit_count FROM accounting.line WHERE entry_id=NEW.entry_id;
  IF debit_count < 1 OR credit_count < 1 OR debit_count <> credit_count THEN
    RAISE EXCEPTION 'Payroll accrual import must contain paired debit and credit lines';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER guard_payroll_accrual_receipt
BEFORE INSERT ON accounting.payroll_accrual_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_payroll_accrual_receipt();

CREATE TRIGGER immutable_payroll_accrual_receipt
BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.payroll_accrual_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE OR REPLACE FUNCTION accounting.check_payroll_accrual_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer; e accounting.entry%ROWTYPE; r accounting.payroll_accrual_receipt%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF e.operation IS DISTINCT FROM 'payroll_accrual_import' THEN RETURN NULL; END IF;
  SELECT * INTO r FROM accounting.payroll_accrual_receipt WHERE entry_id=target;
  IF NOT FOUND THEN RAISE EXCEPTION 'Payroll accrual import requires its complete source receipt'; END IF;
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER complete_payroll_accrual_entry
AFTER INSERT ON accounting.entry DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_payroll_accrual_complete();
CREATE CONSTRAINT TRIGGER complete_payroll_accrual_receipt
AFTER INSERT ON accounting.payroll_accrual_receipt DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_payroll_accrual_complete();

-- A reviewed statutory payroll package is source-bound in the same way as a
-- gross accrual package.  The amounts are imported from evidence; no rate or
-- statutory-report calculation is implied by this receipt.
CREATE OR REPLACE FUNCTION accounting.guard_payroll_statutory_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; debit_count integer; credit_count integer;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  IF NOT FOUND OR e.organization_id IS DISTINCT FROM NEW.organization_id
     OR e.operation IS DISTINCT FROM 'payroll_statutory_import'
     OR e.source IS DISTINCT FROM 'payroll:statutory:'||NEW.organization_id||':'||NEW.source_document
     OR e.source_version IS DISTINCT FROM NEW.source_version
     OR to_char(e.posting_date,'YYYY-MM') IS DISTINCT FROM NEW.month
     OR e.digest IS DISTINCT FROM NEW.digest
     OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
     OR NEW.command->>'source_document' IS DISTINCT FROM NEW.source_document
     OR (NEW.command->>'source_version')::integer IS DISTINCT FROM NEW.source_version
     OR NEW.command->>'source_digest' IS DISTINCT FROM NEW.source_digest
     OR NEW.source->>'source_document' IS DISTINCT FROM NEW.source_document
     OR (NEW.source->>'source_version')::integer IS DISTINCT FROM NEW.source_version
     OR NEW.source->>'source_digest' IS DISTINCT FROM NEW.source_digest
     OR NEW.posting IS NULL THEN
    RAISE EXCEPTION 'Payroll statutory receipt does not match its ledger entry';
  END IF;
  SELECT count(*) FILTER (WHERE side='debit'), count(*) FILTER (WHERE side='credit')
    INTO debit_count, credit_count FROM accounting.line WHERE entry_id=NEW.entry_id;
  IF debit_count < 1 OR credit_count < 1 OR debit_count <> credit_count THEN
    RAISE EXCEPTION 'Payroll statutory import must contain paired debit and credit lines';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER guard_payroll_statutory_receipt
BEFORE INSERT ON accounting.payroll_statutory_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_payroll_statutory_receipt();

CREATE TRIGGER immutable_payroll_statutory_receipt
BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.payroll_statutory_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE OR REPLACE FUNCTION accounting.check_payroll_statutory_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer; e accounting.entry%ROWTYPE; r accounting.payroll_statutory_receipt%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF e.operation IS DISTINCT FROM 'payroll_statutory_import' THEN RETURN NULL; END IF;
  SELECT * INTO r FROM accounting.payroll_statutory_receipt WHERE entry_id=target;
  IF NOT FOUND THEN RAISE EXCEPTION 'Payroll statutory import requires its complete source receipt'; END IF;
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER complete_payroll_statutory_entry
AFTER INSERT ON accounting.entry DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_payroll_statutory_complete();
CREATE CONSTRAINT TRIGGER complete_payroll_statutory_receipt
AFTER INSERT ON accounting.payroll_statutory_receipt DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_payroll_statutory_complete();


-- Proposal-only PostgreSQL guards for the explicit input-VAT register.
-- The source document and ledger line are immutable snapshots; no deduction is
-- created by this table.  Do not register this file as a production migration
-- without an operator-assigned migration revision.

CREATE OR REPLACE FUNCTION accounting.reject_input_vat_register_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Input VAT register history is immutable';
END;
$$;

CREATE TRIGGER input_vat_register_immutable
BEFORE UPDATE OR DELETE ON accounting.input_vat_register_entry
FOR EACH ROW EXECUTE FUNCTION accounting.reject_input_vat_register_mutation();

CREATE TRIGGER input_vat_register_no_truncate
BEFORE TRUNCATE ON accounting.input_vat_register_entry
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_input_vat_register_mutation();

CREATE OR REPLACE FUNCTION accounting.check_input_vat_register_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; l accounting.line%ROWTYPE;
BEGIN
  SELECT * INTO STRICT e FROM accounting.entry WHERE id = NEW.entry_id;
  SELECT * INTO STRICT l FROM accounting.line WHERE id = NEW.line_id;
  IF e.organization_id <> NEW.organization_id OR l.entry_id <> e.id
     OR NEW.source <> e.source OR NEW.source_version <> e.source_version
     OR NEW.entry_digest <> e.digest OR NEW.posting_date <> e.posting_date
     OR l.account_code !~ '^18(\.|$)' OR l.amount <> NEW.amount
     OR l.currency <> NEW.currency OR l.side <> NEW.side THEN
    RAISE EXCEPTION 'Input VAT register source does not match its posted line';
  END IF;
  IF NEW.tax_period !~ '^[0-9]{4}-(0[1-9]|1[0-2])$' THEN
    RAISE EXCEPTION 'Invalid input VAT tax period';
  END IF;
  IF NEW.eschf_status = 'provided' AND nullif(btrim(NEW.eschf_identifier), '') IS NULL THEN
    RAISE EXCEPTION 'Provided ЭСЧФ requires an identifier';
  END IF;
  IF NEW.eschf_status <> 'provided' AND NEW.eschf_identifier IS NOT NULL THEN
    RAISE EXCEPTION 'ЭСЧФ identifier requires provided status';
  END IF;
  IF NEW.deduction_status = 'eligible'
     AND NEW.eschf_status NOT IN ('provided', 'not_required') THEN
    RAISE EXCEPTION 'Eligible input VAT requires explicit ЭСЧФ status';
  END IF;
  IF NEW.side = 'credit' AND NEW.deduction_status = 'eligible' THEN
    RAISE EXCEPTION 'Credit input VAT line cannot be eligible';
  END IF;
  RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER input_vat_register_source_consistency
AFTER INSERT ON accounting.input_vat_register_entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.check_input_vat_register_source();


-- Proposal-only PostgreSQL guards for the accrued-output-VAT register.

CREATE OR REPLACE FUNCTION accounting.reject_output_vat_register_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Output VAT register history is immutable';
END;
$$;

CREATE TRIGGER output_vat_register_immutable
BEFORE UPDATE OR DELETE ON accounting.output_vat_register_entry
FOR EACH ROW EXECUTE FUNCTION accounting.reject_output_vat_register_mutation();

CREATE TRIGGER output_vat_register_no_truncate
BEFORE TRUNCATE ON accounting.output_vat_register_entry
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_output_vat_register_mutation();

CREATE OR REPLACE FUNCTION accounting.check_output_vat_register_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; l accounting.line%ROWTYPE;
BEGIN
  SELECT * INTO STRICT e FROM accounting.entry WHERE id = NEW.entry_id;
  SELECT * INTO STRICT l FROM accounting.line WHERE id = NEW.line_id;
  IF e.organization_id <> NEW.organization_id OR l.entry_id <> e.id
     OR NEW.source <> e.source OR NEW.source_version <> e.source_version
     OR NEW.entry_digest <> e.digest OR NEW.posting_date <> e.posting_date
     OR l.account_code !~ '^90[.]2([.]|$)' OR l.side <> 'debit' OR l.amount <> NEW.amount
     OR l.currency <> NEW.currency THEN
    RAISE EXCEPTION 'Output VAT register source does not match its posted 90.2 line';
  END IF;
  IF NEW.tax_period !~ '^[0-9]{4}-(0[1-9]|1[0-2])$' THEN
    RAISE EXCEPTION 'Invalid output VAT tax period';
  END IF;
  IF NEW.eschf_status = 'provided' AND nullif(btrim(NEW.eschf_identifier), '') IS NULL THEN
    RAISE EXCEPTION 'Provided ЭСЧФ requires an identifier';
  END IF;
  IF NEW.eschf_status <> 'provided' AND NEW.eschf_identifier IS NOT NULL THEN
    RAISE EXCEPTION 'ЭСЧФ identifier requires provided status';
  END IF;
  IF NEW.tax_treatment = 'zero_export' AND nullif(btrim(NEW.export_evidence), '') IS NULL THEN
    RAISE EXCEPTION 'Zero-export treatment requires export evidence';
  END IF;
  IF NEW.tax_treatment <> 'zero_export' AND NEW.export_evidence IS NOT NULL THEN
    RAISE EXCEPTION 'Export evidence is allowed only for zero-export treatment';
  END IF;
  RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER output_vat_register_source_consistency
AFTER INSERT ON accounting.output_vat_register_entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.check_output_vat_register_source();


-- Proposal-only PostgreSQL guards for the explicit import/export register.
CREATE OR REPLACE FUNCTION accounting.reject_foreign_trade_register_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Foreign-trade register history is immutable';
END $$;

CREATE TRIGGER immutable_foreign_trade_register
BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.foreign_trade_register_entry
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_foreign_trade_register_mutation();

CREATE OR REPLACE FUNCTION accounting.guard_foreign_trade_register_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; l accounting.line%ROWTYPE;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  SELECT * INTO l FROM accounting.line WHERE id=NEW.line_id;
  IF NOT FOUND OR e.id IS DISTINCT FROM NEW.entry_id OR l.entry_id IS DISTINCT FROM NEW.entry_id
     OR e.organization_id IS DISTINCT FROM NEW.organization_id
     OR e.digest IS DISTINCT FROM NEW.entry_digest
     OR e.source IS DISTINCT FROM NEW.source OR e.source_version IS DISTINCT FROM NEW.source_version
     OR l.currency IS DISTINCT FROM NEW.currency OR l.amount IS DISTINCT FROM NEW.amount
     OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
     OR NEW.command->>'entry_id' IS DISTINCT FROM NEW.entry_id::text
     OR NEW.command->>'line_id' IS DISTINCT FROM NEW.line_id::text
     OR NEW.command->>'expected_entry_digest' IS DISTINCT FROM NEW.entry_digest
     OR NEW.command->>'trade_mode' IS DISTINCT FROM NEW.trade_mode
     OR NEW.command->>'tax_period' IS DISTINCT FROM NEW.tax_period THEN
    RAISE EXCEPTION 'Foreign-trade register source does not match its posted line';
  END IF;
  IF NEW.trade_mode NOT IN ('eaeu_import','third_country_import','export')
     OR NEW.tax_period !~ '^[0-9]{4}-(0[1-9]|1[0-2])$'
     OR NEW.amount <= 0 OR NEW.customs_duty < 0 OR NEW.import_vat < 0 THEN
    RAISE EXCEPTION 'Invalid foreign-trade register metadata';
  END IF;
  IF NEW.trade_mode IN ('eaeu_import','third_country_import') AND NEW.incoterms IS NULL THEN
    RAISE EXCEPTION 'Import trade evidence requires Incoterms';
  END IF;
  IF NEW.trade_mode = 'eaeu_import' AND NEW.eaeu_reference IS NULL THEN
    RAISE EXCEPTION 'EAEU trade evidence requires its document reference';
  END IF;
  IF NEW.trade_mode IN ('third_country_import','export') AND NEW.customs_reference IS NULL THEN
    RAISE EXCEPTION 'This trade lane requires a customs reference';
  END IF;
  IF NEW.trade_mode = 'export' AND (NEW.export_evidence IS NULL OR NEW.import_vat <> 0 OR NEW.customs_duty <> 0) THEN
    RAISE EXCEPTION 'Export trade evidence has invalid customs or transport data';
  END IF;
  IF NEW.trade_mode = 'export' THEN
    IF l.side <> 'credit' OR (l.account_code <> '90.1' AND l.account_code NOT LIKE '90.1.%') THEN
      RAISE EXCEPTION 'Export evidence must bind to a credit 90.1 source line';
    END IF;
  ELSIF l.side <> 'debit' OR NOT (l.account_code IN ('10','18','20','41')
         OR l.account_code LIKE '10.%' OR l.account_code LIKE '18.%'
         OR l.account_code LIKE '20.%' OR l.account_code LIKE '41.%') THEN
    RAISE EXCEPTION 'Import evidence must bind to a debit inventory or input-VAT source line';
  END IF;
  IF NEW.currency = 'BYN' THEN
    IF NEW.original_amount IS NOT NULL OR NEW.rate IS NOT NULL OR NEW.rate_scale IS NOT NULL
       OR NEW.rate_date IS NOT NULL OR NEW.rate_source IS NOT NULL
       OR l.original_amount IS NOT NULL OR l.rate IS NOT NULL OR l.rate_scale IS NOT NULL
       OR l.rate_date IS NOT NULL OR l.rate_source IS NOT NULL THEN
      RAISE EXCEPTION 'BYN trade evidence cannot carry FX metadata';
    END IF;
  ELSE
    IF NEW.original_amount IS NULL OR NEW.rate IS NULL OR NEW.rate_scale IS NULL
       OR NEW.rate_date IS NULL OR NEW.rate_source IS NULL
       OR l.original_amount IS DISTINCT FROM NEW.original_amount
       OR l.rate IS DISTINCT FROM NEW.rate OR l.rate_scale IS DISTINCT FROM NEW.rate_scale
       OR l.rate_date IS DISTINCT FROM NEW.rate_date OR l.rate_source IS DISTINCT FROM NEW.rate_source THEN
      RAISE EXCEPTION 'Foreign-currency trade evidence does not match the posted rate source';
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE CONSTRAINT TRIGGER foreign_trade_register_insert_guard
AFTER INSERT ON accounting.foreign_trade_register_entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.guard_foreign_trade_register_insert();


-- Proposal-only guards for the fixed-asset register and straight-line
-- depreciation receipt.  Allocate a migration revision only after review.

CREATE OR REPLACE FUNCTION accounting.reject_fixed_asset_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Fixed-asset history is immutable: %', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER fixed_asset_register_immutable
BEFORE UPDATE OR DELETE ON accounting.fixed_asset_register_entry
FOR EACH ROW EXECUTE FUNCTION accounting.reject_fixed_asset_mutation();

CREATE TRIGGER fixed_asset_register_no_truncate
BEFORE TRUNCATE ON accounting.fixed_asset_register_entry
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_fixed_asset_mutation();

CREATE TRIGGER fixed_asset_depreciation_immutable
BEFORE UPDATE OR DELETE ON accounting.fixed_asset_depreciation_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.reject_fixed_asset_mutation();

CREATE TRIGGER fixed_asset_depreciation_no_truncate
BEFORE TRUNCATE ON accounting.fixed_asset_depreciation_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_fixed_asset_mutation();

CREATE OR REPLACE FUNCTION accounting.check_fixed_asset_register_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; l accounting.line%ROWTYPE; p accounting.policy%ROWTYPE;
BEGIN
  SELECT * INTO STRICT e FROM accounting.entry WHERE id=NEW.source_entry_id;
  SELECT * INTO STRICT l FROM accounting.line WHERE id=NEW.source_line_id;
  SELECT * INTO STRICT p FROM accounting.policy WHERE id=e.policy_id;
  IF e.organization_id IS DISTINCT FROM NEW.organization_id
     OR l.entry_id IS DISTINCT FROM e.id
     OR e.digest IS DISTINCT FROM NEW.source_digest
     OR l.account_code IS DISTINCT FROM NEW.asset_account
     OR l.side IS DISTINCT FROM 'debit'
     OR l.amount IS DISTINCT FROM NEW.cost
     OR l.currency IS DISTINCT FROM 'BYN'
     OR split_part(NEW.asset_account, '.', 1) <> '01'
     OR split_part(NEW.accumulated_account, '.', 1) <> '02'
     OR p.depreciation_method IS DISTINCT FROM NEW.depreciation_method THEN
    RAISE EXCEPTION 'Fixed-asset register source does not match its posted acquisition';
  END IF;
  IF NEW.commissioning_date < NEW.acquisition_date
     OR NEW.depreciation_start < NEW.commissioning_date
     OR NEW.residual_value < 0 OR NEW.residual_value > NEW.cost
     OR NEW.useful_life_months <= 0 THEN
    RAISE EXCEPTION 'Invalid fixed-asset dates or cost bounds';
  END IF;
  RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER fixed_asset_register_source_consistency
AFTER INSERT ON accounting.fixed_asset_register_entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.check_fixed_asset_register_source();

CREATE OR REPLACE FUNCTION accounting.check_fixed_asset_depreciation_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; a accounting.fixed_asset_register_entry%ROWTYPE;
BEGIN
  SELECT * INTO STRICT e FROM accounting.entry WHERE id=NEW.entry_id;
  SELECT * INTO STRICT a FROM accounting.fixed_asset_register_entry WHERE id=NEW.asset_id;
  IF e.organization_id IS DISTINCT FROM NEW.organization_id
     OR a.organization_id IS DISTINCT FROM NEW.organization_id
     OR e.operation IS DISTINCT FROM 'fixed_asset_depreciation'
     OR e.source IS DISTINCT FROM 'fixed-asset:depreciation:'||NEW.organization_id||':'||a.asset_key||':'||NEW.month
     OR e.source_version <> 1 OR e.digest IS DISTINCT FROM NEW.digest
     OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
     OR NEW.command->>'month' IS DISTINCT FROM NEW.month
     OR NEW.calculation->>'method' IS DISTINCT FROM 'straight_line' THEN
    RAISE EXCEPTION 'Fixed-asset depreciation receipt does not match its ledger entry';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER fixed_asset_depreciation_source_consistency
BEFORE INSERT ON accounting.fixed_asset_depreciation_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.check_fixed_asset_depreciation_receipt();

CREATE OR REPLACE FUNCTION accounting.check_fixed_asset_depreciation_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer; e accounting.entry%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF e.operation IS DISTINCT FROM 'fixed_asset_depreciation' THEN RETURN NULL; END IF;
  IF NOT EXISTS (SELECT 1 FROM accounting.fixed_asset_depreciation_receipt WHERE entry_id=target) THEN
    RAISE EXCEPTION 'Fixed-asset depreciation requires its complete receipt';
  END IF;
  RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER fixed_asset_depreciation_complete_entry
AFTER INSERT ON accounting.entry DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_fixed_asset_depreciation_complete();

CREATE CONSTRAINT TRIGGER fixed_asset_depreciation_complete_receipt
AFTER INSERT ON accounting.fixed_asset_depreciation_receipt DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_fixed_asset_depreciation_complete();


-- Proposal-only guards for reviewed paid and warranty repair packages.

CREATE OR REPLACE FUNCTION accounting.guard_repair_accounting_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; debit_count integer; credit_count integer;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  IF NOT FOUND OR e.organization_id IS DISTINCT FROM NEW.organization_id
     OR e.operation IS DISTINCT FROM 'repair_service'
     OR e.source IS DISTINCT FROM 'service:repair:'||NEW.organization_id||':'||NEW.service_request_id
     OR e.source_version IS DISTINCT FROM NEW.source_version
     OR e.digest IS DISTINCT FROM NEW.digest
     OR to_char(e.posting_date,'YYYY-MM') IS DISTINCT FROM NEW.month
     OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
     OR (NEW.command->>'service_request_id')::integer IS DISTINCT FROM NEW.service_request_id
     OR (NEW.command->>'source_version')::integer IS DISTINCT FROM NEW.source_version
     OR NEW.command->>'source_digest' IS DISTINCT FROM NEW.source_digest
     OR NEW.command->>'serial_number' IS DISTINCT FROM NEW.serial_number
     OR NEW.command->>'owner_type' IS DISTINCT FROM NEW.owner_type
     OR NEW.command->>'owner_reference' IS DISTINCT FROM NEW.owner_reference
     OR NEW.command->>'coverage' IS DISTINCT FROM NEW.coverage
     OR NEW.source->>'scope' IS DISTINCT FROM 'repair_accounting'
     OR (NEW.source->>'service_request_id')::integer IS DISTINCT FROM NEW.service_request_id
     OR NEW.source->>'source_digest' IS DISTINCT FROM NEW.source_digest
     OR NEW.source->>'serial_number' IS DISTINCT FROM NEW.serial_number
     OR NEW.source->>'owner_type' IS DISTINCT FROM NEW.owner_type
     OR NEW.source->>'owner_reference' IS DISTINCT FROM NEW.owner_reference
     OR NEW.source->>'coverage' IS DISTINCT FROM NEW.coverage
     OR NEW.posting IS NULL THEN
    RAISE EXCEPTION 'Repair accounting receipt does not match its ledger entry';
  END IF;
  SELECT count(*) FILTER (WHERE side='debit'), count(*) FILTER (WHERE side='credit')
    INTO debit_count, credit_count FROM accounting.line WHERE entry_id=NEW.entry_id;
  IF debit_count < 1 OR credit_count < 1 OR debit_count <> credit_count THEN
    RAISE EXCEPTION 'Repair accounting package must contain balanced debit and credit lines';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements(NEW.command::jsonb->'lines') line
    WHERE line->>'material_owner'='customer'
      AND ((line->>'amount_byn')::numeric <> 0 OR line->>'debit_account' IS NOT NULL
           OR line->>'credit_account' IS NOT NULL)
  ) THEN
    RAISE EXCEPTION 'Customer-owned repair materials cannot carry an owned accounting value';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER guard_repair_accounting_receipt
BEFORE INSERT ON accounting.repair_accounting_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_repair_accounting_receipt();

CREATE TRIGGER immutable_repair_accounting_receipt
BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.repair_accounting_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE OR REPLACE FUNCTION accounting.check_repair_accounting_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer; e accounting.entry%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF e.operation IS DISTINCT FROM 'repair_service' THEN RETURN NULL; END IF;
  IF NOT EXISTS (SELECT 1 FROM accounting.repair_accounting_receipt WHERE entry_id=target) THEN
    RAISE EXCEPTION 'Repair service posting requires its complete source receipt';
  END IF;
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER complete_repair_accounting_entry
AFTER INSERT ON accounting.entry DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_repair_accounting_complete();

CREATE CONSTRAINT TRIGGER complete_repair_accounting_receipt
AFTER INSERT ON accounting.repair_accounting_receipt DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_repair_accounting_complete();


CREATE TRIGGER immutable_order_completion BEFORE UPDATE OR DELETE OR TRUNCATE ON production.order_completion
FOR EACH STATEMENT EXECUTE FUNCTION production.reject_order_ownership_mutation();

CREATE FUNCTION production.check_order_completion_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE o production.production_order%ROWTYPE; total numeric; accepted numeric; rejected numeric; missing integer; earliest date;
DECLARE documents jsonb; unit_name text; unit_count integer; sku_code text; lot_value text; lot_count integer; expected jsonb;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  SELECT * INTO o FROM production.production_order WHERE id=NEW.order_id FOR UPDATE;
  IF NOT FOUND OR NOT EXISTS (SELECT 1 FROM production.order_ownership WHERE order_id=o.id AND organization_id=NEW.organization_id)
    OR o.completed_at IS NOT NULL OR o.stage='done' OR o.qty<=0 OR NULLIF(btrim(NEW.actor),'') IS NULL THEN
    RAISE EXCEPTION 'Order completion source is unavailable';
  END IF;
  SELECT sum(c.quantity),sum(a.accepted_quantity),sum(a.rejected_quantity),
    count(*) FILTER (WHERE a.receipt_id IS NULL OR r.status IS DISTINCT FROM 'accepted'),max((d.command->>'operation_date')::date)
    INTO total,accepted,rejected,missing,earliest FROM production.output_confirmation c
    JOIN production.output_document d ON d.id=c.document_id
    LEFT JOIN wms.production_arrival a ON a.event_id=c.event_id
    LEFT JOIN wms.receipt r ON r.id=a.receipt_id WHERE c.order_id=o.id;
  IF total IS DISTINCT FROM o.qty::numeric OR accepted IS DISTINCT FROM o.qty::numeric
    OR rejected IS DISTINCT FROM 0::numeric OR missing<>0
    OR (NEW.command->>'operation_date')::date<earliest
    OR coalesce(NEW.command->>'expected_digest','') !~ '^[a-f0-9]{64}$'
    OR length(btrim(coalesce(NEW.command->>'evidence','')))<10
    OR NEW.snapshot::jsonb->'order'->'order_id' IS DISTINCT FROM to_jsonb(o.id)
    OR NEW.snapshot::jsonb->'order'->'quantity' IS DISTINCT FROM to_jsonb(o.qty) THEN
    RAISE EXCEPTION 'Order completion requires fully accepted output';
  END IF;
  IF jsonb_typeof(NEW.command::jsonb) IS DISTINCT FROM 'object'
    OR NEW.command::jsonb IS DISTINCT FROM jsonb_build_object('expected_digest',NEW.command->>'expected_digest',
      'operation_date',NEW.command->>'operation_date','evidence',NEW.command->>'evidence')
    OR coalesce(NEW.command->>'operation_date','') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
    OR length(NEW.command->>'evidence')>1000 THEN
    RAISE EXCEPTION 'Order completion command is incomplete';
  END IF;
  SELECT jsonb_agg(jsonb_build_object('document_id',d.id,'request_id',d.request_id,
      'sku_code',d.snapshot->'sku_snapshot'->>'code','lot',d.command->>'lot',
      'operation_date',d.command->>'operation_date','quantity',to_char(c.quantity,'FM9999999999990.00'),
      'state',r.status,'receipt_id',r.id,
      'accepted_quantity',to_char(a.accepted_quantity,'FM9999999999990.00'),
      'rejected_quantity',to_char(a.rejected_quantity,'FM9999999999990.00'),
      'movement_ids',CASE WHEN a.movement_id IS NULL THEN '[]'::jsonb ELSE jsonb_build_array(a.movement_id) END) ORDER BY d.id),
    min(d.snapshot->'sku_snapshot'->>'unit'),
    count(DISTINCT (d.snapshot->'sku_snapshot'->>'code',d.snapshot->'sku_snapshot'->>'unit')),
    min(d.snapshot->'sku_snapshot'->>'code'), min(NULLIF(d.command->>'lot','')),
    count(DISTINCT NULLIF(d.command->>'lot',''))
    INTO documents,unit_name,unit_count,sku_code,lot_value,lot_count FROM production.output_confirmation c
    JOIN production.output_document d ON d.id=c.document_id
    JOIN wms.production_arrival a ON a.event_id=c.event_id
    JOIN wms.receipt r ON r.id=a.receipt_id WHERE c.order_id=o.id;
  expected := jsonb_build_object('order',jsonb_build_object('order_id',o.id,'number',o.number,
      'product',o.product,'quantity',o.qty,'stage',o.stage,'created_at',NEW.snapshot::jsonb->'order'->'created_at'),
    'minimum_date',to_char(earliest,'YYYY-MM-DD'),
    'reconciliation',jsonb_build_object('organization_id',NEW.organization_id,'order_id',o.id,'planned_quantity',o.qty::text,
      'confirmed_quantity',to_char(total,'FM9999999999990.00'),'accepted_quantity',to_char(accepted,'FM9999999999990.00'),
      'rejected_quantity','0.00','pending_quantity','0.00','documents',documents,
      'sku_code',CASE WHEN unit_count=1 THEN sku_code ELSE NULL END,
      'lot',CASE WHEN lot_count=1 THEN lot_value ELSE NULL END,'unit',unit_name,
      'scope','confirmed_output_documents','accounting_final',false));
  IF unit_count<>1 OR unit_name IS NULL OR NEW.snapshot::jsonb IS DISTINCT FROM expected
    OR (NEW.snapshot->'order'->>'created_at')::timestamp IS DISTINCT FROM o.created_at THEN
    RAISE EXCEPTION 'Order completion snapshot differs from its sources';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER check_order_completion_insert BEFORE INSERT ON production.order_completion
FOR EACH ROW EXECUTE FUNCTION production.check_order_completion_insert();

CREATE FUNCTION production.check_completed_order_state() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target integer; o production.production_order%ROWTYPE; c production.order_completion%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='order_completion' THEN target:=NEW.order_id; ELSE target:=NEW.id; END IF;
  SELECT * INTO c FROM production.order_completion WHERE order_id=target;
  IF NOT FOUND THEN RETURN NULL; END IF;
  SELECT * INTO o FROM production.production_order WHERE id=target;
  IF o.stage IS DISTINCT FROM 'done' OR o.progress IS DISTINCT FROM 100 OR o.made_qty IS DISTINCT FROM o.qty
    OR o.qty IS DISTINCT FROM (c.snapshot->'order'->>'quantity')::integer
    OR o.completed_at IS DISTINCT FROM (c.command->>'operation_date')::timestamp THEN
    RAISE EXCEPTION 'Completed order state differs from completion receipt';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER check_order_completion_state AFTER INSERT ON production.order_completion
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION production.check_completed_order_state();
CREATE CONSTRAINT TRIGGER check_completed_order_state AFTER UPDATE ON production.production_order
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION production.check_completed_order_state();


-- Recompute monetary allocation from actual ledger rows, never from supplied totals.
CREATE OR REPLACE FUNCTION accounting.verify_production_cost_review(
  book integer, review_month text, review_policy integer, posting_day date,
  reviewed jsonb, review_command jsonb, excluded_entries integer[], allow_empty boolean DEFAULT false
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE p accounting.policy%ROWTYPE; settings jsonb; classes jsonb; bindings jsonb; saved jsonb;
  actual_sources jsonb; actual_ids jsonb; classified_ids jsonb; expected_matrix jsonb;
  expected_balances jsonb; saved_balances jsonb; expected_allocations jsonb; saved_allocations jsonb;
  first_day date; last_day date; item jsonb; saved_order jsonb; order_row production.production_order%ROWTYPE;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=book FOR UPDATE;
  first_day := (review_month||'-01')::date;
  last_day := (first_day + interval '1 month - 1 day')::date;
  SELECT * INTO p FROM accounting.policy WHERE organization_id=book AND effective_from<=last_day
    ORDER BY effective_from DESC LIMIT 1;
  -- The API validates/stores a typed policy, while the optional finished-goods
  -- field may be omitted from older JSON rows. Rebuild the canonical shape
  -- used by the Python source snapshot before comparing it with the review.
  settings := jsonb_build_object(
    'overhead_accounts', p.production_costing::jsonb->'overhead_accounts',
    'wip_account', p.production_costing::jsonb->>'wip_account',
    'finished_goods_account', p.production_costing::jsonb->>'finished_goods_account',
    'pool_dimensions', p.production_costing::jsonb->'pool_dimensions',
    'order_dimension', p.production_costing::jsonb->>'order_dimension',
    'rounding', p.production_costing::jsonb->>'rounding',
    'reference', p.production_costing::jsonb->>'reference'
  );
  saved := reviewed->'snapshot'->'source'->'snapshot';
  classes := review_command->'classifications';
  bindings := review_command->'orders';
  IF p.id IS DISTINCT FROM review_policy OR p.effective_from>first_day OR settings IS NULL
    OR posting_day IS NULL OR posting_day<first_day OR posting_day>last_day
    OR excluded_entries IS NULL OR array_position(excluded_entries,NULL) IS NOT NULL OR allow_empty IS NULL
    OR p.allocation_basis IS DISTINCT FROM 'direct_cost'
    OR settings->>'rounding' IS DISTINCT FROM 'largest_remainder_cent'
    OR settings->>'order_dimension' IS DISTINCT FROM 'order'
    OR settings->'pool_dimensions' NOT IN ('[]'::jsonb,'["department"]'::jsonb)
    OR saved->'settings' IS DISTINCT FROM settings
    OR saved->>'organization_id' IS DISTINCT FROM book::text
    OR saved->>'month' IS DISTINCT FROM review_month OR saved->>'policy_id' IS DISTINCT FROM p.id::text
    OR reviewed->'snapshot'->>'organization_id' IS DISTINCT FROM book::text
    OR reviewed->'snapshot'->>'month' IS DISTINCT FROM review_month
    OR reviewed->'snapshot'->>'status' IS DISTINCT FROM 'reviewed_allocation_preview'
    OR reviewed->'snapshot'->'posted' IS DISTINCT FROM 'false'::jsonb
    OR reviewed->'snapshot'->'final_cost_certified' IS DISTINCT FROM 'false'::jsonb
    OR reviewed->'snapshot'->'review' IS DISTINCT FROM review_command
    OR jsonb_typeof(classes) IS DISTINCT FROM 'array' OR jsonb_array_length(classes)=0
    OR jsonb_typeof(bindings) IS DISTINCT FROM 'array' OR (NOT allow_empty AND jsonb_array_length(bindings)=0) THEN
    RAISE EXCEPTION 'Invalid production overhead policy or review structure';
  END IF;
  SELECT jsonb_agg(l.id ORDER BY l.id), jsonb_agg(jsonb_build_object(
    'entry_id',s.id,'line_id',l.id,'entry_digest',s.digest,'source',s.source,'source_version',s.source_version,
    'operation',s.operation,'posting_date',s.posting_date::text,'operation_date',s.operation_date::text,
    'opening',s.opening,'correction_of',s.correction_of,'account',l.account_code,'account_title',l.account_title,
    'dimensions',l.dimensions::jsonb,'side',l.side,'amount_byn',l.amount::text) ORDER BY s.posting_date,s.id,l.id)
    INTO actual_ids,actual_sources
  FROM accounting.line l JOIN accounting.entry s ON s.id=l.entry_id
  WHERE s.organization_id=book AND NOT (s.id=ANY(excluded_entries)) AND s.posting_date<=last_day
    AND (l.account_code=settings->>'wip_account' OR settings->'overhead_accounts' ? l.account_code);
  SELECT jsonb_agg((c->>'line_id')::integer ORDER BY (c->>'line_id')::integer) INTO classified_ids FROM jsonb_array_elements(classes) c;
  IF classified_ids IS DISTINCT FROM actual_ids OR actual_sources IS DISTINCT FROM saved->'lines' THEN
    RAISE EXCEPTION 'Production overhead source lines differ from ledger or classification';
  END IF;
  WITH balances AS (
    SELECT l.account_code,l.dimensions::jsonb AS dimensions,
      sum(CASE WHEN s.posting_date<first_day OR s.opening THEN l.amount*CASE WHEN l.side='debit' THEN 1 ELSE -1 END ELSE 0 END) AS opening,
      sum(CASE WHEN s.posting_date>=first_day AND NOT s.opening AND l.side='debit' THEN l.amount ELSE 0 END) AS debit,
      sum(CASE WHEN s.posting_date>=first_day AND NOT s.opening AND l.side='credit' THEN l.amount ELSE 0 END) AS credit
    FROM accounting.line l JOIN accounting.entry s ON s.id=l.entry_id
    WHERE s.organization_id=book AND NOT (s.id=ANY(excluded_entries)) AND s.posting_date<=last_day
      AND (l.account_code=settings->>'wip_account' OR settings->'overhead_accounts' ? l.account_code)
    GROUP BY l.account_code,l.dimensions::jsonb
  ), objects AS (SELECT jsonb_build_object('account',account_code,'dimensions',dimensions,
      'role',CASE WHEN account_code=settings->>'wip_account' THEN 'wip' ELSE 'overhead' END,
      'opening_byn',opening::numeric(38,2)::text,'debit_byn',debit::numeric(38,2)::text,
      'credit_byn',credit::numeric(38,2)::text,'closing_byn',(opening+debit-credit)::numeric(38,2)::text) AS value FROM balances)
  SELECT jsonb_agg(value ORDER BY value) INTO expected_balances FROM objects;
  SELECT jsonb_agg(value ORDER BY value) INTO saved_balances FROM jsonb_array_elements(saved->'balances');
  IF expected_balances IS DISTINCT FROM saved_balances THEN
    RAISE EXCEPTION 'Production overhead saved balances differ from ledger';
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(classes) c WHERE
      c->>'role' NOT IN ('direct_cost','overhead','excluded') OR c->>'role' IS NULL
      OR length(btrim(coalesce(c->>'evidence','')))<10 OR length(c->>'evidence')>1000)
    OR (SELECT count(*) FROM jsonb_array_elements(bindings)) IS DISTINCT FROM
       (SELECT count(DISTINCT b->>'analytical_order') FROM jsonb_array_elements(bindings) b)
    OR (SELECT count(*) FROM jsonb_array_elements(bindings)) IS DISTINCT FROM
       (SELECT count(DISTINCT (b->>'order_id')::integer) FROM jsonb_array_elements(bindings) b) THEN
    RAISE EXCEPTION 'Invalid production overhead classification or order bindings';
  END IF;
  IF jsonb_typeof(reviewed->'snapshot'->'production_orders') IS DISTINCT FROM 'array'
    OR jsonb_array_length(reviewed->'snapshot'->'production_orders') IS DISTINCT FROM jsonb_array_length(bindings) THEN
    RAISE EXCEPTION 'Production overhead order snapshots are incomplete';
  END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(bindings) LOOP
    SELECT o.* INTO order_row FROM production.production_order o JOIN production.order_ownership own ON own.order_id=o.id
      WHERE o.id=(item->>'order_id')::integer AND own.organization_id=book FOR UPDATE OF o;
    IF NOT FOUND OR length(btrim(coalesce(item->>'evidence','')))<10 OR length(item->>'evidence')>1000
      OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(classes) c JOIN accounting.line l ON l.id=(c->>'line_id')::integer
          WHERE c->>'role'='direct_cost' AND l.dimensions->>'order'=item->>'analytical_order') THEN
      RAISE EXCEPTION 'Production overhead target is not a reviewed owned order';
    END IF;
    SELECT value INTO saved_order FROM jsonb_array_elements(reviewed->'snapshot'->'production_orders')
      WHERE value->>'order_id'=order_row.id::text;
    IF NOT FOUND OR saved_order IS DISTINCT FROM jsonb_build_object('order_id',order_row.id,
        'number',order_row.number,'product',order_row.product,'quantity',order_row.qty,'stage',order_row.stage,
        'created_at',saved_order->'created_at')
      OR (saved_order->>'created_at')::timestamptz IS DISTINCT FROM order_row.created_at THEN
      RAISE EXCEPTION 'Production overhead order snapshot differs from its source';
    END IF;
  END LOOP;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(classes) c JOIN accounting.line l ON l.id=(c->>'line_id')::integer
      JOIN accounting.entry s ON s.id=l.entry_id
      WHERE c->>'role'<>'excluded' AND (
        s.opening OR s.posting_date<first_day OR s.posting_date>posting_day OR l.currency<>'BYN' OR l.cash OR l.quantity IS NOT NULL
        OR (c->>'role'='direct_cost' AND (l.account_code IS DISTINCT FROM settings->>'wip_account'
          OR l.category<>'asset' OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(bindings) b WHERE b->>'analytical_order'=l.dimensions->>'order')))
        OR (c->>'role'='overhead' AND NOT (settings->'overhead_accounts' ? l.account_code))
        OR l.dimensions::jsonb IS DISTINCT FROM
          (CASE WHEN settings->'pool_dimensions'='[]'::jsonb THEN '{}'::jsonb ELSE jsonb_build_object('department',l.dimensions->>'department') END
           || CASE WHEN c->>'role'='direct_cost' THEN jsonb_build_object('order',l.dimensions->>'order') ELSE '{}'::jsonb END))) THEN
    RAISE EXCEPTION 'Production overhead included source has invalid date, role or analytics';
  END IF;
  -- Integer quotient/remainder avoids floating or finite-scale division in tie ranking.
  WITH classified AS (
    SELECT l.*, c->>'role' AS role,
      CASE WHEN settings->'pool_dimensions'='[]'::jsonb THEN '{}'::jsonb ELSE jsonb_build_object('department',l.dimensions->>'department') END AS pool,
      l.amount*100*CASE WHEN l.side='debit' THEN 1 ELSE -1 END AS cents
    FROM jsonb_array_elements(classes) c JOIN accounting.line l ON l.id=(c->>'line_id')::integer WHERE c->>'role'<>'excluded'
  ), direct AS (
    SELECT pool,b->>'analytical_order' AS analytical,(b->>'order_id')::integer AS order_id,sum(cents) AS basis
    FROM classified c JOIN jsonb_array_elements(bindings) b ON b->>'analytical_order'=c.dimensions->>'order'
    WHERE role='direct_cost' GROUP BY pool,b->>'analytical_order',(b->>'order_id')::integer
  ), overhead AS (
    SELECT account_code,pool,sum(cents) AS cents FROM classified WHERE role='overhead' GROUP BY account_code,pool
  ), totals AS (SELECT pool,sum(basis) AS total FROM direct GROUP BY pool),
  quotas AS (
    SELECT h.account_code,h.pool,h.cents,d.analytical,d.order_id,d.basis,t.total,
      div(h.cents*d.basis,t.total) AS floor,mod(h.cents*d.basis,t.total) AS remainder
    FROM overhead h JOIN totals t ON t.pool=h.pool JOIN direct d ON d.pool=h.pool WHERE h.cents>0 AND t.total>0
  ), ranked AS (
    SELECT *,row_number() OVER (PARTITION BY account_code,pool ORDER BY remainder DESC,order_id) AS rank,
      cents-sum(floor) OVER (PARTITION BY account_code,pool) AS residual FROM quotas
  ), expected AS (
    SELECT settings->>'wip_account' AS account,'debit' AS side,pool||jsonb_build_object('order',analytical) AS dimensions,
      (floor+CASE WHEN rank<=residual THEN 1 ELSE 0 END)/100 AS amount FROM ranked
    UNION ALL SELECT account_code,'credit',pool,cents/100 FROM overhead WHERE cents>0
  ), allocations AS (
    SELECT jsonb_build_object('account',account_code,'pool_dimensions',pool,'allocation',jsonb_build_object(
      'amount_byn',max(cents)::numeric/100,'basis','direct_cost','rounding','largest_remainder_cent',
      'shares',jsonb_agg(jsonb_build_object('order_id',order_id,'basis_amount',(basis/100)::numeric(38,6)::text,
        'amount_byn',((floor+CASE WHEN rank<=residual THEN 1 ELSE 0 END)/100)::numeric(38,2)::text) ORDER BY order_id),
      'status','arithmetic_preview','posted',false,'source_movements_verified',false,'final_cost_certified',false)) AS value
    FROM ranked GROUP BY account_code,pool
  ), allocation_strings AS (
    SELECT jsonb_set(value,'{allocation,amount_byn}',to_jsonb((value->'allocation'->>'amount_byn')::numeric(38,2)::text)) AS value FROM allocations
  ), invalid AS (
    SELECT 1 FROM direct WHERE basis<0 UNION ALL SELECT 1 FROM overhead h LEFT JOIN totals t ON t.pool=h.pool
      WHERE h.cents<0 OR (h.cents>0 AND coalesce(t.total,0)<=0)
  )
  SELECT (SELECT CASE WHEN EXISTS(SELECT 1 FROM invalid) THEN NULL ELSE coalesce(jsonb_agg(jsonb_build_array(account,side,dimensions,amount)
    ORDER BY account,side,dimensions,amount),'[]'::jsonb) END FROM expected WHERE amount>0),
    (SELECT jsonb_agg(value ORDER BY value) FROM allocation_strings) INTO expected_matrix,expected_allocations;
  SELECT jsonb_agg(value ORDER BY value) INTO saved_allocations FROM jsonb_array_elements(reviewed->'snapshot'->'allocations');
  IF expected_allocations IS DISTINCT FROM saved_allocations THEN
    RAISE EXCEPTION 'Production overhead saved allocation differs from independent calculation';
  END IF;
  IF expected_matrix IS NULL OR (NOT allow_empty AND expected_matrix='[]'::jsonb) THEN
    RAISE EXCEPTION 'Production overhead posting differs from independently allocated ledger costs';
  END IF;
  IF reviewed->>'digest' IS DISTINCT FROM accounting.financial_sha(reviewed->'snapshot')
    OR reviewed->'snapshot'->'source'->>'digest' IS DISTINCT FROM accounting.financial_sha(saved)
    OR review_command->>'expected_source_digest' IS DISTINCT FROM accounting.financial_sha(saved) THEN
    RAISE EXCEPTION 'Production overhead saved review digest is invalid';
  END IF;
  RETURN expected_matrix;
END $$;

-- Compare an independently verified target with actual applied ledger movements.
-- The revision admission guard supplies the complete, validated predecessor chain.
CREATE OR REPLACE FUNCTION accounting.production_cost_delta(
  book integer, desired jsonb, applied_entries integer[]
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE actual jsonb; result jsonb;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=book FOR UPDATE;
  IF applied_entries IS NULL OR cardinality(applied_entries)=0
    OR array_position(applied_entries,NULL) IS NOT NULL
    OR cardinality(applied_entries)<>(SELECT count(DISTINCT id) FROM unnest(applied_entries) id)
    OR cardinality(applied_entries)<>(SELECT count(*) FROM accounting.entry WHERE id=ANY(applied_entries)
        AND organization_id=book AND operation IN ('production_overhead','production_overhead_correction')) THEN
    RAISE EXCEPTION 'Cost correction requires unique existing allocation entries of this organization';
  END IF;
  IF jsonb_typeof(desired) IS DISTINCT FROM 'array' OR EXISTS (
    SELECT 1 FROM jsonb_array_elements(desired) row WHERE jsonb_typeof(row) IS DISTINCT FROM 'array'
      OR jsonb_array_length(row)<>4 OR jsonb_typeof(row->0) IS DISTINCT FROM 'string'
      OR length(row->>0)=0 OR row->>1 NOT IN ('debit','credit') OR row->>1 IS NULL
      OR jsonb_typeof(row->2) IS DISTINCT FROM 'object' OR jsonb_typeof(row->3) IS DISTINCT FROM 'number'
      OR (row->>3)::numeric<=0 OR (row->>3)::numeric*100<>trunc((row->>3)::numeric*100)) THEN
    RAISE EXCEPTION 'Cost correction requires an exact positive BYN target matrix';
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_array(l.account_code,l.side,l.dimensions::jsonb,l.amount)),'[]'::jsonb)
    INTO actual FROM accounting.line l WHERE l.entry_id=ANY(applied_entries);
  IF coalesce((SELECT sum((row->>3)::numeric*CASE WHEN row->>1='debit' THEN 1 ELSE -1 END)
      FROM jsonb_array_elements(desired) row),0)<>0
    OR coalesce((SELECT sum((row->>3)::numeric*CASE WHEN row->>1='debit' THEN 1 ELSE -1 END)
      FROM jsonb_array_elements(actual) row),0)<>0 THEN
    RAISE EXCEPTION 'Cost correction target and applied entries must each balance';
  END IF;
  WITH movements AS (
    SELECT row->>0 AS account,row->2 AS dimensions,(row->>3)::numeric*100*
      CASE WHEN row->>1='debit' THEN 1 ELSE -1 END AS cents FROM jsonb_array_elements(desired) row
    UNION ALL
    SELECT row->>0,row->2,(row->>3)::numeric*100*
      CASE WHEN row->>1='debit' THEN -1 ELSE 1 END FROM jsonb_array_elements(actual) row
  ), differences AS (
    SELECT account,dimensions,sum(cents) AS cents FROM movements GROUP BY account,dimensions
  )
  SELECT coalesce(jsonb_agg(jsonb_build_array(account,CASE WHEN cents>0 THEN 'debit' ELSE 'credit' END,dimensions,abs(cents)/100)
    ORDER BY account,dimensions),'[]'::jsonb) INTO result FROM differences WHERE cents<>0;
  RETURN result;
END $$;

-- Initial posting keeps its strict entry/receipt contract. Correction admission
-- reuses the independent source calculation and supplies its own validated chain.
CREATE OR REPLACE FUNCTION accounting.verify_production_overhead(target integer) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE r accounting.production_overhead_receipt%ROWTYPE; e accounting.entry%ROWTYPE;
  expected_matrix jsonb; actual_matrix jsonb;
BEGIN
  SELECT * INTO r FROM accounting.production_overhead_receipt WHERE entry_id=target;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF r.entry_id IS NULL OR e.id IS NULL THEN RAISE EXCEPTION 'Missing production overhead entry or receipt'; END IF;
  expected_matrix := accounting.verify_production_cost_review(e.organization_id,r.month,e.policy_id,e.posting_date,
    r.review::jsonb,r.command::jsonb->'review',ARRAY[target],false);
  SELECT jsonb_agg(jsonb_build_array(account_code,side,dimensions::jsonb,amount)
    ORDER BY account_code,side,dimensions::jsonb,amount) INTO actual_matrix FROM accounting.line WHERE entry_id=target;
  IF expected_matrix IS DISTINCT FROM actual_matrix THEN
    RAISE EXCEPTION 'Production overhead posting differs from independently allocated ledger costs';
  END IF;
END $$;


CREATE TRIGGER immutable_production_overhead_receipt BEFORE UPDATE OR DELETE OR TRUNCATE
ON accounting.production_overhead_receipt FOR EACH STATEMENT
EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE TRIGGER immutable_production_overhead_withdrawal BEFORE UPDATE OR DELETE OR TRUNCATE
ON accounting.production_overhead_withdrawal FOR EACH STATEMENT
EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE OR REPLACE FUNCTION accounting.guard_production_overhead_decision() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  IF TG_TABLE_NAME='production_overhead_withdrawal' THEN
    IF EXISTS (SELECT 1 FROM accounting.production_overhead_receipt WHERE organization_id=NEW.organization_id AND request_key=NEW.request_key) THEN
      RAISE EXCEPTION 'A posted overhead request cannot be withdrawn';
    END IF;
    IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
      OR NEW.month IS DISTINCT FROM to_char((NEW.month||'-01')::date,'YYYY-MM')
      OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
      OR to_char((NEW.command->>'posting_date')::date,'YYYY-MM') IS DISTINCT FROM NEW.month
      OR length(btrim(NEW.actor))<1 OR length(btrim(NEW.reason))<10 THEN
      RAISE EXCEPTION 'Withdrawal must retain the original request identity and reason';
    END IF;
  ELSIF EXISTS (SELECT 1 FROM accounting.production_overhead_withdrawal WHERE organization_id=NEW.organization_id AND request_key=NEW.request_key) THEN
    RAISE EXCEPTION 'A withdrawn overhead request cannot be posted';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER production_overhead_withdrawal_decision BEFORE INSERT ON accounting.production_overhead_withdrawal
FOR EACH ROW EXECUTE FUNCTION accounting.guard_production_overhead_decision();
CREATE TRIGGER production_overhead_receipt_decision BEFORE INSERT ON accounting.production_overhead_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_production_overhead_decision();

CREATE OR REPLACE FUNCTION accounting.check_production_overhead_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer; e accounting.entry%ROWTYPE; r accounting.production_overhead_receipt%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target := NEW.id; ELSE target := NEW.entry_id; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF e.operation IS DISTINCT FROM 'production_overhead_correction' AND EXISTS (
      SELECT 1 FROM accounting.entry original WHERE original.id=e.correction_of
             AND original.operation IN ('production_overhead','production_overhead_correction')) THEN
    RAISE EXCEPTION 'Production overhead corrections require their dedicated workflow';
  END IF;
  IF e.operation IS DISTINCT FROM 'production_overhead' THEN
    IF TG_TABLE_NAME='production_overhead_receipt' THEN RAISE EXCEPTION 'Invalid production overhead receipt entry'; END IF;
    RETURN NULL;
  END IF;
  SELECT * INTO r FROM accounting.production_overhead_receipt WHERE entry_id=target;
  IF NOT FOUND OR r.organization_id IS DISTINCT FROM e.organization_id
    OR r.actor IS DISTINCT FROM e.actor OR r.month IS DISTINCT FROM to_char(e.posting_date,'YYYY-MM')
    OR e.source IS DISTINCT FROM 'production:overhead:'||e.organization_id||':'||r.month
    OR e.source_version<>1 OR e.rule_version<>'production-overhead-v1' OR e.opening OR e.correction_of IS NOT NULL
    OR r.command->>'request_key' IS DISTINCT FROM r.request_key
    OR r.command->>'expected_review_digest' IS DISTINCT FROM r.review->>'digest'
    OR r.review->'snapshot'->>'organization_id' IS DISTINCT FROM e.organization_id::text
    OR r.review->'snapshot'->>'month' IS DISTINCT FROM r.month
    OR r.command->>'posting_date' IS DISTINCT FROM e.posting_date::text
    OR accounting.posting_body_projection(r.posting::jsonb) IS DISTINCT FROM
       accounting.posting_body_projection(accounting.financial_posting_body(target),false) THEN
    RAISE EXCEPTION 'Production overhead requires its matching complete receipt';
  END IF;
  PERFORM accounting.verify_production_overhead(target);
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_production_overhead_entry AFTER INSERT ON accounting.entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_production_overhead_complete();
CREATE CONSTRAINT TRIGGER complete_production_overhead_line AFTER INSERT ON accounting.line
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_production_overhead_complete();
CREATE CONSTRAINT TRIGGER complete_production_overhead_receipt AFTER INSERT ON accounting.production_overhead_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_production_overhead_complete();

-- Ledger lines and stored source snapshots are immutable. Independent ID coverage
-- detects every subsequently admitted source line without trusting UI evidence.
CREATE OR REPLACE FUNCTION accounting.assert_production_overhead_current(book integer, closing_month text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE r accounting.production_overhead_receipt%ROWTYPE; p accounting.policy%ROWTYPE;
  latest accounting.production_overhead_revision%ROWTYPE; applied integer[];
  saved jsonb; settings jsonb; policy_settings jsonb; actual_ids jsonb; expected_ids jsonb; first_day date; last_day date;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=book FOR UPDATE;
  FOR r IN SELECT * FROM accounting.production_overhead_receipt WHERE organization_id=book AND month<=closing_month ORDER BY month LOOP
    first_day := (r.month||'-01')::date;
    last_day := (first_day + interval '1 month - 1 day')::date;
    SELECT * INTO p FROM accounting.policy WHERE organization_id=book AND effective_from<=last_day ORDER BY effective_from DESC LIMIT 1;
    policy_settings := jsonb_build_object(
      'overhead_accounts', p.production_costing::jsonb->'overhead_accounts',
      'wip_account', p.production_costing::jsonb->>'wip_account',
      'finished_goods_account', p.production_costing::jsonb->>'finished_goods_account',
      'pool_dimensions', p.production_costing::jsonb->'pool_dimensions',
      'order_dimension', p.production_costing::jsonb->>'order_dimension',
      'rounding', p.production_costing::jsonb->>'rounding',
      'reference', p.production_costing::jsonb->>'reference'
    );
    SELECT * INTO latest FROM accounting.production_overhead_revision WHERE original_entry_id=r.entry_id ORDER BY sequence DESC LIMIT 1;
    SELECT ARRAY[r.entry_id]||coalesce(array_agg(entry_id) FILTER(WHERE entry_id IS NOT NULL),ARRAY[]::integer[])
      INTO applied FROM accounting.production_overhead_revision WHERE original_entry_id=r.entry_id;
    saved := CASE WHEN latest.id IS NULL THEN r.review::jsonb->'snapshot'->'source'->'snapshot'
      ELSE latest.preview::jsonb->'snapshot'->'reviewed'->'snapshot'->'source'->'snapshot' END;
    settings := saved->'settings';
    IF p.id IS DISTINCT FROM (r.command->'review'->>'policy_id')::integer OR p.effective_from>first_day
      OR policy_settings IS DISTINCT FROM settings THEN
      RAISE EXCEPTION 'Production overhead sources changed or cannot be verified for %; repeat costing before closing', r.month;
    END IF;
    SELECT coalesce(jsonb_agg(l.id ORDER BY l.id),'[]'::jsonb) INTO actual_ids
      FROM accounting.entry e JOIN accounting.line l ON l.entry_id=e.id
      WHERE e.organization_id=book AND e.posting_date<=last_day AND NOT(e.id=ANY(applied))
        AND l.account_code IN (SELECT jsonb_array_elements_text(settings->'overhead_accounts'||jsonb_build_array(settings->>'wip_account')));
    SELECT coalesce(jsonb_agg((line->>'line_id')::integer ORDER BY (line->>'line_id')::integer),'[]'::jsonb) INTO expected_ids
      FROM jsonb_array_elements(saved->'lines') line;
    IF actual_ids IS DISTINCT FROM expected_ids THEN
      RAISE EXCEPTION 'Production overhead sources changed or cannot be verified for %; repeat costing before closing', r.month;
    END IF;
  END LOOP;
END $$;
CREATE OR REPLACE FUNCTION accounting.guard_production_cost_close() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.closed THEN PERFORM accounting.assert_production_overhead_current(NEW.organization_id,NEW.month); END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER costing_before_period_close BEFORE INSERT OR UPDATE ON accounting.period
FOR EACH ROW EXECUTE FUNCTION accounting.guard_production_cost_close();


CREATE TRIGGER immutable_production_overhead_revision BEFORE UPDATE OR DELETE OR TRUNCATE
ON accounting.production_overhead_revision FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER a_capture_period_basis BEFORE INSERT ON accounting.production_overhead_revision
FOR EACH ROW EXECUTE FUNCTION accounting.capture_period_basis();

CREATE OR REPLACE FUNCTION accounting.guard_overhead_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE original accounting.production_overhead_receipt; predecessor accounting.production_overhead_revision; day date;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  IF EXISTS (SELECT 1 FROM accounting.production_overhead_correction_withdrawal
    WHERE organization_id=NEW.organization_id AND request_key=NEW.request_key) THEN
    RAISE EXCEPTION 'Withdrawn correction request cannot be confirmed';
  END IF;
  SELECT * INTO original FROM accounting.production_overhead_receipt WHERE entry_id=NEW.original_entry_id;
  SELECT * INTO predecessor FROM accounting.production_overhead_revision WHERE original_entry_id=NEW.original_entry_id ORDER BY sequence DESC LIMIT 1;
  day := (NEW.command->'preview'->>'posting_date')::date;
  IF original.entry_id IS NULL OR original.organization_id IS DISTINCT FROM NEW.organization_id OR original.month IS DISTINCT FROM NEW.month
    OR NEW.sequence IS DISTINCT FROM coalesce(predecessor.sequence,0)+1 OR NEW.previous_id IS DISTINCT FROM predecessor.id
    OR NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
    OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
    OR day IS NULL OR to_char(day,'YYYY-MM') IS DISTINCT FROM NEW.month
    OR day<coalesce((predecessor.command->'preview'->>'posting_date')::date,(original.command->>'posting_date')::date)
    OR length(btrim(NEW.actor))<1 OR length(btrim(coalesce(NEW.command->'preview'->>'evidence',''))) NOT BETWEEN 10 AND 1000
    OR NEW.command->'preview'->>'method' IS DISTINCT FROM 'delta'
    OR EXISTS (SELECT 1 FROM accounting.period WHERE organization_id=NEW.organization_id AND month>=NEW.month AND closed) THEN
    RAISE EXCEPTION 'Invalid or stale production calculation revision chain';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER a_overhead_revision_chain BEFORE INSERT ON accounting.production_overhead_revision
FOR EACH ROW EXECUTE FUNCTION accounting.guard_overhead_revision();

CREATE OR REPLACE FUNCTION accounting.verify_overhead_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE r accounting.production_overhead_revision; original accounting.production_overhead_receipt;
  e accounting.entry; predecessor accounting.production_overhead_revision;
  target integer; applied integer[]; excluded integer[]; ids jsonb; chain jsonb; snap jsonb; reviewed jsonb;
  desired jsonb; delta jsonb; expected_lines jsonb; declared_matrix jsonb; actual_matrix jsonb; day date;
  basis accounting.period_root_basis; before_period jsonb; current_period accounting.period; current_generation bigint;
BEGIN
  IF TG_TABLE_NAME='production_overhead_revision' THEN SELECT * INTO r FROM accounting.production_overhead_revision WHERE id=NEW.id;
  ELSE
    IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
    SELECT * INTO e FROM accounting.entry WHERE id=target;
    IF e.operation IS DISTINCT FROM 'production_overhead_correction' THEN RETURN NULL; END IF;
    SELECT * INTO r FROM accounting.production_overhead_revision WHERE entry_id=target;
  END IF;
  IF r.id IS NULL THEN RAISE EXCEPTION 'Production correction requires its complete immutable calculation revision'; END IF;
  PERFORM 1 FROM accounting.organization WHERE id=r.organization_id FOR UPDATE;
  SELECT * INTO original FROM accounting.production_overhead_receipt WHERE entry_id=r.original_entry_id;
  SELECT * INTO e FROM accounting.entry WHERE id=r.original_entry_id;
  SELECT * INTO predecessor FROM accounting.production_overhead_revision WHERE id=r.previous_id;
  SELECT coalesce(jsonb_agg(id ORDER BY sequence),'[]'::jsonb),
    ARRAY[r.original_entry_id]||coalesce(array_agg(entry_id ORDER BY sequence) FILTER(WHERE entry_id IS NOT NULL),ARRAY[]::integer[])
    INTO ids,applied FROM accounting.production_overhead_revision WHERE original_entry_id=r.original_entry_id AND sequence<r.sequence;
  chain:=jsonb_build_object('revision_ids',ids,'applied_entry_ids',to_jsonb(applied),
    'latest_digest',coalesce(predecessor.preview->>'digest',original.review->>'digest'));
  snap:=r.preview::jsonb->'snapshot'; reviewed:=snap->'reviewed'; day:=(r.command->'preview'->>'posting_date')::date;
  IF snap->'command' IS DISTINCT FROM r.command::jsonb->'preview'
    OR snap->>'organization_id' IS DISTINCT FROM r.organization_id::text OR snap->>'month' IS DISTINCT FROM r.month
    OR snap->>'original_entry_id' IS DISTINCT FROM r.original_entry_id::text
    OR snap->'original_posting' IS DISTINCT FROM original.posting::jsonb
    OR snap->>'status' IS DISTINCT FROM 'correction_preview' OR snap->'posted' IS DISTINCT FROM 'false'::jsonb
    OR snap->'confirmation_available' IS DISTINCT FROM 'true'::jsonb OR snap->'final_cost_certified' IS DISTINCT FROM 'false'::jsonb
    OR reviewed->'snapshot'->'source'->'snapshot'->'calculation_chain' IS DISTINCT FROM chain
    OR reviewed->'snapshot'->'source'->'snapshot'->>'scope' IS DISTINCT FROM 'production_cost_correction_sources'
    OR reviewed->'snapshot'->'source'->'snapshot'->'excluded_allocation' IS DISTINCT FROM
      jsonb_build_object('entry_id',original.entry_id,'entry_digest',e.digest,'request_key',original.request_key)
    OR r.command->'preview'->>'original_entry_id' IS DISTINCT FROM r.original_entry_id::text
    OR r.command->'preview'->'review'->>'policy_id' IS DISTINCT FROM original.command->'review'->>'policy_id'
    OR r.command->'preview'->>'expected_review_digest' IS DISTINCT FROM reviewed->>'digest'
    OR r.preview->>'digest' IS DISTINCT FROM accounting.financial_sha(snap)
    OR r.command->>'expected_preview_digest' IS DISTINCT FROM r.preview->>'digest' THEN
    RAISE EXCEPTION 'Production correction calculation snapshot or chain mismatch';
  END IF;
  excluded:=applied||CASE WHEN r.entry_id IS NULL THEN ARRAY[]::integer[] ELSE ARRAY[r.entry_id] END;
  desired:=accounting.verify_production_cost_review(r.organization_id,r.month,(original.command->'review'->>'policy_id')::integer,
    day,reviewed,r.command::jsonb->'preview'->'review',excluded,true);
  SELECT coalesce(jsonb_agg(jsonb_build_array(line->>'account',line->>'side',line->'dimensions',(line->>'amount')::numeric)
    ORDER BY line->>'account',line->>'side',line->'dimensions',(line->>'amount')::numeric),'[]'::jsonb)
    INTO declared_matrix FROM jsonb_array_elements(snap->'desired_allocation_lines') line;
  IF desired IS DISTINCT FROM declared_matrix THEN RAISE EXCEPTION 'Production correction target differs from verified costs'; END IF;
  delta:=accounting.production_cost_delta(r.organization_id,desired,applied);
  SELECT coalesce(jsonb_agg(jsonb_build_object('account',line->>0,'side',line->>1,'dimensions',line->2,
    'amount',((line->>3)::numeric)::numeric(38,2)::text) ORDER BY line->>0,line->2),'[]'::jsonb)
    INTO expected_lines FROM jsonb_array_elements(delta) line;
  IF snap->'correction_lines' IS DISTINCT FROM expected_lines
    OR snap->'creates_entry' IS DISTINCT FROM to_jsonb(delta<>'[]'::jsonb)
    OR (r.entry_id IS NULL) IS DISTINCT FROM (delta='[]'::jsonb) THEN
    RAISE EXCEPTION 'Production correction delta or optional entry mismatch';
  END IF;
  IF r.entry_id IS NULL THEN
    IF r.posting::jsonb IS NOT NULL AND r.posting::jsonb<>'null'::jsonb THEN RAISE EXCEPTION 'Zero correction cannot contain a posting'; END IF;
    SELECT * INTO basis FROM accounting.period_root_basis WHERE organization_id=r.organization_id AND root_transaction=txid_current();
    SELECT generation INTO current_generation FROM accounting.organization WHERE id=r.organization_id;
    IF basis.organization_id IS NULL OR current_generation<>basis.organization_generation+1
      OR EXISTS (SELECT 1 FROM accounting.entry movement JOIN accounting.entry_transaction t ON t.entry_id=movement.id
        WHERE movement.organization_id=r.organization_id AND t.root_transaction=txid_current())
      OR (SELECT count(*) FROM accounting.period WHERE organization_id=r.organization_id)<>jsonb_array_length(basis.periods_before) THEN
      RAISE EXCEPTION 'Zero correction must invalidate its calculation generation exactly once';
    END IF;
    FOR before_period IN SELECT value FROM jsonb_array_elements(basis.periods_before) LOOP
      SELECT * INTO current_period FROM accounting.period WHERE id=(before_period->>'id')::integer;
      IF before_period->>'month'<r.month THEN
        IF to_jsonb(current_period) IS DISTINCT FROM before_period THEN RAISE EXCEPTION 'Zero correction changed an earlier period'; END IF;
      ELSIF current_period.generation<>(before_period->>'generation')::bigint+1 OR current_period.closed
        OR current_period.evidence::jsonb<>'{}'::jsonb THEN
        RAISE EXCEPTION 'Zero correction must invalidate every dependent period';
      END IF;
    END LOOP;
    RETURN NULL;
  END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=r.entry_id;
  IF e.operation IS DISTINCT FROM 'production_overhead_correction' OR e.organization_id IS DISTINCT FROM r.organization_id
    OR e.actor IS DISTINCT FROM r.actor OR e.posting_date IS DISTINCT FROM day OR e.document_date IS DISTINCT FROM day OR e.operation_date IS DISTINCT FROM day
    OR e.policy_id IS DISTINCT FROM (original.command->'review'->>'policy_id')::integer OR e.opening
    OR e.correction_of IS DISTINCT FROM applied[cardinality(applied)] OR e.source_version IS DISTINCT FROM r.sequence
    OR e.source IS DISTINCT FROM 'production:overhead:'||r.organization_id||':'||r.month
    OR e.rule_version IS DISTINCT FROM 'production-overhead-correction-v1' OR e.explanation IS DISTINCT FROM r.command->'preview'->>'evidence'
    OR accounting.posting_body_projection(r.posting::jsonb) IS DISTINCT FROM accounting.posting_body_projection(accounting.financial_posting_body(e.id),false) THEN
    RAISE EXCEPTION 'Production correction entry differs from its calculation receipt';
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('account',account_code,'side',side,'dimensions',dimensions::jsonb,'amount',amount::text)
    ORDER BY account_code,dimensions::jsonb),'[]'::jsonb) INTO actual_matrix FROM accounting.line WHERE entry_id=e.id;
  IF actual_matrix IS DISTINCT FROM expected_lines THEN RAISE EXCEPTION 'Production correction ledger delta mismatch'; END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_overhead_revision AFTER INSERT ON accounting.production_overhead_revision
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.verify_overhead_revision();
CREATE CONSTRAINT TRIGGER complete_overhead_revision_entry AFTER INSERT ON accounting.entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.verify_overhead_revision();
CREATE CONSTRAINT TRIGGER complete_overhead_revision_line AFTER INSERT ON accounting.line
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.verify_overhead_revision();

CREATE TRIGGER immutable_overhead_correction_withdrawal BEFORE UPDATE OR DELETE OR TRUNCATE
ON accounting.production_overhead_correction_withdrawal FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE OR REPLACE FUNCTION accounting.guard_correction_withdrawal() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  IF EXISTS (SELECT 1 FROM accounting.production_overhead_revision WHERE organization_id=NEW.organization_id AND request_key=NEW.request_key) THEN
    RAISE EXCEPTION 'Confirmed correction request cannot be withdrawn';
  END IF;
  IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
    OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
    OR to_char((NEW.command->'preview'->>'posting_date')::date,'YYYY-MM') IS DISTINCT FROM NEW.month
    OR length(btrim(NEW.actor))<1 OR length(btrim(NEW.reason)) NOT BETWEEN 10 AND 1000 THEN
    RAISE EXCEPTION 'Correction withdrawal must retain request identity and reason';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER correction_withdrawal_decision BEFORE INSERT ON accounting.production_overhead_correction_withdrawal
FOR EACH ROW EXECUTE FUNCTION accounting.guard_correction_withdrawal();


-- Unallocated proposal guard: a finished-goods transfer is admitted only
-- together with its immutable source package and a balanced two-line entry.
CREATE OR REPLACE FUNCTION accounting.guard_production_output_transfer_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; debit_count integer; credit_count integer;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  IF NOT FOUND OR e.organization_id <> NEW.organization_id
     OR e.source IS DISTINCT FROM 'production:output-transfer:'||NEW.organization_id||':'||NEW.order_id
     OR e.operation IS DISTINCT FROM 'production_output_transfer'
     OR e.source_version <> 1 OR e.digest IS DISTINCT FROM NEW.digest
     OR NEW.command->>'order_id' IS DISTINCT FROM NEW.order_id::text
     OR NEW.command->>'basis_digest' IS DISTINCT FROM NEW.basis_digest
     OR NEW.command->>'digest' IS DISTINCT FROM NEW.digest
     OR NEW.posting IS NULL OR NEW.basis IS NULL THEN
    RAISE EXCEPTION 'Production output transfer receipt does not match its ledger entry';
  END IF;
  SELECT count(*) FILTER (WHERE side='debit'), count(*) FILTER (WHERE side='credit')
    INTO debit_count, credit_count FROM accounting.line WHERE entry_id=NEW.entry_id;
  IF debit_count <> 1 OR credit_count <> 1 THEN
    RAISE EXCEPTION 'Production output transfer must contain one debit and one credit';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER guard_production_output_transfer_receipt
BEFORE INSERT ON accounting.production_output_transfer_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_production_output_transfer_receipt();

CREATE OR REPLACE FUNCTION accounting.immutable_production_output_transfer_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Production output transfer receipts are immutable';
END $$;

CREATE TRIGGER immutable_production_output_transfer_receipt
BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.production_output_transfer_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.immutable_production_output_transfer_receipt();


-- Reviewed advance offsets are immutable and may only point to the two
-- accounting entries that the application snapshots in the same organization.
CREATE OR REPLACE FUNCTION accounting.guard_settlement_offset_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE posted_entry accounting.entry;
DECLARE bank_entry accounting.entry;
DECLARE source_line accounting.line;
DECLARE target_line accounting.line;
DECLARE bank_cash_line accounting.line;
DECLARE bank_settlement_line accounting.line;
DECLARE posting_line_count integer;
DECLARE bank_line_count integer;
DECLARE used_offsets numeric;
DECLARE used_invoice_settlements numeric;
DECLARE available numeric;
DECLARE expected_source_side text;
DECLARE expected_target_side text;
BEGIN
  SELECT * INTO posted_entry FROM accounting.entry
    WHERE id = NEW.entry_id AND organization_id = NEW.organization_id;
  IF posted_entry IS NULL OR posted_entry.operation <> 'settlement_offset'
     OR posted_entry.rule_version <> 'settlement-offset-v1'
     OR posted_entry.source <> ('accounting:settlement-offset:' || NEW.request_key)
     OR posted_entry.source_version <> 1 THEN
    RAISE EXCEPTION 'Settlement receipt must bind its reviewed ledger entry';
  END IF;
  SELECT * INTO bank_entry FROM accounting.entry
    WHERE id = NEW.bank_entry_id AND organization_id = NEW.organization_id;
  IF bank_entry IS NULL OR bank_entry.operation <> 'bank_settlement'
     OR bank_entry.rule_version <> 'bank-byn-v1' OR bank_entry.correction_of IS NOT NULL THEN
    RAISE EXCEPTION 'Settlement receipt must bind an uncorrected bank settlement';
  END IF;
  expected_source_side := CASE WHEN NEW.kind = 'customer_advance' THEN 'debit' ELSE 'credit' END;
  expected_target_side := CASE WHEN NEW.kind = 'customer_advance' THEN 'credit' ELSE 'debit' END;
  IF NEW.source_account = NEW.target_account THEN
    RAISE EXCEPTION 'Settlement offset source and target accounts must be different';
  END IF;
  SELECT count(*) INTO posting_line_count FROM accounting.line WHERE entry_id = NEW.entry_id;
  SELECT * INTO source_line FROM accounting.line
    WHERE entry_id = NEW.entry_id AND account_code = NEW.source_account AND side = expected_source_side;
  SELECT * INTO target_line FROM accounting.line
    WHERE entry_id = NEW.entry_id AND account_code = NEW.target_account AND side = expected_target_side;
  IF posting_line_count <> 2 OR source_line.id IS NULL OR target_line.id IS NULL
     OR source_line.amount <> NEW.amount OR target_line.amount <> NEW.amount
     OR posted_entry.digest IS DISTINCT FROM NEW.digest THEN
    RAISE EXCEPTION 'Settlement receipt amount or ledger package differs from its snapshot';
  END IF;
  SELECT count(*) INTO bank_line_count FROM accounting.line WHERE entry_id = NEW.bank_entry_id;
  SELECT * INTO bank_cash_line FROM accounting.line WHERE entry_id = NEW.bank_entry_id AND cash;
  SELECT * INTO bank_settlement_line FROM accounting.line WHERE entry_id = NEW.bank_entry_id AND NOT cash;
  IF bank_line_count <> 2 OR bank_cash_line.id IS NULL OR bank_settlement_line.id IS NULL
     OR bank_settlement_line.account_code <> NEW.source_account
     OR bank_cash_line.amount <> bank_settlement_line.amount
     OR bank_cash_line.currency <> 'BYN' OR bank_settlement_line.currency <> 'BYN'
     OR (NEW.kind = 'customer_advance' AND (bank_cash_line.side <> 'debit' OR bank_settlement_line.side <> 'credit'
                                             OR bank_settlement_line.category <> 'liability'))
     OR (NEW.kind = 'supplier_advance' AND (bank_cash_line.side <> 'credit' OR bank_settlement_line.side <> 'debit'
                                             OR bank_settlement_line.category <> 'asset')) THEN
    RAISE EXCEPTION 'Settlement receipt direction or bank source role is invalid';
  END IF;
  IF (NEW.source_snapshot->>'entry_id')::integer IS DISTINCT FROM NEW.bank_entry_id
     OR NEW.source_snapshot->>'digest' IS DISTINCT FROM bank_entry.digest
     OR NEW.target_snapshot->>'document' IS DISTINCT FROM NEW.target_document
     OR NEW.target_snapshot->'dimensions'->>'settlement_document' IS DISTINCT FROM NEW.target_document THEN
    RAISE EXCEPTION 'Settlement source or target snapshot is inconsistent';
  END IF;
  SELECT coalesce(sum(amount), 0) INTO used_offsets FROM accounting.settlement_offset_receipt
    WHERE organization_id = NEW.organization_id AND bank_entry_id = NEW.bank_entry_id;
  SELECT coalesce(sum(amount), 0) INTO used_invoice_settlements FROM sales.invoice_settlement
    WHERE organization_id = NEW.organization_id AND bank_entry_id = NEW.bank_entry_id;
  available := bank_cash_line.amount - used_offsets - used_invoice_settlements;
  IF NEW.amount > available THEN
    RAISE EXCEPTION 'Settlement receipt exceeds the available bank source amount';
  END IF;
  IF NEW.amount <= 0 OR NEW.command_digest IS NULL OR NEW.basis_digest IS NULL
     OR NEW.digest IS NULL OR NEW.target_document = '' THEN
    RAISE EXCEPTION 'Settlement receipt has incomplete immutable evidence';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER guard_settlement_offset_receipt
BEFORE INSERT ON accounting.settlement_offset_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_settlement_offset_receipt();
CREATE TRIGGER immutable_settlement_offset_receipt
BEFORE UPDATE OR DELETE ON accounting.settlement_offset_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_settlement_offset_receipt
BEFORE TRUNCATE ON accounting.settlement_offset_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();


-- Imported bank rows are an explicit source binding, not an automatic posting.
CREATE OR REPLACE FUNCTION accounting.guard_bank_import_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry;
DECLARE cash_line accounting.line;
DECLARE settlement_line accounting.line;
DECLARE line_count integer;
BEGIN
  SELECT * INTO e FROM accounting.entry
    WHERE id = NEW.entry_id AND organization_id = NEW.organization_id;
  IF e IS NULL OR e.operation <> 'bank_settlement'
     OR e.rule_version <> 'bank-byn-v1'
     OR e.source <> NEW.source OR e.source_version <> 1
     OR e.digest <> NEW.digest THEN
    RAISE EXCEPTION 'Bank import receipt must bind its reviewed bank entry';
  END IF;
  SELECT count(*) INTO line_count FROM accounting.line WHERE entry_id = NEW.entry_id;
  SELECT * INTO cash_line FROM accounting.line WHERE entry_id = NEW.entry_id AND cash;
  SELECT * INTO settlement_line FROM accounting.line WHERE entry_id = NEW.entry_id AND NOT cash;
  IF line_count <> 2 OR cash_line.id IS NULL OR settlement_line.id IS NULL
     OR cash_line.side <> 'debit' OR settlement_line.side <> 'credit'
     OR cash_line.account_code <> NEW.bank_account
     OR settlement_line.account_code <> NEW.settlement_account
     OR cash_line.amount <> NEW.amount OR settlement_line.amount <> NEW.amount
     OR cash_line.currency <> 'BYN' OR settlement_line.currency <> 'BYN'
     OR cash_line.dimensions->>'bank_statement' IS DISTINCT FROM NEW.source_ext_id
     OR NEW.source_transaction_id <= 0 OR NEW.source_digest IS NULL THEN
    RAISE EXCEPTION 'Bank import receipt does not match its two-line BYN settlement';
  END IF;
  IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
     OR NEW.command_digest IS NULL OR NEW.basis_digest IS NULL
     OR NEW.digest IS NULL OR NEW.source = '' THEN
    RAISE EXCEPTION 'Bank import receipt has incomplete source evidence';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER guard_bank_import_receipt
BEFORE INSERT ON accounting.bank_import_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_bank_import_receipt();
CREATE TRIGGER immutable_bank_import_receipt
BEFORE UPDATE OR DELETE ON accounting.bank_import_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_bank_import_receipt
BEFORE TRUNCATE ON accounting.bank_import_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
