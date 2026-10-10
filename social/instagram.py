"""Integração com a Instagram Graph API (Meta).

Permite publicar Reels, Stories e vídeos de feed em contas Instagram
Profissional (Creator/Business) vinculadas a uma Página do Facebook.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com/v19.0"


@dataclass
class InstagramAccount:
    """Conta do Instagram conectada."""

    ig_user_id: str
    username: str
    page_id: str
    page_name: str


class InstagramError(Exception):
    """Erro retornado pela Graph API do Instagram."""

    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.code = code


def _raise_for_error(response: requests.Response) -> None:
    """Converte resposta de erro da Graph API em InstagramError legível."""
    try:
        data = response.json()
    except Exception:
        data = {"error": {"message": response.text}}
    error = data.get("error", {})
    msg = error.get("message", "Erro desconhecido no Instagram")
    code = error.get("code")
    raise InstagramError(msg, code)


def connect_account(access_token: str) -> InstagramAccount:
    """Descobre a conta Instagram Profissional vinculada ao token.

    O token precisa ter permissões `instagram_basic` e `instagram_content_publish`.
    """
    # 1. Lista as páginas do usuário
    pages_resp = requests.get(
        f"{GRAPH_BASE}/me/accounts",
        params={"access_token": access_token, "fields": "name,id,instagram_business_account"},
        timeout=30,
    )
    if not pages_resp.ok:
        _raise_for_error(pages_resp)

    pages = pages_resp.json().get("data", [])
    if not pages:
        raise InstagramError(
            "Nenhuma Página do Facebook encontrada para este token. "
            "A conta Instagram precisa estar vinculada a uma página."
        )

    # 2. Procura a primeira página com conta Instagram vinculada
    for page in pages:
        ig_account = page.get("instagram_business_account")
        if ig_account and ig_account.get("id"):
            ig_user_id = ig_account["id"]
            # 3. Pega username da conta Instagram
            ig_resp = requests.get(
                f"{GRAPH_BASE}/{ig_user_id}",
                params={"access_token": access_token, "fields": "username"},
                timeout=30,
            )
            if not ig_resp.ok:
                _raise_for_error(ig_resp)
            return InstagramAccount(
                ig_user_id=str(ig_user_id),
                username=ig_resp.json().get("username", ""),
                page_id=str(page["id"]),
                page_name=str(page.get("name", "")),
            )

    raise InstagramError(
        "Nenhuma conta Instagram Profissional vinculada encontrada. "
        "Verifique se a conta é do tipo Creator ou Business e está conectada à página."
    )


def publish_video(
    ig_user_id: str,
    video_url: str,
    caption: str,
    media_type: str,
    access_token: str,
    cover_url: Optional[str] = None,
    share_to_feed: bool = True,
    timeout_seconds: float = 180.0,
) -> dict:
    """Publica um vídeo no Instagram.

    Parâmetros:
        media_type: "REELS", "STORIES" ou "VIDEO" (feed).
        video_url: URL pública do vídeo .mp4 (H.264/AAC).
        caption: legenda completa com hashtags.
    """
    media_type = media_type.upper()
    if media_type not in {"REELS", "STORIES", "VIDEO"}:
        raise InstagramError("Tipo de mídia deve ser REELS, STORIES ou VIDEO")

    params: dict = {
        "media_type": media_type,
        "video_url": video_url,
        "caption": caption,
        "access_token": access_token,
    }
    if media_type == "REELS":
        params["share_to_feed"] = "true" if share_to_feed else "false"
    if cover_url:
        params["cover_url"] = cover_url

    # 1. Cria o container
    create_resp = requests.post(
        f"{GRAPH_BASE}/{ig_user_id}/media",
        data=params,
        timeout=60,
    )
    if not create_resp.ok:
        _raise_for_error(create_resp)

    creation_id = create_resp.json().get("id")
    if not creation_id:
        raise InstagramError("Instagram não retornou o ID do container de mídia")

    # 2. Aguarda o container ficar pronto (especialmente Reels/vídeos)
    start = time.time()
    status = "IN_PROGRESS"
    while status == "IN_PROGRESS" and time.time() - start < timeout_seconds:
        time.sleep(5)
        status_resp = requests.get(
            f"{GRAPH_BASE}/{creation_id}",
            params={"access_token": access_token, "fields": "status_code"},
            timeout=30,
        )
        if status_resp.ok:
            status = status_resp.json().get("status_code", "UNKNOWN")
        else:
            status = "ERROR"

    if status != "FINISHED":
        raise InstagramError(
            f"Container do Instagram não ficou pronto a tempo (status: {status}). "
            "O vídeo pode estar fora das especificações."
        )

    # 3. Publica
    publish_resp = requests.post(
        f"{GRAPH_BASE}/{ig_user_id}/media_publish",
        data={"creation_id": creation_id, "access_token": access_token},
        timeout=60,
    )
    if not publish_resp.ok:
        _raise_for_error(publish_resp)

    result = publish_resp.json()
    return {
        "media_id": result.get("id"),
        "permalink": f"https://instagram.com/p/{result.get('id')}" if result.get("id") else None,
        "creation_id": creation_id,
    }
