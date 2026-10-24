import threading
import time
import unittest
import uuid

from focus_guard import instance


def unique(kind):
    return f"Local\\FocusGuardTest.{kind}.{uuid.uuid4().hex}"


class ClaimTest(unittest.TestCase):
    def test_second_claim_fails_until_released(self):
        name = unique("mutex")
        first = instance.claim(name)
        self.assertIsNotNone(first)
        self.assertIsNone(instance.claim(name))
        instance.release(first)
        again = instance.claim(name)
        self.assertIsNotNone(again)
        instance.release(again)


class ShowSignalTest(unittest.TestCase):
    def test_signal_show_reaches_the_waiting_process(self):
        name, stop, shown = unique("show"), threading.Event(), []
        waiter = threading.Thread(target=instance.wait_show, args=(name, lambda: shown.append(1), stop))
        waiter.start()
        time.sleep(0.2)
        instance.signal_show(name)
        for _ in range(40):
            if shown:
                break
            time.sleep(0.05)
        stop.set()
        waiter.join(2)
        self.assertEqual(shown, [1])
        self.assertFalse(waiter.is_alive())

    def test_signal_with_nobody_waiting_is_harmless(self):
        instance.signal_show(unique("nobody"))


if __name__ == "__main__":
    unittest.main()
