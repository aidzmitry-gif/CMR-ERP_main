-- Read-only diagnostics before bank_period_guards installation.
-- An empty result means these structural checks found no conflicting rows;
-- it does not certify the books or infer ownership of unbound bank rows.
SELECT 'invalid_bank_binding' AS issue, b.organization_id, NULL::text AS month,
       b.id AS binding_id, b.source_id AS source_transaction_id
FROM accounting.source_binding b
LEFT JOIN finance.bank_transaction s ON s.id=b.source_id
WHERE b.source_type='finance_bank_transaction'
  AND (s.id IS NULL OR b.ownership<>'own')
UNION ALL
SELECT 'closed_period_unposted_bank' AS issue, b.organization_id, p.month,
       b.id AS binding_id, b.source_id AS source_transaction_id
FROM accounting.source_binding b
JOIN finance.bank_transaction s ON s.id=b.source_id
JOIN accounting.period p ON p.organization_id=b.organization_id AND p.closed
LEFT JOIN accounting.bank_import_receipt r
  ON r.organization_id=b.organization_id AND r.source_transaction_id=s.id
WHERE b.source_type='finance_bank_transaction' AND b.ownership='own'
  AND r.entry_id IS NULL
  AND (s.occurred_on IS NULL OR to_char(s.occurred_on,'YYYY-MM')<=p.month)
ORDER BY organization_id, month, binding_id;
