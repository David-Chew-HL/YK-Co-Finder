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
    input_stream = io.BytesIO(pdf_bytes)
    output_stream = io.BytesIO()
    
    reader = PdfReader(input_stream)
    writer = PdfWriter()

    for page_num, page in enumerate(reader.pages):
        try:
            # Add the page to the writer
            writer.add_page(page)
            resources = page.get("/Resources", {})
            xobjects = resources.get("/XObject", {})

            # Remove images if any are present in the XObject dictionary
            if xobjects:
                xobjects_obj = xobjects.get_object()
                for obj_key in list(xobjects_obj.keys()):
                    obj = xobjects_obj[obj_key]
                    if obj.get("/Subtype") == "/Image":
                        del xobjects_obj[obj_key]

        except Exception as e:
            st.warning(f"Error processing page {page_num}: {e}")

    writer.write(output_stream)
    return output_stream.getvalue()

def upload_to_github(file_bytes, filename):
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO.split('/')[-1])
        
        # Encode the file content
        content = base64.b64encode(file_bytes).decode()
        
        # Check if the file exists in the repository
        try:
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
            if "404" in str(e):
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
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        st.info(f"Connected to repository: {GITHUB_REPO} ({GITHUB_BRANCH} branch)")
    except Exception as e:
        st.error(f"Failed to connect to GitHub: {str(e)}")
        return
    
    uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")
    
    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        
        try:
            processed_file_bytes = remove_images_from_pdf(file_bytes)
            st.success("Images removed successfully")
        except Exception as e:
            st.error(f"Error removing images: {str(e)}")
            processed_file_bytes = file_bytes

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
