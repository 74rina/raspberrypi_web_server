from pathlib import Path
from threading import Lock, Thread
from time import sleep

LED_PIN = 17

_led = None
_notification_lock = Lock()


def _is_raspberry_pi() -> bool:
    cpuinfo_path = Path("/proc/cpuinfo")

    if not cpuinfo_path.exists():
        return False

    try:
        cpuinfo = cpuinfo_path.read_text(encoding="utf-8")
    except OSError:
        return False

    return "Raspberry Pi" in cpuinfo or "BCM" in cpuinfo


try:
    if not _is_raspberry_pi():
        raise RuntimeError("Raspberry Piではない環境です。")

    from gpiozero import LED

    _led = LED(LED_PIN)
    print(f"LEDをGPIO{LED_PIN}で初期化しました。")
except Exception as exc:
    # GPIOが使えないMacなどでもWebサーバ部分だけテストできるようにする
    print(f"LEDを初期化できませんでした: {exc}")
    print("LEDなしのテストモードで起動します。")


def _blink_pattern() -> None:
    """リマインダー通知時のLED点滅パターン。"""

    if _led is None:
        print("[REMINDER] LED点滅の代わりにコンソールへ出力しました。")
        return

    # すでにLEDが点滅している場合は、新しい点滅を重ねない
    if not _notification_lock.acquire(blocking=False):
        return

    try:
        for _ in range(8):
            _led.on()
            sleep(0.25)
            _led.off()
            sleep(0.25)
    finally:
        _led.off()
        _notification_lock.release()


def notify_reminder() -> None:
    """
    LED点滅を別スレッドで開始する。

    Webサーバのリクエスト処理を止めないため、
    点滅処理はバックグラウンドで実行する。
    """

    thread = Thread(target=_blink_pattern, daemon=True)
    thread.start()
