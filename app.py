from __future__ import annotations

from flask import Flask, jsonify, render_template, request

from hardware import notify_reminder
from reminders import ReminderService, ReminderValidationError


app = Flask(__name__)

reminder_service = ReminderService(
    notify_callback=notify_reminder,
)
reminder_service.start()


@app.get("/")
def index():
    """リマインダー画面を表示する。"""

    return render_template("index.html")


@app.get("/api/reminders")
def get_reminders():
    """登録されたリマインダー一覧を返す。"""

    return jsonify(reminder_service.list_reminders())


@app.post("/api/reminders")
def create_reminder():
    """やることと通知日時を受け取り、リマインダーを登録する。"""

    data = request.get_json(silent=True) or request.form

    try:
        reminder = reminder_service.create_reminder(
            todo=data.get("todo", ""),
            remind_at_text=data.get("remind_at", ""),
        )
    except ReminderValidationError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(
        {
            "message": "リマインダーを登録しました。",
            "reminder": reminder,
        }
    ), 201


@app.post("/api/reminders/<reminder_id>/complete")
def complete_reminder(reminder_id: str):
    """リマインダーを完了にする。"""

    reminder = reminder_service.update_status(
        reminder_id=reminder_id,
        status="done",
    )

    if reminder is None:
        return jsonify({"error": "リマインダーが見つかりません。"}), 404

    return jsonify(
        {
            "message": "リマインダーを完了にしました。",
            "reminder": reminder,
        }
    )


@app.post("/api/reminders/<reminder_id>/cancel")
def cancel_reminder(reminder_id: str):
    """リマインダーを取り消す。"""

    reminder = reminder_service.update_status(
        reminder_id=reminder_id,
        status="canceled",
    )

    if reminder is None:
        return jsonify({"error": "リマインダーが見つかりません。"}), 404

    return jsonify(
        {
            "message": "リマインダーを取り消しました。",
            "reminder": reminder,
        }
    )


@app.post("/api/test-led")
def test_led():
    """LEDだけをすぐに光らせる。"""

    notify_reminder()

    return jsonify(
        {
            "message": "LEDテストを実行しました。",
        }
    )


@app.errorhandler(404)
def not_found(_error):
    return jsonify(
        {
            "error": "ページが見つかりません。",
            "path": request.path,
        }
    ), 404


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        threaded=True,
    )
