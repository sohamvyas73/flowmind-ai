import { useState, useEffect } from 'react';
import {
  Users, BarChart3, Zap, Globe, Workflow, ArrowLeft,
  Brain, RefreshCw, Shield, CheckCircle,
  TrendingUp, Activity, CreditCard, ScanLine, ChevronDown, ChevronRight,
  Settings, Eye, EyeOff, Save, Cpu, UserCheck, Clock, Plus, Minus,
  List, PieChart, RotateCcw, Edit3,
} from 'lucide-react';
import { adminApi, AdminUser, CreditBreakdown, RawCreditRow, ConnectorUsage, AdminWorkflow, PlatformSettings } from '@/services/api';
import { useAuthStore } from '@/store/authStore';

type Section = 'overview' | 'users' | 'credits' | 'connectors' | 'workflows' | 'platform';

const NODE_LABELS: Record<string, string> = {
  aiNode: 'AI Agent', verificationNode: 'Verification', decisionNode: 'Decision',
  indianKycNode: 'Indian KYC', httpNode: 'HTTP Request', codeNode: 'Code Runner',
  transformNode: 'Transform', ruleNode: 'Rule Engine', validatorNode: 'Validator',
  switchNode: 'Switch', formatterNode: 'Formatter', aggregatorNode: 'Aggregator',
  humanReviewNode: 'Human Review', inputNode: 'Input', outputNode: 'Output',
};

// Flat-rate nodes (credits/call)
const CREDIT_COSTS: Record<string, number> = {
  indianKycNode: 15, httpNode: 2, codeNode: 2,
  transformNode: 1, ruleNode: 1, validatorNode: 1,
  switchNode: 1, formatterNode: 1, aggregatorNode: 1,
  humanReviewNode: 1, inputNode: 0, outputNode: 0,
};

// Token-based nodes — billed at 1 credit per 1,000 tokens (min 1)
const TOKEN_BASED_NODES = new Set(['aiNode', 'verificationNode', 'decisionNode']);
const TOKENS_PER_CREDIT = 1000;

function StatCard({ label, value, sub, icon: Icon, color }: {
  label: string; value: string | number; sub?: string;
  icon: React.FC<{ className?: string }>; color: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 flex items-start gap-4">
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${color}`}>
        <Icon className="w-5 h-5" />
      </div>
      <div>
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
        <p className="text-2xl font-bold text-gray-900 mt-0.5">{value}</p>
        {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}

function Badge({ label, color }: { label: string; color: string }) {
  return <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${color}`}>{label}</span>;
}

// ── Overview ──────────────────────────────────────────────────────────────────

