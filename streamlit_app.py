import streamlit as st
import base64
from github import Github
import json
import tempfile
import os
import google
import google.generativeai as genai
from google.ai.generativelanguage_v1beta.types import content
import pandas as pd
import re
from io import StringIO, BytesIO
import requests
from bs4 import BeautifulSoup
import time
import nest_asyncio
import concurrent.futures
from pypdf import PdfReader
import ocrmypdf
from matplotlib.ticker import MaxNLocator
import matplotlib.pyplot as plt
import seaborn as sns

GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
GITHUB_REPO = st.secrets["GITHUB_REPO"]
GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "main")
GLIC_LIST = ["Khazanah", "EPF", "KWAP", "PNB", "Tabung Haji", "LTAT","Ministry of Finance"]
DOC = st.secrets["DOC"]
correct_password = st.secrets["VERIFY_PASSWORD"]

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

generation_config = {
  "temperature": 1,
  "top_p": 0.95,
  "top_k": 40,
  "max_output_tokens": 8192,
  "response_schema": content.Schema(
    type = content.Type.OBJECT,
    enum = [],
    required = ["companyName", "reportYear", "industry", "companyDescription", "topShareholders"],
    properties = {
      "companyName": content.Schema(
        type = content.Type.STRING,
      ),
      "reportYear": content.Schema(
        type = content.Type.INTEGER,
      ),
      "industry": content.Schema(
        type = content.Type.STRING,
      ),
      "companyDescription": content.Schema(
        type = content.Type.STRING,
      ),
      "topShareholders": content.Schema(
        type = content.Type.ARRAY,
        items = content.Schema(
          type = content.Type.OBJECT,
          enum = [],
          required = ["shareholderName", "glicAssociation", "percentageHeld","pageNumber"],
          properties = {
            "shareholderName": content.Schema(
              type = content.Type.STRING,
            ),
            "glicAssociation": content.Schema(
              type = content.Type.STRING,
            ),
            "percentageHeld": content.Schema(
              type = content.Type.NUMBER,
            ),
            "pageNumber": content.Schema(
              type = content.Type.NUMBER,
            ),
          },
        ),
      ),
    },
  ),
  "response_mime_type": "application/json",
}


def upload_to_github(json_data, filename,year):
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
   
        try:
            repo.get_contents("reports", ref=GITHUB_BRANCH)
        except:
            repo.create_file("reports/.gitkeep", "Create reports directory", "", branch=GITHUB_BRANCH)
        
        content = json.dumps(json_data, indent=2)
        file_path = f"reports/{filename} {year}.json"
        
        try:
            file = repo.get_contents(file_path, ref=GITHUB_BRANCH)
            repo.update_file(
                file_path,
                f"Update {filename}.json",
                content,
                file.sha,
                branch=GITHUB_BRANCH
            )
            return True, "File updated successfully"
        except Exception as e:

            
            if "404" in str(e):

                ref = repo.get_git_ref(f"heads/{GITHUB_BRANCH}")
                latest_commit = repo.get_git_commit(ref.object.sha)

                repo.create_file(
                    file_path,
                    f"Add {filename}.json",
                    content,
                    branch=GITHUB_BRANCH
                )
                return True, "File uploaded successfully"
            else:
                raise e
                
    except Exception as e:
        return False, f"Upload failed: {str(e)}"
    

def get_json_files_from_github(exclude_verified):
    """
    Fetches JSON files from the GitHub repo. If `exclude_verified` is True, 
    only includes JSON files without '_v_' in the filename (for unverified files).
    If `exclude_verified` is False, only includes JSON files with '_v_' in the filename.
    """
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        contents = repo.get_contents("reports", ref=GITHUB_BRANCH)

        json_files = []
        for content in contents:
            if content.name.endswith('.json'):
                is_verified = "_v" in content.name
                # Include based on whether we are excluding verified files or not
                if (exclude_verified and not is_verified) or (not exclude_verified and is_verified):
                    json_files.append({
                        'name': content.name.replace('.json', ''),
                        'path': content.path,
                        'sha': content.sha
                    })
        return json_files
    except Exception as e:
        st.error(f"Error fetching JSON files: {str(e)}")
        return []


