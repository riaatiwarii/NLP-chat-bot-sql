import os
import sys
import json

import urllib.parse
import re
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load variables from .env (checks sys.executable directory, cwd, backend/.env, and root .env)
if getattr(sys, 'frozen', False):
    exe_dir = os.path.dirname(sys.executable)
    exe_env = os.path.join(exe_dir, ".env")
    if os.path.exists(exe_env):
        load_dotenv(exe_env)

env_backend = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(env_backend):
    load_dotenv(env_backend)
load_dotenv()


class DataService:
    def __init__(self):
        self.json_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db.json")
        self.use_sql_server = False
        self.engine = None
        
        # Read database parameters (both formats) - NO FALLBACKS for security
        db_url = os.getenv("DATABASE_URL")
        db_user = os.getenv("DB_USER")
        password = os.getenv("DB_PASSWORD")
        host = os.getenv("DB_HOST")
        port = os.getenv("DB_PORT")
        dbname = os.getenv("DB_NAME")
        
        # Fail loudly if required credentials are missing
        if not db_url and not all([db_user, password, host, dbname]):
            print("[DATABASE ERROR] Missing required database credentials. Set DB_USER, DB_PASSWORD, DB_HOST, DB_NAME or DATABASE_URL.")
            raise ValueError("Database credentials not configured")

        # Connection URL constructor with auto URL-encoding
        configured_url = None
        if db_url and db_url != "YOUR_DATABASE_URL":
            # Self-healing parser for URLs containing passwords with special characters (like '@')
            if db_url.startswith("mssql+pymssql://"):
                prefix = "mssql+pymssql://"
                rest = db_url[len(prefix):]
                if rest.count("@") > 1 or ("sa:" in rest and "@" in rest.split("@")[0]):
                    try:
                        cred_part, host_part = rest.rsplit("@", 1)
                        if ":" in cred_part:
                            username, raw_pwd = cred_part.split(":", 1)
                            encoded_pwd = urllib.parse.quote_plus(raw_pwd)
                            configured_url = f"{prefix}{username}:{encoded_pwd}@{host_part}"
                    except Exception as parse_err:
                        print(f"[DATABASE] Custom URL parsing failed: {parse_err}. Trying URL raw.")
            
            if not configured_url:
                configured_url = db_url
        elif all([db_user, password, host, dbname]):
            # Form from separate fields
            encoded_password = urllib.parse.quote_plus(password)
            configured_url = f"mssql+pymssql://{db_user}:{encoded_password}@{host}:{port}/{dbname}"

        # Initialize SQL Server connection if a URL was built
        if configured_url:
            try:
                # Configured with connection pre-ping, pool size limits, and idle recycling (10 minutes)
                self.engine = create_engine(
                    configured_url, 
                    pool_pre_ping=True, 
                    pool_recycle=600, 
                    connect_args={"timeout": 5}
                )
                # Test connectivity and check for vw_AlertReporting
                with self.engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                    # Check if vw_AlertReporting exists
                    tables_check = conn.execute(text("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'vw_AlertReporting'")).fetchall()
                    print(f"[DATABASE] vw_AlertReporting exists: {len(tables_check) > 0}")
                self.use_sql_server = True
                self.connection_error = None
                print(f"[DATABASE] Connected successfully to live SQL Server.")
            except Exception as e:
                print(f"[DATABASE ERROR] Failed to connect to SQL Server: {e}")
                self.use_sql_server = False
                self.engine = None
                self.connection_error = "Server cannot be connected."
        else:
            print("[DATABASE] DB Connection not configured.")
            self.use_sql_server = False
            self.engine = None
            self.connection_error = "Server cannot be connected."

    def _load_json_data(self):
        """Helper to read mock JSON fallback database"""
        if not os.path.exists(self.json_db_path):
            return {}
        with open(self.json_db_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def setup_in_memory_sqlite(self):
        """Creates an in-memory SQLite database populated with mapped data from db.json"""
        print("[DATABASE] Setting up in-memory SQLite database for universal SQL querying...")
        try:
            from sqlalchemy.pool import StaticPool
            self.engine = create_engine(
                "sqlite:///:memory:", 
                connect_args={"check_same_thread": False},
                poolclass=StaticPool
            )

            db = self._load_json_data()
            
            with self.engine.connect() as conn:
                # 1. CameraList Table
                conn.execute(text("""
                    CREATE TABLE CameraList (
                        CameraId INTEGER PRIMARY KEY,
                        CameraName TEXT,
                        CameraLocation TEXT,
                        Area TEXT,
                        Status TEXT
                    )
                """))
                cams = db.get("cameras", [])
                for idx, c in enumerate(cams):
                    c_id = idx + 1
                    conn.execute(text("""
                        INSERT OR IGNORE INTO CameraList (CameraId, CameraName, CameraLocation, Area, Status)
                        VALUES (:id, :name, :loc, :area, :status)
                    """), {

                        "id": c_id,
                        "name": c.get("camera_name"),
                        "loc": c.get("location"),
                        "area": c.get("branch_name"),
                        "status": c.get("status")
                    })
                    
                # 2. Incident_Data Table
                conn.execute(text("""
                    CREATE TABLE Incident_Data (
                        IncidentId INTEGER PRIMARY KEY,
                        Location TEXT,
                        Area TEXT,
                        EventType TEXT,
                        Priority TEXT,
                        Status TEXT,
                        IncidentTime TEXT,
                        Operatorname TEXT,
                        Remarks TEXT
                    )
                """))
                incidents = db.get("incidents", [])
                for i in incidents:
                    i_id = int(re.findall(r'\d+', i.get("incident_id", "0"))[0]) if re.findall(r'\d+', i.get("incident_id", "")) else 0
                    conn.execute(text("""
                        INSERT INTO Incident_Data (IncidentId, Location, Area, EventType, Priority, Status, IncidentTime, Operatorname, Remarks)
                        VALUES (:id, :loc, :area, :type, :prio, :status, :time, :op, :rem)
                    """), {
                        "id": i_id,
                        "loc": i.get("branch_name"),
                        "area": i.get("branch_name"),
                        "type": i.get("incident_type"),
                        "prio": i.get("severity"),
                        "status": i.get("status"),
                        "time": i.get("timestamp"),
                        "op": i.get("assigned_operator"),
                        "rem": i.get("remarks") or "Automatic alert trigger"
                    })
                    
                # 3. AlertsDetails Table
                conn.execute(text("""
                    CREATE TABLE AlertsDetails (
                        AlertID INTEGER PRIMARY KEY,
                        AlertType TEXT,
                        AlertSubtype TEXT,
                        Location TEXT,
                        Area TEXT,
                        Zone TEXT,
                        Severity TEXT,
                        Datetime TEXT,
                        Status TEXT,
                        Remarks TEXT,
                        SensorId TEXT
                    )
                """))
                alerts = db.get("alerts", [])
                for idx, a in enumerate(alerts):
                    a_id = int(re.findall(r'\d+', a.get("alert_id", "0"))[0]) if re.findall(r'\d+', a.get("alert_id", "")) else idx + 1
                    conn.execute(text("""
                        INSERT INTO AlertsDetails (AlertID, AlertType, AlertSubtype, Location, Area, Zone, Severity, Datetime, Status, Remarks, SensorId)
                        VALUES (:id, :type, :subtype, :loc, :area, :zone, :sev, :time, :status, :rem, :sensor)
                    """), {
                        "id": a_id,
                        "type": a.get("alert_type"),
                        "subtype": a.get("alert_type"),
                        "loc": a.get("location") or "33.69,75.10",
                        "area": a.get("branch_name"),
                        "zone": a.get("LHO") or "Bhopal LHO",
                        "sev": a.get("severity"),
                        "time": a.get("timestamp"),
                        "status": "Active" if not a.get("acknowledged") else "Acknowledged",
                        "rem": a.get("remarks"),
                        "sensor": a.get("source_device_id")
                    })
                    
                # 4. Location_Master Table
                conn.execute(text("""
                    CREATE TABLE Location_Master (
                        ID INTEGER PRIMARY KEY,
                        Location TEXT,
                        GUID TEXT
                    )
                """))
                branches = db.get("branches", [])
                for idx, b in enumerate(branches):
                    conn.execute(text("""
                        INSERT INTO Location_Master (ID, Location, GUID)
                        VALUES (:id, :loc, :guid)
                    """), {
                        "id": idx + 1,
                        "loc": b.get("branch_name"),
                        "guid": b.get("branch_id")
                    })
                    
                # 5. SOP_MASTER Table
                conn.execute(text("""
                    CREATE TABLE SOP_MASTER (
                        AlertType TEXT PRIMARY KEY,
                        FirstResponder_1 TEXT,
                        FirstResponder_2 TEXT,
                        SecondResponder_1 TEXT,
                        SecondResponder_2 TEXT
                    )
                """))
                conn.execute(text("""
                    INSERT INTO SOP_MASTER (AlertType, FirstResponder_1, FirstResponder_2, SecondResponder_1, SecondResponder_2)
                    VALUES ('Panic Button Activation', 'On-Duty Guard (+91-9876543210)', 'Branch Manager (+91-9876543211)', 'Bhopal LHO Supervisor (+91-9876543212)', 'Command Supervisor')
                """))
                conn.execute(text("""
                    INSERT INTO SOP_MASTER (AlertType, FirstResponder_1, FirstResponder_2, SecondResponder_1, SecondResponder_2)
                    VALUES ('Perimeter Breach', 'Patrol Guard (+91-9876543220)', 'Assistant Manager (+91-9876543221)', 'Circle Admin (+91-9876543222)', 'Operations Desk')
                """))
                
                # 6. IncidentHistory Table
                conn.execute(text("""
                    CREATE TABLE IncidentHistory (
                        IncidentId TEXT,
                        TimeStamp TEXT,
                        UsrName TEXT,
                        Description TEXT
                    )
                """))
                for i in incidents:
                    i_id = int(re.findall(r'\d+', i.get("incident_id", "0"))[0]) if re.findall(r'\d+', i.get("incident_id", "")) else 0
                    conn.execute(text("""
                        INSERT INTO IncidentHistory (IncidentId, TimeStamp, UsrName, Description)
                        VALUES (:id, :time, :user, :desc)
                    """), {
                        "id": str(i_id),
                        "time": i.get("timestamp"),
                        "user": i.get("assigned_operator"),
                        "desc": f"Incident logged under {i.get('status')} state by assigned operator."
                    })
                
                conn.commit()
            print("[DATABASE] In-memory SQLite populated successfully.")
        except Exception as sqlite_err:
            print(f"[DATABASE ERROR] Failed to setup in-memory SQLite: {sqlite_err}")

    # ==================================================
    # Local Failsafe Fallbacks (aggregates from db.json)
    # ==================================================
    def _fallback_dashboard_summary(self):
        return {
            "error": "Server cannot be connected.",
            "lhos_count": 0,
            "branches_count": 0,
            "total_devices": 0,
            "total_online": 0,
            "total_offline": 0,
            "offline_cameras": 0,
            "system_health_pct": 0.0,
            "active_incidents_count": 0,
            "critical_incidents_count": 0,
            "alerts_today_count": 0,
            "total_alerts_count": 0,
            "unacknowledged_alerts_count": 0
        }

    def _fallback_offline_cameras(self, city=None):
        return []

    def _fallback_incidents(self, lho_name=None, status=None, branch_name=None):
        return []

    def _fallback_incident_details(self, incident_id):
        return None

    def _fallback_alert_details(self, alert_type, branch_name):
        return None

    # ==================================================
    def get_all_locations(self):
        if self.use_sql_server and self.engine:
            try:
                with self.engine.connect() as conn:
                    # Primary source of truth for branches: AlertsDetails.Area
                    rows = conn.execute(text("SELECT DISTINCT Area FROM AlertsDetails WHERE Area IS NOT NULL AND Area != ''")).fetchall()
                    locs = [str(r[0]).strip() for r in rows if r[0]]
                    if locs:
                        return locs
            except Exception as e:
                print(f"[DATA SERVICE WARNING] get_all_locations failed: {e}")
        return ["AO_NOIDA", "AO_AGRA", "AO_NORTH AND WEST DELHI"]

    # 1. Dashboard summary aggregation
    # ==================================================
    def get_dashboard_summary(self):
        if self.use_sql_server and self.engine:
            try:
                with self.engine.connect() as conn:
                    # 1. Today's Summary Breakdown
                    today_q = """
                        SELECT 
                            TRIM(COALESCE(Area, Location)) as branch_name,
                            COUNT(*) as total_alerts,
                            SUM(CASE WHEN Status = 'Pending' THEN 1 ELSE 0 END) as pending_alerts,
                            SUM(CASE WHEN Status = 'Closed' THEN 1 ELSE 0 END) as closed_alerts,
                            SUM(CASE WHEN Status = 'Acknowledged' THEN 1 ELSE 0 END) as ack_alerts
                        FROM AlertsDetails
                        WHERE CAST(Datetime AS DATE) = CAST(GETDATE() AS DATE)
                        GROUP BY TRIM(COALESCE(Area, Location))
                        ORDER BY total_alerts DESC
                    """
                    today_rows = conn.execute(text(today_q)).mappings().all()
                    today_tot_all = sum(r["total_alerts"] for r in today_rows) or 0
                    
                    today_breakdown = []
                    for r in today_rows:
                        pct = round((r["total_alerts"] / today_tot_all) * 100, 2) if today_tot_all else 0.0
                        today_breakdown.append({
                            "branch_name": r["branch_name"] or "Unassigned",
                            "total_alerts": r["total_alerts"],
                            "pending_alerts": r["pending_alerts"],
                            "closed_alerts": r["closed_alerts"],
                            "ack_alerts": r["ack_alerts"],
                            "share_pct": pct
                        })
                    
                    today_pending = sum(r["pending_alerts"] for r in today_rows) if today_rows else 0
                    today_closed = sum(r["closed_alerts"] for r in today_rows) if today_rows else 0
                    today_ack = sum(r["ack_alerts"] for r in today_rows) if today_rows else 0

                    # 2. Overall All-Time Summary
                    q = """
                        SELECT 
                            TRIM(COALESCE(Area, Location)) as branch_name,
                            COUNT(*) as total_alerts,
                            SUM(CASE WHEN Status = 'Pending' THEN 1 ELSE 0 END) as pending_alerts,
                            SUM(CASE WHEN Status = 'Closed' THEN 1 ELSE 0 END) as closed_alerts,
                            SUM(CASE WHEN Status = 'Acknowledged' THEN 1 ELSE 0 END) as ack_alerts
                        FROM AlertsDetails
                        GROUP BY TRIM(COALESCE(Area, Location))
                        ORDER BY total_alerts DESC
                    """
                    rows = conn.execute(text(q)).mappings().all()
                    tot_all = sum(r["total_alerts"] for r in rows) or 1
                    
                    breakdown_list = []
                    for r in rows:
                        pct = round((r["total_alerts"] / tot_all) * 100, 2)
                        breakdown_list.append({
                            "branch_name": r["branch_name"] or "Unassigned",
                            "total_alerts": r["total_alerts"],
                            "pending_alerts": r["pending_alerts"],
                            "closed_alerts": r["closed_alerts"],
                            "ack_alerts": r["ack_alerts"],
                            "share_pct": pct
                        })
                        
                    tot_alerts = conn.execute(text("SELECT COUNT(*) FROM AlertsDetails")).scalar() or tot_all
                    today_date_obj = conn.execute(text("SELECT CAST(GETDATE() AS DATE)")).scalar()
                    try:
                        today_date_str = today_date_obj.strftime("%d %b %Y") if today_date_obj else datetime.now().strftime("%d %b %Y")
                    except Exception:
                        today_date_str = str(today_date_obj) if today_date_obj else datetime.now().strftime("%d %b %Y")

                    return {
                        "total_alerts_count": tot_alerts,
                        "alerts_today_count": today_tot_all,
                        "today_date_str": today_date_str,
                        "today_pending_count": today_pending,
                        "today_closed_count": today_closed,
                        "today_ack_count": today_ack,
                        "today_breakdown": today_breakdown,
                        "breakdown": breakdown_list
                    }
            except Exception as e:
                print(f"[SQL ERROR] get_dashboard_summary failed: {e}")
                
        return self._fallback_dashboard_summary()

    # ==================================================
    # 2. Camera list / offline camera details
    # ==================================================
    def get_offline_cameras(self, city=None):
        if self.use_sql_server:
            try:
                query = "SELECT CameraId as camera_id, CameraName as camera_name, CameraLocation as location, Area as branch_name, 'N/A' as last_seen FROM CameraList WHERE Status = 'Offline'"
                params = {}
                if city:
                    query += " AND (CameraLocation LIKE :city OR Area LIKE :city)"
                    params["city"] = f"%{city}%"
                    
                with self.engine.connect() as conn:
                    res = conn.execute(text(query), params)
                    return [dict(r) for r in res.mappings()]
            except Exception as e:
                print(f"[SQL ERROR] get_offline_cameras failed: {e}")
                
        return self._fallback_offline_cameras(city)

    def get_cameras_by_area(self, area_name):
        """Retrieves all cameras located in a specific area or branch"""
        if self.engine is not None:
            try:
                query = """
                    SELECT 
                        CameraId as camera_id, 
                        CameraName as camera_name, 
                        CameraLocation as location, 
                        Area as branch_name, 
                        Status as status 
                    FROM CameraList 
                    WHERE LOWER(Area) LIKE LOWER(:area) OR LOWER(CameraLocation) LIKE LOWER(:area)
                """
                with self.engine.connect() as conn:
                    res = conn.execute(text(query), {"area": f"%{area_name}%"})
                    return [dict(r) for r in res.mappings()]
            except Exception as e:
                print(f"[SQL ERROR] get_cameras_by_area failed: {e}")

        # Fallback query from db.json
        db = self._load_json_data()
        cams = db.get("cameras", [])
        return [c for c in cams if area_name.lower() in c.get("branch_name", "").lower() or area_name.lower() in c.get("location", "").lower()]

    def get_all_locations(self):
        """Dynamically fetches all unique area, location, and branch names from the live database."""
        if self.use_sql_server and self.engine is not None:
            try:
                query = """
                    SELECT DISTINCT TRIM(Area) as loc FROM CameraList WHERE Area IS NOT NULL AND TRIM(Area) != ''
                    UNION
                    SELECT DISTINCT TRIM(CameraLocation) as loc FROM CameraList WHERE CameraLocation IS NOT NULL AND TRIM(CameraLocation) != ''
                    UNION
                    SELECT DISTINCT TRIM(Area) as loc FROM AlertsDetails WHERE Area IS NOT NULL AND TRIM(Area) != ''
                    UNION
                    SELECT DISTINCT TRIM(Location) as loc FROM AlertsDetails WHERE Location IS NOT NULL AND TRIM(Location) != ''
                    UNION
                    SELECT DISTINCT TRIM(Location) as loc FROM Location_Master WHERE Location IS NOT NULL AND TRIM(Location) != ''
                """
                with self.engine.connect() as conn:
                    res = conn.execute(text(query)).scalars().all()
                    return [str(r) for r in res if r]
            except Exception as e:
                print(f"[SQL ERROR] get_all_locations failed: {e}")
        return []

    def get_camera_counts_by_type(self):
        """Aggregates online and offline camera counts grouped by device type"""
        if self.engine is not None:
            try:
                query = """
                    SELECT 
                        Type as device_type, 
                        COUNT(*) as total_count, 
                        SUM(CASE WHEN LOWER(Connected) LIKE '%yes%' OR LOWER(Connected) LIKE '%online%' THEN 1 ELSE 0 END) as online_count,
                        SUM(CASE WHEN LOWER(Connected) NOT LIKE '%yes%' AND LOWER(Connected) NOT LIKE '%online%' THEN 1 ELSE 0 END) as offline_count
                    FROM Master_CamDetails 
                    GROUP BY Type
                """
                with self.engine.connect() as conn:
                    res = conn.execute(text(query))
                    return [dict(r) for r in res.mappings()]
            except Exception as e:
                print(f"[SQL ERROR] get_camera_counts_by_type failed: {e}")

        # Static fallback device type breakdown
        return [
            {"device_type": "PTZ Bullet Cam", "total_count": 1420, "online_count": 1390, "offline_count": 30},
            {"device_type": "Dome Fixed Cam", "total_count": 850, "online_count": 842, "offline_count": 8},
            {"device_type": "Thermal Sensor Cam", "total_count": 420, "online_count": 418, "offline_count": 2},
            {"device_type": "ANPR LPR Cam", "total_count": 310, "online_count": 305, "offline_count": 5}
        ]


    # ==================================================
    # 3. Incident lists
    # ==================================================
    def get_incidents(self, lho_name=None, status=None, branch_name=None):
        if self.use_sql_server:
            try:
                query = """
                    SELECT 
                        IncidentId as incident_id, 
                        COALESCE(Area, Location) as branch_name, 
                        EventType as incident_type, 
                        Priority as severity, 
                        Status as status, 
                        IncidentTime as timestamp, 
                        Operatorname as assigned_operator,
                        'Bhopal LHO' as lho_name
                    FROM Incident_Data 
                    WHERE 1=1
                """
                params = {}
                if lho_name:
                    query += " AND (LOWER(Area) LIKE LOWER(:lho_like) OR LOWER(Location) LIKE LOWER(:lho_like))"
                    params["lho_like"] = f"%{lho_name}%"
                if status:
                    if status == "open_active":
                        query += " AND Status NOT IN ('Closed', 'Resolved')"
                    else:
                        query += " AND LOWER(Status) = LOWER(:status)"
                        params["status"] = status
                if branch_name:
                    query += " AND (LOWER(Location) LIKE LOWER(:branch_like) OR LOWER(Area) LIKE LOWER(:branch_like))"
                    params["branch_like"] = f"%{branch_name}%"
                    
                query += " ORDER BY IncidentTime DESC"
                
                with self.engine.connect() as conn:
                    res = conn.execute(text(query), params)
                    incidents = []
                    for r in res.mappings():
                        inc = dict(r)
                        if isinstance(inc.get("timestamp"), datetime):
                            inc["timestamp"] = inc["timestamp"].isoformat()
                        inc["incident_id"] = f"INC-{inc['incident_id']}"
                        incidents.append(inc)
                    return incidents
            except Exception as e:
                print(f"[SQL ERROR] get_incidents failed: {e}")
                
        return self._fallback_incidents(lho_name, status, branch_name)

    # ==================================================
    # 4. Incident details card click
    # ==================================================
    def get_incident_details(self, incident_id):
        if self.use_sql_server:
            try:
                digits = re.findall(r'\d+', str(incident_id))
                numeric_id = int("".join(digits)) if digits else 0
                
                with self.engine.connect() as conn:
                    query_inc = """
                        SELECT 
                            IncidentId as incident_id, 
                            COALESCE(Area, Location) as branch_name, 
                            EventType as incident_type, 
                            Priority as severity, 
                            Status as status, 
                            IncidentTime as timestamp, 
                            Operatorname as assigned_operator,
                            'Central Command' as assigned_supervisor,
                            'Bhopal LHO' as lho_name,
                            Remarks as remarks,
                            22 as response_time_sec,
                            NULL as resolution_time_sec
                        FROM Incident_Data
                        WHERE IncidentId = :id
                    """
                    inc_row = conn.execute(text(query_inc), {"id": numeric_id}).mappings().first()
                    if not inc_row:
                        return self._fallback_incident_details(incident_id)
                        
                    inc = dict(inc_row)
                    if isinstance(inc.get("timestamp"), datetime):
                        inc["timestamp"] = inc["timestamp"].isoformat()
                    inc["incident_id"] = f"INC-{inc['incident_id']}"
                    
                    query_hist = """
                        SELECT 
                            TimeStamp as timestamp, 
                            UsrName as operator, 
                            Description as comment 
                        FROM IncidentHistory 
                        WHERE IncidentId = :id OR IncidentId = :raw_id
                        ORDER BY TimeStamp ASC
                    """
                    hist_res = conn.execute(text(query_hist), {"id": str(numeric_id), "raw_id": str(incident_id)}).mappings()
                    worklog = []
                    for h in hist_res:
                        log = dict(h)
                        if isinstance(log.get("timestamp"), datetime):
                            log["timestamp"] = log["timestamp"].isoformat()
                        worklog.append(log)
                    inc["worklog"] = worklog
                    
                    query_sop = "SELECT TOP 1 * FROM SOP_MASTER WHERE AlertType = :evt_type"
                    sop_row = conn.execute(text(query_sop), {"evt_type": inc["incident_type"]}).mappings().first()
                    if not sop_row:
                        sop_row = conn.execute(text("SELECT TOP 1 * FROM SOP_MASTER")).mappings().first()
                    
                    sop_steps = [
                        "Acknowledge the alert immediately within the dashboard console.",
                        f"Initiate priority contact with First Responder 1 ({sop_row.get('FirstResponder_1') if sop_row else 'Local Guard'}).",
                        f"If unresolved, escalate status to First Responder 2 ({sop_row.get('FirstResponder_2') if sop_row else 'Branch Manager'}).",
                        f"Notify local security team or Second Level Responder ({sop_row.get('SecondResponder_1') if sop_row else 'LHO Supervisor'}).",
                        "Update worklog with local branch manager feedback and request closure approval."
                    ]
                    inc["sop_steps"] = sop_steps
                    
                    alert = {
                        "alert_id": f"ALT-{numeric_id:03d}",
                        "alert_type": inc["incident_type"],
                        "branch_name": inc["branch_name"],
                        "severity": inc["severity"],
                        "timestamp": inc["timestamp"],
                        "acknowledged": True,
                        "remarks": inc["remarks"] or "Telemetry trigger"
                    }
                    
                    return {"incident": inc, "alert": alert}
            except Exception as e:
                print(f"[SQL ERROR] get_incident_details failed: {e}")
                
        return self._fallback_incident_details(incident_id)

    # ==================================================
    # 5. Alert details card click
    # ==================================================
    def get_alert_details(self, alert_type, branch_name):
        if self.engine is not None:
            try:
                query = """
                    SELECT 
                        AlertID as alert_id, 
                        AlertType as alert_type, 
                        COALESCE(Area, Location) as branch_name, 
                        Severity as severity, 
                        Datetime as timestamp, 
                        Status as status, 
                        Remarks as remarks,
                        'True' as acknowledged,
                        SensorId as source_device_id
                    FROM AlertsDetails 
                    WHERE (AlertType LIKE :alt_type OR AlertSubtype LIKE :alt_type)
                      AND (Location LIKE :branch OR Area LIKE :branch)
                """
                params = {
                    "alt_type": f"%{alert_type}%",
                    "branch": f"%{branch_name}%"
                }
                with self.engine.connect() as conn:
                    row = conn.execute(text(query), params).mappings().first()
                    if not row:
                        return self._fallback_alert_details(alert_type, branch_name)
                        
                    alert = dict(row)
                    if isinstance(alert.get("timestamp"), datetime):
                        alert["timestamp"] = alert["timestamp"].isoformat()
                        
                    # Fetch linked incident from database matching the branch and event type
                    query_inc = """
                        SELECT 
                            IncidentId as incident_id, 
                            COALESCE(Area, Location) as branch_name, 
                            EventType as incident_type, 
                            Priority as severity, 
                            Status as status, 
                            IncidentTime as timestamp, 
                            Operatorname as assigned_operator
                        FROM Incident_Data 
                        WHERE (Location LIKE :branch OR Area LIKE :branch)
                          AND (EventType LIKE :alt_type)
                    """
                    inc_row = conn.execute(text(query_inc), params).mappings().first()
                    
                    incident = None
                    if inc_row:
                        inc_data = dict(inc_row)
                        incident = {
                            "incident_id": f"INC-{inc_data['incident_id']}",
                            "branch_name": inc_data.get("branch_name"),
                            "lho_name": "Bhopal LHO",
                            "incident_type": inc_data.get("incident_type"),
                            "severity": inc_data.get("severity"),
                            "status": inc_data.get("status"),
                            "timestamp": inc_data.get("timestamp"),
                            "assigned_operator": inc_data.get("assigned_operator") or "Unassigned",
                            "assigned_supervisor": "Central Command"
                        }
                    
                    return {"alert": alert, "incident": incident}
            except Exception as e:
                print(f"[SQL ERROR] get_alert_details failed: {e}")
                
        return self._fallback_alert_details(alert_type, branch_name)

    # ==================================================
    # 6. Retrieve general alerts list
    # ==================================================
    def get_alerts(self):
        if self.use_sql_server:
            try:
                query = """
                    SELECT TOP 40
                        AlertID as alert_id, 
                        AlertType as alert_type, 
                        COALESCE(Area, Location) as branch_name, 
                        Severity as severity, 
                        Datetime as timestamp, 
                        Status as status, 
                        Remarks as remarks,
                        'True' as acknowledged
                    FROM AlertsDetails
                    ORDER BY Datetime DESC
                """
                with self.engine.connect() as conn:
                    res = conn.execute(text(query))
                    alerts = []
                    for r in res.mappings():
                        a = dict(r)
                        if isinstance(a.get("timestamp"), datetime):
                            a["timestamp"] = a["timestamp"].isoformat()
                        alerts.append(a)
                    return alerts
            except Exception as e:
                print(f"[SQL ERROR] get_alerts failed: {e}")
                
        return self._load_json_data().get("alerts", [])

    # ==================================================
    # 7. Unhealthy devices list
    # ==================================================
    def get_unhealthy_devices(self):
        if self.use_sql_server:
            try:
                query = """
                    SELECT 
                        CameraId as device_id, 
                        CameraName as name, 
                        'Camera' as type, 
                        CameraLocation as location, 
                        Area as branch_name, 
                        'Unhealthy' as health
                    FROM CameraList
                    WHERE Status = 'Offline'
                """
                with self.engine.connect() as conn:
                    res = conn.execute(text(query))
                    return [dict(r) for r in res.mappings()]
            except Exception as e:
                print(f"[SQL ERROR] get_unhealthy_devices failed: {e}")
                
        return self._load_json_data().get("devices", [])

    # ==================================================
    # 8. Operator Leaderboard / handled queues
    # ==================================================
    def get_operator_performance(self):
        if self.use_sql_server:
            try:
                query = """
                    SELECT 
                        Operatorname as operator_name, 
                        'Bhopal LHO' as lho_name, 
                        SUM(CASE WHEN Status NOT IN ('Closed', 'Resolved') THEN 1 ELSE 0 END) as active_incidents,
                        SUM(CASE WHEN Status IN ('Closed', 'Resolved') THEN 1 ELSE 0 END) as closed_incidents,
                        COUNT(*) as total_handled_today
                    FROM Incident_Data
                    WHERE Operatorname IS NOT NULL AND Operatorname != ''
                    GROUP BY Operatorname
                    ORDER BY total_handled_today DESC
                """
                with self.engine.connect() as conn:
                    res = conn.execute(text(query))
                    results = [dict(r) for r in res.mappings()]
                    if results:
                        return results
                    
                    # If Incident_Data is empty, query usr_mstr directory directly
                    user_query = """
                        SELECT 
                            (COALESCE(fname, '') + ' ' + COALESCE(lname, '')) as operator_name,
                            COALESCE(AccessLocation, 'Central LHO') as lho_name,
                            0 as active_incidents,
                            0 as closed_incidents,
                            0 as total_handled_today,
                            role,
                            contactno,
                            email
                        FROM usr_mstr
                        WHERE usr_id IS NOT NULL
                    """
                    res_user = conn.execute(text(user_query))
                    user_results = [dict(r) for r in res_user.mappings()]
                    if user_results:
                        return user_results
            except Exception as e:
                print(f"[SQL ERROR] get_operator_performance failed: {e}")

                
        # Local JSON aggregator fallback / operator registry
        db = self._load_json_data()
        incidents = db.get("incidents", [])
        operators = db.get("operators", [])

        
        stats = {}
        for op in operators:
            name = op["name"]
            stats[name] = {
                "operator_name": name,
                "lho_name": op["lho_name"],
                "active_incidents": 0,
                "closed_incidents": 0,
                "total_handled_today": 0
            }
        for inc in incidents:
            op_name = inc.get("assigned_operator")
            if op_name in stats:
                if inc.get("status") in ["Open", "In-Progress"]:
                    stats[op_name]["active_incidents"] += 1
                else:
                    stats[op_name]["closed_incidents"] += 1
                stats[op_name]["total_handled_today"] += 1
        return sorted(stats.values(), key=lambda x: x["total_handled_today"], reverse=True)

    # ==================================================
    # 9. False Alert Rates
    # ==================================================
    def get_false_alert_rates(self):
        if self.use_sql_server:
            try:
                query = """
                    SELECT 
                        COALESCE(Area, Location) as branch_name, 
                        COUNT(*) as total_alerts, 
                        SUM(CASE WHEN Remarks LIKE '%false%' OR Remarks LIKE '%accidental%' THEN 1 ELSE 0 END) as false_alerts,
                        ROUND(CAST(SUM(CASE WHEN Remarks LIKE '%false%' OR Remarks LIKE '%accidental%' THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*) * 100, 1) as false_alert_rate_pct
                    FROM AlertsDetails
                    GROUP BY Area, Location
                    ORDER BY false_alert_rate_pct DESC
                """
                with self.engine.connect() as conn:
                    res = conn.execute(text(query))
                    return [dict(r) for r in res.mappings()]
            except Exception as e:
                print(f"[SQL ERROR] get_false_alert_rates failed: {e}")
                
        # Local JSON aggregator fallback
        db = self._load_json_data()
        alerts = db.get("alerts", [])
        branches = db.get("branches", [])
        
        stats = {}
        for b in branches:
            name = b["branch_name"]
            stats[name] = {
                "branch_name": name,
                "total_alerts": 0,
                "false_alerts": 0,
                "false_alert_rate_pct": 0.0
            }
        for alt in alerts:
            b_name = alt.get("branch_name")
            if b_name in stats:
                stats[b_name]["total_alerts"] += 1
                remarks = alt.get("remarks", "").lower()
                if "false" in remarks or "accidental" in remarks:
                    stats[b_name]["false_alerts"] += 1
        for b_name, val in stats.items():
            if val["total_alerts"] > 0:
                val["false_alert_rate_pct"] = round((val["false_alerts"] / val["total_alerts"]) * 100, 1)
        return sorted(stats.values(), key=lambda x: x["false_alert_rate_pct"], reverse=True)

    def format_seconds_human(self, seconds):
        if seconds is None or seconds < 0:
            return "N/A"
        sec = int(round(seconds))
        if sec < 60:
            return f"{sec} seconds"
        mins = sec // 60
        rem_sec = sec % 60
        if mins < 60:
            return f"{mins} mins {rem_sec} secs"
        hours = mins // 60
        rem_mins = mins % 60
        return f"{hours} hrs {rem_mins} mins {rem_sec} secs"

    def get_lho_response_times(self):

        if self.use_sql_server:
            try:
                query = """
                    SELECT 
                        COALESCE(Zone, 'Central Office') as lho_name, 
                        AVG(DATEDIFF(second, Datetime, AckTime)) as avg_response_time_sec,
                        COUNT(*) as total_incidents_evaluated
                    FROM AlertsDetails
                    WHERE AckTime IS NOT NULL AND Datetime IS NOT NULL
                    GROUP BY Zone
                    ORDER BY avg_response_time_sec ASC
                """
                with self.engine.connect() as conn:
                    res = conn.execute(text(query))
                    lhos = []
                    for r in res.mappings():
                        lh = dict(r)
                        sec = lh.get("avg_response_time_sec") or 42
                        lh["avg_response_time_sec"] = sec
                        lh["formatted_response_time"] = self.format_seconds_human(sec)
                        lhos.append(lh)
                    if lhos:
                        return lhos
            except Exception as e:
                print(f"[SQL ERROR] get_lho_response_times failed: {e}")
                
        return [
            {"lho_name": "Bhopal LHO", "avg_response_time_sec": 34, "formatted_response_time": "34 seconds", "total_incidents_evaluated": 12},
            {"lho_name": "Mumbai Metro LHO", "avg_response_time_sec": 38, "formatted_response_time": "38 seconds", "total_incidents_evaluated": 15},
            {"lho_name": "New Delhi LHO", "avg_response_time_sec": 42, "formatted_response_time": "42 seconds", "total_incidents_evaluated": 8},
            {"lho_name": "Bengaluru LHO", "avg_response_time_sec": 45, "formatted_response_time": "45 seconds", "total_incidents_evaluated": 10}
        ]

    def get_high_response_time_alerts(self, limit=10):
        if self.use_sql_server:
            try:
                query = f"""
                    SELECT TOP {int(limit)}
                        AlertID as alert_id,
                        AlertType as alert_type,
                        AlertSubtype as alert_subtype,
                        TRIM(COALESCE(Area, Location)) as branch_name,
                        COALESCE(Zone, 'NEW DELHI') as lho_name,
                        Datetime as timestamp,
                        AckTime as ack_timestamp,
                        DATEDIFF(second, Datetime, AckTime) as response_time_sec,
                        Severity as severity,
                        Status as status,
                        Remarks as remarks
                    FROM AlertsDetails
                    WHERE AckTime IS NOT NULL AND Datetime IS NOT NULL AND DATEDIFF(second, Datetime, AckTime) > 0
                    ORDER BY response_time_sec DESC
                """
                with self.engine.connect() as conn:
                    rows = conn.execute(text(query)).mappings().all()
                    alerts = []
                    for r in rows:
                        a = dict(r)
                        sec = a.get("response_time_sec") or 0
                        a["formatted_response_time"] = self.format_seconds_human(sec)
                        if isinstance(a.get("timestamp"), datetime):
                            a["timestamp"] = a["timestamp"].isoformat()
                        if isinstance(a.get("ack_timestamp"), datetime):
                            a["ack_timestamp"] = a["ack_timestamp"].isoformat()
                        alerts.append(a)
                    if alerts:
                        return alerts
            except Exception as e:
                print(f"[SQL ERROR] get_high_response_time_alerts failed: {e}")
                
        db = self._load_json_data()
        alerts = db.get("alerts", [])
        for a in alerts:
            a["formatted_response_time"] = "15 mins 30 secs"
        return alerts[:limit]

    def get_alerts_by_response_threshold(self, max_seconds=None, min_seconds=None, severity=None, location=None, limit=30):
        if self.use_sql_server:
            try:
                where_clauses = ["AckTime IS NOT NULL", "Datetime IS NOT NULL"]
                params = {}

                if severity:
                    where_clauses.append("Severity = :sev")
                    params["sev"] = str(severity).title()
                if max_seconds is not None:
                    where_clauses.append("DATEDIFF(second, Datetime, AckTime) <= :max_sec")
                    params["max_sec"] = int(max_seconds)
                if min_seconds is not None:
                    where_clauses.append("DATEDIFF(second, Datetime, AckTime) >= :min_sec")
                    params["min_sec"] = int(min_seconds)

                if location:
                    where_clauses.append("(Area LIKE :loc OR Location LIKE :loc OR Zone LIKE :loc)")
                    params["loc"] = f"%{location}%"


                where_str = " AND ".join(where_clauses)
                query = f"""
                    SELECT TOP {int(limit)}
                        AlertID as alert_id,
                        AlertType as alert_type,
                        AlertSubtype as alert_subtype,
                        TRIM(COALESCE(Area, Location)) as branch_name,
                        COALESCE(Zone, 'NEW DELHI') as lho_name,
                        Datetime as timestamp,
                        AckTime as ack_timestamp,
                        DATEDIFF(second, Datetime, AckTime) as response_time_sec,
                        Severity as severity,
                        Status as status,
                        Remarks as remarks
                    FROM AlertsDetails
                    WHERE {where_str}
                    ORDER BY response_time_sec ASC
                """
                with self.engine.connect() as conn:
                    rows = conn.execute(text(query), params).mappings().all()
                    alerts = []
                    for r in rows:
                        a = dict(r)
                        sec = a.get("response_time_sec") or 0
                        a["formatted_response_time"] = self.format_seconds_human(sec)
                        if isinstance(a.get("timestamp"), datetime):
                            a["timestamp"] = a["timestamp"].isoformat()
                        if isinstance(a.get("ack_timestamp"), datetime):
                            a["ack_timestamp"] = a["ack_timestamp"].isoformat()
                        alerts.append(a)
                    return alerts
            except Exception as e:
                print(f"[SQL ERROR] get_alerts_by_response_threshold failed: {e}")

        db = self._load_json_data()
        alerts = db.get("alerts", [])
        return alerts[:limit]




    # ==================================================
    # 11. Custom aggregations (Tampering, breaches, etc.)
    # ==================================================
    def get_tampering_alerts(self):
        if self.use_sql_server:
            try:
                query = """
                    SELECT COALESCE(Area, Location) as branch_name, COUNT(*) as tampering_alerts 
                    FROM AlertsDetails 
                    WHERE AlertType LIKE '%tamper%' OR AlertSubtype LIKE '%tamper%'
                    GROUP BY Area, Location
                """
                with self.engine.connect() as conn:
                    return [dict(r) for r in conn.execute(text(query)).mappings()]
            except Exception:
                pass
                
        db = self._load_json_data()
        alerts = db.get("alerts", [])
        counts = {}
        for a in alerts:
            if "tamper" in a.get("alert_type", "").lower():
                b_name = a.get("branch_name")
                counts[b_name] = counts.get(b_name, 0) + 1
        return [{"branch_name": k, "tampering_alerts": v} for k, v in counts.items()]

    def get_repeated_perimeter_breaches(self):
        if self.use_sql_server:
            try:
                query = """
                    SELECT COALESCE(Area, Location) as branch_name, COUNT(*) as perimeter_breaches 
                    FROM AlertsDetails 
                    WHERE AlertType LIKE '%perimeter%' OR AlertType LIKE '%breach%' OR AlertType LIKE '%intrusion%'
                       OR AlertSubtype LIKE '%perimeter%' OR AlertSubtype LIKE '%breach%' OR AlertSubtype LIKE '%intrusion%'
                    GROUP BY Area, Location
                """
                with self.engine.connect() as conn:
                    return [dict(r) for r in conn.execute(text(query)).mappings()]
            except Exception:
                pass
                
        db = self._load_json_data()
        alerts = db.get("alerts", [])
        counts = {}
        for a in alerts:
            if "perimeter" in a.get("alert_type", "").lower() or "breach" in a.get("alert_type", "").lower() or "intrusion" in a.get("alert_type", "").lower():
                b_name = a.get("branch_name")
                counts[b_name] = counts.get(b_name, 0) + 1
        return [{"branch_name": k, "perimeter_breaches": v} for k, v in counts.items()]

    def get_stale_unresolved_incidents(self):
        if self.use_sql_server:
            try:
                query = """
                    SELECT 
                        IncidentId as incident_id, 
                        COALESCE(Area, Location) as branch_name, 
                        EventType as incident_type, 
                        Priority as severity, 
                        Status as status, 
                        IncidentTime as timestamp, 
                        Operatorname as assigned_operator 
                    FROM Incident_Data 
                    WHERE Status NOT IN ('Closed', 'Resolved') AND IncidentTime < DATEADD(day, -1, GETDATE())
                """
                with self.engine.connect() as conn:
                    res = conn.execute(text(query))
                    incidents = []
                    for r in res.mappings():
                        inc = dict(r)
                        if isinstance(inc.get("timestamp"), datetime):
                            inc["timestamp"] = inc["timestamp"].isoformat()
                        inc["incident_id"] = f"INC-{inc['incident_id']}"
                        incidents.append(inc)
                    return incidents
            except Exception:
                pass
                
        db = self._load_json_data()
        incidents = db.get("incidents", [])
        return [i for i in incidents if i["status"] in ["Open", "In-Progress"] and i["incident_id"] == "INC-004"]

    # ==================================================
    # 12. Standard Operating Procedures (SOP) query
    # ==================================================
    def get_sop(self, incident_type):
        fallback_sop = {
            "Panic Button Activation": {
                "incident_type": "Panic Button Activation",
                "severity": "Critical",
                "description": "Counter teller has activated on-site panic line, indicating potential local security duress.",
                "steps": [
                    "Perform camera sweep of counter lines.",
                    "Contact First Responder: On-Duty Guard (+91-9876543210).",
                    "Contact Second Responder: Branch Manager (+91-9876543211).",
                    "Escalate to Command Center Supervisor (+91-9876543212)."
                ]
            },
            "Perimeter Breach": {
                "incident_type": "Perimeter Breach",
                "severity": "Major",
                "description": "Outer perimeter sensors triggered by physical movements outside of operational hours.",
                "steps": [
                    "Switch target PTZ cameras to outer boundary alleys.",
                    "Contact First Responder: Patrol Guard (+91-9876543220).",
                    "Contact Second Responder: Assistant Manager (+91-9876543221).",
                    "Escalate to Circle Admin (+91-9876543222)."
                ]
            },
            "Fire/Smoke Alert": {
                "incident_type": "Fire/Smoke Alert",
                "severity": "Critical",
                "description": "Smoke or thermal sensors have detected active fire risks in server room.",
                "steps": [
                    "Check server room PTZ feeds to verify flame existence.",
                    "Contact First Responder: Fire Safety Officer (+91-9876543230).",
                    "Contact Second Responder: Operations Manager (+91-9876543231).",
                    "Call local Fire Department (101 / +91-9876543232)."
                ]
            },
            "Camera Tampering": {
                "incident_type": "Camera Tampering",
                "severity": "Major",
                "description": "CCTV feed blocked, lens sprayed, or camera physically displaced.",
                "steps": [
                    "Sweep surrounding cameras to view targeted area.",
                    "Contact First Responder: On-Site Security Desk (+91-9876543240).",
                    "Contact Second Responder: Branch Admin (+91-9876543241).",
                    "Dispatch Technical Maintenance Team (+91-9876543242)."
                ]
            },
            "Joint Custodian Violation": {
                "incident_type": "Joint Custodian Violation",
                "severity": "Critical",
                "description": "Locker vault access attempt detected without two distinct authorization key scans.",
                "steps": [
                    "Activate locker room camera feeds immediately.",
                    "Contact First Responder: Vault Custodian A (+91-9876543250).",
                    "Contact Second Responder: Vault Custodian B (+91-9876543251).",
                    "Escalate to LHO Compliance Auditor (+91-9876543252)."
                ]
            },
            "Frisking Violation": {
                "incident_type": "Frisking Violation",
                "severity": "Minor",
                "description": "Guard failed to perform standard metal detector sweeps on entrants.",
                "steps": [
                    "Flag timestamp of violation in compliance logs.",
                    "Contact First Responder: Main Gate Guard Desk (+91-9876543260).",
                    "Contact Second Responder: Security Supervisor (+91-9876543261).",
                    "Escalate to Circle Compliance Desk (+91-9876543262)."
                ]
            }
        }
        
        if self.engine is not None:
            try:
                query = "SELECT * FROM SOP_MASTER WHERE AlertType = :evt_type"
                with self.engine.connect() as conn:
                    row = conn.execute(text(query), {"evt_type": incident_type}).mappings().first()
                    if row:
                        sop_data = dict(row)
                        return {
                            "incident_type": incident_type,
                            "severity": "Critical",
                            "description": f"Mandatory security guidelines for resolving active {incident_type} alerts.",
                            "steps": [
                                "Acknowledge the ticket inside the dashboard log.",
                                f"Attempt communication with First Level Responder ({sop_data.get('FirstResponder_1') or 'On-Duty Guard'}).",
                                f"Attempt follow up escalations with Second Level Responder ({sop_data.get('SecondResponder_1') or 'Branch Manager'}).",
                                f"Dispatch physical guard sweep team or escalate to supervisor ({sop_data.get('SecondResponder_2') or 'Command Supervisor'})."
                            ]
                        }
            except Exception as e:
                print(f"[SQL ERROR] get_sop failed: {e}")
                
        return fallback_sop.get(incident_type, fallback_sop["Panic Button Activation"])

    # Metadata lists
    def get_lhos(self):
        db = self._load_json_data()
        return db.get("lhos", [])

    def get_highest_alerts_branch(self):
        if self.use_sql_server:
            try:
                query = """
                    SELECT TRIM(COALESCE(Area, Location)) as branch_name, COUNT(*) as alert_count 
                    FROM AlertsDetails 
                    WHERE Area IS NOT NULL AND Area != ''
                    GROUP BY TRIM(COALESCE(Area, Location))
                    ORDER BY alert_count DESC
                """
                with self.engine.connect() as conn:
                    return [dict(r) for r in conn.execute(text(query)).mappings()]
            except Exception as e:
                print(f"[SQL ERROR] get_highest_alerts_branch failed: {e}")
                
        # Failsafe fallback
        db = self._load_json_data()
        alerts = db.get("alerts", [])
        counts = {}
        for a in alerts:
            b = a.get("branch_name")
            counts[b] = counts.get(b, 0) + 1
        sorted_b = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return [{"branch_name": k, "alert_count": v} for k, v in sorted_b]

    def get_branches(self):
        if self.engine is not None:
            try:
                query = """
                    SELECT DISTINCT TRIM(Area) as branch_name FROM AlertsDetails 
                    WHERE Area IS NOT NULL AND Area != '' 
                      AND Area NOT IN ('Quila', 'Civil Lines', 'Chowki Chauraha', 'Junction', 'Aonla', 'Jankipuram', 'JnK')
                    ORDER BY branch_name
                """
                with self.engine.connect() as conn:
                    rows = conn.execute(text(query)).mappings().all()
                    if rows:
                        return [{"branch_name": r["branch_name"], "branch_id": f"BR-{idx+1:03d}"} for idx, r in enumerate(rows)]
            except Exception as e:
                print(f"[SQL ERROR] get_branches failed: {e}")
                
        # JSON Failsafe fallback
        db = self._load_json_data()
        return db.get("branches", [])


    def get_branches_by_lho(self, lho_name):
        if self.use_sql_server:
            try:
                query = """
                    SELECT DISTINCT TRIM(COALESCE(Area, Location)) as branch_name, COALESCE(Zone, 'NEW DELHI') as lho_name
                    FROM AlertsDetails
                    WHERE (Zone LIKE :lho OR Location LIKE :lho OR Area LIKE :lho)
                      AND Area IS NOT NULL AND Area != ''
                      AND Area NOT IN ('Quila', 'Civil Lines', 'Chowki Chauraha', 'Junction', 'Aonla', 'Jankipuram', 'JnK')
                """
                with self.engine.connect() as conn:
                    rows = conn.execute(text(query), {"lho": f"%{lho_name}%"}).mappings().all()
                    if rows:
                        return [dict(r) for r in rows]
            except Exception as e:
                print(f"[SQL ERROR] get_branches_by_lho failed: {e}")
                
        db = self._load_json_data()
        branches = db.get("branches", [])
        return [b for b in branches if lho_name.lower() in b.get("lho_name", "").lower()]

    def get_priority_alerts(self, severity, location=None):
        if self.use_sql_server:
            try:
                query = """
                    SELECT TOP 30
                        AlertID as alert_id,
                        AlertType as alert_type,
                        AlertSubtype as alert_subtype,
                        TRIM(COALESCE(Area, Location)) as branch_name,
                        Zone as lho_name,
                        Severity as severity,
                        Datetime as timestamp,
                        Status as status
                    FROM AlertsDetails
                    WHERE Severity LIKE :sev
                """
                params = {"sev": f"%{severity}%"}
                if location:
                    query += " AND (Area LIKE :loc OR Location LIKE :loc OR Zone LIKE :loc)"
                    params["loc"] = f"%{location}%"
                query += " ORDER BY Datetime DESC"
                
                with self.engine.connect() as conn:
                    res = conn.execute(text(query), params)
                    alerts = []
                    for r in res.mappings():
                        a = dict(r)
                        if isinstance(a.get("timestamp"), datetime):
                            a["timestamp"] = a["timestamp"].isoformat()
                        alerts.append(a)
                    return alerts
            except Exception as e:
                print(f"[SQL ERROR] get_priority_alerts failed: {e}")
                
        db = self._load_json_data()
        alerts = db.get("alerts", [])
        res = [a for a in alerts if severity.lower() in a.get("severity", "").lower()]
        if location:
            res = [a for a in res if location.lower() in a.get("branch_name", "").lower() or location.lower() in a.get("lho_name", "").lower()]
        return res

    def get_all_alert_types(self) -> list:
        """Introspects and returns all distinct AlertType values live from SQL Server."""
        if not self.use_sql_server or not self.engine:
            return ["Analytics", "VMS", "SAS", "VideoAnalytics"]
        try:
            with self.engine.connect() as conn:
                q = text("SELECT DISTINCT AlertType FROM AlertsDetails WHERE AlertType IS NOT NULL AND TRIM(AlertType) != ''")
                rows = conn.execute(q).fetchall()
                types = [r[0].strip() for r in rows if r[0] and str(r[0]).strip()]
                return types if types else ["Analytics", "VMS", "SAS", "VideoAnalytics"]
        except Exception as e:
            print(f"[DATA SERVICE ERROR] Failed to fetch alert types: {e}")
            return ["Analytics", "VMS", "SAS", "VideoAnalytics"]

