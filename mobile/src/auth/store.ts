/**
 * Auth store — zustand with SecureStore-backed hydration.
 *
 * Drives the route guard in `app/_layout.tsx`: when `status === 'authed'`
 * we render the role-appropriate tab tree, otherwise we send the user
 * to the onboarding stack.
 */

import { create } from 'zustand';

import { setOnLogout } from '../api/client';
import { clearRole, clearTokens, loadRole, loadTokens, saveRole, saveTokens } from '../api/tokens';
import type { components } from '../../types/api';

export type Role = 'driver' | 'business' | 'admin';
export type User = components['schemas']['UserOut'];

type State = {
  status: 'hydrating' | 'authed' | 'guest';
  user: User | null;
  role: Role | null;
  setSession: (tokens: { access_token: string; refresh_token: string }, user: User) => Promise<void>;
  setRole: (role: Role) => Promise<void>;
  hydrate: () => Promise<void>;
  logout: () => Promise<void>;
};

export const useAuth = create<State>((set) => ({
  status: 'hydrating',
  user: null,
  role: null,

  setSession: async (tokens, user) => {
    await saveTokens({ access: tokens.access_token, refresh: tokens.refresh_token });
    if (user.role) await saveRole(user.role);
    set({ status: 'authed', user, role: (user.role as Role) ?? null });
  },

  setRole: async (role) => {
    await saveRole(role);
    set({ role });
  },

  hydrate: async () => {
    const [tokens, role] = await Promise.all([loadTokens(), loadRole()]);
    if (!tokens) {
      set({ status: 'guest', user: null, role: role as Role | null });
      return;
    }
    // Validate the session via `/v1/me`. The axios client transparently
    // refreshes on 401, so a single GET is enough to confirm the access
    // token is alive (or get a fresh one on the way past).
    try {
      const { fetchMe } = await import('../api/me');
      const user = await fetchMe();
      if (user.role) await saveRole(user.role);
      set({ status: 'authed', user, role: (user.role as Role) ?? (role as Role) ?? null });
    } catch {
      // 401 / refresh failure / network — fall back to guest.
      await clearTokens();
      set({ status: 'guest', user: null, role: role as Role | null });
    }
  },

  logout: async () => {
    const tokens = await loadTokens();
    if (tokens) {
      try {
        const { logoutSession } = await import('./api');
        await logoutSession(tokens.refresh).catch(() => undefined);
      } catch {
        // best effort
      }
    }
    await clearTokens();
    await clearRole();
    set({ status: 'guest', user: null, role: null });
  },
}));

// Wire client → store: client triggers a logout on refresh failure.
setOnLogout(() => {
  void useAuth.getState().logout();
});
