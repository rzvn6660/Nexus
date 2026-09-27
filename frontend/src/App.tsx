import React, { useState, useEffect, useCallback } from 'react';
import { AppShell } from './components/layout/AppShell';
import { OverviewPage } from './pages/OverviewPage';
import { AnalyticsPage } from './pages/AnalyticsPage';
import { InvestigationsPage } from './pages/InvestigationsPage';
import { ForecastsPage } from './pages/ForecastsPage';
import { AskNexusPage } from './pages/AskNexusPage';
import { DataPage } from './pages/DataPage';
import { KnowledgePage } from './pages/KnowledgePage';
import { HistoryPage } from './pages/HistoryPage';
import { LoginPage } from './pages/LoginPage';
import { SignupPage } from './pages/SignupPage';
import { LandingPage } from './pages/LandingPage';
import { OnboardingPage } from './pages/OnboardingPage';
import { BusinessSettingsPage } from './pages/BusinessSettingsPage';
import { getHealthStatus } from './services/api';
import { AuthService, UserProfileResponse } from './services/auth';
import { HealthResponse } from './types/api';

export const App: React.FC = () => {
  const [currentRoute, setCurrentRoute] = useState<string>(() => {
    const path = window.location.pathname;
    return path || '/';
  });

  const [activeAskQuery, setActiveAskQuery] = useState<string>('');
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(() => AuthService.isAuthenticated());
  const [userProfile, setUserProfile] = useState<UserProfileResponse | null>(null);

  // Synchronize browser popstate (back/forward)
  useEffect(() => {
    const handlePopState = () => {
      setCurrentRoute(window.location.pathname || '/');
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const handleNavigate = useCallback((route: string) => {
    setCurrentRoute(route);
    if (window.location.pathname !== route) {
      window.history.pushState({}, '', route);
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, []);

  const handleTriggerAsk = useCallback(
    (query: string) => {
      setActiveAskQuery(query);
      handleNavigate('/ask');
    },
    [handleNavigate]
  );

  // Load user profile when authenticated
  const loadProfile = useCallback(async () => {
    if (!AuthService.isAuthenticated()) {
      setUserProfile(null);
      return;
    }
    try {
      const p = await AuthService.getMe();
      setUserProfile(p);
    } catch (err) {
      console.warn('Profile load notice:', err);
    }
  }, []);

  useEffect(() => {
    if (isAuthenticated) {
      loadProfile();
    }
  }, [isAuthenticated, loadProfile]);

  // Initial health check
  useEffect(() => {
    getHealthStatus()
      .then((data) => setHealth(data))
      .catch((err) => {
        console.warn('Initial health check notice:', err);
      });
  }, []);

  const handleAuthSuccess = () => {
    setIsAuthenticated(true);
    loadProfile();
  };

  const handleLogout = () => {
    AuthService.logout();
    setIsAuthenticated(false);
    setUserProfile(null);
    handleNavigate('/login');
  };

  // Auth Perimeter: Unauthenticated users are gated from workspace routes
  if (!isAuthenticated) {
    if (currentRoute === '/signup') {
      return (
        <SignupPage
          onNavigate={handleNavigate}
          onSignupSuccess={handleAuthSuccess}
        />
      );
    }
    if (currentRoute === '/login') {
      return (
        <LoginPage
          onNavigate={handleNavigate}
          onLoginSuccess={handleAuthSuccess}
        />
      );
    }
    return (
      <LandingPage
        onNavigate={handleNavigate}
        isAuthenticated={false}
      />
    );
  }

  // Full-screen landing page viewable anytime by authenticated users
  if (currentRoute === '/landing') {
    return (
      <LandingPage
        onNavigate={handleNavigate}
        isAuthenticated={true}
      />
    );
  }

  // Full-screen focused onboarding flow
  if (currentRoute === '/onboarding') {
    return (
      <OnboardingPage
        onNavigate={handleNavigate}
        onComplete={() => handleNavigate('/')}
      />
    );
  }

  // Active Business & Role resolution
  const currentOrg = userProfile?.tenants?.[0];
  const activeBiz = currentOrg?.businesses?.find(
    (b) => b.id === AuthService.getActiveBusinessId()
  ) || currentOrg?.businesses?.[0];
  const activeBusinessName = activeBiz?.name || 'Workspace';
  const userRole = currentOrg?.role || 'owner';

  const renderActivePage = () => {
    switch (currentRoute) {
      case '/':
        return (
          <OverviewPage
            onNavigate={handleNavigate}
            onAskQuery={handleTriggerAsk}
          />
        );
      case '/analytics':
        return (
          <AnalyticsPage
            onNavigate={handleNavigate}
            onAskQuery={handleTriggerAsk}
          />
        );
      case '/investigations':
        return (
          <InvestigationsPage
            onNavigate={handleNavigate}
            onAskQuery={handleTriggerAsk}
          />
        );
      case '/forecasts':
        return (
          <ForecastsPage
            onNavigate={handleNavigate}
            onAskQuery={handleTriggerAsk}
          />
        );
      case '/ask':
        return (
          <AskNexusPage
            onNavigate={handleNavigate}
            initialQuery={activeAskQuery}
          />
        );
      case '/data':
        return <DataPage />;
      case '/knowledge':
        return <KnowledgePage />;
      case '/history':
        return <HistoryPage />;
      case '/business':
        return <BusinessSettingsPage onNavigate={handleNavigate} />;
      default:
        return (
          <OverviewPage
            onNavigate={handleNavigate}
            onAskQuery={handleTriggerAsk}
          />
        );
    }
  };

  return (
    <AppShell
      currentRoute={currentRoute}
      onNavigate={handleNavigate}
      health={health}
      onAskQuery={handleTriggerAsk}
      activeBusinessName={activeBusinessName}
      userRole={userRole}
      onLogout={handleLogout}
    >
      {renderActivePage()}
    </AppShell>
  );
};

export default App;
