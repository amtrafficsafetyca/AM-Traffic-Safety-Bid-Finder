import csv
import html
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "AM-Traffic-Safety-Bid-Finder/2.0"
}

SOURCES = {
    "Humboldt County":
        "https://www.humboldtgov.org/Bids.aspx",
    "Mendocino County":
        "https://www.mendocinocounty.gov/departments/general-services/central-services/open-rfp-quotes-bids",
    "Caltrans District 1":
        "https://ccop.dot.ca.gov/onestopshop/1",
}

TRAFFIC_KEYWORDS = [
    "traffic control", "traffic safety", "work zone", "lane closure",
    "flagging", "roadway", "road work", "road construction", "paving",
    "pavement", "asphalt", "resurfacing", "culvert", "drainage",
    "guardrail", "bridge", "sidewalk", "excavation", "grading",
    "utility", "trenching", "highway", "street", "erosion control",
    "striping", "delineation",
]

EQUIPMENT_KEYWORDS = {
    "Cones": ["cone", "traffic cone"],
    "Barricades": ["barricade", "type i", "type iii"],
    "Temporary Signs": ["temporary sign", "road sign", "traffic sign", "signage"],
    "Warning Lights": ["warning light", "flashing light", "beacon"],
    "Arrow Board": ["arrow board", "arrow panel", "message board"],
    "Delineators": ["delineator", "channelizer", "vertical panel"],
    "Stop/Slow Paddles": ["stop/slow", "stop slow", "flagger"],
}

PROJECT_KEYWORDS = {
    "Road / paving": [
        "roadway", "road work", "road construction", "paving",
        "pavement", "asphalt", "resurfacing", "highway", "street"
    ],
    "Bridge / culvert": ["bridge", "culvert"],
    "Excavation / utilities": ["excavation", "grading", "utility", "trenching"],
    "Drainage / erosion": ["drainage", "erosion control"],
    "Traffic control": ["traffic control", "work zone", "lane closure", "flagging"],
}

DATE_PATTERNS = [
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    r"\b\d{1,2}-\d{1,2}-\d{2,4}\b",
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b",
]

ID_PATTERNS = [
    r"\b(?:bid|project|solicitation|contract|rfp|rfq|IFB)\s*"
    r"(?:no\.?|number|id)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{2,})",
    r"\b(01-[A-Z0-9]{4,})\b",
    r"\b([0-9]{5,})\b",
]

STATUS_PATTERNS = [
    ("AWARDED", [
        "awarded", "award notice", "notice of award",
        "contract award", "bid results", "award results"
    ]),
    ("CLOSED", [
        "closed", "bid closed", "solicitation closed", "past due"
    ]),
    ("OPEN BID", [
        "open bid", "bid due", "bid deadline", "due date",
        "submission deadline", "bids due", "proposal due"
    ]),
    ("UPCOMING", ["upcoming", "anticipated", "coming soon"]),
]


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def find_dates(text):
    found = []
    for pattern in DATE_PATTERNS:
        found.extend(re.findall(pattern, text, flags=re.I))
    result = []
    for item in found:
        if item not in result:
            result.append(item)
    return result


def choose_due_date(text):
    dates = find_dates(text)
    if not dates:
        return ""
    deadline_words = r"(?:due|deadline|close|closing|bid|proposal|submit|opening)"
    for match in re.finditer(deadline_words, text, flags=re.I):
        nearby = text[match.start():match.start() + 220]
        nearby_dates = find_dates(nearby)
        if nearby_dates:
            return nearby_dates[0]
    return dates[0]


def find_project_id(text):
    for pattern in ID_PATTERNS:
        match = re.search(pattern, text, flags=re.I)
        if match:
            value = match.group(1)
            if value.lower() not in {"number", "no", "id"}:
                return value
    return ""


def infer_status(text):
    lower = text.lower()
    for status, phrases in STATUS_PATTERNS:
        if any(phrase in lower for phrase in phrases):
            return status
    return "REVIEW SOURCE"


def equipment_needed(text):
    lower = text.lower()
    found = []
    for equipment, phrases in EQUIPMENT_KEYWORDS.items():
        if any(phrase in lower for phrase in phrases):
            found.append(equipment)
    if not found:
        found.append("Traffic safety equipment — review project")
    return ", ".join(found)


def project_types(text):
    lower = text.lower()
    found = []
    for label, phrases in PROJECT_KEYWORDS.items():
        if any(phrase in lower for phrase in phrases):
            found.append(label)
    return ", ".join(found[:3])


def score(text):
    lower = text.lower()
    traffic_matches = sum(word in lower for word in TRAFFIC_KEYWORDS)
    equipment_matches = sum(
        any(phrase in lower for phrase in phrases)
        for phrases in EQUIPMENT_KEYWORDS.values()
    )
    status_bonus = 8 if any(
        phrase in lower
        for phrase in ["bid due", "bid deadline", "bids due", "open bid"]
    ) else 0
    total = traffic_matches * 8 + equipment_matches * 10 + status_bonus
    return min(100, total)


