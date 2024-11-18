import os
import random
import requests
import openai
from datetime import datetime, timezone

def bsky_login_session(pds_url: str, handle: str, password: str):
    resp = requests.post(
        pds_url + "/xrpc/com.atproto.server.createSession",
        json={"identifier": handle, "password": password},
    )
    resp.raise_for_status()
    return resp.json()

def create_bsky_post(session, pds_url, post_content):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    post = {
        "$type": "app.bsky.feed.post",
        "text": post_content,
        "createdAt": now,
    }
    
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

def generate_kitten_image():
    openai.api_key = os.getenv("OPENAI_API_KEY")
    response = openai.Image.create(
        prompt="A super cute kitten in a playful pose with a beautiful background, very colorful and detailed",
        n=1,
        size="1024x1024"
    )
    return response['data'][0]['url']

def generate_kitten_fact():
    openai.api_key = os.getenv("OPENAI_API_KEY")
    response = openai.Completion.create(
        model="text-davinci-003",
        prompt="Provide a cute and fun fact about kittens.",
        max_tokens=50
    )
    return response.choices[0].text.strip()

def main():
    pds_url = "https://bsky.social"
    handle = os.getenv("BLUESKY_HANDLE")
    password = os.getenv("BLUESKY_PASSWORD")

    # Log in to Bluesky
    session = bsky_login_session(pds_url, handle, password)

    # Randomly decide whether to post an image or a fun fact
    if random.choice([True, False]):
        # Generate a kitten image
        image_url = generate_kitten_image()
        post_content = f"MeowMeow! 🐾\n{image_url}"
    else:
        # Generate a kitten fun fact
        post_content = generate_kitten_fact()

    # Create a post on Bluesky
    create_bsky_post(session, pds_url, post_content)

if __name__ == "__main__":
    main()
