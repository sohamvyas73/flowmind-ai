import { useEffect, useMemo, useState } from 'react';
import type { Node } from 'reactflow';
import { AlertTriangle, Lightbulb, Plus, Trash2 } from 'lucide-react';
import { useWorkflowStore } from '@/store/workflowStore';
import { useAuthStore } from '@/store/authStore';
import { connectionsApi, dataApi, mlApi, Connection, DataFile } from '@/services/api';
import { Field, Select, inp } from './NodePropertiesPanel';

type Data = Record<string, unknown>;
type Up = (k: string, v: unknown) => void;
const ring = 'focus:ring-emerald-500';
const arr = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);

const Tip = ({ children }: { children: React.ReactNode }) => (
  <div className="flex gap-2 text-xs text-emerald-800 bg-emerald-50 border border-emerald-100 rounded p-2"><Lightbulb className="w-4 h-4 flex-shrink-0" /><div>{children}</div></div>
);

/** Names available from the node connected to this one: a table's columns (after Preview) or an Input node's fields. */
function useUpstreamNames(node: Node): string[] {
  const { edges, nodes, previewSchemas } = useWorkflowStore();
  return useMemo(() => {
    const e = edges.find(x => x.target === node.id);
    if (!e) return [];
    const src = nodes.find(n => n.id === e.source);
    const fields = (src?.data as Data | undefined)?.fields;
    if (src?.type === 'inputNode' && Array.isArray(fields)) return fields.map(f => String((f as { name: string }).name));
    return (previewSchemas[e.source] ?? []).map(c => c.name);
  }, [edges, nodes, previewSchemas, node.id]);
}

function ConnectionPicker({ type, label, value, onChange, hint }: { type: 'ml_endpoint' | 'mlflow'; label: string; value: string; onChange: (v: string) => void; hint?: (c?: Connection) => React.ReactNode }) {
  const { setView } = useAuthStore();
  const [conns, setConns] = useState<Connection[]>([]);
  useEffect(() => { connectionsApi.list().then(c => setConns(c.filter(x => x.type === type))).catch(() => setConns([])); }, [type]);
  const sel = conns.find(c => c.id === value);
  return (
    <>
      <Field label={label}>
        <Select value={value} onChange={onChange} ring={ring}>
          <option value="">— choose a connection —</option>
          {conns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </Select>
      </Field>
      {conns.length === 0 && (
        <div className="text-xs text-amber-900 bg-amber-50 border border-amber-200 rounded p-2 flex gap-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>No {type === 'mlflow' ? 'MLflow' : 'model endpoint'} connection yet. Nothing is chosen for you:{' '}
            <button className="underline font-medium" onClick={() => setView('connections')}>add one on the Connections page</button>.</span>
        </div>
      )}
      {hint?.(sel)}
    </>
  );
}

function FeatureList({ node, data, up, label = 'Features the model expects' }: { node: Node; data: Data; up: Up; label?: string }) {
  const names = useUpstreamNames(node);
  const feats = arr<string>(data.features);
  const toggle = (n: string) => up('features', feats.includes(n) ? feats.filter(f => f !== n) : [...feats, n]);
  return (
    <Field label={label}>
      <input type="text" value={feats.join(', ')} onChange={e => up('features', e.target.value.split(',').map(x => x.trim()).filter(Boolean))}
        placeholder="tenure_months, monthly_spend, support_tickets" className={`${inp(ring)} font-mono`} />
      {names.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1.5">
          {names.map(n => (
            <button key={n} type="button" onClick={() => toggle(n)}
              className={`text-[11px] font-mono px-1.5 py-0.5 rounded border ${feats.includes(n) ? 'bg-emerald-600 text-white border-emerald-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}`}>{n}</button>
          ))}
        </div>
      )}
      <p className="text-xs text-gray-400 mt-1">Only these are sent to the model. Nothing is guessed, so private columns never leave by accident.</p>
    </Field>
  );
}

function ColumnPick({ node, label, value, onChange, placeholder }: { node: Node; label: string; value: string; onChange: (v: string) => void; placeholder: string }) {
  const names = useUpstreamNames(node);
  return (
    <Field label={label}>
      {names.length > 0 ? (
        <Select value={value} onChange={onChange} ring={ring}><option value="">— choose —</option>{names.map(n => <option key={n} value={n}>{n}</option>)}</Select>
      ) : (
        <input type="text" value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} className={`${inp(ring)} font-mono`} />
      )}
    </Field>
  );
}

