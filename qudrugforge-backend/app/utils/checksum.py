import hashlib

def calculate_sha256(file_path_or_bytes) -> str:
    """
    Computes the SHA256 checksum of a file given its path or raw bytes.
    """
    sha256 = hashlib.sha256()
    
    if isinstance(file_path_or_bytes, bytes):
        sha256.update(file_path_or_bytes)
        return sha256.hexdigest()
        
    # Treat as file path
    with open(file_path_or_bytes, "rb") as f:
        while chunk := f.read(1024 * 64): # 64KB chunks
            sha256.update(chunk)
            
    return sha256.hexdigest()
