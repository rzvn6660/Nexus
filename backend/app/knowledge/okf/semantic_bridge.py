"""OKF Semantic Resolution Bridge for NEXUS (Phase 14F).

Integrates portable OKF business context with the Phase 13 Canonical Intent Taxonomy
and KPIOntology / SemanticResolver without duplicating or displacing the taxonomy.

Architecture Invariants:
1. CanonicalIntent.SEMANTIC_RESOLUTION is the authoritative intent for definitional inquiries.
2. Business synonyms map into existing canonical concepts or provide policy/definition lookups.
3. Business definitions tell what terms mean; they NEVER manufacture factual analytics numbers.
4. Conflicting definitions are surfaced explicitly as ambiguities rather than guessed.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from app.decisions.taxonomy import CanonicalIntent
from app.knowledge.okf.models import OKFBundle, OKFItem, OKFItemType
from app.rag.semantic.models import KPI, BusinessDomain, MetricUnit
from app.rag.semantic.ontology import KPIOntology, SemanticResolver


@dataclass
class OKFDefinitionResolution:
    """Result of resolving a query against the OKF business knowledge layer."""
    term: str
    item_id: str
    item_name: str
    item_type: str
    definition: str
    formula: str | None = None
    canonical_intent: str = CanonicalIntent.SEMANTIC_RESOLUTION.value
    mapped_kpi_canonical: str | None = None
    source: str = ""
    is_business_definition: bool = True
    is_ambiguous: bool = False
    ambiguity_candidates: list[str] = field(default_factory=list)
    has_conflict: bool = False
    conflict_description: str | None = None


class OKFSemanticBridge:
    """
    Bridges OKF business knowledge into NEXUS semantic resolution.
    
    Provides:
    - Company-specific abbreviation and synonym lookup ("What does GP mean?")
    - Custom business concept resolution ("What do we call repeat customers?")
    - Policy and calendar inquiry resolution ("What is our return policy?")
    - Registration of OKF synonyms into the runtime KPIOntology
    """

    def __init__(self, ontology: KPIOntology | None = None) -> None:
        self.ontology = ontology or KPIOntology()
        self._items_by_id: dict[str, OKFItem] = {}
        self._synonym_index: dict[str, list[str]] = {}  # lowercase term -> list of item_ids

    def register_bundle(self, bundle: OKFBundle) -> None:
        """Index all items and synonyms in an OKF bundle."""
        for item in bundle.items:
            self.register_item(item)

    def register_item(self, item: OKFItem) -> None:
        """Index a single OKF item and its synonyms."""
        self._items_by_id[item.id] = item

        terms = [item.name.lower().strip()]
        for s in item.synonyms:
            terms.append(s.lower().strip())

        for t in terms:
            if not t:
                continue
            if t not in self._synonym_index:
                self._synonym_index[t] = []
            if item.id not in self._synonym_index[t]:
                self._synonym_index[t].append(item.id)

        # If item is a verified KPI and maps to an existing canonical KPI, register synonyms
        if item.type == OKFItemType.KPI and item.metric_field:
            existing_kpi = self.ontology.get_kpi(item.metric_field)
            if existing_kpi:
                for syn in item.synonyms:
                    self.ontology._synonym_map[syn.lower().strip()] = existing_kpi.canonical_name

    def resolve_term(self, query: str) -> OKFDefinitionResolution | None:
        """
        Check if the query asks about or matches an OKF business definition or term.
        Longest matching phrase takes precedence.
        """
        clean = query.lower().strip()
        clean = re.sub(r"[?!.,;:]+$", "", clean)

        # Sort indexed terms by length descending to match specific multi-word phrases first
        sorted_terms = sorted(self._synonym_index.keys(), key=len, reverse=True)

        for term in sorted_terms:
            pattern = rf"\b{re.escape(term)}(?:s|es)?\b"
            if re.search(pattern, clean):
                item_ids = self._synonym_index[term]

                # Conflict detection: more than one item registered for the exact same term with differing definitions
                if len(item_ids) > 1:
                    conflicting_items = [self._items_by_id[i] for i in item_ids if i in self._items_by_id]
                    # Check if they have differing formulas or descriptions
                    desc_set = {it.description.strip() for it in conflicting_items if it.description}
                    if len(desc_set) > 1 or len(conflicting_items) > 1:
                        names = [it.name for it in conflicting_items]
                        return OKFDefinitionResolution(
                            term=term,
                            item_id=conflicting_items[0].id,
                            item_name=conflicting_items[0].name,
                            item_type=conflicting_items[0].type.value,
                            definition=f"Conflicting definitions found for term '{term}'.",
                            canonical_intent=CanonicalIntent.SEMANTIC_RESOLUTION.value,
                            is_ambiguous=True,
                            ambiguity_candidates=names,
                            has_conflict=True,
                            conflict_description=(
                                f"Ambiguity/Conflict detected: Business knowledge contains conflicting definitions "
                                f"for '{term}' across items: {', '.join(names)}."
                            ),
                        )

                item = self._items_by_id.get(item_ids[0])
                if not item:
                    continue

                # Clean definition text
                definition_text = item.description or f"{item.name} is defined in {item.source}."
                return OKFDefinitionResolution(
                    term=term,
                    item_id=item.id,
                    item_name=item.name,
                    item_type=item.type.value,
                    definition=definition_text,
                    formula=item.formula,
                    canonical_intent=CanonicalIntent.SEMANTIC_RESOLUTION.value,
                    mapped_kpi_canonical=item.metric_field,
                    source=item.source,
                    is_business_definition=True,
                    is_ambiguous=False,
                )

        return None