def extract_glic_total(filename): #extract from filename
    try:
        match = re.search(r"_v_(\d+\.\d+)", filename)
        return float(match.group(1)) if match else 0.0
    except Exception:
        return 0.0

def verify_page():
    st.title("Verify Extracted Information abc")
    st.write("Starting verification process...")  # Debugging line
      
    password_input = st.text_input("Enter password to access verification page:", type="password")
    st.write("Password input received.")  # Debugging line
    
    if not password_input:
        st.warning("Please enter the password to continue.")
        return
    
    if password_input != correct_password:
        st.error("Incorrect password. Please try again.")
        return
    
    st.write("Please verify the info scraped.")

    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        st.write("Connected to GitHub repository.")  # Debugging line
    except Exception as e:
        st.error(f"Error connecting to GitHub: {str(e)}")
        return

    try:
        verified_shareholders = get_verified_shareholders(repo)
        st.write("Verified shareholders data retrieved.")  # Debugging line
    except Exception as e:
        st.error(f"Error fetching verified shareholders: {str(e)}")
        return
    
    try:
        json_files = get_json_files_from_github(exclude_verified=True)
        st.write(f"Found {len(json_files)} JSON files for verification.")  # Debugging line
        if not json_files:
            st.info("No JSON files found in the repository")
            return
    except Exception as e:
        st.error(f"Error fetching JSON files: {str(e)}")
        return

    verification_completed = False
    modified_files = []

    for file_index, file in enumerate(json_files):
        try:
            st.write(f"Processing file {file['name']}...")  # Debugging line
            file_content = repo.get_contents(file['path'], ref=GITHUB_BRANCH)
            json_content = base64.b64decode(file_content.content).decode()
            data = json.loads(json_content)
            st.write(f"Loaded data for company: {data['companyName']}")  # Debugging line

            shareholders = data['topShareholders'].copy()
            modified = False

            # Auto-fill verification for known shareholders
            for shareholder in shareholders:
                shareholder_name = shareholder['shareholderName']
                if shareholder_name in verified_shareholders['shareholderName'].values:
                    verified_glic = verified_shareholders[
                        verified_shareholders['shareholderName'] == shareholder_name
                    ]['glicAssociation'].iloc[0]
                    
                    if shareholder['glicAssociation'] != verified_glic:
                        shareholder['glicAssociation'] = verified_glic
                        modified = True
                        st.info(f"Auto-verified {shareholder_name} as {verified_glic}")

            # Handle unverified shareholders
            unverified_shareholders = [
                s for s in shareholders 
                if s['shareholderName'] not in verified_shareholders['shareholderName'].values
            ]
            
            if unverified_shareholders:
                st.write("Please verify the following shareholders:")
                for idx, shareholder in enumerate(unverified_shareholders):
                    shareholder_name = shareholder['shareholderName']
                    unique_key = f"file_{file_index}_shareholder_{idx}_{shareholder_name}"
                    
                    current_glic = shareholder.get('glicAssociation', "None")
                    glic_options = ["None", "Khazanah", "EPF", "KWAP", "PNB", "Tabung Haji", "LTAT", "Ministry of Finance"]
                    
                    default_index = glic_options.index(current_glic) if current_glic in glic_options else 0
                    
                    glic_selection = st.selectbox(
                        f"{shareholder_name}",
                        glic_options,
                        key=unique_key,
                        index=default_index
                    )
                    
                    if shareholder['glicAssociation'] != glic_selection:
                        shareholder['glicAssociation'] = glic_selection
                        modified = True

            if modified:
                modified_files.append((file, shareholders, data))
                st.write(f"File {file['name']} marked as modified.")  # Debugging line

        except Exception as e:
            st.error(f"Error processing file {file['name']}: {str(e)}")

    if st.button("Approve Verification", key="approve_verification"):
        st.write("Approve Verification button clicked.")  # Debugging line
        for file, shareholders, data in modified_files:
            try:
                st.write(f"Processing updates for {file['name']}...")  # Debugging line
                glic_total = sum(
                    s['percentageHeld']
                    for s in shareholders
                    if s['glicAssociation'] in GLIC_LIST
                )
                st.write(f"GLIC total calculated: {glic_total}")  # Debugging line

                data['topShareholders'] = shareholders
                new_file_name = f"{file['name']}_v_{glic_total:.1f}.json"
                new_file_path = f"reports/{new_file_name}"
                st.write(f"New file path: {new_file_path}")  # Debugging line

                try:
                    repo.create_file(
                        new_file_path,
                        f"Add verified file {new_file_name}",
                        json.dumps(data, indent=2),
                        branch=GITHUB_BRANCH
                    )
                    st.write(f"Verified file created: {new_file_name}")  # Debugging line
                    
                    shareholders_for_csv = [
                        {
                            "shareholderName": s['shareholderName'],
                            "glicAssociation": s['glicAssociation']
                        }
                        for s in shareholders
                    ]
                    if not add_verified_shareholders(repo, shareholders_for_csv):
                        st.error("Failed to update verified shareholders CSV")
                    else:
                        st.write("Verified shareholders CSV updated.")  # Debugging line
                    
                    repo.delete_file(
                        file['path'],
                        f"Delete unverified file {file['name']}",
                        file['sha'],
                        branch=GITHUB_BRANCH
                    )
                    st.write(f"Unverified file deleted: {file['name']}")  # Debugging line

                    st.success(f"Successfully verified {data['companyName']} and updated files")
                    verification_completed = True

                except Exception as e:
                    st.error(f"Error updating files for {file['name']}: {str(e)}")
                    
            except Exception as e:
                st.error(f"Error finalizing file {file['name']}: {str(e)}")
    
    if verification_completed:
        st.success("Verification completed!")
        time.sleep(2)  # Wait for 2 seconds before refreshing
        st.experimental_rerun()  # Refresh the page

