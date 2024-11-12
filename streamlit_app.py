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
        text += page.extract_text()
    return text

def remove_images_from_pdf(pdf_bytes):
    try:
        input_stream = io.BytesIO(pdf_bytes)
        output_stream = io.BytesIO()
        
        reader = PdfReader(input_stream)
        writer = PdfWriter()

        for page in reader.pages:
            clean_page = page
            
            if '/Resources' in clean_page:
                resources = clean_page['/Resources']
   
                if '/XObject' in resources:
                    del resources['/XObject']

                if hasattr(clean_page, '/Contents'):
                    content = clean_page['/Contents']
                    if isinstance(content, list):
                        for obj in content:
                            if hasattr(obj, 'get_object'):
                                obj = obj.get_object()
                    elif hasattr(content, 'get_object'):
                        content = content.get_object()
  
                for key in list(resources.keys()):
                    if key.startswith('/Im'):
                        del resources[key]

                if '/Forms' in resources:
                    del resources['/Forms']
            
            writer.add_page(clean_page)

            writer.add_compression(compress_streams=True)

        writer.write(output_stream)
    
        processed_pdf_bytes = output_stream.getvalue()
        input_stream.close()
        output_stream.close()
        
        return processed_pdf_bytes
        
    except Exception as e:
        raise Exception(f"Error processing PDF: {str(e)}")


def upload_to_github(file_bytes, filename):

    try:
        g = Github(GITHUB_TOKEN)
        
        # Get authenticated user and repository
        user = g.get_user()
        repo = user.get_repo(GITHUB_REPO.split('/')[-1])  # Get repo name without owner
        
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
        except Exception as e:
            if "404" in str(e):  # File doesn't exist
                # Create new file
                repo.create_file(
                    filename,
                    f"Add {filename}",
                    content,
                    branch=GITHUB_BRANCH
                )
                return True, "File uploaded successfully"
            else:
                raise e
    except Exception as e:
        return False, f"Error: {str(e)}"

def main():
    st.title("PDF Upload and Text Extraction")
    
    try:
        # Test GitHub connection
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        st.info(f"Connected to repository: {GITHUB_REPO} ({GITHUB_BRANCH} branch)")
    except Exception as e:
        st.error(f"Failed to connect to GitHub: {str(e)}")
        return
    
    uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")
    
    if uploaded_file is not None:
        # Read the original file bytes
        
        
        try:
            processed_file = remove_images_from_pdf(uploaded_file)
            processed_file_bytes = uploaded_file.getvalue()
            st.success("Images removed successfully")
        except Exception as e:
            st.error(f"Error removing images: {str(e)}")
            processed_file_bytes = uploaded_file.getvalue()

        #two columns
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Upload to GitHub")
            if st.button("Upload to GitHub"):
                with st.spinner("Uploading to GitHub..."):
                    success, message = upload_to_github(
                        processed_file_bytes,
                        f"pdfs/{uploaded_file.name}"
                    )
                    if success:
                        st.success(message)
                    else:
                        st.error(message)
        
        with col2:
            st.subheader("Extract Text")
            if st.button("Extract Text"):
                with st.spinner("Extracting text..."):
                    text = extract_text_from_pdf(processed_file_bytes)
                    st.text_area("Extracted Text", text, height=300)

if __name__ == "__main__":
    main()
