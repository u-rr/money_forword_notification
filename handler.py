from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.select import Select
from selenium.common.exceptions import TimeoutException
import time
import os
import requests
import re

os.environ["HOME"] = "/var/task"
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
LOGIN_ID = os.environ["LOGIN_ID"]
LOGIN_PASSWORD = os.environ["LOGIN_PASSWORD"]
UA = os.environ["UA"]
ACOUNT_SBI1_NAME = os.environ["ACOUNT_SBI1_NAME"]
ACOUNT_SBI2_NAME = os.environ["ACOUNT_SBI2_NAME"]
ACOUNT_BUSINESS_NAME = os.environ["ACOUNT_BUSINESS_NAME"]
SBI1_NAME = os.environ["SBI1_NAME"]
SBI2_NAME = os.environ["SBI2_NAME"]
BUSINESS_NAME = os.environ["BUSINESS_NAME"]


def main(event, context):
    # driverをセット
    driver = set_driver()

    # 口座一覧ページを開く
    driver.get("https://moneyforward.com/accounts")

    # 正しいURLが表示されてるか確認
    assert "moneyforward.com" in driver.current_url

    # マネーフォワードにログイン
    login(driver)

    # 口座一覧を一括更新する
    accounts_update = WebDriverWait(driver, 60).until(EC.visibility_of_element_located((By.CLASS_NAME, "btn-warning")))
    accounts_update.click()

    # ステータスが「更新中」に変わるのを待つ
    time.sleep(3)

    # 1行目のステータス「正常」が表示されるまで待つ
    try:
        status = WebDriverWait(driver, 300).until(EC.visibility_of_element_located((By.ID, "js-status-sentence-span-cNHmiFwd2QoSX5MiHCFs_w")))
        assert status.text == "正常"
    # タイムアウトをキャッチして無視
    except TimeoutException:
        pass
    # タイムアウトしてもしなくても口座情報スクレイピングする
    finally:
        acount_remaining_list = acount_table_scraping(driver)

    # Select要素を取得
    groups = get_select("group_id_hash", driver)

    # プライベートグループじゃなかったらグループを変更する
    if groups.first_selected_option.text != "プライベートの収支":
        groups.select_by_visible_text("プライベートの収支")
        time.sleep(1)

    # メイン口座の代表口座の残高だけをスクレイピング
    driver.find_element(By.CSS_SELECTOR, "#cNHmiFwd2QoSX5MiHCFs_w > td:nth-child(1) > a:nth-child(1)").click()
    sbi_1_balance = (
        WebDriverWait(driver, 60)
        .until(EC.visibility_of_element_located((By.CSS_SELECTOR, "#TABLE_1 > tbody > tr:nth-child(1) > td:nth-child(4)")))
        .text
    )

    # 口座情報をSlackに送りやすいテキストに整形
    acount1 = f"{SBI1_NAME}：{sbi_1_balance}\n{acount_remaining_list['sbi_1_latest_date']} {acount_remaining_list['sbi_1_status']}"
    acount2 = (
        f"{SBI2_NAME}：{acount_remaining_list['sbi_2_balance']}\n{acount_remaining_list['sbi_2_latest_date']} {acount_remaining_list['sbi_2_status']}"
    )
    acount3 = f"{BUSINESS_NAME}：{acount_remaining_list['business_balance']}\n{acount_remaining_list['business_latest_date']} {acount_remaining_list['business_status']}"

    slack_send_remaining_list = f"＊——最新の口座残高（生活・事業）——＊\n{acount1}\n\n{acount2}\n\n{acount3}"

    # 予算ページを表示
    driver.get("https://moneyforward.com/spending_summaries")

    # 念の為URL確認
    assert "spending_summaries" in driver.current_url

    # 集計期間をスクレイピング
    period = (
        WebDriverWait(driver, 60)
        .until(EC.visibility_of_element_located((By.CSS_SELECTOR, "#budgets-progress > div > section > div > div > div")))
        .text
    )

    # 残り日数をスクレイピングして数値だけに変換
    days_left = driver.find_element(
        By.CSS_SELECTOR, "#budgets-progress > div > section > table > thead > tr.budget_sub_header > th:nth-child(2) > div > div"
    ).text
    days_left_int = int(re.sub(r"\D", "", days_left))

    # 今日の残高に計算した結果を変数に格納
    food_remaining_per_day = calc_remaining_per_day(
        "#budgets-progress > div > section > table > tbody > tr:nth-child(5) > td.remaining", days_left_int, driver
    )
    total_remaining_per_day = calc_remaining_per_day(
        "#budgets-progress > div > section > table > tbody > tr.budget_type_total_expense.variable_type > td.remaining", days_left_int, driver
    )

    # 今月のトータル残高を取得
    total_remaining = driver.find_element(
        By.CSS_SELECTOR, "#budgets-progress > div > section > table > tbody > tr.budget_type_total_expense.variable_type > td.remaining"
    ).text

    # slackに送るテキストを整形
    balance = f"＊——プライベートの残高——＊\n今日使える食費：{food_remaining_per_day}\n今日使える総額：{total_remaining_per_day}\n今月の予算残高総額：{total_remaining}"

    # グラフのスクショを撮る
    png = screenshot(driver)

    # Select要素を再度取得（ページ更新でリセットされるため）
    groups = get_select("group_id_hash", driver)

    # 業務委託にグループを変更する
    groups.select_by_visible_text("業務委託の収支")
    time.sleep(1)

    # 今月のトータル残高を取得
    business_total_remaining = driver.find_element(
        By.CSS_SELECTOR, "#budgets-progress > div > section > table > tbody > tr.budget_type_total_expense.variable_type > td.remaining"
    ).text

    # slackに送るテキストを整形
    business_balance = f"＊——事業用の残高——＊\n今月の予算残高総額：{business_total_remaining}\n\n集計期間：{period}"

    # slackに送信
    send_message(f"{slack_send_remaining_list}\n\n{balance}\n\n{business_balance}")
    upload_img(png)

    # Select要素を再度取得（ページ更新でリセットされるため）
    groups = get_select("group_id_hash", driver)

    # アプリから確認のときにプライベートが開いてて欲しいので選択状態にしておく
    groups.select_by_visible_text("プライベートの収支")
    time.sleep(1)

    driver.quit()


