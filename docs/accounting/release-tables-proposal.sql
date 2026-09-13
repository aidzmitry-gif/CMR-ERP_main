-- Test fixture excerpt of the release tables frozen in migration 0130.
-- Existing WMS tables must exist; production uses the registered migration.

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
