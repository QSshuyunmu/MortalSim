# Result schema v3

Schema v3 adds an explicit decision and native-runtime identity while retaining
metrics v2.

```json
{
  "schema_version": 3,
  "metrics_version": 2,
  "merge_state_version": 2,
  "decision_contract": "stable_advantage_v2",
  "runtime": {
    "engine_id": "aoti-cuda-sm89",
    "artifact_sha256": "...",
    "build_id": "v0.3.0rc1-...",
    "compute_capability": "8.9",
    "batch_size": 1000,
    "batch_capacity": 1024,
    "precision_profile": "amp-static-advantage"
  }
}
```

Rules:

- schema v1/v2 records remain readable and exportable;
- schema v1/v2 records are read-only and cannot be extended into v3;
- the “rerun as Formal Lite” operation creates a new v3 record;
- extension merge requires exact model SHA, decision contract, runtime identity,
  batch, simulation rules, and `merge_state_version: 2`;
- merge state v2 persists exact event denominators and sums for scalar averages.
  In particular, a double ron is one terminal `self_deal_in` game but two
  `houjuu` events, so defense averages cannot be merged by terminal-game count;
- early schema-v3 RC records without merge state v2 remain readable and
  exportable, but are read-only and must be rerun before extension;
- failures and cancellations never modify the parent result;
- JSON export preserves the complete identity; the Excel export remains the
  user-facing complete metric table only.