def get_verified_shareholders(repo):
    # Check for existence of verified_shareholders.csv
    try:
        file_content = repo.get_contents("verified_shareholders.csv", ref=GITHUB_BRANCH)
        csv_data = base64.b64decode(file_content.content).decode()
        verified_shareholders = pd.read_csv(StringIO(csv_data))
    except:
        # Create a new verified shareholders CSV if it doesn't exist
        csv_content = "shareholderName,glicAssociation\n"
        repo.create_file("verified_shareholders.csv", "Initialize verified shareholders file", csv_content, branch=GITHUB_BRANCH)
        verified_shareholders = pd.DataFrame(columns=["shareholderName", "glicAssociation"])
    
    return verified_shareholders

def add_verified_shareholders(repo, new_entries):
    """Add new verified shareholders to the CSV file."""
    try:
        try:
            file_content = repo.get_contents("verified_shareholders.csv", ref=GITHUB_BRANCH)
            csv_data = base64.b64decode(file_content.content).decode()
            verified_shareholders = pd.read_csv(StringIO(csv_data))
        except:
            # If file doesn't exist, create new DataFrame
            verified_shareholders = pd.DataFrame(columns=["shareholderName", "glicAssociation"])
        
        # Convert new_entries to DataFrame if it's a list of dicts
        if isinstance(new_entries, list):
            new_entries = pd.DataFrame(new_entries)
            
        # Add new verified entries and avoid duplicates
        updated_shareholders = pd.concat([verified_shareholders, new_entries], ignore_index=True)
        # Drop duplicates, keeping the most recent entry
        updated_shareholders = updated_shareholders.drop_duplicates(
            subset="shareholderName", 
            keep="last"
        ).sort_values("shareholderName")
        
        csv_content = updated_shareholders.to_csv(index=False)
        
        try:
            # Try to update existing file
            repo.update_file(
                "verified_shareholders.csv",
                "Update verified shareholders list",
                csv_content,
                file_content.sha,
                branch=GITHUB_BRANCH
            )
        except:
            # If file doesn't exist, create it
            repo.create_file(
                "verified_shareholders.csv",
                "Initialize verified shareholders list",
                csv_content,
                branch=GITHUB_BRANCH
            )
        return True
    except Exception as e:
        st.error(f"Error updating verified shareholders: {str(e)}")
        return False

