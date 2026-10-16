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
