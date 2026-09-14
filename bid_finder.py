import csv
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "AM-Traffic-Safety-Bid-Finder/1.0"
}

SOURCES = {
    "Humboldt County":
        "https://www.humboldtgov.org/Bids.aspx",

    "Mendocino County":
        "https://www.mendocinocounty.gov/departments/general-services/central-services/open-rfp-quotes-bids",

    "Caltrans District 1":
        "https://ccop.dot.ca.gov/onestopshop/1",
}

KEYWORDS = [
    "traffic control",
    "traffic safety",
    "roadway",
    "road work",
    "road construction",
    "paving",
    "pavement",
    "asphalt",
    "resurfacing",
    "culvert",
    "drainage",
    "guardrail",
    "bridge",
    "sidewalk",
    "excavation",
    "grading",
    "utility",
    "trenching",
    "highway",
    "street",
    "erosion control",
    "striping",
    "delineation",
    "work zone",
    "lane closure",
    "cone",
    "barricade",
    "sign",
    "warning light",
    "arrow board",
    "channelizer",
    "delineator",
]


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def score(text):
    text = text.lower()
    matches = sum(word in text for word in KEYWORDS)
    return min(100, matches * 12)


def main():
    rows = []

    for source, url in SOURCES.items():

        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            seen = set()

            for link in soup.find_all(
                "a",
                href=True
            ):

                title = clean(
                    link.get_text(
                        " ",
                        strip=True
                    )
                )

                if len(title) < 8:
                    continue

                if link.parent:
                    context = clean(
                        link.parent.get_text(
                            " ",
                            strip=True
                        )
                    )
                else:
                    context = title

                context = context[:1200]

                total_score = score(
                    title + " " + context
                )

                if total_score < 24:
                    continue

                full_url = urljoin(
                    url,
                    link["href"]
                )

                key = (
                    source,
                    title,
                    full_url
                )

                if key in seen:
                    continue

                seen.add(key)

                if "Humboldt" in source:
                    county = "Humboldt"
                elif "Mendocino" in source:
                    county = "Mendocino"
                else:
                    county = "Humboldt/Mendocino"

                if total_score >= 70:
                    priority = "HIGH"
                elif total_score >= 40:
                    priority = "MEDIUM"
                else:
                    priority = "LOW"

                rows.append({
                    "source": source,
                    "title": title,
                    "status": "See source",
                    "bid_due": "",
                    "project_id": "",
                    "county": county,
                    "description": context,
                    "score": total_score,
                    "priority": priority,
                    "url": full_url,
                })

        except Exception as error:

            output = Path("output")
            output.mkdir(
                exist_ok=True
            )

            with open(
                output / "errors.txt",
                "a",
                encoding="utf-8"
            ) as file:

                file.write(
                    f"{source}: {error}\n"
                )

    rows.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    output = Path("output")
    output.mkdir(
        exist_ok=True
    )

    fields = [
        "source",
        "title",
        "status",
        "bid_due",
        "project_id",
        "county",
        "description",
        "score",
        "priority",
        "url",
    ]

    csv_file = (
        output /
        "am_traffic_safety_opportunities.csv"
    )

    with csv_file.open(
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fields
        )

        writer.writeheader()
        writer.writerows(rows)

    html = []

    html.append(
        "<html><body>"
    )

    html.append(
        "<h1>AM TRAFFIC SAFETY — "
        "DAILY OPPORTUNITY REPORT</h1>"
    )

    html.append(
        f"<p>Generated: "
        f"{datetime.now().astimezone():%Y-%m-%d %I:%M %p %Z}"
        f"</p>"
    )

    html.append(
        f"<p>Relevant opportunities found: "
        f"{len(rows)}</p>"
    )

    html.append(
        "<table border='1' "
        "cellpadding='6'>"
        "<tr>"
        "<th>Priority</th>"
        "<th>Source</th>"
        "<th>Project</th>"
        "<th>Score</th>"
        "<th>Link</th>"
        "</tr>"
    )

    for item in rows[:50]:

        html.append(
            "<tr>"
            f"<td>{item['priority']}</td>"
            f"<td>{item['source']}</td>"
            f"<td>{item['title']}</td>"
            f"<td>{item['score']}</td>"
            f"<td><a href='{item['url']}'>"
            "Open source</a></td>"
            "</tr>"
        )

    html.append(
        "</table></body></html>"
    )

    html_file = (
        output /
        "am_traffic_safety_report.html"
    )

    html_file.write_text(
        "".join(html),
        encoding="utf-8"
    )

    print(
        f"Found {len(rows)} "
        "relevant opportunities."
    )


if __name__ == "__main__":
    main()
