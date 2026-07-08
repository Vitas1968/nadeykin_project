import os
import sys

# Put src/ first so "from llm import ..." resolves to production llm package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
