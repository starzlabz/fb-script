import os
import sys
import json
import time
import sqlite3
import warnings
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

import requests


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DB_DIR, "scheduler.db")
BOT_FLOW_ENV_NAMES = {
    "custom": "BOT_BUTTONS",
    "send-invite": "BOT_SEND_INVITE_BUTTONS",
    "accept-invite": "BOT_ACCEPT_INVITE_BUTTONS",
}
BOT_FLOW_URL_ENV_NAMES = {
    "custom": ("BOT_URL",),
    "send-invite": ("BOT_SEND_INVITE_URL", "BOT_POST_PAGE_URL", "BOT_URL"),
    "accept-invite": ("BOT_ACCEPT_INVITE_URL", "BOT_ACCEPT_PAGE_URL", "BOT_URL"),
}
BOT_FLOW_PROFILE_ENV_NAMES = {
    "send-invite": ("BOT_SEND_INVITE_PROFILE_NAME", "BOT_POST_PAGE_NAME"),
    "accept-invite": ("BOT_ACCEPT_INVITE_PROFILE_NAME", "BOT_ACCEPT_PAGE_NAME"),
}
BOT_FACEBOOK_PAGE_FLOWS = {"send-invite", "accept-invite"}
BOT_SWITCH_PROMPT_TARGET = "switch-profile-if-present"
BOT_OLD_SWITCH_PROMPT_TARGET = "optional=text=Switch"


def is_placeholder_value(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized.startswith("your_") and normalized.endswith("_here")


def strip_env_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def get_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if value is None or not value.strip():
        raise ValueError(f"Missing environment variable: {name}")
    value = value.strip()
    if is_placeholder_value(value):
        raise ValueError(f"{name} is still set to a placeholder value in .env")
    return value


def get_optional_env(name: str) -> Optional[str]:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None

    value = value.strip()
    if is_placeholder_value(value):
        raise ValueError(f"{name} is still set to a placeholder value in .env")

    return value


def load_env_file(env_path: str = ".env") -> None:
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = strip_env_quotes(value)

            if key and key not in os.environ:
                os.environ[key] = value


def validate_facebook_config(page_access_token: str) -> None:
    if page_access_token.lower().startswith("bearer "):
        raise ValueError("PAGE_ACCESS_TOKEN should contain only the token, without 'Bearer '")

    if any(ch.isspace() for ch in page_access_token):
        raise ValueError("PAGE_ACCESS_TOKEN contains whitespace; keep the token on one line in .env")


def get_env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False

    raise ValueError(f"{name} must be a boolean value like true or false")


def get_env_int(name: str, default: int, minimum: int = 0) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default

    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be a whole number") from exc

    if parsed < minimum:
        raise ValueError(f"{name} must be at least {minimum}")

    return parsed


def normalize_bot_url(url: str) -> str:
    normalized = url.strip()
    if not normalized:
        raise ValueError("Missing bot URL")

    parsed = urlparse(normalized)
    if not parsed.scheme:
        normalized = f"https://{normalized}"
        parsed = urlparse(normalized)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Bot URL must be a valid http or https URL")

    return normalized


def parse_bot_buttons(value: str) -> list[str]:
    value = value.strip()
    if not value:
        return []

    if value.startswith("["):
        buttons = json.loads(value)
        if not isinstance(buttons, list) or not all(isinstance(button, str) for button in buttons):
            raise ValueError("BOT_BUTTONS must be a JSON array of strings")
        return [button.strip() for button in buttons if button.strip()]

    return [button.strip() for button in value.split(",") if button.strip()]


def get_bot_profile_dir() -> str:
    profile_dir = os.getenv("BOT_PROFILE_DIR", os.path.join("data", "browser-profile")).strip()
    if not profile_dir:
        profile_dir = os.path.join("data", "browser-profile")

    if not os.path.isabs(profile_dir):
        profile_dir = os.path.join(BASE_DIR, profile_dir)

    os.makedirs(profile_dir, exist_ok=True)
    return profile_dir


def get_bot_page(context):
    if context.pages:
        return context.pages[0]
    return context.new_page()


def launch_bot_context(playwright, headless: bool, slow_mo_ms: int):
    profile_dir = get_bot_profile_dir()
    print(f"Using browser profile: {profile_dir}")
    return playwright.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=headless,
        slow_mo=slow_mo_ms,
        args=[
            "--deny-permission-prompts",
            "--disable-notifications",
        ],
    )


