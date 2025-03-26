import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="multiprocessing.resource_tracker")

import time
import pickle
import os
import sys
import atexit
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException

# Configuratie
USERNAME = "Nick90NL"
PASSWORD = "taqdoR-gigty5-zyrmev"
COOKIES_FILE = "cookies.pkl"
LOGIN_URL = "https://aternos.org/go/"
SERVER_URL = "https://aternos.org/servers/"
MAX_RETRY_COUNT = 3
MAX_WAIT_ONLINE = 300  # 5 minuten
SCRIPT_VERSION = "1.2.1"

# Globale variabelen
driver = None
browser_closed = False
audio_muted_once = False  # Zorgt ervoor dat het debugbericht voor audio muting slechts één keer verschijnt

def debug_print(msg):
    """Print een debug-bericht met timestamp."""
    timestamp = time.strftime("%H:%M:%S", time.localtime())
    print(f"[{timestamp}] {msg}")

def cleanup_browser():
    """Sluit browser netjes af als dat nog niet gebeurd is."""
    global driver, browser_closed
    if driver and not browser_closed:
        try:
            debug_print("Browser netjes afsluiten...")
            driver.service.process.send_signal(15)  # SIGTERM
            time.sleep(0.5)
            driver.service.process.kill()  # SIGKILL als backup
            driver.quit()
            browser_closed = True
            debug_print("Browser afgesloten.")
        except Exception as e:
            debug_print(f"Fout tijdens afsluiten browser: {str(e)}")

def cleanup_and_exit(exit_code=0, message=None):
    """Ruim netjes op en sluit af met opgegeven exit code."""
    if message:
        debug_print(message)
    cleanup_browser()
    debug_print(f"Script beëindigd met exit code {exit_code}")
    os._exit(exit_code)

def save_cookies(driver, file_path):
    """Sla cookies op voor hergebruik."""
    try:
        with open(file_path, "wb") as f:
            pickle.dump(driver.get_cookies(), f)
        debug_print("✓ Cookies opgeslagen.")
        return True
    except Exception as e:
        debug_print(f"✗ Fout bij opslaan cookies: {str(e)}")
        return False

def load_cookies(driver, file_path):
    """Laad opgeslagen cookies."""
    try:
        if not os.path.exists(file_path):
            debug_print("✗ Cookies-bestand niet gevonden.")
            return False
        with open(file_path, "rb") as f:
            cookies = pickle.load(f)
            for cookie in cookies:
                driver.add_cookie(cookie)
        debug_print("✓ Cookies geladen.")
        return True
    except Exception as e:
        debug_print(f"✗ Fout bij laden cookies: {str(e)}")
        return False

def apply_audio_muting(driver):
    """Forceer audio muting voor alle media-elementen; debugbericht slechts één keer weergeven."""
    global audio_muted_once
    try:
        driver.execute_script("""
            // Dempt alle audio- en video-elementen
            document.querySelectorAll('audio, video').forEach(el => {
                el.muted = true;
                el.volume = 0;
                el.pause();
            });
            // AudioContext aanpassen zodat nieuwe audio automatisch gemute wordt
            if (window.AudioContext || window.webkitAudioContext) {
                const OrigAudioContext = window.AudioContext || window.webkitAudioContext;
                window.AudioContext = window.webkitAudioContext = class extends OrigAudioContext {
                    constructor() {
                        super();
                        if (this.destination && this.destination.gain) {
                            this.destination.gain.value = 0;
                        }
                    }
                };
            }
        """)
        if not audio_muted_once:
            debug_print("✓ Audio geforceerd gemute (alle media-elementen).")
            audio_muted_once = True
        return True
    except Exception as e:
        debug_print(f"✗ Fout bij audio muting: {str(e)}")
        return False

def click_consent_buttons(driver, timeout=15):
    """Zoek en klik op consent-knoppen."""
    try:
        end_time = time.time() + timeout
        clicked = False
        while time.time() < end_time:
            consent_buttons = driver.find_elements(By.XPATH, "//button[@aria-label='Consent']")
            if not consent_buttons:
                break
            for btn in consent_buttons:
                if btn.is_displayed() and btn.is_enabled():
                    driver.execute_script("arguments[0].click();", btn)
                    clicked = True
                    time.sleep(0.5)
            if not clicked:
                break
        if clicked:
            debug_print("✓ Consent-knoppen verwerkt.")
        return clicked
    except Exception as e:
        debug_print("✗ Fout bij verwerken consent-knoppen: " + str(e))
        return False

