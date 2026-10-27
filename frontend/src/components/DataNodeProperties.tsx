import { useEffect, useMemo, useState } from 'react';
import type { Node } from 'reactflow';
import { Plus, Trash2, Lightbulb } from 'lucide-react';
import { useWorkflowStore } from '@/store/workflowStore';
import { connectionsApi, dataApi, Connection, DataFile, DiscoveredTable, QualityRule } from '@/services/api';
import { Field, Select, TextArea, inp } from './NodePropertiesPanel';

type Data = Record<string, unknown>;

const arr = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);
const slug = (label: string) => {
  const s = label.toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '');
  return (/^\d/.test(s) ? `t_${s}` : s).slice(0, 40);
};

/** Columns coming into the selected node (one list per connected input, in edge order), from the last data preview. */
function useUpstream(node: Node) {
  const { edges, nodes, previewSchemas, previewDatasetIds } = useWorkflowStore();
  return useMemo(() => {
    return edges.filter(e => e.target === node.id).map(e => {
      const src = nodes.find(n => n.id === e.source);
      return {
        id: e.source,
        label: String((src?.data as Data | undefined)?.label ?? e.source),
        columns: (previewSchemas[e.source] ?? []) as { name: string; type: string; pii?: boolean }[],
        datasetId: previewDatasetIds[e.source],
      };
    });
  }, [edges, nodes, previewSchemas, previewDatasetIds, node.id]);
}

const NoSchemaHint = () => (
  <p className="text-xs text-gray-400">Click <b>Preview data</b> in the toolbar to see column names here.</p>
);

// ── Column pickers ──────────────────────────────────────────────────────────────

function ColumnsInput({ value, options, onChange, placeholder }: {
  value: string[]; options: string[]; onChange: (v: string[]) => void; placeholder?: string;
}) {
  const toggle = (c: string) => onChange(value.includes(c) ? value.filter(x => x !== c) : [...value, c]);
  return (
    <div className="space-y-1.5">
      {options.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {options.map(c => (
            <button
              key={c} type="button" onClick={() => toggle(c)}
              className={`px-2 py-0.5 rounded-full text-xs border font-mono ${value.includes(c)
                ? 'bg-cyan-600 text-white border-cyan-600' : 'bg-white text-gray-600 border-gray-300 hover:border-cyan-400'}`}
            >{c}</button>
          ))}
        </div>
      ) : (
        <>
          <input
            type="text" value={value.join(', ')} placeholder={placeholder ?? 'column_a, column_b'}
            onChange={e => onChange(e.target.value.split(',').map(x => x.trim()).filter(Boolean))}
            className={`${inp('focus:ring-cyan-500')} font-mono`}
          />
          <NoSchemaHint />
        </>
      )}
    </div>
  );
}

function ColumnSelect({ value, options, onChange, extra }: {
  value: string; options: string[]; onChange: (v: string) => void; extra?: { value: string; label: string }[];
}) {
  if (options.length === 0 && !extra?.length) {
    return <input type="text" value={value} onChange={e => onChange(e.target.value)} placeholder="column"
      className={`${inp('focus:ring-cyan-500')} font-mono`} />;
  }
  return (
    <Select value={value} onChange={onChange} ring="focus:ring-cyan-500">
      <option value="">— choose —</option>
      {extra?.map(x => <option key={x.value} value={x.value}>{x.label}</option>)}
      {options.map(c => <option key={c} value={c}>{c}</option>)}
    </Select>
  );
}

const RemoveBtn = ({ onClick }: { onClick: () => void }) => (
  <button onClick={onClick} className="p-1 text-gray-400 hover:text-red-500" title="Remove"><Trash2 className="w-3.5 h-3.5" /></button>
);
const AddBtn = ({ label, onClick }: { label: string; onClick: () => void }) => (
  <button onClick={onClick} className="flex items-center gap-1 text-xs font-medium text-cyan-700 hover:opacity-80">
    <Plus className="w-3.5 h-3.5" />{label}
  </button>
);
const Tip = ({ children }: { children: React.ReactNode }) => (
  <div className="flex gap-2 text-xs text-cyan-800 bg-cyan-50 border border-cyan-100 rounded p-2">
    <Lightbulb className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" /><div>{children}</div>
  </div>
);

