"""Main conversation agent orchestrator."""
import asyncio
import json
from typing import Dict, Any, Optional
from datetime import datetime
import logging

from backend.config import settings
from backend.models.schemas import SessionState, ConversationState, GeminiStreamChunk
from backend.gemini.streaming_client import GeminiStreamingClient, GeminiChunkParser
from backend.gemini.function_registry import function_registry
from backend.core.state_machine import conversation_state_machine
from backend.core.session_manager import SessionManager

logger = logging.getLogger(__name__)


class ConversationAgent:
    """Main AI agent that orchestrates the conversation flow."""
    
    def __init__(self):
        """Initialize conversation agent."""
        self.gemini_client = None
        self.chunk_parser = GeminiChunkParser()
        self.function_registry = function_registry
        self.state_machine = conversation_state_machine
        self.session_manager = SessionManager()
        self.max_iterations = settings.MAX_ITERATIONS
        
    async def _get_gemini_client(self) -> GeminiStreamingClient:
        """Get or create Gemini client."""
        if self.gemini_client is None:
            self.gemini_client = GeminiStreamingClient()
        return self.gemini_client
    
    def _build_system_prompt(self, session_state: SessionState) -> str:
        """Build context-aware system prompt."""
        current_state = session_state.current_state
        requirements = session_state.requirements.model_dump()
        capabilities = session_state.capabilities.model_dump() if session_state.capabilities else {}
        
        # Get state-specific instructions
        state_instructions = self.state_machine.get_state_instructions(current_state)
        
        # Get progress information
        progress_info = self.state_machine.get_state_progress(session_state)
        
        system_prompt = f"""You are an AI agent that helps users bootstrap development projects.

CURRENT SESSION INFO:
- Session ID: {session_state.session_id}
- Current State: {current_state.value}
- Iteration: {session_state.iteration_count}
- Progress: {progress_info['progress_percentage']}%
- Completion: {session_state.completion_percentage}%

COLLECTED REQUIREMENTS:
{json.dumps(requirements, indent=2)}

SYSTEM CAPABILITIES:
{json.dumps(capabilities, indent=2)}

CURRENT STATE INSTRUCTIONS:
{state_instructions}

AVAILABLE FUNCTIONS:
{json.dumps([func["name"] for func in self.function_registry.get_function_schemas()], indent=2)}

CONVERSATION GUIDELINES:
1. Be conversational and helpful
2. Use function calls to update state and collect information
3. Stream responses naturally, thinking step by step
4. Adapt based on user responses and system capabilities
5. Always validate information before proceeding
6. Handle errors gracefully with alternatives
7. Keep the user informed of progress

IMPORTANT RULES:
- If you are explicitly in a waiting stage, write back to the user in some time / frame it as a question so the user know what next
- Use function calls when you need to update state or ask structured questions
- Don't ask Language and Framework related questions.
- Take decision on what Language and Framework to use based on detected system capabilities
- Framework questions should be asked if user have multiple tools, which can be used for the same Project Requirement, Else suggest the best from detected system capabilities
- Always confirm critical decisions before execution
- Provide examples when the user seems confused
- If something fails, suggest alternatives


REQUIRED WORKFLOW:
1. First, request permissions if needed (request_permission function)
2. Ask User to first give permission to read capabilites and then move forward, end the session if not permission
2. Then detect system capabilities (detect_system_capabilities function)
3. Collect all project requirements (update_project_requirements function) 
4. Create the project directly by calling create_project_with_steps function with detailed steps

CRITICAL: When user confirms project creation, you MUST immediately call create_project_with_steps function with detailed steps.
DO NOT just say "creating project" - ACTUALLY CALL THE FUNCTION!

This function allows you to:
- Provide shell commands to execute (mkdir, npm init, etc.)
- Create files with content using command="CREATE_FILE", file_path="path/to/file", file_content="content"
- Everything executes immediately - no separate execution step needed!

ALWAYS call this function immediately after user confirms. Do not hesitate or ask again.

IMPORTANT: First basic setup needs to be done, then For creating files, use generate_file_content function first to create appropriate content, should be executed for each file created during our create_project_with_steps!

Example workflow for React Native project:
1. generate_file_content(file_path="App.tsx", project_type="mobile_app", project_name="MyApp", framework="React Native")
2. create_project_with_steps([
  {{"command": "mkdir -p MyApp", "description": "Create project directory"}},
  {{"command": "npx @react-native-community/cli init MyApp --template react-native-template-typescript", "description": "Create React Native project with modern CLI"}},
  {{"command": "CREATE_FILE", "file_path": "App.tsx", "file_content": "[CONTENT FROM generate_file_content]", "description": "Create main App component with proper React Native code"}},
  {{"command": "CREATE_FILE", "file_path": "README.md", "file_content": "[GENERATED README]", "description": "Create project documentation"}}
])

This ensures files have meaningful, working content instead of being empty!

Remember: This is iteration {session_state.iteration_count}. Build upon the conversation history."""
        
        return system_prompt
    
    def _get_status_message(self, status: str, function_name: str) -> str:
        """Get user-friendly status message for function results."""
        status_messages = {
            "waiting_for_user": f"⏳ {function_name} is waiting for your input",
            "permission_requested": f"🔐 {function_name} requesting permission",
            "completed": f"✅ {function_name} completed successfully",
            "capabilities_detected": "✅ System capabilities detected successfully",
            "capabilities_already_detected": "✅ System capabilities already available",
            "requirements_updated": "✅ Project requirements updated",
            "plan_generated": "✅ Execution plan ready",
            "error": f"❌ {function_name} encountered an error",
            "failed": f"❌ {function_name} failed",
            "needs_retry": f"🔄 {function_name} will be retried",
            "executing": f"⚙️ {function_name} is running...",
            "validating": f"🔍 Validating {function_name} parameters..."
        }
        return status_messages.get(status, f"📝 {function_name}: {status}")
    
    async def _should_advance_workflow(self, session_state: SessionState, websocket=None) -> bool:
        """Determine if workflow should advance based on function results and state."""
        
        # Don't advance if waiting for user input
        if session_state.waiting_for_user or session_state.pending_question:
            return False
        
        # Get last function result from existing function_results list
        if not session_state.function_results:
            # No function executed, safe to advance
            return True
        
        # Get the most recent function result
        last_function = session_state.function_results[-1]
        
        function_name = last_function.get('name')
        status = last_function.get('status')
        
        # Define completion statuses that allow workflow advancement
        advancement_statuses = [
            'completed',
            'capabilities_detected', 
            'capabilities_already_detected',
            'requirements_updated',
            'updated',  # For update_project_requirements function
            'validation_complete',  # For validate_requirements_against_capabilities function
            'confirmed',  # For confirm_project_creation function
            'plan_generated',
            'ai_recovery_needed'  # Let AI analyze and provide alternative approach
        ]
        
        # Define blocking statuses that prevent advancement
        blocking_statuses = [
            'waiting_for_user',
            'permission_requested',
            'error',
            'failed',
            'needs_retry',
            'executing',
            'validating'
        ]
        
        # Special handling for permission_requested - check if permissions are actually granted
        if status == 'permission_requested':
            if function_name == 'request_permission':
                # Check if permissions are granted for INIT state
                if session_state.current_state == ConversationState.INIT:
                    has_permissions = len(session_state.permissions) > 0 and any(
                        perm.get('granted', False) for perm in session_state.permissions.values()
                    )
                    
                    logger.info(f"🔍 Permission check: has_permissions={has_permissions}, permissions={list(session_state.permissions.keys())}")
                    
                    if has_permissions:
                        # Permission granted - allow advancement
                        logger.info("✅ Permission granted - allowing state advancement")
                        return True
                    else:
                        # Permission still pending - block advancement
                        logger.warning("⚠️ Permission still pending - blocking advancement")
                        if websocket:
                            await websocket.send_json({
                                "type": "advancement_blocked",
                                "data": {
                                    "reason": "permission_pending",
                                    "function_name": function_name,
                                    "message": "⚠️ Waiting for user permission approval",
                                    "timestamp": datetime.now().isoformat()
                                }
                            })
                        return False
        
        if status in blocking_statuses:
            # Stream why we're not advancing
            if websocket:
                await websocket.send_json({
                    "type": "advancement_blocked",
                    "data": {
                        "reason": status,
                        "function_name": function_name,
                        "message": f"⚠️ Cannot advance: {function_name} status is {status}",
                        "timestamp": datetime.now().isoformat()
                    }
                })
            return False
        
        if status in advancement_statuses:
            # Check state-specific advancement logic
            current_state = session_state.current_state.value
            
            # Additional validation based on current state
            if current_state == "INIT":
                # Can advance if permissions are granted or handled
                return len(session_state.permissions) > 0
                
            elif current_state == "CHECK_SYSTEM_CAPABILITIES":
                # Can advance if capabilities are detected
                return hasattr(session_state, 'capabilities') and session_state.capabilities is not None
                
            elif current_state in ["ASK_PROJECT_TYPE", "ASK_PROJECT_NAME_FOLDER", "ASK_ADDITIONAL_DETAILS"]:
                # Can advance if basic requirements are collected
                return (hasattr(session_state.requirements, 'project_type') and 
                       session_state.requirements.project_type is not None)
                
            elif current_state == "PLANNING":
                # Can advance if execution plan exists
                return hasattr(session_state, 'execution_plan') and session_state.execution_plan is not None
            
            # Default: allow advancement for completion statuses
            return True
        
        # Unknown status - be conservative and don't advance
        if websocket:
            await websocket.send_json({
                "type": "advancement_uncertain",
                "data": {
                    "status": status,
                    "function_name": function_name,
                    "message": f"⚠️ Unknown status {status} from {function_name}, staying in current state",
                    "timestamp": datetime.now().isoformat()
                }
            })
        
        return False
    
    def _format_conversation_history(self, session_state: SessionState) -> list:
        """Format conversation history for Gemini."""
        messages = []
        
        # Add system message
        system_prompt = self._build_system_prompt(session_state)
        messages.append({
            "role": "system",
            "content": system_prompt
        })
        
        # Add conversation history (last 20 messages to stay within limits)
        recent_history = session_state.conversation_history[-20:] if session_state.conversation_history else []
        
        for msg in recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            # Skip empty messages
            if not content.strip():
                continue
            
            messages.append({
                "role": role,
                "content": content
            })
        
        return messages
    
    async def process_conversation(
        self,
        user_input: str,
        session_state: SessionState,
        websocket=None
    ):
        """
        Main conversation processing with streaming and state management.
        
        Args:
            user_input: User's input message
            session_state: Current session state
            websocket: WebSocket for real-time updates
        """
        try:
            # Add user message to history first
            session_state.add_message("user", user_input)
            
            # Handle pending function responses (like user choices) BEFORE clearing state
            if session_state.pending_question:
                response_valid = await self._handle_user_response(user_input, session_state, websocket)
                
                # Only clear waiting state if response was valid
                if response_valid and session_state.waiting_for_user:
                    session_state.waiting_for_user = False
                    # pending_question is cleared by _handle_user_response if valid
                    
                    # Stream status update
                    if websocket:
                        await websocket.send_json({
                            "type": "user_response_processed", 
                            "data": {
                                "message": "✓ Response accepted, continuing workflow...",
                                "timestamp": datetime.now().isoformat()
                            }
                        })
                    
                    await self._process_with_gemini(session_state, websocket)
                    return
            
            # Process with Gemini
            await self._process_with_gemini(session_state, websocket)
            
        except Exception as e:
            logger.error(f"Error in process_conversation: {e}")
            session_state.error_message = str(e)
            
            if websocket:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": f"An error occurred: {e}"}
                })
    
    async def _handle_user_response(
        self,
        user_input: str,
        session_state: SessionState,
        websocket=None
    ) -> bool:
        """Handle user response to pending questions.
        
        Returns:
            bool: True if response was valid, False if invalid
        """
        if not session_state.pending_question:
            return True
        
        question = session_state.pending_question
        question_type = question.get("type")
        
        if question_type == "choice":
            # Handle multiple choice response
            field = question.get("field")
            options = question.get("options", [])
            
            # Find matching option (case insensitive)
            selected_option = None
            user_lower = user_input.lower().strip()
            
            for option in options:
                if option.lower() == user_lower or user_lower in option.lower():
                    selected_option = option
                    break
            
            if selected_option:
                # Update requirements with user choice
                if hasattr(session_state.requirements, field):
                    # Handle project_type mapping from user-friendly input to enum
                    if field == "project_type" and isinstance(selected_option, str):
                        from backend.models.schemas import ProjectType
                        selected_option = self._map_project_type_string(selected_option)
                    setattr(session_state.requirements, field, selected_option)
                
                # Add to conversation
                session_state.add_message(
                    "assistant", 
                    f"✓ Great! I've noted that you want {field}: {selected_option}"
                )
                
                # Clear pending question only when valid
                session_state.pending_question = None
                
                # Stream success update
                if websocket:
                    await websocket.send_json({
                        "type": "choice_accepted",
                        "data": {
                            "field": field,
                            "value": selected_option,
                            "message": f"✓ {field} set to {selected_option}",
                            "timestamp": datetime.now().isoformat()
                        }
                    })
                
                return True  # Valid response
                
            else:
                # Invalid choice, ask again - DON'T clear state
                session_state.add_message(
                    "assistant",
                    f"❌ I didn't understand '{user_input}'. Please choose from: {', '.join(options)}"
                )
                
                # Stream validation error
                if websocket:
                    await websocket.send_json({
                        "type": "choice_invalid",
                        "data": {
                            "user_input": user_input,
                            "valid_options": options,
                            "message": f"Invalid choice. Please select: {', '.join(options)}",
                            "timestamp": datetime.now().isoformat()
                        }
                    })
                
                return False  # Invalid response
        
        elif question_type == "permission":
            # Handle permission response
            permission_granted = user_input.lower().strip() in ['yes', 'y', 'ok', 'allow', 'grant', 'approve']
            
            if permission_granted:
                # Grant permission
                from backend.models.schemas import Permission
                permission = Permission(
                    type=question.get("permission_type"),
                    scope=question.get("scope"),
                    granted=True,
                    timestamp=datetime.now()
                )
                
                session_state.permissions[question.get("scope")] = permission
                
                session_state.add_message(
                    "assistant",
                    f"✓ Permission granted for {question.get('scope')}. Thank you!"
                )
                
                # Stream permission granted
                if websocket:
                    await websocket.send_json({
                        "type": "permission_granted",
                        "data": {
                            "scope": question.get("scope"),
                            "message": f"✓ Permission granted for {question.get('scope')}",
                            "timestamp": datetime.now().isoformat()
                        }
                    })
                
                # PROACTIVE CAPABILITY DETECTION: Auto-call after permissions are granted
                try:
                    logger.info("🔍 Auto-starting capability detection after permission granted...")
                    from backend.gemini.function_registry import function_registry
                    
                    # Call detect_system_capabilities function directly via registry
                    detect_func = function_registry.functions.get("detect_system_capabilities")
                    if detect_func:
                        result = await detect_func(session_state=session_state, websocket=websocket, force_refresh=False)
                        logger.info(f"🔍 Auto capability detection result: {result.get('status', 'unknown')}")
                        
                        if websocket and result.get("status") == "capabilities_detected":
                            caps = result.get("capabilities", {})
                            
                            # Create detailed capability summary for UI
                            capability_lines = []
                            if caps.get("os"):
                                capability_lines.append(f"🖥️  OS: {caps['os']}")
                            if caps.get("python_version"):
                                capability_lines.append(f"🐍 Python: {caps['python_version']}")
                            if caps.get("node_version"):
                                capability_lines.append(f"🟢 Node.js: {caps['node_version']}")
                            if caps.get("npm_version"):
                                capability_lines.append(f"📦 npm: {caps['npm_version']}")
                            if caps.get("docker_installed"):
                                capability_lines.append("🐳 Docker: Available")
                            if caps.get("git_installed"):
                                capability_lines.append("🗂️  Git: Available")
                            if caps.get("available_package_managers"):
                                managers = ", ".join(caps["available_package_managers"])
                                capability_lines.append(f"📋 Package Managers: {managers}")
                            
                            summary_message = "🔍 System capabilities detected automatically:\n" + "\n".join(capability_lines)
                            
                            await websocket.send_json({
                                "type": "capabilities_auto_detected",
                                "data": {
                                    "message": summary_message,
                                    "capabilities": caps,
                                    "timestamp": datetime.now().isoformat()
                                }
                            })
                    else:
                        logger.warning("❌ detect_system_capabilities function not found in registry")
                        
                except Exception as e:
                    logger.error(f"❌ Error in auto capability detection: {e}")
                    # Don't fail the permission grant if capability detection fails
                
            else:
                session_state.add_message(
                    "assistant", 
                    "❌ Permission denied. I'll work with the available permissions."
                )
                
                # Stream permission denied
                if websocket:
                    await websocket.send_json({
                        "type": "permission_denied",
                        "data": {
                            "scope": question.get("scope"),
                            "message": "Permission denied. Working with available permissions.",
                            "timestamp": datetime.now().isoformat()
                        }
                    })
            
            # Clear pending question for both cases
            session_state.pending_question = None
            return True  # Both grant and deny are valid responses
        
        return True  # Default: accept all responses
    
    async def _process_with_gemini(
        self,
        session_state: SessionState,
        websocket=None
    ):
        """Process conversation with Gemini AI."""
        try:
            client = await self._get_gemini_client()
        except ValueError as e:
            # API key not configured
            error_msg = "Gemini API key not configured. Please set GEMINI_API_KEY in backend/.env file"
            logger.error(error_msg)
            if websocket:
                await websocket.send_json({
                    "type": "error",
                    "data": {
                        "message": error_msg,
                        "error": "configuration_error",
                        "help": "Copy backend/.env.example to backend/.env and add your Gemini API key"
                    }
                })
            return
        
        # Format messages for Gemini
        messages = self._format_conversation_history(session_state)
        
        # Get function schemas
        function_schemas = self.function_registry.get_function_schemas()
        
        # Stream completion from Gemini
        accumulated_response = ""
        
        async with client:
            try:
                async for chunk in client.stream_completion(
                    messages=messages,
                    functions=function_schemas,
                    temperature=0.7
                ):
                    # Process chunk
                    result = await self.chunk_parser.process_chunk(
                        chunk,
                        session_state.__dict__,
                        websocket
                    )
                    
                    # Handle text chunks
                    if result["type"] == "text":
                        accumulated_response += result["content"]
                    
                    # Handle function calls
                    elif result["type"] == "function_call":
                        function_call = result["function_call"]
                        
                        # Execute function
                        func_result = await self.function_registry.execute(
                            function_call,
                            session_state,
                            websocket
                        )
                        
                        # Handle function result comprehensively
                        status = func_result.get("status")
                        
                        # Stream function completion status
                        if websocket:
                            await websocket.send_json({
                                "type": "function_result",
                                "data": {
                                    "function_name": function_call.get("name"),
                                    "status": status,
                                    "message": self._get_status_message(status, function_call.get("name")),
                                    "timestamp": datetime.now().isoformat()
                                }
                            })
                        
                        if status == "waiting_for_user" or status == "permission_requested":
                            # Function is waiting for user input - stop processing
                            session_state.waiting_for_user = True
                            
                            # Get the pending question for user-friendly message
                            pending_question = session_state.pending_question or {}
                            question_text = pending_question.get("question", "Waiting for your response...")
                            
                            if websocket:
                                await websocket.send_json({
                                    "type": "permission_request",
                                    "data": {
                                        "question": question_text,
                                        "permission_type": pending_question.get("permission_type", ""),
                                        "scope": pending_question.get("scope", ""),
                                        "reason": pending_question.get("reason", ""),
                                        "message": f"🔐 {question_text}",
                                        "timestamp": datetime.now().isoformat()
                                    }
                                })
                            break
                            
                        elif status == "completed":
                            # Function completed successfully - continue processing
                            if websocket:
                                await websocket.send_json({
                                    "type": "function_completed",
                                    "data": {
                                        "function_name": function_call.get("name"),
                                        "message": f"✓ {function_call.get('name')} completed successfully",
                                        "timestamp": datetime.now().isoformat()
                                    }
                                })
                            # Continue to next chunk
                            
                        elif status == "capabilities_detected" or status == "capabilities_already_detected":
                            # Capabilities detection complete - advance workflow
                            session_state.capabilities_detected = True
                            if websocket:
                                await websocket.send_json({
                                    "type": "capabilities_ready",
                                    "data": {
                                        "message": "✓ System capabilities detected. Ready for next step.",
                                        "next_action": "collect_requirements",
                                        "timestamp": datetime.now().isoformat()
                                    }
                                })
                            
                        elif status == "requirements_updated":
                            # Requirements updated - continue collection or advance
                            if websocket:
                                await websocket.send_json({
                                    "type": "requirements_updated",
                                    "data": {
                                        "message": "✓ Requirements updated successfully",
                                        "timestamp": datetime.now().isoformat()
                                    }
                                })
                            
                        elif status == "execution_completed":
                            if websocket:
                                # Get project details from function result
                                project_name = func_result.get("project_name", "Project")
                                project_path = func_result.get("project_path", "./project")
                                successful_steps = func_result.get("successful_steps", 0)
                                total_steps = func_result.get("total_steps", 0)
                                
                                logger.info(f"📤 Sending project_creation_success to UI: {project_name} ({successful_steps}/{total_steps})")
                                
                                # Create the messages
                                success_message = {
                                    "type": "project_creation_success",
                                    "data": {
                                        "message": f"🎉 {project_name} created successfully!",
                                        "project_name": project_name,
                                        "project_path": project_path,
                                        "successful_steps": successful_steps,
                                        "total_steps": total_steps,
                                        "steps_completed": f"{successful_steps}/{total_steps}",
                                        "success": True,
                                        "next_steps": [
                                            f"Navigate to: {project_path}",
                                            "Install dependencies: npm install", 
                                            "Start development: npm start"
                                        ],
                                        "timestamp": datetime.now().isoformat()
                                    }
                                }
                                
                                completion_message = {
                                    "type": "workflow_complete",
                                    "data": {
                                        "message": f"✅ All done! Your {project_name} project is ready to use.",
                                        "final_state": "COMPLETED",
                                        "timestamp": datetime.now().isoformat()
                                    }
                                }
                                
                                # Try to send messages with fallback to WebSocket manager
                                try:
                                    await websocket.send_json(success_message)
                                    logger.info(f"✅ Direct WebSocket send successful for project_creation_success")
                                except Exception as e:
                                    logger.warning(f"❌ Direct WebSocket failed: {e}, trying WebSocket manager fallback")
                                    # Fallback to WebSocket manager
                                    try:
                                        from backend.app import app
                                        if hasattr(app.state, 'websocket_manager') and session_state.session_id:
                                            await app.state.websocket_manager.send_to_session(session_state.session_id, success_message)
                                            logger.info(f"✅ WebSocket manager fallback successful for project_creation_success")
                                    except Exception as fallback_error:
                                        logger.error(f"❌ WebSocket manager fallback also failed: {fallback_error}")
                                
                                # Also send completion notification
                                logger.info(f"📤 Sending workflow_complete notification to UI")
                                try:
                                    await websocket.send_json(completion_message)
                                    logger.info(f"✅ Direct WebSocket send successful for workflow_complete")
                                except Exception as e:
                                    logger.warning(f"❌ Direct WebSocket failed: {e}, trying WebSocket manager fallback")
                                    try:
                                        from backend.app import app
                                        if hasattr(app.state, 'websocket_manager') and session_state.session_id:
                                            await app.state.websocket_manager.send_to_session(session_state.session_id, completion_message)
                                            logger.info(f"✅ WebSocket manager fallback successful for workflow_complete")
                                    except Exception as fallback_error:
                                        logger.error(f"❌ WebSocket manager fallback also failed: {fallback_error}")
                            else:
                                logger.warning("❌ No websocket available for execution_completed notification")
                            
                            # Transition to COMPLETED state
                            session_state.update_state(ConversationState.COMPLETED)
                            logger.info(f"🏁 State transitioned to COMPLETED")
                        
                        elif status == "plan_generated":
                            # Execution plan ready - Automatically execute it!
                            if websocket:
                                await websocket.send_json({
                                    "type": "plan_ready",
                                    "data": {
                                        "message": "✓ Execution plan generated. Starting project creation automatically...",
                                        "next_action": "execute_plan",
                                        "timestamp": datetime.now().isoformat()
                                    }
                                })
                            
                            # AUTOMATIC EXECUTION: Don't wait for AI, just execute!
                            logger.info("🚀 Automatically executing project creation after plan generation")
                            
                            # Call execute_project_creation directly
                            exec_result = await self.function_registry.execute(
                                {
                                    "name": "execute_project_creation",
                                    "arguments": {"confirm_execution": True}
                                },
                                session_state,
                                websocket
                            )
                            
                            # Handle execution result
                            if exec_result.get("status") == "execution_completed":
                                logger.info("✅ Project creation completed automatically")
                                if websocket:
                                    await websocket.send_json({
                                        "type": "project_created",
                                        "data": {
                                            "message": "✓ Project created successfully!",
                                            "results": exec_result.get("results_summary", {}),
                                            "timestamp": datetime.now().isoformat()
                                        }
                                    })
                            
                        elif status == "execution_completed":
                            # Project execution completed
                            if websocket:
                                await websocket.send_json({
                                    "type": "project_created",
                                    "data": {
                                        "message": "✓ Project created successfully!",
                                        "results": func_result.get("results_summary", {}),
                                        "timestamp": datetime.now().isoformat()
                                    }
                                })
                            
                        elif status == "error" or status == "failed":
                            # Function failed - handle error
                            error_msg = func_result.get("error", "Unknown error occurred")
                            if websocket:
                                await websocket.send_json({
                                    "type": "function_error",
                                    "data": {
                                        "function_name": function_call.get("name"),
                                        "error": error_msg,
                                        "message": f"❌ {function_call.get('name')} failed: {error_msg}",
                                        "timestamp": datetime.now().isoformat()
                                    }
                                })
                            
                        elif status == "needs_retry":
                            # Function needs retry - don't advance state
                            if websocket:
                                await websocket.send_json({
                                    "type": "function_retry",
                                    "data": {
                                        "function_name": function_call.get("name"),
                                        "message": f"♾️ {function_call.get('name')} will be retried",
                                        "timestamp": datetime.now().isoformat()
                                    }
                                })
                        
                        # Store function result in existing function_results list
                        function_result = {
                            "name": function_call.get("name"),
                            "status": status,
                            "timestamp": datetime.now().isoformat(),
                            "result": func_result
                        }
                        session_state.function_results.append(function_result)
                        
                        # Keep only last 10 function results to prevent memory bloat
                        if len(session_state.function_results) > 10:
                            session_state.function_results.pop(0)
                        
                    # Handle completion
                    elif result["finished"]:
                        # Add AI response to conversation history
                        if accumulated_response.strip():
                            session_state.add_message("assistant", accumulated_response)
                        
                        # Check if we should advance workflow based on function results
                        should_transition = await self._should_advance_workflow(session_state, websocket)
                        
                        # Store current state before potential transition
                        old_state = session_state.current_state.value
                        state_changed = False
                        
                        if should_transition:
                            # Stream workflow progression
                            if websocket:
                                await websocket.send_json({
                                    "type": "workflow_advancing",
                                    "data": {
                                        "from_state": session_state.current_state.value,
                                        "message": "🔄 Advancing to next step...",
                                        "timestamp": datetime.now().isoformat()
                                    }
                                })
                            
                            # Advance state machine only if functions are complete
                            self.state_machine.auto_transition(session_state)
                            new_state = session_state.current_state.value
                            state_changed = (old_state != new_state)
                            
                            # Stream state transition
                            if state_changed and websocket:
                                await websocket.send_json({
                                    "type": "state_transitioned",
                                    "data": {
                                        "from_state": old_state,
                                        "to_state": new_state,
                                        "message": f"✅ Moved from {old_state} to {new_state}",
                                        "timestamp": datetime.now().isoformat()
                                    }
                                })
                        else:
                            # Don't transition - functions still working or incomplete
                            if websocket:
                                await websocket.send_json({
                                    "type": "workflow_waiting",
                                    "data": {
                                        "current_state": session_state.current_state.value,
                                        "message": "⏳ Staying in current state - work not complete",
                                        "timestamp": datetime.now().isoformat()
                                    }
                                })
                        
                        # Update iteration count only after successful processing
                        session_state.iteration_count += 1
                        
                        # Stream iteration update
                        if websocket:
                            await websocket.send_json({
                                "type": "iteration_complete",
                                "data": {
                                    "iteration": session_state.iteration_count,
                                    "state": session_state.current_state.value,
                                    "message": f"📝 Iteration {session_state.iteration_count} complete",
                                    "timestamp": datetime.now().isoformat()
                                }
                            })
                        
                        if should_transition and state_changed:
                            await self.session_manager.save_state(session_state.session_id, session_state)
                            await self._process_with_gemini(session_state, websocket)
                        
                        break
                
            except Exception as e:
                logger.error(f"Error in Gemini processing: {e}")
                
                # Add error message
                error_response = f"I encountered an error: {str(e)}. Let me try to help you differently."
                session_state.add_message("assistant", error_response)
                
                if websocket:
                    await websocket.send_json({
                        "type": "ai_message",
                        "data": {"message": error_response}
                    })
    
    async def start_new_conversation(
        self,
        session_id: str,
        websocket=None
    ) -> SessionState:
        """
        Start a new conversation session.
        
        Args:
            session_id: Session identifier
            websocket: WebSocket for real-time updates
            
        Returns:
            New session state
        """
        # Create new session
        session_state = await self.session_manager.create_session(session_id)
        
        # Send initial greeting
        initial_message = """Hi! I'm your AI project bootstrapper. I'll help you create a new development project by asking a few questions about what you want to build.

To get started, I'll need permission to:
1. Read your system information (OS, installed tools)
2. Create files and folders for your project

This helps me suggest the best tools and create a project that works on your system. Is that okay?"""
        
        session_state.add_message("assistant", initial_message)
        
        # Save session
        await self.session_manager.save_state(session_id, session_state)
        
        # Send to UI
        if websocket:
            await websocket.send_json({
                "type": "ai_message",
                "data": {
                    "message": initial_message,
                    "state": session_state.current_state.value
                }
            })
        
        await self._process_with_gemini(session_state, websocket)
        
        # Save updated state after AI processing
        await self.session_manager.save_state(session_id, session_state)
        
        return session_state
    
    async def resume_conversation(
        self,
        session_id: str,
        websocket=None
    ) -> SessionState:
        """
        Resume an existing conversation.
        
        Args:
            session_id: Session identifier
            websocket: WebSocket for real-time updates
            
        Returns:
            Resumed session state
        """
        # Load existing session
        session_state = await self.session_manager.load_state(session_id)
        
        # Send current state to UI
        if websocket:
            await websocket.send_json({
                "type": "session_resumed",
                "data": {
                    "session_id": session_id,
                    "state": session_state.current_state.value,
                    "conversation_history": session_state.conversation_history[-10:],  # Last 10 messages
                    "progress": self.state_machine.get_state_progress(session_state)
                }
            })
        
        return session_state
    
    def _map_project_type_string(self, project_type_input: str) -> 'ProjectType':
        """Map user-friendly project type input to ProjectType enum."""
        from backend.models.schemas import ProjectType
        
        # Normalize input
        input_lower = project_type_input.lower().strip()
        
        # Mapping dictionary for user-friendly inputs
        project_type_mappings = {
            # Web-related
            "web app": ProjectType.FULLSTACK,
            "web application": ProjectType.FULLSTACK,
            "website": ProjectType.FRONTEND,
            "frontend": ProjectType.FRONTEND,
            "web frontend": ProjectType.FRONTEND,
            "react app": ProjectType.FRONTEND,
            "vue app": ProjectType.FRONTEND,
            "angular app": ProjectType.FRONTEND,
            
            # API-related
            "api": ProjectType.WEB_API,
            "web api": ProjectType.WEB_API,
            "rest api": ProjectType.WEB_API,
            "backend": ProjectType.WEB_API,
            "web backend": ProjectType.WEB_API,
            "server": ProjectType.WEB_API,
            
            # Full stack
            "fullstack": ProjectType.FULLSTACK,
            "full stack": ProjectType.FULLSTACK,
            "full-stack": ProjectType.FULLSTACK,
            "fullstack app": ProjectType.FULLSTACK,
            "todo app": ProjectType.FULLSTACK,
            "web app with backend": ProjectType.FULLSTACK,
            
            # CLI
            "cli": ProjectType.CLI,
            "command line": ProjectType.CLI,
            "command line tool": ProjectType.CLI,
            "terminal app": ProjectType.CLI,
            
            # Mobile
            "mobile": ProjectType.MOBILE_APP,
            "mobile app": ProjectType.MOBILE_APP,
            "android app": ProjectType.MOBILE_APP,
            "ios app": ProjectType.MOBILE_APP,
            
            # Library
            "library": ProjectType.LIBRARY,
            "package": ProjectType.LIBRARY,
            "sdk": ProjectType.LIBRARY,
            
            # Microservice
            "microservice": ProjectType.MICROSERVICE,
            "micro service": ProjectType.MICROSERVICE,
            "service": ProjectType.MICROSERVICE,
        }
        
        # Try exact match first
        if input_lower in project_type_mappings:
            logger.info(f"✅ Mapped '{project_type_input}' to {project_type_mappings[input_lower].value}")
            return project_type_mappings[input_lower]
        
        # Try partial matching for better coverage
        for key, project_type in project_type_mappings.items():
            if key in input_lower or input_lower in key:
                logger.info(f"✅ Partial matched '{project_type_input}' to {project_type.value}")
                return project_type
        
        # Try to match directly to enum values
        for project_type in ProjectType:
            if project_type.value.lower() == input_lower:
                logger.info(f"✅ Direct enum matched '{project_type_input}' to {project_type.value}")
                return project_type
        
        # Default fallback
        logger.warning(f"⚠️  No mapping found for '{project_type_input}', defaulting to FULLSTACK")
        return ProjectType.FULLSTACK