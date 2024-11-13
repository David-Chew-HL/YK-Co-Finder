import streamlit as st
import base64
from github import Github
import json
import tempfile
import os
import google.generativeai as genai
from google.ai.generativelanguage_v1beta.types import content
from PyPDF2 import PdfReader
import pandas as pd
import re
from io import StringIO

GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
GITHUB_REPO = st.secrets["GITHUB_REPO"]
GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "main")
GLIC_LIST = ["Khazanah", "EPF", "KWAP", "PNB", "Tabung Haji", "LTAT"]

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

model = genai.GenerativeModel(
  model_name="gemini-1.5-flash-002",
  generation_config=generation_config,
)

def upload_to_github(json_data, filename,year):
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        
        # Ensure pdfs directory exists
        try:
            repo.get_contents("reports", ref=GITHUB_BRANCH)
        except:
            repo.create_file("reports/.gitkeep", "Create reports directory", "", branch=GITHUB_BRANCH)
        
        #content = base64.b64encode(json.dumps(json_data).encode()).decode()
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

                # Get the latest commit SHA
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
                is_verified = "_v_" in content.name
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

def update_json_file(repo, file_path, content, branch=GITHUB_BRANCH):
    try:
        file = repo.get_contents(file_path, ref=branch)
        repo.update_file(
            file_path,
            f"Update {os.path.basename(file_path)}",
            content,
            file.sha,
            branch=branch
        )
        return True, "File updated successfully"
    except Exception as e:
        if "404" in str(e):
            repo.create_file(
                file_path,
                f"Add {os.path.basename(file_path)}",
                content,
                branch=branch
            )
            return True, "File created successfully"
        else:
            raise e

def verify_page():
    st.title("Verify Extracted Information")
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
            
            new_verifications = []
            
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
                    
                    # Find the shareholder in the original list and update it
                    for s in shareholders:
                        if s['shareholderName'] == shareholder_name:
                            if s['glicAssociation'] != glic_selection:
                                s['glicAssociation'] = glic_selection
                                modified = True
                                new_verifications.append({
                                    "shareholderName": shareholder_name,
                                    "glicAssociation": glic_selection
                                })
                            break

            if st.button("Approve Verification"):
                success = True
                # First, save verified shareholders
                if new_verifications:
                    new_verified = pd.DataFrame(new_verifications)
                    if not add_verified_shareholders(repo, new_verified):
                        st.error("Failed to update verified shareholders CSV")
                        success = False
                
                if success:
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
                        
                        # Delete the old unverified file
                        repo.delete_file(
                            file['path'],
                            f"Delete unverified file {file['name']}",
                            file['sha'],
                            branch=GITHUB_BRANCH
                        )
                        
                        st.success(f"Successfully verified {data['companyName']} and updated files")
                        verification_completed = True
                        # Force a page refresh to show updated files
                        st.experimental_rerun()
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
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        
        try:
            file_content = repo.get_contents("verified_shareholders.csv", ref=GITHUB_BRANCH)
            csv_data = base64.b64decode(file_content.content).decode()
            verified_shareholders = pd.read_csv(StringIO(csv_data))
        except:
            # If file doesn't exist, create new DataFrame
            verified_shareholders = pd.DataFrame(columns=["shareholderName", "glicAssociation"])
        
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
            file_content = repo.get_contents("verified_shareholders.csv", ref=GITHUB_BRANCH)
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
    
    if uploaded_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_file.flush()
            
            reader = PdfReader(tmp_file.name)
            text = ""
            for page in reader.pages:
                text += page.extract_text()
        
        st.subheader("Extract Information")
        if st.button("Extract Information"):
            with st.spinner("Extracting Information..."):    
                chat_session = model.start_chat()
                response = chat_session.send_message("Extract the following information from the provided text of the annual report and format it in JSON:\n\n\nCompany full name.\nYear of the report.\nIndustry of the company (choose one from the following: Automobiles, Banks, Capital Goods, Commercial Services, Consumer Durables, Consumer Retailing, Consumer Services, Diversified Financials, Energy, Food, Beverage, Tobacco, Healthcare, Household, Insurance, Materials, Media, Pharmaceuticals, Biotech, Real Estate, Real Estate Management and Development, Retail, Semiconductors, Software, Tech, Telecom, Transportation, Utilities).\nA brief description of the company's business.\nTop Shareholders:\nFor each of the top 30 shareholders, include:\nFull name of the shareholder.\nIf the shareholder is associated with any of the following six Malaysian Government-Linked Investment Companies (GLICs), specify which one: Khazanah Nasional Berhad (Khazanah), Employees Provident Fund (EPF), Kumpulan Wang Persaraan (Diperbadankan) [KWAP], Permodalan Nasional Berhad (PNB), Lembaga Tabung Haji, or Lembaga Tabung Angkatan Tentera (LTAT). \nReturn this information in the JSON format:\n\njson\nCopy code\n{\n  \"companyName\": \"Company full name\",\n  \"reportYear\": Year,\n  \"industry\": \"Industry name from the provided list\",\n  \"companyDescription\": \"Brief description of company\",\n  \"topShareholders\": [\n    {\n      \"shareholderName\": \"Shareholder's name\",\n      \"glicAssociation\": \"GLIC name if applicable, otherwise None\",\n      \"percentageHeld\": Percentage of shares held\n    },\n    ...\n  ]\n}\nIf a shareholder is not associated with any of the specified GLICs, set the \"glicAssociation\" field to None in the JSON output. If the shareholder is a subsidiary or affiliate of a GLIC (e.g., \"Amanah Trustees\" under \"PNB\"), note the primary GLIC association in the \"glicAssociation\" field.\"  Annual Report: \"" + text)
                output_json = json.loads(response.text)
                
                # Upload the JSON to GitHub
                file_name = output_json["companyName"]
                year = output_json["reportYear"]
                upload_to_github(output_json, file_name, year)
                
                st.success("Information extracted and uploaded to GitHub!")

def view_page():
    st.title("View Extracted Information")
    
    json_files = get_json_files_from_github(exclude_verified=True)
    
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