import re
import time
from urllib.parse import urlparse, unquote

import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

import env  # noqa: F401
from env import DriverLocation  # Asegúrate de que tu env.py define estas variables

def ifGDRPNotice(driver):
    """Acepta el aviso de cookies si aparece."""
    if 'consent.google.com' in driver.current_url:
        try:
            driver.execute_script('document.getElementsByTagName("form")[0].submit();')
            time.sleep(2)
        except:
            pass

def wait_until_loaded(driver):
    """Espera a que la página termine de cargar."""
    while driver.execute_script('return document.readyState;') != 'complete':
        time.sleep(1)

def get_reviews_container(driver, timeout=15):
    """
    Devuelve el contenedor scrollable que realmente contiene las reseñas.
    Google anida varias capas con clases m6QErb; solo la que también contiene
    DxyBCb/dS8AEf responde a scrollTop, por eso filtramos específicamente.
    """
    wait = WebDriverWait(driver, timeout)

    def _locate(_):
        candidates = driver.find_elements(By.CSS_SELECTOR, "div.m6QErb.DxyBCb")
        for c in candidates:
            if c.get_attribute("tabindex") == "-1" and c.find_elements(By.CSS_SELECTOR, "div.jftiEf"):
                return c
        return False

    return wait.until(_locate)


def get_reviews_scroll_wrapper(driver, timeout=15):
    """Devuelve el contenedor externo que gestiona el scroll (clase XltNde tTVLSc)."""
    wait = WebDriverWait(driver, timeout)
    return wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.XltNde.tTVLSc")))


def scroll_until_end(driver, pause=2.0, stable_rounds=10, max_scrolls=800):
    """
    Scrollea haciendo scrollIntoView del último elemento de la lista repetidamente.
    """
    print("Scrolling reviews container until all reviews are loaded...")
    target = get_reviews_container(driver)
    driver.execute_script("arguments[0].focus();", target)

    prev_count = 0
    stagnant_rounds = 0

    for idx in range(1, max_scrolls + 1):
        cards = target.find_elements(By.CSS_SELECTOR, "div.jftiEf.fontBodyMedium")
        if not cards:
            break

        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", target)
        print(f"   · Scroll pass {idx} (scrolled to card #{len(cards)})")
        time.sleep(pause)

        new_count = len(target.find_elements(By.CSS_SELECTOR, "div.jftiEf.fontBodyMedium"))
        print(f"     Reviews loaded: {new_count} (prev {prev_count})")

        if new_count == prev_count:
            stagnant_rounds += 1
            if stagnant_rounds >= stable_rounds:
                print("   · No further growth detected, stopping scroll.")
                break
        else:
            stagnant_rounds = 0
            prev_count = new_count

    total_reviews = len(target.find_elements(By.CSS_SELECTOR, "div.jftiEf.fontBodyMedium"))
    print(f"✅ Scroll completed. Reviews detected: {total_reviews}")
    return target

def expand_long_reviews(driver, container=None):
    """Hace click en los botones 'Más' para expandir textos completos."""
    print("Expanding long reviews...")
    target = container or get_reviews_container(driver)
    buttons = target.find_elements(By.CSS_SELECTOR, "button.w8nwRe")
    for btn in buttons:
        try:
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(0.1)
        except:
            pass

def get_data(driver, container=None):
    """Extrae nombre, rating, texto completo."""
    print("Extracting reviews...")

    target = container or get_reviews_container(driver)
    reviews = target.find_elements(By.CSS_SELECTOR, "div.jftiEf.fontBodyMedium")
    data = []

    for idx, r in enumerate(reviews, start=1):
        try:
            name = r.find_element(By.CSS_SELECTOR, "div.d4r55").text
        except:
            name = "Unknown"

        try:
            rating = r.find_element(By.CSS_SELECTOR, "span.kvMYJc").get_attribute("aria-label")[0]
        except:
            rating = "-"

        try:
            text = r.find_element(By.CSS_SELECTOR, "span.wiI7pd").text
        except:
            text = ""

        try:
            raw_date = r.find_element(By.CSS_SELECTOR, "span.rsqaWe").text
        except:
            raw_date = ""

        snippet = text[:60].replace("\n", " ")
        print(f" → Review #{idx} | {name} | {rating}⭐ | {snippet}...")

        data.append([name, text, rating, raw_date])

    return data

def write_to_csv(data, filename="out.csv"):
    print(f"Saving to {filename}...")
    df = pd.DataFrame(data, columns=["name", "comment", "rating", "review_date"])
    df.insert(0, "id", range(1, len(df) + 1))  # autonumérico
    df.to_csv(filename, index=False, encoding='utf-8')
    print(f"✅ File saved as {filename}")


def get_target_urls():
    urls = getattr(env, "URLS", None)
    if urls is None:
        urls = getattr(env, "URL", None)

    if urls is None:
        raise ValueError("Agrega una variable URL o URLS en env.py")

    if isinstance(urls, str):
        cleaned = [urls.strip()]
    else:
        try:
            cleaned = [u.strip() for u in urls if isinstance(u, str)]
        except TypeError:
            raise TypeError("URLS debe ser un iterable de strings.")

    cleaned = [u for u in cleaned if u]
    if not cleaned:
        raise ValueError("No se encontraron URLs válidas en env.py")
    return cleaned


def scrape_url(url):
    print(f"\n============================")
    print(f"Scraping: {url}")

    options = webdriver.ChromeOptions()
    options.add_argument("--lang=es-ES")
    options.add_experimental_option('prefs', {'intl.accept_languages': 'es-ES'})

    driver = webdriver.Chrome(executable_path=DriverLocation, options=options)
    try:
        driver.get(url)

        wait_until_loaded(driver)
        ifGDRPNotice(driver)
        wait_until_loaded(driver)

        container = scroll_until_end(driver)
        expand_long_reviews(driver, container=container)
        return get_data(driver, container=container)
    finally:
        driver.quit()


def business_slug_from_url(url):
    parsed = urlparse(url)
    path = parsed.path or ""
    marker = "/place/"
    start = path.find(marker)
    if start == -1:
        return "reviews"
    segment = path[start + len(marker):]
    segment = segment.split("/@", 1)[0]
    segment = segment.strip("/")
    if not segment:
        return "reviews"
    decoded = unquote(segment)
    decoded = decoded.replace("+", "_").replace(" ", "_")
    decoded = re.sub(r"[^\w_]", "_", decoded)
    decoded = re.sub(r"_+", "_", decoded).strip("_")
    return decoded or "reviews"

if __name__ == "__main__":
    for target_url in get_target_urls():
        dataset = scrape_url(target_url)
        if dataset:
            filename = f"{business_slug_from_url(target_url)}.csv"
            write_to_csv(dataset, filename=filename)
        else:
            print(f"⚠️ No data written for {target_url}.")
