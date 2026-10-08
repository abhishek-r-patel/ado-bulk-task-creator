# Azure DevOps Bulk Task Creator: create child tasks from CSV using a signed-in Edge session.
import argparse
import csv
import html
import logging
import math
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from time import perf_counter
from urllib.parse import parse_qs, quote, unquote, urlsplit

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.edge.options import Options


# ============================================================
# Paths
# ============================================================

# Anchor runtime files to this script, not the shell's current working directory.
SCRIPT_DIR = Path(__file__).resolve().parent

CSV_FILE = SCRIPT_DIR / "tasks.csv"
TEMP_DIR = SCRIPT_DIR / "temp"
LOG_DIR = TEMP_DIR / "logs"
STATE_DIR = TEMP_DIR / "state"
STATE_FILE = STATE_DIR / "created_tasks.csv"

REQUIRED_COLUMNS = [
    "Title",
]


# ============================================================
# Browser requests use the interactive Edge session's cookies.
# ============================================================

# Selenium supplies the final callback argument; calling it completes execute_async_script.
# Same-origin cookies authenticate requests without exposing credentials to Python.
BROWSER_REQUEST_SCRIPT = """
const [url, method, body, contentType, done] = arguments;
if (new URL(url).origin !== location.origin) {
    done({error: 'Refusing a request outside the signed-in page origin.'});
} else {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    fetch(url, {
        method, credentials: 'same-origin', redirect: 'error',
        headers: {Accept: 'application/json', 'Content-Type': contentType},
        body: body === null ? undefined : JSON.stringify(body),
        signal: controller.signal
    }).then(async response => {
        let data;
        try { data = await response.json(); }
        catch { throw new Error('Expected JSON; check Azure DevOps sign-in.'); }
        done({status: response.status, data});
    }).catch(error => done({error: error.message}))
      .finally(() => clearTimeout(timer));
}
"""


# ============================================================
# General helpers
# ============================================================

