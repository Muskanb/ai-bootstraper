"""Execution plan generation."""
import os
from typing import Dict, List, Any
from datetime import datetime
import logging

from backend.models.schemas import (
    ProjectRequirements, SystemCapability, ExecutionPlan, ExecutionStep
)
from backend.capabilities.mappers import toolchain_mapper
from backend.planning.templates import template_generator

logger = logging.getLogger(__name__)


class ExecutionPlanner:
    """Generate execution plans for project creation."""
    
    def __init__(self):
        """Initialize execution planner."""
        pass
    
    async def generate_execution_plan(
        self,
        requirements: ProjectRequirements,
        capabilities: SystemCapability
    ) -> ExecutionPlan:
        """
        Generate complete execution plan.
        
        Args:
            requirements: Project requirements
            capabilities: System capabilities
            
        Returns:
            Complete execution plan
        """
        logger.info(f"Generating execution plan for {requirements.project_type} project")
        
        # Get appropriate toolchain
        toolchain = await toolchain_mapper.map_requirements_to_toolchain(
            requirements, capabilities
        )
        
        # Generate steps
        steps = []
        
        # 1. Create project directory
        steps.extend(self._generate_directory_steps(requirements))
        
        # 2. Generate project files
        steps.extend(self._generate_file_creation_steps(requirements))
        
        # 3. Setup development environment
        steps.extend(self._generate_environment_steps(requirements, toolchain, capabilities))
        
        # 4. Install dependencies
        steps.extend(self._generate_dependency_steps(requirements, toolchain, capabilities))
        
        # 5. Database setup (if needed)
        if requirements.database:
            steps.extend(self._generate_database_steps(requirements))
        
        # 6. Docker setup (if needed)
        if requirements.docker:
            steps.extend(self._generate_docker_steps(requirements))
        
        # 7. Testing setup (if needed)
        if requirements.testing:
            steps.extend(self._generate_testing_steps(requirements, capabilities))
        
        # Create execution plan
        plan = ExecutionPlan(
            steps=steps,
            total_steps=len(steps),
            estimated_duration=self._estimate_duration(steps),
            requires_permissions=self._extract_required_permissions(steps),
            created_at=datetime.now()
        )
        
        logger.info(f"Generated execution plan with {len(steps)} steps")
        return plan
    
    def _generate_directory_steps(self, requirements: ProjectRequirements) -> List[ExecutionStep]:
        """Generate directory creation steps."""
        steps = []
        
        project_path = requirements.folder_path or f"./{requirements.project_name}"
        
        # Create main project directory
        steps.append(ExecutionStep(
            command=f"mkdir -p {project_path}",
            description=f"Create project directory: {project_path}",
            working_directory=".",
            timeout=10
        ))
        
        # Create subdirectories
        directories = template_generator._get_directory_structure(requirements)
        for directory in directories:
            dir_path = os.path.join(project_path, directory)
            steps.append(ExecutionStep(
                command=f"mkdir -p {dir_path}",
                description=f"Create directory: {directory}",
                working_directory=".",
                timeout=10
            ))
        
        return steps
    
    def _generate_file_creation_steps(self, requirements: ProjectRequirements) -> List[ExecutionStep]:
        """Generate file creation steps."""
        steps = []
        
        project_path = requirements.folder_path or f"./{requirements.project_name}"
        
        # Generate project files
        files_to_create = template_generator.generate_project_files(project_path, requirements)
        
        for file_info in files_to_create:
            if file_info["type"] == "file":
                # Create file with content
                file_path = file_info["path"]
                content = file_info["content"].replace('\n', '\\n').replace('"', '\\"')
                
                steps.append(ExecutionStep(
                    command=f'echo "{content}" > "{file_path}"',
                    description=f"Create file: {file_info['name']}",
                    working_directory=".",
                    timeout=10
                ))
        
        return steps
    
    def _generate_environment_steps(
        self, 
        requirements: ProjectRequirements,
        toolchain: Dict[str, Any],
        capabilities: SystemCapability
    ) -> List[ExecutionStep]:
        """Generate environment setup steps."""
        steps = []
        
        language = requirements.language.lower() if requirements.language else ""
        project_path = requirements.folder_path or f"./{requirements.project_name}"
        
        if language == "python":
            # Determine Python command
            python_cmd = "python3" if capabilities.python_version else "python"
            
            # Create virtual environment
            steps.append(ExecutionStep(
                command=f"{python_cmd} -m venv venv",
                description="Create Python virtual environment",
                working_directory=project_path,
                fallback_command=f"virtualenv venv",
                timeout=60
            ))
            
            # Activate virtual environment (for Unix-like systems)
            if capabilities.os != "Windows":
                steps.append(ExecutionStep(
                    command="source venv/bin/activate",
                    description="Activate virtual environment",
                    working_directory=project_path,
                    timeout=10
                ))
        
        elif language in ["javascript", "node"]:
            # Initialize npm project if package.json doesn't exist
            steps.append(ExecutionStep(
                command="npm init -y",
                description="Initialize npm project",
                working_directory=project_path,
                timeout=30
            ))
        
        return steps
    
    def _generate_dependency_steps(
        self,
        requirements: ProjectRequirements,
        toolchain: Dict[str, Any],
        capabilities: SystemCapability
    ) -> List[ExecutionStep]:
        """Generate dependency installation steps."""
        steps = []
        
        language = requirements.language.lower() if requirements.language else ""
        project_path = requirements.folder_path or f"./{requirements.project_name}"
        
        if language == "python":
            # Install Python dependencies
            pip_cmd = "pip3" if "pip3" in capabilities.available_package_managers else "pip"
            
            steps.append(ExecutionStep(
                command=f"{pip_cmd} install -r requirements.txt",
                description="Install Python dependencies",
                working_directory=project_path,
                fallback_command=f"python -m pip install -r requirements.txt",
                timeout=300
            ))
        
        elif language in ["javascript", "node"]:
            # Install Node.js dependencies
            npm_cmd = "npm"
            if "yarn" in capabilities.available_package_managers:
                npm_cmd = "yarn"
            
            steps.append(ExecutionStep(
                command=f"{npm_cmd} install",
                description="Install Node.js dependencies",
                working_directory=project_path,
                fallback_command="npm install --legacy-peer-deps",
                timeout=300
            ))
        
        return steps
    
    def _generate_database_steps(self, requirements: ProjectRequirements) -> List[ExecutionStep]:
        """Generate database setup steps."""
        steps = []
        
        database = requirements.database.lower()
        project_path = requirements.folder_path or f"./{requirements.project_name}"
        
        if database == "sqlite":
            # SQLite setup is usually automatic
            steps.append(ExecutionStep(
                command="touch database.db",
                description="Create SQLite database file",
                working_directory=project_path,
                timeout=10
            ))
        
        elif database == "postgresql":
            steps.append(ExecutionStep(
                command="echo 'DATABASE_URL=postgresql://user:password@localhost/database' >> .env",
                description="Create PostgreSQL connection template",
                working_directory=project_path,
                timeout=10
            ))
        
        elif database == "mysql":
            steps.append(ExecutionStep(
                command="echo 'DATABASE_URL=mysql://user:password@localhost/database' >> .env",
                description="Create MySQL connection template",
                working_directory=project_path,
                timeout=10
            ))
        
        return steps
    
    def _generate_docker_steps(self, requirements: ProjectRequirements) -> List[ExecutionStep]:
        """Generate Docker setup steps."""
        steps = []
        
        project_path = requirements.folder_path or f"./{requirements.project_name}"
        project_name = requirements.project_name or "my-app"
        
        # Build Docker image
        steps.append(ExecutionStep(
            command=f"docker build -t {project_name} .",
            description="Build Docker image",
            working_directory=project_path,
            timeout=600,
            requires_permission=True
        ))
        
        return steps
    
    def _generate_testing_steps(
        self,
        requirements: ProjectRequirements,
        capabilities: SystemCapability
    ) -> List[ExecutionStep]:
        """Generate testing setup steps."""
        steps = []
        
        language = requirements.language.lower() if requirements.language else ""
        project_path = requirements.folder_path or f"./{requirements.project_name}"
        
        if language == "python":
            steps.append(ExecutionStep(
                command="pytest --version",
                description="Verify pytest installation",
                working_directory=project_path,
                fallback_command="python -m pytest --version",
                timeout=30
            ))
        
        elif language in ["javascript", "node"]:
            steps.append(ExecutionStep(
                command="npm test -- --passWithNoTests",
                description="Run initial test suite",
                working_directory=project_path,
                timeout=60
            ))
        
        return steps
    
    def _estimate_duration(self, steps: List[ExecutionStep]) -> int:
        """Estimate total execution duration."""
        base_duration = sum(step.timeout for step in steps)
        
        # Add buffer for setup and processing
        return int(base_duration * 1.2)
    
    def _extract_required_permissions(self, steps: List[ExecutionStep]) -> List[str]:
        """Extract required permissions from steps."""
        permissions = []
        
        for step in steps:
            if step.requires_permission:
                permissions.append(f"Execute: {step.command}")
            
            # Check for commands that need special permissions
            if any(keyword in step.command.lower() for keyword in ["sudo", "docker", "systemctl"]):
                permissions.append(f"System command: {step.command}")
        
        return list(set(permissions))


# Global planner instance
execution_planner = ExecutionPlanner()