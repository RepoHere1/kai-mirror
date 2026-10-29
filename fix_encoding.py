import re

# Fix encoding issues in HTML files
replacements = {
    'â€"': '—',      # em dash
    'â€¦': '…',      # ellipsis
    'Â·': '·',       # middle dot
    'â€™': "'",       # apostrophe
    'â€œ': '"',       # opening quote
    'â€': '"',        # closing quote
    'â€': '"',        # closing quote (alt)
    'Â': '',          # stray
    'â€"': '—',      # em dash (alt)
    'â€ ': '— ',     # em dash with space
    'â€œ': '"',       # opening quote
    'â€š': "'",       # single quote
    'â€˜': "'",       # single quote
}

files = [
    'all-no-markets.html',
    'dry-home.html',
    'dry_home.html',
    'live-home.html',
    'live_home.html',
]

for fname in files:
    path = f'C:\\Users\\darri\\Kai-Mirror\\{fname}'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original = content
        for bad, good in replacements.items():
            content = content.replace(bad, good)
        
        if content != original:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Fixed: {fname}")
        else:
            print(f"No changes: {fname}")
    except Exception as e:
        print(f"Error {fname}: {e}")

print("Done!")