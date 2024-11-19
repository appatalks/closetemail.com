import os
import requests
import subprocess
import string
import re
from datetime import datetime, timezone
from typing import List, Dict

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
    # Extract URL facets from the post content
    facets = parse_facets(post_content)
    
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    post = {
        "$type": "app.bsky.feed.post",
        "text": post_content,
        "createdAt": now,
    }

    # Include the facets in the post using the parsed facets
    if facets:
        post["facets"] = facets

    if embed:
        post["embed"] = embed
    
    try:
        resp = requests.post(
            pds_url + "/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {session['accessJwt']}"},
            json={
                "repo": session["did"],
                "collection": "app.bsky.feed.post",
                "record": post,
            },
        )
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        # Print additional debugging information
        print(f"HTTP Error: {e}")
        print(f"Response Status Code: {resp.status_code}")
        print(f"Response Content: {resp.text}")
        raise

    return resp.json()

# Function to fetch top 3 news headlines (due to character limit)
def fetch_top4_news():
    # Run the curl pipeline command
    curl_command = """
    curl -s "https://ground.news/interest/international" | \
    grep -o '"start":"[^"]*","title":"[^"]*"' | \
    sed -E 's/"start":"([^"]*)","title":"([^"]*)"/\\1 - \\2/' | \
    awk -F ' - ' '{print $2}' | head -n 3
    """
    result = subprocess.run(curl_command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Error fetching news: {result.stderr}")
    return result.stdout.strip().split("\n")

# Function to reduce content to a 300-character limit
def reduce_to_300_chars(headlines, additional_text):
    # Remove punctuation from each headline
    translator = str.maketrans("", "", string.punctuation)
    headlines = [headline.translate(translator) for headline in headlines]
    
    # Calculate the maximum length allowed for the headlines
    max_length = 296 - len(additional_text) - len("\n - ") * len(headlines)  # Account for formatting
    combined_length = sum(len(headline) for headline in headlines)

    # Track which headlines were truncated
    truncated_indices = set()

    # Step 1: Remove words after the last comma for headlines with >2 commas
    for i, headline in enumerate(headlines):
        if headline.count(",") > 2:
            last_comma_index = headline.rfind(",")
            if last_comma_index != -1:
                headlines[i] = headline[:last_comma_index]
                truncated_indices.add(i)

    # Recalculate combined length after trimming by commas
    combined_length = sum(len(headline) for headline in headlines)

    # Step 2: Iteratively remove the last word from the longest headlines until within limit
    while combined_length > max_length:
        # Find the headline that is longest and trim its last word
        longest_idx = max(range(len(headlines)), key=lambda x: len(headlines[x]))
        if len(headlines[longest_idx].split()) > 1:  # Ensure there's more than one word to trim
            words = headlines[longest_idx].split()
            headlines[longest_idx] = " ".join(words[:-1])
            truncated_indices.add(longest_idx)
        else:
            # If a headline only has one word, leave it alone and move to others
            break
        
        combined_length = sum(len(headline) for headline in headlines)

    # Step 3: Add ".." to truncated headlines
    for i in truncated_indices:
        if not headlines[i].endswith(".."):
            headlines[i] += " .."

    return headlines

# Function to format the date with a suffix
def get_date_with_suffix():
    today = datetime.utcnow()
    day = today.day
    if 11 <= day <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return today.strftime(f"%A, %B {day}{suffix}, %Y")

# Function to parse URLs from text and return a list of spans
def parse_urls(text: str) -> List[Dict]:
    spans = []
    # Partial/naive URL regex based on: https://stackoverflow.com/a/3809435
    url_regex = rb"[$|\W](https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*[-a-zA-Z0-9@%_\+~#//=])?)"
    text_bytes = text.encode("UTF-8")
    for m in re.finditer(url_regex, text_bytes):
        spans.append({
            "start": m.start(1),
            "end": m.end(1),
            "url": m.group(1).decode("UTF-8"),
        })
    return spans

# Function to parse facets from the text
def parse_facets(text: str) -> List[Dict]:
    facets = []
    for u in parse_urls(text):
        facets.append({
            "index": {
                "byteStart": u["start"],
                "byteEnd": u["end"],
            },
            "features": [
                {
                    "$type": "app.bsky.richtext.facet#link",
                    "uri": u["url"],
                }
            ],
        })
    return facets

def main():
    # Bluesky setup
    pds_url = "https://bsky.social"
    handle = os.getenv("BLUESKY_TOP4NEWS_H")
    password = os.getenv("BLUESKY_TOP4NEWS_P")
    
    # Log in to Bluesky
    #session = bsky_login_session(pds_url, handle, password)
    #print("Session data:", session)  # Debug session details
    
    # Fetch top 3 news headlines
    try:
        top3_news = fetch_top4_news()
    except RuntimeError as e:
        print("Error fetching news:", e)
        return
    
    # Format the date and additional text
    formatted_date = get_date_with_suffix()
    additional_text = "Read more at: https://ground.news/"
    post_header = f"Top Headlines for {formatted_date}:\n"
    
    # Reduce content to 300 characters
    trimmed_headlines = reduce_to_300_chars(top3_news, post_header + additional_text)
    
    # Combine the headlines with the formatted header and link
    post_content = (
        post_header +
        "\n - ".join([""] + trimmed_headlines) +  # Add " - " before each headline
        f"\n\n{additional_text}"
    )
    embed = None
    
    # Post to Bluesky
    #try:
    #    create_bsky_post(session, pds_url, post_content, embed)
    #except requests.exceptions.HTTPError as e:
    #    print("Failed to create post:", e)
    #    return

    # Debug output
    print("Debug Response:\n", post_content)

if __name__ == "__main__":
    main()
