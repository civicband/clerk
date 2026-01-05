"""Sphinx configuration for clerk documentation."""

import os
import sys

# Add src directory to path for autodoc
sys.path.insert(0, os.path.abspath("../src"))

# Project information
project = "clerk"
author = "Philip James"
copyright = "2026, Philip James"
release = "0.0.1"

# General configuration
extensions = [
    "myst_parser",  # Markdown support
    "sphinx.ext.autodoc",  # Auto API docs
    "sphinx.ext.napoleon",  # Google/NumPy docstrings
    "sphinx.ext.viewcode",  # Source code links
    "sphinx_autodoc_typehints",  # Type hint support
]

# MyST parser configuration
myst_enable_extensions = [
    "colon_fence",  # ::: fences
    "deflist",  # Definition lists
    "linkify",  # Auto-link URLs
]

# Templates and static files
templates_path = ["_templates"]
html_static_path = ["_static"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# HTML output configuration
html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "navigation_depth": 4,
    "collapse_navigation": False,
}

# Autodoc configuration
autodoc_default_options = {
    "members": True,
    "show-inheritance": True,
    "undoc-members": True,
}

# Napoleon settings for docstring parsing
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
