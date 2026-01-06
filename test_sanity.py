# Minimal sanity test (no browser): checks imports + keyword extraction
import spacy
from app import extract_keywords

text = "The Roman Empire conquered Gaul. Julius Caesar led the army. Rome expanded across Europe."
keywords = extract_keywords(text, max_keywords=10)
print("KEYWORDS:", keywords)

assert "roman" in keywords or "empire" in keywords or "rome" in keywords
print("OK")
