"""Generate the synthetic documents, and the ground truth that goes with them.

Every document in docs/ is drawn here from the facts in SPECS. Nothing is
scanned, downloaded or photographed, which matters for two reasons.

The repository is public. A real payslip or invoice carries a real person's
name, address and national insurance or social security number, and anything
committed to a public repository stays public after it is deleted. Drawing the
documents means there is no real personal data in the project to leak in the
first place, rather than a redaction step that has to work perfectly every time.

The second reason is the useful one. Because the facts are written down before
the image exists, every extraction can be **scored**. Most document-AI demos
show you a JSON blob and leave you to eyeball whether it is right. Here the
answer key is `docs/ground_truth.json`, so Textract and a foundation model can
be marked against the same set of facts and the comparison means something.

The images are deliberately plain: black text, white background, a clean
sans-serif. That makes the OCR task easy, so anything either approach gets
wrong is a failure of understanding rather than of image quality. A noisy scan
would be more realistic and would confound the comparison.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

FONT_DIR = Path("/System/Library/Fonts/Supplemental")
W, H = 1240, 1754  # A4 at 150 dpi


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for candidate in (FONT_DIR / name, Path("/Library/Fonts") / name):
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default(size)


REG, BOLD, MONO = "Arial.ttf", "Arial Bold.ttf", "Courier New.ttf"


# --- the facts ------------------------------------------------------------
# Written first. The images are rendered from these, and extraction is scored
# against them. Every person, company, address and identifier is invented, and
# where a reserved range exists for fiction it is used, because these values go
# into a public repository under labels like "Social Security Number":
#
#   SSN     900-999 as the area number. The SSA has never issued those, so the
#           number cannot belong to anyone. The first draft used a made-up
#           number in a real assigned range, which is structurally valid and
#           could be somebody's. Making one up is not the same as it being
#           unused, and this one is published under the label "Social Security
#           Number".
#   Phone   555-0100 to 555-0199, the block reserved for fictional use.
#   Email   the .example TLD, reserved by RFC 2606 and unregistrable.

SPECS = {
    "invoice": {
        "fields": {
            "invoice_number": "INV-2026-0417",
            "invoice_date": "2026-03-14",
            "due_date": "2026-04-13",
            "vendor_name": "Meridian Supply Co.",
            "customer_name": "Harlow Analytics Ltd",
            "subtotal_usd": 4820.00,
            "tax_usd": 433.80,
            "total_usd": 5253.80,
            "contact_email": "billing@meridiansupply.example",
            "contact_phone": "555-0182",
        },
        "line_items": [
            ("Standing desk frame", 4, 620.00, 2480.00),
            ("Monitor arm, dual", 6, 145.00, 870.00),
            ("Acoustic panel, 60cm", 15, 98.00, 1470.00),
        ],
        "pii_expected": ["EMAIL", "PHONE"],
    },
    "paystub": {
        "fields": {
            "employee_name": "Dana Whitfield",
            "employee_id": "EMP-55213",
            "ssn": "900-55-8907",  # 900-999 is never issued by the SSA, so this cannot be anyone's
            "pay_period_end": "2026-02-28",
            "gross_pay_usd": 5400.00,
            "net_pay_usd": 3867.42,
            "employer_name": "Northbank Logistics",
        },
        "deductions": [
            ("Federal income tax", 918.00),
            ("Social security", 334.80),
            ("Medicare", 78.30),
            ("Health plan", 201.48),
        ],
        "pii_expected": ["NAME", "SSN"],
    },
    "letter": {
        "fields": {
            "sender_name": "Dr. Imogen Clarke",
            "recipient_name": "Marcus Bell",
            "letter_date": "2026-01-22",
            "clinic_name": "Fenwick Road Practice",
            "appointment_date": "2026-02-09",
        },
        "body": [
            "Dear Mr Bell,",
            "",
            "Thank you for attending the Fenwick Road Practice on 22 January 2026.",
            "Your blood pressure was 128 over 82, which is a clear improvement on",
            "the reading taken in November, and your cholesterol has come down to",
            "4.9 mmol/L.",
            "",
            "I would like to see you again on 9 February 2026 at 10:30 to review",
            "the medication. Please continue the current dose until then. If you",
            "have questions before that date you can reach the practice on",
            "555-0133 or by email at reception@fenwickroad.example.",
            "",
            "I was sorry to hear the move to Dorchester has been stressful. Do",
            "mention it at the next appointment.",
            "",
            "Kind regards,",
            "Dr. Imogen Clarke",
        ],
        "pii_expected": ["NAME", "PHONE", "EMAIL", "ADDRESS"],
        "note": "Free prose rather than a form. Textract's form extraction has "
                "almost nothing to grip here, which is the point: this is the "
                "document that belongs to Comprehend.",
    },
}


def draw_invoice(spec: dict) -> Image.Image:
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f = spec["fields"]

    d.text((80, 70), "INVOICE", font=font(BOLD, 52), fill="black")
    d.text((80, 150), f["vendor_name"], font=font(BOLD, 28), fill="black")
    d.text((80, 190), "118 Kesteven Way, Portland, OR 97204", font=font(REG, 20), fill="#333")
    d.text((80, 220), f"{f['contact_email']}   ·   {f['contact_phone']}", font=font(REG, 20), fill="#333")

    y = 310
    for label, value in (("Invoice Number", f["invoice_number"]),
                         ("Invoice Date", f["invoice_date"]),
                         ("Due Date", f["due_date"]),
                         ("Bill To", f["customer_name"])):
        d.text((80, y), f"{label}:", font=font(BOLD, 22), fill="black")
        d.text((360, y), str(value), font=font(REG, 22), fill="black")
        y += 42

    y += 40
    d.rectangle([80, y, W - 80, y + 40], fill="#e8e8e8")
    for x, head in ((95, "Description"), (660, "Qty"), (790, "Unit"), (1000, "Amount")):
        d.text((x, y + 9), head, font=font(BOLD, 21), fill="black")
    y += 48

    for desc, qty, unit, amount in spec["line_items"]:
        d.text((95, y), desc, font=font(REG, 21), fill="black")
        d.text((660, y), str(qty), font=font(REG, 21), fill="black")
        d.text((790, y), f"{unit:,.2f}", font=font(REG, 21), fill="black")
        d.text((1000, y), f"{amount:,.2f}", font=font(REG, 21), fill="black")
        y += 38

    y += 30
    d.line([700, y, W - 80, y], fill="#999", width=2)
    y += 20
    for label, value, bold in (("Subtotal", f["subtotal_usd"], False),
                               ("Tax (9%)", f["tax_usd"], False),
                               ("Total Due", f["total_usd"], True)):
        face = font(BOLD, 24) if bold else font(REG, 22)
        d.text((790, y), label, font=face, fill="black")
        d.text((1000, y), f"${value:,.2f}", font=face, fill="black")
        y += 40

    d.text((80, H - 140), "Payment due within 30 days. Late payments accrue 1.5% monthly.",
           font=font(REG, 19), fill="#555")
    return img


def draw_paystub(spec: dict) -> Image.Image:
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f = spec["fields"]

    d.text((80, 70), f["employer_name"], font=font(BOLD, 38), fill="black")
    d.text((80, 125), "Statement of Earnings", font=font(REG, 26), fill="#333")

    y = 210
    for label, value in (("Employee Name", f["employee_name"]),
                         ("Employee ID", f["employee_id"]),
                         ("Social Security Number", f["ssn"]),
                         ("Pay Period Ending", f["pay_period_end"])):
        d.text((80, y), f"{label}:", font=font(BOLD, 22), fill="black")
        d.text((460, y), str(value), font=font(MONO, 22), fill="black")
        y += 44

    y += 50
    d.text((80, y), "Earnings", font=font(BOLD, 26), fill="black")
    y += 45
    d.text((95, y), "Gross Pay", font=font(REG, 22), fill="black")
    d.text((900, y), f"${f['gross_pay_usd']:,.2f}", font=font(MONO, 22), fill="black")

    y += 70
    d.text((80, y), "Deductions", font=font(BOLD, 26), fill="black")
    y += 45
    for label, amount in spec["deductions"]:
        d.text((95, y), label, font=font(REG, 22), fill="black")
        d.text((900, y), f"-${amount:,.2f}", font=font(MONO, 22), fill="black")
        y += 38

    y += 30
    d.line([80, y, W - 80, y], fill="#333", width=2)
    y += 22
    d.text((80, y), "Net Pay", font=font(BOLD, 28), fill="black")
    d.text((880, y), f"${f['net_pay_usd']:,.2f}", font=font(BOLD, 28), fill="black")

    d.text((80, H - 140), "This document is synthetic. All names and identifiers are invented.",
           font=font(REG, 19), fill="#777")
    return img


def draw_letter(spec: dict) -> Image.Image:
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f = spec["fields"]

    d.text((80, 70), f["clinic_name"], font=font(BOLD, 34), fill="black")
    d.text((80, 118), "41 Fenwick Road, Dorchester", font=font(REG, 20), fill="#444")
    d.text((80, 180), f["letter_date"], font=font(REG, 22), fill="black")

    # Recipient block. Added after the first run: the answer key wanted
    # "Marcus Bell" but the body only said "Dear Mr Bell", so the full name was
    # nowhere on the page and Textract was marked wrong for being right.
    d.text((80, 230), f["recipient_name"], font=font(REG, 22), fill="black")
    d.text((80, 262), "8 Brackley Close", font=font(REG, 22), fill="black")
    d.text((80, 294), "Dorchester DT1 2QS", font=font(REG, 22), fill="black")

    y = 370
    for line in spec["body"]:
        d.text((80, y), line, font=font(REG, 23), fill="black")
        y += 38

    d.text((80, H - 140), "This document is synthetic. All names and identifiers are invented.",
           font=font(REG, 19), fill="#777")
    return img


DRAW = {"invoice": draw_invoice, "paystub": draw_paystub, "letter": draw_letter}


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    truth = {}

    for name, spec in SPECS.items():
        image = DRAW[name](spec)
        path = DOCS / f"{name}.png"
        image.save(path, "PNG", optimize=True)

        truth[name] = {
            "file": path.name,
            "fields": spec["fields"],
            "pii_expected": spec["pii_expected"],
        }
        if "note" in spec:
            truth[name]["note"] = spec["note"]

        print(f"  {path.name:14} {path.stat().st_size // 1024:4} KB  "
              f"{len(spec['fields'])} fields to extract")

    (DOCS / "ground_truth.json").write_text(json.dumps(truth, indent=2) + "\n")
    print(f"\nground truth for {len(truth)} documents -> docs/ground_truth.json")


if __name__ == "__main__":
    main()
