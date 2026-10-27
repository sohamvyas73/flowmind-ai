import { useEffect, useMemo, useState } from 'react';
import type { Node } from 'reactflow';
import { AlertTriangle, Lightbulb } from 'lucide-react';
import { useWorkflowStore } from '@/store/workflowStore';
import { useAuthStore } from '@/store/authStore';
import { ragApi, RagCollection, RagFile, RagSettings } from '@/services/api';
import { Field, Select, TextArea, inp } from './NodePropertiesPanel';

type Data = Record<string, unknown>;
type Up = (k: string, v: unknown) => void;
const ring = 'focus:ring-indigo-500';

function SetupBanner({ s }: { s: RagSettings | null }) {
  const { setView } = useAuthStore();
  if (!s || s.ready) return null;
  return (
    <div className="text-xs text-amber-900 bg-amber-50 border border-amber-200 rounded p-2 flex gap-2">
      <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
      <span>
        {s.configured ? 'Retrieval setup has a failing test.' : 'Retrieval is not set up yet.'} This node will refuse to run until you{' '}
        <button className="underline font-medium" onClick={() => setView('retrieval')}>choose an embedding model and vector store</button>.
      </span>
    </div>
  );
}

const Tip = ({ children }: { children: React.ReactNode }) => (
  <div className="flex gap-2 text-xs text-indigo-800 bg-indigo-50 border border-indigo-100 rounded p-2"><Lightbulb className="w-4 h-4 flex-shrink-0" /><div>{children}</div></div>
);

function CollectionField({ data, up, cols }: { data: Data; up: Up; cols: RagCollection[] }) {
  return (
    <Field label="Collection">
      <input list="fm-collections" type="text" value={(data.collection as string) || ''} onChange={e => up('collection', e.target.value)}
        placeholder="help" className={`${inp(ring)} font-mono`} />
      <datalist id="fm-collections">{cols.map(c => <option key={c.id} value={c.name} />)}</datalist>
      <p className="text-xs text-gray-400 mt-1">A named set of indexed documents. Index and Retrieve nodes that share a name share the data.</p>
    </Field>
  );
}

function Passages({ data, up, label }: { data: Data; up: Up; label: string }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      <Field label={label}>
        <input type="number" min={1} max={50} value={(data.topK as number) ?? 4} onChange={e => up('topK', Number(e.target.value))} className={inp(ring)} />
      </Field>
      <Field label="Minimum score (0–1)">
        <input type="number" min={0} max={1} step={0.05} value={(data.minScore as number) ?? 0} onChange={e => up('minScore', Number(e.target.value))} className={inp(ring)} />
      </Field>
    </div>
  );
}

