"""Backtesting and forecast accuracy metrics with safe mathematical bounds."""

import numpy as np

from app.predictive.schemas import EvaluationMetrics


def calc_mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean Absolute Error."""
    if len(y_true) == 0:
        return 0.0
    return float(np.mean(np.abs(y_true - y_pred)))


def calc_rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Root Mean Squared Error."""
    if len(y_true) == 0:
        return 0.0
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def calc_smape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Symmetric Mean Absolute Percentage Error (sMAPE).
    Bounded between 0.0% and 200.0%. Safe against zero values.
    """
    if len(y_true) == 0:
        return 0.0
    denom = (np.abs(y_true) + np.abs(y_pred)) / 2.0
    # Avoid zero division when both true and pred are zero
    mask = denom > 1e-8
    if not np.any(mask):
        return 0.0
    diff = np.abs(y_pred[mask] - y_true[mask])
    smape_val = np.mean(diff / denom[mask]) * 100.0
    return float(round(smape_val, 2))


def calc_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float | None:
    """
    Mean Absolute Percentage Error (MAPE).
    Handles zero values safely by masking zeros. Returns None if all actuals are zero.
    """
    if len(y_true) == 0:
        return None
    mask = np.abs(y_true) > 1e-8
    if not np.any(mask):
        return None
    mape_val = np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100.0
    return float(round(mape_val, 2))


def calc_wape(y_true: np.ndarray, y_pred: np.ndarray) -> float | None:
    """
    Weighted Absolute Percentage Error (WAPE): sum(|y_true - y_pred|) / sum(y_true).
    """
    total_true = float(np.sum(np.abs(y_true)))
    if total_true < 1e-8:
        return None
    wape_val = (float(np.sum(np.abs(y_true - y_pred))) / total_true) * 100.0
    return float(round(wape_val, 2))


def evaluate_forecast(y_true: list[float] | np.ndarray, y_pred: list[float] | np.ndarray) -> EvaluationMetrics:
    """Compute comprehensive validation metrics for out-of-sample predictions."""
    arr_true = np.asarray(y_true, dtype=np.float64)
    arr_pred = np.asarray(y_pred, dtype=np.float64)

    if len(arr_true) != len(arr_pred):
        raise ValueError(f"Length mismatch: y_true ({len(arr_true)}) != y_pred ({len(arr_pred)})")

    mae = calc_mae(arr_true, arr_pred)
    rmse = calc_rmse(arr_true, arr_pred)
    smape = calc_smape(arr_true, arr_pred)
    mape = calc_mape(arr_true, arr_pred)
    wape = calc_wape(arr_true, arr_pred)

    return EvaluationMetrics(
        mae=round(mae, 2),
        rmse=round(rmse, 2),
        mape=mape,
        smape=round(smape, 2),
        wape=wape,
    )
