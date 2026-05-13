from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillCard:
    name: str
    path: Path
    description: str


def list_skills(skills_dir: Path) -> list[SkillCard]:
    if not skills_dir.exists():
        return []
    cards: list[SkillCard] = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        name = skill_md.parent.name
        description = ""
        for line in text.splitlines():
            if line.startswith("description:"):
                description = line.split(":", 1)[1].strip().strip('"')
                break
        cards.append(SkillCard(name=name, path=skill_md, description=description))
    return cards


def read_skill(skills_dir: Path, name: str) -> str:
    safe_name = name.replace("/", "").replace("..", "")
    path = skills_dir / safe_name / "SKILL.md"
    if not path.exists():
        raise FileNotFoundError(f"Unknown skill: {name}")
    return path.read_text(encoding="utf-8")


def render_skill_summary(skills_dir: Path) -> str:
    cards = list_skills(skills_dir)
    if not cards:
        return "No local skills are installed."
    return "\n".join(f"- {card.name}: {card.description}" for card in cards)

