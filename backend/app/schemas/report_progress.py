from pydantic import BaseModel


class WarmProgress(BaseModel):
    """Approximate progress of a background report warm, surfaced on a
    ``computing`` response so the UI can render a determinate bar instead of a
    bare spinner.

    ``done``/``total`` count patients (distinct NIKs) decrypted so far vs. the
    total to scan. It is an APPROXIMATION: the up-front DB fetch and the final
    aggregate pass aren't counted, so the bar may sit briefly near the end
    before the cache fills and ``computing`` flips false.
    """

    phase: str = "decrypting"
    done: int = 0
    total: int = 0
