import streamlit as st
import base64
from github import Github
import json
import tempfile
import os
import google
import google.generativeai as genai
from google.ai.generativelanguage_v1beta.types import content
from PyPDF2 import PdfReader
import pandas as pd
import re
from io import StringIO
import requests
from bs4 import BeautifulSoup
import time
import nest_asyncio
nest_asyncio.apply()


from llama_parse import LlamaParse

GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
GITHUB_REPO = st.secrets["GITHUB_REPO"]
GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "main")
GLIC_LIST = ["Khazanah", "EPF", "KWAP", "PNB", "Tabung Haji", "LTAT"]
DOC = st.secrets["DOC"]
correct_password = st.secrets["VERIFY_PASSWORD"]

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

parser = LlamaParse(
    api_key = DOC, 
    result_type = "markdown", 
    verbose = True,
)


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
          required = ["shareholderName", "glicAssociation", "percentageHeld"],
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
    

def get_json_files_from_github(exclude_verified=True):
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
    st.title("Verify Extracted Information")
      
    password_input = st.text_input("Enter password to access verification page:", type="password")
    
    if not password_input:
        st.warning("Please enter the password to continue.")
        return
    
    if password_input != correct_password:
        st.error("Incorrect password. Please try again.")
        return
    
    
    st.write("Please verify the info scraped.")

    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(GITHUB_REPO)
    verified_shareholders = get_verified_shareholders(repo)
    
    json_files = get_json_files_from_github(exclude_verified=True)
    if not json_files:
        st.info("No JSON files found in the repository")
        return

    verification_completed = False

    for file_index, file in enumerate(json_files):
        try:
            file_content = repo.get_contents(file['path'], ref=GITHUB_BRANCH)
            json_content = base64.b64decode(file_content.content).decode()
            data = json.loads(json_content)

            st.subheader(f"Verifying: {data['companyName']} ({data['reportYear']})")

            # Create a deep copy to ensure we don't lose any shareholders
            shareholders = data['topShareholders'].copy()
            modified = False

            # First, auto-fill verification for known shareholders
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

            # Then handle unverified shareholders
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
                    glic_options = ["None", "Khazanah", "EPF", "KWAP", "PNB", "Tabung Haji", "LTAT"]
                    
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

            if st.button("Approve Verification"):
                success = True
                
                # Calculate GLIC total
                glic_total = sum(
                    s['percentageHeld']
                    for s in shareholders
                    if s['glicAssociation'] in GLIC_LIST
                )
                
                # Update data with complete shareholders list
                data['topShareholders'] = shareholders
                
                # Create new verified filename with GLIC total
                new_file_name = f"{file['name']}_v_{glic_total:.1f}.json"
                new_file_path = f"reports/{new_file_name}"
                
                try:
                    # Create the new verified file
                    repo.create_file(
                        new_file_path,
                        f"Add verified file {new_file_name}",
                        json.dumps(data, indent=2),
                        branch=GITHUB_BRANCH
                    )
                    
                    # After creating verified JSON, update verified_shareholders.csv with all shareholders
                    shareholders_for_csv = [
                        {
                            "shareholderName": s['shareholderName'],
                            "glicAssociation": s['glicAssociation']
                        }
                        for s in shareholders
                    ]
                    if not add_verified_shareholders(repo, shareholders_for_csv):
                        st.error("Failed to update verified shareholders CSV")
                        success = False
                    
                    # Delete the old unverified file
                    repo.delete_file(
                        file['path'],
                        f"Delete unverified file {file['name']}",
                        file['sha'],
                        branch=GITHUB_BRANCH
                    )
                    
                    st.success(f"Successfully verified {data['companyName']} and updated files")
                    verification_completed = True
                     
                except Exception as e:
                    st.error(f"Error updating files: {str(e)}")
                    
        except Exception as e:
            st.error(f"Error processing file: {str(e)}")
    
    if verification_completed:
        st.success("Verification completed!")

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

def view_json_file(file_content):
    data = json.loads(file_content)

    st.subheader(data["companyName"])
    st.write(f"Report Year: {data['reportYear']}")
    st.write(f"Industry: {data['industry']}")
    st.write(f"Company Description: {data['companyDescription']}")

    st.subheader("Top Shareholders")
    shareholder_data = [["#", "Shareholder Name", "GLIC Association", "Percentage Held"]]

    # Populate the data, starting the row counter from 1
    for idx, shareholder in enumerate(data['topShareholders'], start=1):
        shareholder_data.append([
            idx,
            shareholder['shareholderName'],
            shareholder['glicAssociation'],
            f"{shareholder['percentageHeld']}%"
        ])

    st.table(shareholder_data)

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