def set_driver():
    options = webdriver.ChromeOptions()
    options.binary_location = "/opt/headless-chromium"
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--single-process")
    options.add_argument("--disable-dev-shm-usage")
    # ユーザーエージェントを偽装（ヘッドレスモードで実行するため）
    options.add_argument(f"--user-agent={UA}")

    # Headless Chromeをreturnする
    return webdriver.Chrome(executable_path="/opt/chromedriver", chrome_options=options)


def login(driver):
    """[summary]
        マネーフォワードにログインする処理
    """
    # メールアドレスでログインをクリック
    login_mail_address = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.LINK_TEXT, "メールアドレスでログイン")))
    login_mail_address.send_keys(Keys.RETURN)

    # ログインIDを入力
    login_id = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.NAME, "mfid_user[email]")))
    assert "email" in driver.current_url
    login_id.send_keys(LOGIN_ID, Keys.RETURN)

    # パスワードを入力
    password = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.NAME, "mfid_user[password]")))
    assert "password" in driver.current_url
    password.send_keys(LOGIN_PASSWORD, Keys.RETURN)


def get_select(id: str, driver):
    """[summary]

    Args:
        id (str): select要素を取得したい場所のid名
        driver ([type]): driverを渡す

    Returns:
        select要素
    """
    group_list = WebDriverWait(driver, 60).until(EC.visibility_of_element_located((By.ID, id)))
    return Select(group_list)