def priority_for(total_score, status):
    if status == "AWARDED":
        return "HIGH"
    if total_score >= 70:
        return "HIGH"
    if total_score >= 40:
        return "MEDIUM"
    return "LOW"


def source_page_rows(source, url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    seen = set()
    rows = []

    for link in soup.find_all("a", href=True):
        title = clean(link.get_text(" ", strip=True))
        if len(title) < 8:
            continue

        if link.parent:
            context = clean(link.parent.get_text(" ", strip=True))
        else:
            context = title

        container = link.find_parent(["tr", "li", "div"])
        if container:
            context = clean(container.get_text(" ", strip=True))

        context = context[:1600]
        combined = clean(title + " " + context)
        total_score = score(combined)

        if total_score < 24:
            continue

        full_url = urljoin(url, link["href"])
        key = (source, title, full_url)
        if key in seen:
            continue
        seen.add(key)

        if "Humboldt" in source:
            county = "Humboldt"
        elif "Mendocino" in source:
            county = "Mendocino"
        else:
            county = "Humboldt / Mendocino"

        status = infer_status(combined)
        rows.append({
            "priority": priority_for(total_score, status),
            "source": source,
            "title": title,
            "status": status,
            "bid_due": choose_due_date(combined),
            "project_id": find_project_id(combined),
            "county": county,
            "project_type": project_types(combined),
            "equipment": equipment_needed(combined),
            "description": context,
            "score": total_score,
            "url": full_url,
        })

    return rows


def write_csv(rows, output):
    fields = [
        "priority", "source", "title", "status", "bid_due",
        "project_id", "county", "project_type", "equipment",
        "description", "score", "url"
    ]
    csv_file = output / "am_traffic_safety_opportunities.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return csv_file


def write_html(rows, output):
    html_parts = [
        "<html><head><meta charset='utf-8'>",
        "<style>",
        "body{font-family:Arial,sans-serif;margin:20px}",
        "table{border-collapse:collapse;width:100%;font-size:14px}",
        "th,td{border:1px solid #ccc;padding:7px;vertical-align:top}",
        "th{background:#eee}",
        "</style></head><body>",
        "<h1>AM TRAFFIC SAFETY — DAILY OPPORTUNITY REPORT</h1>",
        f"<p><b>Generated:</b> "
        f"{datetime.now().astimezone():%Y-%m-%d %I:%M %p %Z}</p>",
        f"<p><b>Relevant opportunities found:</b> {len(rows)}</p>",
        "<table><tr>",
        "<th>Priority</th><th>Source</th><th>Project</th>",
        "<th>Status</th><th>Deadline</th><th>Project ID</th>",
        "<th>County</th><th>Potential Equipment</th>",
        "<th>Score</th><th>Link</th></tr>",
    ]

    for item in rows[:50]:
        html_parts.append(
            "<tr>"
            f"<td><b>{html.escape(item['priority'])}</b></td>"
            f"<td>{html.escape(item['source'])}</td>"
            f"<td>{html.escape(item['title'])}</td>"
            f"<td>{html.escape(item['status'])}</td>"
            f"<td>{html.escape(item['bid_due'])}</td>"
            f"<td>{html.escape(item['project_id'])}</td>"
            f"<td>{html.escape(item['county'])}</td>"
            f"<td>{html.escape(item['equipment'])}</td>"
            f"<td>{item['score']}</td>"
            f"<td><a href='{html.escape(item['url'], quote=True)}'>"
            "Open source</a></td></tr>"
        )

    html_parts.append(
        "</table>"
        "<h2>Recommended next action</h2>"
        "<p>Review HIGH and MEDIUM priority opportunities first. "
        "For projects marked AWARDED, identify the winning contractor "
        "and contact them about local traffic safety equipment support.</p>"
        "</body></html>"
    )

    html_file = output / "am_traffic_safety_report.html"
    html_file.write_text("".join(html_parts), encoding="utf-8")
    return html_file


def main():
    output = Path("output")
    output.mkdir(exist_ok=True)

    rows = []
    errors_file = output / "errors.txt"
    errors_file.write_text("", encoding="utf-8")

    for source, url in SOURCES.items():
        try:
            rows.extend(source_page_rows(source, url))
        except Exception as error:
            with errors_file.open("a", encoding="utf-8") as file:
                file.write(f"{source}: {error}\n")

    unique = {}
    for row in rows:
        key = (row["source"], row["title"], row["url"])
        if key not in unique or row["score"] > unique[key]["score"]:
            unique[key] = row

    rows = list(unique.values())
    rows.sort(
        key=lambda item: (
            {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(item["priority"], 0),
            item["score"],
        ),
        reverse=True,
    )

    write_csv(rows, output)
    write_html(rows, output)

    print(f"Found {len(rows)} relevant opportunities.")


if __name__ == "__main__":
    main()
