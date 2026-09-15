import csv
import html
import re
from datetime import date, timedelta, datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "AM-Traffic-Safety-Bid-Finder/3.1"
}

SOURCES = {
    "Humboldt County":
        "https://www.humboldtgov.org/Bids.aspx?CatID=showStatus&Status=open&showAllBids=&txtSort=Title",
    "Mendocino County":
        "https://www.mendocinocounty.gov/departments/general-services/central-services/open-rfp-quotes-bids",
    "Caltrans District 1":
        "https://ccop.dot.ca.gov/onestopshop/1",
}

TRAFFIC_TERMS = [
    "traffic", "work zone", "lane closure", "flagging", "roadway",
    "road work", "road construction", "paving", "pavement", "asphalt",
    "resurfacing", "culvert", "drainage", "guardrail", "bridge",
    "sidewalk", "excavation", "grading", "utility", "trenching",
    "highway", "street", "erosion", "striping", "delineation",
    "sign", "barricade", "cone", "warning light", "arrow board",
    "channelizer", "delineator"
]

EQUIPMENT = {
    "Cones": ["cone"],
    "Barricades": ["barricade"],
    "Temporary Signs": ["traffic sign", "temporary sign", "signage", "sign structures"],
    "Warning Lights": ["warning light", "flashing light", "beacon"],
    "Arrow Board": ["arrow board", "arrow panel", "message board"],
    "Delineators": ["delineator", "channelizer", "vertical panel"],
    "Stop/Slow Paddles": ["flagging", "flagger", "stop/slow"],
}

