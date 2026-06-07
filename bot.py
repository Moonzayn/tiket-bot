import json
import os
import re
import time
from urllib.parse import urlparse, parse_qs
from patchright.sync_api import Playwright, sync_playwright


def load_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def get_url_param(url, param):
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get(param)
    return values[0] if values else None


def adjust_quantity(page, target_qty):
    if target_qty <= 1:
        return
    for _ in range(target_qty - 1):
        plus_btn = page.get_by_role("button", name="Tambah", exact=False)
        if plus_btn.is_visible() and plus_btn.is_enabled():
            plus_btn.click()
            time.sleep(0.3)


def select_package(page, config):
    url = config["url"]
    pkg_cfg = config.get("packages", {})
    detail = pkg_cfg.get("detail", 1)
    qty = pkg_cfg.get("qty", 1)

    base = url.rstrip("/").split("?")[0].split("#")[0]
    pkgs_url = f"{base}/packages#pricetierDetail-{detail}"
    page.goto(pkgs_url)
    page.wait_for_timeout(10000)

    # cek Cloudflare
    if page.locator("text=challenge").count() > 0 or page.locator("text=Turnstile").count() > 0:
        print("[!] Cloudflare challenge terdeteksi — tunggu penyelesaian manual 30dtk")
        page.wait_for_timeout(30000)



    adjust_quantity(page, qty)

    pesan_btn = page.get_by_role("button", name=re.compile("Pesan|Book", re.I))
    if pesan_btn.first.is_visible(timeout=5000) and pesan_btn.first.is_enabled():
        pesan_btn.first.click()
        print(f"[INFO] Berhasil Book pricetierDetail-{detail}")
        return True

    group = page.get_by_test_id(f"package-group-{detail - 1}")
    group.scroll_into_view_if_needed(timeout=5000)
    pilih_btn = group.get_by_role("button", name=re.compile("Pilih|Select", re.I))
    if pilih_btn.first.is_visible(timeout=3000) and pilih_btn.first.is_enabled():
        pilih_btn.first.click()
        page.wait_for_timeout(1500)
        adjust_quantity(page, qty)
        if pesan_btn.first.is_visible(timeout=3000) and pesan_btn.first.is_enabled():
            pesan_btn.first.click()
            print(f"[INFO] Berhasil Book pricetierDetail-{detail}")
            return True

    print(f"[ERROR] Tombol Pesan tidak muncul")
    return False


def select_nationality(page, country="Indonesia"):
    field = page.get_by_text(re.compile(r"Negara tempat tinggal", re.I)).first
    field.scroll_into_view_if_needed()
    field.click(force=True)
    page.wait_for_timeout(2000)

    if "compCountrySelection" not in page.url:
        page.locator("#countryregion-of-residence").first.click(force=True)
        page.wait_for_timeout(2000)

    page.wait_for_function(
        "() => window.location.hash.includes('compCountrySelection')",
        timeout=10000
    )

    option = page.get_by_text(re.compile(rf"^{country}\s*\(\+62\)", re.I)).first
    option.scroll_into_view_if_needed()
    option.click(force=True)

    page.wait_for_function(
        "() => !window.location.hash.includes('compCountrySelection')",
        timeout=10000
    )
    print(f"[INFO] Nationality selected: {country}. URL: {page.url}")


TITLE_MAP = {
    "Mr.": re.compile(r"Mr\.?|Tuan", re.I),
    "Mrs.": re.compile(r"Mrs\.?|Nyonya", re.I),
    "Ms.": re.compile(r"Ms\.?|Nona", re.I),
}


def fill_contact_details(page, config):
    title_pat = TITLE_MAP.get(config["title"], re.compile(config["title"], re.I))
    page.get_by_role("radio", name=title_pat).first.click(force=True)
    page.wait_for_timeout(300)

    page.locator('[id="full-name"]').first.fill(config["fullName"])
    page.locator("#mobile-number").fill(config["mobileNumber"])
    page.locator("#email-address").fill(config["email"])

    page.locator("#countryregion-of-residence").click()
    page.wait_for_timeout(1000)
    page.keyboard.type("Indo")
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")
    page.wait_for_timeout(500)

    page.get_by_text(re.compile(r"Sama dengan pemesan", re.I)).first.click()
    page.wait_for_timeout(500)
    page.locator("#identity-card-number").fill(config["identityCardNumber"])


