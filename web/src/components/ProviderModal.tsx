import { useEffect, useState } from "react";
import { api, type ProviderInfo } from "../api";

const DESCRIPTIONS: Record<string, string> = {
  claude:
    "Claude (Anthropic). Direção de edição completa: cortes, transições, efeitos e destaques. Recomendado.",
  openai:
    "ChatGPT (OpenAI). Mesma direção de edição, usando modelos GPT.",
  ollama:
    "Modelo local (Ollama). Roda no seu PC, sem custo por análise — precisa do Ollama instalado.",
};

const KEY_HELP: Record<string, { label: string; url: string }> = {
  claude: {
    label: "Criar chave em console.anthropic.com",
    url: "https://console.anthropic.com/settings/keys",
  },
  openai: {
    label: "Criar chave em platform.openai.com",
    url: "https://platform.openai.com/api-keys",
  },
};

interface Props {
  onClose: () => void;
  onSaved?: () => void;
}

export default function ProviderModal({ onClose, onSaved }: Props) {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [active, setActive] = useState("");
  const [selected, setSelected] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .providers()
      .then((d) => {
        setProviders(d.providers);
        setActive(d.active);
        select(d.providers.find((p) => p.id === d.active) || d.providers[0]);
      })
      .catch((e) => setError(String(e.message || e)));
  }, []);

  const select = (p: ProviderInfo) => {
    setSelected(p.id);
    setModel(p.model || "");
    setBaseUrl(p.base_url || "");
    setApiKey("");
    setSaved(false);
  };

  const current = providers.find((p) => p.id === selected);

  const save = async () => {
    if (!current) return;
    setSaving(true);
    setError("");
    try {
      const payload: Record<string, unknown> = {
        provider_id: current.id,
        model,
        active: true,
      };
      if (apiKey.trim()) payload.api_key = apiKey.trim();
      if (current.supports_base_url) payload.base_url = baseUrl;
      const res = await api.saveProvider(payload as any);
      setProviders(res.providers);
      setActive(res.active);
      setSaved(true);
      onSaved?.();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal provider-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Inteligência artificial (diretor de edição)</h3>
          <button className="ghost" onClick={onClose}>
            ✕
          </button>
        </div>
        <p className="hint">
          A IA é o “diretor” da sua edição: escolhe os melhores momentos,
          transições e efeitos automaticamente durante a análise. Sem IA
          configurada, o editor usa a heurística local (mais simples).
        </p>

        <div className="provider-list">
          {providers.map((p) => (
            <button
              key={p.id}
              className={`provider-card ${p.id === selected ? "selected" : ""}`}
              onClick={() => select(p)}
            >
              <span className="provider-name">
                {p.label}
                {p.id === active && <em className="active-tag">em uso</em>}
                {p.has_key && <em className="ok-tag">configurado</em>}
              </span>
              <span className="provider-desc">
                {DESCRIPTIONS[p.id] || ""}
              </span>
            </button>
          ))}
        </div>

        {current && (
          <div className="provider-form">
            {current.requires_api_key && (
              <>
                <label>
                  API key {current.has_key && <small>(já salva — deixe vazio para manter)</small>}
                  <input
                    type="password"
                    placeholder="cole sua API key aqui"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                  />
                </label>
                {KEY_HELP[current.id] && (
                  <a
                    className="hint"
                    href={KEY_HELP[current.id].url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {KEY_HELP[current.id].label} ↗
                  </a>
                )}
              </>
            )}
            <label>
              Modelo
              <input
                placeholder={current.model || "padrão do provedor"}
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
            </label>
            {current.supports_base_url && (
              <label>
                URL base (opcional)
                <input
                  placeholder="http://localhost:11434"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                />
              </label>
            )}
            <button className="accent" onClick={save} disabled={saving}>
              {saving ? "Salvando…" : "Salvar e usar esta IA"}
            </button>
            {saved && (
              <p className="ok-msg">
                Salvo! A próxima análise usará {current.label} como diretor.
              </p>
            )}
            {error && <p className="error">{error}</p>}
          </div>
        )}
      </div>
    </div>
  );
}
