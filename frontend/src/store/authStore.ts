import { create } from 'zustand';

export interface AuthUser {
  id: string;
  email: string;
  full_name?: string;
  role: 'user' | 'admin';
  api_token: string;
  credits_total: number;
  credits_used: number;
  is_active: boolean;
}

export type AppView = 'canvas' | 'admin' | 'config';

interface AuthState {
  user: AuthUser | null;
  token: string | null;
  activeView: AppView;

  setAuth: (user: AuthUser, token: string) => void;
  updateUser: (user: AuthUser) => void;
  logout: () => void;
  setView: (v: AppView) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: localStorage.getItem('fm_token'),
  activeView: 'canvas',

  setAuth: (user, token) => {
    localStorage.setItem('fm_token', token);
    set({ user, token });
  },

  updateUser: (user) => set({ user }),

  logout: () => {
    localStorage.removeItem('fm_token');
    set({ user: null, token: null, activeView: 'canvas' });
  },

  setView: (v) => set({ activeView: v }),
}));
