import os
import requests
import subprocess
from datetime import datetime, timezone

# Function to fetch top 4 news headlines and format timestamps
def fetch_top4_news():
    # Run the curl pipeline command
    curl_command = """
    curl -s "https://ground.news/interest/international" | \
    grep -o '"start":"[^"]*","title":"[^"]*"' | \
    sed -E 's/"start":"([^"]*)","title":"([^"]*)"/\\1 - \\2/' | \
    awk -F ' - ' '{ cmd="date -u -d \\"" $1 "\\" +\\"%Y-%m-%d %H:%M UTC\\""; cmd | getline new_date; close(cmd); print new_date " - " $2 }' | \
    sort | head -n 4
    """
    result = subprocess.run(curl_command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Error fetching news: {result.stderr}")
    return result.stdout.strip().split("\n")

# Function to log in to Bluesky
def bsky_login_session(pds_url: str, handle: str, password: str):
    resp = requests.post(
        pds_url + "/xrpc/com.atproto.server.createSession",
        json={"identifier": handle, "password": password},
    )
    resp.raise_for_status()
    return resp.json()

# Function to create a Bluesky post
def create_bsky_post(session, pds_url, post_content, embed=None):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    post = {
        "$type": "app.bsky.feed.post",
        "text": post_content,
        "createdAt": now,
    }
    if embed:
        post["embed"] = embed
    
    resp = requests.post(
        pds_url + "/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": "Bearer " + session["accessJwt"]},
        json={
            "repo": session["did"],
            "collection": "app.bsky.feed.post",
            "record": post,
        },
    )
    resp.raise_for_status()
    return resp.json()

def get_date_with_suffix():
    # Get the current UTC date
    today = datetime.utcnow()
    day = today.day

    # Determine the suffix for the day
    if 11 <= day <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    
    # Format the date as "Monday, November 12th, 2024"
    return today.strftime(f"%A, %B {day}{suffix}, %Y")

def main():
    # Bluesky setup
    pds_url = "https://bsky.social"
    handle = os.getenv("BLUESKY_TOP4NEWS_H")
    password = os.getenv("BLUESKY_TOP4NEWS_P")
    
    # Log in to Bluesky
    # session = bsky_login_session(pds_url, handle, password)
    
    # Fetch top 4 news headlines
    top4_news = fetch_top4_news()
    
    # Get the formatted date with a suffix
    formatted_date = get_date_with_suffix()
    
    # Combine the news headlines into a single post with a link
    post_content = (
        f"Top Headlines for {formatted_date}:\n" +
        "\n".join(top4_news) +
        "\n\nRead more at: https://ground.news/interest/international"
    )
    
    # Post to Bluesky
    # create_bsky_post(session, pds_url, post_content, embed)

    # Debug
    print("Debug Response:", post_content)

if __name__ == "__main__":
    main()
