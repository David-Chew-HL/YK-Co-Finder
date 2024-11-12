import streamlit as st
import base64
from github import Github
from PyPDF2 import PdfReader
import io
from pypdf import PdfWriter
import tempfile
import os

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

        for page in reader.pages:
            # Create a deep copy of the page to avoid reference issues
            page_copy = writer.add_page(page)
            if hasattr(page_copy, '/Resources') and '/XObject' in page_copy['/Resources']:
                resources = page_copy['/Resources']
                if '/XObject' in resources:
                    try:
                        xobject_dict = resources['/XObject'].get_object()
                        # Clear only image XObjects
                        for key, obj in list(xobject_dict.items()):
                            if isinstance(obj, dict) and obj.get('/Subtype') == '/Image':
                                del xobject_dict[key]
                    except:
                        continue

        writer.write(output_stream)
        processed_bytes = output_stream.getvalue()
        
        input_stream.close()
        output_stream.close()
        
        return processed_bytes
    except Exception as e:
        st.error(f"Image removal error: {str(e)}")
        return pdf_bytes

def upload_to_github(file_bytes, filename):
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        
        try:
            repo.get_contents("pdfs", ref=GITHUB_BRANCH)
        except:
            repo.create_file("pdfs/.gitkeep", "Create pdfs directory", "", branch=GITHUB_BRANCH)
        
        content = base64.b64encode(file_bytes).decode()
        file_path = filename
        
        try:
            file = repo.get_contents(file_path, ref=GITHUB_BRANCH)
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

def get_pdf_files_from_github():
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        contents = repo.get_contents("pdfs", ref=GITHUB_BRANCH)
        
        pdf_files = []
        for content in contents:
            if content.name.endswith('.pdf'):
                pdf_files.append({
                    'name': content.name,
                    'path': content.path,
                    'download_url': content.download_url,
                    'sha': content.sha
                })
        return pdf_files
    except Exception as e:
        st.error(f"Error fetching PDF files: {str(e)}")
        return []

def view_pdf_file(file_content):
    # Create a temporary file to display the PDF
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
        tmp_file.write(file_content)
        tmp_file.flush()
        with open(tmp_file.name, 'rb') as f:
            base64_pdf = base64.b64encode(f.read()).decode('utf-8')
    
    # Display PDF using HTML
    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800" type="application/pdf"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)
    
    # Clean up the temporary file
    os.unlink(tmp_file.name)

def upload_page():
    st.title("PDF Upload and Text Extraction")
    
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
                        processed_file_bytes = remove_images_from_pdf(file_bytes)
                        
                    with st.spinner("Uploading to GitHub..."):
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

def view_page():
    st.title("View PDFs from Repository")
    
    pdf_files = get_pdf_files_from_github()
    
    if not pdf_files:
        st.info("No PDF files found in the repository")
        return
    
    selected_pdf = st.selectbox(
        "Select a PDF to view",
        options=[file['name'] for file in pdf_files],
        format_func=lambda x: x
    )
    
    if selected_pdf:
        selected_file = next(file for file in pdf_files if file['name'] == selected_pdf)
        
        try:
            g = Github(GITHUB_TOKEN)
            repo = g.get_repo(GITHUB_REPO)
            file_content = repo.get_contents(selected_file['path'], ref=GITHUB_BRANCH)
            
            # Decode content
            pdf_content = base64.b64decode(file_content.content)
            
            # Display file info
            st.write(f"File: {selected_pdf}")
            
            # Add download button
            st.download_button(
                label="Download PDF",
                data=pdf_content,
                file_name=selected_pdf,
                mime="application/pdf"
            )
            
            # Display PDF
            view_pdf_file(pdf_content)
            
        except Exception as e:
            st.error(f"Error loading PDF: {str(e)}")

def main():
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", ["Upload PDF", "View PDFs"])
    
    if page == "Upload PDF":
        upload_page()
    else:
        view_page()

if __name__ == "__main__":
    main()
