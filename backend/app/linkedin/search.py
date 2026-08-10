import logging
import re
from html import unescape

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

LINKEDIN_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LINKEDIN_JOB_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _extract_job_id(href: str, card=None) -> str | None:
    if card is not None:
        urn = card.get("data-entity-urn") or ""
        match = re.search(r"jobPosting:(\d+)", urn)
        if match:
            return match.group(1)

    match = re.search(r"/jobs/view/(?:[^/?]+-)?(\d+)", href)
    if match:
        return match.group(1)

    match = re.search(r"-(\d+)(?:\?|$)", href)
    if match:
        return match.group(1)

    return None


def _parse_job_card(li) -> dict | None:
    card = li.select_one(".base-card, .base-search-card, .job-search-card")
    link = li.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
    if not link:
        return None
    href = link.get("href") or ""
    job_id = _extract_job_id(href, card)
    if not job_id:
        logger.debug("Could not parse job id from href: %s", href)
        return None
    title_el = li.select_one(".base-search-card__title, h3")
    company_el = li.select_one(".base-search-card__subtitle, h4")
    location_el = li.select_one(".job-search-card__location, .base-search-card__metadata")
    title = unescape((title_el.get_text(strip=True) if title_el else "") or "Untitled")
    company = unescape((company_el.get_text(strip=True) if company_el else "") or "")
    location = unescape((location_el.get_text(strip=True) if location_el else "") or "")
    job_url = href if href.startswith("http") else f"https://www.linkedin.com{href}"
    return {
        "linkedin_job_id": job_id,
        "title": title,
        "company": company,
        "location": location,
        "job_url": job_url.split("?")[0],
        "description": "",
    }


async def search_linkedin_jobs(
    keywords: str,
    *,
    location: str = "",
    start: int = 0,
    limit: int = 25,
) -> list[dict]:
    params = {"keywords": keywords, "start": start}
    if location.strip():
        params["location"] = location.strip()

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(LINKEDIN_SEARCH_URL, params=params, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        jobs: list[dict] = []
        for li in soup.select("li"):
            job = _parse_job_card(li)
            if job and not any(j["linkedin_job_id"] == job["linkedin_job_id"] for j in jobs):
                jobs.append(job)
            if len(jobs) >= limit:
                break
        return jobs


async def fetch_job_description(job_id: str) -> str:
    meta = await fetch_job_posting(job_id)
    return meta.get("description") or ""


async def fetch_job_posting(job_id: str) -> dict[str, str]:
    """Fetch title/company/description from LinkedIn guest job posting API."""
    url = LINKEDIN_JOB_URL.format(job_id=job_id)
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, trust_env=False) as client:
        response = await client.get(url, headers=HEADERS)
        if response.status_code >= 400:
            logger.warning("LinkedIn job detail fetch failed for %s: %s", job_id, response.status_code)
            return {"title": "", "company": "", "description": "", "location": ""}
        soup = BeautifulSoup(response.text, "html.parser")

        title_el = soup.select_one(
            "h1.top-card-layout__title, h1.topcard__title, .top-card-layout__title, h1"
        )
        company_el = soup.select_one(
            "a.topcard__org-name-link, a.topcard__flavor--black-link, "
            ".topcard__org-name-link, .top-card-layout__card .topcard__flavor a, "
            ".topcard__flavor--black-link"
        )
        if not company_el:
            company_el = soup.select_one(".topcard__flavor")
        location_el = soup.select_one(
            ".topcard__flavor--bullet, span.topcard__flavor--bullet, "
            ".top-card__bullet, .main-job-card__location"
        )
        desc_el = soup.select_one(
            ".show-more-less-html__markup, .description__text, .description__text--rich"
        )

        title = unescape(title_el.get_text(" ", strip=True)) if title_el else ""
        company = unescape(company_el.get_text(" ", strip=True)) if company_el else ""
        location = unescape(location_el.get_text(" ", strip=True)) if location_el else ""
        if desc_el:
            description = unescape(desc_el.get_text("\n", strip=True))
        else:
            description = unescape(soup.get_text("\n", strip=True)[:4000])

        # Guest pages sometimes put company in a flavor span next to location
        if company and location and company == location:
            company = ""
        if not company:
            for el in soup.select(".topcard__flavor, .top-card-layout__entity-info a"):
                text = unescape(el.get_text(" ", strip=True))
                if text and text != location and text != title and len(text) < 120:
                    company = text
                    break

        return {
            "title": title or f"LinkedIn job {job_id}",
            "company": company,
            "location": location,
            "description": description,
        }
