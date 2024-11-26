import hashlib
import os

API_KEY_FILE = "api_key.txt"  # File to store the hashed API key

def hash_api_key(api_key):
    """Hash the API key using SHA-256."""
    return hashlib.sha256(api_key.encode()).hexdigest()

def save_hashed_api_key(api_key):
    """Save the hashed API key to a file."""
    
    with open(API_KEY_FILE, "w") as file:
        file.write(api_key)
    print("API key hashed and saved.")

def load_hashed_api_key():
    """Load the hashed API key from the file if it exists."""
    if os.path.exists(API_KEY_FILE):
        with open(API_KEY_FILE, "r") as file:
            return file.read().strip()
    return None