import { useState } from 'react';
import { CheckCircle2, XCircle, AlertTriangle, ChevronDown, ChevronRight, ShieldAlert } from 'lucide-react';
import type { QualityReport, QualityRuleResult, DataProfile } from '@/services/api';

/** Pass/fail report of a Quality Check node, with example offending rows for each failed check. */
export function QualityReportView({ report }: { report: QualityReport }) {
  return (
    <div className="space-y-2">
      <div className={`flex items-center gap-2 text-sm font-medium rounded-lg px-3 py-2 ${report.passed ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
        {report.passed ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
        {report.passed
          ? `All ${report.checks} checks passed`
          : `${report.failed_errors} of ${report.checks} checks failed`}
        {report.failed_warnings > 0 && <span className="text-amber-600 font-normal"> · {report.failed_warnings} warning(s)</span>}
        <span className="ml-auto text-xs font-normal text-gray-500">{report.total_rows.toLocaleString()} rows checked</span>
      </div>
      <div className="border border-gray-200 rounded-lg divide-y divide-gray-100">
        {report.rules.map(r => <RuleRow key={r.id} rule={r} />)}
      </div>
    </div>
  );
}

function RuleRow({ rule }: { rule: QualityRuleResult }) {
  const [open, setOpen] = useState(false);
  const failed = rule.status === 'fail';
  const icon = !failed ? <CheckCircle2 className="w-4 h-4 text-green-600 flex-shrink-0" />
    : rule.severity === 'warn' ? <AlertTriangle className="w-4 h-4 text-amber-500 flex-shrink-0" />
    : <XCircle className="w-4 h-4 text-red-600 flex-shrink-0" />;
  const cols = rule.examples[0] ? Object.keys(rule.examples[0]) : [];
  return (
    <div>
      <button onClick={() => failed && rule.examples.length > 0 && setOpen(o => !o)}
        className="w-full flex items-start gap-3 px-3 py-2 text-left">
        {icon}
        <div className="min-w-0 flex-1">
          <p className="text-sm text-gray-900">{rule.description}
            {rule.severity === 'warn' && <span className="ml-2 text-[10px] uppercase tracking-wide text-amber-600 border border-amber-200 rounded px-1">warn only</span>}
          </p>
          {failed && rule.message && <p className="text-xs text-red-600 mt-0.5">{rule.message}</p>}
        </div>
        {failed && rule.examples.length > 0 && (open ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />)}
      </button>
      {open && cols.length > 0 && (
        <div className="px-10 pb-3">
          <p className="text-xs text-gray-500 mb-1">Examples ({rule.examples.length} shown)</p>
          <div className="overflow-auto border border-gray-200 rounded">
            <table className="min-w-full text-xs">
              <thead className="bg-gray-50"><tr>{cols.map(c => <th key={c} className="text-left px-2 py-1 font-semibold text-gray-600">{c}</th>)}</tr></thead>
              <tbody>
                {rule.examples.map((row, i) => (
                  <tr key={i} className="border-t border-gray-100">
                    {cols.map(c => <td key={c} className="px-2 py-1 whitespace-nowrap">{row[c] == null ? <span className="text-gray-300">null</span> : String(row[c])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/** Per-column statistics. Personal-data columns show no values. */
export function ProfileTable({ profile }: { profile: DataProfile }) {
  return (
    <div className="space-y-2">
      <p className="text-xs text-gray-600">{profile.total_rows.toLocaleString()} rows · {profile.columns.length} columns</p>
      <div className="overflow-auto border border-gray-200 rounded-lg max-h-[50vh]">
        <table className="min-w-full text-xs">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              {['Column', 'Type', 'Empty', 'Different values', 'Smallest', 'Largest', 'Average'].map(h =>
                <th key={h} className="text-left px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {profile.columns.map(c => (
              <tr key={c.name} className="border-t border-gray-100">
                <td className="px-3 py-1.5 font-medium text-gray-900 whitespace-nowrap">
                  {c.name}{c.pii && <ShieldAlert className="inline w-3 h-3 ml-1 text-amber-600" />}
                </td>
                <td className="px-3 py-1.5 text-gray-500">{c.type}</td>
                <td className={`px-3 py-1.5 ${c.nulls > 0 ? 'text-amber-700' : 'text-gray-500'}`}>{c.nulls} ({c.null_pct}%)</td>
                <td className="px-3 py-1.5 text-gray-700">{c.distinct.toLocaleString()}</td>
                <td className="px-3 py-1.5 text-gray-700 max-w-[140px] truncate">{c.pii ? <span className="text-gray-300">hidden</span> : c.min ?? ''}</td>
                <td className="px-3 py-1.5 text-gray-700 max-w-[140px] truncate">{c.pii ? <span className="text-gray-300">hidden</span> : c.max ?? ''}</td>
                <td className="px-3 py-1.5 text-gray-700">{c.pii ? '' : c.mean ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