function OverviewSection() {
  const [stats, setStats] = useState<any>(null);
  useEffect(() => { adminApi.getStats().then(setStats); }, []);
  if (!stats) return <Spinner />;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Users" value={stats.total_users} icon={Users} color="bg-blue-100 text-blue-600" />
        <StatCard label="Workflows" value={stats.total_workflows} icon={Workflow} color="bg-purple-100 text-purple-600" />
        <StatCard label="Executions" value={stats.total_executions}
          sub={`${stats.success_rate}% success rate`} icon={Activity} color="bg-green-100 text-green-600" />
        <StatCard label="Credits Consumed" value={stats.total_credits_consumed.toLocaleString()}
          sub={`${stats.total_credits_remaining?.toLocaleString() ?? '—'} remaining across all users`}
          icon={CreditCard} color="bg-amber-100 text-amber-600" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
            <CheckCircle className="w-4 h-4 text-green-500" /> Execution Results
          </p>
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">Completed</span>
              <span className="font-semibold text-green-700">{stats.completed_executions}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">Failed</span>
              <span className="font-semibold text-red-600">{stats.failed_executions}</span>
            </div>
            {stats.total_executions > 0 && (
              <div className="mt-2">
                <div className="w-full bg-gray-100 rounded-full h-2">
                  <div
                    className="bg-green-500 h-2 rounded-full transition-all"
                    style={{ width: `${stats.success_rate}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
            <Globe className="w-4 h-4 text-orange-500" /> Third-Party Connectors
          </p>
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">Indian KYC calls</span>
              <span className="font-semibold">{stats.third_party.kyc_calls}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">HTTP API calls</span>
              <span className="font-semibold">{stats.third_party.http_calls}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">AI model calls</span>
              <span className="font-semibold">{stats.third_party.ai_calls}</span>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-blue-500" /> Credit Pricing Guide
          </p>
          <div className="space-y-1.5">
            {[
              ['AI / Verify / Decision', '1 cr / 1K tokens'],
              ['Indian KYC', '15 cr flat'],
              ['HTTP / Code', '2 cr flat'],
              ['Other nodes', '1 cr flat'],
              ['Input / Output', 'Free'],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs">
                <span className="text-gray-500">{k}</span>
                <span className={`font-medium ${v.includes('token') ? 'text-purple-700' : 'text-gray-700'}`}>{v}</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-gray-400 mt-2 border-t border-gray-100 pt-2">AI nodes: min 1 cr per call</p>
        </div>
      </div>
    </div>
  );
}

// ── Users ─────────────────────────────────────────────────────────────────────

type CreditAction = { type: 'set' | 'add' | 'sub'; value: number } | null;

function UsersSection() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [creditAction, setCreditAction] = useState<Record<string, CreditAction>>({});
  const [customVal, setCustomVal] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => { adminApi.getUsers().then(setUsers); }, []);

  const applyCredit = async (user: AdminUser, action: CreditAction) => {
    if (!action) return;
    setSaving(user.id);
    try {
      const payload =
        action.type === 'set' ? { credits_total: action.value } :
        action.type === 'add' ? { add_credits: action.value } :
        { subtract_credits: action.value };
      const updated = await adminApi.updateUser(user.id, payload);
      setUsers(u => u.map(x => x.id === user.id ? { ...x, credits_total: updated.credits_total, credits_used: updated.credits_used } : x));
      setCreditAction(a => { const n = { ...a }; delete n[user.id]; return n; });
      setCustomVal(v => { const n = { ...v }; delete n[user.id]; return n; });
    } finally {
      setSaving(null);
    }
  };

  const resetUsed = async (user: AdminUser) => {
    setSaving(user.id + '_reset');
    try {
      const updated = await adminApi.updateUser(user.id, { reset_credits_used: true });
      setUsers(u => u.map(x => x.id === user.id ? { ...x, credits_used: updated.credits_used } : x));
    } finally {
      setSaving(null);
    }
  };

  const toggleActive = async (user: AdminUser) => {
    await adminApi.updateUser(user.id, { is_active: !user.is_active });
    setUsers(u => u.map(x => x.id === user.id ? { ...x, is_active: !user.is_active } : x));
  };

  const pending = users.filter(u => !u.is_active && u.role !== 'admin');
  const active  = users.filter(u => u.is_active  || u.role === 'admin');

  const UserRow = ({ user }: { user: AdminUser }) => {
    const remaining = user.credits_total - user.credits_used;
    const pct = Math.min(100, (user.credits_used / Math.max(user.credits_total, 1)) * 100);
    const barColor = pct > 90 ? 'bg-red-500' : pct > 70 ? 'bg-amber-500' : 'bg-green-500';
    const action = creditAction[user.id];
    const isSaving = saving === user.id;
    const isResetting = saving === user.id + '_reset';

    return (
      <tr className="hover:bg-gray-50/50 transition-colors align-top">
        {/* User */}
        <td className="px-4 py-3">
          <p className="font-medium text-gray-900">{user.full_name || '—'}</p>
          <p className="text-xs text-gray-400 font-mono">{user.email}</p>
        </td>
        {/* Role */}
        <td className="px-4 py-3">
          <Badge label={user.role} color={user.role === 'admin' ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-600'} />
        </td>
        {/* Workflows / Executions */}
        <td className="px-4 py-3 text-gray-700 font-medium">{user.workflow_count}</td>
        <td className="px-4 py-3 text-gray-700 font-medium">{user.execution_count}</td>

        {/* Credits block */}
        <td className="px-4 py-3 min-w-[220px]">
          {/* Summary row */}
          <div className="flex items-baseline gap-1.5 text-sm">
            <span className="font-bold text-gray-900">{remaining.toLocaleString()}</span>
            <span className="text-gray-400 text-xs">remaining</span>
            <span className="text-gray-300">·</span>
            <span className="text-gray-500 text-xs">{user.credits_used} used / {user.credits_total} total</span>
          </div>
          {/* Bar */}
          <div className="mt-1 mb-2 w-full bg-gray-100 rounded-full h-1.5">
            <div className={`h-1.5 rounded-full transition-all ${barColor}`} style={{ width: `${pct}%` }} />
          </div>

          {/* Quick action buttons */}
          {!action ? (
            <div className="flex flex-wrap gap-1">
              {[50, 100, 500].map(n => (
                <button key={n} onClick={() => applyCredit(user, { type: 'add', value: n })}
                  className="flex items-center gap-0.5 text-xs px-2 py-0.5 rounded bg-green-50 text-green-700 border border-green-200 hover:bg-green-100 font-medium">
                  <Plus className="w-3 h-3" />{n}
                </button>
              ))}
              <button onClick={() => setCreditAction(a => ({ ...a, [user.id]: { type: 'sub', value: 0 } }))}
                className="flex items-center gap-0.5 text-xs px-2 py-0.5 rounded bg-red-50 text-red-600 border border-red-200 hover:bg-red-100 font-medium">
                <Minus className="w-3 h-3" />Remove
              </button>
              <button onClick={() => { setCreditAction(a => ({ ...a, [user.id]: { type: 'set', value: user.credits_total } })); setCustomVal(v => ({ ...v, [user.id]: String(user.credits_total) })); }}
                className="flex items-center gap-0.5 text-xs px-2 py-0.5 rounded bg-blue-50 text-blue-600 border border-blue-200 hover:bg-blue-100 font-medium">
                <Edit3 className="w-3 h-3" />Set
              </button>
              <button onClick={() => resetUsed(user)} disabled={isResetting || user.credits_used === 0}
                className="flex items-center gap-0.5 text-xs px-2 py-0.5 rounded bg-gray-50 text-gray-500 border border-gray-200 hover:bg-gray-100 font-medium disabled:opacity-40">
                <RotateCcw className="w-3 h-3" />{isResetting ? '…' : 'Reset Used'}
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-1 flex-wrap">
              <span className="text-xs text-gray-500 font-medium">
                {action.type === 'add' ? 'Add:' : action.type === 'sub' ? 'Remove:' : 'Set total:'}
              </span>
              <input
                type="number" min={0} autoFocus
                value={customVal[user.id] ?? (action.type === 'set' ? String(user.credits_total) : '')}
                onChange={e => {
                  const v = e.target.value;
                  setCustomVal(cv => ({ ...cv, [user.id]: v }));
                  setCreditAction(a => ({ ...a, [user.id]: { ...action!, value: parseInt(v) || 0 } }));
                }}
                className="w-20 px-2 py-0.5 text-xs border border-blue-400 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <button onClick={() => applyCredit(user, action)} disabled={isSaving}
                className="text-xs px-2 py-0.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
                {isSaving ? '…' : 'Save'}
              </button>
              <button onClick={() => { setCreditAction(a => { const n = { ...a }; delete n[user.id]; return n; }); setCustomVal(v => { const n = { ...v }; delete n[user.id]; return n; }); }}
                className="text-xs text-gray-400 hover:text-gray-600">✕</button>
            </div>
          )}
        </td>

        {/* Status */}
        <td className="px-4 py-3">
          <Badge label={user.is_active ? 'Active' : 'Pending'}
            color={user.is_active ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'} />
        </td>
        {/* Joined */}
        <td className="px-4 py-3 text-xs text-gray-400">
          {user.created_at ? new Date(user.created_at).toLocaleDateString() : '—'}
        </td>
        {/* Activate/Deactivate */}
        <td className="px-4 py-3">
          <button onClick={() => toggleActive(user)}
            className={`text-xs px-2.5 py-1 rounded-md font-medium transition-colors ${
              user.is_active ? 'bg-red-50 text-red-600 hover:bg-red-100' : 'bg-green-600 text-white hover:bg-green-700'
            }`}>
            {user.is_active ? 'Deactivate' : 'Approve'}
          </button>
        </td>
      </tr>
    );
  };

  const HEADERS = ['User', 'Role', 'Workflows', 'Executions', 'Credits', 'Status', 'Joined', 'Action'];

  const Table = ({ rows, amber }: { rows: AdminUser[]; amber?: boolean }) => (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className={`text-xs uppercase tracking-wide ${amber ? 'bg-amber-50/50 text-amber-700' : 'bg-gray-50 text-gray-500'}`}>
          <tr>{HEADERS.map(h => <th key={h} className="px-4 py-3 text-left font-medium">{h}</th>)}</tr>
        </thead>
        <tbody className={`divide-y ${amber ? 'divide-amber-50' : 'divide-gray-50'}`}>
          {rows.map(u => <UserRow key={u.id} user={u} />)}
        </tbody>
      </table>
    </div>
  );

  return (
    <div className="space-y-6">
      {pending.length > 0 && (
        <div className="bg-white rounded-xl border-2 border-amber-300 overflow-hidden">
          <div className="px-5 py-4 border-b border-amber-100 bg-amber-50 flex items-center gap-3">
            <Clock className="w-4 h-4 text-amber-600" />
            <div>
              <p className="font-semibold text-amber-800">Pending Approval ({pending.length})</p>
              <p className="text-xs text-amber-600">These users signed up and are waiting for your approval.</p>
            </div>
          </div>
          <Table rows={pending} amber />
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center gap-2">
          <UserCheck className="w-4 h-4 text-green-600" />
          <p className="font-semibold text-gray-800">All Users ({active.length})</p>
        </div>
        <Table rows={active} />
        {active.length === 0 && (
          <p className="px-4 py-8 text-center text-gray-400 text-sm">No active users yet.</p>
        )}
      </div>
    </div>
  );
}

// ── Credit Usage ──────────────────────────────────────────────────────────────

function CreditsSection() {
  const [tab, setTab] = useState<'summary' | 'transactions' | 'pricing'>('summary');
  const [summary, setSummary] = useState<CreditBreakdown[]>([]);
  const [raw, setRaw] = useState<RawCreditRow[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [filterUser, setFilterUser] = useState('');
  const [loadingRaw, setLoadingRaw] = useState(false);

  useEffect(() => { adminApi.getCreditUsage().then(setSummary); }, []);

  const loadRaw = async (userId?: string) => {
    setLoadingRaw(true);
    try { setRaw(await adminApi.getRawCreditUsage(userId)); }
    finally { setLoadingRaw(false); }
  };

  useEffect(() => { if (tab === 'transactions') loadRaw(); }, [tab]);

  const toggle = (uid: string) =>
    setExpanded(s => { const n = new Set(s); n.has(uid) ? n.delete(uid) : n.add(uid); return n; });

  const filteredRaw = filterUser
    ? raw.filter(r => r.email.toLowerCase().includes(filterUser.toLowerCase()))
    : raw;

  const uniqueEmails = [...new Set(raw.map(r => r.email))];

  return (
    <div className="space-y-4">
      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit">
        {([
          { id: 'summary',      label: 'Summary',      icon: PieChart },
          { id: 'transactions', label: 'Transactions',  icon: List },
          { id: 'pricing',      label: 'Pricing Guide', icon: CreditCard },
        ] as const).map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              tab === id ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}>
            <Icon className="w-3.5 h-3.5" />{label}
          </button>
        ))}
      </div>

      {/* Summary — grouped accordion */}
      {tab === 'summary' && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
            <div>
              <p className="font-semibold text-gray-800">Credit Usage by User</p>
              <p className="text-xs text-gray-400 mt-0.5">Expand to see per-node breakdown</p>
            </div>
            <p className="text-xs font-semibold text-gray-500 bg-gray-100 px-2 py-1 rounded">
              Total: {summary.reduce((s, r) => s + r.total_credits, 0).toLocaleString()} cr
            </p>
          </div>
          <div className="divide-y divide-gray-100">
            {summary.map(row => (
              <div key={row.user_id}>
                <button onClick={() => toggle(row.user_id)}
                  className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-gray-50 transition-colors text-left">
                  <div className="flex items-center gap-3">
                    {expanded.has(row.user_id)
                      ? <ChevronDown className="w-4 h-4 text-gray-400" />
                      : <ChevronRight className="w-4 h-4 text-gray-400" />}
                    <div>
                      <p className="text-sm font-medium text-gray-900">{row.email}</p>
                      <p className="text-xs text-gray-400">{row.breakdown.length} node type{row.breakdown.length !== 1 ? 's' : ''}</p>
                    </div>
                  </div>
                  <p className="text-sm font-bold text-gray-900">{row.total_credits.toLocaleString()} cr</p>
                </button>
                {expanded.has(row.user_id) && (
                  <div className="bg-gray-50 px-5 pb-3">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-gray-400 uppercase tracking-wide">
                          <th className="text-left py-1.5 pl-7">Node Type</th>
                          <th className="text-right py-1.5">Calls</th>
                          <th className="text-right py-1.5">Credits Used</th>
                          <th className="text-right py-1.5">Cost/call</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {row.breakdown.sort((a, b) => b.credits - a.credits).map(b => (
                          <tr key={b.node_type}>
                            <td className="py-1.5 pl-7 text-gray-700 font-medium">{NODE_LABELS[b.node_type] || b.node_type}</td>
                            <td className="py-1.5 text-right text-gray-600">{b.calls}</td>
                            <td className="py-1.5 text-right font-semibold text-gray-900">{b.credits}</td>
                            <td className="py-1.5 text-right text-gray-400">
                          {TOKEN_BASED_NODES.has(b.node_type)
                            ? `1/${TOKENS_PER_CREDIT / 1000}K tok`
                            : (CREDIT_COSTS[b.node_type] ?? '—')}
                        </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ))}
            {summary.length === 0 && (
              <p className="px-5 py-8 text-center text-gray-400 text-sm">No credit usage recorded yet.</p>
            )}
          </div>
        </div>
      )}

      {/* Transactions — raw rows */}
      {tab === 'transactions' && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between flex-wrap gap-3">
            <div>
              <p className="font-semibold text-gray-800">Raw Transactions</p>
              <p className="text-xs text-gray-400 mt-0.5">Every credit deduction, newest first (last 200)</p>
            </div>
            <div className="flex items-center gap-2">
              <select value={filterUser} onChange={e => setFilterUser(e.target.value)}
                className="text-xs px-2.5 py-1.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white">
                <option value="">All users</option>
                {uniqueEmails.map(e => <option key={e} value={e}>{e}</option>)}
              </select>
              <button onClick={() => loadRaw()} disabled={loadingRaw}
                className="flex items-center gap-1 text-xs px-2.5 py-1.5 bg-gray-100 hover:bg-gray-200 rounded-lg text-gray-600 transition-colors disabled:opacity-50">
                <RefreshCw className={`w-3.5 h-3.5 ${loadingRaw ? 'animate-spin' : ''}`} />Refresh
              </button>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 text-gray-500 uppercase tracking-wide">
                <tr>
                  {['Time', 'User', 'Node', 'Credits', 'Description', 'Execution ID'].map(h => (
                    <th key={h} className="px-4 py-2.5 text-left font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filteredRaw.map(row => (
                  <tr key={row.id} className="hover:bg-gray-50/50">
                    <td className="px-4 py-2.5 text-gray-400 whitespace-nowrap">
                      {row.created_at ? new Date(row.created_at).toLocaleString() : '—'}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-gray-600">{row.email}</td>
                    <td className="px-4 py-2.5">
                      <span className="px-1.5 py-0.5 bg-gray-100 rounded text-gray-700 font-medium">
                        {NODE_LABELS[row.node_type] || row.node_type}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 font-bold text-amber-700">−{row.credits}</td>
                    <td className="px-4 py-2.5 text-gray-500 max-w-xs truncate">{row.description || '—'}</td>
                    <td className="px-4 py-2.5 font-mono text-gray-400">
                      {row.execution_id ? row.execution_id.slice(0, 8) + '…' : '—'}
                    </td>
                  </tr>
                ))}
                {filteredRaw.length === 0 && !loadingRaw && (
                  <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">No transactions found.</td></tr>
                )}
                {loadingRaw && (
                  <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">Loading…</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Pricing guide */}
      {tab === 'pricing' && (
        <div className="space-y-4">
          {/* Token-based section */}
          <div className="bg-white rounded-xl border border-purple-200 overflow-hidden">
            <div className="px-5 py-4 border-b border-purple-100 bg-purple-50 flex items-center gap-2">
              <Brain className="w-4 h-4 text-purple-600" />
              <div>
                <p className="font-semibold text-purple-900">Token-Based Billing</p>
                <p className="text-xs text-purple-600 mt-0.5">
                  1 credit per {TOKENS_PER_CREDIT.toLocaleString()} tokens (input + output combined) · minimum 1 credit per call
                </p>
              </div>
            </div>
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
                <tr>
                  <th className="px-5 py-3 text-left font-medium">Node</th>
                  <th className="px-5 py-3 text-left font-medium">Type Key</th>
                  <th className="px-5 py-3 text-right font-medium">Cost Formula</th>
                  <th className="px-5 py-3 text-right font-medium">Example (2K tokens)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {['aiNode', 'verificationNode', 'decisionNode'].map(type => (
                  <tr key={type} className="hover:bg-gray-50/50">
                    <td className="px-5 py-3 font-medium text-gray-800">{NODE_LABELS[type] || type}</td>
                    <td className="px-5 py-3 font-mono text-xs text-gray-400">{type}</td>
                    <td className="px-5 py-3 text-right">
                      <span className="font-bold text-purple-600">⌈tokens ÷ {TOKENS_PER_CREDIT}⌉ cr</span>
                    </td>
                    <td className="px-5 py-3 text-right text-sm font-semibold text-gray-700">2 cr</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Flat-rate section */}
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-100">
              <p className="font-semibold text-gray-800">Flat-Rate Billing</p>
              <p className="text-xs text-gray-400 mt-0.5">Fixed credit cost per node execution, regardless of data size</p>
            </div>
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
                <tr>
                  <th className="px-5 py-3 text-left font-medium">Node</th>
                  <th className="px-5 py-3 text-left font-medium">Type Key</th>
                  <th className="px-5 py-3 text-right font-medium">Credits / call</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {Object.entries(CREDIT_COSTS).sort((a, b) => b[1] - a[1]).map(([type, cost]) => (
                  <tr key={type} className="hover:bg-gray-50/50">
                    <td className="px-5 py-3 font-medium text-gray-800">{NODE_LABELS[type] || type}</td>
                    <td className="px-5 py-3 font-mono text-xs text-gray-400">{type}</td>
                    <td className="px-5 py-3 text-right">
                      <span className={`font-bold ${cost === 0 ? 'text-gray-400' : cost >= 10 ? 'text-red-600' : cost >= 2 ? 'text-amber-600' : 'text-green-600'}`}>
                        {cost === 0 ? 'Free' : `${cost} cr`}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Connectors ────────────────────────────────────────────────────────────────

function ConnectorsSection() {
  const [data, setData] = useState<ConnectorUsage[]>([]);
  useEffect(() => { adminApi.getConnectors().then(setData); }, []);

  const icon = (c: string) => c === 'indianKycNode'
    ? <ScanLine className="w-3.5 h-3.5 text-fuchsia-600" />
    : <Globe className="w-3.5 h-3.5 text-orange-500" />;

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100">
        <p className="font-semibold text-gray-800">Third-Party Connector Usage</p>
        <p className="text-xs text-gray-400 mt-0.5">Indian KYC (15 cr/call) and HTTP (2 cr/call) requests per user</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
            <tr>
              {['User', 'Connector', 'Details', 'Calls', 'Credits Used'].map(h => (
                <th key={h} className="px-4 py-3 text-left font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {data.map((row, i) => (
              <tr key={i} className="hover:bg-gray-50/50">
                <td className="px-4 py-3 text-xs text-gray-500 font-mono">{row.email}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1.5">
                    {icon(row.connector)}
                    <span className="text-xs font-medium">{NODE_LABELS[row.connector] || row.connector}</span>
                  </div>
                </td>
                <td className="px-4 py-3 text-xs text-gray-500 max-w-xs truncate">{row.description || '—'}</td>
                <td className="px-4 py-3 font-semibold text-gray-900">{row.call_count}</td>
                <td className="px-4 py-3 font-semibold text-amber-700">{row.credits_used}</td>
              </tr>
            ))}
            {data.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400 text-sm">No connector usage yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Workflows ─────────────────────────────────────────────────────────────────

function WorkflowsSection() {
  const [data, setData] = useState<AdminWorkflow[]>([]);
  useEffect(() => { adminApi.getWorkflows().then(setData); }, []);

  const statusColor: Record<string, string> = {
    draft: 'bg-gray-100 text-gray-600',
    active: 'bg-green-100 text-green-700',
    paused: 'bg-amber-100 text-amber-700',
    archived: 'bg-red-100 text-red-600',
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100">
        <p className="font-semibold text-gray-800">All Workflows ({data.length})</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
            <tr>
              {['Workflow', 'Owner', 'Status', 'Nodes', 'Executions', 'Created'].map(h => (
                <th key={h} className="px-4 py-3 text-left font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {data.map(wf => (
              <tr key={wf.id} className="hover:bg-gray-50/50">
                <td className="px-4 py-3">
                  <p className="font-medium text-gray-900 max-w-[200px] truncate">{wf.name}</p>
                  <p className="text-xs text-gray-400 font-mono">{wf.id.slice(0, 8)}…</p>
                </td>
                <td className="px-4 py-3 text-xs text-gray-500">{wf.owner_email}</td>
                <td className="px-4 py-3">
                  <Badge label={wf.status} color={statusColor[wf.status] || 'bg-gray-100 text-gray-600'} />
                </td>
                <td className="px-4 py-3 text-gray-700">{wf.node_count}</td>
                <td className="px-4 py-3 font-semibold text-gray-900">{wf.execution_count}</td>
                <td className="px-4 py-3 text-xs text-gray-400">
                  {wf.created_at ? new Date(wf.created_at).toLocaleDateString() : '—'}
                </td>
              </tr>
            ))}
            {data.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400 text-sm">No workflows yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Platform Settings ─────────────────────────────────────────────────────────

const OPENAI_MODELS   = ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo', 'o1-mini'];
const ANTHROPIC_MODELS = ['claude-opus-4-8', 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001'];
const GEMINI_MODELS   = ['gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-2.0-flash', 'gemini-2.5-pro'];

interface ProviderDraft { apiKey: string; model: string; showKey: boolean; }
const EMPTY: ProviderDraft = { apiKey: '', model: '', showKey: false };

function PlatformSettingsSection() {
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [openai,    setOpenai]    = useState<ProviderDraft>(EMPTY);
  const [anthropic, setAnthropic] = useState<ProviderDraft>(EMPTY);
  const [gemini,    setGemini]    = useState<ProviderDraft>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    adminApi.getPlatformSettings().then(s => {
      setSettings(s);
      setOpenai(d => ({ ...d, model: s.openai.model }));
      setAnthropic(d => ({ ...d, model: s.anthropic.model }));
      setGemini(d => ({ ...d, model: s.gemini.model }));
    });
  }, []);

  const save = async () => {
    setSaving(true);
    setSaved(false);
    try {
      const payload: Record<string, unknown> = {};
      if (openai.apiKey) payload.openai_api_key = openai.apiKey;
      if (openai.model) payload.openai_model = openai.model;
      if (anthropic.apiKey) payload.anthropic_api_key = anthropic.apiKey;
      if (anthropic.model) payload.anthropic_model = anthropic.model;
      if (gemini.apiKey) payload.gemini_api_key = gemini.apiKey;
      if (gemini.model) payload.gemini_model = gemini.model;
      const updated = await adminApi.updatePlatformSettings(payload as any);
      setSettings(updated);
      setOpenai(d => ({ ...d, apiKey: '' }));
      setAnthropic(d => ({ ...d, apiKey: '' }));
      setGemini(d => ({ ...d, apiKey: '' }));
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } finally {
      setSaving(false);
    }
  };

  if (!settings) return <Spinner />;

  const ProvCard = ({
    label, icon, models, cfg, draft, onChange, isActive,
  }: {
    label: string; icon: string; models: string[];
    cfg: PlatformSettings['openai']; draft: ProviderDraft;
    onChange: (fn: (d: ProviderDraft) => ProviderDraft) => void;
    isActive?: boolean;
  }) => (
    <div className={`bg-white rounded-xl border ${isActive ? 'border-blue-300' : 'border-gray-200'} p-5 space-y-4`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xl">{icon}</span>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-gray-900">{label}</h3>
              {isActive && <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-medium flex items-center gap-1"><Zap className="w-3 h-3" />Active</span>}
            </div>
          </div>
        </div>
        <div className="text-right">
          {cfg.api_key_set
            ? <span className="text-xs text-green-600 font-medium flex items-center gap-1"><CheckCircle className="w-3.5 h-3.5" />{cfg.api_key_masked}</span>
            : <span className="text-xs text-gray-400">No key set</span>}
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1.5">API Key (platform default)</label>
        <div className="relative">
          <input
            type={draft.showKey ? 'text' : 'password'}
            placeholder={cfg.api_key_set ? 'Enter new key to replace…' : 'Set platform default key…'}
            value={draft.apiKey}
            onChange={e => onChange(d => ({ ...d, apiKey: e.target.value }))}
            className="w-full px-3 py-2 pr-10 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-400 font-mono"
          />
          <button
            onClick={() => onChange(d => ({ ...d, showKey: !d.showKey }))}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
          >
            {draft.showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
          </button>
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1.5">
          <Cpu className="inline w-3 h-3 mr-1" />Default Model
        </label>
        <select
          value={draft.model}
          onChange={e => onChange(d => ({ ...d, model: e.target.value }))}
          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-400 bg-white"
        >
          {models.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="bg-purple-50 border border-purple-200 rounded-xl p-4 flex gap-3">
        <Shield className="w-4 h-4 text-purple-600 flex-shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-semibold text-purple-800">Platform-wide model defaults</p>
          <p className="text-sm text-purple-700 mt-0.5">
            These keys and models are used when users haven't configured their own.
            Users can override per-provider in their Settings page.
            AI nodes currently use the Gemini engine.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5">
        <ProvCard label="OpenAI" icon="🟢" models={OPENAI_MODELS} cfg={settings.openai}
          draft={openai} onChange={setOpenai} />
        <ProvCard label="Anthropic" icon="🟠" models={ANTHROPIC_MODELS} cfg={settings.anthropic}
          draft={anthropic} onChange={setAnthropic} />
        <ProvCard label="Google Gemini" icon="🔵" models={GEMINI_MODELS} cfg={settings.gemini}
          draft={gemini} onChange={setGemini} isActive />
      </div>

      <div className="flex items-center justify-between">
        {saved && (
          <span className="text-sm text-green-600 flex items-center gap-1.5">
            <CheckCircle className="w-4 h-4" /> Platform settings saved!
          </span>
        )}
        <button
          onClick={save}
          disabled={saving}
          className="ml-auto flex items-center gap-2 px-5 py-2.5 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-400 text-white text-sm font-semibold rounded-lg transition-colors"
        >
          {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          {saving ? 'Saving…' : 'Save Platform Settings'}
        </button>
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <div className="flex items-center justify-center py-16">
      <RefreshCw className="w-6 h-6 text-gray-400 animate-spin" />
    </div>
  );
}

// ── Main Admin Panel ──────────────────────────────────────────────────────────

const NAV: { id: Section; label: string; icon: React.FC<{ className?: string }> }[] = [
  { id: 'overview',   label: 'Overview',          icon: BarChart3 },
  { id: 'users',      label: 'Users',              icon: Users },
  { id: 'credits',    label: 'Credit Usage',       icon: CreditCard },
  { id: 'connectors', label: 'Connectors',         icon: Globe },
  { id: 'workflows',  label: 'Workflows',          icon: Workflow },
  { id: 'platform',   label: 'Platform Settings',  icon: Settings },
];

export function AdminPanel() {
  const { setView, user } = useAuthStore();
  const [section, setSection] = useState<Section>('overview');

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">

      {/* Sidebar */}
      <aside className="w-56 bg-white border-r border-gray-200 flex flex-col flex-shrink-0">
        <div className="px-4 py-5 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 bg-purple-600 rounded-lg flex items-center justify-center">
              <Shield className="w-4 h-4 text-white" />
            </div>
            <span className="font-bold text-gray-900 text-sm">Admin Panel</span>
          </div>
          <p className="text-xs text-gray-400 mt-1 truncate">{user?.email}</p>
        </div>

        <nav className="flex-1 p-3 space-y-0.5">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setSection(id)}
              className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                section === id
                  ? 'bg-purple-50 text-purple-700'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
              }`}
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              {label}
            </button>
          ))}
        </nav>

        <div className="p-3 border-t border-gray-100">
          <button
            onClick={() => setView('canvas')}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Canvas
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto">
        <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between sticky top-0 z-10">
          <div>
            <h1 className="font-bold text-gray-900">
              {NAV.find(n => n.id === section)?.label}
            </h1>
            <p className="text-xs text-gray-400 mt-0.5">FlowMind AI · Admin Console</p>
          </div>
          <div className="flex items-center gap-2">
            <Brain className="w-4 h-4 text-purple-500" />
            <span className="text-xs font-medium text-gray-600">FlowMind AI</span>
          </div>
        </header>

        <div className="p-6">
          {section === 'overview'   && <OverviewSection />}
          {section === 'users'      && <UsersSection />}
          {section === 'credits'    && <CreditsSection />}
          {section === 'connectors' && <ConnectorsSection />}
          {section === 'workflows'  && <WorkflowsSection />}
          {section === 'platform'   && <PlatformSettingsSection />}
        </div>
      </main>
    </div>
  );
}
