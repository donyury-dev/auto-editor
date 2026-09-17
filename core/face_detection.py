"""Detecção simples de rosto para centralizar o zoom.

Tenta YuNet (DNN do OpenCV) primeiro; em caso de falha, cai para Haar
Cascade. Retorna o centro normalizado [0,1] do maior rosto detectado no
frame. Se nenhum rosto for encontrado, retorna None.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).parent.parent / "assets"
YUNET_MODEL = ASSETS_DIR / "face_detection_yunet_2023mar.onnx"
CASCADE_PATH = ASSETS_DIR / "haarcascade_frontalface_alt2.xml"


def _largest_face_haar(
    cascade: cv2.CascadeClassifier, gray: np.ndarray
) -> Optional[tuple[int, int, int, int]]:
    """Tenta detectar o maior rosto com pré-processamento leve."""
    equalized = cv2.equalizeHist(gray)
    min_w = max(20, gray.shape[1] // 15)
    min_h = max(20, gray.shape[0] // 15)

    for image in (gray, equalized):
        faces = cascade.detectMultiScale(
            image,
            scaleFactor=1.05,
            minNeighbors=3,
            minSize=(min_w, min_h),
            flags=cv2.CASCADE_SCALE_IMAGE,
        )
        if len(faces) > 0:
            return max(faces, key=lambda rect: rect[2] * rect[3])
    return None


def _detect_yunet(image: np.ndarray) -> Optional[tuple[float, float]]:
    """Detecta o centro do maior rosto usando YuNet."""
    if not YUNET_MODEL.exists():
        return None

    h, w = image.shape[:2]
    detector = cv2.FaceDetectorYN.create(
        str(YUNET_MODEL),
        "",
        (w, h),
        0.6,  # confiança mínima
        0.3,  # nms
        5000,  # top_k
    )
    _, faces = detector.detect(image)
    if faces is None or len(faces) == 0:
        return None

    # cada face: [x1, y1, w, h, confidence, ...]
    largest = max(faces, key=lambda f: f[2] * f[3])
    x, y, fw, fh = largest[:4]
    cx = (x + fw / 2) / w
    cy = (y + fh / 2) / h
    return (float(cx), float(cy))


def detect_face_center(frame_path: Path | str) -> Optional[tuple[float, float]]:
    """Detecta o centro do maior rosto em um frame.

    Retorna (cx, cy) em coordenadas normalizadas [0, 1] ou None se não
    encontrar nenhum rosto.
    """
    frame_path = Path(frame_path)
    if not frame_path.exists():
        return None

    try:
        image = cv2.imread(str(frame_path))
        if image is None:
            return None
    except Exception as exc:
        logger.debug("Falha ao ler frame para detecção de rosto: %s", exc)
        return None

    # upscale leve melhora detecção em vídeos de baixa resolução
    scale = 2.0
    h, w = image.shape[:2]
    upscaled = cv2.resize(
        image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC
    )

    # 1) YuNet (mais preciso)
    try:
        center = _detect_yunet(upscaled)
        if center:
            logger.debug("Rosto YuNet em %s: cx=%.3f cy=%.3f", frame_path, *center)
            return center
    except Exception as exc:
        logger.debug("YuNet falhou: %s", exc)

    # 2) Haar Cascade (fallback)
    if not CASCADE_PATH.exists():
        return None

    try:
        gray = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(str(CASCADE_PATH))
        largest = _largest_face_haar(cascade, gray)
        if largest is None:
            return None
        x, y, w, h = largest
        h_img, w_img = gray.shape
        cx = (x + w / 2) / w_img
        cy = (y + h / 2) / h_img
        logger.debug(
            "Rosto Haar em %s: cx=%.3f cy=%.3f", frame_path, cx, cy
        )
        return (float(cx), float(cy))
    except Exception as exc:
        logger.debug("Haar Cascade falhou: %s", exc)
        return None
