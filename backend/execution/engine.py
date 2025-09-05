"""Command execution engine with streaming and fallback support."""
import asyncio
import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Any, AsyncGenerator
import logging

from backend.models.schemas import ExecutionPlan, ExecutionStep, ExecutionResult, SessionState
from backend.config import settings

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Execute commands with streaming output and fallback support."""
    
    def __init__(self):
        """Initialize execution engine."""
        self.max_execution_time = settings.MAX_EXECUTION_TIME
        self.log_file = os.path.join(settings.LOG_DIR, "execution_log.jsonl")
        
    async def execute_plan(
        self,
        execution_plan: ExecutionPlan,
        session_state: SessionState,
        websocket=None
    ) -> List[ExecutionResult]:
        """
        Execute a complete execution plan.
        
        Args:
            execution_plan: Plan to execute
            session_state: Current session state
            websocket: Optional WebSocket for streaming updates
            
        Returns:
            List of execution results
        """
        logger.info(f"Starting execution of plan with {len(execution_plan.steps)} steps")
        
        results = []
        
        for i, step in enumerate(execution_plan.steps):
            # Notify start of step
            if websocket:
                await websocket.send_json({
                    "type": "command_start",
                    "data": {
                        "step_index": i,
                        "total_steps": len(execution_plan.steps),
                        "command": step.command,
                        "description": step.description,
                        "timestamp": datetime.now().isoformat()
                    }
                })
            
            # Execute step with streaming
            result = await self.execute_step(step, i, websocket)
            results.append(result)
            
            # Log result
            await self._log_execution_result(result)
            
            # Check if step failed
            if not result.success and not step.fallback_command:
                logger.error(f"Step {i} failed without fallback: {step.command}")
                
                if websocket:
                    await websocket.send_json({
                        "type": "command_error",
                        "data": {
                            "step_index": i,
                            "error": f"Command failed: {result.stderr}",
                            "timestamp": datetime.now().isoformat()
                        }
                    })
                
                # Stop execution on critical failure
                break
            
            elif not result.success and step.fallback_command:
                # Try fallback command
                logger.warning(f"Step {i} failed, trying fallback: {step.fallback_command}")
                
                fallback_step = ExecutionStep(
                    command=step.fallback_command,
                    description=f"Fallback for: {step.description}",
                    working_directory=step.working_directory,
                    timeout=step.timeout
                )
                
                fallback_result = await self.execute_step(fallback_step, i, websocket)
                fallback_result.fallback_used = True
                results.append(fallback_result)
                
                await self._log_execution_result(fallback_result)
                
                if not fallback_result.success:
                    logger.error(f"Fallback also failed for step {i}")
                    break
        
        logger.info(f"Execution completed. {len(results)} commands executed")
        return results
    
    async def execute_step(
        self,
        step: ExecutionStep,
        step_index: int,
        websocket=None
    ) -> ExecutionResult:
        """
        Execute a single step with streaming output.
        
        Args:
            step: Execution step
            step_index: Index of the step
            websocket: Optional WebSocket for streaming
            
        Returns:
            Execution result
        """
        start_time = datetime.now()
        
        logger.info(f"Executing step {step_index}: {step.command}")
        
        try:
            # Parse command
            cmd_parts = step.command.split()
            if not cmd_parts:
                raise ValueError("Empty command")
            
            # Set working directory
            cwd = step.working_directory or os.getcwd()
            if not os.path.exists(cwd):
                os.makedirs(cwd, exist_ok=True)
            
            # Create subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )
            
            # Stream output
            stdout_lines = []
            stderr_lines = []
            
            async def stream_stdout():
                async for line in process.stdout:
                    line_str = line.decode('utf-8', errors='ignore').rstrip()
                    stdout_lines.append(line_str)
                    
                    if websocket:
                        await websocket.send_json({
                            "type": "command_output",
                            "data": {
                                "step_index": step_index,
                                "stream": "stdout",
                                "line": line_str,
                                "timestamp": datetime.now().isoformat()
                            }
                        })
            
            async def stream_stderr():
                async for line in process.stderr:
                    line_str = line.decode('utf-8', errors='ignore').rstrip()
                    stderr_lines.append(line_str)
                    
                    if websocket:
                        await websocket.send_json({
                            "type": "command_output",
                            "data": {
                                "step_index": step_index,
                                "stream": "stderr",
                                "line": line_str,
                                "timestamp": datetime.now().isoformat()
                            }
                        })
            
            # Wait for completion with timeout
            try:
                stdout_task = asyncio.create_task(stream_stdout())
                stderr_task = asyncio.create_task(stream_stderr())
                
                await asyncio.wait_for(
                    asyncio.gather(stdout_task, stderr_task, process.wait()),
                    timeout=step.timeout
                )
                
                exit_code = process.returncode
                
            except asyncio.TimeoutError:
                logger.warning(f"Command timed out after {step.timeout} seconds: {step.command}")
                
                # Kill process
                try:
                    process.kill()
                    await process.wait()
                except:
                    pass
                
                exit_code = 1
                stderr_lines.append(f"Command timed out after {step.timeout} seconds")
            
            # Calculate duration
            duration = (datetime.now() - start_time).total_seconds()
            
            # Create result
            result = ExecutionResult(
                step_index=step_index,
                command=step.command,
                success=(exit_code == 0),
                stdout='\n'.join(stdout_lines),
                stderr='\n'.join(stderr_lines),
                exit_code=exit_code,
                duration=duration,
                timestamp=start_time
            )
            
            # Notify completion
            if websocket:
                await websocket.send_json({
                    "type": "command_complete",
                    "data": {
                        "step_index": step_index,
                        "success": result.success,
                        "exit_code": exit_code,
                        "duration": duration,
                        "timestamp": datetime.now().isoformat()
                    }
                })
            
            return result
            
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            error_msg = str(e)
            
            logger.error(f"Error executing step {step_index}: {error_msg}")
            
            result = ExecutionResult(
                step_index=step_index,
                command=step.command,
                success=False,
                stdout="",
                stderr=error_msg,
                exit_code=1,
                duration=duration,
                timestamp=start_time
            )
            
            if websocket:
                await websocket.send_json({
                    "type": "command_error",
                    "data": {
                        "step_index": step_index,
                        "error": error_msg,
                        "timestamp": datetime.now().isoformat()
                    }
                })
            
            return result
    
    async def execute_single_command(
        self,
        command: str,
        working_directory: Optional[str] = None,
        timeout: int = 60,
        websocket=None
    ) -> ExecutionResult:
        """
        Execute a single command.
        
        Args:
            command: Command to execute
            working_directory: Working directory
            timeout: Timeout in seconds
            websocket: Optional WebSocket for streaming
            
        Returns:
            Execution result
        """
        step = ExecutionStep(
            command=command,
            description=f"Execute: {command}",
            working_directory=working_directory,
            timeout=timeout
        )
        
        return await self.execute_step(step, 0, websocket)
    
    async def _log_execution_result(self, result: ExecutionResult):
        """Log execution result to JSONL file."""
        try:
            log_entry = {
                "timestamp": result.timestamp.isoformat(),
                "step_index": result.step_index,
                "command": result.command,
                "success": result.success,
                "exit_code": result.exit_code,
                "duration": result.duration,
                "stdout_length": len(result.stdout),
                "stderr_length": len(result.stderr),
                "fallback_used": result.fallback_used
            }
            
            # Append to log file
            os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
                
        except Exception as e:
            logger.error(f"Failed to log execution result: {e}")
    
    async def validate_command(self, command: str) -> Dict[str, Any]:
        """
        Validate a command before execution.
        
        Args:
            command: Command to validate
            
        Returns:
            Validation result
        """
        validation = {
            "valid": True,
            "warnings": [],
            "errors": []
        }
        
        # Basic safety checks
        dangerous_patterns = [
            "rm -rf /",
            "format c:",
            "del /s /q",
            "sudo rm -rf",
            "rm -rf *",
            ":(){ :|:& };:"  # Fork bomb
        ]
        
        command_lower = command.lower()
        
        for pattern in dangerous_patterns:
            if pattern in command_lower:
                validation["valid"] = False
                validation["errors"].append(f"Dangerous command pattern detected: {pattern}")
        
        # Check for sudo usage
        if command.startswith("sudo "):
            validation["warnings"].append("Command requires sudo privileges")
        
        # Check for network access
        network_commands = ["curl", "wget", "git clone", "npm install", "pip install"]
        if any(cmd in command_lower for cmd in network_commands):
            validation["warnings"].append("Command requires network access")
        
        return validation
    
    def get_execution_stats(self) -> Dict[str, Any]:
        """Get execution statistics."""
        stats = {
            "total_commands": 0,
            "successful_commands": 0,
            "failed_commands": 0,
            "average_duration": 0.0,
            "fallbacks_used": 0
        }
        
        try:
            if os.path.exists(self.log_file):
                total_duration = 0.0
                
                with open(self.log_file, 'r') as f:
                    for line in f:
                        entry = json.loads(line.strip())
                        stats["total_commands"] += 1
                        
                        if entry.get("success"):
                            stats["successful_commands"] += 1
                        else:
                            stats["failed_commands"] += 1
                        
                        if entry.get("fallback_used"):
                            stats["fallbacks_used"] += 1
                        
                        total_duration += entry.get("duration", 0.0)
                
                if stats["total_commands"] > 0:
                    stats["average_duration"] = total_duration / stats["total_commands"]
        
        except Exception as e:
            logger.error(f"Error calculating execution stats: {e}")
        
        return stats


# Global execution engine instance
execution_engine = ExecutionEngine()