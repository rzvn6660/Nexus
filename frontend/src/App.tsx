import React, { useState, useEffect, useCallback } from 'react';
import { AppShell } from './components/layout/AppShell';
import { OverviewPage } from './pages/OverviewPage';
import { AnalyticsPage } from './pages/AnalyticsPage';
import { InvestigationsPage } from './pages/InvestigationsPage';
import { ForecastsPage } from './pages/ForecastsPage';
import { AskNexusPage } from './pages/AskNexusPage';
import { DataPage } from './pages/DataPage';
import { KnowledgePage } from './pages/KnowledgePage';
import { getHealthStatus } from './services/api';
import { HealthResponse } from './types/api';

export const App: React.FC = () => {
  const [currentRoute, setCurrentRoute] = useState<string>(() => {
    const path = window.location.pathname;
    return path || '/';
  });

  const [activeAskQuery, setActiveAskQuery] = useState<string>('');
  const [health, setHealth] = useState<HealthResponse | null>(null);

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

  const handleTriggerAsk = useCallback((query: string) => {
    setActiveAskQuery(query);
    handleNavigate('/ask');
  }, [handleNavigate]);

  // Initial health check
  useEffect(() => {
    getHealthStatus()
      .then((data) => setHealth(data))
      .catch((err) => {
        console.warn('Initial health check notice:', err);
      });
  }, []);

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
    >
      {renderActivePage()}
    </AppShell>
  );
};

export default App;
