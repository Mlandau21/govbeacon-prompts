"""Scrape SAM.gov opportunity metadata and attachments using Playwright."""

from __future__ import annotations

import csv
import io
import json
import logging
import mimetypes
import random
import re
import sys
import time
import zipfile
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import (
    BrowserContext,
    APIRequestContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


LOGGER = logging.getLogger(__name__)

SAM_HOME_URL = "https://sam.gov/content/home"
SESSION_DIR = Path(".playwright/session")

OPPORTUNITY_DETAIL_URL = (
    "https://sam.gov/api/prod/opps/v2/opportunities/{opportunity_id}?api_key=null&random={nonce}"
)
ORGANIZATION_DETAIL_URL = (
    "https://sam.gov/api/prod/federalorganizations/v1/organizations/{organization_id}?api_key=null&random={nonce}"
)
ATTACHMENTS_LIST_URL = (
    "https://sam.gov/api/prod/opps/v3/opportunities/{opportunity_id}/resources?api_key=null&excludeDeleted=false&withScanResult=false&random={nonce}"
)
ATTACHMENT_DOWNLOAD_URL = (
    "https://sam.gov/api/prod/opps/v3/opportunities/{opportunity_id}/resources/download/zip?api_key=null&resourceIds={resource_id}&random={nonce}"
)

METADATA_HEADERS = [
    "sam-url",
    "opportunity_id",
    "title",
    "description",
    "published_date",
    "response_date",
    "set_aside",
    "naics",
    "psc",
    "place_of_performance",
    "contact_information",
    "department",
    "sub_tier",
    "office",
]


@dataclass
class ScrapeConfig:
    input_csv: Path
    output_dir: Path
    require_login: bool = False
    limit: Optional[int] = None
    concurrency: int = 2


@dataclass
class OpportunityMetadata:
    sam_url: str
    opportunity_id: str
    title: str = ""
    description: str = ""
    published_date: str = ""
    response_date: str = ""
    set_aside: str = ""
    naics: str = ""
    psc: str = ""
    place_of_performance: str = ""
    contact_information: str = ""
    department: str = ""
    sub_tier: str = ""
    office: str = ""

    def to_csv_row(self) -> Dict[str, str]:
        return {
            "sam-url": self.sam_url,
            "opportunity_id": self.opportunity_id,
            "title": self.title,
            "description": self.description,
            "published_date": self.published_date,
            "response_date": self.response_date,
            "set_aside": self.set_aside,
            "naics": self.naics,
            "psc": self.psc,
            "place_of_performance": self.place_of_performance,
            "contact_information": self.contact_information,
            "department": self.department,
            "sub_tier": self.sub_tier,
            "office": self.office,
        }

    def update(self, **fields: str) -> None:
        for key, value in fields.items():
            if not value:
                continue
            if hasattr(self, key):
                setattr(self, key, value)


@dataclass
class AttachmentInfo:
    name: str
    url: str
    file_type: Optional[str] = None
    size: Optional[str] = None
    local_path: Optional[Path] = None
    attachment_id: Optional[str] = None
    resource_id: Optional[str] = None


@dataclass
class OpportunityResult:
    metadata: OpportunityMetadata
    attachments: List[AttachmentInfo] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    payload: Optional[Dict[str, Any]] = None
    status: str = "success"


def scrape_opportunities(
    *,
    input_csv: Path,
    output_dir: Path,
    require_login: bool,
    limit: Optional[int],
    concurrency: int,
) -> None:
    """Entry point invoked by the CLI."""

    config = ScrapeConfig(
        input_csv=input_csv,
        output_dir=output_dir,
        require_login=require_login,
        limit=limit,
        concurrency=concurrency,
    )

    manager = PlaywrightSessionManager(SESSION_DIR)
    manager.prepare_session(require_login=config.require_login)

    config.output_dir.mkdir(parents=True, exist_ok=True)

    scraper = OpportunityScraper(config=config, session_manager=manager)
    results = scraper.run()
    LOGGER.info("Scraped %s opportunities", len(results))


class PlaywrightSessionManager:
    """Handle persistent browser sessions for SAM.gov."""

    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir

    def prepare_session(self, *, require_login: bool) -> None:
        """Ensure the persistent session directory is initialized."""

        self.session_dir.mkdir(parents=True, exist_ok=True)

        has_existing_state = any(self.session_dir.iterdir())
        if not has_existing_state and not require_login:
            LOGGER.warning(
                "No existing SAM.gov session found. Re-run the command with --login to authenticate."
            )
            require_login = True

        with sync_playwright() as playwright:
            context = self._launch_context(playwright, headless=not require_login)
            try:
                page = context.new_page()
                page.goto(SAM_HOME_URL, wait_until="load")

                if require_login:
                    LOGGER.info(
                        "Browser opened for SAM.gov login. Complete authentication and wait for the script to continue."
                    )
                    if sys.stdin and sys.stdin.isatty():
                        input("Press Enter after you finish logging in...")
                    else:
                        # Allow time for interactive login in non-interactive environments.
                        time.sleep(120)
                else:
                    LOGGER.debug("Validated existing SAM.gov session in headless mode.")
            finally:
                context.close()

    def launch_context(self, playwright, *, headless: bool = True) -> BrowserContext:
        return self._launch_context(playwright, headless=headless)

    def _launch_context(self, playwright, *, headless: bool) -> BrowserContext:
        browser = playwright.chromium

        context = browser.launch_persistent_context(
            user_data_dir=str(self.session_dir.resolve()),
            headless=headless,
            viewport={"width": 1280, "height": 720},
            args=["--start-maximized"],
        )
        return context


class OpportunityScraper:
    def __init__(self, *, config: ScrapeConfig, session_manager: PlaywrightSessionManager) -> None:
        self.config = config
        self.session_manager = session_manager
        self.metadata_dir = self.config.output_dir / "metadata"
        self.attachments_dir = self.config.output_dir / "attachments"
        self.manifest_dir = self.config.output_dir / "manifests"
        self.results: List[OpportunityResult] = []

    def run(self) -> List[OpportunityResult]:
        rows = self._load_input_rows()
        if not rows:
            LOGGER.warning("No sam-url entries found in %s", self.config.input_csv)
            return []

        self._ensure_output_dirs()

        with sync_playwright() as playwright:
            context = self.session_manager.launch_context(playwright, headless=True)
            api_context = playwright.request.new_context(
                storage_state=context.storage_state()
            )
            try:
                page = context.new_page()
                for index, row in enumerate(rows, start=1):
                    result = self._process_row(
                        page,
                        api_context,
                        row,
                        index=index,
                        total=len(rows),
                    )
                    self.results.append(result)
            finally:
                api_context.dispose()
                context.close()

        self._write_metadata(self.results)
        self._write_manifest(self.results)
        successes = sum(1 for result in self.results if result.status == "success")
        attachments_downloaded = sum(
            1
            for result in self.results
            for attachment in result.attachments
            if attachment.local_path and attachment.local_path.exists()
        )
        failures = len(self.results) - successes

        LOGGER.info(
            "Scrape finished: %s success, %s with errors, %s attachments downloaded",
            successes,
            failures,
            attachments_downloaded,
        )
        return self.results

    def _load_input_rows(self) -> List[Dict[str, str]]:
        with self.config.input_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if "sam-url" not in reader.fieldnames:
                raise ValueError("input.csv must contain a 'sam-url' column")

            rows: List[Dict[str, str]] = []
            for row in reader:
                if not row.get("sam-url"):
                    continue
                rows.append(row)

        if self.config.limit:
            rows = rows[: self.config.limit]

        return rows

    def _ensure_output_dirs(self) -> None:
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_dir.mkdir(parents=True, exist_ok=True)

    def _process_row(
        self,
        page: Page,
        api_context: APIRequestContext,
        row: Dict[str, str],
        *,
        index: int,
        total: int,
    ) -> OpportunityResult:
        sam_url = row["sam-url"].strip()
        opportunity_id = parse_opportunity_id(sam_url)
        metadata = OpportunityMetadata(sam_url=sam_url, opportunity_id=opportunity_id)
        result = OpportunityResult(metadata=metadata)

        LOGGER.info("[%s/%s] Processing %s", index, total, sam_url)

        api_data = self._fetch_opportunity_json(api_context, opportunity_id)
        org_data = None
        if api_data:
            org_id = api_data.get("data2", {}).get("organizationId")
            if org_id:
                org_data = self._fetch_organization_json(api_context, org_id)

        try:
            page.goto(sam_url, wait_until="networkidle", timeout=90_000)
            html = page.content()
            fields: Dict[str, str] = {}

            if api_data:
                fields.update(extract_metadata_from_api(api_data, org_data))

            html_fields = extract_metadata_from_html(html)
            for key, value in html_fields.items():
                if not fields.get(key):
                    fields[key] = value

            metadata.update(**fields)
            result.payload = {
                "opportunity": api_data,
                "organization": org_data,
            }

            result.attachments = self._collect_attachments(
                api_context=api_context,
                opportunity_id=opportunity_id,
                sam_url=sam_url,
                html=html,
            )
            self._download_attachments(api_context, result)
        except PlaywrightTimeoutError as exc:
            LOGGER.exception("Timeout loading %s", sam_url)
            result.errors.append(f"timeout: {exc}")
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.exception("Failed to scrape %s", sam_url)
            result.errors.append(f"error: {exc}")

        if result.errors:
            result.status = "error"

        return result

    def _download_attachments(
        self, api_context: APIRequestContext, result: OpportunityResult
    ) -> None:
        if not result.attachments:
            return

        opportunity_dir = self.attachments_dir / result.metadata.opportunity_id
        opportunity_dir.mkdir(parents=True, exist_ok=True)

        used_names: set[str] = set()

        for attachment in result.attachments:
            try:
                output_path = self._download_single_attachment(
                    api_context,
                    result.metadata.opportunity_id,
                    attachment,
                    opportunity_dir,
                    used_names,
                )
                if output_path:
                    attachment.local_path = output_path
                    LOGGER.info("Downloaded attachment %s", output_path.name)
            except Exception as exc:  # pylint: disable=broad-except
                LOGGER.exception(
                    "Failed to download attachment %s from %s",
                    attachment.name,
                    attachment.url or attachment.resource_id,
                )
                result.errors.append(f"attachment:{attachment.name}:{exc}")

    def _download_single_attachment(
        self,
        api_context: APIRequestContext,
        opportunity_id: str,
        attachment: AttachmentInfo,
        destination_dir: Path,
        used_names: set[str],
    ) -> Optional[Path]:
        if attachment.resource_id:
            zip_bytes = self._download_attachment_zip(
                api_context, opportunity_id, attachment.resource_id
            )
            if not zip_bytes:
                raise RuntimeError(
                    f"Failed to request download for resource {attachment.resource_id}"
                )
            extracted_paths = self._extract_zip_entries(
                zip_bytes,
                destination_dir,
                attachment.name,
                used_names,
            )
            if not extracted_paths:
                raise RuntimeError(
                    f"Downloaded archive for {attachment.name} but found no files"
                )
            return extracted_paths[0]

        if not attachment.url:
            raise ValueError("Attachment URL is empty")

        response = api_context.get(attachment.url, timeout=120_000)
        if response.status >= 400:
            raise RuntimeError(
                f"Download failed with status {response.status} for {attachment.url}"
            )

        data = response.body()
        filename = self._build_filename(attachment)
        unique_name = self._ensure_unique_filename(filename, destination_dir, used_names)
        output_path = destination_dir / unique_name

        with output_path.open("wb") as handle:
            handle.write(data)

        return output_path

    def _build_filename(self, attachment: AttachmentInfo) -> str:
        preferred = sanitize_filename(attachment.name or "")

        parsed = urlparse(attachment.url)
        url_name = sanitize_filename(Path(unquote(parsed.path)).name)

        name = preferred or url_name or "attachment"

        if "." not in name:
            extension = ""
            if attachment.file_type:
                extension = _extension_from_mime_or_type(attachment.file_type)
            if not extension and url_name and "." in url_name:
                extension = Path(url_name).suffix
            if extension and not name.endswith(extension):
                name = f"{name}{extension}"

        return name

    @staticmethod
    def _ensure_unique_filename(
        filename: str, destination_dir: Path, used_names: set[str]
    ) -> str:
        base = Path(filename)
        stem = base.stem or "attachment"
        suffix = base.suffix

        candidate = f"{stem}{suffix}"
        counter = 1
        while candidate in used_names or (destination_dir / candidate).exists():
            candidate = f"{stem}_{counter}{suffix}"
            counter += 1

        used_names.add(candidate)
        return candidate

    def _fetch_opportunity_json(
        self, api_context: APIRequestContext, opportunity_id: str
    ) -> Optional[Dict[str, Any]]:
        url = OPPORTUNITY_DETAIL_URL.format(
            opportunity_id=opportunity_id, nonce=self._nonce()
        )
        try:
            response = api_context.get(url, timeout=120_000)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("Failed to request opportunity JSON for %s: %s", opportunity_id, exc)
            return None

        if response.status >= 400:
            LOGGER.warning(
                "Opportunity API returned status %s for %s", response.status, opportunity_id
            )
            return None

        try:
            return response.json()
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("Invalid JSON for opportunity %s: %s", opportunity_id, exc)
            return None

    def _fetch_organization_json(
        self, api_context: APIRequestContext, organization_id: str
    ) -> Optional[Dict[str, Any]]:
        url = ORGANIZATION_DETAIL_URL.format(
            organization_id=organization_id, nonce=self._nonce()
        )
        try:
            response = api_context.get(url, timeout=120_000)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("Failed to request organization JSON for %s: %s", organization_id, exc)
            return None

        if response.status >= 400:
            LOGGER.warning(
                "Organization API returned status %s for %s", response.status, organization_id
            )
            return None

        try:
            return response.json()
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("Invalid JSON for organization %s: %s", organization_id, exc)
            return None

    def _fetch_attachments_list(
        self, api_context: APIRequestContext, opportunity_id: str
    ) -> List[AttachmentInfo]:
        url = ATTACHMENTS_LIST_URL.format(
            opportunity_id=opportunity_id, nonce=self._nonce()
        )
        try:
            response = api_context.get(url, timeout=120_000)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning(
                "Failed to request attachments list for %s: %s", opportunity_id, exc
            )
            return []

        if response.status >= 400:
            LOGGER.debug(
                "Attachments API returned status %s for %s", response.status, opportunity_id
            )
            return []

        try:
            payload = response.json()
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("Invalid attachments JSON for %s: %s", opportunity_id, exc)
            return []

        attachments: List[AttachmentInfo] = []
        seen: set[tuple[str, Optional[str]]] = set()

        for group in payload.get("_embedded", {}).get("opportunityAttachmentList", []):
            for attachment in group.get("attachments", []):
                name = (attachment.get("name") or "").strip()
                resource_id = attachment.get("resourceId")
                key = (name, resource_id)
                if key in seen:
                    continue
                seen.add(key)
                attachments.append(
                    AttachmentInfo(
                        name=name,
                        url="",
                        file_type=attachment.get("mimeType"),
                        size=str(attachment.get("size")) if attachment.get("size") else None,
                        attachment_id=attachment.get("attachmentId"),
                        resource_id=resource_id,
                    )
                )

        return attachments

    def _download_attachment_zip(
        self,
        api_context: APIRequestContext,
        opportunity_id: str,
        resource_id: str,
    ) -> Optional[bytes]:
        url = ATTACHMENT_DOWNLOAD_URL.format(
            opportunity_id=opportunity_id,
            resource_id=resource_id,
            nonce=self._nonce(),
        )
        try:
            response = api_context.get(url, timeout=120_000)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning(
                "Failed to request download link for resource %s: %s", resource_id, exc
            )
            return None

        if response.status >= 400:
            LOGGER.warning(
                "Download link request returned status %s for resource %s",
                response.status,
                resource_id,
            )
            return None

        try:
            payload = response.json()
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("Invalid download link JSON for resource %s: %s", resource_id, exc)
            return None

        location = payload.get("location")
        if not location:
            return None

        file_response = api_context.get(location, timeout=120_000)
        if file_response.status >= 400:
            LOGGER.warning(
                "Attachment download failed with status %s for resource %s",
                file_response.status,
                resource_id,
            )
            return None

        return file_response.body()

    def _extract_zip_entries(
        self,
        zip_bytes: bytes,
        destination_dir: Path,
        preferred_name: Optional[str],
        used_names: set[str],
    ) -> List[Path]:
        paths: List[Path] = []
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                data = archive.read(info)
                inner_name = sanitize_filename(Path(info.filename).name)
                if preferred_name:
                    preferred = sanitize_filename(Path(preferred_name).name)
                    if preferred:
                        inner_name = preferred
                if not inner_name:
                    inner_name = "attachment"
                unique_name = self._ensure_unique_filename(
                    inner_name, destination_dir, used_names
                )
                output_path = destination_dir / unique_name
                with output_path.open("wb") as handle:
                    handle.write(data)
                paths.append(output_path)
        return paths

    def _collect_attachments(
        self,
        api_context: APIRequestContext,
        opportunity_id: str,
        sam_url: str,
        html: str,
    ) -> List[AttachmentInfo]:
        attachments = self._fetch_attachments_list(api_context, opportunity_id)
        if attachments:
            return attachments
        return collect_attachments_from_html(html, sam_url)

    @staticmethod
    def _nonce() -> int:
        return random.randint(1, 10**12)

    def _write_metadata(self, results: List[OpportunityResult]) -> None:
        metadata_path = self.metadata_dir / "sam-metadata.csv"
        existing = self._load_existing_metadata(metadata_path)

        for result in results:
            existing[result.metadata.sam_url] = result.metadata.to_csv_row()

        with metadata_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=METADATA_HEADERS)
            writer.writeheader()
            for sam_url in sorted(existing.keys()):
                writer.writerow(existing[sam_url])

    @staticmethod
    def _load_existing_metadata(path: Path) -> Dict[str, Dict[str, str]]:
        if not path.exists():
            return {}

        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = {row["sam-url"]: row for row in reader if row.get("sam-url")}
        return rows

    def _write_manifest(self, results: List[OpportunityResult]) -> None:
        manifest_path = self.manifest_dir / f"manifest-{datetime.utcnow():%Y%m%d-%H%M%S}.json"

        manifest_payload = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "input_csv": str(self.config.input_csv),
            "output_dir": str(self.config.output_dir),
            "metadata_csv": str(self.metadata_dir / "sam-metadata.csv"),
            "attachments_dir": str(self.attachments_dir),
            "opportunities": [self._manifest_entry(result) for result in results],
        }

        with manifest_path.open("w", encoding="utf-8") as handle:
            json.dump(manifest_payload, handle, indent=2)

        LOGGER.info("Wrote manifest %s", manifest_path)

    def _manifest_entry(self, result: OpportunityResult) -> Dict[str, Any]:
        return {
            "sam_url": result.metadata.sam_url,
            "opportunity_id": result.metadata.opportunity_id,
            "status": result.status,
            "errors": result.errors,
            "metadata": result.metadata.to_csv_row(),
            "attachments": [
                {
                    "name": attachment.name,
                    "url": attachment.url,
                    "file_type": attachment.file_type,
                    "size": attachment.size,
                    "attachment_id": attachment.attachment_id,
                    "resource_id": attachment.resource_id,
                    "downloaded": bool(attachment.local_path and attachment.local_path.exists()),
                    "local_path": _relative_path(attachment.local_path, self.config.output_dir),
                }
                for attachment in result.attachments
            ],
        }


