"""Optional semantic ranking for search_tools, fused with BM25 (MAPLE_SEARCH=hybrid).

Phase 2 of the discovery plan (docs/ROADMAP.md): an index of tool metadata
only, never data. Each tool's name, summary line, Keywords and Mots-clés are
embedded once, by `python -m maplestats_mcp.shared.semantic build`; at run
time only the query is embedded, on this machine (no embedding API: a query
never leaves the server), and its ranking is merged with BM25's by reciprocal
rank fusion. Measured on tests/discovery_benchmark/ (phase2.md there): better
first-rank answers, French above all, for about 220 MB more memory, which is
why it is off unless MAPLE_SEARCH=hybrid and the `semantic` extra is installed.

The model is intfloat/multilingual-e5-small (MIT), in the int8 ONNX file its
authors publish, run by onnxruntime with sentencepiece as the tokenizer: the
`tokenizers` package holds about 280 MB for this 250,000-word vocabulary,
sentencepiece about 60 MB, for the same token ids (checked on every tool card
on 2026-10-27). The files are pinned to one revision and checked by SHA-256.

The index records the model, its revision, the vector size and the card
format (OpenMCP's catalog_meta guard): an index built any other way is refused
rather than compared with query vectors it was not made for. A tool whose
card changed since the build, or that is new, has no vector; it is ranked by
BM25 alone until the index is rebuilt, and the log says how many.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import os
import re
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("maplestats_mcp.semantic")

MODEL = "intfloat/multilingual-e5-small"
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
# Local name -> (path in the model repository, SHA-256).
FILES = {
    "model.onnx": (
        "onnx/model_qint8_avx512_vnni.onnx",
        "dd476dd0c2514e9b9be83aeb3853fac0763e0bdf4a71645407587d77c48a2d88",
    ),
    "sentencepiece.bpe.model": (
        "sentencepiece.bpe.model",
        "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
    ),
}
DIMENSION = 384
# Bump when tool_card() changes: an index of old cards is then refused.
TEXT_VERSION = 1
MAX_TOKENS = 512
# E5 models are trained with these prefixes; without them queries match worse.
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "
# Reciprocal rank fusion (Cormack et al., 2009); 60 is the usual constant, not tuned here.
RRF_K = 60
FUSION_DEPTH = 50
INDEX_FILE = "index.json"
MODES = ("bm25", "hybrid")


class SemanticUnavailable(RuntimeError):
    """The extra is not installed, or the model or index is missing or does not match."""


def search_mode() -> str:
    """MAPLE_SEARCH: "bm25" (the default) or "hybrid"; anything else warns and means bm25."""
    raw = os.environ.get("MAPLE_SEARCH", "").strip().lower() or "bm25"
    if raw not in MODES:
        logger.warning("MAPLE_SEARCH=%r is not one of %s; using bm25.", raw, MODES)
        return "bm25"
    return raw


def index_dir() -> Path:
    """MAPLE_SEMANTIC_DIR, or a folder in the system temp folder.

    A hosted deployment should build into a folder that survives restarts (or
    into the image), or every cold start finds no index and searches by BM25.
    """
    raw = os.environ.get("MAPLE_SEMANTIC_DIR", "").strip()
    return Path(raw) if raw else Path(tempfile.gettempdir()) / "maplestats-mcp" / "semantic"


# A Keywords or Mots-clés line runs on to the next such line or paragraph end.
_KEYWORDS = re.compile(
    r"^\s*(?:Keywords|Mots-clés)\s*:(.*?)(?=^\s*(?:Keywords|Mots-clés)\s*:|\n\n|\Z)",
    re.MULTILINE | re.DOTALL,
)


def tool_card(name: str, description: str) -> str:
    """What is embedded for a tool: its name, first paragraph, Keywords and Mots-clés.

    Measured 2026-10-27 (tests/discovery_benchmark/phase2.md): the whole docstring
    did worse (first-rank 0.46 against 0.58 alone for e5-small), because parameter
    notes and caveats dilute one 384-number vector, and short models cut the
    Mots-clés line, last in the docstring. The "Keywords:" labels are left out:
    the same words on every card carry nothing.
    """
    first = description.strip().split("\n\n")[0]
    parts = [name.replace("_", " "), first]
    parts += [match.group(1) for match in _KEYWORDS.finditer(description)]
    return " ".join(" ".join(part.split()) for part in parts if part.strip())


def card_hash(card: str) -> str:
    return hashlib.sha256(card.encode("utf-8")).hexdigest()[:16]


def _import(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise SemanticUnavailable(
            f"{name} is not installed: install maplestats-mcp[semantic] for MAPLE_SEARCH=hybrid"
        ) from exc


class Embedder:
    """The e5-small encoder: sentencepiece ids, onnxruntime, mean pooling, unit length."""

    def __init__(self, folder: Path) -> None:
        self.np = _import("numpy")
        ort = _import("onnxruntime")
        spm = _import("sentencepiece")
        for local in FILES:
            if not (folder / local).is_file():
                raise SemanticUnavailable(f"{folder / local} is missing; run the build first")
        self._sp = spm.SentencePieceProcessor(model_file=str(folder / "sentencepiece.bpe.model"))
        options = ort.SessionOptions()
        # One query at a time on a small host: more threads add memory, not speed.
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(folder / "model.onnx"), options, providers=["CPUExecutionProvider"]
        )

    def _ids(self, text: str) -> list[int]:
        # XLM-R's fairseq ids: <s>=0, <pad>=1, </s>=2, <unk>=3, and every
        # sentencepiece id shifted by one (its own <unk> is 0).
        pieces = [3 if i == 0 else i + 1 for i in self._sp.encode(text)]
        return [0, *pieces[: MAX_TOKENS - 2], 2]

    def embed(self, text: str) -> Any:
        np = self.np
        ids = np.array([self._ids(text)], dtype=np.int64)
        mask = np.ones_like(ids)
        hidden = self._session.run(
            None, {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)}
        )[0][0]
        vector = hidden.mean(axis=0)
        return vector / np.linalg.norm(vector)


def _meta() -> dict[str, Any]:
    return {
        "model": MODEL,
        "revision": REVISION,
        "files": {local: sha for local, (_, sha) in FILES.items()},
        "dimension": DIMENSION,
        "text_version": TEXT_VERSION,
        "query_prefix": QUERY_PREFIX,
        "passage_prefix": PASSAGE_PREFIX,
    }


class SemanticIndex:
    """Tool vectors from a build, and the encoder that made them, for queries."""

    def __init__(self, embedder: Embedder, names: list[str], hashes: list[str], vectors: Any):
        self.embedder = embedder
        self.np = embedder.np
        self._row = {name: i for i, name in enumerate(names)}
        self._hashes = hashes
        self._vectors = vectors

    @classmethod
    def load(cls, folder: Path) -> SemanticIndex:
        path = folder / INDEX_FILE
        if not path.is_file():
            raise SemanticUnavailable(f"no index at {path}; run the build first")
        data = json.loads(path.read_text(encoding="utf-8"))
        expected = _meta()
        wrong = [key for key, value in expected.items() if data.get("meta", {}).get(key) != value]
        if wrong:
            raise SemanticUnavailable(
                f"{path} was built with a different {', '.join(wrong)}; rebuild it"
            )
        embedder = Embedder(folder)
        np = embedder.np
        tools = data["tools"]
        vectors = np.array([tool["vector"] for tool in tools], dtype=np.float32)
        if vectors.shape[1:] != (DIMENSION,):
            raise SemanticUnavailable(f"{path} holds vectors of shape {vectors.shape}")
        names = [tool["name"] for tool in tools]
        return cls(embedder, names, [tool["card_hash"] for tool in tools], vectors)

    def rows(self, tools: Sequence[tuple[str, str]]) -> list[int | None]:
        """Each tool's row in the index, or None when it is new or its card changed."""
        rows: list[int | None] = []
        for name, description in tools:
            row = self._row.get(name)
            fresh = row is not None and self._hashes[row] == card_hash(tool_card(name, description))
            rows.append(row if fresh else None)
        return rows

    def ranking(self, query: str, rows: Sequence[int | None], depth: int) -> list[int]:
        """Positions (into `rows`) of the `depth` tools closest to the query, closest first."""
        present = [(pos, row) for pos, row in enumerate(rows) if row is not None]
        if not present:
            return []
        vector = self.embedder.embed(QUERY_PREFIX + query)
        similarity = self._vectors[[row for _, row in present]] @ vector
        order = self.np.argsort(-similarity, kind="stable")[:depth]
        return [present[int(i)][0] for i in order]


