import axios from 'axios';
import { Workflow, WorkflowExecution } from '@/types/workflow';
import { AuthUser } from '@/store/authStore';

export const healthCheck = async (): Promise<boolean> => {
  try {
    await axios.get('/health');
    return true;
  } catch {
    return false;
  }
};

const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
});

// Attach Bearer token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('fm_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// On 401, clear auth and reload to login screen
api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('fm_token');
      window.location.reload();
    }
    return Promise.reject(error);
  },
);

// ── Auth ──────────────────────────────────────────────────────────────────────

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export const authApi = {
  signup: async (email: string, password: string, full_name?: string): Promise<TokenResponse> => {
    const res = await api.post('/auth/signup', { email, password, full_name });
    return res.data;
  },

  login: async (email: string, password: string): Promise<TokenResponse> => {
    const res = await api.post('/auth/login', { email, password });
    return res.data;
  },

  getMe: async (): Promise<AuthUser> => {
    const res = await api.get('/auth/me');
    return res.data;
  },

  refreshApiToken: async (): Promise<AuthUser> => {
    const res = await api.post('/auth/refresh-api-token');
    return res.data;
  },
};

// ── Workflows ─────────────────────────────────────────────────────────────────

export const workflowApi = {
  createWorkflow: async (data: {
    name: string;
    description?: string;
    graph_data: { nodes: any[]; edges: any[] };
  }): Promise<Workflow> => {
    const res = await api.post('/workflows/workflows', data);
    return res.data;
  },

  getWorkflows: async (): Promise<Workflow[]> => {
    const res = await api.get('/workflows/workflows');
    return res.data;
  },

  getWorkflow: async (id: string): Promise<Workflow> => {
    const res = await api.get(`/workflows/workflows/${id}`);
    return res.data;
  },

  updateWorkflow: async (
    id: string,
    data: Partial<{ name: string; description?: string; graph_data: { nodes: any[]; edges: any[] }; status: string }>,
  ): Promise<Workflow> => {
    const res = await api.put(`/workflows/workflows/${id}`, data);
    return res.data;
  },

  deleteWorkflow: async (id: string): Promise<void> => {
    await api.delete(`/workflows/workflows/${id}`);
  },

  executeWorkflow: async (workflowId: string, inputData?: any): Promise<WorkflowExecution> => {
    const res = await api.post(`/workflows/workflows/${workflowId}/execute`, {
      workflow_id: workflowId,
      input_data: inputData,
    });
    return res.data;
  },

  triggerWorkflow: async (workflowId: string, body: Record<string, unknown> = {}) => {
    const res = await api.post(`/workflows/workflows/${workflowId}/trigger`, body);
    return res.data as { workflow_id: string; execution_id: string; status: string; output: unknown };
  },

  getExecution: async (executionId: string): Promise<WorkflowExecution> => {
    const res = await api.get(`/workflows/executions/${executionId}`);
    return res.data;
  },

  getWorkflowExecutions: async (workflowId: string): Promise<WorkflowExecution[]> => {
    const res = await api.get(`/workflows/workflows/${workflowId}/executions`);
    return res.data;
  },
};

// ── User Config ───────────────────────────────────────────────────────────────

export interface ProviderConfig {
  api_key_set: boolean;
  api_key_masked: string | null;
  model: string | null;
  effective_key_masked: string | null;
  effective_model: string;
  source: 'user' | 'platform' | 'env';
}

export interface UserConfig {
  openai: ProviderConfig;
  anthropic: ProviderConfig;
  gemini: ProviderConfig;
}

export interface ConfigUpdatePayload {
  openai_api_key?: string;
  openai_model?: string;
  anthropic_api_key?: string;
  anthropic_model?: string;
  gemini_api_key?: string;
  gemini_model?: string;
  clear_openai_api_key?: boolean;
  clear_anthropic_api_key?: boolean;
  clear_gemini_api_key?: boolean;
}

export interface PlatformProviderConfig {
  api_key_set: boolean;
  api_key_masked: string | null;
  model: string;
}

export interface PlatformSettings {
  openai: PlatformProviderConfig;
  anthropic: PlatformProviderConfig;
  gemini: PlatformProviderConfig;
}

export const configApi = {
  getMyConfig: async (): Promise<UserConfig> => {
    const res = await api.get('/config/me');
    return res.data;
  },

  updateMyConfig: async (data: ConfigUpdatePayload): Promise<UserConfig> => {
    const res = await api.put('/config/me', data);
    return res.data;
  },
};

// ── Admin ─────────────────────────────────────────────────────────────────────

export const adminApi = {
  getStats: async () => {
    const res = await api.get('/admin/stats');
    return res.data;
  },

  getUsers: async () => {
    const res = await api.get('/admin/users');
    return res.data as AdminUser[];
  },

  updateUser: async (userId: string, data: Partial<{
    credits_total: number; add_credits: number; subtract_credits: number;
    reset_credits_used: boolean; is_active: boolean; role: string;
  }>) => {
    const res = await api.patch(`/admin/users/${userId}`, data);
    return res.data;
  },

  resetApiToken: async (userId: string) => {
    const res = await api.post(`/admin/users/${userId}/reset-api-token`);
    return res.data as { api_token: string };
  },

  getCreditUsage: async () => {
    const res = await api.get('/admin/credit-usage');
    return res.data as CreditBreakdown[];
  },

  getRawCreditUsage: async (userId?: string) => {
    const params = userId ? { user_id: userId } : {};
    const res = await api.get('/admin/credit-usage/raw', { params });
    return res.data as RawCreditRow[];
  },

  getConnectors: async () => {
    const res = await api.get('/admin/connectors');
    return res.data as ConnectorUsage[];
  },

  getWorkflows: async () => {
    const res = await api.get('/admin/workflows');
    return res.data as AdminWorkflow[];
  },

  getPlatformSettings: async (): Promise<PlatformSettings> => {
    const res = await api.get('/admin/platform-settings');
    return res.data;
  },

  updatePlatformSettings: async (data: Partial<{
    openai_api_key: string; openai_model: string;
    anthropic_api_key: string; anthropic_model: string;
    gemini_api_key: string; gemini_model: string;
    clear_openai_api_key: boolean; clear_anthropic_api_key: boolean; clear_gemini_api_key: boolean;
  }>): Promise<PlatformSettings> => {
    const res = await api.put('/admin/platform-settings', data);
    return res.data;
  },
};

// ── Admin types ───────────────────────────────────────────────────────────────

export interface AdminUser {
  id: string;
  email: string;
  full_name?: string;
  role: string;
  api_token: string;
  credits_total: number;
  credits_used: number;
  credits_remaining: number;
  is_active: boolean;
  workflow_count: number;
  execution_count: number;
  created_at: string;
}

export interface CreditBreakdown {
  user_id: string;
  email: string;
  breakdown: { node_type: string; credits: number; calls: number }[];
  total_credits: number;
}

export interface RawCreditRow {
  id: string;
  user_id: string;
  email: string;
  workflow_id: string | null;
  execution_id: string | null;
  node_type: string;
  credits: number;
  description: string;
  created_at: string | null;
}

export interface ConnectorUsage {
  user_id: string;
  email: string;
  connector: string;
  description: string;
  call_count: number;
  credits_used: number;
}

export interface AdminWorkflow {
  id: string;
  name: string;
  status: string;
  owner_email: string;
  owner_id?: string;
  execution_count: number;
  node_count: number;
  created_at: string;
  updated_at: string;
}
