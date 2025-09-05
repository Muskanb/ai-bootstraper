"""Report generation system."""
import os
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
from jinja2 import Template
import logging

from backend.models.schemas import (
    SessionState, ProjectRequirements, SystemCapability, 
    ExecutionResult, ExecutionPlan
)

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generate project reports and documentation."""
    
    def __init__(self):
        """Initialize report generator."""
        self.templates = self._load_templates()
    
    async def generate_project_readme(
        self,
        project_path: str,
        requirements: ProjectRequirements,
        capabilities: SystemCapability,
        execution_plan: ExecutionPlan,
        execution_results: List[ExecutionResult],
        verification_results: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate README.md for the created project.
        
        Args:
            project_path: Path to the project
            requirements: Project requirements
            capabilities: System capabilities
            execution_plan: Execution plan used
            execution_results: Results of execution
            verification_results: Verification test results
            
        Returns:
            Generated README content
        """
        logger.info(f"Generating README for project: {requirements.project_name}")
        
        # Get appropriate template
        template_content = self._get_readme_template(requirements)
        template = Template(template_content)
        
        # Prepare template context
        context = {
            "project_name": requirements.project_name or "My Project",
            "project_type": self._format_project_type(requirements.project_type),
            "language": requirements.language or "Unknown",
            "framework": requirements.framework,
            "database": requirements.database,
            "has_auth": requirements.authentication,
            "has_testing": requirements.testing,
            "has_docker": requirements.docker,
            "python_version": capabilities.python_version,
            "node_version": capabilities.node_version,
            "os": capabilities.os,
            "shell": capabilities.shell,
            "package_managers": capabilities.available_package_managers,
            "execution_steps": self._format_execution_steps(execution_plan.steps),
            "setup_commands": self._extract_setup_commands(execution_results),
            "run_commands": self._get_run_commands(requirements),
            "verification_passed": verification_results.get("success", True) if verification_results else True,
            "tests_summary": self._format_test_summary(verification_results) if verification_results else None,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "next_steps": self._generate_next_steps(requirements),
            "project_structure": self._generate_project_structure(project_path),
            "dependencies": self._extract_dependencies(requirements, execution_results)
        }
        
        # Render template
        readme_content = template.render(**context)
        
        # Write README file
        readme_path = os.path.join(project_path, "README.md")
        with open(readme_path, "w") as f:
            f.write(readme_content)
        
        logger.info(f"README generated: {readme_path}")
        return readme_content
    
    async def generate_execution_summary(
        self,
        session_state: SessionState,
        execution_results: List[ExecutionResult],
        verification_results: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate execution summary report.
        
        Args:
            session_state: Complete session state
            execution_results: Results of execution
            verification_results: Verification test results
            
        Returns:
            Execution summary
        """
        successful_commands = sum(1 for r in execution_results if r.success)
        failed_commands = len(execution_results) - successful_commands
        total_duration = sum(r.duration for r in execution_results)
        
        summary = {
            "project_info": {
                "name": session_state.requirements.project_name,
                "type": session_state.requirements.project_type.value if session_state.requirements.project_type else None,
                "language": session_state.requirements.language,
                "framework": session_state.requirements.framework
            },
            "execution_stats": {
                "total_commands": len(execution_results),
                "successful_commands": successful_commands,
                "failed_commands": failed_commands,
                "total_duration_seconds": round(total_duration, 2),
                "success_rate": round((successful_commands / len(execution_results)) * 100, 1) if execution_results else 0
            },
            "verification_stats": {
                "tests_run": verification_results.get("tests_run", 0) if verification_results else 0,
                "tests_passed": verification_results.get("tests_passed", 0) if verification_results else 0,
                "tests_failed": verification_results.get("tests_failed", 0) if verification_results else 0,
                "overall_success": verification_results.get("success", False) if verification_results else False
            },
            "session_info": {
                "session_id": session_state.session_id,
                "created_at": session_state.created_at.isoformat(),
                "completed_at": datetime.now().isoformat(),
                "total_iterations": session_state.iteration_count,
                "final_state": session_state.current_state.value
            },
            "system_info": {
                "os": session_state.capabilities.os if session_state.capabilities else "Unknown",
                "python_version": session_state.capabilities.python_version if session_state.capabilities else None,
                "node_version": session_state.capabilities.node_version if session_state.capabilities else None
            }
        }
        
        return summary
    
    def _get_readme_template(self, requirements: ProjectRequirements) -> str:
        """Get appropriate README template based on requirements."""
        project_type = requirements.project_type.value if requirements.project_type else "generic"
        language = requirements.language.lower() if requirements.language else "generic"
        
        # Try to find specific template
        template_key = f"{project_type}_{language}"
        if template_key in self.templates:
            return self.templates[template_key]
        
        # Fallback to language template
        if language in self.templates:
            return self.templates[language]
        
        # Fallback to generic template
        return self.templates["generic"]
    
    def _format_project_type(self, project_type) -> str:
        """Format project type for display."""
        if not project_type:
            return "Generic Project"
        
        type_names = {
            "web_api": "Web API",
            "frontend": "Frontend Application",
            "fullstack": "Full-Stack Application",
            "cli": "Command Line Tool",
            "library": "Library",
            "microservice": "Microservice"
        }
        
        return type_names.get(project_type.value, project_type.value.replace("_", " ").title())
    
    def _format_execution_steps(self, steps: List) -> List[Dict[str, Any]]:
        """Format execution steps for README."""
        return [
            {
                "command": step.command,
                "description": step.description,
                "working_directory": step.working_directory
            }
            for step in steps
        ]
    
    def _extract_setup_commands(self, execution_results: List[ExecutionResult]) -> List[str]:
        """Extract setup commands from execution results."""
        setup_commands = []
        
        for result in execution_results:
            if result.success and any(keyword in result.command.lower() 
                                    for keyword in ["install", "init", "create", "setup"]):
                setup_commands.append(result.command)
        
        return setup_commands
    
    def _get_run_commands(self, requirements: ProjectRequirements) -> Dict[str, str]:
        """Get run commands based on project requirements."""
        language = requirements.language.lower() if requirements.language else ""
        framework = requirements.framework.lower() if requirements.framework else ""
        
        commands = {}
        
        if language == "python":
            if framework == "fastapi":
                commands["dev"] = "uvicorn main:app --reload"
                commands["prod"] = "uvicorn main:app --host 0.0.0.0 --port 8000"
            elif framework == "django":
                commands["dev"] = "python manage.py runserver"
                commands["migrate"] = "python manage.py migrate"
            elif framework == "flask":
                commands["dev"] = "python app.py"
            else:
                commands["run"] = "python main.py"
        
        elif language in ["javascript", "node"]:
            commands["dev"] = "npm run dev"
            commands["start"] = "npm start"
            commands["build"] = "npm run build"
        
        if requirements.testing:
            if language == "python":
                commands["test"] = "pytest"
            elif language in ["javascript", "node"]:
                commands["test"] = "npm test"
        
        if requirements.docker:
            commands["docker-build"] = "docker build -t " + (requirements.project_name or "my-app") + " ."
            commands["docker-run"] = "docker run -p 8000:8000 " + (requirements.project_name or "my-app")
        
        return commands
    
    def _format_test_summary(self, verification_results: Dict[str, Any]) -> Dict[str, Any]:
        """Format verification test summary."""
        return {
            "total_tests": verification_results.get("tests_run", 0),
            "passed": verification_results.get("tests_passed", 0),
            "failed": verification_results.get("tests_failed", 0),
            "success_rate": round(
                (verification_results.get("tests_passed", 0) / max(verification_results.get("tests_run", 1), 1)) * 100, 1
            ),
            "errors": verification_results.get("errors", []),
            "warnings": verification_results.get("warnings", [])
        }
    
    def _generate_next_steps(self, requirements: ProjectRequirements) -> List[str]:
        """Generate suggested next steps."""
        steps = []
        
        language = requirements.language.lower() if requirements.language else ""
        
        if language == "python":
            steps.extend([
                "Activate the virtual environment: `source venv/bin/activate`",
                "Install dependencies: `pip install -r requirements.txt`"
            ])
        elif language in ["javascript", "node"]:
            steps.extend([
                "Install dependencies: `npm install`"
            ])
        
        if requirements.database:
            if requirements.database.lower() == "postgresql":
                steps.append("Set up PostgreSQL database and update connection settings")
            elif requirements.database.lower() == "mysql":
                steps.append("Set up MySQL database and update connection settings")
        
        if requirements.authentication:
            steps.append("Configure authentication settings and secret keys")
        
        if requirements.docker:
            steps.extend([
                "Build Docker image: `docker build -t your-app .`",
                "Run with Docker: `docker run -p 8000:8000 your-app`"
            ])
        
        steps.extend([
            "Review and customize the generated code",
            "Add your business logic",
            "Run tests to ensure everything works",
            "Deploy to your preferred platform"
        ])
        
        return steps
    
    def _generate_project_structure(self, project_path: str) -> str:
        """Generate project structure tree."""
        try:
            structure = []
            
            for root, dirs, files in os.walk(project_path):
                level = root.replace(project_path, '').count(os.sep)
                indent = ' ' * 2 * level
                structure.append(f"{indent}{os.path.basename(root)}/")
                
                sub_indent = ' ' * 2 * (level + 1)
                for file in files:
                    if not file.startswith('.') and file != 'README.md':  # Skip hidden files and README
                        structure.append(f"{sub_indent}{file}")
            
            return '\n'.join(structure[:20])  # Limit to first 20 lines
            
        except Exception as e:
            logger.warning(f"Failed to generate project structure: {e}")
            return "Project structure generation failed"
    
    def _extract_dependencies(self, requirements: ProjectRequirements, execution_results: List[ExecutionResult]) -> Dict[str, List[str]]:
        """Extract dependencies information."""
        dependencies = {"main": [], "dev": []}
        
        language = requirements.language.lower() if requirements.language else ""
        
        if language == "python":
            if requirements.framework == "fastapi":
                dependencies["main"].extend(["fastapi", "uvicorn"])
            elif requirements.framework == "django":
                dependencies["main"].append("django")
            elif requirements.framework == "flask":
                dependencies["main"].append("flask")
            
            if requirements.database:
                if requirements.database.lower() == "postgresql":
                    dependencies["main"].append("psycopg2-binary")
                elif requirements.database.lower() == "mysql":
                    dependencies["main"].append("mysql-connector-python")
            
            if requirements.testing:
                dependencies["dev"].extend(["pytest", "pytest-asyncio"])
        
        elif language in ["javascript", "node"]:
            if requirements.framework == "express":
                dependencies["main"].extend(["express", "cors", "helmet"])
            elif requirements.framework == "react":
                dependencies["main"].extend(["react", "react-dom"])
            
            if requirements.testing:
                dependencies["dev"].extend(["jest", "@testing-library/react"])
        
        return dependencies
    
    def _load_templates(self) -> Dict[str, str]:
        """Load README templates."""
        return {
            "generic": """# {{ project_name }}

{{ project_type }} built with {{ language }}{% if framework %} and {{ framework }}{% endif %}.

## Overview

This project was automatically generated by AI Agent Bootstrapper.

**Project Details:**
- **Type:** {{ project_type }}
- **Language:** {{ language }}{% if framework %}
- **Framework:** {{ framework }}{% endif %}{% if database %}
- **Database:** {{ database }}{% endif %}{% if has_auth %}
- **Authentication:** Enabled{% endif %}{% if has_testing %}
- **Testing:** Configured{% endif %}{% if has_docker %}
- **Docker:** Configured{% endif %}

## Requirements

- **OS:** {{ os }}{% if python_version %}
- **Python:** {{ python_version }}{% endif %}{% if node_version %}
- **Node.js:** {{ node_version }}{% endif %}

## Quick Start

{% for command in setup_commands %}
```bash
{{ command }}
```
{% endfor %}

## Available Commands

{% for name, command in run_commands.items() %}
### {{ name|title }}
```bash
{{ command }}
```
{% endfor %}

## Project Structure

```
{{ project_structure }}
```

{% if dependencies.main %}
## Dependencies

### Main Dependencies
{% for dep in dependencies.main %}
- {{ dep }}{% endfor %}
{% endif %}

{% if dependencies.dev %}
### Development Dependencies
{% for dep in dependencies.dev %}
- {{ dep }}{% endfor %}
{% endif %}

{% if tests_summary %}
## Testing

{{ tests_summary.total_tests }} tests configured with {{ tests_summary.passed }} passing ({{ tests_summary.success_rate }}% success rate).

{% if tests_summary.errors %}
**Test Errors:**
{% for error in tests_summary.errors %}
- {{ error }}{% endfor %}
{% endif %}
{% endif %}

## Next Steps

{% for step in next_steps %}
{{ loop.index }}. {{ step }}{% endfor %}

## System Information

This project was generated on {{ generated_at }} using:
- **OS:** {{ os }}
- **Shell:** {{ shell }}{% if package_managers %}
- **Package Managers:** {{ package_managers|join(', ') }}{% endif %}

{% if verification_passed %}
✅ **All verification tests passed!**
{% else %}
⚠️ **Some verification tests failed. Please check the setup.**
{% endif %}

---

*Generated by AI Agent Bootstrapper*
""",
            
            "python": """# {{ project_name }}

{{ project_type }} built with Python{% if framework %} and {{ framework }}{% endif %}.

## Setup

### 1. Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\\Scripts\\activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

{% if framework == "fastapi" %}
### 3. Run the Application
```bash
uvicorn main:app --reload
```

Visit http://localhost:8000 to see your API.
API documentation available at http://localhost:8000/docs
{% elif framework == "django" %}
### 3. Database Migration
```bash
python manage.py migrate
```

### 4. Run the Application
```bash
python manage.py runserver
```
{% elif framework == "flask" %}
### 3. Run the Application
```bash
python app.py
```
{% else %}
### 3. Run the Application
```bash
python main.py
```
{% endif %}

{% if has_testing %}
## Testing
```bash
pytest
```
{% endif %}

{% if has_docker %}
## Docker

### Build Image
```bash
docker build -t {{ project_name }} .
```

### Run Container
```bash
docker run -p 8000:8000 {{ project_name }}
```
{% endif %}

## Development

This is a {{ project_type|lower }} project. Key files:
- `main.py` - Application entry point{% if framework == "fastapi" %}
- `requirements.txt` - Python dependencies
- `README.md` - This file{% endif %}

---

*Generated by AI Agent Bootstrapper on {{ generated_at }}*
""",
            
            "javascript": """# {{ project_name }}

{{ project_type }} built with JavaScript{% if framework %} and {{ framework }}{% endif %}.

## Setup

### 1. Install Dependencies
```bash
npm install
```

{% if framework == "react" %}
### 2. Start Development Server
```bash
npm start
```

Visit http://localhost:3000 to see your application.
{% elif framework == "express" %}
### 2. Start Server
```bash
npm start
```

API will be available at http://localhost:3000
{% else %}
### 2. Run Application
```bash
npm start
```
{% endif %}

## Available Scripts

{% for name, command in run_commands.items() %}
### `{{ command }}`
{{ name|title }} the application.
{% endfor %}

{% if has_testing %}
## Testing
```bash
npm test
```
{% endif %}

{% if has_docker %}
## Docker

Build and run with Docker:
```bash
docker build -t {{ project_name }} .
docker run -p 3000:3000 {{ project_name }}
```
{% endif %}

## Project Structure

```
{{ project_structure }}
```

---

*Generated by AI Agent Bootstrapper on {{ generated_at }}*
"""
        }


# Global report generator instance
report_generator = ReportGenerator()