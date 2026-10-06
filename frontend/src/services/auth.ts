/**
 * SaaS Authentication & Tenant Workspace Management Service (Phase 15B, 15C, 15H).
 *
 * Manages JWT tokens, authenticated identity, organization membership,
 * active business workspace, and persistent session state.
 */

import { apiRequest } from './api';

export interface UserIdentity {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_verified: boolean;
  created_at?: string;
}

export interface BusinessWorkspace {
  id: string;
  name: string;
  industry?: string;
  country?: string;
  currency?: string;
  timezone?: string;
  business_type?: string;
  fiscal_year_start?: number;
  status: string;
  onboarding_step: string;
  data_readiness_status: string;
}

export interface OrganizationTenant {
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  role: 'owner' | 'admin' | 'member';
  businesses: BusinessWorkspace[];
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: UserIdentity;
  organization?: {
    id: string;
    name: string;
    slug: string;
  };
  business?: BusinessWorkspace;
}

export interface UserProfileResponse {
  user: UserIdentity;
  tenants: OrganizationTenant[];
}

const TOKEN_KEY = 'nexus_access_token';
const ACTIVE_BIZ_KEY = 'nexus_business_id';
const ACTIVE_ORG_KEY = 'nexus_org_id';
const USER_CACHE_KEY = 'nexus_user_profile';

export const AuthService = {
  getToken(): string | null {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem(TOKEN_KEY);
  },

  setToken(token: string): void {
    if (typeof window !== 'undefined') {
      localStorage.setItem(TOKEN_KEY, token);
    }
  },

  removeToken(): void {
    if (typeof window !== 'undefined') {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(ACTIVE_BIZ_KEY);
      localStorage.removeItem(ACTIVE_ORG_KEY);
      localStorage.removeItem(USER_CACHE_KEY);
    }
  },

  isAuthenticated(): boolean {
    return !!this.getToken();
  },

  getActiveBusinessId(): string | null {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem(ACTIVE_BIZ_KEY);
  },

  setActiveBusinessId(businessId: string): void {
    if (typeof window !== 'undefined') {
      localStorage.setItem(ACTIVE_BIZ_KEY, businessId);
    }
  },

  getActiveOrgId(): string | null {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem(ACTIVE_ORG_KEY);
  },

  setActiveOrgId(orgId: string): void {
    if (typeof window !== 'undefined') {
      localStorage.setItem(ACTIVE_ORG_KEY, orgId);
    }
  },

  async signup(data: {
    email: string;
    password: string;
    full_name?: string;
    organization_name?: string;
    business_name?: string;
  }): Promise<TokenResponse> {
    const res = await apiRequest<TokenResponse>('/api/v1/auth/signup', {
      method: 'POST',
      body: JSON.stringify(data),
      headers: { 'Content-Type': 'application/json' },
    });

    if (res.access_token) {
      this.setToken(res.access_token);
      if (res.business?.id) {
        this.setActiveBusinessId(res.business.id);
      }
      if (res.organization?.id) {
        this.setActiveOrgId(res.organization.id);
      }
      if (res.user) {
        localStorage.setItem(USER_CACHE_KEY, JSON.stringify(res.user));
      }
    }
    return res;
  },

  async login(data: { email: string; password: string }): Promise<TokenResponse> {
    const res = await apiRequest<TokenResponse>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
      headers: { 'Content-Type': 'application/json' },
    });

    if (res.access_token) {
      this.setToken(res.access_token);
      if (res.business?.id) {
        this.setActiveBusinessId(res.business.id);
      }
      if (res.organization?.id) {
        this.setActiveOrgId(res.organization.id);
      }
      if (res.user) {
        localStorage.setItem(USER_CACHE_KEY, JSON.stringify(res.user));
      }
    }
    return res;
  },

  async getMe(): Promise<UserProfileResponse> {
    const profile = await apiRequest<UserProfileResponse>('/api/v1/auth/me');
    if (profile.tenants && profile.tenants.length > 0) {
      const activeBiz = this.getActiveBusinessId();
      const allBiz = profile.tenants.flatMap((t) => t.businesses);
      // If current active business is not found or not set, set to first available
      if (!activeBiz || !allBiz.some((b) => b.id === activeBiz)) {
        if (allBiz.length > 0) {
          this.setActiveBusinessId(allBiz[0].id);
          this.setActiveOrgId(profile.tenants[0].organization_id);
        }
      }
    }
    return profile;
  },

  async tryRefreshToken(): Promise<boolean> {
    try {
      const token = this.getToken();
      if (!token) return false;
      const res = await apiRequest<TokenResponse>('/api/v1/auth/refresh', {
        method: 'POST',
      });
      if (res?.access_token) {
        this.setToken(res.access_token);
        return true;
      }
      return false;
    } catch {
      return false;
    }
  },

  clearSessionAndRedirect(): void {
    this.removeToken();
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new Event('nexus-auth-changed'));
      if (window.location.pathname !== '/login') {
        window.history.pushState({}, '', '/login');
        window.dispatchEvent(new PopStateEvent('popstate'));
      }
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
  },

  async handleSessionExpired(): Promise<void> {
    let refreshed = false;
    try {
      refreshed = await this.tryRefreshToken();
    } catch {
      refreshed = false;
    }

    if (refreshed) {
      return;
    }

    this.clearSessionAndRedirect();
  },

  logout(): void {
    this.removeToken();
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new Event('nexus-auth-changed'));
    }
  },
};

export function isSessionExpiredError(message?: string | null, technicalDetails?: any): boolean {
  if (technicalDetails?.status === 401 || technicalDetails?.status_code === 401) {
    return true;
  }
  if (typeof message === 'string') {
    const lower = message.toLowerCase();
    return (
      lower.includes('token has expired') ||
      lower.includes('token has been revoked') ||
      lower.includes('please log in again') ||
      lower.includes('session has expired') ||
      lower.includes('session expired') ||
      lower.includes('invalid authentication token') ||
      lower.includes('not authenticated') ||
      lower.includes('unauthorized') ||
      lower.includes('jwt expired')
    );
  }
  return false;
}
