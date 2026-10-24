import unittest

from focus_guard.supervisor import Supervisor


class SupervisorTest(unittest.TestCase):
    def make(self, active=True, alive=False):
        self.now, self.started = 0.0, 0
        self.state = {"active": active, "alive": alive}

        def start():
            self.started += 1

        return Supervisor(
            lambda: self.state["active"], lambda: self.state["alive"], start, interval=2.0, clock=lambda: self.now
        )

    def test_restarts_a_dead_peer_during_a_session(self):
        supervisor = self.make()
        self.assertTrue(supervisor.tick())
        self.assertEqual(self.started, 1)

    def test_leaves_a_live_peer_alone(self):
        supervisor = self.make(alive=True)
        self.assertFalse(supervisor.tick())
        self.assertEqual(self.started, 0)

    def test_does_nothing_when_no_session_is_active(self):
        supervisor = self.make(active=False)
        self.assertFalse(supervisor.tick())
        self.assertEqual(self.started, 0)

    def test_checks_are_throttled(self):
        supervisor = self.make()
        self.assertTrue(supervisor.tick())
        self.now = 1.0
        self.assertFalse(supervisor.tick())
        self.assertEqual(self.started, 1)
        self.now = 2.1
        self.assertTrue(supervisor.tick())
        self.assertEqual(self.started, 2)


if __name__ == "__main__":
    unittest.main()
