import streamlit as st
import base64
from github import Github
from PyPDF2 import PdfReader
import io
from pypdf import PdfWriter

GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
GITHUB_REPO = st.secrets["GITHUB_REPO"]
GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "main")

def extract_text_from_pdf(pdf_bytes):
    pdf_io = io.BytesIO(pdf_bytes)
    reader = PdfReader(pdf_io)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text
    return text

def remove_images_from_pdf(pdf_bytes):
    try:
        input_stream = io.BytesIO(pdf_bytes)
        output_stream = io.BytesIO()
        
        reader = PdfReader(input_stream)
        writer = PdfWriter()

        # Process each page
        for page in reader.pages:
            writer.add_page(page)
            if '/Resources' in page and '/XObject' in page['/Resources']:
                resources = page['/Resources']
                if '/XObject' in resources:
                    resources['/XObject'].clear()

        writer.write(output_stream)
        processed_bytes = output_stream.getvalue()
        
        # Clean up
        input_stream.close()
        output_stream.close()
        
        return processed_bytes
    except Exception as e:
        st.error(f"Image removal error: {str(e)}")
        return pdf_bytes

def upload_to_github(file_bytes, filename):
    try:
        # Initialize Github
        g = Github(GITHUB_TOKEN)
        
        # Get repository (full name including owner)
        repo = g.get_repo(GITHUB_REPO)
        
        # Ensure pdfs directory exists
        try:
            repo.get_contents("pdfs", ref=GITHUB_BRANCH)
        except:
            # Create pdfs directory if it doesn't exist
            repo.create_file("pdfs/.gitkeep", "Create pdfs directory", "", branch=GITHUB_BRANCH)
        
        # Encode content
        content = base64.b64encode(file_bytes).decode()
        
        # Full path to file
        file_path = filename
        
        try:
            # Try to get existing file
            file = repo.get_contents(file_path, ref=GITHUB_BRANCH)
            # Update existing file
            repo.update_file(
                file_path,
                f"Update {filename}",
                content,
                file.sha,
                branch=GITHUB_BRANCH
            )
            return True, "File updated successfully"
        except Exception as e:
            if "404" in str(e):
                # Create new file
                repo.create_file(
                    file_path,
                    f"Add {filename}",
                    content,
                    branch=GITHUB_BRANCH
                )
                return True, "File uploaded successfully"
            else:
                raise e
                
    except Exception as e:
        st.error(f"GitHub error details: {str(e)}")
        return False, f"Upload failed: {str(e)}"

def main():
    st.title("PDF Upload and Text Extraction")
    
    # Test GitHub connection
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        st.info(f"Connected to repository: {GITHUB_REPO} ({GITHUB_BRANCH} branch)")
    except Exception as e:
        st.error(f"GitHub connection failed: {str(e)}")
        return
    
    uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")
    
    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Upload to GitHub")
            if st.button("Upload to GitHub"):
                try:
                    with st.spinner("Processing PDF..."):
                        # Remove images
                        processed_file_bytes = remove_images_from_pdf(file_bytes)
                        
                    with st.spinner("Uploading to GitHub..."):
                        # Upload to GitHub
                        success, message = upload_to_github(
                            processed_file_bytes,
                            f"pdfs/{uploaded_file.name}"
                        )
                        
                    if success:
                        st.success(message)
                    else:
                        st.error(message)
                        
                except Exception as e:
                    st.error(f"Error: {str(e)}")
        
        with col2:
            st.subheader("Extract Text")
            if st.button("Extract Text"):
                with st.spinner("Extracting text..."):
                    text = extract_text_from_pdf(file_bytes)
                    st.text_area("Extracted Text", text, height=300)

if __name__ == "__main__":
    main()
