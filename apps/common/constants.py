"""Shared validation constants."""

import re

# Module and topic codes become directory and file names on disk, so they are
# restricted to a slug shape. This also removes any chance of a `..` segment
# escaping the uploads tree.
CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

CODE_PATTERN_MESSAGE = (
    "code faqat harf, raqam, nuqta, pastki chiziq va defisdan iborat bo'lishi "
    "va harf yoki raqam bilan boshlanishi kerak"
)

ALLOWED_UPLOAD_EXTENSIONS = frozenset({".pdf", ".pptx", ".docx", ".txt", ".md"})
