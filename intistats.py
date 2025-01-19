import os
import json
import re
import pandas as pd
from pathlib import Path

# Constants
GLIC_LIST = ["Khazanah", "EPF", "KWAP", "PNB", "Tabung Haji", "LTAT", "Ministry of Finance"]
LOCAL_REPORTS_DIR = "reports"  # Directory containing JSON files
OUTPUT_FILE = "statistics.json"  # Output statistics file

def extract_glic_total(filename):
    """Extract GLIC total percentage from filename."""
    try:
        match = re.search(r"_v_(\d+\.\d+)", filename)
        return float(match.group(1)) if match else 0.0
    except Exception:
        return 0.0

def initialize_dashboard_statistics():
    try:
        # Ensure reports directory exists
        reports_dir = Path(LOCAL_REPORTS_DIR)
        if not reports_dir.exists():
            print(f"Reports directory '{LOCAL_REPORTS_DIR}' not found")
            return False
            
        # Get all verified JSON files
        json_files = [f for f in reports_dir.glob("*.json") if "_v_" in f.name]
        
        if not json_files:
            print("No verified JSON files found")
            return False
            
        file_data = []
        total_industries = set()
        
        # Process each JSON file
        for file_path in json_files:
            try:
                # Read JSON file
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Extract GLIC total from filename
                glic_total = extract_glic_total(file_path.name)
                
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
                print(f"Error processing file {file_path.name}: {str(e)}")
                continue
        
        # Calculate statistics using pandas
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
        
        # Save statistics to local file
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(statistics, f, indent=2)
            
        print(f"Successfully initialized dashboard statistics in {OUTPUT_FILE}")
        
        # Print summary
        print("\nSummary:")
        print(f"Total companies processed: {statistics['total_companies']}")
        print(f"Bond serving companies: {statistics['bond_serving_companies']}")
        print(f"Total industries: {statistics['total_industries']}")
        print("\nIndustries found:", ", ".join(statistics['industries']))
        
        return True
        
    except Exception as e:
        print(f"Error initializing statistics: {str(e)}")
        return False

if __name__ == "__main__":
    initialize_dashboard_statistics()