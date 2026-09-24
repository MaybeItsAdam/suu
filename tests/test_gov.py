import pytest
from suu.scrape.gov import GovDocsScraper, _needs_ocr, parse_amendments_html

def test_version_from_filename():
    # Test original formats
    assert GovDocsScraper._version_from_filename("http://example.com/ucl_code_of_practice_5th_february_2014.pdf") == "5th February 2014"
    assert GovDocsScraper._version_from_filename("https://studentsunionucl.org/sites/default/files/u3832/documents/ucl_code_of_practice_5th_february_2014.pdf") == "5th February 2014"
    
    # Test new format with month/year, spaces, hyphens, and url-encoding
    assert GovDocsScraper._version_from_filename("https://studentsunionucl.org/sites/default/files/2025-07/Club%20and%20Society%20Regulations%20-%20July%202025%20.pdf") == "July 2025"
    assert GovDocsScraper._version_from_filename("https://example.com/Club%20and%20Society%20Regulations%20-%20July%202025.pdf") == "July 2025"
    assert GovDocsScraper._version_from_filename("https://example.com/Club_and_Society_Regulations_July_2025.pdf") == "July 2025"
    assert GovDocsScraper._version_from_filename("https://example.com/Club_and_Society_Regulations-July-2025.pdf") == "July 2025"

    # Test month abbreviation and various separations
    assert GovDocsScraper._version_from_filename("https://example.com/regs_oct_2024.pdf") == "Oct 2024"
    assert GovDocsScraper._version_from_filename("https://example.com/regs_12th_dec_2023.pdf") == "12th Dec 2023"

    # Non-matching cases
    assert GovDocsScraper._version_from_filename("https://example.com/no_date_here.pdf") is None
    assert GovDocsScraper._version_from_filename("https://example.com/Regulations_2025.pdf") is None  # 'Regulations' is not a month


def test_parse_amendments_groups_dates_and_multiple_pdf_assets():
    html = """
      <h5>AGD 2501 Number of Committee Positions per person</h5>
      <p>Passed 06/10/2025</p>
      <p>In effect from March 2026</p>
      <p><a href="/one.pdf">Proposal</a><a href="/tracked.pdf">Tracked changes</a></p>
      <h3>AGD 2405 Bye-Laws Tidy Up</h3>
      <p>Passed: 02/06/2025</p>
      <p><a href="/two.pdf">Download</a><a href="/notes.txt">Text</a></p>
    """
    amendments = parse_amendments_html(html, "https://studentsunionucl.org/amendments")

    assert [item.reference for item in amendments] == ["AGD2501", "AGD2405"]
    assert amendments[0].passed_at == "2025-10-06"
    assert amendments[0].effective_label == "March 2026"
    assert [asset.slug for asset in amendments[0].assets] == ["agd2501-1", "agd2501-2"]
    assert amendments[1].assets[0].label == "Bye-Laws Tidy Up"
    assert len(amendments[1].assets) == 1


def test_sparse_image_pdf_text_triggers_ocr_without_reprocessing_real_text():
    assert _needs_ocr(["Contents", "5.1.1 .", "» »"] * 8) is True
    assert _needs_ocr(["A complete governing document clause. " * 100]) is False
