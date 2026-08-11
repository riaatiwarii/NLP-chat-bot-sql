import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.data_service import DataService
from app.chatbot_service import ChatbotService

def run_tests():
    print("==================================================")
    print("Testing SBI CMS Backend & Chatbot Services...")
    print("==================================================")
    
    try:
        # 1. Initialize data service
        ds = DataService()
        print("[SUCCESS] DataService initialized successfully.")
        
        # Test dashboard summary
        summary = ds.get_dashboard_summary()
        print(f"[SUCCESS] Summary: Uptime Health = {summary['system_health_pct']}%, Active Incidents = {summary['active_incidents_count']}")
        
        # Test active incidents
        active_incidents = ds.get_incidents(status="open_active")
        print(f"[SUCCESS] Active Incidents Count: {len(active_incidents)}")
        
        # Test offline cameras
        offline_cams = ds.get_offline_cameras()
        print(f"[SUCCESS] Offline Cameras Count: {len(offline_cams)}")
        
        # Test operator stats
        op_stats = ds.get_operator_performance()
        if op_stats:
            print(f"[SUCCESS] Top Operator: {op_stats[0]['operator_name']} ({op_stats[0]['total_handled_today']} handled today)")
        else:
            print("[INFO] Operator Stats: No active operator performance records in database.")
            
        # Test false alert rate
        false_rates = ds.get_false_alert_rates()
        if false_rates:
            print(f"[SUCCESS] Highest False Alarm Branch: {false_rates[0]['branch_name']} ({false_rates[0]['false_alert_rate_pct']}% rate)")
        else:
            print("[INFO] False Alert Rates: No alert records in database to calculate rate.")
            
        # Test new lookup queries
        alert_details = ds.get_alert_details("Enclosure Tampering", "SBI Nariman Point")
        if alert_details and alert_details.get("alert") and alert_details.get("incident"):
            print(f"[SUCCESS] Checked Nariman Point Alert Details: Alert ID = {alert_details['alert']['alert_id']}, Linked Ticket = {alert_details['incident']['incident_id']}")
        else:
            print("[INFO] Alert details query skipped/empty (no matching alert in database).")
            
        incident_details = ds.get_incident_details("INC-001")
        if incident_details and incident_details.get("incident"):
            print(f"[SUCCESS] Checked INC-001 Incident Details: Incident Type = {incident_details['incident']['incident_type']}, Operator = {incident_details['incident']['assigned_operator']}")
        else:
            print("[INFO] Incident details query skipped/empty (no INC-001 in database).")
            
        # 2. Initialize chatbot service
        cb = ChatbotService(ds)
        print("[SUCCESS] ChatbotService initialized successfully.")
        
        # Test chat queries in local fallback mode
        test_queries = [
            "Show today's dashboard summary",
            "How many active incidents are there today?",
            "Which CCTV cameras are offline?",
            "Show incidents from Bhopal LHO",
            "Which operator handled the most incidents today?",
            "Show standard operating procedure for panic button",
            "which branch has highest number of alerts",
            "how many branches we have",
            "which branch is this",
            "tell me any anomaly alert today",
            "can you explain me this data , what is it",
            "Show me AI use case alert stats.",
            "What is the escalation procedure for a joint custodian violation?",
            "Who is the first responder for a perimeter breach alert?",
            "Show me the contact details for fire alerts.",
            "Tell me more about the Analytics alert at AO_AGRA",
            "how many alerts priya patel is handling",
            "how many alert types we have",
            "how many alerts of VMS we have and where",
            "What is the count of High, Medium, and Low severity alerts in the system today?",
            "Show the most recent 5 VMS alerts from Noida circle ordered by time"
        ]
        
        context = {}
        history = []
        
        for q in test_queries:
            print(f"\nUser: {q}")
            response, context = cb.process_message(q, history, context)
            history.append({"role": "user", "content": q})
            history.append({"role": "assistant", "content": response})
            
            lines = response.split('\n')
            preview = "\n".join(lines[:2])
            print(f"Chatbot:\n{preview}\n[... truncated {len(lines)-2} lines ...]")
            
        print("\n[SUCCESS] Context state after queries:")
        print(context)
        
        # --- Targeted fix verifications ---
        print("\n--- Running targeted fix assertions ---")
        
        # 1. BRANCH_COUNT should now return actual branches from DB (not 1 or dummy value)
        branches = ds.get_branches()
        branch_count = len(branches)
        assert branch_count > 0, f"[FAIL] BRANCH_COUNT is 0 — get_branches() returned empty"
        print(f"[ASSERT] Branch count from DB: {branch_count} branches -> OK")
        
        # 2. Branch count chat response must mention real branch count
        ctx2 = {}
        resp_branches, _ = cb.process_message("how many branches do we have", [], ctx2)
        assert str(branch_count) in resp_branches, f"[FAIL] BRANCH_COUNT response missing real count '{branch_count}'. Got: {resp_branches[:200]}"
        print(f"[ASSERT] Branch count chat response correct (mentions {branch_count}) -> OK")
        
        # 3. ALERT_SEVERITY_COUNT must now return non-zero results (no today-date filter)
        ctx3 = {}
        resp_sev, _ = cb.process_message("What is the count of High, Medium, and Low severity alerts in the system today?", [], ctx3)
        assert "No alerts were found" not in resp_sev, f"[FAIL] ALERT_SEVERITY_COUNT still returning empty — fix Issue 3 failed. Got: {resp_sev[:200]}"
        print("[ASSERT] Severity count returns data (not empty) -> OK")
        
        # 4. FALSE_ALERT_RATE must NOT fire on "highest number of alerts"
        ctx4 = {}
        resp_highest, _ = cb.process_message("which branch has highest number of alerts", [], ctx4)
        assert "false alert rate" not in resp_highest.lower() and "false alarm" not in resp_highest.lower(), \
            f"[FAIL] 'highest number of alerts' incorrectly routed to FALSE_ALERT_RATE. Got: {resp_highest[:200]}"
        print("[ASSERT] 'highest number of alerts' routes to HIGHEST_ALERTS_BRANCH (not false alert) -> OK")
        
        # 5. ALERT_TYPES must return actual types (not empty)
        ctx5 = {}
        resp_types, _ = cb.process_message("how many alert types we have", [], ctx5)
        assert "No distinct alert types" not in resp_types, f"[FAIL] ALERT_TYPES returned empty — text scope issue still present. Got: {resp_types[:200]}"
        print("[ASSERT] Alert types returns data -> OK")
        
        # 6. ALERTS_BY_TYPE (VMS) must return actual results
        ctx6 = {}
        resp_vms, _ = cb.process_message("how many alerts of VMS we have and where", [], ctx6)
        assert "No active alerts of type" not in resp_vms, f"[FAIL] VMS alert count returned empty. Got: {resp_vms[:200]}"
        print("[ASSERT] VMS alert count returns data -> OK")
        
        print("\n=================================================")
        print("ALL TESTS PASSED SUCCESSFULLY!")
        print("==================================================")
        
    except AssertionError as ae:
        print(f"\n{ae}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"[FAILURE] Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
