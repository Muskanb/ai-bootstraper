"""Map requirements to toolchains based on capabilities."""
from typing import Dict, List, Optional, Any
import logging

from backend.models.schemas import ProjectRequirements, SystemCapability, ExecutionPlan, ExecutionStep
from backend.capabilities.detector import capability_detector

logger = logging.getLogger(__name__)


class ToolchainMapper:
    """Map project requirements to appropriate toolchains."""
    
    def __init__(self):
        """Initialize toolchain mapper."""
        self.toolchain_templates = self._load_toolchain_templates()
    
    async def map_requirements_to_toolchain(
        self,
        requirements: ProjectRequirements,
        capabilities: SystemCapability
    ) -> Dict[str, Any]:
        """
        Map project requirements to best available toolchain.
        
        Args:
            requirements: Project requirements
            capabilities: System capabilities
            
        Returns:
            Recommended toolchain configuration
        """
        logger.info(f"Mapping requirements to toolchain: {requirements.project_type}")
        
        # Find compatible toolchains
        compatible_toolchains = self._find_compatible_toolchains(requirements, capabilities)
        
        if not compatible_toolchains:
            raise ValueError(f"No compatible toolchain found for {requirements.project_type} with {requirements.language}")
        
        # Select best toolchain (first one for now, can be enhanced with scoring)
        selected_toolchain = compatible_toolchains[0]
        
        # Customize toolchain based on specific requirements
        customized_toolchain = self._customize_toolchain(
            selected_toolchain,
            requirements,
            capabilities
        )
        
        logger.info(f"Selected toolchain: {customized_toolchain['name']}")
        return customized_toolchain
    
    def _find_compatible_toolchains(
        self,
        requirements: ProjectRequirements,
        capabilities: SystemCapability
    ) -> List[Dict[str, Any]]:
        """Find toolchains compatible with requirements and capabilities."""
        compatible = []
        
        project_type = requirements.project_type.value if requirements.project_type else None
        language = requirements.language.lower() if requirements.language else None
        
        for toolchain in self.toolchain_templates:
            # Check project type compatibility
            if project_type not in toolchain.get("supported_project_types", []):
                continue
            
            # Check language compatibility
            if language not in toolchain.get("supported_languages", []):
                continue
            
            # Check system capabilities
            if self._check_toolchain_compatibility(toolchain, capabilities):
                compatible.append(toolchain)
        
        # Sort by preference/score (can be enhanced)
        compatible.sort(key=lambda x: x.get("priority", 0), reverse=True)
        
        return compatible
    
    def _check_toolchain_compatibility(
        self,
        toolchain: Dict[str, Any],
        capabilities: SystemCapability
    ) -> bool:
        """Check if toolchain is compatible with system capabilities."""
        required_tools = toolchain.get("required_tools", [])
        
        for tool in required_tools:
            tool_name = tool.get("name")
            
            # Check if tool is available
            if tool_name == "python" and not capabilities.python_version:
                return False
            elif tool_name == "node" and not capabilities.node_version:
                return False
            elif tool_name == "docker" and not capabilities.docker_installed:
                return False
            elif tool_name == "git" and not capabilities.git_installed:
                return False
            elif tool_name in capabilities.available_package_managers:
                continue
            elif tool_name in capabilities.available_runtimes:
                continue
            else:
                # Tool not found - check if it's optional
                if not tool.get("optional", False):
                    return False
        
        return True
    
    def _customize_toolchain(
        self,
        toolchain: Dict[str, Any],
        requirements: ProjectRequirements,
        capabilities: SystemCapability
    ) -> Dict[str, Any]:
        """Customize toolchain based on specific requirements."""
        customized = toolchain.copy()
        
        # Add database-specific dependencies
        if requirements.database:
            db_deps = self._get_database_dependencies(requirements.database, requirements.language)
            customized["dependencies"].extend(db_deps)
        
        # Add authentication dependencies
        if requirements.authentication:
            auth_deps = self._get_authentication_dependencies(requirements.language, requirements.framework)
            customized["dependencies"].extend(auth_deps)
        
        # Add testing dependencies
        if requirements.testing:
            test_deps = self._get_testing_dependencies(requirements.language, requirements.framework)
            customized["dependencies"].extend(test_deps)
        
        # Add Docker configuration
        if requirements.docker:
            docker_config = self._get_docker_configuration(requirements.language, requirements.framework)
            customized["docker"] = docker_config
        
        # Customize commands based on available package managers
        customized = self._adapt_commands_to_capabilities(customized, capabilities)
        
        return customized
    
    def _get_database_dependencies(self, database: str, language: Optional[str]) -> List[Dict[str, Any]]:
        """Get database-specific dependencies."""
        db_deps = {
            "sqlite": {
                "python": [{"name": "sqlite3", "type": "builtin"}],
                "node": [{"name": "sqlite3", "type": "npm"}],
                "javascript": [{"name": "sqlite3", "type": "npm"}]
            },
            "postgresql": {
                "python": [{"name": "psycopg2-binary", "type": "pip"}],
                "node": [{"name": "pg", "type": "npm"}],
                "javascript": [{"name": "pg", "type": "npm"}]
            },
            "mysql": {
                "python": [{"name": "mysql-connector-python", "type": "pip"}],
                "node": [{"name": "mysql2", "type": "npm"}],
                "javascript": [{"name": "mysql2", "type": "npm"}]
            },
            "mongodb": {
                "python": [{"name": "pymongo", "type": "pip"}],
                "node": [{"name": "mongodb", "type": "npm"}],
                "javascript": [{"name": "mongodb", "type": "npm"}]
            }
        }
        
        if database.lower() in db_deps and language and language.lower() in db_deps[database.lower()]:
            return db_deps[database.lower()][language.lower()]
        
        return []
    
    def _get_authentication_dependencies(self, language: Optional[str], framework: Optional[str]) -> List[Dict[str, Any]]:
        """Get authentication dependencies."""
        auth_deps = {
            "python": {
                "fastapi": [{"name": "python-jose[cryptography]", "type": "pip"}, {"name": "passlib[bcrypt]", "type": "pip"}],
                "django": [{"name": "djangorestframework-simplejwt", "type": "pip"}],
                "flask": [{"name": "Flask-JWT-Extended", "type": "pip"}]
            },
            "javascript": {
                "express": [{"name": "jsonwebtoken", "type": "npm"}, {"name": "bcryptjs", "type": "npm"}],
                "react": [{"name": "@auth0/auth0-react", "type": "npm"}],
                "vue": [{"name": "@auth0/auth0-vue", "type": "npm"}]
            }
        }
        
        if language and language.lower() in auth_deps:
            if framework and framework.lower() in auth_deps[language.lower()]:
                return auth_deps[language.lower()][framework.lower()]
        
        return []
    
    def _get_testing_dependencies(self, language: Optional[str], framework: Optional[str]) -> List[Dict[str, Any]]:
        """Get testing framework dependencies."""
        test_deps = {
            "python": [
                {"name": "pytest", "type": "pip"},
                {"name": "pytest-asyncio", "type": "pip"}
            ],
            "javascript": [
                {"name": "jest", "type": "npm"},
                {"name": "@testing-library/jest-dom", "type": "npm"}
            ]
        }
        
        if language and language.lower() in test_deps:
            return test_deps[language.lower()]
        
        return []
    
    def _get_docker_configuration(self, language: Optional[str], framework: Optional[str]) -> Dict[str, Any]:
        """Get Docker configuration."""
        docker_configs = {
            "python": {
                "base_image": "python:3.11-slim",
                "port": 8000,
                "install_cmd": "pip install -r requirements.txt",
                "start_cmd": "python -m uvicorn main:app --host 0.0.0.0 --port 8000"
            },
            "javascript": {
                "base_image": "node:18-alpine",
                "port": 3000,
                "install_cmd": "npm install",
                "start_cmd": "npm start"
            }
        }
        
        if language and language.lower() in docker_configs:
            return docker_configs[language.lower()]
        
        return {
            "base_image": "ubuntu:22.04",
            "port": 8080,
            "install_cmd": "echo 'No install command'",
            "start_cmd": "echo 'No start command'"
        }
    
    def _adapt_commands_to_capabilities(
        self,
        toolchain: Dict[str, Any],
        capabilities: SystemCapability
    ) -> Dict[str, Any]:
        """Adapt toolchain commands based on available capabilities."""
        # Adapt Python commands
        if "python" in toolchain.get("required_tools", []):
            python_cmd = "python3" if capabilities.python_version and "python3" in capabilities.available_runtimes else "python"
            
            # Replace python commands in setup steps
            for step in toolchain.get("setup_steps", []):
                if "python " in step.get("command", ""):
                    step["command"] = step["command"].replace("python ", f"{python_cmd} ")
        
        # Adapt package manager commands
        available_managers = capabilities.available_package_managers
        
        if "pip" in available_managers:
            pip_cmd = "pip"
        elif "pip3" in available_managers:
            pip_cmd = "pip3"
        else:
            pip_cmd = "pip"  # Fallback
        
        # Replace pip commands
        for step in toolchain.get("setup_steps", []):
            if "pip " in step.get("command", ""):
                step["command"] = step["command"].replace("pip ", f"{pip_cmd} ")
        
        return toolchain
    
    def _load_toolchain_templates(self) -> List[Dict[str, Any]]:
        """Load toolchain templates."""
        return [
            {
                "name": "Python FastAPI",
                "supported_project_types": ["web_api", "microservice"],
                "supported_languages": ["python"],
                "priority": 90,
                "required_tools": [
                    {"name": "python", "optional": False},
                    {"name": "pip", "optional": False}
                ],
                "dependencies": [
                    {"name": "fastapi", "type": "pip"},
                    {"name": "uvicorn[standard]", "type": "pip"}
                ],
                "setup_steps": [
                    {
                        "command": "python -m venv venv",
                        "description": "Create virtual environment",
                        "working_directory": "{project_path}"
                    },
                    {
                        "command": "pip install -r requirements.txt",
                        "description": "Install dependencies",
                        "working_directory": "{project_path}"
                    }
                ],
                "start_command": "uvicorn main:app --reload",
                "test_command": "pytest"
            },
            
            {
                "name": "Node.js Express",
                "supported_project_types": ["web_api", "fullstack"],
                "supported_languages": ["javascript", "node"],
                "priority": 85,
                "required_tools": [
                    {"name": "node", "optional": False},
                    {"name": "npm", "optional": False}
                ],
                "dependencies": [
                    {"name": "express", "type": "npm"},
                    {"name": "cors", "type": "npm"},
                    {"name": "helmet", "type": "npm"}
                ],
                "setup_steps": [
                    {
                        "command": "npm init -y",
                        "description": "Initialize npm project",
                        "working_directory": "{project_path}"
                    },
                    {
                        "command": "npm install",
                        "description": "Install dependencies",
                        "working_directory": "{project_path}"
                    }
                ],
                "start_command": "npm start",
                "test_command": "npm test"
            },
            
            {
                "name": "React Frontend",
                "supported_project_types": ["frontend", "fullstack"],
                "supported_languages": ["javascript", "typescript"],
                "priority": 88,
                "required_tools": [
                    {"name": "node", "optional": False},
                    {"name": "npm", "optional": False}
                ],
                "dependencies": [
                    {"name": "react", "type": "npm"},
                    {"name": "react-dom", "type": "npm"}
                ],
                "setup_steps": [
                    {
                        "command": "npx create-react-app {project_name}",
                        "description": "Create React application",
                        "working_directory": "{project_parent_path}"
                    }
                ],
                "start_command": "npm start",
                "test_command": "npm test"
            },
            
            {
                "name": "Vue.js Frontend",
                "supported_project_types": ["frontend", "fullstack"],
                "supported_languages": ["javascript", "typescript"],
                "priority": 87,
                "required_tools": [
                    {"name": "node", "optional": False},
                    {"name": "npm", "optional": False}
                ],
                "dependencies": [
                    {"name": "vue", "type": "npm"}
                ],
                "setup_steps": [
                    {
                        "command": "npm create vue@latest {project_name}",
                        "description": "Create Vue.js application",
                        "working_directory": "{project_parent_path}"
                    }
                ],
                "start_command": "npm run dev",
                "test_command": "npm run test"
            },
            
            {
                "name": "Python CLI",
                "supported_project_types": ["cli"],
                "supported_languages": ["python"],
                "priority": 85,
                "required_tools": [
                    {"name": "python", "optional": False},
                    {"name": "pip", "optional": False}
                ],
                "dependencies": [
                    {"name": "click", "type": "pip"},
                    {"name": "typer", "type": "pip"}
                ],
                "setup_steps": [
                    {
                        "command": "python -m venv venv",
                        "description": "Create virtual environment",
                        "working_directory": "{project_path}"
                    },
                    {
                        "command": "pip install -r requirements.txt",
                        "description": "Install dependencies",
                        "working_directory": "{project_path}"
                    }
                ],
                "start_command": "python main.py",
                "test_command": "pytest"
            },
            
            {
                "name": "Python Fullstack (FastAPI + React)",
                "supported_project_types": ["fullstack"],
                "supported_languages": ["python"],
                "priority": 87,
                "required_tools": [
                    {"name": "python", "optional": False},
                    {"name": "pip", "optional": False},
                    {"name": "node", "optional": False},
                    {"name": "npm", "optional": False}
                ],
                "dependencies": [
                    {"name": "fastapi", "type": "pip"},
                    {"name": "uvicorn[standard]", "type": "pip"},
                    {"name": "sqlalchemy", "type": "pip"},
                    {"name": "pydantic", "type": "pip"}
                ],
                "setup_steps": [
                    {
                        "command": "python -m venv venv",
                        "description": "Create Python virtual environment",
                        "working_directory": "{project_path}/backend"
                    },
                    {
                        "command": "pip install -r requirements.txt",
                        "description": "Install Python dependencies",
                        "working_directory": "{project_path}/backend"
                    },
                    {
                        "command": "npx create-react-app frontend",
                        "description": "Create React frontend",
                        "working_directory": "{project_path}"
                    }
                ],
                "start_command": "uvicorn main:app --reload",
                "test_command": "pytest"
            },
            
            # Mobile App Templates
            {
                "name": "React Native",
                "supported_project_types": ["mobile_app"],
                "supported_languages": ["javascript", "typescript", "react native"],
                "priority": 90,
                "required_tools": [
                    {"name": "node", "optional": False},
                    {"name": "npm", "optional": False}
                ],
                "dependencies": [
                    {"name": "react-native", "type": "npm"},
                    {"name": "react", "type": "npm"}
                ],
                "setup_steps": [
                    {
                        "command": "npx react-native init {project_name}",
                        "description": "Initialize React Native project",
                        "working_directory": "{project_parent_path}"
                    }
                ],
                "start_command": "npx react-native run-ios",
                "test_command": "npm test"
            },
            
            {
                "name": "Kotlin Android",
                "supported_project_types": ["mobile_app"],
                "supported_languages": ["kotlin", "java", "android"],
                "priority": 88,
                "required_tools": [
                    {"name": "java", "optional": False}
                ],
                "dependencies": [],
                "setup_steps": [
                    {
                        "command": "mkdir -p {project_path}",
                        "description": "Create project directory",
                        "working_directory": "."
                    },
                    {
                        "command": "mkdir -p app/src/main/java/com/example/{project_name}",
                        "description": "Create source directories",
                        "working_directory": "{project_path}"
                    },
                    {
                        "command": "mkdir -p app/src/main/res/layout",
                        "description": "Create resource directories",
                        "working_directory": "{project_path}"
                    }
                ],
                "start_command": "./gradlew build",
                "test_command": "./gradlew test"
            },
            
            {
                "name": "Swift iOS",
                "supported_project_types": ["mobile_app"],
                "supported_languages": ["swift", "ios"],
                "priority": 87,
                "required_tools": [
                    {"name": "xcode", "optional": True}
                ],
                "dependencies": [],
                "setup_steps": [
                    {
                        "command": "mkdir -p {project_path}",
                        "description": "Create project directory",
                        "working_directory": "."
                    },
                    {
                        "command": "mkdir -p {project_name}/Sources",
                        "description": "Create Swift source directory",
                        "working_directory": "{project_path}"
                    },
                    {
                        "command": "mkdir -p {project_name}/Resources",
                        "description": "Create resources directory",
                        "working_directory": "{project_path}"
                    }
                ],
                "start_command": "swift build",
                "test_command": "swift test"
            },
            
            {
                "name": "Flutter",
                "supported_project_types": ["mobile_app"],
                "supported_languages": ["dart", "flutter"],
                "priority": 89,
                "required_tools": [
                    {"name": "flutter", "optional": True}
                ],
                "dependencies": [],
                "setup_steps": [
                    {
                        "command": "flutter create {project_name}",
                        "description": "Create Flutter project",
                        "working_directory": "{project_parent_path}",
                        "fallback_command": "mkdir -p {project_path} && cd {project_path} && mkdir -p lib test"
                    }
                ],
                "start_command": "flutter run",
                "test_command": "flutter test"
            }
        ]


# Global toolchain mapper instance
toolchain_mapper = ToolchainMapper()