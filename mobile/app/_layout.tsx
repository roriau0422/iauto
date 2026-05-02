/**
 * Root layout — providers + auth-aware redirect logic.
 *
 * Boot order:
 *   1. Mount providers (Theme, QueryClient, GestureHandler, SafeArea).
 *   2. Hydrate the auth store (validates the access token, recovers the role).
 *   3. While `status === 'hydrating'` we render a splash placeholder.
 *   4. Once hydrated:
 *      - status === 'guest'   → push to /onboarding/role
 *      - status === 'authed'  → enter the role-appropriate tab tree
 *
 * Routing here is declarative — we decide which subtree to mount via
 * <Redirect> instead of imperatively pushing routes inside an effect.
 */

import { QueryClientProvider } from '@tanstack/react-query';
import { Redirect, Stack } from 'expo-router';
import { useEffect } from 'react';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { queryClient } from '../src/api/queryClient';
import { useAuth } from '../src/auth/store';
import { ThemeProvider } from '../src/theme/ThemeProvider';

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <QueryClientProvider client={queryClient}>
          <ThemeProvider>
            <RootGate />
          </ThemeProvider>
        </QueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

function RootGate() {
  const status = useAuth((s) => s.status);
  const role = useAuth((s) => s.role);
  const hydrate = useAuth((s) => s.hydrate);

  useEffect(() => {
    void hydrate();
  }, [hydrate]);

  // While we don't know yet, render the splash route.
  if (status === 'hydrating') {
    return <Stack screenOptions={{ headerShown: false, animation: 'none' }} />;
  }

  if (status === 'guest') {
    return (
      <>
        <Redirect href="/onboarding/role" />
        <Stack screenOptions={{ headerShown: false, animation: 'fade' }} />
      </>
    );
  }

  // Authed — pick the tab tree by role. If a role somehow isn't set
  // (older session), default to driver — it's the safest read-only home.
  const target = role === 'business' ? '/(business)' : '/(driver)';
  return (
    <>
      <Redirect href={target} />
      <Stack screenOptions={{ headerShown: false, animation: 'fade' }} />
    </>
  );
}
