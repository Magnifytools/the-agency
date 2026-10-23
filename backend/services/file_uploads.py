"""Qué archivos se aceptan como adjunto y cómo se devuelven.

El tipo lo decide la EXTENSIÓN, no el Content-Type que manda el navegador: un
mismo .zip llega como `application/zip`, `application/x-zip-compressed` o
`application/octet-stream` según el sistema, y rechazarlo por eso era un fallo
sin explicación. Se guarda el tipo canónico de la extensión.

Al devolverlos, sólo PDF e imágenes rasterizadas se enseñan en el navegador
(con CSP `sandbox`). Todo lo demás, HTML incluido, sale como descarga opaca
(`application/octet-stream`, `attachment`, `nosniff`): un informe HTML subido
nunca se ejecuta en nuestro origen.
"""
import os
from urllib.parse import quote

from fastapi import HTTPException, UploadFile

ATTACHMENT_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".zip": "application/zip",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
ALLOWED_LABEL = "PDF, imágenes, Word, Excel, PowerPoint, TXT, CSV, Markdown, HTML o ZIP"

INLINE_RASTER_MIME_TYPES = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/avif",
})
PDF_MIME_TYPE = "application/pdf"


def attachment_type(filename: str) -> str:
    """Tipo canónico de un adjunto por su extensión, o 415 con el motivo."""
    if len(filename) > 255:
        raise HTTPException(status_code=400, detail="El nombre del archivo es demasiado largo (máx. 255 caracteres)")
    ext = os.path.splitext(filename.lower())[1]
    mime = ATTACHMENT_TYPES.get(ext)
    if mime is None:
        shown = ext or "sin extensión"
        raise HTTPException(
            status_code=415,
            detail=f"No se admiten archivos {shown}. Sube {ALLOWED_LABEL}.",
        )
    return mime


async def read_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Lee como mucho `max_bytes`; si hay más, 413 con el límite en MB."""
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"El archivo supera el límite de {max_bytes // (1024 * 1024)} MB",
        )
    return content


def stored_file_response_args(name: str, mime_type: str, *, inline: bool = False) -> dict:
    """`media_type` y cabeceras para devolver un archivo guardado sin riesgo.

    `inline=True` sólo se respeta para PDF e imágenes rasterizadas; el tipo
    guardado de filas antiguas venía del navegador y no se usa para nada más.
    """
    can_inline = mime_type in INLINE_RASTER_MIME_TYPES or mime_type == PDF_MIME_TYPE
    show_inline = inline and can_inline
    headers = {
        "Content-Disposition": (
            f"{'inline' if show_inline else 'attachment'}; filename*=UTF-8''{quote(name, safe='')}"
        ),
        "X-Content-Type-Options": "nosniff",
    }
    if mime_type == PDF_MIME_TYPE or not show_inline:
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return {
        "media_type": mime_type if show_inline else "application/octet-stream",
        "headers": headers,
    }
