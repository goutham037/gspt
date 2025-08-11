"""
Merged scraper + Flask app for Gokaraju student portal.
Contains:
 - Playwright-based scrapers for: timetable, faculty allocation, academic calendar,
   attendance, library books, bio-data & education.
 - Flask HTTP endpoints that accept JSON {"username":..., "password":...}
   and return the scraped data. Saves outputs under ./output/*.json and CSVs where appropriate.

Usage:
  python merged_gokaraju_scraper_app.py

Notes:
 - Playwright must be installed and browsers installed (``playwright install``).
 - This file intentionally keeps login credentials in request bodies (POST). Do not log or store them insecurely.
"""

import asyncio
import json
import csv
from pathlib import Path
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from playwright.async_api import async_playwright

# ----------------- Configuration -----------------
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

LOGIN_URL      = "https://www.webprosindia.com/Gokaraju/StudentMaster.aspx"
ATTENDANCE_URL = "https://www.webprosindia.com/Gokaraju/Academics/StudentAttendance.aspx?scrid=3&showtype=SA"
LIBRARY_URL    = "https://www.webprosindia.com/gokaraju/Library/studentsbooks.aspx?scrid=14"
PROFILE_URL    = "https://www.webprosindia.com/Gokaraju/Academics/StudentProfile.aspx?scrid=17"
TIMETABLE_URL  = "https://www.webprosindia.com/gokaraju/Academics/TimeTableReport.aspx?scrid=18"
ACADEMIC_CALENDAR_URL = "https://www.webprosindia.com/gokaraju/Academics/AcademicCalenderReport.aspx?scrid=1"

# Toggle headless here (True for server). Set to False for debugging.
HEADLESS = True

# ----------------- Playwright helpers -----------------
async def login_and_get_page(playwright, username: str, password: str):
    """Launch browser, open a new page, perform login and return (browser, page).
    Caller is responsible for closing the browser.
    """
    browser = await playwright.chromium.launch(headless=HEADLESS)
    page = await browser.new_page()
    await page.goto(LOGIN_URL, timeout=60000)
    await page.fill("#txtId2", username)
    await page.fill("#txtPwd2", password)
    await page.click("#imgBtn2")
    # short wait so the portal finishes login redirect
    await page.wait_for_timeout(2000)
    return browser, page

# ----------------- Scrapers (async) -----------------
async def extract_timetable_and_faculty(page):
    """Extract timetable and faculty allocation from #tblReport tables on the TimeTableReport page."""
    tables = await page.query_selector_all("#tblReport table")
    timetable = []
    faculty = []

    for table in tables:
        header_cells = await table.query_selector_all("tr:first-child td, tr:first-child th")
        headers = [ (await cell.inner_text()).strip() for cell in header_cells ]

        # Timetable detection
        if any(h.lower().startswith("day") or "period" in h.lower() for h in headers):
            rows = await table.query_selector_all("tr")
            std_headers = ["Day","Period 1","Period 2","Period 3","Break","Period 4","Period 5","Period 6","Period 7"]
            for row in rows[1:]:
                cells = await row.query_selector_all("td")
                values = [ (await cell.inner_text()).strip().replace("\xa0", "") for cell in cells ]
                if len(values) != len(std_headers):
                    continue
                timetable.append(dict(zip(std_headers, values)))

        # Faculty allocation detection
        if any("subject code" in h.lower() or "faculty" in h.lower() for h in headers):
            rows = await table.query_selector_all("tr")
            for row in rows[1:]:
                cells = await row.query_selector_all("td")
                values = [ (await cell.inner_text()).strip().replace("\xa0", "") for cell in cells ]
                if len(values) >= 3:
                    faculty.append({
                        "Subject Code": values[0],
                        "Subject":       values[1] if len(values)>1 else "",
                        "Faculty Name":  values[2] if len(values)>2 else "",
                        "Initials":      values[3] if len(values)>3 else ""
                    })

    # Save files
    if timetable:
        (OUTPUT_DIR / "timetable.json").write_text(json.dumps(timetable, indent=2, ensure_ascii=False), encoding="utf-8")
    if faculty:
        (OUTPUT_DIR / "faculty_allocation.json").write_text(json.dumps(faculty, indent=2, ensure_ascii=False), encoding="utf-8")

    return timetable, faculty

