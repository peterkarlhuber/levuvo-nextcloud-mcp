"""Expected, user-facing errors.

Every subclass of :class:`LevuvoError` carries a short English message that is safe to
show to an MCP client: it never contains credentials, tokens, HTTP headers or document
content. The MCP layer converts these errors into SDK ``ToolError`` results; anything
else is treated as an unexpected crash and only a generic message reaches the client.
"""

from __future__ import annotations


class LevuvoError(Exception):
    """Base class for anticipated errors with a client-safe message."""


class ConfigurationError(LevuvoError, ValueError):
    """Invalid or missing server configuration (raised at startup)."""


class InvalidArgumentError(LevuvoError, ValueError):
    """A tool argument is syntactically invalid (e.g. a malformed path)."""


class AccessDeniedError(LevuvoError, PermissionError):
    """The path is not released for the MCP agent (allowlist/denylist)."""


class NotFoundError(LevuvoError):
    """The file or folder does not exist (or is not visible to the technical user)."""


class LimitExceededError(LevuvoError):
    """A configured size/count limit was exceeded."""


class UnsupportedFormatError(LevuvoError, ValueError):
    """The document format cannot be converted to text."""


class DocumentError(LevuvoError):
    """The document is damaged, encrypted or otherwise unreadable."""


class NextcloudError(LevuvoError):
    """Nextcloud/WebDAV failed (authentication, permissions, network, server)."""


# Backwards-compatible name used by earlier versions of the code base.
WebDAVError = NextcloudError


class FileChangedError(LevuvoError):
    """The file has a different ETag than the caller expected (changed between two calls)."""
