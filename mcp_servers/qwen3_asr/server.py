"""Qwen3-ASR-1.7B HTTP transcription server.

CPU-only deployment using the transformers backend (qwen-asr package).
Exposes POST /transcribe for audio transcription and GET /health for readiness.

Audio format: OGG/Opus from Telegram voice messages — accepted natively.
No ffmpeg required — qwen-asr uses soundfile/librosa under the hood.

Model: Qwen/Qwen3-ASR-1.7B (configurable via ASR_MODEL env var)
Dtype: bfloat16 (falls back to float32 if CPU does not support it)
Inference: synchronous model.transcribe() runs in asyncio thread pool executor
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import torch
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from qwen_asr import Qwen3ASRModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ASR_MODEL = os.environ.get("ASR_MODEL", "Qwen/Qwen3-ASR-1.7B")

_model: Qwen3ASRModel | None = None


def _load_model() -> Qwen3ASRModel:
    """Load Qwen3-ASR model on CPU with bfloat16, fallback to float32.

    Returns:
        Loaded Qwen3ASRModel instance.
    """
    # Try bfloat16 first — ~3.4GB RAM vs ~6.8GB for float32
    # bfloat16 on CPU requires AVX512-BF16 support (most modern x86_64)
    try:
        logger.info("Loading %s with bfloat16 on CPU...", ASR_MODEL)
        model = Qwen3ASRModel.from_pretrained(
            ASR_MODEL,
            device_map="cpu",
            torch_dtype=torch.bfloat16,
        )
        logger.info("Model loaded in bfloat16 (%.1f GB RAM)", 3.4)
        return model
    except (RuntimeError, Exception) as e:
        logger.warning("bfloat16 failed (%s), falling back to float32", e)
        model = Qwen3ASRModel.from_pretrained(
            ASR_MODEL,
            device_map="cpu",
            torch_dtype=torch.float32,
        )
        logger.info("Model loaded in float32 (%.1f GB RAM)", 6.8)
        return model


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """Load model at startup, release at shutdown.

    Args:
        app: FastAPI application instance.

    Yields:
        Control to FastAPI after model is loaded.
    """
    global _model
    logger.info("Starting Qwen3-ASR server, loading model: %s", ASR_MODEL)
    _model = await asyncio.get_event_loop().run_in_executor(None, _load_model)
    logger.info("Model ready. Server accepting requests.")
    yield
    _model = None
    logger.info("Model unloaded.")


app = FastAPI(
    title="Qwen3-ASR",
    description="CPU-only speech-to-text using Qwen3-ASR-1.7B",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint.

    Returns:
        Dict with status and model name.

    Raises:
        HTTPException 503: If model is not loaded.
    """
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"status": "ok", "model": ASR_MODEL}


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)) -> JSONResponse:
    """Transcribe an OGG/Opus audio file to text.

    Accepts voice messages from Telegram (OGG/Opus format). Saves to a
    temporary file and passes the path to qwen-asr for transcription.
    Runs in a thread pool executor to avoid blocking the async event loop.

    Args:
        audio: Uploaded audio file. Expected OGG/Opus from Telegram.

    Returns:
        JSON with 'text' field containing the transcription.

    Raises:
        HTTPException 503: If model is not loaded.
        HTTPException 500: If transcription fails.
    """
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    # Save uploaded bytes to a temp file — qwen-asr needs a file path
    tmp_path: Path | None = None
    try:
        audio_bytes = await audio.read()
        logger.debug(
            "Received audio: %d bytes, content_type=%s",
            len(audio_bytes),
            audio.content_type,
        )

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = Path(tmp.name)

        # model.transcribe() is synchronous — run in thread pool to avoid blocking
        def _transcribe() -> str:
            results = _model.transcribe(audio=str(tmp_path))  # type: ignore[union-attr]
            return results[0].text if results else ""

        text = await asyncio.get_event_loop().run_in_executor(None, _transcribe)
        text = text.strip()

        logger.info(
            "Transcribed %d bytes → %d chars: %r",
            len(audio_bytes),
            len(text),
            text[:80],
        )
        return JSONResponse({"text": text})

    except Exception as e:
        logger.exception("Transcription failed")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}") from e
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8086, log_level="info")
