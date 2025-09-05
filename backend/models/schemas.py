"""Pydantic models and schemas."""
from pydantic import BaseModel, Field, field_validator
from typing import Dict, List, Optional, Any, Union
from enum import Enum
from datetime import datetime


class ConversationState(str, Enum):
    """Conversation state machine states."""
    INIT = "INIT"
    ASK_PROJECT_TYPE = "ASK_PROJECT_TYPE"
    ASK_LANGUAGE_PREFERENCE = "ASK_LANGUAGE_PREFERENCE"
    ASK_PROJECT_NAME_FOLDER = "ASK_PROJECT_NAME_FOLDER"
    ASK_ADDITIONAL_DETAILS = "ASK_ADDITIONAL_DETAILS"
    CHECK_SYSTEM_CAPABILITIES = "CHECK_SYSTEM_CAPABILITIES"
    VALIDATE_INFO = "VALIDATE_INFO"
    SUMMARY_CONFIRMATION = "SUMMARY_CONFIRMATION"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"
    ABORTED = "ABORTED"


class ProjectType(str, Enum):
    """Supported project types."""
    WEB_API = "web_api"
    FRONTEND = "frontend"
    CLI = "cli"
    MOBILE_APP = "mobile_app"
    FULLSTACK = "fullstack"
    LIBRARY = "library"
    MICROSERVICE = "microservice"


class Permission(BaseModel):
    """Permission model."""
    type: str = Field(..., description="Permission type (global/folder)")
    scope: str = Field(..., description="Permission scope")
    granted: bool = Field(default=False)
    timestamp: datetime = Field(default_factory=datetime.now)
    revoked: Optional[datetime] = None


class ProjectRequirements(BaseModel):
    """Project requirements collected from user."""
    project_type: Optional[ProjectType] = None
    language: Optional[str] = None
    framework: Optional[str] = None
    project_name: Optional[str] = None
    folder_path: Optional[str] = None
    database: Optional[str] = None
    authentication: bool = False
    testing: bool = False
    docker: bool = False
    additional_features: List[str] = Field(default_factory=list)
    
    @field_validator('project_type', mode='before')
    @classmethod
    def validate_project_type(cls, v):
        """Convert string project type to enum."""
        if v is None:
            return None
            
        if isinstance(v, ProjectType):
            return v
            
        if isinstance(v, str):
            # Normalize input
            input_lower = v.lower().strip()
            
            # Mapping dictionary for user-friendly inputs
            project_type_mappings = {
                # Web-related
                "web app": ProjectType.FULLSTACK,
                "web application": ProjectType.FULLSTACK,
                "website": ProjectType.FRONTEND,
                "frontend": ProjectType.FRONTEND,
                "backend": ProjectType.WEB_API,
                "web api": ProjectType.WEB_API,
                "api": ProjectType.WEB_API,
                "fullstack": ProjectType.FULLSTACK,
                "full stack": ProjectType.FULLSTACK,
                "full-stack": ProjectType.FULLSTACK,
                # CLI-related
                "cli": ProjectType.CLI,
                "command line": ProjectType.CLI,
                "command-line": ProjectType.CLI,
                "script": ProjectType.CLI,
                "tool": ProjectType.CLI,
                # Mobile
                "mobile": ProjectType.MOBILE_APP,
                "mobile app": ProjectType.MOBILE_APP,
                "android": ProjectType.MOBILE_APP,
                "ios": ProjectType.MOBILE_APP,
                # Library
                "library": ProjectType.LIBRARY,
                "package": ProjectType.LIBRARY,
                "lib": ProjectType.LIBRARY,
                # Microservice
                "microservice": ProjectType.MICROSERVICE,
                "micro service": ProjectType.MICROSERVICE,
                "service": ProjectType.MICROSERVICE,
            }
            
            # Try exact match first
            if input_lower in project_type_mappings:
                return project_type_mappings[input_lower]
            
            # Try partial matching for better coverage
            for key, project_type in project_type_mappings.items():
                if key in input_lower or input_lower in key:
                    return project_type
            
            # Try to match directly to enum values
            for project_type in ProjectType:
                if project_type.value.lower() == input_lower:
                    return project_type
            
            # Default fallback
            return ProjectType.FULLSTACK
            
        return v


