
# crawler/google_trends.py
import json
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager


def get_google_trends_data(keyword: str, geo="HK", hl="zh-TW"):
    """
    利用 Selenium 爬取 Google Trends 官方頁面資料
    （改良：等待頁面載入、避免找不到 __NEXT_DATA__）
    """
    result = {"topics": [], "queries": []}
    if not keyword.strip():
        print("⚠️ 輸入關鍵字為空。")
        return result

    print(f"📡 啟動 Selenium, 正在打開 Google Trends：「{keyword}」 ...")

    # ========== Chrome 设置 ==========
    chrome_opts = Options()
    # ⚠️ 先暫時註解掉 headless 看是否有 CAPTCHA 或不同版面
    # chrome_opts.add_argument("--headless=new")
    chrome_opts.add_argument("--disable-gpu")
    chrome_opts.add_argument("--no-sandbox")
    chrome_opts.add_argument("--window-size=1920,1080")
    chrome_opts.add_argument("--lang=zh-TW")

    driver = None

    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_opts)
        url = f"https://trends.google.com/trends/explore?hl={hl}&geo={geo}&q={keyword}"
        driver.get(url)

        # ========== 等待 JSON 出現 ==========
        try:
            wait = WebDriverWait(driver, 15)
            elem = wait.until(EC.presence_of_element_located((By.ID, "__NEXT_DATA__")))
            json_text = elem.get_attribute("innerText")
        except TimeoutException:
            print("❌ 等待 __NEXT_DATA__ 超時，可能頁面載入失敗或被導向其他頁。")
            driver.quit()
            return result

        data = json.loads(json_text)

        # 關閉瀏覽器
        driver.quit()

        # ========== 解析 JSON ==========
        widgets = (
            data.get("props", {})
            .get("pageProps", {})
            .get("initialData", {})
            .get("widgets", [])
        )

        related_topics = next((w for w in widgets if w["id"] == "RELATED_TOPICS"), None)
        related_queries = next((w for w in widgets if w["id"] == "RELATED_QUERIES"), None)

        if related_topics:
            for section in ["rising", "top"]:
                for item in related_topics.get("data", {}).get("default", {}).get(section, []):
                    result["topics"].append({
                        "topic_title": item["topic"]["title"],
                        "type": section
                    })
        else:
            print("⚠️ 沒有找到 RELATED_TOPICS")

        if related_queries:
            for section in ["rising", "top"]:
                for item in related_queries.get("data", {}).get("default", {}).get(section, []):
                    result["queries"].append({
                        "query": item["query"],
                        "value": str(item.get("value", "")),
                        "type": section
                    })
        else:
            print("⚠️ 沒有找到 RELATED_QUERIES")

        print(f"✅ 成功抓取 {len(result['topics'])} 主題、{len(result['queries'])} 搜尋")
        return result

    except NoSuchElementException as e:
        print("❌ 找不到元素：", e)
        if driver:
            driver.quit()
        return result

    except Exception as e:
        print("❌ Selenium 抓取錯誤：", e)
        if driver:
            driver.quit()
        return result