async def extract_academic_calendar(page):
    container = await page.query_selector("#ctl00_CapPlaceHolder_divstudent table.reportTable")
    calendar = []
    if not container:
        return calendar

    rows = await container.query_selector_all("tr")
    if not rows:
        return calendar

    header_cells = await rows[0].query_selector_all("td, th")
    headers = [ (await cell.inner_text()).strip() for cell in header_cells ]

    for row in rows[1:]:
        cells = await row.query_selector_all("td")
        values = [ (await cell.inner_text()).strip() for cell in cells ]
        if len(values) == len(headers):
            calendar.append(dict(zip(headers, values)))

    if calendar:
        (OUTPUT_DIR / "academic_calendar.json").write_text(json.dumps(calendar, indent=2, ensure_ascii=False), encoding="utf-8")
    return calendar

async def fetch_attendance(username: str, password: str):
    async with async_playwright() as pw:
        browser, page = await login_and_get_page(pw, username, password)
        await page.goto(ATTENDANCE_URL, timeout=60000)
        await page.wait_for_load_state("networkidle")

        # try click the 'Till Now' radio and show button if present
        try:
            await page.check('input[id="radTillNow"]')
            await page.click('input[id="btnShow"]')
        except Exception:
            pass
        await page.wait_for_timeout(1500)

        rows = await page.query_selector_all('table.cellBorder tr')
        headers = ["Sl.No.", "Subject", "Held", "Attend", "%"]
        data = []
        for row in rows:
            cols = await row.query_selector_all("td")
            if len(cols) == 5:
                vals = [ (await c.inner_text()).strip() for c in cols ]
                if vals[0].isdigit():
                    data.append(dict(zip(headers, vals)))

        await browser.close()

        # save
        with open(OUTPUT_DIR / "attendance_data.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        with open(OUTPUT_DIR / "attendance_data.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(data)

        return data

async def fetch_library_books(username: str, password: str):
    async with async_playwright() as pw:
        browser, page = await login_and_get_page(pw, username, password)
        await page.goto(LIBRARY_URL, timeout=60000)
        await page.wait_for_timeout(1500)

        rows = await page.query_selector_all("table#tblbooks tr")
        headers = ["Sl.No", "Acc.No", "Title", "Author", "Issue Date", "Due Date", "Fine Days", "Fine Amount"]
        data = []
        for row in rows:
            cols = await row.query_selector_all("td")
            if len(cols) == 8:
                vals = [ (await c.inner_text()).strip() for c in cols ]
                if vals[0].isdigit():
                    data.append(dict(zip(headers, vals)))

        await browser.close()

        with open(OUTPUT_DIR / "library_books.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        with open(OUTPUT_DIR / "library_books.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(data)

        return data

async def fetch_bio_data(username: str, password: str):
    async with async_playwright() as pw:
        browser, page = await login_and_get_page(pw, username, password)
        await page.goto(PROFILE_URL, timeout=60000)
        await page.wait_for_timeout(1000)

        # expand BIO-DATA tab if needed
        try:
            await page.click("text=BIO-DATA")
            await page.wait_for_selector("#divProfile_BioData", state="visible", timeout=3000)
        except Exception:
            # sometimes BIO-DATA content is already present
            pass

        tables = page.locator("#divProfile_BioData > table")
        bio = {}
        # parse personal bio (table 0)
        rows0 = tables.nth(0).locator("tr")
        for i in range(await rows0.count()):
            cells = rows0.nth(i).locator("td")
            cnt = await cells.count()
            if cnt == 2:
                k = (await cells.nth(0).inner_text()).strip().rstrip(":")
                v = (await cells.nth(1).inner_text()).strip()
                if k and v:
                    bio[k] = v
            elif cnt >= 6:
                k1 = (await cells.nth(0).inner_text()).strip().rstrip(":")
                v1 = (await cells.nth(2).inner_text()).strip()
                k2 = (await cells.nth(3).inner_text()).strip().rstrip(":")
                v2 = (await cells.nth(5).inner_text()).strip()
                if k1 and v1: bio[k1] = v1
                if k2 and v2: bio[k2] = v2

        # parse education details (nested table in table 1)
        inner = tables.nth(1).locator("table")
        rows1 = inner.locator("tr")
        edu = {
            "School (SSC)": {"Board":"", "HallTicketNo":"", "YearOfPass":"", "Institute":"", "MaxMarks":"", "Obtained":"", "GradeLetter":"", "GradePoints":""},
            "Intermediate": {"Board":"", "HallTicketNo":"", "YearOfPass":"", "Institute":"", "MaxMarks":"", "Obtained":"", "GradeLetter":"", "GradePoints":""},
            "Diploma":      {"Board":"", "HallTicketNo":"", "YearOfPass":"", "Institute":"", "MaxMarks":"", "Obtained":"", "GradeLetter":"", "GradePoints":""},
        }

        for i in range(1, await rows1.count()):
            cells = rows1.nth(i).locator("td")
            if await cells.count() < 7:
                continue
            qual = (await cells.nth(0).inner_text()).strip().lower()
            if not qual:
                continue

            key = None
            if qual in ("ssc", "s.s.c"):        key = "School (SSC)"
            elif qual in ("inter", "intermediate"): key = "Intermediate"
            elif qual == "diploma":             key = "Diploma"
            if not key:
                continue

            B  = (await cells.nth(1).inner_text()).strip()
            H  = (await cells.nth(2).inner_text()).strip()
            Y  = (await cells.nth(3).inner_text()).strip()
            I  = (await cells.nth(4).inner_text()).strip()
            Mx = (await cells.nth(5).inner_text()).strip()
            Ob = (await cells.nth(6).inner_text()).strip()
            GL = (await cells.nth(7).inner_text()).strip() if await cells.count()>7 else ""
            GP = (await cells.nth(8).inner_text()).strip() if await cells.count()>8 else ""

            if any([B,H,Y,I,Mx,Ob,GL,GP]):
                edu[key] = {
                    "Board":        B,
                    "HallTicketNo": H,
                    "YearOfPass":   Y,
                    "Institute":    I,
                    "MaxMarks":     Mx,
                    "Obtained":     Ob,
                    "GradeLetter":  GL,
                    "GradePoints":  GP
                }

        await browser.close()

        result = {"BioData": bio, "Education": edu}
        with open(OUTPUT_DIR / "bio_data.json", "w", encoding="utf-8") as jf:
            json.dump(result, jf, indent=4, ensure_ascii=False)

        # also emit a CSV summary
        with open(OUTPUT_DIR / "bio_data.csv", "w", newline="", encoding="utf-8") as cf:
            writer = csv.writer(cf)
            writer.writerow(["Section","Subsection","Field","Value"])
            for f, v in bio.items():
                writer.writerow(["BioData","",f,v])
            for sec, details in edu.items():
                for fld, val in details.items():
                    writer.writerow(["Education", sec, fld, val])

        return result

async def fetch_timetable_and_calendar(username: str, password: str):
    async with async_playwright() as pw:
        browser, page = await login_and_get_page(pw, username, password)
        # TimeTable page
        await page.goto(TIMETABLE_URL, timeout=60000)
        await page.wait_for_selector("#tblReport", timeout=8000)
        timetable, faculty = await extract_timetable_and_faculty(page)

        # Academic Calendar page
        await page.goto(ACADEMIC_CALENDAR_URL, timeout=60000)
        await page.wait_for_timeout(1000)
        calendar = await extract_academic_calendar(page)

        await browser.close()
        return {
            "timetable": timetable,
            "faculty_allocation": faculty,
            "academic_calendar": calendar,
        }
# ----------------- Single-roll result scraper & Flask route -----------------
async def scrape_griet_result(roll_number: str):
    """
    Scrape GRIET result for a single roll number.
    Returns: {"headers": [...], "rows": [[...], ...]}
    """
    url = "https://share.google/gRCrPbNPt35EwEUJW"  # main page that opens getresult.php in a new tab

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(url, timeout=60000)
        await page.fill('input[name="rollno"]', roll_number)

        # click submit and wait for the new tab that contains results
        async with context.expect_page() as new_page_info:
            await page.click('input[name="submit"]')
        result_page = await new_page_info.value

        # wait for the table (try two selectors)
        try:
            await result_page.wait_for_selector("table.collapse", timeout=10000)
            table = await result_page.query_selector("table.collapse")
        except Exception:
            await result_page.wait_for_selector("table[border='1']", timeout=10000)
            table = await result_page.query_selector("table[border='1']")

        if not table:
            await browser.close()
            return {"headers": [], "rows": []}

        # extract headers
        header_cells = await table.query_selector_all("tr:first-child td, tr:first-child th")
        headers = [ (await c.inner_text()).strip() for c in header_cells ]

        # extract body rows
        rows_sel = await table.query_selector_all("tr")
        rows = []
        for r in rows_sel[1:]:  # skip header
            cols = await r.query_selector_all("td")
            if not cols:
                continue
            vals = [ (await c.inner_text()).strip() for c in cols ]
            rows.append(vals)

        await browser.close()
        return {"headers": headers, "rows": rows}

 
# ----------------- Flask app & HTTP endpoints -----------------
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})  # dev only

