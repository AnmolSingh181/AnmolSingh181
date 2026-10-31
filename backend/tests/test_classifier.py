from app.services.ai_classifier import validate_ai_output
from app.services.classifier import classify_text, find_polymers


def rows(text):
    return {(m.polymer, m.grade_category, m.application, m.relationship) for m in classify_text(text).materials}


def test_lldpe_not_confused_with_ldpe():
    assert [p for p, _, _ in find_polymers("We sell LLDPE only")] == ["LLDPE"]
    assert [p for p, _, _ in find_polymers("Linear low density polyethylene")] == ["LLDPE"]
    assert [p for p, _, _ in find_polymers("low density polyethylene")] == ["LDPE"]
    assert {p for p, _, _ in find_polymers("PE-LD, PE-LLD and PE-HD")} == {"LDPE", "LLDPE", "HDPE"}


def test_grades_applications_relationship_per_clause():
    r = rows("We supply virgin LLDPE film grade and off-grade LDPE in 25 kg bags.")
    assert ("LLDPE", "virgin_prime", "film", "seller") in r
    assert ("LDPE", "off_grade", "unknown", "seller") in r
    assert not any(p == "LDPE" and g == "virgin_prime" for p, g, _, _ in r)


def test_buyer_intent_and_recycled_categories():
    r = rows("We buy recycled HDPE regrind and post-consumer HDPE flakes for blow moulding.")
    assert ("HDPE", "recycled", "unknown", "buyer") in r
    assert ("HDPE", "pcr", "blow_moulding", "buyer") in r


def test_specs_only_when_explicit():
    res = classify_text("We supply virgin LLDPE film grade (SABIC 218W, MFI 2.0 g/10 min, density 0.918 g/cm3).")
    spec = res.materials[0].specs[0]
    assert (spec.brand, spec.grade_number, spec.mfi, spec.density) == ("SABIC", "218W", 2.0, 0.918)
    res2 = classify_text("We supply virgin LLDPE film grade.")
    assert all(not m.specs for m in res2.materials)


def test_non_prime_needs_review():
    res = classify_text("Non-prime LDPE available for sale.")
    m = [m for m in res.materials if m.polymer == "LDPE"][0]
    assert m.grade_category == "non_prime_unspecified" and m.review_status == "needs_review"


def test_unknown_when_no_intent():
    assert rows("Products: LDPE, LLDPE and HDPE film grade.") == {
        ("LDPE", "unknown", "film", "unknown"), ("LLDPE", "unknown", "film", "unknown"), ("HDPE", "unknown", "film", "unknown")}


def test_converter_is_not_resin_manufacturer():
    res = classify_text("We are a manufacturer of plastic bags and shrink films made from LDPE.")
    cats = {b.category for b in res.business_types}
    assert "converter" in cats and "manufacturer" not in cats
    res2 = classify_text("Leading petrochemical company and polyethylene producer with a steam cracker.")
    assert "manufacturer" in {b.category for b in res2.business_types}


def test_price_and_quantity_extraction():
    res = classify_text("Off-grade LDPE film grade, 300 MT available per month. Price USD 950/MT CIF.")
    m = [m for m in res.materials if m.polymer == "LDPE"][0]
    assert m.available_quantity == 300 and m.quantity_period == "month"
    assert res.prices and res.prices[0].price == 950 and res.prices[0].currency == "USD" and res.prices[0].incoterm == "CIF"


def test_ai_output_validated_against_evidence():
    src = "We supply virgin LLDPE film grade with MFI 1.0 from stock."
    data = {"materials": [
        {"polymer": "LLDPE", "grade_category": "virgin_prime", "application": "film", "relationship": "seller", "form": None,
         "evidence_quote": "We supply virgin LLDPE film grade with MFI 1.0", "mfi": 1.0, "density": 0.92,
         "grade_number": "1002YB", "brand": None, "colour": None, "available_quantity_mt": 500, "required_quantity_mt": None},
        {"polymer": "HDPE", "grade_category": "recycled", "application": "pipe", "relationship": "buyer", "form": None,
         "evidence_quote": "We buy HDPE pipe scrap", "mfi": None, "density": None, "grade_number": None, "brand": None,
         "colour": None, "available_quantity_mt": None, "required_quantity_mt": None}],
        "business_types": [{"category": "trader", "evidence_quote": "invented sentence not in the text"}]}
    res, rejected = validate_ai_output(data, src)
    assert len(res.materials) == 1  # HDPE quote is not in the source -> dropped
    m = res.materials[0]
    assert m.specs[0].mfi == 1.0
    assert m.specs[0].density is None and m.specs[0].grade_number is None and m.available_quantity is None
    assert not res.business_types
    assert any("density" in r for r in rejected) and any("not found" in r for r in rejected)
