# Definition comparison (2026-09-30 15:24 UTC)

Each model is trained and evaluated on its OWN definition's labels and time splits; metrics are not a champion-vs-challenger comparison across definitions.

## Label rates and baseline performance

| definition   | version      | name           |   dpd |   window |   eligible |   default_rate |   baseline_val_auc |   baseline_val_ks |   baseline_val_ece |
|:-------------|:-------------|:---------------|------:|---------:|-----------:|---------------:|-------------------:|------------------:|-------------------:|
| A            | 57d48e7ce373 | dpd60_ever_12m |    60 |       12 |      26723 |         0.1283 |             0.6696 |            0.2513 |             0.0265 |
| B            | 9a8e4e5657ed | dpd90_ever_12m |    90 |       12 |      26723 |         0.0954 |             0.6726 |            0.2557 |             0.0240 |

## Baseline feature importance (share)

|                |      A |      B |
|:---------------|-------:|-------:|
| bureau_score   | 0.0568 | 0.0500 |
| pmt_to_income  | 0.0527 | 0.0524 |
| util_revolving | 0.0225 | 0.0212 |
| bur_attr_089   | 0.0207 | 0.0209 |
| channel        | 0.0204 | 0.0249 |
| dti            | 0.0192 | 0.0200 |
| bur_attr_048   | 0.0189 | 0.0181 |
| purpose        | 0.0176 | 0.0161 |
| bur_attr_032   | 0.0175 | 0.0156 |
| bur_attr_003   | 0.0173 | 0.0140 |
| bur_attr_023   | 0.0163 | 0.0078 |
| bur_attr_012   | 0.0148 | 0.0145 |
| device_os      | 0.0139 | 0.0236 |
| bur_attr_034   | 0.0127 | 0.0125 |
| bur_attr_103   | 0.0127 | 0.0119 |
| bur_attr_033   | 0.0124 | 0.0113 |
| bur_attr_072   | 0.0124 | 0.0075 |
| inq_6m         | 0.0120 | 0.0144 |
| bur_attr_035   | 0.0120 | 0.0041 |
| bur_attr_055   | 0.0118 | 0.0107 |
