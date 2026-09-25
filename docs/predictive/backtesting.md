# Time-Series Backtesting & Leakage Prevention

## Overview
Forecasting models in NEXUS must never be evaluated solely on training data. Random cross-validation (e.g. k-fold) is strictly forbidden because it leaks future information into past predictions.

---

## 1. Expanding Window Methodology
NEXUS implements an **Expanding Window Backtesting Engine** (`ExpandingWindowBacktester`):

```
Fold 1:
[======= Train =======] ---> [ Validate ]

Fold 2:
[============ Train ============] ---> [ Validate ]

Fold 3:
[================= Train =================] ---> [ Validate ]
```

### Protocol
1. **Initial Training Split**: The series is partitioned into an initial training set (at least `min_train_periods`).
2. **Out-of-Sample Horizon**: For each fold, the candidate model is fit strictly on history up to index $t$, and predicts periods $t+1$ to $t+h$.
3. **Metric Accumulation**: Errors are evaluated against actual held-out observations.
4. **Window Expansion**: The training boundary advances by $1$ period, and the process repeats across all remaining valid splits.

---

## 2. Leakage Prevention Guarantees
- **No Future Data in Preprocessing**: Normalization, parameter fitting, and trend estimation are recalculated per fold using only observations in that fold's training set.
- **Strict Chronological Ordering**: Time series indexes are asserted to be strictly monotonically increasing.
- **Out-of-Sample Isolation**: Model `.fit()` never accesses or peeks at the target validation sequence.