def click_bot_target(page, target: str, timeout_ms: int, timeout_error) -> None:
    target = target.strip()
    if not target:
        return

    def split_action_value(action: str, value: str) -> tuple[str, str]:
        if "|" not in value:
            raise ValueError(f"{action} action must be in format {action}=target|value")

        action_target, action_value = value.split("|", 1)
        action_target = action_target.strip()
        action_value = action_value.strip()

        if not action_target or not action_value:
            raise ValueError(f"{action} action must include both target and value")

        return action_target, action_value

    def click_first(locator) -> None:
        locator.first.click(timeout=timeout_ms)

    def click_last(locator) -> None:
        locator.last.click(timeout=timeout_ms)

    def click_visible(locator, reverse: bool = False) -> bool:
        count = min(locator.count(), 50)
        indexes = range(count - 1, -1, -1) if reverse else range(count)

        for index in indexes:
            candidate = locator.nth(index)
            try:
                if candidate.is_visible(timeout=250):
                    candidate.click(timeout=timeout_ms)
                    return True
            except timeout_error:
                continue

        return False

    def click_text(text: str, reverse: bool = False) -> None:
        text = text.strip()
        exact_match = page.get_by_text(text, exact=True)
        partial_match = page.get_by_text(text, exact=False)

        if click_visible(exact_match, reverse=reverse):
            return

        if click_visible(partial_match, reverse=reverse):
            return

        click_first(exact_match)

    def get_locator(spec: str):
        spec = spec.strip()
        if spec == "facebook-composer":
            dialog_editor = page.locator("[role='dialog'] [contenteditable='true']")
            try:
                if dialog_editor.first.is_visible(timeout=500):
                    return dialog_editor
            except timeout_error:
                pass
            return page.locator("[contenteditable='true']")
        if spec.startswith("css="):
            return page.locator(spec[4:].strip())
        if spec.startswith("selector="):
            return page.locator(spec[9:].strip())
        if spec.startswith("xpath="):
            return page.locator(spec)
        if spec.startswith("text="):
            return page.get_by_text(spec[5:].strip(), exact=True)
        if spec.startswith("text-partial="):
            return page.get_by_text(spec[13:].strip(), exact=False)
        if spec.startswith("label="):
            return page.get_by_label(spec[6:].strip(), exact=False)
        if spec.startswith("placeholder="):
            return page.get_by_placeholder(spec[12:].strip(), exact=False)
        if spec.startswith("testid="):
            return page.get_by_test_id(spec[7:].strip())
        if spec.startswith("data-testid="):
            return page.get_by_test_id(spec[12:].strip())
        if spec.startswith("role="):
            role_spec = spec[5:].strip()
            role_name = None
            if ":" in role_spec:
                role_spec, role_name = role_spec.split(":", 1)
                role_name = role_name.strip()
            return page.get_by_role(role_spec.strip(), name=role_name, exact=True)
        return page.locator(spec)

    def fill_target(spec: str, value: str) -> None:
        locator = get_locator(spec)
        locator.first.fill(value, timeout=timeout_ms)

    def type_target(spec: str, value: str) -> None:
        locator = get_locator(spec)
        locator.first.click(timeout=timeout_ms)
        locator.first.type(value, delay=50, timeout=timeout_ms)

    def upload_target(spec: str, file_path: str) -> None:
        normalized_path = os.path.expanduser(file_path)
        if not os.path.isabs(normalized_path):
            normalized_path = os.path.join(BASE_DIR, normalized_path)
        get_locator(spec).first.set_input_files(normalized_path, timeout=timeout_ms)

    def wait_for_target(spec: str) -> None:
        get_locator(spec).first.wait_for(state="visible", timeout=timeout_ms)

    def is_profile_menu_open() -> bool:
        menu_markers = [
            "See all profiles",
            "Select profile",
            "Account Controls and Settings",
        ]

        for marker in menu_markers:
            try:
                if page.get_by_text(marker, exact=False).first.is_visible(timeout=750):
                    return True
            except timeout_error:
                pass

        try:
            return page.locator("[role='dialog'], [role='menu']").first.is_visible(timeout=750)
        except timeout_error:
            return False

    def open_profile_menu() -> None:
        viewport = page.viewport_size or {"width": 1280}
        locator_candidates = [
            page.locator("[aria-label='Account Controls and Settings']"),
            page.locator("[aria-label*='Account' i]"),
            page.locator("[aria-label*='profile' i]"),
        ]

        for locator in locator_candidates:
            try:
                if click_visible(locator, reverse=True):
                    page.wait_for_timeout(750)
                    if is_profile_menu_open():
                        return
            except Exception:
                pass

        coordinate_candidates = [
            (viewport["width"] - 20, 42),
            (viewport["width"] - 40, 28),
            (viewport["width"] - 60, 28),
        ]

        for x, y in coordinate_candidates:
            page.mouse.click(x, y)
            page.wait_for_timeout(750)
            if is_profile_menu_open():
                return

        raise ValueError("Could not open the Facebook profile menu")

    def click_collaborator_icon() -> None:
        candidates = [
            page.get_by_role("button", name="Invite collaborators", exact=False),
            page.get_by_role("button", name="Invite collaborator", exact=False),
            page.locator("[aria-label*='collaborator' i]"),
            page.locator("[aria-label*='collaborators' i]"),
        ]

        for candidate in candidates:
            if click_visible(candidate):
                return

        add_to_post = page.get_by_text("Add to your post", exact=True).first
        box = add_to_post.bounding_box(timeout=timeout_ms)
        if box is None:
            raise ValueError("Could not find the Add to your post row")

        viewport = page.viewport_size or {"width": 1280}
        page.mouse.click(viewport["width"] - 275, box["y"] + (box["height"] / 2))

    def composer_editor_is_visible(timeout: int = 500) -> bool:
        candidates = [
            page.locator("[role='dialog'] [contenteditable='true']"),
            page.locator("[contenteditable='true'][role='textbox']"),
            page.locator("[contenteditable='true']"),
        ]

        for candidate in candidates:
            try:
                if candidate.first.is_visible(timeout=timeout):
                    return True
            except timeout_error:
                pass

        return False

    def wait_for_composer_editor(wait_ms: int = 6000) -> bool:
        deadline = time.monotonic() + (wait_ms / 1000)
        while time.monotonic() < deadline:
            if composer_editor_is_visible(timeout=500):
                return True
            page.wait_for_timeout(500)
        return composer_editor_is_visible(timeout=500)

    def open_facebook_composer() -> None:
        if composer_editor_is_visible():
            return

        trigger_candidates = [
            page.get_by_text("What's on your mind", exact=False),
            page.get_by_text("Create post", exact=True),
            page.get_by_text("Create post", exact=False),
            page.get_by_text("Write something", exact=False),
            page.get_by_role("button", name="Create post", exact=False),
            page.locator("[aria-label*='Create post' i]"),
            page.locator("[aria-label*=\"What's on your mind\" i]"),
            page.locator("[aria-label*='Write something' i]"),
        ]

        for candidate in trigger_candidates:
            if click_visible(candidate):
                if wait_for_composer_editor():
                    return

        page.mouse.wheel(0, -1200)
        page.wait_for_timeout(1000)

        for candidate in trigger_candidates:
            if click_visible(candidate):
                if wait_for_composer_editor():
                    return

        raise ValueError("Could not open the Facebook post composer")

    def text_is_visible(text: str, exact: bool = True, timeout: int = 250) -> bool:
        locator = page.get_by_text(text, exact=exact)
        count = min(locator.count(), 50)

        for index in range(count):
            try:
                if locator.nth(index).is_visible(timeout=timeout):
                    return True
            except timeout_error:
                pass

        return False

    def is_profile_active(profile_name: str) -> bool:
        active_markers = [
            f"What's on your mind, {profile_name}?",
            f"Comment as {profile_name}",
        ]

        for marker in active_markers:
            if text_is_visible(marker, exact=True) or text_is_visible(marker, exact=False):
                return True

        return False

    def wait_for_profile_active(profile_name: str, wait_ms: int = 10000) -> bool:
        deadline = time.monotonic() + (wait_ms / 1000)
        while time.monotonic() < deadline:
            if is_profile_active(profile_name):
                return True
            page.wait_for_timeout(750)
        return is_profile_active(profile_name)

    def switch_profile(profile_name: str, step_wait_ms: int) -> None:
        open_profile_menu()
        page.wait_for_timeout(step_wait_ms)

        if click_if_visible("See all profiles"):
            page.wait_for_timeout(step_wait_ms)

        click_bot_target(page, f"text-last={profile_name}", timeout_ms, timeout_error)
        page.wait_for_timeout(step_wait_ms)

        click_switch_confirmation(profile_name, step_wait_ms)

    def click_if_visible(text: str, reverse: bool = False) -> bool:
        locator = page.get_by_text(text, exact=True)
        return click_visible(locator, reverse=reverse)

    def click_switch_confirmation(profile_name: str, step_wait_ms: int) -> bool:
        text_candidates = [
            f"Switch to {profile_name}",
            f"Switch into {profile_name}",
            f"Continue as {profile_name}",
            f"Use Facebook as {profile_name}",
            "Switch Now",
            "Switch",
            "Continue",
        ]
        for text in text_candidates:
            if click_if_visible(text, reverse=True):
                page.wait_for_timeout(step_wait_ms)
                return True

        locator_candidates = [
            page.locator("[aria-label*='Switch' i]"),
            page.locator("[aria-label*='Continue as' i]"),
            page.locator("[aria-label*='Use Facebook as' i]"),
            page.locator("[aria-label*='Log in as' i]"),
        ]
        for locator in locator_candidates:
            if click_visible(locator, reverse=True):
                page.wait_for_timeout(step_wait_ms)
                return True

        return False

    def switch_profile_prompt_if_present(profile_name: Optional[str] = None) -> None:
        wait_ms = get_env_int("BOT_SWITCH_PROMPT_TIMEOUT_MS", 8000, minimum=0)
        step_wait_ms = get_env_int("BOT_AFTER_CLICK_MS", 1500, minimum=0)
        deadline = time.monotonic() + (wait_ms / 1000)

        while True:
            dialog = page.locator("[role='dialog']").filter(has_text="Switch profiles")
            dialog_candidates = [
                dialog.get_by_role("button", name="Switch", exact=True),
                dialog.get_by_text("Switch", exact=True),
            ]

            for locator in dialog_candidates:
                if click_visible(locator, reverse=True):
                    print("Clicked Facebook Switch profile prompt.")
                    page.wait_for_timeout(step_wait_ms)
                    if profile_name and wait_for_profile_active(profile_name):
                        print(f"Confirmed active profile: {profile_name}")
                    return

            prompt_visible = (
                text_is_visible("Switch profiles", exact=True, timeout=250)
                or text_is_visible("Switch to", exact=False, timeout=250)
            )
            if prompt_visible:
                fallback_candidates = [
                    page.get_by_role("button", name="Switch", exact=True),
                    page.get_by_text("Switch", exact=True),
                ]
                for locator in fallback_candidates:
                    if click_visible(locator, reverse=True):
                        print("Clicked Facebook Switch profile prompt.")
                        page.wait_for_timeout(step_wait_ms)
                        if profile_name and wait_for_profile_active(profile_name):
                            print(f"Confirmed active profile: {profile_name}")
                        return

            if time.monotonic() >= deadline:
                print("No Facebook Switch profile prompt visible.")
                if profile_name and not is_profile_active(profile_name):
                    if switch_from_manage_page(profile_name, step_wait_ms):
                        page.wait_for_timeout(step_wait_ms)
                    if not wait_for_profile_active(profile_name):
                        raise ValueError(f"Could not confirm active Facebook profile is {profile_name}")
                    print(f"Confirmed active profile: {profile_name}")
                return

            page.wait_for_timeout(500)

    def switch_from_manage_page(profile_name: str, step_wait_ms: int) -> bool:
        if not text_is_visible("Manage Page", exact=True):
            return False

        if not text_is_visible(profile_name, exact=True):
            return False

        if click_switch_confirmation(profile_name, step_wait_ms):
            return True

        switch_control_candidates = [
            page.locator("[aria-label*='Switch' i]"),
            page.locator("[aria-label*='profile switcher' i]"),
            page.locator("[aria-label*='Use Facebook as' i]"),
        ]
        for locator in switch_control_candidates:
            if click_visible(locator, reverse=True):
                page.wait_for_timeout(step_wait_ms)
                if click_switch_confirmation(profile_name, step_wait_ms) or is_profile_active(profile_name):
                    return True

        try:
            header_box = page.get_by_text("Manage Page", exact=True).first.bounding_box(timeout=timeout_ms)
        except timeout_error:
            header_box = None

        if header_box is None:
            return False

        # Facebook's Page screen can show a round switcher icon on the Manage Page header.
        y = header_box["y"] + (header_box["height"] / 2)
        for offset_x in (310, 280, 340):
            page.mouse.click(header_box["x"] + offset_x, y)
            page.wait_for_timeout(step_wait_ms)
            if click_switch_confirmation(profile_name, step_wait_ms) or is_profile_active(profile_name):
                return True

        return False

    if target.startswith("ensure-profile="):
        profile_name = target[15:].strip()
        step_wait_ms = get_env_int("BOT_AFTER_CLICK_MS", 1500, minimum=0)

        if is_profile_active(profile_name):
            print(f"Already using profile: {profile_name}")
            return

        switch_profile(profile_name, step_wait_ms)
        if not wait_for_profile_active(profile_name):
            switch_from_manage_page(profile_name, step_wait_ms)
        if not wait_for_profile_active(profile_name):
            raise ValueError(f"Could not confirm active Facebook profile is {profile_name}")

        return

    if target.startswith("require-profile="):
        profile_name = target[16:].strip()
        if not is_profile_active(profile_name):
            raise ValueError(f"Expected active Facebook profile to be {profile_name}, but it was not confirmed")
        print(f"Confirmed active profile: {profile_name}")
        return

    if target.startswith("page-switch="):
        profile_name = target[12:].strip()
        step_wait_ms = get_env_int("BOT_AFTER_CLICK_MS", 1500, minimum=0)
        if is_profile_active(profile_name):
            print(f"Already using profile: {profile_name}")
            return
        if not switch_from_manage_page(profile_name, step_wait_ms) or not wait_for_profile_active(profile_name):
            raise ValueError(f"Could not switch into Facebook Page profile {profile_name}")
        return

    if target.startswith("go="):
        goto_bot_url(page, normalize_bot_url(target[3:]), timeout_ms, timeout_error)
        return

    if target == "switch-profile-if-present" or target.startswith("switch-profile-if-present="):
        profile_name = ""
        if "=" in target:
            _, profile_name = target.split("=", 1)
        switch_profile_prompt_if_present(profile_name.strip() or None)
        return

    if target == "facebook-composer":
        open_facebook_composer()
        return

    if target.startswith("optional="):
        optional_target = target[9:].strip()
        try:
            click_bot_target(page, optional_target, timeout_ms, timeout_error)
        except Exception as exc:
            print(f"Optional step skipped: {optional_target} ({exc})")
        return

    if target == "accept-invite-if-present":
        step_wait_ms = get_env_int("BOT_AFTER_CLICK_MS", 1500, minimum=0)
        if not click_if_visible("Accept", reverse=True):
            print("No visible collaboration invite to accept.")
            return

        page.wait_for_timeout(step_wait_ms)
        if click_if_visible("Accept", reverse=True):
            page.wait_for_timeout(step_wait_ms)

        return

    if target == "collaborator-icon":
        click_collaborator_icon()
        return

    if target.startswith("wait-ms="):
        page.wait_for_timeout(int(target[8:].strip()))
        return

    if target.startswith("wait="):
        wait_for_target(target[5:])
        return

    if target.startswith("fill="):
        fill_target(*split_action_value("fill", target[5:]))
        return

    if target.startswith("type="):
        type_target(*split_action_value("type", target[5:]))
        return

    if target.startswith("press="):
        press_value = target[6:].strip()
        if "|" in press_value:
            press_target, key = split_action_value("press", press_value)
            get_locator(press_target).first.press(key, timeout=timeout_ms)
        else:
            page.keyboard.press(press_value)
        return

    if target.startswith("upload="):
        upload_target(*split_action_value("upload", target[7:]))
        return

    if target.startswith("xy="):
        raw_x, raw_y = target[3:].split(",", 1)
        page.mouse.click(float(raw_x.strip()), float(raw_y.strip()))
        return

    if target.startswith("profile-menu"):
        open_profile_menu()
        return

    if target.startswith("css="):
        click_first(page.locator(target[4:].strip()))
        return

    if target.startswith("css-last="):
        click_last(page.locator(target[9:].strip()))
        return

    if target.startswith("selector="):
        click_first(page.locator(target[9:].strip()))
        return

    if target.startswith("xpath="):
        click_first(page.locator(target))
        return

    if target.startswith("text="):
        click_text(target[5:])
        return

    if target.startswith("text-partial="):
        click_first(page.get_by_text(target[13:].strip(), exact=False))
        return

    if target.startswith("text-last="):
        click_text(target[10:], reverse=True)
        return

    if target.startswith("testid="):
        click_first(page.get_by_test_id(target[7:].strip()))
        return

    if target.startswith("data-testid="):
        click_first(page.get_by_test_id(target[12:].strip()))
        return

    if target.startswith("role="):
        role_spec = target[5:].strip()
        role_name = None
        if ":" in role_spec:
            role_spec, role_name = role_spec.split(":", 1)
            role_name = role_name.strip()
        try:
            click_first(page.get_by_role(role_spec.strip(), name=role_name, exact=True))
        except timeout_error:
            if not role_name:
                raise
            click_text(role_name)
        return

    try:
        click_first(page.get_by_role("button", name=target, exact=True))
    except timeout_error:
        try:
            click_text(target)
        except timeout_error:
            click_first(page.locator(target))


