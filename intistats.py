import os
import json
import base64
from github import Github
import pandas as pd

def initialize_dashboard_statistics():
    # Replace these with your actual values if running locally
    GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
    GITHUB_REPO = os.environ.get("GITHUB_REPO")
    GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
    GLIC_LIST = ["Khazanah", "EPF", "KWAP", "PNB", "Tabung Haji", "LTAT", "Ministry of Finance"]

    def extract_glic_total(filename):
        try:
            match = re.search(r"_v_(\d+\.\d+)", filename)
            return float(match.group(1)) if match else 0.0
        except Exception:
            return 0.0

    try:
        # Initialize GitHub connection
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        
        # Get all verified JSON files
        contents = repo.get_contents("reports", ref=GITHUB_BRANCH)
        json_files = [
            content for content in contents 
            if content.name.endswith('.json') and '_v_' in content.name
        ]
        
        if not json_files:
            print("No verified JSON files found")
            return False
        
        file_data = []
        total_industries = set()
        
        # Process each JSON file
        for file in json_files:
            try:
                # Get file content
                json_content = base64.b64decode(file.content).decode()
                data = json.loads(json_content)
                
                # Extract GLIC total from filename
                glic_total = extract_glic_total(file.name)
                
                # Get industry
                industry = data.get("industry", "Unknown")
                
                # Add to data collection
                file_data.append({
                    "company": data.get("companyName", "Unknown"),
                    "industry": industry,
                    "glic_total": glic_total,
                    "is_bond_serving": glic_total >= 20
                })
                
                if industry != "Unknown":
                    total_industries.add(industry)
                    
            except Exception as e:
                print(f"Error processing file {file.name}: {str(e)}")
                continue
        
        # Calculate statistics
        df = pd.DataFrame(file_data)
        
        # Calculate industry distribution
        industry_distribution = (
            df.groupby(["industry", "is_bond_serving"])
            .size()
            .unstack(fill_value=0)
            .to_dict()
        )
        
        # Prepare statistics object
        statistics = {
            "total_companies": len(file_data),
            "bond_serving_companies": sum(1 for item in file_data if item["is_bond_serving"]),
            "total_industries": len(total_industries),
            "industries": sorted(list(total_industries)),
            "industry_distribution": industry_distribution,
            "company_details": file_data
        }
        
        # Save to GitHub
        statistics_json = json.dumps(statistics, indent=2)
        try:
            # Try to update existing file
            file = repo.get_contents("statistics.json", ref=GITHUB_BRANCH)
            repo.update_file(
                "statistics.json",
                "Update dashboard statistics",
                statistics_json,
                file.sha,
                branch=GITHUB_BRANCH
            )
        except:
            # Create new file if it doesn't exist
            repo.create_file(
                "statistics.json",
                "Initialize dashboard statistics",
                statistics_json,
                branch=GITHUB_BRANCH
            )
            
        print("Successfully initialized dashboard statistics")
        return True
        
    except Exception as e:
        print(f"Error initializing statistics: {str(e)}")
        return False

if __name__ == "__main__":
    initialize_dashboard_statistics()