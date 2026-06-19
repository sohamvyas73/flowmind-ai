import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import {
  Database, Brain, CheckCircle, GitBranch, Send,
  Globe, Shuffle, UserCheck,
  Scale, Terminal, ShieldCheck, GitFork, FileText, Calculator, ScanLine,
} from 'lucide-react';

const nodeStyles = 'px-4 py-3 shadow-lg rounded-lg border-2 bg-white min-w-[160px]';

// ── Original 5 nodes ──────────────────────────────────────────────────────────

export const InputNode = memo(({ data, selected }: NodeProps) => (
  <div className={`${nodeStyles} ${selected ? 'border-blue-500' : 'border-gray-300'}`}>
    <div className="flex items-center gap-2">
      <Database className="w-5 h-5 text-blue-600" />
      <div className="font-semibold text-sm">{data.label}</div>
    </div>
    {data.description && <div className="text-xs text-gray-500 mt-1">{data.description}</div>}
    <Handle type="source" position={Position.Right} className="w-3 h-3 bg-blue-500" />
  </div>
));

export const AINode = memo(({ data, selected }: NodeProps) => (
  <div className={`${nodeStyles} ${selected ? 'border-purple-500' : 'border-gray-300'}`}>
    <Handle type="target" position={Position.Left} className="w-3 h-3 bg-purple-500" />
    <div className="flex items-center gap-2">
      <Brain className="w-5 h-5 text-purple-600" />
      <div className="font-semibold text-sm">{data.label}</div>
    </div>
    {data.aiTask && (
      <div className="text-xs text-gray-600 mt-1 bg-purple-50 px-2 py-1 rounded flex items-center justify-between">
        <span>{data.aiTask}</span>
        {data.outputFormat && data.outputFormat !== 'text' && (
          <span className="ml-1 text-purple-500 font-mono">[{data.outputFormat}]</span>
        )}
      </div>
    )}
    <Handle type="source" position={Position.Right} className="w-3 h-3 bg-purple-500" />
  </div>
));

export const VerificationNode = memo(({ data, selected }: NodeProps) => (
  <div className={`${nodeStyles} ${selected ? 'border-green-500' : 'border-gray-300'}`}>
    <Handle type="target" position={Position.Left} className="w-3 h-3 bg-green-500" />
    <div className="flex items-center gap-2">
      <CheckCircle className="w-5 h-5 text-green-600" />
      <div className="font-semibold text-sm">{data.label}</div>
    </div>
    {data.verificationType && <div className="text-xs text-gray-600 mt-1">{data.verificationType}</div>}
    <Handle type="source" position={Position.Right} className="w-3 h-3 bg-green-500" />
  </div>
));

export const DecisionNode = memo(({ data, selected }: NodeProps) => (
  <div className={`${nodeStyles} ${selected ? 'border-yellow-500' : 'border-gray-300'}`}>
    <Handle type="target" position={Position.Left} className="w-3 h-3 bg-yellow-500" />
    <div className="flex items-center gap-2">
      <GitBranch className="w-5 h-5 text-yellow-600" />
      <div className="font-semibold text-sm">{data.label}</div>
    </div>
    {data.threshold !== undefined && (
      <div className="text-xs text-gray-600 mt-1">Threshold: {data.threshold}</div>
    )}
    <Handle type="source" position={Position.Right} id="approved" className="w-3 h-3 bg-green-500" style={{ top: '30%' }} />
    <Handle type="source" position={Position.Right} id="rejected" className="w-3 h-3 bg-red-500"   style={{ top: '70%' }} />
  </div>
));

export const OutputNode = memo(({ data, selected }: NodeProps) => (
  <div className={`${nodeStyles} ${selected ? 'border-indigo-500' : 'border-gray-300'}`}>
    <Handle type="target" position={Position.Left} className="w-3 h-3 bg-indigo-500" />
    <div className="flex items-center gap-2">
      <Send className="w-5 h-5 text-indigo-600" />
      <div className="font-semibold text-sm">{data.label}</div>
    </div>
    {data.outputType && <div className="text-xs text-gray-600 mt-1">{data.outputType}</div>}
  </div>
));

// ── Batch 2 nodes ─────────────────────────────────────────────────────────────

