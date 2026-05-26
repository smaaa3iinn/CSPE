'use client';

import { QueryProvider } from './QueryProvider';
import { ThemeProvider } from './ThemeProvider';
import type { ReactNode } from 'react';

interface ProvidersProps {
  children: ReactNode;
}

/** Provider racine combinant tous les providers de l'application */
export function Providers({ children }: ProvidersProps) {
  return (
    <ThemeProvider attribute="data-theme" defaultTheme="dark" enableSystem={false}>
      <QueryProvider>{children}</QueryProvider>
    </ThemeProvider>
  );
}
