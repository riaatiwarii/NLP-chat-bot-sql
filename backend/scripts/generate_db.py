import json
import os
import random
from datetime import datetime, timedelta

def generate_data():
    print("Generating SBI CMS interconnected dummy database...")
    
    # 1. LHOs List (17 LHOs as per PDF)
    lho_names = [
        "Amaravati", "Chennai", "Hyderabad", "Trivandrum", "Bengaluru", 
        "Chandigarh", "Jaipur", "Bhopal", "Maharashtra", "Kolkata", 
        "Gandhinagar", "Lucknow", "Guwahati", "Patna", "New Delhi", 
        "Mumbai Metro", "Bhubaneswar"
    ]
    
    lhos = []
    for i, name in enumerate(lho_names, 1):
        lhos.append({
            "lho_id": f"LHO-{i:03d}",
            "lho_name": name,
            "state": get_lho_state(name),
            "operator_count": 9,  # 3 operators per shift * 3 shifts
            "supervisor_count": 3, # 1 supervisor per shift * 3 shifts
            "status": "Active"
        })
        
    # 2. Branches (25 branches distributed across LHOs, focused on some specific ones for query results)
    branch_templates = [
        {"lho": "Bhopal", "name": "SBI MP Nagar", "code": "SBI0001", "city": "Bhopal", "district": "Bhopal", "region": "Region-1", "type": "Metro"},
        {"lho": "Bhopal", "name": "SBI Arera Colony", "code": "SBI0002", "city": "Bhopal", "district": "Bhopal", "region": "Region-1", "type": "Metro"},
        {"lho": "Bhopal", "name": "SBI TT Nagar", "code": "SBI0003", "city": "Bhopal", "district": "Bhopal", "region": "Region-1", "type": "Urban"},
        {"lho": "Bhopal", "name": "SBI Indore Main", "code": "SBI0004", "city": "Indore", "district": "Indore", "region": "Region-2", "type": "Urban"},
        {"lho": "Bhopal", "name": "SBI Hoshangabad Rural", "code": "SBI0005", "city": "Hoshangabad", "district": "Hoshangabad", "region": "Region-3", "type": "Rural"},
        
        {"lho": "Mumbai Metro", "name": "SBI Nariman Point", "code": "SBI0006", "city": "Mumbai", "district": "Mumbai", "region": "Region-1", "type": "Metro"},
        {"lho": "Mumbai Metro", "name": "SBI Bandra Kurla Complex", "code": "SBI0007", "city": "Mumbai", "district": "Mumbai Suburban", "region": "Region-2", "type": "Metro"},
        {"lho": "Mumbai Metro", "name": "SBI Fort Main", "code": "SBI0008", "city": "Mumbai", "district": "Mumbai", "region": "Region-1", "type": "Metro"},
        
        {"lho": "New Delhi", "name": "SBI Connaught Place", "code": "SBI0009", "city": "Delhi", "district": "New Delhi", "region": "Region-1", "type": "Metro"},
        {"lho": "New Delhi", "name": "SBI Nehru Place", "code": "SBI0010", "city": "Delhi", "district": "South Delhi", "region": "Region-2", "type": "Metro"},
        {"lho": "New Delhi", "name": "SBI Chandni Chowk", "code": "SBI0011", "city": "Delhi", "district": "North Delhi", "region": "Region-3", "type": "Urban"},
        
        {"lho": "Bengaluru", "name": "SBI MG Road", "code": "SBI0012", "city": "Bengaluru", "district": "Bengaluru Urban", "region": "Region-1", "type": "Metro"},
        {"lho": "Bengaluru", "name": "SBI Whitefield", "code": "SBI0013", "city": "Bengaluru", "district": "Bengaluru Urban", "region": "Region-2", "type": "Metro"},
        {"lho": "Bengaluru", "name": "SBI Jayanagar", "code": "SBI0014", "city": "Bengaluru", "district": "Bengaluru Urban", "region": "Region-1", "type": "Metro"},
        
        {"lho": "Kolkata", "name": "SBI Park Street", "code": "SBI0015", "city": "Kolkata", "district": "Kolkata", "region": "Region-1", "type": "Metro"},
        {"lho": "Kolkata", "name": "SBI Salt Lake", "code": "SBI0016", "city": "Kolkata", "district": "North 24 Parganas", "region": "Region-2", "type": "Urban"},
        
        {"lho": "Bhubaneswar", "name": "SBI Cuttack Road", "code": "SBI0017", "city": "Bhubaneswar", "district": "Khurda", "region": "Region-1", "type": "Urban"},
        {"lho": "Patna", "name": "SBI Gandhi Maidan", "code": "SBI0018", "city": "Patna", "district": "Patna", "region": "Region-1", "type": "Urban"},
        {"lho": "Lucknow", "name": "SBI Hazratganj", "code": "SBI0019", "city": "Lucknow", "district": "Lucknow", "region": "Region-1", "type": "Urban"},
        {"lho": "Chandigarh", "name": "SBI Sector 17", "code": "SBI0020", "city": "Chandigarh", "district": "Chandigarh", "region": "Region-1", "type": "Urban"},
        
        {"lho": "Chennai", "name": "SBI Anna Salai", "code": "SBI0021", "city": "Chennai", "district": "Chennai", "region": "Region-1", "type": "Metro"},
        {"lho": "Hyderabad", "name": "SBI Gachibowli", "code": "SBI0022", "city": "Hyderabad", "district": "Rangareddy", "region": "Region-1", "type": "Metro"},
        {"lho": "Trivandrum", "name": "SBI Palayam", "code": "SBI0023", "city": "Trivandrum", "district": "Thiruvananthapuram", "region": "Region-1", "type": "Urban"},
        {"lho": "Jaipur", "name": "SBI C-Scheme", "code": "SBI0024", "city": "Jaipur", "district": "Jaipur", "region": "Region-1", "type": "Urban"},
        {"lho": "Gandhinagar", "name": "SBI Sector 10", "code": "SBI0025", "city": "Gandhinagar", "district": "Gandhinagar", "region": "Region-1", "type": "Urban"}
    ]
    
    branches = []
    lho_by_name = {l["lho_name"]: l for l in lhos}
    
    for idx, t in enumerate(branch_templates, 1):
        lho_obj = lho_by_name[t["lho"]]
        branches.append({
            "branch_id": f"BR-{idx:03d}",
            "branch_name": t["name"],
            "branch_code": t["code"],
            "city": t["city"],
            "state": lho_obj["state"],
            "district": t["district"],
            "region": t["region"],
            "lho_id": lho_obj["lho_id"],
            "lho_name": lho_obj["lho_name"],
            "type": t["type"],
            "status": "Active"
        })
        
    # 3. Operators & Supervisors per LHO
    operators = []
    shifts = ["Morning (06:00-14:00)", "Evening (14:00-22:00)", "Night (22:00-06:00)"]
    names_pool = [
        "Aarav Sharma", "Aditya Patel", "Ananya Iyer", "Arjun Singh", "Bhavana Rao",
        "Deepak Verma", "Ishaan Reddy", "Karan Malhotra", "Kavita Nair", "Meera Joshi",
        "Neha Gupta", "Pankaj Pandey", "Pooja Trivedi", "Pranav Joshi", "Rahul Deshmukh",
        "Rohan Sen", "Sanjay Dutt", "Siddharth Das", "Sneha Kulkarni", "Vikram Rathore"
    ]
    random.seed(42) # For reproducible relationships
    
    for lho in lhos:
        lho_ops = random.sample(names_pool, 3)
        for s_idx, op_name in enumerate(lho_ops):
            operators.append({
                "operator_id": f"OP-{lho['lho_id'][-3:]}-{s_idx+1}",
                "name": op_name,
                "lho_id": lho["lho_id"],
                "lho_name": lho["lho_name"],
                "shift": shifts[s_idx],
                "active_incidents": 0,
                "closed_incidents_today": random.randint(3, 12)
            })

    # 4. Devices (CCTV Cameras, NVRs, Alarm panels, Access controllers)
    cameras = []
    nvrs = []
    alarms = []
    access_controllers = []
    
    camera_placements = [
        ("CAM-PER-1", "Branch Periphery Left", "Bullet"),
        ("CAM-PER-2", "Branch Periphery Right", "Bullet"),
        ("CAM-PER-3", "Branch Periphery Front", "PTZ"),
        ("CAM-FRISK", "Frisking Area Entrance", "Dome"),
        ("CAM-CASH-1", "Cash Counter 1", "Dome"),
        ("CAM-CASH-2", "Cash Counter 2", "Dome"),
        ("CAM-UPS", "UPS and Server Room", "Dome"),
        ("CAM-ENT", "Main Entrance Door", "Bullet"),
        ("CAM-EXIT", "Emergency Exit Door", "Bullet"),
        ("CAM-LOCKER", "Locker Room Outer Lobby", "Dome"),
        ("CAM-HALL", "Banking Hall Waiting Area", "PTZ")
    ]
    
    # We will set a few specific cameras to offline or degraded health to satisfy chatbot queries
    # e.g. Bhopal Arera Colony Locker camera offline, Connaught Place Cash Counter critical, etc.
    offline_cameras_info = [
        {"branch": "SBI Arera Colony", "cam": "CAM-LOCKER", "status": "Offline", "health": "Critical", "last_seen": "2026-07-17T02:15:00"},
        {"branch": "SBI Arera Colony", "cam": "CAM-PER-1", "status": "Offline", "health": "Critical", "last_seen": "2026-07-17T05:30:00"},
        {"branch": "SBI Whitefield", "cam": "CAM-UPS", "status": "Offline", "health": "Critical", "last_seen": "2026-07-17T09:12:00"},
        {"branch": "SBI Whitefield", "cam": "CAM-PER-3", "status": "Online", "health": "Critical", "last_seen": "2026-07-17T15:33:00"}, # degraded
        {"branch": "SBI Nariman Point", "cam": "CAM-ENT", "status": "Offline", "health": "Critical", "last_seen": "2026-07-17T11:45:00"},
        {"branch": "SBI Fort Main", "cam": "CAM-CASH-1", "status": "Online", "health": "Warning", "last_seen": "2026-07-17T15:33:00"} # Warning
    ]
    
    device_health_metrics = {}
    
    for b in branches:
        b_id = b["branch_id"]
        
        # Create NVR for branch
        nvr_id = f"NVR-{b_id[-3:]}"
        n_status = "Online"
        n_health = "Healthy"
        
        # If Whitefield has offline devices, let's make its NVR degraded
        if b["branch_name"] == "SBI Whitefield":
            n_status = "Online"
            n_health = "Warning"
            
        nvrs.append({
            "nvr_id": nvr_id,
            "branch_id": b_id,
            "branch_name": b["branch_name"],
            "storage_usage_pct": random.randint(45, 95) if b["branch_name"] != "SBI Nariman Point" else 98, # Nariman Point high storage
            "recording_health": n_health,
            "status": n_status,
            "capacity_tb": 8
        })
        
        # Create Cameras for branch
        for c_suffix, loc, c_type in camera_placements:
            c_id = f"CAM-{b_id[-3:]}-{c_suffix}"
            
            c_status = "Online"
            c_health = "Healthy"
            last_seen = "2026-07-17T15:33:33"
            
            # Check if this camera is in our predefined offline/degraded list
            for oc in offline_cameras_info:
                if oc["branch"] == b["branch_name"] and oc["cam"] == c_suffix:
                    c_status = oc["status"]
                    c_health = oc["health"]
                    last_seen = oc["last_seen"]
                    
            cameras.append({
                "camera_id": c_id,
                "branch_id": b_id,
                "camera_name": f"{b['branch_name']} - {loc}",
                "camera_type": c_type,
                "location": loc,
                "status": c_status,
                "recording_status": "Recording" if c_status == "Online" else "Stopped",
                "health": c_health,
                "last_seen": last_seen,
                "nvr_id": nvr_id
            })
            
            # Device Health Telemetry
            device_health_metrics[c_id] = {
                "device_id": c_id,
                "device_type": "Camera",
                "cpu_usage_pct": random.randint(15, 45) if c_status == "Online" else 0,
                "memory_usage_pct": random.randint(20, 50) if c_status == "Online" else 0,
                "network_latency_ms": random.randint(5, 45) if c_status == "Online" else 999,
                "uptime_days": random.randint(10, 150) if c_status == "Online" else 0,
                "overall_health": c_health
            }
            
        # NVR health metrics
        device_health_metrics[nvr_id] = {
            "device_id": nvr_id,
            "device_type": "NVR",
            "cpu_usage_pct": random.randint(30, 75) if n_status == "Online" else 0,
            "memory_usage_pct": random.randint(40, 80) if n_status == "Online" else 0,
            "network_latency_ms": random.randint(4, 20) if n_status == "Online" else 999,
            "uptime_days": random.randint(30, 200) if n_status == "Online" else 0,
            "overall_health": n_health
        }
        
        # Create Security Alarm System (SAS) for branch
        # Panel Status: Armed (normal), Triggered (under panic button activation)
        alarm_status = "Armed"
        if b["branch_name"] in ["SBI MP Nagar", "SBI Connaught Place"]:
            # Triggered alarms for active incidents
            alarm_status = "Triggered"
            
        alarms.append({
            "alarm_panel_id": f"ALM-{b_id[-3:]}",
            "branch_id": b_id,
            "branch_name": b["branch_name"],
            "panic_button_status": "Triggered" if b["branch_name"] == "SBI MP Nagar" else "Normal",
            "pir_sensor_status": "Triggered" if b["branch_name"] == "SBI Connaught Place" else "Normal",
            "magnetic_sensor_status": "Normal",
            "vibration_sensor_status": "Normal",
            "hooter_status": "Active" if alarm_status == "Triggered" else "Inactive",
            "alarm_status": alarm_status
        })
        
        # Create Access Control System (ACS) for branch
        access_controllers.append({
            "controller_id": f"ACS-{b_id[-3:]}",
            "branch_id": b_id,
            "branch_name": b["branch_name"],
            "door_name": "Vault Strong Room Door",
            "biometric_reader_status": "Active" if b["branch_name"] != "SBI Whitefield" else "Failed", # Whitefield failed biometric
            "rfid_reader_status": "Active",
            "face_recognition_status": "Active",
            "status": "Online" if b["branch_name"] != "SBI Whitefield" else "Offline"
        })

    # 5. Access Control logs (Joint Custodian verification entries & normal access)
    access_logs = []
    # Generate some logs for today
    base_time = datetime(2026, 7, 17, 9, 0, 0)
    for b in branches:
        b_id = b["branch_id"]
        # Generate Joint Custodian logs (two custodians log in within 1-2 mins)
        access_logs.append({
            "log_id": f"LOG-{b_id[-3:]}-101",
            "controller_id": f"ACS-{b_id[-3:]}",
            "branch_name": b["branch_name"],
            "timestamp": (base_time + timedelta(hours=random.randint(1, 3))).strftime("%Y-%m-%dT%H:%M:%S"),
            "employee_name": "Alok Kumar (Custodian Group A)",
            "auth_method": "Face Recognition",
            "direction": "Entry",
            "access_granted": True,
            "remarks": "Joint custodian session initiated"
        })
        access_logs.append({
            "log_id": f"LOG-{b_id[-3:]}-102",
            "controller_id": f"ACS-{b_id[-3:]}",
            "branch_name": b["branch_name"],
            "timestamp": (base_time + timedelta(hours=random.randint(1, 3), minutes=1)).strftime("%Y-%m-%dT%H:%M:%S"),
            "employee_name": "Sunita Verma (Custodian Group B)",
            "auth_method": "Biometric (Fingerprint)",
            "direction": "Entry",
            "access_granted": True,
            "remarks": "Joint custodian verification successful. Vault Door Opened."
        })
        
        # Let's generate a Violation log for Bhopal MP Nagar (Group A + Group A trying to enter - access denied)
        if b["branch_name"] == "SBI MP Nagar":
            access_logs.append({
                "log_id": f"LOG-{b_id[-3:]}-103",
                "controller_id": f"ACS-{b_id[-3:]}",
                "branch_name": b["branch_name"],
                "timestamp": "2026-07-17T14:10:00",
                "employee_name": "Alok Kumar (Custodian Group A)",
                "auth_method": "Face Recognition",
                "direction": "Entry",
                "access_granted": True,
                "remarks": "Custodian A verified. Awaiting Custodian B."
            })
            access_logs.append({
                "log_id": f"LOG-{b_id[-3:]}-104",
                "controller_id": f"ACS-{b_id[-3:]}",
                "branch_name": b["branch_name"],
                "timestamp": "2026-07-17T14:11:30",
                "employee_name": "Rajesh Mehta (Custodian Group A)",
                "auth_method": "RFID Card",
                "direction": "Entry",
                "access_granted": False,
                "remarks": "Access Denied: Violation of Joint Custodian policy. Two personnel of SAME Group A attempted access."
            })

    # 6. AI Video Analytics / Devices Alerts
    # Generate realistic alerts that map to incidents.
    # Severity: Critical, Major, Minor
    alerts = [
        # Alerts for Bhopal MP Nagar
        {
            "alert_id": "ALT-001",
            "alert_type": "Panic Button Activation",
            "severity": "Critical",
            "source_device_id": "ALM-001",
            "branch_id": "BR-001",
            "branch_name": "SBI MP Nagar",
            "acknowledged": True,
            "timestamp": "2026-07-17T13:45:00",
            "remarks": "Panic button at Single Window Counter 2 activated."
        },
        # Alerts for Bhopal Arera Colony
        {
            "alert_id": "ALT-002",
            "alert_type": "Camera Tampering",
            "severity": "Major",
            "source_device_id": "CAM-002-CAM-LOCKER",
            "branch_id": "BR-002",
            "branch_name": "SBI Arera Colony",
            "acknowledged": True,
            "timestamp": "2026-07-17T02:15:00",
            "remarks": "Video signal lost / obstruction detected on Locker Room camera."
        },
        {
            "alert_id": "ALT-003",
            "alert_type": "Perimeter Breach",
            "severity": "Critical",
            "source_device_id": "CAM-002-CAM-PER-1",
            "branch_id": "BR-002",
            "branch_name": "SBI Arera Colony",
            "acknowledged": True,
            "timestamp": "2026-07-17T02:16:00",
            "remarks": "Intrusion detected at rear wall area during non-operational hours."
        },
        # Alerts for Delhi Connaught Place
        {
            "alert_id": "ALT-004",
            "alert_type": "Fire/Smoke Detection",
            "severity": "Critical",
            "source_device_id": "CAM-009-CAM-UPS",
            "branch_id": "BR-009",
            "branch_name": "SBI Connaught Place",
            "acknowledged": True,
            "timestamp": "2026-07-17T15:10:00",
            "remarks": "AI analytics flagged smoke patterns in UPS and Server Room."
        },
        # Alerts for Bengaluru Whitefield
        {
            "alert_id": "ALT-005",
            "alert_type": "Frisking Violation",
            "severity": "Minor",
            "source_device_id": "CAM-013-CAM-FRISK",
            "branch_id": "BR-013",
            "branch_name": "SBI Whitefield",
            "acknowledged": True,
            "timestamp": "2026-07-17T10:30:00",
            "remarks": "Personnel bypassed strong room frisking area without security guard scan."
        },
        {
            "alert_id": "ALT-006",
            "alert_type": "Helmet-Face Mask Detection",
            "severity": "Major",
            "source_device_id": "CAM-013-CAM-FRISK",
            "branch_id": "BR-013",
            "branch_name": "SBI Whitefield",
            "acknowledged": False,
            "timestamp": "2026-07-17T15:20:00",
            "remarks": "Person entering restricted zone wearing full motorcycle helmet."
        },
        # Stale Unresolved Alert for Mumbai Nariman Point (older than 24 hours)
        {
            "alert_id": "ALT-007",
            "alert_type": "Enclosure Tampering",
            "severity": "Critical",
            "source_device_id": "ALM-006",
            "branch_id": "BR-006",
            "branch_name": "SBI Nariman Point",
            "acknowledged": True,
            "timestamp": "2026-07-16T10:00:00",
            "remarks": "NVR enclosure magnetic contact opened without work order."
        },
        # Additional alerts for analytics use case queries (frisking, tampering, perimeter breaches)
        {
            "alert_id": "ALT-008",
            "alert_type": "Camera Tampering",
            "severity": "Major",
            "source_device_id": "CAM-013-CAM-PER-3",
            "branch_id": "BR-013",
            "branch_name": "SBI Whitefield",
            "acknowledged": True,
            "timestamp": "2026-07-17T09:40:00",
            "remarks": "Camera angle shift detected on Whitefield Periphery PTZ."
        },
        {
            "alert_id": "ALT-009",
            "alert_type": "Perimeter Breach",
            "severity": "Major",
            "source_device_id": "CAM-013-CAM-PER-1",
            "branch_id": "BR-013",
            "branch_name": "SBI Whitefield",
            "acknowledged": True,
            "timestamp": "2026-07-15T23:10:00",
            "remarks": "Loitering detected at side alley area."
        },
        {
            "alert_id": "ALT-010",
            "alert_type": "Abandoned Object Detection",
            "severity": "Minor",
            "source_device_id": "CAM-001-CAM-HALL",
            "branch_id": "BR-001",
            "branch_name": "SBI MP Nagar",
            "acknowledged": True,
            "timestamp": "2026-07-17T11:00:00",
            "remarks": "Briefcase left unattended in banking hall for over 15 minutes."
        },
        {
            "alert_id": "ALT-011",
            "alert_type": "Joint Custodian Violation",
            "severity": "Major",
            "source_device_id": "ACS-001",
            "branch_id": "BR-001",
            "branch_name": "SBI MP Nagar",
            "acknowledged": True,
            "timestamp": "2026-07-17T14:11:30",
            "remarks": "Alert triggered: Rajesh Mehta (Group A) and Alok Kumar (Group A) logged instead of Group A + Group B."
        }
    ]

    # 7. Incidents
    # Map to alerts, operators
    # Incident status: Open, In-Progress, Resolved, Closed
    incidents = [
        # Active incident at SBI MP Nagar (Panic Button)
        {
            "incident_id": "INC-001",
            "branch_id": "BR-001",
            "branch_name": "SBI MP Nagar",
            "lho_name": "Bhopal",
            "incident_type": "Panic Button Activation",
            "severity": "Critical",
            "category": "Security",
            "status": "Open",
            "timestamp": "2026-07-17T13:45:00",
            "assigned_operator": "Aarav Sharma", # Working at LHO Bhopal
            "assigned_supervisor": "Sanjay Dutt",
            "response_time_sec": 45,
            "resolution_time_sec": None,
            "linked_alert_id": "ALT-001",
            "worklog": [
                {"timestamp": "2026-07-17T13:45:45", "operator": "Aarav Sharma", "comment": "Incident auto-created. Panic Button SWC-2 triggered hooter. Correlated camera CAM-001-CASH-1 live feed activated."}
            ],
            "sop_steps": [
                "Activate local hooter/alarm (DONE - Auto)",
                "Identify source of panic button (DONE - SWC-2)",
                "Verify visual feed of cash counter for robbery/duress (IN PROGRESS - cash officers seen communicating normally, looks like accidental press)",
                "Establish discreet contact with Branch Manager via voice line",
                "If genuine, dispatch local QRT (Quick Reaction Team) and alert local police",
                "If accidental, log false alert details, reset panel, and close ticket with supervisor approval"
            ]
        },
        # Resolved incident at Bhopal Arera Colony (Locker Tampering & Perimeter Breach)
        {
            "incident_id": "INC-002",
            "branch_id": "BR-002",
            "branch_name": "SBI Arera Colony",
            "lho_name": "Bhopal",
            "incident_type": "Perimeter Breach",
            "severity": "Critical",
            "category": "Security",
            "status": "Resolved",
            "timestamp": "2026-07-17T02:16:00",
            "assigned_operator": "Aarav Sharma",
            "assigned_supervisor": "Sanjay Dutt",
            "response_time_sec": 30,
            "resolution_time_sec": 1800, # 30 mins
            "linked_alert_id": "ALT-003",
            "worklog": [
                {"timestamp": "2026-07-17T02:16:30", "operator": "Aarav Sharma", "comment": "Perimeter breach alert correlated with camera CAM-002-CAM-PER-1. Confirmed a stray animal jumped the rear boundary wall."},
                {"timestamp": "2026-07-17T02:40:00", "operator": "Aarav Sharma", "comment": "Security guards dispatched to inspect. Perimeter secured. Animal driven out. Rescanned feed, no intrusion signs."}
            ],
            "sop_steps": [
                "Focus PTZ cameras on breach coordinate (DONE)",
                "Examine pre-event clip (10s) and live stream (DONE)",
                "Dispatch branch security guard for physical verification (DONE)",
                "If animal or false trigger, document and resolve (DONE)",
                "Log FSR and close incident"
            ]
        },
        # Open incident at Connaught Place (Fire/Smoke)
        {
            "incident_id": "INC-003",
            "branch_id": "BR-009",
            "branch_name": "SBI Connaught Place",
            "lho_name": "New Delhi",
            "incident_type": "Fire/Smoke Alert",
            "severity": "Critical",
            "category": "Safety",
            "status": "In-Progress",
            "timestamp": "2026-07-17T15:10:00",
            "assigned_operator": "Karan Singh", # Delhi LHO
            "assigned_supervisor": "Aditya Patel",
            "response_time_sec": 20,
            "resolution_time_sec": None,
            "linked_alert_id": "ALT-004",
            "worklog": [
                {"timestamp": "2026-07-17T15:10:20", "operator": "Karan Singh", "comment": "Smoke detected in UPS room. Correlated camera CAM-009-CAM-UPS shows small spark from battery rack. Local smoke detector hooter is active."},
                {"timestamp": "2026-07-17T15:12:00", "operator": "Karan Singh", "comment": "Alerted Branch Manager and local security team. Evacuating branch. Fire suppression system (CO2 gas) discharged."}
            ],
            "sop_steps": [
                "Identify fire source using cameras (DONE - battery rack spark)",
                "Verify fire alarm panel status (DONE - smoke hooter active)",
                "Immediately contact Branch Manager to initiate evacuation (DONE)",
                "Alert Fire Department (Delhi Fire Service) (DONE - call logged)",
                "Instruct operator to power down main UPS bypass (IN PROGRESS)",
                "Log action reports and wait for fire clearance"
            ]
        },
        # Stale Unresolved Incident at Nariman Point (older than 24 hours)
        {
            "incident_id": "INC-004",
            "branch_id": "BR-006",
            "branch_name": "SBI Nariman Point",
            "lho_name": "Mumbai Metro",
            "incident_type": "Enclosure Tampering",
            "severity": "Major",
            "category": "Technical",
            "status": "Open",
            "timestamp": "2026-07-16T10:00:00",
            "assigned_operator": "Priya Patel", # Mumbai Metro LHO
            "assigned_supervisor": "Vikram Mehta",
            "response_time_sec": 120,
            "resolution_time_sec": None,
            "linked_alert_id": "ALT-007",
            "worklog": [
                {"timestamp": "2026-07-16T10:02:00", "operator": "Priya Patel", "comment": "Enclosure open alert for NVR. Branch Manager contacted. Confirmed vendor AMC was scheduled but no formal entry permit was filed in CMS."},
                {"timestamp": "2026-07-16T14:00:00", "operator": "Priya Patel", "comment": "Called branch manager. Vendor completed work but cabinet door magnet sensor is still showing open. Needs physical alignment."}
            ],
            "sop_steps": [
                "Verify authorization for enclosure access (DONE - AMC scheduled)",
                "Confirm if cabinet door is closed post-work (FAILED - showing open)",
                "Log ticket for maintenance vendor to align magnetic sensor (DONE - Ticket sent to OEM)",
                "Awaiting field engineer visit to align sensor"
            ]
        },
        # Resolved incident at Whitefield (Camera Tampering)
        {
            "incident_id": "INC-005",
            "branch_id": "BR-013",
            "branch_name": "SBI Whitefield",
            "lho_name": "Bengaluru",
            "incident_type": "Camera Tampering",
            "severity": "Major",
            "category": "Technical",
            "status": "Closed",
            "timestamp": "2026-07-17T09:40:00",
            "assigned_operator": "Bhavana Rao", # Bengaluru LHO
            "assigned_supervisor": "Arjun Singh",
            "response_time_sec": 50,
            "resolution_time_sec": 3600, # 1 hour
            "linked_alert_id": "ALT-008",
            "worklog": [
                {"timestamp": "2026-07-17T09:40:50", "operator": "Bhavana Rao", "comment": "PTZ camera angle shift detected. Image shows tree branches obstructing view due to strong winds."},
                {"timestamp": "2026-07-17T10:35:00", "operator": "Bhavana Rao", "comment": "Branch admin trimmed the branches. Camera view restored. Supervisor verified feed quality and approved closure."}
            ],
            "sop_steps": [
                "Analyze video frame baseline difference (DONE)",
                "Check for vandalism or environmental shift (DONE - Wind/Tree branch)",
                "Coordinate with branch staff to clear obstruction (DONE)",
                "Verify camera view against original baseline (DONE)",
                "Resolve and close incident (DONE)"
            ]
        },
        # Active incident at MP Nagar (Joint Custodian Violation)
        {
            "incident_id": "INC-006",
            "branch_id": "BR-001",
            "branch_name": "SBI MP Nagar",
            "lho_name": "Bhopal",
            "incident_type": "Joint Custodian Violation",
            "severity": "Major",
            "category": "Compliance",
            "status": "In-Progress",
            "timestamp": "2026-07-17T14:11:30",
            "assigned_operator": "Aarav Sharma",
            "assigned_supervisor": "Sanjay Dutt",
            "response_time_sec": 15,
            "resolution_time_sec": None,
            "linked_alert_id": "ALT-011",
            "worklog": [
                {"timestamp": "2026-07-17T14:11:45", "operator": "Aarav Sharma", "comment": "Joint Custodian policy violation alert triggered at Strong Room Door. Two Group A keys scanned. Door access denied. Verified camera feed: Rajesh Mehta and Alok Kumar are at the vault gate. Awaiting explanation."}
            ],
            "sop_steps": [
                "Verify operator ID scans (DONE - Rajesh Mehta Group A, Alok Kumar Group A)",
                "Hold vault door release / check controller lock status (DONE - Access Denied)",
                "Verify live camera stream for forced entry or duress (DONE - No duress seen)",
                "Call Branch Manager to request explanation of custodian replacement",
                "Ensure correct dual-group keys (Group A + Group B) are presented",
                "Instruct custodians to swipe in correct order with correct credentials"
            ]
        }
    ]

    # Update LHO operator status based on incidents
    for op in operators:
        op["active_incidents"] = sum(1 for inc in incidents if inc["assigned_operator"] == op["name"] and inc["status"] in ["Open", "In-Progress"])

    # 8. SOPs database
    sops = {
        "Panic Button Activation": {
            "incident_type": "Panic Button Activation",
            "severity": "Critical",
            "description": "Triggered when panic button under counters or branch manager desk is pressed during robbery, assault, or high distress.",
            "steps": [
                "Activate LHO console alert and automatically open live feeds of nearby CCTV cameras.",
                "Inspect the live video feeds to verify the nature of the emergency (silent robbery, hostage, medical emergency, or accidental trigger).",
                "Confirm alarm hooter status. A silent panic alarm is raised to the LHO without sounding the hooter at the branch, unless explicitly triggered by LHO.",
                "If robbery/violence is visible, immediately notify Local Police Station and SBI Central Security Officer.",
                "Dispatch Circle Quick Reaction Team (QRT) to the branch.",
                "Log all evidence including video snapshots, and maintain open communication with the branch manager."
            ]
        },
        "Perimeter Breach": {
            "incident_type": "Perimeter Breach",
            "severity": "Critical",
            "description": "Triggered when AI video analytics detects human intrusion near perimeters, alleys, or roofs during non-operational hours.",
            "steps": [
                "Pivot PTZ cameras to target coordinates immediately.",
                "Verify if the intrusion is human or a false trigger (animals, falling branches, debris).",
                "If human, trigger hooter/siren remotely to deter the intruder.",
                "Instruct local guards on the ground to inspect the breach point.",
                "If unauthorized entry persists or looks suspicious, alert local police dispatch.",
                "Log the incident status and upload 10 seconds of pre/post-event video clips."
            ]
        },
        "Fire/Smoke Alert": {
            "incident_type": "Fire/Smoke Alert",
            "severity": "Critical",
            "description": "Smoke patterns or active flames detected by camera analytics or physical smoke alarms, particularly in server/UPS rooms.",
            "steps": [
                "Pinpoint fire location on the CMS dashboard map.",
                "Review live video feed of the camera that triggered the alert.",
                "Contact Branch Manager immediately to begin evacuation procedures.",
                "Dispatch local fire service and notify the LHO supervisor.",
                "Verify automatic shutdown of high-power IT components (e.g. UPS system) to prevent electrical fires from spreading.",
                "Follow up until fire safety team provides clearance."
            ]
        },
        "Camera Tampering": {
            "incident_type": "Camera Tampering",
            "severity": "Major",
            "description": "Camera obstruction, defocus, angle change, signal loss, or blackout detected by VMS diagnostics.",
            "steps": [
                "Examine baseline image of the camera to determine displacement.",
                "Inspect nearby cameras to check for physical vandalism or deliberate masking by suspects.",
                "Alert branch security staff to physically inspect the camera for mud, spray paint, or physical damage.",
                "If it is an environmental cause (e.g. wind, spider webs), log a service ticket for routine maintenance.",
                "If vandalism is suspected, initiate a full branch lockdown assessment and escalate to major incident."
            ]
        },
        "Joint Custodian Violation": {
            "incident_type": "Joint Custodian Violation",
            "severity": "Major",
            "description": "Access control system flags unauthorized vault entry sequence, such as two logins from the same custodian group.",
            "steps": [
                "Lock the strong room controller to prevent door unlock.",
                "Review live vault entrance camera feeds for unauthorized personnel or physical coercion.",
                "Verify logs for card scans, face readers, or biometric logs.",
                "Call the Branch Manager to verify if a temporary shift substitution was authorized.",
                "Ensure that one custodian from Group A and one from Group B are present.",
                "Require dual-scan sequence for successful release of the electromagnetic lock."
            ]
        },
        "Frisking Violation": {
            "incident_type": "Frisking Violation",
            "severity": "Minor",
            "description": "AI analytics detects bank personnel or visitors bypassing the mandatory guard scan at the strong room entry point.",
            "steps": [
                "Log the violation with timestamp and photo evidence.",
                "Play automated audio warning prompt at the frisking booth.",
                "Instruct the on-duty guard to bring the individual back for standard scanning.",
                "Log the guard compliance record and file a weekly report for branch audits."
            ]
        }
    }

    # Consolidated Database
    db = {
        "lhos": lhos,
        "branches": branches,
        "operators": operators,
        "cameras": cameras,
        "nvrs": nvrs,
        "alarms": alarms,
        "access_controllers": access_controllers,
        "access_logs": access_logs,
        "alerts": alerts,
        "incidents": incidents,
        "sops": sops,
        "device_health_metrics": list(device_health_metrics.values())
    }
    
    # Save to db.json
    db_dir = os.path.dirname(os.path.abspath(__file__))
    # Let's target backend/app/db.json
    target_path = os.path.join(os.path.dirname(db_dir), "app", "db.json")
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
        
    print(f"Interconnected dummy database successfully generated at {target_path}!")

def get_lho_state(lho_name):
    states = {
        "Amaravati": "Andhra Pradesh",
        "Chennai": "Tamil Nadu",
        "Hyderabad": "Telangana",
        "Trivandrum": "Kerala",
        "Bengaluru": "Karnataka",
        "Chandigarh": "Punjab",
        "Jaipur": "Rajasthan",
        "Bhopal": "Madhya Pradesh",
        "Maharashtra": "Maharashtra",
        "Kolkata": "West Bengal",
        "Gandhinagar": "Gujarat",
        "Lucknow": "Uttar Pradesh",
        "Guwahati": "Assam",
        "Patna": "Bihar",
        "New Delhi": "Delhi",
        "Mumbai Metro": "Maharashtra",
        "Bhubaneswar": "Odisha"
    }
    return states.get(lho_name, "Unknown")

if __name__ == "__main__":
    generate_data()