class SystemCapability(BaseModel):
    """System capability detection result."""
    os: str = Field(..., description="Operating system")
    shell: str = Field(..., description="Shell type")
    python_version: Optional[str] = None
    node_version: Optional[str] = None
    npm_version: Optional[str] = None
    docker_installed: bool = False
    git_installed: bool = False
    available_package_managers: List[str] = Field(default_factory=list)
    available_runtimes: Dict[str, str] = Field(default_factory=dict)
    environment_variables: Dict[str, str] = Field(default_factory=dict)
    detection_completed: bool = Field(default=False, description="Whether detection was completed successfully")


class ExecutionStep(BaseModel):
    """Single execution step in the plan."""
    command: str = Field(..., description="Command to execute")
    description: str = Field(..., description="Step description")
    working_directory: Optional[str] = None
    fallback_command: Optional[str] = None
    expected_output_pattern: Optional[str] = None
    timeout: int = Field(default=30, description="Timeout in seconds")
    retry_count: int = Field(default=0)
    requires_permission: bool = Field(default=False)


class ExecutionPlan(BaseModel):
    """Complete execution plan."""
    steps: List[ExecutionStep] = Field(default_factory=list)
    total_steps: int = 0
    estimated_duration: int = Field(default=0, description="Estimated duration in seconds")
    requires_permissions: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    
    def model_post_init(self, __context):
        """Update total_steps after initialization."""
        self.total_steps = len(self.steps)


class ExecutionResult(BaseModel):
    """Result of command execution."""
    step_index: int
    command: str
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration: float = Field(default=0.0, description="Execution duration in seconds")
    timestamp: datetime = Field(default_factory=datetime.now)
    fallback_used: bool = False
    retry_count: int = 0


class SessionState(BaseModel):
    """Complete session state."""
    session_id: str
    current_state: ConversationState = ConversationState.INIT
    requirements: ProjectRequirements = Field(default_factory=ProjectRequirements)
    capabilities: Optional[SystemCapability] = None
    permissions: Dict[str, Permission] = Field(default_factory=dict)
    execution_plan: Optional[ExecutionPlan] = None
    execution_results: List[ExecutionResult] = Field(default_factory=list)
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    pending_question: Optional[Dict[str, Any]] = None
    waiting_for_user: bool = False
    completion_percentage: float = 0.0
    error_message: Optional[str] = None
    function_results: List[Dict[str, Any]] = Field(default_factory=list)
    capabilities_detected: bool = Field(default=False)
    validation_completed: bool = Field(default=False)
    should_regenerate_steps: bool = Field(default=False)
    state_history: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    iteration_count: int = 0
    state_version: int = 1
    
    def add_message(self, role: str, content: str, **kwargs):
        """Add message to conversation history."""
        self.conversation_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        })
        self.updated_at = datetime.now()
    
    def update_state(self, new_state: ConversationState):
        """Update conversation state."""
        self.current_state = new_state
        self.updated_at = datetime.now()
        self.iteration_count += 1


class GeminiMessage(BaseModel):
    """Message format for Gemini API."""
    role: str = Field(..., description="Message role (user/assistant/system)")
    content: str = Field(..., description="Message content")
    function_call: Optional[Dict[str, Any]] = None


class GeminiRequest(BaseModel):
    """Request format for Gemini API."""
    model: str = Field(default="gemini-1.5-flash")
    messages: List[GeminiMessage]
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=8192)
    stream: bool = Field(default=True)
    functions: Optional[List[Dict[str, Any]]] = None


class GeminiFunctionCall(BaseModel):
    """Function call from Gemini."""
    name: str = Field(..., description="Function name")
    arguments: Dict[str, Any] = Field(default_factory=dict)


class GeminiStreamChunk(BaseModel):
    """Streaming chunk from Gemini."""
    type: str = Field(..., description="Chunk type (text/function_call/finish)")
    content: Optional[str] = None
    function_call: Optional[GeminiFunctionCall] = None
    finish_reason: Optional[str] = None
    accumulated_content: str = ""


class WebSocketMessage(BaseModel):
    """WebSocket message format."""
    type: str = Field(..., description="Message type")
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)


class APIResponse(BaseModel):
    """Standard API response."""
    success: bool = True
    message: str = ""
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class CreateSessionRequest(BaseModel):
    """Request to create new session."""
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UserResponseRequest(BaseModel):
    """User response to agent question."""
    session_id: str
    response: str
    metadata: Dict[str, Any] = Field(default_factory=dict)