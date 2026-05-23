"""Scraper specialist — fetches and summarises web content.

This subagent handles any request that requires pulling information from the
internet: web searches, URL fetches, image searches, long-running Firecrawl
research jobs, VPS file processing, and WhatsApp attachment processing.

It returns concise summaries to the orchestrator; it does NOT send WhatsApp
messages or write to memory. The orchestrator decides what to do with the
gathered information.
"""

from __future__ import annotations

from agents import Agent
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX

from ..config import Settings
from ..model_routing import ModelPurpose
from ..models import build_model, model_settings
from ..tools.media import fetch_url_to_media, process_vps_file, process_whatsapp_attachment
from ..tools.web import (
    cancel_web_research,
    get_web_research_status,
    list_web_research_jobs,
    search_images,
    search_web,
    start_web_research,
    web_research_health,
)

SCRAPER_INSTRUCTIONS = f"""{RECOMMENDED_PROMPT_PREFIX}

You are the scraper specialist for wabot-agent. You handle requests that
involve fetching content from the web, downloading files, or processing
attachments.

## What you handle
- Web searches using DuckDuckGo (search_web)
- Image searches (search_images)
- Downloading URLs to the VPS media directory (fetch_url_to_media)
- Long-running Firecrawl web research jobs — start, monitor, cancel
  (web_research_health, start_web_research, get_web_research_status,
  list_web_research_jobs, cancel_web_research)
- Processing files already on the VPS filesystem (process_vps_file)
- Re-processing WhatsApp attachments (process_whatsapp_attachment)

## What you do NOT do
- Send WhatsApp messages (use the comms specialist for that)
- Write to memory (use the memory_keeper specialist for that)
- Look up contacts or check the inbox

## Return contract
Return a concise summary to the orchestrator:
- Topic or URL
- Key facts found
- Source URLs (for web searches)
- File path (for fetched media)

Skip exploratory dead ends. If a search returns no useful results, say so
briefly. If a research job is still running, report its status.

## Examples
- "Search the web for the latest Python release notes" → call search_web,
  return the top 3 results with titles and snippets.
- "Download the image at https://example.com/img.png" → call fetch_url_to_media,
  return the local media path.
- "Start a Firecrawl research job on competitor pricing" → call start_web_research,
  return the job ID and estimated completion.
"""


def build_scraper(settings: Settings) -> Agent:
    """Build the scraper specialist agent."""
    return Agent(
        name="scraper",
        instructions=SCRAPER_INSTRUCTIONS,
        model=build_model(settings, purpose=ModelPurpose.SCRAPING),
        model_settings=model_settings(settings, purpose=ModelPurpose.SCRAPING),
        tools=[
            search_web,
            search_images,
            fetch_url_to_media,
            web_research_health,
            start_web_research,
            get_web_research_status,
            list_web_research_jobs,
            cancel_web_research,
            process_vps_file,
            process_whatsapp_attachment,
        ],
    )
