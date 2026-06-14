import { useState, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Node } from 'reactflow';
import {
  X, Upload, Play, CheckCircle2, XCircle, Loader2,
  Database, Brain, CheckCircle, GitBranch, Send,
  Globe, Shuffle, UserCheck, Clock,
  Scale, Terminal, ShieldCheck, GitFork, FileText, Calculator,
} from 'lucide-react';
import { WorkflowExecution, InputField } from '@/types/workflow';

type Phase = 'input' | 'running' | 'result';

const nodeIcons: Record<string, React.FC<{ className?: string }>> = {
  inputNode:        ({ className }) => <Database      className={className} />,
  aiNode:           ({ className }) => <Brain         className={className} />,
  verificationNode: ({ className }) => <CheckCircle   className={className} />,
  decisionNode:     ({ className }) => <GitBranch     className={className} />,
  outputNode:       ({ className }) => <Send          className={className} />,
  httpNode:         ({ className }) => <Globe         className={className} />,
  transformNode:    ({ className }) => <Shuffle       className={className} />,
  humanReviewNode:  ({ className }) => <UserCheck     className={className} />,
  ruleNode:         ({ className }) => <Scale         className={className} />,
  codeNode:         ({ className }) => <Terminal      className={className} />,
  validatorNode:    ({ className }) => <ShieldCheck   className={className} />,
  switchNode:       ({ className }) => <GitFork       className={className} />,
  formatterNode:    ({ className }) => <FileText      className={className} />,
  aggregatorNode:   ({ className }) => <Calculator    className={className} />,
};

const nodeColors: Record<string, string> = {
  inputNode:        'text-blue-600',
  aiNode:           'text-purple-600',
  verificationNode: 'text-green-600',
  decisionNode:     'text-yellow-600',
  outputNode:       'text-indigo-600',
  httpNode:         'text-orange-600',
  transformNode:    'text-teal-600',
  humanReviewNode:  'text-rose-600',
  ruleNode:         'text-amber-600',
  codeNode:         'text-zinc-600',
  validatorNode:    'text-emerald-600',
  switchNode:       'text-violet-600',
  formatterNode:    'text-lime-700',
  aggregatorNode:   'text-sky-600',
};

interface ExecutionModalProps {
  nodes: Node[];
  onClose: () => void;
  onRun: (inputData: Record<string, unknown>) => Promise<WorkflowExecution>;
}

// Derive fields from node data, with backward compat for old inputType nodes
function getNodeFields(node: Node): InputField[] {
  const data = node.data as Record<string, unknown>;
  if (Array.isArray(data.fields) && data.fields.length > 0) return data.fields as InputField[];
  return [{ id: 'default', name: 'input', type: (data.inputType as InputField['type']) || 'text' }];
}