def view_json_file(file_content, selected_file):
    data = json.loads(file_content)
    st.subheader(data["companyName"])
        # Extract the percentage from the file name using a regular expression
    match = re.search(r"(\d+\.\d+)$", selected_file)  # This captures the number after the last underscore

    if match:
        glic_percentage = float(match.group(1))  # Convert the extracted string to a float
        is_glic_above_20 = glic_percentage >= 20  # Check if the percentage is >= 20
        st.write(f"✔️ _A Bond Serving Company_")
    else:
        is_glic_above_20 = False  # Default to False if no valid percentage is found
        st.write(f"❌ _Isn't A Bond Serving Company_")
    # Display company information
    
    st.write(f"Report Year: {data['reportYear']}")
    st.write(f"Industry: {data['industry']}")
    st.write(f"Company Description: {data['companyDescription']}")

    # Prepare shareholder data
    shareholder_data = []
    for shareholder in data['topShareholders']:
        shareholder_data.append({
            "Shareholder Name": shareholder['shareholderName'],
            "GLIC Association": shareholder['glicAssociation'],
            "Percentage Held %": shareholder['percentageHeld']
        })

    # Create DataFrame
    df = pd.DataFrame(shareholder_data)

    # Define Group 1 (Associated) and Group 2 (Unassociated)
    df['Group'] = df['GLIC Association'].apply(lambda x: 1 if x != "None" else 2)

    # Sort by Group first, then by Percentage Held descending within each group
    df = df.sort_values(by=["Group", "Percentage Held %"], ascending=[True, False]).drop(columns=["Group"])

    # Adjust table display
    st.subheader("Top Shareholders")
    st.markdown(
        df.to_html(index=False, escape=False, justify="left"),
        unsafe_allow_html=True
    )



def save_extracted_text_to_github(repo, company_name, extracted_text, year):
    """Save extracted text to GitHub in the extracted folder."""
    try:
        # Ensure extracted directory exists
        try:
            repo.get_contents("extracted", ref=GITHUB_BRANCH)
        except:
            repo.create_file("extracted/.gitkeep", "Create extracted directory", "", branch=GITHUB_BRANCH)
        
        file_path = f"extracted/{company_name} {year}.txt"
        
        try:
            # Try to update existing file
            file = repo.get_contents(file_path, ref=GITHUB_BRANCH)
            repo.update_file(
                file_path,
                f"Update extracted text for {company_name}",
                extracted_text,
                file.sha,
                branch=GITHUB_BRANCH
            )
        except:
            # Create new file if it doesn't exist
            repo.create_file(
                file_path,
                f"Add extracted text for {company_name}",
                extracted_text,
                branch=GITHUB_BRANCH
            )
        return True
    except Exception as e:
        st.error(f"Error saving extracted text: {str(e)}")
        return False

    
def extract_text_from_pdf(reader):
    full_text = ""
    for idx, page in enumerate(reader.pages):
        text = page.extract_text()
        #if text:
        full_text += f"---- Page {idx+1} ----\n" + text + "\n\n"
    return full_text.strip()

def convert_pdf_to_text(pdf_file):
    reader = PdfReader(pdf_file)
    full_text = extract_text_from_pdf(reader)

    # Check if there are any images and perform OCR if necessary
    image_count = sum(len(page.images) for page in reader.pages)
    if image_count > 0 and len(full_text) < 1000:
        with tempfile.NamedTemporaryFile(delete=False, suffix='_ocr.pdf') as temp_ocr_pdf:
            ocrmypdf.ocr(pdf_file, temp_ocr_pdf.name, force_ocr=True)
            reader = PdfReader(temp_ocr_pdf.name)
            full_text = extract_text_from_pdf(reader)
        os.unlink(temp_ocr_pdf.name)

    return full_text

