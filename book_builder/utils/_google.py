"""Google API helpers for the CBC‑Grade‑10‑Maths project.

This module centralises authentication and service creation for both
Google Drive and Sheets.  The existing helper scripts duplicate this
boilerplate; moving it here means other modules can import and reuse it.

The functions in this file are deliberately lightweight wrappers around
`googleapiclient.discovery.build`.  They expect a `credentials.json`
file in the ``utils/secret`` subdirectory (previously placed alongside the
script) and will store OAUTH tokens in a local `token.pickle` if needed.
"""

from __future__ import annotations

import pickle
import functools
from pathlib import Path
from typing import Iterable, Dict, Any

from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


# configuration and tokens live in the "secret" subdirectory to avoid
# accidentally committing sensitive information.  We write the token into
# the same folder so that it is kept alongside the credentials rather than
# the public source tree.
CONFIG_PATH = Path.cwd() / "secret" / "google_ids.json"
CREDENTIALS_FILE = Path.cwd() / "secret" / "credentials.json"
TOKEN_FILE = Path.cwd() / "secret" / "token.pickle"


# scopes used in this repository; extra scopes can be passed to the helpers.
DEFAULT_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]


def _get_credentials(scopes: list[str] | None = None) -> Any:
    """Return valid credentials, performing the OAuth flow if necessary.

    The scopes list may be extended by callers; a cached token will be
    re‑used when possible.
    """

    scopes = scopes or DEFAULT_SCOPES
    creds = None

    # load existing token if present
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    # if we already have credentials that are valid and cover the
    # requested scopes, return them immediately.
    if creds and creds.valid and not creds.expired:
        if hasattr(creds, "scopes"):
            existing = set(creds.scopes)
            needed = set(scopes)
            if needed.issubset(existing):
                return creds
        else:
            # unknown scopes, conservatively re‑auth
            pass

    # if we have expired credentials with a refresh token, refresh them
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None  # fall through to reauth
    
    if not creds or creds.expired:
        if not CREDENTIALS_FILE.exists():
            raise FileNotFoundError(f"credentials.json not found at {CREDENTIALS_FILE}")

        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), scopes)
        creds = flow.run_local_server(port=0)

    # cache for next time
    with open(TOKEN_FILE, "wb") as f:
        pickle.dump(creds, f)

    return creds



# helper used by callers that perform API requests.  When a token has
# expired the first request will raise ``HttpError`` with a 401/403 status.
# our strategy is to remove the cached token and retry the entire operation
# once; the next call into :func:`_get_credentials` will prompt the user for
# fresh credentials (or refresh the token automatically).  the decorator
# can be applied to any function that may interact with Google APIs.



def _is_auth_failure(exc: Exception) -> bool:
    """Return true if *exc* is an authorization error from the API.

    The :class:`HttpError` raised by ``googleapiclient`` carries the HTTP
    response on ``exc.resp``.
    """
    if not isinstance(exc, HttpError):
        return False
    status = getattr(exc.resp, "status", None)
    return status in (401, 403)


def retry_on_auth_failure(func):
    """Decorator that reruns *func* one time after clearing token file.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # cover HttpError and friends
            if _is_auth_failure(exc):
                # blow away cached token so that _get_credentials will
                # initiate the OAuth flow again.
                try:
                    TOKEN_FILE.unlink()
                except OSError:
                    pass
                # second attempt; if it fails again let the exception bubble
                return func(*args, **kwargs)
            raise

    return wrapper


def get_drive_service(scopes: list[str] | None = None) -> Any:
    """Return a Google Drive API service object.

    Additional scopes may be supplied, but the default is
    ``drive.readonly``.
    """
    creds = _get_credentials(scopes or ["https://www.googleapis.com/auth/drive.readonly"])
    return build("drive", "v3", credentials=creds)


def get_sheets_service(scopes: list[str] | None = None) -> Any:
    """Return a Google Sheets API service object.

    The default scope is ``spreadsheets``.  Callers that need write
    access may supply expanded scopes.
    """
    creds = _get_credentials(scopes or ["https://www.googleapis.com/auth/spreadsheets"])
    return build("sheets", "v4", credentials=creds)



@retry_on_auth_failure
def _fetch_tab_values(spreadsheet_id: str, tab_name: str) -> list[list[str]]:
    """Fetch a range of cells from a Google Sheet """
    service = get_sheets_service()
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id, range=f"'{tab_name}'").execute()
    return result.get("values", [])



def load_ids_config() -> dict[str, Any]:
    """Return the JSON object from ``google_ids.json``.

    Helper for other modules that need folder/spreadsheet IDs.
    """
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"google_ids.json not found at {CONFIG_PATH}")
    import json

    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)
    

@retry_on_auth_failure
def write_validated_to_sheet(
    grade: str,
    rows: Iterable[Dict[str, str]],
    sheet_name: str = "Automatic Links Upload"
) -> None:
    """Write *rows* back to a (possibly new) sheet in the same workbook.

    This mirrors the behaviour of the original helper, but operates purely on
    the row data provided.
    """
    rows = list(rows)
    if not rows:
        return
    service = get_sheets_service()
    ids = load_ids_config()
    try:
        spreadsheet_id = ids["grade"][grade]["textbook_spreadsheet_id"]
    except KeyError:
        raise ValueError(f"Spreadsheet ID not found for grade '{grade}'")
    sheet = service.spreadsheets()

    # ensure sheet exists
    metadata = sheet.get(spreadsheetId=spreadsheet_id).execute()
    existing_titles = [s["properties"]["title"] for s in metadata.get("sheets", [])]
    if sheet_name not in existing_titles:
        body = {"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]}
        sheet.batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()

    # clear
    sheet.values().clear(spreadsheetId=spreadsheet_id, range=f"'{sheet_name}'!A:Z").execute()
    values = [list(rows[0].keys())] + [[row.get(col, "") for col in rows[0].keys()] for row in rows]
    sheet.values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()
