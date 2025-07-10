import zipfile
import os
import shutil
import re
import sys
import traceback
import pytesseract # Make sure pytesseract is imported for the Tesseract check


from func_to_import import (
    remove_undesired_patterns,
    remove_pdf_metadata,
    redact_pdf_content,
    extract_text_from_pdf,
    REDACTION_PATTERNS,
    IS_CASE_SENSITIVE_PDF_REDACTION
)

def process_zip_file_workflow(zip_file_path, output_base_dir="processed_output"):
    """
    Orchestrates the entire process of handling a ZIP file containing PDFs:
    1. Extracts PDFs.
    2. Removes metadata from PDFs using func_import.remove_pdf_metadata.
    3. Redacts specified content (headers, footers, and patterns) from PDFs
       using func_import.redact_pdf_content.
    4. Extracts text from redacted PDFs using OCR via func_import.extract_text_from_pdf.
    5. Cleans up extracted text using func_import.remove_undesired_patterns.
    6. Saves the cleaned text to a .txt file.
    """
    # Create necessary output directories
    os.makedirs(output_base_dir, exist_ok=True)
    extracted_pdf_dir = os.path.join(output_base_dir, "extracted_pdfs")
    os.makedirs(extracted_pdf_dir, exist_ok=True)
    redacted_pdf_dir = os.path.join(output_base_dir, "redacted_pdfs")
    os.makedirs(redacted_pdf_dir, exist_ok=True)
    text_output_dir = os.path.join(output_base_dir, "text_output")
    os.makedirs(text_output_dir, exist_ok=True)

    try:
        if not os.path.exists(zip_file_path):
            print(f"ERROR: ZIP file not found at '{zip_file_path}'")
            return False

        with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
            pdf_files_in_zip = []
            for member in zip_ref.namelist():
                if member.lower().endswith(".pdf"):
                    # Extract PDF to a temporary location for initial processing
                    extracted_path = os.path.join(extracted_pdf_dir, os.path.basename(member))
                    os.makedirs(os.path.dirname(extracted_path), exist_ok=True) # Ensure directory exists
                    
                    with zip_ref.open(member) as source, open(extracted_path, 'wb') as target:
                        shutil.copyfileobj(source, target)
                    pdf_files_in_zip.append(extracted_path)
                    print(f"INFO: Extracted PDF: {os.path.basename(member)}")

            if not pdf_files_in_zip:
                print(f"WARNING: No PDF files found in '{os.path.basename(zip_file_path)}'.")
                return False

            for pdf_path in pdf_files_in_zip:
                base_name = os.path.basename(pdf_path)
                print(f"\n--- Processing '{base_name}' ---")

                # Step 1: Remove PDF metadata (in-place modification)
                print("INFO: Step 1: Removing PDF metadata...")
                metadata_removed = remove_pdf_metadata(pdf_path) # Call from func_import
                if not metadata_removed:
                    print(f"ERROR: Failed to remove metadata from '{base_name}'. Skipping further processing for this PDF.")
                    continue

                # Step 2: Redact PDF content (outputs a new redacted PDF)
                redacted_pdf_path = os.path.join(redacted_pdf_dir, f"redacted_{base_name}")
                print("INFO: Step 2: Redacting PDF content (headers, footers, and specified patterns)...")
                # Use the imported REDACTION_PATTERNS and IS_CASE_SENSITIVE_PDF_REDACTION
                redacted = redact_pdf_content(pdf_path, redacted_pdf_path, REDACTION_PATTERNS, IS_CASE_SENSITIVE_PDF_REDACTION) # Call from func_import
                if not redacted:
                    print(f"ERROR: Failed to redact '{base_name}'. Skipping further processing for this PDF.")
                    continue

                # Step 3: Extract text from redacted PDF using OCR
                print("INFO: Step 3: Extracting text from redacted PDF using OCR...")
                extracted_text = extract_text_from_pdf(redacted_pdf_path) # Call from func_import
                if not extracted_text:
                    print(f"ERROR: Failed to extract text from '{os.path.basename(redacted_pdf_path)}'.")
                    continue

                # Step 4: Further cleanup of extracted text (e.g., remove "uptodate" variations)
                print("INFO: Step 4: Performing text-level cleanup (e.g., removing 'uptodate')...")
                cleaned_text = remove_undesired_patterns(extracted_text) # Call from func_import

                # Step 5: Save the cleaned text to a .txt file
                output_txt_file = os.path.join(text_output_dir, f"{os.path.splitext(base_name)[0]}.txt")
                with open(output_txt_file, 'w', encoding='utf-8') as f:
                    f.write(cleaned_text)
                print(f"INFO: Successfully processed and saved text for '{base_name}' to '{os.path.basename(output_txt_file)}'.")

        print(f"INFO: All PDFs from '{os.path.basename(zip_file_path)}' processed successfully!")
        return True

    except zipfile.BadZipFile:
        print(f"ERROR: '{os.path.basename(zip_file_path)}' is not a valid ZIP file.")
        return False
    except Exception as e:
        print(f"ERROR: An unexpected error occurred during processing: {e}")
        traceback.print_exc() # Print full traceback for unexpected errors
        return False
    finally:
        # Optional: Clean up the extracted_pdfs and redacted_pdfs directories if you don't need them for debugging
        # if os.path.exists(extracted_pdf_dir):
        #     shutil.rmtree(extracted_pdf_dir)
        # if os.path.exists(redacted_pdf_dir):
        #     shutil.rmtree(redacted_pdf_dir)
        pass

if __name__ == "__main__":

    # Get ZIP file path from user input
    zip_file_input = input("Enter the path to your ZIP file containing PDFs: ").strip()
    output_folder_name = input("Enter a name for the output folder (e.g., 'my_processed_docs'): ").strip()

    if not zip_file_input:
        print("ERROR: No ZIP file path provided. Exiting.")
        sys.exit(1)
    if not output_folder_name:
        print("WARNING: No output folder name provided. Using 'processed_output' as default.")
        output_folder_name = "processed_output"

    full_output_path = os.path.join(os.getcwd(), output_folder_name)

    print(f"INFO: Attempting to process '{zip_file_input}' and save results to '{full_output_path}'")

    # Before starting the main workflow, check if Tesseract is available
    try:
        tesseract_version = pytesseract.get_tesseract_version()
        print(f"INFO: Tesseract OCR found and accessible. Version: {tesseract_version}")
    except pytesseract.TesseractNotFoundError:
        print("ERROR: Tesseract OCR is not installed or not in your system's PATH.")
        print("Please install Tesseract OCR (https://tesseract-ocr.github.io/tessdoc/Installation.html) and ensure it's accessible.")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: An unexpected error occurred while checking Tesseract: {e}")
        traceback.print_exc()
        sys.exit(1)

    print("\n--- Starting PDF Processing Workflow ---")
    success = process_zip_file_workflow(zip_file_input, output_base_dir=full_output_path)

    if success:
        print("\n--- Processing completed successfully! ---")
        print(f"Output files can be found in the directory: {os.path.abspath(full_output_path)}")
        print(f"  - Extracted PDFs (metadata removed): '{output_folder_name}/extracted_pdfs'")
        print(f"  - Redacted PDFs: '{output_folder_name}/redacted_pdfs'")
        print(f"  - Final text outputs: '{output_folder_name}/text_output'")
    else:
        print("\n--- Processing failed. Please check the messages above for details. ---")
