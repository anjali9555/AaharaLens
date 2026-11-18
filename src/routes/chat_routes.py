from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Request, status
from src.core.config import settings
from src.core.limiter import limiter
from src.schemas.nutrition_schemas import ChatMessageRequest, ChatMessageResponse
from src.routes.deps import get_optional_current_user, get_current_user, get_current_admin_user
from src.services.rag_service import rag_service
from src.repositories.database import chat_history_collection

router = APIRouter(prefix="/chat", tags=["Conversational AI Nutritionist (RAG)"])

@router.post("", response_model=ChatMessageResponse)
@limiter.limit(settings.RATE_LIMIT_CHAT)
def ask_chat(
    req: ChatMessageRequest, 
    request: Request = None,
    user: Optional[dict] = Depends(get_optional_current_user)
):
    """
    Conversational AI nutrition chatbot backed by persistent knowledge RAG and user context.
    Enforces conversation thread ownership to prevent unauthorized cross-user access.
    """
    clean_msg = req.message.strip()
    if not clean_msg:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question message cannot be empty."
        )

    user_id = user["id"] if user else None

    # Enforce conversation ownership if a conversation_id is specified
    if req.conversation_id:
        existing_thread = chat_history_collection.find_one({"conversation_id": req.conversation_id})
        if existing_thread:
            thread_owner = existing_thread.get("user_id")
            if thread_owner and thread_owner != user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: This conversation belongs to another user."
                )

    return rag_service.answer_query(
        question=clean_msg,
        user_id=user_id,
        conversation_id=req.conversation_id,
        include_user_context=req.include_user_context
    )

@router.get("/history/{conversation_id}")
def get_chat_history(
    conversation_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Retrieves conversation thread messages for the authenticated owner.
    Guards against unauthorized eavesdropping on other users' conversations.
    """
    if not conversation_id or not conversation_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Conversation ID cannot be empty."
        )

    # Check conversation ownership
    existing_messages = chat_history_collection.find_many(
        {"conversation_id": conversation_id.strip()},
        limit=50,
        sort_by="created_at",
        reverse=False
    )

    if existing_messages:
        for msg in existing_messages:
            thread_owner = msg.get("user_id")
            if thread_owner and thread_owner != current_user["id"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: You do not have permission to view this conversation."
                )

    return existing_messages

@router.get("/status")
def get_rag_health_status():
    """Returns real-time health diagnostics of FastEmbed BGE, Qdrant vector database, and BM25 index."""
    return rag_service.get_health_status()

@router.post("/rebuild-index")
def rebuild_rag_index(admin_user: dict = Depends(get_current_admin_user)):
    """
    Forces rescanning of all knowledge documents, computes FastEmbed BGE embeddings,
    and synchronizes dense vectors with Qdrant and local persistent BM25 index.
    Restricted to authorized administrators.
    """
    chunks_count = rag_service.rebuild_index()
    return {
        "status": "success",
        "message": f"Successfully reindexed {chunks_count} knowledge chunks.",
        "chunks": chunks_count,
        "authorized_by": admin_user.get("username", "admin")
    }

@router.post("/clear-cache")
def clear_rag_cache(admin_user: dict = Depends(get_current_admin_user)):
    """
    Clears in-memory query response cache.
    Restricted to authorized administrators.
    """
    rag_service.clear_cache()
    return {
        "status": "success",
        "message": "RAG query response cache cleared.",
        "authorized_by": admin_user.get("username", "admin")
    }
