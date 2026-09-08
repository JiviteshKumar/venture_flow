"""OCR on decks whose pages are pictures.

The defect these guard against was a hard refusal: an image-only PDF -- a valid,
human-legible file whose every page is a slide image with no text layer --
returned 422 "VentureFlow has no OCR". Six well-known decks in this project's
own corpus are exactly that shape (Dropbox, LinkedIn, YouTube, Facebook, WeWork,
BuzzFeed), each extracting 0 characters across 20-40 pages.

The fixture is built rather than committed. `_image_only_pdf` writes a text PDF
with known sentences and then rasterizes it, which produces a file with a text
layer of *exactly zero characters* -- the real failure mode, reproduced from
scratch on every run, with ground truth we wrote ourselves. A committed binary
fixture would test the same thing while hiding what is in it.

These tests run the real ONNX engine. Stubbing it would leave the interesting
question -- does OCR actually read a slide -- untested, which is the only
question that matters here.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

import api
import ocr_extractor

# The sentences the fixture deck contains. Chosen to exercise what a pitch deck
# actually carries: a currency figure, a percentage, a multiple, and a plain
# claim -- the shapes the claim extractor and the financial parser look for.
SLIDE_TEXT = [
    [
        "Northwind Robotics",
        "Warehouse automation for mid-market distributors",
    ],
    [
        "Revenue reached 2.4 million dollars in the last year",
        "Gross margin improved to 71 percent",
        "We operate in 14 distribution centres across three states",
    ],
]

pytestmark = pytest.mark.skipif(
    not ocr_extractor.is_available(),
    reason="OCR engine not installed; see requirements.txt",
)


def _text_pdf() -> bytes:
    """A normal PDF, with a text layer, containing SLIDE_TEXT."""
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=landscape(letter))
    for lines in SLIDE_TEXT:
        # 28pt is roughly pitch-deck body size once rendered at 144dpi. Smaller
        # type would test the engine's limits rather than the wiring.
        pdf.setFont("Helvetica", 28)
        y = 420
        for line in lines:
            pdf.drawString(60, y, line)
            y -= 60
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _image_only_pdf() -> bytes:
    """The same deck with its text layer destroyed, by rendering each page to a
    bitmap and rebuilding a PDF out of the images."""
    import pypdfium2

    document = pypdfium2.PdfDocument(_text_pdf())
    images = [
        document[i].render(scale=1.6).to_pil().convert("RGB")
        for i in range(len(document))
    ]
    document.close()

    buffer = io.BytesIO()
    images[0].save(
        buffer, format="PDF", save_all=True, append_images=images[1:], resolution=115
    )
    return buffer.getvalue()


@pytest.fixture(scope="module")
def image_only_deck() -> bytes:
    return _image_only_pdf()


@pytest.fixture(autouse=True)
def enable_ocr():
    """Undo the suite-wide OCR switch for this file only (see conftest)."""
    original = ocr_extractor.ENABLED
    ocr_extractor.ENABLED = True
    yield
    ocr_extractor.ENABLED = original


def test_the_fixture_really_has_no_text_layer(image_only_deck):
    """If this fails, every other test in the file is proving nothing.

    A rasterizer that quietly preserved the text layer would let the upload
    tests below pass without OCR running at all.
    """
    import pdfplumber

    with pdfplumber.open(io.BytesIO(image_only_deck)) as pdf:
        extracted = "".join((page.extract_text() or "") for page in pdf.pages)
    assert extracted.strip() == "", (
        f"The fixture was supposed to be image-only but yielded "
        f"{len(extracted.strip())} characters of text layer."
    )

    from document_extractor import extract_document

    document = extract_document("deck.pdf", image_only_deck)
    assert document["text_layer"] == "none"
    assert document["extracted_chars"] == 0


def test_ocr_reads_the_slides(image_only_deck):
    result = ocr_extractor.ocr_pdf(image_only_deck)

    assert result["available"] is True, result.get("reason")
    assert result["pages_read"] == len(SLIDE_TEXT)
    assert result["pages_total"] == len(SLIDE_TEXT)
    assert result["truncated"] is False

    lowered = result["text"].lower()
    assert "northwind robotics" in lowered
    assert "warehouse automation" in lowered
    # The numbers matter more than the prose: a deck's figures are what an
    # investor acts on, and they are what OCR is most likely to get wrong.
    assert "2.4 million" in lowered
    assert "71 percent" in lowered
    assert "14 distribution" in lowered


def test_ocr_output_is_labelled_as_recognised_not_read(image_only_deck):
    """OCR text must never be presentable as text the document contained.

    A recognised revenue figure and a read one are not equally trustworthy, and
    the difference has to survive as far as the reader.
    """
    result = ocr_extractor.ocr_pdf(image_only_deck)

    assert "ocr" in result["provenance"].lower() or "recognis" in result["provenance"].lower()
    assert "RapidOCR" in result["engine"]
    for page in range(1, len(SLIDE_TEXT) + 1):
        assert f"--- Slide {page} (recognised from the page image) ---" in result["text"]


def test_a_partial_read_says_it_is_partial(image_only_deck):
    """A budget too small to finish must truncate visibly, not silently."""
    result = ocr_extractor.ocr_pdf(image_only_deck, time_budget_s=0.0)

    # Either it read nothing (and said so), or it read some and flagged it.
    if result["available"]:
        assert result["truncated"] is True
        assert result["truncation_note"]
        assert str(result["pages_total"]) in result["truncation_note"]
    else:
        assert result["reason"]
        assert result["text"] == ""


def test_disabled_ocr_reports_a_reason_rather_than_pretending(image_only_deck):
    ocr_extractor.ENABLED = False
    result = ocr_extractor.ocr_pdf(image_only_deck)

    assert result["available"] is False
    assert result["text"] == ""
    assert "disabled" in result["reason"].lower()


def test_unavailable_never_carries_text():
    """The invariant the whole module rests on: `available: False` means there
    is nothing here, so a caller can never analyse a failed read as content."""
    result = ocr_extractor.ocr_pdf(b"not a pdf at all")

    assert result["available"] is False
    assert result.get("text", "") == ""
    assert result["pages_read"] == 0
    assert result["reason"]


class TestShouldSupplement:
    """When OCR is worth running on a deck that already extracted some text.

    "Has a text layer" and "has been read" are different facts. Coinbase's real
    2012 deck is 12 pages and 635 characters because its content lives in
    images; OCR takes it to 2,304 characters and surfaces the traction figures.
    """

    def test_no_text_layer_always_runs(self):
        assert ocr_extractor.should_supplement("none", 0, 20) is True

    def test_sparse_text_layer_always_runs(self):
        assert ocr_extractor.should_supplement("sparse", 80, 20) is True

    def test_thin_but_present_text_layer_runs(self):
        # The Coinbase shape: 635 characters across 12 pages.
        assert ocr_extractor.should_supplement("present", 635, 12) is True

    def test_a_normal_deck_does_not_pay_for_ocr(self):
        # The Uber shape: 5,390 characters across 25 pages.
        assert ocr_extractor.should_supplement("present", 5390, 25) is False

    def test_a_one_slide_teaser_is_not_dragged_through_ocr(self):
        """The threshold is per page, so a short deck that is dense for its
        length is left alone."""
        assert ocr_extractor.should_supplement("present", 400, 1) is False


class TestUploadEndpoint:
    """The user-facing half: the 422 is gone, and what replaces it is honest."""

    def test_an_image_only_deck_is_now_analysed(self, image_only_deck):
        client = TestClient(api.app)
        response = client.post(
            "/upload-pdf",
            files={"file": ("northwind.pdf", image_only_deck, "application/pdf")},
            data={"company_name": "Northwind Robotics"},
        )

        assert response.status_code == 200, response.text
        body = response.json()

        assert body["text_source"] == "ocr"
        assert body["ocr"]["pages_read"] == len(SLIDE_TEXT)
        assert body["ocr"]["engine"]
        assert body["ocr"]["provenance"]
        assert "northwind" in body["extracted_text"].lower()

        # Coverage must be measured against the OCR'd slides. Measuring it
        # against the (empty) text layer would report 0% understood for a deck
        # that was in fact read correctly -- the metric contradicting the
        # extraction it exists to describe.
        assert len([s for s in body["deck_slides"] if s.strip()]) == len(SLIDE_TEXT)

    def test_with_ocr_off_the_refusal_says_what_was_missing(self, image_only_deck):
        """The honest-degradation path. Without OCR this deck is unreadable, and
        the error has to name that cause rather than implying a broken file."""
        ocr_extractor.ENABLED = False
        client = TestClient(api.app)
        response = client.post(
            "/upload-pdf",
            files={"file": ("northwind.pdf", image_only_deck, "application/pdf")},
            data={"company_name": "Northwind Robotics"},
        )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "ocr" in detail.lower()
        assert "text-based PDF" in detail
