"""Build a review-only manifest from offline catalogue and scoped shop records.

Never updates the catalogue or sends network requests. Private input/output files
must stay outside the public repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


def valid_record(row):
    if row.get("unscoped") or not all(row.get(k) for k in
            ("name", "detail_url", "product_id", "shop_id", "shop_name")):
        return False
    pid = str(row["product_id"])
    if not pid.isdigit():
        return False
    url = urlsplit(row["detail_url"])
    return (url.scheme == "https" and url.hostname == "haohuo.jinritemai.com"
            and not url.username and not url.password and url.port in (None, 443)
            and url.path == "/ecommerce/trade/detail/index.html"
            and parse_qs(url.query).get("id") == [pid])


def audit(products, records):
    candidates = []
    for product in products:
        if product.get("product_url"):
            continue
        try:
            meta = json.loads(product.get("link_meta") or "{}")
        except (ValueError, TypeError):
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        matches = []
        for row in records:
            try:
                valid = valid_record(row)
            except (ValueError, TypeError, AttributeError):
                valid = False
            if (valid and row["name"] == product.get("product_name")
                    and product.get("store_name") == row["shop_name"]
                    and str(meta.get("shop_id", "")) == str(row["shop_id"])):
                matches.append(row)
        if matches:
            identities = {(str(r["product_id"]), r["detail_url"]) for r in matches}
            candidates.append({"catalogue_id": product["id"],
                               "status": "single_link_candidate" if len(identities) == 1 else "multiple_link_candidates",
                               "link_option_count": len(identities),
                               "expected_before": product,
                               "records": matches,
                               "live_link_validated": False,
                               "cart_acceptance_validated": False})
    return {"mode": "review_only_no_updates", "candidates": candidates}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("records", type=Path, help="JSON list of scoped shop records")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    inputs = [args.catalogue, args.records]
    if args.output.resolve() in [p.resolve() for p in inputs]:
        parser.error("Output must not overwrite an input")
    result = audit(json.loads(args.catalogue.read_text()), json.loads(args.records.read_text()))
    result["input_sha256"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"candidate_count": len(result["candidates"]),
                      "mode": result["mode"]}))


if __name__ == "__main__":
    main()
