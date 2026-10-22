import logging
from langchain_core.tools import tool
import requests
import trafilatura

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Web Page Fetching
# ---------------------------------------------------------------------------

# Kept in step with all_tools.py's _MCP_TOOL_RESULT_CHAR_LIMIT — same
# reasoning (bound a single tool result to what the local model's context
# can absorb), just a separate constant since this module doesn't import
# from all_tools.py (all_tools.py already imports from here).
_FETCH_WEBPAGE_CHAR_LIMIT = 12000


@tool
def fetch_webpage(url: str) -> str:
    """Fetch a specific webpage and extract its actual main content (not
    navigation, ads, or sidebar chrome) as clean text via boilerplate
    removal, not just an HTML-to-markdown dump. Use this after search_web
    when a result's snippet is only a pointer to what you need — a blurb
    saying a page has a full timeline/list/figures — rather than the detail
    itself, so you can read the real content instead of just relaying a
    link back to the user.

    Args:
        url: The exact URL to fetch, usually taken from a search_web result.
    """
    try:
        response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error("Error fetching %s: %s", url, e)
        return f"Couldn't fetch '{url}': {e}"

    extracted = trafilatura.extract(response.text, output_format="markdown", include_links=False)
    if not extracted:
        return (
            f"Couldn't extract readable article content from '{url}' — it may not be a "
            "plain content page (e.g. requires JavaScript, or is a non-article format)."
        )

    if len(extracted) > _FETCH_WEBPAGE_CHAR_LIMIT:
        total = len(extracted)
        extracted = extracted[:_FETCH_WEBPAGE_CHAR_LIMIT] + f"\n\n[...truncated, {total} chars total]"

    return extracted
