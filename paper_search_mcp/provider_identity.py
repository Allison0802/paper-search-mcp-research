"""Truthful provider-facing identity for this maintained fork.

Set ``PAPER_SEARCH_MCP_CONTACT_EMAIL`` when a provider supports a maintainer
contact (for example, Crossref's polite-pool ``mailto`` parameter).  The
default identifies the public project repository and intentionally does not
invent a contact address.
"""

from importlib.metadata import PackageNotFoundError, version

from .config import get_env


DISTRIBUTION_NAME = "paper-search-mcp-research"
REPOSITORY_URL = "https://github.com/Allison0802/paper-search-mcp-research"


def _distribution_version() -> str:
    try:
        return version(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        # Keep source-tree execution identifiable before a wheel is installed.
        return "0.2.0"


def contact_email() -> str:
    """Return a user-supplied provider contact, never a placeholder."""
    return get_env("CONTACT_EMAIL", "").strip()


def provider_user_agent(context: str = "") -> str:
    """Build a provider User-Agent with an optional truthful contact."""
    details = [REPOSITORY_URL]
    if context:
        details.append(context)
    email = contact_email()
    if email:
        details.append(f"mailto:{email}")
    return f"{DISTRIBUTION_NAME}/{_distribution_version()} ({'; '.join(details)})"
