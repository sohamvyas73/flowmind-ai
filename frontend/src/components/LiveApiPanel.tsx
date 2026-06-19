import { useState, useEffect, useRef } from 'react';
import { X, Copy, Check, Send, Loader2, Zap, Upload, FileText, Database, Key } from 'lucide-react';
import { useWorkflowStore } from '@/store/workflowStore';
import { workflowApi } from '@/services/api';
import { useAuthStore } from '@/store/authStore';
import { InputField } from '@/types/workflow';
import { Node } from 'reactflow';

const BASE_URL = 'http://localhost:8000';

const MAX_STR = 300;

function sanitizeForDisplay(value: unknown): unknown {
  if (typeof value === 'string') {
    if (value.startsWith('data:')) {
      const mime = value.split(';')[0].replace('data:', '');
      const sizeKb = Math.round((value.length * 0.75) / 1024);
      return `[file: ${mime}, ~${sizeKb} KB]`;
    }
    return value.length > MAX_STR ? `${value.slice(0, MAX_STR)}… [${value.length} chars]` : value;
  }
  if (Array.isArray(value)) return value.map(sanitizeForDisplay);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, sanitizeForDisplay(v)])
    );
  }
  return value;
}

function getNodeFields(node: Node): InputField[] {
  const data = node.data as Record<string, unknown>;
  if (Array.isArray(data.fields) && data.fields.length > 0) return data.fields as InputField[];
  return [{ id: 'default', name: 'input', type: (data.inputType as InputField['type']) || 'text' }];
}

interface FieldState {
  nodeId: string;
  fieldId: string;
  fieldName: string;
  fieldType: string;
  value: string;
  filename?: string;
}

