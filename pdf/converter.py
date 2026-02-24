import sys
import pdfplumber
from PIL import Image
from typing import List
from pathlib import Path

def convert_pdf_to_images(pdf_path: Path) -> List[Image.Image]:
    """
    Converts each page of a PDF file into a PIL Image.
    Returns a list of PIL Images.
    """
    images = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                p_image = page.to_image(resolution=150)
                images.append(p_image.original)
    except Exception as e:
        sys.stderr.write(f"Error converting PDF to images: {e}\n")
        # Return whatever we managed to collect or empty list

    return images
