"""Extract: pull comments from the YouTube Data API v3.

One read-only API key covers every channel. The Google client library is
imported lazily so demo mode and the tests run without it installed.
"""
import time

try:  # pragma: no cover - exercised only in live mode
    from googleapiclient.errors import HttpError
except ImportError:  # demo / test environments without the Google SDK
    class HttpError(Exception):  # type: ignore[no-redef]
        resp = None


def make_client(api_key: str):
    from googleapiclient.discovery import build
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


def get_upload_playlist(youtube, channel_id: str):
    """Every channel has a hidden 'uploads' playlist containing all its videos."""
    resp = youtube.channels().list(part="contentDetails", id=channel_id).execute()
    items = resp.get("items", [])
    if not items:
        return None
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def list_video_ids(youtube, uploads_playlist: str, max_videos: int):
    """Walk the uploads playlist, newest first, up to max_videos."""
    if not uploads_playlist:
        return []
    video_ids, page_token = [], None
    while len(video_ids) < max_videos:
        resp = youtube.playlistItems().list(
            part="contentDetails", playlistId=uploads_playlist,
            maxResults=50, pageToken=page_token,
        ).execute()
        for it in resp.get("items", []):
            video_ids.append(it["contentDetails"]["videoId"])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return video_ids[:max_videos]


def fetch_video_titles(youtube, video_ids):
    """Return {video_id: title} for the given IDs (batched 50 per call, 1 quota unit each)."""
    titles = {}
    ids = list(dict.fromkeys(video_ids))  # de-dup, keep order
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        try:
            resp = youtube.videos().list(part="snippet", id=",".join(chunk),
                                         maxResults=50).execute()
        except HttpError:
            continue
        for item in resp.get("items", []):
            titles[item["id"]] = item["snippet"]["title"]
    return titles


def fetch_comments(youtube, video_id: str, max_retries: int = 5, sleep=time.sleep):
    """Yield top-level comments for one video, handling paging, retries and errors."""
    page_token, retries = None, 0
    while True:
        try:
            resp = youtube.commentThreads().list(
                part="snippet", videoId=video_id, maxResults=100,
                textFormat="plainText", order="relevance", pageToken=page_token,
            ).execute()
        except HttpError as e:
            status = getattr(getattr(e, "resp", None), "status", 0) or 0
            # Comments disabled / video gone: skip this video.
            if status in (403, 404):
                return
            # Rate limited / server error: bounded exponential back-off.
            if (status == 429 or status >= 500) and retries < max_retries:
                retries += 1
                sleep(min(60, 2 ** retries))
                continue
            raise
        retries = 0
        for thread in resp.get("items", []):
            top = thread["snippet"]["topLevelComment"]
            s = top["snippet"]
            yield {
                "comment_id": top["id"],
                "video_id": video_id,
                "text": s["textDisplay"],
                "likes": s["likeCount"],
                "author": s["authorDisplayName"],
                "published_at": s["publishedAt"],
            }
        page_token = resp.get("nextPageToken")
        if not page_token:
            return
        sleep(0.1)  # stay well under rate limits