def save_bot_debug_screenshot(page) -> None:
    ensure_db_dir()
    screenshot_path = os.path.join(DB_DIR, "bot-error.png")
    page.screenshot(path=screenshot_path, full_page=True)
    print(f"Saved debug screenshot: {screenshot_path}")


def goto_bot_url(page, url: str, timeout_ms: int, timeout_error) -> None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except timeout_error:
        print("Page load timed out; continuing with the current browser state.")
        page.wait_for_timeout(2000)


def run_browser_bot(
    url: str,
    click_targets: list[str],
    stay_open_override: Optional[bool] = None,
) -> None:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run: pip install -r requirements.txt && "
            "python -m playwright install chromium"
        ) from exc

    normalized_url = normalize_bot_url(url)
    headless = get_env_bool("BOT_HEADLESS", False)
    stay_open = stay_open_override
    if stay_open is None:
        stay_open = get_env_bool("BOT_STAY_OPEN", not headless)
    slow_mo_ms = get_env_int("BOT_SLOW_MO_MS", 250, minimum=0)
    timeout_ms = get_env_int("BOT_TIMEOUT_MS", 15000, minimum=1000)
    after_click_ms = get_env_int("BOT_AFTER_CLICK_MS", 1500, minimum=0)

    with sync_playwright() as playwright:
        context = launch_bot_context(playwright, headless=headless, slow_mo_ms=slow_mo_ms)
        try:
            page = get_bot_page(context)
            page.set_default_timeout(timeout_ms)

            print(f"Opening: {normalized_url}")
            goto_bot_url(page, normalized_url, timeout_ms, PlaywrightTimeoutError)

            for target in click_targets:
                print(f"Clicking: {target}")
                try:
                    click_bot_target(page, target, timeout_ms, PlaywrightTimeoutError)
                except Exception:
                    save_bot_debug_screenshot(page)
                    raise
                page.wait_for_timeout(after_click_ms)

            if stay_open:
                print("Browser is open. Press Enter to close it.")
                try:
                    input()
                except EOFError:
                    page.wait_for_timeout(2000)
        finally:
            context.close()