def parse_arguments():
    """Translate command-line opt-ins into the internal workflow settings."""
    parser = argparse.ArgumentParser(
        description="Azure DevOps Bulk Task Creator: create child tasks from CSV through a signed-in Edge session (no PAT).",
        epilog=(
            "Fill tasks_template.csv or tasks.csv: only the Title header is required, "
            "and Title values must be nonblank. Description is an optional column; "
            "missing or blank values are omitted from task requests. "
            "RemainingWork (nonnegative hours) and Tags (semicolon-separated) are optional "
            "columns; missing or blank values are omitted from task requests. "
            "AssignedTo is an optional column: a nonblank account name overrides the PBI "
            "assignee; a blank or missing value falls back to the PBI. If both are empty, "
            "the task request explicitly sets Assigned To to empty. "
            "New tags require the Azure DevOps Create tag definition permission. "
            "CSV tags are skipped by default; use --include-tags to include them. If permission "
            "is unavailable, omit --include-tags; the CSV itself is not changed. "
            "Save as UTF-8 CSV. Quote values containing commas. "
            "Area and iteration are inherited from the PBI. "
            "Run --dry-run first, then rerun "
            "without it and type CREATE to save. "
            "The console shows the loaded PBI ID/title and [SUCCESS] or [FAILED] task names; "
            "dry runs report planned tasks without claiming creation success. "
            "Sign in/MFA in the dedicated Edge window; "
            "if the initial sign-in redirect fails, paste the PBI link in that same window "
            "and press Enter only after it loads. By default Edge starts with a blank "
            "window for manual navigation; use --auto-navigation to open the PBI automatically. "
            "existing personal Edge windows are not used. The automation window closes at the "
            "end; reopen or refresh the PBI in your normal browser to see the tasks. "
            "By default only temp/SeleniumEdgeProfile is deleted after Edge closes; this "
            "removes saved sign-in and caches, so the next run requires sign-in. "
            "Use --keep-edge-profile to retain the profile between runs. "
            "Logs and the task ledger are retained. Cleanup is skipped if browser shutdown "
            "fails, and locked files are reported without forced deletion. Validation-only "
            "runs do not delete an existing profile. "
            "Only Azure DevOps Services is supported; "
            "custom required fields may need code changes. Duplicates are compared by normalized "
            "title within the PBI, not across projects. Do not run concurrent bulk imports. "
            "On request failure, refresh the PBI before retrying. Logs and the success ledger "
            "are under temp/logs and temp/state. Each run appends launcher diagnostics, "
            "sanitized parameters, file hashes, a replay command, prompts, and Python events "
            "to one run_RUNID.log with timestamps and source labels. "
            "Technical diagnostics and tracebacks are file-only; "
            "the console shows prompts, task names, concise errors, and summaries. "
            "Manual browser clicks and sign-in input are not recorded. Logs contain work-item "
            "information; review before sharing. temp/SeleniumEdgeProfile contains sensitive "
            "session cookies and must not be shared. Selenium Manager may need network access "
            "to download a matching EdgeDriver on first launch."
        ),
    )
    parser.add_argument("--pbi-url", help="Azure DevOps Services PBI edit URL.")
    parser.add_argument("--run-id", help="Run identifier used by the shared launcher/Python log.")
    parser.add_argument("--log-file", type=Path, help="Append Python events to this shared run log.")
    parser.add_argument("--csv", type=Path, default=CSV_FILE, help="Task CSV path.")
    # store_false reverses each enabled default when its opt-in flag is supplied.
    parser.add_argument(
        "--keep-edge-profile", dest="clean_edge_profile", action="store_false", default=True,
        help="Retain the dedicated Edge profile and saved sign-in instead of the default cleanup.",
    )
    parser.add_argument(
        "--include-tags", dest="skip_tags", action="store_false", default=True,
        help="Include CSV tags in task requests; tags are skipped by default.",
    )
    parser.add_argument(
        "--auto-navigation", dest="manual_navigation", action="store_false", default=True,
        help="Open the PBI automatically instead of the default blank window for manual navigation.",
    )
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Validate the URL and CSV without opening Edge or creating tasks.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Validate the CSV and report create/skip decisions "
            "without creating tasks."
        ),
    )

    parser.add_argument(
        "--ignore-state",
        action="store_true",
        help=(
            "Ignore this PBI's local success ledger. Existing child tasks "
            "in Azure DevOps are still detected."
        ),
    )

    return parser.parse_args()


def ensure_directories():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)


class RunLogFormatter(logging.Formatter):
    """Label every Python event and traceback line in the shared chronological log."""

    def format(self, record):
        timestamp = datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="milliseconds")
        prefix = f"{timestamp} | PYTHON | {record.levelname} | "
        return "\n".join(prefix + line for line in super().format(record).splitlines())


class UserConsoleFilter(logging.Filter):
    """Show only events explicitly marked for the user; keep diagnostics file-only."""

    def filter(self, record):
        return bool(getattr(record, "user_visible", False) or hasattr(record, "console_message"))


class UserConsoleFormatter(logging.Formatter):
    """Use concise console text without timestamps or exception tracebacks."""

    def format(self, record):
        return getattr(record, "console_message", record.getMessage())


