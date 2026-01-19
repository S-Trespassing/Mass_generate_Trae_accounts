import asyncio
import random
import string
import os
import re
import json
import sys
from playwright.async_api import async_playwright
from mail_client import AsyncMailClient

# Setup directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_DIR = os.path.join(BASE_DIR, "cookies")
ACCOUNTS_FILE = os.path.join(BASE_DIR, "accounts.txt")
os.makedirs(COOKIES_DIR, exist_ok=True)

def generate_password(length=12):
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choices(chars, k=length))

async def save_account(email, password):
    write_header = not os.path.exists(ACCOUNTS_FILE) or os.path.getsize(ACCOUNTS_FILE) == 0
    with open(ACCOUNTS_FILE, "a", encoding="utf-8") as f:
        if write_header:
            f.write("Email    Password\n")
        f.write(f"{email}    {password}\n")
    print(f"账号已保存到: {ACCOUNTS_FILE}")

async def run_registration():
    print("开始单账号注册流程...")
    
    mail_client = AsyncMailClient()
    browser = None
    context = None
    page = None

    try:
        # 1. Setup Mail
        await mail_client.start()
        email = mail_client.get_email()
        password = generate_password()

        # 2. Setup Browser
        async with async_playwright() as p:
            print("启动浏览器...")
            # Use headless=False if you want to watch it, True for background
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            # 3. Sign Up Process
            print("打开注册页面...")
            await page.goto("https://www.trae.ai/sign-up")
            
            # Fill Email
            await page.get_by_role("textbox", name="Email").fill(email)
            await page.get_by_text("Send Code").click()
            print("验证码已发送，等待邮件...")

            # Poll for code
            verification_code = None
            for i in range(12): # 60 seconds max
                await mail_client.check_emails()
                if mail_client.last_verification_code:
                    verification_code = mail_client.last_verification_code
                    break
                print(f"正在检查邮箱... ({i+1}/12)")
                await asyncio.sleep(5)

            if not verification_code:
                print("60秒内未收到验证码。")
                return

            # Fill Code & Password
            await page.get_by_role("textbox", name="Verification code").fill(verification_code)
            await page.get_by_role("textbox", name="Password").fill(password)

            # Click Sign Up
            signup_btns = page.get_by_text("Sign Up")
            if await signup_btns.count() > 1:
                await signup_btns.nth(1).click()
            else:
                await signup_btns.click()
            
            print("正在提交注册...")

            # Verify Success (Check URL change or specific element)
            try:
                await page.wait_for_url(lambda url: "/sign-up" not in url, timeout=20000)
                print("注册成功（页面已跳转）")
            except:
                # Check for errors
                if await page.locator(".error-message").count() > 0:
                    err = await page.locator(".error-message").first.inner_text()
                    print(f"注册失败：{err}")
                    return
                print("注册成功检查超时，继续后续流程...")

            # Save Account
            await save_account(email, password)

            # 4. Claim Gift
            print("检查周年礼包...")
            await page.goto("https://www.trae.ai/2026-anniversary-gift")
            await page.wait_for_load_state("networkidle")

            claim_btn = page.get_by_role("button", name=re.compile("claim", re.IGNORECASE))
            if await claim_btn.count() > 0:
                text = await claim_btn.first.inner_text()
                if "claimed" in text.lower():
                    print("礼包状态：已领取")
                else:
                    print(f"点击领取按钮：{text}")
                    await claim_btn.first.click()
                    # Wait for status update
                    try:
                        await page.wait_for_function(
                            "btn => btn.innerText.toLowerCase().includes('claimed')",
                            arg=await claim_btn.first.element_handle(),
                            timeout=10000
                        )
                        print("礼包领取成功！")
                    except:
                        print("已点击领取，但状态未更新为“已领取”。")
            else:
                print("未找到领取按钮。")

            # 5. Save Cookies
            cookies = await context.cookies()
            cookie_path = os.path.join(COOKIES_DIR, f"{email}.json")
            with open(cookie_path, "w", encoding="utf-8") as f:
                json.dump(cookies, f)
            print(f"已保存浏览器 Cookie 到: {cookie_path}")

    except Exception as e:
        print(f"发生异常：{e}")
    finally:
        if mail_client:
            await mail_client.close()
        # Browser closes automatically with context manager

async def run_batch(total, concurrency):
    if total <= 0:
        print("批量注册数量必须大于 0。")
        return
    if concurrency <= 0:
        print("并发数量必须大于 0。")
        return
    concurrency = min(concurrency, total)
    print(f"开始批量注册，总数量：{total}，并发数：{concurrency}")

    queue = asyncio.Queue()
    for i in range(1, total + 1):
        queue.put_nowait(i)
    for _ in range(concurrency):
        queue.put_nowait(None)

    async def worker(worker_id):
        while True:
            index = await queue.get()
            if index is None:
                queue.task_done()
                return
            print(f"[线程 {worker_id}] 开始注册第 {index}/{total} 个账号...")
            try:
                await run_registration()
            finally:
                print(f"[线程 {worker_id}] 第 {index}/{total} 个账号完成。")
                queue.task_done()

    tasks = [asyncio.create_task(worker(i + 1)) for i in range(concurrency)]
    await queue.join()
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    # if sys.platform == 'win32':
    #     asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    total = 1
    concurrency = 1
    if len(sys.argv) > 1:
        try:
            total = int(sys.argv[1])
        except ValueError:
            print("参数错误：请输入批量注册数量（整数）。")
            sys.exit(1)
    if len(sys.argv) > 2:
        try:
            concurrency = int(sys.argv[2])
        except ValueError:
            print("参数错误：请输入并发数量（整数）。")
            sys.exit(1)
    asyncio.run(run_batch(total, concurrency))
