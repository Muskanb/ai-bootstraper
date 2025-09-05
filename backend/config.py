"""Application configuration."""
import os
from typing import List
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    """Application settings."""
    
    # Gemini API Configuration
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    GEMINI_API_URL: str = os.getenv("GEMINI_API_URL", "https://generativelanguage.googleapis.com/v1beta")
    
    # Application Configuration
    APP_ENV: str = os.getenv("APP_ENV", "development")
    APP_PORT: int = int(os.getenv("APP_PORT", "8000"))
    APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
    DEBUG: bool = os.getenv("DEBUG", "True").lower() == "true"
    
    # Session Configuration
    SESSION_TIMEOUT: int = int(os.getenv("SESSION_TIMEOUT", "3600"))
    MAX_ITERATIONS: int = int(os.getenv("MAX_ITERATIONS", "50"))
    MAX_EXECUTION_TIME: int = int(os.getenv("MAX_EXECUTION_TIME", "300"))
    
    # WebSocket Configuration
    WS_HEARTBEAT_INTERVAL: int = int(os.getenv("WS_HEARTBEAT_INTERVAL", "30"))
    WS_MAX_CONNECTIONS: int = int(os.getenv("WS_MAX_CONNECTIONS", "100"))
    
    # CORS Configuration
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "data/logs/app.log")
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-this-in-production")
    ENABLE_SANDBOX: bool = os.getenv("ENABLE_SANDBOX", "True").lower() == "true"
    
    # Rate Limiting
    RATE_LIMIT_REQUESTS: int = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
    RATE_LIMIT_PERIOD: int = int(os.getenv("RATE_LIMIT_PERIOD", "60"))
    
    # File Storage
    DATA_DIR: str = os.getenv("DATA_DIR", "./data")
    SESSION_DIR: str = os.getenv("SESSION_DIR", "./data/sessions")
    LOG_DIR: str = os.getenv("LOG_DIR", "./data/logs")
    
    # Project Creation Configuration
    PROJECT_BASE_DIR: str = os.getenv("PROJECT_BASE_DIR", "./apps")
    ALLOW_ABSOLUTE_PROJECT_PATHS: bool = os.getenv("ALLOW_ABSOLUTE_PROJECT_PATHS", "False").lower() == "true"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Create global settings instance
settings = Settings()

# Ensure directories exist
os.makedirs(settings.DATA_DIR, exist_ok=True)
os.makedirs(settings.SESSION_DIR, exist_ok=True)
os.makedirs(settings.LOG_DIR, exist_ok=True)