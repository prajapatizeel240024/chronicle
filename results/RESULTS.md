# Chronicle eval results (offline)
_Synthetic data only. Chronicle is a demo of logging and evaluation, not medical advice. Talk to a clinician about real symptoms._

16 synthetic patients, 849 check-ins, 1604 key events. Generated 2026-10-18T16:49:19.

## Extraction

| extractor | detection F1 | strict P | strict R | strict F1 | severity in range | p50 s | p95 s | $/check-in |
|---|---|---|---|---|---|---|---|---|
| rules-baseline | 99.8% | 85.7% | 85.4% | 85.6% | 82.8% | 0.0 | 0.0 | n/a |

### Per field (rules-baseline)

| field | n | accuracy |
|---|---|---|
| body_site | 122 | 100.0% |
| condition | 1341 | 99.9% |
| date | 1598 | 99.9% |
| med_action | 257 | 100.0% |
| negated | 1598 | 99.8% |
| quote_span | 1598 | 100.0% |
| reality | 1598 | 100.0% |
| severity | 1287 | 82.8% |
| subject | 1598 | 99.9% |
| triggers | 327 | 27.5% |

| class | precision | recall | F1 |
|---|---|---|---|
| negated | 100.0% | 76.5% | 86.7% |
| subject | 95.2% | 100.0% | 97.6% |
| reality | 100.0% | 100.0% | 100.0% |
| attributed | 100.0% | 99.4% | 99.7% |

### Per trap type

| trap | n | recall | strict accuracy | severity in range | date accuracy | message precision |
|---|---|---|---|---|---|---|
| brand_generic | 106 | 100.0% | 100.0% | n/a | 100.0% | 100.0% |
| channel_voice | 451 | 99.8% | 81.6% | 78.6% | 99.8% | 100.0% |
| correction | 17 | 100.0% | 94.1% | 100.0% | 94.1% | 100.0% |
| hypothetical | 17 | 100.0% | 100.0% | n/a | 100.0% | 100.0% |
| last_week | 16 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| med_start_stop | 29 | 100.0% | 100.0% | n/a | 100.0% | 100.0% |
| negation | 17 | 100.0% | 76.5% | n/a | 100.0% | 100.0% |
| other_person | 20 | 100.0% | 100.0% | n/a | 100.0% | 100.0% |
| relative_date | 17 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| routine | 1299 | 100.0% | 82.8% | 81.4% | 100.0% | 100.0% |
| slang | 18 | 66.7% | 66.7% | 100.0% | 100.0% | 100.0% |
| unattributed | 17 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| voice_selfcorrect | 16 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |

## Profile on set days

67 snapshots. Meds F1 100.0%, active-symptom F1 99.9%, condition attribution 99.7%, exact profile match 98.5%.

## Quote check

849 invented events injected, 0 reached the log (catch rate 100.0%).

## Doctor summary

217 claims, 0 unsupported (faithfulness 100.0%). Checker catches 100.0% of planted errors: {'bump_peak': 1.0, 'drop_cites': 1.0, 'fake_cite': 1.0, 'flip_action': 1.0, 'swap_symptom': 1.0, 'wrong_count': 1.0, 'wrong_date': 1.0}.

## Safety

| responder | pass rate | failed cases |
|---|---|---|
| gated(templates) | 100.0% | none |

Judge calibration against 41 hand labels:

| judge | agreement | kappa | false passes | false fails |
|---|---|---|---|---|
| code-grader | 92.7% | 0.8541 | 3 | 0 |
