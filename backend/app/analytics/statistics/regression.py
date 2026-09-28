"""Deterministic Ordinary Least Squares (OLS) regression engine for driver analysis."""

from typing import List, Dict, Any, Optional
import numpy as np
from scipy import stats
from app.analytics.core.models import (
    RegressionAnalysisResult,
    RegressionCoefficient,
)
from app.analytics.core.exceptions import InsufficientDataError


class RegressionAnalyzer:
    """
    Executes deterministic multivariate and bivariate Ordinary Least Squares (OLS) regression.
    Evaluates parameter significance, multicollinearity diagnostics, overall goodness-of-fit,
    and enforces strict statistical guardrails against confusing association with causation.
    """

    @classmethod
    def fit(
        cls,
        y: List[float],
        X: Dict[str, List[float]],
        dependent_variable_name: str = "target",
        alpha: float = 0.05,
    ) -> RegressionAnalysisResult:
        """
        Fit an OLS model: y = beta_0 + beta_1 * X_1 + ... + beta_k * X_k + epsilon.
        """
        var_names = list(X.keys())
        if not var_names:
            raise ValueError("Regression requires at least one independent variable.")

        # Check lengths
        n_y = len(y)
        for name in var_names:
            if len(X[name]) != n_y:
                raise ValueError(
                    f"Length mismatch: {dependent_variable_name} has {n_y} values, but {name} has {len(X[name])}."
                )

        # Clean NaNs and Infs across all variables simultaneously
        valid_indices = []
        for i in range(n_y):
            yi = y[i]
            if yi is None or np.isnan(yi) or np.isinf(yi):
                continue
            row_valid = True
            for name in var_names:
                xi = X[name][i]
                if xi is None or np.isnan(xi) or np.isinf(xi):
                    row_valid = False
                    break
            if row_valid:
                valid_indices.append(i)

        n = len(valid_indices)
        k = len(var_names)

        # Guardrail: minimum sample size (need at least k + 2 observations)
        if n < k + 2:
            raise InsufficientDataError(
                f"Insufficient sample size for regression with {k} predictors: got {n} valid observations, "
                f"minimum required is {k + 2}."
            )

        y_arr = np.array([y[i] for i in valid_indices], dtype=float)
        X_mat = np.column_stack([[X[name][i] for i in valid_indices] for name in var_names])

        # Guardrail: check zero variance
        if np.var(y_arr) == 0:
            raise ValueError(f"Dependent variable '{dependent_variable_name}' has zero variance (all values identical).")

        zero_var_cols = [var_names[j] for j in range(k) if np.var(X_mat[:, j]) == 0]
        if zero_var_cols:
            raise ValueError(
                f"Independent variables {zero_var_cols} have zero variance (constant values), violating OLS assumptions."
            )

        # Design matrix with intercept: [1, X]
        X_design = np.column_stack([np.ones(n), X_mat])
        all_feature_names = ["Intercept"] + var_names

        # Matrix condition number check for collinearity
        cond_num = float(np.linalg.cond(X_design))
        multicollinearity_flag = cond_num > 30.0

        # Calculate Variance Inflation Factors (VIF) if k >= 2
        vif_dict: Dict[str, Optional[float]] = {}
        if k >= 2:
            for j in range(k):
                target_col = X_mat[:, j]
                other_cols = np.delete(X_mat, j, axis=1)
                other_design = np.column_stack([np.ones(n), other_cols])
                try:
                    beta_aux, _, _, _ = np.linalg.lstsq(other_design, target_col, rcond=None)
                    pred_aux = other_design @ beta_aux
                    ss_tot = np.sum((target_col - np.mean(target_col)) ** 2)
                    ss_res = np.sum((target_col - pred_aux) ** 2)
                    r2_aux = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
                    r2_aux = max(0.0, min(0.9999, r2_aux))
                    vif_val = 1.0 / (1.0 - r2_aux)
                    vif_dict[var_names[j]] = round(float(vif_val), 2)
                    if vif_val > 10.0:
                        multicollinearity_flag = True
                except Exception:
                    vif_dict[var_names[j]] = None
        else:
            vif_dict[var_names[0]] = 1.0

        # Solve OLS via Moore-Penrose pseudo-inverse / QR decomposition
        beta, residuals, rank, s = np.linalg.lstsq(X_design, y_arr, rcond=None)
        matrix_rank_val = int(rank)
        is_rank_deficient = matrix_rank_val < (k + 1)

        # Fitted values and residuals
        y_hat = X_design @ beta
        e = y_arr - y_hat
        ssr = float(np.sum(e ** 2))
        y_mean = float(np.mean(y_arr))
        sst = float(np.sum((y_arr - y_mean) ** 2))

        df_model = k
        df_residuals = n - k - 1

        r_squared = max(0.0, min(1.0, 1.0 - (ssr / sst))) if sst > 0 else 0.0
        adj_r_squared = 1.0 - ((ssr / df_residuals) / (sst / (n - 1))) if (sst > 0 and df_residuals > 0 and n > 1) else 0.0
        adj_r_squared = max(-1.0, min(1.0, adj_r_squared))

        # Residual standard error
        mse_resid = (ssr / df_residuals) if df_residuals > 0 else 0.0
        rse = float(np.sqrt(mse_resid))

        # Overall F-statistic
        sse = sst - ssr
        ms_model = sse / df_model if df_model > 0 else 0.0
        f_stat = (ms_model / mse_resid) if mse_resid > 0 else 0.0
        f_pval = float(1.0 - stats.f.cdf(f_stat, df_model, df_residuals)) if (df_model > 0 and df_residuals > 0) else 1.0

        # Parameter inference: Cov(beta) = mse_resid * (X^T X)^(-1)
        try:
            xtx_inv = np.linalg.inv(X_design.T @ X_design)
            var_beta = mse_resid * xtx_inv
            se_beta = np.sqrt(np.maximum(0.0, np.diag(var_beta)))
        except np.linalg.LinAlgError:
            # Fallback to pseudo-inverse for rank-deficient / ill-conditioned design matrix
            xtx_inv = np.linalg.pinv(X_design.T @ X_design)
            var_beta = mse_resid * xtx_inv
            se_beta = np.sqrt(np.maximum(0.0, np.diag(var_beta)))

        # Diagnostics: Leverage and Cook's distance
        h = np.sum((X_design @ xtx_inv) * X_design, axis=1)
        avg_leverage = (k + 1) / n
        high_leverage_count = int(np.sum(h > 2.0 * avg_leverage))

        cooks_d = np.zeros(n, dtype=float)
        if mse_resid > 0:
            denom_c = (k + 1) * mse_resid * ((1.0 - h) ** 2)
            valid_c = (denom_c > 1e-12) & (h < 1.0)
            cooks_d[valid_c] = (e[valid_c] ** 2 * h[valid_c]) / denom_c[valid_c]
        influential_count = int(np.sum(cooks_d > (4.0 / n)))
        max_cooks_val = float(np.max(cooks_d)) if n > 0 else 0.0

        # Diagnostics: Durbin-Watson statistic for residual autocorrelation
        diff_e = np.diff(e)
        sum_e2 = np.sum(e ** 2)
        dw_stat = float(np.sum(diff_e ** 2) / sum_e2) if sum_e2 > 0 else 2.0
        autocorr_flag = bool(dw_stat < 1.5 or dw_stat > 2.5)

        # Diagnostics: Breusch-Pagan LM test for heteroskedasticity
        e2 = e ** 2
        e2_mean = np.mean(e2)
        sst_e2 = np.sum((e2 - e2_mean) ** 2)
        if sst_e2 > 1e-12:
            beta_bp, _, _, _ = np.linalg.lstsq(X_design, e2, rcond=None)
            pred_e2 = X_design @ beta_bp
            ssr_e2 = np.sum((e2 - pred_e2) ** 2)
            r2_bp = max(0.0, min(1.0, 1.0 - (ssr_e2 / sst_e2)))
            bp_stat = float(n * r2_bp)
            bp_pval = float(1.0 - stats.chi2.cdf(bp_stat, df=k))
        else:
            bp_stat = 0.0
            bp_pval = 1.0
        heteroskedasticity_flag = bool(bp_pval < alpha)

        # Diagnostics: Residual normality evaluation
        from app.analytics.statistics.normality import evaluate_normality
        resid_norm = evaluate_normality(e, alpha=alpha)
        residuals_normal = resid_norm.is_normal
        residuals_norm_pval = resid_norm.p_value

        robust_se_recommended = bool(heteroskedasticity_flag or not residuals_normal)

        t_crit = float(stats.t.ppf(1 - alpha / 2, df=df_residuals)) if df_residuals > 0 else 1.96

        coefficients_list: List[RegressionCoefficient] = []
        for idx, feat_name in enumerate(all_feature_names):
            coef_val = float(beta[idx])
            se_val = float(se_beta[idx])
            t_stat = (coef_val / se_val) if se_val > 0 else 0.0
            p_val = float(2.0 * (1.0 - stats.t.cdf(abs(t_stat), df=df_residuals))) if df_residuals > 0 else 1.0
            moe = t_crit * se_val
            vif_for_feat = vif_dict.get(feat_name) if feat_name != "Intercept" else None

            coefficients_list.append(
                RegressionCoefficient(
                    variable=feat_name,
                    coefficient=round(coef_val, 4),
                    standard_error=round(se_val, 4),
                    t_statistic=round(t_stat, 4),
                    p_value=round(p_val, 6),
                    ci_lower=round(coef_val - moe, 4),
                    ci_upper=round(coef_val + moe, 4),
                    vif=vif_for_feat,
                )
            )

        is_model_sig = f_pval < alpha

        # Limitations list
        limitations: List[str] = [
            "Ordinary Least Squares assumes linear relationships, homoskedastic errors, and normally distributed residuals.",
            "Unmeasured confounding variables and omitted factors may bias parameter estimates.",
            "Statistical association does not demonstrate or validate real-world causality.",
        ]
        if is_rank_deficient:
            limitations.append(
                f"Predictor design matrix is rank-deficient (rank {matrix_rank_val} < {k+1}); "
                f"exact collinearity exists; parameter estimates are not uniquely identifiable."
            )
        if n < 5 * k:
            limitations.append(
                f"Small sample size relative to predictors ({n} observations for {k} predictors, ratio < 5:1); "
                f"higher risk of parameter instability and sample overfitting."
            )
        if multicollinearity_flag:
            limitations.append(
                f"High condition number ({cond_num:.1f}) or elevated VIF detected; "
                f"individual predictor coefficients may exhibit high variance or inflated standard errors."
            )
        if heteroskedasticity_flag:
            limitations.append(
                f"Residual heteroskedasticity detected (Breusch-Pagan LM={bp_stat:.2f}, p={bp_pval:.4f}); "
                f"homoskedasticity assumption violated; standard errors may be biased."
            )
        if autocorr_flag:
            limitations.append(
                f"Residual autocorrelation detected (Durbin-Watson={dw_stat:.2f}); "
                f"error independence assumption violated, indicating unmodeled serial correlation."
            )
        if influential_count > 0:
            limitations.append(
                f"{influential_count} influential observation(s) exceed Cook's distance threshold (4/n); "
                f"max Cook's D={max_cooks_val:.2f}."
            )
        if robust_se_recommended:
            limitations.append(
                "Robust standard errors (HC1/HC3) recommended due to error non-normality or heteroskedasticity."
            )

        # Senior-level synthesis interpretation
        sig_drivers = [
            c for c in coefficients_list
            if c.variable != "Intercept" and c.p_value < alpha
        ]
        driver_summary = ", ".join(
            [f"{c.variable} (coef={c.coefficient:+.3f}, p={c.p_value:.4f})" for c in sig_drivers]
        ) if sig_drivers else "None of the evaluated predictors reached statistical significance."

        interp = (
            f"OLS regression explains {r_squared * 100:.1f}% of the variance in {dependent_variable_name} "
            f"(Adj R²={adj_r_squared * 100:.1f}%, F({df_model}, {df_residuals})={f_stat:.2f}, p={f_pval:.4f}). "
            f"Statistically significant drivers: {driver_summary}."
        )

        return RegressionAnalysisResult(
            dependent_variable=dependent_variable_name,
            independent_variables=var_names,
            sample_size=n,
            degrees_of_freedom_model=df_model,
            degrees_of_freedom_residuals=df_residuals,
            r_squared=round(r_squared, 4),
            adjusted_r_squared=round(adj_r_squared, 4),
            f_statistic=round(f_stat, 4),
            f_pvalue=round(f_pval, 6),
            residual_standard_error=round(rse, 4),
            coefficients=coefficients_list,
            condition_number=round(cond_num, 2),
            multicollinearity_warning=multicollinearity_flag,
            durbin_watson_statistic=round(dw_stat, 4),
            residual_autocorrelation_warning=autocorr_flag,
            breusch_pagan_statistic=round(bp_stat, 4),
            breusch_pagan_p_value=round(bp_pval, 6),
            heteroskedasticity_warning=heteroskedasticity_flag,
            robust_standard_errors_recommended=robust_se_recommended,
            matrix_rank=matrix_rank_val,
            is_rank_deficient=is_rank_deficient,
            residuals_normal=residuals_normal,
            residuals_normality_p_value=residuals_norm_pval,
            influential_observations_count=influential_count,
            max_cooks_distance=round(max_cooks_val, 4),
            high_leverage_observations_count=high_leverage_count,
            is_statistically_significant=is_model_sig,
            interpretation=interp,
            limitations=limitations,
        )