def run_browser_login(url: Optional[str] = None) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run: pip install -r requirements.txt && "
            "python -m playwright install chromium"
        ) from exc

    login_url = normalize_bot_url(url or os.getenv("BOT_LOGIN_URL", "https://www.facebook.com/"))
    slow_mo_ms = get_env_int("BOT_SLOW_MO_MS", 250, minimum=0)
    timeout_ms = get_env_int("BOT_TIMEOUT_MS", 15000, minimum=1000)

    with sync_playwright() as playwright:
        context = launch_bot_context(playwright, headless=False, slow_mo_ms=slow_mo_ms)
        try:
            page = get_bot_page(context)
            page.set_default_timeout(timeout_ms)

            print(f"Opening login page: {login_url}")
            page.goto(login_url, wait_until="domcontentloaded", timeout=timeout_ms)
            print("Log in manually in the browser. When you are fully logged in, press Enter here.")
            try:
                input()
            except EOFError:
                page.wait_for_timeout(2000)
        finally:
            context.close()


def ensure_db_dir() -> None:
    os.makedirs(DB_DIR, exist_ok=True)


def get_db_connection() -> sqlite3.Connection:
    ensure_db_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            published_at TEXT,
            facebook_post_id TEXT,
            error_message TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_bot_flows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flow_name TEXT NOT NULL,
            bot_url TEXT NOT NULL,
            click_targets_json TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            ran_at TEXT,
            error_message TEXT
        )
    """)

    conn.commit()
    conn.close()


def validate_datetime(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return True
    except ValueError:
        return False


def add_post(message: str, scheduled_at: str) -> None:
    if not validate_datetime(scheduled_at):
        raise ValueError("Date must be in format: YYYY-MM-DD HH:MM:SS")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO scheduled_posts (message, scheduled_at, created_at)
        VALUES (?, ?, ?)
    """, (
        message,
        scheduled_at,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ))

    conn.commit()
    conn.close()


