import os
import uuid
import requests

from dotenv import load_dotenv

load_dotenv()


def download_resume(resume_url: str) -> str:
    """
    Download resume from URL and save it to uploads directory with a unique ID.
    Returns the local file path.
    """
    try:
        # Create uploads directory if it doesn't exist
        # Go up from utils directory to server directory, then to uploads
        server_dir = os.path.dirname(os.path.dirname(__file__))
        uploads_dir = os.path.join(server_dir, "uploads")
        os.makedirs(uploads_dir, exist_ok=True)

        # Generate unique ID for the file
        file_id = str(uuid.uuid4())

        # Get file extension from URL or default to .pdf
        if resume_url.lower().endswith(".pdf"):
            file_ext = ".pdf"
        elif resume_url.lower().endswith(".doc"):
            file_ext = ".doc"
        elif resume_url.lower().endswith(".docx"):
            file_ext = ".docx"
        else:
            file_ext = ".pdf"  # Default to PDF

        # Create local file path
        local_filename = f"{file_id}{file_ext}"
        local_path = os.path.join(uploads_dir, local_filename)

        # Download the file
        response = requests.get(resume_url, timeout=30)
        response.raise_for_status()

        # Save the file
        with open(local_path, "wb") as f:
            f.write(response.content)

        print(f"✅ Resume downloaded: {local_path}")
        return local_path

    except Exception as e:
        print(f"❌ Failed to download resume: {str(e)}")
        raise


def cleanup_resume(file_path: str):
    """
    Delete the resume file after processing.
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"🗑️  Resume file cleaned up: {file_path}")
    except Exception as e:
        print(f"⚠️  Failed to cleanup resume file: {str(e)}")

