/**
 * Standardized data formatters for financial, numeric, and temporal values.
 */

export function formatCurrency(
  val?: number | null,
  compact: boolean = false,
  currencySymbol: string = '₹'
): string {
  if (val === undefined || val === null || isNaN(val)) {
    return `${currencySymbol}0.00`;
  }

  if (compact) {
    const absVal = Math.abs(val);
    if (absVal >= 1_000_000_000) {
      return `${currencySymbol}${(val / 1_000_000_000).toFixed(2)}B`;
    }
    if (absVal >= 1_000_000) {
      return `${currencySymbol}${(val / 1_000_000).toFixed(2)}M`;
    }
    if (absVal >= 1_000) {
      return `${currencySymbol}${(val / 1_000).toFixed(1)}K`;
    }
  }

  return `${currencySymbol}${val.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatNumber(
  val?: number | null,
  decimals: number = 0
): string {
  if (val === undefined || val === null || isNaN(val)) {
    return '0';
  }
  return val.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatPercent(
  val?: number | null,
  decimals: number = 1,
  showPlus: boolean = true
): string {
  if (val === undefined || val === null || isNaN(val)) {
    return '0.0%';
  }
  const prefix = showPlus && val > 0 ? '+' : '';
  return `${prefix}${val.toFixed(decimals)}%`;
}

export function formatDate(val?: string | null): string {
  if (!val) return '—';
  try {
    const d = new Date(val);
    if (isNaN(d.getTime())) return val;
    return d.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return val;
  }
}

export function formatDuration(ms?: number | null): string {
  if (ms === undefined || ms === null || isNaN(ms)) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}
