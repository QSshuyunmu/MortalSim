# Result schema v3

Schema v3 adds an explicit decision and native-runtime identity while retaining
metrics v2.

```json
{
  "schema_version": 3,
  "metrics_version": 2,
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
  batch, and simulation rules;
- failures and cancellations never modify the parent result;
- JSON export preserves the complete identity; the Excel export remains the
  user-facing complete metric table only.
