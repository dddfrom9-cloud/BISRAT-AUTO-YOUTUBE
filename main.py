import io
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/youtube.upload",
]
STATE_FILE = Path("state.json")
DOWNLOAD_DIR = Path("downloads")
CHUNK_SIZE = 8 * 1024 * 1024

def required_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing GitHub Actions secret: {name}")
    return value

def google_services():
    creds = Credentials(
        token=None,
        refresh_token=required_env("GOOGLE_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=required_env("GOOGLE_CLIENT_ID"),
        client_secret=required_env("GOOGLE_CLIENT_SECRET"),
        scopes=SCOPES,
    )
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    return drive, youtube

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"uploaded": []}

def list_videos(drive, folder_id):
    query = (
        f"'{folder_id}' in parents and trashed = false "
        "and mimeType contains 'video/'"
    )
    items, page_token = [], None
    while True:
        response = drive.files().list(
            q=query,
            pageSize=1000,
            pageToken=page_token,
            orderBy="name",
            fields="nextPageToken, files(id,name,mimeType,size,modifiedTime)",
        ).execute()
        items.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return items

def safe_title(filename):
    title = Path(filename).stem
    title = re.sub(r"[_]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return (title or "New video")[:100]

def download_video(drive, file_id, filename):
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    path = DOWNLOAD_DIR / Path(filename).name
    request = drive.files().get_media(fileId=file_id)
    with path.open("wb") as output:
        downloader = MediaIoBaseDownload(output, request, chunksize=CHUNK_SIZE)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                print(f"Drive download: {int(status.progress() * 100)}%")
    return path

def upload_video(youtube, path, title):
    # Schedule publication 90 minutes after this run starts, allowing time
    # for the video transfer and YouTube processing.
    publish_at = (datetime.now(timezone.utc) + timedelta(minutes=90))
    publish_at = publish_at.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    description = os.environ.get(
        "DEFAULT_DESCRIPTION",
        "Thanks for watching! Subscribe for more videos.",
    )
    tags = [x.strip() for x in os.environ.get("DEFAULT_TAGS", "").split(",") if x.strip()]
    category = os.environ.get("YOUTUBE_CATEGORY_ID", "22")

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": category,
            "tags": tags[:500],
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at,
        },
    }
    media = MediaFileUpload(
        str(path),
        mimetype="video/*",
        chunksize=CHUNK_SIZE,
        resumable=True,
    )
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"YouTube upload: {int(status.progress() * 100)}%")
    print(f"Uploaded video ID: {response['id']}")
    print(f"Scheduled publication (UTC): {publish_at}")
    return response["id"]

def main():
    folder_id = required_env("DRIVE_FOLDER_ID")
    drive, youtube = google_services()
    state = load_state()
    uploaded = set(state.get("uploaded", []))
    candidates = list_videos(drive, folder_id)
    next_video = next((v for v in candidates if v["id"] not in uploaded), None)

    if not next_video:
        print("Queue empty: no new videos in the Google Drive folder.")
        return

    print(f"Next video: {next_video['name']}")
    path = download_video(drive, next_video["id"], next_video["name"])
    try:
        video_id = upload_video(youtube, path, safe_title(next_video["name"]))
        state.setdefault("uploaded", []).append(next_video["id"])
        state.setdefault("youtube_ids", {})[next_video["id"]] = video_id
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        print("Queue state updated.")
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
