import { useState } from 'react';
import { createPortal } from 'react-dom';
import { X, CheckCircle2, XCircle, MinusCircle, Copy, Check, FlaskConical } from 'lucide-react';
import { dataApi, type PreviewResult, type PreviewNode, type DataProfile } from '@/services/api';
import { DatasetTable } from './DatasetTable';
import { QualityReportView, ProfileTable } from './QualityViews';

/** Result of a sample run: per node status, schema + sample rows, and the SQL each data node compiled to. */
export function PreviewModal({ result, onClose }: { result: PreviewResult; onClose: () => void }) {
  const dataNodes = result.nodes.filter(n => n.status !== 'skipped' || n.dataset);
  const [openId, setOpenId] = useState<string | null>(
    result.nodes.find(n => n.status === 'error')?.node_id
      ?? result.nodes.find(n => n.quality && !n.quality.passed)?.node_id          // surface failed checks first
      ?? [...result.nodes].reverse().find(n => n.dataset)?.node_id ?? null,
  );

  return createPortal(
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <div>
            <h2 className="text-base font-semibold text-gray-900 flex items-center gap-2">
              <FlaskConical className="w-4 h-4 text-cyan-600" /> Data preview
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Ran on a sample of up to {result.sample_rows.toLocaleString()} rows. No credits used; AI, HTTP and other
              side-effect nodes are skipped.
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-5 h-5" /></button>
        </div>

        <div className="overflow-y-auto px-6 py-4 space-y-2">
          {result.status === 'failed' && result.error && (
            <div className="flex gap-2 items-start bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <XCircle className="w-4 h-4 mt-0.5 flex-shrink-0" /> <span>{result.error}</span>
            </div>
          )}
          {result.nodes.length === 0 && <p className="text-sm text-gray-500">Nothing ran. Add a Load Data node and connect it.</p>}
          {dataNodes.map(n => <StepCard key={n.node_id} node={n} open={openId === n.node_id}
            onToggle={() => setOpenId(openId === n.node_id ? null : n.node_id)} />)}
          {result.nodes.some(n => n.status === 'skipped' && !n.dataset) && (
            <p className="text-xs text-gray-400 pt-1">
              Skipped: {result.nodes.filter(n => n.status === 'skipped' && !n.dataset).map(n => n.label ?? n.node_type).join(', ')}
            </p>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

function StepCard({ node, open, onToggle }: { node: PreviewNode; open: boolean; onToggle: () => void }) {
  const [copied, setCopied] = useState(false);
  const [profile, setProfile] = useState<DataProfile | null>(null);
  const [profiling, setProfiling] = useState(false);
  const icon = node.status === 'ok' ? <CheckCircle2 className="w-4 h-4 text-green-600" />
    : node.status === 'error' ? <XCircle className="w-4 h-4 text-red-600" /> : <MinusCircle className="w-4 h-4 text-gray-400" />;
  const ds = node.dataset;

  const runProfile = async () => {
    if (!node.dataset) return;
    setProfiling(true);
    try { setProfile(await dataApi.profileDataset(node.dataset.id)); } catch { setProfile(null); } finally { setProfiling(false); }
  };

  const copy = async () => {
    if (!node.sql) return;
    await navigator.clipboard.writeText(node.sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className={`border rounded-lg ${node.status === 'error' ? 'border-red-200' : 'border-gray-200'}`}>
      <button onClick={onToggle} className="w-full flex items-center gap-3 px-4 py-2.5 text-left">
        {icon}
        <span className="text-sm font-medium text-gray-900">{node.label ?? node.node_id}</span>
        <span className="text-xs text-gray-400 font-mono">{node.node_type.replace('Node', '')}</span>
        {ds && (
          <span className="ml-auto text-xs text-gray-500">
            {(ds.row_count ?? 0).toLocaleString()} rows × {ds.columns.length} cols
          </span>
        )}
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-3">
          {node.error && <p className="text-sm text-red-600">{node.error}</p>}
          {node.quality && <QualityReportView report={node.quality} />}
          {node.note && <p className="text-xs text-gray-500">{node.note}</p>}
          {node.sql && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <p className="text-xs font-semibold text-gray-600">SQL this step ran</p>
                <button onClick={copy} className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-800">
                  {copied ? <Check className="w-3 h-3 text-green-600" /> : <Copy className="w-3 h-3" />} {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
              <pre className="bg-gray-900 text-gray-100 text-xs rounded-lg p-3 overflow-auto max-h-48">{node.sql}</pre>
            </div>
          )}
          {ds && <DatasetTable dataset={ds} maxHeight="40vh" />}
          {ds && !node.quality && (
            <div>
              {!profile && (
                <button onClick={runProfile} disabled={profiling} className="text-xs font-medium text-cyan-700 hover:underline disabled:opacity-50">
                  {profiling ? 'Profiling…' : 'Profile columns (empty values, ranges, distinct counts)'}
                </button>
              )}
              {profile && <ProfileTable profile={profile} />}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
