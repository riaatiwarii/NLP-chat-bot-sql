import re

class ContextTracker:
    """
    Dialogue Context Tracker & Coreference Resolver.
    Maintains conversational state filters across multi-turn interactions 
    and enriches follow-up user questions with implicit entities from history.
    """

    KNOWN_LHOS = [
        "bhopal", "mumbai metro", "maharashtra", "bengaluru", "kolkata", 
        "new delhi", "delhi", "chennai", "hyderabad", "trivandrum", 
        "chandigarh", "jaipur", "bhubaneswar", "patna", "lucknow", 
        "guwahati", "amaravati", "gandhinagar"
    ]

    def __init__(self):
        pass

    def update_and_resolve_context(self, message_text, context_dict, history_list):
        """
        Updates persistent conversation filters and resolves coreferences in follow-up queries.
        
        Returns:
            resolved_query (str): Enriched query text with explicit entities
            updated_context (dict): Updated filter context dictionary
        """
        context = dict(context_dict) if context_dict else {}
        msg_lower = message_text.strip().lower()

        # 1. Entity Extraction - LHO Circles
        for lho in self.KNOWN_LHOS:
            if re.search(r'\b' + re.escape(lho) + r'\b', msg_lower):
                mapped_lho = "New Delhi" if lho == "delhi" else lho.title()
                context["active_lho_filter"] = mapped_lho
                break

        # 2. Entity Extraction - Branch Names
        branch_match = re.search(r'(?:at|for|branch|in|sbi)\s+(sbi\s+[a-zA-Z\s]+|ao_[a-zA-Z]+)', msg_lower)
        if branch_match:
            raw_branch = branch_match.group(1).strip()
            branch_name = raw_branch.upper() if raw_branch.startswith("ao_") else raw_branch.title()
            if not branch_name.startswith("Sbi ") and not branch_name.startswith("AO_"):
                branch_name = "Sbi " + branch_name
            context["active_branch_filter"] = branch_name

        # 3. Coreference Resolution for Follow-up Queries
        resolved_query = message_text

        # Check for implicit pronouns or follow-up indicators ("them", "this branch", "those alerts")
        has_pronoun = any(word in msg_lower for word in ["them", "these", "those", "it", "this branch", "here"])
        
        if has_pronoun or len(msg_lower.split()) <= 4:
            active_branch = context.get("active_branch_filter")
            active_lho = context.get("active_lho_filter")

            # Enrich query if active filters exist in context
            additions = []
            if active_branch and active_branch.lower() not in msg_lower:
                additions.append(f"at branch {active_branch}")
            elif active_lho and active_lho.lower() not in msg_lower:
                additions.append(f"in {active_lho} LHO")

            if additions:
                resolved_query = f"{message_text} ({', '.join(additions)})"

        return resolved_query, context
