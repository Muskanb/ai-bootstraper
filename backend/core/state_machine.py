"""Conversation state machine."""
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
import logging
from datetime import datetime

from backend.models.schemas import ConversationState, SessionState

logger = logging.getLogger(__name__)


class StateTransition:
    """Represents a state transition."""
    
    def __init__(
        self,
        from_state: ConversationState,
        to_state: ConversationState,
        condition: Optional[Callable[[SessionState], bool]] = None,
        action: Optional[Callable[[SessionState], None]] = None,
        description: str = ""
    ):
        """
        Initialize state transition.
        
        Args:
            from_state: Source state
            to_state: Target state
            condition: Optional condition function
            action: Optional action to perform on transition
            description: Human-readable description
        """
        self.from_state = from_state
        self.to_state = to_state
        self.condition = condition
        self.action = action
        self.description = description
    
    def can_transition(self, session_state: SessionState) -> bool:
        """Check if transition is possible."""
        if session_state.current_state != self.from_state:
            return False
        
        if self.condition:
            return self.condition(session_state)
        
        return True
    
    def execute(self, session_state: SessionState):
        """Execute the transition."""
        if self.action:
            self.action(session_state)
        
        old_state = session_state.current_state
        session_state.update_state(self.to_state)
        
        logger.info(f"State transition: {old_state.value} -> {self.to_state.value}")


