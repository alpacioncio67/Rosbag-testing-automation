import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()  # Loads FOXGLOVE_TOKEN and MCAP_FOLDER from .env

TOKEN  = os.getenv("FOXGLOVE_TOKEN")
FOLDER = os.getenv("MCAP_FOLDER")


def upload_mcap(path):
    url = "https://api.foxglove.dev/v1/uploads"

    with open(path, "rb") as f:
        files   = {"file": (os.path.basename(path), f, "application/octet-stream")}
        headers = {"Authorization": f"Bearer {TOKEN}"}

        print(f"Uploading {path}...")
        r = requests.post(url, files=files, headers=headers)

    if r.status_code == 200:
        print("✔ Uploaded successfully")
    else:
        print("✖ Error:", r.status_code, r.text)


def watch_folder():
    seen = set()

    while True:
        for f in os.listdir(FOLDER):
            if f.endswith(".mcap"):
                fullpath = os.path.join(FOLDER, f)
                if fullpath not in seen:
                    seen.add(fullpath)
                    upload_mcap(fullpath)
        time.sleep(3)


if __name__ == "__main__":
    watch_folder()