def setup_session(context, config):
    mode = config.get("session_mode", "direct")
    if mode == "paste":
        session_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session.json")

        print("Paste session JSON (paste semua cookies dari Chrome DevTools, lalu Enter 2x):")
        print("  Cara: DevTools > Application > Cookies > Copy cookies as JSON")
        lines = []
        while True:
            line = input()
            if not line:
                break
            lines.append(line)
        raw = "\n".join(lines).strip()

        if raw:
            try:
                cookies = json.loads(raw)
                with open(session_path, "w", encoding="utf-8") as f:
                    json.dump(cookies, f, indent=2)
                context.add_cookies(cookies)
                print(f"[OK] Session tersimpan & loaded ({len(cookies)} cookies)")
                return
            except Exception as e:
                print(f"[ERROR] Gagal parse JSON: {e}")

        if os.path.exists(session_path):
            with open(session_path, encoding="utf-8") as f:
                try:
                    cookies = json.load(f)
                    context.add_cookies(cookies)
                    print("[OK] Session loaded dari session.json")
                except Exception as e:
                    print(f"[ERROR] Gagal load session.json: {e}")
        else:
            print("[!] Tidak ada session. Lanjut tanpa session.")
    else:
        print("[OK] Pakai Chrome session langsung.")


def run(playwright: Playwright, config: dict) -> None:
    browser = playwright.chromium.launch(
        headless=config["headless"],
        channel="chrome",
    )
    context = browser.new_context()
    setup_session(context, config)
    page = context.new_page()

    if not select_package(page, config):
        context.close()
        browser.close()
        return

    print("[INFO] Menunggu halaman order...")
    page.wait_for_timeout(5000)
    print(f"[DEBUG] URL saat ini: {page.url}")

    def check_errors(msg="[DETECTED]"):
        t = page.evaluate("document.body.innerText")
        errs = re.findall(r'(?:Kuota[^\n]{0,100}|[^\n]{0,20}(?:gagal|error|tidak bisa|habis|limit|batas)[^\n]{0,80})', t, re.I)
        for e in errs:
            e = e.strip()
            if len(e) > 10:
                print(f"{msg} {e}")

    check_errors("[ORDER PAGE]")

    title_pat = TITLE_MAP.get(config["title"], re.compile(config["title"], re.I))
    try:
        radio = page.get_by_role("radio", name=title_pat)
        if radio.first.is_visible(timeout=5000):
            radio.first.click(force=True)
            print(f"[INFO] Klik radio: {config['title']}")
    except Exception as e:
        print(f"[DEBUG] Gagal klik radio: {e}")

    try:
        select_nationality(page, "Indonesia")
    except Exception as e:
        print(f"[DEBUG] Gagal pilih nationality: {e}")

    page.wait_for_timeout(1000)

    try:
        page.locator('#nama-lengkap').nth(0).fill(config["fullName"], timeout=5000)
        page.locator('#nomor-ponsel').nth(0).fill(config["mobileNumber"], timeout=5000)
        email_input = page.locator('#alamat-email')
        if email_input.is_enabled():
            email_input.fill(config["email"], timeout=5000)
        else:
            print("[DEBUG] Email sudah terisi dari session")
        print("[INFO] Isi contact details")
    except Exception as e:
        print(f"[DEBUG] Gagal isi contact: {e}")

    try:
        visitor_title = page.locator("label:has(input[name='salutation-0'])").filter(has_text=title_pat).first
        if visitor_title.count() > 0:
            visitor_title.click(force=True)
            print(f"[INFO] Klik title visitor: {config['title']}")

        page.locator('#nama-lengkap').nth(1).fill(config["fullName"], timeout=5000)
        page.locator('#nomor-ponsel').nth(1).fill(config["mobileNumber"], timeout=5000)
        page.locator('#email').fill(config["email"], timeout=5000)
        page.locator('#nomor-ktp').fill(config["identityCardNumber"], timeout=5000)
        print("[INFO] Isi visitor details")
    except Exception as e:
        print(f"[DEBUG] Gagal isi visitor: {e}")

    btn = page.get_by_role("button", name=re.compile("Lanjutkan pembayaran|Continue", re.I))
    btn.scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    btn.click()
    print("[INFO] Klik Lanjutkan pembayaran")
    page.wait_for_timeout(5000)

    check_errors("[AFTER CLICK]")

    page.wait_for_timeout(1000)
    base_payment_url = page.url
    if "pagePreventInitialized=true" not in base_payment_url:
        sep = "&" if "?" in base_payment_url else "?"
        base_payment_url = f"{base_payment_url}{sep}pagePreventInitialized=true"
    print(f"\n=== PAYMENT URL ===")
    print(base_payment_url)
    print("===================\n")
    print("[INFO] Selesai — browser akan ditutup dalam 5dtk.")
    page.wait_for_timeout(5000)
    context.close()
    browser.close()


if __name__ == "__main__":
    config = load_config()
    with sync_playwright() as playwright:
        run(playwright, config)
