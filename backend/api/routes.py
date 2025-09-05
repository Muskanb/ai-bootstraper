"""REST API routes."""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import List, Dict, Any, Optional
import uuid
from datetime import datetime
import logging

from backend.models.schemas import (
    APIResponse, 
    CreateSessionRequest, 
    UserResponseRequest,
    SessionState,
    ConversationState
)
from backend.core.session_manager import SessionManager
from backend.core.agent import ConversationAgent

logger = logging.getLogger(__name__)

# Create API router
api_router = APIRouter()

# Global instances (these would be dependency injected in production)
session_manager = SessionManager()
conversation_agent = ConversationAgent()


async def get_session_manager() -> SessionManager:
    """Dependency to get session manager."""
    return session_manager


async def get_conversation_agent() -> ConversationAgent:
    """Dependency to get conversation agent."""
    return conversation_agent


@api_router.post("/sessions", response_model=APIResponse)
async def create_session(
    request: CreateSessionRequest,
    session_mgr: SessionManager = Depends(get_session_manager)
):
    """
    Create a new conversation session.
    
    Args:
        request: Session creation request
        
    Returns:
        API response with new session info
    """
    try:
        # Generate session ID if not provided
        session_id = str(uuid.uuid4())
        
        # Create session
        session_state = await session_mgr.create_session(
            session_id=session_id,
            metadata=request.metadata
        )
        
        logger.info(f"Created session: {session_id}")
        
        return APIResponse(
            success=True,
            message="Session created successfully",
            data={
                "session_id": session_id,
                "state": session_state.current_state.value,
                "created_at": session_state.created_at.isoformat()
            }
        )
        
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/sessions", response_model=APIResponse)
async def list_sessions(
    session_mgr: SessionManager = Depends(get_session_manager)
):
    """
    List all sessions.
    
    Returns:
        API response with session list
    """
    try:
        sessions = await session_mgr.list_sessions()
        
        return APIResponse(
            success=True,
            message=f"Found {len(sessions)} sessions",
            data={"sessions": sessions}
        )
        
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/sessions/{session_id}", response_model=APIResponse)
async def get_session(
    session_id: str,
    session_mgr: SessionManager = Depends(get_session_manager)
):
    """
    Get session details.
    
    Args:
        session_id: Session identifier
        
    Returns:
        API response with session details
    """
    try:
        session_state = await session_mgr.load_state(session_id)
        
        return APIResponse(
            success=True,
            message="Session loaded successfully",
            data={
                "session": session_state.model_dump(mode='json'),
                "conversation_count": len(session_state.conversation_history)
            }
        )
        
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Error loading session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.delete("/sessions/{session_id}", response_model=APIResponse)
async def delete_session(
    session_id: str,
    session_mgr: SessionManager = Depends(get_session_manager)
):
    """
    Delete a session.
    
    Args:
        session_id: Session identifier
        
    Returns:
        API response confirming deletion
    """
    try:
        deleted = await session_mgr.delete_session(session_id)
        
        if not deleted:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return APIResponse(
            success=True,
            message="Session deleted successfully",
            data={"session_id": session_id}
        )
        
    except Exception as e:
        logger.error(f"Error deleting session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/sessions/{session_id}/messages", response_model=APIResponse)
async def send_message(
    session_id: str,
    request: UserResponseRequest,
    background_tasks: BackgroundTasks,
    session_mgr: SessionManager = Depends(get_session_manager),
    agent: ConversationAgent = Depends(get_conversation_agent)
):
    """
    Send a message to the conversation (non-streaming).
    
    Args:
        session_id: Session identifier
        request: User message request
        
    Returns:
        API response with conversation update
    """
    try:
        # Load session
        session_state = await session_mgr.load_state(session_id)
        
        # Process conversation in background
        background_tasks.add_task(
            agent.process_conversation,
            user_input=request.response,
            session_state=session_state,
            websocket=None
        )
        
        # Save session
        background_tasks.add_task(
            session_mgr.save_state,
            session_id,
            session_state
        )
        
        return APIResponse(
            success=True,
            message="Message sent, processing in background",
            data={
                "session_id": session_id,
                "message": request.response
            }
        )
        
    except Exception as e:
        logger.error(f"Error sending message to session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/sessions/{session_id}/history", response_model=APIResponse)
