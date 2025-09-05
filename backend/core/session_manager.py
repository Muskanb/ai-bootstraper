"""Session management system."""
import json
import aiofiles
import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import asyncio
import logging

from backend.config import settings
from backend.models.schemas import SessionState, ConversationState

logger = logging.getLogger(__name__)


class SessionManager:
    """Manage session state persistence and lifecycle."""
    
    def __init__(self):
        """Initialize session manager."""
        self.session_dir = settings.SESSION_DIR
        self.session_timeout = settings.SESSION_TIMEOUT
        self._locks = {}  # Per-session locks for atomic operations
        
        # Ensure session directory exists
        os.makedirs(self.session_dir, exist_ok=True)
    
    def _get_session_file(self, session_id: str) -> str:
        """Get session file path."""
        return os.path.join(self.session_dir, f"{session_id}.json")
    
    def _get_lock(self, session_id: str) -> asyncio.Lock:
        """Get or create lock for session."""
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]
    
    async def create_session(
        self,
        session_id: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> SessionState:
        """
        Create a new session.
        
        Args:
            session_id: Optional session ID, generates UUID if not provided
            metadata: Optional metadata to include
            
        Returns:
            New session state
        """
        if not session_id:
            session_id = str(uuid.uuid4())
        
        session_state = SessionState(
            session_id=session_id,
            current_state=ConversationState.INIT,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        # Add metadata if provided
        if metadata:
            session_state.conversation_history.append({
                "role": "system",
                "content": f"Session metadata: {json.dumps(metadata)}",
                "timestamp": datetime.now().isoformat(),
                "metadata": metadata
            })
        
        # Save to file
        await self.save_state(session_id, session_state)
        
        logger.info(f"Created new session: {session_id}")
        return session_state
    
    async def load_state(self, session_id: str) -> SessionState:
        """
        Load session state from file.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session state
            
        Raises:
            FileNotFoundError: If session doesn't exist
        """
        session_file = self._get_session_file(session_id)
        
        if not os.path.exists(session_file):
            logger.warning(f"Session not found: {session_id}")
            # Create new session with the given ID
            return await self.create_session(session_id)
        
        lock = self._get_lock(session_id)
        async with lock:
            try:
                async with aiofiles.open(session_file, 'r') as f:
                    data = await f.read()
                    session_data = json.loads(data)
                    
                    # Create SessionState from loaded data
                    session_state = SessionState(**session_data)
                    
                    # Check if session is expired
                    if self._is_session_expired(session_state):
                        logger.warning(f"Session expired: {session_id}")
                        session_state.current_state = ConversationState.ERROR
                        session_state.error_message = "Session expired"
                    
                    return session_state
                    
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error for session {session_id}: {e}")
                # Create new session if corrupted
                return await self.create_session(session_id)
            except Exception as e:
                logger.error(f"Failed to load session {session_id}: {e}")
                # Try to handle validation errors by recreating the session
                return await self.create_session(session_id)
    
    async def save_state(self, session_id: str, session_state: SessionState):
        """
        Save session state to file atomically.
        
        Args:
            session_id: Session identifier
            session_state: Session state to save
        """
        session_file = self._get_session_file(session_id)
        temp_file = f"{session_file}.tmp"
        
        # Update timestamp
        session_state.updated_at = datetime.now()
        session_state.state_version += 1
        
        lock = self._get_lock(session_id)
        async with lock:
            try:
                # Write to temporary file first
                async with aiofiles.open(temp_file, 'w') as f:
                    await f.write(session_state.model_dump_json(indent=2))
                
                # Atomic move
                os.rename(temp_file, session_file)
                
                logger.debug(f"Saved session state: {session_id}")
                
            except Exception as e:
                logger.error(f"Failed to save session {session_id}: {e}")
                # Clean up temp file if it exists
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                raise
    
    async def update_state(
        self,
        session_id: str,
        updates: Dict,
        create_if_not_exists: bool = True
    ) -> SessionState:
        """
        Update session state with partial updates.
        
        Args:
            session_id: Session identifier
            updates: Dictionary of updates to apply
            create_if_not_exists: Create session if it doesn't exist
            
        Returns:
            Updated session state
        """
        try:
            session_state = await self.load_state(session_id)
        except FileNotFoundError:
            if create_if_not_exists:
                session_state = await self.create_session(session_id)
            else:
                raise
        
        # Apply updates
        for key, value in updates.items():
            if hasattr(session_state, key):
                setattr(session_state, key, value)
        
        await self.save_state(session_id, session_state)
        return session_state
    
    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if deleted, False if not found
        """
        session_file = self._get_session_file(session_id)
        
        if os.path.exists(session_file):
            os.remove(session_file)
            
            # Clean up lock
            if session_id in self._locks:
                del self._locks[session_id]
            
            logger.info(f"Deleted session: {session_id}")
            return True
        
        return False
    
    async def list_sessions(self) -> List[Dict[str, str]]:
        """
        List all sessions.
        
        Returns:
            List of session information
        """
        sessions = []
        
        try:
            for filename in os.listdir(self.session_dir):
                if filename.endswith('.json'):
                    session_id = filename[:-5]  # Remove .json
                    session_file = self._get_session_file(session_id)
                    
                    try:
                        stat = os.stat(session_file)
                        sessions.append({
                            "session_id": session_id,
                            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            "size": stat.st_size
                        })
                    except Exception as e:
                        logger.warning(f"Failed to get stats for session {session_id}: {e}")
                        
        except Exception as e:
            logger.error(f"Failed to list sessions: {e}")
        
        return sessions
    
    async def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions.
        
        Returns:
            Number of sessions cleaned up
        """
        cleaned = 0
        
        try:
            sessions = await self.list_sessions()
            
            for session_info in sessions:
                try:
                    # Load session to check expiry
                    session_state = await self.load_state(session_info["session_id"])
                    
                    if self._is_session_expired(session_state):
                        await self.delete_session(session_info["session_id"])
                        cleaned += 1
                        
                except Exception as e:
                    logger.warning(f"Failed to check session {session_info['session_id']}: {e}")
                    
        except Exception as e:
            logger.error(f"Failed to cleanup expired sessions: {e}")
        
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} expired sessions")
        
        return cleaned
    
    def _is_session_expired(self, session_state: SessionState) -> bool:
        """
        Check if session is expired.
        
        Args:
            session_state: Session state to check
            
        Returns:
            True if expired
        """
        if not session_state.updated_at:
            return False
        
        expiry_time = session_state.updated_at + timedelta(seconds=self.session_timeout)
        return datetime.now() > expiry_time
    
    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        **kwargs
    ):
        """
        Add a message to session conversation history.
        
        Args:
            session_id: Session identifier
            role: Message role (user/assistant/system)
            content: Message content
            **kwargs: Additional message metadata
        """
        session_state = await self.load_state(session_id)
        session_state.add_message(role, content, **kwargs)
        await self.save_state(session_id, session_state)
    
    async def get_conversation_history(
        self,
        session_id: str,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Get conversation history for session.
        
        Args:
            session_id: Session identifier
            limit: Optional limit on number of messages
            
        Returns:
            Conversation history
        """
        session_state = await self.load_state(session_id)
        history = session_state.conversation_history
        
        if limit:
            history = history[-limit:]
        
        return history
    
    async def create_checkpoint(self, session_id: str) -> str:
        """
        Create a checkpoint of the current session state.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Checkpoint identifier
        """
        session_state = await self.load_state(session_id)
        checkpoint_id = f"{session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        checkpoint_file = os.path.join(self.session_dir, f"checkpoint_{checkpoint_id}.json")
        
        async with aiofiles.open(checkpoint_file, 'w') as f:
            await f.write(session_state.model_dump_json(indent=2))
        
        logger.info(f"Created checkpoint: {checkpoint_id}")
        return checkpoint_id
    
    async def restore_checkpoint(self, session_id: str, checkpoint_id: str) -> bool:
        """
        Restore session from checkpoint.
        
        Args:
            session_id: Session identifier
            checkpoint_id: Checkpoint identifier
            
        Returns:
            True if restored successfully
        """
        checkpoint_file = os.path.join(self.session_dir, f"checkpoint_{checkpoint_id}.json")
        
        if not os.path.exists(checkpoint_file):
            return False
        
        try:
            async with aiofiles.open(checkpoint_file, 'r') as f:
                data = await f.read()
                session_data = json.loads(data)
                
                # Update session ID to current one
                session_data['session_id'] = session_id
                session_state = SessionState(**session_data)
                
                await self.save_state(session_id, session_state)
                logger.info(f"Restored session {session_id} from checkpoint {checkpoint_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to restore checkpoint {checkpoint_id}: {e}")
            return False