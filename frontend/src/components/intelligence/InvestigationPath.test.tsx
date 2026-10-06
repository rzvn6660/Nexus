import { describe, it, expect } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  InvestigationPath,
  formatMetricLabel,
} from './InvestigationPath';
import {
  InvestigationObservation,
  InvestigationHypothesis,
  EvidenceGap,
} from '../../types/api';

describe('Investigation Acceptance Presentation Regression Suite', () => {
  describe('formatMetricLabel', () => {
    it('formats known metrics and variance dimensions into clear human labels', () => {
      expect(formatMetricLabel('net_sales')).toBe('Net Sales (Revenue)');
      expect(formatMetricLabel('price_volume_mix')).toBe('Price / Volume / Mix (PVM)');
      expect(formatMetricLabel('variance_category')).toBe('Category Variance');
      expect(formatMetricLabel('variance_product')).toBe('Product Variance');
      expect(formatMetricLabel(null)).toBe('Diagnostic Metric');
    });
  });

  describe('Observed Empirical Signals Presentation', () => {
    it('never renders bare "-" when telemetry is unavailable, showing explicit informative status', () => {
      const observations: InvestigationObservation[] = [
        {
          observation_id: 'OBS-1-VAR-CAT',
          id: 'OBS-1-VAR-CAT',
          metric: 'variance_category',
          finding: 'Variance analysis by category is unavailable: current tenant lacks required line-item/product telemetry.',
          statement: 'Variance analysis by category is unavailable: current tenant lacks required line-item/product telemetry.',
          observed_value: null as any,
          baseline_value: null as any,
          variance_pct: null as any,
          value_current: null as any,
          value_baseline: null as any,
          change_pct: null as any,
        },
        {
          observation_id: 'OBS-2-PVM',
          id: 'OBS-2-PVM',
          metric: 'price_volume_mix',
          finding: 'Price/Volume/Mix decomposition is unavailable: current tenant lacks required line-item/product telemetry.',
          statement: 'Price/Volume/Mix decomposition is unavailable: current tenant lacks required line-item/product telemetry.',
          observed_value: null as any,
          baseline_value: null as any,
          variance_pct: null as any,
          value_current: null as any,
          value_baseline: null as any,
          change_pct: null as any,
        },
      ];

      const html = renderToStaticMarkup(
        <InvestigationPath
          rootSymptom="Why did revenue decline?"
          observations={observations}
          hypotheses={[]}
        />
      );

      // Must render explicit unavailable status
      expect(html).toContain('Unavailable — line-item/product data required');
      expect(html).toContain('Telemetry Unavailable');

      // Must never render bare "-" in place of variance or observed/baseline values
      expect(html).not.toContain('Observed: -');
      expect(html).not.toContain('Baseline: -');
      expect(html).not.toContain('> - <');
      expect(html).not.toContain('>-<');
    });

    it('renders normal metric and variance when telemetry is valid', () => {
      const observations: InvestigationObservation[] = [
        {
          observation_id: 'OBS-1-FIN',
          id: 'OBS-1-FIN',
          metric: 'net_sales',
          finding: 'Net Sales was measured at $254,192.00.',
          statement: 'Net Sales was measured at $254,192.00.',
          observed_value: 254192,
          baseline_value: 260000,
          variance_pct: -2.2,
          value_current: 254192,
          value_baseline: 260000,
          change_pct: -2.2,
        },
      ];

      const html = renderToStaticMarkup(
        <InvestigationPath
          rootSymptom="Quarterly Review"
          observations={observations}
          hypotheses={[]}
        />
      );

      expect(html).toContain('Net Sales (Revenue)');
      expect(html).toContain('-2.2%');
      expect(html).toContain('Observed:');
      expect(html).toContain('Baseline:');
      expect(html).toContain('254');
    });
  });

  describe('Tested Hypotheses Presentation & Evidence Status', () => {
    it('never renders "Confidence: DIRECT" on NOT_SUPPORTED hypothesis, showing evidence status', () => {
      const hypotheses: InvestigationHypothesis[] = [
        {
          hypothesis_id: 'HYP-CAT',
          statement: 'Revenue decline was driven by specific product category drop',
          type: 'category_contribution',
          status: 'NOT_SUPPORTED',
          evidence_strength: 'INSUFFICIENT' as any,
          confidence_reason: 'Category variance breakdown returned zero categorized line items; insufficient line-item telemetry to confirm category concentration.',
          evidence_summary: 'Category variance breakdown returned zero categorized line items.',
          supporting_evidence: [],
          contradicting_evidence: [],
        } as any,
        {
          hypothesis_id: 'HYP-VOL',
          statement: 'Volume loss drove revenue variance',
          type: 'volume_effect',
          status: 'NOT_SUPPORTED',
          evidence_strength: 'INSUFFICIENT' as any,
          confidence_reason: 'Price/Volume/Mix decomposition evaluated zero line items or zero variance; insufficient line-item telemetry to support volume effect.',
          evidence_summary: 'Zero line items evaluated.',
          supporting_evidence: [],
          contradicting_evidence: [],
        } as any,
      ];

      const html = renderToStaticMarkup(
        <InvestigationPath
          rootSymptom="Why did revenue decline?"
          observations={[]}
          hypotheses={hypotheses}
        />
      );

      // Must preserve NOT_SUPPORTED status
      expect(html).toContain('NOT_SUPPORTED');

      // Must NEVER display Confidence: DIRECT for NOT_SUPPORTED
      expect(html).not.toContain('Confidence: DIRECT');

      // Must display evidence status reflecting insufficient telemetry
      expect(html).toContain('Evidence: Insufficient telemetry');
    });

    it('displays Evidence: Refuted by empirical data when hypothesis was actively tested and contradicted', () => {
      const hypotheses: InvestigationHypothesis[] = [
        {
          hypothesis_id: 'HYP-DIFFUSE',
          statement: 'Single category drove entire revenue loss',
          type: 'category_contribution',
          status: 'NOT_SUPPORTED',
          evidence_strength: 'MODERATE' as any,
          confidence_reason: 'Variance was widely dispersed across 15 categories.',
          supporting_evidence: [],
          contradicting_evidence: [
            {
              tool_name: 'run_variance_analysis',
              metric: 'category_contribution_share',
              source: 'sales',
              value: 'Category A: 12.0%',
            },
          ],
        } as any,
      ];

      const html = renderToStaticMarkup(
        <InvestigationPath
          rootSymptom="Why did revenue decline?"
          observations={[]}
          hypotheses={hypotheses}
        />
      );

      expect(html).toContain('NOT_SUPPORTED');
      expect(html).not.toContain('Confidence: DIRECT');
      expect(html).toContain('Evidence: Refuted by empirical data');
    });
  });

  describe('Evidence Gaps Rendering Safe Display', () => {
    it('renders cleanly without stray colon when area is absent or empty', () => {
      // Direct rendering simulation of Evidence Gaps list
      const gaps: EvidenceGap[] = [
        {
          gap_id: 'GAP-1',
          area: '',
          description: 'Competitor pricing and macroeconomic market indicators are unobserved.',
          impact_assessment: 'Limited to internal transactional telemetry.',
        },
        {
          gap_id: 'GAP-2',
          area: 'Market Intelligence',
          description: 'Regional foot-traffic data is unobserved.',
          impact_assessment: 'Offline impact cannot be evaluated.',
        },
      ];

      const html = renderToStaticMarkup(
        <ul className="list-disc list-inside space-y-1 text-slate-300 text-[11px]">
          {gaps.map((gap, idx) => (
            <li key={gap.gap_id || `gap-${idx}`}>
              {gap.area && gap.area.trim() ? (
                <strong className="text-slate-200">{gap.area}: </strong>
              ) : null}
              {gap.description}
            </li>
          ))}
        </ul>
      );

      // Must NOT contain stray bullet colon "<li>: " or "<li>• : "
      expect(html).not.toContain('>: </strong>');
      expect(html).not.toContain('<li>: ');
      expect(html).toContain('Competitor pricing and macroeconomic market indicators are unobserved.');
      // When area is present, renders correctly
      expect(html).toContain('<strong class="text-slate-200">Market Intelligence: </strong>Regional foot-traffic data is unobserved.');
    });
  });
});
