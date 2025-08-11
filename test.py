from playwright.sync_api import sync_playwright
import csv

def scrape_griet_result(roll_number):
    url = "https://share.google/gRCrPbNPt35EwEUJW"  # main page

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # Go to the main results page
        page.goto(url)

        # Fill Hall Ticket No
        page.fill('input[name="rollno"]', roll_number)

        # Click 'Get Result' and wait for new tab
        with context.expect_page() as new_page_info:
            page.click('input[name="submit"]')
        result_page = new_page_info.value

        # Wait for table in new tab
        result_page.wait_for_selector("table.collapse")

        # Extract rows
        rows = result_page.locator("table.collapse tr").all()[1:]
        results = []
        for row in rows:
            cells = [cell.inner_text().strip() for cell in row.locator("td").all()]
            results.append(cells)

        browser.close()
        return results


if __name__ == "__main__":
    roll_number = "24241A05J9"  # Example: "22WH1A0501"
    result_data = scrape_griet_result(roll_number)

    # Save to CSV
    with open("griet_result.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["S.No", "Subject Code", "Subject Name", "Grade Point", "Grade", "Credits", "Result"])
        writer.writerows(result_data)

    print("✅ Results saved to griet_result.csv")
