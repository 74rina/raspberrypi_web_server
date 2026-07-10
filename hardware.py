from threading import Lock, Thread
from time import sleep

LED_PIN = 17

_led = None
_alert_lock = Lock()

try:
    from gpiozero import LED

    _led = LED(LED_PIN)
    print(f"LEDをGPIO{LED_PIN}で初期化しました。")
except Exception as exc:
    # GPIOが使えないMacなどでもWebサーバ部分だけテストできるようにする
    print(f"LEDを初期化できませんでした: {exc}")
    print("LEDなしのテストモードで起動します。")


def _blink_pattern() -> None:
    """攻撃検知時のLED点滅パターン。"""

    if _led is None:
        print("[ALERT] LED点滅の代わりにコンソールへ出力しました。")
        return

    # すでにLEDが点滅している場合は、新しい点滅を重ねない
    if not _alert_lock.acquire(blocking=False):
        return

    try:
        for _ in range(5):
            _led.on()
            sleep(0.15)
            _led.off()
            sleep(0.15)
    finally:
        _led.off()
        _alert_lock.release()


def notify_attack() -> None:
    """
    LED点滅を別スレッドで開始する。

    Webサーバのリクエスト処理を止めないため、
    点滅処理はバックグラウンドで実行する。
    """

    thread = Thread(target=_blink_pattern, daemon=True)
    thread.start()
