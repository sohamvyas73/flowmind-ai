import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, FolderOpen, Loader2, Clock, GitBranch, Trash2 } from 'lucide-react';
import { workflowApi } from '@/services/api';
import { Workflow } from '@/types/workflow';
import { useWorkflowStore } from '@/store/workflowStore';

interface Props {
  onLoad: (workflow: Workflow) => void;
  onClose: () => void;
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function LoadWorkflowModal({ onLoad, onClose }: Props) {
  const { workflowId: activeWorkflowId, clearWorkflow } = useWorkflowStore();

  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    fetchWorkflows();
  }, []);

  const fetchWorkflows = () => {
    setLoading(true);
    setError(null);
    workflowApi.getWorkflows()
      .then(data => setWorkflows([...data].reverse())) // newest first
      .catch(() => setError('Could not load workflows. Is the backend running?'))
      .finally(() => setLoading(false));
  };

  const handleDelete = async (wf: Workflow, e: React.MouseEvent) => {
    e.stopPropagation(); // don't trigger the load click
    if (!confirm(`Delete "${wf.name}"?\n\nThis will also delete all its execution history. This cannot be undone.`)) return;

    setDeletingId(wf.id);
    try {
      await workflowApi.deleteWorkflow(wf.id);
      setWorkflows(prev => prev.filter(w => w.id !== wf.id));
      // If the deleted workflow was currently loaded, clear the canvas
      if (wf.id === activeWorkflowId) {
        clearWorkflow();
      }
    } catch {
      alert('Failed to delete workflow.');
    } finally {
      setDeletingId(null);
    }
  };

  return createPortal(
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-2xl w-[500px] max-h-[72vh] flex flex-col">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b flex-shrink-0">
          <div className="flex items-center gap-2">
            <FolderOpen className="w-5 h-5 text-blue-500" />
            <h2 className="text-base font-semibold text-gray-800">Load Workflow</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 p-4">
          {loading && (
            <div className="flex items-center justify-center py-12 gap-3 text-gray-400">
              <Loader2 className="w-5 h-5 animate-spin" />
              <span className="text-sm">Loading saved workflows…</span>
            </div>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
              {error}
            </div>
          )}

          {!loading && !error && workflows.length === 0 && (
            <div className="text-center py-12 text-gray-400">
              <FolderOpen className="w-10 h-10 mx-auto mb-3 opacity-40" />
              <p className="text-sm font-medium">No saved workflows yet</p>
              <p className="text-xs mt-1">Build a workflow and click Save to store it.</p>
            </div>
          )}

          {!loading && !error && workflows.length > 0 && (
            <div className="space-y-2">
              {workflows.map(wf => {
                const nodeCount = wf.graph_data?.nodes?.length ?? 0;
                const edgeCount = wf.graph_data?.edges?.length ?? 0;
                const isActive = wf.id === activeWorkflowId;
                const isDeleting = deletingId === wf.id;

                return (
                  <div
                    key={wf.id}
                    onClick={() => { onLoad(wf); onClose(); }}
                    className={`w-full text-left px-4 py-3 rounded-lg border transition-colors cursor-pointer group flex items-start gap-3 ${
                      isActive
                        ? 'border-blue-300 bg-blue-50'
                        : 'border-gray-200 hover:border-blue-400 hover:bg-blue-50'
                    }`}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-semibold text-gray-800 group-hover:text-blue-700 truncate">
                          {wf.name || '(Untitled)'}
                        </p>
                        {isActive && (
                          <span className="flex-shrink-0 text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-medium">
                            current
                          </span>
                        )}
                        <span className={`flex-shrink-0 text-xs px-1.5 py-0.5 rounded font-medium ${
                          wf.status === 'active' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                        }`}>
                          {wf.status}
                        </span>
                      </div>

                      {wf.description && (
                        <p className="text-xs text-gray-500 mt-0.5 truncate">{wf.description}</p>
                      )}

                      <div className="flex items-center gap-3 mt-1.5">
                        <span className="flex items-center gap-1 text-xs text-gray-400">
                          <GitBranch className="w-3 h-3" />
                          {nodeCount} nodes · {edgeCount} edges
                        </span>
                        <span className="flex items-center gap-1 text-xs text-gray-400">
                          <Clock className="w-3 h-3" />
                          {timeAgo(wf.updated_at)}
                        </span>
                      </div>
                    </div>

                    {/* Delete button */}
                    <button
                      onClick={e => handleDelete(wf, e)}
                      disabled={isDeleting}
                      className="flex-shrink-0 p-1.5 rounded text-gray-300 hover:text-red-500 hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100 disabled:opacity-50"
                      title="Delete workflow and all its executions"
                    >
                      {isDeleting
                        ? <Loader2 className="w-4 h-4 animate-spin" />
                        : <Trash2 className="w-4 h-4" />
                      }
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t flex-shrink-0 flex justify-between items-center">
          <span className="text-xs text-gray-400">
            {workflows.length} workflow{workflows.length !== 1 ? 's' : ''} · stored in PostgreSQL
          </span>
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
