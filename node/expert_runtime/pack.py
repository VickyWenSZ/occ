from pathlib import Path
import yaml
from node.retrieval.search import keyword_search


class ExpertPack:
    def __init__(self, pack_dir: Path):
        self.pack_dir = Path(pack_dir)
        self.wiki_dir = self.pack_dir / "wiki"
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> dict:
        p = self.pack_dir / "manifest.yaml"
        if p.exists():
            return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return {}

    def retrieve(self, query: str, max_chars: int = 8000) -> str:
        return keyword_search(self.wiki_dir, query, max_chars=max_chars)

    @property
    def name(self) -> str:
        return self.manifest.get("name", self.pack_dir.name)

    @property
    def domains(self) -> list[str]:
        return self.manifest.get("domains", [self.pack_dir.name])


class MultiPackRetriever:
    """Retrieves knowledge from multiple expert packs simultaneously."""

    def __init__(self, packs: list[ExpertPack]):
        self.packs = packs

    def retrieve(self, query: str, max_chars: int = 8000) -> str:
        if not self.packs:
            return ""
        per_pack = max_chars // len(self.packs)
        results = []
        for pack in self.packs:
            r = pack.retrieve(query, max_chars=per_pack)
            if r:
                results.append(f"=== [{pack.name}] ===\n{r}")
        return "\n\n".join(results)

    @property
    def name(self) -> str:
        return "+".join(p.name for p in self.packs)

    @property
    def domains(self) -> list[str]:
        seen, result = set(), []
        for p in self.packs:
            for d in p.domains:
                if d not in seen:
                    seen.add(d)
                    result.append(d)
        return result


def load_pack(pack_path: str | Path) -> ExpertPack:
    return ExpertPack(Path(pack_path))


def load_all_packs(packs_root: Path) -> MultiPackRetriever:
    """Auto-discover and load all valid packs from expert-packs/."""
    packs = []
    if packs_root.exists():
        for d in sorted(packs_root.iterdir()):
            if d.is_dir() and (d / "manifest.yaml").exists():
                packs.append(ExpertPack(d))
    return MultiPackRetriever(packs)
