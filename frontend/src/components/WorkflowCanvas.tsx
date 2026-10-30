import { useCallback, useRef } from 'react';
import ReactFlow, {
  Controls,
  Background,
  BackgroundVariant,
  MiniMap,
  Panel,
} from 'reactflow';
import 'reactflow/dist/style.css';

import { useWorkflowStore } from '@/store/workflowStore';
import {
  InputNode, AINode, VerificationNode, DecisionNode, OutputNode,
  HttpNode, TransformNode, HumanReviewNode,
  RuleNode, CodeNode, ValidatorNode, SwitchNode, FormatterNode, AggregatorNode,
  IndianKycNode, LoadDataNode, CleanDataNode, CombineDataNode, SummariseDataNode, SqlNode, QualityGateNode, IndexDocsNode, RetrieveNode, RagAnswerNode,
  PredictNode, BatchScoreNode, DriftCheckNode, FeedbackNode, RegistryPromoteNode,
} from './CustomNodes';
import { NodePalette } from './NodePalette';
import { NodePropertiesPanel } from './NodePropertiesPanel';
import { LiveApiPanel } from './LiveApiPanel';
import { Toolbar } from './Toolbar';

const nodeTypes = {
  inputNode: InputNode,
  aiNode: AINode,
  verificationNode: VerificationNode,
  decisionNode: DecisionNode,
  outputNode: OutputNode,
  httpNode: HttpNode,
  transformNode: TransformNode,
  humanReviewNode: HumanReviewNode,
  ruleNode: RuleNode,
  codeNode: CodeNode,
  validatorNode: ValidatorNode,
  switchNode: SwitchNode,
  formatterNode: FormatterNode,
  aggregatorNode: AggregatorNode,
  indianKycNode: IndianKycNode,
  loadDataNode: LoadDataNode,
  cleanDataNode: CleanDataNode,
  combineDataNode: CombineDataNode,
  summariseDataNode: SummariseDataNode,
  sqlNode: SqlNode,
  qualityGateNode: QualityGateNode,
  indexDocsNode: IndexDocsNode,
  predictNode: PredictNode,
  batchScoreNode: BatchScoreNode,
  driftCheckNode: DriftCheckNode,
  feedbackNode: FeedbackNode,
  registryPromoteNode: RegistryPromoteNode,
  retrieveNode: RetrieveNode,
  ragAnswerNode: RagAnswerNode,
};

export function WorkflowCanvas() {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    addNode,
    setSelectedNode,
    showLivePanel,
  } = useWorkflowStore();

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      const type = event.dataTransfer.getData('application/reactflow');
      
      if (!type || !reactFlowWrapper.current) {
        return;
      }

      const reactFlowBounds = reactFlowWrapper.current.getBoundingClientRect();
      const position = {
        x: event.clientX - reactFlowBounds.left - 75,
        y: event.clientY - reactFlowBounds.top - 20,
      };

      addNode(type, position);
    },
    [addNode]
  );

  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: any) => {
      setSelectedNode(node);
    },
    [setSelectedNode]
  );

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
  }, [setSelectedNode]);

  return (
    <div className="w-full h-screen" ref={reactFlowWrapper}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        fitView
        className="bg-gray-50"
      >
        <Background variant={BackgroundVariant.Dots} gap={12} size={1} />
        <Controls />
        <MiniMap
          nodeColor={(node) => {
            const colors: { [key: string]: string } = {
              inputNode: '#3b82f6',
              aiNode: '#9333ea',
              verificationNode: '#22c55e',
              decisionNode: '#eab308',
              outputNode: '#6366f1',
              httpNode: '#f97316',
              transformNode: '#14b8a6',
              humanReviewNode: '#f43f5e',
              ruleNode: '#f59e0b',
              codeNode: '#71717a',
              validatorNode: '#10b981',
              switchNode: '#7c3aed',
              formatterNode: '#65a30d',
              aggregatorNode: '#0ea5e9',
              indianKycNode: '#c026d3',
              loadDataNode: '#06b6d4',
              cleanDataNode: '#06b6d4',
              combineDataNode: '#06b6d4',
              summariseDataNode: '#06b6d4',
              sqlNode: '#06b6d4',
              qualityGateNode: '#ec4899',
              indexDocsNode: '#6366f1',
              predictNode: '#10b981',
              batchScoreNode: '#10b981',
              driftCheckNode: '#10b981',
              feedbackNode: '#10b981',
              registryPromoteNode: '#10b981',
              retrieveNode: '#6366f1',
              ragAnswerNode: '#6366f1',
            };
            return colors[node.type || 'default'] || '#94a3b8';
          }}
          className="bg-white border border-gray-200 rounded"
        />
        <Panel position="top-left" className="!m-0 !left-[288px] !right-4 !top-4 flex justify-center pointer-events-none">
          <div className="max-w-full overflow-x-auto pointer-events-auto rounded-lg [&>div]:min-w-max"><Toolbar /></div>
        </Panel>
      </ReactFlow>
      
      <NodePalette />
      {showLivePanel ? <LiveApiPanel /> : <NodePropertiesPanel />}
    </div>
  );
}
