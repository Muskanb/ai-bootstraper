"""Verification and smoke testing system."""
import asyncio
import os
from typing import Dict, List, Any, Optional
import logging
from datetime import datetime

from backend.models.schemas import ExecutionResult, ProjectRequirements, SystemCapability
from backend.execution.engine import execution_engine

logger = logging.getLogger(__name__)


class ProjectTester:
    """Run verification tests for created projects."""
    
    def __init__(self):
        """Initialize project tester."""
        self.test_suites = self._load_test_suites()
    
    async def run_verification_tests(
        self,
        project_path: str,
        requirements: ProjectRequirements,
        capabilities: SystemCapability,
        websocket=None
    ) -> Dict[str, Any]:
        """
        Run verification tests for the created project.
        
        Args:
            project_path: Path to the created project
            requirements: Project requirements
            capabilities: System capabilities
            websocket: Optional WebSocket for updates
            
        Returns:
            Verification results
        """
        logger.info(f"Starting verification tests for project: {project_path}")
        
        # Get appropriate test suite
        test_suite = self._get_test_suite(requirements)
        
        if not test_suite:
            logger.warning(f"No test suite found for project type: {requirements.project_type}")
            return {
                "success": False,
                "error": f"No test suite available for {requirements.project_type}",
                "tests_run": 0,
                "tests_passed": 0,
                "tests_failed": 0
            }
        
        # Run tests
        results = {
            "success": True,
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "test_results": [],
            "errors": [],
            "warnings": []
        }
        
        for test in test_suite["tests"]:
            if websocket:
                await websocket.send_json({
                    "type": "verification_test_start",
                    "data": {
                        "test_name": test["name"],
                        "description": test["description"]
                    }
                })
            
            test_result = await self._run_single_test(
                test, project_path, requirements, capabilities, websocket
            )
            
            results["test_results"].append(test_result)
            results["tests_run"] += 1
            
            if test_result["success"]:
                results["tests_passed"] += 1
            else:
                results["tests_failed"] += 1
                results["success"] = False
                if test_result.get("error"):
                    results["errors"].append(test_result["error"])
            
            if test_result.get("warnings"):
                results["warnings"].extend(test_result["warnings"])
        
        logger.info(f"Verification completed: {results['tests_passed']}/{results['tests_run']} tests passed")
        return results
    
    async def _run_single_test(
        self,
        test: Dict[str, Any],
        project_path: str,
        requirements: ProjectRequirements,
        capabilities: SystemCapability,
        websocket=None
    ) -> Dict[str, Any]:
        """Run a single verification test."""
        test_name = test["name"]
        test_type = test["type"]
        
        logger.debug(f"Running test: {test_name}")
        
        try:
            if test_type == "file_exists":
                return await self._test_file_exists(test, project_path)
            elif test_type == "command":
                return await self._test_command_execution(test, project_path, websocket)
            elif test_type == "dependency_check":
                return await self._test_dependency_installation(test, project_path, requirements)
            elif test_type == "import_test":
                return await self._test_imports(test, project_path, requirements)
            elif test_type == "structure_check":
                return await self._test_project_structure(test, project_path)
            else:
                return {
                    "name": test_name,
                    "success": False,
                    "error": f"Unknown test type: {test_type}"
                }
                
        except Exception as e:
            logger.error(f"Test {test_name} failed with exception: {e}")
            return {
                "name": test_name,
                "success": False,
                "error": str(e)
            }
    
    async def _test_file_exists(self, test: Dict, project_path: str) -> Dict[str, Any]:
        """Test if required files exist."""
        files_to_check = test["files"]
        missing_files = []
        
        for file_path in files_to_check:
            full_path = os.path.join(project_path, file_path)
            if not os.path.exists(full_path):
                missing_files.append(file_path)
        
        success = len(missing_files) == 0
        
        return {
            "name": test["name"],
            "success": success,
            "error": f"Missing files: {missing_files}" if missing_files else None,
            "details": {
                "expected_files": files_to_check,
                "missing_files": missing_files
            }
        }
    
    async def _test_command_execution(
        self, 
        test: Dict, 
        project_path: str, 
        websocket=None
    ) -> Dict[str, Any]:
        """Test command execution."""
        command = test["command"]
        expected_exit_code = test.get("expected_exit_code", 0)
        timeout = test.get("timeout", 30)
        
        # Execute command
        result = await execution_engine.execute_single_command(
            command=command,
            working_directory=project_path,
            timeout=timeout,
            websocket=websocket
        )
        
        success = result.exit_code == expected_exit_code
        
        return {
            "name": test["name"],
            "success": success,
            "error": f"Command failed with exit code {result.exit_code}" if not success else None,
            "details": {
                "command": command,
                "exit_code": result.exit_code,
                "expected_exit_code": expected_exit_code,
                "stdout": result.stdout[:500],  # Limit output
                "stderr": result.stderr[:500]
            }
        }
    
    async def _test_dependency_installation(
        self, 
        test: Dict, 
        project_path: str,
        requirements: ProjectRequirements
    ) -> Dict[str, Any]:
        """Test if dependencies are properly installed."""
        language = requirements.language.lower() if requirements.language else ""
        
        if language == "python":
            return await self._test_python_dependencies(test, project_path)
        elif language in ["javascript", "node"]:
            return await self._test_node_dependencies(test, project_path)
        else:
            return {
                "name": test["name"],
                "success": True,
                "warnings": [f"Dependency check not implemented for {language}"]
            }
    
    async def _test_python_dependencies(self, test: Dict, project_path: str) -> Dict[str, Any]:
        """Test Python dependencies."""
        # Check if requirements.txt exists
        req_file = os.path.join(project_path, "requirements.txt")
        if not os.path.exists(req_file):
            return {
                "name": test["name"],
                "success": False,
                "error": "requirements.txt not found"
            }
        
        # Try to run pip list to check installed packages
        result = await execution_engine.execute_single_command(
            command="pip list",
            working_directory=project_path,
            timeout=30
        )
        
        return {
            "name": test["name"],
            "success": result.success,
            "error": "Failed to list Python packages" if not result.success else None,
            "details": {
                "pip_output": result.stdout[:500]
            }
        }
    
    async def _test_node_dependencies(self, test: Dict, project_path: str) -> Dict[str, Any]:
        """Test Node.js dependencies."""
        # Check if package.json exists
        pkg_file = os.path.join(project_path, "package.json")
        if not os.path.exists(pkg_file):
            return {
                "name": test["name"],
                "success": False,
                "error": "package.json not found"
            }
        
        # Check if node_modules exists
        modules_dir = os.path.join(project_path, "node_modules")
        if not os.path.exists(modules_dir):
            return {
                "name": test["name"],
                "success": False,
                "error": "node_modules directory not found - dependencies may not be installed"
            }
        
        return {
            "name": test["name"],
            "success": True,
            "details": {
                "package_json_exists": True,
                "node_modules_exists": True
            }
        }
    
    async def _test_imports(self, test: Dict, project_path: str, requirements: ProjectRequirements) -> Dict[str, Any]:
        """Test if key imports work."""
        language = requirements.language.lower() if requirements.language else ""
        
        if language == "python":
            return await self._test_python_imports(test, project_path)
        else:
            return {
                "name": test["name"],
                "success": True,
                "warnings": [f"Import test not implemented for {language}"]
            }
    
    async def _test_python_imports(self, test: Dict, project_path: str) -> Dict[str, Any]:
        """Test Python imports."""
        imports_to_test = test.get("imports", [])
        
        for import_stmt in imports_to_test:
            # Create a simple test script
            test_script = f"""
try:
    {import_stmt}
    print("SUCCESS: {import_stmt}")
except ImportError as e:
    print(f"FAILED: {import_stmt} - {{e}}")
    exit(1)
"""
            
            # Write test script
            test_file = os.path.join(project_path, "import_test.py")
            with open(test_file, "w") as f:
                f.write(test_script)
            
            # Run test
            result = await execution_engine.execute_single_command(
                command="python import_test.py",
                working_directory=project_path,
                timeout=15
            )
            
            # Clean up
            os.remove(test_file)
            
            if not result.success:
                return {
                    "name": test["name"],
                    "success": False,
                    "error": f"Import failed: {import_stmt}",
                    "details": {
                        "failed_import": import_stmt,
                        "error_output": result.stderr
                    }
                }
        
        return {
            "name": test["name"],
            "success": True,
            "details": {
                "imports_tested": imports_to_test
            }
        }
    
    async def _test_project_structure(self, test: Dict, project_path: str) -> Dict[str, Any]:
        """Test project directory structure."""
        required_structure = test["structure"]
        missing_items = []
        
        def check_structure(structure, current_path=""):
            for item_name, item_config in structure.items():
                item_path = os.path.join(project_path, current_path, item_name)
                
                if isinstance(item_config, dict):
                    # It's a directory
                    if not os.path.isdir(item_path):
                        missing_items.append(f"Directory: {os.path.join(current_path, item_name)}")
                    else:
                        # Check nested structure
                        check_structure(item_config, os.path.join(current_path, item_name))
                else:
                    # It's a file
                    if not os.path.isfile(item_path):
                        missing_items.append(f"File: {os.path.join(current_path, item_name)}")
        
        check_structure(required_structure)
        
        success = len(missing_items) == 0
        
        return {
            "name": test["name"],
            "success": success,
            "error": f"Missing structure items: {missing_items}" if missing_items else None,
            "details": {
                "missing_items": missing_items
            }
        }
    
    def _get_test_suite(self, requirements: ProjectRequirements) -> Optional[Dict[str, Any]]:
        """Get appropriate test suite for project requirements."""
        project_type = requirements.project_type.value if requirements.project_type else None
        language = requirements.language.lower() if requirements.language else None
        
        # Find matching test suite
        for suite in self.test_suites:
            if (project_type in suite.get("project_types", []) and 
                language in suite.get("languages", [])):
                return suite
        
        return None
    
    def _load_test_suites(self) -> List[Dict[str, Any]]:
        """Load test suite definitions."""
        return [
            {
                "name": "Python Web API",
                "project_types": ["web_api", "microservice"],
                "languages": ["python"],
                "tests": [
                    {
                        "name": "Essential Files Check",
                        "type": "file_exists",
                        "description": "Check if essential project files exist",
                        "files": ["main.py", "requirements.txt", "README.md"]
                    },
                    {
                        "name": "Dependencies Check",
                        "type": "dependency_check",
                        "description": "Verify Python dependencies are installed"
                    },
                    {
                        "name": "FastAPI Import Test",
                        "type": "import_test",
                        "description": "Test if FastAPI can be imported",
                        "imports": ["import fastapi", "from fastapi import FastAPI"]
                    },
                    {
                        "name": "Syntax Check",
                        "type": "command",
                        "command": "python -m py_compile main.py",
                        "description": "Check Python syntax",
                        "expected_exit_code": 0,
                        "timeout": 15
                    }
                ]
            },
            {
                "name": "Node.js Express API",
                "project_types": ["web_api", "fullstack"],
                "languages": ["javascript", "node"],
                "tests": [
                    {
                        "name": "Essential Files Check",
                        "type": "file_exists",
                        "description": "Check if essential project files exist",
                        "files": ["package.json", "index.js", "README.md"]
                    },
                    {
                        "name": "Dependencies Check",
                        "type": "dependency_check",
                        "description": "Verify Node.js dependencies are installed"
                    },
                    {
                        "name": "Syntax Check",
                        "type": "command",
                        "command": "node -c index.js",
                        "description": "Check JavaScript syntax",
                        "expected_exit_code": 0,
                        "timeout": 15
                    }
                ]
            },
            {
                "name": "React Frontend",
                "project_types": ["frontend", "fullstack"],
                "languages": ["javascript", "typescript"],
                "tests": [
                    {
                        "name": "Essential Files Check",
                        "type": "file_exists",
                        "description": "Check if essential project files exist",
                        "files": ["package.json", "src/App.js", "public/index.html"]
                    },
                    {
                        "name": "Dependencies Check",
                        "type": "dependency_check",
                        "description": "Verify React dependencies are installed"
                    },
                    {
                        "name": "Build Test",
                        "type": "command",
                        "command": "npm run build",
                        "description": "Test if project builds successfully",
                        "expected_exit_code": 0,
                        "timeout": 120
                    }
                ]
            },
            {
                "name": "Generic Project",
                "project_types": ["cli", "library"],
                "languages": ["python", "javascript", "typescript"],
                "tests": [
                    {
                        "name": "README Check",
                        "type": "file_exists",
                        "description": "Check if README exists",
                        "files": ["README.md"]
                    },
                    {
                        "name": "Project Structure",
                        "type": "structure_check",
                        "description": "Verify basic project structure",
                        "structure": {
                            "README.md": "file",
                            "src": {}
                        }
                    }
                ]
            }
        ]


# Global tester instance
project_tester = ProjectTester()