async def get_conversation_history(
    session_id: str,
    limit: Optional[int] = None,
    session_mgr: SessionManager = Depends(get_session_manager)
):
    """
    Get conversation history for a session.
    
    Args:
        session_id: Session identifier
        limit: Optional limit on number of messages
        
    Returns:
        API response with conversation history
    """
    try:
        history = await session_mgr.get_conversation_history(session_id, limit)
        
        return APIResponse(
            success=True,
            message=f"Retrieved {len(history)} messages",
            data={
                "history": history,
                "session_id": session_id
            }
        )
        
    except Exception as e:
        logger.error(f"Error getting history for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/sessions/{session_id}/state", response_model=APIResponse)
async def update_session_state(
    session_id: str,
    updates: Dict[str, Any],
    session_mgr: SessionManager = Depends(get_session_manager)
):
    """
    Update session state.
    
    Args:
        session_id: Session identifier
        updates: State updates to apply
        
    Returns:
        API response with updated state
    """
    try:
        session_state = await session_mgr.update_state(session_id, updates)
        
        return APIResponse(
            success=True,
            message="Session state updated",
            data={"session": session_state.model_dump()}
        )
        
    except Exception as e:
        logger.error(f"Error updating session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/sessions/{session_id}/checkpoint", response_model=APIResponse)
async def create_checkpoint(
    session_id: str,
    session_mgr: SessionManager = Depends(get_session_manager)
):
    """
    Create a checkpoint of the current session state.
    
    Args:
        session_id: Session identifier
        
    Returns:
        API response with checkpoint info
    """
    try:
        checkpoint_id = await session_mgr.create_checkpoint(session_id)
        
        return APIResponse(
            success=True,
            message="Checkpoint created",
            data={"checkpoint_id": checkpoint_id}
        )
        
    except Exception as e:
        logger.error(f"Error creating checkpoint for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/sessions/{session_id}/restore", response_model=APIResponse)
async def restore_checkpoint(
    session_id: str,
    checkpoint_id: str,
    session_mgr: SessionManager = Depends(get_session_manager)
):
    """
    Restore session from checkpoint.
    
    Args:
        session_id: Session identifier
        checkpoint_id: Checkpoint identifier
        
    Returns:
        API response confirming restoration
    """
    try:
        success = await session_mgr.restore_checkpoint(session_id, checkpoint_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Checkpoint not found")
        
        return APIResponse(
            success=True,
            message="Session restored from checkpoint",
            data={
                "session_id": session_id,
                "checkpoint_id": checkpoint_id
            }
        )
        
    except Exception as e:
        logger.error(f"Error restoring session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/cleanup", response_model=APIResponse)
async def cleanup_expired_sessions(
    background_tasks: BackgroundTasks,
    session_mgr: SessionManager = Depends(get_session_manager)
):
    """
    Clean up expired sessions.
    
    Returns:
        API response with cleanup results
    """
    try:
        # Run cleanup in background
        background_tasks.add_task(session_mgr.cleanup_expired_sessions)
        
        return APIResponse(
            success=True,
            message="Cleanup started in background",
            data={"timestamp": datetime.now().isoformat()}
        )
        
    except Exception as e:
        logger.error(f"Error starting cleanup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/health", response_model=APIResponse)
async def health_check():
    """
    Health check endpoint.
    
    Returns:
        API response with health status
    """
    return APIResponse(
        success=True,
        message="Service is healthy",
        data={
            "timestamp": datetime.now().isoformat(),
            "status": "running"
        }
    )


@api_router.get("/stats", response_model=APIResponse)
async def get_stats(
    session_mgr: SessionManager = Depends(get_session_manager)
):
    """
    Get service statistics.
    
    Returns:
        API response with statistics
    """
    try:
        sessions = await session_mgr.list_sessions()
        
        # Calculate stats
        total_sessions = len(sessions)
        active_sessions = sum(1 for s in sessions if 'modified' in s)
        
        return APIResponse(
            success=True,
            message="Statistics retrieved",
            data={
                "total_sessions": total_sessions,
                "active_sessions": active_sessions,
                "timestamp": datetime.now().isoformat()
            }
        )
        
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))