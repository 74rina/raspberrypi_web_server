from __future__ import annotations
from flask import Flask, jsonify, render_template, request
from hardware import notify_reminder
from reminders import ReminderService, ReminderValidationError


app = Flask(__name__)

reminder_service = ReminderService(
    notify_callback=notify_reminder,
)
reminder_service.start()


# 画面本体の表示
@app.get("/")
def index():
    return render_template("index.html")


# リマインダー一覧を取得するAPI
@app.get("/api/reminders")
def get_reminders():
    return jsonify(reminder_service.list_reminders())


# リマインダーを登録するAPI
@app.post("/api/reminders")
def create_reminder():
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


# リマインダーを「完了」の状態にするAPI
@app.post("/api/reminders/<reminder_id>/complete")
def complete_reminder(reminder_id):
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

# リマインダーを取り消すAPI
@app.post("/api/reminders/<reminder_id>/cancel")
def cancel_reminder(reminder_id):
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


# LED点灯テスト用API
@app.post("/api/test-led")
def test_led():
    notify_reminder()

    return jsonify(
        {
            "message": "LEDテストを実行しました。",
        }
    )


# 404エラー
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
