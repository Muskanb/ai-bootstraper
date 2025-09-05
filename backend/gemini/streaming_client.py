"""Gemini API streaming client with SSE support."""
import aiohttp
import json
import asyncio
import ssl
import certifi
from typing import AsyncGenerator, Dict, Any, List, Optional
from datetime import datetime
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.config import settings
from backend.models.schemas import (
    GeminiMessage,
    GeminiStreamChunk,
    GeminiFunctionCall
)

logger = logging.getLogger(__name__)


class GeminiStreamingClient:
    """Raw HTTP/SSE client for Gemini API."""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize Gemini client."""
        self.api_key = api_key or settings.GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("Gemini API key is required")
        
        self.base_url = settings.GEMINI_API_URL
        self.model = settings.GEMINI_MODEL
        self.session = None
        self.timeout = aiohttp.ClientTimeout(total=300, connect=10)
        
        # Create SSL context with certifi certificates
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        
    async def __aenter__(self):
        """Async context manager entry."""
        # Create TCP connector with proper SSL context
        import ssl
        ssl_context = ssl.create_default_context()
        # Trust the system certificates
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        
        self.connector = aiohttp.TCPConnector(ssl=ssl_context)
        self.session = aiohttp.ClientSession(timeout=self.timeout, connector=self.connector)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            try:
                await self.session.close()
            except Exception as e:
                logger.warning(f"Error closing aiohttp session: {e}")
            finally:
                self.session = None
                
        if hasattr(self, 'connector') and self.connector:
            try:
                await self.connector.close()
            except Exception as e:
                logger.warning(f"Error closing aiohttp connector: {e}")
            finally:
                self.connector = None
    
    def _format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format messages for Gemini API."""
        formatted = []
        for msg in messages:
            # Convert to Gemini format
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            # Gemini uses 'user' and 'model' roles
            if role == "assistant":
                role = "model"
            elif role == "system":
                # Prepend system messages to user content
                role = "user"
                content = f"System: {content}"
            
            formatted.append({
                "role": role,
                "parts": [{"text": content}]
            })
        
        return formatted
    
    def _build_request_payload(
        self,
        messages: List[Dict[str, Any]],
        functions: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 8192
    ) -> Dict[str, Any]:
        """Build request payload for Gemini API."""
        payload = {
            "contents": self._format_messages(messages),
            "generationConfig": {
                "temperature": temperature,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": max_tokens,
                "candidateCount": 1
            }
        }
        
        # Add function declarations if provided
        if functions:
            payload["tools"] = [{
                "functionDeclarations": functions
            }]
            # Enable function calling
            payload["toolConfig"] = {
                "functionCallingConfig": {
                    "mode": "AUTO"
                }
            }
        
        return payload
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    async def stream_completion(
        self,
        messages: List[Dict[str, Any]],
        functions: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 8192
    ) -> AsyncGenerator[GeminiStreamChunk, None]:
        """
        Stream responses from Gemini using SSE.
        
        Args:
            messages: Conversation history
            functions: Optional function declarations
            temperature: Sampling temperature
            max_tokens: Maximum output tokens
            
        Yields:
            GeminiStreamChunk: Parsed streaming chunks
        """
        if not self.session:
            raise ValueError("Client session not initialized. Use 'async with client:' context manager.")
        
        headers = {
            "Content-Type": "application/json",
        }
        
        # Build request payload
        payload = self._build_request_payload(
            messages, functions, temperature, max_tokens
        )
        
        # API endpoint with streaming
        url = f"{self.base_url}/models/{self.model}:streamGenerateContent"
        params = {
            "key": self.api_key
        }
        
        accumulated_content = ""
        
        try:
            async with self.session.post(
                url,
                headers=headers,
                json=payload,
                params=params
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Gemini API error: {response.status} - {error_text}")
                    raise Exception(f"Gemini API error: {response.status}")
                
                # Process streaming response - Gemini returns list of chunks
                response_data = await response.json()
                
                if isinstance(response_data, list):
                    # Process each chunk in the response
                    for chunk_data in response_data:
                        if "candidates" in chunk_data and chunk_data["candidates"]:
                            candidate = chunk_data["candidates"][0]
                            
                            # Check for text content
                            if "content" in candidate and "parts" in candidate["content"]:
                                for part in candidate["content"]["parts"]:
                                    if "text" in part:
                                        text_chunk = part["text"]
                                        accumulated_content += text_chunk
                                        
                                        yield GeminiStreamChunk(
                                            type="text",
                                            content=text_chunk,
                                            accumulated_content=accumulated_content
                                        )
                                    
                                    elif "functionCall" in part:
                                        func_call = part["functionCall"]
                                        
                                        yield GeminiStreamChunk(
                                            type="function_call",
                                            function_call=GeminiFunctionCall(
                                                name=func_call.get("name"),
                                                arguments=func_call.get("args", {})
                                            ),
                                            accumulated_content=accumulated_content
                                        )
                            
                            # Check for finish reason
                            if "finishReason" in candidate:
                                yield GeminiStreamChunk(
                                    type="finish",
                                    finish_reason=candidate["finishReason"],
                                    accumulated_content=accumulated_content
                                )
                                return
                else:
                    # Handle single response (fallback)
                    if "candidates" in response_data and response_data["candidates"]:
                        candidate = response_data["candidates"][0]
                        
                        if "content" in candidate and "parts" in candidate["content"]:
                            for part in candidate["content"]["parts"]:
                                if "text" in part:
                                    text = part["text"]
                                    accumulated_content += text
                                    
                                    yield GeminiStreamChunk(
                                        type="text",
                                        content=text,
                                        accumulated_content=accumulated_content
                                    )
                        
                        finish_reason = candidate.get("finishReason", "stop")
                        yield GeminiStreamChunk(
                            type="finish",
                            finish_reason=finish_reason,
                            accumulated_content=accumulated_content
                        )
                            
        except asyncio.TimeoutError:
            logger.error("Request to Gemini API timed out")
            raise
        except aiohttp.ClientError as e:
            logger.error(f"HTTP client error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in stream_completion: {e}")
            raise
    
    async def complete(
        self,
        messages: List[Dict[str, Any]],
        functions: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 8192
    ) -> Dict[str, Any]:
        """
        Get non-streaming completion from Gemini.
        
        Args:
            messages: Conversation history
            functions: Optional function declarations
            temperature: Sampling temperature
            max_tokens: Maximum output tokens
            
        Returns:
            Complete response as dictionary
        """
        if not self.session:
            raise ValueError("Client session not initialized. Use 'async with client:' context manager.")
        
        headers = {
            "Content-Type": "application/json",
        }
        
        # Build request payload
        payload = self._build_request_payload(
            messages, functions, temperature, max_tokens
        )
        
        # API endpoint without streaming
        url = f"{self.base_url}/models/{self.model}:generateContent"
        params = {"key": self.api_key}
        
        try:
            async with self.session.post(
                url,
                headers=headers,
                json=payload,
                params=params
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Gemini API error: {response.status} - {error_text}")
                    raise Exception(f"Gemini API error: {response.status}")
                
                return await response.json()
                
        except Exception as e:
            logger.error(f"Error in complete: {e}")
            raise


class GeminiChunkParser:
    """Parser for Gemini streaming chunks."""
    
    def __init__(self):
        """Initialize parser."""
        self.partial_content = ""
        self.partial_function_call = {}
        self.current_function_args = ""
        
    async def process_chunk(
        self,
        chunk: GeminiStreamChunk,
        session_state: Dict[str, Any],
        websocket = None
    ) -> Dict[str, Any]:
        """
        Process streaming chunk and update state incrementally.
        
        Args:
            chunk: Streaming chunk from Gemini
            session_state: Current session state
            websocket: Optional WebSocket for UI updates
            
        Returns:
            Processed result dictionary
        """
        result = {
            "type": chunk.type,
            "content": None,
            "function_call": None,
            "finished": False
        }
        
        # Handle text chunks
        if chunk.type == "text":
            self.partial_content += chunk.content
            result["content"] = chunk.content
            
            # Stream to UI immediately
            if websocket:
                await websocket.send_json({
                    "type": "ai_message_chunk",
                    "data": {
                        "chunk": chunk.content,
                        "accumulated": self.partial_content
                    }
                })
            
            # Update session state incrementally
            session_state["partial_response"] = self.partial_content
        
        # Handle function calls
        elif chunk.type == "function_call":
            self.partial_function_call = {
                "name": chunk.function_call.name,
                "arguments": chunk.function_call.arguments
            }
            result["function_call"] = self.partial_function_call
            
            if websocket:
                await websocket.send_json({
                    "type": "function_call_detected",
                    "data": self.partial_function_call
                })
        
        # Handle completion
        elif chunk.type == "finish":
            result["finished"] = True
            
            # Finalize response
            if self.partial_content:
                session_state["last_response"] = self.partial_content
                
            if self.partial_function_call:
                session_state["pending_function"] = self.partial_function_call
            
            session_state["response_complete"] = True
            
            # Reset parser state
            self.partial_content = ""
            self.partial_function_call = {}
        
        return result