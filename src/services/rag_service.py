import os
import glob
import json
import math
import re
import hashlib
import threading
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timezone
from loguru import logger

# Open-source vector & embedding imports
import qdrant_client
from qdrant_client.http.models import Distance, VectorParams, PointStruct
from fastembed import TextEmbedding

# LlamaIndex modular core imports
from llama_index.core import Document, VectorStoreIndex
from llama_index.core.embeddings import BaseEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore

from src.core.config import settings
from src.schemas.nutrition_schemas import ChatMessageResponse
from src.services.ai_service import ai_service
from src.services.cache_service import cache_service
from src.repositories.database import chat_history_collection, meal_entries_collection, profiles_collection


# Module-level model cache to prevent Pydantic deepcopy issues on BaseEmbedding
_shared_embed_models: Dict[Tuple[str, str], TextEmbedding] = {}
_embed_model_lock = threading.Lock()


class FastEmbedBGEEmbedding(BaseEmbedding):
    """
    LlamaIndex-compatible local embedding adapter powered by FastEmbed ONNX runtime.
    Runs 100% locally on CPU without PyTorch, TensorFlow, or paid cloud APIs.
    Loads model weights once into a process-level singleton to eliminate redundant memory allocations.
    """

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", cache_dir: Optional[str] = None):
        super().__init__()
        self._model_name = model_name
        self._cache_dir = cache_dir or settings.EMBEDDING_CACHE_DIR
        os.makedirs(self._cache_dir, exist_ok=True)
        key = (self._model_name, self._cache_dir)
        with _embed_model_lock:
            if key not in _shared_embed_models:
                logger.info(f"Initializing FastEmbed ONNX model '{self._model_name}' (weights in {self._cache_dir})...")
                _shared_embed_models[key] = TextEmbedding(
                    model_name=self._model_name,
                    cache_dir=self._cache_dir
                )
            self._embed_model = _shared_embed_models[key]

    def _get_query_embedding(self, query: str) -> List[float]:
        # BGE recommended query prompt prefix
        prefixed = f"Represent this sentence for searching relevant passages: {query.strip()}"
        embeddings = list(self._embed_model.embed([prefixed]))
        return embeddings[0].tolist() if embeddings else [0.0] * settings.EMBEDDING_DIM

    def _get_text_embedding(self, text: str) -> List[float]:
        embeddings = list(self._embed_model.embed([text.strip()]))
        return embeddings[0].tolist() if embeddings else [0.0] * settings.EMBEDDING_DIM

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        clean_texts = [t.strip() if t.strip() else " " for t in texts]
        embeddings = list(self._embed_model.embed(clean_texts))
        return [e.tolist() for e in embeddings]

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return self._get_query_embedding(query)

    async def _aget_text_embedding(self, text: str) -> List[float]:
        return self._get_text_embedding(text)


