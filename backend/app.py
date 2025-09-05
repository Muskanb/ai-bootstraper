"""Main FastAPI application."""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import asyncio
from typing import Dict, List
import uuid
from datetime import datetime

from backend.config import settings
from backend.api.routes import api_router
from backend.api.websockets import WebSocketManager, handle_websocket_message
from backend.core.session_manager import SessionManager
from backend.core.agent import ConversationAgent
import logging

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(settings.LOG_FILE),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting AI Agent Bootstrapper...")
    logger.info(f"Environment: {settings.APP_ENV}")
    logger.info(f"Debug mode: {settings.DEBUG}")
    
    # Initialize components
    app.state.websocket_manager = WebSocketManager()
    app.state.session_manager = SessionManager()
    app.state.conversation_agent = ConversationAgent()
    
    yield
    
    # Shutdown
    logger.info("Shutting down AI Agent Bootstrapper...")
    # Cleanup tasks
    await app.state.websocket_manager.disconnect_all()


# Create FastAPI app
app = FastAPI(
    title="AI Agent Bootstrapper",
    description="Intelligent project scaffolding with Gemini AI",
    version="1.0.0",
    debug=settings.DEBUG,
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "AI Agent Bootstrapper",
        "version": "1.0.0",
        "status": "running",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "environment": settings.APP_ENV,
        "gemini_configured": bool(settings.GEMINI_API_KEY)
    }


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time communication."""
    manager = app.state.websocket_manager
    await manager.connect(websocket, session_id)
    
    try:
        # Send initial connection message
        await websocket.send_json({
            "type": "connection_established",
            "data": {
                "session_id": session_id,
                "timestamp": datetime.now().isoformat()
            }
        })
        
        # CRITICAL FIX: Auto-start conversation when WebSocket connects
        # Check if session exists and start conversation if needed
        try:
            from backend.api.websockets import handle_websocket_message
            # Trigger conversation start automatically
            await handle_websocket_message(
                websocket=websocket,
                message={"type": "start_new_session", "data": {}},
                session_id=session_id,
                conversation_agent=app.state.conversation_agent,
                session_manager=app.state.session_manager,
                websocket_manager=app.state.websocket_manager
            )
        except Exception as e:
            logger.error(f"Error auto-starting conversation: {e}")
        
        # Keep connection alive and handle messages
        while True:
            data = await websocket.receive_json()
            
            # Handle message using the dedicated handler
            await handle_websocket_message(
                websocket=websocket,
                message=data,
                session_id=session_id,
                conversation_agent=app.state.conversation_agent,
                session_manager=app.state.session_manager,
                websocket_manager=app.state.websocket_manager
            )
                
    except WebSocketDisconnect:
        manager.disconnect(session_id)
        logger.info(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(session_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower()
    )