import re
import os
import shutil
import PyPDF2
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import traceback # Keep traceback for printing detailed errors

# Define patterns for redaction (these can also be defined in the main file
# and passed, but for now, keeping them here as they are directly used by redact_pdf_content)
# NOTE: The order of patterns can sometimes matter for overlapping matches.
# It's generally good practice to put more specific/longer patterns first.
REDACTION_PATTERNS = [
    "Ref",
    "Use of UpToDate is subject to the Terms of Use",
    "2025© UpToDate, Inc. and its affiliates and/or licensors. All Rights Reserved",
    'show table',
    'Contributor Disclosures',
    "For abbreviations, symbols, and age group definitions",
    "Use of UpToDate is subject to the Terms of Us\"", # Typo here, kept as provided
    # General citation-like patterns, often found in medical docs
    re.compile(r"\b\([A-Za-z]+\s+\d{4}(?:[,;]\s*[A-Za-z]+\s+\d{4})*\)\b", re.IGNORECASE | re.UNICODE),

    # Patterns for visible text "metadata" like author/editor info
    re.compile(r"AUTHORS:.*?(?:\n|$)", re.IGNORECASE),
    re.compile(r"SECTION EDITOR:.*?(?:\n|$)", re.IGNORECASE),
    re.compile(r"DEPUTY EDITOR:.*?(?:\n|$)", re.IGNORECASE),
    re.compile(r"CONTRIBUTOR DISCLOSURES.*?(?:\n|$)", re.IGNORECASE),
    re.compile(r"INTRODUCTION.*?(?:\n|$)", re.IGNORECASE),
    re.compile(r"All topics are updated as new evidence becomes available and our peer review process is complete", re.IGNORECASE),
    re.compile(r"This topic last updated: (?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}, \d{4}\.", re.IGNORECASE),
    re.compile(r"Literature review current through:.*?(?:\n|$)", re.IGNORECASE),
    re.compile(r"Topic \d+ Version \d+\.\d+", re.IGNORECASE),
    re.compile(r"ACKNOWLEDGMENT.*?prior versions of this topic review\.", re.IGNORECASE | re.DOTALL),
    re.compile(r"UpToDate is a registered trademark of UpToDate, Inc. All rights reserved.", re.IGNORECASE)
]

# Flag to control case-sensitivity for redaction
IS_CASE_SENSITIVE_PDF_REDACTION = False


def remove_undesired_patterns(text):
    """
    Removes:
    1. Lines containing "Copyright ©" followed by digits,
        the line immediately before, and the line immediately after.
    2. The word "uptodate" and its variations (case-insensitive).
    This is a text-level cleanup, applied after extraction.
    """
    lines = text.split('\n')
    output_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Regex to find "Copyright ©" followed by digits (year)
        # This is a text-level cleanup, useful if redaction missed or for other sources.
        if re.search(r"Copyright ©\s*\d{4}", line, re.IGNORECASE):
            # Check if the previous line exists and is the same as the last appended line, then remove it
            # This logic might need refinement depending on exact desired behavior for surrounding lines.
            if output_lines and i > 0 and (i - 1 < len(lines) and lines[i-1] == output_lines[-1]):
                output_lines.pop()

            i += 2 # Skip current line (copyright) and the one after
        else:
            # Remove "uptodate" and its variations (case-insensitive)
            cleaned_line = re.sub(r'\b[Uu][Pp][Tt][Oo][Dd][Aa][Tt][Ee]\b', '', line)
            output_lines.append(cleaned_line)
        i += 1
    return "\n".join(output_lines)

def remove_pdf_metadata(file_path):
    """
    Removes metadata from a PDF file using PyPDF2.
    Modifies the file in-place (by writing to a temp and replacing).
    """
    try:
        reader = PyPDF2.PdfReader(file_path)
        writer = PyPDF2.PdfWriter()

        for page in reader.pages:
            writer.add_page(page)

        # Add empty metadata to effectively remove existing metadata
        writer.add_metadata({})
        temp_path = file_path.replace(".pdf", "_temp_metadata_stripped.pdf")

        with open(temp_path, 'wb') as f:
            writer.write(f)

        # Replace the original file with the metadata-stripped one
        os.replace(temp_path, file_path)
        print(f"INFO: Metadata successfully removed from: '{os.path.basename(file_path)}'")
        return True
    except Exception as e:
        print(f"ERROR: Error while removing metadata from '{os.path.basename(file_path)}': {e}")
        traceback.print_exc()
        return False

