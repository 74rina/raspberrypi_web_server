from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Callable
from uuid import uuid4


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DATA_FILE = DATA_DIR / "reminders.json"
LOG_FILE = LOG_DIR / "reminder.log"

CHECK_INTERVAL_SECONDS = 1

STATUS_LABELS = {
    "pending": "待機中",
    "notified": "通知済み",
    "done": "完了",
    "canceled": "取消",
}


class ReminderValidationError(ValueError):
    """リマインダー入力に問題がある場合のエラー。"""


reminder_logger = logging.getLogger("reminder")
reminder_logger.setLevel(logging.INFO)
reminder_logger.propagate = False

if not reminder_logger.handlers:
    LOG_DIR.mkdir(exist_ok=True)

    file_handler = logging.FileHandler(
        LOG_FILE,
        encoding="utf-8",
    )

    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s"
        )
    )

    reminder_logger.addHandler(file_handler)


def _now() -> datetime:
    return datetime.now().astimezone()


def _local_timezone():
    return _now().tzinfo


def _format_datetime(value: str | None) -> str:
    if not value:
        return "-"

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value

    return parsed.astimezone(_local_timezone()).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _clean_log_text(value: str) -> str:
    return " ".join(value.split())


def _serialize(reminder: dict[str, str]) -> dict[str, str]:
    serialized = dict(reminder)
    serialized["status_label"] = STATUS_LABELS.get(
        reminder["status"],
        reminder["status"],
    )
    serialized["remind_at_display"] = _format_datetime(
        reminder.get("remind_at")
    )
    serialized["created_at_display"] = _format_datetime(
        reminder.get("created_at")
    )
    serialized["notified_at_display"] = _format_datetime(
        reminder.get("notified_at")
    )

    return serialized


def _sort_key(reminder: dict[str, str]):
    status_order = {
        "pending": 0,
        "notified": 1,
        "done": 2,
        "canceled": 3,
    }

    remind_at = reminder.get("remind_at", "")

    if reminder.get("status") == "pending":
        return (
            status_order["pending"],
            remind_at,
        )

    return (
        status_order.get(reminder.get("status", ""), 9),
        reminder.get("notified_at")
        or reminder.get("updated_at")
        or reminder.get("created_at", ""),
    )


class ReminderService:
    """リマインダーの保存、状態更新、通知時刻の監視を担当する。"""

    def __init__(
        self,
        *,
        notify_callback: Callable[[], None],
        check_interval_seconds: int = CHECK_INTERVAL_SECONDS,
    ) -> None:
        self._notify_callback = notify_callback
        self._check_interval_seconds = check_interval_seconds
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._reminders = self._load_reminders()

    def start(self) -> None:
        """通知時刻を監視するスレッドを開始する。"""

        if self._thread and self._thread.is_alive():
            return

        self._thread = Thread(
            target=self._run_scheduler,
            daemon=True,
        )
        self._thread.start()

    def list_reminders(self) -> list[dict[str, str]]:
        """画面表示用にリマインダー一覧を返す。"""

        with self._lock:
            reminders = sorted(
                self._reminders,
                key=_sort_key,
            )

            return [_serialize(reminder) for reminder in reminders]

    def create_reminder(
        self,
        *,
        todo: str,
        remind_at_text: str,
    ) -> dict[str, str]:
        """入力された内容からリマインダーを作成する。"""

        normalized_todo = " ".join(todo.split())

        if not normalized_todo:
            raise ReminderValidationError(
                "やることを入力するニャン😸"
            )

        if len(normalized_todo) > 120:
            raise ReminderValidationError(
                "120文字以内で入力してください。"
            )

        remind_at = self._parse_remind_at(remind_at_text)
        created_at = _now().isoformat(timespec="seconds")

        reminder = {
            "id": uuid4().hex,
            "todo": normalized_todo,
            "remind_at": remind_at.isoformat(timespec="seconds"),
            "created_at": created_at,
            "updated_at": created_at,
            "notified_at": "",
            "status": "pending",
        }

        with self._lock:
            self._reminders.append(reminder)
            self._save_locked()

        reminder_logger.info(
            "created | id=%s | remind_at=%s | todo=%s",
            reminder["id"],
            reminder["remind_at"],
            _clean_log_text(reminder["todo"]),
        )

        return _serialize(reminder)

    def update_status(
        self,
        *,
        reminder_id: str,
        status: str,
    ) -> dict[str, str] | None:
        """リマインダーの状態を更新する。"""

        if status not in {"done", "canceled"}:
            raise ValueError(f"invalid status: {status}")

        updated_at = _now().isoformat(timespec="seconds")

        with self._lock:
            reminder = self._find_locked(reminder_id)

            if reminder is None:
                return None

            reminder["status"] = status
            reminder["updated_at"] = updated_at
            self._save_locked()
            serialized = _serialize(reminder)

        reminder_logger.info(
            "%s | id=%s | todo=%s",
            status,
            reminder_id,
            _clean_log_text(serialized["todo"]),
        )

        return serialized

    def _run_scheduler(self) -> None:
        while not self._stop_event.wait(self._check_interval_seconds):
            due_reminders = self._mark_due_reminders()

            for reminder in due_reminders:
                reminder_logger.warning(
                    "notified | id=%s | remind_at=%s | todo=%s",
                    reminder["id"],
                    reminder["remind_at"],
                    _clean_log_text(reminder["todo"]),
                )
                self._notify_callback()

    def _mark_due_reminders(self) -> list[dict[str, str]]:
        now = _now()
        notified_at = now.isoformat(timespec="seconds")
        due_reminders: list[dict[str, str]] = []

        with self._lock:
            for reminder in self._reminders:
                if reminder.get("status") != "pending":
                    continue

                remind_at = datetime.fromisoformat(
                    reminder["remind_at"]
                )

                if remind_at <= now:
                    reminder["status"] = "notified"
                    reminder["notified_at"] = notified_at
                    reminder["updated_at"] = notified_at
                    due_reminders.append(dict(reminder))

            if due_reminders:
                self._save_locked()

        return due_reminders

    def _parse_remind_at(self, value: str) -> datetime:
        text = value.strip()

        if not text:
            raise ReminderValidationError(
                "何時に知らせてほしい？😻"
            )

        try:
            remind_at = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ReminderValidationError(
                "日時の形式が正しくありません。"
            ) from exc

        if remind_at.tzinfo is None:
            remind_at = remind_at.replace(tzinfo=_local_timezone())
        else:
            remind_at = remind_at.astimezone(_local_timezone())

        return remind_at

    def _load_reminders(self) -> list[dict[str, str]]:
        DATA_DIR.mkdir(exist_ok=True)

        if not DATA_FILE.exists():
            return []

        try:
            with DATA_FILE.open("r", encoding="utf-8") as file:
                reminders = json.load(file)
        except (OSError, json.JSONDecodeError):
            reminder_logger.exception(
                "failed to load reminders from %s",
                DATA_FILE,
            )
            return []

        if not isinstance(reminders, list):
            return []

        return [
            reminder
            for reminder in reminders
            if isinstance(reminder, dict)
        ]

    def _save_locked(self) -> None:
        DATA_DIR.mkdir(exist_ok=True)

        with DATA_FILE.open("w", encoding="utf-8") as file:
            json.dump(
                self._reminders,
                file,
                ensure_ascii=False,
                indent=2,
            )

    def _find_locked(
        self,
        reminder_id: str,
    ) -> dict[str, str] | None:
        for reminder in self._reminders:
            if reminder.get("id") == reminder_id:
                return reminder

        return None
