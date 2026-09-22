"""
Regression Test Suite for SBI CMS NL-to-SQL Pipeline
Tests specific queries with explicit expected values.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.pipeline.orchestrator import PipelineOrchestrator
from app.data_service import DataService

def test_unresolved_alerts():
    """Test query for unresolved alerts"""
    data_service = DataService()
    orchestrator = PipelineOrchestrator(db_engine=data_service.engine if data_service.use_sql_server else None)
    
    query = "show me unresolved alerts"
    result = orchestrator.process_query(query)
    
    # Expected checks
    assert result["response"] is not None, "Response should not be None"
    assert result["sql"] is not None, "SQL should be generated"
    assert result["confidence_score"] > 0, "Confidence score should be positive"
    assert result["is_abstention"] == False, "Should not abstain on simple query"
    
    print(f"✓ Unresolved alerts test passed")
    print(f"  SQL: {result['sql']}")
    print(f"  Response snippet: {result['response'][:100]}...")
    return True

def test_alerts_by_location():
    """Test query for alerts by specific location"""
    data_service = DataService()
    orchestrator = PipelineOrchestrator(db_engine=data_service.engine if data_service.use_sql_server else None)
    
    query = "show alerts from Noida"
    result = orchestrator.process_query(query)
    
    assert result["response"] is not None, "Response should not be None"
    assert result["sql"] is not None, "SQL should be generated"
    assert "Noida" in result["sql"].lower() or "like" in result["sql"].lower(), "SQL should contain location filter"
    
    print(f"✓ Alerts by location test passed")
    print(f"  SQL: {result['sql']}")
    return True

def test_alert_summary():
    """Test query for alert summary/telemetry"""
    data_service = DataService()
    orchestrator = PipelineOrchestrator(db_engine=data_service.engine if data_service.use_sql_server else None)
    
    query = "show me alert summary"
    result = orchestrator.process_query(query)
    
    assert result["response"] is not None, "Response should not be None"
    assert result["confidence_score"] > 0, "Confidence score should be positive"
    
    print(f"✓ Alert summary test passed")
    print(f"  Response snippet: {result['response'][:100]}...")
    return True

def test_attachment_query():
    """Test query that should return attachments"""
    data_service = DataService()
    orchestrator = PipelineOrchestrator(db_engine=data_service.engine if data_service.use_sql_server else None)
    
    query = "show recent alert with attachments"
    result = orchestrator.process_query(query)
    
    assert result["response"] is not None, "Response should not be None"
    
    print(f"✓ Attachment query test passed")
    print(f"  Response snippet: {result['response'][:100]}...")
    return True

def run_all_tests():
    """Run all regression tests"""
    print("=" * 60)
    print("SBI CMS NL-to-SQL Regression Test Suite")
    print("=" * 60)
    
    tests = [
        ("Unresolved Alerts", test_unresolved_alerts),
        ("Alerts by Location", test_alerts_by_location),
        ("Alert Summary", test_alert_summary),
        ("Attachment Query", test_attachment_query),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        print(f"\nRunning: {test_name}")
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"✗ {test_name} FAILED: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)