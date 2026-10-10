import { useState } from "react";
import { api } from "../api";

interface InstagramPublishModalProps {
  projectId: string;
  initialCaption: string;
  onClose: () => void;
}

type Step = "connect" | "publish" | "publishing" | "published";

export default function InstagramPublishModal({
  projectId,
  initialCaption,
  onClose,
}: InstagramPublishModalProps) {
  const [step, setStep] = useState<Step>("connect");
  const [token, setToken] = useState("");
  const [username, setUsername] = useState("");
  const [igUserId, setIgUserId] = useState("");
  const [mediaType, setMediaType] = useState<"REELS" | "STORIES" | "VIDEO">(
    "REELS"
  );
  const [caption, setCaption] = useState(initialCaption);
  const [error, setError] = useState("");
  const [postUrl, setPostUrl] = useState("");

  const connect = async () => {
    setError("");
    if (!token.trim()) {
      setError("Cole o Access Token do Meta.");
      return;
    }
    try {
      const res = await api.instagramConnect(token.trim());
      setUsername(res.username);
      setIgUserId(res.ig_user_id);
      setStep("publish");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao conectar");
    }
  };

  const publish = async () => {
    setError("");
    setStep("publishing");
    try {
      const res = await api.instagramPublish(projectId, {
        access_token: token.trim(),
        ig_user_id: igUserId,
        media_type: mediaType,
        caption,
      });
      setPostUrl(res.permalink || "");
      setStep("published");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao publicar");
      setStep("publish");
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header>
          <h3>Publicar no Instagram</h3>
          <button className="ghost" onClick={onClose}>
            ✕
          </button>
        </header>

        {step === "connect" && (
          <div className="modal-body">
            <p className="hint">
              1. Crie um app em developers.facebook.com (produto Instagram).
              <br />
              2. Copie o Access Token de produção (permissões
              instagram_basic e instagram_content_publish).
              <br />
              3. Sua conta precisa ser Instagram Profissional vinculada a uma
              página do Facebook.
            </p>
            <label>
              Access Token do Meta
              <textarea
                rows={4}
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="EAAG..."
              />
            </label>
            {error && <p className="error">{error}</p>}
            <button className="accent" onClick={connect}>
              Conectar conta
            </button>
          </div>
        )}

        {step === "publish" && (
          <div className="modal-body">
            <p>
              Conectado como <strong>@{username}</strong>
            </p>
            <label>
              Tipo de postagem
              <select
                value={mediaType}
                onChange={(e) =>
                  setMediaType(e.target.value as typeof mediaType)
                }
              >
                <option value="REELS">Reels</option>
                <option value="STORIES">Story (máx. 60s)</option>
                <option value="VIDEO">Post (feed)</option>
              </select>
            </label>
            <label>
              Legenda (com hashtags)
              <textarea
                rows={6}
                value={caption}
                onChange={(e) => setCaption(e.target.value)}
              />
            </label>
            {error && <p className="error">{error}</p>}
            <button className="accent" onClick={publish}>
              Publicar agora
            </button>
          </div>
        )}

        {step === "publishing" && (
          <div className="modal-body">
            <p className="hint">
              Publicando… o Instagram processa o vídeo, isso pode levar um
              minuto. Não feche esta janela.
            </p>
          </div>
        )}

        {step === "published" && (
          <div className="modal-body">
            <p className="ok">Publicado com sucesso!</p>
            {postUrl && (
              <p>
                <a href={postUrl} target="_blank" rel="noreferrer">
                  Ver publicação no Instagram
                </a>
              </p>
            )}
            <button onClick={onClose}>Fechar</button>
          </div>
        )}
      </div>
    </div>
  );
}
