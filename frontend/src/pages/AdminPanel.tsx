import { useState, useEffect } from 'react';
import {
  Users, BarChart3, Zap, Globe, Workflow, ArrowLeft,
  Brain, RefreshCw, Shield, CheckCircle, XCircle,
  TrendingUp, Activity, CreditCard, ScanLine, ChevronDown, ChevronRight,
} from 'lucide-react';
import { adminApi, AdminUser, CreditBreakdown, ConnectorUsage, AdminWorkflow } from '@/services/api';
import { useAuthStore } from '@/store/authStore';

type Section = 'overview' | 'users' | 'credits' | 'connectors' | 'workflows';

const NODE_LABELS: Record<string, string> = {
  aiNode: 'AI Agent', verificationNode: 'Verification', decisionNode: 'Decision',
  indianKycNode: 'Indian KYC', httpNode: 'HTTP Request', codeNode: 'Code Runner',
  transformNode: 'Transform', ruleNode: 'Rule Engine', validatorNode: 'Validator',
  switchNode: 'Switch', formatterNode: 'Formatter', aggregatorNode: 'Aggregator',
  humanReviewNode: 'Human Review', inputNode: 'Input', outputNode: 'Output',
};

const CREDIT_COSTS: Record<string, number> = {
  aiNode: 10, verificationNode: 10, decisionNode: 10,
  indianKycNode: 15, httpNode: 2, codeNode: 2,
  transformNode: 1, ruleNode: 1, validatorNode: 1,
  switchNode: 1, formatterNode: 1, aggregatorNode: 1,
  humanReviewNode: 1, inputNode: 0, outputNode: 0,
};

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
            {[['AI / Verify / Decision', '10 credits'], ['Indian KYC', '15 credits'],
              ['HTTP / Code', '2 credits'], ['Other nodes', '1 credit'], ['Input / Output', 'Free']].map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs">
                <span className="text-gray-500">{k}</span>
                <span className="font-medium text-gray-700">{v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Users ─────────────────────────────────────────────────────────────────────

function UsersSection() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [editing, setEditing] = useState<Record<string, number>>({});
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => { adminApi.getUsers().then(setUsers); }, []);

  const save = async (userId: string) => {
    setSaving(userId);
    try {
      await adminApi.updateUser(userId, { credits_total: editing[userId] });
      setUsers(u => u.map(x => x.id === userId ? { ...x, credits_total: editing[userId] } : x));
      setEditing(e => { const n = { ...e }; delete n[userId]; return n; });
    } finally {
      setSaving(null);
    }
  };

  const toggleActive = async (user: AdminUser) => {
    await adminApi.updateUser(user.id, { is_active: !user.is_active });
    setUsers(u => u.map(x => x.id === user.id ? { ...x, is_active: !user.is_active } : x));
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
        <p className="font-semibold text-gray-800">All Users ({users.length})</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
            <tr>
              {['User', 'Role', 'Workflows', 'Executions', 'Credits Used / Total', 'Status', 'Joined', 'Actions'].map(h => (
                <th key={h} className="px-4 py-3 text-left font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {users.map(user => (
              <tr key={user.id} className="hover:bg-gray-50/50 transition-colors">
                <td className="px-4 py-3">
                  <p className="font-medium text-gray-900">{user.full_name || '—'}</p>
                  <p className="text-xs text-gray-400 font-mono">{user.email}</p>
                </td>
                <td className="px-4 py-3">
                  <Badge
                    label={user.role}
                    color={user.role === 'admin' ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-600'}
                  />
                </td>
                <td className="px-4 py-3 text-gray-700 font-medium">{user.workflow_count}</td>
                <td className="px-4 py-3 text-gray-700 font-medium">{user.execution_count}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="text-gray-700 font-medium">{user.credits_used}</span>
                    <span className="text-gray-400">/</span>
                    {editing[user.id] !== undefined ? (
                      <div className="flex items-center gap-1">
                        <input
                          type="number"
                          value={editing[user.id]}
                          onChange={e => setEditing(ed => ({ ...ed, [user.id]: parseInt(e.target.value) || 0 }))}
                          className="w-20 px-2 py-0.5 text-xs border border-blue-400 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                        />
                        <button
                          onClick={() => save(user.id)}
                          disabled={saving === user.id}
                          className="text-xs px-2 py-0.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                        >
                          {saving === user.id ? '…' : 'Save'}
                        </button>
                        <button
                          onClick={() => setEditing(e => { const n = { ...e }; delete n[user.id]; return n; })}
                          className="text-xs text-gray-400 hover:text-gray-600"
                        >✕</button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setEditing(e => ({ ...e, [user.id]: user.credits_total }))}
                        className="text-gray-700 font-medium hover:text-blue-600 underline decoration-dotted cursor-pointer"
                        title="Click to edit"
                      >
                        {user.credits_total.toLocaleString()}
                      </button>
                    )}
                  </div>
                  <div className="mt-1 w-32 bg-gray-100 rounded-full h-1.5">
                    <div
                      className={`h-1.5 rounded-full ${user.credits_used / user.credits_total > 0.9 ? 'bg-red-500' : user.credits_used / user.credits_total > 0.7 ? 'bg-amber-500' : 'bg-green-500'}`}
                      style={{ width: `${Math.min(100, (user.credits_used / Math.max(user.credits_total, 1)) * 100)}%` }}
                    />
                  </div>
                </td>
                <td className="px-4 py-3">
                  <Badge
                    label={user.is_active ? 'Active' : 'Disabled'}
                    color={user.is_active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-600'}
                  />
                </td>
                <td className="px-4 py-3 text-xs text-gray-400">
                  {user.created_at ? new Date(user.created_at).toLocaleDateString() : '—'}
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => toggleActive(user)}
                    className={`text-xs px-2.5 py-1 rounded-md font-medium transition-colors ${
                      user.is_active
                        ? 'bg-red-50 text-red-600 hover:bg-red-100'
                        : 'bg-green-50 text-green-600 hover:bg-green-100'
                    }`}
                  >
                    {user.is_active ? 'Disable' : 'Enable'}
                  </button>
                </td>
              </tr>
            ))}
            {users.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400 text-sm">No users yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Credit Usage ──────────────────────────────────────────────────────────────

function CreditsSection() {
  const [data, setData] = useState<CreditBreakdown[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => { adminApi.getCreditUsage().then(setData); }, []);

  const toggle = (uid: string) =>
    setExpanded(s => { const n = new Set(s); n.has(uid) ? n.delete(uid) : n.add(uid); return n; });

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100">
        <p className="font-semibold text-gray-800">Credit Usage by User</p>
        <p className="text-xs text-gray-400 mt-0.5">Expand each user to see per-node breakdown</p>
      </div>
      <div className="divide-y divide-gray-100">
        {data.map(row => (
          <div key={row.user_id}>
            <button
              onClick={() => toggle(row.user_id)}
              className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-gray-50 transition-colors text-left"
            >
              <div className="flex items-center gap-3">
                {expanded.has(row.user_id) ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
                <div>
                  <p className="text-sm font-medium text-gray-900">{row.email}</p>
                  <p className="text-xs text-gray-400">{row.breakdown.length} node type{row.breakdown.length !== 1 ? 's' : ''} used</p>
                </div>
              </div>
              <div className="text-right">
                <p className="text-sm font-bold text-gray-900">{row.total_credits.toLocaleString()} credits</p>
              </div>
            </button>
            {expanded.has(row.user_id) && (
              <div className="bg-gray-50 px-5 pb-3">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-400 uppercase tracking-wide">
                      <th className="text-left py-1.5 pl-7">Node Type</th>
                      <th className="text-right py-1.5">Calls</th>
                      <th className="text-right py-1.5">Credits</th>
                      <th className="text-right py-1.5">Cost/call</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {row.breakdown.sort((a, b) => b.credits - a.credits).map(b => (
                      <tr key={b.node_type}>
                        <td className="py-1.5 pl-7 text-gray-700 font-medium">
                          {NODE_LABELS[b.node_type] || b.node_type}
                        </td>
                        <td className="py-1.5 text-right text-gray-600">{b.calls}</td>
                        <td className="py-1.5 text-right font-semibold text-gray-900">{b.credits}</td>
                        <td className="py-1.5 text-right text-gray-400">{CREDIT_COSTS[b.node_type] ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ))}
        {data.length === 0 && (
          <div className="px-5 py-8 text-center text-gray-400 text-sm">No credit usage recorded yet.</div>
        )}
      </div>
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

function Spinner() {
  return (
    <div className="flex items-center justify-center py-16">
      <RefreshCw className="w-6 h-6 text-gray-400 animate-spin" />
    </div>
  );
}

// ── Main Admin Panel ──────────────────────────────────────────────────────────

const NAV: { id: Section; label: string; icon: React.FC<{ className?: string }> }[] = [
  { id: 'overview',   label: 'Overview',      icon: BarChart3 },
  { id: 'users',      label: 'Users',          icon: Users },
  { id: 'credits',    label: 'Credit Usage',   icon: CreditCard },
  { id: 'connectors', label: 'Connectors',     icon: Globe },
  { id: 'workflows',  label: 'Workflows',      icon: Workflow },
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
        </div>
      </main>
    </div>
  );
}