def list_posts() -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, message, scheduled_at, status, published_at, facebook_post_id, error_message
        FROM scheduled_posts
        ORDER BY scheduled_at ASC
    """)

    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("No scheduled posts found.")
        return

    for row in rows:
        print("-" * 80)
        print(f"ID: {row['id']}")
        print(f"Message: {row['message']}")
        print(f"Scheduled At: {row['scheduled_at']}")
        print(f"Status: {row['status']}")
        print(f"Published At: {row['published_at']}")
        print(f"Facebook Post ID: {row['facebook_post_id']}")
        print(f"Error: {row['error_message']}")


def delete_post(post_id: int) -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM scheduled_posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()


def retry_post(post_id: int) -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE scheduled_posts
        SET status = 'pending',
            error_message = NULL
        WHERE id = ?
    """, (post_id,))

    conn.commit()
    conn.close()


def normalize_bot_flow_name(flow_name: str) -> str:
    return flow_name.strip().lower().replace("_", "-")


def get_bot_flow_env_name(flow_name: str) -> str:
    normalized = normalize_bot_flow_name(flow_name)
    if normalized in BOT_FLOW_ENV_NAMES:
        return BOT_FLOW_ENV_NAMES[normalized]

    if normalized.startswith("env:"):
        return normalized[4:].upper()

    allowed = ", ".join(sorted(BOT_FLOW_ENV_NAMES))
    raise ValueError(f"Unknown bot flow '{flow_name}'. Use one of: {allowed}")


def get_bot_flow_url(flow_name: str) -> str:
    normalized = normalize_bot_flow_name(flow_name)

    if normalized.startswith("env:"):
        return get_env("BOT_URL")

    url_env_names = BOT_FLOW_URL_ENV_NAMES.get(normalized)
    if url_env_names is None:
        get_bot_flow_env_name(flow_name)
        url_env_names = ("BOT_URL",)

    for env_name in url_env_names:
        value = get_optional_env(env_name)
        if value:
            return normalize_bot_url(value)

    raise ValueError(f"Missing one of these URL settings in .env: {', '.join(url_env_names)}")


