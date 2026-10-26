import { ShieldAlert } from 'lucide-react';
import type { DatasetRef } from '@/services/api';

/** Schema + sample rows of a DatasetRef. PII columns arrive pre-masked from the server. */
export function DatasetTable({ dataset, maxHeight = '50vh' }: { dataset: DatasetRef; maxHeight?: string }) {
  const rows = dataset.row_count;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3 text-xs text-gray-600">
        <span>{dataset.columns.length} columns</span>
        {rows != null && <span>{rows.toLocaleString()} rows{dataset.row_count_is_estimate ? ' (estimate)' : ''}</span>}
        {dataset.size_bytes != null && <span>{formatBytes(dataset.size_bytes)}</span>}
        {dataset.columns.some(c => c.tags.includes('pii')) && (
          <span className="text-amber-700 flex items-center gap-1">
            <ShieldAlert className="w-3 h-3" /> Possible PII columns are masked in previews
          </span>
        )}
      </div>
      <div className="overflow-auto border border-gray-200 rounded-lg" style={{ maxHeight }}>
        <table className="min-w-full text-xs">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              {dataset.columns.map(c => (
                <th key={c.name} className="text-left px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                  {c.name}
                  <span className="block font-normal text-gray-400">{c.type}{c.tags.includes('pii') ? ' · pii' : ''}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dataset.sample.map((row, i) => (
              <tr key={i} className="border-t border-gray-100">
                {dataset.columns.map(c => (
                  <td key={c.name} className="px-3 py-1.5 text-gray-700 whitespace-nowrap max-w-[240px] truncate">
                    {row[c.name] == null ? <span className="text-gray-300">null</span> : String(row[c.name])}
                  </td>
                ))}
              </tr>
            ))}
            {dataset.sample.length === 0 && (
              <tr><td colSpan={dataset.columns.length} className="px-3 py-4 text-center text-gray-400">No rows</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {dataset.sample.length > 0 && rows != null && rows > dataset.sample.length && (
        <p className="text-[11px] text-gray-400">Showing the first {dataset.sample.length} rows.</p>
      )}
    </div>
  );
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}
