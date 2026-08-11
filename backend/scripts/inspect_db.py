import os
import json
import urllib.parse
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect

# Load environment variables
load_dotenv()

def inspect_database():
    print("==================================================")
    print("SBI CMS - SQL Server Schema Inspector (Auto-Encoder)")
    print("==================================================")

    # Read granular connection parameters
    db_user = os.getenv("DB_USER", "sa")
    password = os.getenv("DB_PASSWORD", "YOUR_PASSWORD")
    host = os.getenv("DB_HOST", "198.38.87.117")
    port = os.getenv("DB_PORT", "1433")
    dbname = os.getenv("DB_NAME", "OmniDash_CMS")

    if password == "YOUR_PASSWORD":
        print("[WARNING] DB_PASSWORD is not configured in .env.")
        password = input("Enter password for SQL Server 'sa' user: ").strip()
        if not password:
            print("[ERROR] Password cannot be empty.")
            return
            
        # Update .env file automatically
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()
            with open(env_path, "w") as f:
                for line in lines:
                    if line.startswith("DB_PASSWORD="):
                        f.write(f"DB_PASSWORD={password}\n")
                    else:
                        f.write(line)
            print("[INFO] Updated DB_PASSWORD in .env!")
        else:
            with open(env_path, "w") as f:
                f.write(f"DB_USER={db_user}\n")
                f.write(f"DB_PASSWORD={password}\n")
                f.write(f"DB_HOST={host}\n")
                f.write(f"DB_PORT={port}\n")
                f.write(f"DB_NAME={dbname}\n")
            print("[INFO] Created .env with database configurations.")

    # Auto-encode special characters in the password (e.g. '@' -> '%40')
    encoded_password = urllib.parse.quote_plus(password)
    db_url = f"mssql+pymssql://{db_user}:{encoded_password}@{host}:{port}/{dbname}"

    print(f"\n[INFO] Connecting to: {host}:{port} / Database: {dbname}...")
    
    try:
        engine = create_engine(db_url)
        inspector = inspect(engine)
        
        tables = inspector.get_table_names()
        if not tables:
            print("[WARNING] Connection successful, but no tables found in database.")
            return
            
        print(f"[SUCCESS] Connected! Found {len(tables)} tables.\n")
        
        schema_summary = {}
        
        for table_name in tables:
            print(f"Table: {table_name}")
            columns = inspector.get_columns(table_name)
            column_names = []
            for col in columns:
                col_type = str(col['type'])
                is_nullable = "NULL" if col['nullable'] else "NOT NULL"
                print(f"  - {col['name']} ({col_type}) {is_nullable}")
                column_names.append(f"{col['name']} ({col_type})")
            
            schema_summary[table_name] = column_names
            print("-" * 30)
            
        # Write schema locally
        schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema_summary.json")
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(schema_summary, f, indent=2)
        print(f"\n[SUCCESS] Schema summary written to {schema_path}")
        
    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")
        print("Please check: ")
        print("1. If your password is correct (any '@' characters are now handled automatically).")
        print("2. If the SQL Server host '198.38.87.117' is reachable and port 1433 is open.")
        print("3. If 'SQL Server Authentication' is enabled on the server.")

if __name__ == "__main__":
    inspect_database()