def parse_opportunity_id(sam_url: str) -> str:
    match = re.search(r"/opp/([a-zA-Z0-9]+)/", sam_url)
    if match:
        return match.group(1)

    tail = sam_url.rstrip("/").split("/")[-1]
    return re.sub(r"[^A-Za-z0-9]+", "-", tail)


def extract_metadata_from_payload(payload: Dict[str, Any]) -> Dict[str, str]:
    data: Dict[str, str] = {}

    data["title"] = stringify(_find_first(payload, ["title", "opportunityTitle", "noticeTitle"]))
    data["description"] = stringify(_find_first(payload, ["description", "summary", "noticeSummary"]))
    data["published_date"] = stringify(
        _find_first(payload, ["publishDate", "publicationDate", "postedDate", "publish_date"])
    )
    data["response_date"] = stringify(
        _find_first(payload, ["responseDate", "responseDueDate", "closeDate", "responseCloseDate"])
    )
    data["set_aside"] = stringify(
        _find_first(payload, ["typeOfSetAside", "setAside", "set_aside"])
    )

    naics_value = _find_first(payload, ["naics", "naicsCodes", "naics_code"])
    data["naics"] = format_code_list(naics_value)

    psc_value = _find_first(payload, ["psc", "pscCodes", "psc_code"])
    data["psc"] = format_code_list(psc_value, code_keys=("psc", "pscCode", "code"))

    place_value = _find_first(payload, ["placeOfPerformance", "place_of_performance"])
    data["place_of_performance"] = format_place_of_performance(place_value)

    contacts_value = _find_first(payload, ["contacts", "pointsOfContact", "primaryContact", "contact"])
    data["contact_information"] = format_contacts(contacts_value)

    hierarchy = _find_first(payload, ["organizationHierarchy", "organizationHierarchyDisplay"])
    department, sub_tier, office = extract_organization_levels(hierarchy)
    if not department:
        department = stringify(_find_first(payload, ["department", "agency", "agencyName"]))
    if not sub_tier:
        sub_tier = stringify(_find_first(payload, ["subTier", "subtier", "subAgency"]))
    if not office:
        office = stringify(_find_first(payload, ["office", "officeName"]))

    data["department"] = department
    data["sub_tier"] = sub_tier
    data["office"] = office

    return {key: value for key, value in data.items() if value}


