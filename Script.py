import argparse
import json
import re
from pathlib import Path
from tkinter import Button, END, Label, Listbox, SINGLE, Tk, filedialog

from playwright.sync_api import sync_playwright

USER_DATA_DIR = Path("playwright_user_data")
DASHBOARD_URL = "https://app.retain.io/tutors/dashboard"

def select_json_file():
    root = Tk()
    root.withdraw()  # hide empty Tk window
    root.attributes("-topmost", True)

    file_path = filedialog.askopenfilename(
        title="Select session_answers.json",
        filetypes=[("JSON files", "*.json")]
    )
    root.destroy()

    if not file_path:
        raise FileNotFoundError("No file selected.")

    return file_path


def resolve_json_path() -> Path:
    parser = argparse.ArgumentParser(
        description="Populate session note fields from a JSON export."
    )
    parser.add_argument(
        "json_path",
        nargs="?",
        help="Path to session_answers.json (optional if using the file picker).",
    )
    args = parser.parse_args()

    if args.json_path:
        return Path(args.json_path).expanduser().resolve()

    try:
        return Path(select_json_file())
    except KeyboardInterrupt as exc:
        raise SystemExit("File picker cancelled. Provide a JSON path to skip the dialog.") from exc

def select_pending_report(reports):
    if not reports:
        raise RuntimeError("No pending reports found on the dashboard.")

    root = Tk()
    root.title("Select report to file")
    root.attributes("-topmost", True)

    Label(
        root,
        text="Select a pending report to file:",
        padx=12,
        pady=8
    ).pack()

    listbox = Listbox(root, selectmode=SINGLE, width=90)
    for report in reports:
        listbox.insert(
            END,
            f"{report['course']} | {report['time']} | {report['attendee']}"
        )
    listbox.pack(padx=12, pady=8)
    listbox.selection_set(0)

    selection = {"index": None}

    def on_select():
        if listbox.curselection():
            selection["index"] = listbox.curselection()[0]
            root.quit()

    Button(root, text="Continue", command=on_select, padx=10, pady=6).pack(pady=8)
    root.mainloop()
    root.destroy()

    if selection["index"] is None:
        raise RuntimeError("No report selected.")

    return reports[selection["index"]]

def collect_pending_reports(page):
    page.wait_for_selector("div.card")
    cards = page.query_selector_all("div.card")
    pending = []

    for card in cards:
        time_header = card.query_selector(".card-header .row .col .card-header-title")
        time_text = time_header.inner_text().split("\n")[0].strip() if time_header else "Unknown time"
        time_text = re.sub(r"\s+", " ", time_text)

        class_header = card.query_selector(".card-header .row .col:nth-child(2) .card-header-title")
        class_text = class_header.inner_text().strip() if class_header else ""
        course_match = re.search(r"\(([^)]+)\)", class_text)
        course = course_match.group(1) if course_match else class_text

        rows = card.query_selector_all("tbody tr")
        for row in rows:
            status = row.query_selector("span.badge")
            status_text = status.inner_text().strip() if status else ""
            if status_text.lower() != "pending":
                continue

            attendee_cell = row.query_selector("td")
            attendee_name = attendee_cell.inner_text().strip() if attendee_cell else "Unknown attendee"
            link = row.query_selector("a[href*='session_notes']")
            href = link.get_attribute("href") if link else None
            if not href:
                continue

            pending.append(
                {
                    "time": time_text,
                    "course": course,
                    "attendee": attendee_name,
                    "href": href,
                }
            )

    return pending

def fill_form(json_path: Path) -> None:
    # Load JSON
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(USER_DATA_DIR),
            headless=False
        )

        # Attach to already-open form tab
        page = context.pages[0] if context.pages else context.new_page()

        page.goto(DASHBOARD_URL, wait_until="domcontentloaded")

        if "users/sign_in" in page.url:
            page.wait_for_selector("input[type='email']")
            page.fill("input[type='email']", "thomas-hart@uiowa.edu")
            page.fill("input[type='password']", "Th@Rt@28")
            page.locator("button[type='submit'], input[type='submit']").first.click()
            page.wait_for_url(DASHBOARD_URL, wait_until="domcontentloaded")

        pending_reports = collect_pending_reports(page)
        selection = select_pending_report(pending_reports)

        report_link = selection["href"]
        report_locator = page.locator(f"a[href='{report_link}']").first
        report_locator.scroll_into_view_if_needed()
        report_locator.click()

        # Wait until form is ready
        page.wait_for_selector("#session_note_question_3")

        # --- REQUIRED FIXED FIELDS ---

        # Q1: Always checked
        page.check("#session_note_question_1")

        # Q2: Always YES
        page.check("#session_note_question_2_yes")

        # --- JSON-DRIVEN FIELDS ---
        page.fill("#session_note_question_3", data["question_3"])
        page.fill("#session_note_question_4", data["question_4"])
        page.fill("#session_note_question_5", data["question_5"])
        page.fill("#session_note_notes", data["notes"])

        print("✔ Session note fields populated. Review and submit manually.")

        # Keep browser open
        context.wait_for_event("close")

if __name__ == "__main__":
    JSON_PATH = resolve_json_path()
    if not JSON_PATH.exists():
        raise FileNotFoundError(f"JSON file not found: {JSON_PATH}")
    fill_form(JSON_PATH)
