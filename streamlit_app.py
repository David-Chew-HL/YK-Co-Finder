import streamlit as st
import base64
from github import Github
import json
import tempfile
import os
import google.generativeai as genai
from google.ai.generativelanguage_v1beta.types import content
from PyPDF2 import PdfReader

GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
GITHUB_REPO = st.secrets["GITHUB_REPO"]
GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "main")

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

def get_json_files_from_github(exclude_versions=True):
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        contents = repo.get_contents("reports", ref=GITHUB_BRANCH)
        
        json_files = []
        for content in contents:
            if content.name.endswith('.json') and (not exclude_versions or not content.name.endswith(('_v', '_vb'))):
                json_files.append({
                    'name': content.name.replace('.json', ''),
                    'path': content.path,
                    'sha': content.sha
                })
        return json_files
    except Exception as e:
        st.error(f"Error fetching JSON files: {str(e)}")
        return []

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

    json_files = get_json_files_from_github(exclude_versions=True)

    if not json_files:
        st.info("No JSON files found in the repository")
        return

    # Collect unique shareholder names and GLIC associations
    shareholder_data = {}
    for file in json_files:
        try:
            g = Github(GITHUB_TOKEN)
            repo = g.get_repo(GITHUB_REPO)
            file_content = repo.get_contents(file['path'], ref=GITHUB_BRANCH)
            json_content = base64.b64decode(file_content.content).decode()
            data = json.loads(json_content)

            for shareholder in data['topShareholders']:
                shareholder_name = shareholder['shareholderName']
                if shareholder_name not in shareholder_data:
                    shareholder_data[shareholder_name] = {
                        'glicAssociation': shareholder['glicAssociation']
                    }
                else:
                    shareholder_data[shareholder_name]['glicAssociation'] = shareholder['glicAssociation']
        except Exception as e:
            st.error(f"Error loading JSON: {str(e)}")

    # Create the table
    shareholder_table = [["Shareholder Name", "GLIC Association"]]
    for shareholder_name, shareholder_info in shareholder_data.items():
        shareholder_table.append([
            shareholder_name,
            st.selectbox(f"GLIC Association for {shareholder_name}", [
                "Khazanah", "EPF", "KWAP", "PNB", "Tabung Haji", "LTAT", "None"
            ], key=f"{shareholder_name}_glic", index=["Khazanah", "EPF", "KWAP", "PNB", "Tabung Haji", "LTAT", "None"].index(shareholder_info['glicAssociation']))
        ])

    st.table(shareholder_table)

    if st.button("Verify"):
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)

        for file in json_files:
            try:
                file_content = repo.get_contents(file['path'], ref=GITHUB_BRANCH)
                json_content = base64.b64decode(file_content.content).decode()
                data = json.loads(json_content)

                for shareholder in data['topShareholders']:
                    shareholder_name = shareholder['shareholderName']
                    new_glic_association = shareholder_table[shareholder_table.index([shareholder_name, _])+1][1]
                    if new_glic_association != shareholder['glicAssociation']:
                        shareholder['glicAssociation'] = new_glic_association

                # Calculate the sum of percentages held by non-None GLICs
                non_none_glic_total = sum(
                    shareholder['percentageHeld']
                    for shareholder in data['topShareholders']
                    if shareholder['glicAssociation'] != 'None'
                )

                # Update the file name if the non-None GLIC total exceeds 20
                if non_none_glic_total > 20:
                    new_file_name = f"{file['name']}_v_{non_none_glic_total:.1f}.json"
                else:
                    new_file_name = f"{file['name']}_v.json"

                new_file_path = os.path.join("reports", new_file_name)
                update_json_file(repo, new_file_path, json.dumps(data, indent=2))
            except Exception as e:
                st.error(f"Error updating file: {str(e)}")

        st.success("JSON files updated and verified.")         
            
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
    
    json_files = get_json_files_from_github()
    
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

def main():
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", ["Upload PDF", "View Extracted Information", "Verify Extracted Information"])
    
    if page == "Upload PDF":
        upload_page()
    elif page == "View Extracted Information":
        view_page()
    else:
        verify_page()


if __name__ == "__main__":
    main()