def extract_metadata_from_api(
    opportunity: Dict[str, Any], organization: Optional[Dict[str, Any]]
) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    details = opportunity.get("data2", {})

    fields["title"] = stringify(details.get("title"))

    description_body = ""
    for item in opportunity.get("description", []) or []:
        body = item.get("body")
        if body:
            description_body = body
            break
    fields["description"] = html_to_text(description_body)

    fields["published_date"] = to_date_string(opportunity.get("postedDate"))
    response_value = (
        details.get("solicitation", {})
        .get("deadlines", {})
        .get("response")
    )
    fields["response_date"] = to_date_string(response_value)

    fields["set_aside"] = stringify(
        details.get("typeOfSetAside")
        or details.get("setAside")
        or details.get("sbaProgram")
    )

    fields["naics"] = format_naics_codes(details.get("naics"))
    fields["psc"] = stringify(details.get("classificationCode"))
    fields["place_of_performance"] = format_place_of_performance(
        details.get("placeOfPerformance")
    )
    fields["contact_information"] = format_contacts(details.get("pointOfContact"))

    department, sub_tier, office = extract_department_fields(organization)
    fields["department"] = department
    fields["sub_tier"] = sub_tier
    fields["office"] = office

    return {key: value for key, value in fields.items() if value}


def extract_metadata_from_html(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    data: Dict[str, str] = {}

    title_meta = soup.select_one('meta[property="og:title"]') or soup.select_one('meta[name="twitter:title"]')
    if title_meta and title_meta.get("content"):
        data["title"] = title_meta.get("content").strip()

    desc_meta = soup.select_one('meta[name="description"]')
    if desc_meta and desc_meta.get("content"):
        data["description"] = desc_meta.get("content").strip()

    return data


def html_to_text(html: Optional[str]) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def to_date_string(value: Optional[str]) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        candidate = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.date().isoformat()
        except ValueError:
            return value
    return stringify(value)


def format_code_list(value: Any, *, code_keys: Iterable[str] = ("code", "naics", "naicsCode")) -> str:
    if not value:
        return ""

    codes: List[str] = []

    for item in _iterate_nested(value):
        if isinstance(item, str):
            entry = item.strip()
        elif isinstance(item, dict):
            entry = ""
            for key in code_keys:
                if key in item and item[key]:
                    entry = str(item[key]).strip()
                    break
            if entry:
                desc = item.get("description") or item.get("title")
                if desc:
                    entry = f"{entry} - {str(desc).strip()}"
        else:
            entry = ""

        if entry:
            codes.append(entry)

    deduped = []
    seen = set()
    for entry in codes:
        if entry not in seen:
            seen.add(entry)
            deduped.append(entry)

    return "; ".join(deduped)


def format_place_of_performance(value: Any) -> str:
    if not value:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, dict):
        parts = []
        for key in ("city", "state", "stateCode", "zip", "country", "countryCode"):
            if value.get(key):
                parts.append(str(value[key]).strip())
        if parts:
            return ", ".join(parts)

    if isinstance(value, list):
        parts = [format_place_of_performance(item) for item in value]
        parts = [p for p in parts if p]
        return "; ".join(parts)

    return stringify(value)


