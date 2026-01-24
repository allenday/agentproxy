"""
Data sanitization for telemetry exports.

Provides three modes:
- "none": Don't export task descriptions at all (maximum privacy)
- "hash": Export only a cryptographic hash (default, safe, allows correlation)
- "full": Export everything (⚠️ DANGEROUS - only use with trusted internal systems)

For custom sanitization logic, subclass BaseSanitizer and set via set_sanitizer().
"""

import os
import hashlib
from typing import Any, Dict, Optional
from abc import ABC, abstractmethod


class BaseSanitizer(ABC):
    """
    Base class for custom telemetry sanitizers.

    Implement this interface to create custom sanitization logic.
    Use set_sanitizer() to register your implementation.
    """

    @abstractmethod
    def sanitize_task_description(self, task: str) -> Optional[str]:
        """
        Sanitize a task description for export.

        Args:
            task: Raw task description from user

        Returns:
            Sanitized version safe for export, or None to omit
        """
        pass

    @abstractmethod
    def sanitize_attributes(self, attributes: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize telemetry attributes dictionary.

        Args:
            attributes: Raw attributes dictionary

        Returns:
            Sanitized attributes safe for export
        """
        pass


class TelemetrySanitizer(BaseSanitizer):
    """
    Default sanitizer with three modes: none, hash, full.

    This implementation does NOT attempt to surgically remove secrets from strings.
    That approach is fundamentally flawed and creates false security.

    Instead, we offer three honest choices:
    - none: Don't export (most private)
    - hash: Export only hash (default, safe, allows correlation)
    - full: Export everything (only for trusted systems)

    If you need custom sanitization logic, implement BaseSanitizer.
    """

    def __init__(self):
        """Initialize sanitizer with configuration from environment."""
        mode = os.getenv("AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS", "hash").lower()

        # Only accept valid modes
        if mode not in ["none", "hash", "full"]:
            mode = "hash"  # Safe default

        self.export_mode = mode
        self.max_task_length = self._parse_max_task_length()

    def _parse_max_task_length(self) -> int:
        """Parse max task length from environment with safe default."""
        default_length = 100
        max_length_str = os.getenv("AGENTPROXY_TELEMETRY_MAX_TASK_LENGTH", str(default_length))
        try:
            return int(max_length_str)
        except ValueError:
            return default_length

    def sanitize_task_description(self, task: str) -> Optional[str]:
        """
        Sanitize task description based on configured mode.

        Args:
            task: Raw task description

        Returns:
            - None if mode is "none"
            - Hash string if mode is "hash" (default)
            - Truncated task if mode is "full"
        """
        if not task:
            return None

        if self.export_mode == "none":
            # Maximum privacy: don't export at all
            return None

        elif self.export_mode == "hash":
            # Safe default: export only hash for correlation
            task_hash = hashlib.sha256(task.encode()).hexdigest()[:16]
            return f"task_{task_hash}"

        elif self.export_mode == "full":
            # ⚠️ DANGEROUS: export everything
            # Only use with trusted, internal telemetry systems
            if len(task) > self.max_task_length:
                return task[:self.max_task_length] + "..."
            return task

        return None

    def sanitize_attributes(self, attributes: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize telemetry attributes.

        Applies task description sanitization to attributes containing task descriptions.
        All other attributes pass through unchanged.

        Args:
            attributes: Raw attributes dictionary

        Returns:
            Sanitized attributes
        """
        sanitized = {}

        for key, value in attributes.items():
            # Apply task sanitization to task description attributes
            if "task" in key.lower() and "description" in key.lower():
                if isinstance(value, str):
                    sanitized_value = self.sanitize_task_description(value)
                    if sanitized_value is not None:
                        sanitized[key] = sanitized_value
                    # If None, omit the attribute
            else:
                # All other attributes pass through unchanged
                sanitized[key] = value

        return sanitized


# Global sanitizer instance
_sanitizer: Optional[BaseSanitizer] = None


def get_sanitizer() -> BaseSanitizer:
    """
    Get the current sanitizer instance.

    Returns the global sanitizer, creating default if none exists.
    Checks AGENTPROXY_CUSTOM_SANITIZER env var for custom implementation.
    """
    global _sanitizer
    if _sanitizer is None:
        # Check for custom sanitizer via environment variable
        custom_sanitizer_path = os.getenv("AGENTPROXY_CUSTOM_SANITIZER")
        if custom_sanitizer_path:
            _sanitizer = _load_custom_sanitizer(custom_sanitizer_path)
        else:
            _sanitizer = TelemetrySanitizer()
    return _sanitizer


def _load_custom_sanitizer(module_path: str) -> BaseSanitizer:
    """
    Load a custom sanitizer from a module path.

    Args:
        module_path: Python module path like "mypackage.MySanitizer"

    Returns:
        Custom sanitizer instance

    Raises:
        ImportError: If module cannot be imported
        AttributeError: If class not found in module
        TypeError: If class doesn't implement BaseSanitizer
    """
    import importlib

    # Split module path and class name
    parts = module_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError(
            f"Invalid sanitizer path: {module_path}. "
            "Expected format: 'module.path.ClassName'"
        )

    module_name, class_name = parts

    # Import module and get class
    module = importlib.import_module(module_name)
    sanitizer_class = getattr(module, class_name)

    # Verify it implements BaseSanitizer
    if not issubclass(sanitizer_class, BaseSanitizer):
        raise TypeError(
            f"{module_path} must implement BaseSanitizer interface"
        )

    # Instantiate and return
    return sanitizer_class()


def set_sanitizer(sanitizer: BaseSanitizer):
    """
    Set a custom sanitizer implementation.

    Use this to provide your own sanitization logic by implementing BaseSanitizer.

    Example:
        class MySanitizer(BaseSanitizer):
            def sanitize_task_description(self, task: str) -> Optional[str]:
                # Your custom logic here
                return custom_sanitize(task)

            def sanitize_attributes(self, attributes: Dict[str, Any]) -> Dict[str, Any]:
                # Your custom logic here
                return custom_sanitize_attrs(attributes)

        set_sanitizer(MySanitizer())

    Args:
        sanitizer: Custom sanitizer implementing BaseSanitizer
    """
    global _sanitizer
    _sanitizer = sanitizer


def reset_sanitizer():
    """Reset sanitizer to default (for testing)."""
    global _sanitizer
    _sanitizer = None
