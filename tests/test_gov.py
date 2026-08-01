import pytest
from suu.scrape.gov import GovDocsScraper

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
