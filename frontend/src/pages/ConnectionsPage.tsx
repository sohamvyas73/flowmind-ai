import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft, Database, Plus, Loader2, CheckCircle2, XCircle, CircleDashed, Trash2, Pencil,
  PlugZap, Table2, Eye, EyeOff, X, ShieldAlert, Lock, Globe, Info,
} from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { DatasetTable } from '@/components/DatasetTable';
import {
  connectionsApi, Connection, ConnectorSpec, DatasetRef, DiscoveredTable, FieldSpec,
} from '@/services/api';

const SECRET_SENTINEL = '__secret__';

function errMsg(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
}

// ── Page ────────────────────────────────────────────────────────────────────────

export function ConnectionsPage() {
  const { setView, user } = useAuthStore();
  const isAdmin = user?.role === 'admin';

  const [specs, setSpecs] = useState<ConnectorSpec[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showAll, setShowAll] = useState(false);
  const [editing, setEditing] = useState<Connection | 'new' | null>(null);
  const [browsing, setBrowsing] = useState<Connection | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, c] = await Promise.all([connectionsApi.types(), connectionsApi.list(isAdmin && showAll)]);
      setSpecs(s);
      setConnections(c);
      setError('');
    } catch (e) {
      setError(errMsg(e, 'Failed to load connections.'));
    } finally {
      setLoading(false);
    }
  }, [isAdmin, showAll]);

  useEffect(() => { void load(); }, [load]);

  const specByType = useMemo(() => Object.fromEntries(specs.map(s => [s.type, s])), [specs]);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4">
        <button
          onClick={() => setView('canvas')}
          className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" /> Back to Canvas
        </button>
        <div className="h-5 w-px bg-gray-300" />
        <h1 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <Database className="w-5 h-5 text-blue-600" /> Data Connections
        </h1>
        <div className="ml-auto flex items-center gap-3">
          {isAdmin && (
            <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
              <input type="checkbox" checked={showAll} onChange={e => setShowAll(e.target.checked)} />
              Show all users
            </label>
          )}
          <button
            onClick={() => setEditing('new')}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" /> New connection
          </button>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-6 py-8 space-y-4">
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 flex gap-3">
          <Info className="w-4 h-4 text-blue-500 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-blue-700">
            Connections store credentials encrypted and are <strong>read-only by default</strong>. Hosts on private
            networks are blocked unless an admin allow-lists them for the connection.
          </p>
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
            <XCircle className="w-4 h-4 flex-shrink-0" /> {error}
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 animate-spin text-blue-500" /></div>
        ) : connections.length === 0 ? (
          <div className="bg-white border border-dashed border-gray-300 rounded-xl p-12 text-center">
            <Database className="w-10 h-10 text-gray-300 mx-auto mb-3" />
            <p className="text-sm font-medium text-gray-700">No connections yet</p>
            <p className="text-xs text-gray-500 mt-1">Add a PostgreSQL database or an HTTP API to start building data pipelines.</p>
          </div>
        ) : (
          connections.map(c => (
            <ConnectionCard
              key={c.id}
              conn={c}
              spec={specByType[c.type]}
              isAdmin={isAdmin}
              onEdit={() => setEditing(c)}
              onBrowse={() => setBrowsing(c)}
              onChanged={load}
            />
          ))
        )}
      </div>

      {editing && (
        <ConnectionForm
          specs={specs}
          existing={editing === 'new' ? null : editing}
          isAdmin={isAdmin}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); void load(); }}
        />
      )}
      {browsing && <BrowseModal conn={browsing} onClose={() => setBrowsing(null)} />}
    </div>
  );
}

// ── Card ────────────────────────────────────────────────────────────────────────