class ConversationStateMachine:
    """State machine for conversation flow."""
    
    def __init__(self):
        """Initialize state machine."""
        self.transitions: List[StateTransition] = []
        self.state_handlers: Dict[ConversationState, List[Callable]] = {}
        self._setup_transitions()
    
    def add_transition(self, transition: StateTransition):
        """Add a transition to the state machine."""
        self.transitions.append(transition)
    
    def add_state_handler(self, state: ConversationState, handler: Callable):
        """Add a handler for a specific state."""
        if state not in self.state_handlers:
            self.state_handlers[state] = []
        self.state_handlers[state].append(handler)
    
    def get_valid_transitions(self, session_state: SessionState) -> List[StateTransition]:
        """Get all valid transitions from current state."""
        return [
            transition for transition in self.transitions
            if transition.can_transition(session_state)
        ]
    
    def get_next_state(self, session_state: SessionState) -> Optional[ConversationState]:
        """Determine the next state based on current state and conditions."""
        valid_transitions = self.get_valid_transitions(session_state)
        
        if not valid_transitions:
            return None
        
        # Return the first valid transition (can be enhanced with priority)
        return valid_transitions[0].to_state
    
    def transition_to(
        self,
        session_state: SessionState,
        target_state: ConversationState,
        force: bool = False
    ) -> bool:
        """
        Transition to a specific state.
        
        Args:
            session_state: Current session state
            target_state: Target state to transition to
            force: Force transition even if no valid path exists
            
        Returns:
            True if transition was successful
        """
        if force:
            session_state.update_state(target_state)
            logger.info(f"Forced transition to: {target_state.value}")
            return True
        
        # Find valid transition to target state
        for transition in self.transitions:
            if (transition.from_state == session_state.current_state and
                transition.to_state == target_state and
                transition.can_transition(session_state)):
                
                transition.execute(session_state)
                return True
        
        logger.warning(f"No valid transition from {session_state.current_state.value} to {target_state.value}")
        return False
    
    def auto_transition(self, session_state: SessionState) -> Optional[ConversationState]:
        """
        Automatically transition to next valid state.
        
        Args:
            session_state: Current session state
            
        Returns:
            New state if transition occurred, None otherwise
        """
        logger.info(f"🔄 Auto-transition check from {session_state.current_state.value}")
        valid_transitions = self.get_valid_transitions(session_state)
        
        logger.info(f"🔍 Found {len(valid_transitions)} valid transitions: {[t.to_state.value for t in valid_transitions]}")
        
        if valid_transitions:
            transition = valid_transitions[0]  # Take first valid transition
            old_state = session_state.current_state.value
            transition.execute(session_state)
            new_state = session_state.current_state.value
            logger.info(f"✅ State transitioned: {old_state} → {new_state}")
            return session_state.current_state
        else:
            logger.warning(f"⚠️ No valid transitions found from {session_state.current_state.value}")
        
        return None
    
    def handle_state(self, session_state: SessionState):
        """Execute handlers for current state."""
        current_state = session_state.current_state
        
        if current_state in self.state_handlers:
            for handler in self.state_handlers[current_state]:
                try:
                    handler(session_state)
                except Exception as e:
                    logger.error(f"Error in state handler for {current_state.value}: {e}")
    
    def get_state_progress(self, session_state: SessionState) -> Dict[str, Any]:
        """Get progress information for current state."""
        state_progress = {
            ConversationState.INIT: 0,
            ConversationState.ASK_PROJECT_TYPE: 10,
            ConversationState.ASK_LANGUAGE_PREFERENCE: 20,
            ConversationState.ASK_PROJECT_NAME_FOLDER: 30,
            ConversationState.ASK_ADDITIONAL_DETAILS: 40,
            ConversationState.CHECK_SYSTEM_CAPABILITIES: 50,
            ConversationState.VALIDATE_INFO: 60,
            ConversationState.SUMMARY_CONFIRMATION: 70,
            ConversationState.PLANNING: 80,
            ConversationState.EXECUTING: 90,
            ConversationState.VERIFYING: 95,
            ConversationState.COMPLETED: 100
        }
        
        current_progress = state_progress.get(session_state.current_state, 0)
        
        return {
            "current_state": session_state.current_state.value,
            "progress_percentage": current_progress,
            "completed_states": [
                state.value for state, progress in state_progress.items()
                if progress < current_progress
            ],
            "next_states": [
                transition.to_state.value
                for transition in self.get_valid_transitions(session_state)
            ]
        }
    
    def _setup_transitions(self):
        """Set up the conversation flow transitions."""
        
        # INIT -> ASK_PROJECT_TYPE
        self.add_transition(StateTransition(
            from_state=ConversationState.INIT,
            to_state=ConversationState.ASK_PROJECT_TYPE,
            description="Start project type interview"
        ))
        
        # ASK_PROJECT_TYPE -> ASK_PROJECT_NAME_FOLDER (AI MUST set both type and language)
        self.add_transition(StateTransition(
            from_state=ConversationState.ASK_PROJECT_TYPE,
            to_state=ConversationState.ASK_PROJECT_NAME_FOLDER,
            condition=lambda state: state.requirements.project_type is not None,
            description="AI has set project type and should have also set language - proceed immediately"
        ))
        
        # ASK_LANGUAGE_PREFERENCE -> ASK_PROJECT_NAME_FOLDER
        self.add_transition(StateTransition(
            from_state=ConversationState.ASK_LANGUAGE_PREFERENCE,
            to_state=ConversationState.ASK_PROJECT_NAME_FOLDER,
            condition=lambda state: state.requirements.language is not None,
            description="Language collected, ask for project details"
        ))
        
        # ASK_PROJECT_NAME_FOLDER -> CHECK_SYSTEM_CAPABILITIES (SKIP ADDITIONAL DETAILS)
        self.add_transition(StateTransition(
            from_state=ConversationState.ASK_PROJECT_NAME_FOLDER,
            to_state=ConversationState.CHECK_SYSTEM_CAPABILITIES,
            condition=lambda state: (state.requirements.project_name is not None and 
                                   state.requirements.folder_path is not None and
                                   # Skip additional details if AI already set database/auth/etc
                                   (state.requirements.database is not None or 
                                    not hasattr(state.requirements, 'additional_features_decided') or
                                    True)),  # Always skip to CHECK_SYSTEM_CAPABILITIES
            description="Skip additional details - AI decides everything"
        ))
        
        # ASK_PROJECT_NAME_FOLDER -> ASK_ADDITIONAL_DETAILS (FALLBACK - rarely used)
        self.add_transition(StateTransition(
            from_state=ConversationState.ASK_PROJECT_NAME_FOLDER,
            to_state=ConversationState.ASK_ADDITIONAL_DETAILS,
            condition=lambda state: (state.requirements.project_name is not None and 
                                   state.requirements.folder_path is not None and
                                   False),  # Never go here unless forced
            description="Basic info collected, ask for additional details (DEPRECATED)"
        ))
        
        # ASK_ADDITIONAL_DETAILS -> CHECK_SYSTEM_CAPABILITIES
        self.add_transition(StateTransition(
            from_state=ConversationState.ASK_ADDITIONAL_DETAILS,
            to_state=ConversationState.CHECK_SYSTEM_CAPABILITIES,
            description="Additional details collected, check system"
        ))
        
        # CHECK_SYSTEM_CAPABILITIES -> VALIDATE_INFO (MANDATORY - Must have capabilities)
        self.add_transition(StateTransition(
            from_state=ConversationState.CHECK_SYSTEM_CAPABILITIES,
            to_state=ConversationState.VALIDATE_INFO,
            condition=lambda state: (state.capabilities is not None and 
                                   hasattr(state.capabilities, 'detection_completed') and
                                   state.capabilities.detection_completed),
            description="System capabilities MUST be detected before validation"
        ))
        
        # VALIDATE_INFO -> PLANNING (Direct transition when validation complete AND user already confirmed)
        self.add_transition(StateTransition(
            from_state=ConversationState.VALIDATE_INFO,
            to_state=ConversationState.PLANNING,
            condition=lambda state: (state.capabilities is not None and
                                   hasattr(state, 'validation_completed') and
                                   getattr(state, 'validation_completed', False) and
                                   state.completion_percentage >= 80),  # User has provided most info
            description="Requirements validated and user has confirmed - proceed to planning"
        ))
        
        # VALIDATE_INFO -> SUMMARY_CONFIRMATION (MANDATORY - Must validate against capabilities)
        self.add_transition(StateTransition(
            from_state=ConversationState.VALIDATE_INFO,
            to_state=ConversationState.SUMMARY_CONFIRMATION,
            condition=lambda state: (state.capabilities is not None and
                                   hasattr(state, 'validation_completed') and
                                   getattr(state, 'validation_completed', False)),
            description="Requirements MUST be validated against capabilities"
        ))
        
        # VALIDATE_INFO -> ASK_PROJECT_TYPE (if incomplete, loop back)
        self.add_transition(StateTransition(
            from_state=ConversationState.VALIDATE_INFO,
            to_state=ConversationState.ASK_PROJECT_TYPE,
            condition=lambda state: state.completion_percentage < 100,
            description="Info incomplete, restart collection"
        ))
        
        # SUMMARY_CONFIRMATION -> PLANNING (handled by confirm_project_creation function)
        self.add_transition(StateTransition(
            from_state=ConversationState.SUMMARY_CONFIRMATION,
            to_state=ConversationState.PLANNING,
            description="User confirmed via confirm_project_creation function"
        ))
        
        # PLANNING -> EXECUTING
        self.add_transition(StateTransition(
            from_state=ConversationState.PLANNING,
            to_state=ConversationState.EXECUTING,
            condition=lambda state: (state.execution_plan is not None and 
                                   len(state.execution_plan.steps) > 0),
            description="Plan generated, start execution"
        ))
        
        # EXECUTING -> VERIFYING
        self.add_transition(StateTransition(
            from_state=ConversationState.EXECUTING,
            to_state=ConversationState.VERIFYING,
            condition=lambda state: len(state.execution_results) > 0,
            description="Commands executed, verify results"
        ))
        
        # VERIFYING -> COMPLETED
        self.add_transition(StateTransition(
            from_state=ConversationState.VERIFYING,
            to_state=ConversationState.COMPLETED,
            description="Verification passed, project complete"
        ))
        
        # Error transitions from any state
        for state in ConversationState:
            if state not in [ConversationState.ERROR, ConversationState.ABORTED]:
                self.add_transition(StateTransition(
                    from_state=state,
                    to_state=ConversationState.ERROR,
                    condition=lambda session_state: session_state.error_message is not None,
                    description="Error occurred"
                ))
                
                self.add_transition(StateTransition(
                    from_state=state,
                    to_state=ConversationState.ABORTED,
                    description="User aborted"
                ))
    
    def get_state_instructions(self, state: ConversationState) -> str:
        """Get instructions for AI agent based on current state."""
        instructions = {
            ConversationState.INIT: """
                🚨 CRITICAL: YOU ARE IN INIT STATE - EXTREMELY LIMITED ACTIONS!
                
                ONLY 2 ACTIONS ALLOWED:
                1. Greet user and ask for permission via request_permission function
                2. After permission granted: IMMEDIATELY STOP - state will auto-advance
                
                🚫 ABSOLUTELY FORBIDDEN IN INIT STATE:
                - update_project_requirements (BLOCKED - will cause error)
                - create_project_with_steps (BLOCKED - will cause error)
                - generate_file_content (BLOCKED - will cause error) 
                - fail_technology_and_switch (BLOCKED - will cause error)
                - ANY project creation functions (BLOCKED - will cause error)
                
                🎯 YOUR ONLY JOB IN INIT STATE:
                1. If no permissions: Ask for permission
                2. If permissions granted: WAIT for automatic state transition
                
                DO NOT discuss project details in INIT state!
                DO NOT try to collect requirements in INIT state!
                DO NOT call any project-related functions in INIT state!
                
                The state machine will automatically advance you to ASK_PROJECT_TYPE 
                where you can properly collect requirements.
            """,
            
            ConversationState.ASK_PROJECT_TYPE: """
                ASK ONLY FOR APP REQUIREMENTS - AUTO-DECIDE EVERYTHING ELSE!
                
                1. Simply ask: "What do you want to build? Describe your app idea."
                2. Listen to their description
                3. AUTOMATICALLY decide EVERYTHING:
                   - Project type
                   - Programming language
                   - Framework
                   - Database (if needed)
                   - Authentication (if needed)
                   - Additional features
                
                SMART FRAMEWORK SELECTION BASED ON REQUIREMENTS:
                
                REST API:
                - Python available → FastAPI (modern, fast, auto-docs)
                - Node.js available → Express + TypeScript
                - Both available → Choose FastAPI for better performance
                
                Web Application:
                - Frontend: React (if Node.js available)
                - Backend: FastAPI (Python) or Express (Node.js)
                - Full-stack: Next.js if Node.js available
                
                CLI Tool:
                - Python → Click or Typer (modern CLI frameworks)
                - Node.js → Commander.js
                
                Mobile App:
                - React Native (if Node.js available)
                - Flutter (if Dart available)
                
                AUTOMATIC FEATURE DECISIONS:
                - E-commerce/Social/SaaS → Add PostgreSQL + Auth + Redis
                - API/Backend → Add PostgreSQL + JWT Auth
                - CLI/Script → No database, no auth
                - Static Site → No backend, just HTML/CSS/JS
                
                EXAMPLE RESPONSE:
                User: "I want to build a task management API"
                AI: "Perfect! I'll create a task management REST API using:
                     • Python with FastAPI for blazing-fast performance
                     • PostgreSQL for data persistence
                     • JWT authentication for secure access
                     • Docker setup for easy deployment
                     • Comprehensive test suite with pytest
                     
                     All these tools are available on your system and perfectly suited for your project!"
                
                IMMEDIATELY CALL update_project_requirements with ALL fields:
                - project_type, language, framework (auto-decided based on requirements)  
                - project_name (inferred from description or use a good default)
                - folder_path (suggest "./[project_name]" or ask user preference)
                - database, authentication, testing, docker (auto-decided)
                
                EXAMPLE: If user says "todo app", immediately call update_project_requirements with:
                project_type="cli", language="python", project_name="todo-app", 
                folder_path="./todo-app", framework="click"
            """,
            
            ConversationState.ASK_LANGUAGE_PREFERENCE: """
                ⚠️ THIS STATE SHOULD ALMOST NEVER BE REACHED!
                
                The AI should have already auto-selected the best language based on:
                - User's app requirements
                - Available system capabilities
                - Best practices for the project type
                
                This state exists ONLY as a fallback if somehow language wasn't set.
                If you reach this state, something went wrong - the AI should have already
                made an intelligent choice in ASK_PROJECT_TYPE state.
                
                If forced to use this state:
                - Don't ask "What language do you want?"
                - Instead say: "I notice I haven't selected a technology yet. Based on your 
                  system capabilities, I recommend [best available option]."
                - Then immediately set the language and continue
                
                REMEMBER: Users shouldn't need to think about languages/frameworks.
                They describe what they want, we build it with their best available tools.
            """,
            
            ConversationState.ASK_PROJECT_NAME_FOLDER: """
                FIRST: Check if language is set. If not, AUTO-SET IT based on project type and capabilities!
                
                LANGUAGE AUTO-SELECTION (if missing):
                - Mobile app + Node.js available → React Native (JavaScript)
                - Mobile app + Python available → Python with Kivy/Flask API
                - Web API + Python available → Python with FastAPI
                - Web API + Node.js available → Node.js with Express
                - CLI tool + Python available → Python
                
                Then ask for:
                1. Project name (suggest based on their description)  
                2. Folder path where they want to create it
                
                IMMEDIATELY call update_project_requirements if language was missing!
            """,
            
            ConversationState.ASK_ADDITIONAL_DETAILS: """
                DO NOT ASK ABOUT TECHNICAL DETAILS - AUTO-DECIDE EVERYTHING!
                
                Based on the user's app requirements, AUTOMATICALLY decide:
                - Database: Choose based on app type (API→PostgreSQL, Simple→SQLite, None if not needed)
                - Authentication: Add if app involves users/security
                - Testing: Always include (good practice)
                - Docker: Include for production-ready apps
                - Framework specifics: Auto-select best options
                
                SKIP THIS STATE if possible - go straight to CHECK_SYSTEM_CAPABILITIES
                
                The AI should intelligently infer what's needed:
                - "E-commerce site" → Needs database, auth, payment integration
                - "CLI tool" → Probably no database or auth needed
                - "REST API" → Needs database, possibly auth
                - "Static website" → No database or auth needed
                
                DO NOT ASK USER - just set these in requirements automatically!
            """,
            
            ConversationState.CHECK_SYSTEM_CAPABILITIES: """
                🚨 MANDATORY FIRST STEP: IF capabilities are missing, call detect_system_capabilities immediately!
                
                CHECK: If session_state.capabilities is None or missing detection_completed=True:
                → IMMEDIATELY call detect_system_capabilities(force_refresh=False)
                → This function is REQUIRED for state progression!
                
                CAPABILITIES SHOULD ALREADY BE DETECTED (auto-detected after permissions).
                
                This state is for CONFIRMING the auto-selected tech stack is available.
                The AI should have already chosen the language/framework in ASK_PROJECT_TYPE.
                
                🚨 RECOVERY CONTEXT CHECK:
                If the last function call returned 'ai_recovery_needed', this means a command FAILED.
                You MUST analyze the failure and choose a DIFFERENT approach:
                
                RECOVERY ANALYSIS:
                1. Check function_results for failed_command and error_details
                2. Understand WHY it failed (template issues, deprecated commands, missing tools)
                3. Choose COMPLETELY DIFFERENT approach - don't repeat same command!
                
                RECOVERY EXAMPLES:
                - React Native template fails → Use Expo CLI instead: "npx create-expo-app"  
                - React Native fails → Switch to Flutter: "flutter create"
                - Mobile fails → Create web app that works on mobile
                - Node.js issue → Switch to Python Flask API
                
                PROCESS:
                1. Capabilities should already exist from auto-detection after permissions
                2. If RECOVERY needed → Analyze failure and switch technology stack completely
                3. If normal flow → Verify the AI's auto-selected language/framework is available
                4. If available → Continue without any questions
                5. If not available → Auto-select next best alternative without asking
                
                INTELLIGENT AUTO-SELECTION:
                - User wants API + has Python → Use FastAPI
                - User wants API + has Node.js → Use Express
                - User wants CLI + has Python → Use Click
                - User wants web app + has Node.js → Use React/Vue
                - User wants web app + has Python → Use Django/Flask
                
                NEVER ASK USER TO CHOOSE - ALWAYS AUTO-SELECT!
                NEVER REPEAT FAILED COMMANDS - LEARN FROM ERRORS!
                
                Example: "✅ Perfect! Python 3.12 and FastAPI are ready for your API project."
            """,
            
            ConversationState.VALIDATE_INFO: """
                🚨 MANDATORY: YOU MUST CALL validate_requirements_against_capabilities FUNCTION!
                
                STEP 1: ALWAYS call validate_requirements_against_capabilities(auto_correct=True) FIRST
                This function is REQUIRED to advance to the next state!
                
                STEP 2: Check if last function returned 'ai_recovery_needed' (previous commands FAILED!)
                If recovery needed - SWITCH TECHNOLOGY COMPLETELY:
                - React Native failed → Use Expo: "npx create-expo-app"
                - React Native still failing → Use Flutter or Swift  
                - Mobile frameworks failing → Create Progressive Web App
                - Node.js issues → Switch to Python Flask
                
                If recovery needed, call update_project_requirements with DIFFERENT framework!
                DO NOT use the same technology that failed!
                
                INTELLIGENT SELF-CORRECTION WITH AUTO-ADAPTATION:
                
                The validate_requirements_against_capabilities function will:
                - Check if your selected tech stack works with their system
                - Auto-correct to better alternatives if needed
                - Set validation_completed flag (required for state progression)
                
                SELF-CORRECTION INTELLIGENCE:
                - Analyze WHAT the user wants to achieve (not just the tech they mentioned)
                - Find the BEST available alternative that meets their goals
                - Consider performance, ecosystem, learning curve, and maintenance
                - Explain WHY the alternative is actually better for their use case
                
                SMART DECISION EXAMPLES:
                - User wants "Rust API" but no Rust → "Python FastAPI delivers similar performance with easier maintenance"
                - User wants "React Native" but commands fail → "Expo provides better developer experience and no CLI issues"
                - User wants "Django" but old Python → "FastAPI with your Python 3.12 gives better async performance"
                - React Native deprecated errors → "Swift native development offers better performance and no CLI compatibility issues"
                
                AUTO-ADAPTATION FLOW:
                1. CALL validate_requirements_against_capabilities(auto_correct=True) - MANDATORY!
                2. Check for failed commands - if found, CHANGE TECHNOLOGY!
                3. Detect missing/incompatible tools
                4. Analyze project requirements and user goals  
                5. Select optimal available alternative
                6. Present as an IMPROVEMENT, not a fallback
                7. "Based on your system, I found an even better approach..."
                
                ALWAYS frame alternatives as advantages, not compromises!
                NEVER REPEAT FAILED COMMANDS - LEARN FROM ERRORS!
            """,
            
            ConversationState.SUMMARY_CONFIRMATION: """
                Present a clear summary of what will be created:
                - Project type and stack
                - Features to include  
                - Where it will be created
                - What commands will be run
                
                Ask the user: "Does this look good? Should I proceed with creating your project?"
                
                After the user responds, call confirm_project_creation function:
                - If they say yes/ok/proceed/looks good: call with user_confirmed=true
                - If they want changes: call with user_confirmed=false
                
                Let the AI intelligently interpret their response - don't use hardcoded keyword matching.
            """,
            
            ConversationState.PLANNING: """
                CRITICAL: You MUST use AI to generate project creation steps dynamically!
                
                ⚠️ EXACT FUNCTION NAMES TO USE (case-sensitive):
                1. First: ai_generate_project_steps
                2. Then: create_project_with_steps
                
                WORKFLOW:
                1. VERIFY requirements are saved: Check session_state has project_name, project_type, folder_path
                   If ANY are missing, call update_project_requirements FIRST with extracted values
                2. Call the function named EXACTLY: ai_generate_project_steps
                   Parameters: requirements_summary="User wants to create a [project_type] using [language/framework] with [specific features]..."
                3. Take the AI-generated steps and call the function named EXACTLY: create_project_with_steps
                   Parameters: steps=[...AI generated steps from previous function...]
                
                IMPORTANT: Function names are lowercase with underscores, NOT camelCase or PascalCase!
                - ✅ CORRECT: create_project_with_steps
                - ❌ WRONG: CreateProjectWithSteps, CreateProjectWithStepsSteps
                
                WHY USE AI GENERATION:
                - No hardcoded assumptions about technology stacks
                - Dynamically adapts to ANY language/framework combination
                - Generates appropriate file content for the specific stack
                - Considers user's system capabilities
                - Creates comprehensive, working projects
                
                EXAMPLE with EXACT function names:
                1. Call: ai_generate_project_steps with requirements_summary="User wants CLI tool in Python"
                2. Call: create_project_with_steps with steps=[...the steps returned from above...]
                
                DO NOT hardcode anything - let AI generate everything based on user requirements!
                CALL THE AI FUNCTIONS IMMEDIATELY with the EXACT names shown above!
            """,
            
            ConversationState.EXECUTING: """
                Execute the plan step by step.
                Stream output to the user in real-time.
                Handle errors with fallback strategies.
                Keep the user informed of progress.
            """,
            
            ConversationState.VERIFYING: """
                Run verification tests to ensure the project works.
                Check that dependencies are installed correctly.
                Verify the project structure is correct.
                Test basic functionality if possible.
            """,
            
            ConversationState.COMPLETED: """
                Congratulate the user on successful project creation.
                Provide next steps and suggestions.
                Offer to create documentation or additional features.
                Ask if they need help with anything else.
            """
        }
        
        return instructions.get(state, "Continue the conversation naturally.").strip()


# Global state machine instance
conversation_state_machine = ConversationStateMachine()