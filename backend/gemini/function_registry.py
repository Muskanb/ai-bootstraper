"""Function registry for Gemini function calling."""
import inspect
import asyncio
from typing import Dict, Any, Callable, List, Optional
from datetime import datetime
import logging

from backend.models.schemas import SessionState, ConversationState, ProjectRequirements
from backend.config import settings
from backend.capabilities.detector import capability_detector
from backend.planning.planner import execution_planner
from backend.execution.engine import execution_engine
from backend.verification.tester import project_tester
from backend.reporting.generator import report_generator

logger = logging.getLogger(__name__)


class FunctionRegistry:
    """Registry for functions that Gemini can call."""
    
    def __init__(self):
        """Initialize function registry."""
        self.functions: Dict[str, Callable] = {}
        self.schemas: List[Dict[str, Any]] = []
        self._register_default_functions()
    
    def register(self, name: str, description: str, parameters: Dict[str, Any]):
        """
        Register a function that Gemini can call.
        
        Args:
            name: Function name
            description: Function description
            parameters: JSON Schema parameters
        """
        def decorator(func: Callable):
            self.functions[name] = func
            self.schemas.append({
                "name": name,
                "description": description,
                "parameters": parameters
            })
            return func
        return decorator
    
    async def execute(
        self,
        function_call: Dict[str, Any],
        session_state: SessionState,
        websocket=None
    ) -> Dict[str, Any]:
        """
        Execute a function called by Gemini.
        
        Args:
            function_call: Function call information
            session_state: Current session state
            websocket: Optional WebSocket for UI updates
            
        Returns:
            Function execution result
        """
        func_name = function_call.get("name")
        args = function_call.get("arguments", {})
        
        if func_name not in self.functions:
            error_msg = f"Unknown function: {func_name}"
            logger.error(error_msg)
            return {"error": error_msg, "status": "failed"}
        
        # Notify UI about function execution
        if websocket:
            await websocket.send_json({
                "type": "function_execution_start",
                "data": {
                    "name": func_name,
                    "args": args,
                    "timestamp": datetime.now().isoformat()
                }
            })
        
        try:
            # Check if function needs auto-intervention (instead of blocking)
            auto_call_result = await self._handle_missing_requirements(func_name, session_state, websocket)
            if auto_call_result:
                logger.info(f"🔄 Auto-called missing functions before executing {func_name}")
                # Update session state after auto-intervention
                if websocket:
                    await websocket.send_json({
                        "type": "auto_intervention",
                        "data": {
                            "message": f"Auto-extracted requirements from conversation before executing {func_name}",
                            "timestamp": datetime.now().isoformat()
                        }
                    })
            
            # Now validate function is allowed in current state
            validation_error = self._validate_function_for_state(func_name, session_state)
            if validation_error:
                logger.error(f"🚫 Function {func_name} blocked: {validation_error}")
                return {
                    "status": "blocked_by_state_machine",
                    "error": validation_error,
                    "current_state": session_state.current_state.value,
                    "allowed_functions": self._get_allowed_functions_for_state(session_state.current_state)
                }
            
            func = self.functions[func_name]
            
            # Execute function with session context
            if inspect.iscoroutinefunction(func):
                result = await func(session_state, websocket, **args)
            else:
                result = func(session_state, websocket, **args)
            
            # Store function result in session
            if not hasattr(session_state, 'function_results'):
                session_state.function_results = []
            
            session_state.function_results.append({
                "name": func_name,
                "args": args,
                "result": result,
                "timestamp": datetime.now().isoformat()
            })
            
            # Notify UI about completion
            if websocket:
                await websocket.send_json({
                    "type": "function_execution_complete",
                    "data": {
                        "name": func_name,
                        "result": result,
                        "timestamp": datetime.now().isoformat()
                    }
                })
            
            logger.info(f"Executed function {func_name} successfully")
            return result
            
        except Exception as e:
            error_msg = f"Function execution error in {func_name}: {str(e)}"
            logger.error(error_msg)
            
            # Notify UI about error
            if websocket:
                await websocket.send_json({
                    "type": "function_execution_error",
                    "data": {
                        "name": func_name,
                        "error": error_msg,
                        "timestamp": datetime.now().isoformat()
                    }
                })
            
            return {"error": error_msg, "status": "failed"}
    
    def get_function_schemas(self) -> List[Dict[str, Any]]:
        """Get all registered function schemas."""
        return self.schemas.copy()
    
    def _register_default_functions(self):
        """Register default functions for the AI agent."""
        
        @self.register(
            name="ask_user_preference",
            description="Ask user to select from multiple options",
            parameters={
                "type": "object",
                "properties": {
                    "field": {
                        "type": "string",
                        "description": "Field being asked about (e.g., 'database', 'framework')"
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of available options"
                    },
                    "question": {
                        "type": "string",
                        "description": "Question to ask the user"
                    },
                    "default": {
                        "type": "string",
                        "description": "Default option if user doesn't choose"
                    }
                },
                "required": ["field", "options", "question"]
            }
        )
        async def ask_user_preference(
            session_state: SessionState,
            websocket,
            field: str,
            options: List[str],
            question: str,
            default: Optional[str] = None
        ):
            """Ask user to select from options."""
            # Store question in state for UI to display
            session_state.pending_question = {
                "type": "choice",
                "field": field,
                "options": options,
                "question": question,
                "default": default
            }
            session_state.waiting_for_user = True
            return {"status": "waiting_for_user", "field": field}
        
        @self.register(
            name="update_project_requirements",
            description="Update project requirements based on user input. IMPORTANT: Infer project_type from user descriptions - 'script', 'todo app', 'command line' = 'cli'; 'website', 'web app' = 'web_api'; 'fullstack', 'full stack', 'full application' = 'fullstack'; 'mobile app', 'mobile' = 'mobile_app'. Extract paths like '/full' as folder_path.",
            parameters={
                "type": "object",
                "properties": {
                    "project_type": {"type": "string", "description": "Type of project: 'cli' for scripts/command-line tools, 'web_api' for backend APIs, 'frontend' for web UIs, 'fullstack' for complete web apps, 'mobile_app' for mobile, 'library' for packages"},
                    "project_name": {"type": "string", "description": "Project name"},
                    "folder_path": {"type": "string", "description": "Project folder path"},
                    "database": {"type": "string", "description": "Database choice"},
                    "authentication": {"type": "boolean", "description": "Include authentication"},
                    "testing": {"type": "boolean", "description": "Include testing setup"},
                    "docker": {"type": "boolean", "description": "Include Docker setup"}
                }
            }
        )
        def update_project_requirements(
            session_state: SessionState,
            websocket,
            **kwargs
        ):
            """Update project requirements."""
            logger.info(f"🔄 update_project_requirements called with: {kwargs}")
            
            # CRITICAL: Check for previous failures and prevent repeating same technology
            if session_state.function_results:
                for result in reversed(session_state.function_results):
                    if result.get('status') == 'ai_recovery_needed':
                        failed_command = result.get('failed_command', '')
                        proposed_framework = kwargs.get('framework', '').lower()
                        
                        # Block React Native if it previously failed
                        if 'react-native' in failed_command.lower() and 'react' in proposed_framework:
                            logger.error(f"🚫 BLOCKING React Native - it failed before: {failed_command}")
                            
                            # Force switch to alternative framework
                            project_type_str = session_state.requirements.project_type if isinstance(session_state.requirements.project_type, str) else session_state.requirements.project_type.value if session_state.requirements.project_type else ''
                            if 'mobile' in project_type_str.lower():
                                logger.info("🔄 Auto-switching to Expo for mobile app")
                                kwargs['framework'] = 'Expo'
                                kwargs['language'] = 'javascript'
                            else:
                                logger.info("🔄 Auto-switching to Progressive Web App")
                                kwargs['framework'] = 'React PWA'
                                kwargs['language'] = 'javascript'
                            break
            
            # Auto-detect project type if not explicitly provided but project_name/description suggests CLI
            if 'project_name' in kwargs and 'project_type' not in kwargs:
                project_name = kwargs.get('project_name', '').lower()
                # Look for CLI indicators in project name or if we have language context suggesting CLI
                if any(indicator in project_name for indicator in ['todo', 'cli', 'script', 'command']):
                    # Check if this seems like a CLI project based on context
                    if hasattr(session_state, 'conversation_history'):
                        recent_messages = ' '.join([
                            msg.get('content', '') for msg in session_state.conversation_history[-5:]
                            if isinstance(msg.get('content'), str)
                        ]).lower()
                        
                        if any(term in recent_messages for term in ['python script', 'todo', 'command line', 'cli']):
                            logger.info(f"🎯 Auto-detected CLI project type from context")
                            kwargs['project_type'] = 'cli'
            
            # Update requirements
            for key, value in kwargs.items():
                if hasattr(session_state.requirements, key):
                    # Handle project_type mapping from user-friendly input to enum
                    if key == "project_type" and isinstance(value, str):
                        from backend.models.schemas import ProjectType
                        mapped_value = self._map_project_type_string(value)
                        logger.info(f"Mapped project type '{value}' to {mapped_value}")
                        value = mapped_value
                    setattr(session_state.requirements, key, value)
            
            # Calculate completion percentage
            required_fields = ['project_type', 'language', 'project_name', 'folder_path']
            completed = sum(1 for field in required_fields 
                          if getattr(session_state.requirements, field) is not None)
            session_state.completion_percentage = (completed / len(required_fields)) * 100
            
            return {"status": "updated", "requirements": session_state.requirements.model_dump()}
        
        @self.register(
            name="plan_execution_step",
            description="Add a command execution step to the plan",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to execute"},
                    "description": {"type": "string", "description": "Description of what this step does"},
                    "working_directory": {"type": "string", "description": "Directory to execute in"},
                    "fallback_command": {"type": "string", "description": "Fallback command if main fails"},
                    "expected_output_pattern": {"type": "string", "description": "Expected output pattern"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
                    "requires_permission": {"type": "boolean", "description": "Requires user permission", "default": False}
                },
                "required": ["command", "description"]
            }
        )
        def plan_execution_step(
            session_state: SessionState,
            websocket,
            **kwargs
        ):
            """Add execution step to plan."""
            # Initialize execution plan if not exists
            if session_state.execution_plan is None:
                from backend.models.schemas import ExecutionPlan
                session_state.execution_plan = ExecutionPlan()
            
            # Create execution step
            from backend.models.schemas import ExecutionStep
            step = ExecutionStep(**kwargs)
            
            session_state.execution_plan.steps.append(step)
            session_state.execution_plan.total_steps = len(session_state.execution_plan.steps)
            
            return {
                "status": "step_added", 
                "step_number": len(session_state.execution_plan.steps),
                "step": step.model_dump()
            }
        
        @self.register(
            name="update_conversation_state",
            description="Update the conversation state machine",
            parameters={
                "type": "object",
                "properties": {
                    "new_state": {
                        "type": "string",
                        "enum": [state.value for state in ConversationState],
                        "description": "New conversation state"
                    },
                    "reason": {"type": "string", "description": "Reason for state change"}
                },
                "required": ["new_state"]
            }
        )
        def update_conversation_state(
            session_state: SessionState,
            websocket,
            new_state: str,
            reason: Optional[str] = None
        ):
            """Update conversation state."""
            old_state = session_state.current_state
            session_state.update_state(ConversationState(new_state))
            
            # Log state transition
            if not hasattr(session_state, 'state_history'):
                session_state.state_history = []
            
            session_state.state_history.append({
                "from": old_state.value,
                "to": new_state,
                "reason": reason,
                "timestamp": datetime.now().isoformat()
            })
            
            return {
                "status": "state_updated",
                "old_state": old_state.value,
                "new_state": new_state
            }
        
        @self.register(
            name="request_permission",
            description="Request permission from user for specific action",
            parameters={
                "type": "object",
                "properties": {
                    "permission_type": {
                        "type": "string",
                        "enum": ["global", "folder", "command"],
                        "description": "Type of permission requested"
                    },
                    "scope": {"type": "string", "description": "Scope of permission (path, command, etc.)"},
                    "reason": {"type": "string", "description": "Why this permission is needed"},
                    "required": {"type": "boolean", "description": "Is this permission required to continue"}
                },
                "required": ["permission_type", "scope", "reason"]
            }
        )
        async def request_permission(
            session_state: SessionState,
            websocket,
            permission_type: str,
            scope: str,
            reason: str,
            required: bool = True
        ):
            """Request permission from user."""
            # Store permission request
            session_state.pending_question = {
                "type": "permission",
                "permission_type": permission_type,
                "scope": scope,
                "reason": reason,
                "required": required,
                "question": f"Grant {permission_type} permission for: {scope}?\nReason: {reason}"
            }
            session_state.waiting_for_user = True
            
            return {"status": "permission_requested", "type": permission_type, "scope": scope}
        
        @self.register(
            name="validate_requirements",
            description="Validate if all required project information is collected",
            parameters={
                "type": "object",
                "properties": {
                    "check_completeness": {"type": "boolean", "description": "Check if requirements are complete", "default": True}
                }
            }
        )
        def validate_requirements(
            session_state: SessionState,
            websocket,
            check_completeness: bool = True
        ):
            """Validate project requirements completeness."""
            requirements = session_state.requirements
            missing = []
            
            # Check required fields
            required_fields = {
                "project_type": "Project type",
                "language": "Programming language",
                "project_name": "Project name",
                "folder_path": "Project folder path"
            }
            
            for field, label in required_fields.items():
                if not getattr(requirements, field):
                    missing.append(label)
            
            is_complete = len(missing) == 0
            
            # Update completion percentage
            session_state.completion_percentage = ((len(required_fields) - len(missing)) / len(required_fields)) * 100
            
            return {
                "status": "validated",
                "is_complete": is_complete,
                "missing_fields": missing,
                "completion_percentage": session_state.completion_percentage
            }
        
        @self.register(
            name="detect_system_capabilities",
            description="Detect system capabilities and installed tools",
            parameters={
                "type": "object",
                "properties": {
                    "force_refresh": {"type": "boolean", "description": "Force refresh of cached capabilities", "default": False}
                }
            }
        )
        async def detect_system_capabilities(
            session_state: SessionState,
            websocket,
            force_refresh: bool = False
        ):
            """Detect system capabilities."""
            try:
                capabilities = await capability_detector.detect_all_capabilities(force_refresh)
                
                # Set completion flag to ensure state machine progression
                if capabilities:
                    # Create a new capabilities object with detection_completed=True to avoid Pydantic validation issues
                    caps_dict = capabilities.model_dump()
                    caps_dict['detection_completed'] = True
                    
                    # Import the model here to avoid circular imports
                    from backend.models.schemas import SystemCapability
                    capabilities = SystemCapability(**caps_dict)
                
                session_state.capabilities = capabilities
                
                return {
                    "status": "capabilities_detected",
                    "capabilities": capabilities.model_dump()
                }
            except Exception as e:
                logger.error(f"❌ Exception in detect_system_capabilities: {e}", exc_info=True)
                return {
                    "status": "detection_failed",
                    "error": str(e)
                }
        
        @self.register(
            name="validate_requirements_against_capabilities",
            description="Validate user requirements against system capabilities and auto-correct if needed",
            parameters={
                "type": "object",
                "properties": {
                    "auto_correct": {"type": "boolean", "description": "Automatically adjust requirements based on available tools", "default": True},
                    "suggest_alternatives": {"type": "boolean", "description": "Suggest alternative tech stacks when tools are missing", "default": True}
                }
            }
        )
        async def validate_requirements_against_capabilities(
            session_state: SessionState,
            websocket,
            auto_correct: bool = True,
            suggest_alternatives: bool = True
        ):
            """Validate requirements against capabilities and provide auto-correction."""
            try:
                if not session_state.requirements:
                    return {
                        "status": "validation_failed",
                        "error": "No requirements to validate"
                    }
                
                if not session_state.capabilities:
                    return {
                        "status": "validation_failed", 
                        "error": "System capabilities not detected. Please run detect_system_capabilities first."
                    }
                
                requirements = session_state.requirements
                capabilities = session_state.capabilities
                validation_results = []
                corrections_made = []
                
                # INTELLIGENT CAPABILITY ANALYSIS
                requested_lang = requirements.language.lower() if requirements.language else None
                
                # Extract available runtimes from capabilities
                available_runtimes = []
                runtime_versions = {}
                
                if capabilities.python_version:
                    available_runtimes.extend(["python", "python3"])
                    runtime_versions["python"] = capabilities.python_version
                    
                if capabilities.node_version:
                    available_runtimes.extend(["javascript", "node", "nodejs"])
                    runtime_versions["node"] = capabilities.node_version
                    
                # Check available_runtimes dict for other languages
                if capabilities.available_runtimes:
                    for runtime, version in capabilities.available_runtimes.items():
                        if runtime not in runtime_versions:
                            available_runtimes.append(runtime)
                            runtime_versions[runtime] = version
                
                # SMART VALIDATION & AUTO-CORRECTION
                if requested_lang and requested_lang not in available_runtimes:
                    validation_results.append({
                        "issue": f"Requested language '{requested_lang}' not available",
                        "available_alternatives": list(runtime_versions.keys()),
                        "severity": "high"
                    })
                    
                    if auto_correct and runtime_versions:
                        # INTELLIGENT ALTERNATIVE SELECTION
                        project_type = requirements.project_type if requirements.project_type else "web_api"
                        
                        # Smart recommendations based on project type and available tools
                        if project_type in ["web_api", "fullstack"]:
                            if "python" in runtime_versions and float(runtime_versions["python"].split('.')[1]) >= 10:
                                new_lang = "python"
                                reason = f"Python {runtime_versions['python']} excellent for APIs with FastAPI"
                            elif "node" in runtime_versions:
                                new_lang = "javascript"  
                                reason = f"Node.js {runtime_versions['node']} great for web services"
                            else:
                                new_lang = list(runtime_versions.keys())[0]
                                reason = f"Using available {new_lang} {runtime_versions[new_lang]}"
                        
                        elif project_type == "cli":
                            if "go" in runtime_versions:
                                new_lang = "go"
                                reason = f"Go {runtime_versions['go']} perfect for CLI tools - fast compilation"
                            elif "python" in runtime_versions:
                                new_lang = "python"
                                reason = f"Python {runtime_versions['python']} excellent CLI libraries"
                            else:
                                new_lang = list(runtime_versions.keys())[0]
                                reason = f"Using available {new_lang}"
                                
                        elif project_type == "mobile":
                            if "swift" in runtime_versions:
                                new_lang = "swift"
                                reason = f"Swift {runtime_versions['swift']} native iOS development"
                            elif "java" in runtime_versions:
                                new_lang = "java" 
                                reason = f"Java {runtime_versions['java']} for Android development"
                            else:
                                new_lang = "javascript"  # React Native fallback
                                reason = "JavaScript for cross-platform React Native"
                        else:
                            # Default intelligent selection
                            new_lang = "python" if "python" in runtime_versions else list(runtime_versions.keys())[0]
                            reason = f"Recommended {new_lang} for versatility"
                        
                        requirements.language = new_lang
                        corrections_made.append(f"Upgraded from {requested_lang} to {new_lang}: {reason}")
                
                # Note: Let AI dynamically determine project type and language compatibility
                # instead of hardcoding compatibility rules
                
                # Set validation completion flag to ensure state machine progression
                session_state.validation_completed = True
                
                # CRITICAL: Auto-transition after validation to prevent validation loops
                from backend.core.state_machine import ConversationState, ConversationStateMachine
                state_machine = ConversationStateMachine()
                
                # Try auto-transition to next state (PLANNING or SUMMARY_CONFIRMATION)
                old_state = session_state.current_state
                next_state = state_machine.auto_transition(session_state)
                if next_state and next_state != old_state:
                    logger.info(f"🔄 Auto-transitioned from {old_state.value} to {next_state.value} after validation")
                    
                    if websocket:
                        await websocket.send_json({
                            "type": "state_update",
                            "data": {
                                "current_state": next_state.value,
                                "message": f"✅ Validation complete - advancing to {next_state.value}",
                                "timestamp": datetime.now().isoformat()
                            }
                        })
                
                return {
                    "status": "validation_complete", 
                    "validation_results": validation_results,
                    "corrections_made": corrections_made,
                    "updated_requirements": requirements.model_dump(),
                    "available_runtimes": available_runtimes,
                    "recommendations": "Use AI to generate dynamic recommendations based on available tools",
                    "state_transitioned": next_state.value if next_state else old_state.value
                }
                
            except Exception as e:
                logger.error(f"Requirements validation failed: {e}")
                return {
                    "status": "validation_failed",
                    "error": str(e)
                }
        
        @self.register(
            name="confirm_project_creation",
            description="Confirm user wants to proceed with project creation based on their response",
            parameters={
                "type": "object",
                "properties": {
                    "user_confirmed": {"type": "boolean", "description": "True if user confirmed, False if they want to modify"},
                    "confirmation_message": {"type": "string", "description": "Confirmation message to show user"}
                },
                "required": ["user_confirmed", "confirmation_message"]
            }
        )
        async def confirm_project_creation(
            session_state: SessionState,
            websocket,
            user_confirmed: bool,
            confirmation_message: str
        ):
            """Handle user confirmation for project creation."""
            try:
                if user_confirmed:
                    # User confirmed - set flag for state transition
                    session_state.user_confirmed_project = True
                    
                    # Transition to PLANNING state automatically
                    from backend.core.state_machine import ConversationState
                    session_state.update_state(ConversationState.PLANNING)
                    
                    if websocket:
                        await websocket.send_json({
                            "type": "project_confirmed",
                            "data": {
                                "message": confirmation_message,
                                "state": "PLANNING",
                                "timestamp": datetime.now().isoformat()
                            }
                        })
                    
                    return {
                        "status": "confirmed",
                        "message": confirmation_message,
                        "next_state": "PLANNING"
                    }
                else:
                    # User wants to modify
                    session_state.user_confirmed_project = False
                    
                    if websocket:
                        await websocket.send_json({
                            "type": "project_modification_requested",
                            "data": {
                                "message": "User wants to modify the project requirements",
                                "timestamp": datetime.now().isoformat()
                            }
                        })
                    
                    return {
                        "status": "modification_requested",
                        "message": "User wants to modify requirements. Please ask what they'd like to change."
                    }
                    
            except Exception as e:
                logger.error(f"Error in confirm_project_creation: {e}")
                return {
                    "status": "confirmation_failed",
                    "error": str(e)
                }
        
        @self.register(
            name="generate_execution_plan",
            description="Generate execution plan based on requirements and capabilities",
            parameters={
                "type": "object",
                "properties": {
                    "validate_first": {"type": "boolean", "description": "Validate requirements before planning", "default": True}
                }
            }
        )
        async def generate_execution_plan(
            session_state: SessionState,
            websocket,
            validate_first: bool = True
        ):
            """Generate execution plan."""
            if not session_state.requirements:
                return {
                    "status": "planning_failed",
                    "error": "Project requirements missing. Please update requirements first."
                }
            
            if not session_state.capabilities:
                return {
                    "status": "planning_failed", 
                    "error": "System capabilities not detected. Please run detect_system_capabilities first."
                }
            
            try:
                logger.info("Starting execution plan generation...")
                plan = await execution_planner.generate_execution_plan(
                    session_state.requirements,
                    session_state.capabilities
                )
                logger.info(f"Plan generated successfully with {len(plan.steps)} steps")
                session_state.execution_plan = plan
                
                return {
                    "status": "plan_generated",
                    "plan": plan.model_dump(mode='json'),
                    "steps_count": len(plan.steps)
                }
            except Exception as e:
                logger.error(f"Exception in execution plan generation: {e}", exc_info=True)
                return {
                    "status": "planning_failed",
                    "error": str(e)
                }
        
        @self.register(
            name="create_project_with_steps",
            description="Create a project by providing detailed execution steps that will be executed immediately",
            parameters={
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "description": "Detailed execution steps to create the project (commands, file creations, etc.)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", "description": "Shell command to execute or 'CREATE_FILE' for file creation"},
                                "description": {"type": "string", "description": "What this command/action does"},
                                "working_directory": {"type": "string", "description": "Directory to run command in", "default": "."},
                                "file_path": {"type": "string", "description": "For CREATE_FILE: relative path of file to create"},
                                "file_content": {"type": "string", "description": "For CREATE_FILE: content of the file"}
                            },
                            "required": ["command", "description"]
                        }
                    }
                },
                "required": ["steps"]
            }
        )
        async def create_project_with_steps(
            session_state: SessionState,
            websocket,
            steps: List[Dict[str, Any]]
        ):
            """Create project directly from Gemini-provided steps."""
            
            # CRITICAL: Check for technology switch BEFORE executing any steps
            if getattr(session_state, 'should_regenerate_steps', False):
                logger.info("🔄 Technology switched - regenerating steps with new technology")
                
                if websocket:
                    await websocket.send_json({
                        "type": "step_regeneration_notice",
                        "data": {
                            "message": f"🔄 Technology switched to {session_state.requirements.language} + {session_state.requirements.framework}",
                            "note": "Generating new project steps for the updated technology stack...",
                            "action": "regenerating_steps"
                        }
                    })
                
                # Clear the flag first
                session_state.should_regenerate_steps = False
                
                # Ask AI to regenerate steps for the new technology
                try:
                    logger.info("🤖 Asking AI to regenerate steps for new technology...")
                    
                    tech = session_state.requirements.language if session_state.requirements and session_state.requirements.language else "JavaScript"
                    framework = session_state.requirements.framework if session_state.requirements and session_state.requirements.framework else ""
                    project_name = session_state.requirements.project_name if session_state.requirements and session_state.requirements.project_name else "project"
                    folder_path = session_state.requirements.folder_path if session_state.requirements and session_state.requirements.folder_path else f"./{project_name}"
                    project_type = session_state.requirements.project_type if session_state.requirements and session_state.requirements.project_type else "application"
                    
                    # Call AI to regenerate steps using the correct function
                    requirements_summary = f"Create a {project_type} project using {tech} + {framework}, named '{project_name}' in folder '{folder_path}'"
                    
                    regeneration_result = await self.functions["ai_generate_project_steps"](
                        session_state, websocket, requirements_summary=requirements_summary
                    )
                    
                    if regeneration_result.get("status") in ["steps_generated", "steps_generated_text"]:
                        if regeneration_result.get("steps"):
                            new_steps = regeneration_result["steps"]
                            logger.info(f"✅ AI regenerated {len(new_steps)} steps for {tech} + {framework}")
                        else:
                            logger.warning("⚠️ AI generated text response, attempting to parse manually")
                            # For now, use empty steps and let the system continue with defaults
                            new_steps = []
                        
                        if new_steps:  # Only proceed if we have valid steps
                            logger.info(f"🔄 Replacing {len(steps)} old React Native steps with {len(new_steps)} new Flutter steps")
                            
                            if websocket:
                                await websocket.send_json({
                                    "type": "steps_regenerated",
                                    "data": {
                                        "message": f"✅ AI generated {len(new_steps)} new steps for {tech} + {framework}",
                                        "old_steps": len(steps),
                                        "new_steps": len(new_steps),
                                        "technology": f"{tech} + {framework}"
                                    }
                                })
                            
                            # Use the AI-generated steps - CRITICAL FIX
                            steps = new_steps
                        else:
                            logger.warning("⚠️ No new steps generated, continuing with original steps")
                    else:
                        logger.warning("⚠️ AI step regeneration failed, using original steps")
                        if websocket:
                            await websocket.send_json({
                                "type": "step_regeneration_failed",
                                "data": {
                                    "message": "⚠️ AI step regeneration failed, continuing with original steps",
                                    "reason": regeneration_result.get("error", "Unknown error")
                                }
                            })
                
                except Exception as e:
                    logger.error(f"❌ Error during AI step regeneration: {e}")
                    if websocket:
                        await websocket.send_json({
                            "type": "step_regeneration_error", 
                            "data": {
                                "message": f"❌ Step regeneration error: {str(e)}",
                                "fallback": "Continuing with original steps"
                            }
                        })
            
            async def safe_send_websocket_message(message_data: dict, session_id: str, websocket_ref=None):
                """Send WebSocket message with fallback to session manager."""
                try:
                    # Try direct WebSocket first
                    if websocket_ref:
                        await websocket_ref.send_json(message_data)
                        logger.debug(f"✅ Sent via direct WebSocket: {message_data['type']}")
                        return True
                except Exception as e:
                    logger.warning(f"⚠️ Direct WebSocket failed ({e}), trying WebSocket manager...")
                
                # Fallback to WebSocket manager
                try:
                    # Access the WebSocket manager from the app state
                    from backend.app import app
                    websocket_manager = app.state.websocket_manager
                    await websocket_manager.send_to_session(session_id, message_data)
                    logger.debug(f"✅ Sent via WebSocket manager: {message_data['type']}")
                    return True
                except Exception as e:
                    logger.error(f"❌ Both WebSocket methods failed: {e}")
                    return False
            try:
                logger.info(f"🚀 Creating project with {len(steps)} AI-generated steps")
                
                # Get project details with safety checks - PRESERVE USER INPUT
                project_name = session_state.requirements.project_name or "default-project"
                project_type = session_state.requirements.project_type or "web_app"  
                folder_path = session_state.requirements.folder_path or f"./{project_name}"
                
                # LOG PARAMETER PRESERVATION FOR DEBUGGING
                logger.info(f"📝 Project parameters preserved: name='{project_name}', type='{project_type}', path='{folder_path}'")
                session_id = session_state.session_id
                
                # Send initial project creation start notification to UI with resilient WebSocket
                message_data = {
                    "type": "project_creation_started",
                    "data": {
                        "message": f"🚀 Starting creation of {project_name}...",
                        "project_name": project_name,
                        "project_type": project_type,
                        "total_steps": len(steps),
                        "ai_generated": True,
                        "timestamp": datetime.now().isoformat()
                    }
                }
                
                success = await safe_send_websocket_message(message_data, session_id, websocket)
                if success:
                    logger.info("✅ Successfully sent project_creation_started")
                else:
                    logger.warning("❌ Failed to send project_creation_started via all methods")
                
                # Use folder_path if provided, otherwise create in current directory
                if folder_path:
                    project_path = folder_path
                else:
                    project_path = f"./{project_name}"
                
                logger.info(f"📂 Project will be created at: {project_path}")
                logger.info(f"📋 Requirements: name={project_name}, folder={folder_path}, type={project_type}")
                
                # More flexible validation - allow creation even with minimal info
                if project_name == "my-project":
                    logger.warning("⚠️ Using default project name, but proceeding with creation")
                
                # Set default type if missing
                if not session_state.requirements.project_type:
                    session_state.requirements.project_type = project_type
                    logger.info(f"🔧 Set default project type: {project_type}")
                results = []
                failed_steps = []
                
                # Create project directory first
                import os
                if not os.path.exists(project_path):
                    os.makedirs(project_path, exist_ok=True)
                    logger.info(f"📁 Created project directory: {project_path}")
                    
                    # Notify UI about directory creation using safe WebSocket
                    await safe_send_websocket_message({
                        "type": "directory_created",
                        "data": {
                            "message": f"📁 Created project directory: {project_path}",
                            "path": project_path,
                            "timestamp": datetime.now().isoformat()
                        }
                    }, session_id, websocket)
                
                # Send project creation start notification using safe WebSocket
                await safe_send_websocket_message({
                    "type": "project_creation_start",
                    "data": {
                        "message": f"🚀 Starting project creation with {len(steps)} steps",
                        "total_steps": len(steps),
                        "project_name": session_state.requirements.project_name,
                        "project_path": project_path,
                        "timestamp": datetime.now().isoformat()
                    }
                }, session_id, websocket)
                i =0
                attempts = 0
                while i < len(steps) and attempts !=5:
                    step_num = i
                    step_data = steps[i]
                    
                    # CRITICAL: Check for technology switch mid-execution and regenerate steps
                    if getattr(session_state, 'should_regenerate_steps', False):
                        logger.info(f"🔄 Technology switch detected during step {step_num}, regenerating steps for new technology")
                        
                        # Clear the flag first
                        session_state.should_regenerate_steps = False
                        
                        # Regenerate steps using same logic as beginning of function
                        try:
                            tech = session_state.requirements.language if session_state.requirements and session_state.requirements.language else "JavaScript"
                            framework = session_state.requirements.framework if session_state.requirements and session_state.requirements.framework else ""
                            project_name = session_state.requirements.project_name if session_state.requirements and session_state.requirements.project_name else "project"
                            folder_path = session_state.requirements.folder_path if session_state.requirements and session_state.requirements.folder_path else f"./{project_name}"
                            project_type = session_state.requirements.project_type if session_state.requirements and session_state.requirements.project_type else "application"
                            
                            requirements_summary = f"Create a {project_type} project using {tech} + {framework}, named '{project_name}' in folder '{folder_path}'"
                            
                            logger.info(f"🤖 Regenerating steps mid-execution for {tech} + {framework}")
                            regeneration_result = await self.functions["ai_generate_project_steps"](
                                session_state, websocket, requirements_summary=requirements_summary
                            )
                            
                            if regeneration_result.get("status") in ["steps_generated", "steps_generated_text"]:
                                if regeneration_result.get("steps"):
                                    new_steps = regeneration_result["steps"]
                                    logger.info(f"✅ Mid-execution regenerated {len(new_steps)} steps for {tech} + {framework}")
                                    logger.info(f"🔄 BREAKING OUT to restart with new Flutter steps: {[s['description'] for s in new_steps[:3]]}...")
                                    
                                    if websocket:
                                        await websocket.send_json({
                                            "type": "steps_regenerated_mid_execution",
                                            "data": {
                                                "message": f"✅ Generated {len(new_steps)} new steps for {tech} + {framework}",
                                                "interrupted_at_step": step_num,
                                                "new_steps_count": len(new_steps),
                                                "technology": f"{tech} + {framework}",
                                                "action": "restarting_execution"
                                            }
                                        })
                                    
                                    # CRITICAL FIX: Replace steps array and signal to restart
                                    i = -1
                                    steps = new_steps
                                    attempts+=1
                                    continue
                                    
                            logger.warning("⚠️ Mid-execution step regeneration failed, stopping execution")
                            return {
                                "status": "regenerate_steps_failed",
                                "message": f"Failed to regenerate steps for {tech} + {framework}",
                                "interrupted_at_step": step_num
                            }
                            
                        except Exception as e:
                            logger.error(f"❌ Error during mid-execution step regeneration: {e}")
                            return {
                                "status": "regenerate_steps_error", 
                                "error": str(e),
                                "interrupted_at_step": step_num
                            }
                    
                    try:
                        # Send step start notification using safe WebSocket
                        await safe_send_websocket_message({
                            "type": "step_start",
                            "data": {
                                "step": step_num,
                                "total": len(steps),
                                "description": step_data["description"],
                                "command": step_data["command"],
                                "message": f"⚙️ Step {step_num}/{len(steps)}: {step_data['description']}",
                                "progress_percentage": ((step_num - 1) / len(steps)) * 100,
                                "timestamp": datetime.now().isoformat()
                            }
                        }, session_id, websocket)
                        
                        # Execute step
                        if step_data["command"] == "CREATE_FILE":
                            # Handle file creation
                            file_path = step_data["file_path"]
                            file_content = step_data.get("file_content", "")
                            
                            # If no file content provided, use AI to generate it
                            if not file_content or file_content.strip() == "":
                                try:
                                    logger.info(f"🤖 Generating content for {file_path} using AI...")
                                    
                                    # Create context for AI generation
                                    project_context = f"Creating a {project_type} project named '{project_name}'"
                                    if session_state.requirements.language:
                                        project_context += f" using {session_state.requirements.language}"
                                    if session_state.requirements.framework:
                                        project_context += f" with {session_state.requirements.framework}"
                                    if session_state.requirements.database:
                                        project_context += f" and {session_state.requirements.database} database"
                                    
                                    file_purpose = step_data.get("description", f"File for {file_path}")
                                    
                                    # Call AI to generate file content
                                    from backend.gemini.streaming_client import GeminiStreamingClient
                                    
                                    ai_context = f"""
Generate file content for: {file_path}

Purpose: {file_purpose}
Project Context: {project_context}

Project Details:
- Type: {session_state.requirements.project_type or 'general'}
- Language: {session_state.requirements.language or 'JavaScript'}
- Framework: {session_state.requirements.framework or 'generic'}
- Name: {session_state.requirements.project_name or 'MyProject'}
- Database: {session_state.requirements.database or 'none'}
- Authentication: {session_state.requirements.authentication}
- Testing: {session_state.requirements.testing}

Generate appropriate, working file content that follows best practices.
Return ONLY the file content, no explanations, no markdown code blocks.
"""

                                    messages = [{"role": "user", "content": ai_context}]
                                    
                                    async with GeminiStreamingClient() as client:
                                        ai_result = await client.complete(messages, temperature=0.2)
                                        
                                        if "candidates" in ai_result and ai_result["candidates"]:
                                            ai_content = ai_result["candidates"][0]["content"]["parts"][0]["text"]
                                            
                                            # Clean up markdown formatting
                                            import re
                                            if ai_content.startswith('```'):
                                                ai_content = re.sub(r'^```[a-zA-Z]*\s*', '', ai_content)
                                                ai_content = re.sub(r'\s*```$', '', ai_content)
                                            
                                            file_content = ai_content.strip()
                                            logger.info(f"✅ AI generated {len(file_content)} characters for {file_path}")
                                            
                                            # Stream AI generation info to UI
                                            if websocket:
                                                await websocket.send_json({
                                                    "type": "ai_file_generation",
                                                    "data": {
                                                        "file_path": file_path,
                                                        "content_length": len(file_content),
                                                        "generated_by": "AI"
                                                    }
                                                })
                                        else:
                                            logger.warning(f"AI failed to generate content for {file_path}, using placeholder")
                                            file_content = f"// Generated file: {file_path}\n// TODO: Add implementation\n"
                                            
                                except Exception as e:
                                    logger.error(f"Error generating AI content for {file_path}: {e}")
                                    file_content = f"// Generated file: {file_path}\n// Error during AI generation: {str(e)}\n"
                            
                            # Make relative to project path
                            if not file_path.startswith("/"):
                                full_path = os.path.join(project_path, file_path)
                            else:
                                full_path = file_path
                            
                            # Create directory if needed
                            dir_path = os.path.dirname(full_path)
                            if dir_path and dir_path != ".":  # Only create if there's a directory to create
                                os.makedirs(dir_path, exist_ok=True)
                            
                            # Write file
                            with open(full_path, 'w') as f:
                                f.write(file_content)
                            
                            result = {
                                "success": True,
                                "output": f"Created {file_path} ({len(file_content)} chars)",
                                "command": f"CREATE_FILE {file_path}"
                            }
                            logger.info(f"📄 Created file: {file_path}")
                            
                            # Stream file creation details to UI
                            if websocket:
                                await websocket.send_json({
                                    "type": "file_created",
                                    "data": {
                                        "step": step_num,
                                        "file_path": file_path,
                                        "full_path": full_path,
                                        "file_size": len(file_content),
                                        "message": f"📄 Created {file_path} ({len(file_content)} characters)",
                                        "timestamp": datetime.now().isoformat()
                                    }
                                })
                        else:
                            # Execute shell command
                            import subprocess
                            import os
                            work_dir = step_data.get("working_directory", project_path)
                            
                            # Replace project placeholders
                            command = step_data["command"].replace("{project_path}", project_path)
                            command = command.replace("{project_name}", session_state.requirements.project_name or "project")
                            
                            if not os.path.exists(work_dir):
                                try:
                                    os.makedirs(work_dir, exist_ok=True)
                                    logger.info(f"📁 Created directory: {work_dir}")
                                except Exception as e:
                                    logger.error(f"❌ Failed to create directory {work_dir}: {e}")
                                    failed_steps.append({
                                        "step": step_num,
                                        "command": command,
                                        "error": f"Failed to create directory {work_dir}: {e}"
                                    })
                                    continue
                            
                            logger.info(f"⚙️ Executing: {command} in {work_dir}")
                            
                            # Stream command execution start to UI
                            if websocket:
                                await websocket.send_json({
                                    "type": "command_executing",
                                    "data": {
                                        "step": step_num,
                                        "command": command,
                                        "working_directory": work_dir,
                                        "message": f"⚙️ Executing: {command}",
                                        "timestamp": datetime.now().isoformat()
                                    }
                                })
                            
                            proc = subprocess.run(
                                command,
                                shell=True,
                                cwd=work_dir,
                                capture_output=True,
                                text=True,
                                timeout=120
                            )
                            
                            result = {
                                "success": proc.returncode == 0,
                                "output": proc.stdout,
                                "error": proc.stderr,
                                "return_code": proc.returncode,
                                "command": command
                            }
                            
                            if proc.returncode == 0:
                                logger.info(f"✅ Command succeeded: {command}")
                                
                                # Stream success to UI
                                if websocket:
                                    await websocket.send_json({
                                        "type": "command_success",
                                        "data": {
                                            "step": step_num,
                                            "command": command,
                                            "output": proc.stdout[:500] if proc.stdout else "",  # Limit output size
                                            "message": f"✅ Command succeeded: {command}",
                                            "duration": "completed",
                                            "timestamp": datetime.now().isoformat()
                                        }
                                    })
                            else:
                                logger.warning(f"❌ Command failed: {command} - {proc.stderr}")
                                
                                # Stream failure to UI  
                                if websocket:
                                    await websocket.send_json({
                                        "type": "command_failed",
                                        "data": {
                                            "step": step_num,
                                            "command": command,
                                            "error": proc.stderr[:500] if proc.stderr else "",
                                            "message": f"❌ Command failed: {command}",
                                            "return_code": proc.returncode,
                                            "timestamp": datetime.now().isoformat()
                                        }
                                    })
                        
                        results.append(result)
                        
                        if websocket:
                            # Calculate current progress
                            progress_percentage = (step_num / len(steps)) * 100
                            completed_steps = sum(1 for r in results if r["success"])
                            
                            await websocket.send_json({
                                "type": "step_complete",
                                "data": {
                                    "step": step_num,
                                    "total": len(steps),
                                    "success": result["success"],
                                    "message": f"{'✅' if result['success'] else '❌'} Step {step_num}/{len(steps)} completed: {step_data['description']}",
                                    "progress_percentage": progress_percentage,
                                    "completed_steps": completed_steps,
                                    "remaining_steps": len(steps) - step_num,
                                    "output": result.get("output", "")[:300],
                                    "error": result.get("error", "")[:200] if not result["success"] else None,
                                    "timestamp": datetime.now().isoformat()
                                }
                            })
                            
                            # Send progress update every 25% or at key milestones
                            if progress_percentage % 25 == 0 or step_num == len(steps):
                                await websocket.send_json({
                                    "type": "progress_milestone",
                                    "data": {
                                        "progress_percentage": progress_percentage,
                                        "completed_steps": completed_steps,
                                        "total_steps": len(steps),
                                        "milestone_message": f"📊 {progress_percentage:.0f}% complete - {completed_steps}/{len(steps)} steps done",
                                        "timestamp": datetime.now().isoformat()
                                    }
                                })
                        
                        if not result["success"]:
                            # AI-POWERED ERROR RECOVERY: Try to find and execute alternative
                            logger.warning(f"💭 Command failed, trying AI-powered recovery...")
                            
                            # Get AI-powered alternative using the new function
                            alternative_result = await suggest_alternative_command(
                                session_state,
                                websocket, 
                                failed_command=command,
                                error_message=result["error"],
                                project_context=f"Creating {session_state.requirements.project_type} project: {step_data['description']}",
                                attempt_number=1
                            )
                            
                            if websocket:
                                await websocket.send_json({
                                    "type": "attempting_recovery",
                                    "data": {
                                        "step": step_num,
                                        "failed_command": command,
                                        "error": result["error"][:200],
                                        "recovery_status": alternative_result["status"]
                                    }
                                })
                            
                            # Handle the new AI-powered recovery flow
                            if alternative_result.get("status") == "alternative_found":
                                # AI found an alternative command, try it
                                alternative_cmd = alternative_result["alternative_command"]
                                logger.info(f"🔄 Trying AI alternative: {alternative_cmd}")
                                
                                try:
                                    alt_proc = subprocess.run(
                                        alternative_cmd,
                                        shell=True,
                                        cwd=work_dir,
                                        capture_output=True,
                                        text=True,
                                        timeout=120
                                    )
                                    
                                    if alt_proc.returncode == 0:
                                        logger.info(f"✅ AI alternative succeeded: {alternative_cmd}")
                                        # Update result to show success
                                        result = {
                                            "success": True,
                                            "output": alt_proc.stdout,
                                            "error": None,
                                            "return_code": 0,
                                            "command": alternative_cmd,
                                            "is_ai_alternative": True,
                                            "original_command": command,
                                            "recovery_reason": alternative_result["reason"]
                                        }
                                        
                                        if websocket:
                                            await websocket.send_json({
                                                "type": "ai_recovery_successful",
                                                "data": {
                                                    "step": step_num,
                                                    "alternative_command": alternative_cmd,
                                                    "reason": alternative_result["reason"],
                                                    "message": f"✅ AI alternative worked: {alternative_cmd}"
                                                }
                                            })
                                    else:
                                        logger.warning(f"❌ AI alternative also failed: {alternative_cmd}")
                                        # Try technology switch
                                        await self._try_technology_switch(
                                            session_state, websocket, command, result["error"], 
                                            step_data["description"], step_num
                                        )
                                        
                                except Exception as e:
                                    logger.error(f"Error executing AI alternative: {e}")
                                    await self._try_technology_switch(
                                        session_state, websocket, command, str(e),
                                        step_data["description"], step_num
                                    )
                                    
                            elif alternative_result.get("status") in ["tech_switch_needed", "max_attempts_reached", "no_alternative"]:
                                # AI says we need to switch technologies
                                logger.warning(f"🔄 AI recommends technology switch: {alternative_result.get('message')}")
                                await self._try_technology_switch(
                                    session_state, websocket, command, result["error"],
                                    step_data["description"], step_num
                                )
                                break  # Stop current execution, let AI regenerate with new tech
                                
                            else:
                                # Unknown status, mark as failed
                                failed_steps.append(step_num)
                        
                    except Exception as e:
                        failed_steps.append(step_num)
                        logger.error(f"❌ Step {step_num} failed: {e}")
                        results.append({
                            "success": False,
                            "error": str(e),
                            "command": step_data["command"]
                        })
                
                    i = i+ 1

                # Check if we need to regenerate steps due to technology switch
                if session_state.should_regenerate_steps:
                    logger.info("🔄 Technology switch occurred - steps need regeneration")
                    return {
                        "status": "regenerate_steps_needed",
                        "message": f"Technology switched to {session_state.requirements.language} + {session_state.requirements.framework}",
                        "new_language": session_state.requirements.language,
                        "new_framework": session_state.requirements.framework,
                        "project_name": session_state.requirements.project_name,
                        "project_path": project_path,
                        "reason": "Technology switch requires new project steps"
                    }
                
                # Check if AI recovery is needed for any failed steps
                recovery_needed = any(result.get("ai_recovery_suggested", False) for result in results)
                
                if recovery_needed:
                    logger.warning("🤖 AI recovery needed - returning control to AI for alternative approach")
                    
                    # Find the recovery info from the failed step
                    recovery_info = None
                    for result in results:
                        if result.get("ai_recovery_suggested", False):
                            recovery_info = result.get("recovery_info", {})
                            break
                    
                    return {
                        "status": "ai_recovery_needed",
                        "message": "Command failed. AI should analyze available capabilities and provide alternative approach.",
                        "failed_command": recovery_info.get("failed_command", "Unknown") if recovery_info else "Unknown",
                        "error_details": recovery_info.get("error_message", "Command execution failed") if recovery_info else "Command execution failed", 
                        "available_capabilities": recovery_info.get("available_capabilities", []) if recovery_info else [],
                        "project_context": recovery_info.get("project_context", f"Creating {session_state.requirements.project_type} project") if recovery_info else f"Creating {session_state.requirements.project_type} project",
                        "recovery_suggestion": "AI should either: 1) Generate corrected steps, 2) Switch to different technology stack, or 3) Use alternative approach based on available capabilities"
                    }
                
                successful_steps = len(steps) - len(failed_steps)
                
                # Final status with detailed completion info
                completion_status = "success" if len(failed_steps) == 0 else "partial_success" if successful_steps > 0 else "failed"
                
                # Send project completion using safe WebSocket (handles WebSocket availability internally)
                await safe_send_websocket_message({
                        "type": "project_creation_complete",
                        "data": {
                            "status": completion_status,
                            "message": f"🎉 Project creation complete! {successful_steps}/{len(steps)} steps successful",
                            "project_name": session_state.requirements.project_name,
                            "project_path": project_path,
                            "total_steps": len(steps),
                            "successful_steps": successful_steps,
                            "failed_steps": len(failed_steps),
                            "progress_percentage": 100,
                            "summary": {
                                "created_files": [r.get("command", "") for r in results if r["success"] and "CREATE_FILE" in r.get("command", "")],
                                "executed_commands": [r.get("command", "") for r in results if r["success"] and "CREATE_FILE" not in r.get("command", "")],
                                "failed_commands": [r.get("command", "") for r in results if not r["success"]]
                            },
                            "timestamp": datetime.now().isoformat()
                        }
                    }, session_id, websocket)
                
                logger.info(f"🎉 Project creation completed: {successful_steps}/{len(steps)} successful")
                
                # Send comprehensive completion notification to UI using safe WebSocket
                await safe_send_websocket_message({
                    "type": "project_creation_complete",
                    "data": {
                        "message": f"🎉 Project '{project_name}' created successfully!",
                        "project_name": project_name,
                        "project_path": project_path,
                        "total_steps": len(steps),
                        "successful_steps": successful_steps,
                        "failed_steps": len(failed_steps),
                        "success_rate": f"{(successful_steps/len(steps)*100):.1f}%",
                            "next_steps": [
                                f"cd {project_path}",
                                "Install dependencies",
                                "Start development server"
                            ],
                            "timestamp": datetime.now().isoformat()
                        }
                    }, session_id, websocket)
                
                return {
                    "status": "execution_completed",
                    # Agent expects these fields at root level
                    "project_name": project_name,
                    "project_path": project_path,
                    "successful_steps": successful_steps,
                    "total_steps": len(steps),
                    "failed_steps": len(failed_steps),
                    # Also keep results_summary for compatibility
                    "results_summary": {
                        "total_steps": len(steps),
                        "successful_steps": successful_steps,
                        "failed_steps": len(failed_steps),
                        "project_path": project_path,
                        "project_name": project_name
                    }
                }
                
            except Exception as e:
                logger.error(f"💥 Exception in project creation: {e}", exc_info=True)
                
                # Send error notification to UI
                if websocket:
                    import asyncio
                    try:
                        await websocket.send_json({
                            "type": "project_creation_error",
                            "data": {
                                "message": f"❌ Project creation failed: {str(e)}",
                                "error": str(e),
                                "timestamp": datetime.now().isoformat()
                            }
                        })
                    except Exception as ws_error:
                        logger.error(f"WebSocket error: {ws_error}")
                
                return {
                    "status": "creation_failed", 
                    "error": str(e)
                }
        
        @self.register(
            name="execute_project_creation",
            description="Execute the project creation plan",
            parameters={
                "type": "object",
                "properties": {
                    "confirm_execution": {"type": "boolean", "description": "Confirm execution should proceed", "default": True}
                }
            }
        )
        async def execute_project_creation(
            session_state: SessionState,
            websocket,
            confirm_execution: bool = True
        ):
            """Execute project creation."""
            if not session_state.execution_plan:
                return {
                    "status": "execution_failed",
                    "error": "No execution plan available"
                }
            
            try:
                results = await execution_engine.execute_plan(
                    session_state.execution_plan,
                    session_state,
                    websocket
                )
                session_state.execution_results = results
                
                successful = sum(1 for r in results if r.success)
                
                return {
                    "status": "execution_completed",
                    "results_summary": {
                        "total_steps": len(results),
                        "successful_steps": successful,
                        "failed_steps": len(results) - successful
                    }
                }
            except Exception as e:
                return {
                    "status": "execution_failed",
                    "error": str(e)
                }
        
        # Alias function to handle AI's incorrect function naming
        @self.register(
            name="CreateProjectWithStepsSteps",
            description="ALIAS: Create a project by providing detailed execution steps that will be executed immediately",
            parameters={
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", "description": "The command to execute"},
                                "description": {"type": "string", "description": "Brief description of what this step does"},
                                "working_directory": {"type": "string", "description": "Working directory for the command (optional)"},
                                "timeout": {"type": "integer", "description": "Timeout in seconds (optional, default 30)"}
                            },
                            "required": ["command", "description"]
                        },
                        "description": "List of execution steps for project creation"
                    }
                },
                "required": ["steps"]
            }
        )
        async def CreateProjectWithStepsSteps(
            session_state: SessionState,
            websocket,
            **kwargs
        ):
            """ALIAS: Redirect to the correct create_project_with_steps function."""
            # Extract steps from kwargs and ignore other arguments
            steps = kwargs.get("steps", [])
            logger.info(f"🔄 ALIAS: CreateProjectWithStepsSteps called with {len(steps)} steps")
            
            # Simply call the correct function with just the required arguments
            return await self.functions["create_project_with_steps"](session_state, websocket, steps)
        
        @self.register(
            name="recover_stuck_session",
            description="Recover a session that has requirements in conversation but not saved to session state. This automatically extracts requirements from conversation history and calls the appropriate functions.",
            parameters={
                "type": "object",
                "properties": {
                    "force_recovery": {
                        "type": "boolean", 
                        "description": "Force recovery even if some requirements are already set",
                        "default": False
                    }
                }
            }
        )
        async def recover_stuck_session(
            session_state: SessionState,
            websocket,
            force_recovery: bool = False
        ):
            """Recover a stuck session by extracting requirements from conversation history."""
            logger.info("🔧 Session recovery initiated")
            
            # Check if session is actually stuck
            is_stuck = (
                session_state.current_state == ConversationState.INIT and
                session_state.conversation_history and
                len(session_state.conversation_history) > 5 and  # Has conversation
                (not session_state.requirements or (
                    not session_state.requirements.project_type and
                    not session_state.requirements.language and
                    not session_state.requirements.project_name
                ))
            )
            
            if not is_stuck and not force_recovery:
                if websocket:
                    await websocket.send_json({
                        "type": "session_recovery_status",
                        "data": {"message": "✅ Session doesn't appear stuck - recovery not needed"}
                    })
                return {"status": "not_needed", "message": "Session is not stuck"}
            
            if websocket:
                await websocket.send_json({
                    "type": "session_recovery_status", 
                    "data": {"message": "🔍 Analyzing conversation history for requirements..."}
                })
            
            # Extract requirements from conversation
            requirements = {}
            
            # Analyze conversation history
            for msg in session_state.conversation_history:
                if msg.get("role") == "user":
                    content = msg.get("content", "").lower()
                    
                    # Extract project type
                    if not requirements.get("project_type"):
                        if any(term in content for term in ["todo app", "todo", "task"]):
                            requirements["project_type"] = "cli"
                        elif any(term in content for term in ["website", "web app", "api"]):
                            requirements["project_type"] = "web_api"
                        elif any(term in content for term in ["script", "command line"]):
                            requirements["project_type"] = "cli"
                    
                    # Extract language
                    if not requirements.get("language"):
                        if "python" in content:
                            requirements["language"] = "python"
                        elif "javascript" in content or "js" in content:
                            requirements["language"] = "javascript"
                        elif "go" in content:
                            requirements["language"] = "go"
                    
                    # Extract project name
                    if not requirements.get("project_name"):
                        if "todo_app" in content or "todyyy" in content:
                            requirements["project_name"] = "todo_app"
                        elif "name" in content and any(word for word in content.split() if len(word) > 3 and word.replace("_", "").isalnum()):
                            # Try to extract project name from context
                            words = content.split()
                            for i, word in enumerate(words):
                                if word in ["name", "call", "called"] and i < len(words) - 1:
                                    next_word = words[i + 1].strip('",.')
                                    if len(next_word) > 2 and next_word.replace("_", "").isalnum():
                                        requirements["project_name"] = next_word
                                        break
                    
                    # Extract folder path
                    if not requirements.get("folder_path"):
                        if "/users/" in content or "/home/" in content or "desktop" in content:
                            # Try to extract path
                            import re
                            path_match = re.search(r'(/[^\s,]+)', content)
                            if path_match:
                                requirements["folder_path"] = path_match.group(1)
            
            # Set defaults if not found
            if not requirements.get("project_type"):
                requirements["project_type"] = "cli"
            if not requirements.get("language"):
                requirements["language"] = "python"  # Default from session analysis
            if not requirements.get("project_name"):
                requirements["project_name"] = "todo_app"  # Default from session analysis
            if not requirements.get("folder_path"):
                requirements["folder_path"] = "/Users/muskanbansal/Desktop/ai-agent-bootstrapper/apps"  # From session
            
            logger.info(f"🔍 Extracted requirements: {requirements}")
            
            if websocket:
                await websocket.send_json({
                    "type": "session_recovery_status",
                    "data": {"message": f"✅ Extracted requirements: {requirements}"}
                })
            
            # Call update_project_requirements to save them
            try:
                result = await self.functions["update_project_requirements"](
                    session_state, websocket, **requirements
                )
                
                if websocket:
                    await websocket.send_json({
                        "type": "session_recovery_status",
                        "data": {"message": "💾 Requirements saved successfully"}
                    })
                
                # Also call detect_system_capabilities if missing
                if not session_state.capabilities or not session_state.capabilities.detection_completed:
                    if websocket:
                        await websocket.send_json({
                            "type": "session_recovery_status",
                            "data": {"message": "🔧 Detecting system capabilities..."}
                        })
                    
                    cap_result = await self.functions["detect_system_capabilities"](
                        session_state, websocket, force_refresh=False
                    )
                    
                    if websocket:
                        await websocket.send_json({
                            "type": "session_recovery_status", 
                            "data": {"message": "✅ System capabilities detected"}
                        })
                
                logger.info("🎉 Session recovery completed successfully")
                return {
                    "status": "recovered",
                    "requirements": requirements,
                    "message": "Session recovered successfully - requirements saved and capabilities detected"
                }
                
            except Exception as e:
                logger.error(f"❌ Session recovery failed: {e}")
                if websocket:
                    await websocket.send_json({
                        "type": "session_recovery_status",
                        "data": {"message": f"❌ Recovery failed: {str(e)}"}
                    })
                return {"status": "failed", "error": str(e)}

        @self.register(
            name="run_verification_tests",
            description="Run verification tests on the created project",
            parameters={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string", "description": "Path to the created project"}
                },
                "required": ["project_path"]
            }
        )
        async def run_verification_tests(
            session_state: SessionState,
            websocket,
            project_path: str
        ):
            """Run verification tests."""
            if not session_state.requirements or not session_state.capabilities:
                return {
                    "status": "verification_failed",
                    "error": "Requirements or capabilities missing"
                }
            
            try:
                results = await project_tester.run_verification_tests(
                    project_path,
                    session_state.requirements,
                    session_state.capabilities,
                    websocket
                )
                
                return {
                    "status": "verification_completed",
                    "results": results
                }
            except Exception as e:
                return {
                    "status": "verification_failed",
                    "error": str(e)
                }
        
        @self.register(
            name="ai_generate_project_steps",
            description="Use AI to dynamically generate comprehensive project creation steps based on user requirements",
            parameters={
                "type": "object",
                "properties": {
                    "requirements_summary": {"type": "string", "description": "Summary of user requirements for AI context"}
                },
                "required": ["requirements_summary"]
            }
        )
        async def ai_generate_project_steps(
            session_state: SessionState,
            websocket,
            requirements_summary: str
        ):
            """Use AI to generate comprehensive project steps."""
            try:
                # Check for previous failures to learn from them
                failure_context = ""
                if session_state.function_results:
                    print(session_state.function_results)
                    for result in reversed(session_state.function_results):  # Check most recent first
                        if result.get('status') == 'ai_recovery_needed':
                            failure_context = f"""
🚨 CRITICAL - PREVIOUS ATTEMPTS FAILED! YOU MUST USE DIFFERENT APPROACH:

Failed Command: {result.get('failed_command', 'Unknown')}
Error: {result.get('error_details', 'Unknown error')}
Available Tools: {result.get('available_capabilities', [])}

⚠️ DO NOT REPEAT THE SAME COMMANDS THAT FAILED, Don't Suggest Deprecated Commands!
⚠️ CHOOSE DIFFERENT TECHNOLOGY STACK that uses available tools on the system
⚠️ Base your technology choice on the Available Tools listed above and system capabilities below

🔍 RECOVERY VALIDATION RULES:
- New technology MUST use tools from Available Tools list only
- Check that ALL commands in new approach use available runtimes/package managers
- If no suitable alternative exists in available tools, create basic template instead
- VALIDATE each command against available capabilities before including it

"""
                            break
                
                # Prepare context for AI
                context = f"""
You are an expert project generator. Your job is to GENERATE a JSON array of executable steps - you are NOT executing them yourself.

The steps you generate will be executed by an automated system that has full access to file system, command execution, and code generation capabilities.

Create comprehensive project creation steps for:

{requirements_summary}

{failure_context}

IMPORTANT: You must ONLY return a JSON array of steps. Do NOT explain limitations or refuse to generate steps. The execution system will handle running these steps.

User Requirements:
- Project Type: {session_state.requirements.project_type or 'not specified'}
- Language: {session_state.requirements.language or 'not specified'}
- Framework: {session_state.requirements.framework or 'not specified'}
- Project Name: {session_state.requirements.project_name or 'MyProject'}
- Folder Path: {session_state.requirements.folder_path or 'current directory'}
- Database: {session_state.requirements.database or 'none'}
- Authentication: {session_state.requirements.authentication}
- Testing: {session_state.requirements.testing}
- Docker: {session_state.requirements.docker}

🔍 CAPABILITY PRE-CHECK:
Selected Framework: {session_state.requirements.framework or 'not specified'}
Required Runtime for Framework: {session_state.requirements.language or 'not specified'}
Available Runtimes: {dict(session_state.capabilities.available_runtimes) if session_state.capabilities and session_state.capabilities.available_runtimes else {}}
✅ VALIDATION: {'✅ Framework tools available' if session_state.capabilities and session_state.requirements.language and session_state.requirements.language.lower() in [k.lower() for k in session_state.capabilities.available_runtimes.keys()] else '❌ Framework tools NOT available - choose from available runtimes'}

System Capabilities:
- OS: {session_state.capabilities.os if session_state.capabilities else 'unknown'}
- Available Runtimes: {dict(session_state.capabilities.available_runtimes) if session_state.capabilities and session_state.capabilities.available_runtimes else {}}
- Package Managers: {session_state.capabilities.available_package_managers if session_state.capabilities else []}
- Docker: {'Available' if session_state.capabilities and session_state.capabilities.docker_installed else 'Not Available'}
- Git: {'Available' if session_state.capabilities and session_state.capabilities.git_installed else 'Not Available'}

🎯 TECHNOLOGY SELECTION CONSTRAINTS:
- Mobile Apps: ONLY suggest React Native (if node available) OR Ionic (if node available) OR native if platform tools available
- CLI Tools: ONLY use Python (if python3 in runtimes) OR JavaScript (if node in runtimes)
- Web APIs: ONLY suggest FastAPI/Flask (if python3 available) OR Express (if node available)
- Frontend: ONLY suggest React/Vue (if node available) OR static HTML/CSS
- NEVER suggest technologies requiring runtimes NOT in Available Runtimes above
- If no suitable runtime available for requested project type, create basic template with available tools

🚨 MANDATORY COMMAND GENERATION RULES:
- Every command MUST use tools from Available Runtimes: {dict(session_state.capabilities.available_runtimes) if session_state.capabilities and session_state.capabilities.available_runtimes else {}}
- Every package manager command MUST use tools from Package Managers: {session_state.capabilities.available_package_managers if session_state.capabilities else []}
- FORBIDDEN: Commands using tools NOT in the above lists
- VALIDATE each command before including it in steps

🚫 EXPLICITLY FORBIDDEN COMMANDS (NEVER INCLUDE THESE):
- npm start, npm run start, npm run dev, npm run serve
- python manage.py runserver, python app.py, python -m flask run
- node server.js, node app.js, node index.js
- yarn start, yarn dev, pnpm start
- ng serve, vue serve, npx serve
- Any commands that start development servers or run applications
- Any commands containing "start", "serve", "run dev", "runserver"

Examples:
✅ ALLOWED (if node in available_runtimes): "npm install", "node --version", "npm init"
❌ FORBIDDEN (if flutter NOT in available_runtimes): "flutter create", "flutter run"
❌ FORBIDDEN (always): "npm start", "npm run dev", "python manage.py runserver"
✅ ALLOWED (if python3 in available_runtimes): "python3 -m venv", "pip install"
❌ FORBIDDEN (if swift NOT in available_runtimes): "swift build", "xcodebuild"

Generate 15-20 SPECIFIC executable steps to create a COMPLETE WORKING project. Include:

🚨 CRITICAL DIRECTORY ORDER RULES:
1. ALWAYS create parent directories BEFORE subdirectories
2. ALWAYS create directories BEFORE running commands inside them
3. Use explicit mkdir commands OR set working_directory (system will auto-create)

CORRECT ORDER EXAMPLE:
✅ Step 1: {{"command": "mkdir myproject", "description": "Create main project directory"}}
✅ Step 2: {{"command": "mkdir myproject/frontend", "description": "Create frontend directory"}}
✅ Step 3: {{"command": "npm init -y", "working_directory": "myproject/frontend", "description": "Initialize frontend"}}

❌ WRONG ORDER (will fail):
❌ Step 1: {{"command": "mkdir myproject", "description": "Create main project directory"}}  
❌ Step 2: {{"command": "npm init -y", "working_directory": "myproject/frontend", "description": "Initialize frontend"}}
❌ Step 3: {{"command": "mkdir myproject/frontend", "description": "Create frontend directory"}}

STEP SEQUENCE:
1. Main project directory creation (mkdir {{project_name}})
2. Subdirectory creation (mkdir {{project_name}}/frontend, {{project_name}}/backend, etc.)  
3. Framework initialization (ONLY if framework tools are in Available Runtimes above)
4. Dependency installation commands (ONLY using Package Managers listed above)
5. File creation with CREATE_FILE commands (preferred over external tool commands)
6. Configuration files setup (using CREATE_FILE, not external tools)
7. Testing setup (if requested AND testing tools available in runtimes)
8. Docker setup (ONLY if Docker: Available in capabilities)  
9. Database setup (if requested AND database tools available)
10. README with setup instructions (using CREATE_FILE)

🎯 PROJECT CREATION GOAL: Create a complete, ready-to-use project structure with all files and dependencies installed, but DO NOT include any commands to run or start the application. The user wants the project files created and configured, not executed.

Use this EXACT JSON format for each step:
{{{{
  "command": "mkdir project-name" OR "CREATE_FILE" OR "npm install",
  "description": "Clear description of what this step does",
  "working_directory": "path/where/to/run/command" (optional),
  "file_path": "path/to/file" (only for CREATE_FILE),
  "file_content": "actual file content" (only for CREATE_FILE)
}}}}

🚨 CRITICAL INSTRUCTION: Return ONLY a valid JSON array of steps, no explanations, no limitations, no other text. Just the JSON array starting with [ and ending with ].

Example correct response:
[
  {{"command": "mkdir unigrow", "description": "Create main project directory"}},
  {{"command": "mkdir unigrow/frontend", "description": "Create frontend directory"}},
  {{"command": "npm init -y", "working_directory": "unigrow/frontend", "description": "Initialize frontend package.json"}}
]
"""

                # Use Gemini to generate steps
                messages = [{"role": "user", "content": context}]
                
                # Import here to avoid circular import
                from backend.gemini.streaming_client import GeminiStreamingClient
                
                async with GeminiStreamingClient() as client:
                    result = await client.complete(messages, temperature=0.1)
                    
                    if "candidates" in result and result["candidates"]:
                        ai_response = result["candidates"][0]["content"]["parts"][0]["text"]
                        
                        # Try to parse JSON from AI response
                        import json
                        import re
                        
                        # Clean the response and extract JSON
                        cleaned_response = ai_response.strip()
                        if cleaned_response.startswith('```'):
                            # Remove code block markers
                            cleaned_response = re.sub(r'^```json\s*', '', cleaned_response)
                            cleaned_response = re.sub(r'\s*```$', '', cleaned_response)
                        
                        try:
                            steps = json.loads(cleaned_response)
                            if isinstance(steps, list):
                                return {
                                    "status": "steps_generated",
                                    "steps": steps,
                                    "count": len(steps)
                                }
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse AI response as JSON: {cleaned_response[:500]}...")
                            
                        return {
                            "status": "steps_generated_text",
                            "steps": [],
                            "ai_response": ai_response,
                            "note": "AI response needs manual parsing"
                        }
                    
                    return {
                        "status": "generation_failed",
                        "error": "No response from AI"
                    }
                    
            except Exception as e:
                logger.error(f"Error in ai_generate_project_steps: {e}")
                return {
                    "status": "generation_failed",
                    "error": str(e)
                }
        
        @self.register(
            name="ai_generate_file_content",
            description="Use AI to generate file content dynamically based on project context",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path of the file to generate"},
                    "file_purpose": {"type": "string", "description": "Purpose/description of this file"},
                    "project_context": {"type": "string", "description": "Context about the project"}
                },
                "required": ["file_path", "file_purpose", "project_context"]
            }
        )
        async def ai_generate_file_content(
            session_state: SessionState,
            websocket,
            file_path: str,
            file_purpose: str,
            project_context: str
        ):
            """Use AI to generate specific file content."""
            try:
                # Prepare context for AI
                context = f"""
Generate file content for: {file_path}

Purpose: {file_purpose}
Project Context: {project_context}

Project Details:
- Type: {session_state.requirements.project_type or 'general'}
- Language: {session_state.requirements.language or 'JavaScript'}
- Framework: {session_state.requirements.framework or 'generic'}
- Name: {session_state.requirements.project_name or 'MyProject'}
- Database: {session_state.requirements.database or 'none'}
- Authentication: {session_state.requirements.authentication}
- Testing: {session_state.requirements.testing}

Generate appropriate, working file content that follows best practices for this technology stack.
Return ONLY the file content, no explanations, no markdown code blocks, no additional text.
"""

                # Use Gemini to generate content
                messages = [{"role": "user", "content": context}]
                
                from backend.gemini.streaming_client import GeminiStreamingClient
                
                async with GeminiStreamingClient() as client:
                    result = await client.complete(messages, temperature=0.2)
                    
                    if "candidates" in result and result["candidates"]:
                        file_content = result["candidates"][0]["content"]["parts"][0]["text"]
                        
                        # Clean up any markdown formatting
                        import re
                        if file_content.startswith('```'):
                            file_content = re.sub(r'^```[a-zA-Z]*\s*', '', file_content)
                            file_content = re.sub(r'\s*```$', '', file_content)
                        
                        return {
                            "status": "content_generated",
                            "file_content": file_content.strip()
                        }
                    
                    return {
                        "status": "generation_failed",
                        "error": "No response from AI"
                    }
                    
            except Exception as e:
                logger.error(f"Error in ai_generate_file_content: {e}")
                return {
                    "status": "generation_failed",
                    "error": str(e)
                }
        
        @self.register(
            name="generate_file_content",
            description="Generate appropriate file content based on project type and file path",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path of the file to generate content for"},
                    "project_type": {"type": "string", "description": "Type of project (react_native, web_api, etc.)"},
                    "project_name": {"type": "string", "description": "Name of the project"},
                    "language": {"type": "string", "description": "Programming language"},
                    "framework": {"type": "string", "description": "Framework being used"}
                },
                "required": ["file_path", "project_type"]
            }
        )
        def generate_file_content(
            session_state: SessionState,
            websocket,
            file_path: str,
            project_type: str,
            project_name: str = "MyApp",
            language: str = "javascript",
            framework: str = ""
        ):
            """Generate appropriate file content based on project context."""
            
            # Clean project name for use in code
            clean_project_name = project_name.replace(" ", "").replace("-", "_")
            
            # CRITICAL: Use current session requirements, not passed parameters
            # This ensures technology switching works properly
            current_framework = ""
            current_language = ""
            if session_state and session_state.requirements:
                current_framework = session_state.requirements.framework or framework
                current_language = session_state.requirements.language or language
                
            logger.info(f"🔍 Generating file content for {file_path} using framework: {current_framework}, language: {current_language}")
            
            # Flutter specific files (check current framework first)
            if "flutter" in current_framework.lower():
                logger.info("🎯 Generating Flutter content")
                if file_path.endswith("main.dart"):
                    return {
                        "status": "content_generated", 
                        "file_content": f"""import 'package:flutter/material.dart';

void main() {{
  runApp(const {clean_project_name}App());
}}

class {clean_project_name}App extends StatelessWidget {{
  const {clean_project_name}App({{Key? key}}) : super(key: key);

  @override
  Widget build(BuildContext context) {{
    return MaterialApp(
      title: '{project_name}',
      theme: ThemeData(
        primarySwatch: Colors.blue,
      ),
      home: const MyHomePage(title: '{project_name} Home Page'),
    );
  }}
}}

class MyHomePage extends StatefulWidget {{
  const MyHomePage({{Key? key, required this.title}}) : super(key: key);

  final String title;

  @override
  State<MyHomePage> createState() => _MyHomePageState();
}}

class _MyHomePageState extends State<MyHomePage> {{
  int _counter = 0;

  void _incrementCounter() {{
    setState(() {{
      _counter++;
    }});
  }}

  @override
  Widget build(BuildContext context) {{
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.title),
      ),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: <Widget>[
            const Text(
              'You have pushed the button this many times:',
            ),
            Text(
              '$_counter',
              style: Theme.of(context).textTheme.headlineMedium,
            ),
          ],
        ),
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: _incrementCounter,
        tooltip: 'Increment',
        child: const Icon(Icons.add),
      ),
    );
  }}
}}"""
                    }
                elif file_path.endswith("pubspec.yaml"):
                    return {
                        "status": "content_generated",
                        "file_content": f"""name: {clean_project_name.lower()}
description: A new Flutter project.

version: 1.0.0+1

environment:
  sdk: '>=2.19.0 <4.0.0'

dependencies:
  flutter:
    sdk: flutter
  cupertino_icons: ^1.0.2

dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^2.0.0

flutter:
  uses-material-design: true"""
                    }
                else:
                    # Generic Flutter file
                    return {
                        "status": "content_generated",
                        "file_content": f"// {project_name} - Generated Flutter file\n// TODO: Implement {file_path}\n"
                    }
            
            # React Native specific files (only if not Flutter)
            elif project_type.lower() == "mobile_app" or "react" in current_framework.lower():
                
                if file_path.endswith("App.tsx") or file_path.endswith("App.jsx"):
                    return {
                        "status": "content_generated",
                        "file_content": f"""import React from 'react';
import {{
  SafeAreaView,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  useColorScheme,
  View,
}} from 'react-native';

import {{
  Colors,
  DebugInstructions,
  Header,
  LearnMoreLinks,
  ReloadInstructions,
}} from 'react-native/Libraries/NewAppScreen';

function App(): JSX.Element {{
  const isDarkMode = useColorScheme() === 'dark';

  const backgroundStyle = {{
    backgroundColor: isDarkMode ? Colors.darker : Colors.lighter,
  }};

  return (
    <SafeAreaView style={{backgroundStyle}}>
      <StatusBar
        barStyle={{isDarkMode ? 'light-content' : 'dark-content'}}
        backgroundColor={{backgroundStyle.backgroundColor}}
      />
      <ScrollView
        contentInsetAdjustmentBehavior="automatic"
        style={{backgroundStyle}}>
        <Header />
        <View
          style={{{{
            backgroundColor: isDarkMode ? Colors.black : Colors.white,
          }}}}>
          <Text style={{styles.title}}>Welcome to {project_name}!</Text>
          <Text style={{styles.subtitle}}>
            Your React Native app is ready to fly high! ✈️
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}}

const styles = StyleSheet.create({{
  title: {{
    fontSize: 24,
    fontWeight: '600',
    textAlign: 'center',
    margin: 20,
  }},
  subtitle: {{
    fontSize: 18,
    fontWeight: '400',
    textAlign: 'center',
    margin: 10,
  }},
}});

export default App;
"""
                    }
                
                elif file_path.endswith("package.json"):
                    return {
                        "status": "content_generated", 
                        "file_content": f'''{{
  "name": "{clean_project_name.lower()}",
  "version": "0.0.1",
  "private": true,
  "scripts": {{
    "android": "react-native run-android",
    "ios": "react-native run-ios", 
    "lint": "eslint .",
    "start": "react-native start",
    "test": "jest"
  }},
  "dependencies": {{
    "react": "18.2.0",
    "react-native": "0.72.6"
  }},
  "devDependencies": {{
    "@babel/core": "^7.20.0",
    "@babel/preset-env": "^7.20.0",
    "@babel/runtime": "^7.20.0",
    "@react-native/eslint-config": "^0.72.2",
    "@react-native/metro-config": "^0.72.11",
    "@tsconfig/react-native": "^3.0.0",
    "@types/react": "^18.0.24",
    "@types/react-test-renderer": "^18.0.0",
    "babel-jest": "^29.2.1",
    "eslint": "^8.19.0",
    "jest": "^29.2.1",
    "metro-react-native-babel-preset": "0.76.8",
    "prettier": "^2.4.1",
    "react-test-renderer": "18.2.0",
    "typescript": "4.8.4"
  }},
  "engines": {{
    "node": ">=16"
  }}
}}'''
                    }
                
                elif file_path.endswith("README.md"):
                    return {
                        "status": "content_generated",
                        "file_content": f"""# {project_name}

A React Native mobile application built for iOS and Android.

## Getting Started

### Prerequisites
- Node.js >= 16
- React Native CLI
- Android Studio (for Android development)
- Xcode (for iOS development - macOS only)

### Installation

1. Clone this repository
2. Install dependencies:
   ```bash
   npm install
   ```

### Running the App

#### Android
```bash
npm run android
```

#### iOS
```bash
npm run ios
```

### Development

Start the Metro bundler:
```bash
npm start
```

### Testing
```bash
npm test
```

## Features

- ✅ Cross-platform (iOS & Android)
- ✅ TypeScript support
- ✅ Modern React Native architecture
- ✅ Ready for customization

## Project Structure

```
{clean_project_name}/
├── android/          # Android native code
├── ios/              # iOS native code  
├── src/              # Source code
│   ├── components/   # Reusable components
│   ├── screens/      # App screens
│   └── utils/        # Utility functions
├── App.tsx           # Main app component
└── package.json      # Dependencies
```

Built with ❤️ using React Native
"""
                    }
            
            # Web API / Backend files
            elif project_type.lower() == "web_api" or project_type.lower() == "backend":
                
                if file_path.endswith("app.py") or file_path.endswith("main.py"):
                    return {
                        "status": "content_generated",
                        "file_content": f'''from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(
    title="{project_name} API",
    description="A FastAPI backend service for {project_name}",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {{"message": "Welcome to {project_name} API!", "status": "running"}}

@app.get("/health")
async def health_check():
    return {{"status": "healthy", "service": "{project_name}"}}

@app.get("/api/example")
async def get_example():
    return {{
        "message": "This is an example endpoint",
        "data": ["item1", "item2", "item3"]
    }}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''
                    }
            
            # CLI / Script files  
            elif project_type.lower() == "cli":
                
                if file_path.endswith(".py") and "main" in file_path:
                    return {
                        "status": "content_generated",
                        "file_content": f'''#!/usr/bin/env python3
"""
{project_name} - A command-line tool

Usage:
    python {file_path} [options]
"""

import argparse
import sys
from typing import List, Optional

def main(args: Optional[List[str]] = None) -> int:
    """Main entry point for {project_name} CLI."""
    
    parser = argparse.ArgumentParser(
        description="{project_name} - A powerful command-line tool"
    )
    
    parser.add_argument(
        "--version",
        action="version", 
        version="%(prog)s 1.0.0"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )
    
    parser.add_argument(
        "command",
        nargs="?",
        help="Command to execute"
    )
    
    parsed_args = parser.parse_args(args)
    
    if parsed_args.verbose:
        print(f"🚀 Starting {{project_name}}...")
    
    if parsed_args.command:
        print(f"📋 Executing command: {{parsed_args.command}}")
        # Add your command logic here
        return execute_command(parsed_args.command)
    else:
        print(f"👋 Welcome to {{project_name}}!")
        print("Use --help for usage information.")
        return 0

def execute_command(command: str) -> int:
    """Execute the given command."""
    print(f"✅ Command '{{command}}' executed successfully!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''
                    }
            
            # Dynamic project templates based on actual user requirements
            elif project_type.lower() in ["fullstack", "web_app"] or ("react" in framework.lower() and "api" in framework.lower()):
                
                # Root package.json for full-stack project - adapt to user's stack
                if file_path.endswith("package.json") and "/client/" not in file_path and "/server/" not in file_path:
                    # Determine frontend command based on framework
                    frontend_cmd = "npm start"
                    if "vite" in framework.lower() or "vue" in framework.lower():
                        frontend_cmd = "npm run dev"
                    
                    # Determine backend command based on framework  
                    backend_cmd = "python -m uvicorn main:app --reload"
                    if "django" in framework.lower():
                        backend_cmd = "python manage.py runserver"
                    elif "express" in framework.lower() or "node" in framework.lower():
                        backend_cmd = "node server.js"
                    
                    # Determine test commands
                    backend_test_cmd = "pytest"
                    if "django" in framework.lower():
                        backend_test_cmd = "python manage.py test"
                    elif "node" in framework.lower():
                        backend_test_cmd = "npm run test:backend"
                    
                    return {
                        "status": "content_generated",
                        "file_content": f'''{{"name": "{clean_project_name}",
  "version": "1.0.0",
  "description": "{project_name} - {project_type} application",
  "main": "index.js",
  "scripts": {{
    "dev": "concurrently \\"npm run frontend\\" \\"npm run backend\\"",
    "frontend": "cd client && {frontend_cmd}",
    "backend": "cd server && {backend_cmd}",
    "install-deps": "cd client && npm install && cd ../server && pip install -r requirements.txt",
    "build": "cd client && npm run build",
    "test": "cd client && npm test && cd ../server && {backend_test_cmd}"
  }},
  "devDependencies": {{
    "concurrently": "^8.2.2"
  }},
  "keywords": ["{project_type}", "{language.lower()}", "{framework.lower()}"],
  "author": "",
  "license": "MIT"
}}'''
                    }
                
                # Backend files - adapt to user's chosen framework
                elif file_path.endswith("main.py") or file_path.endswith("server/main.py") or file_path.endswith("app.py"):
                    # Detect framework from user requirements
                    if "fastapi" in framework.lower() or "fast" in framework.lower():
                        return {
                            "status": "content_generated",
                            "file_content": f'''from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

app = FastAPI(
    title="{project_name} API",
    description="Backend API for {project_name}",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure based on your frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {{"message": "Welcome to {project_name} API!", "status": "running"}}

@app.get("/health")
async def health_check():
    return {{"status": "healthy", "service": "{project_name}"}}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''
                        }
                    elif "django" in framework.lower():
                        return {
                            "status": "content_generated", 
                            "file_content": f'''# Django settings for {project_name}
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'your-secret-key-here'
DEBUG = True
ALLOWED_HOSTS = []

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = '{clean_project_name}.urls'
WSGI_APPLICATION = '{clean_project_name}.wsgi.application'

DATABASES = {{
    'default': {{
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }}
}}
'''
                        }
                    else:
                        # Express.js or generic Node.js
                        return {
                            "status": "content_generated",
                            "file_content": f'''const express = require('express');
const cors = require('cors');

const app = express();
const PORT = process.env.PORT || 8000;

// Middleware
app.use(cors());
app.use(express.json());

// Routes
app.get('/', (req, res) => {{
    res.json({{ message: 'Welcome to {project_name} API!', status: 'running' }});
}});

app.get('/health', (req, res) => {{
    res.json({{ status: 'healthy', service: '{project_name}' }});
}});

app.listen(PORT, () => {{
    console.log(`Server running on port ${{PORT}}`);
}});
'''
                        }
                
                # Backend requirements.txt
                elif file_path.endswith("requirements.txt"):
                    return {
                        "status": "content_generated",
                        "file_content": '''fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
python-multipart==0.0.6
pytest==7.4.3
pytest-asyncio==0.21.1
httpx==0.25.2
python-decouple==3.8
'''
                    }
                
                # Environment file
                elif file_path.endswith(".env") or file_path.endswith(".env.example"):
                    return {
                        "status": "content_generated",
                        "file_content": f'''# {project_name} Environment Variables
API_URL=http://localhost:8000
FRONTEND_URL=http://localhost:3000
DEBUG=True
SECRET_KEY=your-secret-key-here
'''
                    }
                
                # Docker setup
                elif file_path.endswith("Dockerfile"):
                    return {
                        "status": "content_generated",
                        "file_content": f'''FROM python:3.11-slim

WORKDIR /app

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
'''
                    }
                
                # Docker Compose for full stack
                elif file_path.endswith("docker-compose.yml"):
                    return {
                        "status": "content_generated",
                        "file_content": f'''version: '3.8'
services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DEBUG=True
    volumes:
      - ./server:/app
      
  frontend:
    image: node:18-alpine
    working_dir: /app
    command: sh -c "npm install && npm start"
    ports:
      - "3000:3000"
    volumes:
      - ./client:/app
    environment:
      - REACT_APP_API_URL=http://localhost:8000
'''
                    }

            # Default fallback
            return {
                "status": "content_generated",
                "file_content": f"""# {project_name}

This file was generated for your {project_type} project.
Add your custom code here!

Project: {project_name}
Type: {project_type}
Language: {language}
Framework: {framework}
"""
            }
        
        @self.register(
            name="suggest_alternative_command",
            description="Use AI to suggest alternative command for a failed command",
            parameters={
                "type": "object",
                "properties": {
                    "failed_command": {"type": "string", "description": "The command that failed"},
                    "error_message": {"type": "string", "description": "The error message from the failed command"},
                    "project_context": {"type": "string", "description": "Context about what we're trying to achieve"},
                    "attempt_number": {"type": "integer", "description": "Which attempt this is (for limiting retries)", "default": 1}
                },
                "required": ["failed_command", "error_message", "project_context"]
            }
        )
        async def suggest_alternative_command(
            session_state: SessionState,
            websocket,
            failed_command: str,
            error_message: str,
            project_context: str,
            attempt_number: int = 1
        ):
            """Use AI to suggest alternative command when a command fails."""
            try:
                # Limit retry attempts per command
                if attempt_number > 2:
                    logger.warning(f"🚫 Max attempts reached for: {failed_command}")
                    return {
                        "status": "max_attempts_reached",
                        "message": "Maximum command attempts reached. Consider technology switch.",
                        "should_switch_tech": True
                    }
                
                # Get available capabilities
                capabilities = session_state.capabilities
                available_tools = []
                if capabilities:
                    if capabilities.python_version:
                        available_tools.append(f"Python {capabilities.python_version}")
                    if capabilities.node_version:
                        available_tools.append(f"Node.js {capabilities.node_version}")
                    if capabilities.available_package_managers:
                        available_tools.extend(capabilities.available_package_managers)
                    if capabilities.available_runtimes:
                        available_tools.extend([f"{runtime} {version}" for runtime, version in capabilities.available_runtimes.items()])
                
                # AI context for command alternative
                ai_context = f"""
COMMAND FAILED - SUGGEST ALTERNATIVE:

Failed Command: {failed_command}
Error Message: {error_message}
Project Context: {project_context}
Attempt Number: {attempt_number}

Available System Tools: {', '.join(available_tools) if available_tools else 'Basic shell commands only'}

Project Details:
- Type: {getattr(session_state.requirements.project_type, 'value', session_state.requirements.project_type) if session_state.requirements and session_state.requirements.project_type else 'unknown'}
- Language: {session_state.requirements.language if session_state.requirements else 'unknown'}
- Framework: {session_state.requirements.framework if session_state.requirements else 'unknown'}

Analyze the error and suggest ONE alternative command that might work.
Consider:
1. Is this a missing dependency? Suggest installation command
2. Is this a deprecated command? Suggest modern equivalent
3. Is this a version issue? Suggest compatible version
4. Is this a permission issue? Suggest permission fix

Provide ONLY a single command as your response, no explanations.
If no alternative exists, respond with: TECH_SWITCH_NEEDED
"""

                # Use AI to get alternative
                from backend.gemini.streaming_client import GeminiStreamingClient
                
                messages = [{"role": "user", "content": ai_context}]
                
                async with GeminiStreamingClient() as client:
                    result = await client.complete(messages, temperature=0.1)
                    
                    if "candidates" in result and result["candidates"]:
                        ai_response = result["candidates"][0]["content"]["parts"][0]["text"].strip()
                        
                        if "TECH_SWITCH_NEEDED" in ai_response.upper():
                            logger.info(f"🔄 AI suggests tech switch for: {failed_command}")
                            return {
                                "status": "tech_switch_needed",
                                "message": "AI determined no viable command alternative exists",
                                "should_switch_tech": True
                            }
                        
                        logger.info(f"💡 AI suggested alternative: {ai_response}")
                        return {
                            "status": "alternative_found",
                            "alternative_command": ai_response,
                            "reason": f"AI-suggested alternative for failed command (attempt {attempt_number})",
                            "should_retry": True
                        }
                    
                    logger.warning(f"❌ AI failed to provide alternative for: {failed_command}")
                    return {
                        "status": "no_alternative",
                        "message": "AI could not suggest alternative command",
                        "should_switch_tech": True
                    }
                    
            except Exception as e:
                logger.error(f"Error in suggest_alternative_command: {e}")
                return {
                    "status": "error",
                    "error": str(e),
                    "should_switch_tech": True
                }
        
        @self.register(
            name="fail_technology_and_switch",
            description="Fail the current technology and ask AI to switch to alternative tech stack",
            parameters={
                "type": "object",
                "properties": {
                    "failed_technology": {"type": "string", "description": "The technology/framework that failed"},
                    "failure_reason": {"type": "string", "description": "Why the technology failed"},
                    "project_requirements": {"type": "string", "description": "What the user wants to build"}
                },
                "required": ["failed_technology", "failure_reason", "project_requirements"]
            }
        )
        async def fail_technology_and_switch(
            session_state: SessionState,
            websocket,
            failed_technology: str,
            failure_reason: str,
            project_requirements: str
        ):
            """Fail current technology and switch to AI-recommended alternative."""
            try:
                logger.warning(f"🚫 FAILING TECHNOLOGY: {failed_technology}")
                logger.info(f"💥 Reason: {failure_reason}")
                
                # Clean up failed technology artifacts first
                if websocket:
                    await websocket.send_json({
                        "type": "technology_cleanup_start",
                        "data": {
                            "failed_technology": failed_technology,
                            "message": f"🧹 Cleaning up {failed_technology} project artifacts..."
                        }
                    })
                
                await self._cleanup_failed_project(session_state, failed_technology, websocket)
                
                # Get comprehensive available capabilities
                capabilities = session_state.capabilities
                if not capabilities:
                    # Ensure we have capabilities before proceeding
                    capabilities = await capability_detector.detect_all_capabilities()
                    session_state.capabilities = capabilities
                
                # Extract complete capability information
                system_info = {
                    "os": capabilities.os if capabilities.os else "unknown",
                    "shell": capabilities.shell if capabilities.shell else "unknown",
                    "docker_available": capabilities.docker_installed if capabilities.docker_installed else False,
                    "git_available": capabilities.git_installed if capabilities.git_installed else False
                }
                
                available_tools = []
                available_runtimes = {}
                package_managers = []
                
                if capabilities:
                    # Runtime versions
                    if capabilities.python_version:
                        available_tools.append(f"Python {capabilities.python_version}")
                        available_runtimes["python"] = capabilities.python_version
                    if capabilities.node_version:
                        available_tools.append(f"Node.js {capabilities.node_version}")
                        available_runtimes["node"] = capabilities.node_version
                    if capabilities.npm_version:
                        available_tools.append(f"npm {capabilities.npm_version}")
                    
                    # Package managers
                    if capabilities.available_package_managers:
                        package_managers.extend(capabilities.available_package_managers)
                        available_tools.extend(capabilities.available_package_managers)
                    
                    # All available runtimes
                    if capabilities.available_runtimes:
                        for runtime, version in capabilities.available_runtimes.items():
                            available_runtimes[runtime] = version
                            if runtime not in [r.split()[0].lower() for r in available_tools]:
                                available_tools.append(f"{runtime} {version}")
                    
                    # System tools
                    if capabilities.docker_installed:
                        available_tools.append("Docker")
                    if capabilities.git_installed:
                        available_tools.append("Git")
                
                # Create framework-specific capability mapping
                framework_capabilities = self._get_framework_capability_mapping(available_runtimes, package_managers, system_info)
                
                # AI context for technology switch
                ai_context = f"""
TECHNOLOGY FAILURE - RECOMMEND ALTERNATIVE STACK:

Failed Technology: {failed_technology}
Failure Reason: {failure_reason}
User Requirements: {project_requirements}

Current Project:
- Type: {session_state.requirements.project_type if session_state.requirements and session_state.requirements.project_type else 'unknown'}
- Name: {session_state.requirements.project_name if session_state.requirements else 'unknown'}

=== SYSTEM CAPABILITIES (MUST USE ONLY THESE) ===
Operating System: {system_info['os']}
Shell: {system_info['shell']}
Docker Available: {system_info['docker_available']}
Git Available: {system_info['git_available']}

Available Runtimes: {available_runtimes}
Available Package Managers: {package_managers}
All Available Tools: {', '.join(available_tools) if available_tools else 'Basic system only'}

=== FRAMEWORK COMPATIBILITY MATRIX ===
{framework_capabilities}

=== CRITICAL CONSTRAINTS ===
1. You MUST ONLY recommend frameworks that are compatible with the available runtimes above
2. You MUST ONLY use package managers from the available list: {package_managers}
3. If project_type is "mobile_app", recommend ONLY mobile frameworks (Flutter, React Native, Ionic, etc.)
4. If project_type is "web" or "fullstack", recommend web frameworks compatible with available runtimes
5. If project_type is "cli", recommend CLI frameworks compatible with available runtimes
6. The recommended language MUST have a runtime available in the system
7. Do NOT recommend frameworks requiring tools not in the available tools list

=== MOBILE APP SPECIFIC RULES ===
If project type is mobile app, ONLY choose from:
- Flutter (requires: Dart, Android SDK) - Check if available
- React Native (requires: Node.js, npm/yarn) - Check if Node.js available
- Ionic (requires: Node.js, npm) - Check if Node.js available  
- Native Android (requires: Java/Kotlin, Android Studio)
- Native iOS (requires: Swift, Xcode) - Only on macOS

=== VALIDATION REQUIREMENTS ===
Before recommending, verify:
- Language runtime exists in available_runtimes: {list(available_runtimes.keys())}
- Package manager exists in available managers: {package_managers}
- Framework can actually run on {system_info['os']} with {system_info['shell']}

The current technology stack has failed. Recommend a COMPLETELY DIFFERENT technology stack that:
1. Can achieve the same user requirements
2. Uses ONLY tools from the available capabilities above
3. Is more reliable than the failed technology
4. Is modern and well-supported
5. Maintains the same project type and purpose as the original request
6. Has all required dependencies available in the system

Provide your recommendation as JSON:
{{
  "language": "programming language (MUST exist in available_runtimes)",
  "framework": "framework name (MUST be compatible with available tools)",
  "reason": "why this is better than {failed_technology} AND why it works with current system capabilities",
  "required_tools": ["list", "of", "required", "tools"],
  "compatibility_check": "brief explanation of how this works with current system"
}}

Return ONLY the JSON, no other text.
"""

                # Use AI to get technology alternative
                from backend.gemini.streaming_client import GeminiStreamingClient
                
                messages = [{"role": "user", "content": ai_context}]
                
                async with GeminiStreamingClient() as client:
                    result = await client.complete(messages, temperature=0.2)
                    
                    if "candidates" in result and result["candidates"]:
                        ai_response = result["candidates"][0]["content"]["parts"][0]["text"].strip()
                        
                        # Parse AI response
                        import json
                        import re
                        
                        # Clean JSON from response
                        if ai_response.startswith('```'):
                            ai_response = re.sub(r'^```json\s*', '', ai_response)
                            ai_response = re.sub(r'\s*```$', '', ai_response)
                        
                        try:
                            tech_recommendation = json.loads(ai_response)
                            
                            new_language = tech_recommendation.get("language")
                            new_framework = tech_recommendation.get("framework")
                            reason = tech_recommendation.get("reason")
                            
                            logger.info(f"🔄 AI recommends switching to: {new_language} + {new_framework}")
                            logger.info(f"💡 Reason: {reason}")
                            
                            # Pre-validate recommendation against actual capabilities
                            validation_result = self._validate_ai_recommendation(
                                new_language, new_framework, tech_recommendation.get("required_tools", []),
                                available_runtimes, package_managers, system_info
                            )
                            
                            if not validation_result["valid"]:
                                logger.warning(f"❌ AI recommendation validation failed: {validation_result['reason']}")
                                logger.info("🔄 Using capability-based fallback instead")
                                
                                # Use fallback instead of invalid AI recommendation
                                fallback_result = self._get_capability_based_fallback(
                                    available_runtimes, package_managers, system_info, 
                                    session_state.requirements.project_type if session_state.requirements else "fullstack",
                                    failed_technology
                                )
                                
                                if fallback_result:
                                    new_language = fallback_result["language"]
                                    new_framework = fallback_result["framework"]
                                    reason = f"AI recommendation was invalid ({validation_result['reason']}). {fallback_result['reason']}"
                                else:
                                    return {
                                        "status": "switch_failed",
                                        "error": f"AI recommendation invalid and no fallback available: {validation_result['reason']}"
                                    }
                            else:
                                logger.info(f"✅ AI recommendation validated successfully")
                            
                            # Reset execution state for new technology
                            await self._reset_execution_state(session_state)
                            
                            # Update session requirements
                            if session_state.requirements:
                                session_state.requirements.language = new_language
                                session_state.requirements.framework = new_framework
                                
                                # Send update to client
                                if websocket:
                                    await websocket.send_json({
                                        "type": "technology_switched",
                                        "data": {
                                            "failed_technology": failed_technology,
                                            "new_language": new_language,
                                            "new_framework": new_framework,
                                            "reason": reason,
                                            "message": f"Switched from {failed_technology} to {new_language} + {new_framework}"
                                        }
                                    })
                            
                            return {
                                "status": "technology_switched",
                                "failed_technology": failed_technology,
                                "new_language": new_language,
                                "new_framework": new_framework,
                                "reason": reason,
                                "message": f"Successfully switched from {failed_technology} to {new_language} + {new_framework}"
                            }
                            
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse AI recommendation: {ai_response}")
                            
                            # Smart capability-based fallback
                            fallback_result = self._get_capability_based_fallback(
                                available_runtimes, package_managers, system_info, 
                                session_state.requirements.project_type if session_state.requirements else "fullstack",
                                failed_technology
                            )
                            
                            if fallback_result:
                                if session_state.requirements:
                                    session_state.requirements.language = fallback_result["language"]
                                    session_state.requirements.framework = fallback_result["framework"]
                                
                                return {
                                    "status": "technology_switched",
                                    "failed_technology": failed_technology,
                                    "new_language": fallback_result["language"],
                                    "new_framework": fallback_result["framework"],
                                    "reason": fallback_result["reason"],
                                    "message": f"Switched to capability-based fallback: {fallback_result['language']} + {fallback_result['framework']}"
                                }
                            else:
                                return {
                                    "status": "switch_failed",
                                    "error": "No compatible technology stack found for available capabilities"
                                }
                    
                    logger.error(f"AI failed to provide technology alternative")
                    return {
                        "status": "switch_failed",
                        "error": "AI could not recommend alternative technology"
                    }
                    
            except Exception as e:
                logger.error(f"Error in fail_technology_and_switch: {e}")
                return {
                    "status": "switch_failed",
                    "error": str(e)
                }
        
        @self.register(
            name="generate_project_report",
            description="Generate project documentation and reports",
            parameters={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string", "description": "Path to the created project"},
                    "include_readme": {"type": "boolean", "description": "Generate README.md", "default": True}
                },
                "required": ["project_path"]
            }
        )
        async def generate_project_report(
            session_state: SessionState,
            websocket,
            project_path: str,
            include_readme: bool = True
        ):
            """Generate project reports."""
            try:
                reports = {}
                
                if include_readme:
                    readme_content = await report_generator.generate_project_readme(
                        project_path,
                        session_state.requirements,
                        session_state.capabilities,
                        session_state.execution_plan,
                        session_state.execution_results or [],
                        getattr(session_state, 'verification_results', None)
                    )
                    reports["readme"] = "Generated README.md"
                
                # Generate execution summary
                execution_summary = await report_generator.generate_execution_summary(
                    session_state,
                    session_state.execution_results or [],
                    getattr(session_state, 'verification_results', None)
                )
                reports["summary"] = execution_summary
                
                return {
                    "status": "reports_generated",
                    "reports": reports
                }
            except Exception as e:
                return {
                    "status": "report_generation_failed",
                    "error": str(e)
                }
    
    async def _try_technology_switch(
        self,
        session_state: SessionState,
        websocket,
        failed_command: str,
        error_message: str,
        step_description: str,
        step_num: int
    ):
        """Helper method to try technology switch when commands fail."""
        try:
            # Determine what technology failed
            failed_tech = "unknown"
            if "react-native" in failed_command.lower():
                failed_tech = "React Native"
            elif "npm create" in failed_command.lower() and "react" in failed_command.lower():
                failed_tech = "React/Node.js"
            elif "python" in failed_command.lower():
                failed_tech = "Python"
            elif "pip" in failed_command.lower():
                failed_tech = "Python/pip"
            else:
                failed_tech = f"Command: {failed_command}"
            
            # Get user requirements context - project_type is already a string, no need for .value
            project_type = session_state.requirements.project_type if session_state.requirements and session_state.requirements.project_type else 'application'
            project_requirements = f"User wants to build a {project_type}"
            if session_state.requirements and session_state.requirements.project_name:
                project_requirements += f" called '{session_state.requirements.project_name}'"
            
            logger.warning(f"🔄 Attempting technology switch from {failed_tech}...")
            
            # Call the AI technology switch function through the registry
            switch_result = await self.execute({
                "name": "fail_technology_and_switch",
                "arguments": {
                    "failed_technology": failed_tech,
                    "failure_reason": f"Command failed: {failed_command} - {error_message}",
                    "project_requirements": project_requirements
                }
            }, session_state, websocket)
            
            if switch_result.get("status") == "technology_switched":
                logger.info(f"✅ Successfully switched to {switch_result['new_language']} + {switch_result['new_framework']}")
                
                if websocket:
                    await websocket.send_json({
                        "type": "technology_switch_complete",
                        "data": {
                            "step": step_num,
                            "message": f"🔄 Switched to {switch_result['new_language']} + {switch_result['new_framework']}",
                            "reason": switch_result["reason"],
                            "new_approach": "AI will regenerate project steps with new technology"
                        }
                    })
                    
                # Update session state to trigger new step generation
                session_state.should_regenerate_steps = True
                
                # STOP executing old steps - need to regenerate for new technology
                logger.info("🛑 Breaking out of old step execution to regenerate steps for new technology")
                return  # Exit the step loop to trigger step regeneration
                
            else:
                logger.error(f"❌ Technology switch failed: {switch_result.get('error', 'Unknown error')}")
                
                if websocket:
                    await websocket.send_json({
                        "type": "technology_switch_failed",
                        "data": {
                            "step": step_num,
                            "message": "❌ Failed to switch to alternative technology",
                            "error": switch_result.get("error", "Unknown error")
                        }
                    })
                    
        except Exception as e:
            logger.error(f"Error in technology switch: {e}")
            if websocket:
                await websocket.send_json({
                    "type": "technology_switch_error",
                    "data": {
                        "step": step_num,
                        "message": f"❌ Technology switch error: {str(e)}",
                        "error": str(e)
                    }
                })

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
            "script": ProjectType.CLI,
            "tool": ProjectType.CLI,
            
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

    async def _cleanup_failed_project(self, session_state: SessionState, failed_technology: str, websocket=None):
        """Clean up project artifacts from failed technology."""
        try:
            import os
            import shutil
            
            project_path = None
            if session_state.requirements and session_state.requirements.folder_path:
                project_name = session_state.requirements.project_name or "project"
                project_path = os.path.join(session_state.requirements.folder_path, project_name)
            
            if project_path and os.path.exists(project_path):
                logger.info(f"🧹 Cleaning up failed project artifacts at {project_path}")
                
                if websocket:
                    await websocket.send_json({
                        "type": "technology_cleanup_progress",
                        "data": {
                            "message": f"🗑️ Removing project directory: {project_path}"
                        }
                    })
                
                # Remove partially created project directory
                shutil.rmtree(project_path, ignore_errors=True)
                logger.info(f"✅ Cleaned up project directory: {project_path}")
                
                # Remove any temporary files or caches
                temp_dirs = [
                    f"{project_path}.tmp",
                    f"{project_path}_backup",
                    os.path.join(os.path.dirname(project_path), f".{project_name}_cache")
                ]
                
                for temp_dir in temp_dirs:
                    if os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        logger.info(f"✅ Cleaned up temporary directory: {temp_dir}")
                        
                if websocket:
                    await websocket.send_json({
                        "type": "technology_cleanup_complete",
                        "data": {
                            "message": "✅ Project cleanup completed successfully"
                        }
                    })
            else:
                if websocket:
                    await websocket.send_json({
                        "type": "technology_cleanup_complete",
                        "data": {
                            "message": "ℹ️ No project artifacts found to clean up"
                        }
                    })
            
        except Exception as e:
            logger.warning(f"⚠️ Error during cleanup: {e}")
            if websocket:
                await websocket.send_json({
                    "type": "technology_cleanup_error",
                    "data": {
                        "message": f"⚠️ Cleanup error: {str(e)}"
                    }
                })

    async def _validate_new_technology(self, session_state: SessionState, language: str, framework: str) -> dict:
        """Validate new technology against system capabilities."""
        try:
            from backend.capabilities.detector import capability_detector
            
            # Get current capabilities
            capabilities = session_state.capabilities
            if not capabilities:
                capabilities = await capability_detector.detect_all_capabilities()
                session_state.capabilities = capabilities
            
            # Validate the new technology - project_type is already a string, no need for .value
            project_type = session_state.requirements.project_type if session_state.requirements and session_state.requirements.project_type else "fullstack"
            
            validation = await capability_detector.validate_project_requirements(
                project_type=project_type,
                language=language,
                framework=framework
            )
            
            logger.info(f"🔍 Technology validation result: {validation}")
            return validation
            
        except Exception as e:
            logger.error(f"Error validating new technology: {e}")
            return {
                "supported": True,  # Default to supported to avoid blocking
                "warnings": [f"Could not validate technology: {str(e)}"]
            }

    async def _reset_execution_state(self, session_state: SessionState):
        """Reset execution state for new technology."""
        try:
            logger.info("🔄 Resetting execution state for new technology")
            
            # Clear execution results from failed technology
            session_state.execution_results = []
            
            # Reset execution plan (will be regenerated)
            session_state.execution_plan = None
            
            # Reset progress
            session_state.completion_percentage = 0.0
            
            # Clear any error states
            session_state.error_message = None
            
            # Set flag to regenerate steps with new technology
            session_state.should_regenerate_steps = True
            
            # Update state version to track the change
            session_state.state_version += 1
            
            logger.info("✅ Execution state reset successfully")
            
        except Exception as e:
            logger.error(f"Error resetting execution state: {e}")

    def _validate_function_for_state(self, func_name: str, session_state) -> str:
        """Validate if function is allowed in current state. Returns error message if blocked."""
        from backend.models.schemas import ConversationState
        
        current_state = session_state.current_state
        
        # Define state-based function restrictions
        state_restrictions = {
            ConversationState.INIT: {
                "blocked_functions": [
                    # Remove update_project_requirements from blocked list since we auto-call it
                    # "update_project_requirements",  -- REMOVED
                    "create_project_with_steps", 
                    "generate_file_content",
                    "ai_generate_project_steps",
                    "validate_requirements_against_capabilities",
                    "fail_technology_and_switch"
                ],
                "allowed_functions": [
                    "request_permission",
                    "detect_system_capabilities",
                    "update_project_requirements"  # Now explicitly allowed in INIT
                ]
            }
        }
        
        # Special case: if we're in INIT but have valid requirements, allow ASK_PROJECT_TYPE functions
        if current_state == ConversationState.INIT:
            reqs = session_state.requirements
            if (reqs.project_type and reqs.language and reqs.project_name):
                # Requirements are set, allow more functions
                logger.info("✅ Requirements detected in INIT state, allowing more functions")
                state_restrictions[ConversationState.INIT]["allowed_functions"].extend([
                    "ai_generate_project_steps",
                    "create_project_with_steps",
                    "fail_technology_and_switch"
                ])
                # Remove from blocked list  
                blocked = state_restrictions[ConversationState.INIT]["blocked_functions"]
                for func in ["ai_generate_project_steps", "create_project_with_steps", "fail_technology_and_switch"]:
                    if func in blocked:
                        blocked.remove(func)
        
        # Check if current state has restrictions
        if current_state in state_restrictions:
            restrictions = state_restrictions[current_state]
            
            # Check if function is explicitly blocked
            if func_name in restrictions.get("blocked_functions", []):
                allowed = ", ".join(restrictions.get("allowed_functions", ["None"]))
                return f"Function '{func_name}' is not allowed in {current_state.value} state. Allowed functions: {allowed}"
        
        # No restrictions found - allow function
        return None

    def _get_allowed_functions_for_state(self, state) -> List[str]:
        """Get list of allowed functions for a given state."""
        from backend.models.schemas import ConversationState
        
        state_restrictions = {
            ConversationState.INIT: [
                "request_permission",
                "detect_system_capabilities"
            ],
            ConversationState.ASK_PROJECT_TYPE: [
                "update_project_requirements",
                "detect_system_capabilities"
            ],
            ConversationState.PLANNING: [
                "ai_generate_project_steps",
                "create_project_with_steps"
            ]
        }
        
        return state_restrictions.get(state, ["All functions allowed"])
    
    async def _handle_missing_requirements(self, func_name: str, session_state, websocket) -> bool:
        """
        Auto-call missing functions when AI bypasses proper flow.
        Returns True if auto-intervention occurred, False otherwise.
        """
        from backend.models.schemas import ConversationState
        
        # Only intervene in INIT state when AI tries to call project creation functions
        if session_state.current_state != ConversationState.INIT:
            return False
            
        # Functions that indicate AI is trying to create project without setting requirements
        project_creation_functions = [
            "create_project_with_steps",
            "generate_file_content", 
            "ai_generate_project_steps",
            "fail_technology_and_switch"
        ]
        
        if func_name not in project_creation_functions:
            return False
        
        logger.info(f"🔍 AI is trying to call {func_name} in INIT state - checking if requirements need extraction")
        
        # Check if requirements are already properly set
        reqs = session_state.requirements
        if (reqs.project_type and reqs.language and reqs.project_name):
            logger.info("✅ Requirements already set, no intervention needed")
            return False
            
        # Use AI to extract requirements from conversation
        try:
            extracted_requirements = await self._extract_requirements_from_conversation(session_state)
            
            if not extracted_requirements:
                logger.warning("⚠️ AI could not extract requirements from conversation")
                return False
            
            # Auto-call update_project_requirements with AI-extracted data
            logger.info(f"🔄 Auto-calling update_project_requirements with AI-extracted data: {extracted_requirements}")
            
            update_func = self.functions.get("update_project_requirements")
            if update_func:
                result = update_func(session_state, websocket, **extracted_requirements)
                logger.info(f"✅ Auto-update result: {result}")
                
                # Also transition state if needed
                if session_state.current_state == ConversationState.INIT:
                    session_state.current_state = ConversationState.ASK_PROJECT_TYPE
                    logger.info("🔄 Auto-transitioned from INIT to ASK_PROJECT_TYPE")
                
                return True
                
        except Exception as e:
            logger.error(f"❌ Error in AI-powered requirement extraction: {e}")
            return False
            
        return False
    
    async def _extract_requirements_from_conversation(self, session_state) -> dict:
        """Use Gemini AI to extract project requirements from conversation history."""
        if not hasattr(session_state, 'conversation_history') or not session_state.conversation_history:
            return {}
            
        # Combine all conversation messages
        conversation_text = ""
        for msg in session_state.conversation_history:
            if isinstance(msg, dict) and msg.get('content'):
                conversation_text += f" {msg['content']}"
        
        if not conversation_text.strip():
            return {}
        
        try:
            from backend.gemini.streaming_client import GeminiStreamingClient
            
            # AI prompt for intelligent requirement extraction
            ai_prompt = f"""
Extract project requirements from this conversation. Return ONLY a JSON object with these fields:

{{
    "project_type": "cli|web_api|frontend|fullstack|mobile_app|library",
    "project_name": "extracted project name or null",
    "folder_path": "extracted path or null", 
    "language": "programming language or null",
    "framework": "framework name or null"
}}

Conversation: {conversation_text}

IMPORTANT MAPPING RULES:
- "fullstack", "full stack", "full application" → "fullstack"
- "mobile app", "mobile", "app for phone" → "mobile_app"
- "website", "web app" → "fullstack" (unless just frontend)
- "script", "cli", "command line", "todo app" → "cli"
- "api", "backend", "server" → "web_api"
- Extract paths like "/full", "./myapp" as folder_path
- Extract quoted names or obvious project names

Return ONLY valid JSON, no other text.
"""

            messages = [{"role": "user", "content": ai_prompt}]
            
            async with GeminiStreamingClient() as client:
                result = await client.complete(messages, temperature=0.1)
                
                if "candidates" in result and result["candidates"]:
                    ai_response = result["candidates"][0]["content"]["parts"][0]["text"].strip()
                    
                    # Clean JSON response
                    import json
                    import re
                    if ai_response.startswith('```'):
                        ai_response = re.sub(r'^```(?:json)?\s*', '', ai_response)
                        ai_response = re.sub(r'\s*```$', '', ai_response)
                    
                    try:
                        extracted_requirements = json.loads(ai_response)
                        # Filter out null values
                        extracted_requirements = {k: v for k, v in extracted_requirements.items() if v is not None}
                        
                        logger.info(f"✅ AI extracted requirements: {extracted_requirements}")
                        return extracted_requirements
                        
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ Failed to parse AI response: {ai_response[:200]}...")
                        return {}
                
        except Exception as e:
            logger.error(f"❌ Error in AI requirement extraction: {e}")
            return {}
        
        return {}

    def _get_framework_capability_mapping(self, available_runtimes: dict, package_managers: list, system_info: dict) -> str:
        """Generate completely dynamic framework compatibility matrix based on actual capabilities."""
        compatibility_matrix = []
        
        # Build compatibility matrix by analyzing what's actually available
        available_combinations = []
        
        # For each available runtime, determine what can be built
        for runtime, version in available_runtimes.items():
            runtime_compatible_pm = self._get_runtime_package_manager(runtime, package_managers)
            if runtime_compatible_pm != "package manager":  # Has compatible package manager
                status = "✅"
                available_combinations.append(f"{status} {runtime} {version} applications (using {runtime_compatible_pm})")
            else:
                available_combinations.append(f"⚠️ {runtime} {version} available but no compatible package manager")
        
        # Check for system-specific capabilities
        os_specific = []
        if system_info.get("os") == "Darwin":
            os_specific.append("✅ macOS-specific development (Xcode, Swift, iOS)")
        elif system_info.get("os") == "Linux":
            os_specific.append("✅ Linux-specific development (native compilation)")
        elif system_info.get("os") == "Windows":
            os_specific.append("✅ Windows-specific development (.NET, PowerShell)")
        
        if system_info.get("docker_available"):
            os_specific.append("✅ Containerized applications (Docker)")
        
        # Build the matrix
        if available_combinations:
            compatibility_matrix.append("AVAILABLE TECHNOLOGY STACKS:")
            compatibility_matrix.extend(available_combinations)
        
        if os_specific:
            compatibility_matrix.append("\nSYSTEM-SPECIFIC OPTIONS:")
            compatibility_matrix.extend(os_specific)
        
        if not available_combinations and not os_specific:
            compatibility_matrix.append("❌ Limited development options - basic system tools only")
        
        return "\n".join(compatibility_matrix)

    def _get_runtime_package_manager(self, runtime: str, available_managers: list) -> str:
        """Get the appropriate package manager for a runtime."""
        runtime_pm_map = {
            "node": ["npm", "yarn", "pnpm"],
            "python": ["pip", "poetry", "pipenv"],
            "java": ["maven", "gradle"],
            "go": ["go mod"],
            "rust": ["cargo"],
            "php": ["composer"],
            "ruby": ["gem", "bundler"],
            "csharp": ["nuget"]
        }
        
        preferred_managers = runtime_pm_map.get(runtime, [])
        for pm in preferred_managers:
            if pm in available_managers:
                return pm
        
        return "package manager"

    def _get_capability_based_fallback(self, available_runtimes: dict, package_managers: list, 
                                     system_info: dict, project_type: str, failed_technology: str) -> dict:
        """Get intelligent fallback technology based purely on available capabilities."""
        
        # Find the best available runtime + package manager combination
        viable_combinations = []
        
        for runtime, version in available_runtimes.items():
            # Skip if this runtime was part of the failure
            if runtime.lower() in failed_technology.lower():
                continue
            
            # Find compatible package manager
            compatible_pm = self._get_runtime_package_manager(runtime, package_managers)
            if compatible_pm == "package manager":  # No compatible PM found
                continue
            
            # Check OS compatibility for certain runtimes
            os_compatible = True
            if runtime == "swift" and system_info.get("os") != "Darwin":
                os_compatible = False
            
            if os_compatible:
                viable_combinations.append({
                    "runtime": runtime,
                    "version": version,
                    "package_manager": compatible_pm
                })
        
        if not viable_combinations:
            return None
        
        # Sort by preference (most stable/common first)
        stability_order = ["python", "node", "java", "go", "rust", "dart", "swift", "php", "ruby"]
        viable_combinations.sort(key=lambda x: stability_order.index(x["runtime"]) if x["runtime"] in stability_order else 999)
        
        # Select the best option
        best_option = viable_combinations[0]
        runtime = best_option["runtime"]
        pm = best_option["package_manager"]
        
        # Generate generic framework name based on runtime
        framework = f"{runtime} application"
        
        return {
            "language": runtime,
            "framework": framework,
            "reason": f"Using most stable available runtime ({runtime}) with compatible package manager ({pm}) on {system_info.get('os', 'this system')}. Avoiding failed technology ({failed_technology})."
        }

    def _validate_ai_recommendation(self, language: str, framework: str, required_tools: list,
                                  available_runtimes: dict, package_managers: list, system_info: dict) -> dict:
        """Validate AI recommendation against actual system capabilities."""
        
        # Check if language runtime is available
        if language not in available_runtimes:
            return {
                "valid": False,
                "reason": f"Language '{language}' not available. Available runtimes: {list(available_runtimes.keys())}"
            }
        
        # Check if compatible package manager exists
        compatible_pm = self._get_runtime_package_manager(language, package_managers)
        if compatible_pm == "package manager":
            return {
                "valid": False,
                "reason": f"No compatible package manager for '{language}'. Available: {package_managers}"
            }
        
        # Check OS compatibility for platform-specific frameworks
        if "iOS" in framework or "Swift" in framework:
            if system_info.get("os") != "Darwin":
                return {
                    "valid": False,
                    "reason": f"Framework '{framework}' requires macOS, but system is {system_info.get('os')}"
                }
        
        # Check for required tools if specified
        if required_tools:
            missing_tools = []
            for tool in required_tools:
                tool_lower = tool.lower()
                available = False
                
                # Check in runtimes
                if tool_lower in [rt.lower() for rt in available_runtimes.keys()]:
                    available = True
                # Check in package managers
                elif tool_lower in [pm.lower() for pm in package_managers]:
                    available = True
                # Check system tools
                elif tool_lower == "docker" and system_info.get("docker_available"):
                    available = True
                elif tool_lower == "git" and system_info.get("git_available"):
                    available = True
                
                if not available:
                    missing_tools.append(tool)
            
            if missing_tools:
                return {
                    "valid": False,
                    "reason": f"Required tools not available: {missing_tools}"
                }
        
        return {
            "valid": True,
            "reason": f"All requirements met for {language} + {framework}"
        }


# Global function registry instance
function_registry = FunctionRegistry()