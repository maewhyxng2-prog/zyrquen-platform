import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.conversation_schemas import (
    ConversationCreate,
    ConversationMessageCreate,
    ConversationMessageResponse,
    ConversationRename,
    ConversationResponse,
    ConversationSummary,
)
from apps.api.database import get_db
from apps.api.models import Conversation, ConversationMessage
from apps.api.security import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/conversations", tags=["Conversations"])


def _database_unavailable(db: Session) -> None:
    try:
        db.rollback()
    except SQLAlchemyError:
        logger.error("Conversation transaction rollback failed")
    logger.error("Conversation database operation failed")
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Conversation storage is temporarily unavailable",
    ) from None


def _owned_conversation(db: Session, conversation_id: UUID, user_id: UUID):
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def persist_completed_assistant_message(
    db: Session,
    conversation_id: UUID,
    user_id: UUID,
    message_id: UUID,
    content: str,
    *,
    commit: bool = True,
) -> ConversationMessage:
    conversation = _owned_conversation(db, conversation_id, user_id)

    db.query(Conversation).filter(
        Conversation.id == conversation.id
    ).with_for_update().one()

    existing = db.query(ConversationMessage).filter(
        ConversationMessage.id == message_id
    ).first()
    if existing is not None:
        if (
            existing.conversation_id != conversation.id
            or existing.role != "assistant"
            or existing.content != content
        ):
            raise HTTPException(
                status_code=409,
                detail="Message ID is already associated with different content",
            )
        return existing

    sequence = (
        db.query(func.coalesce(func.max(ConversationMessage.sequence), 0))
        .filter(ConversationMessage.conversation_id == conversation.id)
        .scalar()
        + 1
    )
    created_at = datetime.now(timezone.utc)
    message = ConversationMessage(
        id=message_id,
        conversation_id=conversation.id,
        sequence=sequence,
        role="assistant",
        content=content,
        created_at=created_at,
    )
    conversation.updated_at = created_at
    db.add(message)
    if commit:
        db.commit()
        db.refresh(message)
    else:
        db.flush()
    return message


@router.post("", response_model=ConversationSummary, status_code=201)
def create_conversation(
    payload: ConversationCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Conversation title is required")
    conversation = Conversation(user_id=current_user.id, title=title)
    try:
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return {
            "id": conversation.id,
            "title": conversation.title,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "message_count": 0,
        }
    except SQLAlchemyError:
        _database_unavailable(db)


@router.get("", response_model=list[ConversationSummary])
def list_conversations(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        rows = (
            db.query(Conversation, func.count(ConversationMessage.id))
            .outerjoin(
                ConversationMessage,
                ConversationMessage.conversation_id == Conversation.id,
            )
            .filter(Conversation.user_id == current_user.id)
            .group_by(Conversation.id)
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .all()
        )
        return [
            {
                "id": conversation.id,
                "title": conversation.title,
                "created_at": conversation.created_at,
                "updated_at": conversation.updated_at,
                "message_count": message_count,
            }
            for conversation, message_count in rows
        ]
    except SQLAlchemyError:
        _database_unavailable(db)


@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        conversation = _owned_conversation(db, conversation_id, current_user.id)
        messages = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == conversation.id)
            .order_by(ConversationMessage.sequence.asc())
            .all()
        )
        return {
            "id": conversation.id,
            "title": conversation.title,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "message_count": len(messages),
            "messages": messages,
        }
    except HTTPException:
        raise
    except SQLAlchemyError:
        _database_unavailable(db)


@router.patch("/{conversation_id}", response_model=ConversationSummary)
def rename_conversation(
    conversation_id: UUID,
    payload: ConversationRename,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Conversation title is required")
    try:
        conversation = _owned_conversation(db, conversation_id, current_user.id)
        conversation.title = title
        conversation.updated_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "id": conversation.id,
            "title": conversation.title,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "message_count": db.query(func.count(ConversationMessage.id))
            .filter(ConversationMessage.conversation_id == conversation.id)
            .scalar(),
        }
    except HTTPException:
        raise
    except SQLAlchemyError:
        _database_unavailable(db)


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        conversation = _owned_conversation(db, conversation_id, current_user.id)
        db.delete(conversation)
        db.commit()
    except HTTPException:
        raise
    except SQLAlchemyError:
        _database_unavailable(db)


@router.post(
    "/{conversation_id}/messages",
    response_model=ConversationMessageResponse,
    status_code=201,
)
def save_conversation_message(
    conversation_id: UUID,
    payload: ConversationMessageCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        conversation = _owned_conversation(db, conversation_id, current_user.id)
        if payload.role != "user":
            raise HTTPException(
                status_code=422,
                detail="Client may only create user messages",
            )
        (
            db.query(Conversation)
            .filter(Conversation.id == conversation.id)
            .with_for_update()
            .one()
        )
        existing = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.id == payload.id)
            .first()
        )
        if existing is not None:
            if existing.conversation_id != conversation.id:
                raise HTTPException(status_code=404, detail="Conversation not found")
            if existing.role != payload.role or existing.content != payload.content:
                raise HTTPException(
                    status_code=409,
                    detail="Message ID is already associated with different content",
                )
            return existing
        sequence = (
            db.query(func.coalesce(func.max(ConversationMessage.sequence), 0))
            .filter(ConversationMessage.conversation_id == conversation.id)
            .scalar()
            + 1
        )
        message_created_at = datetime.now(timezone.utc)
        message = ConversationMessage(
            id=payload.id,
            conversation_id=conversation.id,
            sequence=sequence,
            role=payload.role,
            content=payload.content,
            created_at=message_created_at,
        )
        conversation.updated_at = message_created_at
        db.add(message)
        db.commit()
        db.refresh(message)
        return message
    except HTTPException:
        raise
    except SQLAlchemyError:
        _database_unavailable(db)