def process_pdf_content(pdf_content, company_name=None, status_callback=None):
    """Unified PDF processing function for all upload methods."""
    #st.write("entered process pdf func")

    # Create temporary file
    try:
        if isinstance(pdf_content, bytes):
            content_bytes = pdf_content
        else:
            content_bytes = pdf_content.read()
            
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_pdf:
            temp_pdf.write(content_bytes)
            temp_pdf_path = temp_pdf.name
            #st.write(f"Temporary PDF path: {temp_pdf_path}")
    except Exception as temp_file_error:
        st.error(f"Error creating temporary file: {temp_file_error}")
        return False

    def extract_pdf_text():
        try:
            return convert_pdf_to_text(temp_pdf_path), None
        except Exception as e:
            return None, str(e)

    # Run extractors concurrently
    try:

        pdf_text_result, pdf_text_error = extract_pdf_text()

        if pdf_text_error:
            st.warning(f"PDF text extraction failed: {pdf_text_error}")

    finally:
        try:
            os.unlink(temp_pdf_path)
        except:
            pass

    # Process with Gemini
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash-exp", # gemini-2.0-flash-exp  gemini-1.5-flash-8b
        generation_config=generation_config
    )

    results = []
    
    EXTRACTION_PROMPT = """
    Extract the following information from the text and format it in JSON:

    Company full name.
    Year of the report.
    Industry of the company (choose one from the following: Automobiles, Banks, Capital Goods, Commercial Services, 
    Consumer Durables, Consumer Retailing, Consumer Services, Diversified Financials, Energy, Food, Beverage, Healthcare, Household, Insurance, Materials, Media, Pharmaceuticals, Biotech, Real Estate, 
    Real Estate Management and Development, Retail, Semiconductors, Software, Tech, Telecom, Transportation, Utilities).
    A brief description of the company's business.
    Top Shareholders:
    For each of the top 30 shareholders, include:
    Full name of the shareholder.
    If the shareholder is associated with any of the following six Malaysian Government-Linked Investment Companies (GLICs), 
    specify which one: Khazanah Nasional Berhad (Khazanah), Employees Provident Fund (EPF), 
    Kumpulan Wang Persaraan (KWAP), Permodalan Nasional Berhad (PNB), 
    Lembaga Tabung Haji, Lembaga Tabung Angkatan Tentera (LTAT), or Ministry of Finance. 
    Return this information in the JSON format:

    {
    "companyName": "Company full name",
    "reportYear": Year,
    "industry": "Industry name from the provided list",
    "companyDescription": "Brief description of company",
    "topShareholders": [
        {
        "shareholderName": "Shareholder's name. Sometimes the name can span multiple lines, so provide the full name of the shareholder",
        "glicAssociation": "GLIC name if applicable, otherwise None",
        "percentageHeld": "Percentage of shares held",
        "pageNumber": "Page number where the shareholder information is found, looks like ---- Page 236 ----"
        },
        ...
    ]
    }

    If a shareholder is not associated with any of the specified GLICs, set the "glicAssociation" field to None in the JSON output. 
    If the shareholder is a subsidiary or affiliate of a GLIC (e.g., "Amanah Trustees" under "PNB"), 
    note the primary GLIC association in the "glicAssociation" field. 
    Here is the text from the annual report:
    """
    if pdf_text_result:
        chat_session = model.start_chat()
        pdf_text_response = chat_session.send_message(EXTRACTION_PROMPT + str(pdf_text_result))
        try:
            pdf_text_json = json.loads(pdf_text_response.text)
            results.append(pdf_text_json)
        except json.JSONDecodeError:
            st.warning("Failed to parse PDF text results")

    if not results:
        st.error("No valid results obtained from either extractor")
        return False

    # Save to GitHub
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)

        # Save extracted texts
        if pdf_text_result:
            save_extracted_text_to_github(repo, pdf_text_json["companyName"], 
                                        pdf_text_result,
                                        pdf_text_json["reportYear"])
                                        
        # Upload the JSON data
        success, message = upload_to_github(pdf_text_json, pdf_text_json["companyName"],
                                          pdf_text_json["reportYear"])
        
        if success:
            if status_callback:
                status_callback("✅ Successfully processed")
            if company_name:
                update_not_yet_companies(repo, [company_name])
            return True
        else:
            if status_callback:
                status_callback(f"❌ Failed: {message}")
            return False

    except Exception as e:
        if status_callback:
            status_callback(f"❌ Processing Error: {str(e)}")
        return False
    
