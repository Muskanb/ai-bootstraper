"""System capability detection."""
import asyncio
import platform
import os
import shutil
import subprocess
from typing import Dict, List, Optional, Any
import logging
import json
from datetime import datetime

from backend.models.schemas import SystemCapability
from backend.config import settings

logger = logging.getLogger(__name__)


class CapabilityDetector:
    """Detect system capabilities and installed tools."""
    
    def __init__(self):
        """Initialize capability detector."""
        self.cache_file = os.path.join(settings.DATA_DIR, "capabilities.json")
        self.cache_ttl = 3600  # Cache for 1 hour
        
    async def detect_all_capabilities(self, force_refresh: bool = False) -> SystemCapability:
        """
        Detect all system capabilities.
        
        Args:
            force_refresh: Force refresh cache
            
        Returns:
            System capability information
        """
        # Check cache first
        if not force_refresh:
            cached = await self._load_cache()
            if cached:
                logger.info("Using cached capabilities")
                return cached
        
        logger.info("Detecting system capabilities...")
        
        capabilities = SystemCapability(
            os=self._detect_os(),
            shell=self._detect_shell(),
            python_version=await self._detect_python(),
            node_version=await self._detect_node(),
            npm_version=await self._detect_npm(),
            docker_installed=await self._detect_docker(),
            git_installed=await self._detect_git(),
            available_package_managers=await self._detect_package_managers(),
            available_runtimes=await self._detect_runtimes(),
            environment_variables=self._get_relevant_env_vars()
        )
        
        # Save to cache
        await self._save_cache(capabilities)
        
        logger.info("System capability detection completed")
        return capabilities
    
    def _detect_os(self) -> str:
        """Detect operating system."""
        return platform.system()
    
    def _detect_shell(self) -> str:
        """Detect shell type."""
        shell = os.environ.get('SHELL', '')
        if shell:
            return os.path.basename(shell)
        
        # Fallback detection
        if platform.system() == "Windows":
            return "cmd" if "cmd" in os.environ.get('COMSPEC', '') else "powershell"
        else:
            return "bash"  # Default assumption for Unix-like systems
    
    async def _detect_python(self) -> Optional[str]:
        """Detect Python version."""
        try:
            result = await self._run_command(["python", "--version"])
            if result.returncode == 0:
                version = result.stdout.strip().replace('Python ', '')
                return version
            
            # Try python3
            result = await self._run_command(["python3", "--version"])
            if result.returncode == 0:
                version = result.stdout.strip().replace('Python ', '')
                return version
                
        except Exception as e:
            logger.debug(f"Python detection failed: {e}")
        
        return None
    
    async def _detect_node(self) -> Optional[str]:
        """Detect Node.js version."""
        try:
            result = await self._run_command(["node", "--version"])
            if result.returncode == 0:
                return result.stdout.strip().lstrip('v')
        except Exception as e:
            logger.debug(f"Node.js detection failed: {e}")
        
        return None
    
    async def _detect_npm(self) -> Optional[str]:
        """Detect npm version."""
        try:
            result = await self._run_command(["npm", "--version"])
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.debug(f"npm detection failed: {e}")
        
        return None
    
    async def _detect_docker(self) -> bool:
        """Detect Docker installation."""
        try:
            result = await self._run_command(["docker", "--version"])
            return result.returncode == 0
        except Exception as e:
            logger.debug(f"Docker detection failed: {e}")
            return False
    
    async def _detect_git(self) -> bool:
        """Detect Git installation."""
        try:
            result = await self._run_command(["git", "--version"])
            return result.returncode == 0
        except Exception as e:
            logger.debug(f"Git detection failed: {e}")
            return False
    
    async def _detect_package_managers(self) -> List[str]:
        """Detect available package managers."""
        managers = []
        
        # Python package managers
        for cmd in ["pip", "pip3", "pipenv", "poetry", "conda"]:
            if await self._check_command_exists(cmd):
                managers.append(cmd)
        
        # Node.js package managers
        for cmd in ["npm", "yarn", "pnpm"]:
            if await self._check_command_exists(cmd):
                managers.append(cmd)
        
        # System package managers
        system_managers = {
            "Linux": ["apt", "yum", "dnf", "pacman", "zypper", "apk"],
            "Darwin": ["brew", "port"],
            "Windows": ["choco", "scoop"]
        }
        
        os_type = platform.system()
        if os_type in system_managers:
            for cmd in system_managers[os_type]:
                if await self._check_command_exists(cmd):
                    managers.append(cmd)
        
        return managers
    
    async def _detect_runtimes(self) -> Dict[str, str]:
        """Detect available language runtimes."""
        runtimes = {}
        
        # Language runtime commands and version flags
        runtime_commands = {
            "python": ["python", "--version"],
            "python3": ["python3", "--version"],
            "node": ["node", "--version"],
            "go": ["go", "version"],
            "rust": ["rustc", "--version"],
            "java": ["java", "-version"],
            "php": ["php", "--version"],
            "ruby": ["ruby", "--version"],
            "dotnet": ["dotnet", "--version"],
            "swift": ["swift", "--version"],
            # Mobile development tools
            "flutter": ["flutter", "--version"],
            "dart": ["dart", "--version"],
            "kotlin": ["kotlinc", "-version"],
            # Development environments  
            "xcode": ["xcodebuild", "-version"],
            "android": ["adb", "--version"]
        }
        
        for runtime, cmd in runtime_commands.items():
            try:
                result = await self._run_command(cmd)
                if result.returncode == 0:
                    version_output = result.stdout or result.stderr
                    # Extract version number (simplified)
                    version = self._extract_version(version_output)
                    if version:
                        runtimes[runtime] = version
            except Exception as e:
                logger.debug(f"Runtime {runtime} detection failed: {e}")
        
        return runtimes
    
    def _extract_version(self, version_output: str) -> Optional[str]:
        """Extract version number from command output."""
        import re
        
        # Common version patterns
        patterns = [
            r'(\d+\.\d+\.\d+)',  # x.y.z
            r'(\d+\.\d+)',       # x.y
            r'v(\d+\.\d+\.\d+)', # vx.y.z
            r'version (\d+\.\d+\.\d+)',  # version x.y.z
        ]
        
        for pattern in patterns:
            match = re.search(pattern, version_output)
            if match:
                return match.group(1)
        
        return None
    
    def _get_relevant_env_vars(self) -> Dict[str, str]:
        """Get relevant environment variables."""
        relevant_vars = [
            'PATH', 'HOME', 'USER', 'SHELL',
            'NODE_ENV', 'PYTHON_PATH', 'VIRTUAL_ENV',
            'JAVA_HOME', 'GOPATH', 'CARGO_HOME',
            'DOCKER_HOST', 'KUBECONFIG'
        ]
        
        env_vars = {}
        for var in relevant_vars:
            value = os.environ.get(var)
            if value:
                env_vars[var] = value
        
        return env_vars
    
    async def _check_command_exists(self, command: str) -> bool:
        """Check if a command exists in PATH."""
        try:
            result = await self._run_command([command, "--version"])
            return result.returncode == 0
        except Exception:
            # Try with 'which' or 'where'
            try:
                which_cmd = "where" if platform.system() == "Windows" else "which"
                result = await self._run_command([which_cmd, command])
                return result.returncode == 0
            except Exception:
                return False
    
    async def _run_command(
        self,
        command: List[str],
        timeout: int = 10
    ) -> subprocess.CompletedProcess:
        """
        Run a command asynchronously.
        
        Args:
            command: Command to run
            timeout: Timeout in seconds
            
        Returns:
            Completed process result
        """
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
            
            return subprocess.CompletedProcess(
                args=command,
                returncode=process.returncode,
                stdout=stdout.decode('utf-8', errors='ignore'),
                stderr=stderr.decode('utf-8', errors='ignore')
            )
            
        except asyncio.TimeoutError:
            logger.warning(f"Command timed out: {' '.join(command)}")
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout="",
                stderr="Command timed out"
            )
        except Exception as e:
            logger.debug(f"Command failed: {' '.join(command)} - {e}")
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout="",
                stderr=str(e)
            )
    
    async def _load_cache(self) -> Optional[SystemCapability]:
        """Load capabilities from cache if valid."""
        try:
            if not os.path.exists(self.cache_file):
                return None
            
            # Check cache age
            cache_age = datetime.now().timestamp() - os.path.getmtime(self.cache_file)
            if cache_age > self.cache_ttl:
                return None
            
            with open(self.cache_file, 'r') as f:
                data = json.load(f)
                return SystemCapability(**data)
                
        except Exception as e:
            logger.debug(f"Failed to load capability cache: {e}")
            return None
    
    async def _save_cache(self, capabilities: SystemCapability):
        """Save capabilities to cache."""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(capabilities.model_dump(), f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save capability cache: {e}")
    
    async def check_specific_tool(self, tool: str) -> Dict[str, Any]:
        """
        Check if a specific tool is available.
        
        Args:
            tool: Tool name to check
            
        Returns:
            Tool information
        """
        result = {
            "tool": tool,
            "available": False,
            "version": None,
            "path": None
        }
        
        try:
            # Check if command exists
            if await self._check_command_exists(tool):
                result["available"] = True
                
                # Get version
                version_result = await self._run_command([tool, "--version"])
                if version_result.returncode == 0:
                    version_output = version_result.stdout or version_result.stderr
                    result["version"] = self._extract_version(version_output)
                
                # Get path
                which_cmd = "where" if platform.system() == "Windows" else "which"
                path_result = await self._run_command([which_cmd, tool])
                if path_result.returncode == 0:
                    result["path"] = path_result.stdout.strip()
                    
        except Exception as e:
            logger.debug(f"Tool check failed for {tool}: {e}")
        
        return result
    
    async def validate_project_requirements(
        self,
        project_type: str,
        language: str,
        framework: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Validate that system can support the project requirements.
        
        Args:
            project_type: Type of project
            language: Programming language
            framework: Optional framework
            
        Returns:
            Validation result with suggestions
        """
        capabilities = await self.detect_all_capabilities()
        
        validation = {
            "supported": True,
            "missing_requirements": [],
            "suggestions": [],
            "warnings": []
        }
        
        # Check language requirements
        if language.lower() == "python":
            if not capabilities.python_version:
                validation["supported"] = False
                validation["missing_requirements"].append("Python interpreter")
                validation["suggestions"].append("Install Python from python.org")
            elif "pip" not in capabilities.available_package_managers:
                validation["warnings"].append("pip not found - package management may be limited")
                
        elif language.lower() == "node" or language.lower() == "javascript":
            if not capabilities.node_version:
                validation["supported"] = False
                validation["missing_requirements"].append("Node.js runtime")
                validation["suggestions"].append("Install Node.js from nodejs.org")
            elif not capabilities.npm_version:
                validation["warnings"].append("npm not found - using node without package manager")
                
        # Check framework requirements
        if framework:
            framework_requirements = {
                "fastapi": ["python", "pip"],
                "express": ["node", "npm"],
                "react": ["node", "npm"],
                "vue": ["node", "npm"],
                "django": ["python", "pip"],
                "flask": ["python", "pip"]
            }
            
            if framework.lower() in framework_requirements:
                for req in framework_requirements[framework.lower()]:
                    if req not in [tool.lower() for tool in capabilities.available_package_managers + [capabilities.python_version, capabilities.node_version] if tool]:
                        validation["missing_requirements"].append(f"{req} (required for {framework})")
        
        # Check Docker if requested
        if project_type == "microservice" and not capabilities.docker_installed:
            validation["warnings"].append("Docker not installed - containerization features will be unavailable")
        
        return validation


# Global capability detector instance
capability_detector = CapabilityDetector()