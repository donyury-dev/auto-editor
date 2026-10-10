import type { Timeline } from "../types";

interface HookPanelProps {
  timeline: Timeline;
  onChange: (t: Timeline) => void;
}

const DEFAULT_HOOK = {
  id: "hook-1",
  enabled: true,
  text: "VOCÊ SABIA?",
  start: 0,
  end: 2.5,
  color: "#FFFFFF",
  highlight_color: "#FF3B30",
  effect: "pulse" as const,
  scale: 1.2,
  x: 0.5,
  y: 0.3,
  font_family: "Anton",
};

export default function HookPanel({ timeline, onChange }: HookPanelProps) {
  const hook = timeline.hook || { ...DEFAULT_HOOK, enabled: false };

  const updateHook = (patch: Partial<typeof hook>) => {
    const next = { ...(hook || DEFAULT_HOOK), ...patch };
    onChange({ ...timeline, hook: next });
  };

  return (
    <div className="hook-panel">
      <h3>Gancho (início do vídeo)</h3>
      <label className="toggle">
        <input
          type="checkbox"
          checked={hook.enabled}
          onChange={(e) => updateHook({ enabled: e.target.checked })}
        />
        Ativar gancho
      </label>

      {hook.enabled && (
        <>
          <label>
            Texto do gancho
            <input
              value={hook.text}
              maxLength={60}
              placeholder="Ex: Você sabia disso?"
              onChange={(e) => updateHook({ text: e.target.value })}
            />
          </label>

          <label>
            Duração: {hook.end.toFixed(1)}s
            <input
              type="range"
              min={5}
              max={50}
              value={Math.round(hook.end * 10)}
              onChange={(e) =>
                updateHook({ end: Number(e.target.value) / 10 })
              }
            />
          </label>

          <label>
            Efeito
            <select
              value={hook.effect}
              onChange={(e) =>
                updateHook({ effect: e.target.value as typeof hook.effect })
              }
            >
              <option value="pulse">Pulso</option>
              <option value="zoom">Zoom de entrada</option>
              <option value="bounce">Bounce</option>
              <option value="shake">Tremor</option>
              <option value="none">Nenhum</option>
            </select>
          </label>

          <div className="color-row">
            <label>
              Cor do texto
              <input
                type="color"
                value={hook.color}
                onChange={(e) => updateHook({ color: e.target.value })}
              />
            </label>
            <label>
              Cor de destaque
              <input
                type="color"
                value={hook.highlight_color}
                onChange={(e) => updateHook({ highlight_color: e.target.value })}
              />
            </label>
          </div>

          <label>
            Tamanho: {Math.round(hook.scale * 100)}%
            <input
              type="range"
              min={50}
              max={250}
              value={Math.round(hook.scale * 100)}
              onChange={(e) =>
                updateHook({ scale: Number(e.target.value) / 100 })
              }
            />
          </label>

          <label>
            Posição horizontal: {Math.round(hook.x * 100)}%
            <input
              type="range"
              min={10}
              max={90}
              value={Math.round(hook.x * 100)}
              onChange={(e) =>
                updateHook({ x: Number(e.target.value) / 100 })
              }
            />
          </label>

          <label>
            Posição vertical: {Math.round(hook.y * 100)}%
            <input
              type="range"
              min={10}
              max={80}
              value={Math.round(hook.y * 100)}
              onChange={(e) =>
                updateHook({ y: Number(e.target.value) / 100 })
              }
            />
          </label>

          <p className="hint">
            O gancho aparece nos primeiros segundos para prender a atenção.
          </p>
        </>
      )}
    </div>
  );
}
