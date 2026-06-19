import type { ReactNode } from 'react';
import { useWorkflowStore } from '@/store/workflowStore';
import { InputField } from '@/types/workflow';
import { X, Plus } from 'lucide-react';

// ── Type helpers ───────────────────────────────────────────────────────────────
type Row = Record<string, string>;

function getFields(data: Record<string, unknown>): InputField[] {
  if (Array.isArray(data.fields) && data.fields.length > 0) return data.fields as InputField[];
  return [{ id: 'default', name: 'input', type: (data.inputType as InputField['type']) || 'text' }];
}
const asRows = (key: string, data: Record<string, unknown>): Row[] =>
  Array.isArray(data[key]) ? (data[key] as Row[]) : [];

// ── Reusable sub-components ────────────────────────────────────────────────────
const lbl = 'block text-sm font-medium text-gray-700 mb-1';
const inp = (ring = 'focus:ring-blue-500') =>
  `w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 ${ring} text-sm`;
const mono = 'font-mono text-xs';

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <label className={lbl}>{label}</label>
      {children}
    </div>
  );
}

function Select({
  value, onChange, ring = 'focus:ring-blue-500', children,
}: { value: string; onChange: (v: string) => void; ring?: string; children: React.ReactNode }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)}
      className={inp(ring)}>
      {children}
    </select>
  );
}

function TextArea({
  value, onChange, rows = 3, placeholder = '', ring = 'focus:ring-blue-500', extraClass = '',
}: { value: string; onChange: (v: string) => void; rows?: number; placeholder?: string; ring?: string; extraClass?: string }) {
  return (
    <textarea value={value} onChange={e => onChange(e.target.value)}
      rows={rows} placeholder={placeholder}
      className={`${inp(ring)} resize-none ${extraClass}`} />
  );
}

