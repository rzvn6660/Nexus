"""Parser and Exporter for portable OKF Markdown + YAML frontmatter bundles (Phase 14B & 14H).

Supports:
- Parsing single Markdown documents with YAML frontmatter into OKFItem
- Parsing multi-document bundles separated by standard YAML document markers (`---`)
- Deterministic, reproducible export back to Markdown + YAML frontmatter
- Round-trip lossless representation
"""

import re
from datetime import date, datetime
from typing import Any
import yaml

from app.knowledge.okf.models import OKFBundle, OKFItem, OKFItemType, OKFStatus
from app.knowledge.okf.security import OKFSecurityError, OKFSecurityFilter


class OKFParseError(ValueError):
    """Raised when parsing OKF markdown frontmatter fails."""
    pass


class OKFParser:
    """Parser for portable Markdown documents with YAML frontmatter."""

    FRONTMATTER_REGEX = re.compile(
        r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?(.*)$",
        re.DOTALL
    )

    @classmethod
    def parse_document(cls, text: str) -> tuple[dict[str, Any], str]:
        """
        Extract YAML frontmatter dictionary and Markdown body.
        
        Returns:
            (frontmatter_dict, markdown_body)
        """
        trimmed = text.strip()
        if not trimmed.startswith("---"):
            raise OKFParseError("Document missing starting YAML frontmatter delimiter ('---').")

        match = cls.FRONTMATTER_REGEX.match(trimmed)
        if not match:
            # Check if document has closing delimiter
            parts = trimmed.split("---", 2)
            if len(parts) < 3:
                raise OKFParseError("Document missing closing YAML frontmatter delimiter ('---').")
            yaml_part = parts[1]
            body_part = parts[2]
        else:
            yaml_part = match.group(1)
            body_part = match.group(2)

        try:
            frontmatter = yaml.safe_load(yaml_part)
        except yaml.YAMLError as exc:
            raise OKFParseError(f"Malformed YAML in frontmatter: {exc}") from exc

        if not isinstance(frontmatter, dict):
            raise OKFParseError("YAML frontmatter must evaluate to a dictionary.")

        return frontmatter, body_part.strip()

    @classmethod
    def parse_item(cls, text: str) -> OKFItem:
        """Parse a single Markdown document into an OKFItem."""
        OKFSecurityFilter.validate_raw_bundle_text(text)
        frontmatter, body = cls.parse_document(text)

        # Merge markdown body into description if description not explicitly in frontmatter
        if body and not frontmatter.get("description"):
            frontmatter["description"] = body
        elif body and frontmatter.get("description"):
            frontmatter["description"] = f"{frontmatter['description'].strip()}\n\n{body}"

        # Sanitize text fields
        for key in ["name", "source", "author", "verified_by", "description", "formula"]:
            if key in frontmatter and isinstance(frontmatter[key], str):
                OKFSecurityFilter.sanitize_string_field(frontmatter[key], key)

        if "metadata" in frontmatter and isinstance(frontmatter["metadata"], dict):
            frontmatter["metadata"] = OKFSecurityFilter.sanitize_metadata(frontmatter["metadata"])

        try:
            return OKFItem(**frontmatter)
        except Exception as exc:
            raise OKFParseError(f"Validation failed for OKFItem: {exc}") from exc

    @classmethod
    def parse_bundle(cls, text: str) -> OKFBundle:
        """
        Parse a multi-document bundle stream into an OKFBundle.
        
        The first document must be of type 'bundle' or contain bundle metadata (id, name, author).
        Subsequent documents represent OKFItems.
        """
        OKFSecurityFilter.validate_raw_bundle_text(text)

        # Split documents by delimiter
        # Standard YAML multi-doc split
        docs_raw = re.split(r"(?m)^---\s*$", text)
        clean_docs = [d.strip() for d in docs_raw if d.strip()]

        if not clean_docs:
            raise OKFParseError("Empty bundle content.")

        # Re-attach '---' prefix for parsing
        reconstructed_docs = []
        i = 0
        while i < len(clean_docs):
            doc_str = f"---\n{clean_docs[i]}"
            # If the doc is split into yaml and markdown
            if i + 1 < len(clean_docs) and not clean_docs[i + 1].startswith("id:"):
                # Could be separated markdown body
                doc_str += f"\n---\n{clean_docs[i + 1]}"
                i += 2
            else:
                i += 1
            reconstructed_docs.append(doc_str)

        bundle_metadata: dict[str, Any] = {}
        items: list[OKFItem] = []

        for idx, doc_text in enumerate(reconstructed_docs):
            try:
                fm, body = cls.parse_document(doc_text)
            except Exception:
                # Try single-block document format
                try:
                    fm = yaml.safe_load(doc_text.replace("---", ""))
                    body = ""
                    if not isinstance(fm, dict):
                        continue
                except Exception as e:
                    raise OKFParseError(f"Error parsing document at index {idx}: {e}")

            doc_type = fm.get("type")
            if doc_type == OKFItemType.BUNDLE.value or ("id" in fm and "author" in fm and not items and not bundle_metadata):
                # Bundle manifest document
                bundle_metadata = fm
                if body and not bundle_metadata.get("description"):
                    bundle_metadata["description"] = body
            else:
                if body and not fm.get("description"):
                    fm["description"] = body
                item = OKFItem(**fm)
                items.append(item)

        if not bundle_metadata:
            raise OKFParseError("Bundle manifest document (type: bundle) missing from bundle text.")

        bundle_metadata["items"] = items
        try:
            return OKFBundle(**bundle_metadata)
        except Exception as exc:
            raise OKFParseError(f"Failed to instantiate OKFBundle: {exc}") from exc


