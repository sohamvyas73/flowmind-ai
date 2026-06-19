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
  IndianKycNode,
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
            };
            return colors[node.type || 'default'] || '#94a3b8';
          }}
          className="bg-white border border-gray-200 rounded"
        />
        <Panel position="top-center">
          <Toolbar />
        </Panel>
      </ReactFlow>
      
      <NodePalette />
      {showLivePanel ? <LiveApiPanel /> : <NodePropertiesPanel />}
    </div>
  );
}
