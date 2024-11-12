import streamlit as st
import base64
from github import Github
from PyPDF2 import PdfReader
import io
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# GitHub configuration from environment variables
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO')
GITHUB_BRANCH = os.getenv('GITHUB_BRANCH', 'main')  # Default to 'main' if not specified

def extract_text_from_pdf(pdf_bytes):
    """Extract text from PDF bytes."""
    pdf_io = io.BytesIO(pdf_bytes)
    reader = PdfReader(pdf_io)
    text = ""
    for page in reader.pages:
        text += page.extract_text()
    return text

def upload_to_github(file_bytes, filename):
    """Upload file to GitHub repository."""
    try:
        # Initialize GitHub instance
        g = Github(GITHUB_TOKEN)
        repo = g.get_user().get_repo(GITHUB_REPO)
        
        # Encode content
        content = base64.b64encode(file_bytes).decode()
        
        try:
            # Try to get the file first
            file = repo.get_contents(filename, ref=GITHUB_BRANCH)
            repo.update_file(
                filename,
                f"Update {filename}",
                content,
                file.sha,
                branch=GITHUB_BRANCH
            )
            return True, "File updated successfully"
        except:
            # File doesn't exist, create it
            repo.create_file(
                filename,
                f"Add {filename}",
                content,
                branch=GITHUB_BRANCH
            )
            return True, "File uploaded successfully"
    except Exception as e:
        return False, str(e)

def main():
    st.title("PDF Upload and Text Extraction")
    
    # Show configuration status
    if not GITHUB_TOKEN or not GITHUB_REPO:
        st.error("GitHub configuration is missing. Please check your environment variables.")
        return
    
    st.info(f"Connected to repository: {GITHUB_REPO} ({GITHUB_BRANCH} branch)")
    
    # File uploader
    uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")
    
    if uploaded_file is not None:
        # Read file bytes
        file_bytes = uploaded_file.getvalue()
        
        # Create two columns
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Upload to GitHub")
            if st.button("Upload to GitHub"):
                with st.spinner("Uploading to GitHub..."):
                    success, message = upload_to_github(
                        file_bytes,
                        f"pdfs/{uploaded_file.name}"
                    )
                    if success:
                        st.success(message)
                    else:
                        st.error(f"Upload failed: {message}")
        
        with col2:
            st.subheader("Extract Text")
            if st.button("Extract Text"):
                with st.spinner("Extracting text..."):
                    text = extract_text_from_pdf(file_bytes)
                    st.text_area("Extracted Text", text, height=300)

if __name__ == "__main__":
    main()
