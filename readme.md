<a href="https://buymeacoffee.com/abhishek.patel">
    <img align="right" src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" width="144" height="40">
</a>

# Azure DevOps Bulk Task Creator

GitHub repository name: `ado-bulk-task-creator`.

Create child tasks under an Azure DevOps PBI from a CSV using a dedicated Microsoft Edge session. Sign in normally, including MFA; no personal access token (PAT) is required. Python sends requests through the authenticated browser session rather than filling the task form with UI selectors.

## First-time setup

Follow this sequence before using the project-specific examples later in this document. You do not need VS Code, Git, an administrator terminal, a PAT, or a manually installed EdgeDriver to run the scripts.

1. Obtain the project by cloning its repository or downloading and extracting its ZIP. Review the scripts before running them. Keep [run.ps1](run.ps1), [create_tasks.py](create_tasks.py), [requirements.txt](requirements.txt), and [tasks_template.csv](tasks_template.csv) together in the extracted project folder. Do not copy another user's browser profile or local state.

2. Install Microsoft Edge and Python 3.11 or newer if they are missing. Python downloads are available from [python.org](https://www.python.org/downloads/windows/). Include pip and enable the installer option to add Python to PATH. Open a new PowerShell window after installation so it sees the updated PATH.

3. Navigate to the actual project folder and check Python and pip. Replace the example folder path:

    ```powershell
    Set-Location "C:\path\to\ado-bulk-task-creator"
    python --version
    python -m pip --version
    ```

    If only the Python launcher is available, check `py -3 --version` and `py -3 -m pip --version` instead. The project launcher supports `python` or `py`. If `python` opens Microsoft Store or cannot start, fix its PATH/app execution alias before continuing. Python packages and a matching EdgeDriver are handled automatically when needed; first setup may require download access through your organization's network.

4. Create your own CSV from the template, then replace its example rows with your actual tasks. This command leaves an existing populated CSV untouched:

    ```powershell
    if (-not (Test-Path -LiteralPath .\tasks.csv)) {
         Copy-Item -LiteralPath .\tasks_template.csv -Destination .\tasks.csv
    }
    ```

    Edit the resulting CSV in a text editor or spreadsheet application and save as UTF-8 CSV, not an Excel workbook. Only `Title` is required. `RemainingWork` is hours, not minutes. Leave `AssignedTo` blank to inherit the PBI's assignee. See **Prepare the CSV** below for details. Existing PBI-specific CSVs are example training data; do not use their IDs or task lists for an unrelated project.

5. Open your own PBI in your normal browser, confirm you have access, and copy its work-item edit link. Replace the example URL below with that link and validate the CSV locally:

    ```powershell
    $pbiUrl = "https://dev.azure.com/YOUR-ORG/YOUR-PROJECT/_workitems/edit/12345"
    .\run.ps1 -PbiUrl $pbiUrl -Csv "tasks.csv" -ValidateOnly
    ```

    Expected result: `Validation passed. No browser was opened and no tasks were created.` This checks the file and URL format only, not your Azure DevOps permissions. If PowerShell blocks the script, use the trusted-script guidance in **Troubleshooting** below rather than repeatedly rerunning it. No runtime folders need to be created manually.

6. Validate against Azure DevOps without saving tasks:

    ```powershell
    .\run.ps1 -PbiUrl $pbiUrl -Csv "tasks.csv" -DryRun
    ```

    Wait for the dedicated blank Edge window. Paste the same PBI link there, sign in, and complete MFA. Your normal browser's sign-in is not automatically shared with this window. Press Enter in the PowerShell terminal only after the requested PBI loads successfully. Check the printed PBI ID/title and planned task names. Expected result: a dry-run summary with no tasks created. If it reports skips, those task titles already exist or are in the local ledger. Resolve any validation errors before continuing.

7. Create tasks by removing `-DryRun`:

    ```powershell
    .\run.ps1 -PbiUrl $pbiUrl -Csv "tasks.csv"
    ```

    Repeat browser sign-in as needed, verify the PBI and planned tasks, then type `CREATE` when prompted. Any other answer cancels creation. Tasks use the CSV assignee or PBI fallback and inherit the PBI's area/iteration. Do not run imports concurrently.

8. Reopen or refresh the PBI in your normal browser and verify its child tasks. The automation window closes and its sign-in profile is deleted by default. Logs and the success ledger remain; the final `Logs:` line shows the single run log to inspect when something fails.

Manual navigation, skipped CSV tags, and profile cleanup are the defaults. Add `-IncludeTags` only when you want the CSV tags and have permission to use/create them. Add `-KeepEdgeProfile` to retain this automation profile's sign-in between runs. Add `-AutoNavigation` to open the PBI automatically. Use the same desired switches for both the dry run and creation run.

## Files and folders

```text
ado-bulk-task-creator/
|-- .gitignore                   Excludes local runtime data and credentials
|-- readme.md                    Usage and troubleshooting
|-- run.ps1                      PowerShell launcher
|-- create_tasks.py              CSV validation and task creation
|-- requirements.txt             Python dependencies
|-- tasks.csv                    Optional user-created default task list
|-- tasks_1338076.csv            Reltio training tasks for PBI 1338076
|-- tasks_1340138.csv            Admin, TDM, and DS tasks for PBI 1340138
|-- tasks_1341029.csv            Reltio basics tasks for PBI 1341029
|-- tasks_template.csv           Editable example task template
`-- temp/
    |-- SeleniumEdgeProfile/     Current automation browser profile
    |-- EdgeAutomation/          Legacy profile, no longer used
    |-- logs/                    One shared log per run
    `-- state/                   Successful-task ledger
```

| File or folder | Purpose |
| --- | --- |
| [.gitignore](.gitignore) | Excludes browser profiles, logs/state under `temp/`, Python caches, virtual environments, local `.env` files, and OS metadata. Source scripts, task CSVs, and example environment templates remain trackable. Ignore rules do not untrack files already committed. |
| [run.ps1](run.ps1) | Resolves paths, checks dependencies locally, installs missing/incompatible packages, starts the shared run log, and launches Python with your selected options. |
| [create_tasks.py](create_tasks.py) | Validates the CSV, opens Edge, reads the parent PBI, checks duplicate titles, validates requests against Azure DevOps, and creates linked child tasks after confirmation. |
| [requirements.txt](requirements.txt) | Requires Selenium `>=4.11,<5` and pandas. Selenium Manager can download a matching EdgeDriver when needed. |
| `tasks.csv` (user-created) | Default input when `-Csv` is omitted; not included in the project. Create it from the template as shown above, or explicitly select another CSV with `-Csv`. |
| [tasks_1338076.csv](tasks_1338076.csv) | 32 Reltio training tasks for PBI 1338076, excluding the overlapping architecture task. Estimates are decimal hours rounded to two places; descriptions retain the original durations. Blank assignees use the PBI fallback. Role tags use `ReltioTC`, `ReltioAdmin`, and `ReltioArch` alongside `ReltioTraining`; tags are sent only with `-IncludeTags`. |
| [tasks_1340138.csv](tasks_1340138.csv) | 10 Admin, Technical Delivery Manager, and Data Steward training tasks for PBI 1340138. Estimates are decimal hours rounded to two places; descriptions retain the original durations. Blank assignees use the PBI fallback. Tags use `ReltioTraining` and `ReltioAdmin`, `ReltioTDM`, or `ReltioDS`; tags are sent only with `-IncludeTags`. |
| [tasks_1341029.csv](tasks_1341029.csv) | 6 introductory Reltio training tasks for PBI 1341029. Role/category tags use the `Reltio` prefix, including `ReltioBasics`, `ReltioTC`, `ReltioArch`, `ReltioTDM`, and `ReltioExam`. The five-column CSV has blank `AssignedTo` values for PBI assignment fallback; tags are sent only with `-IncludeTags`. |
| [tasks_template.csv](tasks_template.csv) | Sample rows to replace with your actual tasks. It is not selected automatically; pass `-Csv tasks_template.csv`. |
| `temp/SeleniumEdgeProfile/` | Edge cookies, saved sign-in, settings, and caches. Deleted after browser shutdown by default; use `-KeepEdgeProfile` to retain it. Never share this folder. |
| `temp/EdgeAutomation/` | Leftover from the earlier remote-debugging approach. Current scripts do not use it. Remove it only after closing any browser session using it. |
| `temp/logs/` | One timestamped, source-labelled log per run containing launcher diagnostics and Python events. Old logs can be removed when no longer needed. |
| `temp/state/created_tasks.csv` | Records confirmed task creation, scoped to the parent PBI URL. Keep it for rerun duplicate protection. |

## Prerequisites

- Windows with PowerShell and Microsoft Edge installed.
- Python 3.11 or newer with pip, available as `python` or `py`; tested with Python 3.11.9.
- Network access to Azure DevOps and, when installation is needed, Python packages and EdgeDriver downloads.
- An Azure DevOps Services work-item edit link and permission to create tasks and link them to the PBI.

Normal runs check package versions locally and skip pip when they already satisfy the requirements. Ordinary Edge windows are not used or closed. By default the automation window opens blank for manual navigation, CSV tags are skipped, and its dedicated profile is deleted after browser shutdown. Use `-AutoNavigation`, `-IncludeTags`, and `-KeepEdgeProfile` to reverse those defaults individually. The automation window still closes when the run ends, including when its profile is retained.

## Prepare the CSV

Save the file as UTF-8 CSV. Only the `Title` header is required, and task titles must be nonblank. `Description`, `RemainingWork`, `AssignedTo`, and `Tags` columns are optional. Missing optional values are treated as empty; `AssignedTo` still follows the PBI fallback rules below. The full template puts `AssignedTo` fourth and `Tags` fifth. Columns are read by name, so reduced and existing four-column CSVs remain supported.

The minimum format is:

```csv
Title
Review requirements
Implement changes
```

These reduced formats also work:

```csv
Title,Description
Review requirements,Review scope and acceptance criteria.
```

```csv
Title,Description,RemainingWork
Review requirements,Review scope and acceptance criteria.,2
```

The full format is:

```csv
Title,Description,RemainingWork,AssignedTo,Tags
Review requirements,"Review scope, dependencies, and acceptance criteria.",2,,Analysis;Planning
Implement changes,Implement the agreed changes.,4,person@example.com,Development
Test changes,Verify acceptance criteria and record results.,2,,Testing
```

| Column | Meaning |
| --- | --- |
| `Title` | Required task name. Repeated titles in the CSV are skipped after trimming, normalizing whitespace, and ignoring case. |
| `Description` | Optional column and plain-text value. Missing/blank values are omitted from the request. Commas and multiline values must be quoted as valid CSV. Text is escaped before being sent to Azure DevOps. |
| `RemainingWork` | Optional column and estimate in hours, such as `2` or `0.58`. Supplied values must be finite, numeric, and nonnegative. Missing/blank values are omitted from the request. |
| `AssignedTo` | Optional column and value. Enter a valid Azure DevOps account email/unique name to override the PBI assignee for that row. Blank cells or a missing column fall back to the PBI. Replace `person@example.com` in the example with a real project user. |
| `Tags` | Optional column and Azure DevOps labels, separated by semicolons, such as `Training;Reltio`. Missing/blank values are omitted from the request. These are labels, not command switches. |

CSV tags are skipped by default without editing the CSV. Add `-IncludeTags` to include them. New Azure DevOps tags require **Create tag definition** permission; if unavailable, omit `-IncludeTags`, leave the CSV values blank, or use existing permitted tags.

In the PBI-specific Reltio training CSVs, certification and exam tasks also carry `ReltioExam` alongside their training and role tags.

Tasks inherit the PBI's area and iteration. **Assigned To** follows this precedence:

1. A nonblank CSV `AssignedTo` value assigns the task to that account.
2. If the CSV value is blank or the column is missing, the task uses the source PBI's assignee (unique account name or identity ID).
3. If both are empty, the request explicitly sets Assigned To to empty, rather than relying on an implicit default or the signed-in browser user.

No new command switch is needed. Dry-run validation and creation use the same assignment rules, and the selected account/source is recorded only in the detailed task log. Azure DevOps validates account values and enforces its process rules; if a process disallows unassigned tasks or the account is invalid, validation fails instead of silently choosing another person. Existing tasks are not reassigned. Additional custom required fields may require script changes.

## Command parameters

These are the command-line switches (sometimes called flags or "tags") supported by the PowerShell launcher:

| PowerShell parameter | Python equivalent | Default | Effect |
| --- | --- | --- | --- |
| `-PbiUrl "LINK"` | `--pbi-url "LINK"` | Not supplied | Target PBI edit link. Python prompts for it when omitted, except in validation-only mode. URL query strings and fragments are omitted by the launcher. |
| `-Csv "FILE"` | `--csv "FILE"` | `tasks.csv` | CSV input. Relative paths passed to PowerShell resolve against the script folder. Absolute paths are also supported. |
| `-DryRun` | `--dry-run` | Off | Opens Edge, reads the PBI, checks duplicates, and validates planned requests against Azure DevOps using `validateOnly=true`. Saves no tasks. |
| `-ValidateOnly` | `--validate-only` | Off | Validates the CSV and any supplied PBI URL locally. Does not open Edge, contact Azure DevOps, or delete an existing browser profile. Launcher dependency checks still run. |
| `-AutoNavigation` | `--auto-navigation` | Off (manual navigation) | Opens the PBI automatically. Without this flag, Edge opens blank and you paste the PBI link yourself. |
| `-IncludeTags` | `--include-tags` | Off (skip tags) | Includes CSV tags in validation and creation requests. Without this flag, all CSV tags are omitted. |
| `-KeepEdgeProfile` | `--keep-edge-profile` | Off (cleanup enabled) | Retains the dedicated browser profile and saved sign-in after Edge closes. Without this flag, the profile is deleted after successful shutdown; logs/state remain and locked files produce a warning. |

`-ValidateOnly` takes precedence over the browser-related options, including `-DryRun` and default profile cleanup. It does not delete an existing profile. To actually create tasks, omit both `-ValidateOnly` and `-DryRun`.

The old `-ManualNavigation`, `-SkipTags`, and `-CleanEdgeProfile` switches are replaced by these defaults and are no longer accepted. Remove them from old commands. Direct Python commands use the same new defaults and opt-ins.

### Python-only options

The launcher supplies `--run-id` and `--log-file` automatically so both processes append to the same log. You normally do not set them yourself. Direct Python runs also create one `run_<run-id>.log` when no log path is supplied. Python supports `--ignore-state`, which ignores the local ledger but still checks live child-task titles. There is no PowerShell `-IgnoreState` parameter.

```powershell
python .\create_tasks.py --help
```

## Sample commands

Run these from the project folder. Replace the example rows before creating real tasks.

### Every PowerShell parameter

This includes all parameters and switches. It performs **local validation only** because `-ValidateOnly` is present:

```powershell
.\run.ps1 -PbiUrl "https://dev.azure.com/YOUR-ORG/YOUR-PROJECT/_workitems/edit/12345" -Csv "tasks_template.csv" -DryRun -ValidateOnly -AutoNavigation -IncludeTags -KeepEdgeProfile
```

### Validate against Azure DevOps

The recommended dry run uses the default manual navigation, skipped tags, and profile cleanup:

```powershell
.\run.ps1 -PbiUrl "https://dev.azure.com/YOUR-ORG/YOUR-PROJECT/_workitems/edit/12345" -Csv "tasks_template.csv" -DryRun
```

### Create tasks

After a successful dry run, omit `-DryRun` too:

```powershell
.\run.ps1 -PbiUrl "https://dev.azure.com/YOUR-ORG/YOUR-PROJECT/_workitems/edit/12345" -Csv "tasks_template.csv"
```

To open the PBI automatically, include CSV tags, and retain sign-in, add all three opt-ins (tag permissions must allow the supplied values):

```powershell
.\run.ps1 -PbiUrl "https://dev.azure.com/YOUR-ORG/YOUR-PROJECT/_workitems/edit/12345" -Csv "tasks_template.csv" -DryRun -AutoNavigation -IncludeTags -KeepEdgeProfile
```

### Use the populated task list

After creating and populating your own `tasks.csv` during setup:

```powershell
.\run.ps1 -PbiUrl "https://dev.azure.com/YOUR-ORG/YOUR-PROJECT/_workitems/edit/12345" -Csv "tasks.csv" -DryRun
```

## What happens during a run

1. PowerShell starts the shared log and records the parameters, replay command, working directory, versions, and input/source file hashes.
2. Dependencies are checked offline. Pip runs only when a package is missing or incompatible.
3. Python validates the CSV. Unless `-ValidateOnly` is set, it opens its dedicated Edge window.
4. Open the PBI in that window, sign in, complete MFA, and press Enter in the terminal only after the PBI loads. Type `CANCEL` instead to stop browser setup.
5. Python reads the PBI title, area, iteration, assignee, and existing child tasks. The inherited assignee is recorded in the detailed log. It prints a heading such as:

   ```text
   Adding Task under PBI: 1341029 - MDM | Reltio | Upskilling & Training | Abhishek - Sprint 0
   ```

6. Existing child-task titles and this PBI's success ledger are checked before planning new tasks. Every planned request is validated against Azure DevOps before any task is saved.
7. A dry run ends here. Otherwise, review the planned tasks and type `CREATE` when prompted. Any other response cancels creation.
8. Confirmed creations print `[SUCCESS] Task name`; created work-item IDs are recorded in the detailed log. Failures print `[FAILED] Task name` with concise guidance; full error details and tracebacks stay in the log. The run stops at the first creation failure; it does not automatically retry uncertain writes.
9. The automation browser closes. Its profile is cleaned up by default unless `-KeepEdgeProfile` is set. Logs and the ledger are retained.

Do not run concurrent imports. After an uncertain creation error, refresh the PBI before rerunning; a task may have been saved even when the response could not be confirmed. Duplicate detection is title-based, not a transaction or a guarantee against concurrent creation.

## Developer walkthrough

Start with the launcher, then follow the Python workflow in this order:

| Area | Where to read | What to notice |
| --- | --- | --- |
| Startup | [run.ps1](run.ps1) | Opt-in switches are inverted into workflow defaults. Paths are relative to the project; Python receives the same log path as the launcher. |
| Entry point | `main()` and `run_tasks()` | Python appends events to the shared log. Local validation returns before Edge starts; browser teardown lives in `finally`. |
| Input | `load_and_validate_tasks()` | Only Title is required. Optional columns default to blank, estimates are validated, and normalized duplicate titles are skipped. |
| Browser setup | `connect_to_edge()` and `wait_for_pbi()` | A dedicated profile isolates personal Edge windows. Sign-in is manual, and the requested PBI tab must be confirmed before requests run. |
| Authentication | `BROWSER_REQUEST_SCRIPT` and `browser_request()` | JavaScript fetch runs in the signed-in page, using same-origin cookies. Selenium's callback returns the result to Python; no PAT is extracted. |
| Task payload | `get_parent_assignee()` and `build_task_patch()` | JSON Patch operations set fields and the parent link. CSV assignment overrides the PBI; descriptions are escaped for the HTML field. |
| Duplicate protection | `collect_existing_titles()` and `load_created_titles()` | Live child tasks and a PBI-specific success ledger both contribute title checks. Neither is a concurrency lock. |
| Two-stage processing | `process_tasks()` and `submit_task()` | All planned requests are validated before confirmation or saving. A dry run uses the same payload but never saves it. |
| Success/failure | `process_tasks()` and `record_created_task()` | Only a confirmed ID and parent link are recorded as success. Uncertain writes stop the run instead of triggering an automatic retry. |
| Output | `RunLogFormatter`, `UserConsoleFilter`, and `configure_logging()` | Every file line is timestamped and source-labelled. Mark an event with `user_visible` or provide `console_message` only when the user needs to see it. |
| Cleanup | `close_edge()` | Browser shutdown precedes profile deletion. Redirected paths and locked files are handled safely; logs/state are not deleted. |

Comments explain the safety decisions rather than narrating each assignment. CSV files contain data, not code comments; their columns are documented above. The `temp/` browser profiles, logs, ledger, and `__pycache__/` contents are generated runtime artifacts, not source files to annotate or edit manually.

When extending the script, keep validation and creation payloads identical, preserve the assignment fallback, and update this README and CLI help with any new fields or switches. Test changes first with `-ValidateOnly`, then with `-DryRun` before creating live tasks.

## Logs and debugging

The console shows only browser/sign-in instructions, prompts, the PBI heading, planned/skipped task names, task results, concise errors, and a final summary. Technical details such as folder checks, versions, file hashes, command arguments, API timings, and tracebacks stay in log files. A dependency installation displays a short progress message, not pip's detailed output.

Each run creates only **one file**, `temp/logs/run_<run-id>.log`. The launcher prints its path at the end. It contains parameters, the replay command, file hashes, dependency output, prompts, confirmations, PBI/task information, API status/timing, errors/tracebacks, cleanup, and exit status.

Entries are appended as events happen, not collected into separate sections at the end. Each line uses this format:

```text
2026-10-08T14:00:00.000+05:30 | POWERSHELL | INFO | [STEP 5] Launch task creator
2026-10-08T14:00:01.000+05:30 | PYTHON | INFO | [STEP] Load and validate CSV.
2026-10-08T14:00:02.000+05:30 | POWERSHELL | INFO | [STEP 5] Task creator exit code: 0
```

| Source | Meaning |
| --- | --- |
| `POWERSHELL` | Launcher setup, parameters, user-facing messages, and final status. |
| `DEPENDENCY` | Output from the local Python package/version check. |
| `PIP` | Package installation output, only when installation is needed. |
| `PYTHON` | CSV/browser/task workflow events, prompts, and errors. Traceback lines receive the same timestamp/source labels. |

The launcher waits for Python to finish; both writers append directly with timezone-aware, millisecond timestamps. Python flushes each event and its interactive process is not piped through output filters. Old four-file logs are left unchanged; new runs do not create those files.

Logs record workflow confirmations, not raw answers, manual browser clicks, or sign-in input. Request payloads and authentication headers are not deliberately logged. Do not share the browser profile, and review the log for sensitive work-item information before sharing it.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| PowerShell says script execution is disabled | For trusted, reviewed scripts, inspect `Get-ExecutionPolicy -List`. If organizational policy permits, use `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` in the current terminal. This setting expires when that terminal closes. If Group Policy still blocks execution, ask IT; do not try to bypass it. |
| A trusted downloaded script is blocked as unsigned | After reviewing the script and verifying its source, use `Unblock-File -LiteralPath .\run.ps1`. This removes the download marker; it does not override organizational execution policy. |
| Python is missing or opens Microsoft Store | Install Python with pip and PATH enabled, then reopen PowerShell. Check Windows app execution aliases/PATH if `python` still invokes the Store; verify `python --version` and `python -m pip --version` before running the project. |
| Dependency or EdgeDriver downloads fail | Check proxy/network restrictions with IT. The launcher installs only missing/incompatible packages, and Selenium may need to download EdgeDriver on first use. Review the run log for the actual failure. |
| Missing CSV / default input not found | Create your own CSV from the template or pass the correct filename with `-Csv`. Relative CSV paths resolve against the project folder; use an absolute path for a file elsewhere. |
| Sign-in redirect shows "services aren't available" | Omit `-AutoNavigation` to use the default manual navigation, or paste the PBI link again in the same automation window. Confirm readiness only after it loads. |
| `TF401289` / no permission to create tags | Omit `-IncludeTags` to use the default skipped tags, clear CSV values, or ask your project administrator for Create tag definition permission. |
| Edge cannot launch | Close an earlier automation Edge window using the same profile. Check Edge/EdgeDriver compatibility and download/network access. |
| Profile cleanup reports locked files | Close any remaining automation browser session. Remaining files are not forcibly removed; cleanup can be attempted on a later browser run. |
| No tasks created in a successful run | Check `-DryRun`, `-ValidateOnly`, duplicate skips, and whether you accepted the `CREATE` prompt. |
| Custom process rejects a required field | Review the validation error with your project administrator; the script may need additional field support. |

Only Azure DevOps Services links in `https://dev.azure.com/ORG/PROJECT/_workitems/edit/ID` or `https://ORG.visualstudio.com/PROJECT/_workitems/edit/ID` format are supported. On-premises Azure DevOps Server links are not supported.