import { useState, useEffect } from 'react';
import {
  ArrowLeft, Save, Eye, EyeOff, CheckCircle2, AlertCircle,
  Loader2, Info, Cpu, Zap,
} from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { configApi, UserConfig, ConfigUpdatePayload } from '@/services/api';

// ── Model options per provider ─────────────────────────────────────────────────

const OPENAI_MODELS = [
  'gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo', 'o1-mini', 'o1-preview',
];
const ANTHROPIC_MODELS = [
  'claude-opus-4-8', 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001',
];
const GEMINI_MODELS = [
  'gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-2.0-flash', 'gemini-2.5-pro',
];

// ── Provider card state ────────────────────────────────────────────────────────

interface ProviderDraft {
  useCustom: boolean;
  apiKey: string;      // new value (empty = unchanged)
  model: string;
  showKey: boolean;
}

const EMPTY_DRAFT: ProviderDraft = { useCustom: false, apiKey: '', model: '', showKey: false };

// ── Main component ─────────────────────────────────────────────────────────────

export function ConfigPage() {
  const { setView } = useAuthStore();
  const [config, setConfig] = useState<UserConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  const [openai, setOpenai] = useState<ProviderDraft>(EMPTY_DRAFT);
  const [anthropic, setAnthropic] = useState<ProviderDraft>(EMPTY_DRAFT);
  const [gemini, setGemini] = useState<ProviderDraft>(EMPTY_DRAFT);

  useEffect(() => {
    configApi.getMyConfig()
      .then(cfg => {
        setConfig(cfg);
        setOpenai(d => ({
          ...d,
          useCustom: cfg.openai.api_key_set,
          model: cfg.openai.model || cfg.openai.effective_model,
        }));
        setAnthropic(d => ({
          ...d,
          useCustom: cfg.anthropic.api_key_set,
          model: cfg.anthropic.model || cfg.anthropic.effective_model,
        }));
        setGemini(d => ({
          ...d,
          useCustom: cfg.gemini.api_key_set,
          model: cfg.gemini.model || cfg.gemini.effective_model,
        }));
      })
      .catch(() => setError('Failed to load configuration.'))
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setError('');
    setSaved(false);
    try {
      const payload: ConfigUpdatePayload = {};

      if (!openai.useCustom) {
        payload.clear_openai_api_key = true;
      } else if (openai.apiKey) {
        payload.openai_api_key = openai.apiKey;
      }
      if (openai.useCustom) payload.openai_model = openai.model || undefined;

      if (!anthropic.useCustom) {
        payload.clear_anthropic_api_key = true;
      } else if (anthropic.apiKey) {
        payload.anthropic_api_key = anthropic.apiKey;
      }
      if (anthropic.useCustom) payload.anthropic_model = anthropic.model || undefined;

      if (!gemini.useCustom) {
        payload.clear_gemini_api_key = true;
      } else if (gemini.apiKey) {
        payload.gemini_api_key = gemini.apiKey;
      }
      if (gemini.useCustom) payload.gemini_model = gemini.model || undefined;

      const updated = await configApi.updateMyConfig(payload);
      setConfig(updated);
      // Clear entered keys after save
      setOpenai(d => ({ ...d, apiKey: '' }));
      setAnthropic(d => ({ ...d, apiKey: '' }));
      setGemini(d => ({ ...d, apiKey: '' }));
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch {
      setError('Failed to save configuration.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top bar */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4">
        <button
          onClick={() => setView('canvas')}
          className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Canvas
        </button>
        <div className="h-5 w-px bg-gray-300" />
        <h1 className="text-lg font-semibold text-gray-900">Model & API Settings</h1>
      </div>

      <div className="max-w-3xl mx-auto px-6 py-8 space-y-6">

        {/* Info banner */}
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 flex gap-3">
          <Info className="w-4 h-4 text-blue-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-blue-800">How key resolution works</p>
            <p className="text-sm text-blue-700 mt-0.5">
              Your custom keys take priority. If not set, the platform defaults configured by your admin are used.
              Env-level keys are the final fallback. AI nodes in workflows use the Gemini key.
            </p>
          </div>
        </div>

        {/* Provider cards */}
        <ProviderCard
          provider="openai"
          label="OpenAI"
          color="green"
          icon="🟢"
          models={OPENAI_MODELS}
          config={config?.openai}
          draft={openai}
          onChange={setOpenai}
          note="Used for GPT-based nodes (future)"
        />

        <ProviderCard
          provider="anthropic"
          label="Anthropic"
          color="orange"
          icon="🟠"
          models={ANTHROPIC_MODELS}
          config={config?.anthropic}
          draft={anthropic}
          onChange={setAnthropic}
          note="Used for Claude-based nodes (future)"
        />

        <ProviderCard
          provider="gemini"
          label="Google Gemini"
          color="blue"
          icon="🔵"
          models={GEMINI_MODELS}
          config={config?.gemini}
          draft={gemini}
          onChange={setGemini}
          note="Active engine for AI nodes, verification, and decision nodes"
          isActive
        />

        {/* Error / Save */}
        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        <div className="flex items-center justify-between pt-2">
          {saved && (
            <div className="flex items-center gap-2 text-green-600 text-sm">
              <CheckCircle2 className="w-4 h-4" />
              Configuration saved!
            </div>
          )}
          <div className="ml-auto">
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-2 px-6 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white text-sm font-semibold rounded-lg transition-colors"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              {saving ? 'Saving…' : 'Save Configuration'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Provider card ──────────────────────────────────────────────────────────────

interface ProviderCardProps {
  provider: 'openai' | 'anthropic' | 'gemini';
  label: string;
  color: string;
  icon: string;
  models: string[];
  config: UserConfig['openai'] | undefined;
  draft: ProviderDraft;
  onChange: (fn: (d: ProviderDraft) => ProviderDraft) => void;
  note?: string;
  isActive?: boolean;
}

function ProviderCard({ label, icon, models, config, draft, onChange, note, isActive }: ProviderCardProps) {
  const sourceLabel = config?.source === 'user' ? 'Custom key' : config?.source === 'platform' ? 'Platform default' : 'Environment';

  return (
    <div className={`bg-white rounded-xl border ${isActive ? 'border-blue-300 shadow-sm shadow-blue-100' : 'border-gray-200'} overflow-hidden`}>
      <div className="px-5 py-4 flex items-start justify-between border-b border-gray-100">
        <div className="flex items-center gap-3">
          <span className="text-xl">{icon}</span>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-gray-900">{label}</h3>
              {isActive && (
                <span className="flex items-center gap-1 text-xs font-medium text-blue-700 bg-blue-100 px-2 py-0.5 rounded-full">
                  <Zap className="w-3 h-3" />
                  Active engine
                </span>
              )}
            </div>
            {note && <p className="text-xs text-gray-500 mt-0.5">{note}</p>}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs text-gray-400">{sourceLabel}</div>
          <div className="text-xs font-mono text-gray-600 mt-0.5">{config?.effective_model}</div>
        </div>
      </div>

      <div className="px-5 py-4 space-y-4">
        {/* Toggle */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-gray-700">Use custom API key</p>
            <p className="text-xs text-gray-500">Override the platform default for your account</p>
          </div>
          <button
            onClick={() => onChange(d => ({ ...d, useCustom: !d.useCustom }))}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              draft.useCustom ? 'bg-blue-600' : 'bg-gray-200'
            }`}
          >
            <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${
              draft.useCustom ? 'translate-x-6' : 'translate-x-1'
            }`} />
          </button>
        </div>

        {draft.useCustom && (
          <>
            {/* API key input */}
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1.5">
                API Key
                {config?.api_key_set && (
                  <span className="ml-2 text-green-600 font-normal">
                    (currently: {config.api_key_masked})
                  </span>
                )}
              </label>
              <div className="relative">
                <input
                  type={draft.showKey ? 'text' : 'password'}
                  placeholder={config?.api_key_set ? 'Enter new key to replace…' : 'sk-…'}
                  value={draft.apiKey}
                  onChange={e => onChange(d => ({ ...d, apiKey: e.target.value }))}
                  className="w-full px-3 py-2 pr-10 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-400 font-mono"
                />
                <button
                  type="button"
                  onClick={() => onChange(d => ({ ...d, showKey: !d.showKey }))}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                >
                  {draft.showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Model selection */}
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1.5">
                <Cpu className="inline w-3 h-3 mr-1" />
                Model
              </label>
              <select
                value={draft.model}
                onChange={e => onChange(d => ({ ...d, model: e.target.value }))}
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-400 bg-white"
              >
                <option value="">— Use platform default —</option>
                {models.map(m => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
          </>
        )}

        {!draft.useCustom && config && (
          <div className="bg-gray-50 rounded-lg px-4 py-3 flex items-center gap-3">
            <CheckCircle2 className="w-4 h-4 text-green-500 flex-shrink-0" />
            <div>
              <p className="text-xs font-medium text-gray-700">
                Using {config.source === 'platform' ? 'platform default' : 'environment'} key
              </p>
              <p className="text-xs text-gray-500">
                Model: <span className="font-mono">{config.effective_model}</span>
                {config.effective_key_masked && ` · Key: ${config.effective_key_masked}`}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
