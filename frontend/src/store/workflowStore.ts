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
  // Column schemas per node id, filled by a data preview; powers the column pickers in the properties panel
  previewSchemas: Record<string, { name: string; type: string; pii?: boolean }[]>;
  setPreviewSchemas: (schemas: Record<string, { name: string; type: string; pii?: boolean }[]>) => void;
  // Dataset id of each node's last preview (lets the editor profile data and suggest quality checks)
  previewDatasetIds: Record<string, string>;
  setPreviewDatasetIds: (ids: Record<string, string>) => void;

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
  previewSchemas: {},
  setPreviewSchemas: (schemas) => set({ previewSchemas: schemas }),
  previewDatasetIds: {},
  setPreviewDatasetIds: (ids) => set({ previewDatasetIds: ids }),
  
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
    } else if (type === 'loadDataNode') {
      data.source = 'file';
      data.fileName = '';
      data.connectionId = '';
      data.schema = 'public';
      data.table = '';
      data.maxRows = '';
    } else if (type === 'cleanDataNode') {
      data.trimAll = true;
      data.removeDuplicates = false;
      data.dropMissing = [];
      data.fillMissing = [];
      data.rename = [];
      data.keepColumns = [];
    } else if (type === 'combineDataNode') {
      data.joinType = 'inner';
      data.keys = [{ left: '', right: '' }];
      data.swap = false;
    } else if (type === 'summariseDataNode') {
      data.groupBy = [];
      data.aggregations = [{ column: '*', fn: 'count', as: 'row_count' }];
    } else if (type === 'qualityGateNode') {
      data.rules = [];
      data.onFail = 'stop';
    } else if (type === 'indexDocsNode') {
      data.collection = '';
      data.source = 'files';
      data.fileNames = [];
      data.textColumn = '';
      data.sourceColumn = '';
      data.chunkSize = 800;
      data.overlap = 100;
      data.removeMissing = false;
    } else if (type === 'retrieveNode') {
      data.collection = '';
      data.query = '{{question}}';
      data.topK = 4;
      data.minScore = 0;
    } else if (type === 'ragAnswerNode') {
      data.collection = '';
      data.question = '{{question}}';
      data.topK = 4;
      data.minScore = 0;
      data.instructions = '';
      data.noAnswerText = 'I could not find this in your documents.';
    } else if (type === 'sqlNode') {
      data.query = 'SELECT *\nFROM input\nLIMIT 100';
    } else if (type === 'indianKycNode') {
      data.documentType = 'pan';
      data.provider = 'surepass';
      data.apiKey = '';
      data.documentField = 'document_number';
      data.customEndpoint = '';
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
    indianKycNode: 'Indian KYC',
    loadDataNode: 'Load Data',
    cleanDataNode: 'Clean',
    combineDataNode: 'Combine',
    summariseDataNode: 'Summarise',
    sqlNode: 'SQL',
    qualityGateNode: 'Quality Check',
    indexDocsNode: 'Index Documents',
    retrieveNode: 'Retrieve',
    ragAnswerNode: 'RAG Answer',
  };
  return labels[type] || 'Node';
}
