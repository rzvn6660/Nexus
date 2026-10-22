import { describe, it, expect } from 'vitest';
import {
  resolveLocalKpiFallback,
  getResolverBadgeConfig,
  KnowledgeResolvedResult,
} from './KnowledgePage';
import { KPIResponse, SemanticResolveResponse } from '../types/api';

const MOCK_KPIS: KPIResponse[] = [
  {
    canonical_name: 'net_revenue',
    display_name: 'Net Revenue',
    description: 'Gross sales less returns, discounts, and allowances.',
    synonyms: ['sales', 'revenue', 'topline', 'turnover'],
    analytics_tool: 'financial_analytics',
    metric_field: 'total_net_amount',
    calculation_reference: 'SUM(gross_sales) - SUM(returns) - SUM(discounts)',
    unit: 'USD',
    business_domain: 'commercial',
    status: 'ACTIVE',
  },
  {
    canonical_name: 'gross_margin',
    display_name: 'Gross Margin',
    description: 'Revenue less cost of goods sold as a percentage of revenue.',
    synonyms: ['margin', 'gm'],
    analytics_tool: 'financial_analytics',
    metric_field: 'margin_pct',
    calculation_reference: '(SUM(net_revenue) - SUM(cogs)) / SUM(net_revenue)',
    unit: '%',
    business_domain: 'finance',
    status: 'ACTIVE',
  },
];

describe('Knowledge Resolver Provenance Suite (Finding M-01)', () => {
  describe('resolveLocalKpiFallback', () => {
    it('matches local KPI catalog by canonical_name (case-insensitive)', () => {
      const result = resolveLocalKpiFallback('NET_REVENUE', MOCK_KPIS, new Error('Network timeout'));
      expect(result).not.toBeNull();
      expect(result?.canonical_name).toBe('net_revenue');
      expect(result?.is_client_fallback).toBe(true);
      expect(result?.fallback_reason).toBe('Network timeout');
      expect(result?.is_ambiguous).toBe(false);
      expect(result?.candidate_kpis).toHaveLength(1);
    });

    it('matches local KPI catalog by display_name (case-insensitive)', () => {
      const result = resolveLocalKpiFallback('Gross Margin', MOCK_KPIS);
      expect(result).not.toBeNull();
      expect(result?.canonical_name).toBe('gross_margin');
      expect(result?.display_name).toBe('Gross Margin');
      expect(result?.is_client_fallback).toBe(true);
    });

    it('matches local KPI catalog by registered synonyms', () => {
      const result = resolveLocalKpiFallback('topline', MOCK_KPIS, {
        data: { detail: 'PostgreSQL connection refused' },
      });
      expect(result).not.toBeNull();
      expect(result?.canonical_name).toBe('net_revenue');
      expect(result?.is_client_fallback).toBe(true);
      expect(result?.fallback_reason).toBe('PostgreSQL connection refused');
    });

    it('returns null when query has no matching KPI in local catalog', () => {
      const result = resolveLocalKpiFallback('unknown_arbitrary_term', MOCK_KPIS);
      expect(result).toBeNull();
    });

    it('preserves failure context from server error without erasing it', () => {
      const customErr = { message: '503 Service Unavailable: Semantic Engine Down' };
      const result = resolveLocalKpiFallback('revenue', MOCK_KPIS, customErr);
      expect(result?.fallback_reason).toBe('503 Service Unavailable: Semantic Engine Down');
      expect(result?.is_client_fallback).toBe(true);
    });
  });

  describe('getResolverBadgeConfig', () => {
    it('renders visibly distinct amber RESOLVED (OFFLINE CATALOG) status for client-side fallback', () => {
      const fallbackResult: KnowledgeResolvedResult = {
        query: 'revenue',
        canonical_name: 'net_revenue',
        is_ambiguous: false,
        candidate_kpis: [],
        is_supported: true,
        availability_status: 'AVAILABLE',
        is_client_fallback: true,
        fallback_reason: 'Semantic service offline',
      };

      const config = getResolverBadgeConfig(fallbackResult);
      expect(config.isFallback).toBe(true);
      expect(config.badgeText).toBe('RESOLVED (OFFLINE CATALOG)');
      expect(config.badgeClasses).toContain('amber');
      expect(config.badgeClasses).not.toContain('emerald');
    });

    it('never returns green RESOLVED CANONICAL for a local fallback result', () => {
      const fallbackResult: KnowledgeResolvedResult = {
        query: 'revenue',
        canonical_name: 'net_revenue',
        is_ambiguous: false,
        candidate_kpis: [],
        is_supported: true,
        availability_status: 'AVAILABLE', // Even if availability_status is 'AVAILABLE'
        is_client_fallback: true,
      };

      const config = getResolverBadgeConfig(fallbackResult);
      expect(config.badgeText).not.toBe('RESOLVED CANONICAL');
      expect(config.badgeText).toBe('RESOLVED (OFFLINE CATALOG)');
    });

    it('preserves authoritative green RESOLVED CANONICAL status for genuine server resolution', () => {
      const authoritativeResult: SemanticResolveResponse = {
        query: 'net revenue',
        canonical_name: 'net_revenue',
        canonical_kpi: 'net_revenue',
        display_name: 'Net Revenue',
        availability_status: 'AVAILABLE',
        is_ambiguous: false,
        candidate_kpis: [],
        is_supported: true,
        semantic_version: 1,
      };

      const config = getResolverBadgeConfig(authoritativeResult);
      expect(config.isFallback).toBe(false);
      expect(config.badgeText).toBe('RESOLVED CANONICAL');
      expect(config.badgeClasses).toContain('emerald');
    });

    it('preserves authoritative AMBIGUOUS TERM status for ambiguous server resolution', () => {
      const ambiguousResult: SemanticResolveResponse = {
        query: 'margin',
        is_ambiguous: true,
        clarification_prompt: 'Did you mean gross margin or net profit margin?',
        candidate_kpis: [],
        is_supported: true,
      };

      const config = getResolverBadgeConfig(ambiguousResult);
      expect(config.isFallback).toBe(false);
      expect(config.badgeText).toBe('AMBIGUOUS TERM');
      expect(config.badgeClasses).toContain('amber');
    });

    it('preserves non-available availability status from backend without inventing availability', () => {
      const unavailResult: SemanticResolveResponse = {
        query: 'customer acquisition cost',
        canonical_name: 'cac',
        is_ambiguous: false,
        candidate_kpis: [],
        is_supported: false,
        availability_status: 'REQUIRES_MARKETING_SPEND_DATA',
      };

      const config = getResolverBadgeConfig(unavailResult);
      expect(config.isFallback).toBe(false);
      expect(config.badgeText).toBe('REQUIRES_MARKETING_SPEND_DATA');
    });
  });
});