// ── Entry point ─────────────────────────────────────────────────────────────────

export function DataNodeProperties({ node, data, up }: { node: Node; data: Data; up: (k: string, v: unknown) => void }) {
  switch (node.type) {
    case 'loadDataNode': return <LoadProps data={data} up={up} />;
    case 'cleanDataNode': return <CleanProps node={node} data={data} up={up} />;
    case 'combineDataNode': return <CombineProps node={node} data={data} up={up} />;
    case 'summariseDataNode': return <SummariseProps node={node} data={data} up={up} />;
    case 'sqlNode': return <SqlProps node={node} data={data} up={up} />;
    case 'qualityGateNode': return <QualityProps node={node} data={data} up={up} />;
    default: return null;
  }
}

type PropsBase = { data: Data; up: (k: string, v: unknown) => void };

// ── Load Data ───────────────────────────────────────────────────────────────────

function LoadProps({ data, up }: PropsBase) {
  const [files, setFiles] = useState<DataFile[]>([]);
  const [conns, setConns] = useState<Connection[]>([]);
  const [tables, setTables] = useState<DiscoveredTable[]>([]);
  const [busy, setBusy] = useState(false);
  const source = (data.source as string) || 'file';
  const connectionId = (data.connectionId as string) || '';

  const refresh = () => {
    dataApi.listFiles().then(setFiles).catch(() => setFiles([]));
    connectionsApi.list().then(c => setConns(c.filter(x => x.type === 'postgres'))).catch(() => setConns([]));
  };
  useEffect(refresh, []);

  useEffect(() => {
    if (source !== 'connection' || !connectionId) { setTables([]); return; }
    connectionsApi.discover(connectionId).then(r => setTables(r.tables)).catch(() => setTables([]));
  }, [source, connectionId]);

  const loadExamples = async () => {
    setBusy(true);
    try { await dataApi.installExamples(); refresh(); } finally { setBusy(false); }
  };

  return (
    <>
      <Field label="Where is the data?">
        <Select value={source} onChange={v => up('source', v)} ring="focus:ring-cyan-500">
          <option value="file">An uploaded file</option>
          <option value="connection">A database table</option>
        </Select>
      </Field>

      {source === 'file' && (
        <>
          <Field label="File">
            <Select
              value={(data.fileName as string) || ''}
              onChange={v => { up('fileName', v); up('fileId', files.find(f => f.name === v)?.id ?? ''); }}
              ring="focus:ring-cyan-500"
            >
              <option value="">— choose a file —</option>
              {files.map(f => <option key={f.id} value={f.name}>{f.name}{f.row_count != null ? ` (${f.row_count.toLocaleString()} rows)` : ''}</option>)}
            </Select>
          </Field>
          {files.length === 0 && (
            <Tip>
              No files yet. Upload one on the <b>Data</b> page, or
              {' '}<button onClick={loadExamples} disabled={busy} className="underline font-medium">
                {busy ? 'loading…' : 'load the example data'}
              </button>.
            </Tip>
          )}
        </>
      )}

      {source === 'connection' && (
        <>
          <Field label="Connection">
            <Select value={connectionId} onChange={v => up('connectionId', v)} ring="focus:ring-cyan-500">
              <option value="">— choose a connection —</option>
              {conns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </Select>
          </Field>
          {conns.length === 0 && <Tip>Add a PostgreSQL connection on the <b>Connections</b> page first.</Tip>}
          <Field label="Table">
            <input
              list="fm-tables" type="text" value={(data.table as string) || ''}
              onChange={e => {
                const val = e.target.value;
                const hit = tables.find(t => `${t.schema}.${t.name}` === val || t.name === val);
                if (hit) { up('schema', hit.schema); up('table', hit.name); } else { up('table', val); }
              }}
              placeholder="orders" className={`${inp('focus:ring-cyan-500')} font-mono`}
            />
            <datalist id="fm-tables">
              {tables.map(t => <option key={`${t.schema}.${t.name}`} value={`${t.schema}.${t.name}`} />)}
            </datalist>
            <p className="text-xs text-gray-400 mt-1">Schema: <span className="font-mono">{(data.schema as string) || 'public'}</span></p>
          </Field>
          <Field label="Only these columns (optional)">
            <input
              type="text" value={arr<string>(data.columns).join(', ')}
              onChange={e => up('columns', e.target.value.split(',').map(x => x.trim()).filter(Boolean))}
              placeholder="id, name, total" className={`${inp('focus:ring-cyan-500')} font-mono`}
            />
          </Field>
        </>
      )}

      <Field label="Max rows (optional)">
        <input type="number" min={1} value={(data.maxRows as string | number) ?? ''}
          onChange={e => up('maxRows', e.target.value)} placeholder="all (up to 1,000,000)"
          className={inp('focus:ring-cyan-500')} />
      </Field>
    </>
  );
}

// ── Clean ───────────────────────────────────────────────────────────────────────

function CleanProps({ node, data, up }: PropsBase & { node: Node }) {
  const upstream = useUpstream(node);
  const cols = upstream[0]?.columns ?? [];
  const names = cols.map(c => c.name);
  const textNames = cols.filter(c => c.type.toUpperCase().startsWith('VARCHAR')).map(c => c.name);
  const fills = arr<{ column: string; value: string }>(data.fillMissing);
  const renames = arr<{ from: string; to: string }>(data.rename);
  const tc = (data.textCase as { columns?: string[]; mode?: string } | undefined) ?? {};
  const protects = arr<{ column: string; method: string }>(data.protect);

  return (
    <>
      <Tip>Each switch below becomes a step of one SQL query. Open <b>Preview data</b> to see the SQL it writes.</Tip>
      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={!!data.trimAll} onChange={e => up('trimAll', e.target.checked)} />
        Trim extra spaces from all text columns
      </label>
      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={!!data.removeDuplicates} onChange={e => up('removeDuplicates', e.target.checked)} />
        Remove duplicate rows
      </label>

      <Field label="Drop rows where these are empty">
        <ColumnsInput value={arr<string>(data.dropMissing)} options={names} onChange={v => up('dropMissing', v)} />
      </Field>

      <Field label="Fill empty values">
        <div className="space-y-2">
          {fills.map((f, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <div className="flex-1"><ColumnSelect value={f.column} options={names} onChange={v => up('fillMissing', fills.map((x, j) => j === i ? { ...x, column: v } : x))} /></div>
              <input type="text" value={f.value} placeholder="with…" className={`${inp('focus:ring-cyan-500')} w-24`}
                onChange={e => up('fillMissing', fills.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
              <RemoveBtn onClick={() => up('fillMissing', fills.filter((_, j) => j !== i))} />
            </div>
          ))}
          <AddBtn label="Add" onClick={() => up('fillMissing', [...fills, { column: '', value: '' }])} />
        </div>
      </Field>

      <Field label="Protect personal data">
        <div className="space-y-2">
          {cols.some(c => c.pii) && protects.length === 0 && (
            <button
              onClick={() => up('protect', cols.filter(c => c.pii).map(c => ({ column: c.name, method: 'hash' })))}
              className="text-xs text-cyan-700 underline text-left"
            >
              Personal data detected in: {cols.filter(c => c.pii).map(c => c.name).join(', ')} — protect them
            </button>
          )}
          {protects.map((p, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <div className="flex-1"><ColumnSelect value={p.column} options={names} onChange={v => up('protect', protects.map((x, j) => j === i ? { ...x, column: v } : x))} /></div>
              <select value={p.method} onChange={e => up('protect', protects.map((x, j) => j === i ? { ...x, method: e.target.value } : x))}
                className={`${inp('focus:ring-cyan-500')} w-28`}>
                <option value="hash">hash</option>
                <option value="mask">mask (last 4)</option>
                <option value="redact">redact</option>
                <option value="blank">blank out</option>
              </select>
              <RemoveBtn onClick={() => up('protect', protects.filter((_, j) => j !== i))} />
            </div>
          ))}
          <AddBtn label="Add" onClick={() => up('protect', [...protects, { column: '', method: 'hash' }])} />
          {protects.some(p => p.method === 'hash') && (
            <input type="text" value={(data.hashSalt as string) || ''} onChange={e => up('hashSalt', e.target.value)}
              placeholder="optional secret salt for hashes" className={`${inp('focus:ring-cyan-500')} font-mono`} />
          )}
          <p className="text-xs text-gray-400">Hashes are one-way but guessable for short values like phone numbers — add a salt.</p>
        </div>
      </Field>

      <Field label="Change text case">
        <div className="space-y-1.5">
          <Select value={tc.mode || ''} onChange={v => up('textCase', { ...tc, mode: v || undefined })} ring="focus:ring-cyan-500">
            <option value="">Leave as is</option>
            <option value="lower">lowercase</option>
            <option value="upper">UPPERCASE</option>
          </Select>
          {tc.mode && <ColumnsInput value={tc.columns ?? []} options={textNames.length ? textNames : names} onChange={v => up('textCase', { ...tc, columns: v })} />}
        </div>
      </Field>

      <Field label="Rename columns">
        <div className="space-y-2">
          {renames.map((r, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <div className="flex-1"><ColumnSelect value={r.from} options={names} onChange={v => up('rename', renames.map((x, j) => j === i ? { ...x, from: v } : x))} /></div>
              <span className="text-gray-400 text-xs">→</span>
              <input type="text" value={r.to} placeholder="new name" className={`${inp('focus:ring-cyan-500')} w-24 font-mono`}
                onChange={e => up('rename', renames.map((x, j) => j === i ? { ...x, to: e.target.value } : x))} />
              <RemoveBtn onClick={() => up('rename', renames.filter((_, j) => j !== i))} />
            </div>
          ))}
          <AddBtn label="Add" onClick={() => up('rename', [...renames, { from: '', to: '' }])} />
        </div>
      </Field>

      <Field label="Keep only these columns (blank = all)">
        <ColumnsInput value={arr<string>(data.keepColumns)} options={names} onChange={v => up('keepColumns', v)} />
      </Field>
    </>
  );
}

// ── Combine ─────────────────────────────────────────────────────────────────────

function CombineProps({ node, data, up }: PropsBase & { node: Node }) {
  const upstream = useUpstream(node);
  const swap = !!data.swap;
  const ordered = swap ? [upstream[1], upstream[0]] : [upstream[0], upstream[1]];
  const left = ordered[0], right = ordered[1];
  const keys = arr<{ left: string; right: string }>(data.keys);

  return (
    <>
      <Tip>
        Connect <b>two</b> data nodes into this one. The first connection is the <b>left</b> table, the second is the <b>right</b>.
        {left && right && <div className="mt-1">Left: <b>{left.label}</b> · Right: <b>{right.label}</b></div>}
        {upstream.length < 2 && <div className="mt-1 text-amber-700">Only {upstream.length} input connected so far.</div>}
      </Tip>
      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={swap} onChange={e => up('swap', e.target.checked)} /> Swap left and right
      </label>
      <Field label="Keep…">
        <Select value={(data.joinType as string) || 'inner'} onChange={v => up('joinType', v)} ring="focus:ring-cyan-500">
          <option value="inner">only rows that match on both sides (inner)</option>
          <option value="left">all rows from the left, matches from the right (left)</option>
          <option value="right">all rows from the right, matches from the left (right)</option>
          <option value="full">every row from both sides (full)</option>
        </Select>
      </Field>
      <Field label="Match rows where">
        <div className="space-y-2">
          {keys.map((k, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <div className="flex-1"><ColumnSelect value={k.left} options={(left?.columns ?? []).map(c => c.name)}
                onChange={v => up('keys', keys.map((x, j) => j === i ? { ...x, left: v } : x))} /></div>
              <span className="text-gray-400 text-xs">=</span>
              <div className="flex-1"><ColumnSelect value={k.right} options={(right?.columns ?? []).map(c => c.name)}
                onChange={v => up('keys', keys.map((x, j) => j === i ? { ...x, right: v } : x))} /></div>
              {keys.length > 1 && <RemoveBtn onClick={() => up('keys', keys.filter((_, j) => j !== i))} />}
            </div>
          ))}
          <AddBtn label="Add another match" onClick={() => up('keys', [...keys, { left: '', right: '' }])} />
          {(!left?.columns.length || !right?.columns.length) && <NoSchemaHint />}
        </div>
      </Field>
    </>
  );
}

// ── Summarise ───────────────────────────────────────────────────────────────────

const AGG_LABELS: Record<string, string> = {
  count: 'count rows', count_distinct: 'count different values', sum: 'total (sum)', avg: 'average',
  min: 'smallest', max: 'largest', median: 'median',
};

function SummariseProps({ node, data, up }: PropsBase & { node: Node }) {
  const upstream = useUpstream(node);
  const cols = upstream[0]?.columns ?? [];
  const names = cols.map(c => c.name);
  const aggs = arr<{ column: string; fn: string; as: string }>(data.aggregations);

  return (
    <>
      <Tip>Example: group by <b>region</b>, then <b>total</b> of <b>revenue</b> gives one row per region.</Tip>
      <Field label="Group by (one result row per value)">
        <ColumnsInput value={arr<string>(data.groupBy)} options={names} onChange={v => up('groupBy', v)} />
      </Field>
      <Field label="Calculate">
        <div className="space-y-2">
          {aggs.map((a, i) => (
            <div key={i} className="space-y-1 border border-gray-200 rounded p-2">
              <div className="flex items-center gap-1.5">
                <Select value={a.fn} onChange={v => up('aggregations', aggs.map((x, j) => j === i ? { ...x, fn: v } : x))} ring="focus:ring-cyan-500">
                  {Object.entries(AGG_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </Select>
                <RemoveBtn onClick={() => up('aggregations', aggs.filter((_, j) => j !== i))} />
              </div>
              <ColumnSelect
                value={a.column} options={names}
                extra={a.fn === 'count' ? [{ value: '*', label: '* (all rows)' }] : undefined}
                onChange={v => up('aggregations', aggs.map((x, j) => j === i ? { ...x, column: v } : x))}
              />
              <input type="text" value={a.as ?? ''} placeholder="result column name (optional)"
                onChange={e => up('aggregations', aggs.map((x, j) => j === i ? { ...x, as: e.target.value } : x))}
                className={`${inp('focus:ring-cyan-500')} font-mono`} />
            </div>
          ))}
          <AddBtn label="Add calculation" onClick={() => up('aggregations', [...aggs, { column: '', fn: 'sum', as: '' }])} />
        </div>
      </Field>
    </>
  );
}

// ── SQL ─────────────────────────────────────────────────────────────────────────

function SqlProps({ node, data, up }: PropsBase & { node: Node }) {
  const upstream = useUpstream(node);
  const [open, setOpen] = useState(false);
  const tables = useMemo(() => {
    const out: { name: string; label?: string }[] = [];
    const seen = new Set<string>();
    upstream.forEach((u, i) => {
      const base = i === 0 ? 'input' : `input${i + 1}`;
      out.push({ name: base, label: u.label }); seen.add(base);
    });
    upstream.forEach(u => {
      const s = slug(u.label);
      if (s && !seen.has(s)) { out.push({ name: s, label: u.label }); seen.add(s); }
    });
    return out;
  }, [upstream]);
  const example = tables.some(t => t.name === 'input2')
    ? 'SELECT a.*, b.*\nFROM input AS a\nJOIN input2 AS b USING (customer_id)'
    : 'SELECT *\nFROM input\nWHERE 1 = 1\nLIMIT 100';
  return (
    <>
      <Field label="SQL query">
        <TextArea value={(data.query as string) || ''} onChange={v => up('query', v)} rows={9} ring="focus:ring-cyan-500" extraClass="font-mono text-xs" />
      </Field>
      <div className="text-xs text-gray-600">
        <p className="font-medium mb-1">Tables you can query</p>
        {tables.length === 0 ? <p className="text-gray-400">Connect a data node to this one first.</p> : (
          <ul className="space-y-0.5">
            {tables.map(t => <li key={t.name}><code className="bg-gray-100 rounded px-1">{t.name}</code>{t.label ? <span className="text-gray-400"> — {t.label}</span> : null}</li>)}
          </ul>
        )}
        {upstream[0]?.columns.length ? (
          <p className="mt-2 text-gray-400 font-mono break-words">{upstream[0].columns.map(c => c.name).join(', ')}</p>
        ) : null}
      </div>
      <button onClick={() => setOpen(o => !o)} className="text-xs text-cyan-700 font-medium">{open ? 'Hide' : 'Show'} help</button>
      {open && (
        <div className="text-xs text-gray-600 space-y-1 bg-gray-50 rounded p-2">
          <p>• One <b>SELECT</b> statement only (no INSERT / DROP / COPY).</p>
          <p>• Files and the internet are not reachable from SQL — only the connected tables.</p>
          <p>• DuckDB SQL: <code>GROUP BY</code>, window functions, <code>QUALIFY</code>, <code>strftime()</code>, …</p>
          <button className="underline" onClick={() => up('query', example)}>Insert an example</button>
        </div>
      )}
    </>
  );
}


// ── Quality Check ───────────────────────────────────────────────────────────────

const RULE_LABELS: Record<QualityRule['type'], string> = {
  not_null: 'Never empty',
  unique: 'No duplicates',
  range: 'Number / date in range',
  allowed_values: 'Only these values',
  regex: 'Matches a pattern',
  max_null_pct: 'At most N% empty',
  min_rows: 'At least N rows',
  max_rows: 'At most N rows',
  schema: 'Columns match a contract',
  expression: 'Custom condition (SQL)',
};

function newRule(type: QualityRule['type']): QualityRule {
  switch (type) {
    case 'not_null': return { type, columns: [] };
    case 'unique': return { type, columns: [] };
    case 'range': return { type, column: '', min: '', max: '' };
    case 'allowed_values': return { type, column: '', values: '' };
    case 'regex': return { type, column: '', pattern: '' };
    case 'max_null_pct': return { type, column: '', max: 5 };
    case 'min_rows': return { type, value: 1 };
    case 'max_rows': return { type, value: 1000000 };
    case 'schema': return { type, expected: [], allowExtra: true };
    default: return { type: 'expression', expression: '', label: '' };
  }
}

function valuesText(v: QualityRule['values']): string {
  return Array.isArray(v) ? v.join(', ') : v ?? '';
}

function QualityProps({ node, data, up }: PropsBase & { node: Node }) {
  const upstream = useUpstream(node);
  const cols = upstream[0]?.columns ?? [];
  const names = cols.map(c => c.name);
  const rules = arr<QualityRule>(data.rules);
  const [suggestions, setSuggestions] = useState<QualityRule[] | null>(null);
  const [picked, setPicked] = useState<Record<number, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  const datasetId = upstream[0]?.datasetId;

  const setRule = (i: number, patch: Partial<QualityRule>) => up('rules', rules.map((r, j) => j === i ? { ...r, ...patch } : r));

  const suggest = async () => {
    if (!datasetId) return;
    setLoading(true); setErr('');
    try {
      const p = await dataApi.profileDataset(datasetId);
      setSuggestions(p.suggested_rules);
      setPicked(Object.fromEntries(p.suggested_rules.map((_, i) => [i, true])));
    } catch {
      setErr('Could not profile the data. Run Preview data again.');
    } finally { setLoading(false); }
  };
  const addPicked = () => {
    const add = (suggestions ?? []).filter((_, i) => picked[i]).map(({ reason: _reason, ...r }) => r as QualityRule);
    up('rules', [...rules, ...add]);
    setSuggestions(null);
  };

  return (
    <>
      <Tip>Checks run on the table coming in. If one fails, the run <b>stops</b> (or only warns) and tells you exactly what was wrong, with example rows.</Tip>

      <Field label="When a check fails">
        <Select value={(data.onFail as string) || 'stop'} onChange={v => up('onFail', v)} ring="focus:ring-cyan-500">
          <option value="stop">Stop the run</option>
          <option value="warn">Keep going, just report it</option>
        </Select>
      </Field>

      <div className="space-y-2">
        {rules.map((r, i) => (
          <div key={i} className="border border-gray-200 rounded p-2 space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-semibold text-pink-700 flex-1">{RULE_LABELS[r.type]}</span>
              <select value={r.severity || 'error'} onChange={e => setRule(i, { severity: e.target.value as 'error' | 'warn' })}
                className="text-xs border border-gray-200 rounded px-1 py-0.5 bg-white">
                <option value="error">must pass</option>
                <option value="warn">warn only</option>
              </select>
              <RemoveBtn onClick={() => up('rules', rules.filter((_, j) => j !== i))} />
            </div>
            <RuleFields rule={r} names={names} set={p => setRule(i, p)} />
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <select value="" onChange={e => e.target.value && up('rules', [...rules, newRule(e.target.value as QualityRule['type'])])}
          className={`${inp('focus:ring-pink-500')} flex-1`}>
          <option value="">+ Add a check…</option>
          {Object.entries(RULE_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </div>

      <button onClick={suggest} disabled={!datasetId || loading}
        className="text-xs font-medium text-pink-700 hover:underline disabled:text-gray-400 disabled:no-underline text-left">
        {loading ? 'Looking at your data…' : datasetId ? '✨ Suggest checks from my data' : '✨ Suggest checks (run Preview data first)'}
      </button>
      {err && <p className="text-xs text-red-600">{err}</p>}
      {suggestions && (
        <div className="border border-pink-200 bg-pink-50/50 rounded p-2 space-y-1.5">
          <p className="text-xs font-semibold text-pink-800">Suggested checks — untick any you don&apos;t want</p>
          {suggestions.map((s, i) => (
            <label key={i} className="flex gap-2 text-xs text-gray-700">
              <input type="checkbox" checked={!!picked[i]} onChange={e => setPicked(p => ({ ...p, [i]: e.target.checked }))} />
              <span><b>{RULE_LABELS[s.type]}</b>{s.column ? ` · ${s.column}` : s.columns?.length ? ` · ${s.columns.join(', ')}` : ''}
                <span className="block text-gray-500">{s.reason}</span></span>
            </label>
          ))}
          <div className="flex gap-2 pt-1">
            <button onClick={addPicked} className="px-2.5 py-1 text-xs font-medium text-white bg-pink-600 rounded hover:bg-pink-700">Add selected</button>
            <button onClick={() => setSuggestions(null)} className="px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-100 rounded">Cancel</button>
          </div>
        </div>
      )}
    </>
  );
}

function RuleFields({ rule, names, set }: { rule: QualityRule; names: string[]; set: (p: Partial<QualityRule>) => void }) {
  const small = `${inp('focus:ring-pink-500')} font-mono text-xs`;
  switch (rule.type) {
    case 'not_null':
    case 'unique':
      return <ColumnsInput value={rule.columns ?? (rule.column ? [rule.column] : [])} options={names} onChange={v => set({ columns: v, column: undefined })} />;
    case 'range':
      return (
        <>
          <ColumnSelect value={rule.column ?? ''} options={names} onChange={v => set({ column: v })} />
          <div className="flex gap-1.5">
            <input type="text" value={rule.min ?? ''} placeholder="min" onChange={e => set({ min: e.target.value })} className={small} />
            <input type="text" value={rule.max ?? ''} placeholder="max" onChange={e => set({ max: e.target.value })} className={small} />
          </div>
          <p className="text-[11px] text-gray-400">Numbers, or dates like 2026-03-31. Leave one side blank for “at least / at most”.</p>
        </>
      );
    case 'allowed_values':
      return (
        <>
          <ColumnSelect value={rule.column ?? ''} options={names} onChange={v => set({ column: v })} />
          <input type="text" value={valuesText(rule.values)} placeholder="delivered, shipped, cancelled" onChange={e => set({ values: e.target.value })} className={small} />
        </>
      );
    case 'regex':
      return (
        <>
          <ColumnSelect value={rule.column ?? ''} options={names} onChange={v => set({ column: v })} />
          <input type="text" value={rule.pattern ?? ''} placeholder="^\d{4}-\d{2}-\d{2}$" onChange={e => set({ pattern: e.target.value })} className={small} />
        </>
      );
    case 'max_null_pct':
      return (
        <div className="flex gap-1.5 items-center">
          <div className="flex-1"><ColumnSelect value={rule.column ?? ''} options={names} onChange={v => set({ column: v })} /></div>
          <input type="number" min={0} max={100} value={rule.max ?? ''} onChange={e => set({ max: e.target.value })} className={`${small} w-16`} />
          <span className="text-xs text-gray-500">%</span>
        </div>
      );
    case 'min_rows':
    case 'max_rows':
      return <input type="number" min={0} value={rule.value ?? ''} onChange={e => set({ value: e.target.value })} className={small} />;
    case 'schema':
      return (
        <>
          <textarea
            rows={4} className={small} placeholder={'order_id: integer\nstatus: text\nunit_price: number'}
            value={(rule.expected ?? []).map(e => e.type ? `${e.name}: ${e.type}` : e.name).join('\n')}
            onChange={e => set({ expected: e.target.value.split('\n').map(l => l.trim()).filter(Boolean).map(l => {
              const [name, type] = l.split(':').map(x => x.trim());
              return type ? { name, type } : { name };
            }) })}
          />
          <label className="flex items-center gap-2 text-xs text-gray-600">
            <input type="checkbox" checked={rule.allowExtra !== false} onChange={e => set({ allowExtra: e.target.checked })} /> Allow extra columns
          </label>
          <p className="text-[11px] text-gray-400">One per line. Types: integer, number, text, boolean, date, timestamp (optional).</p>
        </>
      );
    default:
      return (
        <>
          <textarea rows={2} className={small} value={rule.expression ?? ''} placeholder="quantity * unit_price > 0"
            onChange={e => set({ expression: e.target.value })} />
          <input type="text" value={rule.label ?? ''} placeholder="Name for this check (optional)" onChange={e => set({ label: e.target.value })} className={inp('focus:ring-pink-500')} />
          <p className="text-[11px] text-gray-400">Must be TRUE for every row (SQL expression over the columns).</p>
        </>
      );
  }
}