def format_contacts(value: Any) -> str:
    if not value:
        return ""

    contacts: List[str] = []

    for item in _iterate_nested(value):
        if isinstance(item, dict):
            pieces = []
            name = item.get("fullName") or item.get("name") or item.get("contactName")
            email = item.get("email") or item.get("emailAddress")
            phone = item.get("phone") or item.get("phoneNumber")

            if name:
                pieces.append(str(name).strip())
            if email:
                pieces.append(str(email).strip())
            if phone:
                pieces.append(str(phone).strip())

            if pieces:
                contacts.append(" | ".join(pieces))
        elif isinstance(item, str):
            contacts.append(item.strip())

    deduped = []
    seen = set()
    for entry in contacts:
        if entry and entry not in seen:
            seen.add(entry)
            deduped.append(entry)

    return "; ".join(deduped)


def format_naics_codes(entries: Optional[List[Dict[str, Any]]]) -> str:
    if not entries:
        return ""

    formatted: List[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        codes = entry.get("code")
        if isinstance(codes, list):
            code_value = ", ".join(str(code) for code in codes if code)
        else:
            code_value = stringify(codes)

        description = stringify(
            entry.get("title") or entry.get("description") or entry.get("type")
        )

        if code_value and description and description.lower() not in {"primary"}:
            formatted.append(f"{code_value} - {description}")
        elif code_value:
            formatted.append(code_value)

    return "; ".join(formatted)


def extract_organization_levels(value: Any) -> tuple[str, str, str]:
    if not value:
        return "", "", ""

    names: List[str] = []
    for item in _iterate_nested(value, depth=1):
        if isinstance(item, dict):
            name = item.get("name") or item.get("title")
            if name:
                names.append(str(name).strip())
        elif isinstance(item, str):
            names.append(item.strip())

    department = names[0] if len(names) > 0 else ""
    sub_tier = names[1] if len(names) > 1 else ""
    office = names[2] if len(names) > 2 else ""
    return department, sub_tier, office


def extract_department_fields(
    organization: Optional[Dict[str, Any]]
) -> tuple[str, str, str]:
    if not organization:
        return "", "", ""

    embedded = organization.get("_embedded")
    if isinstance(embedded, list) and embedded:
        org = embedded[0].get("org", {})
    elif isinstance(embedded, dict):
        org = embedded.get("org", {})
    else:
        org = {}

    path = stringify(org.get("fullParentPathName"))
    if path:
        parts = [part.strip() for part in path.split(".") if part.strip()]
        department = parts[0] if parts else ""
        sub_tier = parts[1] if len(parts) > 1 else ""
        if len(parts) > 2:
            office = parts[-1]
        elif len(parts) == 2:
            office = parts[1]
        else:
            office = stringify(org.get("name"))
        return department, sub_tier, office

    name = stringify(org.get("name"))
    short = stringify(org.get("l1ShortName"))
    return short or name, name, name


def stringify(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)


INVALID_FILENAME_CHARS = re.compile(r"[\\/:*?\"<>|]+")


def sanitize_filename(name: str) -> str:
    if not name:
        return ""
    cleaned = INVALID_FILENAME_CHARS.sub("_", name)
    cleaned = cleaned.strip().strip(".")
    return cleaned


ATTACHMENT_URL_KEYWORDS = ("download", "attachment", "document", "file", "docs")
ATTACHMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv", ".zip")


def collect_attachments_from_html(html: str, page_url: str) -> List[AttachmentInfo]:
    soup = BeautifulSoup(html, "html.parser")
    attachments: List[AttachmentInfo] = []
    seen: set[tuple[str, str]] = set()

    for link in soup.find_all("a", href=True):
        href = link["href"].strip()
        absolute = urljoin(page_url, href)

        if not _looks_like_attachment_url(absolute):
            continue

        parsed = urlparse(absolute)
        file_name_from_url = Path(unquote(parsed.path)).name

        label = link.get_text(strip=True) or file_name_from_url
        label = label.strip()
        if not label:
            continue

        attachment = AttachmentInfo(name=label, url=absolute)
        if file_name_from_url:
            ext = Path(file_name_from_url).suffix.lstrip(".")
            if ext:
                attachment.file_type = ext

        key = (attachment.name, attachment.url)
        if key in seen:
            continue

        seen.add(key)
        attachments.append(attachment)

    return attachments


def _looks_like_attachment_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False

    path = parsed.path.lower()
    if any(path.endswith(ext) for ext in ATTACHMENT_EXTENSIONS):
        return True

    if any(keyword in path for keyword in ATTACHMENT_URL_KEYWORDS):
        return True

    query = parsed.query.lower()
    return any(keyword in query for keyword in ATTACHMENT_URL_KEYWORDS)


def _extension_from_mime_or_type(value: str) -> str:
    candidate = value.strip().lower()
    if not candidate:
        return ""

    if "/" in candidate:
        guessed = mimetypes.guess_extension(candidate)
        if guessed:
            return guessed

    if not candidate.startswith("."):
        candidate = f".{candidate}"

    return candidate


def _relative_path(path: Optional[Path], base: Path) -> Optional[str]:
    if path is None:
        return None

    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path.resolve())


def _find_first(obj: Any, keys: Iterable[str]) -> Any:
    lowered = [key.lower() for key in keys]
    for result in _iterate_nested(obj):
        if isinstance(result, dict):
            for key, value in result.items():
                if key.lower() in lowered:
                    return value
    return None


def _iterate_nested(obj: Any, depth: Optional[int] = None) -> Iterator[Any]:
    if isinstance(obj, dict):
        if depth is None or depth >= 0:
            yield obj
        next_depth = None if depth is None else depth - 1
        if next_depth is None or next_depth >= 0:
            for value in obj.values():
                yield from _iterate_nested(value, next_depth)
    elif isinstance(obj, list):
        if depth is None or depth >= 0:
            yield obj
        next_depth = None if depth is None else depth - 1
        if next_depth is None or next_depth >= 0:
            for item in obj:
                yield from _iterate_nested(item, next_depth)
    else:
        yield obj

