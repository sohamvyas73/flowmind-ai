import axios from 'axios';
import { Workflow, WorkflowExecution } from '@/types/workflow';

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
  headers: {
    'Content-Type': 'application/json',
  },
});

export const workflowApi = {
  // Workflows
  createWorkflow: async (data: {
    name: string;
    description?: string;
    graph_data: { nodes: any[]; edges: any[] };
  }): Promise<Workflow> => {
    const response = await api.post('/workflows/workflows', data);
    return response.data;
  },

  getWorkflows: async (): Promise<Workflow[]> => {
    const response = await api.get('/workflows/workflows');
    return response.data;
  },

  getWorkflow: async (id: string): Promise<Workflow> => {
    const response = await api.get(`/workflows/workflows/${id}`);
    return response.data;
  },

  updateWorkflow: async (
    id: string,
    data: Partial<{
      name: string;
      description?: string;
      graph_data: { nodes: any[]; edges: any[] };
      status: string;
    }>
  ): Promise<Workflow> => {
    const response = await api.put(`/workflows/workflows/${id}`, data);
    return response.data;
  },

  deleteWorkflow: async (id: string): Promise<void> => {
    await api.delete(`/workflows/workflows/${id}`);
  },

  // Executions
  executeWorkflow: async (
    workflowId: string,
    inputData?: any
  ): Promise<WorkflowExecution> => {
    const response = await api.post(`/workflows/workflows/${workflowId}/execute`, {
      workflow_id: workflowId,
      input_data: inputData,
    });
    return response.data;
  },

  triggerWorkflow: async (workflowId: string, body: Record<string, unknown> = {}) => {
    const response = await api.post(`/workflows/workflows/${workflowId}/trigger`, body);
    return response.data as { workflow_id: string; execution_id: string; status: string; output: unknown };
  },

  getExecution: async (executionId: string): Promise<WorkflowExecution> => {
    const response = await api.get(`/workflows/executions/${executionId}`);
    return response.data;
  },

  getWorkflowExecutions: async (workflowId: string): Promise<WorkflowExecution[]> => {
    const response = await api.get(`/workflows/workflows/${workflowId}/executions`);
    return response.data;
  },
};
