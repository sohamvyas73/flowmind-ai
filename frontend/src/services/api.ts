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

  updateUser: async (userId: string, data: Partial<{ credits_total: number; is_active: boolean; role: string }>) => {
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

  getConnectors: async () => {
    const res = await api.get('/admin/connectors');
    return res.data as ConnectorUsage[];
  },

  getWorkflows: async () => {
    const res = await api.get('/admin/workflows');
    return res.data as AdminWorkflow[];
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