export function ExecutionModal({ nodes, onClose, onRun }: ExecutionModalProps) {
  const [phase, setPhase] = useState<Phase>('input');
  const [result, setResult] = useState<WorkflowExecution | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  // keyed by `${nodeId}__${fieldId}`
  const [fileInputs, setFileInputs] = useState<Record<string, { content: string; filename: string }>>({});
  const [textInputs, setTextInputs] = useState<Record<string, string>>({});

  const inputNodes = nodes.filter(n => n.type === 'inputNode');
  const labelMap = Object.fromEntries(nodes.map(n => [n.id, n.data.label as string]));

  const handleFileChange = (key: string, file: File) => {
    const reader = new FileReader();
    reader.onload = e => {
      setFileInputs(prev => ({
        ...prev,
        [key]: { content: e.target?.result as string, filename: file.name },
      }));
    };
    const isText = file.type.startsWith('text/') || /\.(txt|csv|json|xml)$/i.test(file.name);
    if (isText) reader.readAsText(file);
    else reader.readAsDataURL(file);
  };

  const handleRun = async () => {
    setPhase('running');
    setRunError(null);

    const nodeInputs: Record<string, unknown> = {};
    inputNodes.forEach(node => {
      const fields = getNodeFields(node);
      const nodeData: Record<string, unknown> = {};
      fields.forEach(field => {
        const key = `${node.id}__${field.id}`;
        if (field.type === 'file' && fileInputs[key]) {
          nodeData[field.name] = fileInputs[key]; // { content, filename }
        } else if (textInputs[key]) {
          nodeData[field.name] = { content: textInputs[key] };
        }
      });
      if (Object.keys(nodeData).length) nodeInputs[node.id] = nodeData;
    });

    try {
      const execution = await onRun({ node_inputs: nodeInputs });
      setResult(execution);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } }; message?: string })
        ?.response?.data?.detail ?? (e as Error)?.message ?? 'Execution failed';
      setRunError(msg);
    }
    setPhase('result');
  };

  const title = phase === 'input' ? 'Execute Workflow'
    : phase === 'running' ? 'Running…'
    : 'Execution Results';

  return createPortal(
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-2xl w-[540px] max-h-[84vh] flex flex-col">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b flex-shrink-0">
          <h2 className="text-base font-semibold text-gray-800">{title}</h2>
          {phase !== 'running' && (
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-6 py-5">

          {/* ── Input phase ── */}
          {phase === 'input' && (
            <div className="space-y-6">
              {inputNodes.length === 0 && (
                <p className="text-sm text-gray-500">
                  No input nodes detected. The workflow will run with default node values.
                </p>
              )}

              {inputNodes.map(node => {
                const fields = getNodeFields(node);
                return (
                  <div key={node.id}>
                    {/* Node header */}
                    <div className="flex items-center gap-2 mb-3">
                      <Database className="w-4 h-4 text-blue-500 flex-shrink-0" />
                      <span className="text-sm font-semibold text-gray-800">{node.data.label as string}</span>
                      {node.data.description && (
                        <span className="text-xs text-gray-400 truncate">{node.data.description as string}</span>
                      )}
                    </div>

                    {/* Fields */}
                    <div className="space-y-3 pl-4 border-l-2 border-blue-100">
                      {fields.map(field => {
                        const key = `${node.id}__${field.id}`;
                        return (
                          <div key={field.id}>
                            <label className="flex items-center gap-1.5 text-xs font-medium text-gray-600 mb-1.5">
                              <span className="font-mono text-gray-800">{field.name || 'unnamed'}</span>
                              <span className="bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">{field.type}</span>
                            </label>
                            {field.type === 'file' ? (
                              <FileDropzone
                                filename={fileInputs[key]?.filename}
                                onChange={file => handleFileChange(key, file)}
                              />
                            ) : (
                              <textarea
                                rows={field.type === 'json' ? 4 : 2}
                                placeholder={
                                  field.type === 'json' ? '{"key": "value"}' :
                                  field.type === 'number' ? '0' :
                                  `Enter ${field.name || 'value'}…`
                                }
                                value={textInputs[key] || ''}
                                onChange={e => setTextInputs(prev => ({ ...prev, [key]: e.target.value }))}
                                spellCheck={false}
                                className={`w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none bg-gray-50 ${field.type === 'json' ? 'font-mono' : ''}`}
                              />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* ── Running phase ── */}
          {phase === 'running' && (
            <div className="flex flex-col items-center justify-center py-14 gap-4">
              <Loader2 className="w-10 h-10 text-blue-500 animate-spin" />
              <p className="text-sm text-gray-500">Executing workflow nodes…</p>
            </div>
          )}

          {/* ── Result phase ── */}
          {phase === 'result' && (
            <div className="space-y-3">
              {runError && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
                  {runError}
                </div>
              )}
              {result?.execution_trace?.map((step: Record<string, unknown>, i: number) => {
                const stepResult = step.result as Record<string, unknown> | undefined;
                const hasError = !!stepResult?.error;
                const nodeType = step.node_type as string;
                const Icon = nodeIcons[nodeType];
                const color = nodeColors[nodeType] || 'text-gray-500';
                return (
                  <div
                    key={i}
                    className={`border rounded-lg p-3 ${hasError ? 'border-red-200 bg-red-50' : 'border-gray-200 bg-gray-50'}`}
                  >
                    <div className="flex items-center gap-2 mb-1.5">
                      {Icon && <Icon className={`w-4 h-4 ${color}`} />}
                      <span className="text-xs font-semibold text-gray-700">
                        {labelMap[step.node_id as string] || step.node_id as string}
                      </span>
                      {hasError
                        ? <XCircle className="w-3.5 h-3.5 text-red-500 ml-auto flex-shrink-0" />
                        : <CheckCircle2 className="w-3.5 h-3.5 text-green-500 ml-auto flex-shrink-0" />
                      }
                    </div>
                    <StepSummary result={stepResult} />
                  </div>
                );
              })}
              {result && !result.execution_trace?.length && !runError && (
                <p className="text-sm text-gray-500">Execution completed with no trace data.</p>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t flex-shrink-0 flex justify-end gap-3">
          {phase === 'input' && (
            <>
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleRun}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-green-600 hover:bg-green-700 rounded-lg transition-colors"
              >
                <Play className="w-4 h-4" />
                Run Workflow
              </button>
            </>
          )}
          {phase === 'result' && (
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
            >
              Close
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}

function FileDropzone({ filename, onChange }: { filename?: string; onChange: (f: File) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div
      onClick={() => ref.current?.click()}
      className="border-2 border-dashed border-gray-300 rounded-lg p-4 text-center cursor-pointer hover:border-blue-400 hover:bg-blue-50/50 transition-colors"
    >
      <input
        ref={ref}
        type="file"
        className="hidden"
        onChange={e => e.target.files?.[0] && onChange(e.target.files[0])}
      />
      {filename ? (
        <p className="text-sm text-green-600 font-medium">✓ {filename}</p>
      ) : (
        <>
          <Upload className="w-5 h-5 text-gray-400 mx-auto mb-1" />
          <p className="text-sm text-gray-500">Click to upload</p>
          <p className="text-xs text-gray-400 mt-0.5">PDF, image, CSV, TXT…</p>
        </>
      )}
    </div>
  );
}

function sanitizeForDisplay(value: unknown, maxStr = 300): unknown {
  if (typeof value === 'string') {
    if (value.startsWith('data:')) {
      const mime = value.split(';')[0].replace('data:', '');
      const sizeKb = Math.round((value.length * 0.75) / 1024);
      return `[file: ${mime}, ~${sizeKb} KB]`;
    }
    return value.length > maxStr ? `${value.slice(0, maxStr)}… [${value.length} chars]` : value;
  }
  if (Array.isArray(value)) return value.map(v => sanitizeForDisplay(v, maxStr));
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, sanitizeForDisplay(v, maxStr)])
    );
  }
  return value;
}

function StepSummary({ result }: { result: Record<string, unknown> | undefined }) {
  if (!result) return null;
  if (result.error) return <p className="text-xs text-red-600">{result.error as string}</p>;

  const safe = sanitizeForDisplay(result) as Record<string, unknown>;

  // Human Review node — awaiting review
  if (safe.status === 'awaiting_review') {
    return (
      <div className="space-y-1.5 mt-1">
        <div className="flex items-center gap-2">
          <Clock className="w-3.5 h-3.5 text-rose-500 flex-shrink-0" />
          <span className="text-xs font-bold text-rose-700 bg-rose-50 px-2 py-0.5 rounded-full">
            Awaiting Human Review
          </span>
        </div>
        {typeof safe.review_prompt === 'string' && safe.review_prompt && (
          <p className="text-xs text-gray-600 italic">{safe.review_prompt as string}</p>
        )}
        <p className="text-xs text-gray-400">Workflow execution paused at this step.</p>
      </div>
    );
  }

  // Decision node — rich layout
  if (safe.decision !== undefined) {
    const approved = String(safe.decision).toLowerCase() === 'approved';
    const confidence = typeof safe.confidence === 'number' ? safe.confidence : null;
    const threshold = typeof safe.threshold === 'number' ? safe.threshold : null;
    const findings = Array.isArray(safe.key_findings) ? safe.key_findings as string[] : [];

    return (
      <div className="space-y-1.5 mt-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${approved ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
            {approved ? '✓ Approved' : '✗ Rejected'}
          </span>
          {confidence !== null && (
            <span className="text-xs text-gray-500">Confidence: {(confidence * 100).toFixed(0)}%</span>
          )}
          {threshold !== null && (
            <span className="text-xs text-gray-400">Threshold: {(threshold * 100).toFixed(0)}%</span>
          )}
        </div>
        {typeof safe.summary === 'string' && safe.summary && (
          <p className="text-xs text-gray-600">{safe.summary as string}</p>
        )}
        {typeof safe.reasoning === 'string' && safe.reasoning && (
          <p className="text-xs text-gray-500 italic">{safe.reasoning as string}</p>
        )}
        {findings.length > 0 && (
          <ul className="text-xs text-gray-500 space-y-0.5 pl-3">
            {findings.slice(0, 4).map((f, i) => <li key={i} className="list-disc">{f}</li>)}
          </ul>
        )}
      </div>
    );
  }

  // HTTP node — status code + summary
  if (safe.status_code !== undefined) {
    const ok = safe.success as boolean;
    return (
      <div className="space-y-1 mt-1">
        <div className="flex items-center gap-2">
          <span className={`text-xs font-mono font-bold px-2 py-0.5 rounded ${ok ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
            {safe.status_code as number}
          </span>
          <span className="text-xs text-gray-500 font-mono">{safe.method as string} {safe.url as string}</span>
        </div>
        {safe.response !== undefined && (
          <p className="text-xs text-gray-500 font-mono truncate">
            {typeof safe.response === 'object'
              ? `{${Object.keys(safe.response as object).slice(0, 3).join(', ')}${Object.keys(safe.response as object).length > 3 ? '…' : ''}}`
              : String(safe.response).slice(0, 80)}
          </p>
        )}
      </div>
    );
  }

  // Transform node
  if (safe.transformed !== undefined) {
    const keys = typeof safe.transformed === 'object' && safe.transformed !== null
      ? Object.keys(safe.transformed as object) : [];
    return (
      <p className="text-xs text-gray-600 mt-1">
        Mode: {safe.mode as string} · Output keys: {keys.length > 0 ? keys.join(', ') : '(empty)'}
      </p>
    );
  }

  // Rule Engine node
  if (safe.passed !== undefined && safe.matched_rules !== undefined) {
    const passed = safe.passed as boolean;
    const matched = Array.isArray(safe.matched_rules) ? safe.matched_rules as string[] : [];
    const failed = Array.isArray(safe.failed_rules) ? safe.failed_rules as string[] : [];
    return (
      <div className="space-y-1 mt-1">
        <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${passed ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
          {passed ? '✓ Pass' : '✗ Fail'} · {safe.combine_mode as string}
        </span>
        {matched.length > 0 && <p className="text-xs text-green-600">Matched: {matched.join(', ')}</p>}
        {failed.length > 0 && <p className="text-xs text-red-600">Failed: {failed.join(', ')}</p>}
      </div>
    );
  }

  // Code Runner node
  if (safe.output !== undefined && safe.executed !== undefined) {
    return (
      <div className="mt-1">
        <p className="text-xs text-gray-500 font-mono">
          {typeof safe.output === 'object'
            ? JSON.stringify(safe.output).slice(0, 120)
            : String(safe.output).slice(0, 120)}
        </p>
      </div>
    );
  }

  // Validator node
  if (safe.valid !== undefined && safe.errors !== undefined) {
    const valid = safe.valid as boolean;
    const errors = Array.isArray(safe.errors) ? safe.errors as string[] : [];
    return (
      <div className="space-y-1 mt-1">
        <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${valid ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
          {valid ? `✓ Valid (${(safe.passed_rules as number) ?? 0} checks passed)` : `✗ Invalid`}
        </span>
        {errors.map((e, i) => <p key={i} className="text-xs text-red-600">{e}</p>)}
      </div>
    );
  }

  // Switch Router node
  if (safe.routed_to !== undefined) {
    return (
      <p className="text-xs text-gray-600 mt-1 font-mono">
        Routed → <span className="font-bold text-violet-700">{safe.routed_to as string}</span>
        {safe.switch_value !== undefined && <span className="text-gray-400"> (value: {String(safe.switch_value).slice(0, 30)})</span>}
      </p>
    );
  }

  // Formatter node
  if (safe.rendered !== undefined) {
    return (
      <div className="mt-1">
        <p className="text-xs text-gray-400 mb-0.5">Format: {safe.output_format as string}</p>
        <p className="text-xs text-gray-600 bg-gray-100 rounded p-1.5 font-mono whitespace-pre-wrap leading-relaxed">
          {String(safe.rendered).slice(0, 200)}{String(safe.rendered).length > 200 ? '…' : ''}
        </p>
      </div>
    );
  }

  // Aggregator node
  if (safe.operation !== undefined && safe.result !== undefined) {
    return (
      <p className="text-xs text-gray-600 mt-1 font-mono">
        {safe.operation as string}({safe.source_field as string || ''}) = <span className="font-bold text-sky-700">
          {typeof safe.result === 'object' ? JSON.stringify(safe.result).slice(0, 80) : String(safe.result)}
        </span>
        {safe.item_count !== undefined && <span className="text-gray-400 ml-2">[{safe.item_count as number} items]</span>}
      </p>
    );
  }

  // All other nodes — compact text
  const parts: string[] = [];
  if (typeof safe.result === 'string') parts.push(safe.result);
  if (safe.verification_type) parts.push(`Type: ${safe.verification_type as string}`);
  if (safe.confidence !== undefined)
    parts.push(`Confidence: ${((safe.confidence as number) * 100).toFixed(0)}%`);
  if (typeof safe.analysis === 'string' && safe.analysis) parts.push(safe.analysis);
  if (!parts.length) {
    const inputs = safe.inputs;
    if (inputs && typeof inputs === 'object') {
      parts.push(`Fields: ${Object.keys(inputs as object).join(', ')}`);
    }
  }

  return parts.length
    ? <p className="text-xs text-gray-600 leading-relaxed mt-1">{parts.join(' · ')}</p>
    : null;
}
