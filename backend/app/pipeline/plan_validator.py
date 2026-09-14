from app.pipeline.schema_graph import SchemaGraph

class PlanValidator:
    """
    Stage 8: Plan Validation
    Validates structured query plan against NetworkX schema graph.
    Checks table existence, column existence, and foreign key join connectivity.
    """
    def __init__(self, schema_graph: SchemaGraph):
        self.schema_graph = schema_graph

    def validate(self, plan: dict) -> tuple[bool, str]:
        """
        Returns (is_valid: bool, error_message: str).
        """
        if not isinstance(plan, dict):
            return False, "Plan is not a valid JSON dictionary object."

        tables_needed = plan.get("tables_needed", [])
        if not tables_needed or not isinstance(tables_needed, list):
            return False, "Plan does not specify any valid 'tables_needed'."

        # Extract all referenced columns
        columns_ref = []
        for f in plan.get("filters", []):
            if isinstance(f, dict):
                col = f.get("column")
                tbl = f.get("table", tables_needed[0])
                if col:
                    columns_ref.append((tbl, col))

        group_by = plan.get("group_by")
        if group_by and isinstance(group_by, list):
            for col in group_by:
                columns_ref.append((tables_needed[0], col))

        # Perform schema graph validation
        is_valid, reason = self.schema_graph.validate_plan_schema(tables_needed, columns_ref)
        return is_valid, reason
