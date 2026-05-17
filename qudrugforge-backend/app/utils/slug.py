import re

def generate_slug(name: str) -> str:
    """
    Generates a clean slug from a string name.
    """
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', name).strip('-').lower()
    return slug or "project"