def wait_for_element(driver, locator, timeout=10, condition="presence"):
    """Wacht op een element met foutafhandeling."""
    try:
        if condition == "presence":
            element = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located(locator)
            )
        elif condition == "clickable":
            element = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable(locator)
            )
        elif condition == "visible":
            element = WebDriverWait(driver, timeout).until(
                EC.visibility_of_element_located(locator)
            )
        return element
    except TimeoutException:
        return None
    except Exception as e:
        debug_print(f"✗ Fout bij wachten op element {locator}: {str(e)}")
        return None

def is_server_online(driver):
    """Controleer of de server online is via verschillende methoden."""
    try:
        try:
            online_status = driver.find_element(By.CSS_SELECTOR, "div.status.online")
            if online_status.is_displayed():
                return True
        except (NoSuchElementException, StaleElementReferenceException):
            pass
        try:
            status_label = driver.find_element(By.CSS_SELECTOR, "span.statuslabel-label")
            if status_label and "Online" in status_label.text:
                return True
        except (NoSuchElementException, StaleElementReferenceException):
            pass
        return False
    except Exception as e:
        debug_print("✗ Fout bij controleren online status: " + str(e))
        return False

def get_remaining_time(driver):
    """Haal de resterende tijd op indien beschikbaar."""
    try:
        countdown = driver.find_element(By.CSS_SELECTOR, "div.server-end-countdown")
        if countdown.is_displayed():
            return countdown.text
    except (NoSuchElementException, StaleElementReferenceException):
        pass
    return None

def initialize_browser():
    debug_print(f"Aternos Server Script v{SCRIPT_VERSION} - Start")
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.page_load_strategy = 'eager'
    options.add_argument("--mute-audio")
    options.add_argument("--autoplay-policy=user-gesture-required")
    options.add_argument("--disable-audio-output")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    options.add_argument("--disable-logging")
    options.add_argument("--log-level=3")
    try:
        browser = uc.Chrome(options=options)
        browser.set_window_size(1280, 800)
        # Overwrite de play() methode zodat media-elementen niet afspelen
        browser.execute_script("""
            HTMLMediaElement.prototype.play = function() {
                return Promise.resolve();
            };
        """)
        browser.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        debug_print("✓ Browser succesvol geïnitialiseerd")
        return browser
    except Exception as e:
        debug_print("✗ Fout bij initialiseren browser: " + str(e))
        return None

def login_with_cookies(driver):
    """Probeer in te loggen met opgeslagen cookies."""
    try:
        driver.get(SERVER_URL)
        apply_audio_muting(driver)
        if not load_cookies(driver, COOKIES_FILE):
            return False
        driver.refresh()
        apply_audio_muting(driver)
        account_element = wait_for_element(driver, (By.CSS_SELECTOR, "div.user a[title='Account']"), timeout=15)
        if account_element:
            debug_print("✓ Ingelogd met cookies")
            return True
        else:
            debug_print("✗ Cookies verlopen of ongeldig")
            return False
    except Exception as e:
        debug_print("✗ Fout bij inloggen met cookies: " + str(e))
        return False

def login_manually(driver):
    """Voer handmatige login uit."""
    try:
        debug_print("🔐 Handmatig inloggen...")
        driver.get(LOGIN_URL)
        apply_audio_muting(driver)
        login_wrapper = wait_for_element(driver, (By.CLASS_NAME, "login-wrapper"), timeout=30)
        if not login_wrapper:
            debug_print("✗ Login formulier niet gevonden")
            driver.save_screenshot("no_login_form.png")
            return False
        driver.find_element(By.CLASS_NAME, "username").send_keys(USERNAME)
        driver.find_element(By.CLASS_NAME, "password").send_keys(PASSWORD)
        driver.find_element(By.CLASS_NAME, "login-button").click()
        if WebDriverWait(driver, 30).until(EC.url_contains("/servers")):
            debug_print("✓ Handmatig inloggen succesvol, URL: " + driver.current_url)
            save_cookies(driver, COOKIES_FILE)
            return True
        else:
            debug_print("✗ Handmatig inloggen mislukt")
            driver.save_screenshot("login_failed.png")
            return False
    except Exception as e:
        debug_print("✗ Fout bij handmatig inloggen: " + str(e))
        driver.save_screenshot("login_error.png")
        return False

