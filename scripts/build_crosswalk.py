import csv
import glob
import os
import re
import unicodedata
from collections import defaultdict


INPUT_GLOB = "/workspace/split/SplitChessECO - *.csv"
OUT_DIR = "/workspace/outputs"


def normalize_text(value: str) -> str:
    text = value if value is not None else ""
    text = unicodedata.normalize("NFKC", str(text))
    return text.strip()


def sniff_delimiter(sample_path: str) -> str:
    with open(sample_path, "r", encoding="utf-8", errors="ignore") as f:
        head = f.read(4096)
    # Prefer ';' if present in header line; else default to ','
    header_line = head.splitlines()[0] if head else ""
    if header_line.count(";") > header_line.count(","):
        return ";"
    return ","


def acceptance_status(name: str) -> str:
    n = name.lower()
    if "accepted" in n:
        return "accepted"
    if "declined" in n:
        return "declined"
    return "neutral"


FAMILY_RULES = [
    (r"\bsicilian\b", "sicilian-defense"),
    (r"\bfrench\b", "french-defense"),
    (r"\bcaro[-\s]?kann\b", "caro-kann-defense"),
    (r"\bscandinavian\b|\bcenter\s+counter\b", "scandinavian-defense"),
    (r"\bitalian\b|\bgiuoco\b", "italian-game"),
    (r"\bruy\s*lopez\b|\besp[aá]nol[a]?\b", "ruy-lopez"),
    (r"\bvienna\b", "vienna-game"),
    (r"\bscotch\b", "scotch-game"),
    (r"\btwo\s+knights\b", "two-knights-defense"),
    (r"\bfour\s+knights\b", "four-knights-game"),
    (r"\bphilidor\b", "philidor-defense"),
    (r"\bpetrov\b|\brussian\b", "petrov-defense"),
    (r"\bpirc\b|\bmodern\s+defense\b|\bmodern\b", "pirc-modern"),
    (r"\balekhine?\b|\balekhine?'?s\b|\balekhine\b|\balekhine\b|\balekhine\b|\balekhine\b", "alekhine-defense"),
    (r"\bdutch\b", "dutch-defense"),
    (r"\bbenoni\b", "benoni-defense"),
    (r"\bold\s+benoni\b", "benoni-defense"),
    (r"\bmodern\s+benoni\b", "benoni-defense"),
    (r"\bbenko\b|\bvolga\b", "benko-gambit"),
    (r"\bgr[uü]nfeld\b", "grunfeld-defense"),
    (r"\bnimzo[-\s]?indian\b", "nimzo-indian-defense"),
    (r"\bbogo[-\s]?indian\b", "bogo-indian-defense"),
    (r"\bqueen'?s?\s+indian\b", "queens-indian-defense"),
    (r"\bking'?s?[-\s]?indian\b", "kings-indian-defense"),
    (r"\bslav\b", "slav-defense"),
    (r"\bsemi[-\s]?slav\b", "semi-slav-defense"),
    (r"\bqueen'?s?\s+gambit\b", "queens-gambit"),
    (r"\bcatalan\b", "catalan-opening"),
    (r"\benglish\b", "english-opening"),
    (r"\br[ée]ti\b|\breti\b", "reti-opening"),
    (r"\bbird'?s?\b", "birds-opening"),
    (r"\blondon\b", "london-system"),
    (r"\bcolle\b", "colle-system"),
    (r"\btrompowsky\b", "trompowsky-attack"),
    (r"\bveresov\b|\bjobava\b", "veresov-opening"),
    (r"\bking'?s?\s+gambit\b", "kings-gambit"),
    (r"\bcenter\s+game\b", "center-game"),
    (r"\bscandinavian\b", "scandinavian-defense"),
]


FAMILY_SYNONYMS = {
    "king s": "kings",
    "queen s": "queens",
    "bird s": "birds",
    "ruy l pez": "ruy lopez",
    "gr nfeld": "grunfeld",
}


