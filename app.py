from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
import logging
from pathlib import Path
from threading import Lock
from time import monotonic
from urllib.parse import unquote

from flask import Flask, g, jsonify, render_template, request

from hardware import notify_attack


app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)


# -------------------------
# 設定
# -------------------------

# 何秒間のアクセス回数を見るか
RATE_LIMIT_WINDOW_SECONDS = 5

# 上の時間内に何回アクセスされたら警告するか
RATE_LIMIT_REQUESTS = 10

# 不審とみなす文字列
SUSPICIOUS_PATTERNS = {
    "/admin": "管理画面を探すアクセス",
    "/wp-login.php": "WordPressのログイン画面を探すアクセス",
    "../": "ディレクトリトラバーサルらしき文字列",
    "<script": "スクリプトを埋め込もうとする文字列",
    "union select": "SQLインジェクションらしき文字列",
}

# 検知対象から外すURL
EXCLUDED_PATHS = {
    "/api/events",
    "/favicon.ico",
}


# -------------------------
# ロガー
# -------------------------

security_logger = logging.getLogger("security")
security_logger.setLevel(logging.INFO)
security_logger.propagate = False

if not security_logger.handlers:
    file_handler = logging.FileHandler(
        LOG_DIR / "security.log",
        encoding="utf-8",
    )

    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s"
        )
    )

    security_logger.addHandler(file_handler)


# -------------------------
# サーバ内で保持するデータ
# -------------------------

# IPアドレスごとの最近のアクセス時刻
access_history: dict[str, deque[float]] = defaultdict(deque)
access_history_lock = Lock()

# Web画面に表示する直近100件
events: deque[dict[str, str]] = deque(maxlen=100)
events_lock = Lock()


# -------------------------
# 検知処理
# -------------------------

def is_too_many_requests(ip_address: str) -> bool:
    """
    同じIPアドレスから、短時間に大量のアクセスがあったか調べる。
    """

    now = monotonic()

    with access_history_lock:
        history = access_history[ip_address]

        # 監視時間より古いアクセスを削除
        while (
            history
            and now - history[0] > RATE_LIMIT_WINDOW_SECONDS
        ):
            history.popleft()

        history.append(now)

        return len(history) >= RATE_LIMIT_REQUESTS


def detect_suspicious_request() -> list[str]:
    """
    現在のHTTPリクエストを検査し、
    不審と判断した理由の一覧を返す。
    """

    reasons: list[str] = []

    ip_address = request.remote_addr or "unknown"

    # パーセントエンコードされた文字列も調べられるようにデコードする
    request_target = unquote(request.full_path).lower()

    # 課題の実演用URL
    if request.path == "/attack":
        reasons.append("攻撃テスト用URLへのアクセス")

    # URLやクエリ文字列に不審な文字列がないか確認
    for pattern, description in SUSPICIOUS_PATTERNS.items():
        if pattern in request_target:
            reasons.append(description)

    # 短時間の大量アクセスを確認
    if is_too_many_requests(ip_address):
        reasons.append(
            f"{RATE_LIMIT_WINDOW_SECONDS}秒以内に"
            f"{RATE_LIMIT_REQUESTS}回以上のアクセス"
        )

    # 同じ理由が重複した場合に取り除く
    return list(dict.fromkeys(reasons))


def record_event(
    *,
    ip_address: str,
    target: str,
    method: str,
    status: str,
    reasons: list[str],
) -> None:
    """アクセス履歴をメモリとファイルへ保存する。"""

    reason_text = "、".join(reasons) if reasons else "-"

    event = {
        "time": datetime.now().astimezone().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "ip": ip_address,
        "method": method,
        "target": target,
        "status": status,
        "reason": reason_text,
    }

    with events_lock:
        # appendleftで新しいイベントを先頭に置く
        events.appendleft(event)

    log_level = (
        logging.WARNING
        if status == "ALERT"
        else logging.INFO
    )

    security_logger.log(
        log_level,
        "ip=%s | method=%s | target=%s | status=%s | reason=%s",
        ip_address,
        method,
        target,
        status,
        reason_text,
    )


# -------------------------
# 全リクエストの事前処理
# -------------------------

@app.before_request
def inspect_request() -> None:
    """
    各URLの処理が実行される前にアクセスを検査する。
    """

    # CSSやログ取得APIを数えると、
    # Web画面自身の通信で大量アクセス判定されるため除外する
    if (
        request.path.startswith("/static/")
        or request.path in EXCLUDED_PATHS
    ):
        return

    reasons = detect_suspicious_request()
    g.detection_reasons = reasons

    status = "ALERT" if reasons else "NORMAL"
    ip_address = request.remote_addr or "unknown"
    target = request.full_path.rstrip("?")

    record_event(
        ip_address=ip_address,
        target=target,
        method=request.method,
        status=status,
        reasons=reasons,
    )

    if reasons:
        notify_attack()


# -------------------------
# URL
# -------------------------

@app.get("/")
def index():
    """監視画面を表示する。"""

    return render_template(
        "index.html",
        rate_limit_requests=RATE_LIMIT_REQUESTS,
        rate_limit_window=RATE_LIMIT_WINDOW_SECONDS,
    )


@app.get("/attack")
def attack():
    """
    攻撃検知の実演用URL。

    before_requestで攻撃として検知され、
    LEDが点滅する。
    """

    return jsonify(
        {
            "detected": True,
            "message": "攻撃テストを検知しました。",
            "reasons": g.detection_reasons,
        }
    )


@app.get("/probe")
def probe():
    """
    大量アクセス検知を実演するための通常URL。
    Web画面から短時間に複数回呼び出す。
    """

    return jsonify(
        {
            "received": True,
            "number": request.args.get("n"),
        }
    )


@app.get("/api/events")
def get_events():
    """Web画面へ直近のアクセス履歴を返す。"""

    with events_lock:
        return jsonify(list(events))


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
