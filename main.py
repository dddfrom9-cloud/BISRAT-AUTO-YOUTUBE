import json
import mimetypes
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import io

SCHEDULE_PATH = Path("schedule.json")
STATE_PATH = Path("state.json")

DEFAULT_SCHEDULE = {
    "mode": "repeat",
    "intervalHours": 6,
    "intervalMinutes": 0,
    "active": False,
    "nextRunAt": None,
    "lastRunAt": None,
    "updatedAt": None,
}

DEFAULT_STATE = {
    "uploaded": [],
    "youtube_ids": {},
}


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return json.loads(json.dumps(default))
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return json.loads(json.dumps(default))
    return data


def save_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def normalize_state(raw: dict) -> dict:
    state = json.loads(json.dumps(DEFAULT_STATE))
    uploaded = raw.get("uploaded")
    if isinstance(uploaded, list):
        for item in uploaded:
            if isinstance(item, str) and item not in state["uploaded"]:
                state["uploaded"].append(item)

    yt_ids = raw.get("youtube_ids")
    if isinstance(yt_ids, dict):
        for k, v in yt_ids.items():
            if isinstance(k, str):
                state["youtube_ids"][k] = v
                if k not in state["uploaded"]:
                    state["uploaded"].append(k)

    for key, val in raw.items():
        if key not in ("uploaded", "youtube_ids"):
            state[key] = val

    return state


def get_google_creds() -> Credentials:
    client_id = os.environ["GOOGLE_CLIENT_ID"]
    client_secret = os.environ["GOOGLE_CLIENT_SECRET"]
    refresh_token = os.environ["GOOGLE_REFRESH_TOKEN"]

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=[
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/youtube.upload",
        ],
    )
    creds.refresh(Request())
    return creds


def should_run_upload(schedule: dict) -> bool:
    manual = os.environ.get("MANUAL_TRIGGER", "").lower() == "true"
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if manual or event_name == "workflow_dispatch":
        return True

    if not schedule.get("active"):
        return False

    next_run_str = schedule.get("nextRunAt")
    if not next_run_str:
        return False

    try:
        next_run = datetime.fromisoformat(next_run_str.replace("Z", "+00:00"))
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=timezone.utc)
    except ValueError:
        return False

    return datetime.now(timezone.utc) >= next_run


def advance_schedule(schedule: dict) -> dict:
    now = datetime.now(timezone.utc)
    schedule["lastRunAt"] = now.isoformat()
    schedule["updatedAt"] = now.isoformat()

    mode = schedule.get("mode", "repeat")
    if mode == "once":
        schedule["active"] = False
        schedule["nextRunAt"] = None
    else:
        hours = max(0, int(schedule.get("intervalHours", 6) or 0))
        minutes = max(0, min(59, int(schedule.get("intervalMinutes", 0) or 0)))
        delta = timedelta(hours=hours, minutes=minutes)
        if delta.total_seconds() <= 0:
            delta = timedelta(hours=1)
        schedule["active"] = True
        schedule["nextRunAt"] = (now + delta).isoformat()

    return schedule


def list_next_drive_video(drive_service, folder_id: str, uploaded_ids: set) -> dict | None:
    query = (
        f"'{folder_id}' in parents and trashed = false and "
        f"mimeType contains 'video/'"
    )
    page_token = None
    while True:
        resp = (
            drive_service.files()
            .list(
                q=query,
                fields="nextPageToken, files(id, name, mimeType, createdTime)",
                orderBy="name",
                pageSize=50,
                pageToken=page_token,
            )
            .execute()
        )
        for f in resp.get("files", []):
            if f["id"] not in uploaded_ids:
                return f
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return None


def download_drive_file(drive_service, file_id: str, target_path: Path) -> None:
    request = drive_service.files().get_media(fileId=file_id)
    with target_path.open("wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()


def upload_to_youtube(youtube_service, file_path: Path, title: str) -> str:
    publish_at = (datetime.now(timezone.utc) + timedelta(minutes=90)).strftime(
        "%Y-%m-%dT%H:%M:%S.0Z"
    )
    description = os.environ.get("DEFAULT_DESCRIPTION", "")
    raw_tags = os.environ.get("DEFAULT_TAGS", "")
    tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    category_id = os.environ.get("YOUTUBE_CATEGORY_ID") or "22"

    mime_type, _ = mimetypes.guess_type(str(file_path))
    if not mime_type or not mime_type.startswith("video/"):
        mime_type = "video/mp4"

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at,
        },
    }

    media = MediaFileUpload(str(file_path), mimetype=mime_type, resumable=True)
    request = youtube_service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )
    response = None
    while response is None:
        _, response = request.next_chunk()
    return response["id"]


def main() -> None:
    schedule = {**DEFAULT_SCHEDULE, **load_json(SCHEDULE_PATH, DEFAULT_SCHEDULE)}
    state = normalize_state(load_json(STATE_PATH, DEFAULT_STATE))

    if not should_run_upload(schedule):
        print("Upload not due or schedule inactive. Skipping.")
        save_json(SCHEDULE_PATH, schedule)
        save_json(STATE_PATH, state)
        return

    folder_id = os.environ.get("DRIVE_FOLDER_ID") or "1T6p5uPhh720-NG_f7yuJmvi3A5Wa1bgg"
    creds = get_google_creds()
    drive_service = build("drive", "v3", credentials=creds)
    youtube_service = build("youtube", "v3", credentials=creds)

    uploaded_set = set(state["uploaded"])
    next_video = list_next_drive_video(drive_service, folder_id, uploaded_set)

    if not next_video:
        print("No new unprocessed videos found in Google Drive queue.")
        save_json(STATE_PATH, state)
        return

    drive_id = next_video["id"]
    raw_name = next_video.get("name") or "BISRAT_VIDEO"
    clean_title = Path(raw_name).stem.replace("_", " ").strip() or "BISRAT VIDEO"
    suffix = Path(raw_name).suffix or ".mp4"

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_file = Path(tmp_dir) / f"{drive_id}{suffix}"
        print(f"Downloading '{raw_name}' ({drive_id}) from Drive...")
        download_drive_file(drive_service, drive_id, tmp_file)

        print(f"Uploading '{clean_title}' to YouTube (scheduled +90 mins)...")
        yt_id = upload_to_youtube(youtube_service, tmp_file, clean_title)

    if drive_id not in state["uploaded"]:
        state["uploaded"].append(drive_id)
    state["youtube_ids"][drive_id] = yt_id
    state.pop("last_error", None)

    schedule = advance_schedule(schedule)

    save_json(STATE_PATH, state)
    save_json(SCHEDULE_PATH, schedule)
    print(f"Upload successful! Drive ID: {drive_id} -> YouTube ID: {yt_id}")


if __name__ == "__main__":
    main()
