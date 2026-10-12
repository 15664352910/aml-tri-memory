"""AML Tri-Memory: a three-layer long-term memory service for the
Agent Memory Leaderboard (AML) Add/Search contract.

Design is derived from the Tri-Memory research project
(persona / episodic / world-model layers with typed governance),
re-engineered for the competition contract: strict user_id isolation,
synchronous ingestion, evidence-only Search, and abstention by
returning an empty data array.
"""

__version__ = "0.1.0"