def get_bot_flow_profile_name(flow_name: str) -> Optional[str]:
    normalized = normalize_bot_flow_name(flow_name)
    profile_env_names = BOT_FLOW_PROFILE_ENV_NAMES.get(normalized, ())

    for env_name in profile_env_names:
        value = get_optional_env(env_name)
        if value:
            return value

    return None


def has_configured_bot_flow_url(flow_name: str) -> bool:
    normalized = normalize_bot_flow_name(flow_name)
    url_env_names = BOT_FLOW_URL_ENV_NAMES.get(normalized, ())

    for env_name in url_env_names:
        if env_name == "BOT_URL":
            continue
        if get_optional_env(env_name):
            return True

    return False


def get_bot_flow_targets(flow_name: str) -> list[str]:
    env_name = get_bot_flow_env_name(flow_name)
    return parse_bot_buttons(get_env(env_name))


def is_profile_navigation_target(target: str) -> bool:
    normalized = target.strip()
    if normalized.startswith(("ensure-profile=", "require-profile=", "page-switch=")):
        return True

    if not normalized.startswith("go="):
        return False

    try:
        parsed = urlparse(normalize_bot_url(normalized[3:]))
    except ValueError:
        return False

    return parsed.netloc in {"facebook.com", "www.facebook.com"} and parsed.path in {"", "/"} and not parsed.query


def without_profile_navigation_targets(click_targets: list[str]) -> list[str]:
    return [target for target in click_targets if not is_profile_navigation_target(target)]


def is_switch_prompt_target(target: str) -> bool:
    normalized = target.strip()
    return normalized == BOT_OLD_SWITCH_PROMPT_TARGET or normalized.startswith(BOT_SWITCH_PROMPT_TARGET)


def is_old_facebook_composer_trigger(target: str) -> bool:
    normalized = target.strip().lower()
    return normalized.startswith(("text=", "text-partial=")) and "what's on your mind" in normalized


def with_facebook_composer_target(click_targets: list[str]) -> list[str]:
    if any(target.strip() == "facebook-composer" for target in click_targets):
        return click_targets

    updated_targets = []
    inserted = False

    for target in click_targets:
        if is_old_facebook_composer_trigger(target):
            if not inserted:
                updated_targets.append("facebook-composer")
                inserted = True
            continue
        updated_targets.append(target)

    return updated_targets


def get_switch_prompt_target(profile_name: Optional[str] = None) -> str:
    if profile_name:
        return f"{BOT_SWITCH_PROMPT_TARGET}={profile_name}"

    return BOT_SWITCH_PROMPT_TARGET


def with_optional_switch_prompt(click_targets: list[str], profile_name: Optional[str] = None) -> list[str]:
    return [
        get_switch_prompt_target(profile_name),
        *[target for target in click_targets if not is_switch_prompt_target(target)],
    ]


def prepare_scheduled_bot_flow(bot_flow: sqlite3.Row) -> tuple[str, list[str]]:
    flow_name = bot_flow["flow_name"]
    click_targets = json.loads(bot_flow["click_targets_json"])

    if normalize_bot_flow_name(flow_name) in BOT_FACEBOOK_PAGE_FLOWS and has_configured_bot_flow_url(flow_name):
        click_targets = without_profile_navigation_targets(click_targets)
        if normalize_bot_flow_name(flow_name) == "send-invite":
            click_targets = with_facebook_composer_target(click_targets)
        return get_bot_flow_url(flow_name), with_optional_switch_prompt(click_targets, get_bot_flow_profile_name(flow_name))

    return bot_flow["bot_url"], click_targets


def with_scheduled_post_text(click_targets: list[str], message: str) -> list[str]:
    updated_targets = []
    replaced = False

    for target in click_targets:
        if not replaced and target.startswith("type=") and "|" in target:
            target_spec, _ = target.split("|", 1)
            updated_targets.append(f"{target_spec}|{message}")
            replaced = True
        else:
            updated_targets.append(target)

    if not replaced:
        raise ValueError("Could not find a type= step to replace with the scheduled post text")

    return updated_targets


def add_bot_flow(flow_name: str, scheduled_at: str, click_targets: list[str]) -> None:
    if not validate_datetime(scheduled_at):
        raise ValueError("Date must be in format: YYYY-MM-DD HH:MM:SS")

    bot_url = get_bot_flow_url(flow_name)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO scheduled_bot_flows (flow_name, bot_url, click_targets_json, scheduled_at, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        flow_name,
        bot_url,
        json.dumps(click_targets, ensure_ascii=False),
        scheduled_at,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ))

    conn.commit()
    conn.close()


def add_scheduled_send_invite(message: str, scheduled_at: str) -> None:
    click_targets = with_scheduled_post_text(get_bot_flow_targets("send-invite"), message)
    add_bot_flow("send-invite", scheduled_at, click_targets)


def get_bot_flow(flow_id: int) -> Optional[sqlite3.Row]:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM scheduled_bot_flows WHERE id = ?", (flow_id,))
    row = cur.fetchone()
    conn.close()
    return row