export const HttpNode = memo(({ data, selected }: NodeProps) => (
  <div className={`${nodeStyles} ${selected ? 'border-orange-500' : 'border-gray-300'}`}>
    <Handle type="target" position={Position.Left} className="w-3 h-3 bg-orange-500" />
    <div className="flex items-center gap-2">
      <Globe className="w-5 h-5 text-orange-600" />
      <div className="font-semibold text-sm">{data.label}</div>
    </div>
    {data.method && (
      <div className="text-xs text-gray-600 mt-1 bg-orange-50 px-2 py-1 rounded font-mono truncate">
        {data.method} {data.url ? String(data.url).replace(/^https?:\/\//, '').slice(0, 26) : '—'}
      </div>
    )}
    <Handle type="source" position={Position.Right} className="w-3 h-3 bg-orange-500" />
  </div>
));

export const TransformNode = memo(({ data, selected }: NodeProps) => {
  const modeLabel: Record<string, string> = { field_map: 'Field Map', template: 'Template', filter: 'Filter' };
  return (
    <div className={`${nodeStyles} ${selected ? 'border-teal-500' : 'border-gray-300'}`}>
      <Handle type="target" position={Position.Left} className="w-3 h-3 bg-teal-500" />
      <div className="flex items-center gap-2">
        <Shuffle className="w-5 h-5 text-teal-600" />
        <div className="font-semibold text-sm">{data.label}</div>
      </div>
      {data.transformMode && (
        <div className="text-xs text-gray-600 mt-1">{modeLabel[data.transformMode as string] || data.transformMode}</div>
      )}
      <Handle type="source" position={Position.Right} className="w-3 h-3 bg-teal-500" />
    </div>
  );
});

export const HumanReviewNode = memo(({ data, selected }: NodeProps) => (
  <div className={`${nodeStyles} ${selected ? 'border-rose-500' : 'border-gray-300'}`}>
    <Handle type="target" position={Position.Left} className="w-3 h-3 bg-rose-500" />
    <div className="flex items-center gap-2">
      <UserCheck className="w-5 h-5 text-rose-600" />
      <div className="font-semibold text-sm">{data.label}</div>
    </div>
    <div className="text-xs text-rose-600 mt-1 bg-rose-50 px-2 py-1 rounded">Awaits human approval</div>
    <Handle type="source" position={Position.Right} className="w-3 h-3 bg-rose-500" />
  </div>
));

// ── Batch 3 nodes ─────────────────────────────────────────────────────────────

export const RuleNode = memo(({ data, selected }: NodeProps) => {
  const ruleCount = Array.isArray(data.rules) ? (data.rules as unknown[]).length : 0;
  return (
    <div className={`${nodeStyles} ${selected ? 'border-amber-500' : 'border-gray-300'}`}>
      <Handle type="target" position={Position.Left} className="w-3 h-3 bg-amber-500" />
      <div className="flex items-center gap-2">
        <Scale className="w-5 h-5 text-amber-600" />
        <div className="font-semibold text-sm">{data.label}</div>
      </div>
      <div className="text-xs text-gray-600 mt-1 bg-amber-50 px-2 py-1 rounded">
        {ruleCount} rule{ruleCount !== 1 ? 's' : ''} · {data.combineMode || 'AND'}
      </div>
      <Handle type="source" position={Position.Right} id="pass" className="w-3 h-3 bg-green-500" style={{ top: '30%' }} />
      <Handle type="source" position={Position.Right} id="fail" className="w-3 h-3 bg-red-500"   style={{ top: '70%' }} />
    </div>
  );
});

export const CodeNode = memo(({ data, selected }: NodeProps) => (
  <div className={`${nodeStyles} ${selected ? 'border-zinc-600' : 'border-gray-300'}`}>
    <Handle type="target" position={Position.Left} className="w-3 h-3 bg-zinc-600" />
    <div className="flex items-center gap-2">
      <Terminal className="w-5 h-5 text-zinc-700" />
      <div className="font-semibold text-sm">{data.label}</div>
    </div>
    <div className="text-xs text-zinc-600 mt-1 bg-zinc-100 px-2 py-1 rounded font-mono truncate">
      {data.code ? String(data.code).split('\n')[0].slice(0, 30) + '…' : 'output = input_data'}
    </div>
    <Handle type="source" position={Position.Right} className="w-3 h-3 bg-zinc-600" />
  </div>
));

export const ValidatorNode = memo(({ data, selected }: NodeProps) => {
  const ruleCount = Array.isArray(data.validationRules) ? (data.validationRules as unknown[]).length : 0;
  return (
    <div className={`${nodeStyles} ${selected ? 'border-emerald-500' : 'border-gray-300'}`}>
      <Handle type="target" position={Position.Left} className="w-3 h-3 bg-emerald-500" />
      <div className="flex items-center gap-2">
        <ShieldCheck className="w-5 h-5 text-emerald-600" />
        <div className="font-semibold text-sm">{data.label}</div>
      </div>
      <div className="text-xs text-gray-600 mt-1">{ruleCount} validation rule{ruleCount !== 1 ? 's' : ''}</div>
      <Handle type="source" position={Position.Right} className="w-3 h-3 bg-emerald-500" />
    </div>
  );
});

export const SwitchNode = memo(({ data, selected }: NodeProps) => {
  const cases = Array.isArray(data.cases) ? data.cases as Array<{handle: string; label?: string; matchValue?: string}> : [];
  return (
    <div className={`${nodeStyles} ${selected ? 'border-violet-500' : 'border-gray-300'}`} style={{ minHeight: `${48 + cases.length * 22}px` }}>
      <Handle type="target" position={Position.Left} className="w-3 h-3 bg-violet-500" />
      <div className="flex items-center gap-2">
        <GitFork className="w-5 h-5 text-violet-600" />
        <div className="font-semibold text-sm">{data.label}</div>
      </div>
      {data.switchField && (
        <div className="text-xs text-gray-500 mt-1 font-mono">on: {String(data.switchField).slice(0, 22)}</div>
      )}
      {cases.map((c, i) => (
        <Handle
          key={c.handle}
          type="source"
          position={Position.Right}
          id={c.handle}
          className="w-3 h-3 bg-violet-500"
          style={{ top: `${30 + i * 22}%` }}
          title={c.label || c.matchValue || c.handle}
        />
      ))}
      <Handle type="source" position={Position.Right} id="default" className="w-3 h-3 bg-gray-400"
        style={{ top: `${30 + cases.length * 22}%` }} title="default" />
    </div>
  );
});

export const FormatterNode = memo(({ data, selected }: NodeProps) => (
  <div className={`${nodeStyles} ${selected ? 'border-lime-500' : 'border-gray-300'}`}>
    <Handle type="target" position={Position.Left} className="w-3 h-3 bg-lime-600" />
    <div className="flex items-center gap-2">
      <FileText className="w-5 h-5 text-lime-700" />
      <div className="font-semibold text-sm">{data.label}</div>
    </div>
    {data.outputFormat && (
      <div className="text-xs text-gray-600 mt-1 bg-lime-50 px-2 py-1 rounded">{data.outputFormat}</div>
    )}
    <Handle type="source" position={Position.Right} className="w-3 h-3 bg-lime-600" />
  </div>
));

export const AggregatorNode = memo(({ data, selected }: NodeProps) => (
  <div className={`${nodeStyles} ${selected ? 'border-sky-500' : 'border-gray-300'}`}>
    <Handle type="target" position={Position.Left} className="w-3 h-3 bg-sky-500" />
    <div className="flex items-center gap-2">
      <Calculator className="w-5 h-5 text-sky-600" />
      <div className="font-semibold text-sm">{data.label}</div>
    </div>
    {data.operation && (
      <div className="text-xs text-gray-600 mt-1 bg-sky-50 px-2 py-1 rounded font-mono">
        {data.operation}{data.sourceField ? `(${String(data.sourceField).slice(0, 18)})` : ''}
      </div>
    )}
    <Handle type="source" position={Position.Right} className="w-3 h-3 bg-sky-500" />
  </div>
));

export const IndianKycNode = memo(({ data, selected }: NodeProps) => {
  const docLabels: Record<string, string> = {
    pan: 'PAN Card', aadhaar: 'Aadhaar', voter_id: 'Voter ID',
    driving_license: 'Driving License', passport: 'Passport',
  };
  return (
    <div className={`${nodeStyles} ${selected ? 'border-fuchsia-500' : 'border-gray-300'}`}>
      <Handle type="target" position={Position.Left} className="w-3 h-3 bg-fuchsia-500" />
      <div className="flex items-center gap-2">
        <ScanLine className="w-5 h-5 text-fuchsia-600" />
        <div className="font-semibold text-sm">{data.label}</div>
      </div>
      {data.documentType && (
        <div className="text-xs text-gray-600 mt-1 bg-fuchsia-50 px-2 py-1 rounded flex items-center justify-between">
          <span>{docLabels[data.documentType as string] || data.documentType}</span>
          {data.provider && <span className="ml-1 text-fuchsia-500 capitalize">{data.provider}</span>}
        </div>
      )}
      <Handle type="source" position={Position.Right} className="w-3 h-3 bg-fuchsia-500" />
    </div>
  );
});

// Display names
InputNode.displayName       = 'InputNode';
AINode.displayName          = 'AINode';
VerificationNode.displayName = 'VerificationNode';
DecisionNode.displayName    = 'DecisionNode';
OutputNode.displayName      = 'OutputNode';
HttpNode.displayName        = 'HttpNode';
TransformNode.displayName   = 'TransformNode';
HumanReviewNode.displayName = 'HumanReviewNode';
RuleNode.displayName        = 'RuleNode';
CodeNode.displayName        = 'CodeNode';
ValidatorNode.displayName   = 'ValidatorNode';
SwitchNode.displayName      = 'SwitchNode';
FormatterNode.displayName   = 'FormatterNode';
AggregatorNode.displayName  = 'AggregatorNode';
IndianKycNode.displayName   = 'IndianKycNode';
