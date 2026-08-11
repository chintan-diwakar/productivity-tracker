# Version 0.1 Metrics

## Product metric

Version `0.1` ships one main product metric: **focused active time**.

```text
focused active time = focused time / (focused time + possible phone-use time)
```

The denominator includes only classified active time. It excludes uncertain, away, idle, paused, and error time.

The application displays `Not enough data` for a zero denominator.

This metric estimates visible desk behavior. It does not measure the value or quality of work.

## Coverage guardrail

The interface also shows **classified coverage**.

```text
classified coverage = classified active time / (classified active time + uncertain time)
```

Low coverage means that the focus percentage represents a small part of visible time. Read the two metrics together.

Away, system idle, paused, and camera-error time does not enter this calculation.

## Detector release metric

The primary detector metric is **possible-phone-use precision**.

```text
phone-use precision = correct phone-use predictions / all phone-use predictions
```

Precision is the first quality gate because a false phone label directly reduces focused active time.

The provisional stable-release target is at least `90%` precision. The data set must contain at least 100 phone-use predictions.

The evaluation must also report recall, false-positive rate, uncertain rate, support, and a confusion matrix.

Version `1.0.0` has no real-world baseline for phone-use precision. An accuracy claim needs a representative labeled set.

## Evaluation file

Create one JSON object for each labeled sample. Store the objects in a JSON Lines file.

```json
{"actual_status":"POSSIBLE_PHONE_USE","predicted_status":"POSSIBLE_PHONE_USE"}
{"actual_status":"FOCUSED_SCREEN","predicted_status":"LOOKING_DOWN"}
```

Use one of the status codes from [PRODUCT_SPEC.md](../PRODUCT_SPEC.md).

Create the report:

```bash
kyf evaluate labels.jsonl --output evaluation-report.json
```

The report contains the primary metric and the full confusion matrix. Keep the labeled source with each report.

Do not use frames from people who did not consent to the evaluation.
