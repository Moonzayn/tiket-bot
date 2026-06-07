import re, time, json, sys, os
from patchright.sync_api import sync_playwright


def load_token(path):
    content = open(path, encoding="utf-8").read().strip()
    if content.startswith("["):
        raw = json.loads(content)
        for c in raw:
            if c.get("name") == "session_access_token":
                return c.get("value")
    elif content.startswith("\"") and content.endswith("\""):
        return json.loads(content)
    else:
        return content
    print("[ERROR] session.json tidak mengandung session_access_token")
    return None


def apply_token(context, token_jwt):
    context.add_cookies([{
        "domain": ".tiket.com",
        "httpOnly": True,
        "secure": True,
        "name": "session_access_token",
        "value": token_jwt,
        "path": "/"
    }])
    print("[OK] Session access token loaded (%s...)" % token_jwt[:25])


def adjust_quantity(page, target_qty):
    if target_qty <= 1:
        return
    for _ in range(target_qty - 1):
        plus = page.get_by_role("button", name=re.compile("Tambah|Plus", re.I))
        if plus.first.is_visible() and plus.first.is_enabled():
            plus.first.click()
            time.sleep(0.3)


def select_package(page, config):
    url = config["url"]
    pkg_cfg = config.get("packages", {})
    qty = pkg_cfg.get("qty", 1)
    base = url.rstrip("/").split("?")[0].split("#")[0]

    if "list" in pkg_cfg:
        targets = pkg_cfg["list"]
    elif pkg_cfg.get("auto"):
        targets = list(range(1, 11))
    else:
        start = pkg_cfg.get("detail", 1)
        targets = list(range(start, start + 10))

    def click_pesan():
        pb = page.get_by_role("button", name=re.compile("Pesan|Book", re.I))
        if pb.first.is_visible(timeout=2000) and pb.first.is_enabled():
            pb.first.click()
            return True
        return False

    for detail in targets:
        print(f"[INFO] Coba pricetierDetail-{detail}...")

        # --- Approach A: hash URL ---
        page.goto(f"{base}/packages#pricetierDetail-{detail}", timeout=15000)
        page.wait_for_timeout(5000)

        if page.locator("text=challenge").count() > 0 or page.locator("text=Turnstile").count() > 0:
            print("[!] Cloudflare challenge — tunggu 30dtk")
            page.wait_for_timeout(30000)

        adjust_quantity(page, qty)

        if click_pesan():
            print(f"[INFO] Klik Pesan pricetierDetail-{detail}")
            if _navigate_to_order(page):
                return True

        # --- Approach B: click Pilih ---
        page.goto(f"{base}/packages", timeout=10000)
        page.wait_for_timeout(2000)
        pilih = page.get_by_role("button", name=re.compile("Pilih|Select", re.I)).nth(detail - 1)
        if pilih.count() > 0 and pilih.is_visible(timeout=2000) and pilih.is_enabled():
            pilih.click()
            page.wait_for_timeout(3000)
            adjust_quantity(page, qty)
            if click_pesan():
                print(f"[INFO] Klik Pesan via Pilih pricetierDetail-{detail}")
                if _navigate_to_order(page):
                    return True
            if "order" in page.url.lower():
                print(f"[INFO] Redirect ke order via Pilih pricetierDetail-{detail}")
                return True

        print(f"[DEBUG] pricetierDetail-{detail} gagal")

    print("[ERROR] Semua package tidak tersedia")
    return False


def _navigate_to_order(page):
    """Wait for navigation to /order, handling seat selection if needed."""
    for _ in range(45):
        page.wait_for_timeout(1000)
        if "/order" in page.url.lower():
            return True
        btn = page.get_by_role("button", name=re.compile("Lanjut pilih kursi|Continue to select", re.I))
        if btn.first.count() > 0 and btn.first.is_visible():
            btn.first.click()
            print("[INFO] Klik Lanjut pilih kursi")
            page.wait_for_timeout(3000)
    return False


def select_nationality(page, country="Indonesia"):
    inp = page.locator("#negara-tempat-tinggal").first
    if inp.count() == 0:
        print("[DEBUG] Field negara-tempat-tinggal tidak ditemukan")
        return
    inp.scroll_into_view_if_needed()
    inp.click()
    page.wait_for_timeout(3000)

    opt = page.locator(f"p:has-text('{country}')").first
    if opt.count() == 0:
        opt = page.locator(f"text={country}").first
    if opt.count() > 0:
        opt.click()
        page.wait_for_timeout(1000)
        print(f"[INFO] Nationality selected: {country}")
    else:
        print(f"[DEBUG] Tidak bisa pilih nationality: {country}")


def _fill_field(el, val):
    try:
        el.fill("")
        el.fill(val)
    except Exception:
        el.evaluate("(el, v) => { el.value = v; el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }", val)


def fill_contact_details(page, data):
    print("[INFO] Isi contact details")
    fields = [
        ("#nama-lengkap", data.get("nama")),
        ("#nomor-ponsel", data.get("no_hp")),
        ("#alamat-email", data.get("email")),
    ]
    for sel, val in fields:
        el = page.locator(sel).first
        if el.count() > 0:
            if el.get_attribute("disabled") is not None:
                print(f"[DEBUG] {sel} disabled, skip")
                continue
            _fill_field(el, val)
            page.wait_for_timeout(300)


