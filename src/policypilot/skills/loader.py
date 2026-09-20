"""Lazy, path-safe loading for PolicyPilot skill artifacts and references."""

from __future__ import annotations

import re
from pathlib import Path

from policypilot.skills.models import (
    LoadedSkillReference,
    SkillArtifact,
    SkillMetadata,
    SkillPhase,
    SkillReference,
)

_HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_PHASES = frozenset({"planning", "decision", "recovery"})


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


def _frontmatter_values(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    parent: str | None = None
    for line in lines:
        key, separator, value = line.partition(":")
        if not separator:
            continue
        if line[:1].isspace() and parent:
            full_key = f"{parent}.{key.strip().lower()}"
        else:
            full_key = key.strip().lower()
            parent = full_key if not value.strip() else None
        values[full_key] = value.strip().strip("\"'")
    return values


class SkillLoader:
    """Read only frontmatter for discovery; load bodies after selection."""

    def __init__(self, root: Path | None = None):
        self.root = (root or Path(__file__).resolve().parents[3] / "skills").resolve()
        self._metadata: dict[str, SkillMetadata] | None = None
        self._artifacts: dict[str, SkillArtifact] = {}
        self._reference_contents: dict[tuple[str, str], LoadedSkillReference] = {}

    def metadata(self) -> list[SkillMetadata]:
        if self._metadata is None:
            discovered: dict[str, SkillMetadata] = {}
            if self.root.exists():
                for path in sorted(self.root.glob("*/SKILL.md")):
                    frontmatter, _ = self._read(path, body=False)
                    metadata = self._skill_metadata(path, frontmatter)
                    discovered[metadata.name] = metadata
            self._metadata = discovered
        return sorted(
            self._metadata.values(), key=lambda item: (-item.priority, item.name)
        )

    def load(self, name: str) -> SkillArtifact | None:
        if name in self._artifacts:
            return self._artifacts[name]
        metadata = next((item for item in self.metadata() if item.name == name), None)
        if metadata is None:
            return None
        _, body = self._read(metadata.path, body=True)
        artifact = SkillArtifact(
            metadata=metadata,
            sections=self._sections(body),
            available_references=self._reference_metadata(metadata.path.parent),
        )
        self._artifacts[name] = artifact
        return artifact

    def load_reference(
        self, skill_name: str, reference: SkillReference
    ) -> LoadedSkillReference | None:
        cache_key = (skill_name, reference.id)
        if cache_key in self._reference_contents:
            return self._reference_contents[cache_key]
        artifact = self.load(skill_name)
        if artifact is None or reference not in artifact.available_references:
            return None
        references_dir = (artifact.metadata.path.parent / "references").resolve()
        path = reference.path.resolve()
        try:
            path.relative_to(references_dir)
        except ValueError:
            return None
        if path.suffix.lower() != ".md" or not path.is_file():
            return None
        _, body = self._read(path, body=True)
        loaded = LoadedSkillReference(reference, body.strip())
        self._reference_contents[cache_key] = loaded
        return loaded

    def _reference_metadata(self, skill_dir: Path) -> tuple[SkillReference, ...]:
        references_dir = (skill_dir / "references").resolve()
        try:
            references_dir.relative_to(skill_dir.resolve())
        except ValueError:
            return ()
        if not references_dir.is_dir():
            return ()
        references: dict[str, SkillReference] = {}
        for path in sorted(references_dir.glob("*.md")):
            frontmatter, _ = self._read(path, body=False)
            reference_id = frontmatter.get("id", path.stem).strip()
            references[reference_id] = SkillReference(
                id=reference_id,
                description=frontmatter.get("description", "").strip(),
                path=path,
                applicable_phases=self._phases(
                    frontmatter.get("phases", "planning,decision,recovery")
                ),
                trigger_tags=_csv(frontmatter.get("trigger-tags", "")),
                priority=self._integer(frontmatter.get("priority"), 50),
            )
        return tuple(
            sorted(references.values(), key=lambda item: (-item.priority, item.id))
        )

    def _skill_metadata(self, path: Path, values: dict[str, str]) -> SkillMetadata:
        return SkillMetadata(
            name=values.get("name", path.parent.name).strip(),
            description=values.get("description", "").strip(),
            path=path,
            version=values.get("metadata.version", "1.0").strip(),
            purpose=values.get("metadata.purpose", "").strip(),
            tags=_csv(values.get("metadata.tags", "")),
            phases=self._phases(
                values.get("metadata.phases", "planning,decision,recovery")
            ),
            priority=self._integer(values.get("metadata.priority"), 50),
            required_state_fields=_csv(
                values.get("metadata.required-state-fields", "")
            ),
        )

    @staticmethod
    def _read(path: Path, *, body: bool) -> tuple[dict[str, str], str]:
        if not body:
            frontmatter_lines: list[str] = []
            with path.open("r", encoding="utf-8") as handle:
                if handle.readline().strip() != "---":
                    return {}, ""
                for line in handle:
                    if line.strip() == "---":
                        break
                    frontmatter_lines.append(line.rstrip("\r\n"))
            return _frontmatter_values(frontmatter_lines), ""
        text = path.read_text(encoding="utf-8")
        frontmatter, content = SkillLoader._split_frontmatter(text)
        return frontmatter, content if body else ""

    @staticmethod
    def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
        normalized = text.replace("\r\n", "\n")
        if not normalized.startswith("---\n"):
            return {}, normalized
        end = normalized.find("\n---\n", 4)
        if end < 0:
            return {}, normalized
        values = _frontmatter_values(normalized[4:end].splitlines())
        return values, normalized[end + 5 :]

    @staticmethod
    def _phases(value: str) -> tuple[SkillPhase, ...]:
        phases = tuple(item for item in _csv(value) if item in _PHASES)
        return phases  # type: ignore[return-value]

    @staticmethod
    def _integer(value: str | None, default: int) -> int:
        try:
            return int(value) if value is not None else default
        except ValueError:
            return default

    @staticmethod
    def _sections(body: str) -> dict[str, str]:
        matches = list(_HEADING.finditer(body))
        return {
            match.group(1).strip(): body[
                match.end() : matches[index + 1].start()
            ].strip()
            if index + 1 < len(matches)
            else body[match.end() :].strip()
            for index, match in enumerate(matches)
        }