def replace_bot_flow(flow_id: int, flow_name: str, scheduled_at: str, click_targets: list[str]) -> None:
    if not validate_datetime(scheduled_at):
        raise ValueError("Date must be in format: YYYY-MM-DD HH:MM:SS")

    bot_url = get_bot_flow_url(flow_name)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE scheduled_bot_flows
        SET flow_name = ?,
            bot_url = ?,
            click_targets_json = ?,
            scheduled_at = ?,
            status = 'pending',
            ran_at = NULL,
            error_message = NULL
        WHERE id = ?
    """, (
        flow_name,
        bot_url,
        json.dumps(click_targets, ensure_ascii=False),
        scheduled_at,
        flow_id,
    ))

    conn.commit()
    conn.close()


def rebuild_send_invite_flow(flow_id: int, scheduled_at: str) -> None:
    row = get_bot_flow(flow_id)
    if row is None:
        raise ValueError(f"Bot flow ID {flow_id} was not found")

    old_targets = json.loads(row["click_targets_json"])
    message = ""
    for target in old_targets:
        if target.startswith("type=") and "contenteditable" in target and "|" in target:
            message = target.split("|", 1)[1]
            break

    if not message:
        raise ValueError("Could not find the original scheduled post text")

    click_targets = with_scheduled_post_text(get_bot_flow_targets("send-invite"), message)
    replace_bot_flow(flow_id, "send-invite", scheduled_at, click_targets)


def list_bot_flows() -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, flow_name, bot_url, click_targets_json, scheduled_at, status, ran_at, error_message
        FROM scheduled_bot_flows
        ORDER BY scheduled_at ASC
    """)

    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("No scheduled bot flows found.")
        return

    for row in rows:
        print("-" * 80)
        print(f"ID: {row['id']}")
        print(f"Flow: {row['flow_name']}")
        try:
            effective_url, _ = prepare_scheduled_bot_flow(row)
        except Exception:
            effective_url = row["bot_url"]
        print(f"URL: {effective_url}")
        if effective_url != row["bot_url"]:
            print(f"Saved URL: {row['bot_url']}")
        print(f"Scheduled At: {row['scheduled_at']}")
        print(f"Status: {row['status']}")
        print(f"Ran At: {row['ran_at']}")
        print(f"Error: {row['error_message']}")


def delete_bot_flow(flow_id: int) -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM scheduled_bot_flows WHERE id = ?", (flow_id,))
    conn.commit()
    conn.close()


def retry_bot_flow(flow_id: int) -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE scheduled_bot_flows
        SET status = 'pending',
            ran_at = NULL,
            error_message = NULL
        WHERE id = ?
    """, (flow_id,))

    conn.commit()
    conn.close()


def clear_bot_flows() -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM scheduled_bot_flows")
    conn.commit()
    conn.close()


def get_due_posts() -> list[sqlite3.Row]:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM scheduled_posts
        WHERE status = 'pending'
          AND scheduled_at <= ?
        ORDER BY scheduled_at ASC
    """, (now_str,))

    rows = cur.fetchall()
    conn.close()
    return rows


def mark_post_success(post_id: int, facebook_post_id: Optional[str]) -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE scheduled_posts
        SET status = 'published',
            published_at = ?,
            facebook_post_id = ?,
            error_message = NULL
        WHERE id = ?
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        facebook_post_id,
        post_id,
    ))

    conn.commit()
    conn.close()


def mark_post_failed(post_id: int, error_message: str) -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE scheduled_posts
        SET status = 'failed',
            error_message = ?
        WHERE id = ?
    """, (error_message[:2000], post_id))

    conn.commit()
    conn.close()


def get_due_bot_flows() -> list[sqlite3.Row]:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM scheduled_bot_flows
        WHERE status = 'pending'
          AND scheduled_at <= ?
        ORDER BY scheduled_at ASC
    """, (now_str,))

    rows = cur.fetchall()
    conn.close()
    return rows


def mark_bot_flow_success(flow_id: int) -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE scheduled_bot_flows
        SET status = 'completed',
            ran_at = ?,
            error_message = NULL
        WHERE id = ?
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        flow_id,
    ))

    conn.commit()
    conn.close()


def mark_bot_flow_failed(flow_id: int, error_message: str) -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE scheduled_bot_flows
        SET status = 'failed',
            ran_at = ?,
            error_message = ?
        WHERE id = ?
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        error_message[:2000],
        flow_id,
    ))

    conn.commit()
    conn.close()


def publish_to_facebook(message: str) -> tuple[bool, str]:
    page_id = get_env("PAGE_ID")
    page_access_token = get_env("PAGE_ACCESS_TOKEN")
    graph_api_version = get_env("GRAPH_API_VERSION", "v25.0")
    validate_facebook_config(page_access_token)

    url = f"https://graph.facebook.com/{graph_api_version}/{page_id}/feed"

    payload = {
        "message": message,
        "access_token": page_access_token,
    }

    try:
        response = requests.post(url, data=payload, timeout=30)
        response.raise_for_status()

        data = response.json()

        if "id" in data:
            return True, data["id"]

        return False, f"Unexpected response: {json.dumps(data, ensure_ascii=False)}"

    except requests.HTTPError:
        try:
            error_data = response.json()
            return False, f"Facebook API error: {json.dumps(error_data, ensure_ascii=False)}"
        except Exception:
            return False, f"HTTP error: {response.text}"

    except requests.RequestException as e:
        return False, f"Request failed: {str(e)}"


def run_scheduler() -> None:
    interval = int(get_env("CHECK_INTERVAL_SECONDS", "30"))

    print("Scheduler running...")
    print(f"Checking every {interval} seconds")

    while True:
        due_posts = get_due_posts()
        due_bot_flows = get_due_bot_flows()

        if due_posts:
            print(f"Found {len(due_posts)} due post(s)")

        if due_bot_flows:
            print(f"Found {len(due_bot_flows)} due bot flow(s)")

        for post in due_posts:
            print(f"Publishing post ID {post['id']}...")

            success, result = publish_to_facebook(post["message"])

            if success:
                mark_post_success(post["id"], result)
                print(f"Published successfully: {result}")
            else:
                mark_post_failed(post["id"], result)
                print(f"Failed: {result}")

        for bot_flow in due_bot_flows:
            print(f"Running bot flow ID {bot_flow['id']} ({bot_flow['flow_name']})...")

            try:
                bot_url, click_targets = prepare_scheduled_bot_flow(bot_flow)
                run_browser_bot(bot_url, click_targets, stay_open_override=False)
                mark_bot_flow_success(bot_flow["id"])
                print("Bot flow completed successfully.")
            except Exception as exc:
                mark_bot_flow_failed(bot_flow["id"], str(exc))
                print(f"Bot flow failed: {exc}")

        time.sleep(interval)


