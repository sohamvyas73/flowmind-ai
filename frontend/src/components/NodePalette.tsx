import { useState, useEffect } from 'react';
import { Database, Brain, CheckCircle, GitBranch, Send, Globe, Shuffle, UserCheck, LayoutTemplate, Scale, Terminal, ShieldCheck, GitFork, FileText, Calculator, ScanLine } from 'lucide-react';
import { useReactFlow } from 'reactflow';
import { useWorkflowStore } from '@/store/workflowStore';
import { healthCheck } from '@/services/api';
import { sampleWorkflows, SampleWorkflow } from '@/data/sampleWorkflows';

interface NodeTypeConfig {
  type: string;
  label: string;
  description: string;
  icon: React.FC<{ className?: string }>;
  border: string;
  bg: string;
  text: string;
}

const nodeTypeList: NodeTypeConfig[] = [
  {
    type: 'inputNode',
    label: 'Input',
    description: 'API trigger fields',
    icon: ({ className }) => <Database className={className} />,
    border: 'border-blue-200',
    bg: 'bg-blue-50',
    text: 'text-blue-700',
  },
  {
    type: 'aiNode',
    label: 'AI Agent',
    description: 'LLM processing',
    icon: ({ className }) => <Brain className={className} />,
    border: 'border-purple-200',
    bg: 'bg-purple-50',
    text: 'text-purple-700',
  },
  {
    type: 'verificationNode',
    label: 'Verification',
    description: 'Validate & check',
    icon: ({ className }) => <CheckCircle className={className} />,
    border: 'border-green-200',
    bg: 'bg-green-50',
    text: 'text-green-700',
  },
  {
    type: 'decisionNode',
    label: 'Decision',
    description: 'Approve / reject',
    icon: ({ className }) => <GitBranch className={className} />,
    border: 'border-yellow-200',
    bg: 'bg-yellow-50',
    text: 'text-yellow-700',
  },
  {
    type: 'outputNode',
    label: 'Output',
    description: 'Deliver results',
    icon: ({ className }) => <Send className={className} />,
    border: 'border-indigo-200',
    bg: 'bg-indigo-50',
    text: 'text-indigo-700',
  },
  {
    type: 'httpNode',
    label: 'HTTP Request',
    description: 'Call external APIs',
    icon: ({ className }) => <Globe className={className} />,
    border: 'border-orange-200',
    bg: 'bg-orange-50',
    text: 'text-orange-700',
  },
  {
    type: 'transformNode',
    label: 'Transform',
    description: 'Reshape data',
    icon: ({ className }) => <Shuffle className={className} />,
    border: 'border-teal-200',
    bg: 'bg-teal-50',
    text: 'text-teal-700',
  },
  {
    type: 'humanReviewNode',
    label: 'Human Review',
    description: 'Pause for approval',
    icon: ({ className }) => <UserCheck className={className} />,
    border: 'border-rose-200',
    bg: 'bg-rose-50',
    text: 'text-rose-700',
  },
  {
    type: 'ruleNode',
    label: 'Rule Engine',
    description: 'AND/OR rule conditions',
    icon: ({ className }) => <Scale className={className} />,
    border: 'border-amber-200',
    bg: 'bg-amber-50',
    text: 'text-amber-700',
  },
  {
    type: 'codeNode',
    label: 'Code Runner',
    description: 'Run sandboxed Python',
    icon: ({ className }) => <Terminal className={className} />,
    border: 'border-zinc-200',
    bg: 'bg-zinc-50',
    text: 'text-zinc-700',
  },
  {
    type: 'validatorNode',
    label: 'Validator',
    description: 'Schema & field checks',
    icon: ({ className }) => <ShieldCheck className={className} />,
    border: 'border-emerald-200',
    bg: 'bg-emerald-50',
    text: 'text-emerald-700',
  },
  {
    type: 'switchNode',
    label: 'Switch Router',
    description: 'Route by field value',
    icon: ({ className }) => <GitFork className={className} />,
    border: 'border-violet-200',
    bg: 'bg-violet-50',
    text: 'text-violet-700',
  },
  {
    type: 'formatterNode',
    label: 'Formatter',
    description: 'Template-based output',
    icon: ({ className }) => <FileText className={className} />,
    border: 'border-lime-200',
    bg: 'bg-lime-50',
    text: 'text-lime-700',
  },
  {
    type: 'aggregatorNode',
    label: 'Aggregator',
    description: 'Sum, avg, group arrays',
    icon: ({ className }) => <Calculator className={className} />,
    border: 'border-sky-200',
    bg: 'bg-sky-50',
    text: 'text-sky-700',
  },
  {
    type: 'indianKycNode',
    label: 'Indian KYC',
    description: 'Verify Aadhaar, PAN & more',
    icon: ({ className }) => <ScanLine className={className} />,
    border: 'border-fuchsia-200',
    bg: 'bg-fuchsia-50',
    text: 'text-fuchsia-700',
  },
];

