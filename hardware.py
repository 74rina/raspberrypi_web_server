from pathlib import Path
from threading import Lock, Thread
from time import sleep
from gpiozero import LED

LED_PIN = 17
_led = None
_notification_lock = Lock()


# LEDの初期化
_led = LED(LED_PIN) # LEDの初期化


# LED点滅
def _blink_pattern() -> None:
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


 # LED点滅を開始する関数
 # 点滅はバックグラウンド実行
def notify_reminder() -> None:
    thread = Thread(target=_blink_pattern, daemon=True)
    thread.start()
