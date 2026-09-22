BASE_URL = "https://www.elections.ca/WPAPPS/WPF/EN/CC"
HOME_URL = "https://www.elections.ca/WPAPPS/WPF/EN/Home"
RATE_LIMIT_SOURCE = "elections_financial_returns"
# Unpublished rate limit -- kept conservative, matching this project's other
# legacy-portal modules (see cmhc/constants.py) that also have no published
# figure to cite.
RATE_LIMIT_PER_SECOND = 3.0
RATE_LIMIT_CAPACITY = 3.0
CACHE_TTL_SECONDS = 3600

# Confirmed live 2026-09-21: this is the internal numeric code for the
# "Candidates" political entity on the portal's own Home/RefreshEventList
# and Home/RefreshReportType endpoints (selectedEntityCode=1). Every other
# political entity type (leadership/nomination contestants, registered
# associations/parties) uses a genuinely different search-form shape --
# see the module docstring -- and is out of scope here.
ENTITY_CODE_CANDIDATES = "1"

# The "Select Time Period" dropdown's option values on Home/Index, each a
# distinct Canada Elections Act regime -- confirmed live 2026-09-21. These
# are fixed legislative windows, not portal data, so they are hardcoded
# rather than discovered per call.
ACT_PERIODS: dict[str, str] = {
    "after_2019": "C76",
    "2015_2019": "C23",
    "2007_2014": "C2",
    "2004_2006": "C24",
}

# "Select Financial Return Type" for Candidates -- confirmed live 2026-09-21
# via Home/RefreshReportType?selectedEntityCode=1 across every ACT_PERIODS
# value. Only "campaign_returns" carries the 13-part detailed statement this
# module's get_financial_return_part covers; the other two are single
# summary documents and were not mapped in this pass.
REPORT_TYPES: dict[str, str] = {
    "campaign_returns": "8",
    "statement_of_surplus": "6",
    "statement_of_unpaid_claims_or_loans": "7",
}

# "Return Status" radio group on CC/Index -- confirmed live 2026-09-21.
# Confirmed live that "amended" actually serves Elections Canada's own
# reviewed data (EXPORT_HEADER.RETURN_STATUS reads
# "Data_as_reviewed_by_Elections_Canada") even for a candidate with no
# filed amendment, not strictly "has this candidate amended their return."
RETURN_STATUS: dict[str, str] = {
    "submitted": "1",
    "amended": "2",
}

# "Return Part" dropdown under reportOption=2 (Complete Financial Return) --
# confirmed live 2026-09-21 against a real candidate's full report. Label
# text matches the portal's own dropdown text verbatim.
PART_LABELS: dict[str, str] = {
    "1": "Part 1 - Declaration",
    "2A": "Part 2a - Statement of Contributions Received",
    "2B": "Part 2b - Statement of Operating Loans",
    "2C": "Part 2c - Statement of Contributions Returned to Contributors or Remitted to the Chief Electoral Officer",
    "2D": "Part 2d - Statement of Transfers Received",
    "2E": "Part 2e - Statement of Cash Inflows Other than Contributions, Loans and Transfers",
    "2F": "Part 2f - Summary of Contributions, Loans, Transfers and Other Cash Inflows",
    "3A": "Part 3a - Statement of Electoral Campaign Expenses and Other Outflows",
    "3B": "Part 3b - Statement of Litigation and Candidate's Personal Expenses not Funded by the Campaign",
    "3C": "Part 3c - Summary of Electoral Campaign Expenses and Other Outflows",
    "4": "Part 4 - Statement of Non-Monetary Transfers Sent to Affiliated Political Entities",
    "5": "Part 5 - Statement of Unpaid Loans and Claims, from Parts 2b and 3a",
    "6": "Part 6 - Campaign Bank Reconciliation",
}

# "Complete Financial Return" -- confirmed live 2026-09-21 as the ReportOption
# radio value that exposes the 13-part PART_LABELS breakdown above (the
# other three ReportOption values -- Financial Return Summary, Summary by
# Electoral District, Corrections and Revisions -- are single-document
# views, not per-part, and were not mapped in this pass).
REPORT_OPTION_COMPLETE = "2"

DOWNLOAD_FORMAT_JSON = "3"

# Confirmed live 2026-09-21: an unfiltered search (every filter left at
# "-1"/"All") returned 1,926 candidate rows in one unpaginated response for
# the 45th general election alone. Capped here for the same
# agent-facing-compactness reason SEARCH_ROWS_MAX/DATASTORE_ROWS_MAX are
# capped elsewhere in this project (see the CRA row in ROADMAP.md) -- a
# caller should narrow with last_name/party_id/province_id rather than
# pull the full roster through this tool.
CANDIDATE_SEARCH_MAX = 300
