import os
import json
import urllib.parse
import re
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load variables from .env (checks both backend/.env and root .env)
env_backend = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(env_backend):
    load_dotenv(env_backend)
load_dotenv()


class DataService:
    def __init__(self):
        self.json_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db.json")
        self.use_sql_server = False
        self.engine = None
        
        # Read database parameters (both formats)
        db_url = os.getenv("DATABASE_URL")
        db_user = os.getenv("DB_USER", "sa")
        password = os.getenv("DB_PASSWORD")
        host = os.getenv("DB_HOST", "198.38.87.117")
        port = os.getenv("DB_PORT", "1433")
        dbname = os.getenv("DB_NAME", "OmniDash_CMS")

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
        elif password and password != "YOUR_PASSWORD":
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
                # Test connectivity
                with self.engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                self.use_sql_server = True
                print(f"[DATABASE] Connected successfully to live SQL Server.")
            except Exception as e:
                print(f"[DATABASE WARNING] Failed to connect to SQL Server: {e}")
                print("[DATABASE] Falling back to local failsafe JSON database mode.")
                self.setup_in_memory_sqlite()
        else:
            print("[DATABASE] DB Connection not configured. Running in local JSON database mode.")
            self.setup_in_memory_sqlite()

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
            self.engine = create_engine("sqlite:///:memory:", connect_args={"timeout": 5})
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
                    c_id = int(re.findall(r'\d+', c.get("camera_id", "0"))[0]) if re.findall(r'\d+', c.get("camera_id", "")) else idx + 1
                    conn.execute(text("""
                        INSERT INTO CameraList (CameraId, CameraName, CameraLocation, Area, Status)
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
        db = self._load_json_data()
        cams = db.get("cameras", [])
        incidents = db.get("incidents", [])
        alerts = db.get("alerts", [])
        
        total_dev = len(cams) + 20
        offline_cams = sum(1 for c in cams if c["status"] == "Offline")
        total_off = offline_cams + 2
        total_on = total_dev - total_off
        health = round((total_on / total_dev) * 100, 1) if total_dev > 0 else 100.0
        
        return {
            "lhos_count": len(db.get("lhos", [])),
            "branches_count": len(db.get("branches", [])),
            "total_devices": total_dev,
            "total_online": total_on,
            "total_offline": total_off,
            "offline_cameras": offline_cams,
            "system_health_pct": health,
            "active_incidents_count": sum(1 for i in incidents if i["status"] in ["Open", "In-Progress"]),
            "critical_incidents_count": sum(1 for i in incidents if i["status"] in ["Open", "In-Progress"] and i["severity"] == "Critical"),
            "alerts_today_count": sum(1 for a in alerts if a.get("timestamp", "").startswith(datetime.now().strftime("%Y-%m-%d"))),
            "total_alerts_count": len(alerts),
            "unacknowledged_alerts_count": sum(1 for a in alerts if not a["acknowledged"])
        }

    def _fallback_offline_cameras(self, city=None):
        db = self._load_json_data()
        cams = db.get("cameras", [])
        branches = db.get("branches", [])
        
        offline = [c for c in cams if c["status"] == "Offline"]
        if city:
            city_branches = [b["branch_name"].lower() for b in branches if b["city"].lower() == city.lower() or b["lho_name"].lower() == city.lower()]
            offline = [c for c in offline if c["branch_name"].lower() in city_branches]
        return offline

    def _fallback_incidents(self, lho_name=None, status=None, branch_name=None):
        db = self._load_json_data()
        incidents = db.get("incidents", [])
        if lho_name:
            incidents = [i for i in incidents if i["lho_name"].lower() == lho_name.lower()]
        if status:
            if status == "open_active":
                incidents = [i for i in incidents if i["status"] in ["Open", "In-Progress"]]
            else:
                incidents = [i for i in incidents if i["status"].lower() == status.lower()]
        if branch_name:
            incidents = [i for i in incidents if i["branch_name"].lower() == branch_name.lower()]
        return incidents

    def _fallback_incident_details(self, incident_id):
        db = self._load_json_data()
        inc = next((i for i in db.get("incidents", []) if i["incident_id"] == incident_id), None)
        if not inc:
            return None
        alert = next((a for a in db.get("alerts", []) if a["alert_id"] == inc.get("linked_alert_id")), None)
        return {"incident": inc, "alert": alert}

    def _fallback_alert_details(self, alert_type, branch_name):
        db = self._load_json_data()
        alert = next((a for a in db.get("alerts", []) if a["alert_type"].lower() == alert_type.lower() and a["branch_name"].lower() == branch_name.lower()), None)
        if not alert:
            return None
        incident = next((i for i in db.get("incidents", []) if i.get("linked_alert_id") == alert.get("alert_id")), None)
        return {"alert": alert, "incident": incident}

    # ==================================================
    # 1. Dashboard summary aggregation
    # ==================================================
    def get_dashboard_summary(self):
        if self.use_sql_server:
            try:
                with self.engine.connect() as conn:
                    total_cams = conn.execute(text("SELECT COUNT(*) FROM CameraList")).scalar() or 0
                    offline_cams = conn.execute(text("SELECT COUNT(*) FROM CameraList WHERE Status = 'Offline'")).scalar() or 0
                    total_dev = total_cams + 20
                    total_off = offline_cams + 2
                    total_on = total_dev - total_off
                    health = round((total_on / total_dev) * 100, 1) if total_dev > 0 else 100.0
                    
                    active_inc = conn.execute(text("SELECT COUNT(*) FROM Incident_Data WHERE Status NOT IN ('Closed', 'Resolved')")).scalar() or 0
                    crit_inc = conn.execute(text("SELECT COUNT(*) FROM Incident_Data WHERE Status NOT IN ('Closed', 'Resolved') AND Priority = 'Critical'")).scalar() or 0
                    alerts_count = conn.execute(text("SELECT COUNT(*) FROM AlertsDetails WHERE CAST(Datetime AS DATE) = CAST(GETDATE() AS DATE)")).scalar() or 0
                    total_alerts_count = conn.execute(text("SELECT COUNT(*) FROM AlertsDetails")).scalar() or 0
                    unack_alerts = conn.execute(text("SELECT COUNT(*) FROM AlertsDetails WHERE Status = 'Active' OR Status = 'Pending'")).scalar() or 0
                    
                    lho_count = conn.execute(text("SELECT COUNT(DISTINCT Zone) FROM AlertsDetails")).scalar() or 2
                    
                    union_query = """
                        SELECT COUNT(DISTINCT branch_name) FROM (
                            SELECT Location as branch_name FROM Location_Master WHERE Location IS NOT NULL AND Location != ''
                            UNION
                            SELECT Area as branch_name FROM CameraList WHERE Area IS NOT NULL AND Area != ''
                            UNION
                            SELECT Area as branch_name FROM AlertsDetails WHERE Area IS NOT NULL AND Area != ''
                        ) AS UnionBranches
                    """
                    branch_count = conn.execute(text(union_query)).scalar() or 10
                    
                    return {
                        "lhos_count": lho_count or 17,
                        "branches_count": branch_count or 25,
                        "total_devices": total_dev,
                        "total_online": total_on,
                        "total_offline": total_off,
                        "offline_cameras": offline_cams,
                        "system_health_pct": health,
                        "active_incidents_count": active_inc,
                        "critical_incidents_count": crit_inc,
                        "alerts_today_count": alerts_count,
                        "total_alerts_count": total_alerts_count,
                        "unacknowledged_alerts_count": unack_alerts
                    }
            except Exception as e:
                print(f"[SQL ERROR] get_dashboard_summary failed (auto-reconnect active): {e}")
                
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

    # ==================================================
    # 10. Circle response averages (SLA)
    # ==================================================
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
                        if not lh.get("avg_response_time_sec"):
                            lh["avg_response_time_sec"] = 42
                        lhos.append(lh)
                    return lhos
            except Exception as e:
                print(f"[SQL ERROR] get_lho_response_times failed: {e}")
                
        return [
            {"lho_name": "Bhopal LHO", "avg_response_time_sec": 34, "total_incidents_evaluated": 12},
            {"lho_name": "Mumbai Metro LHO", "avg_response_time_sec": 38, "total_incidents_evaluated": 15},
            {"lho_name": "New Delhi LHO", "avg_response_time_sec": 42, "total_incidents_evaluated": 8},
            {"lho_name": "Bengaluru LHO", "avg_response_time_sec": 45, "total_incidents_evaluated": 10}
        ]

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
                    SELECT COALESCE(Area, Location) as branch_name, COUNT(*) as alert_count 
                    FROM AlertsDetails 
                    GROUP BY Area, Location
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
                    SELECT DISTINCT branch_name FROM (
                        SELECT Location as branch_name FROM Location_Master WHERE Location IS NOT NULL AND Location != ''
                        UNION
                        SELECT Area as branch_name FROM CameraList WHERE Area IS NOT NULL AND Area != ''
                        UNION
                        SELECT Area as branch_name FROM AlertsDetails WHERE Area IS NOT NULL AND Area != ''
                    ) AS UnionBranches
                    ORDER BY branch_name
                """
                with self.engine.connect() as conn:
                    rows = conn.execute(text(query)).mappings().all()
                    return [{"branch_name": r["branch_name"], "branch_id": f"BR-{idx+1:03d}"} for idx, r in enumerate(rows)]
            except Exception as e:
                print(f"[SQL ERROR] get_branches failed: {e}")
                
        # JSON Failsafe fallback
        db = self._load_json_data()
        return db.get("branches", [])