def configure_logging(run_id=None, log_file=None):
    """Append full events to one run log and show selected messages on the console."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    # Restrict the supplied ID so it cannot become a path outside the log directory.
    if run_id and re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        timestamp = run_id
    log_file = log_file or LOG_DIR / f"run_{timestamp}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    # Append preserves the launcher's earlier events; handlers flush each event immediately.
    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setFormatter(RunLogFormatter("%(message)s"))
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.addFilter(UserConsoleFilter())
    console_handler.setFormatter(UserConsoleFormatter())

    logging.basicConfig(
        level=logging.INFO,
        handlers=[
            file_handler,
            console_handler,
        ],
    )

    return log_file


def normalize_title(value):
    """
    Normalize a task title for duplicate comparison.

    Examples:
        "Install   JDK 17" -> "install jdk 17"
        " INSTALL JDK 17 " -> "install jdk 17"
    """
    if value is None:
        return ""

    title = str(value).strip()
    title = re.sub(r"\s+", " ", title)

    return title.casefold()


def clean_optional_value(value):
    if pd.isna(value):
        return ""

    return str(value).strip()


def validate_remaining_work(value, row_number):
    """Validate hours while preserving the difference between blank and zero."""
    value = clean_optional_value(value)

    if not value:
        return ""

    try:
        numeric_value = float(value)
    except ValueError as error:
        raise ValueError(
            f"Row {row_number}: RemainingWork must be numeric."
        ) from error

    if not math.isfinite(numeric_value) or numeric_value < 0:
        raise ValueError(
            f"Row {row_number}: RemainingWork must be finite and nonnegative."
        )

    if numeric_value.is_integer():
        return str(int(numeric_value))

    return str(numeric_value)


# ============================================================
# CSV processing
# ============================================================

def load_and_validate_tasks(csv_file=CSV_FILE):
    """Load optional CSV fields, validate rows, and retain one row per normalized title."""
    if not csv_file.exists():
        raise FileNotFoundError(
            f"CSV file was not found: {csv_file}"
        )

    # Preserve text values such as "NA" and accept UTF-8 files saved with a BOM.
    tasks = pd.read_csv(
        csv_file,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )

    missing_columns = [
        column
        for column in REQUIRED_COLUMNS
        if column not in tasks.columns
    ]

    if missing_columns:
        raise ValueError(
            "tasks.csv is missing required columns: "
            + ", ".join(missing_columns)
        )

    validated_tasks = []
    csv_titles = set()

    for index, row in tasks.iterrows():
        row_number = index + 2

        # Only Title is required; omitted optional columns behave like blank cells.
        title = clean_optional_value(row["Title"])
        description = clean_optional_value(row.get("Description", ""))
        tags = clean_optional_value(row.get("Tags", ""))
        assigned_to = clean_optional_value(row.get("AssignedTo", ""))
        remaining_work = validate_remaining_work(
            row.get("RemainingWork", ""),
            row_number,
        )

        if not title:
            raise ValueError(
                f"Row {row_number}: Title cannot be empty."
            )

        normalized_title = normalize_title(title)

        if normalized_title in csv_titles:
            logging.warning(
                "[CSV DUPLICATE] Row %s skipped: %s",
                row_number,
                title,
            )
            continue

        csv_titles.add(normalized_title)

        validated_tasks.append(
            {
                "title": title,
                "normalized_title": normalized_title,
                "description": description,
                "remaining_work": remaining_work,
                "tags": tags,
                "assigned_to": assigned_to,
                "row_number": row_number,
            }
        )

    if not validated_tasks:
        raise ValueError(
            "No valid task rows were found in tasks.csv."
        )

    return validated_tasks


def parse_pbi_url(value):
    """Validate a Services edit link and return its canonical URL, project, and ID."""
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("Use an HTTPS Azure DevOps PBI edit link.")
    parts = [unquote(part) for part in parsed.path.strip("/").split("/")]
    if parsed.hostname == "dev.azure.com":
        if len(parts) != 5:
            raise ValueError("Expected https://dev.azure.com/ORG/PROJECT/_workitems/edit/ID.")
        organization, project, *route = parts
        base = f"https://dev.azure.com/{quote(organization, safe='')}"
    elif parsed.hostname and parsed.hostname.endswith(".visualstudio.com"):
        if len(parts) != 4:
            raise ValueError("Expected https://ORG.visualstudio.com/PROJECT/_workitems/edit/ID.")
        project, *route = parts
        base = f"https://{parsed.hostname}"
    else:
        raise ValueError("Only Azure DevOps Services PBI edit links are supported.")
    if route[:2] != ["_workitems", "edit"] or len(route) != 3:
        raise ValueError("The link must point to a work item: /_workitems/edit/ID.")
    if not route[2].isdigit() or int(route[2]) <= 0:
        raise ValueError("The parent work-item ID must be a positive integer.")
    return {
        "base": base,
        "project": project,
        "id": int(route[2]),
        "url": f"{base}/{quote(project, safe='')}/_workitems/edit/{int(route[2])}",
    }


def get_parent_assignee(parent):
    """Resolve identity objects to a unique account or ID, not an ambiguous display name."""
    assignee = parent["fields"].get("System.AssignedTo")
    if isinstance(assignee, dict):
        assignee = assignee.get("uniqueName") or assignee.get("id")
        if not assignee:
            raise ValueError("The PBI assignee has no unique account name or identity ID.")
    if assignee is None:
        return ""
    if not isinstance(assignee, str):
        raise ValueError("The PBI Assigned To value has an unsupported format.")
    return assignee.strip()


def build_task_patch(task, parent, target):
    """Build Azure DevOps JSON Patch operations for fields and the parent relationship."""
    fields = {
        "System.Title": task["title"],
        "System.AreaPath": parent["fields"]["System.AreaPath"],
        "System.IterationPath": parent["fields"]["System.IterationPath"],
    }
    # A CSV override wins; explicitly send empty assignment when both sources are blank.
    csv_assignee = clean_optional_value(task.get("assigned_to", ""))
    assignee = csv_assignee or get_parent_assignee(parent)
    fields["System.AssignedTo"] = assignee
    logging.info(
        "[ASSIGN] %s | assigned_to=%s | source=%s",
        task["title"], assignee or "unassigned",
        "CSV" if csv_assignee else "PBI" if assignee else "empty CSV and PBI",
    )
    if task["description"]:
        # Description is an HTML field; CSV text must not become executable markup.
        fields["System.Description"] = html.escape(task["description"]).replace("\n", "<br>")
    if task["remaining_work"]:
        fields["Microsoft.VSTS.Scheduling.RemainingWork"] = float(task["remaining_work"])
    if task["tags"]:
        fields["System.Tags"] = task["tags"]
    patch = [
        {"op": "add", "path": f"/fields/{name}", "value": value}
        for name, value in fields.items()
    ]
    # Hierarchy-Reverse means this new task points back to its parent PBI.
    patch.append({
        "op": "add", "path": "/relations/-",
        "value": {
            "rel": "System.LinkTypes.Hierarchy-Reverse",
            "url": parent.get("url", f"{target['base']}/_apis/wit/workItems/{target['id']}"),
        },
    })
    return patch


# ============================================================
# Local state ledger
# ============================================================

def load_created_titles(page_url):
    """Read successful titles for this PBI only, keeping unrelated PBIs independent."""
    if not STATE_FILE.exists():
        return set()

    created_titles = set()

    with STATE_FILE.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as state_handle:
        reader = csv.DictReader(state_handle)

        for row in reader:
            try:
                recorded_url = parse_pbi_url(row.get("PageUrl", ""))["url"]
            except ValueError:
                continue
            if recorded_url != page_url:
                continue
            title = row.get("Title", "")
            normalized_title = normalize_title(title)

            if normalized_title:
                created_titles.add(normalized_title)

    return created_titles


def record_created_task(task, page_url):
    """Append confirmed success so a later run can avoid creating the same title again."""
    state_exists = STATE_FILE.exists()

    with STATE_FILE.open(
        "a",
        newline="",
        encoding="utf-8-sig",
    ) as state_handle:
        fieldnames = [
            "CreatedAt",
            "Title",
            "Description",
            "RemainingWork",
            "Tags",
            "PageUrl",
        ]

        writer = csv.DictWriter(
            state_handle,
            fieldnames=fieldnames,
        )

        if not state_exists or STATE_FILE.stat().st_size == 0:
            writer.writeheader()

        writer.writerow(
            {
                "CreatedAt": datetime.now().isoformat(
                    timespec="seconds"
                ),
                "Title": task["title"],
                "Description": task["description"],
                "RemainingWork": task["remaining_work"],
                "Tags": task["tags"],
                "PageUrl": page_url,
            }
        )


# ============================================================
# Selenium and Azure DevOps browser API helpers
# ============================================================

def close_edge(driver, clean_edge_profile=False):
    """Close the owned browser before optionally deleting its profile, never logs/state."""
    try:
        logging.info("[STEP] Close the automation Edge session.")
        driver.quit()
        logging.info("[STEP] Edge session closed.")
    except WebDriverException:
        logging.warning(
            "Could not close the Selenium Edge session; profile cleanup skipped.",
            extra={"console_message": "[WARNING] Could not close Edge; browser profile cleanup was skipped."},
        )
        return

    if not clean_edge_profile:
        logging.info("[CLEANUP] Edge profile retained for future sign-in.")
        return
    edge_profile = TEMP_DIR / "SeleniumEdgeProfile"
    expected_path = TEMP_DIR.resolve() / "SeleniumEdgeProfile"
    # Refuse redirected paths so recursive deletion cannot reach an unrelated folder.
    if edge_profile.is_symlink() or edge_profile.resolve() != expected_path:
        logging.warning(
            "[CLEANUP] Refusing to delete a redirected Edge profile path: %s", edge_profile,
            extra={"console_message": "[WARNING] Browser profile cleanup was skipped because its path was redirected."},
        )
        return
    if not edge_profile.exists():
        logging.info("[CLEANUP] Edge profile is already absent.")
        return
    try:
        shutil.rmtree(edge_profile)
        logging.info("[CLEANUP] Deleted Edge profile: %s | logs and state retained", edge_profile)
    except OSError as error:
        logging.warning(
            "[CLEANUP] Could not fully delete Edge profile (files may still be locked): %s", error,
            extra={"console_message": "[WARNING] Browser profile cleanup could not finish. See the logs for details."},
        )


def connect_to_edge(target, manual_navigation=False, clean_edge_profile=False):
    """
    Launch a dedicated Microsoft Edge session through Selenium.

    The isolated profile keeps ordinary Edge windows separate. Manual
    navigation avoids automatically initiating the first sign-in redirect.
    CLI settings are passed explicitly by run_tasks.
    """

    edge_profile = TEMP_DIR / "SeleniumEdgeProfile"
    edge_profile.mkdir(parents=True, exist_ok=True)
    logging.info("[STEP] Launch Edge | profile=%s | manual_navigation=%s", edge_profile, manual_navigation)

    options = Options()

    options.add_argument(
        f"--user-data-dir={edge_profile}"
    )

    options.add_argument("--start-maximized")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")

    try:
        driver = webdriver.Edge(options=options)
    except WebDriverException as error:
        raise RuntimeError(
            "Selenium could not launch Microsoft Edge. "
            "Check Edge/EdgeDriver versions and network access. "
            "Close any earlier Selenium Edge window using temp/SeleniumEdgeProfile."
        ) from error

    try:
        return wait_for_pbi(driver, target, manual_navigation)
    except BaseException:
        # Until setup returns, run_tasks does not own the driver; clean up here on failure.
        close_edge(driver, clean_edge_profile)
        raise


def wait_for_pbi(driver, target, manual_navigation):
    """Let the user finish sign-in and confirm the exact requested PBI tab is open."""
    driver.set_script_timeout(40)
    logging.info("[STEP] Edge launched | browser version=%s", driver.capabilities.get("browserVersion", "unknown"))
    logging.info("[STEP] Navigate to %s", "about:blank" if manual_navigation else target["url"])
    driver.get("about:blank" if manual_navigation else target["url"])

    logging.info("In Edge, open the PBI and complete sign-in/MFA:", extra={"user_visible": True})
    logging.info("%s", target["url"], extra={"user_visible": True})
    logging.info("If sign-in fails, paste this link again in the same Edge window.", extra={"user_visible": True})

    readiness_attempt = 0
    while True:
        readiness_attempt += 1
        logging.info("[USER] Press Enter after the PBI loads, or type CANCEL to stop | attempt=%s", readiness_attempt)
        answer = input("Press Enter after the PBI loads, or type CANCEL to stop: ")
        if answer.strip().casefold() == "cancel":
            logging.info("[USER] Browser setup cancelled.")
            raise RuntimeError("Browser setup cancelled. No tasks were created.")
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            try:
                selected = parse_pbi_url(driver.current_url)
            except ValueError:
                continue
            if selected["url"] == target["url"]:
                logging.info("[STEP] Requested PBI tab confirmed: %s", selected["url"])
                return driver
        logging.warning("[STEP] PBI tab not found after confirmation; waiting for manual recovery.")
        logging.info("The requested PBI is not open yet. Keep this Edge window open and paste:", extra={"user_visible": True})
        logging.info("%s", target["url"], extra={"user_visible": True})


def browser_request(driver, url, method="GET", body=None, content_type="application/json"):
    """Run an authenticated browser request and turn transport/API failures into errors."""
    parsed_url = urlsplit(url)
    validate_only = parse_qs(parsed_url.query).get("validateOnly", ["false"])[0] == "true"
    started = perf_counter()
    logging.info("[API] %s %s | validate_only=%s", method, parsed_url.path, validate_only)
    try:
        result = driver.execute_async_script(
            BROWSER_REQUEST_SCRIPT, url, method, body, content_type,
        )
    except Exception:
        logging.error("[API] Browser execution failed | elapsed=%.3fs", perf_counter() - started)
        raise
    logging.info(
        "[API] Response status=%s | elapsed=%.3fs",
        result.get("status", "unavailable") if isinstance(result, dict) else "unavailable",
        perf_counter() - started,
    )
    if not isinstance(result, dict) or result.get("error"):
        raise RuntimeError(
            f"Browser request failed: {result}. If creating a task, check its child list before retrying."
        )
    if not 200 <= result.get("status", 0) < 300:
        data = result.get("data", {})
        message = data.get("message", "Request rejected") if isinstance(data, dict) else "Request rejected"
        if "TF401289" in message:
            message += (
                " Clear the CSV Tags values, omit --include-tags (PowerShell: -IncludeTags), "
                "or ask your project administrator for Create tag definition permission."
            )
        raise RuntimeError(f"Azure DevOps HTTP {result['status']}: {message}")
    return result["data"]


def api_root(target):
    return f"{target['base']}/{quote(target['project'], safe='')}/_apis/wit"


def get_parent(driver, target):
    parent = browser_request(
        driver, f"{api_root(target)}/workitems/{target['id']}?$expand=relations&api-version=7.1",
    )
    if parent.get("id") != target["id"]:
        raise RuntimeError("Azure DevOps returned an unexpected parent work item.")
    fields = parent["fields"]
    if fields["System.WorkItemType"] == "Task":
        raise ValueError("The parent is a Task. Supply the PBI or user-story link instead.")
    if fields["System.TeamProject"].casefold() != target["project"].casefold():
        raise ValueError("The PBI does not belong to the project in the supplied URL.")
    logging.info("Adding Task under PBI: %s - %s", parent["id"], fields["System.Title"], extra={"user_visible": True})
    logging.info("Inherited area: %s | iteration: %s", fields["System.AreaPath"], fields["System.IterationPath"])
    logging.info("PBI Assigned To fallback: %s", get_parent_assignee(parent) or "unassigned")
    return parent


def collect_existing_titles(driver, target, parent):
    """Read actual linked child tasks instead of relying on titles visible in the UI."""
    existing_titles = set()
    child_ids = []
    for relation in parent.get("relations", []):
        if relation["rel"] != "System.LinkTypes.Hierarchy-Forward":
            continue
        child_ids.append(str(int(relation["url"].rstrip("/").rsplit("/", 1)[-1])))
    # Batches avoid oversized ID lists; missing children would make duplicate checks unsafe.
    for offset in range(0, len(child_ids), 100):
        ids = ",".join(child_ids[offset:offset + 100])
        children = browser_request(
            driver, f"{api_root(target)}/workitems?ids={ids}"
            "&fields=System.Title,System.WorkItemType&api-version=7.1",
        )
        if len(children["value"]) != len(child_ids[offset:offset + 100]):
            raise RuntimeError("Could not read every child work item; refusing incomplete duplicate detection.")
        for child in children["value"]:
            if child["fields"]["System.WorkItemType"] == "Task":
                existing_titles.add(normalize_title(child["fields"]["System.Title"]))
    return existing_titles


def submit_task(driver, task, target, parent, validate_only=False):
    """Use the same payload for rule validation and creation; validateOnly never saves it."""
    suffix = "&validateOnly=true" if validate_only else ""
    return browser_request(
        driver, f"{api_root(target)}/workitems/$Task?api-version=7.1&$expand=relations{suffix}",
        method="POST", body=build_task_patch(task, parent, target),
        content_type="application/json-patch+json",
    )


# ============================================================
# Processing
# ============================================================

def process_tasks(
    driver,
    tasks,
    target,
    parent,
    dry_run=False,
    ignore_state=False,
):
    """Skip known titles, validate every planned request, then create after confirmation."""
    totals = {
        "created": 0,
        "skipped_page": 0,
        "skipped_state": 0,
        "failed": 0,
        "dry_run_create": 0,
    }

    logging.info("[STEP] Check existing child tasks and local ledger for this PBI.")
    existing_page_titles = collect_existing_titles(driver, target, parent)
    logging.info("[STEP] Found %s existing child task titles.", len(existing_page_titles))

    if ignore_state:
        created_state_titles = set()
        logging.warning(
            "Local success ledger is being ignored."
        )
    else:
        created_state_titles = load_created_titles(target["url"])
        logging.info(
            "Loaded %s task titles from the local success ledger.",
            len(created_state_titles),
        )

    pending = []
    for task in tasks:
        title = task["title"]
        normalized_title = task["normalized_title"]

        if normalized_title in existing_page_titles:
            logging.info(
                "[SKIP - EXISTING CHILD TASK] %s",
                title,
                extra={"user_visible": True},
            )
            totals["skipped_page"] += 1
            continue

        if normalized_title in created_state_titles:
            logging.info(
                "[SKIP - PREVIOUSLY CREATED] %s",
                title,
                extra={"user_visible": True},
            )
            totals["skipped_state"] += 1
            continue

        pending.append(task)
        logging.info(
            "[PLANNED] %s | hours=%s | tags=%s", title, task["remaining_work"], task["tags"],
            extra={"console_message": f"[PLANNED] {title}"},
        )

    # Preflight the entire batch before saving anything, avoiding predictable partial imports.
    for task in pending:
        try:
            logging.info("[VALIDATE] CSV row %s | %s", task["row_number"], task["title"])
            submit_task(driver, task, target, parent, validate_only=True)
        except Exception:
            logging.error("[FAILED] %s", task["title"], extra={"user_visible": True})
            logging.exception("Task validation failed; no tasks were created.")
            raise
    logging.info("Validated %s planned task requests against Azure DevOps rules.", len(pending))
    if dry_run:
        logging.info("[STEP] Dry run complete; task creation and confirmation were skipped.")
        totals["dry_run_create"] = len(pending)
        return totals
    if not pending:
        return totals
    logging.info("[USER] Type CREATE to create %s tasks under PBI %s", len(pending), target["id"])
    confirmation = input(f"Type CREATE to create {len(pending)} tasks under PBI {target['id']}: ")
    if confirmation.strip() != "CREATE":
        logging.info("[USER] Creation confirmation not accepted.")
        logging.info("Cancelled. No tasks were created.", extra={"user_visible": True})
        return totals

    logging.info("[USER] Creation confirmation accepted.")
    for task in pending:
        try:
            logging.info("[CREATE] CSV row %s | %s", task["row_number"], task["title"])
            created = submit_task(driver, task, target, parent)
            parent_link = parent.get("url", f"{target['base']}/_apis/wit/workItems/{target['id']}")
            linked = any(
                relation["rel"] == "System.LinkTypes.Hierarchy-Reverse"
                and relation["url"].casefold() == parent_link.casefold()
                for relation in created.get("relations", [])
            )
            # A successful HTTP response alone is not enough to record a confirmed task.
            if not created.get("id") or not linked:
                raise RuntimeError("Task creation response did not confirm the ID and parent link.")
            record_created_task(task, target["url"])
            logging.info("[STEP] Task recorded in success ledger: %s", STATE_FILE)
            totals["created"] += 1
            logging.info("[SUCCESS] %s", task["title"], extra={"user_visible": True})
            logging.info("Created work-item ID: %s", created["id"])
        except Exception:
            totals["failed"] += 1
            logging.error("[FAILED] %s", task["title"], extra={"user_visible": True})
            logging.exception("Refresh the PBI before rerunning; no automatic retry.")
            logging.error("Task creation stopped. Check the PBI before retrying; see the logs for details.", extra={"user_visible": True})
            # The server may have saved the task despite an uncertain response; do not retry.
            break

    return totals


def main():
    """CLI entry point: run the workflow and record its exit status in the shared log."""
    args = parse_arguments()
    exit_code = run_tasks(args)
    logging.info("[RUN END] Python exit code: %s", exit_code)
    return exit_code


def run_tasks(args):
    """Coordinate CSV validation, browser ownership, processing, and guaranteed teardown."""
    ensure_directories()
    log_file = configure_logging(args.run_id, args.log_file)

    logging.info("Log file: %s", log_file)
    logging.info("CSV file: %s", args.csv)
    logging.info("State file: %s", STATE_FILE)
    logging.info("[RUN] ID: %s", args.run_id or "standalone")
    logging.info("[RUN] Interpreter: %s | Python: %s", sys.executable, sys.version.split()[0])
    logging.info("[RUN] Working directory: %s", Path.cwd())
    logging.info(
        "[RUN] Parameters | csv=%s | dry_run=%s | validate_only=%s | manual_navigation=%s | skip_tags=%s | ignore_state=%s | clean_edge_profile=%s",
        args.csv.resolve(), args.dry_run, args.validate_only, args.manual_navigation, args.skip_tags, args.ignore_state, args.clean_edge_profile,
    )

    driver = None
    try:
        logging.info("[STEP] Load and validate CSV.")
        tasks = load_and_validate_tasks(args.csv)
        if args.skip_tags:
            for task in tasks:
                task["tags"] = ""
            logging.warning(
                "CSV tags are omitted from this run; the CSV file is unchanged.",
                extra={"console_message": "Tags are omitted for this run."},
            )
        logging.info(
            "Loaded %s unique task rows.",
            len(tasks),
        )

        pbi_url = args.pbi_url
        if not pbi_url and not args.validate_only:
            logging.info("[USER] Waiting for a PBI link; raw input is not logged.")
            pbi_url = input("Paste the Azure DevOps PBI edit link: ")
        target = parse_pbi_url(pbi_url) if pbi_url else None
        if target:
            logging.info("[RUN] PBI URL: %s", target["url"])
        if args.validate_only:
            # Local validation takes precedence over browser modes and profile cleanup.
            logging.info("Validation passed. No browser was opened and no tasks were created.", extra={"user_visible": True})
            return 0
        if target is None:
            raise ValueError("A PBI link is required.")

        driver = connect_to_edge(
            target, manual_navigation=args.manual_navigation,
            clean_edge_profile=args.clean_edge_profile,
        )
        parent = get_parent(driver, target)

        totals = process_tasks(
            driver=driver,
            tasks=tasks,
            target=target,
            parent=parent,
            dry_run=args.dry_run,
            ignore_state=args.ignore_state,
        )

        logging.info("=" * 60)
        logging.info("Created: %s", totals["created"])
        logging.info(
            "Skipped, existing child task in PBI: %s",
            totals["skipped_page"],
        )
        logging.info(
            "Skipped, recorded by earlier run: %s",
            totals["skipped_state"],
        )
        logging.info(
            "Dry-run tasks that would be created: %s",
            totals["dry_run_create"],
        )
        logging.info("Failed or unconfirmed: %s", totals["failed"])
        logging.info("=" * 60)

        skipped = totals["skipped_page"] + totals["skipped_state"]
        if args.dry_run:
            logging.info(
                "Dry run: %s tasks validated, %s skipped. No tasks created.",
                totals["dry_run_create"], skipped, extra={"user_visible": True},
            )
        else:
            logging.info(
                "Summary: %s created, %s skipped, %s failed.",
                totals["created"], skipped, totals["failed"], extra={"user_visible": True},
            )
        return 1 if totals["failed"] else 0

    except Exception as error:
        logging.exception("The task-creation run failed.")
        logging.error("[ERROR] %s", error, extra={"user_visible": True})
        return 1
    finally:
        if driver is not None:
            close_edge(driver, args.clean_edge_profile)


if __name__ == "__main__":
    sys.exit(main())