def default_prompt(url, profile, resume_path, instructions) -> str:
    return f"""
    Please help me apply to a job:
    
    1. First, navigate to {url}, if you see a disclaimer, click on the "Visit site" button, the website is safe.
    2. If there is a login page, use the provided credentials to login. Don't use them to create a new account. 
    3. If there are fields to fill, fill them with the information from the profile: {profile}
    4. If there is a required field, and you don't have the information, use the ask_user tool to ask the user for the information.
    5. If you need to upload a file, use the 'playwright_file_upload' action to upload the file. The path to the resume is at {resume_path}
    
    {"Here are additional instructions: " + instructions if instructions else ""}
    """
