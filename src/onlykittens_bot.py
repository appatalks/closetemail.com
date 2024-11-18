import os
import random
import requests
from openai import OpenAI
from datetime import datetime, timezone
from typing import List
from PIL import Image
import io

def bsky_login_session(pds_url: str, handle: str, password: str):
    resp = requests.post(
        pds_url + "/xrpc/com.atproto.server.createSession",
        json={"identifier": handle, "password": password},
    )
    resp.raise_for_status()
    return resp.json()

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

def generate_kitten_image():
    # https://platform.openai.com/docs/api-reference/images
    api_key = os.getenv("OPENAI_API_KEY")
    response = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        },
        json={
            "model": "dall-e-3",
            "prompt": "A super cute kitten in a playful pose with a beautiful background, very colorful and detailed",
            "n": 1,
            "size": "1024x1024"
        }
    )
    response.raise_for_status()
    data = response.json()
    return data['data'][0]['url']

def generate_kitten_fact():
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "user", "content": "Provide a cute and fun fact about kittens."}
        ]
    )
    return response.choices[0].message['content'].strip()

def download_image(image_url, save_path):
    img_data = requests.get(image_url).content
    with open(save_path, 'wb') as handler:
        handler.write(img_data)

def compress_image(image_path, max_size=1000000):
    with Image.open(image_path) as img:
        # Convert to RGB if needed to ensure JPEG compatibility
        if img.mode in ('RGBA', 'P'):  
            img = img.convert('RGB')
        
        # Compress and resize iteratively until the image is under the max size
        img_format = 'JPEG'  # Use JPEG to ensure better compression
        buffer = io.BytesIO()
        quality = 85
        width, height = img.size
        while True:
            buffer.seek(0)
            img.save(buffer, format=img_format, quality=quality)
            size = buffer.tell()
            if size <= max_size or quality <= 10:
                break
            # Reduce quality further if needed
            quality -= 5
            # Resize if quality alone is not enough
            if quality <= 50:
                width = int(width * 0.9)
                height = int(height * 0.9)
                img = img.resize((width, height), Image.ANTIALIAS)
        
        # Save the compressed image
        with open(image_path, 'wb') as f:
            f.write(buffer.getvalue())

        # Final check to ensure it's under max_size
        final_size = os.path.getsize(image_path)
        if final_size > max_size:
            raise Exception(f"Compressed image is still too large: {final_size} bytes")

def upload_file(pds_url, access_token, filename, img_bytes) -> dict:
    suffix = filename.split(".")[-1].lower()
    mimetype = "application/octet-stream"
    if suffix in ["png"]:
        mimetype = "image/png"
    elif suffix in ["jpeg", "jpg"]:
        mimetype = "image/jpeg"
    elif suffix in ["webp"]:
        mimetype = "image/webp"

    resp = requests.post(
        pds_url + "/xrpc/com.atproto.repo.uploadBlob",
        headers={
            "Content-Type": mimetype,
            "Authorization": "Bearer " + access_token,
        },
        data=img_bytes,
    )
    resp.raise_for_status()
    return resp.json()["blob"]

def upload_images(pds_url: str, access_token: str, image_paths: List[str], alt_text: str) -> dict:
    images = []
    for ip in image_paths:
        with open(ip, "rb") as f:
            img_bytes = f.read()
        if len(img_bytes) > 1000000:
            raise Exception(
                f"image file size too large. 1000000 bytes maximum, got: {len(img_bytes)}"
            )
        blob = upload_file(pds_url, access_token, ip, img_bytes)
        images.append({"alt": alt_text or "", "image": blob})
    return {
        "$type": "app.bsky.embed.images",
        "images": images,
    }

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
        download_image(image_url, "generated_kitten.png")
        # Compress the image to ensure it's under 1MB
        compress_image("generated_kitten.png")
        alt_text = "A cute kitten in a playful pose"
        embed = upload_images(pds_url, session["accessJwt"], ["generated_kitten.png"], alt_text)
        post_content = "🐾🐾🐾"
    else:
        # Generate a kitten fun fact
        post_content = generate_kitten_fact()
        embed = None

    # Create a post on Bluesky
    create_bsky_post(session, pds_url, post_content, embed)

if __name__ == "__main__":
    main()
