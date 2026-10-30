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
  /** Plaintext API token, present only on signup / rotation. */
  api_token?: string | null;
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

  refreshApiToken: async (): Promise<TokenResponse> => {
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

  previewWorkflow: async (workflowId: string): Promise<PreviewResult> => {
    const res = await api.post(`/workflows/workflows/${workflowId}/preview`, {});
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

export interface ServerFeatures {
  code_node_enabled: boolean;
}

export const configApi = {
  getFeatures: async (): Promise<ServerFeatures> => {
    const res = await api.get('/config/features');
    return res.data;
  },

  getMyConfig: async (): Promise<UserConfig> => {
    const res = await api.get('/config/me');
    return res.data;
  },

  updateMyConfig: async (data: ConfigUpdatePayload): Promise<UserConfig> => {
    const res = await api.put('/config/me', data);
    return res.data;
  },
};

// ── Connections (Phase 1: data plane) ─────────────────────────────────────────

export interface FieldSpec {
  name: string;
  label: string;
  type: 'text' | 'password' | 'number' | 'select';
  required: boolean;
  secret: boolean;
  default?: string | number | null;
  options?: string[] | null;
  help?: string | null;
}

export interface ConnectorSpec {
  type: string;
  label: string;
  description: string;
  fields: FieldSpec[];
  supports_discover: boolean;
  supports_preview: boolean;
}

export interface Connection {
  id: string;
  name: string;
  type: string;
  config: Record<string, string | number>;
  access_mode: 'read_only' | 'read_write';
  host_allowlist: string[];
  last_tested_at?: string | null;
  last_test_ok?: boolean | null;
  last_test_message?: string | null;
  owner_email?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConnectionTestResult {
  ok: boolean;
  message: string;
  latency_ms?: number | null;
  details: Record<string, unknown>;
}

export interface DatasetColumn { name: string; type: string; nullable: boolean; tags: string[] }

export interface DatasetRef {
  id: string;
  kind: string;
  lineage?: { source: string; operation: string }[];
  columns: DatasetColumn[];
  row_count?: number | null;
  location?: { target?: string } | null;
  row_count_is_estimate: boolean;
  size_bytes?: number | null;
  sample: Record<string, unknown>[];
}

export interface DiscoveredTable { schema: string; name: string; type: 'table' | 'view' }

export const connectionsApi = {
  types: async (): Promise<ConnectorSpec[]> => (await api.get('/connections/types')).data,
  list: async (all = false): Promise<Connection[]> => (await api.get('/connections', { params: all ? { all: true } : {} })).data,
  create: async (body: {
    name: string; type: string; config: Record<string, unknown>; access_mode: string; host_allowlist?: string[];
  }): Promise<Connection> => (await api.post('/connections', body)).data,
  update: async (id: string, body: Partial<{
    name: string; config: Record<string, unknown>; access_mode: string; host_allowlist: string[];
  }>): Promise<Connection> => (await api.patch(`/connections/${id}`, body)).data,
  remove: async (id: string): Promise<void> => { await api.delete(`/connections/${id}`); },
  test: async (id: string): Promise<ConnectionTestResult> => (await api.post(`/connections/${id}/test`)).data,
  discover: async (id: string): Promise<{ tables: DiscoveredTable[]; truncated: boolean }> =>
    (await api.get(`/connections/${id}/discover`)).data,
  preview: async (id: string, schema: string, table: string): Promise<DatasetRef> =>
    (await api.get(`/connections/${id}/preview`, { params: { schema, table } })).data,
};

// ── Data: files, datasets, preview (Phase 2) ──────────────────────────────────

export interface DataFile {
  id: string;
  name: string;
  format: string;
  size_bytes: number;
  row_count?: number | null;
  columns?: { name: string; type: string }[] | null;
  created_at: string;
}

export interface DatasetInfo {
  id: string;
  name?: string | null;
  size_bytes: number;
  row_count?: number | null;
  columns?: { name: string; type: string }[] | null;
  sql?: string | null;
  execution_id?: string | null;
  created_at: string;
  expires_at?: string | null;
}

export interface DataUsage {
  used_bytes: number;
  limit_bytes: number;
  files: number;
  datasets: number;
  max_upload_bytes: number;
}

// ── Quality, profiling, lineage (Phase 3) ──────────────────────────────────────

export interface QualityRule {
  id?: string;
  type: 'not_null' | 'unique' | 'range' | 'allowed_values' | 'regex' | 'max_null_pct' | 'min_rows' | 'max_rows' | 'schema' | 'expression';
  severity?: 'error' | 'warn';
  column?: string;
  columns?: string[];
  min?: string | number;
  max?: string | number;
  values?: string[] | string;
  pattern?: string;
  value?: string | number;
  expression?: string;
  label?: string;
  expected?: { name: string; type?: string }[];
  allowExtra?: boolean;
  reason?: string;
}

export interface QualityRuleResult {
  id: string;
  type: string;
  description: string;
  severity: 'error' | 'warn';
  status: 'pass' | 'fail';
  failed: number;
  unit: string;
  message: string;
  examples: Record<string, unknown>[];
  columns: string[];
}

export interface QualityReport {
  passed: boolean;
  total_rows: number;
  checks: number;
  failed_errors: number;
  failed_warnings: number;
  rules: QualityRuleResult[];
  sql: string;
}

export interface ColumnProfile {
  name: string;
  type: string;
  nulls: number;
  null_pct: number;
  distinct: number;
  min?: string | null;
  max?: string | null;
  mean?: number | null;
  pii: boolean;
}

export interface DataProfile {
  total_rows: number;
  columns: ColumnProfile[];
  suggested_rules: QualityRule[];
}

export interface LineageStep {
  node_id: string;
  label: string;
  node_type: string;
  reads: { source: string; operation: string }[];
  dataset_id?: string | null;
  row_count?: number | null;
  columns: number;
  error?: string | null;
  quality?: { passed: boolean; checks: number; failed_errors: number; failed_warnings: number } | null;
}

export interface RunLineage {
  execution_id: string;
  workflow?: string | null;
  status: string;
  steps: LineageStep[];
  events: number;
}

export interface PreviewNode {
  node_id: string;
  node_type: string;
  label?: string | null;
  status: 'ok' | 'error' | 'skipped';
  error?: string;
  note?: string;
  sql?: string;
  dataset?: DatasetRef;
  quality?: QualityReport;
}

export interface PreviewResult {
  status: string;
  sample_rows: number;
  nodes: PreviewNode[];
  error?: string;
  failed_node_id?: string;
}

const saveBlob = (blob: Blob, filename: string) => {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
};

export const dataApi = {
  usage: async (): Promise<DataUsage> => (await api.get('/data/usage')).data,
  listFiles: async (): Promise<DataFile[]> => (await api.get('/data/files')).data,
  uploadFile: async (file: File): Promise<DataFile> => {
    const form = new FormData();
    form.append('file', file);
    return (await api.post('/data/files', form, { headers: { 'Content-Type': 'multipart/form-data' } })).data;
  },
  deleteFile: async (id: string): Promise<void> => { await api.delete(`/data/files/${id}`); },
  previewFile: async (id: string): Promise<DatasetRef> => (await api.get(`/data/files/${id}/preview`)).data,
  installExamples: async (): Promise<DataFile[]> => (await api.post('/data/examples')).data,
  listDatasets: async (): Promise<DatasetInfo[]> => (await api.get('/data/datasets')).data,
  profileFile: async (id: string): Promise<DataProfile> => (await api.get(`/data/files/${id}/profile`)).data,
  profileDataset: async (id: string): Promise<DataProfile> => (await api.get(`/data/datasets/${id}/profile`)).data,
  previewDataset: async (id: string): Promise<DatasetRef> => (await api.get(`/data/datasets/${id}/preview`)).data,
  deleteDataset: async (id: string): Promise<void> => { await api.delete(`/data/datasets/${id}`); },
  download: async (id: string, name: string, format: 'csv' | 'parquet'): Promise<void> => {
    const res = await api.get(`/data/datasets/${id}/download`, { params: { format }, responseType: 'blob' });
    saveBlob(res.data, `${name.replace(/[^\w.-]+/g, '_') || 'dataset'}.${format}`);
  },
};

// ── Retrieval / RAG (Phase 4) ──────────────────────────────────────────────────

export interface EmbedderInfo {
  provider: string; label: string; description: string; needs_key: boolean; local: boolean; semantic: boolean;
  verified_here: boolean; models: { model: string; dim: number; note: string }[];
}
export interface StoreInfo {
  type: string; label: string; summary: string; best_for: string; needs_connection: boolean; needs_docker: boolean;
  docker: string | null; setup?: string[]; default_url?: string; profile?: string;
}
export interface RagCatalog { stores: StoreInfo[]; embedders: EmbedderInfo[]; compose: string; script: string }
export interface RagSettings {
  configured: boolean; ready: boolean; embed_provider?: string | null; embed_model?: string | null; embed_dim?: number | null;
  has_embed_key: boolean; store_type?: string | null; connection_id?: string | null; embed_ok: boolean; store_ok: boolean;
  embed_message?: string | null; store_message?: string | null; tested_at?: string | null;
}
export interface RagSettingsInput {
  embed_provider: string; embed_model: string; embed_dim: number; embed_api_key?: string | null;
  store_type: string; connection_id?: string | null;
}
export interface RagFile { id: string; name: string; format: string; size_bytes: number; created_at: string }
export interface RagCollection {
  id: string; name: string; store_type: string; embedding: string; documents: number; chunks: number; sources: string[]; updated_at: string;
}
export interface RagPassage { text: string; score: number; source: string; chunk?: number | null }
export interface IndexStats {
  collection: string; created: boolean; added: number; updated: number; unchanged: number; removed: number;
  chunks: number; total_chunks: number;
}

export const ragApi = {
  catalog: async (): Promise<RagCatalog> => (await api.get('/rag/catalog')).data,
  settings: async (): Promise<RagSettings> => (await api.get('/rag/settings')).data,
  save: async (body: RagSettingsInput): Promise<RagSettings> => (await api.put('/rag/settings', body)).data,
  test: async (): Promise<RagSettings> => (await api.post('/rag/settings/test')).data,
  reset: async (): Promise<void> => { await api.delete('/rag/settings'); },
  files: async (): Promise<RagFile[]> => (await api.get('/rag/files')).data,
  upload: async (file: File): Promise<RagFile> => {
    const form = new FormData();
    form.append('file', file);
    return (await api.post('/rag/files', form, { headers: { 'Content-Type': 'multipart/form-data' } })).data;
  },
  removeFile: async (id: string): Promise<void> => { await api.delete(`/rag/files/${id}`); },
  samples: async (): Promise<RagFile[]> => (await api.post('/rag/samples')).data,
  collections: async (): Promise<RagCollection[]> => (await api.get('/rag/collections')).data,
  removeCollection: async (name: string): Promise<void> => { await api.delete(`/rag/collections/${encodeURIComponent(name)}`); },
  index: async (body: { collection: string; file_names: string[]; chunk_size: number; overlap: number }): Promise<IndexStats> =>
    (await api.post('/rag/index', body)).data,
  query: async (body: { collection: string; query: string; top_k: number; min_score: number }): Promise<{ passages: RagPassage[] }> =>
    (await api.post('/rag/query', body)).data,
};

// ── Warehouses (Phase 6) ───────────────────────────────────────────────────────

export const warehouseApi = {
  installExamples: async (connectionId: string, tables?: string[]): Promise<{ schema_name: string; tables: string[] }> =>
    (await api.post(`/warehouse/connections/${connectionId}/examples`, { tables })).data,
};

// ── ML (Phase 5) ───────────────────────────────────────────────────────────────

export interface MlVersion { version: string; status?: string | null; run_id?: string | null; created?: number | null; metrics: Record<string, number>; aliases: string[] }
export interface MlModel { name: string; versions: MlVersion[]; aliases: Record<string, string> }
export interface MlModels { connection: string; can_promote: boolean; models: MlModel[] }
export interface FeedbackBatch { id: string; model_name: string; task_type: string; rows: number; metric: string; value: number; details?: Record<string, unknown> | null; created_at: string }

export const mlApi = {
  models: async (connectionId: string): Promise<MlModels> => (await api.get(`/ml/connections/${connectionId}/models`)).data,
  tryEndpoint: async (connectionId: string, features: string[], record: Record<string, string>): Promise<{ prediction: unknown; probability?: number | null; latency_ms: number; features: Record<string, unknown> }> =>
    (await api.post(`/ml/endpoints/${connectionId}/score`, { features, record })).data,
  feedback: async (model?: string): Promise<FeedbackBatch[]> => (await api.get('/ml/feedback', { params: model ? { model } : {} })).data,
};

// ── Runs & schedules (Phase 1: job queue) ──────────────────────────────────────

export interface JobInfo {
  id: string;
  state: 'queued' | 'running' | 'succeeded' | 'cancelled' | 'dead_lettered';
  attempts: number;
  max_attempts: number;
  run_after?: string | null;
  last_error?: string | null;
  cancel_requested: boolean;
}

export interface RunSummary {
  execution_id: string;
  workflow_id: string;
  workflow_name?: string | null;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  triggered_by?: string | null;
  schedule_id?: string | null;
  started_at: string;
  completed_at?: string | null;
  error_message?: string | null;
  job?: JobInfo | null;
}

export interface RunDetail extends RunSummary {
  input_data?: Record<string, unknown> | null;
  output_data?: Record<string, unknown> | null;
  execution_trace?: { node_id: string; node_type: string; result: unknown; timestamp: string }[] | null;
}

export interface Schedule {
  id: string;
  workflow_id: string;
  workflow_name?: string | null;
  name: string;
  cron: string;
  timezone: string;
  enabled: boolean;
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_status?: string | null;
  last_execution_id?: string | null;
  input_data?: Record<string, unknown> | null;
  created_at: string;
}

export const lineageApi = {
  forRun: async (executionId: string): Promise<RunLineage> => (await api.get(`/lineage/runs/${executionId}`)).data,
  events: async (executionId: string): Promise<unknown[]> => (await api.get(`/lineage/runs/${executionId}/events`)).data,
  exportEvents: async (executionId: string): Promise<void> => {
    const events = await lineageApi.events(executionId);
    saveBlob(new Blob([JSON.stringify(events, null, 2)], { type: 'application/json' }), `openlineage-${executionId.slice(0, 8)}.json`);
  },
};

export const runsApi = {
  start: async (workflowId: string, inputData?: Record<string, unknown>) =>
    (await api.post('/runs', { workflow_id: workflowId, input_data: inputData })).data as
      { execution_id: string; job_id: string; status: string },
  list: async (workflowId?: string): Promise<RunSummary[]> =>
    (await api.get('/runs', { params: workflowId ? { workflow_id: workflowId } : {} })).data,
  get: async (executionId: string): Promise<RunDetail> => (await api.get(`/runs/${executionId}`)).data,
  cancel: async (executionId: string): Promise<RunSummary> => (await api.post(`/runs/${executionId}/cancel`)).data,
};

export const schedulesApi = {
  list: async (workflowId?: string): Promise<Schedule[]> =>
    (await api.get('/schedules', { params: workflowId ? { workflow_id: workflowId } : {} })).data,
  create: async (body: {
    workflow_id: string; name: string; cron: string; timezone: string;
    input_data?: Record<string, unknown>; enabled?: boolean;
  }): Promise<Schedule> => (await api.post('/schedules', body)).data,
  update: async (id: string, body: Partial<{
    name: string; cron: string; timezone: string; input_data: Record<string, unknown>; enabled: boolean;
  }>): Promise<Schedule> => (await api.patch(`/schedules/${id}`, body)).data,
  remove: async (id: string): Promise<void> => { await api.delete(`/schedules/${id}`); },
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

  getJobStats: async (): Promise<JobStats> => (await api.get('/admin/jobs/stats')).data,

  listJobs: async (state = 'dead_lettered'): Promise<AdminJob[]> =>
    (await api.get('/admin/jobs', { params: { state } })).data,

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
  api_token_prefix?: string | null;
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

export interface JobStats {
  counts: Record<'queued' | 'running' | 'succeeded' | 'cancelled' | 'dead_lettered', number>;
  oldest_queued_age_s: number;
}

export interface AdminJob {
  id: string;
  kind: string;
  state: string;
  attempts: number;
  max_attempts: number;
  last_error?: string | null;
  execution_id?: string | null;
  created_at?: string | null;
}
