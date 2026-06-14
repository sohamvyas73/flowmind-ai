import { create } from 'zustand';
import { Node, Edge, Connection, addEdge, applyNodeChanges, applyEdgeChanges, NodeChange, EdgeChange } from 'reactflow';

interface WorkflowState {
  nodes: Node[];
  edges: Edge[];
  selectedNode: Node | null;
  workflowName: string;
  workflowDescription: string;
  workflowId: string | null;
  showLivePanel: boolean;

  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  addNode: (type: string, position: { x: number; y: number }) => void;
  deleteNode: (nodeId: string) => void;
  updateNodeData: (nodeId: string, data: any) => void;
  setSelectedNode: (node: Node | null) => void;
  setWorkflowName: (name: string) => void;
  setWorkflowDescription: (description: string) => void;
  setWorkflowId: (id: string | null) => void;
  setShowLivePanel: (show: boolean) => void;
  loadWorkflow: (workflow: { id: string; name: string; description?: string; graph_data: { nodes: Node[]; edges: Edge[] } }) => void;
  clearWorkflow: () => void;
}

let nodeId = 0;
const getId = () => `node_${nodeId++}`;

export const useWorkflowStore = create<WorkflowState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNode: null,
  workflowName: 'Untitled Workflow',
  workflowDescription: '',
  workflowId: null,
  showLivePanel: false,
  
  setNodes: (nodes) => set({ nodes }),
  
  setEdges: (edges) => set({ edges }),
  
  onNodesChange: (changes) => {
    set({
      nodes: applyNodeChanges(changes, get().nodes),
    });
  },
  
  onEdgesChange: (changes) => {
    set({
      edges: applyEdgeChanges(changes, get().edges),
    });
  },
  
  onConnect: (connection) => {
    set({
      edges: addEdge(connection, get().edges),
    });
  },
  
  addNode: (type, position) => {
    const data: Record<string, unknown> = { label: getNodeLabel(type) };
    if (type === 'inputNode') {
      data.fields = [{ id: `f_${Date.now()}`, name: 'input', type: 'text' }];
    } else if (type === 'aiNode') {
      data.aiTask = 'reasoning';
      data.outputFormat = 'text';
      data.temperature = 0.7;
    } else if (type === 'httpNode') {
      data.method = 'GET';
      data.url = '';
      data.headers = [];
      data.authType = 'none';
      data.authValue = '';
      data.authHeader = 'X-API-Key';
      data.bodyTemplate = '';
      data.timeout = 30;
    } else if (type === 'transformNode') {
      data.transformMode = 'field_map';
      data.fieldMappings = [];
      data.template = '{}';
      data.filterKeys = '';
    } else if (type === 'humanReviewNode') {
      data.reviewPrompt = 'Please review the data from the previous step and approve or reject.';
    } else if (type === 'ruleNode') {
      data.rules = [];
      data.combineMode = 'AND';
    } else if (type === 'codeNode') {
      data.code = 'output = input_data';
      data.timeout = 10;
    } else if (type === 'validatorNode') {
      data.validationRules = [];
    } else if (type === 'switchNode') {
      data.switchField = '';
      data.cases = [];
    } else if (type === 'formatterNode') {
      data.template = '';
      data.outputFormat = 'text';
      data.subjectTemplate = '';
    } else if (type === 'aggregatorNode') {
      data.sourceField = '';
      data.operation = 'count';
      data.valueField = '';
      data.groupBy = '';
      data.separator = ', ';
    }
    const newNode: Node = { id: getId(), type, position, data };
    set({ nodes: [...get().nodes, newNode] });
  },
  
  deleteNode: (nodeId) => {
    set({
      nodes: get().nodes.filter((node) => node.id !== nodeId),
      edges: get().edges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId),
    });
  },
  
  updateNodeData: (nodeId, data) => {
    const updatedNodes = get().nodes.map((node) =>
      node.id === nodeId ? { ...node, data: { ...node.data, ...data } } : node
    );
    const sel = get().selectedNode;
    set({
      nodes: updatedNodes,
      selectedNode: sel?.id === nodeId
        ? (updatedNodes.find(n => n.id === nodeId) ?? sel)
        : sel,
    });
  },
  
  setSelectedNode: (node) => set({ selectedNode: node }),
  
  setWorkflowName: (name) => set({ workflowName: name }),
  setWorkflowDescription: (description) => set({ workflowDescription: description }),
  setWorkflowId: (id) => set({ workflowId: id }),
  setShowLivePanel: (show) => set({ showLivePanel: show }),

  loadWorkflow: (workflow) => set({
    nodes: workflow.graph_data?.nodes ?? [],
    edges: workflow.graph_data?.edges ?? [],
    workflowId: workflow.id,
    workflowName: workflow.name,
    workflowDescription: workflow.description ?? '',
    selectedNode: null,
    showLivePanel: false,
  }),

  clearWorkflow: () => set({
    nodes: [],
    edges: [],
    selectedNode: null,
    workflowName: 'Untitled Workflow',
    workflowDescription: '',
    workflowId: null,
    showLivePanel: false,
  }),
}));

function getNodeLabel(type: string): string {
  const labels: { [key: string]: string } = {
    inputNode: 'Input',
    aiNode: 'AI Agent',
    verificationNode: 'Verification',
    decisionNode: 'Decision',
    outputNode: 'Output',
    httpNode: 'HTTP Request',
    transformNode: 'Transform',
    humanReviewNode: 'Human Review',
    ruleNode: 'Rule Engine',
    codeNode: 'Code Runner',
    validatorNode: 'Validator',
    switchNode: 'Switch Router',
    formatterNode: 'Formatter',
    aggregatorNode: 'Aggregator',
  };
  return labels[type] || 'Node';
}
