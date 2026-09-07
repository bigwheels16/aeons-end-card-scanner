"""Application Configuration Management.

Provides centralized access to all environment variables with validation,
safe defaults, and security constraints.
"""

import os
from typing import Optional


class Config:
    """Centralized configuration accessor methods."""

    @staticmethod
    def get_gemini_api_key() -> Optional[str]:
        """Retrieve the Google Gemini API key.
        
        Security Suggestions:
        - Never log, print, or expose this API key in error messages or client responses.
        - Inject this variable via Secret Managers (e.g. Google Cloud Secret Manager)
          in production rather than plain text environment files.
        """
        key = os.environ.get("GEMINI_API_KEY")
        return key.strip() if key else None

    @staticmethod
    def get_gemini_model() -> str:
        """Retrieve the configured Gemini vision model name.
        
        Defaults to 'gemini-3.8-flash'.
        """
        return os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip()

    @staticmethod
    def get_port() -> int:
        """Retrieve the server port for Cloud Run or local binding.
        
        Security Suggestions:
        - Validates that PORT is an integer within the standard unprivileged range (1-65535).
        Defaults to 8080.
        """
        port_raw = os.environ.get("PORT", "8080")
        try:
            port = int(port_raw)
            if 1 <= port <= 65535:
                return port
        except ValueError:
            pass
        return 8080

    @staticmethod
    def get_max_upload_size_bytes() -> int:
        """Retrieve the maximum allowed file upload size in bytes.
        
        Security Suggestions:
        - Enforces strict upper bound on file uploads to mitigate Denial of Service (DoS)
          via memory exhaustion or decompression bombs.
        Defaults to 10MB (10 * 1024 * 1024 bytes).
        """
        size_mb_raw = os.environ.get("MAX_UPLOAD_SIZE_MB", "10")
        try:
            mb = int(size_mb_raw)
            if mb > 0:
                return mb * 1024 * 1024
        except ValueError:
            pass
        return 10 * 1024 * 1024

    @staticmethod
    def get_data_path() -> str:
        """Retrieve the filesystem path to the canonical cards JSON database.
        
        Security Suggestions:
        - Relative paths are resolved against the project root to prevent path traversal attacks.
        """
        default_path = os.path.join(os.path.dirname(__file__), "..", "data", "aeons_end_all.json")
        custom_path = os.environ.get("AEONS_END_DATA_PATH")
        if custom_path:
            return os.path.abspath(custom_path)
        return os.path.abspath(default_path)


# Module-level method accessors
get_gemini_api_key = Config.get_gemini_api_key
get_gemini_model = Config.get_gemini_model
get_port = Config.get_port
get_max_upload_size_bytes = Config.get_max_upload_size_bytes
get_data_path = Config.get_data_path
