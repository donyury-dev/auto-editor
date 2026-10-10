import { useEffect, useState } from "react";
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
  const [tokenKind, setTokenKind] = useState<"instagram" | "facebook">(
    "facebook"
  );
  const [mediaType, setMediaType] = useState<"REELS" | "STORIES" | "VIDEO">(
    "REELS"
  );
  const [caption, setCaption] = useState(initialCaption);
  const [error, setError] = useState("");
  const [postUrl, setPostUrl] = useState("");

  const openInstagramLogin = async () => {
    setError("");
    try {
      const { url } = await api.instagramOAuthStart();
      const popup = window.open(url, "instagram-login", "width=620,height=760");
      if (!popup) {
        setError("O navegador bloqueou a janela de login. Permita pop-ups e tente novamente.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login automático indisponível");
    }
  };

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.data?.type === "instagram-oauth-success") {
        setToken(event.data.access_token);
        setUsername(event.data.username);
        setIgUserId(event.data.ig_user_id);
        setTokenKind(event.data.token_kind === "instagram" ? "instagram" : "facebook");
        setStep("publish");
      } else if (event.data?.type === "instagram-oauth-error") {
        setError(event.data.message || "Não foi possível conectar a conta.");
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

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
        token_kind: tokenKind,
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
            <div className="publish-intro">
              <strong>Conecte sua conta uma vez</strong>
              <span>Você será levado ao Facebook/Meta para autorizar o Auto Editor. A senha nunca passa pelo nosso sistema.</span>
            </div>
            <button className="instagram-login" onClick={openInstagramLogin}>
              Entrar com Instagram
            </button>
            <p className="hint login-note">
              Para publicar, sua conta precisa ser Profissional (Creator ou
              Business) e estar ligada a uma Página do Facebook.
            </p>
            <details className="manual-login">
              <summary>Configuração técnica / usar Access Token</summary>
              <p className="hint">
                Use esta alternativa somente se o administrador ainda não
                configurou o login automático no Meta Developers.
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
            </details>
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
              Publicar no Instagram
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
