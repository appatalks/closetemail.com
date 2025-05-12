import os
import random
import requests
import base64
from openai import OpenAI
from datetime import datetime, timezone
from typing import List
from PIL import Image
import io
import subprocess

def bsky_login_session(pds_url: str, handle: str, password: str):
    # https://docs.bsky.app/docs/get-started#create-a-session
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

def generate_puppy_image():
    # Update to modern gpt-image-1 endpoint
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    prompt = (
        "Create an image of a dog or puppies that is creative and unique with a Summer Time theme with Summer fun activities. "
        "Choose a random art style, such as photo realistic, surrealism, realism, anime, 1970 cartoon, modern cartoon, watercolor, abstract, black and white or digital painting. "
        "Choose a random setting like fantasy worlds, cityscapes, steam punk, lush forests, outerspace or imaginative places. "
        "Let the puppies be doing anything from playing to resting, exploring, or interacting in surprising ways."
    )

    result = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1024",  # Default size, adjust if necessary
        quality="medium"   
    )
    
    # Extract base64 image data and decode it
    image_base64 = result.data[0].b64_json
    image_bytes = base64.b64decode(image_base64)
    
    # Save image to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"generated/images/generated_puppy_{timestamp}.png"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "wb") as f:
        f.write(image_bytes)
    
    # Compress the image to ensure it's under 1MB for Bluesky
    compress_image(output_file)
    
    return output_file

def generate_puppy_fact():
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an artist and a poet. You like to give fun, quick, quirky and little-known facts about puppies and dogs."},
            {"role": "user", "content": "Tell me something interesting about puppies in one short sentance."}
        ]
    )
    
    # Directly access the 'content' attribute of the message
    fact = response.choices[0].message.content
    return fact

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
        headers={"Content-Type": mimetype, "Authorization": "Bearer " + access_token},
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

def push_image_to_branch(image_path):
    branch_name = "generated"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    commit_message = f"Add generated puppy image {timestamp}"

    # Set Git user information for Actions
    subprocess.run(["git", "config", "--global", "user.email", "actions@github.com"])
    subprocess.run(["git", "config", "--global", "user.name", "GitHub Actions"])

    # Ensure the branch is updated before attempting to push
    subprocess.run(["git", "fetch", "origin", branch_name])
    subprocess.run(["git", "checkout", "-B", branch_name])
    subprocess.run(["git", "reset", "--hard", f"origin/{branch_name}"])
    subprocess.run(["git", "pull", "origin", branch_name, "--rebase"])

    # Add, commit, and push the changes
    subprocess.run(["git", "add", image_path])
    subprocess.run(["git", "commit", "-m", commit_message])
    subprocess.run(["git", "push", "origin", branch_name, "--force"])
        
def main():
    pds_url = "https://bsky.social"
    handle = os.getenv("BLUESKY_PUPPIES_H")
    password = os.getenv("BLUESKY_PUPPIES_P")

    # Log in to Bluesky
    session = bsky_login_session(pds_url, handle, password)

    # Randomly decide whether to post an image or a fun fact
    if random.choice([True, False]):
        # Generate a puppy image
        image_path = generate_puppy_image()
        alt_text = "A cute puppy in a playful pose"
        embed = upload_images(pds_url, session["accessJwt"], [image_path], alt_text)
        post_content = "🐾🐾 puppies and dogs 🐾🐾 #puppies #dogs"
        # Push image to generated branch
        push_image_to_branch(image_path)
    else:
        # Generate a puppy fun fact
        image_path = generate_puppy_image()
        alt_text = "A cute puppy in a playful pose"
        embed = upload_images(pds_url, session["accessJwt"], [image_path], alt_text)
        post_content = "🐾🐾 puppies and dogs 🐾🐾 #puppies #dogs"
        push_image_to_branch(image_path)

    # Create a post on Bluesky
    create_bsky_post(session, pds_url, post_content, embed)

if __name__ == "__main__":
    main()
