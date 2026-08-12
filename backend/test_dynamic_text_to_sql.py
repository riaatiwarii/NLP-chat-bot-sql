import sys
import os
import unittest
from sqlalchemy import create_engine, text

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.schema_engine import SchemaEngine
from app.schema_linker import SchemaLinker
from app.context_tracker import ContextTracker
from app.data_service import DataService
from app.chatbot_service import ChatbotService

class TestDynamicTextToSQL(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        from sqlalchemy.pool import StaticPool
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        with cls.engine.begin() as conn:

            conn.execute(text("""
                CREATE TABLE cctv_devices (
                    device_id INTEGER PRIMARY KEY,
                    device_label TEXT,
                    location_zone TEXT,
                    operational_state TEXT
                )
            """))
            conn.execute(text("""
                INSERT INTO cctv_devices (device_id, device_label, location_zone, operational_state)
                VALUES (1, 'Main Gate PTZ', 'SBI Nariman Point', 'Faulty'),
                       (2, 'Lobby Dome Cam', 'Bhopal LHO', 'Operational')
            """))
            
            conn.execute(text("""
                CREATE TABLE security_tickets (
                    ticket_id INTEGER PRIMARY KEY,
                    event_category TEXT,
                    branch_name TEXT,
                    severity_level TEXT,
                    status_flag TEXT
                )
            """))
            conn.execute(text("""
                INSERT INTO security_tickets (ticket_id, event_category, branch_name, severity_level, status_flag)
                VALUES (101, 'Panic Alarm', 'SBI Nariman Point', 'Critical', 'Open')
            """))

    def test_schema_engine_introspection(self):
        """Verify dynamic database introspection discovers custom tables, columns, and samples"""
        se = SchemaEngine(self.engine)
        schema = se.introspect_database()
        
        self.assertIn("cctv_devices", schema)
        self.assertIn("security_tickets", schema)
        
        col_names = [col["name"] for col in schema["cctv_devices"]["columns"]]
        self.assertIn("device_label", col_names)
        self.assertIn("operational_state", col_names)
        
        prompt = se.generate_dynamic_schema_prompt("SQLite")
        self.assertIn("cctv_devices", prompt)
        self.assertIn("device_label", prompt)

    def test_semantic_schema_linking(self):
        """Verify semantic vector embeddings link query terms to custom schema elements"""
        se = SchemaEngine(self.engine)
        sl = SchemaLinker(se)
        
        # Test query about cameras and faulty status
        res = sl.link_schema_and_values("Which cameras are faulty in Nariman Point?")
        
        self.assertIn("cctv_devices", res["relevant_tables"])
        
        # Check value grounding for 'SBI Nariman Point'
        grounded = res["grounded_values"]
        self.assertTrue(len(grounded) > 0)
        self.assertIn(grounded["SBI Nariman Point"]["table_name"], ["cctv_devices", "security_tickets"])


    def test_context_tracker_coreference(self):
        """Verify coreference resolution enriches follow-up queries with persistent context filters"""
        ct = ContextTracker()
        
        # Initial turn
        q1, ctx1 = ct.update_and_resolve_context("Show incidents for Bhopal LHO", {}, [])
        self.assertEqual(ctx1.get("active_lho_filter"), "Bhopal")
        
        # Follow-up turn with implicit pronoun
        q2, ctx2 = ct.update_and_resolve_context("Are any of them critical?", ctx1, [{"role": "user", "content": q1}])
        self.assertIn("in Bhopal LHO", q2)

    def test_full_integration(self):
        """Verify end-to-end ChatbotService initialization with dynamic schema engines"""
        ds = DataService()
        cb = ChatbotService(ds)
        
        self.assertIsNotNone(cb.schema_engine)
        self.assertIsNotNone(cb.schema_linker)
        self.assertIsNotNone(cb.context_tracker)

if __name__ == "__main__":
    unittest.main()
