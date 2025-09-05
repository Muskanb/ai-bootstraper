"""Project template generation."""
import os
from typing import Dict, List, Any
from backend.models.schemas import ProjectRequirements


class ProjectTemplateGenerator:
    """Generate project files and directory structure."""
    
    def __init__(self):
        """Initialize template generator."""
        self.templates = self._load_file_templates()
    
    def generate_project_files(
        self,
        project_path: str,
        requirements: ProjectRequirements
    ) -> List[Dict[str, Any]]:
        """
        Generate project files based on requirements.
        
        Args:
            project_path: Path where project should be created
            requirements: Project requirements
            
        Returns:
            List of files to create
        """
        files_to_create = []
        
        # Create directory structure first
        directories = self._get_directory_structure(requirements)
        for directory in directories:
            dir_path = os.path.join(project_path, directory)
            files_to_create.append({
                "type": "directory",
                "path": dir_path,
                "name": directory
            })
        
        # Generate files based on project type and language
        template_files = self._get_template_files(requirements)
        
        for file_info in template_files:
            file_path = os.path.join(project_path, file_info["path"])
            content = self._generate_file_content(file_info, requirements)
            
            files_to_create.append({
                "type": "file",
                "path": file_path,
                "name": file_info["path"],
                "content": content,
                "template": file_info["template"]
            })
        
        return files_to_create
    
    def _get_directory_structure(self, requirements: ProjectRequirements) -> List[str]:
        """Get directory structure based on requirements."""
        directories = []
        
        language = requirements.language.lower() if requirements.language else ""
        project_type = requirements.project_type.value if requirements.project_type else ""
        
        if language == "python":
            directories.extend(["src", "tests"])
            if requirements.framework == "django":
                directories.extend(["static", "templates", "media"])
        
        elif language in ["javascript", "node"]:
            if project_type == "frontend":
                directories.extend(["src", "public", "build"])
            else:
                directories.extend(["src", "tests"])
        
        # Common directories
        if requirements.docker:
            directories.append(".docker")
        
        return directories
    
    def _get_template_files(self, requirements: ProjectRequirements) -> List[Dict[str, Any]]:
        """Get list of template files to generate."""
        language = requirements.language.lower() if requirements.language else ""
        framework = requirements.framework.lower() if requirements.framework else ""
        project_type = requirements.project_type.value if requirements.project_type else ""
        
        files = []
        
        # Common files
        files.append({"path": "README.md", "template": "readme"})
        files.append({"path": ".gitignore", "template": "gitignore"})
        
        # Language-specific files
        if language == "python":
            files.extend([
                {"path": "requirements.txt", "template": "python_requirements"},
                {"path": "main.py", "template": f"python_{framework}_main" if framework else "python_main"}
            ])
            
            if framework == "fastapi":
                files.extend([
                    {"path": "src/models.py", "template": "fastapi_models"},
                    {"path": "src/routes.py", "template": "fastapi_routes"}
                ])
            elif framework == "django":
                files.extend([
                    {"path": "manage.py", "template": "django_manage"},
                    {"path": "settings.py", "template": "django_settings"}
                ])
            
            if requirements.testing:
                files.append({"path": "tests/test_main.py", "template": "python_test"})
        
        elif language in ["javascript", "node"]:
            files.extend([
                {"path": "package.json", "template": "package_json"},
                {"path": "index.js", "template": f"js_{framework}_main" if framework else "js_main"}
            ])
            
            if framework == "express":
                files.extend([
                    {"path": "src/routes.js", "template": "express_routes"},
                    {"path": "src/middleware.js", "template": "express_middleware"}
                ])
            elif framework == "react":
                files.extend([
                    {"path": "src/App.js", "template": "react_app"},
                    {"path": "src/index.js", "template": "react_index"},
                    {"path": "public/index.html", "template": "react_html"}
                ])
            
            if requirements.testing:
                files.append({"path": "tests/app.test.js", "template": "js_test"})
        
        # Docker files
        if requirements.docker:
            files.extend([
                {"path": "Dockerfile", "template": "dockerfile"},
                {"path": "docker-compose.yml", "template": "docker_compose"}
            ])
        
        return files
    
    def _generate_file_content(
        self, 
        file_info: Dict[str, Any], 
        requirements: ProjectRequirements
    ) -> str:
        """Generate content for a specific file."""
        template_name = file_info["template"]
        
        if template_name not in self.templates:
            return f"# {file_info['path']}\n# Generated file - add your content here\n"
        
        template_content = self.templates[template_name]
        
        # Replace placeholders
        replacements = {
            "{{project_name}}": requirements.project_name or "my-project",
            "{{project_type}}": requirements.project_type.value if requirements.project_type else "web_api",
            "{{language}}": requirements.language or "python",
            "{{framework}}": requirements.framework or "",
            "{{database}}": requirements.database or "",
            "{{description}}": f"{requirements.project_type.value if requirements.project_type else 'Project'} built with {requirements.language or 'Python'}"
        }
        
        content = template_content
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, value)
        
        return content
    
    def _load_file_templates(self) -> Dict[str, str]:
        """Load file templates."""
        return {
            "python_main": '''"""Main application entry point."""
from datetime import datetime

def main():
    """Main function."""
    print("Hello from {{project_name}}!")
    print(f"Current time: {datetime.now()}")

if __name__ == "__main__":
    main()
''',
            
            "python_fastapi_main": '''"""FastAPI application."""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import Dict, Any

# Create FastAPI app
app = FastAPI(
    title="{{project_name}}",
    description="{{description}}",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root() -> Dict[str, Any]:
    """Root endpoint."""
    return {
        "message": "Welcome to {{project_name}}!",
        "timestamp": datetime.now().isoformat(),
        "status": "running"
    }

@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
''',
            
            "python_requirements": '''# Core dependencies
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
python-multipart>=0.0.6
pydantic>=2.5.0

# Database dependencies
{% if database == "postgresql" %}
psycopg2-binary>=2.9.7
{% elif database == "mysql" %}
mysql-connector-python>=8.2.0
{% elif database == "sqlite" %}
# SQLite is built into Python
{% endif %}

# Development dependencies
pytest>=7.4.0
pytest-asyncio>=0.21.0
black>=23.0.0
ruff>=0.1.0
''',
            
            "js_main": '''// Main application entry point
console.log("Hello from {{project_name}}!");
console.log("Current time:", new Date().toISOString());

// Export for module usage
module.exports = {
    name: "{{project_name}}",
    version: "1.0.0"
};
''',
            
            "js_express_main": '''// Express.js application
const express = require('express');
const cors = require('cors');
const helmet = require('helmet');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(helmet());
app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Routes
app.get('/', (req, res) => {
    res.json({
        message: "Welcome to {{project_name}}!",
        timestamp: new Date().toISOString(),
        status: "running"
    });
});

app.get('/health', (req, res) => {
    res.json({ status: "healthy" });
});

// Error handling middleware
app.use((err, req, res, next) => {
    console.error(err.stack);
    res.status(500).json({ error: "Something went wrong!" });
});

// Start server
app.listen(PORT, () => {
    console.log(`{{project_name}} server running on port ${PORT}`);
});

module.exports = app;
''',
            
            "package_json": '''{
  "name": "{{project_name}}",
  "version": "1.0.0",
  "description": "{{description}}",
  "main": "index.js",
  "scripts": {
    "start": "node index.js",
    "dev": "nodemon index.js",
    "test": "jest"
  },
  "dependencies": {
    {% if framework == "express" %}
    "express": "^4.18.0",
    "cors": "^2.8.5",
    "helmet": "^7.1.0"
    {% else %}
    "axios": "^1.6.0"
    {% endif %}
  },
  "devDependencies": {
    "nodemon": "^3.0.0",
    "jest": "^29.7.0"
  },
  "keywords": ["{{project_type}}", "{{language}}"],
  "author": "",
  "license": "MIT"
}''',
            
            "dockerfile": '''FROM {% if language == "python" %}python:3.11-slim{% else %}node:18-alpine{% endif %}

WORKDIR /app

{% if language == "python" %}
# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Run application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
{% else %}
# Copy package files first for better caching
COPY package*.json ./
RUN npm install

# Copy application code
COPY . .

# Expose port
EXPOSE 3000

# Run application
CMD ["npm", "start"]
{% endif %}
''',
            
            "gitignore": '''# Byte-compiled / optimized / DLL files
__pycache__/
*.py[cod]
*$py.class

# C extensions
*.so

# Distribution / packaging
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
pip-wheel-metadata/
share/python-wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST

# Virtual environments
venv/
ENV/
env/
.venv/

# IDEs
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Logs
*.log
logs/

# Environment variables
.env
.env.local
.env.development.local
.env.test.local
.env.production.local

# Node.js
node_modules/
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# Build outputs
build/
dist/
*.tgz
*.tar.gz

# Database
*.db
*.sqlite3

# Temporary files
*.tmp
*.temp
''',
            
            "python_test": '''"""Test cases for {{project_name}}."""
import pytest
from main import main

def test_main_function():
    """Test main function runs without error."""
    try:
        main()
        assert True
    except Exception as e:
        pytest.fail(f"main() raised {e} unexpectedly!")

def test_basic_functionality():
    """Test basic functionality."""
    # Add your tests here
    assert 1 + 1 == 2
''',
            
            "js_test": '''// Test cases for {{project_name}}
const app = require('../index');

describe('{{project_name}}', () => {
    test('should export an object', () => {
        expect(typeof app).toBe('object');
    });
    
    test('should have name property', () => {
        expect(app.name).toBe('{{project_name}}');
    });
    
    test('basic functionality', () => {
        expect(1 + 1).toBe(2);
    });
});
'''
        }


# Global template generator instance
template_generator = ProjectTemplateGenerator()