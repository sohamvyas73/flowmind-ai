import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft, HardDrive, Upload, Loader2, Trash2, Eye, Download, XCircle, FileSpreadsheet, Table2,
  Sparkles, X, Info, BarChart3,
} from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { dataApi, DataFile, DatasetInfo, DatasetRef, DataUsage, DataProfile } from '@/services/api';
import { ProfileTable } from '@/components/QualityViews';
import { DatasetTable, formatBytes } from '@/components/DatasetTable';

function errMsg(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
}

const fmtDate = (iso?: string | null) => (iso ? new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).toLocaleString() : '—');

export function DataPage() {
  const { setView } = useAuthStore();
  const [files, setFiles] = useState<DataFile[]>([]);
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [usage, setUsage] = useState<DataUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState<{ title: string; ref: DatasetRef } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [profile, setProfile] = useState<{ title: string; data: DataProfile } | null>(null);
  const [profiling, setProfiling] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const [f, d, u] = await Promise.all([dataApi.listFiles(), dataApi.listDatasets(), dataApi.usage()]);
      setFiles(f); setDatasets(d); setUsage(u);
    } catch (e) {
      setError(errMsg(e, 'Failed to load your data.'));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const upload = async (list: FileList | File[]) => {
    setError('');
    setUploading(true);
    try {
      for (const f of Array.from(list)) {
        try { await dataApi.uploadFile(f); } catch (e) { setError(`${f.name}: ${errMsg(e, 'upload failed')}`); }
      }
      await load();
    } finally {
      setUploading(false);
    }
  };

  const examples = async () => {
    setError('');
    setUploading(true);
    try { await dataApi.installExamples(); await load(); } catch (e) { setError(errMsg(e, 'Could not load examples.')); }
    finally { setUploading(false); }
  };

  const open = async (title: string, fn: () => Promise<DatasetRef>) => {
    setPreviewLoading(true);
    setPreview(null);
    try { setPreview({ title, ref: await fn() }); } catch (e) { setError(errMsg(e, 'Could not open this data.')); }
    finally { setPreviewLoading(false); }
  };

  const openProfile = async (f: DataFile) => {
    setProfiling(true);
    setProfile(null);
    try { setProfile({ title: f.name, data: await dataApi.profileFile(f.id) }); } catch (e) { setError(errMsg(e, 'Could not profile this file.')); }
    finally { setProfiling(false); }
  };

  const removeFile = async (f: DataFile) => {
    if (!window.confirm(`Delete "${f.name}"? Pipelines that load it will fail until you upload it again.`)) return;
    try { await dataApi.deleteFile(f.id); await load(); } catch (e) { setError(errMsg(e, 'Delete failed.')); }
  };
  const removeSet = async (d: DatasetInfo) => {
    if (!window.confirm(`Delete this output (${d.name ?? 'dataset'})?`)) return;
    try { await dataApi.deleteDataset(d.id); await load(); } catch (e) { setError(errMsg(e, 'Delete failed.')); }
  };

  const pct = usage ? Math.min(100, (usage.used_bytes / Math.max(usage.limit_bytes, 1)) * 100) : 0;

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4">
        <button onClick={() => setView('canvas')} className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900">
          <ArrowLeft className="w-4 h-4" /> Back to Canvas
        </button>
        <div className="h-5 w-px bg-gray-300" />
        <h1 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <HardDrive className="w-5 h-5 text-cyan-600" /> Data
        </h1>
        {usage && (
          <div className="ml-auto flex items-center gap-3 text-xs text-gray-500">
            <span>{formatBytes(usage.used_bytes)} of {formatBytes(usage.limit_bytes)} used</span>
            <div className="w-28 h-1.5 bg-gray-200 rounded-full overflow-hidden">
              <div className={`h-full ${pct > 85 ? 'bg-red-500' : 'bg-cyan-500'}`} style={{ width: `${pct}%` }} />
            </div>
          </div>
        )}
      </div>

      <div className="max-w-4xl mx-auto px-6 py-8 space-y-6">
        <div className="bg-cyan-50 border border-cyan-200 rounded-xl p-4 flex gap-3">
          <Info className="w-4 h-4 text-cyan-600 flex-shrink-0 mt-0.5" />
          <div className="text-sm text-cyan-900">
            <p className="font-semibold">How it fits together</p>
            <p>
              Upload a file here → in the canvas add a <b>Load Data</b> node and pick it → add <b>Clean</b>, <b>Combine</b>,
              <b> Summarise</b> or <b>SQL</b> → click <b>Preview data</b> to see each step. Results of real runs appear below.
            </p>
          </div>
        </div>

        {error && (
          <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
            <XCircle className="w-4 h-4 flex-shrink-0 mt-0.5" /> <span className="flex-1">{error}</span>
            <button onClick={() => setError('')}><X className="w-4 h-4" /></button>
          </div>
        )}

        {/* ── Files ── */}
        <section className="bg-white rounded-xl border border-gray-200">
          <div className="px-5 py-4 flex items-center justify-between border-b border-gray-100">
            <div>
              <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2"><FileSpreadsheet className="w-4 h-4 text-cyan-600" /> Your files</h2>
              <p className="text-xs text-gray-500 mt-0.5">CSV, TSV, JSON, JSONL or Parquet · up to {usage ? formatBytes(usage.max_upload_bytes) : '25 MB'} each</p>
            </div>
            <div className="flex gap-2">
              <button onClick={examples} disabled={uploading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-cyan-700 hover:bg-cyan-50 rounded-md disabled:opacity-50">
                <Sparkles className="w-3.5 h-3.5" /> Load example data
              </button>
              <button onClick={() => input.current?.click()} disabled={uploading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-cyan-600 hover:bg-cyan-700 rounded-md disabled:opacity-50">
                {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />} Upload
              </button>
              <input ref={input} type="file" multiple hidden accept=".csv,.tsv,.json,.jsonl,.ndjson,.parquet"
                onChange={e => { if (e.target.files?.length) void upload(e.target.files); e.target.value = ''; }} />
            </div>
          </div>

          <div
            onDragOver={e => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={e => { e.preventDefault(); setDragging(false); if (e.dataTransfer.files.length) void upload(e.dataTransfer.files); }}
            className={dragging ? 'bg-cyan-50' : ''}
          >
            {loading ? (
              <div className="flex justify-center py-10"><Loader2 className="w-5 h-5 animate-spin text-cyan-500" /></div>
            ) : files.length === 0 ? (
              <div className="py-10 text-center text-sm text-gray-500">
                Drop files here, or <button onClick={() => input.current?.click()} className="underline">browse</button>, or{' '}
                <button onClick={examples} className="underline">load the example data</button> to try things out.
              </div>
            ) : (
              <div className="divide-y divide-gray-100">
                {files.map(f => (
                  <div key={f.id} className="flex items-center gap-4 px-5 py-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-gray-900 truncate">{f.name}</p>
                      <p className="text-xs text-gray-500">
                        {f.format.toUpperCase()} · {f.row_count != null ? `${f.row_count.toLocaleString()} rows · ` : ''}
                        {f.columns?.length ?? 0} columns · {formatBytes(f.size_bytes)}
                      </p>
                    </div>
                    <button onClick={() => open(f.name, () => dataApi.previewFile(f.id))}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100 rounded-md">
                      <Eye className="w-3.5 h-3.5" /> Preview
                    </button>
                    <button onClick={() => openProfile(f)} disabled={profiling}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100 rounded-md disabled:opacity-50"
                      title="Empty values, ranges and distinct counts per column">
                      <BarChart3 className="w-3.5 h-3.5" /> Profile
                    </button>
                    <button onClick={() => removeFile(f)} className="p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600 rounded-md" title="Delete">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        {/* ── Pipeline outputs ── */}
        <section className="bg-white rounded-xl border border-gray-200">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2"><Table2 className="w-4 h-4 text-cyan-600" /> Pipeline outputs</h2>
            <p className="text-xs text-gray-500 mt-0.5">Tables produced by real runs. They are deleted automatically after a few days — download what you want to keep.</p>
          </div>
          {datasets.length === 0 ? (
            <div className="py-10 text-center text-sm text-gray-500">Nothing yet. Run a workflow that has data nodes.</div>
          ) : (
            <div className="divide-y divide-gray-100">
              {datasets.map(d => (
                <div key={d.id} className="flex items-center gap-3 px-5 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-900 truncate">{d.name ?? 'Dataset'}</p>
                    <p className="text-xs text-gray-500">
                      {(d.row_count ?? 0).toLocaleString()} rows · {d.columns?.length ?? 0} columns · {formatBytes(d.size_bytes)} · {fmtDate(d.created_at)}
                      {d.expires_at && <span className="text-amber-600"> · expires {fmtDate(d.expires_at)}</span>}
                    </p>
                  </div>
                  <button onClick={() => open(d.name ?? 'Dataset', () => dataApi.previewDataset(d.id))}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100 rounded-md">
                    <Eye className="w-3.5 h-3.5" /> Preview
                  </button>
                  <button onClick={() => dataApi.download(d.id, d.name ?? 'dataset', 'csv').catch(e => setError(errMsg(e, 'Download failed.')))}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100 rounded-md">
                    <Download className="w-3.5 h-3.5" /> CSV
                  </button>
                  <button onClick={() => dataApi.download(d.id, d.name ?? 'dataset', 'parquet').catch(e => setError(errMsg(e, 'Download failed.')))}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100 rounded-md">
                    <Download className="w-3.5 h-3.5" /> Parquet
                  </button>
                  <button onClick={() => removeSet(d)} className="p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600 rounded-md" title="Delete">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {profile && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => setProfile(null)}>
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-6 py-4 border-b sticky top-0 bg-white">
              <h2 className="text-base font-semibold text-gray-900">Profile · {profile.title}</h2>
              <button onClick={() => setProfile(null)} className="text-gray-400 hover:text-gray-600"><X className="w-5 h-5" /></button>
            </div>
            <div className="px-6 py-5 space-y-4">
              <ProfileTable profile={profile.data} />
              {profile.data.suggested_rules.length > 0 && (
                <div>
                  <p className="text-sm font-semibold text-gray-800 mb-1">Checks we would suggest</p>
                  <ul className="text-xs text-gray-600 space-y-1 list-disc pl-5">
                    {profile.data.suggested_rules.map((r, i) => <li key={i}>{r.reason}</li>)}
                  </ul>
                  <p className="text-xs text-gray-400 mt-2">Add a <b>Quality Check</b> node after Load Data and click “Suggest checks from my data”.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {(preview || previewLoading) && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => setPreview(null)}>
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-6 py-4 border-b sticky top-0 bg-white">
              <h2 className="text-base font-semibold text-gray-900">{preview?.title ?? 'Loading…'}</h2>
              <button onClick={() => setPreview(null)} className="text-gray-400 hover:text-gray-600"><X className="w-5 h-5" /></button>
            </div>
            <div className="px-6 py-5">
              {previewLoading && <div className="flex justify-center py-10"><Loader2 className="w-6 h-6 animate-spin text-cyan-500" /></div>}
              {preview && <DatasetTable dataset={preview.ref} />}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