def fuse(bm25_scores: Sequence[float], semantic_ranking: Sequence[int]) -> list[float]:
    """Reciprocal rank fusion of the BM25 ranking (positive scores only) and the semantic one."""
    fused = [0.0] * len(bm25_scores)
    lexical = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)
    for rank, i in enumerate(lexical[:FUSION_DEPTH], start=1):
        if bm25_scores[i] <= 0:
            break
        fused[i] += 1 / (RRF_K + rank)
    for rank, i in enumerate(semantic_ranking, start=1):
        fused[i] += 1 / (RRF_K + rank)
    return fused


def download(folder: Path) -> None:
    """Fetch the pinned model files into `folder`, checking each SHA-256."""
    folder.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        for local, (remote, sha) in FILES.items():
            target = folder / local
            if target.is_file() and _sha256(target) == sha:
                continue
            url = f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{remote}"
            logger.info("downloading %s", url)
            partial = target.with_suffix(target.suffix + ".part")
            with client.stream("GET", url) as response, partial.open("wb") as out:
                response.raise_for_status()
                for chunk in response.iter_bytes(1 << 20):
                    out.write(chunk)
            if _sha256(partial) != sha:
                partial.unlink()
                raise SemanticUnavailable(f"{url} does not have the expected SHA-256")
            partial.replace(target)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(folder: Path, tools: Sequence[tuple[str, str]]) -> Path:
    """Download the model if needed and embed every tool card into `folder`/index.json."""
    download(folder)
    embedder = Embedder(folder)
    rows = []
    for name, description in tools:
        card = tool_card(name, description)
        vector = embedder.embed(PASSAGE_PREFIX + card)
        rows.append(
            {
                "name": name,
                "card_hash": card_hash(card),
                "vector": [round(float(x), 6) for x in vector],
            }
        )
    path = folder / INDEX_FILE
    payload = {"meta": _meta(), "tools": rows}
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return path


def searchable_tools() -> list[tuple[str, str]]:
    """Every tool search_tools ranks, with its docstring, as the server lists them.

    The server, not tool_catalogue.json alone: a module missing from the
    catalogue (a new one) is loaded at startup and searched all the same.
    """
    import asyncio

    from maplestats_mcp.server import SEARCH_ALWAYS_VISIBLE, mcp

    tools = asyncio.run(mcp._list_tools())
    return [(t.name, t.description or "") for t in tools if t.name not in SEARCH_ALWAYS_VISIBLE]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the search_tools semantic index.")
    parser.add_argument("command", choices=["build"])
    parser.add_argument("--dir", type=Path, default=None, help="default: MAPLE_SEMANTIC_DIR")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # httpx logs every redirect's signed URL at INFO; the download is logged above.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    folder = args.dir or index_dir()
    tools = searchable_tools()
    path = build(folder, tools)
    logger.info("embedded %d tools into %s", len(tools), path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