function ConnectionCard({ conn, spec, isAdmin, onEdit, onBrowse, onChanged }: {
  conn: Connection; spec?: ConnectorSpec; isAdmin: boolean;
  onEdit: () => void; onBrowse: () => void; onChanged: () => void;
}) {
  const [testing, setTesting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const test = async () => {
    setTesting(true);
    setMsg(null);
    try {
      const r = await connectionsApi.test(conn.id);
      setMsg({ ok: r.ok, text: r.ok ? `${r.message}${r.latency_ms != null ? ` · ${r.latency_ms} ms` : ''}` : r.message });
      onChanged();
    } catch (e) {
      setMsg({ ok: false, text: errMsg(e, 'Test failed') });
    } finally {
      setTesting(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete connection "${conn.name}"?`)) return;
    setDeleting(true);
    try {
      await connectionsApi.remove(conn.id);
      onChanged();
    } catch (e) {
      setMsg({ ok: false, text: errMsg(e, 'Delete failed') });
      setDeleting(false);
    }
  };

  const status = conn.last_test_ok == null
    ? { icon: <CircleDashed className="w-3.5 h-3.5" />, text: 'Not tested', cls: 'text-gray-500 bg-gray-100' }
    : conn.last_test_ok
      ? { icon: <CheckCircle2 className="w-3.5 h-3.5" />, text: 'Connected', cls: 'text-green-700 bg-green-100' }
      : { icon: <XCircle className="w-3.5 h-3.5" />, text: 'Failed', cls: 'text-red-700 bg-red-100' };

  const target = conn.type === 'postgres'
    ? `${conn.config.host ?? ''}:${conn.config.port ?? ''}/${conn.config.database ?? ''}`
    : String(conn.config.base_url ?? conn.config.url ?? '');

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-start gap-4">
        <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center flex-shrink-0">
          {conn.type === 'postgres' ? <Database className="w-5 h-5 text-blue-600" /> : <Globe className="w-5 h-5 text-blue-600" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-900">{conn.name}</h3>
            <span className="text-xs text-gray-500 bg-gray-100 rounded-full px-2 py-0.5">{spec?.label ?? conn.type}</span>
            <span className={`flex items-center gap-1 text-xs font-medium rounded-full px-2 py-0.5 ${status.cls}`}>
              {status.icon}{status.text}
            </span>
            <span className={`flex items-center gap-1 text-xs rounded-full px-2 py-0.5 ${conn.access_mode === 'read_only' ? 'text-emerald-700 bg-emerald-50' : 'text-amber-700 bg-amber-50'}`}>
              <Lock className="w-3 h-3" />{conn.access_mode === 'read_only' ? 'Read-only' : 'Read & write'}
            </span>
          </div>
          <p className="text-xs font-mono text-gray-500 mt-1 truncate">{target}</p>
          {conn.owner_email && isAdmin && <p className="text-xs text-gray-400 mt-0.5">Owner: {conn.owner_email}</p>}
          {conn.host_allowlist.length > 0 && (
            <p className="text-xs text-amber-700 mt-1 flex items-center gap-1">
              <ShieldAlert className="w-3 h-3" /> Private hosts allowed: {conn.host_allowlist.join(', ')}
            </p>
          )}
          {conn.last_test_ok === false && conn.last_test_message && !msg && (
            <p className="text-xs text-red-600 mt-1">{conn.last_test_message}</p>
          )}
          {msg && (
            <p className={`text-xs mt-1 ${msg.ok ? 'text-green-700' : 'text-red-600'}`}>{msg.text}</p>
          )}
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            onClick={test}
            disabled={testing}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100 rounded-md disabled:opacity-50"
          >
            {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PlugZap className="w-3.5 h-3.5" />} Test
          </button>
          {spec?.supports_discover && (
            <button onClick={onBrowse} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100 rounded-md">
              <Table2 className="w-3.5 h-3.5" /> Browse
            </button>
          )}
          <button onClick={onEdit} className="p-1.5 text-gray-500 hover:bg-gray-100 rounded-md" title="Edit">
            <Pencil className="w-3.5 h-3.5" />
          </button>
          <button onClick={remove} disabled={deleting} className="p-1.5 text-gray-500 hover:bg-red-50 hover:text-red-600 rounded-md disabled:opacity-50" title="Delete">
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Create / edit form ──────────────────────────────────────────────────────────

function ConnectionForm({ specs, existing, isAdmin, onClose, onSaved }: {
  specs: ConnectorSpec[]; existing: Connection | null; isAdmin: boolean;
  onClose: () => void; onSaved: () => void;
}) {
  const [type, setType] = useState(existing?.type ?? specs[0]?.type ?? 'postgres');
  const spec = specs.find(s => s.type === type);
  const [name, setName] = useState(existing?.name ?? '');
  const [accessMode, setAccessMode] = useState<'read_only' | 'read_write'>(existing?.access_mode ?? 'read_only');
  const [allowlist, setAllowlist] = useState((existing?.host_allowlist ?? []).join(', '));
  const [values, setValues] = useState<Record<string, string>>(() => {
    const v: Record<string, string> = {};
    Object.entries(existing?.config ?? {}).forEach(([k, val]) => { v[k] = String(val); });
    return v;
  });
  const [showSecret, setShowSecret] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Fill in defaults when the type changes (new connections only)
  useEffect(() => {
    if (existing || !spec) return;
    setValues(prev => {
      const next: Record<string, string> = {};
      spec.fields.forEach(f => { next[f.name] = prev[f.name] ?? (f.default != null ? String(f.default) : ''); });
      return next;
    });
  }, [type, spec, existing]);

  const set = (k: string, v: string) => setValues(prev => ({ ...prev, [k]: v }));

  const save = async () => {
    if (!spec) return;
    setSaving(true);
    setError('');
    const config: Record<string, unknown> = {};
    spec.fields.forEach(f => {
      const v = values[f.name];
      if (v !== undefined && v !== '') config[f.name] = f.type === 'number' ? Number(v) : v;
    });
    const hosts = allowlist.split(',').map(h => h.trim()).filter(Boolean);
    try {
      if (existing) {
        await connectionsApi.update(existing.id, {
          name, config, access_mode: accessMode, ...(isAdmin ? { host_allowlist: hosts } : {}),
        });
      } else {
        await connectionsApi.create({
          name, type, config, access_mode: accessMode, ...(isAdmin && hosts.length ? { host_allowlist: hosts } : {}),
        });
      }
      onSaved();
    } catch (e) {
      setError(errMsg(e, 'Failed to save connection.'));
      setSaving(false);
    }
  };

  const input = 'w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-400';

  return (
    <Modal title={existing ? 'Edit connection' : 'New connection'} onClose={onClose}>
      <div className="space-y-4">
        {!existing && (
          <Labeled label="Type">
            <select value={type} onChange={e => setType(e.target.value)} className={`${input} bg-white`}>
              {specs.map(s => <option key={s.type} value={s.type}>{s.label}</option>)}
            </select>
            {spec && <p className="text-xs text-gray-500 mt-1">{spec.description}</p>}
          </Labeled>
        )}
        <Labeled label="Name">
          <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Analytics DB" className={input} />
        </Labeled>

        {spec?.fields.map(f => (
          <FieldInput
            key={f.name}
            field={f}
            value={values[f.name] ?? ''}
            show={!!showSecret[f.name]}
            onToggleShow={() => setShowSecret(s => ({ ...s, [f.name]: !s[f.name] }))}
            onChange={v => set(f.name, v)}
            className={input}
          />
        ))}

        <Labeled label="Access">
          <select value={accessMode} onChange={e => setAccessMode(e.target.value as 'read_only' | 'read_write')} className={`${input} bg-white`}>
            <option value="read_only">Read-only (recommended)</option>
            <option value="read_write">Read &amp; write</option>
          </select>
        </Labeled>

        {isAdmin && (
          <Labeled label="Allow private hosts (admin)">
            <input
              value={allowlist}
              onChange={e => setAllowlist(e.target.value)}
              placeholder="db.internal, 10.0.0.5"
              className={`${input} font-mono`}
            />
            <p className="text-xs text-gray-500 mt-1">
              Comma-separated hosts that may resolve to private addresses for this connection.
            </p>
          </Labeled>
        )}

        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
            <XCircle className="w-4 h-4 flex-shrink-0" /> {error}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">Cancel</button>
          <button
            onClick={save}
            disabled={saving || !name.trim()}
            className="flex items-center gap-2 px-5 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-sm font-semibold rounded-lg"
          >
            {saving && <Loader2 className="w-4 h-4 animate-spin" />} {existing ? 'Save changes' : 'Create'}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function FieldInput({ field, value, show, onToggleShow, onChange, className }: {
  field: FieldSpec; value: string; show: boolean;
  onToggleShow: () => void; onChange: (v: string) => void; className: string;
}) {
  const saved = field.secret && value === SECRET_SENTINEL;
  return (
    <Labeled label={`${field.label}${field.required ? '' : ' (optional)'}`}>
      {field.type === 'select' ? (
        <select value={value} onChange={e => onChange(e.target.value)} className={`${className} bg-white`}>
          {(field.options ?? []).map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      ) : (
        <div className="relative">
          <input
            type={field.secret && !show ? 'password' : field.type === 'number' ? 'number' : 'text'}
            value={saved ? '' : value}
            onChange={e => onChange(e.target.value)}
            placeholder={saved ? '•••••••• saved — type to replace' : ''}
            autoComplete="off"
            className={`${className} ${field.secret ? 'pr-10' : ''}`}
          />
          {field.secret && (
            <button type="button" onClick={onToggleShow} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
              {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          )}
        </div>
      )}
      {field.help && <p className="text-xs text-gray-500 mt-1">{field.help}</p>}
    </Labeled>
  );
}

// ── Browse tables + dataset preview ─────────────────────────────────────────────

function BrowseModal({ conn, onClose }: { conn: Connection; onClose: () => void }) {
  const [tables, setTables] = useState<DiscoveredTable[] | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<DiscoveredTable | null>(null);
  const [dataset, setDataset] = useState<DatasetRef | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);

  useEffect(() => {
    connectionsApi.discover(conn.id)
      .then(r => { setTables(r.tables); setTruncated(r.truncated); })
      .catch(e => setError(errMsg(e, 'Could not list tables.')));
  }, [conn.id]);

  const open = async (t: DiscoveredTable) => {
    setSelected(t);
    setDataset(null);
    setError('');
    setLoadingPreview(true);
    try {
      setDataset(await connectionsApi.preview(conn.id, t.schema, t.name));
    } catch (e) {
      setError(errMsg(e, 'Could not preview this table.'));
    } finally {
      setLoadingPreview(false);
    }
  };

  return (
    <Modal title={`Browse · ${conn.name}`} onClose={onClose} wide>
      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
      {!tables && !error && <div className="flex justify-center py-10"><Loader2 className="w-6 h-6 animate-spin text-blue-500" /></div>}
      {tables && (
        <div className="flex gap-4 min-h-[320px]">
          <div className="w-60 flex-shrink-0 border border-gray-200 rounded-lg overflow-y-auto max-h-[60vh]">
            {tables.length === 0 && <p className="text-xs text-gray-500 p-3">No tables visible to this user.</p>}
            {tables.map(t => (
              <button
                key={`${t.schema}.${t.name}`}
                onClick={() => open(t)}
                className={`w-full text-left px-3 py-2 text-xs border-b border-gray-100 hover:bg-blue-50 ${selected === t ? 'bg-blue-50 font-semibold' : ''}`}
              >
                <span className="text-gray-400">{t.schema}.</span>{t.name}
                {t.type === 'view' && <span className="ml-1 text-[10px] text-gray-400">view</span>}
              </button>
            ))}
            {truncated && <p className="text-[11px] text-amber-700 p-2">Showing the first 500 tables.</p>}
          </div>
          <div className="flex-1 min-w-0">
            {!selected && <p className="text-sm text-gray-500 p-4">Select a table to preview its schema and a sample of rows.</p>}
            {loadingPreview && <div className="flex justify-center py-10"><Loader2 className="w-5 h-5 animate-spin text-blue-500" /></div>}
            {dataset && <DatasetTable dataset={dataset} />}
          </div>
        </div>
      )}
    </Modal>
  );
}

// ── Small shared pieces ─────────────────────────────────────────────────────────

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1.5">{label}</label>
      {children}
    </div>
  );
}

function Modal({ title, onClose, children, wide }: {
  title: string; onClose: () => void; children: React.ReactNode; wide?: boolean;
}) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className={`bg-white rounded-xl shadow-2xl w-full ${wide ? 'max-w-4xl' : 'max-w-lg'} max-h-[90vh] overflow-y-auto`}
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b sticky top-0 bg-white">
          <h2 className="text-base font-semibold text-gray-900">{title}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-5 h-5" /></button>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  );
}