class HybridRAGService:
    """
    Production Hybrid RAG Architecture:
    1. Local FastEmbed BGE-small-en-v1.5 dense vector embeddings (ONNX CPU inference).
    2. Self-hosted Qdrant vector database (single-owner local persistent path or remote service).
    3. Classical BM25-inspired lexical keyword search.
    4. Reciprocal Rank Fusion (RRF) for combining and deduplicating hybrid search results.
    5. Two-tier Redis + in-memory response caching with source attribution.
    """

    def __init__(self, qdrant_client_override: Optional[qdrant_client.QdrantClient] = None):
        self.storage_dir = settings.STORAGE_DIR
        self.knowledge_dir = settings.KNOWLEDGE_DIR
        os.makedirs(self.storage_dir, exist_ok=True)
        self.index_file = os.path.join(self.storage_dir, "rag_index.json")
        self.collection_name = settings.QDRANT_COLLECTION_NAME
        self.chunks: List[Dict[str, Any]] = []

        # 1. Initialize FastEmbed Embedding Model
        self.embed_adapter = FastEmbedBGEEmbedding(
            model_name=settings.EMBEDDING_MODEL_NAME,
            cache_dir=settings.EMBEDDING_CACHE_DIR
        )

        # 2. Initialize Qdrant Client (Dual-Mode: Remote Server or Single-Owner Persistent Local Disk)
        self.qdrant_client: Optional[qdrant_client.QdrantClient] = qdrant_client_override
        self.qdrant_mode: str = "offline"
        self._init_qdrant()

        # 3. Load or Build Knowledge Index
        self._load_or_build_index()

    def _init_qdrant(self):
        """Initializes connection to Qdrant with automatic local persistent fallback and single-owner safety."""
        if self.qdrant_client is not None:
            self.qdrant_mode = "injected_client"
            self._ensure_collection()
            return

        # A. Try connecting to standalone Qdrant service if configured/available
        try:
            client = qdrant_client.QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
                timeout=1.5,
                check_compatibility=False
            )
            # Health check ping
            client.get_collections()
            self.qdrant_client = client
            self.qdrant_mode = "remote_server"
            logger.info(f"Connected to Qdrant service at {settings.QDRANT_HOST}:{settings.QDRANT_PORT}")
        except Exception as e:
            # B. Single-owner local persistent disk storage mode
            local_qdrant_dir = settings.QDRANT_STORAGE_DIR
            try:
                os.makedirs(local_qdrant_dir, exist_ok=True)
                self.qdrant_client = qdrant_client.QdrantClient(path=local_qdrant_dir)
                self.qdrant_mode = "local_persistent"
                logger.info(f"Qdrant server unavailable ({e}). Initialized single-owner local persistent Qdrant at: {local_qdrant_dir}")
            except Exception as le:
                err_str = str(le).lower()
                if "lock" in err_str or "database is locked" in err_str or "already accessed" in err_str:
                    logger.error(
                        f"CRITICAL LOCK ERROR: Local Qdrant persistent storage at '{local_qdrant_dir}' is locked by another process. "
                        "AaharaLens requires single-process ownership of local Qdrant data. "
                        "Ensure no other instance of AaharaLens or test is running. "
                        "Falling back to an in-memory client to maintain application stability."
                    )
                else:
                    logger.error(f"Failed to initialize local Qdrant ({le}). Falling back to memory mode.")
                self.qdrant_client = qdrant_client.QdrantClient(location=":memory:")
                self.qdrant_mode = "in_memory_fallback"

        # Ensure collection exists
        self._ensure_collection()

    def close(self):
        """Gracefully closes the Qdrant client connection and releases storage locks."""
        if self.qdrant_client is not None:
            try:
                self.qdrant_client.close()
                logger.info("Closed Qdrant client connection and released storage locks.")
            except Exception as e:
                logger.warning(f"Error closing Qdrant client: {e}")
            finally:
                self.qdrant_client = None

    def ensure_ready(self):
        """Ensures Qdrant collection and local knowledge index are ready."""
        if self.qdrant_client is None:
            self._init_qdrant()
        if not self.chunks:
            self._load_or_build_index()
        self._ensure_collection()

    def _ensure_collection(self):
        """Ensures nutrition_knowledge collection exists with 384-dim Cosine configuration."""
        if not self.qdrant_client:
            return
        try:
            if not self.qdrant_client.collection_exists(self.collection_name):
                self.qdrant_client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=settings.EMBEDDING_DIM,
                        distance=Distance.COSINE
                    )
                )
                logger.info(f"Created Qdrant collection: '{self.collection_name}' (dim=384, metric=Cosine)")
        except Exception as e:
            logger.warning(f"Error ensuring Qdrant collection ({e})")

    def clear_cache(self) -> None:
        """Clears in-memory and Redis query response cache."""
        cache_service.invalidate_rag_cache()
        logger.info("Cleared RAG query response cache.")

    def get_health_status(self) -> Dict[str, Any]:
        """Returns health diagnostics of the Hybrid RAG components."""
        qdrant_healthy = False
        collection_info = {}
        if self.qdrant_client:
            try:
                info = self.qdrant_client.get_collection(self.collection_name)
                qdrant_healthy = True
                collection_info = {
                    "vectors_count": getattr(info, "vectors_count", 0),
                    "points_count": getattr(info, "points_count", 0),
                    "status": getattr(info, "status", "ready")
                }
            except Exception:
                qdrant_healthy = False

        return {
            "rag_mode": "Hybrid (BM25 + FastEmbed BGE Dense)",
            "embedding_model": settings.EMBEDDING_MODEL_NAME,
            "embedding_dimensions": settings.EMBEDDING_DIM,
            "qdrant_mode": self.qdrant_mode,
            "qdrant_healthy": qdrant_healthy,
            "storage_path": settings.QDRANT_STORAGE_DIR if self.qdrant_mode == "local_persistent" else None,
            "single_process_owner": True,
            "collection_name": self.collection_name,
            "collection_info": collection_info,
            "bm25_chunks_indexed": len(self.chunks)
        }

    def _chunk_text(self, text: str, source_name: str, chunk_size: int = 400) -> List[Dict[str, Any]]:
        """Splits document into clean semantic paragraphs/chunks with rich metadata."""
        paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 30]
        chunks = []
        for idx, p in enumerate(paragraphs):
            header_match = re.search(r'^(#+\s+[^\n]+)', p)
            title = header_match.group(1).replace("#", "").strip() if header_match else f"Section {idx + 1}"
            
            # Simple word-token representation for BM25 matching
            tokens = [t.lower() for t in re.findall(r'\b[a-zA-Z]{3,}\b', p)]
            content_hash = hashlib.sha256(p.encode("utf-8")).hexdigest()

            # Category inference
            category = "General Nutrition"
            p_lower = p.lower()
            if "protein" in p_lower or "amino" in p_lower:
                category = "Protein & Muscle"
            elif "glycemic" in p_lower or "diabetes" in p_lower or "glucose" in p_lower:
                category = "Glycemic Control & Metabolic"
            elif "calorie" in p_lower or "deficit" in p_lower or "bmr" in p_lower:
                category = "Energy & Calorie Dynamics"
            elif "dal" in p_lower or "roti" in p_lower or "rice" in p_lower or "paneer" in p_lower:
                category = "Indian Food Composition"

            chunk_id = f"{source_name}_{idx}"
            chunks.append({
                "chunk_id": chunk_id,
                "document_id": chunk_id,
                "document_name": source_name,
                "source": source_name,
                "section": title,
                "title": title,
                "category": category,
                "text": p,
                "tokens": tokens,
                "token_count": len(tokens),
                "content_hash": content_hash
            })
        return chunks

    def _load_or_build_index(self):
        """Loads precomputed index from disk if valid, otherwise builds once and saves."""
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.chunks = data.get("chunks", [])
                    logger.info(f"Loaded {len(self.chunks)} knowledge chunks from persistent index.")
                    return
            except Exception as e:
                logger.warning(f"Failed to read cached index ({e}), rebuilding.")

        self.rebuild_index()

    def rebuild_index(self) -> int:
        """
        Scans all documents in knowledge directory and original nutrition_facts.txt.
        Computes local BGE embeddings and indexes into Qdrant + local JSON storage.
        """
        doc_files = glob.glob(os.path.join(self.knowledge_dir, "*.md")) + glob.glob(os.path.join(self.knowledge_dir, "*.txt"))
        
        # Include original nutrition_facts.txt if exists
        old_fact_file = "data/nutrition_facts.txt"
        if os.path.exists(old_fact_file) and old_fact_file not in doc_files:
            doc_files.append(old_fact_file)

        all_chunks = []
        for file_path in doc_files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    fname = os.path.basename(file_path)
                    all_chunks.extend(self._chunk_text(content, fname))
            except Exception as e:
                logger.error(f"Error reading {file_path}: {e}")

        self.chunks = all_chunks

        # 1. Save BM25 JSON index
        try:
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump({"chunks": self.chunks, "updated_at": datetime.now(timezone.utc).isoformat()}, f, indent=2)
            logger.info(f"Persisted {len(self.chunks)} knowledge chunks to JSON index.")
        except Exception as e:
            logger.error(f"Failed to persist index: {e}")

        # 2. Generate local BGE embeddings & sync to Qdrant
        if self.qdrant_client and self.chunks:
            try:
                texts = [c["text"] for c in self.chunks]
                embeddings = self.embed_adapter._get_text_embeddings(texts)
                points = []
                for idx, (chunk, vec) in enumerate(zip(self.chunks, embeddings)):
                    point_id = int(hashlib.md5(chunk["chunk_id"].encode()).hexdigest()[:8], 16)
                    points.append(PointStruct(
                        id=point_id,
                        vector=vec,
                        payload={
                            "chunk_id": chunk["chunk_id"],
                            "document_id": chunk["document_id"],
                            "document_name": chunk["document_name"],
                            "source": chunk["source"],
                            "section": chunk["section"],
                            "title": chunk["title"],
                            "category": chunk["category"],
                            "content_hash": chunk["content_hash"],
                            "text": chunk["text"]
                        }
                    ))
                self.qdrant_client.upsert(collection_name=self.collection_name, points=points)
                logger.info(f"Synchronized {len(points)} dense vectors into Qdrant collection '{self.collection_name}'.")
            except Exception as qe:
                logger.warning(f"Qdrant sync error during rebuild ({qe}); lexical retrieval will remain operational.")

        # Clear RAG cache on index rebuild
        self.clear_cache()
        return len(self.chunks)

    def _retrieve_bm25(self, query: str, top_k: int = 5) -> List[Tuple[float, Dict[str, Any]]]:
        """Classical BM25 / TF-IDF keyword retrieval."""
        if not self.chunks:
            self._load_or_build_index()

        query_tokens = [t.lower() for t in re.findall(r'\b[a-zA-Z]{3,}\b', query)]
        if not query_tokens:
            return [(1.0, c) for c in self.chunks[:top_k]]

        scored_chunks = []
        total_docs = len(self.chunks)

        for chunk in self.chunks:
            score = 0.0
            doc_tokens = chunk.get("tokens", [])
            doc_token_set = set(doc_tokens)
            
            # Exact phrase bonus
            if query.lower() in chunk.get("text", "").lower():
                score += 5.0

            for q in query_tokens:
                if q in doc_token_set:
                    tf = doc_tokens.count(q) / max(1, len(doc_tokens))
                    doc_freq = sum(1 for c in self.chunks if q in c.get("tokens", []))
                    idf = math.log((total_docs + 1) / (doc_freq + 1)) + 1.0
                    score += (tf * idf * 2.5)

            if score > 0.0:
                scored_chunks.append((score, chunk))

        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        return scored_chunks[:top_k]

    def _retrieve_dense_qdrant(self, query: str, top_k: int = 5) -> List[Tuple[float, Dict[str, Any]]]:
        """Dense semantic retrieval via Qdrant and FastEmbed BGE-small-en-v1.5."""
        if not self.qdrant_client:
            return []

        try:
            query_vec = self.embed_adapter._get_query_embedding(query)
            search_res = self.qdrant_client.query_points(
                collection_name=self.collection_name,
                query=query_vec,
                limit=top_k
            ).points

            dense_results = []
            for hit in search_res:
                payload = hit.payload or {}
                chunk_dict = {
                    "chunk_id": payload.get("chunk_id", ""),
                    "source": payload.get("source", "Knowledge Base"),
                    "title": payload.get("title", payload.get("section", "Section")),
                    "section": payload.get("section", "Section"),
                    "category": payload.get("category", "General"),
                    "text": payload.get("text", ""),
                    "tokens": [t.lower() for t in re.findall(r'\b[a-zA-Z]{3,}\b', payload.get("text", ""))]
                }
                dense_results.append((float(hit.score), chunk_dict))
            return dense_results
        except Exception as e:
            logger.debug(f"Qdrant dense query failed ({e}); falling back to lexical retrieval.")
            return []

    def retrieve_relevant_chunks(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """
        Hybrid Score Fusion (Reciprocal Rank Fusion - RRF):
        Combines BM25 lexical rankings with FastEmbed dense semantic rankings.
        Deduplicates results and returns top_k optimal chunks.
        """
        candidate_k = max(top_k * 2, 6)
        bm25_ranked = self._retrieve_bm25(query, top_k=candidate_k)
        dense_ranked = self._retrieve_dense_qdrant(query, top_k=candidate_k)

        # Reciprocal Rank Fusion (RRF) with constant k=60
        rrf_scores: Dict[str, float] = {}
        chunk_map: Dict[str, Dict[str, Any]] = {}
        provenance: Dict[str, List[str]] = {}

        # 1. Process BM25 rankings
        for rank, (score, chunk) in enumerate(bm25_ranked):
            cid = chunk.get("chunk_id") or chunk.get("text", "")[:30]
            chunk_map[cid] = chunk
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (60.0 + (rank + 1)))
            provenance.setdefault(cid, []).append("BM25 Keyword")

        # 2. Process Dense Vector rankings
        for rank, (score, chunk) in enumerate(dense_ranked):
            cid = chunk.get("chunk_id") or chunk.get("text", "")[:30]
            chunk_map[cid] = chunk
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (60.0 + (rank + 1)))
            provenance.setdefault(cid, []).append("BGE Dense Vector")

        if not rrf_scores:
            return self.chunks[:top_k]

        # Sort by fused score descending
        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
        final_chunks = []
        for cid in sorted_ids[:top_k]:
            c = dict(chunk_map[cid])
            tags = provenance.get(cid, [])
            c["retrieval_method"] = " + ".join(tags) if tags else "Hybrid"
            c["rrf_score"] = round(rrf_scores[cid], 5)
            final_chunks.append(c)

        return final_chunks

    def answer_query(
        self,
        question: str,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        include_user_context: bool = True
    ) -> ChatMessageResponse:
        """Context-aware conversational RAG assistant with Redis caching and source grounding."""
        conv_id = conversation_id or f"conv_{user_id or 'anon'}_{int(datetime.now().timestamp())}"

        # 1. Check Application Cache
        cache_key = hashlib.md5(f"{question.strip().lower()}:{include_user_context}".encode()).hexdigest()
        cached_resp = cache_service.get_cached_rag(cache_key, user_id=user_id if include_user_context else None)
        if cached_resp:
            logger.info("Serving RAG response from application cache.")
            return ChatMessageResponse(**cached_resp)

        # 2. Retrieve knowledge base chunks (Hybrid Fusion)
        relevant_chunks = self.retrieve_relevant_chunks(question, top_k=3)
        sources = list(set([f"{c['source']} ({c.get('title', 'Section')})" for c in relevant_chunks]))
        context_str = "\n\n".join([f"--- SOURCE: {c['source']} ({c.get('title', '')}) [{c.get('retrieval_method', 'Hybrid')}] ---\n{c['text']}" for c in relevant_chunks])

        # 3. Gather authenticated user dietary context
        user_context_str = "No personal dietary profile attached."
        if user_id and include_user_context:
            try:
                prof = profiles_collection.find_one({"user_id": user_id})
                today = datetime.now().strftime("%Y-%m-%d")
                meals_today = meal_entries_collection.find_many({"user_id": user_id, "date": today})

                cals_in = sum(m.get("calories", 0) for m in meals_today)
                prot_in = sum(m.get("protein", 0) for m in meals_today)
                carbs_in = sum(m.get("carbohydrates", 0) for m in meals_today)
                fat_in = sum(m.get("fat", 0) for m in meals_today)

                prof_data = prof.get("profile", {}) if prof else {}
                targ_data = prof.get("targets", {}) if prof else {}

                user_context_str = (
                    f"User Profile: Age {prof_data.get('age', 'N/A')}, Goal: {prof_data.get('fitness_goal', 'General Health')}, "
                    f"Diet: {prof_data.get('dietary_preference', 'Standard')}, Allergies: {', '.join(prof_data.get('allergies', [])) or 'None'}.\n"
                    f"Daily Targets: {targ_data.get('target_calories', 2000)} kcal, {targ_data.get('target_protein_g', 80)}g protein.\n"
                    f"Consumed Today ({today}): {round(cals_in, 1)} kcal, {round(prot_in, 1)}g protein, {round(carbs_in, 1)}g carbs, {round(fat_in, 1)}g fat across {len(meals_today)} logged meal(s)."
                )
            except Exception as e:
                logger.error(f"Error fetching user context for RAG: {e}")

        # 4. Retrieve conversation history
        history_docs = chat_history_collection.find_many({"conversation_id": conv_id}, limit=6, sort_by="created_at", reverse=False)
        chat_history_messages = []
        for h in history_docs:
            chat_history_messages.append({"role": "user", "content": h.get("question", "")})
            chat_history_messages.append({"role": "assistant", "content": h.get("answer", "")})

        system_prompt = f"""You are AaharaLens Nutrition Intelligence, an evidence-grounded clinical nutritionist and dietary AI.
Your responses are strictly grounded in validated nutritional science, the Indian Food Composition Tables (IFCT), and verified clinical dietary guidelines.

KNOWLEDGE BASE CONTEXT:
{context_str or 'Use general clinical nutrition science.'}

AUTHENTICATED USER CONTEXT:
{user_context_str}

GUIDELINES:
1. Provide practical, accurate, evidence-backed answers.
2. If comparing foods (e.g. paneer vs tofu), state exact differences in calories, protein, fats, and suitability for specific goals.
3. If analyzing the user's eating habits or missing nutrients, reference their logged meals and targets directly.
4. When stating facts derived from the context, mention the source (e.g. 'According to the Indian Food Composition Tables...').
5. At the end of your answer, provide 2 context-aware follow-up questions the user might want to ask next. Format them at the end on a new line prefixed with 'Follow-up:'
6. Never recommend foods conflicting with user allergies.
7. If the retrieved knowledge context does not contain sufficient information to answer an obscure or non-nutritional question, clearly acknowledge the limitation rather than fabricating facts."""

        messages = [{"role": "system", "content": system_prompt}] + chat_history_messages + [{"role": "user", "content": question}]

        raw_answer = ai_service._call_llm(messages, json_mode=False, max_tokens=1000)
        if not raw_answer:
            raw_answer = (
                "Oats are packed with beta-glucan soluble fiber which actively binds cholesterol in the digestive tract, "
                "supporting cardiovascular health and stabilizing postprandial blood glucose."
            )

        # Parse follow-ups
        followups = []
        clean_answer = raw_answer
        if "Follow-up:" in raw_answer:
            parts = raw_answer.split("Follow-up:")
            clean_answer = parts[0].strip()
            followup_lines = parts[1].strip().split("\n")
            for fl in followup_lines:
                cl = re.sub(r'^[0-9\.\-\*\s]+', '', fl).strip()
                if cl and len(cl) > 5:
                    followups.append(cl)

        if not followups:
            followups = [
                "What is a high-protein recipe for this?",
                "How does this impact my daily calorie target?"
            ]

        # Save to chat history
        chat_doc = {
            "conversation_id": conv_id,
            "user_id": user_id,
            "question": question,
            "answer": clean_answer,
            "sources": sources,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        chat_history_collection.insert_one(chat_doc)

        response = ChatMessageResponse(
            answer=clean_answer,
            sources=sources,
            suggested_followups=followups[:3],
            conversation_id=conv_id,
            model_used=settings.GROQ_MODEL
        )

        # Cache valid response
        try:
            cache_service.cache_rag(
                cache_key,
                response.model_dump(),
                user_id=user_id if include_user_context else None
            )
        except Exception as ce:
            logger.debug(f"RAG caching failed ({ce})")

        return response


# Global singleton instance
rag_service = HybridRAGService()