def canonical_family(name: str, eco_code: str) -> tuple[str, float]:
    n = name.lower()
    for k, v in FAMILY_SYNONYMS.items():
        n = n.replace(k, v)
    for pattern, fam in FAMILY_RULES:
        if re.search(pattern, n):
            return fam, 0.99

    # Special inference: Dutch Staunton (even if not containing the word Gambit)
    if re.search(r"\bdutch\b", n) and re.search(r"\bstaunton\b", n):
        return "dutch-defense", 0.95

    eco = (eco_code or "").upper().strip()
    # ECO band fallbacks
    if re.match(r"B[2-9]\d", eco):
        return "sicilian-defense", 0.90
    if re.match(r"C0\d|C1\d", eco):
        return "french-defense", 0.90
    if re.match(r"B1\d", eco):
        return "caro-kann-defense", 0.85
    if re.match(r"B0[67-9]", eco):
        return "pirc-modern", 0.80
    if re.match(r"B0[0-5]", eco):
        return "open-games", 0.80
    if re.match(r"A8\d|A9\d", eco):
        return "dutch-defense", 0.90
    if re.match(r"A5[6-9]|A7\d", eco):
        return "benoni-defense", 0.85
    if re.match(r"D0\d|D3\d|D4\d|D6\d", eco):
        return "queens-gambit", 0.85
    if re.match(r"D1\d", eco):
        return "slav-defense", 0.85
    if re.match(r"D2\d|D5\d", eco):
        return "queens-gambit", 0.80
    if re.match(r"E0[0-9]", eco):
        return "catalan-opening", 0.80
    if re.match(r"E2\d", eco):
        return "nimzo-indian-defense", 0.85
    if re.match(r"E3\d", eco):
        return "queens-indian-defense", 0.85
    if re.match(r"E6\d", eco):
        return "kings-indian-defense", 0.85
    if re.match(r"D7\d|D8\d|D9\d", eco):
        return "grunfeld-defense", 0.85

    return "", 0.0


def read_rows() -> list[dict]:
    rows: list[dict] = []
    files = sorted(glob.glob(INPUT_GLOB))
    if not files:
        return rows
    # Detect delimiter using the first file
    delimiter = sniff_delimiter(files[0])
    for path in files:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for r in reader:
                norm = {k: normalize_text(v) for k, v in r.items()}
                norm["__source_file"] = os.path.basename(path)
                rows.append(norm)
    return rows


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    rows = read_rows()
    crosswalk = []
    review = []
    families = {}

    # Attempt to detect header variants
    for r in rows:
        name = r.get("Name") or r.get("name") or r.get("opening") or r.get("alias_name") or ""
        eco = r.get("eco") or r.get("ECO") or r.get("eco_code") or ""
        slug = r.get("slug") or r.get("alias_slug") or ""
        fam_hint = r.get("family name") or r.get("family_name") or r.get("family") or ""

        acc = acceptance_status(name)

        fam_key = ""
        conf = 0.0
        if fam_hint and fam_hint.upper() != "#N/A":
            fam_norm = fam_hint
            fam_norm = unicodedata.normalize("NFKD", fam_norm)
            fam_norm = fam_norm.replace("’", "'").replace("`", "'").replace("´", "'")
            fam_norm = re.sub(r"'s\b", "s", fam_norm)
            fam_norm = re.sub(r"[^A-Za-z0-9]+", "-", fam_norm.strip())
            fam_key = fam_norm.lower().strip("-")
            # Map some common variants
            fam_key = fam_key.replace("-s-", "s-")
            fam_key = fam_key.replace("-s-", "s-")
            fam_key = fam_key.replace("-gambit-gambit", "-gambit")
            conf = 0.90

        if not fam_key:
            fam_key, conf = canonical_family(name, eco)

        needs_review = False
        notes = ""

        # Special Dutch Staunton handling: infer gambit system for acceptance facet linking downstream
        if re.search(r"\bdutch\b", name.lower()) and re.search(r"\bstaunton\b", name.lower()):
            notes = "inferred staunton under dutch"

        if not fam_key or conf < 0.85:
            needs_review = True

        crosswalk.append({
            "source": r.get("__source_file", "split"),
            "alias_name": name,
            "alias_slug": slug,
            "eco_code": eco,
            "canonical_family_key": fam_key,
            "acceptance_status": acc,
            "confidence": f"{conf:.2f}",
            "needs_review": "TRUE" if needs_review else "FALSE",
            "notes": notes,
        })

        if fam_key:
            families[fam_key] = families.get(fam_key, 0) + 1
        if needs_review:
            review.append({
                "alias_name": name,
                "alias_slug": slug,
                "eco_code": eco,
                "reason": "low_confidence_or_unmatched",
            })

    # Write outputs
    cw_path = os.path.join(OUT_DIR, "FamilyCrosswalk.csv")
    with open(cw_path, "w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "source",
            "alias_name",
            "alias_slug",
            "eco_code",
            "canonical_family_key",
            "acceptance_status",
            "confidence",
            "needs_review",
            "notes",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(crosswalk)

    rv_path = os.path.join(OUT_DIR, "AliasReview.csv")
    with open(rv_path, "w", encoding="utf-8", newline="") as f:
        fieldnames = ["alias_name", "alias_slug", "eco_code", "reason"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review)

    fam_path = os.path.join(OUT_DIR, "FamilyCanonical.csv")
    with open(fam_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["canonical_family_key", "canonical_family_name", "eco_group", "notes"])
        for key in sorted(families.keys()):
            disp = " ".join(part.capitalize() for part in key.split("-"))
            writer.writerow([key, disp, "", "seeded from alias mapping frequency"])

    print(f"Wrote: {cw_path}\nWrote: {rv_path}\nWrote: {fam_path}")


if __name__ == "__main__":
    main()