def run_env_bot_flow(flow_name: str) -> None:
    bot_url = get_bot_flow_url(flow_name)
    click_targets = get_bot_flow_targets(flow_name)
    if normalize_bot_flow_name(flow_name) in BOT_FACEBOOK_PAGE_FLOWS and has_configured_bot_flow_url(flow_name):
        click_targets = with_optional_switch_prompt(click_targets, get_bot_flow_profile_name(flow_name))
    run_browser_bot(bot_url, click_targets)


def print_help() -> None:
    print("""
Commands:
  python app.py init
  python app.py add "Your message here" "2026-04-14 18:30:00"
  python app.py list
  python app.py delete 1
  python app.py retry 1
  python app.py run
  python app.py schedule-send-invite "Your message here" "2026-04-14 18:30:00"
  python app.py schedule-bot-flow send-invite "2026-04-14 18:30:00"
  python app.py schedule-accept-invite "2026-04-14 18:30:00"
  python app.py list-bot-flows
  python app.py delete-bot-flow 1
  python app.py retry-bot-flow 1
  python app.py clear-bot-flows
  python app.py rebuild-send-invite 1 "2026-04-14 18:30:00"
  python app.py bot-login
  python app.py bot-send-invite
  python app.py bot-accept-invite
  python app.py bot "https://example.com" "Accept all" "css=button.submit"
""")


def main() -> None:
    load_env_file()
    init_db()

    if len(sys.argv) < 2:
        print_help()
        sys.exit(1)

    command = sys.argv[1].lower()

    try:
        if command == "init":
            print("Database initialized.")

        elif command == "add":
            if len(sys.argv) < 4:
                print('Example: python app.py add "My post text" "2026-04-14 18:30:00"')
                sys.exit(1)

            message = sys.argv[2]
            scheduled_at = sys.argv[3]
            add_post(message, scheduled_at)
            print("Post added.")

        elif command == "list":
            list_posts()

        elif command == "delete":
            if len(sys.argv) < 3:
                print("Example: python app.py delete 1")
                sys.exit(1)

            delete_post(int(sys.argv[2]))
            print("Post deleted.")

        elif command == "retry":
            if len(sys.argv) < 3:
                print("Example: python app.py retry 1")
                sys.exit(1)

            retry_post(int(sys.argv[2]))
            print("Post marked for retry.")

        elif command == "schedule-send-invite":
            if len(sys.argv) < 4:
                print('Example: python app.py schedule-send-invite "Hello collaborator" "2026-04-14 18:30:00"')
                sys.exit(1)

            message = sys.argv[2]
            scheduled_at = sys.argv[3]
            add_scheduled_send_invite(message, scheduled_at)
            print("Scheduled collaboration invite post.")

        elif command == "schedule-bot-flow":
            if len(sys.argv) < 4:
                print('Example: python app.py schedule-bot-flow send-invite "2026-04-14 18:30:00"')
                sys.exit(1)

            flow_name = sys.argv[2]
            scheduled_at = sys.argv[3]
            add_bot_flow(flow_name, scheduled_at, get_bot_flow_targets(flow_name))
            print("Scheduled bot flow.")

        elif command == "schedule-accept-invite":
            if len(sys.argv) < 3:
                print('Example: python app.py schedule-accept-invite "2026-04-14 18:30:00"')
                sys.exit(1)

            add_bot_flow("accept-invite", sys.argv[2], get_bot_flow_targets("accept-invite"))
            print("Scheduled invite acceptance.")

        elif command == "list-bot-flows":
            list_bot_flows()

        elif command == "delete-bot-flow":
            if len(sys.argv) < 3:
                print("Example: python app.py delete-bot-flow 1")
                sys.exit(1)

            delete_bot_flow(int(sys.argv[2]))
            print("Bot flow deleted.")

        elif command == "retry-bot-flow":
            if len(sys.argv) < 3:
                print("Example: python app.py retry-bot-flow 1")
                sys.exit(1)

            retry_bot_flow(int(sys.argv[2]))
            print("Bot flow marked for retry.")

        elif command == "clear-bot-flows":
            clear_bot_flows()
            print("All scheduled bot flows deleted.")

        elif command == "rebuild-send-invite":
            if len(sys.argv) < 4:
                print('Example: python app.py rebuild-send-invite 1 "2026-04-14 18:30:00"')
                sys.exit(1)

            rebuild_send_invite_flow(int(sys.argv[2]), sys.argv[3])
            print("Send-invite bot flow rebuilt from current .env.")

        elif command == "run":
            run_scheduler()

        elif command == "bot-login":
            login_url = sys.argv[2] if len(sys.argv) >= 3 else None
            run_browser_login(login_url)

        elif command == "bot-send-invite":
            run_env_bot_flow("send-invite")

        elif command == "bot-accept-invite":
            run_env_bot_flow("accept-invite")

        elif command == "bot":
            bot_url = sys.argv[2] if len(sys.argv) >= 3 else get_env("BOT_URL")
            click_targets = sys.argv[3:] if len(sys.argv) >= 4 else parse_bot_buttons(os.getenv("BOT_BUTTONS", ""))
            run_browser_bot(bot_url, click_targets)

        else:
            print_help()
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
