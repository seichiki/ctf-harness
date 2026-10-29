"""Ordinary operation confirmation; never a flag verdict or security approval."""
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock

from harness.confirm import ConfirmationCancelled, ConfirmationUnavailable, ask


class ConfirmationTests(unittest.TestCase):
    def test_yes_blank_case_and_whitespace(self):
        for answer in ("", " ", "y", "Y", "yes", " YES "):
            with self.subTest(answer=answer):
                self.assertTrue(ask("Proceed", input_fn=lambda _: answer, tty=True))

    def test_no_case_and_whitespace(self):
        for answer in ("n", "N", "no", " NO "):
            with self.subTest(answer=answer):
                self.assertFalse(ask("Proceed", input_fn=lambda _: answer, tty=True))

    def test_invalid_reprompts_and_shows_yn(self):
        replies = iter(["maybe", "run", "Y"])
        prompts = []
        def read(prompt):
            prompts.append(prompt)
            return next(replies)
        with redirect_stdout(io.StringIO()) as output:
            self.assertTrue(ask("Proceed", input_fn=read, tty=True))
        self.assertEqual(prompts, ["Proceed [Y/n]: "] * 3)
        self.assertEqual(output.getvalue().count("Enter y or n."), 2)

    def test_eof_and_interrupt_cancel(self):
        for exception in (EOFError, KeyboardInterrupt):
            with self.subTest(exception=exception):
                with self.assertRaises(ConfirmationCancelled):
                    ask("Proceed", input_fn=Mock(side_effect=exception), tty=True)

    def test_non_tty_fails_closed_but_explicit_yes_bypasses_prompt(self):
        read = Mock()
        with self.assertRaises(ConfirmationUnavailable):
            ask("Proceed", input_fn=read, tty=False)
        self.assertTrue(ask("Proceed", yes=True, input_fn=read, tty=False))
        read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
