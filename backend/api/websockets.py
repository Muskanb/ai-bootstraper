"""WebSocket handlers for real-time communication."""
import asyncio
from typing import Dict, List, Optional
from datetime import datetime
import json
import logging
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manage WebSocket connections."""
    
    def __init__(self):
        """Initialize WebSocket manager."""
        self.active_connections: Dict[str, WebSocket] = {}
        self.session_connections: Dict[str, List[WebSocket]] = {}
        self.heartbeat_tasks: Dict[str, asyncio.Task] = {}
        
    async def connect(self, websocket: WebSocket, session_id: str):
        """
        Accept a new WebSocket connection.
        
        Args:
            websocket: WebSocket connection
            session_id: Session identifier
        """
        await websocket.accept()
        
        # Generate connection ID
        connection_id = f"{session_id}_{datetime.now().timestamp()}"
        
        # Store connection
        self.active_connections[connection_id] = websocket
        
        if session_id not in self.session_connections:
            self.session_connections[session_id] = []
        self.session_connections[session_id].append(websocket)
        
        # Start heartbeat
        self.heartbeat_tasks[connection_id] = asyncio.create_task(
            self._heartbeat_loop(websocket, connection_id)
        )
        
        logger.info(f"WebSocket connected: {connection_id} (session: {session_id})")
        
        # Send connection confirmation
        await websocket.send_json({
            "type": "connection_established",
            "data": {
                "connection_id": connection_id,
                "session_id": session_id,
                "timestamp": datetime.now().isoformat()
            }
        })
    
    def disconnect(self, session_id: str, websocket: Optional[WebSocket] = None):
        """
        Disconnect a WebSocket connection.
        
        Args:
            session_id: Session identifier
            websocket: Specific WebSocket to disconnect (optional)
        """
        # Find and remove connection
        connections_to_remove = []
        
        for conn_id, conn_websocket in self.active_connections.items():
            if conn_id.startswith(f"{session_id}_") and (websocket is None or conn_websocket == websocket):
                connections_to_remove.append(conn_id)
        
        for conn_id in connections_to_remove:
            # Cancel heartbeat task
            if conn_id in self.heartbeat_tasks:
                self.heartbeat_tasks[conn_id].cancel()
                del self.heartbeat_tasks[conn_id]
            
            # Remove from active connections
            if conn_id in self.active_connections:
                del self.active_connections[conn_id]
            
            logger.info(f"WebSocket disconnected: {conn_id}")
        
        # Clean up session connections
        if session_id in self.session_connections:
            if websocket:
                self.session_connections[session_id] = [
                    conn for conn in self.session_connections[session_id] 
                    if conn != websocket
                ]
            else:
                self.session_connections[session_id] = []
            
            # Remove empty session
            if not self.session_connections[session_id]:
                del self.session_connections[session_id]
    
    async def send_to_session(self, session_id: str, message: Dict):
        """
        Send message to all connections for a session.
        
        Args:
            session_id: Session identifier
            message: Message to send
        """
        logger.info(f"🔍 Attempting to send message to session {session_id}: {message.get('type', 'unknown')}")
        logger.info(f"🔍 Available sessions: {list(self.session_connections.keys())}")
        
        if session_id not in self.session_connections:
            logger.warning(f"❌ No active connections for session: {session_id}")
            return
        
        # Send to all connections for this session
        disconnected = []
        for websocket in self.session_connections[session_id]:
            try:
                # Ensure message is JSON serializable by using custom encoder
                import json
                from datetime import datetime
                
                def datetime_encoder(obj):
                    if isinstance(obj, datetime):
                        return obj.isoformat()
                    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
                
                # Convert to JSON string first, then send
                json_str = json.dumps(message, default=datetime_encoder)
                json_obj = json.loads(json_str)
                await websocket.send_json(json_obj)
                logger.info(f"✅ Successfully sent {message.get('type', 'unknown')} to WebSocket")
            except Exception as e:
                logger.error(f"Error sending message to WebSocket: {e}")
                disconnected.append(websocket)
        
        # Clean up disconnected connections
        for websocket in disconnected:
            self.disconnect(session_id, websocket)
    
    async def broadcast(self, message: Dict, exclude_sessions: List[str] = None):
        """
        Broadcast message to all active connections.
        
        Args:
            message: Message to broadcast
            exclude_sessions: Sessions to exclude from broadcast
        """
        exclude_sessions = exclude_sessions or []
        
        disconnected = []
        for conn_id, websocket in self.active_connections.items():
            session_id = conn_id.split('_')[0]
            
            if session_id in exclude_sessions:
                continue
            
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to {conn_id}: {e}")
                disconnected.append(conn_id)
        
        # Clean up disconnected connections
        for conn_id in disconnected:
            if conn_id in self.active_connections:
                websocket = self.active_connections[conn_id]
                session_id = conn_id.split('_')[0]
                self.disconnect(session_id, websocket)
    
    async def disconnect_all(self):
        """Disconnect all WebSocket connections."""
        # Cancel all heartbeat tasks
        for task in self.heartbeat_tasks.values():
            task.cancel()
        
        # Close all connections
        for websocket in self.active_connections.values():
            try:
                await websocket.close()
            except Exception as e:
                logger.error(f"Error closing WebSocket: {e}")
        
        # Clear all data structures
        self.active_connections.clear()
        self.session_connections.clear()
        self.heartbeat_tasks.clear()
        
        logger.info("All WebSocket connections disconnected")
    
    def get_connection_count(self) -> int:
        """Get total number of active connections."""
        return len(self.active_connections)
    
    def get_session_count(self) -> int:
        """Get number of active sessions."""
        return len(self.session_connections)
    
    def get_connections_for_session(self, session_id: str) -> List[WebSocket]:
        """Get all connections for a session."""
        return self.session_connections.get(session_id, [])
    
    async def _heartbeat_loop(self, websocket: WebSocket, connection_id: str):
        """
        Maintain heartbeat with WebSocket connection.
        
        Args:
            websocket: WebSocket connection
            connection_id: Connection identifier
        """
        try:
            while True:
                await asyncio.sleep(30)  # Heartbeat every 30 seconds
                
                # Send heartbeat
                await websocket.send_json({
                    "type": "heartbeat",
                    "data": {
                        "timestamp": datetime.now().isoformat(),
                        "connection_id": connection_id
                    }
                })
                
        except asyncio.CancelledError:
            logger.debug(f"Heartbeat cancelled for {connection_id}")
        except Exception as e:
            logger.error(f"Heartbeat error for {connection_id}: {e}")
            # Remove failed connection
            session_id = connection_id.split('_')[0]
            self.disconnect(session_id, websocket)


class MessageTypes:
    """WebSocket message types."""
    
    # Connection management
    CONNECTION_ESTABLISHED = "connection_established"
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"
    
    # User interactions
    USER_MESSAGE = "user_message"
    USER_RESPONSE = "user_response"
    AI_MESSAGE = "ai_message"
    AI_MESSAGE_CHUNK = "ai_message_chunk"
    
    # Function execution
    FUNCTION_CALL_DETECTED = "function_call_detected"
    FUNCTION_EXECUTION_START = "function_execution_start"
    FUNCTION_EXECUTION_COMPLETE = "function_execution_complete"
    FUNCTION_EXECUTION_ERROR = "function_execution_error"
    
    # State management
    STATE_UPDATE = "state_update"
    SESSION_RESUMED = "session_resumed"
    
    # Command execution
    COMMAND_START = "command_start"
    COMMAND_OUTPUT = "command_output"
    COMMAND_COMPLETE = "command_complete"
    COMMAND_ERROR = "command_error"
    
    # Progress tracking
    PROGRESS_UPDATE = "progress_update"
    
    # Errors and notifications
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    SUCCESS = "success"


async def handle_websocket_message(
    websocket: WebSocket,
    message: Dict,
    session_id: str,
    conversation_agent,
    session_manager,
    websocket_manager=None
):
    """
    Handle incoming WebSocket messages.
    
    Args:
        websocket: WebSocket connection
        message: Received message
        session_id: Session identifier
        conversation_agent: Conversation agent instance
        session_manager: Session manager instance
    """
    message_type = message.get("type")
    data = message.get("data", {})
    
    try:
        if message_type == MessageTypes.USER_MESSAGE:
            # User sent a message
            user_message = data.get("message", "")
            
            # Load session state
            session_state = await session_manager.load_state(session_id)
            
            # Process conversation
            await conversation_agent.process_conversation(
                user_input=user_message,
                session_state=session_state,
                websocket=websocket
            )
            
            # Save updated state
            await session_manager.save_state(session_id, session_state)
            
        elif message_type == MessageTypes.USER_RESPONSE:
            # User responded to a question/permission request
            user_response = data.get("response", "")
            
            # Load session state
            session_state = await session_manager.load_state(session_id)
            
            # Process conversation with the user response
            await conversation_agent.process_conversation(
                user_input=user_response,
                session_state=session_state,
                websocket=websocket
            )
            
            # Save updated state
            await session_manager.save_state(session_id, session_state)
            
        elif message_type == MessageTypes.HEARTBEAT:
            # Respond to heartbeat
            await websocket.send_json({
                "type": MessageTypes.HEARTBEAT_ACK,
                "data": {"timestamp": datetime.now().isoformat()}
            })
            
        elif message_type == "get_session_state":
            # Send current session state
            session_state = await session_manager.load_state(session_id)
            
            await websocket.send_json({
                "type": MessageTypes.STATE_UPDATE,
                "data": {
                    "session_state": session_state.model_dump(mode='json'),
                    "timestamp": datetime.now().isoformat()
                }
            })
            
        elif message_type == "start_new_session":
            # Start a new conversation
            session_state = await conversation_agent.start_new_conversation(
                session_id=session_id,
                websocket=websocket
            )
            
            await websocket.send_json({
                "type": MessageTypes.STATE_UPDATE,
                "data": {
                    "session_state": session_state.model_dump(mode='json'),
                    "message": "New session started",
                    "timestamp": datetime.now().isoformat()
                }
            })
            
        elif message_type == "resume_session":
            # Resume existing conversation
            session_state = await conversation_agent.resume_conversation(
                session_id=session_id,
                websocket=websocket
            )
            
        else:
            logger.warning(f"Unknown message type: {message_type}")
            await websocket.send_json({
                "type": MessageTypes.WARNING,
                "data": {
                    "message": f"Unknown message type: {message_type}",
                    "timestamp": datetime.now().isoformat()
                }
            })
            
    except Exception as e:
        logger.error(f"Error handling WebSocket message: {e}")
        
        await websocket.send_json({
            "type": MessageTypes.ERROR,
            "data": {
                "message": f"Error processing message: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }
        })