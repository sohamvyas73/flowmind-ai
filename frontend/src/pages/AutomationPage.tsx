import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft, CalendarClock, Play, Loader2, XCircle, CheckCircle2, Clock, Ban, RefreshCw, Trash2,
  Plus, ChevronDown, ChevronRight, AlertTriangle, Repeat, Power,
} from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { runsApi, schedulesApi, workflowApi, RunDetail, RunSummary, Schedule } from '@/services/api';
import type { Workflow } from '@/types/workflow';

function errMsg(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
}

const fmt = (iso?: string | null) => (iso ? new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).toLocaleString() : '—');

const CRON_PRESETS: { label: string; cron: string }[] = [
  { label: 'Every 5 minutes', cron: '*/5 * * * *' },
  { label: 'Every hour', cron: '0 * * * *' },
  { label: 'Every day at 09:00', cron: '0 9 * * *' },
  { label: 'Weekdays at 09:00', cron: '0 9 * * 1-5' },
  { label: 'Every Monday 08:00', cron: '0 8 * * 1' },
];

type Tab = 'runs' | 'schedules';

export function AutomationPage() {
  const { setView } = useAuthStore();
  const [tab, setTab] = useState<Tab>('runs');
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [workflowId, setWorkflowId] = useState<string>('');
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    workflowApi.getWorkflows()
      .then(ws => { setWorkflows(ws); if (ws[0]) setWorkflowId(ws[0].id); })
      .catch(e => setLoadError(errMsg(e, 'Failed to load workflows.')));
  }, []);

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
          <CalendarClock className="w-5 h-5 text-blue-600" /> Runs &amp; Schedules
        </h1>
        <div className="ml-auto flex bg-gray-100 rounded-lg p-0.5">
          {(['runs', 'schedules'] as Tab[]).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-1.5 text-sm font-medium rounded-md capitalize transition-colors ${tab === t ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-8 space-y-4">
        {loadError && <Banner kind="error">{loadError}</Banner>}
        {tab === 'runs'
          ? <RunsTab workflows={workflows} workflowId={workflowId} setWorkflowId={setWorkflowId} />
          : <SchedulesTab workflows={workflows} workflowId={workflowId} setWorkflowId={setWorkflowId} />}
      </div>
    </div>
  );
}

// ── Runs ────────────────────────────────────────────────────────────────────────

const STATUS_STYLE: Record<RunSummary['status'], { cls: string; icon: React.ReactNode; text: string }> = {
  pending:   { cls: 'text-gray-700 bg-gray-100',   icon: <Clock className="w-3.5 h-3.5" />,                         text: 'Queued' },
  running:   { cls: 'text-blue-700 bg-blue-100',   icon: <Loader2 className="w-3.5 h-3.5 animate-spin" />,          text: 'Running' },
  completed: { cls: 'text-green-700 bg-green-100', icon: <CheckCircle2 className="w-3.5 h-3.5" />,                  text: 'Completed' },
  failed:    { cls: 'text-red-700 bg-red-100',     icon: <XCircle className="w-3.5 h-3.5" />,                       text: 'Failed' },
  cancelled: { cls: 'text-amber-700 bg-amber-100', icon: <Ban className="w-3.5 h-3.5" />,                           text: 'Cancelled' },
};

function WorkflowSelect({ workflows, value, onChange }: {
  workflows: Workflow[]; value: string; onChange: (id: string) => void;
}) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-400 min-w-[220px]"
    >
      {workflows.length === 0 && <option value="">No saved workflows</option>}
      {workflows.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
    </select>
  );
}

