import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, BrainCircuit, Loader2, Sparkles, Activity, Layers, Copy, Check } from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { connectionsApi, mlApi, Connection, MlModels, FeedbackBatch } from '@/services/api';

function errMsg(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
}
const field = 'w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 bg-white';
const when = (iso: string) => new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).toLocaleString();

function Card({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <section className="bg-white rounded-xl border border-gray-200 p-5">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-900 mb-3">{icon}{title}</h2>
      {children}
    </section>
  );
}

function CopyBox({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="relative">
      <pre className="text-xs bg-gray-900 text-gray-100 rounded-lg p-3 pr-10 overflow-x-auto whitespace-pre-wrap">{text}</pre>
      <button onClick={() => { void navigator.clipboard?.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }} className="absolute top-2 right-2 text-gray-300 hover:text-white">
        {done ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
      </button>
    </div>
  );
}

export function ModelsPage() {
  const { setView } = useAuthStore();
  const [conns, setConns] = useState<Connection[]>([]);
  const [mlflowId, setMlflowId] = useState('');
  const [registry, setRegistry] = useState<MlModels | null>(null);
  const [endpointId, setEndpointId] = useState('');
  const [features, setFeatures] = useState('tenure_months, monthly_spend, support_tickets');
  const [values, setValues] = useState<Record<string, string>>({ tenure_months: '3', monthly_spend: '40.5', support_tickets: '5' });
  const [result, setResult] = useState<{ prediction: unknown; probability?: number | null; latency_ms: number } | null>(null);
  const [fb, setFb] = useState<FeedbackBatch[]>([]);
  const [fbModel, setFbModel] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => { connectionsApi.list().then(setConns).catch(() => setConns([])); }, []);
  const loadFb = useCallback(() => { mlApi.feedback(fbModel || undefined).then(setFb).catch(() => setFb([])); }, [fbModel]);
  useEffect(loadFb, [loadFb]);

  const mlflowConns = conns.filter(c => c.type === 'mlflow');
  const endpointConns = conns.filter(c => c.type === 'ml_endpoint');
  const featList = features.split(',').map(f => f.trim()).filter(Boolean);

  const loadRegistry = async (id: string) => {
    setMlflowId(id); setRegistry(null); setError('');
    if (!id) return;
    setBusy(true);
    try { setRegistry(await mlApi.models(id)); } catch (e) { setError(errMsg(e, 'Could not read the registry.')); } finally { setBusy(false); }
  };
  const tryIt = async () => {
    setBusy(true); setError(''); setResult(null);
    try { setResult(await mlApi.tryEndpoint(endpointId, featList, values)); } catch (e) { setError(errMsg(e, 'Scoring failed.')); } finally { setBusy(false); }
  };

  const modelsInFb = Array.from(new Set(fb.map(b => b.model_name)));
  const series = [...fb].reverse();

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-3">
        <button onClick={() => setView('canvas')} className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-900"><ArrowLeft className="w-4 h-4" /> Back to Canvas</button>
        <div className="h-5 w-px bg-gray-300" />
        <BrainCircuit className="w-5 h-5 text-emerald-600" />
        <h1 className="text-base font-semibold text-gray-900">Models</h1>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-6 space-y-5">
        <div className="text-sm bg-emerald-50 border border-emerald-200 text-emerald-900 rounded-xl p-4">
          FlowMind never runs your model itself. It talks to <b>your</b> MLflow registry and <b>your</b> scoring endpoint, using connections you add on the{' '}
          <button className="underline" onClick={() => setView('connections')}>Connections</button> page. Nothing is chosen for you.
          <details className="mt-2"><summary className="cursor-pointer">No MLflow yet? Start a demo in two minutes</summary>
            <div className="mt-2 space-y-2">
              <CopyBox text={'pip install mlflow scikit-learn pandas\nmlflow server --host 127.0.0.1 --port 5000 &\npython scripts/mlflow_demo.py http://127.0.0.1:5000\nmlflow models serve -m "models:/churn-model/2" -p 5001 --env-manager local'} />
              <p className="text-xs">Then add an <b>MLflow</b> connection (<code>http://127.0.0.1:5000</code>) and a <b>Model endpoint</b> connection (<code>http://127.0.0.1:5001/invocations</code>); an admin must allow-list <code>127.0.0.1</code> on each.</p>
            </div>
          </details>
        </div>
        {error && <div className="text-sm bg-red-50 border border-red-200 text-red-800 rounded-lg px-4 py-2">{error}</div>}

        <Card icon={<Layers className="w-4 h-4 text-gray-500" />} title="Model registry">
          <select className={field} value={mlflowId} onChange={e => void loadRegistry(e.target.value)}>
            <option value="">— choose an MLflow connection —</option>
            {mlflowConns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          {mlflowConns.length === 0 && <p className="text-sm text-gray-500 mt-2">No MLflow connection yet. <button className="text-emerald-700 underline" onClick={() => setView('connections')}>Add one</button>.</p>}
          {busy && !registry && mlflowId && <p className="text-sm text-gray-500 mt-3 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Reading the registry…</p>}
          {registry && (
            <div className="mt-4 space-y-4">
              {!registry.can_promote && <p className="text-xs text-amber-700">This connection is read-only, so the Promote Model node cannot change aliases through it.</p>}
              {registry.models.length === 0 && <p className="text-sm text-gray-500">No registered models yet.</p>}
              {registry.models.map(m => (
                <div key={m.name} className="border border-gray-200 rounded-lg overflow-hidden">
                  <div className="px-3 py-2 bg-gray-50 text-sm font-semibold font-mono">{m.name}</div>
                  <table className="w-full text-sm">
                    <thead><tr className="text-xs text-gray-500 text-left"><th className="px-3 py-1.5">Version</th><th className="px-3 py-1.5">Aliases</th><th className="px-3 py-1.5">Training metrics</th></tr></thead>
                    <tbody>
                      {m.versions.map(v => (
                        <tr key={v.version} className="border-t border-gray-100">
                          <td className="px-3 py-2 font-mono">v{v.version}</td>
                          <td className="px-3 py-2">{v.aliases.length ? v.aliases.map(a => <span key={a} className="text-xs bg-emerald-100 text-emerald-800 rounded-full px-2 py-0.5 mr-1">{a}</span>) : <span className="text-gray-300">—</span>}</td>
                          <td className="px-3 py-2 text-xs font-mono text-gray-600">{Object.entries(v.metrics).map(([k, x]) => `${k} ${x.toFixed(3)}`).join('  ·  ') || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card icon={<Sparkles className="w-4 h-4 text-gray-500" />} title="Try a prediction">
          <select className={field} value={endpointId} onChange={e => { setEndpointId(e.target.value); setResult(null); }}>
            <option value="">— choose a model endpoint connection —</option>
            {endpointConns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          {endpointConns.length === 0 && <p className="text-sm text-gray-500 mt-2">No model endpoint connection yet. <button className="text-emerald-700 underline" onClick={() => setView('connections')}>Add one</button>.</p>}
          {endpointId && (
            <div className="mt-4 space-y-3">
              <label className="text-xs text-gray-600 block">Features the model expects (comma separated)
                <input className={`${field} mt-1 font-mono`} value={features} onChange={e => setFeatures(e.target.value)} />
              </label>
              <div className="grid sm:grid-cols-3 gap-3">
                {featList.map(f => (
                  <label key={f} className="text-xs text-gray-600">{f}
                    <input className={`${field} mt-1`} value={values[f] ?? ''} onChange={e => setValues({ ...values, [f]: e.target.value })} />
                  </label>
                ))}
              </div>
              <button onClick={tryIt} disabled={busy || featList.length === 0} className="px-4 py-2 text-sm text-white bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-300 rounded-lg flex items-center gap-2">
                {busy && <Loader2 className="w-4 h-4 animate-spin" />} Predict
              </button>
              {result && (
                <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-3 text-sm">
                  Prediction: <b className="font-mono">{String(result.prediction)}</b>
                  {result.probability != null && <> · confidence <b>{(result.probability * 100).toFixed(1)}%</b></>}
                  <span className="text-gray-500"> · {result.latency_ms} ms</span>
                </div>
              )}
            </div>
          )}
        </Card>

        <Card icon={<Activity className="w-4 h-4 text-gray-500" />} title="Feedback history — is the model still right?">
          <div className="flex items-center gap-3 mb-3">
            <select className={`${field} w-56`} value={fbModel} onChange={e => setFbModel(e.target.value)}>
              <option value="">All models</option>
              {modelsInFb.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
            <span className="text-xs text-gray-500">Added by the <b>Feedback</b> node each time it runs. Only summaries are stored.</span>
          </div>
          {fb.length === 0 ? <p className="text-sm text-gray-400">Nothing yet. Add a Feedback node after Batch Score and run it.</p> : (
            <>
              <div className="flex items-end gap-1 h-16 mb-3" title="Newest on the right">
                {series.map(b => {
                  const h = b.metric === 'accuracy' ? Math.max(4, b.value * 64) : 32;
                  return <div key={b.id} style={{ height: h }} className={`w-3 rounded-t ${b.metric === 'accuracy' ? 'bg-emerald-500' : 'bg-sky-500'}`} title={`${b.metric} ${b.value.toFixed(3)}`} />;
                })}
              </div>
              <table className="w-full text-sm">
                <thead><tr className="text-xs text-gray-500 text-left"><th className="py-1">When</th><th>Model</th><th>Metric</th><th>Rows</th></tr></thead>
                <tbody>{fb.slice(0, 15).map(b => (
                  <tr key={b.id} className="border-t border-gray-100"><td className="py-1.5 text-xs text-gray-500">{when(b.created_at)}</td><td className="font-mono">{b.model_name}</td>
                    <td className="font-mono">{b.metric} {b.value.toFixed(3)}</td><td>{b.rows.toLocaleString()}</td></tr>
                ))}</tbody>
              </table>
            </>
          )}
        </Card>
      </main>
    </div>
  );
}
