import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft, DatabaseZap, Loader2, CheckCircle2, XCircle, CircleDashed, Copy, Check, Upload, Trash2, Search, FileText,
  Sparkles, Container, Layers, Cpu, ShieldCheck,
} from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import {
  ragApi, connectionsApi, RagCatalog, RagSettings, RagFile, RagCollection, RagPassage, Connection, StoreInfo, EmbedderInfo,
} from '@/services/api';

function errMsg(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
}

const field = 'w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white';

function CopyBox({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="relative">
      <pre className="text-xs bg-gray-900 text-gray-100 rounded-lg p-3 pr-10 overflow-x-auto whitespace-pre-wrap break-all">{text}</pre>
      <button
        onClick={() => { void navigator.clipboard?.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }}
        className="absolute top-2 right-2 text-gray-300 hover:text-white" title="Copy"
      >
        {done ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
      </button>
    </div>
  );
}

function Result({ ok, message, label }: { ok: boolean; message?: string | null; label: string }) {
  return (
    <div className={`flex items-start gap-2 text-sm rounded-lg px-3 py-2 ${ok ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}`}>
      {ok ? <CheckCircle2 className="w-4 h-4 mt-0.5 flex-shrink-0" /> : <XCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />}
      <span><b>{label}:</b> {message || (ok ? 'OK' : 'Failed')}</span>
    </div>
  );
}

function Step({ n, title, icon, children }: { n: number; title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="bg-white rounded-xl border border-gray-200 p-5">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-900 mb-3">
        <span className="w-6 h-6 rounded-full bg-indigo-600 text-white text-xs flex items-center justify-center">{n}</span>
        {icon}{title}
      </h2>
      {children}
    </section>
  );
}

export function RetrievalPage() {
  const { setView } = useAuthStore();
  const [catalog, setCatalog] = useState<RagCatalog | null>(null);
  const [saved, setSaved] = useState<RagSettings | null>(null);
  const [conns, setConns] = useState<Connection[]>([]);
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [dim, setDim] = useState(0);
  const [apiKey, setApiKey] = useState('');
  const [store, setStore] = useState('');
  const [connId, setConnId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const [files, setFiles] = useState<RagFile[]>([]);
  const [cols, setCols] = useState<RagCollection[]>([]);
  const [colName, setColName] = useState('help');
  const [chunk, setChunk] = useState(400);
  const [overlap, setOverlap] = useState(50);
  const [indexMsg, setIndexMsg] = useState('');
  const [q, setQ] = useState('how many days until a refund is processed');
  const [qCol, setQCol] = useState('');
  const [hits, setHits] = useState<RagPassage[] | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const loadSetup = useCallback(async () => {
    const [c, s, cn] = await Promise.all([ragApi.catalog(), ragApi.settings(), connectionsApi.list().catch(() => [])]);
    setCatalog(c); setSaved(s); setConns(cn);
    if (s.configured) {
      setProvider(s.embed_provider ?? ''); setModel(s.embed_model ?? ''); setDim(s.embed_dim ?? 0);
      setStore(s.store_type ?? ''); setConnId(s.connection_id ?? '');
    }
  }, []);
  const loadWork = useCallback(async () => {
    const [f, c] = await Promise.all([ragApi.files(), ragApi.collections()]);
    setFiles(f); setCols(c);
    setQCol(prev => prev || c[0]?.name || '');
  }, []);

  useEffect(() => { loadSetup().catch(e => setError(errMsg(e, 'Could not load retrieval settings.'))); }, [loadSetup]);
  useEffect(() => { if (saved?.ready) loadWork().catch(() => undefined); }, [saved?.ready, loadWork]);

  const emb: EmbedderInfo | undefined = catalog?.embedders.find(e => e.provider === provider);
  const st: StoreInfo | undefined = catalog?.stores.find(s => s.type === store);
  const storeConns = conns.filter(c => c.type === store);

  const pickEmbedder = (e: EmbedderInfo) => {
    setProvider(e.provider); setModel(e.models[0].model); setDim(e.models[0].dim); setApiKey('');
  };
  const complete = !!provider && !!model && dim > 0 && !!store && (store === 'pgvector' || !!connId) && (!emb?.needs_key || !!apiKey || (saved?.has_embed_key && saved.embed_provider === provider));

  const saveAndTest = async () => {
    setBusy(true); setError('');
    try {
      const s = await ragApi.save({ embed_provider: provider, embed_model: model, embed_dim: dim, embed_api_key: apiKey || null, store_type: store, connection_id: store === 'pgvector' ? null : connId });
      setSaved(s); setApiKey('');
    } catch (e) { setError(errMsg(e, 'Could not save.')); } finally { setBusy(false); }
  };
  const retest = async () => {
    setBusy(true); setError('');
    try { setSaved(await ragApi.test()); } catch (e) { setError(errMsg(e, 'Test failed.')); } finally { setBusy(false); }
  };
  const reset = async () => {
    if (!window.confirm('Clear your retrieval setup? Retrieval nodes stop working until you set it up again. Indexed data stays in your store.')) return;
    await ragApi.reset();
    setProvider(''); setModel(''); setDim(0); setStore(''); setConnId(''); setSaved(null); await loadSetup();
  };

  const upload = async (list: FileList | File[]) => {
    setError(''); setBusy(true);
    try { for (const f of Array.from(list)) { try { await ragApi.upload(f); } catch (e) { setError(`${f.name}: ${errMsg(e, 'upload failed')}`); } } await loadWork(); }
    finally { setBusy(false); }
  };
  const index = async () => {
    setBusy(true); setError(''); setIndexMsg('');
    try {
      const r = await ragApi.index({ collection: colName, file_names: [], chunk_size: chunk, overlap });
      setIndexMsg(`Indexed "${r.collection}": ${r.added} new, ${r.updated} changed, ${r.unchanged} unchanged · ${r.chunks} chunks embedded · ${r.total_chunks} chunks stored.`);
      setQCol(r.collection); await loadWork();
    } catch (e) { setError(errMsg(e, 'Indexing failed.')); } finally { setBusy(false); }
  };
  const search = async () => {
    setBusy(true); setError(''); setHits(null);
    try { setHits((await ragApi.query({ collection: qCol, query: q, top_k: 4, min_score: 0 })).passages); }
    catch (e) { setError(errMsg(e, 'Search failed.')); } finally { setBusy(false); }
  };

  const banner = !saved?.configured
    ? { cls: 'bg-amber-50 border-amber-200 text-amber-900', icon: <CircleDashed className="w-5 h-5" />, text: 'Not set up. Nothing is chosen for you — pick an embedding model and a vector store below, then run the tests. Retrieval nodes refuse to run until both pass.' }
    : saved.ready
      ? { cls: 'bg-green-50 border-green-200 text-green-900', icon: <ShieldCheck className="w-5 h-5" />, text: `Ready — ${saved.embed_provider} · ${saved.embed_model} → ${saved.store_type}.` }
      : { cls: 'bg-red-50 border-red-200 text-red-900', icon: <XCircle className="w-5 h-5" />, text: 'Setup saved, but a test failed. Fix the problem below and test again.' };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-3">
        <button onClick={() => setView('canvas')} className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-900">
          <ArrowLeft className="w-4 h-4" /> Back to Canvas
        </button>
        <div className="h-5 w-px bg-gray-300" />
        <DatabaseZap className="w-5 h-5 text-indigo-600" />
        <h1 className="text-base font-semibold text-gray-900">Retrieval (RAG) setup</h1>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-6 space-y-5">
        <div className={`flex items-start gap-3 border rounded-xl p-4 text-sm ${banner.cls}`}>{banner.icon}<p>{banner.text}</p></div>
        {error && <div className="text-sm bg-red-50 border border-red-200 text-red-800 rounded-lg px-4 py-2">{error}</div>}

        <Step n={1} title="Choose how text becomes vectors (embeddings)" icon={<Cpu className="w-4 h-4 text-gray-500" />}>
          <div className="grid sm:grid-cols-2 gap-3">
            {catalog?.embedders.map(e => (
              <button key={e.provider} onClick={() => pickEmbedder(e)}
                className={`text-left rounded-lg border p-3 transition ${provider === e.provider ? 'border-indigo-500 ring-2 ring-indigo-200 bg-indigo-50/40' : 'border-gray-200 hover:border-gray-300'}`}>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-gray-900">{e.label}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${e.local ? 'bg-emerald-100 text-emerald-700' : 'bg-sky-100 text-sky-700'}`}>{e.local ? 'runs locally' : 'hosted'}</span>
                  {!e.semantic && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-600">keyword-style</span>}
                </div>
                <p className="text-xs text-gray-500 mt-1">{e.description}</p>
              </button>
            ))}
          </div>
          {emb && (
            <div className="grid sm:grid-cols-3 gap-3 mt-4">
              <label className="text-xs text-gray-600">Model
                <select className={`${field} mt-1`} value={model} onChange={ev => { setModel(ev.target.value); const m = emb.models.find(x => x.model === ev.target.value); if (m) setDim(m.dim); }}>
                  {emb.models.map(m => <option key={m.model} value={m.model}>{m.model} — {m.note}</option>)}
                </select>
              </label>
              <label className="text-xs text-gray-600">Vector size (dimensions)
                <input type="number" className={`${field} mt-1`} value={dim} min={16} max={4096} onChange={ev => setDim(Number(ev.target.value))} />
              </label>
              {emb.needs_key && (
                <label className="text-xs text-gray-600">API key
                  <input type="password" className={`${field} mt-1`} value={apiKey} onChange={ev => setApiKey(ev.target.value)}
                    placeholder={saved?.has_embed_key && saved.embed_provider === provider ? 'saved — leave blank to keep' : 'paste your key'} autoComplete="off" />
                </label>
              )}
            </div>
          )}
          {emb && !emb.verified_here && <p className="text-xs text-amber-700 mt-3">This option needs {emb.needs_key ? 'a real key and internet access' : 'an optional install and model download'}; the test below tells you immediately if it works for you.</p>}
        </Step>

        <Step n={2} title="Choose where vectors are stored" icon={<Layers className="w-4 h-4 text-gray-500" />}>
          <div className="grid sm:grid-cols-2 gap-3">
            {catalog?.stores.map(s => (
              <button key={s.type} onClick={() => { setStore(s.type); setConnId(''); }}
                className={`text-left rounded-lg border p-3 transition ${store === s.type ? 'border-indigo-500 ring-2 ring-indigo-200 bg-indigo-50/40' : 'border-gray-200 hover:border-gray-300'}`}>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-gray-900">{s.label}</span>
                  {s.needs_docker && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-100 text-violet-700">Docker</span>}
                  {!s.needs_docker && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700">no new server</span>}
                </div>
                <p className="text-xs text-gray-500 mt-1">{s.summary}</p>
                <p className="text-[11px] text-gray-400 mt-1">Best for: {s.best_for}</p>
              </button>
            ))}
          </div>

          {st && st.type === 'pgvector' && (
            <div className="mt-4 text-sm text-gray-700 space-y-2">
              <p>Uses the PostgreSQL FlowMind already runs on. The <code className="bg-gray-100 px-1 rounded">vector</code> extension must be installed:</p>
              <CopyBox text={(st.setup ?? []).join('\n')} />
            </div>
          )}
          {st && st.needs_connection && (
            <div className="mt-4 space-y-3">
              <label className="text-xs text-gray-600 block">Your {st.label} connection
                <select className={`${field} mt-1`} value={connId} onChange={ev => setConnId(ev.target.value)}>
                  <option value="">— choose a connection —</option>
                  {storeConns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </label>
              {storeConns.length === 0 && (
                <p className="text-sm text-gray-600">No {st.label} connection yet.{' '}
                  <button onClick={() => setView('connections')} className="text-indigo-600 underline">Add one on the Connections page</button>
                  {' '}(URL <code className="bg-gray-100 px-1 rounded">{st.default_url}</code>; for a local server an admin must allow-list <code className="bg-gray-100 px-1 rounded">localhost</code>).
                </p>
              )}
              <details className="text-sm">
                <summary className="cursor-pointer text-indigo-700 flex items-center gap-1.5 w-fit"><Container className="w-4 h-4" /> Don't have {st.label} running? Start it with Docker</summary>
                <div className="mt-2 space-y-2">
                  <p className="text-xs text-gray-500">One command:</p>
                  <CopyBox text={st.docker ?? ''} />
                  <p className="text-xs text-gray-500">or with the bundled compose file / helper script:</p>
                  <CopyBox text={`docker compose -f docker-compose.vectorstores.yml --profile ${st.profile} up -d\n./scripts/vectorstores.sh start ${st.profile}`} />
                </div>
              </details>
            </div>
          )}
        </Step>

        <Step n={3} title="Save and test" icon={<Sparkles className="w-4 h-4 text-gray-500" />}>
          <div className="flex flex-wrap items-center gap-3">
            <button onClick={saveAndTest} disabled={!complete || busy}
              className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-300 rounded-lg flex items-center gap-2">
              {busy && <Loader2 className="w-4 h-4 animate-spin" />} Save &amp; test connection
            </button>
            {saved?.configured && <button onClick={retest} disabled={busy} className="px-3 py-2 text-sm text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-100">Re-run tests</button>}
            {saved?.configured && <button onClick={reset} className="px-3 py-2 text-sm text-red-600 hover:bg-red-50 rounded-lg">Clear setup</button>}
            {!complete && <span className="text-xs text-gray-500">Choose an embedding model and a vector store first{emb?.needs_key ? ' (and enter your key)' : ''}.</span>}
          </div>
          {saved?.configured && (
            <div className="mt-4 space-y-2">
              <Result ok={saved.embed_ok} label="Embedding model" message={saved.embed_message} />
              <Result ok={saved.store_ok} label="Vector store" message={saved.store_message} />
            </div>
          )}
        </Step>

        <section className={`bg-white rounded-xl border border-gray-200 p-5 ${saved?.ready ? '' : 'opacity-50 pointer-events-none'}`}>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-900 mb-1"><FileText className="w-4 h-4 text-gray-500" /> Documents &amp; collections</h2>
          {!saved?.ready && <p className="text-xs text-gray-500 mb-3">Unlocks when both tests above pass.</p>}
          <div className="grid md:grid-cols-2 gap-5 mt-3">
            <div>
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Your documents</h3>
                <div className="flex gap-2">
                  <button onClick={() => void ragApi.samples().then(loadWork)} className="text-xs text-indigo-700 hover:underline">Load example help-centre docs</button>
                  <button onClick={() => fileInput.current?.click()} className="text-xs flex items-center gap-1 text-indigo-700 hover:underline"><Upload className="w-3 h-3" />Upload</button>
                </div>
                <input ref={fileInput} type="file" multiple accept=".txt,.md,.markdown,.pdf" className="hidden" onChange={e => e.target.files && void upload(e.target.files)} />
              </div>
              <ul className="divide-y divide-gray-100 border border-gray-200 rounded-lg text-sm">
                {files.length === 0 && <li className="px-3 py-3 text-gray-400 text-xs">No documents yet. Upload .txt, .md or .pdf files.</li>}
                {files.map(f => (
                  <li key={f.id} className="flex items-center justify-between px-3 py-2">
                    <span className="truncate">{f.name} <span className="text-xs text-gray-400">{(f.size_bytes / 1024).toFixed(1)} KB</span></span>
                    <button onClick={() => void ragApi.removeFile(f.id).then(loadWork)} className="text-gray-400 hover:text-red-600"><Trash2 className="w-4 h-4" /></button>
                  </li>
                ))}
              </ul>
              <div className="mt-3 grid grid-cols-3 gap-2">
                <label className="text-xs text-gray-600 col-span-3">Index into collection
                  <input className={`${field} mt-1`} value={colName} onChange={e => setColName(e.target.value)} />
                </label>
                <label className="text-xs text-gray-600">Chunk size
                  <input type="number" className={`${field} mt-1`} value={chunk} onChange={e => setChunk(Number(e.target.value))} />
                </label>
                <label className="text-xs text-gray-600">Overlap
                  <input type="number" className={`${field} mt-1`} value={overlap} onChange={e => setOverlap(Number(e.target.value))} />
                </label>
                <button onClick={index} disabled={busy || files.length === 0} className="self-end px-3 py-2 text-sm text-white bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-300 rounded-lg">Index all</button>
              </div>
              {indexMsg && <p className="text-xs text-green-700 mt-2">{indexMsg}</p>}
            </div>
            <div>
              <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">Collections</h3>
              <ul className="divide-y divide-gray-100 border border-gray-200 rounded-lg text-sm">
                {cols.length === 0 && <li className="px-3 py-3 text-gray-400 text-xs">Nothing indexed yet.</li>}
                {cols.map(c => (
                  <li key={c.id} className="flex items-center justify-between px-3 py-2">
                    <span><b>{c.name}</b> <span className="text-xs text-gray-500">{c.documents} docs · {c.chunks} chunks · {c.store_type}</span></span>
                    <button onClick={() => { if (window.confirm(`Delete collection "${c.name}"?`)) void ragApi.removeCollection(c.name).then(loadWork); }} className="text-gray-400 hover:text-red-600"><Trash2 className="w-4 h-4" /></button>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mt-6 mb-2">Try a search</h3>
          <div className="flex flex-wrap gap-2">
            <select className={`${field} w-40`} value={qCol} onChange={e => setQCol(e.target.value)}>
              {cols.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
            </select>
            <input className={`${field} flex-1 min-w-[220px]`} value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && qCol && void search()} />
            <button onClick={search} disabled={busy || !qCol} className="px-4 py-2 text-sm text-white bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-300 rounded-lg flex items-center gap-2"><Search className="w-4 h-4" />Search</button>
          </div>
          {hits && (
            <ol className="mt-3 space-y-2">
              {hits.length === 0 && <li className="text-sm text-gray-500">No passages matched.</li>}
              {hits.map((h, i) => (
                <li key={i} className="border border-gray-200 rounded-lg p-3">
                  <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
                    <span>[{i + 1}] {h.source}</span><span className="font-mono">score {h.score.toFixed(3)}</span>
                  </div>
                  <p className="text-sm text-gray-800 whitespace-pre-wrap">{h.text}</p>
                </li>
              ))}
            </ol>
          )}
        </section>
      </main>
    </div>
  );
}
