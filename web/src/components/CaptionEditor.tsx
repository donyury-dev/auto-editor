import { useEffect, useState } from "react";
import { api } from "../api";

interface CaptionEditorProps {
  projectId: string;
  onCaptionChange?: (caption: string, hashtags: string) => void;
}

export default function CaptionEditor({
  projectId,
  onCaptionChange,
}: CaptionEditorProps) {
  const [caption, setCaption] = useState("");
  const [hashtags, setHashtags] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .caption(projectId)
      .then((d) => {
        setCaption(d.caption || "");
        setHashtags((d.hashtags || []).join(" "));
        setLoading(false);
        onCaptionChange?.(d.caption || "", (d.hashtags || []).join(" "));
      })
      .catch(() => setLoading(false));
  }, [projectId, onCaptionChange]);

  const fullText = `${caption}\n\n${hashtags}`.trim();

  return (
    <div className="caption-editor">
      <h4>Legenda para publicação</h4>
      {loading ? (
        <p className="hint">Gerando legenda…</p>
      ) : (
        <>
          <label>
            Legenda
            <textarea
              rows={3}
              value={caption}
              onChange={(e) => {
                setCaption(e.target.value);
                onCaptionChange?.(e.target.value, hashtags);
              }}
            />
          </label>
          <label>
            Hashtags
            <textarea
              rows={2}
              value={hashtags}
              onChange={(e) => {
                setHashtags(e.target.value);
                onCaptionChange?.(caption, e.target.value);
              }}
            />
          </label>
          <button
            className="ghost small"
            onClick={() => {
              navigator.clipboard.writeText(fullText);
            }}
          >
            Copiar legenda + hashtags
          </button>
        </>
      )}
    </div>
  );
}