def screenshot(driver):
    """[summary]

    Args:
        driver ([type]): driverを渡す

    Returns:
        pngのバイナリデータ
    """
    # 念の為待機
    time.sleep(1)

    # ページ全体の横幅と縦幅を取得してウィンドウサイズとしてセット。これをやらないと画面外が見切れる。
    page_width = driver.execute_script("return document.body.scrollWidth")
    page_height = driver.execute_script("return document.body.scrollHeight")
    driver.set_window_size(page_width, page_height)

    # スクリーンショットをとる
    png = driver.find_element(By.CSS_SELECTOR, "#budgets-progress > div > section").screenshot_as_png

    return png


def calc_remaining_per_day(webElement: str, days_left: int, driver) -> str:
    """[summary]

    Args:
        webElement (str): スクレイピングしたい残高のCSS_SELECTORを渡す
        days_left (int): 残り日数を渡す
        driver ([type]): driverを渡す

    Returns:
        [str]: 残高を残り日数で割った金額をカンマつきのstrにして返す
    """
    time.sleep(1)
    remaining = driver.find_element(By.CSS_SELECTOR, webElement).text
    return "{:,d}円".format(int(remaining[0:-1].replace(",", "")) // days_left)


def acount_table_scraping(driver) -> dict:
    """[summary]
        特定の口座残高の情報をスクレイピングして辞書に格納して返す
    Args:
        driver ([type]): driverを渡す

    Returns:
        str: Slackに送りたい口座残高などが入った辞書
    """

    tableElem = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.TAG_NAME, "table")))
    trs = tableElem.find_elements(By.TAG_NAME, "tr")

    acount_table_dct = {}
    # ヘッダ行は除いて取得
    for i in range(1, len(trs)):
        tds = trs[i].find_elements(By.TAG_NAME, "td")
        line = []
        for j in range(0, len(tds)):
            if j < len(tds) - 1:
                line.append(f"{tds[j].text}\t")
            else:
                line.append(tds[j].text)

        acount_name = line[0]
        if ACOUNT_SBI1_NAME in acount_name:
            # acount_sbi_1_balance = line[1]
            acount_table_dct["sbi_1_latest_date"] = line[2][-13:-2]
            acount_table_dct["sbi_1_status"] = line[3].rstrip()
        if ACOUNT_SBI2_NAME in acount_name:
            acount_table_dct["sbi_2_balance"] = line[1].rstrip()
            acount_table_dct["sbi_2_latest_date"] = line[2][-13:-2]
            acount_table_dct["sbi_2_status"] = line[3].rstrip()
        if ACOUNT_BUSINESS_NAME in acount_name:
            acount_table_dct["business_balance"] = line[1].rstrip()
            acount_table_dct["business_latest_date"] = line[2][-13:-2]
            acount_table_dct["business_status"] = line[3].rstrip()

    return acount_table_dct


def send_message(text: str):
    """[summary]
        Slackにテキストを送る
    Args:
        text (str): Slackに送りたい文字列
    """
    headers = {"Authorization": "Bearer" + SLACK_BOT_TOKEN}

    data = {
        "token": SLACK_BOT_TOKEN,
        "channel": CHANNEL_ID,
        "text": text,
        "icon_emoji": ":moneybag:",
    }

    res = requests.post("https://slack.com/api/chat.postMessage", headers=headers, data=data)
    return res


def upload_img(png):
    """[summary]
        Slackにサマリー画像のキャプチャを送る

    Returns:
        なし
    """
    files = {"file": png}

    data = {
        "token": SLACK_BOT_TOKEN,
        "channels": CHANNEL_ID,
        "filename": "sammary.png",
        "initial_comment": "プライベート予算のサマリー",
        "title": "プライベート予算のサマリー",
        "icon_emoji": ":moneybag:",
    }

    res = requests.post("https://slack.com/api/files.upload", data=data, files=files)
    return res


# if __name__ == "__main__":
#     main()