export function RagNodeProperties({ node, data, up }: { node: Node; data: Data; up: Up }) {
  const [settings, setSettings] = useState<RagSettings | null>(null);
  const [cols, setCols] = useState<RagCollection[]>([]);
  const [files, setFiles] = useState<RagFile[]>([]);
  const { edges, previewSchemas } = useWorkflowStore();

  useEffect(() => {
    ragApi.settings().then(setSettings).catch(() => setSettings(null));
    ragApi.collections().then(setCols).catch(() => setCols([]));
    ragApi.files().then(setFiles).catch(() => setFiles([]));
  }, []);

  const upstreamCols = useMemo(() => {
    const e = edges.find(x => x.target === node.id);
    return e ? previewSchemas[e.source] ?? [] : [];
  }, [edges, previewSchemas, node.id]);

  const selected = (Array.isArray(data.fileNames) ? data.fileNames : []) as string[];

  return (
    <>
      <SetupBanner s={settings} />

      {node.type === 'indexDocsNode' && (
        <>
          <Tip>Turns documents into searchable chunks. Safe to re-run: unchanged documents are skipped, edited ones are replaced.</Tip>
          <CollectionField data={data} up={up} cols={cols} />
          <Field label="What to index">
            <Select value={(data.source as string) || 'files'} onChange={v => up('source', v)} ring={ring}>
              <option value="files">My uploaded documents (.txt .md .pdf)</option>
              <option value="dataset">A text column from a table (connect a data node)</option>
            </Select>
          </Field>
          {(data.source || 'files') === 'files' ? (
            <Field label="Documents (none ticked = all)">
              <div className="border border-gray-200 rounded-lg max-h-32 overflow-y-auto divide-y divide-gray-100">
                {files.length === 0 && <p className="text-xs text-gray-400 p-2">No documents yet — upload some on the Retrieval page.</p>}
                {files.map(f => (
                  <label key={f.id} className="flex items-center gap-2 px-2 py-1 text-xs">
                    <input type="checkbox" checked={selected.includes(f.name)}
                      onChange={e => up('fileNames', e.target.checked ? [...selected, f.name] : selected.filter(n => n !== f.name))} />
                    {f.name}
                  </label>
                ))}
              </div>
            </Field>
          ) : (
            <>
              <Field label="Text column">
                {upstreamCols.length > 0 ? (
                  <Select value={(data.textColumn as string) || ''} onChange={v => up('textColumn', v)} ring={ring}>
                    <option value="">— choose —</option>
                    {upstreamCols.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
                  </Select>
                ) : (
                  <input type="text" value={(data.textColumn as string) || ''} onChange={e => up('textColumn', e.target.value)} placeholder="body" className={`${inp(ring)} font-mono`} />
                )}
              </Field>
              <Field label="Name column (optional)">
                <input type="text" value={(data.sourceColumn as string) || ''} onChange={e => up('sourceColumn', e.target.value)} placeholder="id or title" className={`${inp(ring)} font-mono`} />
              </Field>
              {upstreamCols.length === 0 && <p className="text-xs text-gray-400">Click <b>Preview data</b> in the toolbar to see column names here.</p>}
            </>
          )}
          <div className="grid grid-cols-2 gap-2">
            <Field label="Chunk size (chars)"><input type="number" min={100} max={4000} value={(data.chunkSize as number) ?? 800} onChange={e => up('chunkSize', Number(e.target.value))} className={inp(ring)} /></Field>
            <Field label="Overlap"><input type="number" min={0} max={1000} value={(data.overlap as number) ?? 100} onChange={e => up('overlap', Number(e.target.value))} className={inp(ring)} /></Field>
          </div>
          <label className="flex items-center gap-2 text-xs text-gray-700">
            <input type="checkbox" checked={!!data.removeMissing} onChange={e => up('removeMissing', e.target.checked)} />
            Remove documents from the collection that are no longer in this list
          </label>
        </>
      )}

      {node.type === 'retrieveNode' && (
        <>
          <Tip>Finds the passages most relevant to a question. Use <code>{'{{field}}'}</code> to take the question from an earlier node.</Tip>
          <CollectionField data={data} up={up} cols={cols} />
          <Field label="Question"><TextArea value={(data.query as string) || ''} onChange={v => up('query', v)} rows={2} placeholder="{{question}}" ring={ring} /></Field>
          <Passages data={data} up={up} label="Passages to return" />
          <p className="text-xs text-gray-400">Output: <span className="font-mono">passages, context, count, top_score</span></p>
        </>
      )}

      {node.type === 'ragAnswerNode' && (
        <>
          <Tip>Retrieves passages, then answers <b>only</b> from them, with [1] [2] citations. If nothing relevant is found it says so without calling the AI.</Tip>
          <CollectionField data={data} up={up} cols={cols} />
          <Field label="Question"><TextArea value={(data.question as string) || ''} onChange={v => up('question', v)} rows={2} placeholder="{{question}}" ring={ring} /></Field>
          <Passages data={data} up={up} label="Passages to use" />
          <Field label="Extra instructions (optional)"><TextArea value={(data.instructions as string) || ''} onChange={v => up('instructions', v)} rows={2} placeholder="Answer in two sentences." ring={ring} /></Field>
          <Field label="When nothing is found, say"><input type="text" value={(data.noAnswerText as string) || ''} onChange={e => up('noAnswerText', e.target.value)} className={inp(ring)} /></Field>
          <p className="text-xs text-gray-400">Output: <span className="font-mono">answer, citations, passages, grounded</span></p>
        </>
      )}
    </>
  );
}
