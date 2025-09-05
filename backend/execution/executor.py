"""
Project execution engine - Actually creates files and runs commands
"""
import os
import subprocess
import asyncio
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class ProjectExecutor:
    """Executes project creation commands and creates files"""
    
    def __init__(self):
        self.current_directory = None
    
    async def execute_plan(self, execution_plan, websocket=None) -> Dict[str, Any]:
        """
        Execute the project creation plan step by step
        
        Args:
            execution_plan: ExecutionPlan object with steps
            websocket: Optional websocket for real-time updates
            
        Returns:
            Dict with execution results
        """
        logger.info(f"🚀 Starting project execution with {execution_plan.total_steps} steps")
        
        results = []
        failed_steps = []
        
        try:
            # Create project directory first
            project_path = Path(execution_plan.project_path).resolve()
            if not project_path.exists():
                logger.info(f"📁 Creating project directory: {project_path}")
                project_path.mkdir(parents=True, exist_ok=True)
                
                if websocket:
                    await websocket.send_json({
                        "type": "command_complete",
                        "data": {
                            "message": f"✅ Created project directory: {project_path}",
                            "command": f"mkdir -p {project_path}"
                        }
                    })
            
            self.current_directory = str(project_path)
            
            # Execute each step
            for i, step in enumerate(execution_plan.steps):
                step_num = i + 1
                logger.info(f"⚙️  Executing step {step_num}/{execution_plan.total_steps}: {step.description}")
                
                if websocket:
                    await websocket.send_json({
                        "type": "command_start", 
                        "data": {
                            "step": step_num,
                            "total": execution_plan.total_steps,
                            "description": step.description,
                            "command": step.command
                        }
                    })
                
                try:
                    # Execute the step
                    result = await self._execute_step(step)
                    results.append(result)
                    
                    if websocket:
                        await websocket.send_json({
                            "type": "command_complete",
                            "data": {
                                "step": step_num,
                                "success": result["success"],
                                "message": result["message"],
                                "output": result.get("output", "")[:200]  # Truncate long output
                            }
                        })
                    
                    if not result["success"]:
                        failed_steps.append(step_num)
                        logger.warning(f"⚠️  Step {step_num} failed: {result['error']}")
                        
                        # Try fallback if available
                        if step.fallback_command:
                            logger.info(f"🔄 Trying fallback for step {step_num}")
                            fallback_step = step.copy()
                            fallback_step.command = step.fallback_command
                            fallback_result = await self._execute_step(fallback_step)
                            
                            if fallback_result["success"]:
                                logger.info(f"✅ Fallback succeeded for step {step_num}")
                                results[-1] = fallback_result  # Replace failed result
                                failed_steps.remove(step_num)
                    
                except Exception as e:
                    error_msg = f"Step {step_num} exception: {str(e)}"
                    logger.error(error_msg)
                    failed_steps.append(step_num)
                    results.append({
                        "success": False,
                        "error": error_msg,
                        "message": f"❌ Failed: {step.description}"
                    })
                    
                    if websocket:
                        await websocket.send_json({
                            "type": "command_error",
                            "data": {
                                "step": step_num,
                                "error": error_msg,
                                "message": f"❌ Step {step_num} failed with exception"
                            }
                        })
            
            # Final validation - check if key files exist
            validation_result = await self._validate_project(project_path)
            
            success = len(failed_steps) == 0 and validation_result["valid"]
            
            final_result = {
                "success": success,
                "total_steps": execution_plan.total_steps,
                "completed_steps": execution_plan.total_steps - len(failed_steps),
                "failed_steps": failed_steps,
                "project_path": str(project_path),
                "validation": validation_result,
                "message": f"✅ Project created successfully!" if success else f"⚠️  Project created with {len(failed_steps)} issues"
            }
            
            if websocket:
                await websocket.send_json({
                    "type": "project_created" if success else "project_completed_with_issues",
                    "data": final_result
                })
            
            return final_result
            
        except Exception as e:
            error_msg = f"Execution failed: {str(e)}"
            logger.error(error_msg)
            
            if websocket:
                await websocket.send_json({
                    "type": "execution_error",
                    "data": {"error": error_msg}
                })
            
            return {
                "success": False,
                "error": error_msg,
                "message": "❌ Project execution failed"
            }
    
    async def _execute_step(self, step) -> Dict[str, Any]:
        """Execute a single step"""
        
        try:
            if step.type == "file_create":
                return await self._create_file(step)
            elif step.type == "command":
                return await self._run_command(step)
            elif step.type == "directory_create":
                return await self._create_directory(step)
            else:
                return await self._run_command(step)  # Default to command execution
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"❌ Failed: {step.description}"
            }
    
    async def _create_file(self, step) -> Dict[str, Any]:
        """Create a file with content"""
        try:
            file_path = os.path.join(self.current_directory, step.target_file)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # Write file content
            with open(file_path, 'w') as f:
                f.write(step.content or "# Generated file\n")
            
            return {
                "success": True,
                "message": f"✅ Created: {step.target_file}",
                "output": f"File created at {file_path}"
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"❌ Failed to create: {step.target_file}"
            }
    
    async def _create_directory(self, step) -> Dict[str, Any]:
        """Create a directory"""
        try:
            dir_path = os.path.join(self.current_directory, step.target_file or step.command.split()[-1])
            os.makedirs(dir_path, exist_ok=True)
            
            return {
                "success": True,
                "message": f"✅ Created directory: {os.path.basename(dir_path)}",
                "output": f"Directory created at {dir_path}"
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"❌ Failed to create directory"
            }
    
    async def _run_command(self, step) -> Dict[str, Any]:
        """Run a shell command"""
        try:
            # Parse command
            command = step.command.strip()
            
            # Handle special commands
            if command.startswith('pip install'):
                # Use virtual environment if available
                venv_pip = os.path.join(self.current_directory, 'venv', 'bin', 'pip')
                if os.path.exists(venv_pip):
                    command = command.replace('pip install', f'{venv_pip} install')
            
            logger.info(f"Running command: {command}")
            
            # Run command
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=self.current_directory,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            output = stdout.decode().strip()
            error_output = stderr.decode().strip()
            
            success = process.returncode == 0
            
            result = {
                "success": success,
                "return_code": process.returncode,
                "output": output,
                "error_output": error_output,
                "message": f"✅ Command completed: {command}" if success else f"❌ Command failed: {command}"
            }
            
            if not success:
                result["error"] = f"Command failed with code {process.returncode}: {error_output}"
            
            return result
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"❌ Command execution failed: {step.command}"
            }
    
    async def _validate_project(self, project_path: Path) -> Dict[str, Any]:
        """Validate that the project was created correctly"""
        
        validation = {
            "valid": False,
            "files_created": [],
            "missing_files": [],
            "directories_created": []
        }
        
        try:
            # Check for common project files
            expected_files = [
                "app.py", "main.py", "requirements.txt", 
                "README.md", "setup.py", "__init__.py"
            ]
            
            for root, dirs, files in os.walk(project_path):
                validation["directories_created"].extend([
                    os.path.relpath(os.path.join(root, d), project_path) for d in dirs
                ])
                validation["files_created"].extend([
                    os.path.relpath(os.path.join(root, f), project_path) for f in files
                ])
            
            # Check for at least some key files
            has_main_file = any(f in validation["files_created"] for f in ["app.py", "main.py"])
            has_requirements = "requirements.txt" in validation["files_created"]
            
            validation["valid"] = len(validation["files_created"]) > 0 and has_main_file
            
            for expected in expected_files:
                if expected not in validation["files_created"]:
                    validation["missing_files"].append(expected)
            
            return validation
            
        except Exception as e:
            validation["error"] = str(e)
            return validation

# Global executor instance
project_executor = ProjectExecutor()