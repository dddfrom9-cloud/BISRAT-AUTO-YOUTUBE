# BISRAT AUTO YOUTUBE

Cloud video queue: Google Drive folder -> GitHub Actions -> YouTube scheduled publishing.

## Important
- This project does not need your phone to stay on after setup.
- GitHub Actions scheduled jobs are not guaranteed to start at the exact minute.
- The workflow runs at 00:17, 06:17, 12:17 and 18:17 Ethiopia time (UTC+3).
- Each video is uploaded as private and scheduled for public release 90 minutes after the workflow starts.
- Keep this repository public to use GitHub-hosted Actions without consuming private-repository minutes. Never put credentials or video files in the repository.
- YouTube API quota, Google account security, Drive storage, and upload limits still apply.
- Test with one short video first. Check YouTube Studio to confirm the scheduled publication time.

## 1. Prepare Google Drive
1. Create a folder named `BISRAT_UPLOADS`.
2. Put MP4/MOV videos in it. The uploader selects the first unprocessed video by filename.
3. Copy the folder ID from its URL: `https://drive.google.com/drive/folders/FOLDER_ID`.

## 2. Create Google API credentials
1. Open https://console.cloud.google.com/ on your phone and create a Google Cloud project.
2. Enable **Google Drive API** and **YouTube Data API v3**.
3. Configure the OAuth consent screen. Add your Google account as a test user if the app is in Testing.
4. Create an OAuth Client ID of type **Desktop app** and download its JSON.
5. Obtain a refresh token for these scopes:
   - `https://www.googleapis.com/auth/drive.readonly`
   - `https://www.googleapis.com/auth/youtube.upload`

For a personal test, Google's OAuth Playground can be used with your own OAuth client credentials. Use offline access and save the refresh token securely. If your consent screen is in Testing, Google may expire refresh tokens after 7 days; move the app to an appropriate production/published state if eligible, and follow Google's verification requirements. Never share the client secret or refresh token with anyone.

## 3. Create the GitHub repository
1. Open https://github.com/new on your phone.
2. Create a repository named `bisrat-auto-youtube`.
3. Set it to **Public** so standard GitHub-hosted Actions are free.
4. Upload the files from this project, preserving `.github/workflows/autopost.yml`.
5. In the repository, open Settings -> Secrets and variables -> Actions -> New repository secret.
6. Add these four secrets:
   - `DRIVE_FOLDER_ID` = Google Drive folder ID
   - `GOOGLE_CLIENT_ID` = OAuth client ID
   - `GOOGLE_CLIENT_SECRET` = OAuth client secret
   - `GOOGLE_REFRESH_TOKEN` = OAuth refresh token
7. Optional repository variables:
   - `DEFAULT_DESCRIPTION`
   - `DEFAULT_TAGS` (comma-separated)
   - `YOUTUBE_CATEGORY_ID` (default 22)

## 4. Test safely
1. Open the repository's Actions tab.
2. Select **BISRAT AUTO YOUTUBE**.
3. Tap **Run workflow**.
4. Check the run log. Then open YouTube Studio -> Content -> Scheduled.
5. Confirm the video, title and scheduled publication time before relying on automatic runs.

## Queue behavior
- Do not rename or move videos after they are queued.
- Successfully uploaded Drive file IDs are stored in `state.json`.
- To intentionally upload a video again, remove its Drive file ID from `state.json`.
- If a run fails after YouTube accepts the upload but before state is saved, inspect YouTube Studio before retrying to avoid a duplicate.

## Limitations
- GitHub scheduled workflows can be delayed or fail. They are scheduled 17 minutes past the hour to reduce top-of-hour congestion; public-repository schedules can be disabled after 60 days without repository activity.
- Large video downloads/uploads can exceed available runner time or network limits.
- This basic version uses the filename as the title and one default description/tags set for every video.
- It does not create thumbnails or edit videos.
- A free Google Cloud project and OAuth setup are required; this is not a zero-configuration service.
