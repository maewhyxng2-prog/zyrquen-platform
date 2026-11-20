import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class KnowledgeSystem:
    """
    ZYRQUEN Native Knowledge System.
    Manages entities and relationships for reasoning and planning.
    """
    def __init__(self):
        self.graph: Dict[str, List[str]] = {}
        self.entities: Dict[str, Any] = {}

    def add_entity(self, entity_id: str, data: Dict[str, Any]):
        self.entities[entity_id] = data
        if entity_id not in self.graph:
            self.graph[entity_id] = []

    def add_relation(self, source_id: str, target_id: str):
        if source_id in self.graph:
            self.graph[source_id].append(target_id)
        else:
            self.graph[source_id] = [target_id]
        logger.info(f"Relation added: {source_id} -> {target_id}")

    def query_related(self, entity_id: str) -> List[str]:
        return self.graph.get(entity_id, [])