def process_pdf_content(pdf_content, company_name=None, status_callback=None):
    """Unified PDF processing function for all upload methods."""
    st.write(" enterred process pdf func")
    st.write(f"PDF content type: {type(pdf_content)}, length: {len(pdf_content) if pdf_content else 'None'}")

    try:

        # Create a temporary file to save the PDF content
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_pdf:
            temp_pdf.write(pdf_content)
            temp_pdf_path = temp_pdf.name
            st.write(f"Temporary PDF path: {temp_pdf_path} Temporary PDF: {temp_pdf}")

        try:
    
            extracted_text = parser.load_data(temp_pdf_path)
            st.write(" extracted text")
            #pdf = genai.upload_file(temp_pdf_path)
        except Exception as upload_error:
            st.error(f"Error uploading PDF: {upload_error}")
            return False
        finally:
            # Clean up temporary file
            os.unlink(temp_pdf_path)

        if status_callback:
            status_callback("Sending text to Gemini for analysis...")

        # Initialize Gemini model with chat session
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash-002", #gemini-1.5-flash-002  gemini-2.0-flash-exp
            generation_config=generation_config
        )
        chat_session = model.start_chat()
        st.write("sending to gemini ")
        prompt = """
        Extract the following information from the provided PDF file and format it in JSON:

        Company full name.
        Year of the report.
        Industry of the company (choose one from the following: Automobiles, Banks, Capital Goods, Commercial Services, 
        Consumer Durables, Consumer Retailing, Consumer Services, Diversified Financials, Energy, Food, Beverage, 
        Tobacco, Healthcare, Household, Insurance, Materials, Media, Pharmaceuticals, Biotech, Real Estate, 
        Real Estate Management and Development, Retail, Semiconductors, Software, Tech, Telecom, Transportation, Utilities).
        A brief description of the company's business.
        Top Shareholders:
        For each of the top 30 shareholders, include:
        Full name of the shareholder.
        If the shareholder is associated with any of the following six Malaysian Government-Linked Investment Companies (GLICs), 
        specify which one: Khazanah Nasional Berhad (Khazanah), Employees Provident Fund (EPF), 
        Kumpulan Wang Persaraan (Diperbadankan) [KWAP], Permodalan Nasional Berhad (PNB), 
        Lembaga Tabung Haji, or Lembaga Tabung Angkatan Tentera (LTAT). 
        Return this information in the JSON format:

        {
        "companyName": "Company full name",
        "reportYear": Year,
        "industry": "Industry name from the provided list",
        "companyDescription": "Brief description of company",
        "topShareholders": [
            {
            "shareholderName": "Shareholder's name",
            "glicAssociation": "GLIC name if applicable, otherwise None",
            "percentageHeld": Percentage of shares held
            },
            ...
        ]
        }

        If a shareholder is not associated with any of the specified GLICs, set the "glicAssociation" field to None in the JSON output. 
        If the shareholder is a subsidiary or affiliate of a GLIC (e.g., "Amanah Trustees" under "PNB"), 
        note the primary GLIC association in the "glicAssociation" field.
        Here is the text from the annual report:
        """
        try:
            # Generate content using the uploaded PDF file
            #response = model.generate_content([prompt, pdf])
            response = chat_session.send_message(prompt, extracted_text)
            # Delete the uploaded file
            
            
            try:
                # Parse the JSON response
                output_json = json.loads(response.text)
                
                # Save extracted text to GitHub
                g = Github(GITHUB_TOKEN)
                repo = g.get_repo(GITHUB_REPO)
                save_extracted_text_to_github(repo, output_json["companyName"], extracted_text, output_json["reportYear"])

                # Upload the JSON to GitHub
                file_name = output_json["companyName"]
                year = output_json["reportYear"]
                success, message = upload_to_github(output_json, file_name, year)

                if success:
                    if status_callback:
                        status_callback("✅ Successfully processed")
                    # Update not_yet.txt if company was in the list and provided
                    if company_name:
                        update_not_yet_companies(repo, [company_name])
                    return True
                else:
                    if status_callback:
                        status_callback(f"❌ Failed: {message}")
                    return False

            except json.JSONDecodeError:
                if status_callback:
                    status_callback("❌ Failed to parse response")
                return False

        except Exception as generation_error:
            if status_callback:
                status_callback(f"❌ Generation Error: {str(generation_error)}")
            return False

    except Exception as e:
        if status_callback:
            status_callback(f"❌ Error: {str(e)}")
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
        st.info(f"Connected to repository: {GITHUB_REPO} ({GITHUB_BRANCH} branch)")
    except Exception as e:
        st.error(f"GitHub connection failed: {str(e)}")
        return
    
    uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")
    
    if uploaded_file:
        status_container = st.empty()
        
        def update_status(status=None):
            status_container.text_area("Processing Status:", value=status, height=150)
                
        if st.button("Process File"):
            try:
                pdf_content = handle_pdf_upload(uploaded_file)
                if pdf_content is None:
                    return
        
                update_status("Processing...")
                
                # Use the unified processing function
                success = process_pdf_content(pdf_content, company_name=None, status_callback=update_status)
                
                if success:
                    update_status("Completed ✓")
                else:
                    update_status("Failed ✗")
            except Exception as e:
                update_status(f"Failed: {str(e)} ✗")
    # New section for search and company selection
    st.markdown("---")
    st.subheader("Process New Companies")
    
    # Tab selection for search or dropdown
    tab1, tab2 = st.tabs(["Search Company", "Select from List"])
    
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
                                
                                # Download the PDF and pass it to process
                                pdf_content = download_and_process_pdf(result['url'])
                                process_pdf_content(pdf_content, selected_company, update_status)
                                
            elif selected_company and 'tab2_results' in st.session_state:
                st.error("No PDF reports found for this company")
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
            
            view_json_file(json_content)
            
        except Exception as e:
            st.error(f"Error loading JSON: {str(e)}")