export function MlNodeProperties({ node, data, up }: { node: Node; data: Data; up: Up }) {
  const [files, setFiles] = useState<DataFile[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const connId = (data.connectionId as string) || '';

  useEffect(() => { if (node.type === 'driftCheckNode') dataApi.listFiles().then(setFiles).catch(() => setFiles([])); }, [node.type]);
  useEffect(() => {
    if (node.type !== 'registryPromoteNode' || !connId) { setModels([]); return; }
    mlApi.models(connId).then(r => setModels(r.models.map(m => m.name))).catch(() => setModels([]));
  }, [node.type, connId]);

  if (node.type === 'predictNode') return (
    <>
      <Tip>Sends <b>one record</b> to your model endpoint and returns <code>prediction</code> (and <code>probability</code> when the model gives one). Text numbers like "64000" are converted to numbers.</Tip>
      <ConnectionPicker type="ml_endpoint" label="Model endpoint" value={connId} onChange={v => up('connectionId', v)} />
      <FeatureList node={node} data={data} up={up} />
      <label className="flex items-center gap-2 text-xs text-gray-700">
        <input type="checkbox" checked={data.autoNumbers !== false} onChange={e => up('autoNumbers', e.target.checked)} /> Convert numbers typed as text
      </label>
      <p className="text-xs text-gray-400">Output: <span className="font-mono">prediction, probability, prediction_id, features, latency_ms</span></p>
    </>
  );

  if (node.type === 'batchScoreNode') return (
    <>
      <Tip>Scores <b>every row</b> of the connected table and adds the result as a new column. Re-running costs a call per batch to your endpoint.</Tip>
      <ConnectionPicker type="ml_endpoint" label="Model endpoint" value={connId} onChange={v => up('connectionId', v)} />
      <FeatureList node={node} data={data} up={up} label="Columns the model expects" />
      <div className="grid grid-cols-2 gap-2">
        <Field label="New column"><input type="text" value={(data.outputColumn as string) || ''} onChange={e => up('outputColumn', e.target.value)} className={`${inp(ring)} font-mono`} /></Field>
        <Field label="Rows per request"><input type="number" min={1} max={1000} value={(data.batchSize as number) ?? 200} onChange={e => up('batchSize', Number(e.target.value))} className={inp(ring)} /></Field>
      </div>
      <Field label="Max rows (optional)"><input type="number" min={1} max={500000} value={(data.maxRows as string | number) ?? ''} onChange={e => up('maxRows', e.target.value)} placeholder="up to 100,000" className={inp(ring)} /></Field>
    </>
  );

  if (node.type === 'driftCheckNode') return (
    <>
      <Tip>Compares the connected table with the data your model was <b>trained on</b>. A score (PSI) under 0.1 is stable; over 0.25 means the data has really changed.</Tip>
      <Field label="Reference file (training data)">
        <Select value={(data.referenceFile as string) || ''} onChange={v => up('referenceFile', v)} ring={ring}>
          <option value="">— choose a file —</option>
          {files.map(f => <option key={f.id} value={f.name}>{f.name}</option>)}
        </Select>
      </Field>
      {files.length === 0 && <p className="text-xs text-gray-400">Upload your training data on the Data page (or load the example data).</p>}
      <Field label="Only these columns (optional)">
        <input type="text" value={arr<string>(data.columns).join(', ')} onChange={e => up('columns', e.target.value.split(',').map(x => x.trim()).filter(Boolean))}
          placeholder="all shared columns (IDs and personal data are skipped)" className={`${inp(ring)} font-mono`} />
      </Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Warn at (PSI)"><input type="number" step={0.01} min={0} value={(data.warnAt as number) ?? 0.1} onChange={e => up('warnAt', Number(e.target.value))} className={inp(ring)} /></Field>
        <Field label="Drift at (PSI)"><input type="number" step={0.01} min={0} value={(data.alertAt as number) ?? 0.25} onChange={e => up('alertAt', Number(e.target.value))} className={inp(ring)} /></Field>
      </div>
      <Field label="When data has drifted">
        <Select value={(data.onDrift as string) || 'stop'} onChange={v => up('onDrift', v)} ring={ring}>
          <option value="stop">Stop the run</option><option value="warn">Warn and continue</option>
        </Select>
      </Field>
    </>
  );

  if (node.type === 'feedbackNode') return (
    <>
      <Tip>Compares predictions with what really happened and keeps the history on the <b>Models</b> page, so you can see when a model starts getting worse. Only the summary is stored, never your rows.</Tip>
      <Field label="Model name (a label for the history)"><input type="text" value={(data.modelName as string) || ''} onChange={e => up('modelName', e.target.value)} placeholder="churn-model" className={`${inp(ring)} font-mono`} /></Field>
      <Field label="Kind of model">
        <Select value={(data.taskType as string) || ''} onChange={v => up('taskType', v)} ring={ring}>
          <option value="">— choose —</option><option value="classification">Classification (right or wrong)</option><option value="regression">Regression (a number)</option>
        </Select>
      </Field>
      <ColumnPick node={node} label="Prediction column" value={(data.predictionColumn as string) || ''} onChange={v => up('predictionColumn', v)} placeholder="prediction" />
      <ColumnPick node={node} label="Actual outcome column" value={(data.actualColumn as string) || ''} onChange={v => up('actualColumn', v)} placeholder="churned" />
      <div className="grid grid-cols-2 gap-2">
        <Field label={data.taskType === 'regression' ? 'Worst average error' : 'Lowest accuracy (0–1)'}>
          <input type="number" step={0.01} value={(data.threshold as string | number) ?? ''} onChange={e => up('threshold', e.target.value)} placeholder="optional" className={inp(ring)} />
        </Field>
        <Field label="If it is worse">
          <Select value={(data.onFail as string) || 'warn'} onChange={v => up('onFail', v)} ring={ring}><option value="warn">Warn</option><option value="stop">Stop the run</option></Select>
        </Field>
      </div>
    </>
  );

  if (node.type === 'registryPromoteNode') {
    const gates = arr<{ metric: string; op: string; value: number | string }>(data.gates);
    const setGate = (i: number, patch: Partial<{ metric: string; op: string; value: number | string }>) => up('gates', gates.map((g, j) => (j === i ? { ...g, ...patch } : g)));
    return (
      <>
        <Tip>Points a registry <b>alias</b> (like <code>champion</code>) at a model version — but only if the gates pass. Needs a <b>Read &amp; write</b> MLflow connection.</Tip>
        <ConnectionPicker type="mlflow" label="MLflow connection" value={connId} onChange={v => up('connectionId', v)} />
        <Field label="Model name">
          <input list="fm-models" type="text" value={(data.modelName as string) || ''} onChange={e => up('modelName', e.target.value)} placeholder="churn-model" className={`${inp(ring)} font-mono`} />
          <datalist id="fm-models">{models.map(m => <option key={m} value={m} />)}</datalist>
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Version"><input type="text" value={(data.version as string) || ''} onChange={e => up('version', e.target.value)} placeholder="latest or 3" className={`${inp(ring)} font-mono`} /></Field>
          <Field label="Alias to move"><input type="text" value={(data.alias as string) || ''} onChange={e => up('alias', e.target.value)} placeholder="champion" className={`${inp(ring)} font-mono`} /></Field>
        </div>
        <Field label="Gates (the version's training metrics)">
          <div className="space-y-2">
            {gates.map((g, i) => (
              <div key={i} className="flex gap-1.5 items-center">
                <input type="text" value={g.metric} onChange={e => setGate(i, { metric: e.target.value })} placeholder="accuracy" className={`${inp(ring)} font-mono`} />
                <select value={g.op} onChange={e => setGate(i, { op: e.target.value })} className="px-1 py-2 text-sm border border-gray-300 rounded-lg bg-white">{['>=', '>', '<=', '<'].map(o => <option key={o}>{o}</option>)}</select>
                <input type="number" step={0.01} value={g.value} onChange={e => setGate(i, { value: e.target.value })} className={`${inp(ring)} w-20`} />
                <button onClick={() => up('gates', gates.filter((_, j) => j !== i))} className="text-gray-400 hover:text-red-600"><Trash2 className="w-4 h-4" /></button>
              </div>
            ))}
            <button onClick={() => up('gates', [...gates, { metric: 'accuracy', op: '>=', value: 0.8 }])} className="text-xs text-emerald-700 flex items-center gap-1"><Plus className="w-3 h-3" /> Add a gate</button>
          </div>
        </Field>
        <label className="flex items-center gap-2 text-xs text-gray-700"><input type="checkbox" checked={!!data.beatCurrent} onChange={e => up('beatCurrent', e.target.checked)} /> Must beat the version that holds the alias now</label>
        {!!data.beatCurrent && (
          <div className="grid grid-cols-2 gap-2">
            <Field label="Compare on"><input type="text" value={(data.compareMetric as string) || ''} onChange={e => up('compareMetric', e.target.value)} placeholder="accuracy" className={`${inp(ring)} font-mono`} /></Field>
            <Field label="Better means"><Select value={data.higherIsBetter === false ? 'lower' : 'higher'} onChange={v => up('higherIsBetter', v === 'higher')} ring={ring}><option value="higher">higher</option><option value="lower">lower</option></Select></Field>
          </div>
        )}
        <Field label="When a gate fails">
          <Select value={(data.onFail as string) || 'stop'} onChange={v => up('onFail', v)} ring={ring}><option value="stop">Stop the run</option><option value="skip">Skip promotion, continue</option></Select>
        </Field>
        <p className="text-xs text-gray-400">Want a person to approve first? Put a <b>Human Review</b> node before this one.</p>
      </>
    );
  }
  return null;
}