class OKFExporter:
    """Deterministic exporter serializing OKF bundles and items to Markdown + YAML."""

    @classmethod
    def _format_date(cls, val: Any) -> str | None:
        if isinstance(val, (datetime, date)):
            return val.isoformat()
        return val

    @classmethod
    def export_item(cls, item: OKFItem) -> str:
        """Export a single OKFItem to deterministic Markdown + YAML frontmatter."""
        # Build frontmatter dict with deterministic key ordering
        fm: dict[str, Any] = {
            "id": item.id,
            "name": item.name,
            "type": item.type.value,
            "version": item.version,
            "status": item.status.value,
            "source": item.source,
            "domain": item.domain,
        }

        if item.author:
            fm["author"] = item.author
        if item.verified_by:
            fm["verified_by"] = item.verified_by
        if item.effective_from:
            fm["effective_from"] = cls._format_date(item.effective_from)
        if item.effective_to:
            fm["effective_to"] = cls._format_date(item.effective_to)
        if item.related_to:
            fm["related_to"] = sorted(item.related_to)
        if item.tags:
            fm["tags"] = sorted(item.tags)

        # KPI-specific
        if item.formula is not None:
            fm["formula"] = item.formula
        if item.synonyms:
            fm["synonyms"] = sorted(item.synonyms)
        if item.canonical_intent:
            fm["canonical_intent"] = item.canonical_intent
        if item.analytics_tool:
            fm["analytics_tool"] = item.analytics_tool
        if item.metric_field:
            fm["metric_field"] = item.metric_field
        if item.unit:
            fm["unit"] = item.unit
        if item.target_direction:
            fm["target_direction"] = item.target_direction

        # Rule / Policy
        if item.condition is not None:
            fm["condition"] = item.condition
        if item.action is not None:
            fm["action"] = item.action
        if item.scope is not None:
            fm["scope"] = item.scope
        if item.type in (OKFItemType.RULE, OKFItemType.POLICY):
            fm["priority"] = item.priority

        # Calendar
        if item.fiscal_year_start_month is not None:
            fm["fiscal_year_start_month"] = item.fiscal_year_start_month
        if item.quarter_definitions:
            fm["quarter_definitions"] = dict(sorted(item.quarter_definitions.items()))
        if item.peak_seasons:
            fm["peak_seasons"] = item.peak_seasons
        if item.blackout_dates:
            fm["blackout_dates"] = sorted(item.blackout_dates)

        # Company profile
        if item.legal_name:
            fm["legal_name"] = item.legal_name
        if item.operating_currency:
            fm["operating_currency"] = item.operating_currency
        if item.industry:
            fm["industry"] = item.industry
        if item.reporting_timezone:
            fm["reporting_timezone"] = item.reporting_timezone

        if item.metadata:
            fm["metadata"] = dict(sorted(item.metadata.items()))

        yaml_str = yaml.dump(
            fm,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        ).strip()

        desc = (item.description or "").strip()
        if desc:
            return f"---\n{yaml_str}\n---\n\n{desc}\n"
        return f"---\n{yaml_str}\n---\n"

    @classmethod
    def export_bundle(cls, bundle: OKFBundle) -> str:
        """Export an entire bundle deterministically as a multi-document Markdown string."""
        # 1. Manifest document
        manifest_fm: dict[str, Any] = {
            "id": bundle.id,
            "name": bundle.name,
            "type": OKFItemType.BUNDLE.value,
            "version": bundle.version,
            "status": bundle.status.value,
            "author": bundle.author,
        }
        if bundle.created_at:
            manifest_fm["created_at"] = cls._format_date(bundle.created_at)
        if bundle.metadata:
            manifest_fm["metadata"] = dict(sorted(bundle.metadata.items()))

        manifest_yaml = yaml.dump(
            manifest_fm,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        ).strip()

        desc = (bundle.description or "").strip()
        manifest_doc = f"---\n{manifest_yaml}\n---\n\n{desc}\n" if desc else f"---\n{manifest_yaml}\n---\n"

        # 2. Item documents sorted deterministically by ID
        sorted_items = sorted(bundle.items, key=lambda x: x.id)
        item_docs = [cls.export_item(it) for it in sorted_items]

        return manifest_doc + "\n" + "\n".join(item_docs)