def get_file_content(file_path):
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(GITHUB_REPO)
    content = repo.get_contents(file_path, ref=GITHUB_BRANCH)
    data = json.loads(base64.b64decode(content.content).decode())
    return data

def dashboard_page(): #only show those which are verified and is bondserving
    st.title("Dashboard")

    json_files = get_json_files_from_github(exclude_verified=False)
    if not json_files:
        st.info("No JSON files found with GLIC totals.")
        return

    file_data = []
    industry_counts = {}
    for file in json_files:
        glic_total = extract_glic_total(file['name'])
        file_content = get_file_content(file['path'])
        industry = file_content.get("industry", "Unknown")
        
        file_data.append({
            "Filename": file['name'],
            "Company": file_content.get("companyName", "Unknown"),
            "Industry": industry,
            "GLIC Total": glic_total
        })

        # Update industry counts for the chart
        if industry and industry != "Unknown":
            industry_counts[industry] = industry_counts.get(industry, 0) + 1

    # Display file data in a table
    st.subheader("Files with GLIC Totals")
    file_df = pd.DataFrame(file_data)
    
    # Add filter for GLIC total threshold
    glic_threshold = st.slider("Filter by minimum GLIC total %", 0, 100, 0)
    if glic_threshold > 0:
        file_df = file_df[file_df["GLIC Total"] >= glic_threshold]

    # Industry filter
    all_industries = ["All"] + sorted(list(industry_counts.keys()))
    selected_industry = st.selectbox("Filter by industry:", all_industries)
    
    if selected_industry != "All":
        file_df = file_df[file_df["Industry"] == selected_industry]
    
    # Sort options
    sort_by = st.selectbox("Sort by:", ["GLIC Total", "Company", "Industry"])
    ascending = st.checkbox("Ascending order", value=False)
    file_df = file_df.sort_values(by=sort_by, ascending=ascending)
    
    st.write(file_df)

    # Display industry distribution bar chart
    if industry_counts:  # Only show if we have data
        st.subheader("Industry Distribution")
        industry_df = pd.DataFrame.from_dict(
            industry_counts, 
            orient='index', 
            columns=["Count"]
        ).sort_values("Count", ascending=False)
        st.bar_chart(industry_df)
        
        # Add some statistics
        st.subheader("Summary Statistics")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Companies", len(file_df))
        with col2:
            st.metric("Total Industries", len(industry_counts))
        with col3:
            avg_glic = file_df["GLIC Total"].mean()
            st.metric("Average GLIC Total", f"{avg_glic:.1f}%")

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