type BackendStatus = 'checking' | 'online' | 'offline';

export function NodePalette() {
  const { setNodes, setEdges, setWorkflowName, setWorkflowDescription } = useWorkflowStore();
  const { fitView } = useReactFlow();
  const [status, setStatus] = useState<BackendStatus>('checking');

  useEffect(() => {
    const check = async () => {
      const online = await healthCheck();
      setStatus(online ? 'online' : 'offline');
    };
    check();
    const id = setInterval(check, 5000);
    return () => clearInterval(id);
  }, []);

  const onDragStart = (event: React.DragEvent, nodeType: string) => {
    event.dataTransfer.setData('application/reactflow', nodeType);
    event.dataTransfer.effectAllowed = 'move';
  };

  const loadSample = (sample: SampleWorkflow) => {
    setNodes(sample.nodes);
    setEdges(sample.edges);
    setWorkflowName(sample.name);
    setWorkflowDescription(sample.description);
    setTimeout(() => fitView({ padding: 0.15, duration: 400 }), 50);
  };

  const statusConfig: Record<BackendStatus, { dot: string; text: string; label: string }> = {
    checking: { dot: 'bg-gray-400 animate-pulse', text: 'text-gray-500', label: 'Checking...' },
    online:   { dot: 'bg-green-500', text: 'text-green-700', label: 'Backend: Live' },
    offline:  { dot: 'bg-red-500', text: 'text-red-700', label: 'Backend: Offline' },
  };
  const { dot, text, label } = statusConfig[status];

  return (
    <div className="absolute left-4 top-4 w-64 bg-white rounded-lg shadow-xl border border-gray-200 z-10 flex flex-col max-h-[calc(100vh-32px)]">

      {/* Backend status */}
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-gray-200 flex-shrink-0">
        <span className="relative flex h-2.5 w-2.5 flex-shrink-0">
          {status === 'online' && (
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
          )}
          <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${dot}`} />
        </span>
        <span className={`text-xs font-semibold ${text}`}>{label}</span>
      </div>

      <div className="overflow-y-auto flex-1">

        {/* Node library */}
        <div className="p-4 border-b border-gray-200">
          <p className="text-xs font-semibold text-gray-700 mb-1">Node Library</p>
          <p className="text-xs text-gray-400 mb-3">Drag nodes onto the canvas</p>
          <div className="space-y-1.5">
            {nodeTypeList.map(({ type, label: nodeLabel, description, icon: Icon, border, bg, text: nodeText }) => (
              <div
                key={type}
                draggable
                onDragStart={(e) => onDragStart(e, type)}
                className={`flex items-center gap-2.5 px-3 py-2 rounded-lg border-2 cursor-move hover:shadow-md transition-shadow ${border} ${bg}`}
              >
                <Icon className={`w-3.5 h-3.5 flex-shrink-0 ${nodeText}`} />
                <div className="min-w-0">
                  <p className={`text-xs font-semibold leading-tight ${nodeText}`}>{nodeLabel}</p>
                  <p className="text-xs text-gray-400 leading-tight truncate">{description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Sample workflows */}
        <div className="p-4">
          <div className="flex items-center gap-2 mb-3">
            <LayoutTemplate className="w-3.5 h-3.5 text-gray-500" />
            <p className="text-xs font-semibold text-gray-700">Sample Workflows</p>
          </div>
          <div className="space-y-2.5">
            {sampleWorkflows.map((sample) => (
              <div
                key={sample.name}
                className="border border-gray-200 rounded-lg p-3 hover:border-blue-300 hover:bg-blue-50/40 transition-colors"
              >
                <p className="text-xs font-semibold text-gray-800 mb-1">{sample.name}</p>
                <p className="text-xs text-gray-500 leading-relaxed mb-2">{sample.description}</p>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-400">{sample.nodes.length} nodes</span>
                  <button
                    onClick={() => loadSample(sample)}
                    className="text-xs px-2.5 py-1 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors font-medium"
                  >
                    Load
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}
