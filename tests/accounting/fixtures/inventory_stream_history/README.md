# Synthetic inventory stream histories

These three fixtures were captured from exact root
`e3ffab79c3e1c233267a7373f97e1c2c62b3cf01` and the ten module commits listed
in each file. Its original two monetary methods (16 assertions each) and zero
issue scenario (2 assertions) passed with unchanged application and assertions.
Only test infrastructure changed: the fixture starts at registered0145 or0143;
the zero receipt commits before the real0143->0145 upgrade. No production data
is included. These fixtures preserve the historical contract rather than call
the newer physical-document API against an older schema.

The existing historical replay helper executes each original transaction with
all native financial and immutable guards enabled. It checks every complete
stored-row representation, uses database-assigned registration tokens, and
replays the registered0143->0145 transition. Europe/Minsk is declared locally
for source timestamp rendering, including connections defaulting to UTC.

Current tests independently recompute historical evidence for every correction
cutoff, including the entryless revision; assert the original50/60 monetary sale
costs and10/10 then20 expense corrections; and verify the old zero quantity0.5
survives the upgrade with75 stock/25 expense late-cost allocation. A separate
empty registered0144->0145->0144->0145 roundtrip retains the exact legacy
function definition. These proofs do not establish current API or production
acceptance. Current owned physical-output/API scenarios remain separate.
