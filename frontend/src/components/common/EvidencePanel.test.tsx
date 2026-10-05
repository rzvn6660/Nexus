import { describe, it, expect } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  EvidencePanel,
  formatCalculationClass,
  formatModelName,
} from './EvidencePanel';
import { EvidenceRecord, ForecastEvidence } from '../../types/api';

describe('EvidencePanel UI Formatting & Regression Suite', () => {
  describe('formatCalculationClass', () => {
    it('formats snake_case deterministic_sql_aggregation into title case with preserved acronyms', () => {
      expect(formatCalculationClass('deterministic_sql_aggregation')).toBe(
        'Deterministic SQL Aggregation'
      );
    });

    it('preserves and capitalizes key domain acronyms like GAAP, ARIMA, and AOV', () => {
      expect(formatCalculationClass('gaap_compliant_revenue')).toBe('GAAP Compliant Revenue');
      expect(formatCalculationClass('arima_autoregressive_model')).toBe('ARIMA Autoregressive Model');
      expect(formatCalculationClass('rolling_aov_calculation')).toBe('Rolling AOV Calculation');
    });

    it('returns default fallback when null or undefined', () => {
      expect(formatCalculationClass(null)).toBe('Deterministic Calculation');
      expect(formatCalculationClass(undefined)).toBe('Deterministic Calculation');
      expect(formatCalculationClass('')).toBe('Deterministic Calculation');
    });
  });

  describe('formatModelName', () => {
    it('handles standard models and capitalizes correctly', () => {
      expect(formatModelName('linear_regression')).toBe('Linear Regression');
      expect(formatModelName('arima')).toBe('ARIMA');
      expect(formatModelName('exponential_smoothing')).toBe('Exponential Smoothing');
      expect(formatModelName(null)).toBe('Standard');
    });
  });

  describe('HTML Rendering & Container Constraints', () => {
    const mockEvidence: EvidenceRecord = {
      evidence_id: 'ev_test_1234567890abcdef',
      analysis_id: 'an_test_987654321',
      calculation_type: 'deterministic_sql_aggregation',
      row_count: 60,
      execution_time_ms: 18.4,
      mathematical_formula: 'SUM(sales.subtotal - sales.discount_amount)',
      source_tables: ['sales'],
      source_columns: ['subtotal', 'discount_amount', 'id', 'status', 'business_id'],
      supporting_sources: ['sale_items', 'products', 'expenses'],
      filter_predicates: {
        business_id: 'test-business-uuid-1234',
        status: ['completed', 'shipped'],
        order_date: '>= 2026-01-01',
      },
      checksum: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
      assumptions: ['Foreign keys verified', 'Transactions finalized'],
      limitations: ['Excludes draft orders', 'Does not reflect refunded fees after settlement'],
    };

    it('renders Business View with proper word-break, formula container, and min-w-0 classes', () => {
      const html = renderToStaticMarkup(
        React.createElement(EvidencePanel, {
          evidence: mockEvidence,
          isOpen: true,
          asModal: true,
          initialViewMode: 'business',
        })
      );

      // Verify formatted calculation class is rendered
      expect(html).toContain('Deterministic SQL Aggregation');

      // Verify calculation class container uses overflow wrap / break words
      expect(html).toContain('[overflow-wrap:anywhere]');
      expect(html).toContain('break-words');

      // Verify min-w-0 constraints for flex/grid cells
      expect(html).toContain('min-w-0');

      // Verify sample size and execution latency
      expect(html).toContain('60 rows evaluated');
      expect(html).toContain('18 ms');

      // Verify formal formula block is wrapped in dedicated container with break-all
      expect(html).toContain('SUM(sales.subtotal - sales.discount_amount)');
      expect(html).toContain('break-all');
      expect(html).toContain('whitespace-pre-wrap');

      // Verify Domain Assumptions & Limitations
      expect(html).toContain('Domain Assumptions:');
      expect(html).toContain('Foreign keys verified');
      expect(html).toContain('Analytical Limitations:');
      expect(html).toContain('Excludes draft orders');
    });

    it('renders Analyst View with structured chips, scrollable SQL code block, and truncated checksum', () => {
      const html = renderToStaticMarkup(
        React.createElement(EvidencePanel, {
          evidence: mockEvidence,
          isOpen: true,
          asModal: true,
          initialViewMode: 'analyst',
        })
      );

      // Verify source database lineage header
      expect(html).toContain('Source Database Lineage');

      // Verify Contributing Tables are rendered as structured chips
      expect(html).toContain('Contributing Tables');
      expect(html).toContain('sales');

      // Verify Queried Columns are rendered as individual badges inside scroll container
      expect(html).toContain('Queried Columns');
      expect(html).toContain('subtotal');
      expect(html).toContain('discount_amount');
      expect(html).toContain('business_id');

      // Verify Data Availability Probes are rendered as structured probe chips
      expect(html).toContain('Data Availability Probes');
      expect(html).toContain('sale_items');
      expect(html).toContain('products');
      expect(html).toContain('expenses');
      expect(html).toContain('0 rows / non-contributing');

      // Verify Applied SQL Predicates has scrollable pre container
      expect(html).toContain('Applied SQL Predicates');
      expect(html).toContain('overflow-x-auto');
      expect(html).toContain('overflow-y-auto');
      expect(html).toContain('max-h-56');
      expect(html).toContain('test-business-uuid-1234');
      expect(html).toContain('Tenant boundary verified: business_id isolated');

      // Verify Checksum container with visual truncation and copy button
      expect(html).toContain('SHA-256 Checksum:');
      expect(html).toContain('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
      expect(html).toContain('truncate');
      expect(html).toContain('Copy');
    });

    it('renders with long values without exploding layout or visual collision', () => {
      const longEvidence: EvidenceRecord = {
        evidence_id: 'ev_very_long_custom_identifier_with_excessive_length_0123456789abcdef',
        calculation_type: 'extremely_long_composite_deterministic_sql_aggregation_pipeline_method',
        mathematical_formula:
          'SUM(sales.subtotal * (1 - sales.discount_rate) + sales.tax_amount - sales.refunded_credit_amount_prior_period_adjustment) / NULLIF(COUNT(DISTINCT sales.customer_id), 0)',
        source_tables: ['sales_master_partition_v2_2026_q1', 'order_fulfillment_events_audit_log'],
        source_columns: [
          'transaction_identifier_uuid',
          'subtotal_invoiced_cents',
          'discount_applied_cents',
          'settlement_timestamp_utc',
        ],
        checksum:
          'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad_ultra_long_hash_string_64_plus_bytes',
      };

      const html = renderToStaticMarkup(
        React.createElement(EvidencePanel, {
          evidence: longEvidence,
          isOpen: true,
          initialViewMode: 'analyst',
        })
      );

      // Should format calculation class cleanly and protect against overflow
      expect(html).toContain('Extremely Long Composite Deterministic SQL Aggregation Pipeline Method');

      // Long formula must be present in code block with break-all
      expect(html).toContain('SUM(sales.subtotal');
      expect(html).toContain('break-all');

      // Long source tables & columns rendered safely as chips
      expect(html).toContain('sales_master_partition_v2_2026_q1');
      expect(html).toContain('transaction_identifier_uuid');

      // Checksum container exists with truncate
      expect(html).toContain('truncate');
    });

    it('renders Forecast Provenance in Business View with quick metrics and rationale', () => {
      const mockForecastEvidence: ForecastEvidence = {
        forecast_id: 'fc_test_001',
        target_metric: 'revenue',
        frequency: 'D',
        forecast_horizon: 14,
        selected_model: 'arima',
        model_version: '2.1',
        data_quality_status: 'verified',
        selected_model_rationale: 'Optimal AIC score and lowest backtest sMAPE across validation windows.',
        validation_metrics: {
          mae: 142.5,
          rmse: 198.3,
          smape: 4.8,
        },
      };

      const html = renderToStaticMarkup(
        React.createElement(EvidencePanel, {
          forecastEvidence: mockForecastEvidence,
          isOpen: true,
          asModal: true,
          initialViewMode: 'business',
        })
      );

      // Check header model display
      expect(html).toContain('Model: ARIMA (v2.1)');

      // Check quick metric cards with min-w-0
      expect(html).toContain('BACKTEST MAE');
      expect(html).toContain('142.50');
      expect(html).toContain('BACKTEST RMSE');
      expect(html).toContain('198.30');
      expect(html).toContain('BACKTEST SMAPE');
      expect(html).toContain('4.8%');
      expect(html).toContain('DATA QUALITY');
      expect(html).toContain('verified');

      // Check rationale
      expect(html).toContain('Model Selection Rationale');
      expect(html).toContain('Optimal AIC score and lowest backtest sMAPE');
    });

    it('renders Forecast Provenance in Analyst View with candidate tournament table and training lineage', () => {
      const mockForecastEvidence: ForecastEvidence = {
        forecast_id: 'fc_test_002',
        target_metric: 'revenue',
        frequency: 'D',
        forecast_horizon: 14,
        selected_model: 'arima',
        model_version: '2.1',
        data_quality_status: 'verified',
        candidate_evaluations: {
          arima: { mae: 142.5, rmse: 198.3, smape: 4.8 },
          linear_regression: { mae: 210.1, rmse: 280.4, smape: 8.2 },
          exponential_smoothing: { mae: 185.0, rmse: 245.2, smape: 6.5 },
        },
        source_tables: ['daily_sales_aggregates'],
        source_columns: ['ds', 'y', 'store_id'],
        training_range: {
          from: '2025-01-01',
          to: '2026-03-31',
        },
      };

      const html = renderToStaticMarkup(
        React.createElement(EvidencePanel, {
          forecastEvidence: mockForecastEvidence,
          isOpen: true,
          asModal: true,
          initialViewMode: 'analyst',
        })
      );

      // Check candidate evaluations tournament
      expect(html).toContain('Candidate Model Backtest Tournament');
      expect(html).toContain('Selected (Optimal)');
      expect(html).toContain('Linear Regression');
      expect(html).toContain('Exponential Smoothing');

      // Check table has horizontal scroll container
      expect(html).toContain('overflow-x-auto');
      expect(html).toContain('min-w-[480px]');

      // Check source tables and columns rendered as chips
      expect(html).toContain('daily_sales_aggregates');
      expect(html).toContain('store_id');
      expect(html).toContain('2025-01-01 to 2026-03-31');
    });
  });
});
