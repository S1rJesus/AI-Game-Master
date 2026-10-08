from pathlib import Path

ALLOWED_SUFFIXES = {".txt", ".md"}

def load_evidence(folder: Path) -> str:
    if not folder.exists():
        return "[No evidence folder found.]"
    chunks = []
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.suffix.lower() in ALLOWED_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                chunks.append(f"\n=== EVIDENCE FILE: {path.name} ===\n{text}")
    return "\n".join(chunks) if chunks else "[Evidence library is empty. Do not make substantive conclusions.]"
