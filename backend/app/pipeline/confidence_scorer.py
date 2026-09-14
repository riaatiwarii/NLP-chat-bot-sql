from app.config import config

class ConfidenceScorer:
    """
    Stage 12: Confidence Scoring & Abstention Check
    Evaluates multi-factor confidence signals across input parsing, value resolution,
    plan validation, and SQL validation. Triggers honest abstention if score falls below threshold.
    """
    def __init__(self):
        self.cutoff_threshold = config.CONFIDENCE_ABSTENTION_THRESHOLD

    def calculate_confidence(
        self,
        entities: list[dict],
        plan_valid: bool,
        sql_valid: bool,
        attempts_count: int
    ) -> tuple[float, bool, str]:
        """
        Returns (confidence_score: float, should_abstain: bool, clarification_reason: str).
        """
        score = 1.0
        reasons = []

        # 1. Unresolved Entity Penalty
        unresolved = [e for e in entities if not e.get("is_resolved")]
        if unresolved:
            unresolved_spans = [e.get("original_span") for e in unresolved]
            penalty = 0.40 * len(unresolved)
            score -= penalty
            reasons.append(f"could not confidently match entity '{', '.join(unresolved_spans)}' to database records")

        # 2. Entity Confidence Averages
        resolved = [e for e in entities if e.get("is_resolved")]
        if resolved:
            avg_entity_conf = sum(e.get("confidence", 1.0) for e in resolved) / len(resolved)
            score *= avg_entity_conf

        # 3. Plan Validation Penalty
        if not plan_valid:
            score -= 0.50
            reasons.append("the query plan references invalid tables or unconnected join paths")

        # 4. SQL AST / Dry-Run Validation Penalty
        if not sql_valid:
            score -= 0.50
            reasons.append("syntactic or semantic SQL validation failed")

        # 5. Retry Penalty
        if attempts_count > 1:
            score -= 0.15 * (attempts_count - 1)

        score = max(0.0, min(1.0, score))
        should_abstain = score < self.cutoff_threshold

        if should_abstain:
            clarification_msg = (
                f"I'm not confident enough to execute this query automatically because " +
                (" and ".join(reasons) if reasons else "the overall pipeline confidence score is too low") +
                ". Could you please clarify your question or specify the exact location/metric?"
            )
        else:
            clarification_msg = ""

        return score, should_abstain, clarification_msg