def handle_pdf_upload(uploaded_file):
    if uploaded_file is not None:
        try:
            return uploaded_file
        except Exception as e:
            st.error(f"Error reading PDF file: {str(e)}")
            return None
    return None

def download_and_process_pdf(url):
    try:
        response = requests.get(url)
        return response.content
    except Exception as e:
        st.error(f"Error downloading PDF: {str(e)}")
        return None

def upload_page():
    st.title("Annual Report Information Extraction")
    
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        
    except Exception as e:
        st.error(f"GitHub connection failed: {str(e)}")
        return
    
    uploaded_files = st.file_uploader("Choose PDF files", type="pdf", accept_multiple_files=True)
    
    if uploaded_files:
        status_container = st.empty()
        
        def update_status(status=None):
            status_container.text_area("Processing Status:", value=status, height=150)
                
        if st.button("Process Files"):
            for uploaded_file in uploaded_files:
                try:
                    pdf_content = handle_pdf_upload(uploaded_file)
                    if pdf_content is None:
                        continue
            
                    update_status(f"Processing {uploaded_file.name}...")
                    
                    # Use the unified processing function
                    success = process_pdf_content(pdf_content, company_name=None, status_callback=update_status)
                    
                    if success:
                        update_status(f"Completed {uploaded_file.name} ✓")
                    else:
                        update_status(f"Failed {uploaded_file.name} ✗")
                except Exception as e:
                    update_status(f"Failed {uploaded_file.name}: {str(e)} ✗")
    # New section for search and company selection
    st.markdown("---")
    st.subheader("Process New Companies")
    
    # Tab selection for search or dropdown
    tab2, tab1 = st.tabs([ "Select from List","Search Company"])
    
    with tab1:
        # Initialize session state for search results and status messages
        if 'search_results' not in st.session_state:
            st.session_state.search_results = []
        if 'status_messages' not in st.session_state:
            st.session_state.status_messages = {}
            
        search_query = st.text_input("Search for company annual reports:")
        search_button = st.button("Search")
        
        if search_button and search_query:
            with st.spinner("Searching..."):
                st.session_state.search_results = search_annual_report(search_query)
                
        # Display search results if they exist
        if st.session_state.search_results:
            st.write("Search Results:")
            for idx, result in enumerate(st.session_state.search_results):
                with st.expander(f"{result['title']}", expanded=True):
                    st.write(result['snippet'])
                    st.write(f"URL: {result['url']}")
                    
                    status_key = f"status_tab1_{idx}"
                    
                    # Create columns for status and button
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        if status_key in st.session_state.status_messages:
                            st.info(st.session_state.status_messages[status_key])
                    
                    with col2:
                        if st.button("Process Report", key=f"process_tab1_{idx}"):
                            
                            def update_status(msg):
                                st.session_state.status_messages[status_key] = msg
                                if "Successfully processed" in msg:
                                    st.success("✅ Successfully processed")
                            
                            # Download the PDF and process
                            pdf_content = download_and_process_pdf(result['url'])
                            process_pdf_content(pdf_content, search_query, update_status)
    
    with tab2:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        not_yet_companies = get_not_yet_companies(repo)
        
        if not_yet_companies:
            selected_company = st.selectbox(
                "Select a company to process:",
                options=not_yet_companies
            )
            
            if 'tab2_results' not in st.session_state:
                st.session_state.tab2_results = []
            
            if selected_company and st.button("Search Selected Company"):
                with st.spinner(f"Searching for {selected_company}'s annual report..."):
                    st.session_state.tab2_results = search_annual_report(selected_company)
            
            # Display search results if they exist
            if st.session_state.tab2_results:
                st.write("Found the following reports:")
                for idx, result in enumerate(st.session_state.tab2_results):
                    with st.expander(f"{result['title']}", expanded=True):
                        st.write(result['snippet'])
                        st.write(f"URL: {result['url']}")
                        
                        status_key = f"status_tab2_{idx}"
                        
                        # Create columns for status and button
                        col1, col2 = st.columns([3, 1])
                        
                        with col1:
                            if status_key in st.session_state.status_messages:
                                st.info(st.session_state.status_messages[status_key])
                        
                        with col2:
                            if st.button("Process Report", key=f"process_tab2_{idx}"):
                                def update_status(msg):
                                    st.session_state.status_messages[status_key] = msg
                                    if "Successfully processed" in msg:
                                        st.success("✅ Successfully processed")
                                
                                # Download the PDF and pass it to process
                                pdf_content = download_and_process_pdf(result['url'])
                                process_pdf_content(pdf_content, selected_company, update_status)
                                
            #elif selected_company and 'tab2_results' in st.session_state:
                #st.error("No PDF reports found for this company")
        else:
            st.info("No companies left to process in the list")