@app.route('/')
def index():
    return "Gokaraju scraper running. POST credentials to endpoints to fetch data."


@app.route('/get-result', methods=['POST'])
def http_get_result():
    """
    POST JSON body: { "rollno": "22WH1A0501" }
    Returns JSON: { "rollno": "...", "result": { "headers": [...], "rows": [...] } }
    """
    try:
        payload = request.get_json(force=True)
        rn = payload.get("rollno")
        if not rn:
            return jsonify({"error": "Provide 'rollno' in JSON body."}), 400

        # run the async scraper synchronously from Flask
        result = asyncio.run(scrape_griet_result(str(rn).strip()))

        # save JSON
        out_json = OUTPUT_DIR / f"result_{rn}.json"
        out_json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

        # save CSV (if rows exist)
        csv_path = OUTPUT_DIR / f"result_{rn}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as cf:
            writer = csv.writer(cf)
            if result.get("headers"):
                writer.writerow(result["headers"])
            else:
                writer.writerow(["S.No", "Subject Code", "Subject Name", "Grade Point", "Grade", "Credits", "Result"])
            for row in result.get("rows", []):
                writer.writerow(row)

        return jsonify({"rollno": rn, "result": result}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/get-timetable-and-calendar', methods=['POST'])
def http_get_timetable_and_calendar():
    try:
        creds = request.get_json()
        username = creds.get('username')
        password = creds.get('password')
        data = asyncio.run(fetch_timetable_and_calendar(username, password))
        return jsonify({"data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get-attendance', methods=['POST'])
def http_get_attendance():
    try:
        creds = request.get_json()
        username = creds.get('username')
        password = creds.get('password')
        data = asyncio.run(fetch_attendance(username, password))
        return jsonify({"data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get-library-books', methods=['POST'])
def http_get_library_books():
    try:
        creds = request.get_json()
        username = creds.get('username')
        password = creds.get('password')
        data = asyncio.run(fetch_library_books(username, password))
        return jsonify({"data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get-bio-data', methods=['POST'])
def http_get_bio_data():
    try:
        creds = request.get_json()
        username = creds.get('username')
        password = creds.get('password')
        data = asyncio.run(fetch_bio_data(username, password))
        return jsonify({"data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Convenience combined endpoint
@app.route('/get-all', methods=['POST'])
def http_get_all():
    try:
        creds = request.get_json()
        username = creds.get('username')
        password = creds.get('password')

        # call each function sequentially to avoid parallel playwright sessions
        tt_cal = asyncio.run(fetch_timetable_and_calendar(username, password))
        attendance = asyncio.run(fetch_attendance(username, password))
        library = asyncio.run(fetch_library_books(username, password))
        bio = asyncio.run(fetch_bio_data(username, password))

        combined = {
            **tt_cal,
            "attendance": attendance,
            "library_books": library,
            "bio_data": bio
        }
        return jsonify({"data": combined})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

import os

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

