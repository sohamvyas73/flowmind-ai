import { useState, useRef, useEffect } from 'react';
import { Save, Play, Trash2, Zap, FilePlus, Pencil, FolderOpen } from 'lucide-react';
import { useWorkflowStore } from '@/store/workflowStore';
import { workflowApi } from '@/services/api';
import { Workflow } from '@/types/workflow';
import { ExecutionModal } from './ExecutionModal';
import { LoadWorkflowModal } from './LoadWorkflowModal';

export function Toolbar() {
  const {
    nodes,
    edges,
    workflowName,
    workflowDescription,
    workflowId,
    showLivePanel,
    setWorkflowName,
    setWorkflowId,
    setShowLivePanel,
    setSelectedNode,
    loadWorkflow,
    clearWorkflow,
  } = useWorkflowStore();

  const [saving, setSaving] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [showExecuteModal, setShowExecuteModal] = useState(false);
  const [showLoadModal, setShowLoadModal] = useState(false);
  const nameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingName) nameInputRef.current?.select();
  }, [editingName]);

  const handleSave = async () => {
    if (nodes.length === 0) {
      alert('Please add at least one node before saving.');
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: workflowName,
        description: workflowDescription,
        graph_data: { nodes, edges },
      };

      if (workflowId) {
        await workflowApi.updateWorkflow(workflowId, payload);
      } else {
        const workflow = await workflowApi.createWorkflow(payload);
        setWorkflowId(workflow.id);
      }
    } catch (error) {
      console.error('Save failed:', error);
      alert('Failed to save workflow');
    } finally {
      setSaving(false);
    }
  };

  const handleExecute = () => {
    if (nodes.length === 0) {
      alert('Please add nodes to the workflow first');
      return;
    }
    setShowExecuteModal(true);
  };

  const handleRun = async (inputData: Record<string, unknown>) => {
    setExecuting(true);
    try {
      const payload = {
        name: workflowName,
        description: workflowDescription,
        graph_data: { nodes, edges },
      };
      const workflow = workflowId
        ? await workflowApi.updateWorkflow(workflowId, payload)
        : await workflowApi.createWorkflow(payload);
      if (!workflowId) setWorkflowId(workflow.id);
      return await workflowApi.executeWorkflow(workflow.id, inputData);
    } finally {
      setExecuting(false);
    }
  };

  const commitName = () => {
    setEditingName(false);
    if (!workflowName.trim()) setWorkflowName('Untitled Workflow');
  };

  return (
    <>
      <div className="bg-white rounded-lg shadow-lg border border-gray-200 px-4 py-2 flex items-center gap-3">

        {/* New */}
        <button
          onClick={() => {
            if (nodes.length === 0 || confirm('Start a new workflow? Unsaved changes will be lost.')) {
              clearWorkflow();
            }
          }}
          className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-md transition-colors"
          title="New Workflow"
        >
          <FilePlus className="w-4 h-4" />
          New
        </button>

        {/* Load */}
        <button
          onClick={() => setShowLoadModal(true)}
          className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-md transition-colors"
          title="Load Workflow"
        >
          <FolderOpen className="w-4 h-4" />
          Load
        </button>

        <div className="h-6 w-px bg-gray-300" />

        {/* Inline editable workflow name */}
        {editingName ? (
          <input
            ref={nameInputRef}
            type="text"
            value={workflowName}
            onChange={e => setWorkflowName(e.target.value)}
            onBlur={commitName}
            onKeyDown={e => {
              if (e.key === 'Enter' || e.key === 'Escape') commitName();
            }}
            className="px-2 py-1 text-sm font-medium border border-blue-400 rounded-md outline-none ring-2 ring-blue-100 min-w-[160px]"
          />
        ) : (
          <button
            onClick={() => setEditingName(true)}
            className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-md transition-colors group"
            title="Click to rename workflow"
          >
            <span className="max-w-[200px] truncate">{workflowName}</span>
            <Pencil className="w-3.5 h-3.5 text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity" />
          </button>
        )}

        <div className="h-6 w-px bg-gray-300" />

        {/* Save */}
        <button
          onClick={handleSave}
          disabled={saving || nodes.length === 0}
          className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 rounded-md transition-colors"
        >
          <Save className="w-4 h-4" />
          {saving ? 'Saving…' : workflowId ? 'Update' : 'Save'}
        </button>

        {/* Execute */}
        <button
          onClick={handleExecute}
          disabled={executing || nodes.length === 0}
          className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-white bg-green-600 hover:bg-green-700 disabled:bg-gray-400 rounded-md transition-colors"
        >
          <Play className="w-4 h-4" />
          {executing ? 'Running…' : 'Execute'}
        </button>

        {/* Clear */}
        <button
          onClick={() => {
            if (confirm('Are you sure you want to clear the workflow?')) clearWorkflow();
          }}
          disabled={nodes.length === 0}
          className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 disabled:bg-gray-400 rounded-md transition-colors"
        >
          <Trash2 className="w-4 h-4" />
          Clear
        </button>

        {/* Live API toggle */}
        <button
          onClick={() => { setShowLivePanel(!showLivePanel); setSelectedNode(null); }}
          className={`flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-md transition-colors ${
            showLivePanel
              ? 'text-yellow-700 bg-yellow-100 hover:bg-yellow-200'
              : workflowId
              ? 'text-white bg-yellow-500 hover:bg-yellow-600'
              : 'text-gray-600 bg-gray-100 hover:bg-gray-200'
          }`}
        >
          <Zap className="w-4 h-4" />
          Live API
          {workflowId && !showLivePanel && (
            <span className="w-2 h-2 rounded-full bg-green-400" />
          )}
        </button>

        <div className="text-xs text-gray-400 ml-1">
          {nodes.length} nodes · {edges.length} edges
        </div>
      </div>

      {showExecuteModal && (
        <ExecutionModal
          nodes={nodes}
          onClose={() => setShowExecuteModal(false)}
          onRun={handleRun}
        />
      )}

      {showLoadModal && (
        <LoadWorkflowModal
          onLoad={(wf: Workflow) => loadWorkflow(wf)}
          onClose={() => setShowLoadModal(false)}
        />
      )}
    </>
  );
}
