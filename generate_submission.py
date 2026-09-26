"""
generate_submission.py — Generates the 30 canonical test evaluations for submission.jsonl
========================================================================================

Reads:
    dataset/expanded/test_pairs.json (T01 - T30)
    dataset/expanded/categories/*.json
    dataset/expanded/merchants/*.json
    dataset/expanded/customers/*.json
    dataset/expanded/triggers/*.json

Calls:
    composer.compose(category, merchant, trigger, customer)

Outputs:
    submission.jsonl (30 lines, one per test pair)
"""

import json
from pathlib import Path
from composer import compose

BASE_DIR = Path(__file__).parent.resolve()
EXPANDED_DIR = BASE_DIR / "dataset" / "expanded"
TEST_PAIRS_FILE = EXPANDED_DIR / "test_pairs.json"
OUTPUT_FILE = BASE_DIR / "submission.jsonl"


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    if not TEST_PAIRS_FILE.exists():
        raise FileNotFoundError(f"Missing {TEST_PAIRS_FILE}. Please run generate_dataset.py first.")

    pairs_data = load_json(TEST_PAIRS_FILE)
    pairs = pairs_data.get("pairs", [])
    print(f"Loaded {len(pairs)} test pairs from {TEST_PAIRS_FILE}")

    categories_cache = {}
    for cat_file in (EXPANDED_DIR / "categories").glob("*.json"):
        cat_data = load_json(cat_file)
        categories_cache[cat_data.get("slug", cat_file.stem)] = cat_data

    submissions = []

    for pair in pairs:
        test_id = pair["test_id"]
        m_id = pair["merchant_id"]
        t_id = pair["trigger_id"]
        c_id = pair.get("customer_id")

        m_path = EXPANDED_DIR / "merchants" / f"{m_id}.json"
        t_path = EXPANDED_DIR / "triggers" / f"{t_id}.json"
        c_path = (EXPANDED_DIR / "customers" / f"{c_id}.json") if c_id else None

        merchant = load_json(m_path) if m_path.exists() else {}
        trigger = load_json(t_path) if t_path.exists() else {}
        customer = load_json(c_path) if (c_path and c_path.exists()) else None

        cat_slug = merchant.get("category_slug", "dentists")
        category = categories_cache.get(cat_slug, {})

        # Invoke composer
        result = compose(category, merchant, trigger, customer)

        submission_entry = {
            "test_id": test_id,
            "body": result["body"],
            "cta": result["cta"],
            "send_as": result["send_as"],
            "suppression_key": result["suppression_key"],
            "rationale": result["rationale"],
        }
        submissions.append(submission_entry)

    # Write submission.jsonl
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for entry in submissions:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"Successfully generated {len(submissions)} entries in {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