function RunsTab({ workflows, workflowId, setWorkflowId }: {
  workflows: Workflow[]; workflowId: string; setWorkflowId: (id: string) => void;
}) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const [input, setInput] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const load = useCallback(async () => {
    try {
      setRuns(await runsApi.list());
    } catch (e) {
      setError(errMsg(e, 'Failed to load runs.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  // Poll while anything is still in flight
  const inFlight = useMemo(() => runs.some(r => r.status === 'pending' || r.status === 'running'), [runs]);
  useEffect(() => {
    window.clearInterval(timer.current);
    if (inFlight) timer.current = window.setInterval(() => { void load(); }, 2500);
    return () => window.clearInterval(timer.current);
  }, [inFlight, load]);

  const start = async () => {
    setError('');
    let parsed: Record<string, unknown> | undefined;
    if (input.trim()) {
      try {
        const v = JSON.parse(input);
        if (typeof v !== 'object' || v === null || Array.isArray(v)) throw new Error();
        parsed = v as Record<string, unknown>;
      } catch {
        setError('Input must be a JSON object, e.g. {"name": "Ada"}');
        return;
      }
    }
    setStarting(true);
    try {
      await runsApi.start(workflowId, parsed);
      await load();
    } catch (e) {
      setError(errMsg(e, 'Could not start the run.'));
    } finally {
      setStarting(false);
    }
  };

  const cancel = async (id: string) => {
    try {
      await runsApi.cancel(id);
      await load();
    } catch (e) {
      setError(errMsg(e, 'Could not cancel the run.'));
    }
  };

  return (
    <>
      <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-3">
        <p className="text-sm font-semibold text-gray-800">Run in background</p>
        <p className="text-xs text-gray-500">
          Starts the saved workflow on the server and returns immediately. Credits are reserved up front and
          refunded if the run is cancelled or cannot complete.
        </p>
        <div className="flex flex-wrap items-start gap-3">
          <WorkflowSelect workflows={workflows} value={workflowId} onChange={setWorkflowId} />
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder='Optional input JSON, e.g. {"customer_id": 42}'
            rows={1}
            className="flex-1 min-w-[240px] px-3 py-2 text-sm font-mono border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
          <button
            onClick={start}
            disabled={starting || !workflowId}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-sm font-semibold rounded-lg"
          >
            {starting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />} Run
          </button>
        </div>
        {error && <Banner kind="error">{error}</Banner>}
      </div>

      <div className="flex items-center justify-between pt-2">
        <p className="text-sm font-semibold text-gray-800">Run history</p>
        <button onClick={() => void load()} className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-800">
          <RefreshCw className={`w-3.5 h-3.5 ${inFlight ? 'animate-spin' : ''}`} /> {inFlight ? 'Live' : 'Refresh'}
        </button>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-blue-500" /></div>
      ) : runs.length === 0 ? (
        <div className="bg-white border border-dashed border-gray-300 rounded-xl p-10 text-center text-sm text-gray-500">
          No runs yet. Start one above, or create a schedule.
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
          {runs.map(r => (
            <RunRow
              key={r.execution_id}
              run={r}
              open={expanded === r.execution_id}
              onToggle={() => setExpanded(expanded === r.execution_id ? null : r.execution_id)}
              onCancel={() => cancel(r.execution_id)}
            />
          ))}
        </div>
      )}
    </>
  );
}

function RunRow({ run, open, onToggle, onCancel }: {
  run: RunSummary; open: boolean; onToggle: () => void; onCancel: () => void;
}) {
  const st = STATUS_STYLE[run.status];
  const cancellable = !!run.job && (run.status === 'pending' || run.status === 'running') && !run.job.cancel_requested;
  const retrying = run.job && run.job.state === 'queued' && run.job.attempts > 0;
  return (
    <div>
      <div className="flex items-center gap-3 px-5 py-3">
        <button onClick={onToggle} className="text-gray-400 hover:text-gray-600">
          {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </button>
        <span className={`flex items-center gap-1.5 text-xs font-medium rounded-full px-2.5 py-1 ${st.cls}`}>{st.icon}{st.text}</span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-gray-900 truncate">{run.workflow_name ?? run.workflow_id}</p>
          <p className="text-xs text-gray-500">
            {fmt(run.started_at)} · {run.triggered_by ?? 'manual'}
            {retrying && <span className="text-amber-700"> · retrying (attempt {run.job!.attempts + 1}/{run.job!.max_attempts})</span>}
            {run.job?.cancel_requested && run.status === 'running' && <span className="text-amber-700"> · cancelling…</span>}
          </p>
        </div>
        {run.job && (
          <span className="text-[11px] text-gray-400 hidden sm:block">job: {run.job.state.replace('_', ' ')}</span>
        )}
        {cancellable && (
          <button onClick={onCancel} className="text-xs font-medium text-red-600 hover:bg-red-50 rounded-md px-2.5 py-1">Cancel</button>
        )}
      </div>
      {open && <RunDetails id={run.execution_id} summary={run} />}
    </div>
  );
}

function RunDetails({ id, summary }: { id: string; summary: RunSummary }) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [err, setErr] = useState('');
  const settled = summary.status === 'completed' || summary.status === 'failed' || summary.status === 'cancelled';

  useEffect(() => {
    runsApi.get(id).then(setDetail).catch(e => setErr(errMsg(e, 'Failed to load run details.')));
  // reload when the run settles so output/trace appear without re-opening
  }, [id, settled]);

  if (err) return <div className="px-14 pb-4"><Banner kind="error">{err}</Banner></div>;
  if (!detail) return <div className="px-14 pb-4"><Loader2 className="w-4 h-4 animate-spin text-blue-500" /></div>;

  return (
    <div className="px-14 pb-4 space-y-3 text-xs">
      {detail.error_message && <Banner kind="error">{detail.error_message}</Banner>}
      {detail.job?.last_error && detail.status !== 'failed' && (
        <Banner kind="warn">Last attempt failed: {detail.job.last_error}</Banner>
      )}
      {detail.execution_trace && detail.execution_trace.length > 0 && (
        <div>
          <p className="font-semibold text-gray-700 mb-1">Nodes executed</p>
          <div className="flex flex-wrap gap-1.5">
            {detail.execution_trace.map((t, i) => (
              <span key={i} className="bg-gray-100 text-gray-700 rounded px-2 py-0.5 font-mono">{t.node_type}</span>
            ))}
          </div>
        </div>
      )}
      {detail.output_data && (
        <div>
          <p className="font-semibold text-gray-700 mb-1">Output <span className="font-normal text-gray-400">(sensitive fields are redacted in stored results)</span></p>
          <pre className="bg-gray-900 text-gray-100 rounded-lg p-3 overflow-auto max-h-60">{JSON.stringify(detail.output_data, null, 2)}</pre>
        </div>
      )}
      {!detail.output_data && !detail.error_message && settled && <p className="text-gray-400">No output.</p>}
    </div>
  );
}

// ── Schedules ───────────────────────────────────────────────────────────────────

function SchedulesTab({ workflows, workflowId, setWorkflowId }: {
  workflows: Workflow[]; workflowId: string; setWorkflowId: (id: string) => void;
}) {
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [name, setName] = useState('');
  const [cron, setCron] = useState(CRON_PRESETS[2].cron);
  const [tz, setTz] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC');
  const [input, setInput] = useState('');
  const [saving, setSaving] = useState(false);

  const timezones = useMemo(() => {
    const supported = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.('timeZone');
    const list = supported && supported.length ? supported : ['UTC', 'Asia/Kolkata', 'America/New_York', 'Europe/London'];
    return list.includes('UTC') ? list : ['UTC', ...list];
  }, []);

  const load = useCallback(async () => {
    try {
      setSchedules(await schedulesApi.list());
    } catch (e) {
      setError(errMsg(e, 'Failed to load schedules.'));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const create = async () => {
    setError('');
    let parsed: Record<string, unknown> | undefined;
    if (input.trim()) {
      try {
        const v = JSON.parse(input);
        if (typeof v !== 'object' || v === null || Array.isArray(v)) throw new Error();
        parsed = v as Record<string, unknown>;
      } catch {
        setError('Input must be a JSON object, e.g. {"name": "Ada"}');
        return;
      }
    }
    setSaving(true);
    try {
      await schedulesApi.create({
        workflow_id: workflowId, name: name.trim() || 'Schedule', cron: cron.trim(), timezone: tz, input_data: parsed,
      });
      setName('');
      setInput('');
      await load();
    } catch (e) {
      setError(errMsg(e, 'Could not create the schedule.'));
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (s: Schedule) => {
    try {
      await schedulesApi.update(s.id, { enabled: !s.enabled });
      await load();
    } catch (e) {
      setError(errMsg(e, 'Could not update the schedule.'));
    }
  };

  const remove = async (s: Schedule) => {
    if (!window.confirm(`Delete schedule "${s.name}"?`)) return;
    try {
      await schedulesApi.remove(s.id);
      await load();
    } catch (e) {
      setError(errMsg(e, 'Could not delete the schedule.'));
    }
  };

  const field = 'px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-400';

  return (
    <>
      <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-3">
        <p className="text-sm font-semibold text-gray-800">New schedule</p>
        <div className="flex flex-wrap gap-3">
          <WorkflowSelect workflows={workflows} value={workflowId} onChange={setWorkflowId} />
          <input value={name} onChange={e => setName(e.target.value)} placeholder="Name (optional)" className={`${field} w-48`} />
          <select
            value={CRON_PRESETS.some(p => p.cron === cron) ? cron : ''}
            onChange={e => e.target.value && setCron(e.target.value)}
            className={`${field} bg-white`}
          >
            <option value="">Custom…</option>
            {CRON_PRESETS.map(p => <option key={p.cron} value={p.cron}>{p.label}</option>)}
          </select>
          <input value={cron} onChange={e => setCron(e.target.value)} className={`${field} w-40 font-mono`} title="min hour day month weekday" />
          <select value={tz} onChange={e => setTz(e.target.value)} className={`${field} bg-white w-52`}>
            {timezones.map(z => <option key={z} value={z}>{z}</option>)}
          </select>
        </div>
        <textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder='Optional input JSON passed to every run, e.g. {"region": "EU"}'
          rows={1}
          className={`${field} w-full font-mono`}
        />
        <div className="flex items-center justify-between">
          <p className="text-xs text-gray-500">
            Cron format: <span className="font-mono">minute hour day month weekday</span>. Minimum interval applies. Missed runs while the server
            was down are collapsed into one.
          </p>
          <button
            onClick={create}
            disabled={saving || !workflowId}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-sm font-semibold rounded-lg"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />} Create
          </button>
        </div>
        {error && <Banner kind="error">{error}</Banner>}
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-blue-500" /></div>
      ) : schedules.length === 0 ? (
        <div className="bg-white border border-dashed border-gray-300 rounded-xl p-10 text-center text-sm text-gray-500">
          <Repeat className="w-8 h-8 text-gray-300 mx-auto mb-2" />
          No schedules yet.
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
          {schedules.map(s => (
            <div key={s.id} className="flex items-center gap-4 px-5 py-3">
              <button
                onClick={() => toggle(s)}
                className={`p-1.5 rounded-md ${s.enabled ? 'text-green-600 hover:bg-green-50' : 'text-gray-400 hover:bg-gray-100'}`}
                title={s.enabled ? 'Enabled — click to pause' : 'Paused — click to enable'}
              >
                <Power className="w-4 h-4" />
              </button>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-gray-900 truncate">
                  {s.name} <span className="text-gray-400 font-normal">· {s.workflow_name ?? s.workflow_id}</span>
                </p>
                <p className="text-xs text-gray-500">
                  <span className="font-mono">{s.cron}</span> ({s.timezone}) ·{' '}
                  {s.enabled ? <>next: {fmt(s.next_run_at)}</> : 'paused'}
                  {s.last_run_at && <> · last: {fmt(s.last_run_at)}</>}
                </p>
                {s.last_status && (
                  <p className={`text-xs mt-0.5 flex items-center gap-1 ${s.last_status === 'queued' ? 'text-green-700' : 'text-amber-700'}`}>
                    {s.last_status !== 'queued' && <AlertTriangle className="w-3 h-3" />}
                    {s.last_status === 'queued' ? 'Last fire: run queued' : s.last_status}
                  </p>
                )}
              </div>
              <button onClick={() => remove(s)} className="p-1.5 text-gray-500 hover:bg-red-50 hover:text-red-600 rounded-md" title="Delete">
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function Banner({ kind, children }: { kind: 'error' | 'warn'; children: React.ReactNode }) {
  const cls = kind === 'error' ? 'bg-red-50 border-red-200 text-red-700' : 'bg-amber-50 border-amber-200 text-amber-800';
  return (
    <div className={`flex items-start gap-2 border rounded-lg px-3 py-2 text-sm ${cls}`}>
      {kind === 'error' ? <XCircle className="w-4 h-4 flex-shrink-0 mt-0.5" /> : <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />}
      <span className="break-words min-w-0">{children}</span>
    </div>
  );
}
