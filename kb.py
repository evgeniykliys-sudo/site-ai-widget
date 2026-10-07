"""База знаний: markdown-документы → разделы (## …) → эмбеддинги → ChromaDB; поиск по смыслу.

Ищем по предложениям, отвечаем разделами. Один вектор на целый раздел «размывается»: «замер платный?»
не находил раздел «Замер и смета», где про бесплатный замер — одна фраза из пяти. Поэтому в индекс кладём каждое
предложение (с заголовком раздела), а модели отдаём раздел целиком — с заголовком документа и раздела,
чтобы фрагмент был понятен сам по себе («Санузел под ключ — от 180 000 ₽», а не просто «от 180 000 ₽»).

    python kb.py        # переиндексировать после правки документов в kb/
"""
import re
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

KB_DIR = Path(__file__).parent / "kb"
CHROMA_DIR = Path(__file__).parent / "chroma_db"
COLLECTION = "site_kb"
# многоязычная модель: all-MiniLM (английская) плохо ищет по русским вопросам
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
TOP_K = 4
# Косинусное расстояние 0..2. Дальше порога — фрагмент «не про то»: модель его не видит,
# и на вопрос вне базы ассистент честно говорит «не знаю», а не натягивает ответ. Калибровка — tests/calibrate.py.
MAX_DISTANCE = 0.6

_model: SentenceTransformer | None = None
_collection = None


def model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def split_sections(text: str, source: str) -> list[dict]:
    title, chunks, head, body = source, [], None, []
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            if head and body:
                chunks.append({"text": f"{title} — {head}\n" + "\n".join(body).strip(), "source": source, "section": head})
            head, body = line[3:].strip(), []
        elif head is not None:
            body.append(line)
    if head and body:
        chunks.append({"text": f"{title} — {head}\n" + "\n".join(body).strip(), "source": source, "section": head})
    return chunks


def sentences(section: dict) -> list[str]:
    head = section["section"]
    body = section["text"].split("\n", 1)[1]
    parts = [x.strip() for x in re.split(r"(?<=[.!?])\s+", body) if len(x.strip()) > 15]
    return [f"{head}. {x}" for x in parts] or [section["text"]]


def build() -> int:
    sections = [c for p in sorted(KB_DIR.glob("*.md")) for c in split_sections(p.read_text(encoding="utf-8"), p.name)]
    # ключи поиска: заголовок раздела отдельно + каждое предложение; у всех в метаданных — текст раздела
    chunks = [{"key": k, "text": sec["text"], "source": sec["source"], "section": sec["section"]}
              for sec in sections for k in [sec["section"]] + sentences(sec)]
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    if COLLECTION in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION)
    col = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    col.add(ids=[f"{c['source']}#{i}" for i, c in enumerate(chunks)],
            documents=[c["key"] for c in chunks],
            embeddings=model().encode([c["key"] for c in chunks]).tolist(),
            metadatas=[{"source": c["source"], "section": c["section"], "text": c["text"]} for c in chunks])
    global _collection
    _collection = col
    _df.clear()
    return len(sections)


def collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        if COLLECTION not in [c.name for c in client.list_collections()]:
            build()
        else:
            _collection = client.get_collection(COLLECTION)
    return _collection


STOP = {"сколько", "стоит", "можно", "есть", "какая", "какой", "какие", "если", "через", "будет", "нужно",
        "ваши", "вашей", "это", "или", "для", "как", "что", "где", "когда", "будут", "делаете", "ремонт"}
# Бонус за слово зависит от редкости (идея BM25): «рассрочка» есть в одном разделе — сильный сигнал,
# а «работы» встречается везде — почти никакой. Модель эмбеддингов редкие слова понимает плохо
# («есть рассрочка?» ↔ «Рассрочка без переплаты…» — расстояние 0,92, как у случайной фразы).
RARE_BONUS = 0.45     # слово только в 1 разделе
_df: dict[str, int] = {}
_n_sections = 0


def stems(text: str) -> set[str]:
    # грубая основа слова: первые 5 букв («рассрочка/рассрочку» → «расср»); для базы одной компании хватает
    return {w[:5] for w in re.findall(r"[а-яёa-z0-9]+", text.lower()) if len(w) >= 4 and w not in STOP}


def doc_freq() -> tuple[dict[str, int], int]:
    global _df, _n_sections
    if not _df:
        texts = {m["section"]: m["text"] for m in collection().get(include=["metadatas"])["metadatas"]}
        for t in texts.values():
            for st in stems(t):
                _df[st] = _df.get(st, 0) + 1
        _n_sections = len(texts)
    return _df, _n_sections


def word_bonus(query_stems: set[str], text: str) -> float:
    df, n = doc_freq()
    bonus = sum(RARE_BONUS / df[st] for st in query_stems & stems(text) if df.get(st, 0) and df[st] <= n // 3)
    return min(bonus, RARE_BONUS)


def search(query: str, top_k: int = TOP_K, max_distance: float = MAX_DISTANCE) -> list[dict]:
    """Гибридный поиск: смысл (расстояние раздела — по его лучшему предложению) минус бонус за редкие слова запроса,
    найденные в тексте раздела."""
    col = collection()
    # берём все ключи небольшой базы: редкое слово может «вытянуть» раздел, далёкий по вектору
    res = col.query(query_embeddings=model().encode([query]).tolist(), n_results=min(col.count(), 400))
    q = stems(query)
    best: dict[str, dict] = {}
    for m, d in zip(res["metadatas"][0], res["distances"][0]):
        if m["section"] in best:
            continue                    # результаты отсортированы: первое попадание раздела — его лучшее предложение
        score = round(d - word_bonus(q, m["text"]), 3)
        best[m["section"]] = {"text": m["text"], "section": m["section"], "source": m["source"], "distance": score}
    ranked = sorted((c for c in best.values() if c["distance"] <= max_distance), key=lambda c: c["distance"])
    return ranked[:top_k]


def document(source: str) -> list[dict]:
    """Все разделы документа в исходном порядке."""
    return [c for c in split_sections((KB_DIR / source).read_text(encoding="utf-8"), source)]


def context_for(query: str) -> list[dict]:
    """Что увидит модель: документ лучшего совпадения целиком + остальные найденные разделы.
    Вопрос «какая гарантия и что если отвалится плитка?» точнее всего попадает в «Что покрывает гарантия»,
    а срок гарантии лежит в соседнем разделе — без соседей модель отвечала без главного (2 года)."""
    hits = search(query)
    if not hits:
        return []
    top = hits[0]["source"]
    return document(top) + [h for h in hits if h["source"] != top]


if __name__ == "__main__":
    print(f"Проиндексировано разделов: {build()}")
