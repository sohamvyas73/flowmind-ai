export type NodeType =
  | 'inputNode' | 'aiNode' | 'verificationNode' | 'decisionNode' | 'outputNode'
  | 'httpNode' | 'transformNode' | 'humanReviewNode'
  | 'ruleNode' | 'codeNode' | 'validatorNode' | 'switchNode' | 'formatterNode' | 'aggregatorNode'
  | 'indianKycNode';

export interface InputField {
  id: string;
  name: string;   // becomes the JSON key in the API body
  type: 'text' | 'file' | 'number' | 'json';
}

export interface Position {
  x: number;
  y: number;
}

export interface NodeData {
  label: string;
  description?: string;
  [key: string]: any;
}

export interface WorkflowNode {
  id: string;
  type: NodeType;
  position: Position;
  data: NodeData;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
}

export interface GraphData {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

export interface Workflow {
  id: string;
  name: string;
  description?: string;
  graph_data: GraphData;
  status: 'draft' | 'active' | 'paused' | 'archived';
  created_at: string;
  updated_at: string;
  version: string;
}

export interface WorkflowExecution {
  id: string;
  workflow_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  input_data?: any;
  output_data?: any;
  execution_trace?: any[];
  error_message?: string;
  started_at: string;
  completed_at?: string;
}