def fill_visitor_details(page, data):
    print("[INFO] Isi visitor details")
    fields = [
        ("#nama-lengkap", data.get("nama")),
        ("#nomor-ponsel", data.get("no_hp")),
        ("#email", data.get("email")),
        ("#nomor-ktp", data.get("ktp")),
    ]
    for sel, val in fields:
        el = page.locator(sel).first
        if el.count() > 0:
            if el.get_attribute("disabled") is not None:
                print(f"[DEBUG] {sel} disabled, skip")
                continue
            _fill_field(el, val)
            page.wait_for_timeout(300)


def continue_payment(page):
    def _find_and_click(source):
        btn = source.get_by_role("button", name=re.compile("Lanjutkan pembayaran|Continue", re.I))
        if btn.first.count() > 0 and btn.first.is_visible(timeout=5000):
            btn.first.scroll_into_view_if_needed()
            source.wait_for_timeout(500)
            btn.first.click()
            return True
        return False

    try:
        if _find_and_click(page):
            print("[INFO] Klik Lanjutkan pembayaran")
            return
    except:
        pass

    for f in page.frames:
        try:
            f.wait_for_load_state("domcontentloaded", timeout=3000)
            if _find_and_click(f):
                print(f"[INFO] Klik Lanjutkan pembayaran di iframe: {f.url[:60]}")
                return
        except:
            pass

    print("[DEBUG] Tidak ditemukan tombol Lanjutkan pembayaran dimanapun")


def detect_error_popup(page):
    try:
        body = page.locator("body").inner_text(timeout=5000)
        keywords = ["kuota", "habis", "gagal", "error", "limit", "melebihi"]
        for kw in keywords:
            if kw in body.lower():
                print(f"[!] Terdeteksi popup error: mengandung '{kw}'")
                return True
    except:
        pass
    return False


# ─────────────────────────────────────────────
def main():
    config = json.load(open("config.json", encoding="utf-8"))
    personal = {
        "title": config.get("title", "Ms."),
        "nama": config.get("fullName", ""),
        "no_hp": config.get("mobileNumber", ""),
        "email": config.get("email", ""),
        "ktp": config.get("identityCardNumber", ""),
    }
    token_path = config.get("session_file", "session.json")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chrome")
        context = browser.new_context()

        token_raw = os.environ.get("TIKET_TOKEN", "").strip()
        if not token_raw:
            token_raw = input("Paste session_access_token (Enter untuk pakai session.json): ").strip()
        if token_raw:
            token_jwt = token_raw
        else:
            token_jwt = load_token(token_path)

        if token_jwt:
            apply_token(context, token_jwt)

        page = context.new_page()

        if not select_package(page, config):
            print("[ERROR] Gagal memilih package")
            context.close()
            browser.close()
            return

        page.wait_for_timeout(5000)
        print(f"[DEBUG] URL saat ini: {page.url}")

        if "order" not in page.url.lower():
            print("[ERROR] Tidak di halaman order")
            context.close()
            browser.close()
            return

        # ── klik tidak bisa refund ──
        for btn_text in ["Tidak bisa refund", "Non-refundable", "Tidak bisa"]:
            chk = page.get_by_role("button", name=re.compile(btn_text, re.I))
            if chk.first.count() > 0:
                chk.first.click()
                print(f"[ORDER PAGE] {btn_text}")
                page.wait_for_timeout(1000)
                break

        salutation = personal.get("title", "Ms.")

        # ── title contact ──
        for radio in page.locator("input[name='contactDetails.salutation'], input[name='salutation']").all():
            val = radio.get_attribute("value")
            if val and val.lower() == salutation.lower():
                radio.click(force=True)
                print(f"[INFO] Klik radio: {salutation}")
                page.wait_for_timeout(500)
                break

        # ── nationality ──
        select_nationality(page, "Indonesia")
        page.wait_for_timeout(500)

        # ── contact ──
        fill_contact_details(page, personal)

        # ── visitor: klik "Sama dengan pemesan" ──
        same = page.locator("text=Sama dengan pemesan").first
        if same.count() > 0:
            try:
                same.click()
                page.wait_for_timeout(1000)
                print("[INFO] Klik Sama dengan pemesan")
            except:
                print("[DEBUG] Gagal klik Sama dengan pemesan")

        # ── visitor details ──
        for radio in page.locator("input[name='salutation-0']").all():
            val = radio.get_attribute("value")
            if val and val.lower() == salutation.lower():
                radio.click(force=True)
                print(f"[INFO] Klik title visitor: {salutation}")
                page.wait_for_timeout(500)
                break

        fill_visitor_details(page, personal)

        # ── payment ──
        continue_payment(page)

        # ── tunggu order ID ──
        print("[INFO] Menunggu order ID...")
        order_url = None
        for _ in range(30):
            page.wait_for_timeout(2000)
            cur = page.url
            if "orderId" in cur or "order_id" in cur or re.search(r"/order/\d+", cur) or re.search(r"invoice", cur, re.I):
                order_url = cur
                print(f"[INFO] Order URL ditemukan: {cur}")
                break
            if detect_error_popup(page):
                print("[!] Ada error popup setelah klik Lanjutkan pembayaran")
                break

        if not order_url:
            order_url = page.url
            print(f"[INFO] URL saat ini: {order_url}")

        print(f"\n=== PAYMENT URL ===")
        print(order_url)
        print("===================\n")

        print("[INFO] Selesai — browser akan ditutup dalam 5dtk.")
        time.sleep(5)
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