function AddRowButton({ label, ring, onClick }: { label: string; ring: string; onClick: () => void }) {
  return (
    <button onClick={onClick}
      className={`flex items-center gap-1 text-xs font-medium ${ring.replace('focus:ring-', 'text-').replace('500', '600')} hover:opacity-80`}>
      <Plus className="w-3.5 h-3.5" />{label}
    </button>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────
export function NodePropertiesPanel() {
  const { selectedNode, updateNodeData, setSelectedNode } = useWorkflowStore();
  if (!selectedNode) return null;

  const data = selectedNode.data as Record<string, unknown>;
  const up = (field: string, value: unknown) => updateNodeData(selectedNode.id, { [field]: value });

  const ringMap: Record<string, string> = {
    inputNode: 'focus:ring-blue-500', aiNode: 'focus:ring-purple-500',
    verificationNode: 'focus:ring-green-500', decisionNode: 'focus:ring-yellow-500',
    outputNode: 'focus:ring-indigo-500', httpNode: 'focus:ring-orange-500',
    transformNode: 'focus:ring-teal-500', humanReviewNode: 'focus:ring-rose-500',
    ruleNode: 'focus:ring-amber-500', codeNode: 'focus:ring-zinc-500',
    validatorNode: 'focus:ring-emerald-500', switchNode: 'focus:ring-violet-500',
    formatterNode: 'focus:ring-lime-600', aggregatorNode: 'focus:ring-sky-500',
    indianKycNode: 'focus:ring-fuchsia-500',
  };
  const ring = ringMap[selectedNode.type || ''] || 'focus:ring-blue-500';
  const fi = inp(ring);

  // ── inputNode helpers ──────────────────────────────────────────────────────
  const fields = getFields(data);
  const setField = (idx: number, patch: Partial<InputField>) =>
    up('fields', fields.map((f, i) => i === idx ? { ...f, ...patch } : f));

  // ── httpNode helpers ───────────────────────────────────────────────────────
  const headers = asRows('headers', data);
  const setHeader = (idx: number, patch: Row) =>
    up('headers', headers.map((h, i) => i === idx ? { ...h, ...patch } : h));

  // ── transformNode helpers ──────────────────────────────────────────────────
  const mappings = asRows('fieldMappings', data);
  const setMapping = (idx: number, patch: Row) =>
    up('fieldMappings', mappings.map((m, i) => i === idx ? { ...m, ...patch } : m));

  // ── ruleNode helpers ───────────────────────────────────────────────────────
  const rules = asRows('rules', data);
  const setRule = (idx: number, patch: Row) =>
    up('rules', rules.map((r, i) => i === idx ? { ...r, ...patch } : r));

  // ── validatorNode helpers ──────────────────────────────────────────────────
  const valRules = asRows('validationRules', data);
  const setValRule = (idx: number, patch: Row) =>
    up('validationRules', valRules.map((r, i) => i === idx ? { ...r, ...patch } : r));

  // ── switchNode helpers ─────────────────────────────────────────────────────
  const cases = asRows('cases', data);
  const setCase = (idx: number, patch: Row) =>
    up('cases', cases.map((c, i) => i === idx ? { ...c, ...patch } : c));

  const t = selectedNode.type;

  return (
    <div className="absolute right-4 top-4 w-80 bg-white rounded-lg shadow-xl border border-gray-200 z-10">
      <div className="flex items-center justify-between p-4 border-b border-gray-200">
        <h3 className="font-semibold text-lg">Node Properties</h3>
        <button onClick={() => setSelectedNode(null)} className="p-1 hover:bg-gray-100 rounded">
          <X className="w-5 h-5" />
        </button>
      </div>

      <div className="p-4 space-y-4 max-h-[82vh] overflow-y-auto">

        {/* ── Universal ── */}
        <Field label="Label">
          <input type="text" value={(data.label as string) || ''} onChange={e => up('label', e.target.value)} className={fi} />
        </Field>
        <Field label="Description">
          <TextArea value={(data.description as string) || ''} onChange={v => up('description', v)} rows={2} ring={ring} />
        </Field>

        {/* ═══════════════════ INPUT NODE ═══════════════════ */}
        {t === 'inputNode' && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className={lbl}>API Fields</label>
              <AddRowButton label="Add Field" ring={ring}
                onClick={() => up('fields', [...fields, { id: `f_${Date.now()}`, name: '', type: 'text' }])} />
            </div>
            <div className="space-y-2">
              {fields.map((field, idx) => (
                <div key={field.id} className="flex gap-2 items-center">
                  <input type="text" placeholder="field_name" value={field.name}
                    onChange={e => setField(idx, { name: e.target.value })}
                    className={`flex-1 px-2 py-1.5 text-sm border border-gray-300 rounded-md ${ring} focus:outline-none focus:ring-2 font-mono min-w-0`} />
                  <select value={field.type} onChange={e => setField(idx, { type: e.target.value as InputField['type'] })}
                    className="px-2 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none flex-shrink-0">
                    <option value="text">text</option>
                    <option value="file">file</option>
                    <option value="number">number</option>
                    <option value="json">json</option>
                  </select>
                  <button onClick={() => up('fields', fields.filter((_, i) => i !== idx))}
                    disabled={fields.length === 1}
                    className="text-gray-400 hover:text-red-500 flex-shrink-0 disabled:opacity-30">
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
            <p className="text-xs text-gray-400 mt-2">Field names become JSON keys in the trigger API body.</p>
          </div>
        )}

        {/* ═══════════════════ AI NODE ═══════════════════ */}
        {t === 'aiNode' && (
          <>
            <Field label="AI Task">
              <Select value={(data.aiTask as string) || 'reasoning'} onChange={v => up('aiTask', v)} ring={ring}>
                <option value="reasoning">Reasoning & Analysis</option>
                <option value="extraction">Data Extraction</option>
                <option value="classification">Classification</option>
                <option value="verification">Verification</option>
                <option value="fraud_detection">Fraud Detection</option>
                <option value="summarization">Summarization</option>
                <option value="translation">Translation</option>
              </Select>
            </Field>
            <Field label="Output Format">
              <Select value={(data.outputFormat as string) || 'text'} onChange={v => up('outputFormat', v)} ring={ring}>
                <option value="text">Text (default)</option>
                <option value="json">JSON (auto-parsed)</option>
                <option value="markdown">Markdown</option>
                <option value="csv">CSV</option>
                <option value="html">HTML</option>
                <option value="table">Markdown Table</option>
                <option value="bullet_list">Bullet List</option>
                <option value="custom_schema">Custom JSON Schema</option>
              </Select>
            </Field>
            {data.outputFormat === 'custom_schema' && (
              <Field label="JSON Schema (the model must match this exactly)">
                <TextArea
                  value={(data.outputSchema as string) || '{}'}
                  onChange={v => up('outputSchema', v)}
                  rows={5} ring={ring}
                  extraClass={mono}
                  placeholder={'{\n  "name": "string",\n  "score": "number"\n}'}
                />
              </Field>
            )}
            <div>
              <label className={lbl}>
                Temperature: <span className="font-mono text-purple-700">{(data.temperature as number) ?? 0.7}</span>
              </label>
              <input type="range" min="0" max="2" step="0.1"
                value={(data.temperature as number) ?? 0.7}
                onChange={e => up('temperature', parseFloat(e.target.value))}
                className="w-full accent-purple-600" />
              <div className="flex justify-between text-xs text-gray-400 mt-0.5">
                <span>Precise (0)</span><span>Balanced (0.7)</span><span>Creative (2)</span>
              </div>
            </div>
            <Field label="Custom Prompt">
              <TextArea value={(data.prompt as string) || ''} onChange={v => up('prompt', v)}
                rows={4} placeholder="Enter custom instructions for the AI agent…" ring={ring} />
            </Field>
          </>
        )}

        {/* ═══════════════════ VERIFICATION NODE ═══════════════════ */}
        {t === 'verificationNode' && (
          <Field label="Verification Type">
            <Select value={(data.verificationType as string) || 'consistency'} onChange={v => up('verificationType', v)} ring={ring}>
              <option value="consistency">Consistency Check</option>
              <option value="compliance">Compliance Check</option>
              <option value="signature">Signature Verification</option>
              <option value="document">Document Verification</option>
              <option value="completeness">Completeness Check</option>
              <option value="pii_detection">PII Detection</option>
            </Select>
          </Field>
        )}

        {/* ═══════════════════ DECISION NODE ═══════════════════ */}
        {t === 'decisionNode' && (
          <>
            <Field label="Condition Type">
              <Select value={(data.conditionType as string) || 'threshold'} onChange={v => up('conditionType', v)} ring={ring}>
                <option value="threshold">Confidence Threshold</option>
                <option value="compliance">Compliance Check</option>
                <option value="risk">Risk Assessment</option>
                <option value="rule">Rule-Based</option>
              </Select>
            </Field>
            <Field label="Approval Threshold (0–1)">
              <input type="number" min="0" max="1" step="0.05"
                value={(data.threshold as number) ?? 0.8}
                onChange={e => up('threshold', parseFloat(e.target.value))}
                className={fi} />
            </Field>
            <Field label="Decision Prompt">
              <TextArea value={(data.prompt as string) || ''} onChange={v => up('prompt', v)}
                rows={3} ring={ring}
                placeholder="e.g. Approve only if identity document is valid and all required fields are present." />
              <p className="text-xs text-gray-400 mt-1">Guide the AI. Routes via ✓ Approved / ✗ Rejected handles.</p>
            </Field>
          </>
        )}

        {/* ═══════════════════ OUTPUT NODE ═══════════════════ */}
        {t === 'outputNode' && (
          <>
            <Field label="Output Type">
              <Select value={(data.outputType as string) || 'api'} onChange={v => up('outputType', v)} ring={ring}>
                <option value="api">API Response</option>
                <option value="database">Database Write</option>
                <option value="notification">Notification</option>
                <option value="report">Report</option>
                <option value="webhook">Webhook Delivery</option>
                <option value="slack">Slack Message</option>
                <option value="email">Email</option>
              </Select>
            </Field>
            {(data.outputType === 'webhook' || data.outputType === 'slack') && (
              <Field label="Delivery URL">
                <input type="url" value={(data.deliveryUrl as string) || ''}
                  onChange={e => up('deliveryUrl', e.target.value)}
                  placeholder="https://hooks.example.com/…" className={fi} />
              </Field>
            )}
          </>
        )}

        {/* ═══════════════════ HTTP NODE ═══════════════════ */}
        {t === 'httpNode' && (
          <>
            <div className="flex gap-2">
              <div className="w-28 flex-shrink-0">
                <Field label="Method">
                  <Select value={(data.method as string) || 'GET'} onChange={v => up('method', v)} ring={ring}>
                    {['GET','POST','PUT','PATCH','DELETE'].map(m => <option key={m}>{m}</option>)}
                  </Select>
                </Field>
              </div>
              <div className="flex-1 min-w-0">
                <Field label="Timeout (s)">
                  <input type="number" min="1" max="300"
                    value={(data.timeout as number) ?? 30}
                    onChange={e => up('timeout', parseInt(e.target.value, 10))}
                    className={fi} />
                </Field>
              </div>
            </div>
            <Field label="URL">
              <input type="text" value={(data.url as string) || ''}
                onChange={e => up('url', e.target.value)}
                placeholder="https://api.example.com/{{customer_id}}"
                className={`${fi} ${mono}`} />
              <p className="text-xs text-gray-400 mt-1">{'{{field}}'} injects values from previous node output.</p>
            </Field>
            <Field label="Authentication">
              <Select value={(data.authType as string) || 'none'} onChange={v => up('authType', v)} ring={ring}>
                <option value="none">None</option>
                <option value="bearer">Bearer Token</option>
                <option value="apikey">API Key Header</option>
              </Select>
            </Field>
            {(data.authType === 'bearer' || data.authType === 'apikey') && (
              <>
                {data.authType === 'apikey' && (
                  <Field label="Header Name">
                    <input type="text" value={(data.authHeader as string) || 'X-API-Key'}
                      onChange={e => up('authHeader', e.target.value)} className={`${fi} ${mono}`} />
                  </Field>
                )}
                <Field label={data.authType === 'bearer' ? 'Bearer Token' : 'API Key Value'}>
                  <input type="password" value={(data.authValue as string) || ''}
                    onChange={e => up('authValue', e.target.value)} placeholder="••••••••" className={fi} />
                </Field>
              </>
            )}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className={lbl}>Headers</label>
                <AddRowButton label="Add" ring={ring}
                  onClick={() => up('headers', [...headers, { id: `h_${Date.now()}`, key: '', value: '' }])} />
              </div>
              <div className="space-y-1.5">
                {headers.map((h, idx) => (
                  <div key={h.id} className="flex gap-1.5 items-center">
                    <input type="text" placeholder="Name" value={h.key}
                      onChange={e => setHeader(idx, { ...h, key: e.target.value })}
                      className={`flex-1 px-2 py-1.5 text-xs border border-gray-300 rounded-md ${ring} focus:outline-none focus:ring-2 font-mono min-w-0`} />
                    <input type="text" placeholder="value" value={h.value}
                      onChange={e => setHeader(idx, { ...h, value: e.target.value })}
                      className="flex-1 px-2 py-1.5 text-xs border border-gray-300 rounded-md focus:outline-none min-w-0" />
                    <button onClick={() => up('headers', headers.filter((_, i) => i !== idx))} className="text-gray-400 hover:text-red-500 flex-shrink-0">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
                {headers.length === 0 && <p className="text-xs text-gray-400 italic">No custom headers.</p>}
              </div>
            </div>
            {['POST','PUT','PATCH'].includes((data.method as string) || 'GET') && (
              <Field label="Request Body (JSON template)">
                <TextArea value={(data.bodyTemplate as string) || ''} onChange={v => up('bodyTemplate', v)}
                  rows={4} ring={ring} extraClass={mono}
                  placeholder={'{\n  "id": "{{customer_id}}"\n}'} />
              </Field>
            )}
          </>
        )}

        {/* ═══════════════════ TRANSFORM NODE ═══════════════════ */}
        {t === 'transformNode' && (
          <>
            <Field label="Transform Mode">
              <Select value={(data.transformMode as string) || 'field_map'} onChange={v => up('transformMode', v)} ring={ring}>
                <option value="field_map">Field Map (rename / pick)</option>
                <option value="template">Template (JSON with {'{{vars}}'})</option>
                <option value="filter">Filter (keep keys)</option>
              </Select>
            </Field>
            {(!data.transformMode || data.transformMode === 'field_map') && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className={lbl}>Field Mappings</label>
                  <AddRowButton label="Add" ring={ring}
                    onClick={() => up('fieldMappings', [...mappings, { id: `m_${Date.now()}`, from: '', to: '' }])} />
                </div>
                <div className="space-y-1.5">
                  {mappings.map((m, idx) => (
                    <div key={m.id} className="flex gap-1.5 items-center">
                      <input type="text" placeholder="from" value={m.from}
                        onChange={e => setMapping(idx, { ...m, from: e.target.value })}
                        className={`flex-1 px-2 py-1.5 text-xs border border-gray-300 rounded-md ${ring} focus:outline-none focus:ring-2 font-mono min-w-0`} />
                      <span className="text-gray-400 text-xs flex-shrink-0">→</span>
                      <input type="text" placeholder="to" value={m.to}
                        onChange={e => setMapping(idx, { ...m, to: e.target.value })}
                        className={`flex-1 px-2 py-1.5 text-xs border border-gray-300 rounded-md ${ring} focus:outline-none focus:ring-2 font-mono min-w-0`} />
                      <button onClick={() => up('fieldMappings', mappings.filter((_, i) => i !== idx))} className="text-gray-400 hover:text-red-500 flex-shrink-0">
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                  {mappings.length === 0 && <p className="text-xs text-gray-400 italic">Supports dot notation (e.g. user.name).</p>}
                </div>
              </div>
            )}
            {data.transformMode === 'template' && (
              <Field label="JSON Template">
                <TextArea value={(data.template as string) || '{}'}
                  onChange={v => up('template', v)} rows={6} ring={ring} extraClass={mono}
                  placeholder={'{\n  "userId": "{{id}}",\n  "name": "{{full_name}}"\n}'} />
                <p className="text-xs text-gray-400 mt-1">{'{{key}}'} pulls values from previous node output.</p>
              </Field>
            )}
            {data.transformMode === 'filter' && (
              <Field label="Keys to Keep (comma-separated)">
                <input type="text" value={(data.filterKeys as string) || ''}
                  onChange={e => up('filterKeys', e.target.value)}
                  placeholder="customer_id, full_name, score" className={fi} />
              </Field>
            )}
          </>
        )}

        {/* ═══════════════════ HUMAN REVIEW NODE ═══════════════════ */}
        {t === 'humanReviewNode' && (
          <>
            <Field label="Review Instructions">
              <TextArea value={(data.reviewPrompt as string) || ''} onChange={v => up('reviewPrompt', v)}
                rows={4} ring={ring}
                placeholder="Please review the extracted data and verify it is correct before approval." />
            </Field>
            <p className="text-xs text-rose-600 bg-rose-50 p-2 rounded">
              Workflow pauses here. The previous node's output is surfaced for review.
            </p>
          </>
        )}

        {/* ═══════════════════ RULE ENGINE NODE ═══════════════════ */}
        {t === 'ruleNode' && (
          <>
            <Field label="Combine Mode">
              <Select value={(data.combineMode as string) || 'AND'} onChange={v => up('combineMode', v)} ring={ring}>
                <option value="AND">AND — all rules must pass</option>
                <option value="OR">OR — any rule must pass</option>
              </Select>
            </Field>
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className={lbl}>Rules</label>
                <AddRowButton label="Add Rule" ring={ring}
                  onClick={() => up('rules', [...rules, { id: `r_${Date.now()}`, field: '', operator: 'eq', value: '', label: '' }])} />
              </div>
              <div className="space-y-3">
                {rules.map((rule, idx) => (
                  <div key={rule.id} className="border border-amber-100 rounded-lg p-2 space-y-1.5 bg-amber-50/40">
                    <div className="flex gap-1.5 items-center">
                      <input type="text" placeholder="field.name" value={rule.field}
                        onChange={e => setRule(idx, { ...rule, field: e.target.value })}
                        className={`flex-1 px-2 py-1.5 text-xs border border-gray-300 rounded-md font-mono ${ring} focus:outline-none focus:ring-2 min-w-0`} />
                      <button onClick={() => up('rules', rules.filter((_, i) => i !== idx))} className="text-gray-400 hover:text-red-500 flex-shrink-0">
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    <select value={rule.operator}
                      onChange={e => setRule(idx, { ...rule, operator: e.target.value })}
                      className="w-full px-2 py-1.5 text-xs border border-gray-300 rounded-md focus:outline-none">
                      <optgroup label="Equality">
                        <option value="eq">= equals</option>
                        <option value="neq">≠ not equals</option>
                      </optgroup>
                      <optgroup label="Numeric">
                        <option value="gt">&gt; greater than</option>
                        <option value="gte">≥ greater or equal</option>
                        <option value="lt">&lt; less than</option>
                        <option value="lte">≤ less or equal</option>
                        <option value="between">between (val1,val2)</option>
                      </optgroup>
                      <optgroup label="Text">
                        <option value="contains">contains</option>
                        <option value="not_contains">does not contain</option>
                        <option value="starts_with">starts with</option>
                        <option value="ends_with">ends with</option>
                        <option value="regex">regex match</option>
                      </optgroup>
                      <optgroup label="List">
                        <option value="in_list">in list (a,b,c)</option>
                        <option value="not_in_list">not in list</option>
                      </optgroup>
                      <optgroup label="Existence">
                        <option value="exists">exists</option>
                        <option value="not_exists">does not exist</option>
                        <option value="is_empty">is empty</option>
                        <option value="is_not_empty">is not empty</option>
                      </optgroup>
                    </select>
                    {!['exists','not_exists','is_empty','is_not_empty'].includes(rule.operator) && (
                      <input type="text" placeholder="value" value={rule.value}
                        onChange={e => setRule(idx, { ...rule, value: e.target.value })}
                        className={`w-full px-2 py-1.5 text-xs border border-gray-300 rounded-md font-mono ${ring} focus:outline-none focus:ring-2`} />
                    )}
                    <input type="text" placeholder="Label (optional)" value={rule.label || ''}
                      onChange={e => setRule(idx, { ...rule, label: e.target.value })}
                      className="w-full px-2 py-1.5 text-xs border border-gray-200 rounded-md text-gray-500 focus:outline-none" />
                  </div>
                ))}
                {rules.length === 0 && <p className="text-xs text-gray-400 italic">No rules yet. Add one above.</p>}
              </div>
              <p className="text-xs text-gray-400 mt-2">Routes via ✓ pass / ✗ fail handles.</p>
            </div>
          </>
        )}

        {/* ═══════════════════ CODE NODE ═══════════════════ */}
        {t === 'codeNode' && (
          <>
            <Field label="Python Code">
              <TextArea value={(data.code as string) || 'output = input_data'}
                onChange={v => up('code', v)} rows={10} ring={ring} extraClass={mono}
                placeholder={'# input_data = previous node output\n# assign to `output` to return data\n\noutput = input_data'} />
              <p className="text-xs text-gray-400 mt-1">
                Available: <span className="font-mono">json, re, math, datetime</span>. Set <span className="font-mono">output = ...</span> to return.
              </p>
            </Field>
            <Field label="Timeout (seconds)">
              <input type="number" min="1" max="60"
                value={(data.timeout as number) ?? 10}
                onChange={e => up('timeout', parseInt(e.target.value, 10))} className={fi} />
            </Field>
          </>
        )}

        {/* ═══════════════════ VALIDATOR NODE ═══════════════════ */}
        {t === 'validatorNode' && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className={lbl}>Validation Rules</label>
              <AddRowButton label="Add Rule" ring={ring}
                onClick={() => up('validationRules', [...valRules, { id: `v_${Date.now()}`, field: '', required: 'false', fieldType: '', pattern: '', min: '', max: '', minLength: '', maxLength: '', enum: '' }])} />
            </div>
            <div className="space-y-3">
              {valRules.map((rule, idx) => (
                <div key={rule.id} className="border border-emerald-100 rounded-lg p-2.5 space-y-2 bg-emerald-50/30">
                  <div className="flex gap-1.5 items-center">
                    <input type="text" placeholder="field.name" value={rule.field}
                      onChange={e => setValRule(idx, { ...rule, field: e.target.value })}
                      className={`flex-1 px-2 py-1.5 text-xs border border-gray-300 rounded-md font-mono ${ring} focus:outline-none focus:ring-2`} />
                    <button onClick={() => up('validationRules', valRules.filter((_, i) => i !== idx))} className="text-gray-400 hover:text-red-500 flex-shrink-0">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <div className="flex gap-2">
                    <select value={rule.fieldType || ''}
                      onChange={e => setValRule(idx, { ...rule, fieldType: e.target.value })}
                      className="flex-1 px-2 py-1.5 text-xs border border-gray-300 rounded-md focus:outline-none">
                      <option value="">any type</option>
                      <option value="string">string</option>
                      <option value="number">number</option>
                      <option value="boolean">boolean</option>
                      <option value="array">array</option>
                      <option value="object">object</option>
                    </select>
                    <label className="flex items-center gap-1 text-xs text-gray-600 whitespace-nowrap">
                      <input type="checkbox" checked={rule.required === 'true'}
                        onChange={e => setValRule(idx, { ...rule, required: e.target.checked ? 'true' : 'false' })} />
                      Required
                    </label>
                  </div>
                  <div className="grid grid-cols-2 gap-1.5">
                    {[['pattern','Regex pattern'],['min','Min value'],['max','Max value'],['minLength','Min length'],['maxLength','Max length'],['enum','Allowed values (a,b)']].map(([k,ph]) => (
                      <input key={k} type="text" placeholder={ph} value={rule[k] || ''}
                        onChange={e => setValRule(idx, { ...rule, [k]: e.target.value })}
                        className={`px-2 py-1.5 text-xs border border-gray-300 rounded-md ${k === 'enum' || k === 'pattern' ? 'col-span-2' : ''} focus:outline-none`} />
                    ))}
                  </div>
                </div>
              ))}
              {valRules.length === 0 && <p className="text-xs text-gray-400 italic">No validation rules yet.</p>}
            </div>
            <p className="text-xs text-gray-400 mt-2">Validation failure halts the workflow with an error.</p>
          </div>
        )}

        {/* ═══════════════════ SWITCH NODE ═══════════════════ */}
        {t === 'switchNode' && (
          <>
            <Field label="Switch Field">
              <input type="text" value={(data.switchField as string) || ''}
                onChange={e => up('switchField', e.target.value)}
                placeholder="document_type" className={`${fi} font-mono`} />
              <p className="text-xs text-gray-400 mt-1">Dot notation supported (e.g. data.category). Use | for OR values.</p>
            </Field>
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className={lbl}>Cases</label>
                <AddRowButton label="Add Case" ring={ring}
                  onClick={() => {
                    const idx = cases.length;
                    up('cases', [...cases, { id: `c_${Date.now()}`, matchValue: '', handle: `case_${idx}`, label: '' }]);
                  }} />
              </div>
              <div className="space-y-2">
                {cases.map((c, idx) => (
                  <div key={c.id} className="flex gap-1.5 items-center">
                    <input type="text" placeholder="match value (or a|b)" value={c.matchValue || ''}
                      onChange={e => setCase(idx, { ...c, matchValue: e.target.value })}
                      className={`flex-1 px-2 py-1.5 text-xs border border-gray-300 rounded-md font-mono ${ring} focus:outline-none focus:ring-2 min-w-0`} />
                    <span className="text-gray-400 text-xs flex-shrink-0">→</span>
                    <input type="text" placeholder="label" value={c.label || ''}
                      onChange={e => setCase(idx, { ...c, label: e.target.value })}
                      className="w-16 px-2 py-1.5 text-xs border border-gray-300 rounded-md focus:outline-none min-w-0" />
                    <button onClick={() => up('cases', cases.filter((_, i) => i !== idx))} className="text-gray-400 hover:text-red-500 flex-shrink-0">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
                {cases.length === 0 && <p className="text-xs text-gray-400 italic">No cases yet. Add one above.</p>}
              </div>
              <p className="text-xs text-gray-400 mt-2">Unmatched values route via the <span className="font-mono">default</span> handle.</p>
            </div>
          </>
        )}

        {/* ═══════════════════ FORMATTER NODE ═══════════════════ */}
        {t === 'formatterNode' && (
          <>
            <Field label="Output Format">
              <Select value={(data.outputFormat as string) || 'text'} onChange={v => up('outputFormat', v)} ring={ring}>
                <option value="text">Plain Text</option>
                <option value="html">HTML</option>
                <option value="markdown">Markdown</option>
                <option value="email">Email Body</option>
                <option value="slack">Slack Message</option>
              </Select>
            </Field>
            {(data.outputFormat === 'email' || data.outputFormat === 'slack') && (
              <Field label="Subject / Title Template">
                <input type="text" value={(data.subjectTemplate as string) || ''}
                  onChange={e => up('subjectTemplate', e.target.value)}
                  placeholder="Action required: {{customer_id}}" className={fi} />
              </Field>
            )}
            <Field label="Body Template">
              <TextArea value={(data.template as string) || ''}
                onChange={v => up('template', v)} rows={8} ring={ring}
                placeholder={'Hello {{full_name}},\n\nYour application {{customer_id}} has been {{decision}}.\n\nScore: {{confidence}}'} />
              <p className="text-xs text-gray-400 mt-1">{'{{field}}'} is replaced with values from previous node output.</p>
            </Field>
          </>
        )}

        {/* ═══════════════════ AGGREGATOR NODE ═══════════════════ */}
        {t === 'aggregatorNode' && (
          <>
            <Field label="Source Array Field">
              <input type="text" value={(data.sourceField as string) || ''}
                onChange={e => up('sourceField', e.target.value)}
                placeholder="items (dot notation supported)" className={`${fi} font-mono`} />
              <p className="text-xs text-gray-400 mt-1">Leave blank to use the first array value found.</p>
            </Field>
            <Field label="Operation">
              <Select value={(data.operation as string) || 'count'} onChange={v => up('operation', v)} ring={ring}>
                <optgroup label="Count">
                  <option value="count">count — total items</option>
                </optgroup>
                <optgroup label="Numeric">
                  <option value="sum">sum</option>
                  <option value="avg">avg (mean)</option>
                  <option value="min">min</option>
                  <option value="max">max</option>
                </optgroup>
                <optgroup label="Array">
                  <option value="first">first item</option>
                  <option value="last">last item</option>
                  <option value="join">join (string)</option>
                  <option value="unique">unique values</option>
                  <option value="group_by">group by field</option>
                </optgroup>
              </Select>
            </Field>
            {['sum','avg','min','max','join','unique'].includes((data.operation as string) || '') && (
              <Field label="Value Field (within each item)">
                <input type="text" value={(data.valueField as string) || ''}
                  onChange={e => up('valueField', e.target.value)}
                  placeholder="amount (blank = whole item)" className={`${fi} font-mono`} />
              </Field>
            )}
            {data.operation === 'group_by' && (
              <Field label="Group By Field">
                <input type="text" value={(data.groupBy as string) || ''}
                  onChange={e => up('groupBy', e.target.value)}
                  placeholder="category" className={`${fi} font-mono`} />
              </Field>
            )}
            {data.operation === 'join' && (
              <Field label="Separator">
                <input type="text" value={(data.separator as string) ?? ', '}
                  onChange={e => up('separator', e.target.value)}
                  placeholder=", " className={fi} />
              </Field>
            )}
          </>
        )}

        {/* ═══════════════════ INDIAN KYC NODE ═══════════════════ */}
        {t === 'indianKycNode' && (
          <>
            <Field label="Document Type">
              <Select value={(data.documentType as string) || 'pan'} onChange={v => up('documentType', v)} ring={ring}>
                <option value="pan">PAN Card</option>
                <option value="aadhaar">Aadhaar Card</option>
                <option value="voter_id">Voter ID (EPIC)</option>
                <option value="driving_license">Driving License</option>
                <option value="passport">Passport</option>
              </Select>
            </Field>
            <Field label="KYC Provider">
              <Select value={(data.provider as string) || 'surepass'} onChange={v => up('provider', v)} ring={ring}>
                <option value="surepass">Surepass</option>
                <option value="idfy">IDfy</option>
                <option value="sandbox">Sandbox.co.in</option>
                <option value="karza">Karza</option>
                <option value="custom">Custom Endpoint</option>
              </Select>
            </Field>
            {data.provider === 'custom' && (
              <Field label="Custom API Endpoint">
                <input type="text" value={(data.customEndpoint as string) || ''}
                  onChange={e => up('customEndpoint', e.target.value)}
                  placeholder="https://api.example.com/kyc/verify" className={`${fi} font-mono`} />
              </Field>
            )}
            <Field label="API Key">
              <input type="password" value={(data.apiKey as string) || ''}
                onChange={e => up('apiKey', e.target.value)}
                placeholder="••••••••" className={fi} />
              <p className="text-xs text-gray-400 mt-1">Your {(data.provider as string) || 'provider'} API key.</p>
            </Field>
            <Field label="Document Number Field">
              <input type="text" value={(data.documentField as string) || 'document_number'}
                onChange={e => up('documentField', e.target.value)}
                placeholder="document_number" className={`${fi} font-mono`} />
              <p className="text-xs text-gray-400 mt-1">
                Field path in the previous node&apos;s output containing the document number. Dot notation supported.
              </p>
            </Field>
            <div className="text-xs text-fuchsia-700 bg-fuchsia-50 p-2 rounded border border-fuchsia-100 space-y-1">
              <p className="font-medium">Verified output fields:</p>
              <p className="font-mono text-fuchsia-600">verified, document_type, document_number, kyc_data.name, kyc_data.dob, kyc_data.address, raw_response</p>
            </div>
          </>
        )}

      </div>
    </div>
  );
}