export function LiveApiPanel() {
  const { workflowId, nodes, setShowLivePanel } = useWorkflowStore();
  const { user } = useAuthStore();

  const inputNodes = nodes.filter(n => n.type === 'inputNode');

  // Stable key that changes when node fields change (not just node IDs)
  const nodesKey = inputNodes
    .map(n => {
      const fields = getNodeFields(n);
      return `${n.id}:${fields.map(f => `${f.id}:${f.name}:${f.type}`).join(',')}`;
    })
    .join('|');

  const [fields, setFields] = useState<Record<string, FieldState>>({});
  const [sending, setSending] = useState(false);
  const [response, setResponse] = useState<unknown>(null);
  const [responseStatus, setResponseStatus] = useState<'ok' | 'err' | null>(null);
  const [copied, setCopied] = useState<'url' | 'curl' | null>(null);

  // Re-init fields when input node structure changes, preserving existing values
  useEffect(() => {
    setFields(prev => {
      const next: Record<string, FieldState> = {};
      inputNodes.forEach(node => {
        getNodeFields(node).forEach(field => {
          const key = `${node.id}__${field.id}`;
          next[key] = {
            nodeId: node.id,
            fieldId: field.id,
            fieldName: field.name,
            fieldType: field.type,
            value: prev[key]?.value ?? '',
            filename: prev[key]?.filename,
          };
        });
      });
      return next;
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodesKey, workflowId]);

  const endpoint = workflowId
    ? `${BASE_URL}/api/v1/workflows/workflows/${workflowId}/trigger`
    : null;

  // Actual body to send — field name as key, value (or base64) as value
  const buildBody = (): Record<string, unknown> => {
    const body: Record<string, unknown> = {};
    Object.values(fields).forEach(f => {
      if (f.value) body[f.fieldName || f.fieldId] = f.value;
    });
    return body;
  };

  // Display-safe body for cURL snippet (file content replaced with placeholder)
  const buildDisplayBody = (): Record<string, unknown> => {
    const body: Record<string, unknown> = {};
    const allFields = Object.values(fields);
    const hasValues = allFields.some(f => f.value);

    allFields.forEach(f => {
      const key = f.fieldName || f.fieldId || 'field';
      if (hasValues) {
        if (!f.value) return;
        if (f.fieldType === 'file') {
          body[key] = f.filename ? `<content of ${f.filename}>` : '<file_content>';
        } else {
          body[key] = f.value;
        }
      } else {
        // placeholder when nothing filled
        if (f.fieldType === 'file') body[key] = '<file_content>';
        else if (f.fieldType === 'json') body[key] = { key: 'value' };
        else if (f.fieldType === 'number') body[key] = 0;
        else body[key] = `<${key}>`;
      }
    });
    return body;
  };

  const curlBody = JSON.stringify(buildDisplayBody(), null, 2);
  const apiToken = user?.api_token ?? '<your-api-token>';
  const curlSnippet = endpoint
    ? `curl -X POST "${endpoint}" \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer ${apiToken}" \\\n  -d '${curlBody.replace(/\n/g, '\n       ')}'`
    : '';

  const copy = async (text: string, which: 'url' | 'curl') => {
    await navigator.clipboard.writeText(text);
    setCopied(which);
    setTimeout(() => setCopied(null), 1500);
  };

  const handleFileChange = (key: string, file: File) => {
    const reader = new FileReader();
    reader.onload = e => {
      setFields(prev => ({
        ...prev,
        [key]: { ...prev[key], value: e.target?.result as string, filename: file.name },
      }));
    };
    const isText = file.type.startsWith('text/') || /\.(txt|csv|json|xml|md)$/i.test(file.name);
    if (isText) reader.readAsText(file);
    else reader.readAsDataURL(file);
  };

  const clearFile = (key: string) => {
    setFields(prev => ({ ...prev, [key]: { ...prev[key], value: '', filename: undefined } }));
  };

  const handleSend = async () => {
    if (!workflowId) return;
    setSending(true);
    setResponse(null);
    setResponseStatus(null);
    try {
      const res = await workflowApi.triggerWorkflow(workflowId, buildBody());
      setResponse(res);
      setResponseStatus('ok');
    } catch (e: unknown) {
      const err = e as { response?: { data?: unknown }; message?: string };
      setResponse(err?.response?.data ?? { error: err?.message ?? 'Request failed' });
      setResponseStatus('err');
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="absolute right-4 top-4 w-96 bg-white rounded-lg shadow-xl border border-gray-200 z-10 flex flex-col max-h-[calc(100vh-32px)]">

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b flex-shrink-0">
        <div className="flex items-center gap-2">
          <Zap className="w-4 h-4 text-yellow-500" />
          <span className="text-sm font-semibold text-gray-800">Live API</span>
        </div>
        <button onClick={() => setShowLivePanel(false)} className="text-gray-400 hover:text-gray-600 transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="overflow-y-auto flex-1 p-4 space-y-4">

        {/* Unsaved warning */}
        {!workflowId && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-center">
            <Zap className="w-6 h-6 text-amber-500 mx-auto mb-2" />
            <p className="text-sm font-medium text-amber-800">Save workflow first</p>
            <p className="text-xs text-amber-600 mt-1">Save your workflow to activate its live API endpoint.</p>
          </div>
        )}

        {workflowId && (
          <>
            {/* Endpoint */}
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Endpoint</p>
              <div className="flex items-center gap-2 bg-gray-900 rounded-lg px-3 py-2">
                <span className="text-xs font-bold text-green-400 flex-shrink-0">POST</span>
                <span className="text-xs text-gray-300 flex-1 truncate font-mono">
                  …/workflows/{workflowId.slice(0, 8)}…/trigger
                </span>
                <button
                  onClick={() => copy(endpoint!, 'url')}
                  className="text-gray-400 hover:text-white transition-colors flex-shrink-0"
                  title="Copy full URL"
                >
                  {copied === 'url' ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            {/* API Token */}
            {user && (
              <div>
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Your API Token</p>
                <div className="flex items-center gap-2 bg-gray-900 rounded-lg px-3 py-2">
                  <Key className="w-3.5 h-3.5 text-yellow-400 flex-shrink-0" />
                  <span className="text-xs text-gray-300 flex-1 truncate font-mono">
                    {user.api_token.slice(0, 16)}…
                  </span>
                  <button
                    onClick={() => copy(user.api_token, 'url')}
                    className="text-gray-400 hover:text-white transition-colors flex-shrink-0"
                    title="Copy API token"
                  >
                    {copied === 'url' ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
                  </button>
                </div>
                <p className="text-xs text-gray-400 mt-1">Include this token in the Authorization header to authenticate your requests.</p>
              </div>
            )}

            {/* cURL */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">cURL</p>
                <button
                  onClick={() => copy(curlSnippet, 'curl')}
                  className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
                >
                  {copied === 'curl' ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}
                  {copied === 'curl' ? 'Copied!' : 'Copy'}
                </button>
              </div>
              <pre className="bg-gray-900 rounded-lg p-3 text-xs text-gray-300 font-mono overflow-x-auto whitespace-pre-wrap break-all">
                {curlSnippet}
              </pre>
            </div>

            {/* Dynamic input fields grouped by node */}
            <div className="space-y-5">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                {inputNodes.length ? 'Request Inputs' : 'Request Body'}
              </p>

              {inputNodes.length === 0 && (
                <p className="text-xs text-gray-400">No input nodes in this workflow.</p>
              )}

              {inputNodes.map(node => {
                const nodeFields = Object.values(fields).filter(f => f.nodeId === node.id);
                return (
                  <div key={node.id}>
                    <div className="flex items-center gap-1.5 mb-2">
                      <Database className="w-3.5 h-3.5 text-blue-500 flex-shrink-0" />
                      <span className="text-xs font-semibold text-gray-700">{node.data.label as string}</span>
                    </div>

                    <div className="space-y-3 pl-3 border-l-2 border-blue-100">
                      {nodeFields.map(field => {
                        const key = `${field.nodeId}__${field.fieldId}`;
                        return (
                          <div key={key}>
                            <label className="flex items-center gap-1.5 mb-1.5">
                              <span className="text-xs font-mono font-medium text-gray-800">
                                {field.fieldName || field.fieldId}
                              </span>
                              <span className="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
                                {field.fieldType}
                              </span>
                            </label>

                            {field.fieldType === 'file' ? (
                              <FileUploadField
                                filename={field.filename}
                                onChange={file => handleFileChange(key, file)}
                                onClear={() => clearFile(key)}
                              />
                            ) : (
                              <textarea
                                rows={field.fieldType === 'json' ? 3 : 2}
                                placeholder={
                                  field.fieldType === 'json' ? '{"key": "value"}' :
                                  field.fieldType === 'number' ? '0' :
                                  `Enter ${field.fieldName || 'value'}…`
                                }
                                value={field.value}
                                onChange={e => setFields(prev => ({
                                  ...prev,
                                  [key]: { ...prev[key], value: e.target.value },
                                }))}
                                spellCheck={false}
                                className={`w-full px-3 py-2 text-xs border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-yellow-400 resize-none bg-gray-50 ${field.fieldType === 'json' ? 'font-mono' : ''}`}
                              />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Send button */}
            <button
              onClick={handleSend}
              disabled={sending}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white bg-yellow-500 hover:bg-yellow-600 disabled:bg-gray-300 rounded-lg transition-colors"
            >
              {sending
                ? <><Loader2 className="w-4 h-4 animate-spin" /> Sending…</>
                : <><Send className="w-4 h-4" /> Send Request</>
              }
            </button>

            {/* Response */}
            {response !== null && (
              <div>
                <div className="flex items-center gap-2 mb-1.5">
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Response</p>
                  <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${responseStatus === 'ok' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                    {responseStatus === 'ok' ? '200 OK' : 'Error'}
                  </span>
                </div>
                <pre className={`rounded-lg p-3 text-xs font-mono overflow-x-auto whitespace-pre-wrap break-all max-h-60 ${responseStatus === 'ok' ? 'bg-gray-900 text-gray-200' : 'bg-red-50 text-red-700 border border-red-200'}`}>
                  {JSON.stringify(sanitizeForDisplay(response), null, 2)}
                </pre>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function FileUploadField({
  filename,
  onChange,
  onClear,
}: {
  filename?: string;
  onChange: (f: File) => void;
  onClear: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);

  if (filename) {
    return (
      <div className="flex items-center gap-2 border border-green-300 bg-green-50 rounded-lg px-3 py-2">
        <FileText className="w-4 h-4 text-green-600 flex-shrink-0" />
        <span className="text-xs text-green-700 font-medium flex-1 truncate">{filename}</span>
        <button
          onClick={onClear}
          className="text-green-500 hover:text-red-500 transition-colors flex-shrink-0"
          title="Remove file"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div
      onClick={() => ref.current?.click()}
      className="border-2 border-dashed border-gray-300 rounded-lg p-3 text-center cursor-pointer hover:border-yellow-400 hover:bg-yellow-50/50 transition-colors"
    >
      <input
        ref={ref}
        type="file"
        className="hidden"
        onChange={e => e.target.files?.[0] && onChange(e.target.files[0])}
      />
      <Upload className="w-4 h-4 text-gray-400 mx-auto mb-1" />
      <p className="text-xs text-gray-500">Click to upload</p>
      <p className="text-xs text-gray-400 mt-0.5">PDF, image, CSV, TXT…</p>
    </div>
  );
}