def view_page():
    st.title("View Extracted Information")
    
    json_files = get_json_files_from_github(exclude_verified=False)
    
    if not json_files:
        st.info("No JSON files found in the repository")
        return
    
    selected_json = st.selectbox(
        "Select a file to view",
        options=[file['name'] for file in json_files],
        format_func=lambda x: x
    )
    
    if selected_json:
        selected_file = next(file for file in json_files if file['name'] == selected_json)
        
        try:
            g = Github(GITHUB_TOKEN)
            repo = g.get_repo(GITHUB_REPO)
            file_content = repo.get_contents(selected_file['path'], ref=GITHUB_BRANCH)
            
            # Decode content
            json_content = base64.b64decode(file_content.content).decode()
            
            view_json_file(json_content,selected_file['name'])
            
        except Exception as e:
            st.error(f"Error loading JSON: {str(e)}")

def get_file_content(file_path):
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(GITHUB_REPO)
    content = repo.get_contents(file_path, ref=GITHUB_BRANCH)
    data = json.loads(base64.b64decode(content.content).decode())
    return data



def dashboard_page(): 
    # Only show those which are verified and bond serving
    st.title("Dashboard")

    # Fetch JSON files at the beginning
    json_files = get_json_files_from_github(exclude_verified=False)
    if not json_files:
        st.info("No JSON files found with GLIC totals.")
        return

    file_data = []
    industry_counts = {}
    glic_distribution = {">= 20": {}, "< 20": {}}

    for file in json_files:
        glic_total = extract_glic_total(file['name'])
        file_content = get_file_content(file['path'])
        industry = file_content.get("industry", "Unknown")
        
        file_data.append({
            " ": "✔️" if glic_total >= 20 else "",
            "Company": file_content.get("companyName", "Unknown"),
            "Industry": industry,
            "GLIC Total %": glic_total,
            
        })

        # Update industry counts for the chart
        if industry and industry != "Unknown":
            if glic_total >= 20:
                glic_distribution[">= 20"][industry] = glic_distribution[">= 20"].get(industry, 0) + 1
            else:
                glic_distribution["< 20"][industry] = glic_distribution["< 20"].get(industry, 0) + 1

    # Create data frame from file data
    file_df = pd.DataFrame(file_data)

    # Apply GLIC threshold to separate categories
    high_glic_df = file_df[file_df["GLIC Total %"] >= 20]
    low_glic_df = file_df[file_df["GLIC Total %"] < 20]

    # Display statistics
    st.subheader("Statistics")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Bond Serving Companies", len(high_glic_df))
    with col2:
        st.metric("Total Companies Processed", len(file_df))
    with col3:
        st.metric("Total Industries", len(glic_distribution[">= 20"]) + len(glic_distribution["< 20"]))

    # Industry distribution chart
    industry_df = pd.DataFrame({
        "Industry": list(set(glic_distribution[">= 20"].keys()) | set(glic_distribution["< 20"].keys())),
        "Bond Serving": [glic_distribution[">= 20"].get(ind, 0) for ind in set(glic_distribution[">= 20"].keys()) | set(glic_distribution["< 20"].keys())],
        "Non" : [glic_distribution["< 20"].get(ind, 0) for ind in set(glic_distribution[">= 20"].keys()) | set(glic_distribution["< 20"].keys())],
    })

    # Plot with Matplotlib
    plt.figure(figsize=(10, 4))
    industry_df = industry_df.set_index("Industry")
    ax = industry_df.plot(kind="bar", stacked=True, color=["#46B4A6", "#FFA07A"], edgecolor="black")
    plt.ylabel("Count", fontsize=12)
    plt.xlabel("Industry", fontsize=12)
    plt.xticks(rotation=45, ha="right", fontsize=10, color="black")
    plt.yticks(fontsize=10)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    plt.title("Industry Distribution", fontsize=14, fontweight="bold")
    plt.tight_layout()
    st.pyplot(plt)

    # Sorting and filtering
    st.subheader("Company Details")
    sort_col, filter_col = st.columns(2)
    with sort_col:
        sort_by = st.selectbox("Sort by:", ["GLIC Total %", "Company", "Industry"])
    with filter_col:
        all_industries = ["All"] + sorted(list(set(file_df["Industry"])))
        selected_industry = st.selectbox("Filter by industry:", all_industries)

    # Apply filters and sorting
    if selected_industry != "All":
        file_df = file_df[file_df["Industry"] == selected_industry]

    # Separate into categories and sort
    high_glic_df = file_df[file_df["GLIC Total %"] >= 20].sort_values(by=sort_by, ascending=False)
    low_glic_df = file_df[file_df["GLIC Total %"] < 20].sort_values(by=sort_by, ascending=False)
    sorted_df = pd.concat([high_glic_df, low_glic_df])

    # Display table
    st.dataframe(sorted_df.reset_index(drop=True), use_container_width=True)



