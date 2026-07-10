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

# エラーロガーの初期化
reminder_logger = logging.getLogger("reminder")
reminder_logger.setLevel(logging.INFO)
reminder_logger.propagate = False
reminder_logger.addHandler(logging.NullHandler())

# リマインダーの状態
STATUS_LABELS = {
    "pending": "待機中",
    "notified": "通知済み",
    "done": "完了",
    "canceled": "取消",
}

# 入力エラーのバリデーション
class ReminderValidationError(ValueError):
    pass


#
# ヘルパー関数
#

# 現在時刻を取得する関数
def _now() -> datetime:
    return datetime.now().astimezone()


# ローカル環境のタイムゾーンを取得する関数
def _local_timezone():
    return _now().tzinfo


# 日時文字列を画面表示用の形式に変換する関数
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


# 余分な空白や改行を削除する関数
def _clean_log_text(value: str) -> str:
    return " ".join(value.split())


# リマインダーを画面表示用のデータに変換する関数
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



#
# リマインダーの保存、状態更新、通知時刻の監視するクラス
#
class ReminderService:
    def __init__(self, notify_callback):
        self._notify_callback = notify_callback # 通知時に実行される
        self._check_interval_seconds = 1 # 時刻を監視する間隔(s)
        self._lock = Lock() # 1つのリマインダーを同時に変更しないためのロック
        self._stop_event = Event() # 監視スレッドを止める
        self._thread: Thread | None = None # 通知時刻を監視するスレッド
        self._reminders = self._load_reminders() # 保存済みリマインダー一覧


    # 通知時刻を監視するスレッドを開始
    def start(self) -> None:
        """通知時刻を監視するスレッドを開始する。"""

        if self._thread and self._thread.is_alive():
            return

        self._thread = Thread(
            target=self._run_scheduler,
            daemon=True,
        )
        self._thread.start()


    # リマインダー一覧を取得
    def list_reminders(self):
        with self._lock:
            return [_serialize(reminder) for reminder in self._reminders]


    # リマインダーを作成
    def create_reminder(self, todo, remind_at_text):
        normalized_todo = " ".join(todo.split())

        if not normalized_todo:
            raise ReminderValidationError(
                "入力してください"
            )

        if len(normalized_todo) > 120:
            raise ReminderValidationError(
                "120文字以内で入力してください。"
            )

        remind_at = self._parse_remind_at(remind_at_text)
        created_at = _now().isoformat(timespec="seconds")

        # リマインダー本体を生成
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


    # リマインダーの状態を更新
    def update_status(self, reminder_id, status):
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
    
    
    # 入力された日時をPythonで扱える日時データに変換
    def _parse_remind_at(self, value: str) -> datetime:
        text = value.strip()

        if not text:
            raise ReminderValidationError(
                "入力してください"
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


    #
    # 時刻の監視
    #
    # 通知時刻を定期的に確認
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


    # 通知時刻を過ぎたリマインダーを通知済みに変更
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


    #
    # データの永続化
    #
    # 保存済みのリマインダーをJSONファイルから読み込む
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


    # リマインダー一覧をJSONファイルへ保存
    def _save_locked(self) -> None:
        DATA_DIR.mkdir(exist_ok=True)

        with DATA_FILE.open("w", encoding="utf-8") as file:
            json.dump(
                self._reminders,
                file,
                ensure_ascii=False,
                indent=2,
            )


    # 指定されたIDのリマインダーを探す
    def _find_locked(
        self,
        reminder_id: str,
    ) -> dict[str, str] | None:
        for reminder in self._reminders:
            if reminder.get("id") == reminder_id:
                return reminder

        return None