def redact_pdf_content(input_pdf_path, output_pdf_path, words_and_patterns_to_redact, case_sensitive=False):
    """
    Redacts specific content (headers, footers, and defined words/patterns) from a PDF file.
    Saves the redacted PDF to a new output path.
    """
    print(f"INFO: Attempting redaction for '{os.path.basename(input_pdf_path)}'...")

    if not os.path.exists(input_pdf_path):
        print(f"ERROR: Input PDF not found for redaction: '{os.path.basename(input_pdf_path)}'")
        return False

    try:
        doc = fitz.open(input_pdf_path)
        total_redactions = 0

        # Prepare patterns: convert all to regex strings for search_for
        search_patterns = []
        for item in words_and_patterns_to_redact:
            pattern_string = ""
            current_flags = 0 if case_sensitive else re.IGNORECASE

            if isinstance(item, str):
                # Escape the string and add case-insensitivity flag if needed
                pattern_string = re.escape(item)
            elif isinstance(item, re.Pattern):
                # Get the pattern string from the compiled regex
                pattern_string = item.pattern
                # Ensure the case_sensitive flag is respected, otherwise add IGNORECASE
                if not case_sensitive and not (item.flags & re.IGNORECASE):
                    current_flags |= re.IGNORECASE
                # Also include other relevant flags from the compiled pattern, like DOTALL, MULTILINE, UNICODE
                current_flags |= (item.flags & (re.DOTALL | re.MULTILINE | re.UNICODE))
            else:
                print(f"WARNING: Skipping invalid redaction pattern type: {item}")
                continue
            
            # Embed regex flags into the pattern string for PyMuPDF's search_for
            # E.g., "(?i)pattern" for case-insensitive, "(?s)" for dotall
            flag_str = ""
            if current_flags & re.IGNORECASE: flag_str += "i"
            if current_flags & re.DOTALL: flag_str += "s"
            if current_flags & re.MULTILINE: flag_str += "m"
            if current_flags & re.UNICODE: flag_str += "u" # PyMuPDF often expects Unicode, but explicitly adding for clarity

            if flag_str:
                search_patterns.append(f"(?{flag_str}){pattern_string}")
            else:
                search_patterns.append(pattern_string)


        for page_num in range(doc.page_count):
            page = doc.load_page(page_num)
            page_width = page.rect.width
            page_height = page.rect.height

            # Redact fixed areas (header and footer)
            header_height = 70
            footer_height = 70
            header_rect = fitz.Rect(0, 0, page_width, header_height)
            footer_rect = fitz.Rect(0, page_height - footer_height, page_width, page_height)

            page.add_redact_annot(header_rect, text="", fill=(0, 0, 0)) # Redact with black fill
            page.add_redact_annot(footer_rect, text="", fill=(0, 0, 0))
            total_redactions += 2

            # Redact specific text patterns
            text_instances_found = []
            for s_pattern in search_patterns:
                try:
                    # Pass the regex string directly, and then PyMuPDF's flags
                    # This should resolve the 'argument 2 of type char const *' error
                    # by ensuring the first argument is always a string.
                    text_instances_found.extend(page.search_for(s_pattern, flags=fitz.TEXT_PRESERVE_WHITESPACE))
                except Exception as e:
                    print(f"ERROR: Internal PyMuPDF search error for pattern '{s_pattern}' on page {page_num + 1} of '{os.path.basename(input_pdf_path)}': {e}")
                    # Log the full traceback for more detail
                    traceback.print_exc()
                    # Continue with other patterns/pages rather than failing the whole file
                    continue 

            # Consolidate and apply redactions
            redaction_rects = sorted([inst for inst in text_instances_found], key=lambda r: (r.y0, r.x0))

            for rect in redaction_rects:
                # Only redact if not intersecting with already redacted header/footer
                if not header_rect.intersects(rect) and not footer_rect.intersects(rect):
                    page.add_redact_annot(rect, text="", fill=(0, 0, 0))
                    total_redactions += 1

            # Apply redactions to the page
            page.apply_redactions()

        if total_redactions > 0:
            doc.save(output_pdf_path, garbage=4, deflate=True)
            doc.close()
            print(f"INFO: Successfully applied {total_redactions} redaction(s) and saved redacted PDF to '{os.path.basename(output_pdf_path)}'.")
            return True
        else:
            doc.close()
            shutil.copy(input_pdf_path, output_pdf_path)
            print(f"WARNING: No specific content or fixed area redactions applied for '{os.path.basename(input_pdf_path)}'. Copied original.")
            return True
    except Exception as e:
        print(f"ERROR: Error during redaction of '{os.path.basename(input_pdf_path)}': {e}")
        traceback.print_exc()
        return False

def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extracts text from a PDF file using PyMuPDF and compulsory OCR via Tesseract.
    Returns raw extracted text. Cleanup (remove_undesired_patterns) happens later.
    """
    text = ""
    try:
        doc = fitz.open(pdf_path)
        for page_num, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) # Increase resolution for better OCR
            
            if pix.n == 1:
                mode = "L"
            elif pix.n == 3:
                mode = "RGB"
            elif pix.n == 4:
                mode = "RGBA"
            else:
                print(f"WARNING: Unsupported number of color channels ({pix.n}) in PDF page {page_num+1} of '{os.path.basename(pdf_path)}'. Skipping OCR for this page.")
                continue
            
            img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
            
            # Use a higher DPI for Tesseract for potentially better accuracy
            page_text = pytesseract.image_to_string(img, config='--psm 3 --dpi 300') # PSM 3 for automatic page segmentation
            text += page_text + "\n"
        doc.close()

    except Exception as e:
        print(f"ERROR: Error extracting text from PDF '{os.path.basename(pdf_path)}' using OCR: {e}. Ensure Tesseract OCR is installed and configured correctly (e.g., added to system PATH).")
        traceback.print_exc() # Use traceback.print_exc() for full stack trace
        return ""
    return text