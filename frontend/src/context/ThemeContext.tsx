import React, { createContext, useContext, useEffect, useState, useMemo } from 'react';

export type ThemeChoice = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';
export type DisplayDensity = 'comfortable' | 'compact';

interface ThemeContextType {
  theme: ThemeChoice;
  resolvedTheme: ResolvedTheme;
  setTheme: (theme: ThemeChoice) => void;
  density: DisplayDensity;
  setDensity: (density: DisplayDensity) => void;
  reducedMotion: boolean;
  setReducedMotion: (reduced: boolean) => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

const THEME_STORAGE_KEY = 'nexus_theme_preference';
const DENSITY_STORAGE_KEY = 'nexus_display_density';
const MOTION_STORAGE_KEY = 'nexus_reduced_motion';

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [theme, setThemeState] = useState<ThemeChoice>(() => {
    try {
      const saved = localStorage.getItem(THEME_STORAGE_KEY);
      if (saved === 'light' || saved === 'dark' || saved === 'system') {
        return saved;
      }
    } catch {
      // Fallback on storage errors
    }
    return 'system';
  });

  const [density, setDensityState] = useState<DisplayDensity>(() => {
    try {
      const saved = localStorage.getItem(DENSITY_STORAGE_KEY);
      if (saved === 'comfortable' || saved === 'compact') {
        return saved;
      }
    } catch {
      // Fallback
    }
    return 'comfortable';
  });

  const [reducedMotion, setReducedMotionState] = useState<boolean>(() => {
    try {
      const saved = localStorage.getItem(MOTION_STORAGE_KEY);
      if (saved !== null) {
        return saved === 'true';
      }
    } catch {
      // Fallback
    }
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  });

  // Calculate resolved theme based on choice and system media query
  const [systemPrefersDark, setSystemPrefersDark] = useState<boolean>(() => {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  });

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e: MediaQueryListEvent) => {
      setSystemPrefersDark(e.matches);
    };
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);

  const resolvedTheme: ResolvedTheme = useMemo(() => {
    if (theme === 'light') return 'light';
    if (theme === 'dark') return 'dark';
    return systemPrefersDark ? 'dark' : 'light';
  }, [theme, systemPrefersDark]);

  // Synchronize class list and color-scheme on root element
  useEffect(() => {
    const root = document.documentElement;
    if (resolvedTheme === 'dark') {
      root.classList.add('dark');
      root.classList.remove('light');
      root.style.colorScheme = 'dark';
    } else {
      root.classList.remove('dark');
      root.classList.add('light');
      root.style.colorScheme = 'light';
    }
  }, [resolvedTheme]);

  // Synchronize density class on root element
  useEffect(() => {
    const root = document.documentElement;
    if (density === 'compact') {
      root.classList.add('density-compact');
    } else {
      root.classList.remove('density-compact');
    }
  }, [density]);

  // Synchronize reduced motion
  useEffect(() => {
    const root = document.documentElement;
    if (reducedMotion) {
      root.classList.add('reduced-motion');
    } else {
      root.classList.remove('reduced-motion');
    }
  }, [reducedMotion]);

  const setTheme = (newTheme: ThemeChoice) => {
    setThemeState(newTheme);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, newTheme);
    } catch {
      // Storage unavailable
    }
  };

  const setDensity = (newDensity: DisplayDensity) => {
    setDensityState(newDensity);
    try {
      localStorage.setItem(DENSITY_STORAGE_KEY, newDensity);
    } catch {
      // Storage unavailable
    }
  };

  const setReducedMotion = (reduced: boolean) => {
    setReducedMotionState(reduced);
    try {
      localStorage.setItem(MOTION_STORAGE_KEY, String(reduced));
    } catch {
      // Storage unavailable
    }
  };

  return (
    <ThemeContext.Provider
      value={{
        theme,
        resolvedTheme,
        setTheme,
        density,
        setDensity,
        reducedMotion,
        setReducedMotion,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = (): ThemeContextType => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};