# --- NUEVO: de dónde sacamos nombres de COMPAÑÍAS (no solo proyectos) -------
# Caltrans publica cada semana quién ganó cada contrato de servicio en una
# página por semana. Filtramos por Humboldt/Mendocino y sacamos el nombre
# del que ganó (primero en la lista = oferta más baja).
AWARD_COUNTIES = ["humboldt county", "mendocino county"]


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def get_soup(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def equipment_needed(text):
    low = text.lower()
    found = []
    for label, terms in EQUIPMENT.items():
        if any(term in low for term in terms):
            found.append(label)
    return ", ".join(found) if found else "Review traffic safety needs"


def project_type(text):
    low = text.lower()
    if any(x in low for x in ["bridge", "culvert"]):
        return "Bridge / culvert"
    if any(x in low for x in ["paving", "pavement", "asphalt", "resurfacing"]):
        return "Road / paving"
    if any(x in low for x in ["excavation", "grading", "utility", "trenching"]):
        return "Excavation / utilities"
    if any(x in low for x in ["drainage", "erosion"]):
        return "Drainage / erosion"
    if any(x in low for x in ["sidewalk", "bike lane", "complete streets"]):
        return "Complete streets"
    if any(x in low for x in ["traffic", "lane closure", "flagging"]):
        return "Traffic control"
    return "Infrastructure"


def score(text, status=""):
    low = text.lower()
    matches = sum(1 for term in TRAFFIC_TERMS if term in low)
    equipment_matches = sum(
        1 for terms in EQUIPMENT.values()
        if any(term in low for term in terms)
    )
    total = matches * 8 + equipment_matches * 8
    if status in {"Open", "Advertised", "Upcoming Projects"}:
        total += 12
    if status == "AWARDED":
        total += 15
    return min(100, total)


def priority(value):
    if value >= 70:
        return "HIGH"
    if value >= 40:
        return "MEDIUM"
    return "LOW"


def find_id(text):
    patterns = [
        r"\bRFP\s*(?:No\.?|Number)?\s*[:#]?\s*([A-Z0-9][A-Z0-9._/-]{2,})",
        r"\b(?:Bid|Project|Solicitation|Contract)\s*(?:No\.?|Number|ID)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{2,})",
        r"\b(01-[A-Z0-9]{4,})\b",
        r"\b(01[A-Z]\d{4})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1)
    return ""


def find_deadline(text):
    patterns = [
        r"(?:Closes?|Closing|Bid Due Date|Bid Date|Due Date|Deadline)\s*:?\s*"
        r"([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}(?:\s+[0-9]{1,2}:[0-9]{2}\s*(?:AM|PM))?)",
        r"\b(2026-\d{2}-\d{2})\b",
        r"\b([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1)
    return ""


def infer_action(item):
    if item["status"] == "AWARDED":
        return "Identify winning contractor and offer local equipment support."
    if item["priority"] == "HIGH":
        return "Review today and contact project/contractor."
    if item["priority"] == "MEDIUM":
        return "Review and identify likely contractor."
    return "Keep on watch list."


def add_row(rows, source, title, context, url, status="", bid_due="", project_id="", county="", company=""):
    title = clean(title)
    context = clean(context)
    combined = clean(title + " " + context)

    if len(title) < 8:
        return

    if not county:
        low = combined.lower()
        if "humboldt" in low:
            county = "Humboldt"
        elif "mendocino" in low:
            county = "Mendocino"
        else:
            county = "Humboldt / Mendocino"

    if not status:
        status = "REVIEW SOURCE"

    if not bid_due:
        bid_due = find_deadline(combined)

    if not project_id:
        project_id = find_id(combined)

    value = score(combined, status)

    # Avoid generic page/navigation links.
    if value < 24:
        return

    row = {
        "priority": priority(value),
        "source": source,
        "title": title,
        "status": status,
        "bid_due": bid_due,
        "project_id": project_id,
        "county": county,
        "project_type": project_type(combined),
        "equipment": equipment_needed(combined),
        "company": company,  # NUEVO — vacío para proyectos abiertos, lleno para adjudicados
        "description": context[:1000],
        "score": value,
        "action": infer_action({
            "status": status,
            "priority": priority(value)
        }),
        "url": url,
    }
    rows.append(row)


def parse_humboldt(soup, page_url):
    rows = []
    for tr in soup.find_all("tr"):
        text = clean(tr.get_text(" ", strip=True))
        if not text:
            continue

        links = tr.find_all("a", href=True)
        for link in links:
            title = clean(link.get_text(" ", strip=True))
            if len(title) < 12:
                continue
            if any(x in title.lower() for x in ["read on", "print", "view all"]):
                continue

            href = urljoin(page_url, link["href"])
            status_match = re.search(r"\b(Open|Closed|Awarded|Cancelled)\b", text, re.I)
            status = status_match.group(1).title() if status_match else ""

            bid_due = find_deadline(text)
            project_id = find_id(text)

            add_row(
                rows, "Humboldt County", title, text, href,
                status, bid_due, project_id, "Humboldt"
            )
            break
    return rows


def parse_mendocino(soup, page_url):
    rows = []
    for tr in soup.find_all("tr"):
        text = clean(tr.get_text(" ", strip=True))
        if not text:
            continue

        cells = [clean(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
        if len(cells) < 3:
            continue

        title = ""
        for cell in cells:
            if len(cell) > 15 and not re.fullmatch(r"[0-9./: -]+", cell):
                if cell.lower() not in {"open", "closed", "awarded"}:
                    title = cell
                    break
        if not title:
            continue

        project_id = cells[0] if re.match(r"^[A-Z0-9][A-Z0-9 -]{2,}$", cells[0], re.I) else ""

        status = ""
        for cell in reversed(cells):
            if cell.lower() in {"open", "closed", "awarded"}:
                status = cell.title()
                break

        href = page_url
        link = tr.find("a", href=True)
        if link:
            href = urljoin(page_url, link["href"])

        add_row(
            rows, "Mendocino County", title, text, href,
            status, find_deadline(text), project_id, "Mendocino"
        )
    return rows


def parse_caltrans(soup, page_url):
    rows = []
    text = soup.get_text("\n", strip=True)
    text = text.replace("\xa0", " ")
    blocks = re.split(r"(?=Project ID:\s*)", text, flags=re.I)

    for block in blocks:
        block = clean(block)
        if not block.lower().startswith("project id:"):
            continue

        match_id = re.search(r"Project ID:\s*([A-Z0-9-]+)", block, re.I)
        if not match_id:
            continue
        project_id = match_id.group(1)

        due_match = re.search(
            r"Bid Due Date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2}"
            r"(?:\s+[0-9:AMPDT\s-]+)?)",
            block, re.I
        )
        bid_due = due_match.group(1).strip() if due_match else ""

        status_match = re.search(
            r"Status:\s*(.*?)(?=\s+(?:Humboldt|Mendocino|Del Norte|"
            r"Lake|Sonoma|License|A,|C-|$))",
            block, re.I
        )
        status = status_match.group(1).strip() if status_match else ""

        county_match = re.search(
            r"\b(Humboldt|Mendocino)\b", block, re.I
        )
        county = county_match.group(1).title() if county_match else ""

        title = ""
        title_patterns = [
            r"\b(?:Humboldt|Mendocino)\b.*?\d{4}-\d{2}-\d{2}\s+(.+?)\s+In\s+(?:Humboldt|Mendocino)\b",
            r"\b(?:Humboldt|Mendocino)\b.*?\d{4}-\d{2}-\d{2}\s+(.+?)\s+In\s+",
        ]
        for pattern in title_patterns:
            m = re.search(pattern, block, re.I)
            if m:
                title = clean(m.group(1))
                break
        if not title:
            m = re.search(
                r"\b(Construct|Replace|Install|Earthwork|"
                r"SB Minor B|Cold plane|Bridge|Roadway|"
                r"Trenchless|Realign|Rehabilitate).{10,180}?(?=\s+In\s+)",
                block, re.I
            )
            if m:
                title = clean(m.group(0))
        if not title:
            title = f"Caltrans Project {project_id}"

        add_row(
            rows, "Caltrans District 1", title, block, page_url,
            status, bid_due, project_id, county
        )
    return rows


# ---------------------------------------------------------------------------
# NUEVO: ganadores reales (nombres de COMPAÑÍA) — Caltrans Distrito 1
# ---------------------------------------------------------------------------

def _recent_mondays(n_weeks=10):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return [(monday - timedelta(weeks=i)).isoformat() for i in range(n_weeks)]


def parse_caltrans_awards(n_weeks=10):
    """
    Caltrans publica cada semana los resultados de licitaciones de contratos
    de servicio en una página por semana. Sacamos los renglones que
    mencionen Humboldt o Mendocino, junto con el nombre real de la empresa
    que ganó (la primera en la lista = oferta más baja) y el monto.
    """
    rows = []
    for monday in _recent_mondays(n_weeks):
        url = f"https://dot.ca.gov/programs/procurement-and-contracts/bid-results/bid-week-{monday}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
        except requests.RequestException:
            continue
        if resp.status_code != 200:
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        for tr in soup.select("table tr"):
            cells = tr.find_all("td")
            if len(cells) < 3:
                continue
            contract_link = cells[1].find("a")
            if not contract_link:
                continue
            contract_no = clean(contract_link.get_text())
            contract_url = urljoin(url, contract_link.get("href", ""))

            detail_cell = cells[2]
            lines = [clean(l) for l in detail_cell.get_text("\n").split("\n") if clean(l)]
            if not lines:
                continue
            description = lines[0]

            if not any(county in description.lower() for county in AWARD_COUNTIES):
                continue
            if "no bids" in " ".join(lines).lower():
                continue

            bidder_lines = lines[1:]
            if not bidder_lines:
                continue
            winner_line = bidder_lines[0]
            match = re.match(r"^(.*?)\s+SB:\s*[YN]\s+(\$[\d,.]+)", winner_line)
            if match:
                company, amount = match.group(1).strip(), match.group(2).strip()
            else:
                company, amount = winner_line, ""

            county = "Humboldt" if "humboldt" in description.lower() else "Mendocino"

            add_row(
                rows,
                source="Caltrans District 1 — AWARDED",
                title=description,
                context=f"Awarded to {company} ({amount})" if amount else f"Awarded to {company}",
                url=contract_url,
                status="AWARDED",
                bid_due="",
                project_id=contract_no,
                county=county,
                company=company,
            )
    return rows


def dedupe(rows):
    unique = {}
    for row in rows:
        key = (row["source"], row["project_id"], row["title"])
        if key not in unique:
            unique[key] = row
        else:
            if row["score"] > unique[key]["score"]:
                unique[key] = row
    return list(unique.values())


def write_csv(rows, output):
    fields = [
        "priority", "source", "title", "status", "bid_due",
        "project_id", "county", "project_type", "equipment", "company",
        "description", "score", "action", "url"
    ]
    path = output / "am_traffic_safety_opportunities.csv"
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_html(rows, output):
    parts = [
        "<html><head><meta charset='utf-8'>"
        "<style>"
        "body{font-family:Arial,sans-serif;margin:20px}"
        "table{border-collapse:collapse;width:100%;font-size:13px}"
        "th,td{border:1px solid #ccc;padding:7px;vertical-align:top}"
        "th{background:#eee}"
        "</style></head><body>",
        "<h1>AM TRAFFIC SAFETY — DAILY OPPORTUNITY REPORT</h1>",
        f"<p><b>Generated:</b> "
        f"{datetime.now().astimezone():%Y-%m-%d %I:%M %p %Z}</p>",
        f"<p><b>Relevant opportunities found:</b> {len(rows)}</p>",
        "<table><tr>"
        "<th>Priority</th><th>Source</th><th>Project</th>"
        "<th>Status</th><th>Deadline</th><th>Project ID</th>"
        "<th>County</th><th>Project Type</th><th>Potential Equipment</th>"
        "<th>Winning Company</th>"
        "<th>Score</th><th>Action</th><th>Link</th></tr>"
    ]
    for item in rows[:75]:
        parts.append(
            "<tr>"
            f"<td><b>{html.escape(item['priority'])}</b></td>"
            f"<td>{html.escape(item['source'])}</td>"
            f"<td>{html.escape(item['title'])}</td>"
            f"<td>{html.escape(item['status'])}</td>"
            f"<td>{html.escape(item['bid_due'])}</td>"
            f"<td>{html.escape(item['project_id'])}</td>"
            f"<td>{html.escape(item['county'])}</td>"
            f"<td>{html.escape(item['project_type'])}</td>"
            f"<td>{html.escape(item['equipment'])}</td>"
            f"<td><b>{html.escape(item.get('company', ''))}</b></td>"
            f"<td>{item['score']}</td>"
            f"<td>{html.escape(item['action'])}</td>"
            f"<td><a href='{html.escape(item['url'], quote=True)}'>Open source</a></td>"
            "</tr>"
        )
    parts.append(
        "</table>"
        "<h2>Recommended next action</h2>"
        "<p>Review HIGH and MEDIUM priority opportunities first. "
        "For AWARDED projects, contact the winning company listed directly — "
        "they already need local traffic safety equipment support.</p>"
        "</body></html>"
    )
    (output / "am_traffic_safety_report.html").write_text(
        "".join(parts), encoding="utf-8"
    )


def main():
    output = Path("output")
    output.mkdir(exist_ok=True)
    (output / "errors.txt").write_text("", encoding="utf-8")

    rows = []
    for source, url in SOURCES.items():
        try:
            soup = get_soup(url)
            if source == "Humboldt County":
                parsed = parse_humboldt(soup, url)
            elif source == "Mendocino County":
                parsed = parse_mendocino(soup, url)
            else:
                parsed = parse_caltrans(soup, url)
            rows.extend(parsed)
        except Exception as error:
            with (output / "errors.txt").open("a", encoding="utf-8") as file:
                file.write(f"{source}: {type(error).__name__}: {error}\n")

    # NUEVO: agregar ganadores reales (con nombre de compañía) de Caltrans
    try:
        rows.extend(parse_caltrans_awards())
    except Exception as error:
        with (output / "errors.txt").open("a", encoding="utf-8") as file:
            file.write(f"Caltrans Awards: {type(error).__name__}: {error}\n")

    rows = dedupe(rows)
    rows.sort(
        key=lambda x: (
            {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(x["priority"], 0),
            x["score"]
        ),
        reverse=True
    )

    write_csv(rows, output)
    write_html(rows, output)
    print(f"Found {len(rows)} relevant opportunities.")


if __name__ == "__main__":
    main()
