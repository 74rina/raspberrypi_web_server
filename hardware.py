from pathlib import Path
from threading import Lock, Thread
from time import sleep
from gpiozero import LED

LED_PIN = 17
_led = None

# スレッドのロック（1点滅 = 1スレッド とする）
_notification_lock = Lock()


# LEDの初期化
_led = LED(LED_PIN)


# LED点滅
def _blink_pattern() -> None:
    if _led is None:
        return

    # すでに点滅している場合は飛ばす
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


 # LED点滅を開始する関数
def notify_reminder() -> None:
    thread = Thread(target=_blink_pattern, daemon=True)
    thread.start()