def get_not_yet_companies(repo):
    """Get list of companies that haven't been processed yet."""
    try:
        file_content = repo.get_contents("not_yet.txt", ref=GITHUB_BRANCH)
        companies = base64.b64decode(file_content.content).decode().splitlines()
        return [company.strip() for company in companies if company.strip()]
    except Exception as e:
        st.error(f"Error loading not_yet.txt: {str(e)}")
        return []

def update_not_yet_companies(repo, companies_to_remove):
    """Update not_yet.txt by removing processed companies."""
    try:
        # Get current list
        file_content = repo.get_contents("not_yet.txt", ref=GITHUB_BRANCH)
        current_companies = base64.b64decode(file_content.content).decode().splitlines()
        
        # Remove processed companies
        updated_companies = [company for company in current_companies 
                           if company.strip() and company.strip() not in companies_to_remove]
        
        # Update file
        new_content = "\n".join(updated_companies)
        repo.update_file(
            "not_yet.txt",
            "Update companies list",
            new_content,
            file_content.sha,
            branch=GITHUB_BRANCH
        )
    except Exception as e:
        st.error(f"Error updating not_yet.txt: {str(e)}")

def search_annual_report(company_name):
    """Search for company's annual report PDF using Google Custom Search."""
    query = f"{company_name} annual report pdf filetype:pdf"
    url = f"https://www.googleapis.com/customsearch/v1?q={query}&key={st.secrets['GOOGLE_API_KEY']}&cx={st.secrets['GOOGLE_CSE_ID']}"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        results = []
        if "items" in data:
            for item in data["items"]:
                link = item.get("link")
                if link and link.endswith(".pdf"):
                    results.append({
                        "title": item.get("title", "Untitled"),
                        "url": link,
                        "snippet": item.get("snippet", "No description available")
                    })
        return results
    except Exception as e:
        st.error(f"Error searching for annual reports: {str(e)}")
        return []

    
def main():
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", ["Dashboard", "Upload PDF", "View Extracted Information", "Verify Extracted Information"])
    
    if page == "Dashboard":
        dashboard_page()
    elif page == "Upload PDF":
        upload_page()
    elif page == "View Extracted Information":
        view_page()
    else:
        verify_page()


if __name__ == "__main__":
    main()