def navigate_to_server(driver):
    """Navigeer naar de serverdetailpagina."""
    try:
        driver.get(SERVER_URL)
        apply_audio_muting(driver)
        click_consent_buttons(driver)
        retry_count = 0
        server_clicked = False
        while retry_count < MAX_RETRY_COUNT and not server_clicked:
            try:
                server_xpath = ("//div[contains(@class, 'servercard') and .//div[contains(@class, 'server-name') "
                                "and normalize-space(text())='Nick90NL']]//div[contains(@class, 'server-name')]")
                server_element = wait_for_element(driver, (By.XPATH, server_xpath), timeout=15, condition="clickable")
                if server_element:
                    driver.execute_script("arguments[0].scrollIntoView(true);", server_element)
                    driver.execute_script("arguments[0].click();", server_element)
                    debug_print("🚀 Server 'Nick90NL' aangeklikt")
                    if WebDriverWait(driver, 15).until(EC.url_contains("/server/")):
                        apply_audio_muting(driver)
                        server_clicked = True
                        debug_print("✓ Navigatie naar serverdetailpagina succesvol")
                        return True
                else:
                    debug_print(f"Server element niet gevonden (poging {retry_count+1}/{MAX_RETRY_COUNT})")
            except Exception as e:
                debug_print(f"✗ Fout bij navigeren naar server (poging {retry_count+1}): {str(e)}")
            retry_count += 1
            time.sleep(2)
        if not server_clicked:
            debug_print("✗ Kon niet navigeren naar server na meerdere pogingen")
            driver.save_screenshot("server_navigation_failed.png")
            return False
    except Exception as e:
        debug_print("✗ Onverwachte fout bij navigeren naar server: " + str(e))
        driver.save_screenshot("server_navigation_error.png")
        return False

def check_server_status_and_start(driver):
    """Controleer server status en start indien nodig.
    Zodra de server online is, stopt het script (zonder extra loop-berichten voor audio)."""
    try:
        status_element = wait_for_element(driver, (By.CSS_SELECTOR, "div.status"), timeout=15)
        if not status_element:
            debug_print("✗ Kan server status niet vinden")
            driver.save_screenshot("no_status.png")
            return False
        if is_server_online(driver):
            time_left = get_remaining_time(driver)
            if time_left:
                debug_print(f"✓ Server is al online! Resterende tijd: {time_left}")
            else:
                debug_print("✓ Server is al online!")
            driver.save_screenshot("server_already_online.png")
            return True
        debug_print("Server is offline, probeer te starten...")
        start_button = wait_for_element(driver, (By.ID, "start"), timeout=15, condition="clickable")
        if not start_button:
            debug_print("✗ Kon geen 'Start' knop vinden")
            driver.save_screenshot("no_start_button.png")
            return False
        driver.execute_script("arguments[0].click();", start_button)
        debug_print("✓ 'Start' knop aangeklikt")
        try:
            no_button = wait_for_element(driver, (By.XPATH, "//button[normalize-space(text())='Nee']"), timeout=10, condition="clickable")
            if no_button:
                driver.execute_script("arguments[0].click();", no_button)
                debug_print("✓ 'Nee' knop voor meldingen aangeklikt")
        except TimeoutException:
            debug_print("Geen 'Nee' knop gevonden, doorgaan...")
        debug_print(f"Wachten tot server online komt (max {MAX_WAIT_ONLINE/60:.1f} minuten)...")
        start_time = time.time()
        while time.time() - start_time < MAX_WAIT_ONLINE:
            # Voer periodiek audio muting uit zonder debug-output
            apply_audio_muting(driver)
            if is_server_online(driver):
                time_left = get_remaining_time(driver)
                if time_left:
                    debug_print(f"✓ Server is online gekomen! Resterende tijd: {time_left}")
                else:
                    debug_print("✓ Server is online gekomen!")
                apply_audio_muting(driver)
                driver.save_screenshot("server_online_success.png")
                return True
            time.sleep(1)
        debug_print("✗ Server is niet online gekomen na 5 minuten")
        driver.save_screenshot("server_not_online.png")
        return False
    except Exception as e:
        debug_print("✗ Fout bij controleren/starten van server: " + str(e))
        driver.save_screenshot("server_check_error.png")
        return False

def main():
    """Hoofdfunctie van het script."""
    global driver
    atexit.register(cleanup_browser)
    try:
        driver = initialize_browser()
        if not driver:
            cleanup_and_exit(1, "Kon browser niet initialiseren, script wordt afgebroken.")
        logged_in = login_with_cookies(driver)
        if not logged_in:
            logged_in = login_manually(driver)
        if not logged_in:
            cleanup_and_exit(1, "Kon niet inloggen, script wordt afgebroken.")
        if not navigate_to_server(driver):
            cleanup_and_exit(1, "Kon niet naar server navigeren, script wordt afgebroken.")
        server_online = check_server_status_and_start(driver)
        if server_online:
            cleanup_and_exit(0, "✓ Succes! Server is online. Script voltooid.")
        else:
            cleanup_and_exit(1, "✗ Kon server niet online krijgen. Script gefaald.")
    except Exception as e:
        debug_print("✗ Onverwachte fout in hoofdprogramma: " + str(e))
        if driver:
            driver.save_screenshot("unexpected_error.png")
        cleanup_and_exit(1, "Script afgebroken door onverwachte fout.")

if __name__ == "__main__":
    main()